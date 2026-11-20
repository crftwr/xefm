"""Terminal sessions in the desktop app (#900): everything run in XeFM's
terminal is one - the subshell, a terminal program, a shell from the list.

The registry on its own, then the app's methods against a PuiKit Panel on
the memory backend (libghostty is not installed where the tests run, so a
stand-in view plays the terminal), then what terminal mode does instead.
Screens (#951) are groups in the Panel's layer tree."""

from types import SimpleNamespace

from xefm.app import XeFMApp
from puikit import Panel
from puikit.backends.memory_backend import MemoryBackend

from xefm.screens import FILES, ScreenManager
from xefm.terminal_sessions import PROGRAM, SHELL, Session, SessionRegistry


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

def _panel():
    panel = Panel(MemoryBackend(width=100, height=40))
    panel.render = lambda: None  # the stand-in views draw nothing
    return panel


def _shown(panel):
    """The layers drawn now, bottom first."""
    return panel.shown_layers()


def _app(monkeypatch, *, desktop=True):
    import xefm.app as app_mod
    monkeypatch.setattr(app_mod, "is_desktop_mode", lambda: desktop)
    import xefm.dialog_geometry as geometry
    # No motion: every transition lands at once (test_terminal_transition
    # plays them).
    monkeypatch.setattr(geometry, "animate_from_behind", lambda *a, **k: False)
    panel = _panel()
    app = SimpleNamespace(panel=panel, relisted=0, logged=[], _sessions=SessionRegistry(),
                          _screens=ScreenManager(panel))
    app.pm = SimpleNamespace(left_pane="L", right_pane="R")
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
    app._run_terminal_user_action = lambda name: True
    for name in ("new_terminal_session", "subshell", "_show_session", "_show_screen",
                 "_hide_session", "_shown_session", "_close_session",
                 "_session_exited", "_session_close_request", "_start_session",
                 "_new_shell_session", "_terminal_ready", "_desktop_only",
                 "_session_dir", "_close_terminal_sessions", "_screen_label",
                 "_screen_top_text", "_relist_both", "screens"):
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
    app.screens()  # no session yet: the cursor is on New shell
    assert switcher.labels() == ["File manager", "New shell in /tmp"]
    switcher.enter()
    [view] = app.made
    assert view.shown and _shown(app.panel) == [view] and view.cwd == "/tmp"
    app.screens()  # from the session: the file manager is next
    assert switcher.labels()[:2] == ["zsh - /tmp", "File manager"]
    switcher.enter()  # back to the panes: still running, its screen hidden
    assert not view.shown and view.closed == 0 and _shown(app.panel) == []
    assert app.panel.has_layer(view)  # kept, not removed
    assert app.relisted == 2
    app.screens()  # from the panes: the session is next
    assert switcher.labels()[:2] == ["File manager", "zsh - /tmp"]
    switcher.enter()
    assert app.made == [view] and view.shown


