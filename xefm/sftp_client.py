"""An SFTP (version 3) client over a pair of byte streams.

XeFM's SSH support runs one ``ssh <host> -s sftp`` per host and speaks the
SFTP protocol to the server on the other end of its stdin/stdout (see
``doc/dev/SSH_SYSTEM.md``). This module is the protocol half of that: it knows
nothing about ssh, processes or XeFM paths, only how to frame requests, match
replies to them and decode what comes back — so it can be driven, and tested,
over any pipe, e.g. a local ``sftp-server`` process.

The protocol is draft-ietf-secsh-filexfer-02 (SFTP v3), the version OpenSSH
implements. Every request carries an id and every reply echoes it, so many
requests can be in flight at once: a reader thread hands each reply to the
caller waiting on that id. That is what lets several XeFM threads share one
session, and what lets a transfer keep a window of reads or writes outstanding
instead of paying a round trip per chunk.
"""

from __future__ import annotations

import io
import struct
import threading
from collections import deque
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable, Dict, List, Optional, Tuple

# --- packet types -------------------------------------------------------------

FXP_INIT = 1
FXP_VERSION = 2
FXP_OPEN = 3
FXP_CLOSE = 4
FXP_READ = 5
FXP_WRITE = 6
FXP_LSTAT = 7
FXP_FSTAT = 8
FXP_OPENDIR = 11
FXP_READDIR = 12
FXP_REMOVE = 13
FXP_MKDIR = 14
FXP_RMDIR = 15
FXP_REALPATH = 16
FXP_STAT = 17
FXP_RENAME = 18
FXP_EXTENDED = 200

FXP_STATUS = 101
FXP_HANDLE = 102
FXP_DATA = 103
FXP_NAME = 104
FXP_ATTRS = 105
FXP_EXTENDED_REPLY = 201

# --- status codes -------------------------------------------------------------

FX_OK = 0
FX_EOF = 1
FX_NO_SUCH_FILE = 2
FX_PERMISSION_DENIED = 3
FX_FAILURE = 4
FX_BAD_MESSAGE = 5
FX_NO_CONNECTION = 6
FX_CONNECTION_LOST = 7
FX_OP_UNSUPPORTED = 8

# --- open flags and attribute flags -------------------------------------------

FXF_READ = 0x01
FXF_WRITE = 0x02
FXF_APPEND = 0x04
FXF_CREAT = 0x08
FXF_TRUNC = 0x10
FXF_EXCL = 0x20

ATTR_SIZE = 0x01
ATTR_UIDGID = 0x02
ATTR_PERMISSIONS = 0x04
ATTR_ACMODTIME = 0x08
ATTR_EXTENDED = 0x80000000

#: OpenSSH's rename that replaces an existing target, as POSIX rename() does.
#: Plain SSH_FXP_RENAME refuses one. ``sftp``'s own ``rename`` command uses it
#: whenever the server offers it, so XeFM does too.
POSIX_RENAME = "posix-rename@openssh.com"

#: Bytes asked for per READ / sent per WRITE. 32 KiB is what every server
#: accepts; OpenSSH's own client uses the same default.
CHUNK = 32 * 1024

#: Reads or writes kept in flight during a transfer — 1 MiB at a time, enough
#: to keep a long link busy without a round trip between chunks.
WINDOW = 32

#: READDIRs kept in flight on one directory handle. A small directory then
#: takes one round trip — its entries and the EOF arrive together — instead of
#: one for the entries and one more to learn there are no more. OpenSSH's
#: sftp-server answers requests in order, and so do the others in use; paramiko
#: reads directories ahead the same way.
READDIR_AHEAD = 4

#: The protocol version this client speaks.
VERSION = 3


class SFTPError(Exception):
    """The server answered a request with a failure status."""

    def __init__(self, code: int, message: str):
        super().__init__(message or f"SFTP status {code}")
        self.code = code
        self.message = message


class SFTPClosed(Exception):
    """The session ended — the stream closed, or the client was closed — with
    this request still waiting for its reply."""


class SFTPTimeout(Exception):
    """A reply did not arrive in time."""


# --- wire encoding ------------------------------------------------------------

