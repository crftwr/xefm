"""Markdown (rich) view mode of the built-in file viewer.

The modal text viewer opens ``*.md`` files in raw text and toggles to a rendered
Markdown view in place (PuiKit's ``MarkdownView``), via the ``toggle_view_mode``
action. The rich-renderer registry (``xefm.viewer_registry``) is the seam future
formatted viewers (JSON, CSV, …) plug into. See
doc/dev/MARKDOWN_VIEWER_IMPLEMENTATION.md.

Run with: python -m pytest test/test_markdown_viewer.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend

from xefm.path import Path
from xefm.text_viewer import TextViewer, show_text_viewer
from xefm.viewer_registry import RichRenderer, rich_renderer_for


# Blocks are blank-line separated (joined with "\n\n") so each stays its own
# block — consecutive non-blank lines would otherwise collapse into one wrapped
# paragraph. 60 paragraphs guarantees the document overflows the viewport.
MD_BODY = "\n\n".join(
    [
        "# Title",
        "Some **bold** and *italic* text with a [link](https://example.com).",
        "- one\n- two",
        "```python\nprint('hi')\n```",
    ]
    + [f"Paragraph number {i} with a little text." for i in range(60)]
)


def _key(name=None, char=None):
    return Event(type=EventType.KEY, key=name, char=char)


@pytest.fixture
def md_file(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text(MD_BODY)
    return Path(str(p))


@pytest.fixture
def txt_file(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("plain\nlines\nhere\n")
    return Path(str(p))


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=100, height=30, capabilities=request.param)


# --- registry ----------------------------------------------------------------


def test_registry_maps_markdown_extensions():
    for name in ("a.md", "b.MD", "c.markdown"):
        r = rich_renderer_for(Path(name))
        assert isinstance(r, RichRenderer)
        assert r.name == "Markdown"


def test_registry_no_renderer_for_plain_types():
    for name in ("a.txt", "b.py", "c.log", "plain"):
        assert rich_renderer_for(Path(name)) is None


# --- viewer defaults ---------------------------------------------------------


def test_markdown_file_opens_in_raw_text(md_file):
    v = TextViewer(md_file)
    assert v.mode == "text"          # raw by default (per the chosen UX)
    assert v._rich is not None       # a renderer is available to toggle to
    assert v._rich_widget is None    # but not built until first switch


def test_plain_file_has_no_rich_renderer(txt_file):
    v = TextViewer(txt_file)
    assert v._rich is None
    v._toggle_view_mode()            # nothing to toggle to — stays raw
    assert v.mode == "text"
    assert v._rich_widget is None


# --- toggling ----------------------------------------------------------------


def test_toggle_builds_and_caches(backend, md_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file)
    panel.render()                   # first draw captures the content colors
    assert v.mode == "text"

    v._toggle_view_mode()
    assert v.mode == "rich"
    assert type(v._rich_widget).__name__ == "MarkdownView"
    assert v._rich_widget._sems      # source parsed into semantic blocks


def test_rich_widget_resolves_images_against_file_directory(backend, md_file):
    # The built MarkdownView carries the file's own directory, so a relative
    # image path (``![x](docs/images/a.png)``) resolves as GitHub renders it,
    # not against XeFM's process CWD.
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file)
    panel.render()
    v._toggle_view_mode()
    assert v._rich_widget.base_dir == str(md_file.parent)

    built = v._rich_widget
    v._toggle_view_mode()
    assert v.mode == "text"
    v._toggle_view_mode()
    assert v.mode == "rich"
    assert v._rich_widget is built   # built once, cached (each mode keeps scroll)


def test_toggle_via_key_event(backend, md_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file)
    panel.render()
    assert v.handle_event(_key("m", "m")) is True
    assert v.mode == "rich"
    assert v.handle_event(_key("m", "m")) is True
    assert v.mode == "text"


# --- drawing / event forwarding ---------------------------------------------


def test_draw_both_modes_no_crash(backend, md_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file)
    panel.render()                   # raw mode draws
    v._toggle_view_mode()
    panel.render()                   # rich mode draws the embedded MarkdownView
    assert type(panel._layers[-1].widget).__name__ == "TextViewer"


def test_rich_mode_forwards_scroll(backend, md_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file)
    panel.render()
    v._toggle_view_mode()
    panel.render()                   # lay the document out so it knows it overflows
    mv = v._rich_widget
    assert mv.offset == 0.0
    # A downward notch (negative scroll) is forwarded to the embedded view.
    v.handle_event(Event(type=EventType.MOUSE_SCROLL, scroll=-5))
    assert mv.offset > 0.0


def test_quit_closes_from_rich_mode(backend, md_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, md_file)
    panel.render()
    v._toggle_view_mode()
    panel.render()
    assert type(panel._layers[-1].widget).__name__ == "TextViewer"
    v.handle_event(_key("escape"))
    assert not panel.has_layers or type(panel._layers[-1].widget).__name__ != "TextViewer"


# --- incremental search in rich (Markdown) mode ------------------------------
#
# The ``search`` binding opens the shared ISearchBar in rich mode too; the viewer
# delegates the match set / scrolling / highlighting to the embedded MarkdownView
# (issue #213). The MarkdownView's own search behavior is covered exhaustively in
# PuiKit's test_markdown_view.py; these check the viewer wires it up.


def _type(panel, text):
    for ch in text:
        panel.dispatch_event(_key(ch, ch))


def _into_rich(panel, md_file):
    v = show_text_viewer(panel, md_file)
    panel.render()
    v._toggle_view_mode()
    panel.render()                       # lay the document out (knows it overflows)
    assert v.mode == "rich"
    return v


def test_rich_search_opens_and_matches(backend, md_file):
    panel = Panel(backend)
    v = _into_rich(panel, md_file)

    panel.dispatch_event(_key("f", "f"))             # 'search' binding
    panel.render()
    assert v._isearch.active
    assert type(panel._layers[-1].widget).__name__ == "ISearchBar"

    _type(panel, "paragraph")                        # 60 "Paragraph number N" blocks
    panel.render()
    mv = v._rich_widget
    assert mv._search_pattern == "paragraph"
    assert mv._search_rows                           # matched some display rows
    assert v._search_status() == mv.search_status()  # counter delegates
    assert v._search_status()[0] >= 1


def test_rich_search_navigation_moves_offset(backend, md_file):
    panel = Panel(backend)
    v = _into_rich(panel, md_file)
    mv = v._rich_widget

    panel.dispatch_event(_key("f", "f"))
    _type(panel, "paragraph")
    panel.render()
    assert len(mv._search_rows) >= 3
    first_off = mv.offset
    panel.dispatch_event(_key("down"))               # next match
    panel.render()
    assert mv._search_pos == 1
    assert mv.offset >= first_off
    panel.dispatch_event(_key("up"))                 # back to first
    panel.render()
    assert mv._search_pos == 0


def test_rich_search_cancel_restores_and_clears(backend, md_file):
    panel = Panel(backend)
    v = _into_rich(panel, md_file)
    mv = v._rich_widget
    assert mv.offset == 0.0

    panel.dispatch_event(_key("f", "f"))
    _type(panel, "paragraph")
    panel.dispatch_event(_key("down"))               # scroll away from the origin
    panel.render()
    assert mv.offset > 0.0
    panel.dispatch_event(_key("escape"))             # cancel -> restore + clear
    panel.render()
    assert not v._isearch.active
    assert mv._search_pattern == "" and mv._search_rows == []
    assert mv.offset == 0.0                           # pre-search origin restored
    assert type(panel._layers[-1].widget).__name__ == "TextViewer"


def test_rich_search_accept_keeps_position(backend, md_file):
    panel = Panel(backend)
    v = _into_rich(panel, md_file)
    mv = v._rich_widget

    panel.dispatch_event(_key("f", "f"))
    _type(panel, "paragraph")
    panel.dispatch_event(_key("down"))
    panel.render()
    kept = mv.offset
    assert kept > 0.0
    panel.dispatch_event(_key("enter"))              # accept -> keep scroll, clear
    panel.render()
    assert not v._isearch.active
    assert mv._search_pattern == "" and mv._search_rows == []
    assert mv.offset == kept


def test_rich_search_no_match_status_zero(backend, md_file):
    panel = Panel(backend)
    v = _into_rich(panel, md_file)
    mv = v._rich_widget

    panel.dispatch_event(_key("f", "f"))
    _type(panel, "zzz-no-such-text")
    panel.render()
    assert mv._search_rows == []
    assert v._search_status() == (0, 0)
    assert mv.offset == 0.0                           # nothing matched: origin kept


def test_search_key_ignored_by_renderer_in_rich_mode(backend, md_file):
    # The viewer must intercept the search key before forwarding to the renderer,
    # so search opens rather than being swallowed as an unknown key.
    panel = Panel(backend)
    v = _into_rich(panel, md_file)
    assert not v._isearch.active
    handled = v.handle_event(_key("f", "f"))
    assert handled is True
    assert v._isearch.active
