"""XeFM's terminal (discussion #900).

Terminal mode hands its own terminal to a subshell and to any command marked
``{'terminal': True}``, waits, and re-reads the panes when they are done. The
desktop app has no terminal to hand over, so it runs them in one of its own:
:class:`TerminalView`, a full-window layer over the panes. Each one there is a
terminal session (:mod:`xefm.terminal_sessions`): it can be hidden behind the
panes and keeps running until its program exits.

The emulation is PuiKit's ``TerminalView`` (libghostty-vt over a pty); this
module decides what runs in it and what XeFM does around it. Where the widget
or libghostty is missing, :func:`unavailable` says why; the desktop app then
has no terminal to run such things in.
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

# Shell integration marks (OSC 133) and progress states (OSC 9;4), as PuiKit's
# TerminalView reports them (libghostty-vt's enums).
PROMPT_START, INPUT_START, OUTPUT_START, COMMAND_END = 1, 2, 3, 4
PROGRESS_REMOVE, PROGRESS_SET, PROGRESS_ERROR, PROGRESS_INDETERMINATE, PROGRESS_PAUSE = \
    0, 1, 2, 3, 4


def unavailable(config=None) -> str | None:
    """None when XeFM's terminal can run here, else why not."""
    if _PuiKitTerminalView is None or _terminal_available is None:
        return "this PuiKit has no TerminalView"
    return _terminal_available()


def _term_program_kwargs() -> dict:
    """``TERM_PROGRAM=XeFM`` for the programs in the terminal: the terminal
    they run in is XeFM's, as VS Code's says ``vscode`` (PuiKit sets its own
    ``PUIKIT_TERMINAL`` beside it either way). An older PuiKit takes no name
    and says ``PuiKit``."""
    import inspect
    try:
        params = inspect.signature(_PuiKitTerminalView.__init__).parameters
    except (TypeError, ValueError):
        return {}
    if "term_program" not in params:
        return {}
    from xefm import __version__
    return {"term_program": ("XeFM", __version__)}


def _supported_kwargs(**kwargs) -> dict:
    """The keyword arguments this PuiKit's TerminalView takes, of ``kwargs``:
    shell integration, notifications and progress came in a later release
    than the widget itself."""
    import inspect
    try:
        params = inspect.signature(_PuiKitTerminalView.__init__).parameters
    except (TypeError, ValueError):
        return {}
    return {k: v for k, v in kwargs.items() if k in params and v is not None}


def _user_actions() -> set:
    """The actions a config or extension put in the terminal's context."""
    from xefm.actions import registry
    return {a.name for a in registry.actions(CONTEXT) if a.is_user and a.context == CONTEXT}


_Base = _PuiKitTerminalView if _PuiKitTerminalView is not None else object


