"""Syntax coloring of the file viewer's raw text stays off the UI thread's path.

A file is colored on its first raw-mode frame, not when the viewer is built, so
one that opens rendered (Markdown in rich mode) never pays for it; a large file
is colored on a worker thread and drawn plain until the colors land.

Run with: python -m pytest test/test_text_viewer_highlight.py -v
"""

import time

import pytest

from puikit import Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI, CapabilityProfile
from puikit.backends.memory_backend import MemoryBackend

from xefm import text_viewer
from xefm.path import Path
from xefm.text_viewer import TextViewer, show_text_viewer

MD = "\n\n".join(["# Title"] + [f"Paragraph {i} with `code` text." for i in range(40)])
PY = "\n".join(f"def f{i}():\n    return {i}" for i in range(40))


@pytest.fixture
def md_file(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(MD)
    return Path(str(p))


@pytest.fixture
def py_file(tmp_path):
    p = tmp_path / "mod.py"
    p.write_text(PY)
    return Path(str(p))


def _colored(viewer) -> bool:
    return any(fg is not None for row in viewer.highlighted for _, fg in row)


def _wait(cond, pump, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_building_the_viewer_colors_nothing(py_file):
    v = TextViewer(py_file)
    assert not _colored(v)
    assert len(v.highlighted) == len(v.lines)


def test_rich_mode_never_colors_the_source(md_file):
    panel = Panel(MemoryBackend(width=80, height=24, capabilities=PROFILE_TUI))
    v = show_text_viewer(panel, md_file)
    v._toggle_view_mode()
    panel.render()
    assert v.mode == "rich"
    assert v._highlight_for is None
    assert not _colored(v)


def test_small_file_is_colored_in_its_first_raw_frame(py_file):
    panel = Panel(MemoryBackend(width=80, height=24, capabilities=PROFILE_TUI))
    v = show_text_viewer(panel, py_file)
    panel.render()
    assert v.mode == "text"
    assert _colored(v)


def test_large_file_is_colored_on_a_worker_tui(py_file, monkeypatch):
    monkeypatch.setattr(text_viewer, "_SYNC_HIGHLIGHT_CHARS", 0)
    backend = MemoryBackend(width=80, height=24, capabilities=PROFILE_TUI)
    panel = Panel(backend)
    v = show_text_viewer(panel, py_file)
    panel.render()
    assert v._highlight_ticking  # the terminal drains the result on a tick
    assert _wait(lambda: _colored(v), backend.run_animation_ticks)
    assert not v._highlight_ticking


def test_large_file_is_colored_on_a_worker_gui(py_file, monkeypatch):
    monkeypatch.setattr(text_viewer, "_SYNC_HIGHLIGHT_CHARS", 0)
    backend = MemoryBackend(width=80, height=24, capabilities=PROFILE_GUI_DESKTOP)
    posted = []
    monkeypatch.setattr(backend, "call_on_main_thread", posted.append, raising=False)
    panel = Panel(backend)
    v = show_text_viewer(panel, py_file)
    panel.render()

    def pump():
        while posted:
            posted.pop(0)()

    assert _wait(lambda: _colored(v), pump)


def test_still_backend_colors_synchronously(py_file, monkeypatch):
    monkeypatch.setattr(text_viewer, "_SYNC_HIGHLIGHT_CHARS", 0)
    still = CapabilityProfile(PROFILE_TUI, animation_ticks=False)
    panel = Panel(MemoryBackend(width=80, height=24, capabilities=still))
    v = show_text_viewer(panel, py_file)
    panel.render()
    assert _colored(v)


def test_colors_for_replaced_lines_are_dropped(py_file):
    v = TextViewer(py_file)
    stale_lines = v.lines
    v.lines = list(v.lines)  # a reload replaces the list
    v._highlight_ready = (stale_lines, [[("x", (1, 2, 3))]] * len(stale_lines))
    v._take_highlight()
    assert not _colored(v)
    assert v._highlight_done_for is None
