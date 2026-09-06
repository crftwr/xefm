#!/usr/bin/env python3
"""libarchive-backed archive formats — the engine behind ``.7z``.

XeFM reads zip and tar through the Python standard library. Everything else
comes from `libarchive <https://libarchive.org/>`_, reached through the pure
-ctypes ``libarchive-c`` binding, and registered into
:data:`xefm.archive.ARCHIVE_HANDLERS` as ordinary table entries. Nothing here is
required: with no usable library the table simply has fewer formats in it and
zip and tar carry on unchanged.

**Three supply paths, one loader.** ``libarchive-c`` finds the shared library
itself, in this order:

1. a bundled copy, which the desktop builds point at by setting ``LIBARCHIVE``
   before XeFM starts;
2. the ``LIBARCHIVE`` environment variable, which a terminal user can set to a
   library they downloaded or built;
3. ``ctypes.util.find_library("archive")`` — the system copy, which is what
   macOS and most Linux distributions already have.

Because two of those three are built by somebody else, **what a format needs is
probed, never assumed from a version number**. ``archive_version_details()``
names only the codecs actually compiled in, and a format is registered only when
the loaded library reports what it needs. That is also how the silent
external-program fallback is avoided: libarchive answers a missing stream codec
by spawning ``gzip -d`` or ``xz -d``, one process per entry, and on Windows those
binaries are simply absent — so a format whose codec is missing must never be
offered in the first place.

macOS ships libarchive 3.7.4 with zlib, liblzma and bz2lib, which is enough to
read ``.7z``; it is built without crypto, so AES-encrypted 7z entries cannot be
decrypted on that library at any password. :func:`can_decrypt_7z` establishes
which of the two applies by decrypting a known archive, rather than guessing
from a version, so the UI can say "not supported" instead of rejecting every
password the user types.
"""

import base64
import ctypes
import logging
import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path as PathlibPath
from typing import Callable, Iterator, List, Optional, Set, Tuple

