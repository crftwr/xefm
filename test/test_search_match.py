"""The shared incremental-search query (xefm.search_match, issue #349).

The file pane's isearch and the filter-list dialogs (favorites, drives,
history, external programs, filter history) run one matcher, so multiple
keywords and wildcards work in the dialogs exactly as they do in the pane.
Covers the token compiler, the AND/OR combination, the dialog integration
(including rows streamed in by a background loader), and pane/dialog parity.

Migemo's half of the union lives in test_migemo_search.py; nothing here needs
the engine.

Run with: python -m pytest test/test_search_match.py -v
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm import migemo_search, search_match
from xefm.file_list_manager import FileListManager
from xefm.filter_list_dialog import FilterListDialog


@pytest.fixture(autouse=True)
def no_migemo(monkeypatch):
    """Matching without Migemo's union, so every assertion here is about the
    query language itself. (With the engine installed, romaji only ever *adds*
    matches — see test_migemo_search.py.)"""
    monkeypatch.setattr(migemo_search, "_config",
                        lambda: SimpleNamespace(MIGEMO_SEARCH=False))


class FakePath:
    def __init__(self, name):
        self.name = name


NAMES = ["readme.py", "setup.py", "notes.md", "src_utils.py", "work_src.txt"]


@pytest.fixture
def flm():
    return FileListManager(SimpleNamespace(SHOW_HIDDEN_FILES=True))


@pytest.fixture
def pane():
    return {"files": [FakePath(n) for n in NAMES]}


def isearch(flm, pane, pattern):
    idx = flm.find_matches(pane, pattern, match_all=True, return_indices_only=True)
    return [NAMES[i] for i in idx]


def filtered(items, pattern):
    """The rows a filter-list dialog keeps for ``pattern``."""
    d = FilterListDialog(items)
    d._refilter(pattern)
    return d.filtered


# --- the token compiler ------------------------------------------------------


def test_bare_token_is_wrapped_for_contains():
    assert [glob for glob, _ in search_match.compile_query("py")] == ["*py*"]


def test_glob_token_keeps_its_own_stars():
    assert [glob for glob, _ in search_match.compile_query("*.py")] == ["*.py*"]
    assert [glob for glob, _ in search_match.compile_query("*mid*")] == ["*mid*"]


def test_tokens_split_on_whitespace():
    assert [glob for glob, _ in search_match.compile_query("  a   b ")] == ["*a*", "*b*"]


def test_empty_query_compiles_to_no_tokens():
    assert search_match.compile_query("   ") == []


# --- combination -------------------------------------------------------------


def test_tokens_and_by_default():
    tokens = search_match.compile_query("work src")
    assert search_match.hit(tokens, "work_src.txt")
    assert not search_match.hit(tokens, "src_utils.py")


def test_tokens_or_on_request():
    tokens = search_match.compile_query("work src")
    assert search_match.hit(tokens, "src_utils.py", match_all=False)
    assert not search_match.hit(tokens, "notes.md", match_all=False)


def test_empty_query_passes_everything_under_and():
    assert search_match.hit([], "anything")
    assert not search_match.hit([], "anything", match_all=False)


def test_matching_is_case_insensitive():
    assert search_match.hit(search_match.compile_query("README"), "readme.py")


# --- filter-list dialogs (#349) ---------------------------------------------


def test_dialog_substring_filter_unchanged():
    assert filtered(["apple", "banana", "apricot"], "ap") == ["apple", "apricot"]


def test_dialog_multiple_keywords_narrow():
    items = ["Projects  —  /home/me/work/src", "Docs  —  /home/me/work/doc",
             "Src  —  /srv/src"]
    assert filtered(items, "work src") == ["Projects  —  /home/me/work/src"]


def test_dialog_keyword_matches_across_the_whole_label():
    """Labels are `name — path`; a token may hit either half (the label is one
    string, not two fields)."""
    items = ["Downloads  —  /home/me/dl", "Music  —  /home/me/audio"]
    assert filtered(items, "downloads /home") == ["Downloads  —  /home/me/dl"]


def test_dialog_wildcards_work():
    items = ["readme.py", "readme.md", "setup.cfg"]
    assert filtered(items, "*.md") == ["readme.md"]
    assert filtered(items, "re?dme.py") == ["readme.py"]


def test_dialog_empty_query_keeps_every_row():
    items = ["alpha", "beta"]
    assert filtered(items, "") == items


def test_dialog_unmatched_keyword_empties_the_list():
    assert filtered(["alpha", "beta"], "alpha zzz") == []


def test_dialog_streamed_rows_take_the_active_query():
    d = FilterListDialog(["work src eager"],
                         load_more=lambda cancel: iter(["work_src.txt", "src only"]))
    d.filter_edit.text = "work src"
    d._refilter("work src")
    d._start_load_more()
    assert d.filtered == ["work src eager", "work_src.txt"]
    assert d.all_items == ["work src eager", "work_src.txt", "src only"]


# --- pane / dialog parity ----------------------------------------------------


@pytest.mark.parametrize("pattern", ["py", "*.py", "src py", "READ", "zzz", ""])
def test_pane_and_dialog_agree(flm, pane, pattern):
    dialog_rows = filtered(list(NAMES), pattern)
    pane_rows = list(NAMES) if not pattern.strip() else isearch(flm, pane, pattern)
    assert dialog_rows == pane_rows
