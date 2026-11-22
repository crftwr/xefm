"""TERMINAL_CTRL_CLIPBOARD: Ctrl+C / Ctrl+V copy and paste in the desktop
app's terminal on Windows, or go to the program.

PuiKit's TerminalView turns them on for Windows by default; the setting can
only turn them off there, never on elsewhere (Ctrl+V is a program's key on
macOS and Linux)."""

import sys
from types import SimpleNamespace

import pytest

from xefm import terminal
from xefm.app import XeFMApp

pytestmark = pytest.mark.skipif(
    terminal._PuiKitTerminalView is None
    or "ctrl_clipboard" not in terminal._PuiKitTerminalView.__init__.__code__.co_varnames,
    reason="this PuiKit's TerminalView has no ctrl_clipboard")


def _view(**kwargs):
    return terminal.TerminalView(
        ["true"], cwd=".", env={}, label="t", on_exited=lambda v, c: None,
        on_close_request=lambda v: None, **kwargs)


def test_on_keeps_puikits_default_windows_only():
    assert _view().ctrl_clipboard is (sys.platform == "win32")
    assert _view(ctrl_clipboard=True).ctrl_clipboard is (sys.platform == "win32")


def test_off_gives_both_keys_to_the_program():
    assert _view(ctrl_clipboard=False).ctrl_clipboard is False


def test_the_session_view_reads_the_setting():
    def app(**config):
        stub = SimpleNamespace(config=SimpleNamespace(**config))
        for name in ("_session_exited", "_session_close_request", "screens", "_run_terminal_user_action", "_session_prompt",
                     "_session_title", "_session_notification", "_session_progress"):
            setattr(stub, name, lambda *a, **k: None)
        return stub

    make = XeFMApp._make_session_view
    off = make(app(TERMINAL_CTRL_CLIPBOARD=False), ["true"], cwd=".", env={},
               label="t", shell=True)
    assert off.ctrl_clipboard is False
    unset = make(app(), ["true"], cwd=".", env={}, label="t", shell=True)
    assert unset.ctrl_clipboard is (sys.platform == "win32")
