#!/usr/bin/env python3
"""
XeFM Path - A pathlib-compatible Path class that can be extended for remote storage support
"""

import os
import stat
import sys
import fnmatch
import io
import errno
from concurrent.futures import CancelledError
from contextlib import contextmanager, nullcontext
from abc import ABC, abstractmethod
from pathlib import Path as PathlibPath, PurePath
from datetime import datetime
from typing import Union, Iterator, List, NamedTuple, Optional, Any
from xefm import dir_scan
from xefm import path_schemes
from xefm.log_manager import getLogger
from xefm.str_format import format_size

logger = getLogger("Path")

#: Every capability name a :class:`PathImpl` may declare in its
#: ``CAPABILITIES`` set. A backend names the ones it has; anything left out is
#: absent. The set form is what makes the vocabulary safe to grow — a name
#: added here is simply undeclared by every class written before it, so adding
#: one cannot break a backend that lives outside this repository.
KNOWN_CAPABILITIES = frozenset({
    'write_operations',        # copy, move, create, delete
    'directory_rename',        # renaming a directory, not just a file
    'file_editing',            # handing the file to an external editor
    'streaming_read',          # readable line by line, without a full fetch
    'extraction_for_reading',  # content must be fetched or extracted first
    'cache_for_search',        # that fetch is expensive enough to keep
    'entry_identity',          # lstat()'s st_dev/st_ino name a directory entry
})

#: The capabilities :meth:`Path.supports` answers for as stable API — the ones
#: a caller outside XeFM has a use for. The rest of :data:`KNOWN_CAPABILITIES`
#: tune XeFM's own search and may change.
STABLE_CAPABILITIES = frozenset({
    'write_operations', 'directory_rename', 'file_editing', 'streaming_read',
})

#: The values ``SEARCH_STRATEGY`` may take. ``'streaming'`` reads line by line,
#: ``'buffered'`` downloads to a buffer first, ``'extracted'`` unpacks the whole
#: entry before searching it.
SEARCH_STRATEGIES = frozenset({'streaming', 'buffered', 'extracted'})


class _CallbackAbort(CancelledError):
    """Carries an exception raised by a caller's ``progress_callback`` back out
    of a copy untouched, instead of letting it be folded into the generic
    ``OSError`` every transfer failure becomes.

    Cancelling a transfer is signalled by raising from the progress callback:
    mid-file, it is the only point at which the storage layer calls back into
    the caller often enough to notice. The storage layer stays ignorant of what
    that exception means — it just has to not swallow it.

    The base class must be ``concurrent.futures.CancelledError``: during an S3
    multipart upload the callback fires while botocore is reading the request
    body, and botocore wraps any other exception raised there in its
    *retryable* ``HTTPClientError`` — every in-flight part then retries the
    cancel as if it were a network blip, for ``max_attempts`` times with
    backoff (with ``max_attempts = 100`` in ``~/.aws/config``, effectively
    forever). ``CancelledError`` is the one exception botocore's HTTP layer
    re-raises unwrapped and its retry logic never retries, so a cancel aborts
    the transfer immediately. Since Python 3.8 ``CancelledError`` is a
    ``BaseException``, so cleanup handlers on the transfer path that must see
    it need ``except BaseException``, not ``except Exception``.
    """

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


def _guard_progress(progress_callback: Optional[callable]) -> Optional[callable]:
    """Wrap a caller's progress callback so anything it raises is tagged as
    :class:`_CallbackAbort` and survives the copy's error handling."""
    if progress_callback is None:
        return None

    def guarded(bytes_copied: int, bytes_total: int) -> None:
        try:
            progress_callback(bytes_copied, bytes_total)
        except _CallbackAbort:
            raise
        except BaseException as e:
            raise _CallbackAbort(e) from e

    return guarded


def attrs_via_path(entry) -> dict:
    """Build one :mod:`xefm.dir_scan` attribute record by asking a ``Path``
    itself — the per-file route, for backends with no bulk listing form.

    ``is_symlink`` is captured first because it stays meaningful for a broken
    symlink, whose ``stat`` below fails — as does ``hidden``, which describes
    the directory entry rather than whatever it points at.
    """
    try:
        is_link = entry.is_symlink()
    except Exception:
        is_link = False
    try:
        stat_info = entry.stat()
        is_dir = entry.is_dir()
    except Exception:
        return dict(dir_scan.BROKEN_ATTRS, is_link=is_link,
                    hidden=dir_scan.hidden_of(entry))
    # A followed stat describes the target, so a link's own attribute needs its
    # own look; anything else already has it in hand.
    hidden = (dir_scan.hidden_of(entry) if is_link
              else dir_scan.hidden_from_stat(stat_info))
    return {'is_dir': is_dir, 'is_link': is_link,
            'size': 0 if is_dir else stat_info.st_size,
            'alloc': 0 if is_dir else dir_scan.alloc_from_stat(stat_info),
            'mtime': stat_info.st_mtime, 'hidden': hidden, 'ok': True}


