#!/usr/bin/env python3
"""Base classes for storage backends — **the published extension point**.

:class:`~xefm.path.PathImpl` is XeFM's storage interface, and it is not the
class to inherit from. It has 61 methods and 48 of them are abstract, so a
backend that keeps three files in a dictionary still has to write 48 of them;
``test/test_mock_storage_extensibility.py`` used to prove exactly that, in 384
lines. Worse, the class grows: nine methods were added to it between v0.98 and
v1.0.4, and the day a new ``@abstractmethod`` lands, every subclass living
outside this repository raises ``TypeError`` at *import* — which, for a class
defined in ``~/.xefm/config.py``, means the user's whole configuration stops
loading.

The two classes here are the answer to both halves of that.

:class:`UriPathImpl` fills in the 27 methods that are string arithmetic. Every
URI-addressed backend splits the same way — a root that names the container and
a ``/``-separated key inside it:

======== ======================== =================
backend  root                     key
======== ======================== =================
S3       ``s3://bucket/``         ``key/path``
SSH      ``ssh://host/``          ``abs/path``
archive  ``archive://file.zip#``  ``internal/path``
======== ======================== =================

so ``parent`` drops a segment, ``joinpath`` appends one, ``parts`` splits, and
none of that is worth writing four times. A subclass says what its root looks
like, in at most two small hooks, and gets the arithmetic.

:class:`ReadOnlyPathImpl` adds a *policy* rather than more shared code: the
eleven write operations refuse, and the capability declaration says so, so a
backend that only reads never has to spell out eleven ways of saying no.

The split between them is deliberate. ``UriPathImpl`` is not read-only-specific
— ``s3.py`` and ``ssh.py`` carry roughly 290 lines between them implementing
the same 17 arithmetic methods twice, a debt this class can absorb, and could
not if it had also decided that writing raises.

What subclassing costs
----------------------

Five methods and one class attribute::

    class RegistryPathImpl(ReadOnlyPathImpl):
        SCHEME = 'reg'

        def exists(self): ...
        def is_dir(self): ...
        def iterdir(self): ...
        def stat(self): ...
        def open(self, mode='r', buffering=-1, encoding=None,
                 errors=None, newline=None): ...

The compatibility promise
-------------------------

**This module is where a method added to** :class:`~xefm.path.PathImpl`
**gets its default.** That is the whole reason the classes exist; the
ergonomics above are a side effect. A backend written against today's XeFM
keeps importing tomorrow because anything new arrives here already answered,
and ``test/test_published_base.py`` fails the moment an abstract method reaches
:class:`ReadOnlyPathImpl` without one — so the rule does not depend on anyone
remembering it.

The same reasoning is why :class:`~xefm.path.PathImpl` stays a strict ABC and
is *not* de-abstracted in place: a backend inside this repository that forgets
a method should still fail at import. Strictness for the internal interface,
defaults for the published one.

Preview status
--------------

This surface is covered by ``xefm.user_api.API_VERSION`` — ``0``, meaning it
may change until it reaches ``1``.
"""

import errno
import fnmatch
import stat as stat_module
from abc import abstractmethod
from pathlib import PurePosixPath
from typing import Iterator, List, Optional

from xefm.path import Path, PathImpl


class UriStatResult:
    """An ``os.stat_result`` stand-in built from the three facts a listing
    actually needs.

    Every backend here hand-rolls one of these — ``S3StatResult``, a local
    class inside ``SSHPathImpl.stat``, ``ArchiveEntry.to_stat_result``. A
    virtual folder should not have to::

        def stat(self):
            return UriStatResult(size=0, mtime=0.0, is_dir=True)

    The fields beyond ``st_size`` / ``st_mtime`` / ``st_mode`` are filled with
    zeroes, which is what the three existing ones do too: nothing displays a
    uid or an inode for a path that has neither.
    """

    __slots__ = ('st_size', 'st_mtime', 'st_mode', 'st_atime', 'st_ctime',
                 'st_uid', 'st_gid', 'st_ino', 'st_dev', 'st_nlink')

    def __init__(self, size: int = 0, mtime: float = 0.0, is_dir: bool = False,
                 mode: Optional[int] = None):
        self.st_size = 0 if is_dir else size
        self.st_mtime = mtime
        self.st_mode = mode if mode is not None else (
            stat_module.S_IFDIR | 0o755 if is_dir else stat_module.S_IFREG | 0o644)
        self.st_atime = mtime
        self.st_ctime = mtime
        self.st_uid = 0
        self.st_gid = 0
        self.st_ino = 0
        self.st_dev = 0
        self.st_nlink = 1

    def __repr__(self) -> str:
        kind = 'dir' if stat_module.S_ISDIR(self.st_mode) else 'file'
        return f'UriStatResult({kind}, size={self.st_size}, mtime={self.st_mtime})'


