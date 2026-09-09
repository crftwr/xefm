#!/usr/bin/env python3
"""libarchive-backed archive formats — 7z, RAR, ISO, CAB, cpio and RPM.

XeFM reads zip and tar through the Python standard library. Everything else
comes from `libarchive <https://libarchive.org/>`_, reached through the pure
-ctypes ``libarchive-c`` binding, and registered into
:data:`xefm.archive.ARCHIVE_HANDLERS` as ordinary table entries. Nothing here is
required: with no usable library the table simply has fewer formats in it and
zip and tar carry on unchanged.

**Three supply paths, one loader.** The library that answers is chosen in this
order:

1. the ``LIBARCHIVE`` environment variable, which a terminal user can set to a
   library they downloaded or built;
2. a bundled copy — :func:`bundled_library_path` looks in ``xefm/_bin/``, which
   the desktop builds fill and a source checkout leaves empty. Finding one is
   how ``LIBARCHIVE`` comes to be set when the user did not set it, because
   ``libarchive-c`` reads that variable at import and offers no other way in;
3. ``ctypes.util.find_library("archive")`` — the system copy, which is what
   macOS and most Linux distributions already have, and what Windows does not.

The user's own ``LIBARCHIVE`` deliberately outranks the bundled copy: someone
who names a library is answering exactly this question.

Because two of those three are built by somebody else, **what a format needs is
probed, never assumed from a version number**. ``archive_version_details()``
names only the codecs actually compiled in, and a format is registered only when
the loaded library reports what it needs. That is also how the silent
external-program fallback is avoided: libarchive answers a missing stream codec
by spawning ``gzip -d`` or ``xz -d``, one process per entry, and on Windows those
binaries are simply absent — so a format whose codec is missing must never be
offered in the first place.

macOS ships libarchive 3.7.4 with zlib, liblzma and bz2lib, which is enough to
read ``.7z``. AES-encrypted 7z entries are another matter: no libarchive built
to date decrypts them, whatever crypto it was compiled against — through 3.8.9,
zip is the only format libarchive decrypts, and the 7z reader rejects an
encrypted entry unconditionally. :func:`can_decrypt_7z` settles it by actually
decrypting a known archive rather than reasoning from a version or a build flag,
so the UI can say "not supported" instead of rejecting every password the user
types, and so the day a release does add it needs no change here.
"""

import base64
import ctypes
import logging
import errno
import os
import stat
import sys
import tempfile
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path as PathlibPath
from typing import Callable, Iterator, List, Optional, Set, Tuple

from xefm.log_manager import getLogger
from xefm.path import Path
from xefm.archive import (
    MEMBER_CHUNK, ArchiveCorruptedError, ArchiveEncryptionUnsupported, ArchiveEntry,
    ArchiveExtractionError, ArchiveFormat, ArchiveHandler, ArchiveNavigationError,
    ArchivePasswordRequired, ArchivePermissionError, ArchiveDiskSpaceError, ArchiveError,
    get_archive_password, is_safe_member_path, register_archive_format,
)

logger = getLogger('Archive')

# ``libarchive-c`` logs through a plain stdlib logger of its own, and its
# error-check callback reports every non-fatal ARCHIVE_WARN through it — while an
# archive is being read, which is to say while the TUI is on screen. With no
# handler anywhere on that logger's chain, logging's last-resort handler writes
# warnings straight to stderr, on top of the UI. A NullHandler stops that while
# leaving the records free to propagate, so they still reach XeFM's log pane once
# logging is configured.
logging.getLogger('libarchive').addHandler(logging.NullHandler())


# --- loading and probing ------------------------------------------------------


@dataclass(frozen=True)
class LibarchiveInfo:
    """What the loaded libarchive is and what it can do — the line a bug report
    needs to carry, since three different libraries can end up here."""

    #: The ``libarchive-c`` module, or None when nothing usable loaded.
    binding: Optional[object]
    #: Filesystem path of the shared library that loaded, if known.
    library_path: str = ''
    #: ``archive_version_details()`` — the version plus every codec compiled in.
    details: str = ''
    #: Codec names parsed out of ``details`` (``zlib``, ``liblzma``, …).
    codecs: Tuple[str, ...] = ()
    #: Why nothing loaded, when ``binding`` is None.
    error: str = ''

    @property
    def available(self) -> bool:
        return self.binding is not None


_info_lock = threading.RLock()
_info: Optional[LibarchiveInfo] = None


#: Where the desktop builds put the shared library they bundle — inside XeFM's
#: own package, the one directory this module can find without knowing anything
#: about the bundle around it. Empty in a source checkout, which is why the
#: system and ``LIBARCHIVE`` paths still exist.
_BUNDLED_DIR = PathlibPath(__file__).resolve().parent / '_bin'

#: Names to try in there, in order. Windows is the platform that needs this at
#: all — macOS and most Linux distributions have a system library — but naming
#: the others costs nothing and keeps the answer to "can this bundle one?" the
#: same everywhere.
_BUNDLED_NAMES = ('archive.dll', 'libarchive.dylib', 'libarchive.so')


def bundled_library_path() -> str:
    """The bundled shared library's path, or '' when this is not a desktop build."""
    for name in _BUNDLED_NAMES:
        candidate = _BUNDLED_DIR / name
        if candidate.is_file():
            return str(candidate)
    return ''


#: The charset a format's headers are read and written in, for the formats that
#: get told — see :data:`_CHARSET_BY_LABEL`, which is where the list lives.
_HDRCHARSET = 'UTF-8'


def _use_utf8_ctype() -> None:
    """Put this process's C locale on UTF-8, on Windows only.

    libarchive decides how to convert a filename between its wide and narrow
    forms by calling ``setlocale(LC_CTYPE, NULL)`` in the C runtime and reading a
    code page out of the answer. On a Windows box whose locale is, say,
    ``English_United States.1252``, that is code page 1252, and a name it cannot
    spell — any CJK one — makes libarchive's narrow accessor return NULL. The
    ISO 9660 writer reads that NULL as the virtual root and drops the file
    silently; nothing surfaces but a missing entry.

    macOS and Linux never hit this because their locale is already UTF-8, which
    is what this makes Windows agree with. Python's own encodings are unaffected
    — it derives those from ``GetACP()``, not from the C locale — so the only
    code this reaches is exactly the code that has the problem."""
    if os.name != 'nt':
        return
    import locale as _locale
    try:
        _locale.setlocale(_locale.LC_CTYPE, '.UTF8')
    except Exception as exc:  # noqa: BLE001 — a locale XeFM can live without
        logger.warning(f"Could not select a UTF-8 C locale ({exc}); "
                       f"non-ASCII names may not survive being written to .iso")


def _use_bundled_library() -> None:
    """Point ``libarchive-c`` at the bundled library, if there is one and the user
    has not named their own.

    ``libarchive-c`` reads ``LIBARCHIVE`` once, at import, and loads whatever it
    names; there is no API for choosing a library afterwards. So the choice has
    to be made here, before :func:`_probe` imports it — which is also why this
    lives in the module that does that import rather than in XeFM's startup,
    where it would be one import-order mistake away from having no effect."""
    if os.environ.get('LIBARCHIVE'):
        return  # An explicit choice by the user outranks the bundled copy.
    path = bundled_library_path()
    if path:
        os.environ['LIBARCHIVE'] = path