class PathImpl(ABC):
    """
    Abstract base class for path implementations.

    This defines the interface that all storage implementations must provide.
    Subclasses implement specific storage backends (local, S3, SCP, etc.).

    What a backend *does* stays abstract below. What a backend *is* is declared
    instead, in the five class attributes that follow: they are compile-time
    constants for every backend in this repository, so asking for them through
    twelve overridden methods only obliged each new implementation to answer
    twelve questions in prose. A declaration answers them in one line each, and
    an implementation that declares nothing still gets a usable, conservative
    answer — which is what lets this class's published subclasses in
    :mod:`xefm.path_base` promise not to break when the vocabulary grows.
    """

    #: The URI scheme this backend answers to, without ``://`` — ``'file'``,
    #: ``'s3'``, ``'ssh'``, ``'archive'``. Every concrete implementation must
    #: set it; ``test_path_capabilities.py`` fails when one does not.
    SCHEME: str = ''

    #: Whether paths of this backend live outside the local filesystem. A
    #: backend whose answer varies from one path to the next overrides
    #: :meth:`is_remote` instead — ``ArchivePathImpl`` does, because an archive
    #: held on S3 is remote and the same archive on disk is not.
    IS_REMOTE: bool = False

    #: The capabilities this backend has, named from :data:`KNOWN_CAPABILITIES`.
    #: Undeclared means absent, so the default below is the safe one: a backend
    #: that says nothing is treated as read-only, unstreamable and uneditable.
    CAPABILITIES: frozenset = frozenset()

    #: How content in this backend is best searched, from
    #: :data:`SEARCH_STRATEGIES`. ``'buffered'`` is the default because it is
    #: the one that works everywhere.
    SEARCH_STRATEGY: str = 'buffered'

    #: A storage-type indicator a UI may prepend to a path, with its trailing
    #: space (``'S3: '``). Empty for local files, which need no marking.
    DISPLAY_PREFIX: str = ''

    #: How many requests this storage serves at once: the ceiling on everything
    #: one operation asks of it together, reads and writes alike. 1 — one thing
    #: at a time — is the default because guessing upwards is the guess that
    #: hurts. See :func:`concurrency`.
    CONCURRENCY: int = 1

    #: How many of those requests may be reads (a listing is a read), and how
    #: many writes. ``None`` leaves it to :attr:`CONCURRENCY`; a larger number
    #: is held to it.
    READ_CONCURRENCY: Optional[int] = None
    WRITE_CONCURRENCY: Optional[int] = None

    def __init_subclass__(cls, **kwargs):
        """Validate a backend's declarations as it is defined.

        Warn-and-ignore, matching how ``EVENT_HOOKS`` treats an unknown event:
        a backend that names a capability this version has never heard of keeps
        the ones it got right and loses only the name nobody can act on. That
        is the direction of compatibility that matters — a class written
        against a *later* XeFM must still load here.
        """
        super().__init_subclass__(**kwargs)

        declared = frozenset(cls.CAPABILITIES)
        unknown = declared - KNOWN_CAPABILITIES
        if unknown:
            logger.warning(
                f"{cls.__name__}.CAPABILITIES names unknown "
                f"{'capabilities' if len(unknown) > 1 else 'capability'} "
                f"{', '.join(sorted(unknown))} — ignored; known names: "
                f"{', '.join(sorted(KNOWN_CAPABILITIES))}")
        cls.CAPABILITIES = declared & KNOWN_CAPABILITIES

        if cls.SEARCH_STRATEGY not in SEARCH_STRATEGIES:
            logger.warning(
                f"{cls.__name__}.SEARCH_STRATEGY is {cls.SEARCH_STRATEGY!r}, "
                f"which is not one of {', '.join(sorted(SEARCH_STRATEGIES))} — "
                f"using {PathImpl.SEARCH_STRATEGY!r}")
            cls.SEARCH_STRATEGY = PathImpl.SEARCH_STRATEGY

        # LISTING_CONCURRENCY (Preview) was the read side alone; a backend
        # written against it keeps its number as the total.
        legacy = cls.__dict__.get("LISTING_CONCURRENCY")
        if legacy is not None and "CONCURRENCY" not in cls.__dict__:
            logger.warning(
                f"{cls.__name__}.LISTING_CONCURRENCY is now CONCURRENCY "
                f"(with READ_CONCURRENCY / WRITE_CONCURRENCY) — using "
                f"{legacy!r} as CONCURRENCY")
            cls.CONCURRENCY = legacy

        for name in ("CONCURRENCY", "READ_CONCURRENCY", "WRITE_CONCURRENCY"):
            value = getattr(cls, name)
            if value is None and name != "CONCURRENCY":
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                logger.warning(
                    f"{cls.__name__}.{name} is {value!r}, which is not a count "
                    f"of at least 1 — using {getattr(PathImpl, name)!r}")
                setattr(cls, name, getattr(PathImpl, name))

    def supports(self, capability: str) -> bool:
        """Whether this backend has ``capability``.

        The single reader of :attr:`CAPABILITIES`, and the whole query surface
        that six ``supports_*`` / ``requires_*`` / ``should_*`` methods used to
        be. An unknown name is simply absent, so a caller written against a
        later vocabulary gets ``False`` here rather than an ``AttributeError``.
        """
        return capability in self.CAPABILITIES

    @abstractmethod
    def __str__(self) -> str:
        """String representation of the path"""
        pass
    
    @abstractmethod
    def __eq__(self, other) -> bool:
        """Equality comparison"""
        pass
    
    @abstractmethod
    def __hash__(self) -> int:
        """Hash support for use in sets and dicts"""
        pass
    
    @abstractmethod
    def __lt__(self, other) -> bool:
        """Less than comparison for sorting"""
        pass
    
    # Properties
    @property
    @abstractmethod
    def name(self) -> str:
        """The final component of the path"""
        pass
    
    @property
    @abstractmethod
    def stem(self) -> str:
        """The final component without its suffix"""
        pass
    
    @property
    @abstractmethod
    def suffix(self) -> str:
        """The file extension of the final component"""
        pass
    
    @property
    @abstractmethod
    def suffixes(self) -> List[str]:
        """A list of the path's suffixes"""
        pass
    
    @property
    @abstractmethod
    def parent(self) -> 'Path':
        """The logical parent of the path"""
        pass
    
    @property
    @abstractmethod
    def parents(self):
        """A sequence providing access to the logical ancestors of the path"""
        pass
    
    @property
    @abstractmethod
    def parts(self) -> tuple:
        """A tuple giving access to the path's components"""
        pass
    
    @property
    @abstractmethod
    def anchor(self) -> str:
        """The concatenation of the drive and root"""
        pass
    
    # Path manipulation methods
    @abstractmethod
    def absolute(self) -> 'Path':
        """Return an absolute version of this path"""
        pass
    
    @abstractmethod
    def resolve(self, strict: bool = False) -> 'Path':
        """Make the path absolute, resolving any symlinks"""
        pass
    
    @abstractmethod
    def expanduser(self) -> 'Path':
        """Return a new path with expanded ~ and ~user constructs"""
        pass
    
    @abstractmethod
    def joinpath(self, *args) -> 'Path':
        """Combine this path with one or several arguments"""
        pass
    
    @abstractmethod
    def with_name(self, name: str) -> 'Path':
        """Return a new path with the name changed"""
        pass
    
    @abstractmethod
    def with_stem(self, stem: str) -> 'Path':
        """Return a new path with the stem changed"""
        pass
    
    @abstractmethod
    def with_suffix(self, suffix: str) -> 'Path':
        """Return a new path with the suffix changed"""
        pass
    
    @abstractmethod
    def relative_to(self, other) -> 'Path':
        """Return a version of this path relative to the other path"""
        pass
    
    # File system query methods
    @abstractmethod
    def exists(self) -> bool:
        """Whether this path exists"""
        pass
    
    @abstractmethod
    def is_dir(self) -> bool:
        """Whether this path is a directory"""
        pass
    
    @abstractmethod
    def is_file(self) -> bool:
        """Whether this path is a regular file"""
        pass
    
    @abstractmethod
    def is_symlink(self) -> bool:
        """Whether this path is a symbolic link"""
        pass
    
    @abstractmethod
    def is_absolute(self) -> bool:
        """Whether this path is absolute"""
        pass
    
    @abstractmethod
    def stat(self):
        """Return the result of os.stat() on this path"""
        pass
    
    @abstractmethod
    def lstat(self):
        """Return the result of os.lstat() on this path"""
        pass
    
    # Directory operations
    @abstractmethod
    def iterdir(self) -> Iterator['Path']:
        """Iterate over the files in this directory"""
        pass

    def listdir_attrs(self) -> List[tuple]:
        """Return ``[(Path, attrs), …]`` for this directory's entries, where
        ``attrs`` is the record described in :mod:`xefm.dir_scan`
        (``is_dir``/``is_link``/``size``/``alloc``/``mtime``/``ok``).

        This is ``iterdir`` plus everything a listing needs to know about each
        entry, in one call — so a backend that can answer for the whole
        directory at once (a bulk syscall, a single list request) does, instead
        of being interrogated per file. A pane listing goes through here rather
        than through ``iterdir`` + per-entry ``stat``.

        The default implementation *is* ``iterdir`` + per-entry ``stat``, so a
        backend that has no bulk form keeps working unchanged; override it where
        the underlying protocol already returns metadata alongside names.
        """
        return [(child, attrs_via_path(child)) for child in self.iterdir()]


    @abstractmethod
    def glob(self, pattern: str) -> Iterator['Path']:
        """Iterate over this subtree and yield all existing files matching pattern"""
        pass
    
    @abstractmethod
    def rglob(self, pattern: str) -> Iterator['Path']:
        """Recursively iterate over this subtree and yield all existing files matching pattern"""
        pass
    
    @abstractmethod
    def match(self, pattern: str) -> bool:
        """Return True if this path matches the given pattern"""
        pass
    
    # File I/O operations
    @abstractmethod
    def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        """Open the file pointed to by this path"""
        pass
    
    @abstractmethod
    def read_text(self, encoding=None, errors=None) -> str:
        """Open the file in text mode, read it, and close the file"""
        pass
    
    @abstractmethod
    def read_bytes(self) -> bytes:
        """Open the file in bytes mode, read it, and close the file"""
        pass
    
    @abstractmethod
    def write_text(self, data: str, encoding=None, errors=None, newline=None) -> int:
        """Open the file in text mode, write to it, and close the file"""
        pass
    
    @abstractmethod
    def write_bytes(self, data: bytes) -> int:
        """Open the file in bytes mode, write to it, and close the file"""
        pass
    
    # File system modification operations
    @abstractmethod
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """Create a new directory at this given path"""
        pass
    
    @abstractmethod
    def rmdir(self):
        """Remove this directory"""
        pass
    
    @abstractmethod
    def unlink(self, missing_ok=False):
        """Remove this file or symbolic link"""
        pass
    
    @abstractmethod
    def rename(self, target) -> 'Path':
        """Rename this file or directory to the given target"""
        pass
    
    @abstractmethod
    def replace(self, target) -> 'Path':
        """Replace this file or directory with the given target"""
        pass
    
    @abstractmethod
    def symlink_to(self, target, target_is_directory=False):
        """Make this path a symlink pointing to the target path"""
        pass
    
    @abstractmethod
    def hardlink_to(self, target):
        """Make this path a hard link pointing to the same file as target"""
        pass
    
    @abstractmethod
    def touch(self, mode=0o666, exist_ok=True):
        """Create this file with the given access mode, if it doesn't exist"""
        pass
    
    @abstractmethod
    def chmod(self, mode):
        """Change the permissions of the path"""
        pass
    
    # Storage-specific methods
    def is_remote(self) -> bool:
        """Whether this path names a resource outside the local filesystem.

        Reads :attr:`IS_REMOTE`. A backend whose answer differs from one path
        to the next overrides this instead of declaring the attribute.
        """
        return self.IS_REMOTE

    def get_scheme(self) -> str:
        """The URI scheme of this path — ``'file'``, ``'s3'``, ``'archive'``.

        Reads :attr:`SCHEME`. File operations compare two paths' schemes to
        decide whether a move can be a rename, so a backend that leaves
        :attr:`SCHEME` empty is a bug, not a default.
        """
        return self.SCHEME

    @abstractmethod
    def as_uri(self) -> str:
        """Return the path as a URI"""
        pass

    def forget_cached_metadata(self) -> None:
        """Drop whatever this backend remembers about this path's metadata, so
        the next :meth:`stat` asks the storage itself.

        Remote backends cache stats for a while, which is right for browsing and
        wrong for the one question editing a remote file in place asks before
        each upload — *has anyone changed it since I read it?* (#581). The
        default does nothing, the right answer for a backend that caches
        nothing."""

    # Display methods for UI presentation
    def get_display_title(self) -> str:
        """A human-readable title for viewers, info dialogs and title bars.

        Every remote backend here returns its own URI, which is what
        ``str(self)`` already is. Only a backend that wants to show something
        other than the path it is needs to override this.
        """
        return str(self)

    # Metadata method for info dialogs
    def get_extended_metadata(self) -> dict:
        """Storage-specific detail for an info dialog.

        Returns ``{'type': str, 'details': [(label, value), ...],
        'format_hint': str}``. The default carries nothing beyond the storage
        type, which is the honest answer for a backend nobody has written one
        for — an empty ``details`` list displays as no extra rows, not as a
        row full of blanks.
        """
        return {'type': self.SCHEME or 'unknown', 'details': [],
                'format_hint': 'standard'}

    def target(self) -> Optional['Path']:
        """The real place this path stands for, when it is a reference to one
        rather than a place itself — an entry of an ``.xft`` tree (#573). The
        pane-sync keys reveal it, and bulk work on a selection acts on it.

        ``None`` for every path that is itself the place, which is every path
        but a reference. Not abstract: a backend written before this existed
        keeps working (#426's rule for the published base)."""
        return None
    
    # Compatibility methods
    @abstractmethod
    def samefile(self, other_path) -> bool:
        """Return whether other_path is the same or not as this file"""
        pass
    
    @abstractmethod
    def as_posix(self) -> str:
        """Return the string representation with forward slashes"""
        pass


