"""Recursive disk-usage totals for the file-details dialog.

A :class:`UsageScan` walks one or more directories on a daemon worker thread,
keeping running totals (bytes, bytes on disk, file count, folder count) that
the UI thread reads while it repaints an already-open dialog — so the dialog
appears instantly and the numbers climb as the walk proceeds.

The two byte totals are Finder's "Size" and "on disk": how long the files are,
and how much of the volume they occupy. One sparse file separates them by three
orders of magnitude (issue #275), so the walk keeps both rather than letting
one label stand for whichever the backend happened to report. Where a backend
cannot report an allocation — SSH, S3, an archive, any Windows path — the walk
says so instead of summing zeros; see :func:`reports_allocation`.

The walk is storage-agnostic: it descends via ``Path.listdir_attrs()``, one
bulk call per directory (a bulk syscall locally, a single request over SSH),
so no per-entry ``stat`` round trips happen on any backend.

Symlinks are counted where they stand and never followed: following a link can
revisit the same tree (a cycle) or pull in content outside the directory the
user asked about, either of which makes the total wrong rather than just slow.
"""

from __future__ import annotations

import threading
from typing import Sequence

from xefm.log_manager import getLogger
from xefm import dir_scan

logger = getLogger("DiskUsage")


def reports_allocation(path) -> bool:
    """Whether ``path``'s backend can say how much space an entry occupies on
    disk, as opposed to how many bytes long it is.

    Asked once per root, before the dialog is built, because it decides whether
    the "On disk" row exists at all — and that has to be settled up front: the
    live rows are swapped into an open document whose shape must not change
    between updates, or the restored scroll offset points somewhere else.

    The question is put to the backend in the same terms the walk uses per
    entry — can a ``stat`` here produce an allocation — so the row appears
    exactly where the totals behind it will be real. A local directory answers
    yes on macOS and Linux (its own allocation is 0, which is still an answer)
    and no on Windows, where ``stat_result`` has no such field; SSH, S3 and
    archive paths answer no because the objects they build have none either."""
    try:
        return dir_scan.alloc_from_stat(path.stat()) is not None
    except Exception as e:
        logger.error(f"Could not probe on-disk size support for {path}: {e}")
        return False


class RootTotals:
    """Running totals for one scanned root.

    Single writer (the scan thread) / single reader (the UI thread) on plain
    int attributes: a torn read at worst shows a momentarily stale number that
    the next repaint corrects, so no lock is needed.
    """

    __slots__ = ("bytes", "alloc", "alloc_unknown", "files", "dirs", "errors",
                 "done")

    def __init__(self):
        self.bytes = 0          #: sum of file sizes under the root
        self.alloc = 0          #: sum of the disk space those files occupy
        self.alloc_unknown = 0  #: files whose occupied space went unreported
        self.files = 0    #: non-directory entries (symlinks count here, unfollowed)
        self.dirs = 0     #: directories under the root (the root itself excluded)
        self.errors = 0   #: directories that could not be listed
        self.done = False

    @property
    def on_disk(self):
        """Allocated bytes under this root, or None once any entry's
        allocation went unreported — a sum missing some of its terms would read
        as a smaller directory rather than as an unmeasured one."""
        return None if self.alloc_unknown else self.alloc


class UsageScan:
    """Walk ``roots`` recursively, accumulating per-root and grand totals.

    Construct with the directory ``Path`` objects to measure, then either
    :meth:`start` the daemon worker (the UI polls the counters) or call
    :meth:`run_sync` on the current thread (tests). With no roots the scan is
    born ``done``, so callers need not special-case an all-files selection.
    """

    def __init__(self, roots: Sequence) -> None:
        self.logger = getLogger("DiskUsage")
        self.roots = list(roots)
        self.totals = {str(root): RootTotals() for root in self.roots}
        self.done = not self.roots
        self._cancel = threading.Event()

    # --- control --------------------------------------------------------------

    def start(self) -> None:
        """Run the walk on a daemon thread; counters update as it goes."""
        self.logger.info(f"Scanning disk usage of {len(self.roots)} directories")
        threading.Thread(target=self._run, name="xefm-disk-usage",
                         daemon=True).start()

    def cancel(self) -> None:
        """Stop the walk at the next entry; safe from any thread, idempotent."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # --- reading --------------------------------------------------------------

    def grand_totals(self) -> tuple[int, int, int, int]:
        """``(bytes, files, dirs, errors)`` summed over every root."""
        b = f = d = e = 0
        for t in self.totals.values():
            b += t.bytes
            f += t.files
            d += t.dirs
            e += t.errors
        return b, f, d, e

    def grand_alloc(self):
        """Allocated bytes summed over every root, or None when any root's is
        unknown — :attr:`RootTotals.on_disk` over the whole selection."""
        total = 0
        for t in self.totals.values():
            if t.alloc_unknown:
                return None
            total += t.alloc
        return total

    # --- the walk -------------------------------------------------------------

    def _run(self) -> None:
        try:
            self.run_sync()
        except Exception as e:
            # _walk absorbs per-directory failures, so reaching here is a bug —
            # record it and mark the scan done so the dialog stops saying
            # "scanning" forever.
            self.logger.error(f"Disk usage scan failed: {e}")
            self.done = True

    def run_sync(self) -> None:
        """Walk every root on the calling thread (the worker; tests call this
        directly for a deterministic scan)."""
        for root in self.roots:
            if self._cancel.is_set():
                break
            totals = self.totals[str(root)]
            self._walk(root, totals)
            totals.done = not self._cancel.is_set()
        self.done = True

    def _walk(self, root, totals: RootTotals) -> None:
        stack = [root]
        while stack:
            if self._cancel.is_set():
                return
            directory = stack.pop()
            try:
                entries = directory.listdir_attrs()
            except Exception:
                totals.errors += 1
                continue
            for child, attrs in entries:
                if self._cancel.is_set():
                    return
                # A symlinked directory is counted as an entry but never
                # descended into; a broken entry arrives as a size-0 file.
                if attrs["is_dir"] and not attrs["is_link"]:
                    totals.dirs += 1
                    stack.append(child)
                else:
                    totals.files += 1
                    totals.bytes += attrs["size"]
                    # .get, not [], because a backend outside this repository
                    # (xefm.path_base is a published extension point) may
                    # predate the key entirely — which is exactly the "cannot
                    # say" case None already means.
                    alloc = attrs.get("alloc")
                    if alloc is None:
                        totals.alloc_unknown += 1
                    else:
                        totals.alloc += alloc