class TerminalView(_Base):  # type: ignore[misc,valid-type]
    """One terminal session's view - a shell, a terminal program, a terminal
    editor - run in a full-window layer, as terminal mode runs it in its own
    terminal.

    When the program exits, ``on_exited`` gets the view and the exit code;
    the app closes a clean exit and keeps a failed one on screen with its exit
    bar, so its last output can be read, until Enter or Escape closes it
    (``on_close_request``). A shell is not started again there, as PuiKit's
    own exit bar would on Enter: the one left on screen is a shell that
    could not start, which would fail the same way, and a restart from a
    stray Enter was what an ``exit`` that looked like a failure ran into.
    ``terminal.close`` asks the app to close it early (``on_close_request``),
    which stops a program still running; ``terminal.screens`` opens the
    app's screen switcher, where picking another screen leaves it running
    out of view. An action a config or extension put in the ``terminal``
    context runs through ``on_user_action``."""

    def __init__(self, argv: list[str], *, cwd: str, env: dict, label: str,
                 on_exited: Callable[["TerminalView", int | None], None],
                 on_close_request: Callable[["TerminalView"], None],
                 shell: bool = False,
                 on_screens_request: Callable[[], None] | None = None,
                 on_user_action: Callable[[str], bool] | None = None,
                 on_prompt: Callable[[int, int | None, str], None] | None = None,
                 on_notification: Callable[[str, str], None] | None = None,
                 on_progress: Callable[[int, int | None], None] | None = None,
                 on_title: Callable[[str], None] | None = None,
                 ctrl_clipboard: bool = True) -> None:
        from xefm.text_viewer import VIEWER_PAD_PX
        # The viewers' inset: the grid breathes in from the window frame on GUI
        # by the same few pixels; flush on a character grid.
        # ctrl_clipboard (TERMINAL_CTRL_CLIPBOARD): True keeps PuiKit's
        # default - Ctrl+C / Ctrl+V copy and paste on Windows only - and
        # False turns them off there; it never turns them on elsewhere.
        super().__init__(argv, cwd=cwd, env=env,
                         on_exit=lambda code: on_exited(self, code),
                         padding_px=VIEWER_PAD_PX, **_term_program_kwargs(),
                         **_supported_kwargs(on_prompt=on_prompt,
                                             on_notification=on_notification,
                                             on_progress=on_progress,
                                             on_title=on_title,
                                             ctrl_clipboard=None if ctrl_clipboard else False))
        self.label = label
        self.on_close_request = on_close_request
        self.on_screens_request = on_screens_request
        self.on_user_action = on_user_action
        #: A shell rather than a program: its exit after the user typed into
        #: it ends the session whatever its status (app._session_exited).
        self.shell = shell
        #: Set once the app starts closing or hiding it: it is sliding out, and
        #: keys and clicks no longer reach the program.
        self.closing = False
        #: Whether the view is on screen (a hidden session is not).
        self.shown = False
        #: Whether the user has typed (or pasted) into the program since it
        #: started. A shell that exits after that was told to - its exit
        #: status is the last command's (cmd's ``exit`` passes on ERRORLEVEL,
        #: bash's and zsh's ``$?``) - while one that exits before it could
        #: not start.
        self.typed = False
        self.exit_hint = "press Enter to close"

    @property
    def running(self) -> bool:
        return self._exited is False

    def send(self, data) -> None:
        # Every key and paste PuiKit passes to the program comes through here.
        if self.running:
            self.typed = True
        super().send(data)

    @property
    def idle_at_prompt(self) -> bool:
        """Whether its shell sits at its prompt, so typed text becomes the
        next command (shell integration; False where PuiKit or the shell
        cannot tell)."""
        return bool(getattr(self, "at_prompt", False))

    @property
    def exit_code(self) -> int | None:
        """The program's exit code once it has exited, else None."""
        return None if self._exited is False else self._exited

    @property
    def busy(self) -> bool:
        """Whether quitting would interrupt something: a program still running,
        or a shell running a command. A shell idle at its prompt is not busy -
        known from shell integration, or on POSIX from the pty's foreground
        process. A shell that neither can read counts as busy."""
        if not self.running:
            return False
        if not self.shell:
            return True
        if self.idle_at_prompt:
            return False
        return getattr(self, "child_in_foreground", None) is not True

    @property
    def started(self) -> bool:
        """Whether the program has been started: PuiKit starts it on the
        view's first draw, when it knows the grid size."""
        return self._term is not None or self._exited is not False

    # --- actions ---------------------------------------------------------------
    #: The command palette's view of this surface, as the viewers': its
    #: context, what it runs, and running one by name.
    palette_context = CONTEXT

    def _actions(self) -> dict:
        """What the terminal runs, by name: closing itself, and the app-wide
        actions any surface may run (xefm.surface_actions). Nothing that acts
        on the file list behind it."""
        table = {"terminal.close": lambda: self.on_close_request(self)}
        if self.on_screens_request is not None:
            table["terminal.screens"] = self.on_screens_request
        table.update(surface_actions.handlers())
        return table

    def palette_actions(self) -> set:
        return set(self._actions()) | set(_user_actions())

    def run_action(self, name: str) -> bool:
        handler = self._actions().get(name)
        if handler is not None:
            handler()
            return True
        if self.on_user_action is not None and name in _user_actions():
            return bool(self.on_user_action(name))
        return False

    def takes_binding(self, event, action: str) -> bool:
        """Whether the key bound to ``action`` is taken from the program.

        A binding made for the terminal wins over whatever the program would
        do with the key: a ``terminal.*`` action, and a context-qualified
        ``'terminal.<action>'`` entry in config.py. A binding it merely
        inherits - ``'command_palette': ['Ctrl-T']``, written for the file
        list - is taken only on a chord no terminal program receives
        (Command, Ctrl+Shift); otherwise the key stays the program's (Ctrl-T
        transposes in a shell)."""
        if action.startswith(CONTEXT + ".") or action in _user_actions():
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
        if self.closing:
            return True  # sliding out: the layer is leaving
        if event.type is EventType.KEY:
            action = find_action_for_event(event, context=CONTEXT)
            if action is not None and self.takes_binding(event, action) \
                    and self.run_action(action):
                return True
            if not self.running:
                # The exit bar: Enter or Escape closes it, shell or program,
                # before PuiKit's own handling would start the shell again.
                # Any other key is nobody's: the program is gone.
                if event.key in ("enter", "escape"):
                    self.on_close_request(self)
                return True
        super().handle_event(event)
        return True  # modal: nothing reaches the panes underneath
