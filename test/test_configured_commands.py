"""One marking for every command in config.py (#900): ``TEXT_EDITOR``,
``TEXT_DIFF``, ``FILE_ASSOCIATIONS`` verbs and ``PROGRAMS`` all take
``'terminal': True / False``, and run the same way for it in both modes.

- True: terminal mode hands the terminal over; the desktop app runs a terminal
  session.
- False: the background in both modes, never waited for, output to the log.
- Unmarked: terminal mode hands over, the desktop app starts it in the
  background."""

import os
import sys
import time
from unittest.mock import patch

import pytest

from test_customization_api import app_with, config_with  # noqa: F401
from xefm import config as xc
from xefm import external_programs as ep


# --- reading the marking ------------------------------------------------------------

@pytest.mark.parametrize("value, terminal", [
    ("vim", None), (["code", "--wait"], None),
    ({"command": "vim", "terminal": True}, True),
    ({"command": ["code"], "terminal": False}, False),
    ({"command": "vim"}, None),
])
def test_command_terminal(value, terminal):
    assert ep.command_terminal(value) is terminal


def test_programs_take_the_marking_in_the_entry_or_its_options():
    assert ep.program_wants_terminal({"name": "a", "command": ["x"], "terminal": True})
    assert ep.program_wants_terminal({"name": "a", "command": ["x"],
                                      "options": {"terminal": True}})
    assert not ep.program_wants_terminal({"name": "a", "command": ["x"]})
    # The entry's own key wins over the older spelling.
    assert not ep.program_wants_terminal({"name": "a", "command": ["x"], "terminal": False,
                                          "options": {"terminal": True}})
    entry = xc._program_entry({"name": "a", "command": ["x"], "terminal": True})
    assert entry["options"]["terminal"] is True


def test_file_associations_take_a_marked_command(monkeypatch):
    rules = [
        {"pattern": "*.log", "view": {"command": ["less"], "terminal": True}},
        {"pattern": "*.txt", "open": "code -n", "edit": {"command": "subl", "terminal": False}},
        {"pattern": "*.mp4", "view": {"action": "preview.show"}},
    ]
    monkeypatch.setattr(xc, "get_file_associations", lambda: rules)
    assert xc.get_command_for_file("a.log", "view") == (["less"], True)
    assert xc.get_command_for_file("a.txt", "open") == (["code", "-n"], None)
    assert xc.get_command_for_file("a.txt", "edit") == (["subl"], False)
    assert xc.get_program_for_file("a.log", "view") == ["less"]
    # A command is not an action, and an action is not a command.
    assert xc.get_action_for_file("a.log", "view") is None
    assert xc.get_command_for_file("a.mp4", "view") is None


def test_terminal_in_config_is_reported_as_unused():
    from xefm._config import Config
    from xefm.config import ConfigManager

    class UserConfig(Config):
        TERMINAL = ["open", "-a", "iTerm"]

    errors = ConfigManager().validate_config(UserConfig())
    assert any("TERMINAL is no longer used" in e for e in errors)
    assert not any("TERMINAL" in e for e in ConfigManager().validate_config(Config()))


# --- running it -----------------------------------------------------------------------

def _run(app, terminal, *, desktop):
    with patch("xefm.app.is_desktop_mode", return_value=desktop), \
            patch.object(app, "_terminal_unavailable", return_value=None), \
            patch.object(app, "_run_in_terminal", return_value=0) as handed, \
            patch.object(app, "_start_session") as session, \
            patch("xefm.app.subprocess.Popen") as popen:
        app._run_configured(["tool", "-x"], ["/f"], terminal=terminal, subject="f")
    if handed.called:
        return "hand-over"
    if session.called:
        return "session"
    if popen.called:
        return "background"
    return None


@pytest.mark.parametrize("terminal, desktop, way", [
    (True, False, "hand-over"), (True, True, "session"),
    (False, False, "background"), (False, True, "background"),
    (None, False, "hand-over"), (None, True, "background"),
])
def test_one_rule_for_both_modes(app_with, terminal, desktop, way):
    app, _ = app_with()
    assert _run(app, terminal, desktop=desktop) == way


def test_a_background_command_may_outlive_xefm(app_with):
    """An editor left open survives XeFM's exit: its own session, SIGPIPE
    left ignored (no death when the log pane's pipe breaks)."""
    app, _ = app_with()
    with patch("xefm.app.is_desktop_mode", return_value=True), \
            patch("xefm.app.subprocess.Popen") as popen:
        assert app._run_configured(["code"], ["/f"], terminal=None, subject="f")
    kwargs = popen.call_args.kwargs
    if os.name != "nt":
        assert kwargs["start_new_session"] and kwargs["restore_signals"] is False
    assert popen.call_args.args[0][-1] == "/f"


def test_a_missing_command_is_not_started(app_with):
    app, _ = app_with()
    with patch("xefm.app.is_desktop_mode", return_value=True):
        assert not app._run_configured(["/no/such/xefm-tool"], [], terminal=False,
                                       subject="f")


def test_the_exit_is_the_program_s_not_its_pipes(app_with):
    """A launcher that leaves a child holding its output (``code``) is done
    when it exits, not when the child closes the pipe."""
    app, _ = app_with()
    got = []
    script = ("import subprocess, sys; "
              "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])")
    started = time.monotonic()
    with patch("xefm.app.is_desktop_mode", return_value=True):
        app._run_configured([sys.executable, "-c", script], [], terminal=False,
                            subject="launcher", on_exit=got.append)
    deadline = time.monotonic() + 8
    while not got and time.monotonic() < deadline:
        app._pump_later()
        time.sleep(0.02)
    assert got == [0] and time.monotonic() - started < 8


# --- TEXT_DIFF from the viewers ---------------------------------------------------------

def test_the_directory_diff_merge_does_not_block_the_desktop_app(app_with, tmp_path):
    """The merge used to wait for TEXT_DIFF inside a suspended backend - the
    desktop window froze on `code --diff --wait`. Now it goes through the
    app's launcher and rescans when the tool exits."""
    from types import SimpleNamespace

    from xefm import directory_diff_viewer as ddv
    app, _ = app_with()
    calls = []
    left, right = tmp_path / "l", tmp_path / "r"
    viewer = SimpleNamespace(
        _config=SimpleNamespace(TEXT_DIFF={"command": ["code", "--diff", "--wait"],
                                           "terminal": False}),
        _panel=SimpleNamespace(_layers=[], backend=None),
        _notify=calls.append, _render=lambda: None,
        _node_rel_path=lambda node: "f.txt")
    viewer._current = lambda: SimpleNamespace(
        is_directory=False, type_mismatch=False, left_path=left, right_path=right)
    viewer._panel._layers.append(SimpleNamespace(widget=viewer))
    rescans = []
    viewer._restart_scan = lambda: rescans.append(1)
    with patch.object(app, "_run_configured") as runner:
        ep.set_configured_runner(runner)
        ddv.DirectoryDiffView._edit_merge(viewer)
    argv, args = runner.call_args.args
    assert argv == ["code", "--diff", "--wait"] and args == [str(left), str(right)]
    assert runner.call_args.kwargs["terminal"] is False
    runner.call_args.kwargs["on_exit"](0)
    assert rescans == [1] and not calls
