"""Per-file-type memory of the built-in viewer's mode (issue #217).

The modal file viewer opens rich-renderable files (``*.md`` today) either raw
(plain text + syntax highlighting) or in a rendered "rich" view, toggled with the
``toggle_view_mode`` action. This suite covers remembering that choice per file
*extension* through the state manager, so a type reopens in the mode last chosen
for it — and that types with no rich renderer never persist anything.

Run with: python -m pytest test/test_viewer_mode_memory.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend

from xefm.path import Path
from xefm.state_manager import XeFMStateManager
from xefm.text_viewer import (TextViewer, show_text_viewer,
                             _VIEW_MODE_STATE_PREFIX)


@pytest.fixture
def state(tmp_path):
    # A throwaway on-disk state store (never the real ~/.xefm/state.db).
    return XeFMStateManager("test_viewer_mode", db_path=str(tmp_path / "state.db"))


@pytest.fixture
def md_file(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text("# Title\n\nSome text.\n")
    return Path(str(p))


@pytest.fixture
def md2_file(tmp_path):
    p = tmp_path / "other.md"
    p.write_text("# Other\n\nMore text.\n")
    return Path(str(p))


@pytest.fixture
def markdown_ext_file(tmp_path):
    p = tmp_path / "doc.markdown"
    p.write_text("# Doc\n\nBody.\n")
    return Path(str(p))


@pytest.fixture
def txt_file(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("plain\nlines\n")
    return Path(str(p))


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=100, height=30, capabilities=request.param)


def _md_key():
    return _VIEW_MODE_STATE_PREFIX + ".md"


# --- opening honors the remembered mode --------------------------------------


def test_no_state_manager_opens_raw(md_file):
    # Without a state manager the viewer can't remember anything: always raw.
    v = TextViewer(md_file)
    assert v.mode == "text"


def test_default_opens_raw_when_nothing_stored(md_file, state):
    v = TextViewer(md_file, state_manager=state)
    assert v.mode == "text"
    assert v._rich_widget is None      # nothing built until it's actually shown


def test_remembered_rich_opens_rich(backend, md_file, state):
    state.set_state(_md_key(), "rich")
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file, state_manager=state)
    assert v.mode == "rich"            # chosen at construction, before any draw
    panel.render()                     # first draw builds the embedded renderer
    assert type(v._rich_widget).__name__ == "MarkdownView"


def test_remembered_text_opens_raw(md_file, state):
    state.set_state(_md_key(), "text")
    v = TextViewer(md_file, state_manager=state)
    assert v.mode == "text"


# --- toggling persists the choice --------------------------------------------


def test_toggle_persists_rich_for_type(backend, md_file, md2_file, state):
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file, state_manager=state)
    panel.render()                     # first draw captures the content colors
    assert v.mode == "text"
    v._toggle_view_mode()              # user switches to rendered Markdown
    assert v.mode == "rich"
    assert state.get_state(_md_key()) == "rich"

    # A *different* .md file now opens rendered without any toggle.
    v2 = show_text_viewer(panel, md2_file, state_manager=state)
    assert v2.mode == "rich"


def test_toggle_back_persists_text(backend, md_file, md2_file, state):
    state.set_state(_md_key(), "rich")
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file, state_manager=state)
    panel.render()
    assert v.mode == "rich"
    v._toggle_view_mode()              # back to raw text
    assert v.mode == "text"
    assert state.get_state(_md_key()) == "text"

    v2 = show_text_viewer(panel, md2_file, state_manager=state)
    assert v2.mode == "text"


# --- scoping -----------------------------------------------------------------


def test_memory_is_per_extension(markdown_ext_file, state):
    # A choice stored for .md must not leak to a different extension (.markdown),
    # even though both use the same Markdown renderer.
    state.set_state(_md_key(), "rich")
    v = TextViewer(markdown_ext_file, state_manager=state)
    assert v.mode == "text"


def test_unregistered_type_never_persists(txt_file, state):
    # A type with no rich renderer has nothing to remember: it opens raw,
    # toggling is a no-op, and no state key is ever written for it.
    v = TextViewer(txt_file, state_manager=state)
    assert v._rich is None
    assert v.mode == "text"
    v._toggle_view_mode()
    assert v.mode == "text"
    assert state.get_state(_VIEW_MODE_STATE_PREFIX + ".txt") is None
