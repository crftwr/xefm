"""Compare & Select — the storage-agnostic engine behind the ``compare_selection``
action (the ``W`` key).

Each entry in the active pane is joined to the same-named, same-type (file-vs-dir)
entry in the other pane, after NFC-normalizing names. An entry is selected when
every *enabled* attribute relation holds; entries with no counterpart are selected
only when ``include_missing`` is set. This module is pure and headless — the dialog
(``xefm.compare_dialog``) builds a :class:`CompareCriteria`, and the app folds the
returned path set into ``pane['selected_files']``.

Both feeds are just iterables of path-like entries, so either side may be a
**virtual (search-results) listing** as well as a directory listing. A result set
spans directories, so the other side can hold several entries sharing a basename:
they are all kept as candidates and an entry matches when **any** candidate
satisfies the relations (order-independent — a directory listing has unique names,
so this is a no-op there).

The relations subsume the legacy three-way menu and add direction:

- ``size``    — ``any`` / ``equal`` / ``differs``   (ignored for directories)
- ``mtime``   — ``any`` / ``same`` / ``newer`` / ``older``   (relative to other pane)
- ``content`` — ``any`` / ``equal`` / ``differs``   (byte compare; ignored for dirs)

``stat``-only comparisons (size / mtime) are cheap and are called only on
name-matched pairs. A content comparison reads both files, so callers route it
through the task worker; a size mismatch short-circuits it (files are only read
when their sizes already match). The optional ``checkpoint`` callable is invoked
between entries and between chunks so a worker can raise to cancel.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

# Filesystems round mtimes (FAT ≈ 2s, some networks ≈ 1s); treat timestamps
# within this many seconds as identical.
MTIME_TOLERANCE = 1.0

# Read size for the streaming byte compare (only reached when sizes already match).
_CHUNK = 1 << 16


def _norm(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def _noop() -> None:
    pass


@dataclass(frozen=True)
class CompareCriteria:
    """What to compare, built by the dialog. Each attribute names the relation the
    other pane's counterpart must satisfy; ``"any"`` disables that attribute."""

    size: str = "any"        # any | equal | differs
    mtime: str = "any"       # any | same | newer | older  (current vs other pane)
    content: str = "any"     # any | equal | differs
    include_missing: bool = False  # also select entries with no counterpart
    mode: str = "replace"    # replace | add  (how the app folds it in; engine ignores)

    @property
    def needs_content(self) -> bool:
        """True when a content relation is set — the (file-reading) path the app
        runs on the task worker rather than inline."""
        return self.content != "any"


@dataclass
class CompareResult:
    """The selection to apply, with a file/dir breakdown for the summary log."""

    paths: set = field(default_factory=set)  # set[str] of str(path)
    files: int = 0
    dirs: int = 0

    @property
    def total(self) -> int:
        return len(self.paths)


def compute_compare_selection(
    current_files: Iterable,
    other_files: Iterable,
    criteria: CompareCriteria,
    *,
    checkpoint: Callable[[], None] = _noop,
    on_advance: Optional[Callable[[Any], None]] = None,
) -> CompareResult:
    """Select entries in ``current_files`` by comparing each with its counterpart
    in ``other_files`` under ``criteria``. Returns a :class:`CompareResult`.

    ``current_files`` / ``other_files`` are ``xefm.path.Path``-like entries — a
    directory listing or a virtual (search-results) set, either side. Names are
    NFC-normalized and joined with type (file vs dir), so a file never matches a
    same-named directory. When the other side holds several entries with the same
    name (only possible for a result set spanning directories), the entry is
    selected if **any** of them satisfies the relations. Entries whose ``stat``
    fails are skipped.

    ``checkpoint`` is called between entries and between content chunks (a worker
    raises from it to cancel); ``on_advance(entry)`` is called once per current
    entry, before it is compared, for progress reporting."""
    other_by_key: dict[tuple[str, bool], list] = {}
    for p in other_files:
        try:
            other_by_key.setdefault((_norm(p.name), p.is_dir()), []).append(p)
        except OSError:
            continue

    result = CompareResult()
    for cur in current_files:
        checkpoint()
        if on_advance is not None:
            on_advance(cur)
        try:
            cur_is_dir = cur.is_dir()
        except OSError:
            continue

        candidates = other_by_key.get((_norm(cur.name), cur_is_dir))
        if not candidates:
            if criteria.include_missing:
                _add(result, cur, cur_is_dir)
            continue

        for other in candidates:
            try:
                if _matches(cur, other, cur_is_dir, criteria, checkpoint):
                    _add(result, cur, cur_is_dir)
                    break
            except OSError:
                continue

    return result


def _add(result: CompareResult, entry, is_dir: bool) -> None:
    """Record ``entry`` as selected, once — a virtual feed can repeat a path, and
    the file/dir counts must stay in step with the (deduplicating) path set."""
    key = str(entry)
    if key in result.paths:
        return
    result.paths.add(key)
    if is_dir:
        result.dirs += 1
    else:
        result.files += 1


def _matches(cur, other, is_dir: bool, criteria: CompareCriteria,
             checkpoint: Callable[[], None]) -> bool:
    """Whether the matched pair satisfies every enabled relation. Directories have
    no meaningful size/content, so those relations pass automatically for them."""
    cur_stat = cur.stat()
    other_stat = other.stat()

    if not is_dir and criteria.size != "any":
        equal = cur_stat.st_size == other_stat.st_size
        if criteria.size == "equal" and not equal:
            return False
        if criteria.size == "differs" and equal:
            return False

    if criteria.mtime != "any":
        delta = cur_stat.st_mtime - other_stat.st_mtime  # >0 ⇒ current is newer
        if criteria.mtime == "same" and abs(delta) >= MTIME_TOLERANCE:
            return False
        if criteria.mtime == "newer" and delta <= MTIME_TOLERANCE:
            return False
        if criteria.mtime == "older" and delta >= -MTIME_TOLERANCE:
            return False

    if not is_dir and criteria.content != "any":
        equal = _content_equal(cur, other, cur_stat, other_stat, checkpoint)
        if criteria.content == "equal" and not equal:
            return False
        if criteria.content == "differs" and equal:
            return False

    return True


def _content_equal(cur, other, cur_stat, other_stat,
                   checkpoint: Callable[[], None]) -> bool:
    """Byte-compare two files, short-circuiting: different sizes ⇒ not equal
    (no read), otherwise stream both and stop at the first differing chunk."""
    if cur_stat.st_size != other_stat.st_size:
        return False
    with cur.open("rb") as fa, other.open("rb") as fb:
        while True:
            checkpoint()
            a = fa.read(_CHUNK)
            b = fb.read(_CHUNK)
            if a != b:
                return False
            if not a:
                return True