# Windows refuses to remove an entry that carries FILE_ATTRIBUTE_READONLY
# (ERROR_ACCESS_DENIED, whatever the caller's rights), where POSIX looks only
# at the parent directory's permissions. A permanent delete is meant to remove
# such an entry, so the local removals clear the attribute and try once more
# — only after Windows has refused, so a removal that works touches no
# attribute. Google Drive for desktop, for one, marks every directory of its
# mirrored folder read-only. A ``replace`` onto a read-only file is refused
# the same way and retried the same way: Explorer's Replace goes through one
# without asking (issue #767).
_ERROR_ACCESS_DENIED = 5


def _clear_readonly(os_path: str, exc: PermissionError) -> bool:
    """Drop the read-only attribute from ``os_path`` when that is why ``exc``
    was raised; whether it was dropped. A reparse point (a symlink or a
    junction) is left alone: ``os.chmod`` would reach its target."""
    if sys.platform != 'win32' or getattr(exc, 'winerror', None) != _ERROR_ACCESS_DENIED:
        return False
    try:
        attrs = os.lstat(os_path).st_file_attributes
        if (not attrs & stat.FILE_ATTRIBUTE_READONLY
                or attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return False
        os.chmod(os_path, stat.S_IWRITE)  # on Windows: the read-only bit only
    except OSError:
        return False
    return True


def _retry_without_readonly(os_path: str, exc: PermissionError, remove):
    """After ``remove()`` failed with ``exc``: when ``os_path`` was refused for
    being read-only, clear that and call ``remove()`` once more, putting the
    attribute back if it fails again; otherwise re-raise ``exc``."""
    if not _clear_readonly(os_path, exc):
        raise exc
    # debug, not info: a Google Drive tree has one of these per directory.
    logger.debug(f"Cleared the read-only attribute to remove: {os_path}")
    try:
        return remove()
    except OSError:
        try:
            os.chmod(os_path, stat.S_IREAD)  # the entry stays, so as it was
        except OSError:
            pass
        raise


def _rmtree_local(os_path: str) -> None:
    """``shutil.rmtree`` with the read-only retry of :meth:`LocalPathImpl.rmdir`
    for every entry in the tree."""
    import shutil

    def retry(func, entry, exc):
        if isinstance(exc, tuple):  # onerror (before 3.12) passes exc_info
            exc = exc[1]
        if func not in (os.rmdir, os.unlink, os.remove) or not isinstance(exc, PermissionError):
            raise exc
        _retry_without_readonly(os.fspath(entry), exc, lambda: func(entry))

    if sys.version_info >= (3, 12):
        shutil.rmtree(os_path, onexc=retry)
    else:
        shutil.rmtree(os_path, onerror=retry)


class LocalPathImpl(PathImpl):
    """
    Local file system implementation of PathImpl.
    
    This class wraps pathlib.Path to provide local file system operations
    while implementing the PathImpl interface.
    """

    SCHEME = 'file'
    IS_REMOTE = False
    CAPABILITIES = frozenset({'write_operations', 'directory_rename',
                              'file_editing', 'streaming_read',
                              'entry_identity'})
    SEARCH_STRATEGY = 'streaming'
    DISPLAY_PREFIX = ''
    # Eight requests at once. A copy between two local paths is four files in
    # flight — each a read and a write on this disk, so half of the eight —
    # measured ~1.3–1.9x at 2–4 workers on an APFS SSD and *worse* beyond that,
    # between the GIL and filesystem metadata serialisation. With the other
    # end remote the disk is not what a copy waits on: a download from SSH
    # through a 40 ms round trip kept gaining up to 32 files at once (17.5 s
    # at 4, 8.9 s at 8), and eight reads off the disk while S3 takes them is
    # no strain. This covers a mounted network volume as well as a local disk,
    # and deliberately does not distinguish them: nothing in a path says which
    # it is, and CloseGate (file_operations) serialises the transfer a mounted
    # volume defers to close regardless. A WebDAV mount gained nothing past 2,
    # and loses nothing by being given more it will queue.
    CONCURRENCY = 8

    def __init__(self, path_obj: PathlibPath):
        """Initialize with a pathlib.Path object"""
        self._path = path_obj
    
    def __str__(self) -> str:
        """String representation of the path"""
        return str(self._path)
    
    def __eq__(self, other) -> bool:
        """Equality comparison"""
        if isinstance(other, LocalPathImpl):
            return self._path == other._path
        elif isinstance(other, PathlibPath):
            return self._path == other
        elif isinstance(other, str):
            return str(self._path) == other
        return False
    
    def __hash__(self) -> int:
        """Hash support for use in sets and dicts"""
        return hash(self._path)
    
    def __lt__(self, other) -> bool:
        """Less than comparison for sorting"""
        if isinstance(other, LocalPathImpl):
            return str(self._path) < str(other._path)
        return str(self._path) < str(other)
    
    # Properties
    @property
    def name(self) -> str:
        """The final component of the path"""
        return self._path.name
    
    @property
    def stem(self) -> str:
        """The final component without its suffix"""
        return self._path.stem
    
    @property
    def suffix(self) -> str:
        """The file extension of the final component"""
        return self._path.suffix
    
    @property
    def suffixes(self) -> List[str]:
        """A list of the path's suffixes"""
        return self._path.suffixes
    
    @property
    def parent(self) -> 'Path':
        """The logical parent of the path"""
        return Path(self._path.parent)
    
    @property
    def parents(self):
        """A sequence providing access to the logical ancestors of the path"""
        return [Path(p) for p in self._path.parents]
    
    @property
    def parts(self) -> tuple:
        """A tuple giving access to the path's components"""
        return self._path.parts
    
    @property
    def anchor(self) -> str:
        """The concatenation of the drive and root"""
        return self._path.anchor
    
    # Path manipulation methods
    def absolute(self) -> 'Path':
        """Return an absolute version of this path"""
        return Path(self._path.absolute())
    
    def resolve(self, strict: bool = False) -> 'Path':
        """Make the path absolute, resolving any symlinks"""
        return Path(self._path.resolve(strict=strict))
    
    def expanduser(self) -> 'Path':
        """Return a new path with expanded ~ and ~user constructs"""
        return Path(self._path.expanduser())
    
    def joinpath(self, *args) -> 'Path':
        """Combine this path with one or several arguments"""
        return Path(self._path.joinpath(*args))
    
    def with_name(self, name: str) -> 'Path':
        """Return a new path with the name changed"""
        return Path(self._path.with_name(name))
    
    def with_stem(self, stem: str) -> 'Path':
        """Return a new path with the stem changed"""
        return Path(self._path.with_stem(stem))
    
    def with_suffix(self, suffix: str) -> 'Path':
        """Return a new path with the suffix changed"""
        return Path(self._path.with_suffix(suffix))
    
    def relative_to(self, other) -> 'Path':
        """Return a version of this path relative to the other path"""
        if isinstance(other, Path):
            other = other._impl._path
        elif isinstance(other, LocalPathImpl):
            other = other._path
        return Path(self._path.relative_to(other))
    
    # File system query methods
    def exists(self) -> bool:
        """Whether this path exists"""
        return self._path.exists()
    
    def is_dir(self) -> bool:
        """Whether this path is a directory"""
        return self._path.is_dir()
    
    def is_file(self) -> bool:
        """Whether this path is a regular file"""
        return self._path.is_file()
    
    def is_symlink(self) -> bool:
        """Whether this path is a symbolic link"""
        return self._path.is_symlink()
    
    def is_absolute(self) -> bool:
        """Whether this path is absolute"""
        return self._path.is_absolute()
    
    def stat(self):
        """Return the result of os.stat() on this path"""
        return self._path.stat()
    
    def lstat(self):
        """Return the result of os.lstat() on this path"""
        return self._path.lstat()
    
    # Directory operations
    def iterdir(self) -> Iterator['Path']:
        """Iterate over the files in this directory"""
        for item in self._path.iterdir():
            yield Path(item)

    def listdir_attrs(self) -> List[tuple]:
        """Read the directory and every entry's attributes in one pass — see
        :func:`xefm.dir_scan.scan_dir`, which uses the platform's bulk
        enumeration where one exists. This is what keeps a large directory on a
        network mount from costing one round trip per file."""
        base = self._path
        return [(Path(base / name), attrs)
                for name, attrs in dir_scan.scan_dir(str(base))]


    def glob(self, pattern: str) -> Iterator['Path']:
        """Iterate over this subtree and yield all existing files matching pattern"""
        for item in self._path.glob(pattern):
            yield Path(item)
    
    def rglob(self, pattern: str) -> Iterator['Path']:
        """Recursively iterate over this subtree and yield all existing files matching pattern"""
        for item in self._path.rglob(pattern):
            yield Path(item)
    
    def match(self, pattern: str) -> bool:
        """Return True if this path matches the given pattern"""
        return self._path.match(pattern)
    
    # File I/O operations
    def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        """Open the file pointed to by this path"""
        return self._path.open(mode, buffering, encoding, errors, newline)
    
    def read_text(self, encoding=None, errors=None) -> str:
        """Open the file in text mode, read it, and close the file"""
        return self._path.read_text(encoding, errors)
    
    def read_bytes(self) -> bytes:
        """Open the file in bytes mode, read it, and close the file"""
        return self._path.read_bytes()
    
    def write_text(self, data: str, encoding=None, errors=None, newline=None) -> int:
        """Open the file in text mode, write to it, and close the file"""
        return self._path.write_text(data, encoding, errors)
    
    def write_bytes(self, data: bytes) -> int:
        """Open the file in bytes mode, write to it, and close the file"""
        return self._path.write_bytes(data)
    
    # File system modification operations
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """Create a new directory at this given path"""
        return self._path.mkdir(mode, parents, exist_ok)
    
    def rmdir(self):
        """Remove this directory (a read-only one too, on Windows)"""
        try:
            return self._path.rmdir()
        except PermissionError as exc:
            return _retry_without_readonly(str(self._path), exc, self._path.rmdir)
    
    def unlink(self, missing_ok=False):
        """Remove this file or symbolic link (a read-only one too, on Windows)"""
        try:
            return self._path.unlink(missing_ok)
        except PermissionError as exc:
            return _retry_without_readonly(str(self._path), exc,
                                           lambda: self._path.unlink(missing_ok))
    
    def rename(self, target) -> 'Path':
        """Rename this file or directory to the given target"""
        if isinstance(target, Path):
            target = target._impl._path
        elif isinstance(target, LocalPathImpl):
            target = target._path
        return Path(self._path.rename(target))
    
    def replace(self, target) -> 'Path':
        """Replace this file or directory with the given target (a read-only
        target file too, on Windows)"""
        if isinstance(target, Path):
            target = target._impl._path
        elif isinstance(target, LocalPathImpl):
            target = target._path
        try:
            return Path(self._path.replace(target))
        except PermissionError as exc:
            return _retry_without_readonly(str(target), exc,
                                           lambda: Path(self._path.replace(target)))

    def symlink_to(self, target, target_is_directory=False):
        """Make this path a symlink pointing to the target path"""
        if isinstance(target, Path):
            target = target._impl._path
        elif isinstance(target, LocalPathImpl):
            target = target._path
        return self._path.symlink_to(target, target_is_directory)
    
    def hardlink_to(self, target):
        """Make this path a hard link pointing to the same file as target"""
        if isinstance(target, Path):
            target = target._impl._path
        elif isinstance(target, LocalPathImpl):
            target = target._path
        return self._path.hardlink_to(target)
    
    def touch(self, mode=0o666, exist_ok=True):
        """Create this file with the given access mode, if it doesn't exist"""
        return self._path.touch(mode, exist_ok)
    
    def chmod(self, mode):
        """Change the permissions of the path"""
        return self._path.chmod(mode)
    
    # Storage-specific methods
    def as_uri(self) -> str:
        """Return the path as a URI"""
        return self._path.as_uri()
    
    # Compatibility methods
    def samefile(self, other_path) -> bool:
        """Return whether other_path is the same or not as this file"""
        if isinstance(other_path, Path):
            other_path = other_path._impl._path
        elif isinstance(other_path, LocalPathImpl):
            other_path = other_path._path
        return self._path.samefile(other_path)
    
    def as_posix(self) -> str:
        """Return the string representation with forward slashes"""
        return self._path.as_posix()
    
    # Metadata method for info dialogs
    def get_extended_metadata(self) -> dict:
        """Return storage-specific metadata for display in info dialogs.
        
        For local files, provides standard file system metadata including
        type, size, permissions, and modification time.
        
        Returns:
            dict: Metadata dictionary with structure:
                {
                    'type': 'local',
                    'details': [(label, value), ...],
                    'format_hint': 'standard'
                }
        """
        try:
            stat_info = self._path.stat()
            
            # Determine file type
            if self.is_dir():
                file_type = 'Directory'
            elif self.is_symlink():
                file_type = 'Symbolic Link'
            else:
                file_type = 'File'
            
            # Build details list
            details = [
                ('Type', file_type),
                ('Size', format_size(stat_info.st_size)),
                ('Permissions', self._format_permissions(stat_info.st_mode)),
                ('Modified', self._format_time(stat_info.st_mtime))
            ]
            
            return {
                'type': 'local',
                'details': details,
                'format_hint': 'standard'
            }
        except Exception as e:
            # If we can't get metadata, return minimal info
            return {
                'type': 'local',
                'details': [
                    ('Path', str(self._path)),
                    ('Error', f'Unable to retrieve metadata: {e}')
                ],
                'format_hint': 'standard'
            }
    
    
    def _format_permissions(self, mode: int) -> str:
        """Format permissions as rwxrwxrwx string.
        
        Args:
            mode: File mode from stat
            
        Returns:
            str: Permission string (e.g., 'rwxr-xr-x')
        """
        perms = []
        # Owner permissions
        perms.append('r' if mode & stat.S_IRUSR else '-')
        perms.append('w' if mode & stat.S_IWUSR else '-')
        perms.append('x' if mode & stat.S_IXUSR else '-')
        # Group permissions
        perms.append('r' if mode & stat.S_IRGRP else '-')
        perms.append('w' if mode & stat.S_IWGRP else '-')
        perms.append('x' if mode & stat.S_IXGRP else '-')
        # Other permissions
        perms.append('r' if mode & stat.S_IROTH else '-')
        perms.append('w' if mode & stat.S_IWOTH else '-')
        perms.append('x' if mode & stat.S_IXOTH else '-')
        return ''.join(perms)
    
    def _format_time(self, timestamp: float) -> str:
        """Format timestamp as readable date/time.
        
        Args:
            timestamp: Unix timestamp
            
        Returns:
            str: Formatted date/time string (e.g., '2024-01-15 10:30:00')
        """
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')


class Path:
    """
    A pathlib-compatible Path class designed to support both local and remote storage.
    
    This class acts as a facade that delegates operations to specific storage
    implementations (LocalPathImpl, S3PathImpl, etc.) based on the path scheme.

    **Every public member is stable API.** Extensions are handed a ``Path`` as
    ``EntryInfo.path`` and ``PaneApi.path``, so what it answers to is a promise
    under ``xefm.user_api.API_VERSION`` (doc/dev/STABLE_API_PLAN.md §2.1): the
    pathlib-compatible members below, ``str(path)`` — a filesystem path for a
    local file, a URI (``ssh://…``, ``s3://…``, ``archive://…#…``) otherwise —
    and four additions, :attr:`scheme`, :meth:`supports` (for the names in
    :data:`STABLE_CAPABILITIES`), :meth:`target` and :meth:`is_remote`. A write
    may raise ``OSError`` where the storage is read-only. A pathlib member not
    here yet may arrive later. What XeFM does with a path that is not part of
    that promise lives in module functions (:func:`copy_to`,
    :func:`listdir_attrs`, …), and the API snapshot test fails the moment a
    public member is added or removed here.
    """
    
    def __init__(self, *args):
        """Initialize Path with the same interface as pathlib.Path"""
        # Determine the appropriate implementation based on the path
        if len(args) == 1 and isinstance(args[0], Path):
            # Copy constructor
            self._impl = args[0]._impl
        elif len(args) == 1 and isinstance(args[0], PathlibPath):
            # Wrap existing pathlib.Path
            self._impl = LocalPathImpl(args[0])
        else:
            # Create new path from string arguments. A URI has to survive
            # verbatim: PathlibPath would collapse its 'scheme://' to
            # 'scheme:/'. Which prefixes those are is xefm.path_schemes'
            # business, not a list repeated here.
            if len(args) == 1 and path_schemes.is_uri(args[0]):
                path_str = args[0]
            else:
                path_str = str(PathlibPath(*args))
            self._impl = self._create_implementation(path_str)
    
    @classmethod
    def _from_impl(cls, impl: PathImpl) -> 'Path':
        """Wrap an implementation that is already built, without asking
        :meth:`_create_implementation` which one to build.

        A backend's string arithmetic — ``parent``, ``joinpath``, ``with_name``
        — has to hand back a ``Path``, and every backend here does it by
        formatting a URI and calling ``Path(uri)``. That works only for a
        scheme the factory knows, so a backend defined outside this repository
        could not use it: its own ``parent`` would come back as a local path.
        Going through the implementation it already has keeps the arithmetic
        closed over the class that produced it.
        """
        path = cls.__new__(cls)
        path._impl = impl
        return path

    def _create_implementation(self, path_str: str) -> PathImpl:
        """The backend for ``path_str`` — whichever scheme claims it in
        :mod:`xefm.path_schemes`, or the local filesystem if none does."""
        impl = path_schemes.create(path_str)
        if impl is not None:
            return impl
        return LocalPathImpl(PathlibPath(path_str))
    
    def __str__(self):
        """String representation of the path"""
        return str(self._impl)
    
    def __repr__(self):
        """Representation of the path"""
        return f"Path({str(self._impl)!r})"
    
    def __fspath__(self):
        """Support for os.fspath()"""
        return str(self._impl)
    
    def __truediv__(self, other):
        """Support for / operator"""
        return self._impl.joinpath(other)
    
    def __rtruediv__(self, other):
        """Support for reverse / operator"""
        return Path(other) / self
    
    def __eq__(self, other):
        """Equality comparison"""
        if isinstance(other, Path):
            return self._impl == other._impl
        else:
            return self._impl == other
    
    def __hash__(self):
        """Hash support for use in sets and dicts"""
        return hash(self._impl)
    
    def __lt__(self, other):
        """Less than comparison for sorting"""
        if isinstance(other, Path):
            return self._impl < other._impl
        return self._impl < other
    
    # Properties that delegate to implementation
    @property
    def name(self) -> str:
        """The final component of the path"""
        return self._impl.name
    
    @property
    def stem(self) -> str:
        """The final component without its suffix"""
        return self._impl.stem
    
    @property
    def suffix(self) -> str:
        """The file extension of the final component"""
        return self._impl.suffix
    
    @property
    def suffixes(self) -> List[str]:
        """A list of the path's suffixes"""
        return self._impl.suffixes
    
    @property
    def parent(self) -> 'Path':
        """The logical parent of the path"""
        return self._impl.parent
    
    @property
    def parents(self):
        """A sequence providing access to the logical ancestors of the path"""
        return self._impl.parents
    
    @property
    def parts(self) -> tuple:
        """A tuple giving access to the path's components"""
        return self._impl.parts
    
    @property
    def anchor(self) -> str:
        """The concatenation of the drive and root"""
        return self._impl.anchor
    
    # Methods that delegate to implementation
    def absolute(self) -> 'Path':
        """Return an absolute version of this path"""
        return self._impl.absolute()
    
    def resolve(self, strict: bool = False) -> 'Path':
        """Make the path absolute, resolving any symlinks"""
        return self._impl.resolve(strict=strict)
    
    def expanduser(self) -> 'Path':
        """Return a new path with expanded ~ and ~user constructs"""
        return self._impl.expanduser()
    
    def exists(self) -> bool:
        """Whether this path exists"""
        return self._impl.exists()
    
    def is_dir(self) -> bool:
        """Whether this path is a directory"""
        return self._impl.is_dir()
    
    def is_file(self) -> bool:
        """Whether this path is a regular file"""
        return self._impl.is_file()
    
    def is_symlink(self) -> bool:
        """Whether this path is a symbolic link"""
        return self._impl.is_symlink()
    
    def is_absolute(self) -> bool:
        """Whether this path is absolute"""
        return self._impl.is_absolute()
    
    def stat(self):
        """Return the result of os.stat() on this path"""
        return self._impl.stat()
    
    def lstat(self):
        """Return the result of os.lstat() on this path"""
        return self._impl.lstat()
    
    def iterdir(self) -> Iterator['Path']:
        """Iterate over the files in this directory"""
        return self._impl.iterdir()

    def _listdir_attrs(self) -> List[tuple]:
        """See :func:`listdir_attrs`."""
        return self._impl.listdir_attrs()

    def _concurrency(self) -> 'Concurrency':
        """See :func:`concurrency`."""
        impl = self._impl
        total = getattr(impl, 'CONCURRENCY', 1)
        read = getattr(impl, 'READ_CONCURRENCY', None) or total
        write = getattr(impl, 'WRITE_CONCURRENCY', None) or total
        return Concurrency(total, min(read, total), min(write, total))

    def glob(self, pattern: str) -> Iterator['Path']:
        """Iterate over this subtree and yield all existing files matching pattern"""
        return self._impl.glob(pattern)
    
    def rglob(self, pattern: str) -> Iterator['Path']:
        """Recursively iterate over this subtree and yield all existing files matching pattern"""
        return self._impl.rglob(pattern)
    
    def match(self, pattern: str) -> bool:
        """Return True if this path matches the given pattern"""
        return self._impl.match(pattern)
    
    def relative_to(self, other) -> 'Path':
        """Return a version of this path relative to the other path"""
        return self._impl.relative_to(other)
    
    def with_name(self, name: str) -> 'Path':
        """Return a new path with the name changed"""
        return self._impl.with_name(name)
    
    def with_stem(self, stem: str) -> 'Path':
        """Return a new path with the stem changed"""
        return self._impl.with_stem(stem)
    
    def with_suffix(self, suffix: str) -> 'Path':
        """Return a new path with the suffix changed"""
        return self._impl.with_suffix(suffix)
    
    def joinpath(self, *args) -> 'Path':
        """Combine this path with one or several arguments"""
        return self._impl.joinpath(*args)
    
    # File operations
    def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        """Open the file pointed to by this path"""
        return self._impl.open(mode, buffering, encoding, errors, newline)
    
    def read_text(self, encoding=None, errors=None) -> str:
        """Open the file in text mode, read it, and close the file"""
        return self._impl.read_text(encoding, errors)
    
    def read_bytes(self) -> bytes:
        """Open the file in bytes mode, read it, and close the file"""
        return self._impl.read_bytes()
    
    def write_text(self, data: str, encoding=None, errors=None, newline=None) -> int:
        """Open the file in text mode, write to it, and close the file"""
        return self._impl.write_text(data, encoding, errors, newline)
    
    def write_bytes(self, data: bytes) -> int:
        """Open the file in bytes mode, write to it, and close the file"""
        return self._impl.write_bytes(data)
    
    # Directory operations
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """Create a new directory at this given path"""
        return self._impl.mkdir(mode, parents, exist_ok)
    
    def rmdir(self):
        """Remove this directory"""
        return self._impl.rmdir()
    
    def unlink(self, missing_ok=False):
        """Remove this file or symbolic link"""
        return self._impl.unlink(missing_ok)
    
    def rename(self, target) -> 'Path':
        """Rename this file or directory to the given target"""
        return self._impl.rename(target)
    
    def replace(self, target) -> 'Path':
        """Replace this file or directory with the given target"""
        return self._impl.replace(target)
    
    def symlink_to(self, target, target_is_directory=False):
        """Make this path a symlink pointing to the target path"""
        return self._impl.symlink_to(target, target_is_directory)
    
    def hardlink_to(self, target):
        """Make this path a hard link pointing to the same file as target"""
        return self._impl.hardlink_to(target)
    
    def touch(self, mode=0o666, exist_ok=True):
        """Create this file with the given access mode, if it doesn't exist"""
        return self._impl.touch(mode, exist_ok)
    
    def chmod(self, mode):
        """Change the permissions of the path"""
        return self._impl.chmod(mode)
    
    # Class methods
    @classmethod
    def cwd(cls) -> 'Path':
        """Return a new path representing the current working directory"""
        return cls(PathlibPath.cwd())
    
    @classmethod
    def home(cls) -> 'Path':
        """Return a new path representing the user's home directory"""
        return cls(PathlibPath.home())
    
    # Storage-specific methods
    def is_remote(self) -> bool:
        """Return True if this path represents a remote resource"""
        return self._impl.is_remote()
    
    @property
    def scheme(self) -> str:
        """The storage this path lives on: ``'file'`` for the local disk,
        otherwise the URI scheme — ``'s3'``, ``'ssh'``, ``'archive'``, or one a
        ``PATH_SCHEMES`` backend registered."""
        return self._impl.get_scheme()
    
    def as_uri(self) -> str:
        """Return the path as a URI"""
        return self._impl.as_uri()
    
    # Compatibility methods for os.path operations
    def samefile(self, other_path) -> bool:
        """Return whether other_path is the same or not as this file"""
        return self._impl.samefile(other_path)
    
    def as_posix(self) -> str:
        """Return the string representation with forward slashes"""
        return self._impl.as_posix()
    
    # Capability delegation
    def supports(self, capability: str) -> bool:
        """Whether this path's storage backend has ``capability`` — a name out
        of :data:`KNOWN_CAPABILITIES`, such as ``'write_operations'`` or
        ``'directory_rename'``. Anything undeclared, including a name this
        version has never heard of, is ``False``."""
        return self._impl.supports(capability)

    def _forget_cached_metadata(self) -> None:
        """See :func:`forget_cached_metadata`."""
        self._impl.forget_cached_metadata()

    def target(self) -> Optional['Path']:
        """The real place a reference stands for, or ``None`` — see
        :meth:`PathImpl.target`."""
        return self._impl.target()
    
    def _move_to(self, destination: 'Path', overwrite: bool = False) -> bool:
        """
        Move this file or directory to the destination path.
        
        This method handles cross-storage moving (e.g., local to S3, S3 to local).
        For same-storage moves, it uses the native rename operation.
        For cross-storage moves, it copies then deletes the source.
        
        Args:
            destination: Target path where the file/directory should be moved
            overwrite: Whether to overwrite existing files
            
        Returns:
            True if move was successful, False otherwise
            
        Raises:
            FileNotFoundError: If source doesn't exist
            FileExistsError: If destination exists and overwrite=False
            PermissionError: If insufficient permissions
            OSError: For other I/O errors
        """
        if not self.exists():
            raise FileNotFoundError(f"Source path does not exist: {self}")
        
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Destination already exists: {destination}")
        
        # Handle same-storage moving first
        source_scheme = self.scheme
        dest_scheme = destination.scheme
        
        # Two directories merge rather than replace: no rename can do that, so
        # it takes the copy + delete path below.
        merge = overwrite and self.is_dir() and destination.is_dir()
        if source_scheme == dest_scheme and not merge:
            # Same storage type - use native rename/move. ``rename`` refuses an
            # existing destination on Windows, so an overwrite uses ``replace``.
            try:
                if overwrite and destination.exists():
                    self.replace(destination)
                else:
                    self.rename(destination)
                return True
            except OSError as e:
                # errno 18 is EXDEV (Cross-device link) - different mount points
                # Fall through to copy+delete approach
                if e.errno != 18:
                    raise OSError(f"Failed to move {self} to {destination}: {e}")
        
        # Cross-storage moving: copy then delete
        try:
            # First copy to destination, over a read-only file too (#767)
            with readonly_lifted(destination) if overwrite else nullcontext():
                success = self._copy_to(destination, overwrite=overwrite)
            if not success:
                return False
            
            # Then delete source
            if self.is_dir():
                # For directories, use recursive delete
                if hasattr(self._impl, 'rmtree'):
                    # S3 has optimized recursive delete
                    self._impl.rmtree()
                else:
                    # Use standard recursive delete
                    if source_scheme == 'file':
                        _rmtree_local(str(self))
                    else:
                        # For other remote schemes, delete recursively
                        self._delete_recursive()
            else:
                # Single file
                self.unlink()
            
            return True
            
        except Exception as e:
            raise OSError(f"Failed to move {self} to {destination}: {e}")
    
    def _delete_recursive(self):
        """Delete directory recursively for remote storage"""
        if self.is_dir():
            # Delete all contents first
            for item in self.iterdir():
                if item.is_dir():
                    item._delete_recursive()
                else:
                    item.unlink()
            # Then delete the directory itself
            self.rmdir()
        else:
            self.unlink()
    
    def _copy_to(self, destination: 'Path', overwrite: bool = False, 
                progress_callback: Optional[callable] = None) -> bool:
        """
        Copy this file or directory to the destination path.
        
        This method handles cross-storage copying (e.g., local to S3, S3 to local).
        
        Args:
            destination: Target path where the file/directory should be copied
            overwrite: Whether to overwrite existing files
            progress_callback: Optional callback for progress tracking (bytes_transferred, total_bytes)
            
        Returns:
            True if copy was successful, False otherwise
            
        Raises:
            FileNotFoundError: If source doesn't exist
            FileExistsError: If destination exists and overwrite=False
            PermissionError: If insufficient permissions
            OSError: For other I/O errors
        """
        if not self.exists():
            raise FileNotFoundError(f"Source path does not exist: {self}")
        
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Destination already exists: {destination}")
        
        # Handle same-storage copying first
        source_scheme = self.scheme
        dest_scheme = destination.scheme
        
        if source_scheme == dest_scheme:
            # Same storage type - use native copy if available
            if hasattr(self._impl, 'copy_to') and hasattr(destination._impl, 'copy_from'):
                return self._impl.copy_to(destination._impl)
            elif source_scheme == 'file':
                # Local to local - use shutil
                import shutil
                if self.is_dir():
                    shutil.copytree(str(self), str(destination), dirs_exist_ok=overwrite)
                else:
                    # Create parent directories for local destination
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(self), str(destination))
                return True
        
        # Cross-storage copying with progress tracking. The callback is guarded
        # so that a caller cancelling from inside it gets their own exception
        # back rather than an OSError describing a "failed" copy.
        guarded = _guard_progress(progress_callback)
        try:
            if self.is_dir():
                return self._copy_directory_cross_storage(destination, overwrite, guarded)
            else:
                return self._copy_file_cross_storage(destination, overwrite, guarded)
        except _CallbackAbort as e:
            raise e.original from None
    
    def _copy_file_cross_storage(self, destination: 'Path', overwrite: bool = False, 
                                 progress_callback: Optional[callable] = None) -> bool:
        """Copy a single file across different storage systems.
        
        Handles transfers between different storage types:
        - Local → Remote (SSH, S3)
        - Remote → Local (SSH, S3)
        - Remote → Remote (SSH, S3)
        
        Args:
            destination: Target path for the copy
            overwrite: Whether to overwrite existing files
            progress_callback: Optional callback for progress tracking (bytes_transferred, total_bytes)
            
        Returns:
            True if copy was successful
            
        Raises:
            OSError: If copy operation fails
        """
        try:
            # Create destination directory if needed (only for local destinations)
            if destination.scheme == 'file':
                destination.parent.mkdir(parents=True, exist_ok=True)
            
            # Get source and destination schemes
            source_scheme = self.scheme
            dest_scheme = destination.scheme
            
            # Handle all cross-storage combinations with progress tracking.
            # A leg between the local disk and S3 or SSH streams — boto3's
            # managed transfer, or the SFTP session a window of chunks at a
            # time — reporting bytes as they move and never holding the whole
            # file in memory, so a copy can run several large files at once
            # (#540). Remote ↔ remote still passes whole ``bytes``.
            if source_scheme == 's3' and dest_scheme == 's3':
                # S3 → S3: copied server-side, so no bytes cross the client
                destination._impl.copy_from_s3(self._impl, progress_callback)

            elif source_scheme == 'file' and dest_scheme in ('s3', 'ssh'):
                # Local → S3 / SSH
                with self.open('rb') as src:
                    destination._impl.upload_from_stream(
                        src, self.stat().st_size, progress_callback)

            elif source_scheme in ('s3', 'ssh') and dest_scheme == 'file':
                # S3 / SSH → Local. The file lands as it arrives, so it lands
                # beside the destination and takes its place only once whole:
                # a failure part way through leaves neither a truncated file
                # that looks like a finished copy nor, when overwriting, a
                # lost original.
                part = destination.parent / f".{destination.name}.xefm-part"
                try:
                    with part.open('wb') as dst:
                        self._impl.download_to_stream(dst, progress_callback)
                    os.replace(str(part), str(destination))
                except BaseException:
                    # BaseException so a cancel (_CallbackAbort) also lands
                    # here and the partial file is still removed
                    try:
                        part.unlink()
                    except OSError:
                        pass
                    raise

            elif source_scheme == 'archive' and dest_scheme == 'file':
                # A member of a browsed archive → local disk. Streamed for the
                # same reason the S3 leg above is: the callback it drives is the
                # byte bar *and* the only place a cross-storage copy can notice a
                # cancel. Reading the member whole reached neither, and held it
                # all in memory besides — which a large file inside a 7z is
                # exactly the case for.
                try:
                    with destination.open('wb') as dst:
                        self._impl.extract_to_stream(dst, progress_callback)
                except BaseException:
                    # BaseException so a cancel (_CallbackAbort) also lands here
                    # and the truncated file is still removed
                    try:
                        destination.unlink()
                    except OSError:
                        pass
                    raise

            elif source_scheme in ('s3', 'ssh') and dest_scheme in ('s3', 'ssh'):
                # Remote → Remote across storage types (S3 ↔ SSH). The SSH side
                # only deals in whole ``bytes``, so the object is buffered here
                # even though the S3 side could stream; each leg reports its own
                # progress in turn.
                if source_scheme == 'ssh':
                    if progress_callback:
                        data = self._impl.read_bytes_with_progress(progress_callback)
                    else:
                        data = self.read_bytes()
                else:
                    buffer = io.BytesIO()
                    self._impl.download_to_stream(buffer, progress_callback)
                    data = buffer.getvalue()

                if dest_scheme == 'ssh':
                    if progress_callback:
                        destination._impl.write_bytes_with_progress(data, progress_callback)
                    else:
                        destination.write_bytes(data)
                else:
                    destination._impl.upload_from_stream(
                        io.BytesIO(data), len(data), progress_callback)
            else:
                # Generic cross-storage copy for any other combinations
                data = self.read_bytes()
                destination.write_bytes(data)
            
            return True
        except _CallbackAbort:
            # The caller cancelled from inside their progress callback; their
            # exception is not a copy failure and must not be relabelled as one
            raise
        except Exception as e:
            raise OSError(f"Failed to copy file from {self} to {destination}: {e}")
    
    def _copy_directory_cross_storage(self, destination: 'Path', overwrite: bool = False,
                                      progress_callback: Optional[callable] = None) -> bool:
        """Copy a directory recursively across different storage systems.
        
        Handles recursive copying of directories and their contents across
        different storage types (local, SSH, S3).
        
        Args:
            destination: Target directory path
            overwrite: Whether to overwrite existing files
            progress_callback: Optional callback for progress tracking (bytes_transferred, total_bytes)
            
        Returns:
            True if copy was successful
            
        Raises:
            OSError: If copy operation fails
        """
        try:
            # Create destination directory
            # For local destinations, use parents=True to create intermediate directories
            # For remote destinations, mkdir should handle directory creation
            if destination.scheme == 'file':
                destination.mkdir(parents=True, exist_ok=overwrite)
            else:
                # For remote destinations (SSH, S3), create directory if it doesn't exist
                if not destination.exists():
                    destination.mkdir(exist_ok=True)
            
            # Copy all contents recursively
            for item in self.iterdir():
                dest_item = destination / item.name
                if item.is_dir():
                    # Recursively copy subdirectories
                    item._copy_directory_cross_storage(dest_item, overwrite, progress_callback)
                else:
                    # Copy individual files with progress tracking
                    item._copy_file_cross_storage(dest_item, overwrite, progress_callback)
            
            return True
        except _CallbackAbort:
            raise
        except Exception as e:
            raise OSError(f"Failed to copy directory from {self} to {destination}: {e}")


