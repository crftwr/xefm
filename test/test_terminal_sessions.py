"""Persistent terminal sessions - the console (#900).

The registry on its own, then the app's methods against a stand-in panel
(libghostty is not installed where the tests run, so a stand-in view plays
the terminal), then where terminal mode opens a console of its own."""

from types import SimpleNamespace

import pytest

from xefm import external_terminal
from xefm.app import XeFMApp
from xefm.terminal_sessions import SHELL, Session, SessionRegistry


# --- the registry ------------------------------------------------------------------

class _View:
    def __init__(self, exited=False):
        self._exited = exited
        self.shown = False
        self.closing = False
        self.closed = 0
        self.label = "zsh"

    @property
    def running(self):
        return self._exited is False

    @property
    def exit_code(self):
        return None if self._exited is False else self._exited

    def close(self):
        self.closed += 1


def _session(registry, name="zsh", **kw):
    return registry.add(Session(view=_View(**kw), kind=SHELL, name=name, cwd="/tmp"))


def test_the_last_one_used_is_the_one_the_toggle_returns_to():
    reg = SessionRegistry()
    a = _session(reg)
    b = _session(reg, "zsh 2")
    assert reg.last is b
    reg.touch(a)
    assert reg.last is a
    reg.remove(a)
    assert reg.last is b
    reg.remove(b)
    assert reg.last is None and len(reg) == 0


def test_names_stay_apart():
    reg = SessionRegistry()
    assert reg.next_name("zsh") == "zsh"
    _session(reg, "zsh")
    assert reg.next_name("zsh") == "zsh 2"
    _session(reg, "zsh 2")
    assert reg.next_name("zsh") == "zsh 3"


def test_state_and_running():
    reg = SessionRegistry()
    live = _session(reg)
    failed = _session(reg, "b", exited=2)
    clean = _session(reg, "c", exited=0)
    assert live.state == "running"
    assert failed.state == "exited (2)" and clean.state == "exited"
    assert reg.running() == [live]
    assert reg.for_view(failed.view) is failed


# --- the app ------------------------------------------------------------------------

class _Panel:
    def __init__(self):
        self.backend = SimpleNamespace(size_units=(100.0, 40.0))
        self.base = object()
        self.theme = SimpleNamespace(extras={"dialog_effect": False})
        self._layers = []
        self.removed = []

    def push_layer(self, widget, z, hints=None, reflow=None):
        self._layers.append(SimpleNamespace(widget=widget, z=z))

    def remove_layer(self, widget):
        self.removed.append(widget)
        self._layers = [s for s in self._layers if s.widget is not widget]
        return True

    def animate(self, widget, hints=None):
        return False  # no motion: every transition lands at once

    def render(self):
        pass

    @property
    def widgets(self):
        return [s.widget for s in self._layers]


def _app(monkeypatch, *, desktop=True):
    import xefm.app as app_mod
    monkeypatch.setattr(app_mod, "is_desktop_mode", lambda: desktop)
    panel = _Panel()
    app = SimpleNamespace(panel=panel, relisted=0, logged=[], _sessions=SessionRegistry())
    app.pm = SimpleNamespace(left_pane="L", right_pane="R")
    app._TERMINAL_Z = XeFMApp._TERMINAL_Z
    app.config = SimpleNamespace(TERMINAL=None, SUBSHELL=None)
    app.log_info = app.logged.append
    app.active_pane = lambda: {"path": "/tmp"}
    app._is_local = lambda p: True
    app._terminal_unavailable = lambda: None

    def relist(pane, keep_visible=False):
        app.relisted += 1
    app._relist = relist
    app.made = []

    def make(argv, *, cwd, env, label):
        view = _View()
        view.argv, view.cwd, view.env = argv, cwd, env
        app.made.append(view)
        return view
    app._make_session_view = make
    for name in ("toggle_terminal", "new_terminal_session", "_show_session",
                 "_hide_session", "_shown_session", "_close_session",
                 "_session_exited", "_session_close_request", "_console_env",
                 "_console_dir", "_push_terminal", "_close_terminal_sessions",
                 "_open_console_elsewhere"):
        setattr(app, name, getattr(XeFMApp, name).__get__(app))
    return app


def test_the_toggle_starts_a_shell_then_hides_and_shows_the_same_one(monkeypatch):
    app = _app(monkeypatch)
    app.toggle_terminal()
    [view] = app.made
    assert view.shown and app.panel.widgets == [view]
    assert view.cwd == "/tmp"
    app.toggle_terminal()  # hide: still running, layer gone
    assert not view.shown and view.closed == 0 and app.panel.widgets == []
    assert app.relisted == 2
    app.toggle_terminal()  # back: the same session, no new one
    assert app.made == [view] and view.shown


