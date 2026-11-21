"""Terminal sessions in the desktop app (#900): everything run in XeFM's
terminal is one - the subshell, a terminal program, a shell from the list.

The registry on its own, then the app's methods against a PuiKit Panel on
the memory backend (libghostty is not installed where the tests run, so a
stand-in view plays the terminal), then what terminal mode does instead.
Screens (#951) are groups in the Panel's layer tree."""

import time
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
    app.remote_policies = []
    app._with_remote_env = lambda env, session, policy="user": (
        app.remote_sessions.append(session), app.remote_policies.append(policy),
        env.update(XEFM_SESSION=session))[2] or env
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
    assert switcher.labels()[:2] == ["make test - /tmp",
                                     "File manager - viewing notes.txt"]


def test_rows_that_read_the_same_get_the_sessions_name(monkeypatch):
    app = _app(monkeypatch)
    switcher = _Switcher(monkeypatch)
    app.new_terminal_session()
    app.new_terminal_session()
    app.screens()
    assert switcher.labels()[:3] == ["zsh 2 - /tmp", "zsh - /tmp", "File manager"]
    first = app._sessions.for_view(app.made[0])
    first.command_since, first.command = 1.0, "claude"
    app.screens()
    assert switcher.labels()[:3] == ["zsh - /tmp", "claude - /tmp", "File manager"]


def test_a_chosen_name_heads_its_row():
    reg = SessionRegistry()
    view = _View()
    s = reg.add(Session(view=view, kind=SHELL, name="build", cwd="/tmp",
                        program="zsh", named=True))
    assert s.label == "build - /tmp"
    s.command_since, s.command = 1.0, "make"
    assert s.label == "build - make - /tmp"
    p = reg.add(Session(view=_View(), kind=PROGRAM, name="htop", cwd="/tmp", program="htop"))
    assert p.label == "htop - /tmp"


def test_the_running_programs_own_title_wins_while_it_runs():
    reg = SessionRegistry()
    view = _View()
    s = reg.add(Session(view=view, kind=SHELL, name="zsh", cwd="/tmp", program="zsh"))
    view.child_in_foreground = True
    s.title_changed("~/src")  # the shell's own title at its prompt: ignored
    s.command_since, s.command = time.monotonic(), "claude"
    s.title_changed("claude")  # a preexec title hook, before the job runs
    assert s.activity == "claude"
    view.child_in_foreground, view.foreground_program = False, "claude"
    s.title_changed("\u2733 Claude")
    assert s.activity == "\u2733 Claude"
    s.command_since, s.command = None, ""  # back at the prompt
    view.idle_at_prompt = True
    assert s.activity == ""
    view.idle_at_prompt = False
    s.command_since, s.command = time.monotonic() + 1, "make"
    assert s.activity == "make"  # the old title was the last job's


def test_without_integration_a_title_lasts_while_its_program_does():
    reg = SessionRegistry()
    view = _View()
    s = reg.add(Session(view=view, kind=SHELL, name="zsh", cwd="/tmp", program="zsh"))
    view.child_in_foreground, view.foreground_program = False, "claude"
    s.title_changed("\u2733 Claude")
    assert s.activity == "\u2733 Claude"
    view.foreground_program = "vim"  # the title is claude's, not vim's
    assert s.activity == "vim"


def test_a_shell_that_runs_jobs_on_its_own_ptys_passes_their_titles_on():
    reg = SessionRegistry()
    view = _View()
    s = reg.add(Session(view=view, kind=SHELL, name="eosh", cwd="/tmp", program="eosh"))
    view.child_in_foreground, view.foreground_program = True, "python3.14"
    assert s.activity == ""
    s.title_changed("\u2733 Claude Code")  # eosh relays claude's title
    assert s.activity == "\u2733 Claude Code"
    s.title_changed("")  # and clears it when claude exits
    assert s.activity == ""


def test_the_label_shows_where_the_shell_is_now(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "gethostname", lambda: "mac.local")
    reg = SessionRegistry()
    view = _View()
    s = reg.add(Session(view=view, kind=SHELL, name="zsh", cwd="/tmp", program="zsh"))
    assert s.directory == "/tmp"  # nothing reported yet: where it started
    view.pwd = "file://mac.local/opt/My%20Notes"
    assert s.directory == "/opt/My Notes" and s.label == "zsh - /opt/My Notes"
    assert s.cwd == "/tmp"
    view.pwd = "file://mac/srv"
    assert s.directory == "/srv"
    view.pwd = "file://build-box/home/me"  # a shell over ssh
    assert s.directory == "build-box:/home/me"
    view.pwd = "/var/log"  # a bare path
    assert s.directory == "/var/log"


