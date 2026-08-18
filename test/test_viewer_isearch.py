"""Incremental search + line-wrap keys in the text and file-diff viewers.

Both viewers reuse the main file manager's ``ISearchBar`` (via
``ViewerISearch``) for search, bound to the shared ``search`` action; the text
viewer's line-wrap toggle is the ``toggle_wrap`` action. See
doc/dev/KEY_BINDINGS_IMPLEMENTATION.md and the viewers' module docstrings.

Run with: python -m pytest test/test_viewer_isearch.py -v
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend

from xefm import _config
from xefm.config import KeyBindings
from xefm.path import Path
from xefm.text_viewer import show_text_viewer
from xefm.diff_viewer import show_diff_viewer


def _key(name=None, char=None):
    return Event(type=EventType.KEY, key=name, char=char)


def _type(panel, text):
    for ch in text:
        panel.dispatch_event(_key(ch, ch))  # letters: event.key == the glyph


def _top(panel):
    return type(panel._layers[-1].widget).__name__


def _assert_match_in_context(v, row, total):
    """The current match must be visible with ≥3 rows of context above and
    below (issue #321), except where the document edge is closer than the
    margin — there the clamp legitimately eats it."""
    top = int(v.top)
    assert top <= row <= top + v._view_h - 1
    assert row - top >= min(3, row)
    assert (top + v._view_h - 1) - row >= min(3, total - 1 - row)


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=100, height=30, capabilities=request.param)


@pytest.fixture
def text_file(tmp_path):
    p = tmp_path / "sample.txt"
    body = ["alpha one", "beta two", "gamma alpha", "delta three",
            "alpha epsilon", "zeta final"]
    body += [f"pad line {i}" for i in range(40)]
    p.write_text("\n".join(body))
    return Path(str(p))


@pytest.fixture
def diff_files(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    left = ["needle here", "same", "left only needle", "tail"]
    right = ["needle here", "same", "right side", "tail"]
    pad = [f"x{i}" for i in range(30)]
    a.write_text("\n".join(left + pad))
    b.write_text("\n".join(right + pad))
    return Path(str(a)), Path(str(b))


# --- KeyBindings: action-specific matching resolves the W collision ----------


def test_is_action_for_event_resolves_shared_key():
    kb = KeyBindings(_config.Config().KEY_BINDINGS)
    w = _key("w", "w")
    # W is bound to both toggle_wrap and compare_selection; each is matched by name.
    assert kb.is_action_for_event(w, "toggle_wrap")
    assert kb.is_action_for_event(w, "compare_selection")
    # find_action_for_event returns only the globally-first action for the key.
    assert kb.find_action_for_event(w) == "compare_selection"
    # A different key doesn't match toggle_wrap.
    assert not kb.is_action_for_event(_key("f", "f"), "toggle_wrap")


# --- Text viewer -------------------------------------------------------------


def test_text_search_open_compute_navigate_cancel(backend, text_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, text_file)
    panel.render()
    assert _top(panel) == "TextViewer"

    panel.dispatch_event(_key("f", "f"))          # 'search' binding
    panel.render()
    assert v._isearch.active
    assert _top(panel) == "ISearchBar"

    _type(panel, "alpha")                          # lines 0, 2, 4
    panel.render()
    assert v.matches == [0, 2, 4]
    assert v.pattern == "alpha"
    assert v.match_pos == 0                         # nearest at/after origin
    assert v._search_status() == (1, 3)

    # All three matches sit inside the first page: walking them never scrolls
    # (#321 — jump only when the match would land too close to an edge).
    panel.dispatch_event(_key("down"))
    assert v.match_pos == 1 and v.top == 0.0
    panel.dispatch_event(_key("down"))
    assert v.match_pos == 2 and v.top == 0.0
    panel.dispatch_event(_key("down"))             # wraps
    assert v.match_pos == 0 and v.top == 0.0
    panel.dispatch_event(_key("up"))               # wraps back
    assert v.match_pos == 2 and v.top == 0.0

    panel.dispatch_event(_key("escape"))           # cancel -> restore + clear
    panel.render()
    assert not v._isearch.active
    assert v.pattern == "" and v.matches == []
    assert v.top == 0.0
    assert _top(panel) == "TextViewer"


def test_text_search_accept_keeps_position(backend, text_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, text_file)
    panel.render()
    panel.dispatch_event(_key("f", "f"))
    _type(panel, "pad line 39")                     # line 45 only (the last line)
    panel.render()
    assert v.matches == [45] and v.top > 0.0
    scrolled = v.top
    panel.dispatch_event(_key("enter"))            # accept -> keep scroll, clear
    panel.render()
    assert not v._isearch.active
    assert v.pattern == "" and v.matches == []
    assert v.top == scrolled


def test_text_search_jump_keeps_context_margin(backend, text_file):
    # Jumping to an off-screen match must not pin it to the viewport edge:
    # a few lines above and below stay visible (issue #321).
    panel = Panel(backend)
    v = show_text_viewer(panel, text_file)
    panel.render()
    total = v._total_rows()
    panel.dispatch_event(_key("f", "f"))
    _type(panel, "pad line 20")                     # line 26, below the first page
    panel.render()
    assert v.matches == [26] and v.top > 0.0
    _assert_match_in_context(v, 26, total)


def test_text_search_step_keeps_context_margin(backend, text_file):
    # Walking matches keeps the margin in both directions.
    panel = Panel(backend)
    v = show_text_viewer(panel, text_file)
    panel.render()
    total = v._total_rows()
    panel.dispatch_event(_key("f", "f"))
    _type(panel, "pad line 3")                      # lines 9 and 36..45
    panel.render()
    assert v.matches == [9] + list(range(36, 46))
    assert v.match_pos == 0 and v.top == 0.0        # line 9: already visible

    panel.dispatch_event(_key("down"))              # line 36: scrolls down
    _assert_match_in_context(v, 36, total)
    down_top = v.top
    panel.dispatch_event(_key("up"))                # back to 9: scrolls up
    assert v.top < down_top
    _assert_match_in_context(v, 9, total)


def test_text_search_no_match_restores_origin(backend, text_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, text_file)
    panel.render()
    panel.dispatch_event(_key("f", "f"))
    _type(panel, "zzz-nomatch")
    panel.render()
    assert v.matches == []
    assert v.match_pos == -1
    assert v._search_status() == (0, 0)
    assert v.top == 0.0


def test_text_wrap_toggle(backend, text_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, text_file)
    panel.render()
    assert v.wrap is False
    # W toggles wrap via the toggle_wrap binding (or the literal-'w' fallback when a
    # config predates it) — observably identical either way.
    panel.dispatch_event(_key("w", "w"))
    assert v.wrap is True
    panel.dispatch_event(_key("w", "w"))
    assert v.wrap is False


# --- File diff viewer --------------------------------------------------------


def test_diff_search_matches_both_sides(backend, diff_files):
    panel = Panel(backend)
    v = show_diff_viewer(panel, *diff_files)
    panel.render()
    assert _top(panel) == "DiffViewer"

    panel.dispatch_event(_key("f", "f"))
    panel.render()
    assert v._isearch.active
    assert _top(panel) == "ISearchBar"

    _type(panel, "needle")
    panel.render()
    # Row 0 ("needle here", both sides) and the "left only needle" row match.
    assert v.search_matches and v.search_matches[0] == 0
    assert v.search_pattern == "needle"

    panel.dispatch_event(_key("escape"))
    panel.render()
    assert not v._isearch.active
    assert v.search_pattern == "" and v.search_matches == []
    assert v.top == 0.0


def test_diff_search_jump_keeps_context_margin(backend, diff_files):
    # The diff viewer shares the same margin rule (issue #321).
    panel = Panel(backend)
    v = show_diff_viewer(panel, *diff_files)
    panel.render()
    panel.dispatch_event(_key("f", "f"))
    _type(panel, "x25")                             # pad row 25 -> display row 29
    panel.render()
    assert v.search_matches == [29] and v.top > 0.0
    top = int(v.top)
    total = len(v.rows)
    assert top <= 29 <= top + v._view_h - 1
    assert 29 - top >= 3
    assert (top + v._view_h - 1) - 29 >= min(3, total - 1 - 29)


def test_diff_search_and_block_nav_are_independent(backend, diff_files):
    panel = Panel(backend)
    v = show_diff_viewer(panel, *diff_files)
    panel.render()
    # n/N still navigate diff blocks while no search is open.
    assert v.blocks
    panel.dispatch_event(_key("n", "n"))
    assert int(v.top) == v.blocks[0]