def test_a_console_shell_gets_no_stale_selection(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    env = app.made[0].env
    assert env["XEFM_ACTIVE"] == "1"
    assert not any(k.endswith(("_SELECTED", "_FOCUSED", "_DIR")) and k.startswith("XEFM_")
                   for k in env)


def test_showing_another_session_replaces_the_one_on_screen(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    first, second = app.made
    assert app.panel.widgets == [second] and not first.shown
    assert [s.name for s in app._sessions][1].endswith(" 2")
    app._show_session(app._sessions.for_view(first))
    assert app.panel.widgets == [first] and not second.shown
    assert app._sessions.last.view is first


def test_a_clean_exit_ends_the_session_a_failure_keeps_it(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    a, b = app.made
    b._exited = 3
    app._session_exited(b, 3)
    assert app._sessions.for_view(b) is not None and b.closed == 0
    assert app.logged and "code 3" in app.logged[-1]
    a._exited = 0
    app._session_exited(a, 0)
    assert app._sessions.for_view(a) is None and a.closed == 1


def test_quitting_hangs_up_every_session(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    app._close_terminal_sessions()
    assert len(app._sessions) == 0 and all(v.closed == 1 for v in app.made)


def test_quit_asks_while_a_session_runs(monkeypatch):
    import xefm.app as app_mod
    asked = []
    monkeypatch.setattr(app_mod, "show_message_box",
                        lambda panel, text, **kw: asked.append((text, kw)))
    reg = SessionRegistry()
    _session(reg)
    quit_calls = []
    app = SimpleNamespace(_quit_confirming=False, _sessions=reg, panel=_Panel(),
                          _busy_tasks=lambda: [], _quit=lambda: quit_calls.append(1))
    XeFMApp.confirm_quit(app, only_if_busy=True)
    assert not quit_calls and asked and "terminal session" in asked[0][0]
    asked[0][1]["on_result"]("Quit")
    assert quit_calls == [1]
    # Nothing running: Cmd-Q quits at once.
    app = SimpleNamespace(_quit_confirming=False, _sessions=SessionRegistry(),
                          panel=_Panel(), _busy_tasks=lambda: [],
                          _quit=lambda: quit_calls.append(2))
    XeFMApp.confirm_quit(app, only_if_busy=True)
    assert quit_calls == [1, 2]


def test_terminal_mode_opens_the_console_through_terminal(monkeypatch):
    app = _app(monkeypatch, desktop=False)
    launched = []
    monkeypatch.setattr(external_terminal, "launch_in_terminal",
                        lambda terminal, argv, **kw: launched.append((terminal, argv, kw)))
    monkeypatch.setattr(external_terminal, "terminal_mode_default",
                        lambda cwd, environ=None: ["tmux", "new-window", "-c", cwd])
    app.toggle_terminal()
    assert not app.made
    [(terminal, _argv, kw)] = launched
    assert terminal == ["tmux", "new-window", "-c", "/tmp"] and kw["cwd"] == "/tmp"


# --- terminal mode's default for a window of its own --------------------------------

@pytest.mark.parametrize("environ, expected", [
    ({"TMUX": "/tmp/tmux-1/default,1,0"}, ["tmux", "new-window", "-c", "/w"]),
    ({"WEZTERM_PANE": "3"}, ["wezterm", "cli", "spawn", "--cwd", "/w", "--"]),
    ({"KITTY_WINDOW_ID": "1"}, ["kitty", "@", "launch", "--type=tab", "--cwd", "/w"]),
    ({"SSH_CONNECTION": "1.2.3.4 5 6.7.8.9 22"}, None),
    ({"TMUX": "x", "SSH_TTY": "/dev/ttys001"}, ["tmux", "new-window", "-c", "/w"]),
])
def test_terminal_mode_default(environ, expected):
    assert external_terminal.terminal_mode_default("/w", environ) == expected


def test_terminal_mode_default_falls_back_to_the_platform(monkeypatch):
    monkeypatch.setattr(external_terminal, "default_terminal", lambda: ["open", "-a", "Terminal"])
    assert external_terminal.terminal_mode_default("/w", {}) == ["open", "-a", "Terminal"]


def test_terminal_set_in_config_wins_in_both_modes():
    config = SimpleNamespace(TERMINAL=["alacritty", "-e"])
    assert external_terminal.terminal_command(config, terminal_mode=True, cwd="/w") \
        == ["alacritty", "-e"]
    assert external_terminal.terminal_command(config) == ["alacritty", "-e"]