from xefm.log_manager import getLogger
from xefm.path import Path
from xefm.archive import (
    ArchiveCorruptedError, ArchiveEncryptionUnsupported, ArchiveEntry,
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


def _probe() -> LibarchiveInfo:
    """Import ``libarchive-c`` and ask the library that loaded what it supports.

    Importing the binding is what loads the shared library, so an absent or
    unloadable library surfaces here as an import failure rather than later as a
    read failure."""
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
# of whether the loaded library can decrypt 7z at all: libarchive compiles its
# AES support in behind HAVE_LIBCRYPTO / CNG / CommonCrypto, none of which
# ``archive_version_details()`` mentions, and macOS's system build has none of
# them. Without this probe an encrypted 7z would reject every password the user
# typed with no way to say why.
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
        return _binding().file_reader(self._local_path, passphrase=passphrase or None)

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

    def _require_file(self, internal_path: str) -> Tuple[str, ArchiveEntry]:
        """The normalized path and cached entry for a member that must be a file."""
        if not self._is_open:
            self.open()
        normalized_path = self._normalize_path(internal_path)
        entry = self._entry_cache.get(normalized_path)
        if not entry:
            raise FileNotFoundError(
                f"File not found in archive: {internal_path}",
                f"File '{internal_path}' does not exist in archive")
        if entry.is_dir:
            raise ArchiveExtractionError(
                f"Cannot extract directory as bytes: {internal_path}",
                f"'{internal_path}' is a directory, not a file")
        return normalized_path, entry

    def extract_to_bytes(self, internal_path: str) -> bytes:
        """Extract a file's contents to memory.

        Scans from the start of the archive to the entry, because the format has
        no index to seek with. On a solid archive that means decompressing
        everything ahead of it as well."""
        normalized_path, _entry = self._require_file(internal_path)
        try:
            with self._reader(self._password()) as archive:
                for raw in archive:
                    if clean_member_path(raw.pathname) != normalized_path:
                        continue
                    try:
                        return b''.join(raw.get_blocks())
                    except Exception as exc:  # noqa: BLE001 — libarchive's error
                        if normalized_path in self._encrypted:
                            raise self._decryption_error(exc, normalized_path)
                        raise ArchiveExtractionError(
                            f"Error extracting {internal_path}: {exc}",
                            f"Cannot extract '{internal_path}': {exc}")
        except ArchiveError:
            raise
        except Exception as exc:  # noqa: BLE001 — a failure opening the reader
            raise ArchiveExtractionError(
                f"Error extracting file: {exc}",
                f"Cannot extract '{internal_path}': {exc}")
        raise FileNotFoundError(
            f"File not found in archive: {internal_path}",
            f"File '{internal_path}' does not exist in archive")

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
        large member rather than snapping to full at the end of it. We write the
        blocks ourselves (``get_blocks()``) instead of handing the job to
        ``archive_read_extract``, which is what makes that granularity available
        without libarchive's own progress callback.

        Members that are neither a regular file nor a directory (symlinks,
        devices, sockets) are skipped and logged rather than recreated, as are
        members whose path escapes ``dest_dir``."""
        if not self._is_open:
            self.open()
        root = PathlibPath(str(dest_dir))
        root.mkdir(parents=True, exist_ok=True)
        try:
            with self._reader(password or self._password()) as archive:
                for raw in archive:
                    internal_path = clean_member_path(raw.pathname)
                    if not internal_path:
                        continue
                    if not is_safe_member_path(internal_path):
                        self.logger.warning(
                            f"Skipping unsafe archive member: {internal_path}")
                        continue
                    entry = (self._entry_cache.get(internal_path)
                             or self._to_entry(raw, internal_path))
                    if not entry.is_dir and not raw.isreg:
                        self.logger.info(
                            f"Skipping {internal_path}: not a regular file")
                        continue
                    yield entry
                    target = root.joinpath(*internal_path.split('/'))
                    if entry.is_dir:
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            with open(target, 'wb') as fh:
                                for block in raw.get_blocks():
                                    fh.write(block)
                                    if on_bytes is not None:
                                        on_bytes(len(block))
                        except ArchiveError:
                            raise
                        except OSError as exc:
                            if ("No space left on device" in str(exc)
                                    or "Disk quota exceeded" in str(exc)):
                                raise ArchiveDiskSpaceError(
                                    f"Insufficient disk space: {exc}",
                                    "Insufficient disk space to extract archive")
                            raise ArchiveExtractionError(
                                f"Error writing {internal_path}: {exc}",
                                f"Cannot write '{internal_path}': {exc}")
                        except Exception as exc:  # noqa: BLE001 — libarchive's
                            if internal_path in self._encrypted:
                                raise self._decryption_error(exc, internal_path)
                            raise ArchiveExtractionError(
                                f"Error extracting {internal_path}: {exc}",
                                f"Cannot extract '{internal_path}': {exc}")
                        try:
                            os.utime(str(target), (entry.mtime, entry.mtime))
                        except Exception:  # noqa: BLE001 — metadata is best effort
                            pass
        except ArchiveError:
            raise
        except Exception as exc:  # noqa: BLE001 — a failure opening the reader
            raise ArchiveExtractionError(
                f"Error extracting archive: {exc}",
                f"Cannot extract '{self._archive_path.name}': {exc}")

    # -- encryption ------------------------------------------------------------

    def encryption_status(self) -> str:
        """``'none'``, ``'password'``, or ``'unsupported'``.

        Which entries are encrypted comes from the headers read at ``open()``;
        whether they can be decrypted at all is :func:`can_decrypt_7z`, because a
        libarchive built without crypto reads such an archive's names perfectly
        well and then fails on every byte of its data."""
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
                  on_entry: Optional[Callable[[str, int], None]] = None,
                  on_bytes: Optional[Callable[[int], None]] = None) -> int:
    """Write ``sources`` into a new archive at ``archive_path``, returning the
    number of members written.

    ``on_entry(arcname, size)`` is called before each member, ``on_bytes(n)`` as
    its payload goes past — the create side of the same two-level progress the
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
                on_entry(arcname, size)
            writer.add_file_from_memory(
                arcname, size,
                b'' if is_dir else _file_blocks(path, on_bytes),
                filetype=FileType.DIRECTORY if is_dir else FileType.REGULAR_FILE,
                permission=stat.S_IMODE(info.st_mode),
                mtime=int(info.st_mtime),
            )
            written += 1
    return written


# --- registration -------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    """A format libarchive could give us, and what the library must have for it."""

    label: str
    suffixes: Tuple[str, ...]
    description: str
    #: The reader has to be compiled in — readers are ``#ifdef``-switched.
    symbol: str
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


#: Formats XeFM offers through libarchive. 7z is the only one for now — it is
#: the format actually asked for, and the one that exercises every property of
#: this path (the probe, the loader order, encrypted entries, and the cost of
#: per-entry extraction inside a solid block). rar / lha / cab / iso / xar are
#: additional rows here once 7z has proven the path, not separate projects:
#: libarchive implements all of their readers itself.
_CANDIDATES: Tuple[_Candidate, ...] = (
    _Candidate(label='7z', suffixes=('.7z',), description='7-Zip',
               symbol='archive_read_support_format_7zip',
               # LZMA/LZMA2 is what essentially every real 7z uses; liblzma
               # missing means the format would open and then fail per entry.
               codecs=('liblzma',),
               write_symbol='archive_write_set_format_7zip',
               write_format='7zip', write_options='compression=lzma2'),
)


def libarchive_formats() -> List[ArchiveFormat]:
    """The formats the loaded library actually justifies — empty when libarchive
    is absent or built without what they need."""
    info = libarchive_info()
    if not info.available:
        return []
    formats = []
    for candidate in _CANDIDATES:
        if not _has_symbol(candidate.symbol):
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
    """Add every justified format to the readable-format table and log what
    happened — with three possible supply paths behind the library, a bug report
    has to say which one answered and what it could do."""
    info = libarchive_info()
    if not info.available:
        logger.info(f"libarchive not loaded ({info.error}); "
                    f"zip and tar only")
        return
    formats = libarchive_formats()
    for fmt in formats:
        register_archive_format(fmt)
    read = ' '.join(sfx for fmt in formats for sfx in fmt.suffixes) or '(none)'
    write = ' '.join(sfx for fmt in formats if fmt.writer is not None
                     for sfx in fmt.suffixes) or '(none)'
    logger.info(f"libarchive: {info.details} [{info.library_path}] "
                f"reading {read}, writing {write}")


# Registration runs here rather than in ``xefm/archive.py`` so that it happens
# exactly once and in either import order. This module and that one import each
# other; whichever is imported first finishes the other before reaching its own
# bottom, and only this module can know that every name below is bound.
register_libarchive_formats()
