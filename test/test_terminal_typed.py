"""The end of a terminal session's view.

``typed`` says whether the user has typed into the program since it started,
which tells a shell's own ``exit`` from a shell that could not start
(app._session_exited). On the exit bar, Enter and Escape close the view,
shell or program: a shell is never started again there, as PuiKit's own exit
bar would."""

import pytest
from puikit.event import Event, EventType

from xefm import terminal

pytestmark = pytest.mark.skipif(terminal._PuiKitTerminalView is None,
                                reason="this PuiKit has no TerminalView")


class _Proc:
    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(data)

    def close(self):
        pass


def _view(shell=True):
    closed = []
    view = terminal.TerminalView(
        ["true"], cwd=".", env={}, label="t", shell=shell,
        on_exited=lambda v, c: None, on_close_request=closed.append)
    view._proc = _Proc()
    view.closed_by = closed
    return view


def _key(name):
    return Event(EventType.KEY, key=name)


def test_nothing_is_typed_at_first():
    assert _view().typed is False


def test_input_to_the_program_counts():
    view = _view()
    view.send("exit\r")
    assert view.typed is True and view._proc.written == [b"exit\r"]


def test_input_after_the_program_ended_does_not():
    view = _view()
    view._exited = 1
    view.send("x")
    assert view.typed is False


@pytest.mark.parametrize("shell", [True, False], ids=["shell", "program"])
@pytest.mark.parametrize("key", ["enter", "escape"])
def test_the_exit_bar_closes_on_enter_or_escape(monkeypatch, shell, key):
    monkeypatch.setattr(terminal, "find_action_for_event", lambda *a, **k: None)
    view = _view(shell=shell)
    view._exited = 1
    restarted = []
    view.restart = lambda: restarted.append(1)
    assert view.handle_event(_key(key))
    assert view.closed_by == [view] and restarted == []
    assert view.exit_hint == "press Enter to close"


def test_other_keys_on_the_exit_bar_do_nothing(monkeypatch):
    monkeypatch.setattr(terminal, "find_action_for_event", lambda *a, **k: None)
    view = _view()
    view._exited = 1
    assert view.handle_event(_key("a"))
    assert view.closed_by == [] and view._exited == 1
