"""Shell integration in XeFM's terminal and what the sessions do with it
(#900): the injected startup files, a real zsh read through libghostty, and
the status bar's word from a hidden session."""

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
    commands = []
    term = G.Terminal(80, 24, write_pty=lambda b: proc.write(b),
                      on_semantic_prompt=lambda k, c, cmd: (events.append((k, c)),
                                                            commands.append((k, cmd))))
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
        # The command line came with the output mark, as typed (#954).
        ran = [cmd for k, cmd in commands if k == T.OUTPUT_START]
        assert ran and ran[0].startswith('print -r -- "$FROM_RC|$ZDOTDIR"')
        assert ran[0].endswith("sleep 0.3; false")
        rc, zdotdir = open(result).read().strip().split("|")
        # The user's .zshrc ran, and ZDOTDIR is the user's again afterwards.
        assert rc == "yes" and zdotdir == home
    finally:
        proc.close()
        term.close()


def _bash_44():
    bash = shutil.which("bash")
    if bash is None or sys.platform == "win32":
        return None
    import subprocess
    try:
        ver = subprocess.run([bash, "-c", "echo ${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        major, minor = (int(x) for x in ver.split("."))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return bash if (major, minor) >= (4, 4) else None


@pytest.mark.skipif(_bash_44() is None or _libghostty() is None,
                    reason="needs bash 4.4+, a pty and a libghostty with prompt marks")
def test_bash_sends_the_command_line_with_its_mark(tmp_path):
    G, _pty = _libghostty()
    home = str(tmp_path)
    env = dict(os.environ, HOME=home, PS1="$ ")
    argv = SI.apply([_bash_44(), "-i"], env)
    out = queue.Queue()
    commands = []
    term = G.Terminal(80, 24, write_pty=lambda b: proc.write(b),
                      on_semantic_prompt=lambda k, c, cmd: commands.append((k, cmd)))
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
        proc.write(b"echo 50%; true\r")
        pump(lambda: any(k == T.COMMAND_END for k, _ in commands))
        ran = [cmd for k, cmd in commands if k == T.OUTPUT_START]
        assert ran == ["echo 50%; true"]
    finally:
        proc.close()
        term.close()


# --- hidden sessions -----------------------------------------------------------------

class _View:
    def __init__(self, *, idle=False, running=True, started=True, shown=False):
        self.argv = ["/bin/zsh"]
        self.idle_at_prompt = idle
        self.running = running
        self.started = started
        self.shown = shown
        self.closing = False


def _app(monkeypatch, *, desktop=True):
    import xefm.app as app_mod
    monkeypatch.setattr(app_mod, "is_desktop_mode", lambda: desktop)
    app = SimpleNamespace(_sessions=SessionRegistry(), logged=[])
    app.panel = SimpleNamespace(render=lambda: None)
    app.log_info = app.logged.append
    app._LONG_COMMAND_S = 10.0
    for name in ("_session_prompt", "_session_notification", "_session_progress",
                 "_session_parts"):
        setattr(app, name, getattr(XeFMApp, name).__get__(app))
    return app


def _add(app, view, name="zsh"):
    return app._sessions.add(Session(view=view, kind=SHELL, name=name, cwd="/w d"))


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