#: Sonames to try when ``ctypes.util.find_library`` comes up empty, per
#: ``sys.platform``. Only the versioned name is worth much: the unversioned
#: symlink beside it belongs to the ``-dev`` package on most distributions, while
#: the soname is what the runtime package installs and what every binary linked
#: against libarchive already asks for.
_SONAMES = {
    'linux': ('libarchive.so.13', 'libarchive.so'),
    'darwin': ('libarchive.13.dylib', 'libarchive.dylib'),
    'win32': ('archive.dll', 'libarchive.dll'),
}


def _use_known_soname() -> None:
    """Name libarchive by soname when ``find_library`` cannot.

    ``libarchive-c`` asks ``ctypes.util.find_library('archive')``, which is not a
    question every platform can answer. **On musl — Alpine — it never can**:
    musl's ``ldconfig`` has no ``-p`` for it to read, and its remaining strategies
    need a compiler, so it returns None with libarchive installed at
    ``/usr/lib/libarchive.so.13`` and returns None still with the ``-dev``
    symlink beside it. ``dlopen`` finds that library immediately when handed its
    soname; only ``find_library`` cannot say the name.

    So this runs after ``find_library`` has already failed, and each candidate is
    loaded before being chosen — naming one that does not exist would replace a
    clear "no library" with an obscure import error from the binding. Loading it
    twice costs nothing: ``dlopen`` is reference-counted and hands back the same
    handle when :func:`_probe` imports the binding.
    """
    if os.environ.get('LIBARCHIVE'):
        return
    from ctypes.util import find_library
    if find_library('archive'):
        return  # find_library can answer here; leave the binding to its own way.
    for soname in _SONAMES.get(sys.platform, ()):
        try:
            ctypes.CDLL(soname)
        except OSError:
            continue
        logger.debug(f"find_library could not name libarchive; using {soname}")
        os.environ['LIBARCHIVE'] = soname
        return


def _probe() -> LibarchiveInfo:
    """Import ``libarchive-c`` and ask the library that loaded what it supports.

    Importing the binding is what loads the shared library, so an absent or
    unloadable library surfaces here as an import failure rather than later as a
    read failure."""
    from ctypes.util import find_library

    _use_bundled_library()
    _use_known_soname()
    _use_utf8_ctype()
    if not os.environ.get('LIBARCHIVE') and not find_library('archive'):
        # Say this plainly rather than letting the binding say it badly. With no
        # library named, ``libarchive-c`` calls LoadLibrary(None), which on POSIX
        # succeeds — it opens the main program — and the failure then surfaces as
        # "AttributeError: Symbol not found: archive_version_number", which is
        # true and tells the reader nothing.
        return LibarchiveInfo(
            binding=None,
            error="no libarchive found (set LIBARCHIVE to one, or install "
                  "your platform's libarchive package)")
    try:
        import libarchive
        import libarchive.ffi as ffi
    except Exception as exc:  # noqa: BLE001 — any import failure means "absent"
        return LibarchiveInfo(binding=None, error=f"{type(exc).__name__}: {exc}")

    try:
        details_fn = ffi.libarchive.archive_version_details
        details_fn.restype = ctypes.c_char_p
        details = (details_fn() or b'').decode('utf-8', 'replace')
    except Exception as exc:  # noqa: BLE001 — a library without the symbol
        return LibarchiveInfo(binding=None,
                              error=f"archive_version_details() unavailable: {exc}")

    # "libarchive 3.7.4 zlib/1.2.12 liblzma/5.4.3 bz2lib/1.0.8" — the tokens
    # after the version are the codecs, each "name/version".
    codecs = tuple(token.split('/')[0] for token in details.split()[2:])
    return LibarchiveInfo(
        binding=libarchive,
        library_path=getattr(ffi, 'libarchive_path', '') or '',
        details=details,
        codecs=codecs,
    )


def libarchive_info() -> LibarchiveInfo:
    """The loaded library's identity and capabilities, probed once per process."""
    global _info
    with _info_lock:
        if _info is None:
            _info = _probe()
        return _info


def _binding():
    """The ``libarchive`` module, or raise if it never loaded. Handlers only ever
    reach this after their format was registered, which required it."""
    info = libarchive_info()
    if info.binding is None:
        raise ArchiveError(
            f"libarchive is not available: {info.error}",
            "This archive format needs libarchive, which is not installed")
    return info.binding


def _has_symbol(name: str) -> bool:
    """Whether the loaded library exports ``name`` — how a format reader's
    presence is established, since readers are switched in at build time."""
    info = libarchive_info()
    if info.binding is None:
        return False
    try:
        import libarchive.ffi as ffi
        return hasattr(ffi.libarchive, name)
    except Exception:  # noqa: BLE001
        return False


def _entry_is_encrypted(raw) -> bool:
    """Whether one libarchive entry's data is encrypted. ``libarchive-c`` does not
    wrap ``archive_entry_is_encrypted``, so it is called on the raw struct
    pointer the binding already holds."""
    fn = _encryption_probe()
    if fn is None:
        return False
    try:
        return bool(fn(raw._entry_p))
    except Exception:  # noqa: BLE001 — never let a probe break a listing
        return False


_encryption_fn = None
_encryption_fn_resolved = False


def _encryption_probe():
    """``archive_entry_is_encrypted``, resolved once, or None if this library
    predates it (added in libarchive 3.2)."""
    global _encryption_fn, _encryption_fn_resolved
    with _info_lock:
        if not _encryption_fn_resolved:
            _encryption_fn_resolved = True
            if _has_symbol('archive_entry_is_encrypted'):
                import libarchive.ffi as ffi
                fn = ffi.libarchive.archive_entry_is_encrypted
                fn.argtypes = [ctypes.c_void_p]
                fn.restype = ctypes.c_int
                _encryption_fn = fn
        return _encryption_fn


# A 7z holding one AES-256 encrypted file, "secret.txt", whose contents are
# _PROBE_PLAINTEXT under _PROBE_PASSWORD. Decrypting it is the only honest test
# of whether the loaded library can decrypt 7z at all. Nothing else answers the
# question: ``archive_version_details()`` reports the crypto backend (macOS's
# build has none, XeFM's Windows build reports cng/2.0) but that says nothing
# about 7z, which as of 3.8.9 refuses encrypted entries no matter what the
# library was built with. Without this probe an encrypted 7z would reject every
# password the user typed with no way to say why.
_PROBE_7Z = base64.b64decode(
    'N3q8ryccAARfXI/4gwAAAAAAAAAUAAAAAAAAAA6xR+SEKLWDIBuLctmOWO0Ey2IM4ABu'
    'AGtdAACBMweuD87zck5PYtmjlC7665Rvo9JyRHNFzqR/1QdFG0fWqjQSpDRUacop7qQG'
    'u8He6e+odaxFjYT8fZ8DdHgPvgXSf5V+mKUceOvZE6FVT+t7C9jXdEC+C7ustjoh8i/k'
    'afvfPF7UAAAAABcGEAEJcwAHCwEAASEhARgMbwAA'
)
_PROBE_PASSWORD = b'sesame'
_PROBE_PLAINTEXT = b'top secret\n'

