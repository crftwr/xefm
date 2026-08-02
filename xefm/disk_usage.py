"""Recursive disk-usage totals for the file-details dialog.

A :class:`UsageScan` walks one or more directories on a daemon worker thread,
keeping running totals (bytes, file count, folder count) that the UI thread
reads while it repaints an already-open dialog — so the dialog appears
instantly and the numbers climb as the walk proceeds.

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


class RootTotals:
    """Running totals for one scanned root.

    Single writer (the scan thread) / single reader (the UI thread) on plain
    int attributes: a torn read at worst shows a momentarily stale number that
    the next repaint corrects, so no lock is needed.
    """

    __slots__ = ("bytes", "files", "dirs", "errors", "done")

    def __init__(self):
        self.bytes = 0    #: sum of file sizes under the root
        self.files = 0    #: non-directory entries (symlinks count here, unfollowed)
        self.dirs = 0     #: directories under the root (the root itself excluded)
        self.errors = 0   #: directories that could not be listed
        self.done = False


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
