"""Terminal sessions in the desktop app (#900): everything run in XeFM's
terminal is one - the subshell, a terminal program, a shell from the list.

The registry on its own, then the app's methods against a stand-in panel
(libghostty is not installed where the tests run, so a stand-in view plays
the terminal), then what terminal mode does instead."""

from types import SimpleNamespace

from xefm.app import XeFMApp
from xefm.terminal_sessions import FILES, PROGRAM, SHELL, Session, SessionRegistry


# --- the registry ------------------------------------------------------------------

class _View:
    def __init__(self, exited=False, shell=True, busy=False):
        self._exited = exited
        self.shown = False
        self.closing = False
        self.closed = 0
        self.label = "zsh"
        self.shell = shell
        self._busy = busy

    @property
    def running(self):
        return self._exited is False

    @property
    def busy(self):
        return self.running and (self._busy or not self.shell)

    @property
    def exit_code(self):
        return None if self._exited is False else self._exited

    def close(self):
        self.closed += 1


def _session(registry, name="zsh", **kw):
    return registry.add(Session(view=_View(**kw), kind=SHELL, name=name, cwd="/tmp"))


def test_screens_come_most_recently_on_screen_first():
    reg = SessionRegistry()
    assert reg.screens() == [FILES]
    a = _session(reg)
    reg.touch(a)
    b = _session(reg, "zsh 2")
    reg.touch(b)
    assert reg.screens() == [b, a, FILES]
    reg.touch(FILES)
    assert reg.screens() == [FILES, b, a]
    reg.touch(a)
    assert reg.screens() == [a, FILES, b]
    reg.remove(a)
    assert reg.screens() == [FILES, b]
    reg.remove(b)
    assert reg.screens() == [FILES] and len(reg) == 0


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


def test_busy_is_a_program_or_a_shell_in_a_command():
    reg = SessionRegistry()
    _session(reg, "idle")
    working = _session(reg, "working", busy=True)
    program = reg.add(Session(view=_View(shell=False), kind=PROGRAM, name="vim", cwd="/"))
    _session(reg, "gone", exited=0)
    assert reg.busy() == [working, program]


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
    app.config = SimpleNamespace(SUBSHELL=["/bin/zsh"])
    app.log_info = app.logged.append
    app.active_pane = lambda: {"path": "/tmp"}
    app._is_local = lambda p: True
    app._terminal_unavailable = lambda: None
    app.remote_sessions = []
    app._with_remote_env = lambda env, session: (app.remote_sessions.append(session),
                                                 env.update(XEFM_SESSION=session))[1] or env
    app._shell_launch = lambda: (["/bin/zsh"], {"XEFM_ACTIVE": "1",
                                                "XEFM_THIS_DIR": "/tmp"})
    app.handed = []
    app._run_in_terminal = lambda argv, cwd=None, env=None, pause_on_error=False: \
        app.handed.append((argv, cwd, env)) or 0

    def relist(pane, keep_visible=False):
        app.relisted += 1
    app._relist = relist
    app.made = []

    def make(argv, *, cwd, env, label, shell):
        view = _View(shell=shell)
        view.argv, view.cwd, view.env = argv, cwd, env
        app.made.append(view)
        return view
    app._make_session_view = make
    for name in ("new_terminal_session", "subshell", "_show_session",
                 "_hide_session", "_shown_session", "_close_session",
                 "_session_exited", "_session_close_request", "_start_session",
                 "_new_shell_session", "_terminal_ready", "_desktop_only",
                 "_session_dir", "_push_terminal", "_close_terminal_sessions",
                 "_relist_both", "terminal_sessions"):
        setattr(app, name, getattr(XeFMApp, name).__get__(app))
    return app


class _Switcher:
    """show_filter_list's stand-in: what the list offers, and Enter."""

    def __init__(self, monkeypatch):
        import xefm.app as app_mod
        self.calls = []
        monkeypatch.setattr(app_mod, "show_filter_list", self._show)

    def _show(self, panel, items, **kw):
        dialog = SimpleNamespace(list=SimpleNamespace(selected=0), items=items, kw=kw)
        self.calls.append(dialog)
        return dialog

    @property
    def last(self):
        return self.calls[-1]

    def labels(self):
        return [self.last.kw["to_label"](i) for i in self.last.items]

    def enter(self):
        """Accept the row the cursor starts on."""
        dialog = self.last
        dialog.kw["on_accept"](dialog.items[dialog.list.selected])


def test_the_switcher_goes_back_and_forth_with_enter(monkeypatch):
    app = _app(monkeypatch)
    switcher = _Switcher(monkeypatch)
    app.terminal_sessions()  # no session yet: the cursor is on New shell
    assert switcher.labels() == ["File manager", "New shell in /tmp"]
    switcher.enter()
    [view] = app.made
    assert view.shown and app.panel.widgets == [view] and view.cwd == "/tmp"
    app.terminal_sessions()  # from the session: the file manager is next
    assert switcher.labels()[:2] == ["zsh - /tmp", "File manager"]
    switcher.enter()  # hide: still running, layer gone
    assert not view.shown and view.closed == 0 and app.panel.widgets == []
    assert app.relisted == 2
    app.terminal_sessions()  # from the panes: the session is next
    assert switcher.labels()[:2] == ["File manager", "zsh - /tmp"]
    switcher.enter()
    assert app.made == [view] and view.shown


