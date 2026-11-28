"""Going between the file manager and a session is a tab switch (#1019): at
once, with no transition - the window's chrome stays where it is and only
what is between it changes. Each is a screen (#951), a group in the Panel's
layer tree: the screen left is hidden, not removed.

The app's own methods run against a PuiKit Panel that records the transition
it is asked for and plays it only when the test says so, and a stand-in view
(libghostty is not installed where the tests run)."""

from types import SimpleNamespace

from puikit import Panel
from puikit.backends.memory_backend import MemoryBackend

from xefm.app import XeFMApp
from xefm.screens import ScreenManager
from xefm.terminal_sessions import PROGRAM, Session, SessionRegistry


class _Panel(Panel):
    def __init__(self, *, animates=True, extras=None):
        super().__init__(MemoryBackend(width=100, height=40))
        self.theme = SimpleNamespace(extras=extras or {})
        self.animates = animates
        self.animations = []
        self.removed = []

    def remove_layer(self, widget):
        self.removed.append(widget)
        return super().remove_layer(widget)

    def animate(self, widget, hints=None):
        if not self.animates:
            return False
        self.animations.append((widget, hints))
        return True

    def render(self):
        pass

    def finish(self):
        """The running transitions end: their on_complete hooks fire."""
        for _, hints in list(self.animations):
            if hints.get("on_complete"):
                hints["on_complete"]()

    def of(self, widget):
        return [h for w, h in self.animations if w is widget]


class _View:
    def __init__(self, exited=False):
        self.closing = False
        self.shown = False
        self._exited = exited
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


def _app(panel):
    app = SimpleNamespace(panel=panel, relisted=0, logged=[])
    app.pm = SimpleNamespace(left_pane="L", right_pane="R")

    def relist(pane, keep_visible=False):
        app.relisted += 1
    app._relist = relist
    app.log_info = app.logged.append
    app._sessions = SessionRegistry()
    app._screens = ScreenManager(panel)
    for name in ("_relist_both", "_close_session", "_show_screen",
                 "_remember_closed",
                 "_closed_agents", "_save_closed_agents"):
        setattr(app, name, getattr(XeFMApp, name).__get__(app))
    return app


def _shown(app, view, on_done=None):
    """``view`` as a session on screen."""
    session = app._sessions.add(Session(view=view, kind=PROGRAM, name="vim",
                                        cwd="/", on_done=on_done))
    screen = app._screens.add_terminal(session, view, hints={}, reflow=None)
    app._show_screen(screen)
    app.panel.finish()
    return session


def test_a_session_comes_on_and_goes_at_once():
    panel = _Panel()
    app = _app(panel)
    view = _View()
    session = _shown(app, view)
    assert app._screens.current is session.screen and view.shown
    assert not panel.is_layer_shown(app._screens.files.group)  # hidden, not removed
    app._show_screen(app._screens.files)
    assert not view.shown and panel.has_layer(view)
    assert not panel.is_layer_shown(session.screen.group)
    assert app.relisted == 2  # back on the panes: both re-read
    assert panel.animations == []  # nothing plays


def test_a_viewer_on_the_panes_stays_while_a_session_is_on():
    panel = _Panel()
    app = _app(panel)
    viewer = object()
    panel.push_layer(viewer, z=80)  # on the file manager's screen
    session = _shown(app, _View())
    app._show_screen(app._screens.files)
    assert panel.is_layer_shown(viewer)
    assert panel.animations == []


def test_closing_tears_down_at_once():
    panel = _Panel()
    app = _app(panel)
    done = []
    view = _View()
    session = _shown(app, view, on_done=done.append)
    app._close_session(session)
    assert view.closed == 1 and done == [None] and view in panel.removed or \
        not panel.has_layer(view)
    assert app._screens.current is app._screens.files and panel.animations == []
    app._close_session(session)  # a second close does nothing
    assert view.closed == 1


def test_the_view_swallows_input_while_closing():
    from xefm.terminal import TerminalView
    view = SimpleNamespace(closing=True)
    event = SimpleNamespace(type=None)
    assert TerminalView.handle_event(view, event) is True