_decrypt_7z: Optional[bool] = None


def can_decrypt_7z() -> bool:
    """Whether the loaded library can decrypt AES-encrypted 7z entries, decided
    by actually decrypting :data:`_PROBE_7Z` once per process."""
    global _decrypt_7z
    with _info_lock:
        if _decrypt_7z is None:
            _decrypt_7z = False
            info = libarchive_info()
            if info.binding is not None:
                try:
                    with info.binding.memory_reader(
                            _PROBE_7Z, passphrase=_PROBE_PASSWORD) as archive:
                        for raw in archive:
                            _decrypt_7z = (b''.join(raw.get_blocks())
                                           == _PROBE_PLAINTEXT)
                            break
                except Exception:  # noqa: BLE001 — any failure means "cannot"
                    _decrypt_7z = False
        return _decrypt_7z


# --- the handler --------------------------------------------------------------


@contextmanager
def _open_reader(path: str, passphrase: Optional[bytes] = None, charset: str = ''):
    """``libarchive.file_reader``, plus an optional ``hdrcharset``.

    The option has to be set between ``archive_read_new`` and
    ``archive_read_open``, and ``libarchive-c``'s own ``file_reader`` does both
    in one call with nothing in between — it takes a ``header_codec`` for its
    own decoding but has no way to pass an option down to the library. So the
    two halves are done here instead, out of the same pieces ``file_reader`` is
    built from.

    With no ``charset`` this is exactly ``file_reader``, which is what every
    format but cpio wants. :data:`_CHARSET_BY_LABEL` says why."""
    binding = _binding()
    pieces = _reader_pieces() if charset else None
    if pieces is None:
        # No charset wanted, or libarchive-c rearranged under us. Reading is
        # worth more than naming the charset, so fall back rather than fail.
        with binding.file_reader(path, passphrase=passphrase) as archive:
            yield archive
        return
    new_archive_read, archive_read_class, open_filename, set_options = pieces
    with new_archive_read('all', 'all', passphrase) as archive_p:
        set_options(archive_p, charset)
        open_filename(archive_p, path, MEMBER_CHUNK)
        yield archive_read_class(archive_p)


_reader_pieces_cache = None
_reader_pieces_resolved = False


def _reader_pieces():
    """The parts of ``libarchive-c`` :func:`_open_reader` builds a reader from,
    resolved once, or None if this version does not have them under these
    names."""
    global _reader_pieces_cache, _reader_pieces_resolved
    with _info_lock:
        if not _reader_pieces_resolved:
            _reader_pieces_resolved = True
            _reader_pieces_cache = _resolve_reader_pieces()
        return _reader_pieces_cache


def _resolve_reader_pieces():
    """Import those parts, or warn and give up on the charset."""
    try:
        import ctypes as _ctypes
        import libarchive.ffi as ffi
        from libarchive.read import ArchiveRead, new_archive_read

        set_options_fn = ffi.libarchive.archive_read_set_options
        set_options_fn.argtypes = [_ctypes.c_void_p, _ctypes.c_char_p]
        set_options_fn.restype = _ctypes.c_int

        def set_options(archive_p, charset: str) -> None:
            # A bad option is not worth failing an archive over; the reader
            # simply keeps its default charset.
            set_options_fn(_ctypes.c_void_p(archive_p),
                           f'hdrcharset={charset}'.encode())

        return (new_archive_read, ArchiveRead, ffi.read_open_filename_w, set_options)
    except Exception as exc:  # noqa: BLE001 — any absence means "use the plain reader"
        logger.warning(f"libarchive-c internals not as expected ({exc}); "
                       f"reading archives without an explicit header charset")
        return None


def clean_member_path(pathname: str) -> str:
    """An archive member's name as XeFM's internal path.

    libarchive hands back whatever the writer stored, which for anything bsdtar
    produced is ``./``-prefixed (``./sub/b.txt``, and ``./`` for the root
    itself). Those prefixes are stripped so the tree matches what zip and tar
    produce for the same directory; ``..`` components are left alone for
    :func:`~xefm.archive.is_safe_member_path` to refuse at extraction time."""
    path = (pathname or '').replace('\\', '/')
    while path.startswith('./'):
        path = path[2:]
    if path == '.':
        return ''
    return path.strip('/')