# --------------------------------------------------------------------------- #
# What XeFM does with a Path that is not part of Path
# --------------------------------------------------------------------------- #
#
# ``Path`` is what the stable extension API hands out (``EntryInfo.path``,
# ``PaneApi.path``), so every public member it has is a promise. These are
# XeFM's own: they live here, in a module an extension cannot import, rather
# than as methods anyone holding a Path could call. See
# doc/dev/STABLE_API_PLAN.md §2.2.

def copy_to(src: Path, destination: Path, overwrite: bool = False,
            progress_callback: Optional[callable] = None) -> bool:
    """Copy ``src`` (a file or a directory) to ``destination``, across storage
    if need be (local, S3, SSH, archive members, and anything else through
    ``read_bytes``/``write_bytes``). ``progress_callback(done, total)`` gets
    bytes; raising from it cancels, and the caller gets its own exception back.

    This is the transfer underneath file operations, not a file operation: no
    conflict dialog, no queue, no progress pane. Call it from there."""
    return src._copy_to(destination, overwrite, progress_callback)


def move_to(src: Path, destination: Path, overwrite: bool = False) -> bool:
    """Move ``src`` to ``destination``: a rename within one storage, a
    :func:`copy_to` and delete across two. Two directories merge when
    ``overwrite`` is set. The same caveat as :func:`copy_to` applies."""
    return src._move_to(destination, overwrite)


