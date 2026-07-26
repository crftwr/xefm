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

Every fact a comparison needs — is-it-a-directory, size, mtime — is read from the
:mod:`xefm.dir_scan` attribute records the callers pass in as ``current_attrs`` /
``other_attrs``, not by asking the filesystem again. A pane's listing already
collected exactly those fields for exactly these entries, so the compare is pure
CPU over data in hand. Asking per file instead cost one round trip per entry per
side, which on a network mount *was* the feature: two 1,680-entry panes meant
~6,700 calls where the panes between them held every answer (#245, the same cost
model #183 removed from listing). An entry with no record falls back to reading
it per file, so a caller with no attributes still works — at one ``stat`` each,
which is the cost this exists to avoid.

A content comparison is the one thing no snapshot can answer, so it reads both
files and callers route it through the task worker; a size mismatch short-circuits
it (files are only read when their recorded sizes already match). The optional
``checkpoint`` callable is invoked between entries and between chunks so a worker
can raise to cancel.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional

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


def _attrs_of(entry, attrs: Mapping[str, dict]) -> dict:
    """The attribute record for ``entry``: from the caller's listing snapshot, or
    read per file when it holds none for this entry.

    The per-file route is deliberately not ``attrs_via_path`` — that also asks
    ``is_symlink``, and a comparison reads only ``ok``/``is_dir``/``size``/
    ``mtime``. This fallback exists precisely for the storage where every call is
    a round trip, so it must not spend one on a field nobody here looks at; the
    record it returns is that subset, not a full :mod:`xefm.dir_scan` one."""
    a = attrs.get(str(entry))
    if a is not None:
        return a
    try:
        st = entry.stat()
        is_dir = entry.is_dir()
    except Exception:
        # As broad as ``attrs_via_path``'s, and for the same reason: a remote
        # backend (SSH, S3, an archive) raises its own type here, and every one
        # of them means the same thing to a comparison — this entry cannot be
        # read. That is reported as ``ok`` False rather than swallowed.
        return {'is_dir': False, 'size': 0, 'mtime': 0.0, 'ok': False}
    return {'is_dir': is_dir, 'size': 0 if is_dir else st.st_size,
            'mtime': st.st_mtime, 'ok': True}


def compute_compare_selection(
    current_files: Iterable,
    other_files: Iterable,
    criteria: CompareCriteria,
    *,
    current_attrs: Optional[Mapping[str, dict]] = None,
    other_attrs: Optional[Mapping[str, dict]] = None,
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
    selected if **any** of them satisfies the relations.

    ``current_attrs`` / ``other_attrs`` map ``str(path)`` to the
    :mod:`xefm.dir_scan` record the caller's listing already collected for that
    side — the whole comparison is answered from them, so it touches the
    filesystem only for a content read. Entries missing from the mapping are read
    per file, so passing nothing still works, at one ``stat`` per entry.

    An entry whose attributes are unreadable — a broken symlink, a vanished file,
    ``ok`` False — satisfies no relation, so it is never selected through a
    counterpart. It still *counts* as a counterpart for the other side's
    orphan test, exactly as an entry whose ``stat`` raised always has.

    ``checkpoint`` is called between entries and between content chunks (a worker
    raises from it to cancel); ``on_advance(entry)`` is called once per current
    entry, before it is compared, for progress reporting."""
    current_attrs = current_attrs or {}
    other_attrs = other_attrs or {}

    other_by_key: dict[tuple[str, bool], list] = {}
    for p in other_files:
        a = _attrs_of(p, other_attrs)
        other_by_key.setdefault((_norm(p.name), a['is_dir']), []).append((p, a))

    result = CompareResult()
    for cur in current_files:
        checkpoint()
        if on_advance is not None:
            on_advance(cur)
        cur_a = _attrs_of(cur, current_attrs)
        cur_is_dir = cur_a['is_dir']

        candidates = other_by_key.get((_norm(cur.name), cur_is_dir))
        if not candidates:
            if criteria.include_missing:
                _add(result, cur, cur_is_dir)
            continue

        for other, other_a in candidates:
            try:
                if _matches(cur, other, cur_a, other_a, cur_is_dir, criteria,
                            checkpoint):
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


def _matches(cur, other, cur_a: dict, other_a: dict, is_dir: bool,
             criteria: CompareCriteria,
             checkpoint: Callable[[], None]) -> bool:
    """Whether the matched pair satisfies every enabled relation, judged from the
    two attribute records. Directories have no meaningful size/content, so those
    relations pass automatically for them."""
    if not (cur_a['ok'] and other_a['ok']):
        return False  # unreadable on either side — nothing can be asserted

    if not is_dir and criteria.size != "any":
        equal = cur_a['size'] == other_a['size']
        if criteria.size == "equal" and not equal:
            return False
        if criteria.size == "differs" and equal:
            return False

    if criteria.mtime != "any":
        delta = cur_a['mtime'] - other_a['mtime']  # >0 ⇒ current is newer
        if criteria.mtime == "same" and abs(delta) >= MTIME_TOLERANCE:
            return False
        if criteria.mtime == "newer" and delta <= MTIME_TOLERANCE:
            return False
        if criteria.mtime == "older" and delta >= -MTIME_TOLERANCE:
            return False

    if not is_dir and criteria.content != "any":
        equal = _content_equal(cur, other, cur_a['size'], other_a['size'],
                               checkpoint)
        if criteria.content == "equal" and not equal:
            return False
        if criteria.content == "differs" and equal:
            return False

    return True


def _content_equal(cur, other, cur_size: int, other_size: int,
                   checkpoint: Callable[[], None]) -> bool:
    """Byte-compare two files, short-circuiting: different sizes ⇒ not equal
    (no read), otherwise stream both and stop at the first differing chunk. The
    sizes come from the listing records, so the short-circuit costs no ``stat``."""
    if cur_size != other_size:
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
