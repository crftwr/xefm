"""Tests for the Compare & Select engine (xefm.compare_selection): the name+type
join, each attribute relation (size / mtime direction / content byte-compare),
the include-missing (orphan) path, NFC normalization, the file/dir counts, and
the listing attributes the comparison is answered from instead of the disk."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unicodedata
from unittest import mock

import pytest

from xefm.compare_selection import (
    MTIME_TOLERANCE,
    CompareCriteria,
    compute_compare_selection,
)
from xefm.path import Path, attrs_via_path


def _P(p):
    return Path(str(p))


def _entries(d):
    """Path entries for the immediate children of a directory (like a pane feed)."""
    return list(_P(d).iterdir())


def _write(p, data=b"x", mtime=None):
    p.write_bytes(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def _run(left, right, criteria):
    return compute_compare_selection(_entries(left), _entries(right), criteria)


# --- name join (the legacy "by filename") -----------------------------------

def test_filename_only_selects_common_names(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "a.txt"); _write(left / "only_left.txt")
    _write(right / "a.txt"); _write(right / "only_right.txt")

    res = _run(left, right, CompareCriteria())
    assert res.paths == {str(left / "a.txt")}
    assert (res.files, res.dirs) == (1, 0)


def test_no_counterpart_not_selected_without_include_missing(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "only.txt")
    assert _run(left, right, CompareCriteria()).paths == set()


def test_include_missing_selects_orphans(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "a.txt"); _write(left / "orphan.txt")
    _write(right / "a.txt")

    res = _run(left, right, CompareCriteria(include_missing=True))
    assert res.paths == {str(left / "a.txt"), str(left / "orphan.txt")}


def test_same_name_different_type_is_not_a_match(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "x")            # file named x on the left
    (right / "x").mkdir()         # directory named x on the right
    # No file-vs-file counterpart, so nothing matches; and with include_missing
    # the left file counts as an orphan (no same-type counterpart).
    assert _run(left, right, CompareCriteria()).paths == set()
    assert _run(left, right, CompareCriteria(include_missing=True)).paths == {str(left / "x")}


# --- size --------------------------------------------------------------------

def test_size_equal_and_differs(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "same.bin", b"1234"); _write(right / "same.bin", b"5678")   # equal size
    _write(left / "diff.bin", b"12"); _write(right / "diff.bin", b"123456")   # different size

    assert _run(left, right, CompareCriteria(size="equal")).paths == {str(left / "same.bin")}
    assert _run(left, right, CompareCriteria(size="differs")).paths == {str(left / "diff.bin")}


def test_size_ignored_for_directories(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    (left / "d").mkdir(); (right / "d").mkdir()
    _write(left / "d" / "child")  # give the left dir a size-ish child; dirs still match
    # size=equal must still select the dir (size is meaningless for dirs → passes).
    assert _run(left, right, CompareCriteria(size="equal")).paths == {str(left / "d")}
    assert _run(left, right, CompareCriteria(size="equal")).dirs == 1


# --- mtime direction ---------------------------------------------------------

def test_mtime_same_within_tolerance(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "a", mtime=1000.0)
    _write(right / "a", mtime=1000.0 + MTIME_TOLERANCE / 2)  # within tolerance
    _write(left / "b", mtime=1000.0)
    _write(right / "b", mtime=2000.0)                        # well outside

    assert _run(left, right, CompareCriteria(mtime="same")).paths == {str(left / "a")}


def test_mtime_newer_and_older(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "newer", mtime=5000.0); _write(right / "newer", mtime=1000.0)
    _write(left / "older", mtime=1000.0); _write(right / "older", mtime=5000.0)

    assert _run(left, right, CompareCriteria(mtime="newer")).paths == {str(left / "newer")}
    assert _run(left, right, CompareCriteria(mtime="older")).paths == {str(left / "older")}


# --- content -----------------------------------------------------------------

def test_content_equal_and_differs(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "same", b"hello world"); _write(right / "same", b"hello world")
    # same size, different bytes — content differs but size does not
    _write(left / "diff", b"aaaaa"); _write(right / "diff", b"bbbbb")

    assert _run(left, right, CompareCriteria(content="equal")).paths == {str(left / "same")}
    assert _run(left, right, CompareCriteria(content="differs")).paths == {str(left / "diff")}


def test_content_differs_short_circuits_on_size(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "a", b"short"); _write(right / "a", b"a much longer body")
    # Different sizes ⇒ content differs without a full read.
    assert _run(left, right, CompareCriteria(content="differs")).paths == {str(left / "a")}
    assert _run(left, right, CompareCriteria(content="equal")).paths == set()


# --- combined AND + NFC ------------------------------------------------------

def test_relations_are_anded(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    # size equal AND newer: only "hit" satisfies both.
    _write(left / "hit", b"1234", mtime=5000.0); _write(right / "hit", b"5678", mtime=1000.0)
    _write(left / "oldsize", b"1234", mtime=1000.0); _write(right / "oldsize", b"5678", mtime=1000.0)

    res = _run(left, right, CompareCriteria(size="equal", mtime="newer"))
    assert res.paths == {str(left / "hit")}


def test_nfc_normalization_of_names(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    # Same grapheme, different Unicode normal forms (é as NFC vs NFD).
    nfc = unicodedata.normalize("NFC", "café.txt")
    nfd = unicodedata.normalize("NFD", "café.txt")
    assert nfc != nfd
    _write(left / nfc); _write(right / nfd)
    assert _run(left, right, CompareCriteria()).paths == {str(left / nfc)}


# --- virtual (search-results) feeds ------------------------------------------

def test_scattered_current_feed_joins_by_name(tmp_path):
    """A search-results feed on the current side: entries live in different
    directories and are joined to the other pane by basename, like any listing."""
    right = tmp_path / "R"; right.mkdir()
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(); two.mkdir()
    _write(one / "hit.txt"); _write(two / "miss.txt")
    _write(right / "hit.txt")

    res = compute_compare_selection([_P(one / "hit.txt"), _P(two / "miss.txt")],
                                    _entries(right), CompareCriteria())
    assert res.paths == {str(one / "hit.txt")}


def test_any_same_named_candidate_matches(tmp_path):
    """The other side may be a result set holding several entries with the same
    name; the current entry is selected when *any* of them satisfies the relation,
    so the answer doesn't depend on the feed order."""
    cur = tmp_path / "C"; cur.mkdir()
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(); two.mkdir()
    _write(cur / "x.txt", mtime=3000.0)
    _write(one / "x.txt", mtime=1000.0)   # older than the current entry
    _write(two / "x.txt", mtime=5000.0)   # newer than the current entry
    others = [_P(one / "x.txt"), _P(two / "x.txt")]

    # Matches through the older candidate...
    assert compute_compare_selection(
        _entries(cur), others, CompareCriteria(mtime="newer")).paths == {str(cur / "x.txt")}
    # ...and through the newer one, whichever order they arrive in.
    assert compute_compare_selection(
        _entries(cur), list(reversed(others)),
        CompareCriteria(mtime="older")).paths == {str(cur / "x.txt")}