def test_activity_reads_the_command_then_the_foreground_then_the_title():
    reg = SessionRegistry()
    view = _View()
    s = reg.add(Session(view=view, kind=SHELL, name="zsh", cwd="/tmp", program="zsh"))
    assert s.activity == "" and s.label == "zsh - /tmp"
    view.foreground_program = "zsh"
    assert s.activity == ""  # the shell itself holds the foreground
    view.foreground_program = "python3.14"  # a shell written in Python
    view.child_in_foreground = True         # ... at its own prompt
    assert s.activity == ""
    view.child_in_foreground = False
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


def _xefmctl(app, line, *, session="", policy="user", stdin=None):
    """Run one xefmctl command line against ``app`` as XeFM would, on its UI
    thread: parsed by the client, carried out by remote_dispatch."""
    import shlex
    from xefm import remote_commands as T
    from xefm import remote_dispatch as D
    from xefm.remote_cli import parse
    req = parse(shlex.split(line), stdin)
    req.update(session=session, policy=policy)
    cmd = T.find(req["cmd"].split())[0]
    answer = D._answer(app, cmd, req)
    return answer


def _answered(answer):
    from xefm import remote_dispatch as D
    return answer.wait() if isinstance(answer, D.Pending) else answer


def test_xefmctl_lists_and_shows_screens(monkeypatch):
    app = _app(monkeypatch)
    app._user_ctx = _ctx(app, monkeypatch)
    app.new_terminal_session()
    [view] = app.made
    sid = app._sessions.for_view(view).id
    items = _xefmctl(app, "screen list")["items"]
    assert [(i["marker"], i["id"]) for i in items] == [("*", str(sid)), (" ", "files")]
    assert items[1]["label"] == "File manager"
    assert _xefmctl(app, "screen show files")["ok"]
    assert not view.shown
    refused = _xefmctl(app, "screen show nope")
    assert not refused["ok"] and "screen list" in refused["error"]
    [row] = _xefmctl(app, "terminal-session list", session=str(sid))["items"]
    assert row["marker"] == "*" and row["name"] == "zsh"


def test_xefmctl_view_replaces_the_viewer_at_once(monkeypatch, tmp_path):
    app = _app(monkeypatch)
    app._user_ctx = _ctx(app, monkeypatch)
    log = tmp_path / "log.txt"
    log.write_text("x\n")
    opened = []
    new_viewer = _Viewer()
    app._open_viewer = lambda target: (opened.append(str(target)),
                                       app.panel.push_layer(new_viewer, z=80))
    old_viewer = _Viewer()
    old_viewer._close = lambda: (old_viewer.closed.append(1),
                                 app.panel.remove_layer(old_viewer))
    app.panel.push_layer(old_viewer, z=80)
    app.new_terminal_session()
    assert _xefmctl(app, f"view {log}")["ok"]
    assert app._screens.current is app._screens.files
    assert old_viewer.closed == [1] and opened == [str(log)]
    assert _shown(app.panel) == [new_viewer]
    assert app.panel.layer_parent(new_viewer) is app._screens.files.group


def test_xefmctl_waits_for_what_a_key_could_not_reach(monkeypatch):
    app = _app(monkeypatch)
    app.new_terminal_session()
    files = app._screens.files.group
    dialog = _Dialog("Copy")
    app.panel.push_layer(dialog, z=70, parent=files)
    refused = _xefmctl(app, "invoke reread")
    assert refused["code"] == 5 and "dialog is open" in refused["error"]
    assert "(Copy)" in refused["error"]
    assert _xefmctl(app, "screen list")["ok"]  # reads are never refused
    app.panel.remove_layer(dialog)
    app.panel.push_layer(_Viewer(), z=80, parent=files)
    refused = _xefmctl(app, "invoke reread")  # a file-list action, over a viewer
    assert refused["code"] == 5 and "viewer is open" in refused["error"]


def _run_later(app):
    while app.later:
        app.later.pop(0)()


class _Dialog:
    def __init__(self, title):
        self.title = title


def _asking_ctx(app, monkeypatch, answer=True):
    ctx = _ctx(app, monkeypatch)
    asked, copied = [], []

    def confirm(prompt, *, title="Confirm", on_result=None):
        asked.append(prompt)
        dialog = _Dialog(title)
        app.panel.push_layer(dialog, z=70)
        # The user answers later, as a dialog is answered.
        app.later.append(lambda: (app.panel.remove_layer(dialog), on_result(answer)))
    ctx.confirm = confirm
    ctx.copy = lambda items, dest, on_done=None: copied.append((list(items), dest)) or (
        on_done and on_done(ctx, SimpleNamespace(status="done", error=None)))
    app._user_ctx = ctx
    return asked, copied