def test_the_switcher_offers_the_screen_before_this_one(monkeypatch):
    app = _app(monkeypatch)
    switcher = _Switcher(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    first, second = app.made
    app.screens()  # in the second: the first was on before it
    s1, s2 = (app._sessions.for_view(v) for v in (first, second))
    assert switcher.last.items[:3] == [s2.screen, s1.screen, app._screens.files]
    switcher.enter()
    assert first.shown and not second.shown
    # The file manager and the new-shell row cannot be closed.
    remove = switcher.last.kw["on_remove"]
    assert remove(app._screens.files) is False and remove(switcher.last.items[-1]) is False


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
    app.screens()
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
    assert _shown(app.panel) == [second] and not first.shown
    assert [s.name for s in app._sessions][1].endswith(" 2")
    app._show_session(app._sessions.for_view(first))
    assert _shown(app.panel) == [first] and not second.shown
    assert app._screens.recent()[0].session.view is first


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
    app = SimpleNamespace(_quit_confirming=False, _sessions=reg, panel=_panel(),
                          _busy_tasks=lambda: [], _quit=lambda: quit_calls.append(1))
    XeFMApp.confirm_quit(app, only_if_busy=True)
    assert not quit_calls and asked and "terminal session" in asked[0][0]
    asked[0][1]["on_result"]("Quit")
    assert quit_calls == [1]
    # Only idle shells: Cmd-Q quits at once.
    idle = SessionRegistry()
    _session(idle)
    app = SimpleNamespace(_quit_confirming=False, _sessions=idle,
                          panel=_panel(), _busy_tasks=lambda: [],
                          _quit=lambda: quit_calls.append(2))
    XeFMApp.confirm_quit(app, only_if_busy=True)
    assert quit_calls == [1, 2]


# --- screens (#951) -------------------------------------------------------------------

def test_closing_a_terminal_goes_back_to_the_screen_before_it(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    first, second = app.made
    second._exited = 0
    app._session_exited(second, 0)  # the second ends: back to the first, at once
    assert app._screens.current.session.view is first and first.shown
    assert _shown(app.panel) == [first]
    first._exited = 0
    app._session_exited(first, 0)
    assert app._screens.current is app._screens.files and _shown(app.panel) == []


def test_a_session_started_out_of_view_runs_without_coming_on(monkeypatch):
    app = _app(monkeypatch)
    started = []
    real = app._make_session_view

    def make(*a, **k):
        view = real(*a, **k)
        view.start = lambda panel: started.append(panel)
        return view
    app._make_session_view = make
    session = app._new_shell_session("/tmp", show=False)
    assert started == [app.panel] and not session.view.shown
    assert app._screens.current is app._screens.files
    assert app._screens.recent()[-1] is session.screen  # last until first shown


def test_a_dialog_on_a_hidden_screen_can_close_itself(monkeypatch):
    app = _app(monkeypatch)
    progress = object()
    app.panel.push_layer(progress, z=70)  # opened over the panes
    app.new_terminal_session()
    assert app.panel.has_layer(progress) and not app.panel.is_layer_shown(progress)
    assert app.panel.remove_layer(progress)  # it finished out of view
    app._show_screen(app._screens.files)
    assert _shown(app.panel) == []


def test_the_switcher_says_what_is_on_each_screen(monkeypatch):
    app = _app(monkeypatch)
    switcher = _Switcher(monkeypatch)
    viewer = _Viewer(path="/tmp/notes.txt")
    app.panel.push_layer(viewer, z=80)
    app.new_terminal_session()
    [view] = app.made
    session = app._sessions.for_view(view)
    session.command_since, session.command = 1.0, "make test"
    app.screens()
    assert switcher.labels()[:2] == ["zsh - make test - /tmp",
                                     "File manager - viewing notes.txt"]


def test_activity_reads_the_command_then_the_foreground_then_the_title():
    reg = SessionRegistry()
    view = _View()
    s = reg.add(Session(view=view, kind=SHELL, name="zsh", cwd="/tmp", program="zsh"))
    assert s.activity == "" and s.label == "zsh - /tmp"
    view.foreground_program = "zsh"
    assert s.activity == ""  # the shell itself holds the foreground
    view.foreground_program = "vim"
    assert s.activity == "vim"
    s.command_since, s.command = 1.0, "vim notes.txt"
    assert s.activity == "vim notes.txt"
    s.command_since, s.command = None, ""
    view.foreground_program = None  # Windows: no foreground to read
    view.title = "PowerShell - build"
    assert s.activity == "PowerShell - build"
    view.idle_at_prompt = True
    assert s.activity == ""
    view.idle_at_prompt = False
    view._exited = 0
    assert s.activity == ""


class _Viewer:
    """A stand-in viewer: what the app reads off one (hashable, as widgets are)."""

    def __init__(self, path=None):
        self.path = path
        self.closed = []

    def palette_actions(self):
        return set()


def _ctx(app, monkeypatch):
    import xefm.app as app_mod
    import xefm.user_api as api
    from xefm.user_api import ActionContext
    monkeypatch.setattr(api, "is_desktop_mode", app_mod.is_desktop_mode)
    app._call_later = lambda fn: app.later.append(fn)
    app.later = []
    app.panel_render = None
    return ActionContext(app)


def test_ctx_screens_walks_back_and_forth(monkeypatch):
    app = _app(monkeypatch)
    ctx = _ctx(app, monkeypatch)
    [files] = ctx.screens()
    assert files.kind == "files" and files.id == "files" and files.shown
    assert files.terminal_session is None and ctx.current_screen == files
    app.new_terminal_session()
    now, before = ctx.screens()
    assert now.kind == "terminal" and now.shown and before == files
    assert now.terminal_session.screen == now and now.name == "zsh"
    before.show()  # back to the previous screen
    assert ctx.current_screen == files
    assert [s.id for s in ctx.screens(order="started")] == ["files", now.id]
    [session] = ctx.terminal_sessions()
    session.close()
    assert ctx.terminal_sessions() == [] and session.screen is None
    import pytest
    with pytest.raises(RuntimeError):
        now.show()  # its session is closed: the screen is gone
    with pytest.raises(ValueError):
        ctx.screens(order="newest")


def test_ctx_start_terminal_session_on_the_desktop(monkeypatch):
    app = _app(monkeypatch)
    ctx = _ctx(app, monkeypatch)
    app._program_env = lambda pane: ({"XEFM_ACTIVE": "1"}, "/tmp")
    done = []
    session = ctx.start_terminal_session(["htop"], show=False, name="top",
                                         env={"X": "1"},
                                         on_done=lambda c, code: done.append(code))
    [view] = app.made
    assert session.kind == "program" and session.name == "top" and session.running
    assert view.argv == ["htop"] and view.env["X"] == "1" and not view.shown
    assert ctx.current_screen.kind == "files"
    session.screen.show()
    assert view.shown
    view._exited = 0
    app._session_exited(view, 0)
    assert done == [0]
    shell = ctx.start_terminal_session()
    assert shell.kind == "shell" and shell.screen.shown


def test_ctx_start_terminal_session_in_terminal_mode_hands_the_terminal_over(monkeypatch):
    app = _app(monkeypatch, desktop=False)
    ctx = _ctx(app, monkeypatch)
    done = []
    session = ctx.start_terminal_session(on_done=lambda c, code: done.append(code))
    [(argv, cwd, env)] = app.handed
    assert argv == ["/bin/zsh"] and env["XEFM_SESSION"] == "subshell"
    assert not session.running and session.state == "exited" and session.screen is None
    assert done == []  # never before it returns
    for fn in app.later:
        fn()
    assert done == [0]
    assert [s.kind for s in ctx.screens()] == ["files"] and ctx.terminal_sessions() == []


def test_xefmctl_lists_and_switches_screens(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    [view] = app.made
    answer = XeFMApp._remote_answer.__get__(app)
    app._remote_pane = lambda name: {"path": "/tmp"}
    app._screen_label = XeFMApp._screen_label.__get__(app)
    sid = app._sessions.for_view(view).id
    lines = answer({"cmd": "screen", "verb": "list"})["lines"]
    assert lines[0].startswith(f"* {sid}\tzsh") and lines[1] == "  files\tFile manager"
    assert answer({"cmd": "screen", "verb": "switch", "id": "files"})["ok"]
    assert not view.shown
    assert not answer({"cmd": "screen", "verb": "switch", "id": "nope"})["ok"]
    [line] = answer({"cmd": "session", "verb": "list", "session": str(sid)})["lines"]
    assert line.startswith(f"* {sid}\tzsh\t")


def test_xefmctl_view_opens_on_the_file_manager(monkeypatch):
    app = _app(monkeypatch)
    opened = []
    app._open_viewer = lambda target: (opened.append(target),
                                       app.panel.push_layer(new_viewer, z=80))
    old_viewer = _Viewer()
    old_viewer._close = lambda: (old_viewer.closed.append(1),
                                 app.panel.remove_layer(old_viewer))
    new_viewer = _Viewer()
    app.panel.push_layer(old_viewer, z=80)
    app.new_terminal_session()
    XeFMApp._view_on_file_manager(app, "/tmp/log.txt")
    assert app._screens.current is app._screens.files
    assert old_viewer.closed == [1] and opened == ["/tmp/log.txt"]
    assert _shown(app.panel) == [new_viewer]
    assert app.panel.layer_parent(new_viewer) is app._screens.files.group


def test_xefmctl_parses_the_noun_commands():
    import pytest
    from xefm.remote_cli import RemoteError, _parse
    assert _parse("screen", ["list"])["verb"] == "list"
    req = _parse("screen", ["switch", "files"])
    assert req["verb"] == "switch" and req["id"] == "files"
    assert _parse("session", ["list"])["verb"] == "list"
    for bad in (["screen", []], ["screen", ["switch"]], ["session", ["switch", "1"]],
                ["screen", ["list", "x"]]):
        with pytest.raises(RemoteError):
            _parse(*bad)


def test_an_action_can_live_in_the_terminal_context():
    from xefm import actions as A
    from xefm.user_api import _build_action
    action, problem = _build_action("next-shell", {"func": lambda ctx: None,
                                                   "context": "terminal"})
    assert problem is None and action.context == A.TERMINAL
    _, problem = _build_action("x", {"func": lambda ctx: None, "context": "text_viewer"})
    assert "only in 'filer' and 'terminal'" in problem


def test_the_terminal_runs_a_terminal_context_action():
    from xefm import terminal as T
    ran = []
    view = SimpleNamespace(on_close_request=None, on_screens_request=None,
                           on_user_action=lambda name: ran.append(name) or True)
    view._actions = lambda: {}
    import xefm.terminal as mod
    orig = mod._user_actions
    mod._user_actions = lambda: {"next-shell"}
    try:
        assert T.TerminalView.run_action(view, "next-shell") is True
        assert T.TerminalView.run_action(view, "unknown") is False
    finally:
        mod._user_actions = orig
    assert ran == ["next-shell"]
