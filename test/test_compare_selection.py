"""Tests for the Compare & Select engine (xefm.compare_selection): the name+type
join, each attribute relation (size / mtime direction / content byte-compare),
the include-missing (orphan) path, NFC normalization, and the file/dir counts."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unicodedata

import pytest

from xefm.compare_selection import (
    MTIME_TOLERANCE,
    CompareCriteria,
    compute_compare_selection,
)
from xefm.path import Path


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


def test_needs_content_flag():
    assert not CompareCriteria().needs_content
    assert not CompareCriteria(size="equal", mtime="newer").needs_content
    assert CompareCriteria(content="equal").needs_content
    assert CompareCriteria(content="differs").needs_content