class _PendingWrite:
    """A member written to its destination but not yet closed.

    Handed back by :meth:`_ClaimedMember.write_to` so the slow half of the write
    can happen after the archive claim is released. It never leaves the worker
    that made it: one member, one thread, from ``open`` to ``close``, which is
    what keeps the handle's lifetime a local matter and lets ``finish`` raise
    where the member is still known.

    ``finish`` is where a deferred write actually lands. On a filesystem that
    holds a file in a local cache until it is closed — WebDAV, and NFS's
    close-to-open flush — ``close`` is the upload, and an out-of-space or
    transport failure surfaces from it rather than from any ``write``.

    Including a timeout, which is why one is named apart from the rest. Several
    workers close at once by design; if the destination's client overlaps fewer
    transfers than there are workers, the extra closes queue *inside it*, where
    a client- or server-side timeout can expire on one that has not started
    transferring yet. The failure then reads as the network's rather than as
    over-subscription, so the message says which knob it is."""

    __slots__ = ("target", "internal_path", "_handle", "_mtime")

    def __init__(self, target, internal_path: str, handle, mtime):
        self.target = target
        self.internal_path = internal_path
        self._handle = handle
        self._mtime = mtime

    def finish(self) -> None:
        """Close the file and stamp its timestamp, mapping what close reports."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.close()
        except OSError as exc:
            if ("No space left on device" in str(exc)
                    or "Disk quota exceeded" in str(exc)):
                raise ArchiveDiskSpaceError(
                    f"Insufficient disk space: {exc}",
                    "Insufficient disk space to extract archive")
            if exc.errno in (errno.ETIMEDOUT, errno.ETIME):
                raise ArchiveExtractionError(
                    f"Timed out writing {self.internal_path}: {exc}",
                    f"Timed out writing '{self.internal_path}' — if the "
                    f"destination is a network volume, lowering "
                    f"ARCHIVE_EXTRACT_WORKERS may help")
            raise ArchiveExtractionError(
                f"Error writing {self.internal_path}: {exc}",
                f"Cannot write '{self.internal_path}': {exc}")
        try:
            os.utime(str(self.target), (self._mtime, self._mtime))
        except Exception:  # noqa: BLE001 — metadata is best effort
            pass

    def discard(self) -> None:
        """Close without stamping or reporting — the cleanup path, for a worker
        unwinding on a cancel or another member's failure. What landed stays, the
        same as every other partial extraction."""
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001 — best effort
                pass


class _ClaimedMember:
    """The member a worker holds for the life of its claim.

    Its blocks come off the shared reader, so they must all be read before the
    claim is released — :class:`ExtractionPass` is what enforces that by handing
    one out at a time."""

    __slots__ = ("entry", "_raw", "_pass")

    def __init__(self, entry: ArchiveEntry, raw, owner):
        self.entry = entry
        self._raw = raw
        self._pass = owner

    def blocks(self) -> Iterator[bytes]:
        """The member's payload, with libarchive's errors given XeFM's names —
        the mapping stays here so no caller has to know the binding."""
        try:
            yield from self._raw.get_blocks()
        except Exception as exc:  # noqa: BLE001 — libarchive's own error type
            path = self.entry.internal_path
            if path in self._pass.encrypted:
                raise self._pass.decryption_error(exc, path)
            raise ArchiveExtractionError(
                f"Error extracting {path}: {exc}",
                f"Cannot extract '{path}': {exc}")

    def write_to(self, root: PathlibPath,
                 on_bytes: Optional[Callable[[int], None]] = None
                 ) -> Optional[_PendingWrite]:
        """Create this member under ``root`` and write its payload, returning the
        still-open file for the caller to :meth:`_PendingWrite.finish` *after* the
        claim is released — None for a directory, which is finished here.

        The split is the whole point: everything that touches the shared archive
        happens under the claim, and everything that only touches this member's
        own destination file can happen outside it. Where the destination makes
        ``close`` the expensive part, that is what overlaps."""
        target = root.joinpath(*self.entry.internal_path.split('/'))
        if self.entry.is_dir:
            target.mkdir(parents=True, exist_ok=True)
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = open(target, 'wb')
        except OSError as exc:
            raise ArchiveExtractionError(
                f"Error writing {self.entry.internal_path}: {exc}",
                f"Cannot write '{self.entry.internal_path}': {exc}")
        pending = _PendingWrite(target, self.entry.internal_path, handle,
                                self.entry.mtime)
        try:
            for block in self.blocks():
                handle.write(block)
                if on_bytes is not None:
                    on_bytes(len(block))
        except BaseException:
            pending.discard()
            raise
        return pending


class ExtractionPass:
    """One forward pass over an archive, claimable by any number of workers.

    libarchive has no random access: the reader is a cursor, and reading a member
    means advancing to its header and consuming its payload before anything may
    advance again. On a solid archive those two are one indivisible step — the
    decompressor only stays in step with the stream if every member's data is
    actually read on the way past.

    That invariant lives here, with the cursor. A caller running N workers over
    :meth:`claim_next` never learns why the claims serialise, only that they do,
    which is what lets the worker count be chosen for the *destination* — how
    many concurrent writes it will accept — rather than for the archive."""

    def __init__(self, handler: 'LibarchiveHandler', archive):
        self._handler = handler
        self._iter = iter(archive)
        self._lock = threading.Lock()
        self._done = False
        self._name = handler._archive_path.name
        self.encrypted = handler._encrypted
        self.decryption_error = handler._decryption_error
        self.logger = handler.logger

    @contextmanager
    def claim_next(self) -> Iterator[Optional[_ClaimedMember]]:
        """Claim the next extractable member, or None once the archive is spent.

        The claim is held for the whole ``with`` body, so the payload must be
        read inside it. Members XeFM will not recreate — a path escaping the
        destination, a symlink or device node — are passed over here rather than
        handed out, and a regular file among them has its data *read and
        discarded* rather than skipped: libarchive can only skip within its
        64 KiB decompression buffer, and past that a solid archive's next member
        comes back as a truncated body."""
        with self._lock:
            yield self._advance()

    def _advance(self) -> Optional[_ClaimedMember]:
        while not self._done:
            try:
                raw = next(self._iter)
            except StopIteration:
                self._done = True
                return None
            except ArchiveError:
                self._done = True
                raise
            except Exception as exc:  # noqa: BLE001 — libarchive reading a header
                self._done = True
                raise ArchiveExtractionError(
                    f"Error reading {self._name}: {exc}",
                    f"Cannot extract '{self._name}': {exc}")
            internal_path = clean_member_path(raw.pathname)
            if not internal_path:
                continue
            if not is_safe_member_path(internal_path):
                self.logger.warning(
                    f"Skipping unsafe archive member: {internal_path}")
                self._drain(raw)
                continue
            entry = (self._handler._entry_cache.get(internal_path)
                     or self._handler._to_entry(raw, internal_path))
            if not entry.is_dir and not raw.isreg:
                self.logger.info(f"Skipping {internal_path}: not a regular file")
                self._drain(raw)
                continue
            return _ClaimedMember(entry, raw, self)
        return None

    def retire(self) -> None:
        """No more members may be claimed from this pass.

        Called as the reader is about to be freed. A worker parked on a pass
        whose archive has already been closed then gets None back instead of
        reaching into a freed reader — which matters because a pass can be
        abandoned mid-stream (a cancel, another archive's failure), so
        exhaustion is not the only way it ends."""
        with self._lock:
            self._done = True

    @staticmethod
    def _drain(raw) -> None:
        """Consume a passed-over member's payload so the stream stays in step."""
        if not raw.isreg:
            return
        try:
            for _ in raw.get_blocks():
                pass
        except Exception:  # noqa: BLE001 — a member being skipped anyway
            pass


class _SkipUnreachable(Exception):
    """Internal: this member cannot be reached by skipping the ones ahead of it.

    Raised on :meth:`LibarchiveHandler._member_chunks`' skipping pass and caught
    one frame up, where it selects the draining pass instead. Never escapes the
    handler, so it deliberately is not an :class:`~xefm.archive.ArchiveError`:
    nothing outside should be able to catch it as one."""


class LibarchiveHandler(ArchiveHandler):
    """Reads any format the loaded libarchive supports.

    **libarchive has no random access.** A reader is a forward stream of
    headers, so ``open()`` makes one pass to build the tree and every later read
    re-opens the file and scans to its entry. That suits the ABC's
    "``open()`` caches the structure" contract for browsing, but it makes reading
    n entries one at a time O(n²) on a solid archive — which is why
    :meth:`iter_extract` is overridden to extract everything in a single pass.
    """

    def __init__(self, archive_path: Path, label: str = '7z'):
        super().__init__(archive_path)
        self._label = label
        self._temp_file: Optional[str] = None
        self._local_path: Optional[str] = None
        self._encrypted: Set[str] = set()
        self._member_count = 0
        self._member_bytes = 0
        self.logger = logger

    # -- opening ---------------------------------------------------------------

    def open(self):
        """Open the archive and cache its structure (one pass over the headers)."""
        if not self._archive_path.exists():
            raise FileNotFoundError(
                f"Archive not found: {self._archive_path}",
                f"Archive file '{self._archive_path.name}' does not exist")

        self._local_path = self._materialize()
        try:
            self._cache_entries()
        except ArchiveError:
            raise
        except Exception as exc:  # noqa: BLE001 — libarchive's own error type
            message = str(exc)
            if 'passphrase' in message.lower() or 'encrypted' in message.lower():
                # A header-encrypted archive cannot even be listed without the
                # password, so this is the gate reporting itself rather than a
                # damaged file.
                raise ArchivePasswordRequired(
                    f"Password required to list {self._archive_path.name}: {exc}",
                    f"'{self._archive_path.name}' is password-protected — a valid "
                    f"password is required")
            raise ArchiveCorruptedError(
                f"Cannot read {self._label} archive: {exc}",
                f"Archive '{self._archive_path.name}' is corrupted or invalid")
        self._is_open = True

    def _materialize(self) -> str:
        """The local filesystem path libarchive should read — the archive itself,
        or a temporary copy when it lives on remote storage. libarchive reads
        through a filename, so a remote archive has to land on disk first, the
        same way ZipHandler and TarHandler handle it."""
        if not self._archive_path.is_remote():
            self._temp_file = None
            return str(self._archive_path)
        try:
            suffix = f".{self._label}"
            temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            temp.write(self._archive_path.read_bytes())
            temp.close()
        except PermissionError as exc:
            raise ArchivePermissionError(
                f"Permission denied downloading archive: {exc}",
                f"Cannot download archive '{self._archive_path.name}': Permission denied")
        except OSError as exc:
            if "No space left on device" in str(exc) or "Disk quota exceeded" in str(exc):
                raise ArchiveDiskSpaceError(
                    f"Insufficient disk space: {exc}",
                    "Insufficient disk space to download archive")
            raise ArchiveError(
                f"Error downloading archive: {exc}",
                f"Cannot download archive '{self._archive_path.name}': {exc}")
        self._temp_file = temp.name
        return temp.name

    def close(self):
        """Drop the cached structure and any temporary copy. No libarchive state
        outlives a read — each one opens and closes its own reader — so there is
        nothing native to release here."""
        super().close()
        if self._temp_file:
            try:
                os.unlink(self._temp_file)
            except Exception:  # noqa: BLE001 — best effort
                pass
            self._temp_file = None

    def _reader(self, passphrase: Optional[bytes] = None):
        """A fresh libarchive reader over the local file."""
        return _open_reader(self._local_path, passphrase=passphrase or None,
                            charset=_CHARSET_BY_LABEL.get(self._label, ''))

    def _to_entry(self, raw, internal_path: str) -> ArchiveEntry:
        """One libarchive header as an :class:`~xefm.archive.ArchiveEntry`."""
        size = int(getattr(raw, 'size', 0) or 0)
        mode = int(getattr(raw, 'mode', 0) or 0) & 0o777
        try:
            mtime = float(raw.mtime or 0.0)
        except Exception:  # noqa: BLE001 — an entry with no usable timestamp
            mtime = 0.0
        is_dir = bool(raw.isdir)
        return ArchiveEntry(
            name=internal_path.split('/')[-1],
            internal_path=internal_path,
            is_dir=is_dir,
            size=size,
            # libarchive does not report a per-entry compressed size (a solid
            # block has no per-entry answer to give), so the tar convention of
            # reporting the uncompressed size stands in.
            compressed_size=size,
            mtime=mtime,
            mode=mode or (0o755 if is_dir else 0o644),
            archive_type=self._label,
        )

    def _cache_entries(self):
        """Walk the headers once, building the entry and directory caches and
        noting which entries are encrypted."""
        entries: List[ArchiveEntry] = []
        encrypted: Set[str] = set()
        with self._reader() as archive:
            for raw in archive:
                internal_path = clean_member_path(raw.pathname)
                if not internal_path:
                    continue  # the archive's own root member
                entries.append(self._to_entry(raw, internal_path))
                if _entry_is_encrypted(raw):
                    encrypted.add(internal_path)
        self._encrypted = encrypted
        self._member_count = len(entries)
        self._member_bytes = sum(e.size for e in entries if not e.is_dir)
        self._build_index(iter(entries), self._label)

    def entry_count(self) -> int:
        """How many members the archive actually stores.

        Not the size of the index: :meth:`iter_extract` walks the file's own
        headers, so the directories the index invents for parents that were never
        stored are created on the way past rather than yielded. Counting the
        index instead would leave every extraction's progress bar short of its
        total by however many directories the archive left implicit."""
        if not self._is_open:
            self.open()
        return self._member_count

    def extraction_totals(self) -> Tuple[int, int]:
        """The members the archive stores and the uncompressed bytes they hold.

        Both come off the headers :meth:`_cache_entries` already walked, so
        asking costs nothing — measured at 0.00s against the 1.55s the same
        archive takes to actually decompress. Counted from the stored members
        rather than the index for the reason :meth:`entry_count` gives."""
        if not self._is_open:
            self.open()
        return self._member_count, self._member_bytes

    # -- reading ---------------------------------------------------------------

    def list_entries(self, internal_path: str = "") -> List[ArchiveEntry]:
        """List entries at the given internal path"""
        if not self._is_open:
            self.open()
        normalized_path = self._normalize_path(internal_path)
        if normalized_path not in self._directory_cache:
            if normalized_path and normalized_path not in self._entry_cache:
                raise ArchiveNavigationError(
                    f"Path not found in archive: {internal_path}")
            return []
        return [self._entry_cache[child]
                for child in self._directory_cache[normalized_path]
                if child in self._entry_cache]

    def get_entry_info(self, internal_path: str) -> Optional[ArchiveEntry]:
        """Get information about a specific entry"""
        if not self._is_open:
            self.open()
        return self._entry_cache.get(self._normalize_path(internal_path))

    def _password(self) -> Optional[bytes]:
        """The password the session holds for this archive, if any."""
        return get_archive_password(self._archive_path)

    def _decryption_error(self, exc: Exception, internal_path: str) -> ArchiveError:
        """Map a failed read of an encrypted entry to the right typed error, so
        the UI can tell "wrong password" from "this library cannot decrypt this
        at all" — the second one must not re-prompt."""
        if not can_decrypt_7z():
            return ArchiveEncryptionUnsupported(
                f"Cannot decrypt {internal_path}: {exc}",
                f"Cannot read '{internal_path}': the libarchive in use was built "
                f"without support for this encryption")
        return ArchivePasswordRequired(
            f"Password required for {internal_path}: {exc}",
            f"'{self._archive_path.name}' is password-protected — a valid "
            f"password is required")

    def iter_member_bytes(self, internal_path: str,
                          chunk_size: int = MEMBER_CHUNK) -> Iterator[bytes]:
        """Stream one member's contents in blocks of about ``chunk_size``.

        libarchive hands data over in blocks of its own — around 16 KiB — which
        are coalesced here rather than passed straight on. The consumer reports
        progress and checks for a cancel once per block, both of which take a
        lock on the UI's progress state, and a gigabyte at 16 KiB would do that
        sixty thousand times. One report per megabyte is finer than any frame
        rate can show, and matches what the local copy loop does.

        Scans from the start of the archive to the entry, because the format has
        no index to seek with. Two passes are possible: the members ahead of the
        target are *skipped* first, and only if that leaves the target unreadable
        is the archive re-read *draining* them (see :meth:`_member_chunks`).
        Skipping is what keeps reading one file out of a big ISO or cpio cheap,
        so it stays the first thing tried; the retry is what makes a solid 7z
        work at all."""
        entry = self._require_readable_file(internal_path)
        normalized_path = self._normalize_path(internal_path)
        try:
            yield from self._member_chunks(normalized_path, entry, chunk_size,
                                           drain=False)
            return
        except _SkipUnreachable:
            pass
        self.logger.info(
            f"{self._archive_path.name}: {internal_path} cannot be reached by "
            f"skipping (solid archive) — re-reading from the start")
        yield from self._member_chunks(normalized_path, entry, chunk_size,
                                       drain=True)

    def _member_chunks(self, normalized_path: str, entry: ArchiveEntry,
                       chunk_size: int, *, drain: bool) -> Iterator[bytes]:
        """One pass over the archive, yielding the target member in chunks.

        ``drain`` decides what happens to the members *ahead* of the target.
        Skipping their data costs nothing where the format allows it, but a
        solid archive holds every member in one compressed stream and libarchive
        can only skip within its 64 KiB decompression buffer: past that the
        reader loses its place and the target reads back as "Truncated 7-Zip file
        body". Draining reads and discards that data, which is the only way to
        arrive at the target in step with the decoder.

        Which one a given archive needs is not something the headers say, so it
        is discovered rather than declared: on the skipping pass, a read that
        fails *before yielding anything* raises :class:`_SkipUnreachable` for
        :meth:`iter_member_bytes` to retry with. A failure after the first chunk
        has gone out is a real error — the caller is already consuming those
        bytes, and re-reading would hand it the member twice."""
        internal_path = entry.internal_path
        found = False
        try:
            with self._reader(self._password()) as archive:
                for raw in archive:
                    if clean_member_path(raw.pathname) != normalized_path:
                        if drain and raw.isreg:
                            for _ in raw.get_blocks():
                                pass
                        continue
                    found = True
                    started = False
                    try:
                        pending: List[bytes] = []
                        held = 0
                        for block in raw.get_blocks():
                            pending.append(block)
                            held += len(block)
                            if held >= chunk_size:
                                started = True
                                yield b''.join(pending)
                                pending, held = [], 0
                        if pending:
                            started = True
                            yield b''.join(pending)
                    except Exception as exc:  # noqa: BLE001 — libarchive's error
                        if normalized_path in self._encrypted:
                            raise self._decryption_error(exc, normalized_path)
                        if not drain and not started:
                            raise _SkipUnreachable from exc
                        raise ArchiveExtractionError(
                            f"Error extracting {internal_path}: {exc}",
                            f"Cannot extract '{internal_path}': {exc}")
                    break
        except (ArchiveError, _SkipUnreachable):
            raise
        except Exception as exc:  # noqa: BLE001 — a failure opening the reader
            raise ArchiveExtractionError(
                f"Error extracting file: {exc}",
                f"Cannot extract '{internal_path}': {exc}")
        if not found:
            raise FileNotFoundError(
                f"File not found in archive: {internal_path}",
                f"File '{entry.internal_path}' does not exist in archive")

    def extract_to_bytes(self, internal_path: str) -> bytes:
        """Extract a file's contents to memory — the streaming read, collected."""
        return b''.join(self.iter_member_bytes(internal_path))

    def extract_to_file(self, internal_path: str, target_path: Path):
        """Extract a file to ``target_path``.

        Goes through memory, as ZipHandler and TarHandler do, so the destination
        can be any storage XeFM supports rather than only the local disk."""
        data = self.extract_to_bytes(internal_path)
        entry = self._entry_cache.get(self._normalize_path(internal_path))
        try:
            target_path.write_bytes(data)
        except PermissionError as exc:
            raise ArchivePermissionError(
                f"Permission denied writing to target: {exc}",
                f"Cannot write to '{target_path}': Permission denied")
        except OSError as exc:
            if "No space left on device" in str(exc) or "Disk quota exceeded" in str(exc):
                raise ArchiveDiskSpaceError(
                    f"Insufficient disk space: {exc}",
                    "Insufficient disk space to extract file")
            raise ArchiveExtractionError(
                f"Error writing to target: {exc}",
                f"Cannot write to '{target_path}': {exc}")
        if entry is not None:
            try:
                os.utime(str(target_path), (entry.mtime, entry.mtime))
            except Exception:  # noqa: BLE001 — metadata is best effort
                pass

    @contextmanager
    def extraction_pass(self, dest_dir, *, password: Optional[bytes] = None
                        ) -> Iterator[ExtractionPass]:
        """An :class:`ExtractionPass` over this archive, writing under ``dest_dir``.

        The reader lives for the whole ``with``, so any number of workers may
        claim from it; :meth:`iter_extract` is the one-worker case of exactly
        this. Yields the pass and the destination root together because both are
        needed by whoever drives it, and the root is created here so no worker
        races another to make it."""
        if not self._is_open:
            self.open()
        root = PathlibPath(str(dest_dir))
        root.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            # Only *opening* the reader is wrapped. Whatever the body raises —
            # a mapped ArchiveError, or the driver's own cancellation, which this
            # layer must not have to name — travels out untouched; the stack
            # still closes the reader on its way past.
            try:
                archive = stack.enter_context(
                    self._reader(password or self._password()))
            except ArchiveError:
                raise
            except Exception as exc:  # noqa: BLE001 — libarchive's own error type
                raise ArchiveExtractionError(
                    f"Error extracting archive: {exc}",
                    f"Cannot extract '{self._archive_path.name}': {exc}")
            pass_ = ExtractionPass(self, archive)
            try:
                yield pass_
            finally:
                # The reader dies with the stack below; retiring first means a
                # worker still holding this pass is turned away rather than
                # following a freed pointer.
                pass_.retire()

    @staticmethod
    def extraction_root(dest_dir) -> PathlibPath:
        """The destination as a plain filesystem path — what workers join member
        paths onto. A separate call so a driver can hold it outside the pass."""
        return PathlibPath(str(dest_dir))

    def iter_extract(self, dest_dir, *, password: Optional[bytes] = None,
                     on_bytes: Optional[Callable[[int], None]] = None
                     ) -> Iterator[ArchiveEntry]:
        """Extract everything into ``dest_dir`` in one forward pass.

        The whole reason this is overridden: the generic implementation calls
        ``extract_to_file`` per entry, and with no random access each of those
        rescans the archive from the beginning — quadratic on the solid archives
        7z produces by default. One pass writes every member as its header goes
        by instead.

        The entry is yielded before its payload is written, and ``on_bytes`` is
        called with each block as it is written, so the byte bar moves through a
        large member rather than snapping to full at the end of it.

        This is :meth:`extraction_pass` driven by a single claimer, which is what
        keeps the sequential contract this method promises — one current member,
        entries in archive order — available to callers that want it. A driver
        wanting the destination's write concurrency runs several claimers over
        the pass instead, and gives up that ordering in exchange.

        Members that are neither a regular file nor a directory (symlinks,
        devices, sockets) are skipped and logged rather than recreated, as are
        members whose path escapes ``dest_dir``."""
        root = self.extraction_root(dest_dir)
        with self.extraction_pass(dest_dir, password=password) as pass_:
            while True:
                pending = None
                with pass_.claim_next() as member:
                    if member is None:
                        return
                    yield member.entry
                    pending = member.write_to(root, on_bytes)
                if pending is not None:
                    pending.finish()

    # -- encryption ------------------------------------------------------------

    def encryption_status(self) -> str:
        """``'none'``, ``'password'``, or ``'unsupported'``.

        Which entries are encrypted comes from the headers read at ``open()``;
        whether they can be decrypted at all is :func:`can_decrypt_7z`, which is
        currently False on every libarchive there is — such an archive lists its
        names perfectly well and then fails on every byte of its data."""
        if not self._is_open:
            self.open()
        if not self._encrypted:
            return 'none'
        return 'password' if can_decrypt_7z() else 'unsupported'

    def verify_password(self, password: bytes) -> bool:
        """Whether ``password`` decrypts this archive, tested on its smallest
        encrypted entry so a wrong password costs one small decompression."""
        if not self._is_open:
            self.open()
        if not self._encrypted or not can_decrypt_7z():
            return False
        smallest = min(
            self._encrypted,
            key=lambda path: getattr(self._entry_cache.get(path), 'size', 0) or 0)
        try:
            with self._reader(password) as archive:
                for raw in archive:
                    if clean_member_path(raw.pathname) != smallest:
                        continue
                    b''.join(raw.get_blocks())
                    return True
        except Exception:  # noqa: BLE001 — a wrong password fails the CRC check
            return False
        return False


# --- writing ------------------------------------------------------------------


#: Chunk size for the create path's read-and-compress loop. Large enough that the
#: per-call ctypes overhead disappears against the compression, small enough that
#: the byte bar moves several times a second on a slow source.
_WRITE_BLOCK = 256 * 1024


def member_walk(sources) -> Iterator[Tuple[PathlibPath, str, bool]]:
    """``(path, arcname, is_dir)`` for every member writing ``sources`` produces,
    a directory before its children.

    Deliberately member-for-member identical to
    ``XeFMApp._count_archive_entries(include_dirs=True)``, down to counting a
    directory that cannot be listed as itself and not descending into it — the
    total that pass produced is the one this loop has to reach, or the progress
    bar stops short. Directories are stored rather than left implicit, which is
    what keeps an empty one in the archive.
    """
    def walk(path: PathlibPath, arcname: str):
        is_dir = path.is_dir() and not path.is_symlink()
        yield path, arcname, is_dir
        if not is_dir:
            return
        try:
            children = list(path.iterdir())
        except OSError:  # the write is what surfaces the real error, not this
            return
        for child in children:
            yield from walk(child, f"{arcname}/{child.name}")

    for source in sources:
        root = PathlibPath(str(source))
        yield from walk(root, root.name)


def _file_blocks(path: PathlibPath, on_bytes: Optional[Callable[[int], None]]):
    """A file's contents in chunks, reporting each one as it goes past.

    The count is of bytes *read*, before compression, which is the same thing
    :class:`~xefm.archive_progress.ProgressTarFile` counts on the tar create path
    and the only figure the member's size can be compared against."""
    with open(path, 'rb') as handle:
        while True:
            chunk = handle.read(_WRITE_BLOCK)
            if not chunk:
                return
            if on_bytes is not None:
                on_bytes(len(chunk))
            yield chunk


def write_archive(archive_path, sources, *, format_name: str = '7zip',
                  options: str = '',
                  on_entry: Optional[Callable[[str, int, bool], None]] = None,
                  on_bytes: Optional[Callable[[int], None]] = None,
                  on_finish: Optional[Callable[[], None]] = None) -> int:
    """Write ``sources`` into a new archive at ``archive_path``, returning the
    number of members written.

    ``on_finish()`` is called once every member is written and before the
    archive itself is closed — which, on a destination that holds a file until
    close, is where the whole archive is uploaded and the only part of the run
    with nothing left to report. The caller uses it to say so.

    ``on_entry(arcname, size, is_dir)`` is called before each member,
    ``on_bytes(n)`` as its payload goes past. The directory flag comes from the
    walk rather than from the size, which cannot tell a directory from an empty
    file — the create side of the same two-level progress the
    zip and tar paths get from :mod:`xefm.archive_progress`. libarchive-c takes
    an *iterable* of blocks for a member's data, so the loop that feeds it is
    also the loop that reports; no separate counting proxy is needed.

    Callbacks rather than a generator, unlike
    :meth:`~xefm.archive.ArchiveHandler.iter_extract`: the output archive stays
    open for the whole run, and yielding control back mid-archive would tie that
    file's lifetime to whether the caller finished iterating. A callback that
    raises — ``Cancelled`` — unwinds through here, closing the partial file on
    the way out for the caller to remove.

    Local filesystem paths only, matching the rest of the create path. Symlinks
    are followed and stored as their target's contents, which is what ``zipfile``
    does; tar's link-preserving behaviour has no equivalent here.
    """
    from libarchive.entry import FileType

    binding = _binding()
    written = 0
    with binding.file_writer(str(archive_path), format_name,
                             options=options) as writer:
        for path, arcname, is_dir in member_walk(sources):
            info = path.stat()
            size = 0 if is_dir else info.st_size
            if on_entry is not None:
                on_entry(arcname, size, is_dir)
            writer.add_file_from_memory(
                arcname, size,
                b'' if is_dir else _file_blocks(path, on_bytes),
                filetype=FileType.DIRECTORY if is_dir else FileType.REGULAR_FILE,
                permission=stat.S_IMODE(info.st_mode),
                mtime=int(info.st_mtime),
            )
            written += 1
        # Still inside the writer's `with`: its close, below, is where the
        # archive itself lands — one transfer of the whole thing on a
        # destination that holds a file until it is closed.
        if on_finish is not None:
            on_finish()
    return written


# --- registration -------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    """A format libarchive could give us, and what the library must have for it."""

    label: str
    suffixes: Tuple[str, ...]
    description: str
    #: The readers that have to be compiled in — they are ``#ifdef``-switched,
    #: and a format can need more than one (a ``.rar`` is RAR4 or RAR5, and
    #: offering the suffix while only half of it reads would be a lie).
    symbols: Tuple[str, ...]
    #: Codecs that must appear in ``archive_version_details()``. Registering a
    #: format whose codec is missing is what triggers libarchive's
    #: external-program fallback, so this is a hard requirement, not a hint.
    codecs: Tuple[str, ...]
    #: The writer symbol, probed the same way and separately: libarchive reads
    #: strictly more formats than it writes (rar, lha and cab are read-only), so
    #: a format that arrives here readable is not thereby creatable.
    write_symbol: str = ''
    #: libarchive's own name for the format, passed to ``file_writer``.
    write_format: str = ''
    #: Writer options. Worth being explicit about: libarchive's 7z writer
    #: defaults to LZMA1, while 7-Zip itself has written LZMA2 for years, and an
    #: archive XeFM creates should look like the ones its users already have.
    write_options: str = ''
    #: Filters the format needs on top of its reader — ``.rpm`` is the rpm
    #: filter wrapped around a cpio, and is the only reason this exists.
    filters: Tuple[str, ...] = ()


#: Formats XeFM offers through libarchive. 7z came first and is still the one
#: that exercises every property of this path — the probe, the loader order,
#: encrypted entries, and the cost of per-entry extraction inside a solid block
#: — which is why the rest could arrive as rows rather than as projects:
#: libarchive implements every one of these readers itself.
#:
#: Two formats are deliberately absent. **xar** looks attractive (a macOS .pkg
#: is one) but libarchive 3.7.4 over-reads its entries — a 7-byte member comes
#: back as 13 bytes, NUL-padded — so adding it needs the extraction loops to
#: truncate at the declared size first. **lha** would need CP932 filename
#: conversion, which the same library fails at fatally: an ASCII-named member
#: reads and a Shift_JIS-named one aborts the whole archive, which is the
#: wrong half to support for the archives that format is found in.
_CANDIDATES: Tuple[_Candidate, ...] = (
    _Candidate(label='7z', suffixes=('.7z',), description='7-Zip',
               symbols=('archive_read_support_format_7zip',),
               # LZMA/LZMA2 is what essentially every real 7z uses; liblzma
               # missing means the format would open and then fail per entry.
               codecs=('liblzma',),
               write_symbol='archive_write_set_format_7zip',
               write_format='7zip', write_options='compression=lzma2'),

    # Read-only, and not for want of trying: nobody writes RAR but WinRAR. The
    # win is that libarchive implements the reader itself, so XeFM needs none of
    # the non-free ``unrar`` binary that the ``rarfile`` package shells out to.
    # Both generations are required rather than one: a .rar offered on the
    # strength of the RAR4 reader alone would fail on every modern archive.
    _Candidate(label='rar', suffixes=('.rar',), description='RAR',
               symbols=('archive_read_support_format_rar',
                        'archive_read_support_format_rar5'),
               codecs=()),

    # Browsing a disc image without mounting it. Uncompressed, so no codec is
    # required; zisofs would want zlib, and simply fails to decompress without
    # it rather than reaching for a program.
    _Candidate(label='iso', suffixes=('.iso',), description='ISO 9660',
               symbols=('archive_read_support_format_iso9660',),
               codecs=(),
               write_symbol='archive_write_set_format_iso9660',
               write_format='iso9660'),

    # MSZIP, the common CAB compression, is deflate — hence zlib. LZX is
    # libarchive's own.
    _Candidate(label='cab', suffixes=('.cab',), description='Cabinet',
               symbols=('archive_read_support_format_cab',),
               codecs=('zlib',)),

    _Candidate(label='cpio', suffixes=('.cpio',), description='cpio',
               symbols=('archive_read_support_format_cpio',),
               codecs=(),
               write_symbol='archive_write_set_format_cpio_newc',
               # SVR4 "newc" rather than the historic odc the plain ``cpio``
               # writer produces: odc stores sizes in 8 octal digits, so it
               # cannot hold a member over 8 GB.
               write_format='cpio_newc',
               # See _CHARSET_BY_LABEL for why cpio, alone, is told a charset.
               write_options=f'hdrcharset={_HDRCHARSET}'),

    # An RPM is the rpm filter wrapped around a compressed cpio. The filter
    # itself only skips the package header; the payload's codec is what has to
    # be present, and modern packages use xz. A zstd payload on a library
    # without libzstd is the one case that still reaches for an external
    # program -- a container's inner codec cannot be probed from out here.
    _Candidate(label='rpm', suffixes=('.rpm',), description='RPM package',
               symbols=('archive_read_support_format_cpio',),
               codecs=('zlib', 'liblzma'),
               filters=('archive_read_support_filter_rpm',)),
)


#: Formats whose reader is told outright what its header bytes mean, and what to
#: tell it. Everything absent from here is read with libarchive's own default,
#: and that is the important half of this table.
#:
#: **cpio** is told UTF-8 because its default on Windows is the *OEM* code page —
#: 437 on a US install. That is not the ANSI one, so :func:`_use_utf8_ctype`
#: cannot move it (libarchive maps a locale *name* to an OEM page through a
#: table, ignoring the ``.UTF8`` suffix), and it cannot spell a CJK name: writing
#: one gives question marks, reading one gives mojibake. UTF-8 is also what cpio
#: archives actually contain, since they come from systems whose locale is UTF-8,
#: and it is what libarchive already defaults to on macOS and Linux. ``.rpm`` is
#: a cpio inside an rpm wrapper, so it gets the same.
#:
#: **CAB, RAR, 7z and ISO are deliberately not here.** Their names are either
#: Unicode in the container already, or in a legacy code page that libarchive
#: detects for itself — and forcing UTF-8 on a CAB whose names are CP932 does not
#: garble them, it makes ``archive_entry_pathname`` return NULL for every entry,
#: so the archive opens and appears to be empty. Mojibake is a bad listing;
#: nothing at all is a broken one.
_CHARSET_BY_LABEL = {c.label: c.write_options.split('=', 1)[1]
                     for c in _CANDIDATES
                     if c.write_options.startswith('hdrcharset=')}
_CHARSET_BY_LABEL['rpm'] = _HDRCHARSET


def libarchive_formats() -> List[ArchiveFormat]:
    """The formats the loaded library actually justifies — empty when libarchive
    is absent or built without what they need."""
    info = libarchive_info()
    if not info.available:
        return []
    formats = []
    for candidate in _CANDIDATES:
        if any(not _has_symbol(name) for name in candidate.symbols):
            continue
        if any(not _has_symbol(name) for name in candidate.filters):
            continue
        if any(codec not in info.codecs for codec in candidate.codecs):
            continue
        writer = None
        if candidate.write_symbol and _has_symbol(candidate.write_symbol):
            writer = partial(write_archive, format_name=candidate.write_format,
                             options=candidate.write_options)
        formats.append(ArchiveFormat(
            label=candidate.label,
            suffixes=candidate.suffixes,
            factory=lambda path, label=candidate.label: LibarchiveHandler(path, label),
            description=candidate.description,
            writer=writer,
        ))
    return formats


def register_libarchive_formats() -> None:
    """Add every justified format to the readable-format table, saying something
    only when the outcome is not the ordinary one.

    Three supply paths mean a bug report has to be able to name the library that
    answered, but a full line at every successful startup was a lot of noise for
    the normal case, so success is ``debug`` and the Help dialog carries the same
    information where a user can actually find it. What stays visible is the two
    outcomes worth acting on: no library at all, and a library that loaded and
    then justified nothing — the second being the shape a mis-built or
    half-stripped copy takes, and easy to mistake for the first."""
    info = libarchive_info()
    if not info.available:
        logger.info(f"libarchive not loaded ({info.error}); zip and tar only")
        return
    formats = libarchive_formats()
    for fmt in formats:
        register_archive_format(fmt)
    if not formats:
        logger.warning(f"libarchive loaded but supports none of the formats XeFM "
                       f"offers: {info.details} [{info.library_path}]")
        return
    read = ' '.join(sfx for fmt in formats for sfx in fmt.suffixes)
    write = ' '.join(sfx for fmt in formats if fmt.writer is not None
                     for sfx in fmt.suffixes) or '(none)'
    logger.debug(f"libarchive: {info.details} [{info.library_path}] "
                 f"reading {read}, writing {write}")


# Registration runs here rather than in ``xefm/archive.py`` so that it happens
# exactly once and in either import order. This module and that one import each
# other; whichever is imported first finishes the other before reaching its own
# bottom, and only this module can know that every name below is bound.
register_libarchive_formats()