@contextmanager
def readonly_lifted(destination: Path):
    """Let an overwrite of ``destination`` through its read-only attribute,
    as Explorer's Replace does (issue #767): clear the attribute of a local
    read-only file on Windows, and put it back if the overwrite fails. What
    the overwrite leaves has the source's attributes, not the old file's.

    Up front rather than on a refusal, like the removals: the copy that
    overwrites takes one of several routes (``shutil.copy2``, a stream, a
    download moved into place), each opening the file its own way. A
    reparse point is left alone: ``os.chmod`` would reach its target."""
    os_path = str(destination)
    lifted = False
    if sys.platform == 'win32' and destination.scheme == 'file':
        try:
            attrs = os.lstat(os_path).st_file_attributes
            if (attrs & stat.FILE_ATTRIBUTE_READONLY
                    and not attrs & (stat.FILE_ATTRIBUTE_REPARSE_POINT
                                     | stat.FILE_ATTRIBUTE_DIRECTORY)):
                os.chmod(os_path, stat.S_IWRITE)  # on Windows: the read-only bit only
                lifted = True
                logger.debug(f"Cleared the read-only attribute to overwrite: {os_path}")
        except OSError:
            pass
    try:
        yield
    except BaseException:
        if lifted:
            try:
                os.chmod(os_path, stat.S_IREAD)  # the old file stays, so as it was
            except OSError:
                pass
        raise