def test_candidates_present_but_none_match(tmp_path):
    """Same-named candidates exist, so the entry is not an orphan — it simply
    fails the relation against every one of them."""
    cur = tmp_path / "C"; cur.mkdir()
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(); two.mkdir()
    _write(cur / "x.txt", mtime=3000.0)
    _write(one / "x.txt", mtime=4000.0)
    _write(two / "x.txt", mtime=5000.0)
    others = [_P(one / "x.txt"), _P(two / "x.txt")]

    for criteria in (CompareCriteria(mtime="newer"),
                     CompareCriteria(mtime="newer", include_missing=True)):
        assert compute_compare_selection(_entries(cur), others, criteria).paths == set()


def test_repeated_current_entry_counted_once(tmp_path):
    """A feed may repeat a path; the counts stay in step with the path set."""
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "a.txt"); _write(right / "a.txt")
    entry = _P(left / "a.txt")

    res = compute_compare_selection([entry, entry], _entries(right), CompareCriteria())
    assert res.total == 1
    assert (res.files, res.dirs) == (1, 0)


# --- listing attributes (#245) ------------------------------------------------

def _attrs(entries):
    """What a pane's listing snapshot holds: ``{str(path): dir_scan record}``."""
    return {str(p): attrs_via_path(p) for p in entries}


def _count_os_calls(fn):
    """Run ``fn`` and return ``(result, per-file call count)``. Every route a
    ``Path`` takes to the filesystem for attributes bottoms out in one of these
    two, so counting them counts round trips on a network mount."""
    calls = []
    real_stat, real_lstat = os.stat, os.lstat

    def counted(inner):
        def wrapper(*a, **kw):
            calls.append(1)
            return inner(*a, **kw)
        return wrapper

    with mock.patch("os.stat", counted(real_stat)), \
         mock.patch("os.lstat", counted(real_lstat)):
        result = fn()
    return result, len(calls)


def _both_sides(tmp_path, n=6):
    """Two directories of same-named files, and their listing attributes."""
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    for i in range(n):
        _write(left / f"f{i}.txt", b"x" * (i + 1), mtime=5000.0)
        _write(right / f"f{i}.txt", b"x" * (i + 1), mtime=1000.0)
    cur, oth = _entries(left), _entries(right)
    return left, right, cur, oth, _attrs(cur), _attrs(oth)


_ALL_CRITERIA = (
    CompareCriteria(),
    CompareCriteria(size="equal"),
    CompareCriteria(size="differs"),
    CompareCriteria(mtime="newer"),
    CompareCriteria(mtime="older"),
    CompareCriteria(mtime="same"),
    CompareCriteria(include_missing=True),
)


