"""xefm.archive_progress — byte-level progress for archive create / extract.

The task framework's progress dialog carries two bars: items done out of the
total, and — for the item being worked on — bytes done out of its size. Archive
operations count members easily enough, but a single large member (a VM image, a
video) leaves the item bar sitting still for minutes with nothing else to look
at. That second bar is what this module feeds.

The problem is that the payload copy is buried inside ``zipfile`` / ``tarfile``:
``zf.write()``, ``extractall()``, ``tf.add()`` are each one opaque call. Rewriting
those loops here would mean re-deriving each member's metadata by hand and, on
the extract side, re-deriving their safety checks — zipfile's path sanitization
(drive letters, ``..`` components) and tarfile's sparse-file and deferred
directory-permission handling. That trade is not worth a progress bar.

So instead each subclass below overrides the **one method the payload actually
flows through** and wraps the file object it hands back or takes in. The stdlib
loop, and every check inside it, runs exactly as it always did; only the bytes
are counted on their way past:

======================  =====================================  ================
Operation               Seam                                   Counts
======================  =====================================  ================
zip create              ``ZipFile.open(zinfo, 'w')``           writes
zip extract             ``ZipFile.open(member)``               reads
tar create              ``TarFile.addfile(tarinfo, fileobj)``  reads
tar extract             ``TarFile.makefile`` (via ``fileobj``) reads
======================  =====================================  ================

All four are attribute lookups on ``self``, so the override is what the stdlib
calls. With no :class:`ByteProgress` attached every subclass is a pure
passthrough, byte for byte identical to its base.

Formats read through libarchive (:mod:`xefm.archive_libarchive`) need none of
this. There is no opaque stdlib call to work around there: XeFM writes each
block itself in both directions, so it reports them directly and only
:class:`ByteProgress` is shared. The subclasses below exist because of
``zipfile`` and ``tarfile``, not because of the progress model.
"""

from __future__ import annotations

import tarfile
import zipfile
from typing import Any, Callable, Optional


class ByteProgress:
    """The current member's byte accounting, reported into a ``ProgressManager``.

    :meth:`start` opens a member — call it *after* the item's
    ``update_progress``, which resets the byte fields — and :meth:`advance` is
    fed by the counting proxies as data goes past.

    Reports are rate-limited by volume rather than by time: at most ~200 per
    member (and never more often than every 64 KiB), which is finer than any
    frame rate can show and keeps an 8 KiB-chunked gigabyte from costing a
    hundred thousand lock acquisitions. The final byte of a member always
    reports, so the bar lands on full rather than near it."""

    #: Never report more often than this, however small the member.
    _MIN_STEP = 64 * 1024
    #: Aim for at most this many reports across one member.
    _TARGET_REPORTS = 200

    def __init__(self, prog: Any = None):
        self.prog = prog
        self._total = 0
        self._done = 0
        self._reported = 0
        self._step = self._MIN_STEP

    def start(self, size: Optional[int]) -> None:
        """Begin a member of ``size`` bytes (0 / None for one with no payload —
        a directory, a symlink — which shows no byte bar at all)."""
        try:
            total = int(size or 0)
        except (TypeError, ValueError):
            total = 0
        self._total = max(0, total)
        self._done = 0
        self._reported = 0
        self._step = max(self._MIN_STEP, self._total // self._TARGET_REPORTS)
        if self.prog is not None and self._total:
            self.prog.update_file_byte_progress(0, self._total)

    def advance(self, count: int) -> None:
        if self.prog is None or not self._total or count <= 0:
            return
        self._done = min(self._done + count, self._total)
        if self._done - self._reported < self._step and self._done < self._total:
            return
        self._reported = self._done
        self.prog.update_file_byte_progress(self._done, self._total)


class _CountingFile:
    """Binary file proxy that reports the size of every read and write.

    Everything else — ``seek``, ``tell``, ``close``, ``flush`` — delegates, and
    the context-manager protocol is forwarded explicitly (``__enter__`` /
    ``__exit__`` are looked up on the type, so ``__getattr__`` would not see
    them). Reads are passed through whole: ``tarfile.copyfileobj`` treats a short
    read as a truncated archive, so this must never split one."""

    __slots__ = ("_raw", "_report")

    def __init__(self, raw: Any, report: Callable[[int], None]):
        self._raw = raw
        self._report = report

    def read(self, *args, **kwargs):
        data = self._raw.read(*args, **kwargs)
        if data:
            self._report(len(data))
        return data

    def write(self, data, *args, **kwargs):
        written = self._raw.write(data, *args, **kwargs)
        self._report(len(data))
        return written

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def __enter__(self):
        self._raw.__enter__()
        return self

    def __exit__(self, *exc):
        return self._raw.__exit__(*exc)

    def __iter__(self):
        return iter(self._raw)


class ProgressZipFile(zipfile.ZipFile):
    """A ``ZipFile`` that counts the bytes of every member it reads or writes.

    Both directions flow through ``self.open``: ``write()`` copies the source
    into ``self.open(zinfo, 'w')``, and ``_extract_member`` copies out of
    ``self.open(member, pwd=…)`` — after it has sanitized the member's path,
    which is exactly why extraction still goes through it."""

    #: Assigned by the caller after construction; None disables counting.
    byte_progress: Optional[ByteProgress] = None

    def open(self, *args, **kwargs):
        handle = super().open(*args, **kwargs)
        if self.byte_progress is None:
            return handle
        return _CountingFile(handle, self.byte_progress.advance)


class ProgressTarFile(tarfile.TarFile):
    """A ``TarFile`` that counts the bytes of every member it reads or writes.

    Creation: ``add()`` hands the opened source to ``self.addfile``, so wrapping
    that argument counts the member as it is compressed — while ``add`` keeps its
    own recursion, its refusal to archive the archive it is writing, and its
    symlink / device handling.

    Extraction: ``makefile`` copies out of ``self.fileobj``, so the proxy goes
    there for the duration of the call and comes straight back off. Delegating
    to ``super()`` rather than reimplementing the copy keeps sparse-file support;
    on a compressed tar the bytes counted are post-decompression, which is what
    the member's size is measured in."""

    byte_progress: Optional[ByteProgress] = None

    def addfile(self, tarinfo, fileobj=None, *args, **kwargs):
        if fileobj is not None and self.byte_progress is not None:
            fileobj = _CountingFile(fileobj, self.byte_progress.advance)
        return super().addfile(tarinfo, fileobj, *args, **kwargs)

    def makefile(self, tarinfo, *args, **kwargs):
        if self.byte_progress is None:
            return super().makefile(tarinfo, *args, **kwargs)
        real = self.fileobj
        self.fileobj = _CountingFile(real, self.byte_progress.advance)
        try:
            return super().makefile(tarinfo, *args, **kwargs)
        finally:
            self.fileobj = real