def test_the_switcher_offers_the_screen_before_this_one(monkeypatch):
    app = _app(monkeypatch)
    switcher = _Switcher(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    first, second = app.made
    app.terminal_sessions()  # in the second: the first was on before it
    assert switcher.last.items[:3] == [app._sessions.for_view(second),
                                       app._sessions.for_view(first), FILES]
    switcher.enter()
    assert first.shown and not second.shown
    # The file manager and the new-shell row cannot be closed.
    remove = switcher.last.kw["on_remove"]
    assert remove(FILES) is False and remove(switcher.last.items[-1]) is False


def test_the_subshell_is_a_session_with_the_snapshot_and_xefmctl(monkeypatch):
    app = _app(monkeypatch)
    app.subshell()
    [view] = app.made
    [session] = app._sessions
    assert session.kind == SHELL and view.shown and view.cwd == "/tmp"
    # The XEFM_* snapshot as of the start, and xefmctl as this session.
    assert view.env["XEFM_THIS_DIR"] == "/tmp"
    assert view.env["XEFM_SESSION"] == str(session.id)
    app.subshell()  # another one, not the same shell again
    assert len(app.made) == 2


def test_terminal_mode_hands_the_terminal_to_the_subshell(monkeypatch):
    app = _app(monkeypatch, desktop=False)
    app.subshell()
    assert not app.made and len(app._sessions) == 0
    [(argv, cwd, env)] = app.handed
    assert argv == ["/bin/zsh"] and cwd == "/tmp" and env["XEFM_SESSION"] == "subshell"


def test_terminal_mode_has_no_switcher(monkeypatch):
    app = _app(monkeypatch, desktop=False)
    app.terminal_sessions()
    assert not app.made and not app.handed
    assert all("only in the desktop app" in line for line in app.logged)


def test_without_libghostty_nothing_opens_and_the_log_says_why(monkeypatch):
    app = _app(monkeypatch)
    app._terminal_unavailable = lambda: "libghostty-vt is not installed"
    app.subshell()
    assert not app.made
    assert "libghostty-vt is not installed" in app.logged[-1]


def test_showing_another_session_replaces_the_one_on_screen(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    first, second = app.made
    assert app.panel.widgets == [second] and not first.shown
    assert [s.name for s in app._sessions][1].endswith(" 2")
    app._show_session(app._sessions.for_view(first))
    assert app.panel.widgets == [first] and not second.shown
    assert app._sessions.screens()[0].view is first


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


def test_a_program_session_reports_when_it_ends_shown_or_hidden(monkeypatch):
    app = _app(monkeypatch)
    done = []
    session = app._start_session(["vim", "f"], cwd="/tmp", env={}, name="vim",
                                 shell=False, on_done=done.append)
    assert session.kind == PROGRAM and session.view.shown
    app._hide_session(session.view)
    session.view._exited = 0
    app._session_exited(session.view, 0)  # exits while hidden
    assert done == [0] and len(app._sessions) == 0


def test_a_failed_program_out_of_view_waits_for_the_user(monkeypatch):
    app = _app(monkeypatch)
    done = []
    session = app._start_session(["make"], cwd="/tmp", env={}, name="make",
                                 shell=False, on_done=done.append)
    app._hide_session(session.view)
    session.view._exited = 2
    app._session_exited(session.view, 2)
    assert done == [] and session.attention == ("failed", "make: failed (2)")
    app._session_close_request(session.view)  # closed from the list or the view
    assert done == [2]


def test_quitting_hangs_up_every_session(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    app._close_terminal_sessions()
    assert len(app._sessions) == 0 and all(v.closed == 1 for v in app.made)


def test_quit_asks_only_while_a_session_is_busy(monkeypatch):
    import xefm.app as app_mod
    asked = []
    monkeypatch.setattr(app_mod, "show_message_box",
                        lambda panel, text, **kw: asked.append((text, kw)))
    reg = SessionRegistry()
    _session(reg, "idle")  # a shell at its prompt: no reason to ask
    _session(reg, busy=True)
    quit_calls = []
    app = SimpleNamespace(_quit_confirming=False, _sessions=reg, panel=_Panel(),
                          _busy_tasks=lambda: [], _quit=lambda: quit_calls.append(1))
    XeFMApp.confirm_quit(app, only_if_busy=True)
    assert not quit_calls and asked and "terminal session" in asked[0][0]
    asked[0][1]["on_result"]("Quit")
    assert quit_calls == [1]
    # Only idle shells: Cmd-Q quits at once.
    idle = SessionRegistry()
    _session(idle)
    app = SimpleNamespace(_quit_confirming=False, _sessions=idle,
                          panel=_Panel(), _busy_tasks=lambda: [],
                          _quit=lambda: quit_calls.append(2))
    XeFMApp.confirm_quit(app, only_if_busy=True)
    assert quit_calls == [1, 2]
