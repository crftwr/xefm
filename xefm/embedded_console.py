"""The embedded console (prototype, discussion #900).

A shell that lives behind the panes: the ``console`` action shows it over the
whole window and hides it again, and the session survives in between — FAR's
and Midnight Commander's Ctrl-O console. In desktop mode the subshell and
``PROGRAMS`` entries with ``{'terminal': True}`` run here too, instead of in
the ``TERMINAL`` application, so a full-screen program (vim, less) runs in the
XeFM window and the panes re-read when it is done, as in terminal mode.

The terminal itself is PuiKit's ``TerminalView`` (libghostty-vt over a pty);
this module only decides what runs in it and what XeFM does around it. Where
the widget or libghostty is missing, :func:`unavailable` says why and every
caller keeps the behavior it had before.
"""

from __future__ import annotations

from collections.abc import Callable

from xefm.config import find_action_for_event
from xefm.log_manager import getLogger

logger = getLogger("Console")

try:
    from puikit.event import EventType
    from puikit.widgets.terminal_view import TerminalView
    from puikit.widgets.terminal_view import available as _terminal_available
except ImportError:  # a PuiKit without the prototype widget
    TerminalView = None  # type: ignore[assignment,misc]
    _terminal_available = None


def unavailable(config) -> str | None:
    """None when the embedded console can run, else the reason it cannot."""
    if not getattr(config, "EMBEDDED_TERMINAL", True):
        return "EMBEDDED_TERMINAL is off in config.py"
    if TerminalView is None or _terminal_available is None:
        return "this PuiKit has no TerminalView"
    return _terminal_available()


_Base = TerminalView if TerminalView is not None else object


class ConsoleView(_Base):  # type: ignore[misc,valid-type]
    """A ``TerminalView`` shown as a full-window layer.

    The key bound to the ``console`` action hides it — the one key taken from
    the program inside, so it has to be one a shell does not need. With the
    action unbound (the default while this is a prototype, so no preset loses
    a key to it) F12 does, inside the console only; ``action_bound`` tells
    which. When the child the console started exits, ``on_exited`` gets the
    view and the exit code; the app closes the console and returns to the
    panes. ``one_shot`` marks a program run on the user's behalf rather than
    the persistent shell; if it is left on screen (a failure the user should
    read), Enter or Escape closes it."""

    def __init__(self, argv: list[str], *, cwd: str, env: dict,
                 on_hide: Callable[["ConsoleView"], None],
                 action_bound: Callable[[], bool],
                 on_exited: Callable[["ConsoleView", int | None], None] | None = None,
                 one_shot: bool = False, label: str = "") -> None:
        super().__init__(argv, cwd=cwd, env=env,
                         on_exit=(lambda code: on_exited(self, code)) if on_exited else None)
        self.on_hide = on_hide
        self.action_bound = action_bound
        self.one_shot = one_shot
        self.label = label
        if one_shot:
            self.exit_hint = "press Enter to return to XeFM"

    def _is_hide_key(self, event) -> bool:
        if find_action_for_event(event, context="filer") == "console":
            return True
        return (event.key == "f12" and not event.modifiers
                and not self.action_bound())

    def handle_event(self, event) -> bool:
        if event.type is EventType.KEY:
            if self._is_hide_key(event):
                self.on_hide(self)
                return True
            if self.one_shot and self._exited is not False \
                    and event.key in ("enter", "escape"):
                self.on_hide(self)
                return True
        super().handle_event(event)
        return True  # modal: nothing reaches the panes underneath
