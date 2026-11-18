"""Shell integration in XeFM's terminal and what the console does with it
(#900): the injected startup files, a real zsh read through libghostty,
typing at the prompt only while the shell is idle there, and the status bar's
word from a hidden session."""

import os
import queue
import shutil
import sys
import time
from types import SimpleNamespace

import pytest

from xefm import shell_integration as SI
from xefm import terminal as T
from xefm.app import XeFMApp
from xefm.terminal_sessions import SHELL, Session, SessionRegistry


# --- argv and environment ----------------------------------------------------------

def test_zsh_gets_xefm_s_zdotdir_and_keeps_the_user_s():
    env = {"ZDOTDIR": "/u/zdot"}
    assert SI.apply(["/bin/zsh", "-l"], env) == ["/bin/zsh", "-l"]
    assert os.path.isfile(os.path.join(env["ZDOTDIR"], ".zshrc"))
    assert env["XEFM_USER_ZDOTDIR"] == "/u/zdot"
    env = {}
    SI.apply(["zsh"], env)
    assert "XEFM_USER_ZDOTDIR" not in env  # the user's default: $HOME


def test_bash_gets_an_rcfile_and_a_login_shell_its_profile_order():
    env = {}
    argv = SI.apply(["/bin/bash"], env)
    assert argv[:2] == ["/bin/bash", "--rcfile"] and os.path.isfile(argv[2])
    assert "XEFM_BASH_LOGIN" not in env
    argv = SI.apply(["bash", "-l", "-i"], env)
    assert argv[1] == "--rcfile" and "-l" not in argv and argv[-1] == "-i"
    assert env["XEFM_BASH_LOGIN"] == "1"


@pytest.mark.parametrize("argv", [
    ["bash", "-c", "make"], ["zsh", "-lc", "make"], ["bash", "--norc"],
    ["bash", "--rcfile", "mine"], ["fish"], ["cmd.exe"], ["pwsh"], [],
])
def test_left_alone(argv):
    env = {}
    assert SI.apply(list(argv), env) == argv and env == {}


# --- a real zsh, read through libghostty --------------------------------------------

def _libghostty():
    try:
        from puikit import _ghostty as G
        from puikit import _pty
    except ImportError:
        return None
    if G.load() is None or not _pty.SUPPORTED or not hasattr(G.Terminal, "at_prompt"):
        return None
    return G, _pty


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("zsh") is None
                    or _libghostty() is None,
                    reason="needs zsh, a pty and a libghostty with prompt marks")