def _normalize_key(key: str) -> str:
    """Put a key in the one form the arithmetic below assumes: segments joined
    by ``/``, with no leading or trailing slash, no empty segments and no
    ``.``. ``..`` is left alone, exactly as ``pathlib`` leaves it alone outside
    ``resolve()``."""
    return '/'.join(seg for seg in key.split('/') if seg and seg != '.')


class UriPathImpl(PathImpl):
    """A ``PathImpl`` for any backend addressed by ``scheme://…``, with the
    string arithmetic already written.

    The model is one invariant::

        str(self) == self._root_prefix() + self._key

    where ``_key`` is ``/``-separated with no leading or trailing slash, and
    the root of the backend is the path whose key is empty. Everything else
    here follows from that: ``parent`` drops the last segment, ``joinpath``
    appends, ``parts`` splits, ``name`` is the last one.

    A subclass overrides at most two hooks:

    ``_parse(uri)``
        Pull apart a URI of this scheme, store whatever names the root — a
        bucket, a host, an archive file — on ``self``, and return the key. The
        default accepts ``{SCHEME}://<key>``, which is all a virtual folder
        with no container needs.

    ``_root_prefix()``
        The string a key is appended to, ``'s3://bucket/'`` or
        ``'archive://file.zip#'``. The default is ``'{SCHEME}://'``.

    and then implements what only it can: ``exists``, ``is_dir``, ``iterdir``,
    ``stat``, ``open``, and — unless it inherits :class:`ReadOnlyPathImpl` —
    the write operations.

    Behaviour at the root is the third difference between backends, and it is
    left as an override rather than a hook, because it is genuinely different
    rather than differently spelled: ``parent`` here returns the root itself,
    the way ``pathlib`` makes ``/`` its own parent, but an archive's root has a
    parent that is *outside* the archive.
    """

    #: A URI names a location, not a position relative to one, so this is
    #: always true here.
    IS_REMOTE = True

    def __init__(self, uri: str):
        self._key = _normalize_key(self._parse(str(uri)))

    # -- the two hooks ----------------------------------------------------- #

    def _parse(self, uri: str) -> str:
        """Split ``uri`` and return the key part.

        Called from ``__init__`` before anything else, so this is also where a
        subclass stores whatever its :meth:`_root_prefix` needs. The default
        handles ``{SCHEME}://<key>``.
        """
        prefix = f'{self.SCHEME}://'
        if not uri.startswith(prefix):
            raise ValueError(f'not a {prefix} URI: {uri!r}')
        return uri[len(prefix):]

    def _root_prefix(self) -> str:
        """The string a key is appended to — see the class docstring's
        invariant. The default is ``'{SCHEME}://'``."""
        return f'{self.SCHEME}://'

    # -- building siblings ------------------------------------------------- #

    def _at(self, key: str) -> Path:
        """The ``Path`` for ``key`` under this same root, as this same class.

        Not ``Path(uri)``: that would ask the scheme factory which class to
        build, so a backend the factory has never heard of would find its own
        ``parent`` coming back as a local path. Re-parsing its own URI is the
        registry contract — URI string in, ``PathImpl`` out — applied to
        itself.
        """
        return Path._from_impl(type(self)(self._root_prefix() + _normalize_key(key)))

    def _child(self, name: str) -> Path:
        """The ``Path`` for one entry of this directory — what an
        :meth:`iterdir` implementation yields."""
        return self._at(f'{self._key}/{name}' if self._key else name)

    @property
    def _segments(self) -> List[str]:
        return self._key.split('/') if self._key else []

    # -- identity ---------------------------------------------------------- #

    def __str__(self) -> str:
        return self._root_prefix() + self._key

    def __repr__(self) -> str:
        return f'{type(self).__name__}({str(self)!r})'

    def __eq__(self, other) -> bool:
        return str(self) == str(other)

    def __hash__(self) -> int:
        return hash(str(self))

    def __lt__(self, other) -> bool:
        return str(self) < str(other)

    # -- name components --------------------------------------------------- #

    @property
    def name(self) -> str:
        segments = self._segments
        return segments[-1] if segments else ''

    @property
    def stem(self) -> str:
        return PurePosixPath(self.name).stem if self.name else ''

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.name).suffix if self.name else ''

    @property
    def suffixes(self) -> List[str]:
        return list(PurePosixPath(self.name).suffixes) if self.name else []

    @property
    def parts(self) -> tuple:
        return (self._root_prefix(),) + tuple(self._segments)

    @property
    def anchor(self) -> str:
        return self._root_prefix()

    # -- walking ----------------------------------------------------------- #

    @property
    def parent(self) -> Path:
        """The parent, with the root as its own parent.

        A backend whose root has a parent somewhere else overrides this — an
        archive's does, because the parent of ``archive://f.zip#`` is the
        directory holding ``f.zip``.
        """
        segments = self._segments
        if not segments:
            return self._at('')
        return self._at('/'.join(segments[:-1]))

    @property
    def parents(self) -> List[Path]:
        """Every ancestor, nearest first, stopping at the root.

        The walk compares each step against the one before rather than against
        the starting path: a root that is its own parent would otherwise never
        match again once the walk left it, and the loop would not end.
        """
        ancestors = []
        current = self.parent
        while str(current) != str(self):
            ancestors.append(current)
            nxt = current.parent
            if str(nxt) == str(current):
                break
            current = nxt
        return ancestors

    def joinpath(self, *args) -> Path:
        key = self._key
        for arg in args:
            key = f"{key}/{str(arg)}" if key else str(arg)
        return self._at(key)

    def with_name(self, name: str) -> Path:
        if not self._segments:
            raise ValueError(f'{self} has an empty name')
        return self._at('/'.join(self._segments[:-1] + [name]))

    def with_stem(self, stem: str) -> Path:
        return self.with_name(stem + self.suffix)

    def with_suffix(self, suffix: str) -> Path:
        return self.with_name(self.stem + suffix)

    def relative_to(self, other) -> Path:
        other_str, self_str = str(other), str(self)
        if not self_str.startswith(other_str):
            raise ValueError(f'{self_str!r} is not relative to {other_str!r}')
        relative = self_str[len(other_str):].lstrip('/')
        return Path(relative) if relative else Path('.')

    # -- absoluteness ------------------------------------------------------ #

    def is_absolute(self) -> bool:
        """A URI names one location outright, so always."""
        return True

    def absolute(self) -> Path:
        return self._at(self._key)

    def resolve(self, strict: bool = False) -> Path:
        """No symlink resolution: a backend that has symlinks and can follow
        them overrides this."""
        return self._at(self._key)

    def expanduser(self) -> Path:
        """``~`` has no meaning in a URI, so this is a no-op."""
        return self._at(self._key)

    # -- what the backend still has to answer ------------------------------ #

    @abstractmethod
    def exists(self) -> bool:
        """Whether this path names something."""

    @abstractmethod
    def is_dir(self) -> bool:
        """Whether this path names something that can be listed."""

    @abstractmethod
    def iterdir(self) -> Iterator[Path]:
        """Yield this directory's entries — ``self._child(name)`` for each."""

    @abstractmethod
    def stat(self):
        """Size, mtime and mode — :class:`UriStatResult` builds one."""

    @abstractmethod
    def open(self, mode='r', buffering=-1, encoding=None, errors=None,
             newline=None):
        """Open this path's content as a file object."""

    # -- derived from those ------------------------------------------------ #

    def is_file(self) -> bool:
        return self.exists() and not self.is_dir()

    def is_symlink(self) -> bool:
        """False unless a backend says otherwise; most virtual folders have no
        such notion, and a broken symlink is the only case where the answer
        matters to a listing."""
        return False

    def lstat(self):
        """Without symlinks there is nothing for ``lstat`` to do differently."""
        return self.stat()

    def read_bytes(self) -> bytes:
        with self.open('rb') as f:
            return f.read()

    def read_text(self, encoding=None, errors=None) -> str:
        with self.open('r', encoding=encoding, errors=errors) as f:
            return f.read()

    def write_bytes(self, data: bytes) -> int:
        with self.open('wb') as f:
            return f.write(data)

    def write_text(self, data: str, encoding=None, errors=None,
                   newline=None) -> int:
        with self.open('w', encoding=encoding, errors=errors,
                       newline=newline) as f:
            return f.write(data)

    # -- matching ---------------------------------------------------------- #

    def match(self, pattern: str) -> bool:
        return PurePosixPath('/' + self._key).match(pattern)

    def glob(self, pattern: str) -> Iterator[Path]:
        """Entries of this directory whose name matches ``pattern``."""
        if not self.is_dir():
            return
        for entry in self.iterdir():
            if fnmatch.fnmatch(entry.name, pattern):
                yield entry

    def rglob(self, pattern: str) -> Iterator[Path]:
        """The same, through every directory below this one."""
        if not self.is_dir():
            return
        for entry in self.iterdir():
            if fnmatch.fnmatch(entry.name, pattern):
                yield entry
            if entry.is_dir():
                yield from entry.rglob(pattern)

    # -- odds and ends ----------------------------------------------------- #

    def as_uri(self) -> str:
        return str(self)

    def as_posix(self) -> str:
        """Already ``/``-separated, being a URI."""
        return str(self)

    def samefile(self, other_path) -> bool:
        return str(self) == str(other_path)


