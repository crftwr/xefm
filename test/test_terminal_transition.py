"""XeFM's terminal opens as if it lay behind the file manager, and closes back
there (#900): the file manager zooms up and fades away as the terminal fades
in, and settles back as it fades out.

The app's own methods run against a stand-in panel that records the
transition it is asked for and plays it only when the test says so, and a
stand-in view (libghostty is not installed where the tests run)."""

from types import SimpleNamespace

from xefm.app import XeFMApp
from xefm.dialog_geometry import BEHIND_SCALE, animate_from_behind
from xefm.terminal_sessions import PROGRAM, Session, SessionRegistry


class _Panel:
    def __init__(self, *, animates=True, extras=None):
        self.backend = SimpleNamespace(size_units=(100.0, 40.0))
        self.base = object()
        self.theme = SimpleNamespace(extras=extras or {})
        self._layers = []
        self.animates = animates
        self.animations = []
        self.removed = []

    def push_layer(self, widget, z, hints=None, reflow=None):
        self._layers.append(SimpleNamespace(widget=widget, z=z))

    def remove_layer(self, widget):
        self.removed.append(widget)
        self._layers = [s for s in self._layers if s.widget is not widget]
        return True

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
    app._TERMINAL_Z = XeFMApp._TERMINAL_Z

    def relist(pane, keep_visible=False):
        app.relisted += 1
    app._relist = relist
    app.log_info = app.logged.append
    app._sessions = SessionRegistry()
    app._relist_both = lambda: XeFMApp._relist_both(app)
    app._close_session = lambda s: XeFMApp._close_session(app, s)
    return app


def _shown(app, view, on_done=None):
    """``view`` as a session on screen."""
    session = app._sessions.add(Session(view=view, kind=PROGRAM, name="vim",
                                        cwd="/", on_done=on_done))
    XeFMApp._push_terminal(app, view)
    view.shown = True
    return session


def test_opening_fades_the_terminal_in_as_the_file_manager_zooms_away():
    panel = _Panel()
    view = _View()
    XeFMApp._push_terminal(_app(panel), view)
    [term] = panel.of(view)
    [base] = panel.of(panel.base)
    assert term["transition"] == "fade" and not term["out"]
    assert base["transition"] == "scale" and base["fade"] and base["out"]
    assert base["from_scale"] == BEHIND_SCALE > 1
    assert base["duration_ms"] == term["duration_ms"]


def test_closing_plays_it_back_then_tears_down():
    panel = _Panel()
    app = _app(panel)
    view = _View(exited=0)
    done = []
    session = _shown(app, view, on_done=done.append)
    panel.animations.clear()
    XeFMApp._close_session(app, session)
    [term] = panel.of(view)
    [base] = panel.of(panel.base)
    assert term["transition"] == "fade" and term["out"]
    assert base["transition"] == "scale" and not base["out"]
    # Still on screen, still the program's, while it fades out.
    assert view.closing and view.closed == 0 and not panel.removed and not done
    panel.finish()
    assert panel.removed == [view] and view.closed == 1
    assert app.relisted == 2 and done == [0]


def test_a_second_close_while_closing_does_nothing():
    panel = _Panel()
    app = _app(panel)
    view = _View()
    session = _shown(app, view)
    panel.animations.clear()
    XeFMApp._close_session(app, session)
    XeFMApp._close_session(app, session)
    XeFMApp._session_exited(app, view, 0)
    XeFMApp._session_exited(app, view, 1)
    assert len(panel.of(view)) == 1 and not app.logged
    panel.finish()
    assert view.closed == 1


def test_without_motion_it_closes_at_once():
    for panel in (_Panel(animates=False), _Panel(extras={"dialog_effect": False})):
        app = _app(panel)
        view = _View(exited=0)
        session = _shown(app, view)
        panel.animations.clear()
        XeFMApp._close_session(app, session)
        assert panel.removed == [view] and view.closed == 1
        assert not panel.animations


def test_the_view_swallows_input_while_closing():
    from xefm.terminal import TerminalView
    view = SimpleNamespace(closing=True)
    event = SimpleNamespace(type=None)
    assert TerminalView.handle_event(view, event) is True


def test_it_reports_whether_it_will_call_back():
    panel = _Panel(animates=False)
    assert animate_from_behind(panel, object(), on_complete=lambda: None) is False
    assert not panel.animations


def test_an_older_puikit_without_a_base_still_fades_the_terminal():
    panel = _Panel()
    del panel.base
    view = object()
    assert animate_from_behind(panel, view) is True
    assert [w for w, _h in panel.animations] == [view]
