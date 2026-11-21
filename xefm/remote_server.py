"""The local socket a shell XeFM started talks back on (discussion #900).

:mod:`xefm.remote_cli` is the client: ``xefmctl pane selected``, ``xefmctl pane cd .``,
``xefmctl view foo.log``. This is the listening side. It owns four things:

- **The listener.** ``multiprocessing.connection`` over a Unix socket in a
  private (0700) temp directory, or a named pipe on Windows. Every connection
  authenticates with a per-process key (HMAC challenge) before a byte of its
  request is read. Requests and answers are JSON, never pickles.
- **The shim directory.** An ``xefmctl`` script (``xefmctl.cmd`` on Windows)
  that runs the client with XeFM's own interpreter. It goes first on ``PATH``
  in every shell XeFM starts, so ``xefmctl`` works there even from an app
  bundle that put nothing on the system's ``PATH``, and answers without
  loading the file manager.
- **The environment.** :meth:`RemoteServer.env` - ``XEFM_SOCKET``,
  ``XEFM_TOKEN``, ``XEFM_SESSION_KEY``, ``XEFM_SESSION``, ``XEFM_PYTHON`` and
  the ``PATH`` entry.
- **Session keys.** Every shell gets a key of its own
  (``XEFM_SESSION_KEY``), registered with the session it belongs to and what
  that session may do (its *policy*: an AI agent's session is restricted).
  XeFM reads who asks from the key, never from what the request claims, so
  an agent cannot pass for another session by changing ``XEFM_SESSION``. A
  request with no key, or one XeFM never handed out, is refused.

What a request does is the app's business: the server hands each one to a
``handle(request) -> answer`` callable, with ``session`` and ``policy`` set
from the key. It is called on the listener's worker thread; the app moves
the work to its UI thread. An answer that is an iterator of answers is sent
one by one, each but the last marked ``more`` (a search streaming its hits);
the iterator is closed when the client goes away.

The keys tell XeFM that a request comes from a shell it started, and which
one; they do not keep out other programs running as the same user, which
could read a key from a shell's environment anyway.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import weakref
from collections.abc import Callable

from xefm.log_manager import getLogger
# The longest request accepted, which the client checks before sending.
from xefm.remote_commands import MAX_REQUEST

logger = getLogger("Remote")


class RemoteServer:
    """Listen for :mod:`xefm.remote_cli` requests until :meth:`close`."""

    def __init__(self, handle: Callable[[dict], dict], *, python: str) -> None:
        from multiprocessing.connection import Listener
        self._handle = handle
        self._key = secrets.token_bytes(32)
        #: Session key -> (session id, policy).
        self._sessions: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()
        self._dir = tempfile.mkdtemp(prefix="xefm-")  # 0700
        if sys.platform == "win32":
            self.address = rf"\\.\pipe\xefm-{os.getpid()}-{secrets.token_hex(8)}"
            family = "AF_PIPE"
        else:
            self.address = os.path.join(self._dir, "socket")
            family = "AF_UNIX"
        self._listener = Listener(self.address, family=family, authkey=self._key)
        # Gone at exit even when close() never runs (a crash, a test's app):
        # the listener first, so its own finalizer has nothing left to unlink.
        self._stop = threading.Event()
        weakref.finalize(self, _cleanup, self._listener, self._dir, self._stop)
        self.python = python
        self.bin_dir = self._write_shim(python)
        self._thread = threading.Thread(target=self._serve, name="xefm-remote",
                                        daemon=True)
        self._thread.start()

    # --- the shim ------------------------------------------------------------------
    def _write_shim(self, python: str) -> str:
        bin_dir = os.path.join(self._dir, "bin")
        os.mkdir(bin_dir)
        client = os.path.join(os.path.dirname(os.path.abspath(__file__)), "remote_cli.py")
        if sys.platform == "win32":
            path = os.path.join(bin_dir, "xefmctl.cmd")
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(f'@"{python}" -I "{client}" %*\n')
        else:
            import shlex
            path = os.path.join(bin_dir, "xefmctl")
            with open(path, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n"
                        f"exec {shlex.quote(python)} -I {shlex.quote(client)} \"$@\"\n")
            os.chmod(path, 0o755)
        return bin_dir

    # --- the environment -------------------------------------------------------------
    def register(self, session: str, policy: str = "user") -> str:
        """A new key for ``session`` with ``policy`` (``"user"``, or
        ``"agent"`` for an AI agent's session)."""
        key = secrets.token_hex(16)
        with self._lock:
            self._sessions[key] = (session, policy)
        return key

    def lookup(self, key: str) -> tuple[str, str] | None:
        """``(session, policy)`` for a key this server handed out, or None."""
        if not isinstance(key, str) or not key:
            return None
        with self._lock:
            return self._sessions.get(key)

    def env(self, session: str, policy: str = "user") -> dict:
        """What a shell XeFM starts needs to reach it, as session ``session``
        with ``policy``. ``PATH`` is the shim directory alone: :func:`apply_env`
        puts it in front of the shell's own."""
        return {
            "XEFM_SOCKET": self.address,
            "XEFM_TOKEN": self._key.hex(),
            "XEFM_SESSION_KEY": self.register(session, policy),
            "XEFM_SESSION": session,
            "XEFM_PYTHON": self.python,
            "PATH": self.bin_dir,
        }

    def apply_env(self, env: dict, session: str, policy: str = "user") -> dict:
        """Add :meth:`env` to ``env`` in place, prepending the shim directory
        to its ``PATH``; return ``env``."""
        extra = self.env(session, policy)
        shim = extra.pop("PATH")
        env.update(extra)
        current = env.get("PATH", "")
        parts = [p for p in current.split(os.pathsep) if p and p != shim]
        env["PATH"] = os.pathsep.join([shim, *parts])
        return env

    # --- serving -----------------------------------------------------------------------
    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except OSError:
                if self._stop.is_set():
                    return
                logger.warning("The remote socket stopped accepting connections")
                return
            except Exception as exc:  # AuthenticationError: not one of ours
                if self._stop.is_set():
                    return
                logger.warning(f"Refused a connection to the remote socket: {exc}")
                continue
            threading.Thread(target=self._answer, args=(conn,),
                             name="xefm-remote-request", daemon=True).start()

    def _answer(self, conn) -> None:
        try:
            raw = conn.recv_bytes(MAX_REQUEST)
            try:
                req = json.loads(raw.decode("utf-8"))
                if not isinstance(req, dict) or not isinstance(req.get("cmd"), str):
                    raise ValueError("not a request")
            except ValueError as exc:
                answer = {"ok": False, "error": f"bad request: {exc}", "code": 2}
            else:
                who = self.lookup(req.get("key"))
                if who is None:
                    answer = {"ok": False, "code": 3, "error":
                              "this shell's XEFM_SESSION_KEY is not one XeFM handed "
                              "out; run xefmctl from a shell XeFM started"}
                else:
                    req["session"], req["policy"] = who
                    try:
                        answer = self._handle(req)
                    except Exception as exc:
                        logger.error(f"Remote request {req.get('cmd')!r} failed: {exc}")
                        answer = {"ok": False, "error": str(exc)}
            if isinstance(answer, dict):
                conn.send_bytes(json.dumps(answer).encode("utf-8"))
            else:
                self._stream(conn, answer)
        except (EOFError, OSError) as exc:
            logger.info(f"A remote request was dropped: {exc}")
        finally:
            conn.close()

    def _stream(self, conn, answers) -> None:
        """Send each answer of an iterator, all but the last marked ``more``;
        close the iterator when the client goes away."""
        try:
            for answer in answers:
                if not answer.get("ok", True):
                    conn.send_bytes(json.dumps(answer).encode("utf-8"))
                    return
                conn.send_bytes(json.dumps(dict(answer, ok=True, more=True)).encode("utf-8"))
            conn.send_bytes(json.dumps({"ok": True, "more": False}).encode("utf-8"))
        except (EOFError, OSError):
            raise
        except Exception as exc:
            logger.error(f"A streamed remote answer failed: {exc}")
            conn.send_bytes(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))
        finally:
            close = getattr(answers, "close", None)
            if close is not None:
                close()

    def close(self) -> None:
        """Stop listening and remove the socket and the shim."""
        if self._stop.is_set():
            return
        _cleanup(self._listener, self._dir, self._stop)


def _cleanup(listener, directory: str, stop: threading.Event) -> None:
    stop.set()
    try:
        listener.close()
    except OSError:
        pass
    shutil.rmtree(directory, ignore_errors=True)


def start(handle: Callable[[dict], dict], *, python: str) -> RemoteServer | None:
    """A running :class:`RemoteServer`, or None (logged) where one cannot be
    started - the commands then report that they are not in an XeFM shell."""
    try:
        return RemoteServer(handle, python=python)
    except Exception as exc:
        logger.warning(f"xefmctl is unavailable in XeFM's shells: {exc}")
        return None
