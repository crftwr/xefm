"""Text selection + clipboard copy in the modal file viewers.

The raw text viewer selects source lines as ``(line, col)`` and copies plain
text; in rich (Markdown) mode the viewer forwards mouse + copy to the embedded
PuiKit ``MarkdownView``, which copies plain text plus rich HTML. See
doc/TEXT_VIEWER_FEATURE.md and doc/dev/TEXT_VIEWER_SYSTEM.md.

Run with: python -m pytest test/test_viewer_selection.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend

from xefm.path import Path
from xefm.text_viewer import show_text_viewer


def _key(name=None, char=None, mods=frozenset()):
    return Event(type=EventType.KEY, key=name, char=char, modifiers=mods)


def _drag(panel, x0, y0, x1, y1):
    panel.dispatch_event(Event(type=EventType.MOUSE_DOWN, x=float(x0), y=float(y0)))
    panel.dispatch_event(Event(type=EventType.MOUSE_DRAG, x=float(x1), y=float(y1)))
    panel.dispatch_event(Event(type=EventType.MOUSE_UP, x=float(x1), y=float(y1)))


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=60, height=12, capabilities=request.param)


@pytest.fixture
def text_file(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("hello world\nsecond line\nthird line here\n")
    return Path(str(p))


@pytest.fixture
def md_file(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("# Heading One\n\nSome **bold** text and a [link](http://x.com).\n")
    return Path(str(p))


def _open(panel, path):
    v = show_text_viewer(panel, path)
    panel.render()
    return v


# --- raw text mode ------------------------------------------------------------


def test_drag_selects_and_copies_plain(backend, text_file):
    panel = Panel(backend)
    v = _open(panel, text_file)
    bx0, by0, _, _ = v._body_rect
    gx = bx0 + v._content_x  # left edge of the content column
    _drag(panel, gx, by0, gx + 5, by0)             # "hello"
    assert v._sel.range() == ((0, 0), (0, 5))
    panel.dispatch_event(_key("c", "c", frozenset({"cmd"})))
    assert backend.get_clipboard() == "hello"


def test_multiline_selection(backend, text_file):
    panel = Panel(backend)
    v = _open(panel, text_file)
    bx0, by0, _, _ = v._body_rect
    gx = bx0 + v._content_x
    _drag(panel, gx + 6, by0, gx + 6, by0 + 1)     # "world" .. "second"
    panel.dispatch_event(_key("c", "c", frozenset({"ctrl"})))
    assert backend.get_clipboard() == "world\nsecond"


def test_select_all(backend, text_file):
    panel = Panel(backend)
    v = _open(panel, text_file)
    panel.dispatch_event(_key("a", "a", frozenset({"cmd"})))
    panel.dispatch_event(_key("c", "c", frozenset({"cmd"})))
    assert backend.get_clipboard() == "hello world\nsecond line\nthird line here"


def test_press_outside_body_clears_selection(backend, text_file):
    panel = Panel(backend)
    v = _open(panel, text_file)
    panel.dispatch_event(_key("a", "a", frozenset({"cmd"})))
    assert v._sel.range() is not None
    # A press up in the header row (y=0) clears the selection.
    panel.dispatch_event(Event(type=EventType.MOUSE_DOWN, x=1.0, y=0.0))
    assert v._sel.range() is None


# --- rich (Markdown) mode -----------------------------------------------------


def test_rich_mode_forwards_selection_and_copy(md_file):
    backend = MemoryBackend(width=60, height=12, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    v = _open(panel, md_file)
    panel.dispatch_event(_key("m", "m"))            # toggle to Markdown
    panel.render()
    assert v.mode == "rich" and v._rich_widget.selectable
    bx0, by0, _, _ = v._body_rect
    _drag(panel, bx0, by0, bx0 + 200, by0)          # across the heading row
    assert v._rich_widget.selection_text() == "Heading One"
    panel.dispatch_event(_key("c", "c", frozenset({"cmd"})))
    assert backend.get_clipboard() == "Heading One"
