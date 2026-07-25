"""Unit tests for the reusable TAB-completion engine (``xefm.completion``).

Covers the three pieces independently of any UI: the longest-common-prefix
helper, the filesystem ``FilepathCompleter`` (against a real temp tree), and the
``CompletionController`` bound to a real PuiKit ``TextEdit`` (no backend / draw).
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit.widgets.text_edit import TextEdit  # noqa: E402

from xefm.completion import (  # noqa: E402
    CompletionController,
    FilepathCompleter,
    calculate_common_prefix,
)

SEP = os.sep


# --- calculate_common_prefix -------------------------------------------------

@pytest.mark.parametrize("candidates,expected", [
    ([], ""),
    (["hello"], "hello"),
    (["hello", "help", "hero"], "he"),
    (["abc", "def"], ""),
    (["same", "same", "same"], "same"),
    (["prefix_a", "prefix_b", "prefix_c"], "prefix_"),
])
def test_common_prefix(candidates, expected):
    assert calculate_common_prefix(candidates) == expected


def test_common_prefix_is_case_sensitive():
    assert calculate_common_prefix(["Abc", "abc"]) == ""


# --- FilepathCompleter -------------------------------------------------------

def _make_tree(root):
    (root / "docs").mkdir()
    (root / "downloads").mkdir()
    (root / "data.txt").write_text("x")
    (root / "readme.md").write_text("x")
    (root / "Archive").mkdir()  # capital, for case-sensitivity


def test_filepath_prefix_match_and_dir_sep(tmp_path):
    _make_tree(tmp_path)
    comp = FilepathCompleter(base_directory=str(tmp_path))
    # No separator in the text -> complete within base_directory.
    assert comp.get_candidates("d", 1) == ["data.txt", "docs" + SEP, "downloads" + SEP]
    # Directory candidates carry a trailing separator; files do not.
    assert comp.get_candidates("data", 4) == ["data.txt"]


def test_filepath_directories_only(tmp_path):
    _make_tree(tmp_path)
    comp = FilepathCompleter(base_directory=str(tmp_path), directories_only=True)
    assert comp.get_candidates("d", 1) == ["docs" + SEP, "downloads" + SEP]
    # A file-only prefix yields nothing in directories-only mode.
    assert comp.get_candidates("data", 4) == []


def test_filepath_results_are_sorted(tmp_path):
    for name in ("cherry", "apple", "banana"):
        (tmp_path / name).mkdir()
    comp = FilepathCompleter(base_directory=str(tmp_path))
    assert comp.get_candidates("", 0) == ["apple" + SEP, "banana" + SEP, "cherry" + SEP]


def test_filepath_match_is_case_sensitive(tmp_path):
    _make_tree(tmp_path)
    comp = FilepathCompleter(base_directory=str(tmp_path))
    assert comp.get_candidates("a", 1) == []            # lower 'a' misses "Archive"
    assert comp.get_candidates("A", 1) == ["Archive" + SEP]


def test_filepath_with_separator_lists_that_directory(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / "docs" / "guide.md").write_text("x")
    (tmp_path / "docs" / "gallery").mkdir()
    comp = FilepathCompleter(base_directory=str(tmp_path))
    text = "docs" + SEP + "g"
    assert comp.get_candidates(text, len(text)) == ["gallery" + SEP, "guide.md"]


def test_filepath_absolute_path(tmp_path):
    _make_tree(tmp_path)
    comp = FilepathCompleter(base_directory=str(tmp_path / "docs"))  # base ignored for abs
    text = str(tmp_path) + SEP + "do"
    assert comp.get_candidates(text, len(text)) == ["docs" + SEP, "downloads" + SEP]


def test_filepath_tilde_expansion(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "projects").mkdir(parents=True)
    (home / "photos").mkdir()
    monkeypatch.setenv("HOME", str(home))  # os.path.expanduser reads $HOME on POSIX
    comp = FilepathCompleter(base_directory=str(tmp_path))
    text = "~" + SEP + "p"
    assert comp.get_candidates(text, len(text)) == ["photos" + SEP, "projects" + SEP]


def test_filepath_nonexistent_directory_is_empty(tmp_path):
    comp = FilepathCompleter(base_directory=str(tmp_path / "nope"))
    assert comp.get_candidates("x", 1) == []


def test_completion_start_pos(tmp_path):
    comp = FilepathCompleter(base_directory=str(tmp_path))
    assert comp.get_completion_start_pos("abc", 3) == 0
    text = "docs" + SEP + "gu"
    assert comp.get_completion_start_pos(text, len(text)) == 5


# --- CompletionController ----------------------------------------------------

class StubCompleter:
    """A deterministic completer for controller-state tests: the token is the
    whole text before the caret, matched against a fixed candidate list."""

    def __init__(self, candidates):
        self._candidates = candidates

    def get_candidates(self, text, cursor_pos):
        prefix = text[:cursor_pos]
        return [c for c in self._candidates if c.startswith(prefix)]

    def get_completion_start_pos(self, text, cursor_pos):
        return 0


def _controller(text, candidates):
    edit = TextEdit(text=text)
    edit.cursor = len(text)
    return CompletionController(edit, StubCompleter(candidates)), edit


def test_tab_inserts_common_prefix_and_opens_list():
    ctrl, edit = _controller("he", ["hello", "help", "hero"])
    assert ctrl.on_tab() is True
    assert edit.text == "he"          # common prefix is "he" == already typed: no change
    assert ctrl.active is True
    assert ctrl.candidates == ["hello", "help", "hero"]


def test_tab_extends_to_common_prefix():
    ctrl, edit = _controller("h", ["helium", "helmet"])
    ctrl.on_tab()
    assert edit.text == "hel"         # extended to the common prefix
    assert edit.cursor == 3
    assert ctrl.active is True


def test_tab_single_candidate_completes_fully_with_sep():
    ctrl, edit = _controller("pro", ["projects" + SEP])
    ctrl.on_tab()
    assert edit.text == "projects" + SEP
    assert edit.cursor == len("projects" + SEP)
    assert ctrl.active is False       # a unique match does not open the list


def test_tab_no_candidates_stays_inactive():
    ctrl, edit = _controller("zzz", ["hello"])
    assert ctrl.on_tab() is False
    assert edit.text == "zzz"
    assert ctrl.active is False


def test_typing_narrows_then_hides():
    ctrl, edit = _controller("he", ["hello", "help", "hero"])
    ctrl.on_tab()
    # Narrow to a single match — the list stays open (visible for one candidate).
    edit.text, edit.cursor = "hel", 3
    ctrl.on_text_changed()
    assert ctrl.active is True
    assert ctrl.candidates == ["hello", "help"]
    # Narrow to nothing — the list hides.
    edit.text, edit.cursor = "hez", 3
    ctrl.on_text_changed()
    assert ctrl.active is False
    assert ctrl.candidates == []


def test_move_focus_wraps():
    ctrl, _ = _controller("h", ["ha", "hb", "hc"])
    ctrl.on_tab()
    assert ctrl.focused_index == -1
    ctrl.move_focus(1)
    assert ctrl.focused_index == 0    # from no-highlight, forward -> first
    ctrl.move_focus(-1)
    assert ctrl.focused_index == 2    # wraps to last
    ctrl.move_focus(1)
    assert ctrl.focused_index == 0    # wraps to first


def test_move_focus_from_none_backward_is_last():
    ctrl, _ = _controller("h", ["ha", "hb", "hc"])
    ctrl.on_tab()
    ctrl.move_focus(-1)
    assert ctrl.focused_index == 2


def test_accept_applies_highlighted_candidate():
    ctrl, edit = _controller("h", ["ha", "hb", "hc"])
    ctrl.on_tab()
    ctrl.move_focus(1)                # highlight "ha"
    assert ctrl.accept() is True
    assert edit.text == "ha"
    assert edit.cursor == 2
    assert ctrl.active is False


def test_accept_without_highlight_is_not_consumed():
    ctrl, edit = _controller("h", ["ha", "hb"])
    ctrl.on_tab()                     # active, but nothing highlighted
    assert ctrl.accept() is False     # Enter falls through to a normal submit
    assert edit.text == "h"
    assert ctrl.active is True        # accept() with no highlight leaves the list open


def test_apply_index_replaces_token_within_larger_text():
    edit = TextEdit(text="docs" + SEP + "gu")
    edit.cursor = len(edit.text)
    ctrl = CompletionController(edit, StubCompleter([]))
    ctrl.candidates = ["guide.md", "gallery" + SEP]
    ctrl.completion_start_pos = 5     # right after the separator
    ctrl.active = True
    ctrl.apply_index(0)
    assert edit.text == "docs" + SEP + "guide.md"
    assert ctrl.active is False


def test_dismiss_clears_state():
    ctrl, _ = _controller("h", ["ha", "hb"])
    ctrl.on_tab()
    ctrl.move_focus(1)
    ctrl.dismiss()
    assert ctrl.active is False
    assert ctrl.candidates == []
    assert ctrl.focused_index == -1