def test_an_agents_copy_is_confirmed_in_xefm(monkeypatch):
    app = _app(monkeypatch)
    asked, copied = _asking_ctx(app, monkeypatch)
    app.new_terminal_session()
    agent = app._screens.current
    sid = str(agent.session.id)
    pending = _xefmctl(app, "copy /tmp/a /tmp/b --to /tmp/out --wait",
                       session=sid, policy="agent")
    assert app._screens.current is app._screens.files  # asked there
    _run_later(app)
    answer = _answered(pending)
    assert answer["ok"] and answer["status"] == 0 and answer["outcome"] == "done"
    assert copied == [(["/tmp/a", "/tmp/b"], "/tmp/out")]
    assert "zsh wants to copy 2 item(s) to /tmp/out" in asked[0]
    # The question took the user to the file manager, the answer back.
    assert app._screens.current is agent
    # A shell of the user's own is not asked.
    asked.clear()
    _answered(_xefmctl(app, "copy /tmp/a --to /tmp/out --wait"))
    _run_later(app)
    assert asked == [] and len(copied) == 2


def test_an_agents_trash_reads_naturally(monkeypatch):
    app = _app(monkeypatch)
    asked, _ = _asking_ctx(app, monkeypatch)
    trashed = []
    app._user_ctx.trash = lambda items, on_done=None: trashed.append(list(items))
    titles = []
    confirm = app._user_ctx.confirm
    app._user_ctx.confirm = lambda prompt, *, title="Confirm", on_result=None: (
        titles.append(title), confirm(prompt, title=title, on_result=on_result))
    pending = _xefmctl(app, "trash /tmp/x", policy="agent")
    _run_later(app)
    _answered(pending)
    assert "wants to move 1 item(s) to the trash:" in asked[0]
    assert titles == ["Allow move to the trash?"] and trashed == [["/tmp/x"]]


def test_the_rules_name_the_skill_xefm_handed_over():
    from xefm import agents
    assert "xefm:xefm" in agents.DEFAULT_RULES


def test_an_agent_told_no_gets_a_failure(monkeypatch):
    app = _app(monkeypatch)
    asked, copied = _asking_ctx(app, monkeypatch, answer=False)
    pending = _xefmctl(app, "copy /tmp/a --to /tmp/out", policy="agent")
    _run_later(app)
    answer = _answered(pending)
    assert answer["status"] == 1 and "did not allow" in answer["note"]
    assert copied == []


def test_an_agent_may_not_delete_for_good(monkeypatch):
    app = _app(monkeypatch)
    _asking_ctx(app, monkeypatch)
    refused = _xefmctl(app, "delete /tmp/a", policy="agent")
    assert refused["code"] == 5 and "xefmctl trash" in refused["error"]
    refused = _xefmctl(app, "invoke delete_permanently", policy="agent")
    assert refused["code"] == 5


def test_an_agents_invoke_runs_with_the_confirmations_on(monkeypatch):
    app = _app(monkeypatch)
    ctx = _ctx(app, monkeypatch)
    app.config.CONFIRM_DELETE = False
    app.config.DELETE_TO_TRASH = False
    seen = []
    ctx.invoke = lambda name: seen.append((name, app.config.CONFIRM_DELETE,
                                           app.config.DELETE_TO_TRASH))
    app._user_ctx = ctx
    assert _xefmctl(app, "invoke delete_files", policy="agent")["ok"]
    assert seen == [("delete_files", True, True)]
    assert app.config.CONFIRM_DELETE is False and app.config.DELETE_TO_TRASH is False
    _xefmctl(app, "invoke delete_files")
    assert seen[-1] == ("delete_files", False, False)


