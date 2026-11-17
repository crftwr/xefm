"""A full-window viewer replaces the screen it covers by crossing it (#900):
opening, the viewer fades in while what it covers - the file manager, or the
viewer it was opened from - fades out quickly; closing, the reverse, and the
layer leaves only once it has faded. No scale: growing out of the screen
showed the window's edge."""

import pytest
from puikit import PROFILE_GUI_DESKTOP, PROFILE_TUI, Panel
from puikit.backends.memory_backend import MemoryBackend
from puikit.widgets import Label

from anim_helper import settle
from xefm.dialog_geometry import VIEWER_FADE_IN_MS, VIEWER_FADE_OUT_MS
from xefm.text_viewer import show_text_viewer


@pytest.fixture
def opened(tmp_path):
    def make(profile=PROFILE_GUI_DESKTOP, extras=None):
        path = tmp_path / "a.txt"
        path.write_text("hello\n")
        backend = MemoryBackend(width=60, height=20, capabilities=profile)
        panel = Panel(backend)
        if extras:
            panel.theme.extras.update(extras)
        panel.add(Label("PANES"), x=0, y=0, w=10, h=1)
        viewer = show_text_viewer(panel, path)
        return backend, panel, viewer
    return make


def _hints(backend, widget):
    """What the backend was asked to play for ``widget``, without the
    completion hook PuiKit's Panel adds to every moving transition."""
    return [{k: v for k, v in h.items() if k != "on_complete"}
            for w, h in backend.animate_calls if w is widget]


def _base_hints(backend, panel):
    return _hints(backend, panel.base)


def test_opening_fades_in_while_the_file_manager_fades_out_quickly(opened):
    backend, panel, viewer = opened()
    [mine] = _hints(backend, viewer)
    [base] = _base_hints(backend, panel)
    assert mine == {"transition": "fade", "duration_ms": VIEWER_FADE_IN_MS}
    assert base == {"transition": "fade", "out": True, "duration_ms": VIEWER_FADE_OUT_MS}
    assert VIEWER_FADE_OUT_MS < VIEWER_FADE_IN_MS


def test_closing_fades_out_quickly_while_the_file_manager_fades_in(opened):
    backend, panel, viewer = opened()
    settle(panel)
    backend.animate_calls.clear()
    viewer._close()
    assert panel._layers[-1].widget is viewer  # still there while it fades out
    [mine] = _hints(backend, viewer)
    [base] = _base_hints(backend, panel)
    assert mine["transition"] == "fade" and mine["out"]
    assert mine["duration_ms"] == VIEWER_FADE_OUT_MS
    assert base == {"transition": "fade", "duration_ms": VIEWER_FADE_IN_MS}
    viewer._close()  # a second close while leaving does nothing
    assert len([1 for w, _h in backend.animate_calls if w is viewer]) == 1
    settle(panel)
    assert not panel.has_layers
    panel.render()
    assert "PANES" in backend.snapshot()[0]


def test_a_viewer_opened_from_another_crosses_that_one(opened, tmp_path):
    backend, panel, viewer = opened()
    settle(panel)
    backend.animate_calls.clear()
    upper = show_text_viewer(panel, tmp_path / "a.txt")
    faded = [w for w, h in backend.animate_calls if h.get("out")]
    assert faded == [viewer]  # the viewer beneath, not the hidden file manager
    settle(panel)
    backend.animate_calls.clear()
    upper._close()
    back = [w for w, h in backend.animate_calls if w is not upper]
    assert back == [viewer]
    settle(panel)
    assert panel._layers[-1].widget is viewer


def test_without_motion_both_happen_at_once(opened):
    backend, panel, viewer = opened(extras={"dialog_effect": False})
    assert not _base_hints(backend, panel)
    viewer._close()
    assert not panel.has_layers


def test_on_a_terminal_it_still_closes(opened):
    backend, panel, viewer = opened(profile=PROFILE_TUI)
    settle(panel)
    viewer._close()
    settle(panel)
    assert not panel.has_layers
    panel.render()
    assert "PANES" in backend.snapshot()[0]
