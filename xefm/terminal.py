"""XeFM's terminal (discussion #900).

Terminal mode hands its own terminal to a subshell, to ``PROGRAMS`` entries
with ``{'terminal': True}`` and to a ``TEXT_EDITOR`` marked
``{'terminal': True}``, waits, and re-reads the panes when they are done. The
desktop app has no terminal to hand over, so it runs them in one of its own:
:class:`TerminalView`, a full-window layer over the panes. The same actions
therefore do the same thing in both modes; only the terminal they run in
differs - the one XeFM runs in, or the one XeFM draws.

The emulation is PuiKit's ``TerminalView`` (libghostty-vt over a pty); this
module decides what runs in it and what XeFM does around it. Where the widget
or libghostty is missing, :func:`unavailable` says why and the caller falls
back to the ``TERMINAL`` application.
"""

from __future__ import annotations

from collections.abc import Callable

from xefm import surface_actions
from xefm.config import find_action_for_event
from xefm.log_manager import getLogger

logger = getLogger("Terminal")

try:
    from puikit.event import EventType
    from puikit.widgets.terminal_view import TerminalView as _PuiKitTerminalView
    from puikit.widgets.terminal_view import available as _terminal_available
except ImportError:  # a PuiKit without the widget
    _PuiKitTerminalView = None  # type: ignore[assignment,misc]
    _terminal_available = None

#: The action context of the terminal (xefm.actions.TERMINAL).
CONTEXT = "terminal"


def unavailable(config) -> str | None:
    """None when XeFM's terminal can run here, else the reason it cannot."""
    if not getattr(config, "EMBEDDED_TERMINAL", True):
        return "EMBEDDED_TERMINAL is off in config.py"
    if _PuiKitTerminalView is None or _terminal_available is None:
        return "this PuiKit has no TerminalView"
    return _terminal_available()


_Base = _PuiKitTerminalView if _PuiKitTerminalView is not None else object


class TerminalView(_Base):  # type: ignore[misc,valid-type]
    """One program - a subshell, a terminal program, a terminal editor - run
    in a full-window layer, as terminal mode runs it in its own terminal.

    When the program exits, ``on_exited`` gets the view and the exit code;
    the app closes the layer and re-reads the panes. A program that failed is
    left on screen with its exit bar so its last output can be read, and Enter
    or Escape closes it then. ``terminal.close`` asks the app to close it
    early (``on_close_request``), which stops a program still running."""

    def __init__(self, argv: list[str], *, cwd: str, env: dict, label: str,
                 on_exited: Callable[["TerminalView", int | None], None],
                 on_close_request: Callable[["TerminalView"], None]) -> None:
        from xefm.text_viewer import VIEWER_PAD_PX
        # The viewers' inset: the grid breathes in from the window frame on GUI
        # by the same few pixels; flush on a character grid.
        super().__init__(argv, cwd=cwd, env=env,
                         on_exit=lambda code: on_exited(self, code),
                         padding_px=VIEWER_PAD_PX)
        self.label = label
        self.on_close_request = on_close_request
        #: Called once with the exit code after the layer closes: the caller's
        #: "after the program", as code after terminal mode's blocking run.
        self.on_done: Callable[[int | None], None] | None = None
        self.exit_hint = "press Enter to return to XeFM"

    @property
    def running(self) -> bool:
        return self._exited is False

    # --- actions ---------------------------------------------------------------
    #: The command palette's view of this surface, as the viewers': its
    #: context, what it runs, and running one by name.
    palette_context = CONTEXT

    def _actions(self) -> dict:
        """What the terminal runs, by name: closing itself, and the app-wide
        actions any surface may run (xefm.surface_actions). Nothing that acts
        on the file list behind it."""
        table = {"terminal.close": lambda: self.on_close_request(self)}
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
        """Whether the key bound to ``action`` is taken from the program.

        A binding made for the terminal wins over whatever the program would
        do with the key: a ``terminal.*`` action, and a context-qualified
        ``'terminal.<action>'`` entry in config.py. A binding it merely
        inherits - ``'command_palette': ['Ctrl-T']``, written for the file
        list - is taken only on a chord no terminal program receives
        (Command, Ctrl+Shift); otherwise the key stays the program's (Ctrl-T
        transposes in a shell)."""
        if action.startswith(CONTEXT + "."):
            return True
        if self._qualified(event, action):
            return True
        mods = event.modifiers
        return "cmd" in mods or {"ctrl", "shift"} <= mods

    @staticmethod
    def _qualified(event, action: str) -> bool:
        """Whether config.py binds ``event`` to ``action`` for the terminal
        specifically (``'terminal.command_palette': ['Ctrl-T']``)."""
        from xefm.config import KeyBindings, config_manager
        keys = (getattr(config_manager.get_config(), "KEY_BINDINGS", None) or {}).get(
            f"{CONTEXT}.{action}")
        if not keys:
            return False
        return KeyBindings({action: keys}).is_action_for_event(event, action)

    def handle_event(self, event) -> bool:
        if event.type is EventType.KEY:
            action = find_action_for_event(event, context=CONTEXT)
            if action is not None and self.takes_binding(event, action) \
                    and self.run_action(action):
                return True
            if not self.running and event.key in ("enter", "escape"):
                self.on_close_request(self)
                return True
        super().handle_event(event)
        return True  # modal: nothing reaches the panes underneath