def test_xefmctl_parses_by_the_table():
    import io
    import pytest
    from xefm.remote_cli import RemoteError, parse
    assert parse(["screen", "list"])["cmd"] == "screen list"
    req = parse(["screen", "show", "files"])
    assert req["args"] == {"id": "files"}
    req = parse(["copy", "a", "b", "--to", "/out", "--wait", "--json"])
    assert req["args"]["source"][1].endswith("/b") and req["opts"] == {"to": "/out", "wait": True}
    assert req["json"]
    req = parse(["find-in-files", "TODO", "--case", "--limit", "5"])
    assert req["args"] == {"pattern": "TODO", "url": []} and req["opts"]["limit"] == 5
    req = parse(["pane", "open-list", "-"], io.StringIO('{"path": "/x/a"}\n/x/b\n'))
    assert req["args"]["path"] == ["/x/a", "/x/b"]
    req = parse(["pane", "cd"])
    assert req["args"]["path"]  # this shell's directory
    for bad in (["screen"], ["screen", "show"], ["screen", "list", "x"],
                ["copy", "--pane", "up", "a"], ["nope"], ["pane", "selected", "--frob"]):
        with pytest.raises(RemoteError) as caught:
            parse(bad)
        assert caught.value.code == 2
    with pytest.raises(RemoteError) as caught:
        parse(["pane", "cd", "--help"])
    assert caught.value.code == 0 and "--focus" in str(caught.value)


def test_open_agent_starts_a_restricted_session_with_the_skill(monkeypatch, tmp_path):
    from xefm import agents
    app = _app(monkeypatch)
    app.config.AGENTS = [{"name": "Claude Code", "command": ["claude"],
                          "preset": "claude-code"}]
    app.config.AGENT_RULES = "Leave ~/Taxes alone."
    monkeypatch.setattr(agents, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(agents, "installed", lambda entry: True)
    app._program_env = lambda pane: ({"XEFM_ACTIVE": "1"}, "/tmp")
    app.active_pane = lambda: {"path": "/tmp", "files": [], "selected_files": set()}
    app._focused_entry = lambda: None
    for name in ("open_agent", "ask_agent", "_pick_agent", "_agent_request", "_start_agent"):
        setattr(app, name, getattr(XeFMApp, name).__get__(app))
    app.open_agent()
    [view] = app.made
    argv = view.argv
    assert argv[0] == "claude" and argv[1] == "--plugin-dir"
    plugin = argv[2]
    assert (tmp_path / "x").parent == tmp_path
    import pathlib
    assert (pathlib.Path(plugin) / "skills" / "xefm" / "SKILL.md").exists()
    assert (pathlib.Path(plugin) / ".claude-plugin" / "plugin.json").exists()
    rules = argv[argv.index("--append-system-prompt") + 1]
    assert "xefmctl state" in rules and "Leave ~/Taxes alone." in rules
    settings = pathlib.Path(argv[argv.index("--settings") + 1]).read_text()
    assert "Bash(rm:*)" in settings
    assert app.remote_policies[-1] == "agent"
    session = app._sessions.for_view(view)
    assert session.name == "Claude Code" and app._screens.current.session is session


def test_ask_agent_passes_the_request_and_the_selection(monkeypatch, tmp_path):
    from xefm import agents
    app = _app(monkeypatch)
    app.config.AGENTS = [{"name": "Codex", "command": ["codex", "--skills", "{skills_dir}"],
                          "restrict": False}]
    monkeypatch.setattr(agents, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(agents, "installed", lambda entry: True)
    app._program_env = lambda pane: ({}, "/tmp")
    app.active_pane = lambda: {"path": "/tmp", "files": ["/tmp/a.jpg", "/tmp/b.jpg"],
                               "selected_files": {"/tmp/a.jpg"}}
    app._focused_entry = lambda: "/tmp/b.jpg"
    ctx = _ctx(app, monkeypatch)
    ctx.input = lambda prompt, default="", *, title="", on_accept=None, **k: \
        on_accept("sort these by month")
    app._user_ctx = ctx
    for name in ("open_agent", "ask_agent", "_pick_agent", "_agent_request", "_start_agent"):
        setattr(app, name, getattr(XeFMApp, name).__get__(app))
    app.ask_agent()
    [view] = app.made
    assert view.argv[:2] == ["codex", "--skills"] and view.argv[2].endswith("skills")
    prompt = view.argv[-1]
    assert prompt.startswith("sort these by month") and "/tmp/a.jpg" in prompt
    assert app.remote_policies[-1] == "user"  # restrict: False


def test_agents_entries_are_checked():
    from xefm import agents
    config = SimpleNamespace(AGENTS=[
        {"name": "ok", "command": "claude --verbose"},
        {"command": ["x"]},
        {"name": "bad", "command": ["x"], "preset": "gpt"},
        {"name": "typo", "command": ["x"], "restirct": False},
    ])
    [entry] = agents.entries(config)
    assert entry["command"] == ["claude", "--verbose"] and entry["restrict"] is True
    assert "unknown key" in agents.normalize({"name": "t", "command": ["x"], "rest": 1})


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
