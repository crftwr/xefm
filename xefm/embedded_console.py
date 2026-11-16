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

from xefm import surface_actions
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
        from xefm.text_viewer import VIEWER_PAD_PX
        # The viewers' inset: the grid breathes in from the window frame on GUI
        # by the same few pixels; flush on a character grid.
        super().__init__(argv, cwd=cwd, env=env,
                         on_exit=(lambda code: on_exited(self, code)) if on_exited else None,
                         padding_px=VIEWER_PAD_PX)
        self.on_hide = on_hide
        self.action_bound = action_bound
        #: Called once with the exit code after a one-shot console closes (an
        #: editor run here, whose caller continues when it is done).
        self.on_done: Callable[[int | None], None] | None = None
        self.one_shot = one_shot
        self.label = label
        if one_shot:
            self.exit_hint = "press Enter to return to XeFM"

    # --- actions (#900) -------------------------------------------------------
    #: The command palette's view of this surface, as the viewers': its
    #: context, what it runs, and running one by name.
    palette_context = "console"

    def _actions(self) -> dict:
        """What the console runs, by name: putting itself away, and the
        app-wide actions any surface may run (text size, theme, config, the
        console toggle - xefm.surface_actions). Nothing that acts on the file
        list behind it."""
        table = {"console.close": lambda: self.on_hide(self)}
        table.update(surface_actions.handlers())
        return table

    def palette_actions(self) -> set:
        return set(self._actions())

    def run_action(self, name: str) -> bool:
        handler = self._actions().get(name)
        if handler is None:
            return False
        handler()
        return True

    def takes_binding(self, event, action: str) -> bool:
        """Whether the key bound to ``action`` is taken from the terminal.

        A binding made for the console wins over whatever the program would do
        with the key: a ``console.*`` action, the console's own show / hide
        (``console``, without which there is no way out), and a
        context-qualified ``'console.<action>'`` entry in config.py. A binding
        it merely inherits - ``'command_palette': ['Ctrl-T']``, written for the
        file list - is taken only on a chord no terminal program receives
        (Command, Ctrl+Shift); otherwise the key stays the program's (Ctrl-T
        transposes in a shell)."""
        if action == "console" or action.startswith("console."):
            return True
        if self._qualified(event, action):
            return True
        mods = event.modifiers
        return "cmd" in mods or {"ctrl", "shift"} <= mods

    @staticmethod
    def _qualified(event, action: str) -> bool:
        """Whether config.py binds ``event`` to ``action`` for the console
        specifically (``'console.command_palette': ['Ctrl-T']``)."""
        from xefm.config import KeyBindings, config_manager
        keys = (getattr(config_manager.get_config(), "KEY_BINDINGS", None) or {}).get(
            f"console.{action}")
        if not keys:
            return False
        return KeyBindings({action: keys}).is_action_for_event(event, action)

    def _is_hide_key(self, event) -> bool:
        if find_action_for_event(event, context="filer") == "console":
            return True
        return (event.key == "f12" and not event.modifiers
                and not self.action_bound())

    def handle_event(self, event) -> bool:
        if event.type is EventType.KEY:
            action = find_action_for_event(event, context="console")
            if action is not None and self.takes_binding(event, action) \
                    and self.run_action(action):
                return True
            if self._is_hide_key(event):
                self.on_hide(self)
                return True
            if self.one_shot and self._exited is not False \
                    and event.key in ("enter", "escape"):
                self.on_hide(self)
                return True
        super().handle_event(event)
        return True  # modal: nothing reaches the panes underneath
