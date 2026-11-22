"""Walking a directory tree, listing several directories at once where the
storage rewards it.

A walk costs one listing per directory. On a local disk that is a syscall and
the walk is bound by the disk; on a remote one each listing is round trips, and
a walk that waits for one directory before asking for the next is bound by
latency times the number of directories — a deep tree over SFTP spent nearly
all its time waiting. :func:`walk` keeps up to the storage's read concurrency
in flight instead (:func:`xefm.path.concurrency`), which an SFTP session serves
side by side.

Only a remote storage gets that. Overlapping listings hides round trips, and a
local listing has none to hide: the same 9,800-entry tree walked in 0.13 s one
directory at a time and 0.42 s four at once, the pool costing more than the
listings. Local walks stay the plain depth-first walk they always were.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import FIRST_COMPLETED, wait
from typing import Callable, Iterator, Optional, Tuple

from xefm.path import attrs_via_path, concurrency, listdir_attrs
from xefm.worker_pool import DaemonPool

#: How often a parallel walk waiting on listings looks at its cancel flag.
_CANCEL_POLL = 0.1


def parallel_reads(path) -> int:
    """How many reads at once pay off under ``path``: the storage's read
    concurrency where it is remote, 1 where it is not (see the module note)."""
    try:
        if not path.is_remote():
            return 1
        return concurrency(path).read
    except Exception:  # a stand-in or a broken backend: walk the safe way
        return 1


def walk(root, cancel, descend: Callable[[object, dict], bool], *,
         pool: Optional[DaemonPool] = None,
         on_error: Optional[Callable[[object, Exception], None]] = None
         ) -> Iterator[Tuple[object, dict]]:
    """Yield ``(entry, attrs)`` for every entry under ``root``
    (:func:`xefm.path.listdir_attrs` records), descending into each entry for which
    ``descend(entry, attrs)`` is true. A directory that cannot be listed is
    skipped, after ``on_error(directory, exception)`` when given. Stops as soon
    as ``cancel`` (a ``threading.Event``) is set, and when the consumer stops
    iterating.

    ``pool`` is the operation's own pool, for an operation that also reads
    files through it (a content search): the listings then share its workers
    with those reads, so the operation as a whole stays within the storage's
    ceiling. Without one the walk makes its own, sized by
    :func:`parallel_reads`. A walk given a pool always uses it.

    Either way the pool's threads are daemons (:mod:`xefm.worker_pool`), so
    quitting during a walk does not wait for its listings, and the walk keeps
    no more listings queued than the pool has workers — the directories it
    has yet to list wait here, not in the pool, where a file read the same
    search asks for would queue behind them.

    Order: each directory's entries come together and in its listing order.
    With one listing at a time the walk is depth-first; with several, a
    directory's entries come when its listing does, so the order across
    directories follows the storage, not the tree."""
    if pool is not None:
        yield from _walk_parallel(root, cancel, descend, pool, on_error)
        return
    workers = parallel_reads(root)
    if workers <= 1:
        yield from _walk_sequential(root, cancel, descend, on_error)
        return
    own = DaemonPool(workers, name="xefm-walk")
    try:
        yield from _walk_parallel(root, cancel, descend, own, on_error)
    finally:
        # Listings not started are dropped; ones running finish on their own
        # and are discarded.
        own.shutdown(wait=False, cancel_futures=True)


def walk_root(root, cancel, descend: Callable[[object, dict], bool], *,
              pool: Optional[DaemonPool] = None,
              on_error: Optional[Callable[[object, Exception], None]] = None
              ) -> Iterator[Tuple[object, dict]]:
    """:func:`walk`, for a root someone named on purpose (the public API,
    ``xefmctl``, #962): a folder is walked, and a file is itself the one
    entry, its record marked ``explicit`` so a search looks at it even where
    it would skip it in a walk (a hidden file). A root that is not there
    yields nothing, as :func:`walk` does. Costs one ``stat`` of the root, which
    is why the search dialogs, whose root is always the pane's folder, keep
    :func:`walk`."""
    attrs = attrs_via_path(root)
    if not attrs.get("ok"):
        return
    if attrs.get("is_dir"):
        yield from walk(root, cancel, descend, pool=pool, on_error=on_error)
        return
    if not cancel.is_set():
        yield root, dict(attrs, explicit=True)


def _walk_sequential(root, cancel, descend, on_error=None):
    stack = [root]
    while stack:
        if cancel.is_set():
            return
        directory = stack.pop()
        try:
            entries = listdir_attrs(directory)
        except Exception as e:
            if on_error is not None:
                on_error(directory, e)
            continue
        for entry, attrs in entries:
            if cancel.is_set():
                return
            if descend(entry, attrs):
                stack.append(entry)
            yield entry, attrs


def _walk_parallel(root, cancel, descend, pool, on_error=None):
    """As many listings in flight as ``pool`` has workers. A directory is
    lined up the moment its parent's listing names it — before its siblings
    are handed to the consumer — and sent to the pool as soon as a listing
    ends, so the listings keep running while the consumer works."""
    waiting = deque([root])
    pending: dict = {}

    def top_up() -> None:
        while waiting and len(pending) < pool.size:
            directory = waiting.popleft()
            pending[pool.submit(listdir_attrs, directory)] = directory

    top_up()
    try:
        while pending:
            done, _ = wait(pending, timeout=_CANCEL_POLL, return_when=FIRST_COMPLETED)
            if cancel.is_set():
                return
            for future in done:
                directory = pending.pop(future)
                try:
                    entries = future.result()
                except Exception as e:
                    if on_error is not None:
                        on_error(directory, e)
                    top_up()
                    continue
                waiting.extend(entry for entry, attrs in entries
                               if descend(entry, attrs))
                top_up()
                for item in entries:
                    if cancel.is_set():
                        return
                    yield item
    finally:
        # A shared pool outlives the walk, so drop what the walk queued.
        for future in pending:
            future.cancel()