def test_supplied_attributes_replace_every_stat(tmp_path):
    """The point of #245: comparing panes that have already listed must not go
    back to the filesystem — every fact a stat-only relation needs is in the
    snapshot, so the whole comparison costs zero per-file calls."""
    _l, _r, cur, oth, cur_a, oth_a = _both_sides(tmp_path)

    for criteria in _ALL_CRITERIA:
        _res, calls = _count_os_calls(lambda c=criteria: compute_compare_selection(
            cur, oth, c, current_attrs=cur_a, other_attrs=oth_a))
        assert calls == 0, f"{criteria} issued {calls} per-file calls"


def test_attributes_do_not_change_the_answer(tmp_path):
    """Passing the snapshot is an optimization, not a different comparison."""
    _l, _r, cur, oth, cur_a, oth_a = _both_sides(tmp_path)
    # An orphan on each side, so include_missing has something to find.
    _write(_l / "only_left.txt")
    _write(_r / "only_right.txt")
    cur, oth = _entries(_l), _entries(_r)
    cur_a, oth_a = _attrs(cur), _attrs(oth)

    for criteria in _ALL_CRITERIA + (CompareCriteria(content="equal"),
                                     CompareCriteria(content="differs")):
        with_attrs = compute_compare_selection(
            cur, oth, criteria, current_attrs=cur_a, other_attrs=oth_a)
        without = compute_compare_selection(cur, oth, criteria)
        assert with_attrs.paths == without.paths, criteria
        assert (with_attrs.files, with_attrs.dirs) == (without.files, without.dirs)


def test_content_compare_reads_bytes_but_stats_nothing(tmp_path):
    """A content relation still reads both files — no snapshot can answer it —
    but the size short-circuit that decides *whether* to read comes from the
    records, so no entry is stat'd."""
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "same", b"hello"); _write(right / "same", b"hello")
    _write(left / "sized", b"short"); _write(right / "sized", b"much longer body")
    cur, oth = _entries(left), _entries(right)
    cur_a, oth_a = _attrs(cur), _attrs(oth)   # built outside: this is the listing

    res, calls = _count_os_calls(lambda: compute_compare_selection(
        cur, oth, CompareCriteria(content="equal"),
        current_attrs=cur_a, other_attrs=oth_a))
    assert res.paths == {str(left / "same")}
    assert calls == 0


def test_the_records_are_what_is_compared(tmp_path):
    """Proof the snapshot is actually consulted rather than quietly ignored:
    hand the engine a record that disagrees with the disk, and the selection
    follows the record."""
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "a", b"x", mtime=1000.0)
    _write(right / "a", b"x", mtime=1000.0)     # on disk the two are the same age
    cur, oth = _entries(left), _entries(right)
    cur_a, oth_a = _attrs(cur), _attrs(oth)
    assert compute_compare_selection(
        cur, oth, CompareCriteria(mtime="newer"),
        current_attrs=cur_a, other_attrs=oth_a).paths == set()

    key = str(left / "a")
    cur_a[key] = dict(cur_a[key], mtime=5000.0)  # ...but say the left one is newer
    assert compute_compare_selection(
        cur, oth, CompareCriteria(mtime="newer"),
        current_attrs=cur_a, other_attrs=oth_a).paths == {key}


def test_a_missing_record_falls_back_to_reading_that_entry(tmp_path):
    """A partial snapshot still works: entries it covers cost nothing, the rest
    are read per file — so a caller with no attributes at all is unaffected."""
    _l, _r, cur, oth, cur_a, oth_a = _both_sides(tmp_path)
    dropped = str(cur[0])
    del cur_a[dropped]

    res, calls = _count_os_calls(lambda: compute_compare_selection(
        cur, oth, CompareCriteria(mtime="newer"),
        current_attrs=cur_a, other_attrs=oth_a))
    assert res.paths == {str(p) for p in cur}   # same answer as a full snapshot
    assert 0 < calls <= 2, f"only the one uncovered entry may be read, got {calls}"


def test_unreadable_entry_matches_nothing_but_is_still_a_counterpart(tmp_path):
    """A broken symlink satisfies no relation — nothing can be asserted about a
    target that isn't there — yet it is still an entry of that name, so the
    other side's file is not an orphan either. Both with and without records."""
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir(); right.mkdir()
    _write(left / "x")
    (right / "x").symlink_to(right / "nowhere")   # broken
    cur, oth = _entries(left), _entries(right)

    for kwargs in ({}, {"current_attrs": _attrs(cur), "other_attrs": _attrs(oth)}):
        assert compute_compare_selection(
            cur, oth, CompareCriteria(), **kwargs).paths == set()
        # Not selected, and not reported as missing: a counterpart named x exists.
        assert compute_compare_selection(
            cur, oth, CompareCriteria(include_missing=True), **kwargs).paths == set()


def test_needs_content_flag():
    assert not CompareCriteria().needs_content
    assert not CompareCriteria(size="equal", mtime="newer").needs_content
    assert CompareCriteria(content="equal").needs_content
    assert CompareCriteria(content="differs").needs_content