def test_zsh_marks_its_prompt_and_keeps_the_user_s_startup(tmp_path):
    G, _pty = _libghostty()
    home = str(tmp_path)
    with open(os.path.join(home, ".zshrc"), "w") as f:
        f.write("PROMPT='mine%# '\nexport FROM_RC=yes\n")
    env = dict(os.environ, HOME=home)
    env.pop("ZDOTDIR", None)
    argv = SI.apply(["zsh"], env)
    out = queue.Queue()
    events = []
    term = G.Terminal(80, 24, write_pty=lambda b: proc.write(b),
                      on_semantic_prompt=lambda k, c, cmd: events.append((k, c)))
    proc = _pty.PtyProcess(argv, cols=80, rows=24, cwd=home, env=env,
                           term_program=None, on_output=out.put,
                           on_exit=lambda code: out.put(None))

    def pump(until, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data = out.get(timeout=0.05)
            except queue.Empty:
                data = b""
            if data is None:
                return
            if data:
                term.write(data)
            if until():
                return

    try:
        pump(term.at_prompt)
        assert term.at_prompt()
        result = os.path.join(home, "result")
        proc.write(f'print -r -- "$FROM_RC|$ZDOTDIR" > {result}; sleep 0.3; false\r'
                   .encode())
        pump(lambda: not term.at_prompt(), timeout=5)
        assert not term.at_prompt()  # the command runs: no typing now
        pump(lambda: (T.COMMAND_END, 1) in events)
        pump(term.at_prompt)
        assert term.at_prompt() and (T.COMMAND_END, 1) in events
        rc, zdotdir = open(result).read().strip().split("|")
        # The user's .zshrc ran, and ZDOTDIR is the user's again afterwards.
        assert rc == "yes" and zdotdir == home
    finally:
        proc.close()
        term.close()


# --- the console ----------------------------------------------------------------------

class _View:
    def __init__(self, *, idle=False, running=True, started=True, shown=False):
        self.argv = ["/bin/zsh"]
        self.idle_at_prompt = idle
        self.running = running
        self.started = started
        self.shown = shown
        self.closing = False
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def _app(monkeypatch, *, desktop=True):
    import xefm.app as app_mod
    monkeypatch.setattr(app_mod, "is_desktop_mode", lambda: desktop)
    pane = {"path": "/w d", "files": ["/w d/a b", "/w d/c"],
            "selected_files": {"/w d/c"}, "focused_index": 0}
    app = SimpleNamespace(_sessions=SessionRegistry(), logged=[], clip=[], shown=[],
                          started=0, rendered=0)
    app.panel = SimpleNamespace(set_clipboard=app.clip.append,
                                render=lambda: None)
    app.config = SimpleNamespace(SUBSHELL=["/bin/zsh"])
    app.log_info = app.logged.append
    app.active_pane = lambda: pane
    app._is_local = lambda p: "://" not in str(p)
    app._terminal_unavailable = lambda: None
    app._show_session = lambda s: app.shown.append(s)
    app._shown_session = lambda: None
    app._LONG_COMMAND_S = 10.0
    for name in ("_console_type", "_console_type_to_clipboard", "insert_into_console",
                 "cd_console_here", "_shell_quote", "_selection_paths",
                 "_session_prompt", "_session_notification", "_session_progress",
                 "_session_parts"):
        setattr(app, name, getattr(XeFMApp, name).__get__(app))
    return app


def _add(app, view, name="zsh"):
    return app._sessions.add(Session(view=view, kind=SHELL, name=name, cwd="/w d"))


def test_typed_only_while_idle_at_the_prompt(monkeypatch):
    app = _app(monkeypatch)
    view = _View(idle=True)
    session = _add(app, view)
    app.insert_into_console()
    assert view.sent == ["'/w d/c' "] and app.shown == [session] and not app.clip
    app.cd_console_here()
    assert view.sent[-1] == "cd '/w d'"


def test_a_busy_shell_gets_the_clipboard_instead(monkeypatch):
    app = _app(monkeypatch)
    view = _View(idle=False)
    session = _add(app, view)
    session.command_since = time.monotonic()
    app.insert_into_console()
    assert not view.sent and app.clip == ["'/w d/c' "]
    assert "not at its prompt" in app.logged[-1]


def test_a_shell_xefm_cannot_read_gets_the_clipboard(monkeypatch):
    app = _app(monkeypatch)
    _add(app, _View(idle=False))
    app.insert_into_console()
    assert app.clip and "cannot tell" in app.logged[-1]


def test_a_console_still_starting_gets_it_at_its_first_prompt(monkeypatch):
    app = _app(monkeypatch)
    view = _View(started=False)
    session = _add(app, view)
    app.insert_into_console()
    assert session.pending_insert == "'/w d/c' " and not view.sent
    view.idle_at_prompt = True
    app._session_prompt(view, T.INPUT_START, None)
    assert view.sent == ["'/w d/c' "] and session.pending_insert == ""


def test_nothing_selected_types_the_item_under_the_cursor(monkeypatch):
    app = _app(monkeypatch)
    app.active_pane()["selected_files"].clear()
    view = _View(idle=True)
    _add(app, view)
    app.insert_into_console()
    assert view.sent == ["'/w d/a b' "]


def test_terminal_mode_uses_the_clipboard(monkeypatch):
    app = _app(monkeypatch, desktop=False)
    app.insert_into_console()
    assert app.clip == ["'/w d/c' "] and "TERMINAL" in app.logged[-1]


def test_cmd_quoting():
    app = SimpleNamespace()
    assert XeFMApp._shell_quote(app, r"C:\a b", ["cmd.exe"]) == '"C:\\a b"'
    assert XeFMApp._shell_quote(app, "plain", ["cmd.exe"]) == "plain"


def test_a_long_command_ending_out_of_view_is_news(monkeypatch):
    app = _app(monkeypatch)
    view = _View()
    session = _add(app, view)
    app._session_prompt(view, T.OUTPUT_START, None)
    session.command_since -= 60
    app._session_prompt(view, T.COMMAND_END, 2)
    assert session.attention == ("failed", "zsh: failed (2)")
    assert app._session_parts() == [("failed", "zsh: failed (2)")]
    # A short one is not.
    session.attention = None
    app._session_prompt(view, T.OUTPUT_START, None)
    app._session_prompt(view, T.COMMAND_END, 0)
    assert session.attention is None
    # Nor is anything on screen.
    view.shown = True
    app._session_prompt(view, T.OUTPUT_START, None)
    session.command_since -= 60
    app._session_prompt(view, T.COMMAND_END, 0)
    assert session.attention is None


def test_notifications_and_progress_out_of_view(monkeypatch):
    app = _app(monkeypatch)
    view = _View()
    session = _add(app, view)
    app._session_progress(view, T.PROGRESS_SET, 40)
    assert app._session_parts() == [("busy", "zsh 40%")]
    app._session_notification(view, "", "build done")
    assert session.attention == ("attention", "zsh: build done")
    assert app._session_parts() == [("attention", "zsh: build done")]
    app._session_progress(view, T.PROGRESS_REMOVE, None)
    assert session.progress is None
