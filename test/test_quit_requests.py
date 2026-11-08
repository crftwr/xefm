"""Two ways to quit, two rules for asking.

The ``quit`` action (Q, the File menu's Quit) always asks. The platform's own
ways — the macOS application menu's Quit and the Dock's, the window's close
button, and keys bound to ``quit_app`` (Cmd-Q on macOS and Alt-F4 on
Windows under the OS native preset) — ask only while a task is running, in
front or in the background, and otherwise quit at once. Either way XeFM goes
out through ``_quit``: hooks, job cancel, state save.
"""

import os
import sys
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from test_customization_api import app_with  # noqa: E402,F401
from xefm.config import KeyBindings  # noqa: E402


def _layers(app):
    return len(app.panel._layers)


def _busy(app):
    """Pretend a task is running."""
    return patch.object(app, "_busy_tasks", return_value=[object()])


def test_an_idle_platform_request_quits_at_once(app_with):
    app, _tmp = app_with()
    with patch.object(app, "_quit") as quit_:
        assert app.backend._quit_request() is True     # XeFM took it
    assert quit_.called
    assert not app.panel.has_layers                    # nothing was asked


def test_a_busy_platform_request_asks_first(app_with):
    app, _tmp = app_with()
    with _busy(app), patch.object(app, "_quit") as quit_:
        app.backend._quit_request()
    assert not quit_.called
    assert app.panel.has_layers and app._quit_confirming


def test_the_quit_action_always_asks(app_with):
    app, _tmp = app_with()
    with patch.object(app, "_quit") as quit_:
        app.dispatch("quit")
    assert not quit_.called
    assert app.panel.has_layers and app._quit_confirming


def test_a_second_request_does_not_stack_a_second_confirm(app_with):
    app, _tmp = app_with()
    with _busy(app):
        app.backend._quit_request()
        before = _layers(app)
        app.backend._quit_request()
        app.dispatch("quit")
    assert _layers(app) == before


def test_answering_quit_stops_the_tasks_and_runs_the_whole_quit(app_with):
    app, _tmp = app_with()
    shown = []
    with _busy(app), patch("xefm.app.show_message_box", lambda *a, **k: shown.append(k)), \
            patch.object(app.tasks, "cancel_all", return_value=True) as cancel, \
            patch.object(app, "_quit") as quit_:
        app.backend._quit_request()
        shown[0]["on_result"]("Quit")
    assert cancel.called and quit_.called
    assert not app._quit_confirming


def test_cancel_leaves_xefm_running_and_ready_to_ask_again(app_with):
    app, _tmp = app_with()
    shown = []
    with _busy(app), patch("xefm.app.show_message_box", lambda *a, **k: shown.append(k)), \
            patch.object(app, "_quit") as quit_:
        app.backend._quit_request()
        shown[0]["on_result"]("Cancel")
        app.backend._quit_request()
    assert not quit_.called
    assert len(shown) == 2


def test_a_foreground_task_counts_as_busy(app_with):
    app, _tmp = app_with()
    from xefm.task import Task
    task = Task("Copying", config=app.config)
    with patch.object(app.tasks, "active_tasks", return_value=[task]):
        assert app._busy_tasks() == [task]


def test_quitting_runs_once(app_with):
    """Alt-F4 can arrive both as a key and as the close request."""
    app, _tmp = app_with()
    with patch.object(app, "_save_application_state") as save, \
            patch.object(app.backend, "quit"):
        app._quit()
        app._quit()
    assert save.call_count == 1


def test_the_menu_shows_the_key_for_quitting_the_platform_way(app_with):
    app, _tmp = app_with()
    assert app.backend._quit_shortcut == app._quit_shortcut()
    app.keys = KeyBindings({"quit_app": ["Command-Q"], "quit": ["Ctrl-Q"]})
    assert app._quit_shortcut() == "Cmd-Q"
    app.keys = KeyBindings({"quit_app": []})
    assert app._quit_shortcut() is None


def test_a_keymap_rebuild_updates_the_menus_quit_key(app_with):
    app, _tmp = app_with()
    with patch.object(app, "_quit_shortcut", return_value="Cmd-Q"):
        app._rebuild_keymap()
    assert app.backend._quit_shortcut == "Cmd-Q"


# --------------------------------------------------------------------------- #
# quit_app keys work over a dialog or a viewer, as the close button does
# --------------------------------------------------------------------------- #

def _cmd_q():
    from puikit import Event, EventType
    return Event(type=EventType.KEY, key="q", char=None, modifiers=frozenset({"cmd"}))


def _with_cmd_q(app):
    from xefm import keymap_presets
    app.keys = KeyBindings(dict(keymap_presets.table(keymap_presets.AFX), quit_app=["Command-Q"]))


def test_cmd_q_quits_over_an_open_dialog(app_with):
    app, _tmp = app_with()
    _with_cmd_q(app)
    app.dispatch("help")
    assert app.panel.has_layers
    with patch.object(app, "_quit") as quit_:
        app.on_event(_cmd_q())
    assert quit_.called


def test_cmd_q_over_a_dialog_still_asks_while_busy(app_with):
    app, _tmp = app_with()
    _with_cmd_q(app)
    app.dispatch("help")
    with _busy(app), patch.object(app, "_quit") as quit_:
        app.on_event(_cmd_q())
    assert not quit_.called and app._quit_confirming


def test_cmd_q_does_nothing_where_the_keymap_does_not_bind_it(app_with):
    app, _tmp = app_with()
    app.keys = KeyBindings({"quit_app": []})
    with patch.object(app, "_quit") as quit_:
        app.on_event(_cmd_q())
    assert not quit_.called
