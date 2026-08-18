"""Text viewer selection drag held past an edge keeps scrolling.

A selection can only reach the rows the pointer can touch; dragging below the
body (or above it) scrolls the text under the pointer so the selection runs
past one screenful (issue #320). The scroll is time-based (one rate across a
60fps GUI tick and a terminal's slower one), so these tests drive a fake clock
rather than real elapsed time — the same harness PuiKit's LogView uses.

Run with: python -m pytest test/test_viewer_drag_scroll.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend
from puikit.widgets import _input

from xefm.path import Path
from xefm.text_viewer import show_text_viewer


class _Clock:
    """A monotonic clock the test advances by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(_input.time, "monotonic", c)
    return c


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=40, height=10, capabilities=request.param)


@pytest.fixture
def long_file(tmp_path):
    p = tmp_path / "long.txt"
    p.write_text("".join(f"line{i}\n" for i in range(60)))
    return Path(str(p))


def _open(panel, path):
    v = show_text_viewer(panel, path)
    panel.render()
    return v


def _down(panel, x, y):
    panel.dispatch_event(Event(type=EventType.MOUSE_DOWN, x=float(x), y=float(y),
                              button="left"))


def _drag(panel, x, y):
    panel.dispatch_event(Event(type=EventType.MOUSE_DRAG, x=float(x), y=float(y),
                              button="left"))


def _run_ticks(backend, clock, count=12):
    for _ in range(count):
        clock.advance(1 / 60)
        backend.run_animation_ticks()


def test_drag_below_the_body_scrolls_and_extends(backend, clock, long_file):
    panel = Panel(backend)
    v = _open(panel, long_file)
    _down(panel, 3, 1)
    # Drag well below the window: the Panel clamps the coordinate onto the edge,
    # so the selection alone would stop at the last visible line.
    _drag(panel, 6, 40)
    reached = v._sel.cursor[0]
    assert v.top == 0.0
    _run_ticks(backend, clock)
    assert v.top > 0.0
    assert v._sel.cursor[0] > reached
    text = v._sel.text(v.lines)
    assert text.startswith("line0")
    assert "line8" in text  # past the ~8-row body the pointer could reach


def test_drag_above_the_body_scrolls_back_up(backend, clock, long_file):
    panel = Panel(backend)
    v = _open(panel, long_file)
    v.top = 30.0
    panel.render()
    _down(panel, 3, 6)
    _drag(panel, 3, -8)
    _run_ticks(backend, clock)
    assert v.top < 30.0
    assert v._sel.text(v.lines) != ""


def test_edge_scroll_stops_at_the_end_of_the_file(backend, clock, long_file):
    panel = Panel(backend)
    v = _open(panel, long_file)
    _down(panel, 3, 1)
    _drag(panel, 6, 40)
    _run_ticks(backend, clock, count=400)
    assert v.top == float(len(v.lines) - v._view_h)
    # Against the end, the timer retires instead of re-rendering forever.
    assert v._edge_scroll.active is False


def test_release_stops_the_edge_scroll(backend, clock, long_file):
    panel = Panel(backend)
    v = _open(panel, long_file)
    _down(panel, 3, 1)
    _drag(panel, 6, 40)
    panel.dispatch_event(Event(type=EventType.MOUSE_UP, x=6.0, y=40.0,
                               button="left"))
    assert v._edge_scroll.active is False
    at_release = v.top
    _run_ticks(backend, clock)
    assert v.top == at_release


def test_drag_back_inside_stops_scrolling(backend, clock, long_file):
    panel = Panel(backend)
    v = _open(panel, long_file)
    _down(panel, 3, 1)
    _drag(panel, 6, 40)
    _run_ticks(backend, clock)
    scrolled = v.top
    assert scrolled > 0.0
    _drag(panel, 6, 3)  # pointer back over the body
    assert v._edge_scroll.active is False
    _run_ticks(backend, clock)
    assert v.top == scrolled


def test_drag_inside_the_body_does_not_scroll(backend, clock, long_file):
    panel = Panel(backend)
    v = _open(panel, long_file)
    _down(panel, 3, 1)
    _drag(panel, 6, 4)
    _run_ticks(backend, clock)
    assert v.top == 0.0
    assert v._sel.text(v.lines) != ""