def listdir_attrs(path) -> List[tuple]:
    """``[(Path, attrs), …]`` for the directory ``path`` — ``iterdir`` plus each
    entry's ``is_dir``/``is_link``/``size``/``alloc``/``mtime`` in one call.
    See :meth:`PathImpl.listdir_attrs`."""
    return path._listdir_attrs()


class Concurrency(NamedTuple):
    """What a storage serves at once, from its declarations
    (``PathImpl.CONCURRENCY`` / ``READ_CONCURRENCY`` / ``WRITE_CONCURRENCY``):
    ``total`` requests, of which up to ``read`` reads and ``write`` writes."""
    total: int
    read: int
    write: int


def concurrency(path) -> Concurrency:
    """How many requests the storage holding ``path`` serves at once.

    The numbers are ceilings for one operation — a copy, a search, a disk-usage
    walk — not shared across operations: each sizes its own pool from them, and
    a request never waits on another operation's. Read and write default to
    the total and never exceed it."""
    return path._concurrency()


def forget_cached_metadata(path) -> None:
    """Make the next ``stat`` of ``path`` ask the storage, not a cache — see
    :meth:`PathImpl.forget_cached_metadata`. Something with no cache to
    forget is left alone."""
    forget = getattr(path, "_forget_cached_metadata", None)
    if forget is not None:
        forget()


# Convenience functions that mirror pathlib module-level functions
def PurePath(*args):
    """Create a PurePath - for now, just return our Path class"""
    return Path(*args)


# For backward compatibility, provide access to the underlying pathlib Path
def as_pathlib_path(path: Path) -> PathlibPath:
    """Convert our Path back to a pathlib.Path if needed"""
    if isinstance(path, Path) and isinstance(path._impl, LocalPathImpl):
        return path._impl._path
    return path