class ReadOnlyPathImpl(UriPathImpl):
    """A :class:`UriPathImpl` that refuses every write.

    Not shared code but shared *policy*: eleven operations that all have to say
    no, and a capability declaration that says it in advance so a caller can
    ask before it tries. A backend that browses something — a registry, a
    process list, a remote catalogue — inherits this and implements the five
    methods :class:`UriPathImpl` leaves abstract.

    Refusals are ``OSError`` with ``errno.EROFS``, which is what a read-only
    filesystem raises and what XeFM's file operations already know how to
    report. Set :attr:`READ_ONLY_MESSAGE` to say why in the backend's own
    words.
    """

    #: Conservative by default: no write capability, nothing streams, content
    #: has to be fetched before it is read and the fetch is worth keeping. A
    #: subclass that can do better declares its own set.
    CAPABILITIES = frozenset({'extraction_for_reading', 'cache_for_search'})
    SEARCH_STRATEGY = 'buffered'

    #: What the refusal says. ``None`` builds ``'reg:// paths are read-only'``
    #: from :attr:`~xefm.path.PathImpl.SCHEME`.
    READ_ONLY_MESSAGE: Optional[str] = None

    def _refuse(self):
        message = self.READ_ONLY_MESSAGE or f'{self.SCHEME}:// paths are read-only'
        raise OSError(errno.EROFS, message, str(self))

    def write_bytes(self, data: bytes) -> int:
        self._refuse()

    def write_text(self, data: str, encoding=None, errors=None,
                   newline=None) -> int:
        self._refuse()

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        self._refuse()

    def rmdir(self):
        self._refuse()

    def unlink(self, missing_ok=False):
        self._refuse()

    def rename(self, target) -> Path:
        self._refuse()

    def replace(self, target) -> Path:
        self._refuse()

    def symlink_to(self, target, target_is_directory=False):
        self._refuse()

    def hardlink_to(self, target):
        self._refuse()

    def touch(self, mode=0o666, exist_ok=True):
        self._refuse()

    def chmod(self, mode):
        self._refuse()
