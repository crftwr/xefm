"""Highlighted rows stay aligned with the source lines (issue #417).

Pygments preprocesses its input before lexing, and by default it strips the
blank lines off the top and bottom of a file. A file that opened with a blank
line therefore drew every row one line too high, while the gutter numbers, the
selection, the search highlight and the copied text all still indexed the
viewer's own ``lines``: the text you saw belonged to the line below the one a
click on it selected.

Run with: python -m pytest test/test_viewer_highlight_alignment.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend

from xefm.path import Path
from xefm.text_viewer import _highlight, show_text_viewer


def _row_text(row) -> str:
    return "".join(text for text, _ in row)


@pytest.mark.parametrize("name, lines", [
    # The file attached to issue #417: a blank line, then content.
    ("selection-issue.txt", ["", "aaa", "bbb"]),
    ("a.py", ["", "", "x = 1", "y = 2", ""]),
    ("b.py", ["  indented = 1", "z = 2"]),          # stripall would eat the indent
    ("c.md", ["", "# Title", "", "text"]),
    ("d.json", ["", "{", '  "a": 1', "}"]),
    ("e.c", ["", "int main() {}", ""]),
    ("f.txt", ["", "", ""]),                        # nothing but blanks
    ("g.txt", ["aあb", "", "c"]),                    # wide characters
])
def test_row_i_holds_line_i(name, lines):
    rows = _highlight(lines, Path("/tmp/" + name))
    assert len(rows) == len(lines)
    assert [_row_text(r) for r in rows] == lines


def test_syntax_colors_survive_the_alignment_check():
    """The rows are still *colored* — a lexer whose output can't be aligned falls
    back to plain text, so alignment must not be bought by losing the palette."""
    rows = _highlight(["", "def f(x):", "    return 1"], Path("/tmp/a.py"))
    assert any(fg is not None for row in rows for _, fg in row)


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=60, height=12, capabilities=request.param)


@pytest.fixture
def blank_first_line(tmp_path):
    p = tmp_path / "selection-issue.txt"
    p.write_text("\naaa\nbbb\n")
    return Path(str(p))


def test_selecting_the_text_you_see_copies_that_text(backend, blank_first_line):
    """End to end: find the screen row that shows ``aaa``, drag across it, copy —
    and get ``aaa``, not the blank line above it."""
    panel = Panel(backend)
    viewer = show_text_viewer(panel, blank_first_line)
    panel.render()
    screen = backend.snapshot()
    row = next(y for y, line in enumerate(screen) if "aaa" in line)
    assert "2" in screen[row].split("aaa")[0]      # drawn against its own number
    bx0, _, _, _ = viewer._body_rect
    gx = bx0 + viewer._content_x
    panel.dispatch_event(Event(type=EventType.MOUSE_DOWN, x=gx, y=float(row)))
    panel.dispatch_event(Event(type=EventType.MOUSE_DRAG, x=gx + 3, y=float(row)))
    panel.dispatch_event(Event(type=EventType.MOUSE_UP, x=gx + 3, y=float(row)))
    panel.dispatch_event(Event(type=EventType.KEY, key="c", char="c",
                               modifiers=frozenset({"cmd"})))
    assert backend.get_clipboard() == "aaa"