def _u32(n: int) -> bytes:
    return struct.pack(">I", n)


def _u64(n: int) -> bytes:
    return struct.pack(">Q", n)


def _string(data) -> bytes:
    if isinstance(data, str):
        data = encode_name(data)
    return _u32(len(data)) + data


def encode_name(name: str) -> bytes:
    """A path as the bytes the server sees. Names are bytes on the wire;
    ``surrogateescape`` carries a name that is not valid UTF-8 back out exactly
    as it came in, so such a file can still be opened, renamed or deleted."""
    return name.encode("utf-8", "surrogateescape")


def decode_name(data: bytes) -> str:
    return data.decode("utf-8", "surrogateescape")


def _attrs_bytes(attrs: Optional[Dict] = None) -> bytes:
    """Encode the attributes a request may set; only permissions are used."""
    if attrs and attrs.get("permissions") is not None:
        return _u32(ATTR_PERMISSIONS) + _u32(attrs["permissions"])
    return _u32(0)


class _Reader:
    """Cursor over one packet's payload."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def u32(self) -> int:
        value = struct.unpack_from(">I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def u64(self) -> int:
        value = struct.unpack_from(">Q", self.data, self.pos)[0]
        self.pos += 8
        return value

    def bytes(self) -> bytes:
        n = self.u32()
        value = self.data[self.pos:self.pos + n]
        if len(value) != n:
            raise SFTPError(FX_BAD_MESSAGE, "Truncated SFTP packet")
        self.pos += n
        return value

    def string(self) -> str:
        return decode_name(self.bytes())

    def attrs(self) -> Dict:
        """Decode an ATTRS block into a dict holding the fields it carries:
        ``size``, ``uid``, ``gid``, ``permissions`` (the full ``st_mode``,
        type bits included), ``atime``, ``mtime``."""
        flags = self.u32()
        out: Dict = {}
        if flags & ATTR_SIZE:
            out["size"] = self.u64()
        if flags & ATTR_UIDGID:
            out["uid"] = self.u32()
            out["gid"] = self.u32()
        if flags & ATTR_PERMISSIONS:
            out["permissions"] = self.u32()
        if flags & ATTR_ACMODTIME:
            out["atime"] = self.u32()
            out["mtime"] = self.u32()
        if flags & ATTR_EXTENDED:
            for _ in range(self.u32()):
                self.bytes()
                self.bytes()
        return out


# --- the client ---------------------------------------------------------------

class SFTPClient:
    """One SFTP session over ``rfile`` (the server's output) and ``wfile`` (its
    input). Thread-safe: any number of threads may issue requests at once.

    :meth:`start` performs the version handshake; after that every method sends
    a request and blocks until its reply. ``timeout`` (seconds, None for no
    limit) bounds how long one reply may take — a whole transfer may take much
    longer, but each chunk of it may not.
    """

    def __init__(self, rfile, wfile, *, timeout: Optional[float] = 60.0,
                 on_close: Optional[Callable[[], None]] = None):
        self._rfile = rfile
        self._wfile = wfile
        self.timeout = timeout
        self._on_close = on_close
        self._write_lock = threading.Lock()
        self._pending: Dict[int, Future] = {}
        self._pending_lock = threading.Lock()
        self._next_id = 1
        self._version: Future = Future()
        self._closed = threading.Event()
        self._close_reason = "SFTP session closed"
        self._reader: Optional[threading.Thread] = None
        #: Extensions the server announced in its VERSION reply.
        self.extensions: Dict[str, bytes] = {}

    # --- lifecycle ------------------------------------------------------------

    def start(self, timeout: Optional[float] = None) -> None:
        """Send INIT and wait for the server's VERSION. Raises
        :class:`SFTPClosed` if the stream ends first (the ssh login failed),
        :class:`SFTPTimeout` if nothing arrives in ``timeout`` seconds."""
        self._reader = threading.Thread(target=self._read_loop,
                                        name="xefm-sftp-reader", daemon=True)
        self._reader.start()
        self._send(FXP_INIT, _u32(VERSION))
        try:
            self._version.result(timeout)
        except FutureTimeout:
            raise SFTPTimeout("No SFTP version reply from the server")

    @property
    def alive(self) -> bool:
        return not self._closed.is_set()

    def close(self) -> None:
        """End the session: close the server's input (which ends a well-behaved
        server) and fail whatever is still waiting."""
        self._shutdown("SFTP session closed")
        try:
            self._wfile.close()
        except (OSError, ValueError):
            pass

    def _shutdown(self, reason: str) -> None:
        # Tested and set under the lock submit() checks it under: the reader
        # hitting end-of-stream and a writer's broken pipe (or close()) reach
        # here together when ssh dies, and only one may run the rest.
        with self._pending_lock:
            if self._closed.is_set():
                return
            self._close_reason = reason
            self._closed.set()
            pending = list(self._pending.values())
            self._pending.clear()
        if not self._version.done():
            self._version.set_exception(SFTPClosed(reason))
        for future in pending:
            if not future.done():
                future.set_exception(SFTPClosed(reason))
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:  # noqa: BLE001 — a notification must not break shutdown
                pass

    # --- framing --------------------------------------------------------------

    def _read_exact(self, n: int) -> bytes:
        chunks = []
        while n:
            chunk = self._rfile.read(n)
            if not chunk:
                raise EOFError
            chunks.append(chunk)
            n -= len(chunk)
        return b"".join(chunks)

    def _read_loop(self) -> None:
        reason = "SFTP server closed the connection"
        try:
            while True:
                length = struct.unpack(">I", self._read_exact(4))[0]
                packet = self._read_exact(length)
                ptype, body = packet[0], packet[1:]
                if ptype == FXP_VERSION:
                    self._on_version(body)
                    continue
                request_id = struct.unpack_from(">I", body)[0]
                with self._pending_lock:
                    future = self._pending.pop(request_id, None)
                if future is not None and not future.done():
                    future.set_result((ptype, body[4:]))
        except EOFError:
            pass
        except Exception as e:  # noqa: BLE001 — any read failure ends the session
            reason = f"SFTP connection failed: {e}"
        self._shutdown(reason)

    def _on_version(self, body: bytes) -> None:
        r = _Reader(body)
        r.u32()  # the server's version; v3 servers answer 3
        while r.pos < len(r.data):
            name = r.string()
            self.extensions[name] = r.bytes()
        if not self._version.done():
            self._version.set_result(True)

    def _send(self, ptype: int, payload: bytes) -> None:
        packet = bytes([ptype]) + payload
        try:
            with self._write_lock:
                self._wfile.write(_u32(len(packet)) + packet)
                self._wfile.flush()
        except (OSError, ValueError) as e:
            self._shutdown(f"SFTP connection failed: {e}")
            raise SFTPClosed(self._close_reason)

    def submit(self, ptype: int, payload: bytes) -> Future:
        """Send one request and return the Future its ``(type, body)`` reply
        will land in, without waiting for it."""
        future: Future = Future()
        with self._pending_lock:
            if self._closed.is_set():
                raise SFTPClosed(self._close_reason)
            request_id = self._next_id
            self._next_id = (self._next_id + 1) & 0xFFFFFFFF or 1
            self._pending[request_id] = future
        try:
            self._send(ptype, _u32(request_id) + payload)
        except SFTPClosed:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        return future

    def wait(self, future: Future) -> Tuple[int, bytes]:
        try:
            return future.result(self.timeout)
        except FutureTimeout:
            raise SFTPTimeout(f"No reply from the SFTP server in {self.timeout:g}s")

    def _request(self, ptype: int, payload: bytes) -> Tuple[int, bytes]:
        return self.wait(self.submit(ptype, payload))

    # --- reply decoding -------------------------------------------------------

    @staticmethod
    def _status(body: bytes) -> Tuple[int, str]:
        r = _Reader(body)
        code = r.u32()
        message = r.string() if r.pos < len(r.data) else ""
        return code, message

    def _check(self, reply: Tuple[int, bytes], want: int) -> bytes:
        """The body of a reply of type ``want``; a STATUS reply in its place
        is the server saying no, raised as :class:`SFTPError`."""
        ptype, body = reply
        if ptype == FXP_STATUS:
            code, message = self._status(body)
            if want == FXP_STATUS and code == FX_OK:
                return body
            raise SFTPError(code, message)
        if ptype == want:
            return body
        raise SFTPError(FX_BAD_MESSAGE, f"Unexpected SFTP reply type {ptype}")

    def _ok(self, reply: Tuple[int, bytes]) -> None:
        self._check(reply, FXP_STATUS)

    # --- operations -----------------------------------------------------------

    def realpath(self, path: str) -> str:
        body = self._check(self._request(FXP_REALPATH, _string(path)), FXP_NAME)
        r = _Reader(body)
        r.u32()  # count, always 1
        return r.string()

    def stat(self, path: str) -> Dict:
        """Attributes of ``path``, following a symlink."""
        return _Reader(self._check(self._request(FXP_STAT, _string(path)),
                                   FXP_ATTRS)).attrs()

    def lstat(self, path: str) -> Dict:
        """Attributes of ``path`` itself — a symlink is described as a link."""
        return _Reader(self._check(self._request(FXP_LSTAT, _string(path)),
                                   FXP_ATTRS)).attrs()

    def stat_many(self, paths: List[str]) -> List:
        """``stat`` every path, all requests in flight at once; each result is
        the attribute dict or the :class:`SFTPError` that path got."""
        futures = [self.submit(FXP_STAT, _string(p)) for p in paths]
        out: List = []
        for future in futures:
            try:
                out.append(_Reader(self._check(self.wait(future), FXP_ATTRS)).attrs())
            except SFTPError as e:
                out.append(e)
        return out

    def listdir(self, path: str) -> List[Tuple[str, Dict]]:
        """``(name, lstat attributes)`` for every entry of directory ``path``,
        without ``.`` and ``..``."""
        handle = self._check(self._request(FXP_OPENDIR, _string(path)), FXP_HANDLE)
        handle = _Reader(handle).bytes()
        entries: List[Tuple[str, Dict]] = []
        inflight: deque = deque()
        try:
            while True:
                while len(inflight) < READDIR_AHEAD:
                    inflight.append(self.submit(FXP_READDIR, _string(handle)))
                reply = self.wait(inflight.popleft())
                if reply[0] == FXP_STATUS and self._status(reply[1])[0] == FX_EOF:
                    break
                r = _Reader(self._check(reply, FXP_NAME))
                for _ in range(r.u32()):
                    name = r.string()
                    r.bytes()  # longname: the ls -l line, not needed
                    attrs = r.attrs()
                    if name not in (".", ".."):
                        entries.append((name, attrs))
        finally:
            # The READDIRs still in flight are answered with EOF and dropped.
            self._close_handle(handle, wait=False)
        return entries

    def mkdir(self, path: str, permissions: Optional[int] = None) -> None:
        self._ok(self._request(FXP_MKDIR, _string(path) +
                               _attrs_bytes({"permissions": permissions})))

    def rmdir(self, path: str) -> None:
        self._ok(self._request(FXP_RMDIR, _string(path)))

    def remove(self, path: str) -> None:
        self._ok(self._request(FXP_REMOVE, _string(path)))

    def rename(self, old: str, new: str) -> None:
        """Rename ``old`` to ``new``, replacing ``new`` if the server can
        (see :data:`POSIX_RENAME`)."""
        if POSIX_RENAME in self.extensions:
            self._ok(self._request(FXP_EXTENDED, _string(POSIX_RENAME) +
                                   _string(old) + _string(new)))
        else:
            self._ok(self._request(FXP_RENAME, _string(old) + _string(new)))

    # --- file transfers -------------------------------------------------------

    def _open(self, path: str, flags: int) -> bytes:
        body = self._check(self._request(FXP_OPEN, _string(path) + _u32(flags) +
                                         _attrs_bytes()), FXP_HANDLE)
        return _Reader(body).bytes()

    def _close_handle(self, handle: bytes, *, wait: bool = True) -> None:
        """Close ``handle``, ignoring how the close went: the operation's own
        outcome is what the caller needs. ``wait=False`` sends the CLOSE and
        moves on — for a handle only read from, or one being abandoned, where
        waiting would cost a round trip per file or directory and nothing the
        reply says would change anything. (A completed write checks its close
        itself; see :meth:`write_file`.)"""
        try:
            future = self.submit(FXP_CLOSE, _string(handle))
            if wait:
                self._ok(self.wait(future))
        except (SFTPError, SFTPClosed, SFTPTimeout):
            pass

    def read_file(self, path: str,
                  progress: Optional[Callable[[int, int], None]] = None,
                  sink=None):
        """The whole of file ``path`` — or, given a writable binary ``sink``,
        how many bytes were written into it, the file passing through
        :data:`WINDOW` chunks at a time instead of being held whole.

        Reads are pipelined: up to :data:`WINDOW` requests of :data:`CHUNK`
        bytes are in flight, consumed in order. ``progress(done, total)`` is
        called as each chunk lands — with 0 first and the full size last — and
        is the cancel point: whatever it raises stops the transfer and
        propagates unchanged."""
        handle = self._open(path, FXF_READ)
        try:
            try:
                total = _Reader(self._check(
                    self._request(FXP_FSTAT, _string(handle)), FXP_ATTRS)).attrs().get("size", 0)
            except SFTPError:
                total = 0
            if progress is not None:
                progress(0, total)
            out = bytearray()
            done = 0
            inflight: deque = deque()
            offset = 0          # next offset to ask for
            eof = False
            while not eof:
                # A file may grow while it is read, so asking stops at EOF, not
                # at the size fstat reported; the size only bounds the window.
                want = max(1, -(-(total - offset) // CHUNK) + 1)
                while len(inflight) < min(WINDOW, want):
                    inflight.append((offset, self.submit(
                        FXP_READ, _string(handle) + _u64(offset) + _u32(CHUNK))))
                    offset += CHUNK
                start, future = inflight.popleft()
                ptype, body = self.wait(future)
                if ptype == FXP_STATUS and self._status(body)[0] == FX_EOF:
                    eof = True
                    break
                data = _Reader(self._check((ptype, body), FXP_DATA)).bytes()
                if sink is None:
                    out += data
                else:
                    sink.write(data)
                done += len(data)
                if len(data) < CHUNK:
                    # A short read: the server may return less than asked for at
                    # any offset. Everything already in flight assumed a full
                    # chunk here, so drop it and carry on from where this ended.
                    inflight.clear()
                    offset = start + len(data)
                if progress is not None:
                    progress(done, max(total, done))
            if progress is not None:
                progress(done, done)
            return bytes(out) if sink is None else done
        finally:
            self._close_handle(handle, wait=False)

    def write_file(self, path: str, data,
                   progress: Optional[Callable[[int, int], None]] = None,
                   size: Optional[int] = None) -> None:
        """Create or truncate ``path`` and write ``data`` to it, pipelined the
        way :meth:`read_file` is. ``data`` is ``bytes``, or a readable binary
        stream read :data:`CHUNK` at a time until it ends — ``size`` then
        scales the progress. ``progress`` is called as each chunk is
        acknowledged, and is the cancel point in the same way."""
        if isinstance(data, (bytes, bytearray, memoryview)):
            stream = io.BytesIO(data)
            size = len(data)
        else:
            stream = data
        handle = self._open(path, FXF_WRITE | FXF_CREAT | FXF_TRUNC)
        try:
            total = size or 0
            if progress is not None:
                progress(0, total)
            inflight: deque = deque()
            offset = 0
            done = 0
            ended = False
            while not ended or inflight:
                while not ended and len(inflight) < WINDOW:
                    piece = stream.read(CHUNK)
                    if not piece:
                        ended = True
                        break
                    inflight.append((len(piece), self.submit(
                        FXP_WRITE, _string(handle) + _u64(offset) + _string(bytes(piece)))))
                    offset += len(piece)
                if not inflight:
                    break
                length, future = inflight.popleft()
                self._ok(self.wait(future))
                done += length
                if progress is not None:
                    progress(done, max(total, done))
        except BaseException:
            self._close_handle(handle, wait=False)
            raise
        # The close is where a server that buffers can still report the write
        # failing, so a write that got this far waits for it and checks it.
        self._ok(self._request(FXP_CLOSE, _string(handle)))
