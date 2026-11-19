"""Terminal sessions in the desktop app (discussion #900).

A *terminal session* is one program in XeFM's terminal - a pty and
libghostty (:class:`xefm.terminal.TerminalView`). Everything the desktop app
runs in its terminal is one: the subshell, a command marked
``{'terminal': True}`` (``PROGRAMS``, ``TEXT_EDITOR``, ``TEXT_DIFF``,
``FILE_ASSOCIATIONS``, ``ctx.run_program``), and a shell started from the
session list. Each can be hidden behind the panes and keeps running there; a
clean exit ends it, a failed one keeps its last screen until it is closed.
What it ran decides only what happens at that end: a shell restarts on Enter,
a program closes, then its ``on_done`` runs.

Terminal mode has none of this: it hands its own terminal over and waits.

This module is the registry, kept free of the UI so it can be tested on its
own: which sessions exist, in what order they were last on screen, and what
the session list shows for each. The app owns the views and the layers they are
pushed as.
"""

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field

_ids = itertools.count(1)


def next_id() -> int:
    """A session id not used before in this process: what ``XEFM_SESSION``
    says, so it is known before the session's program starts."""
    return next(_ids)


#: Session kinds, as the session list names them.
SHELL = "shell"
PROGRAM = "program"


@dataclass(eq=False)
class Session:
    """One terminal session: its view, what it runs and where."""

    view: object
    kind: str
    name: str
    cwd: str
    id: int = field(default_factory=next_id)
    #: Called once with the exit code when the session ends (closed by its
    #: program's clean exit, or by the user after a failed one): what the
    #: code after terminal mode's blocking run would do.
    on_done: object = None
    #: What a hidden session has to say - a notification, a long command
    #: that finished - until it is next shown: ``(kind, text)`` with kind
    #: ``done``, ``failed`` or ``attention``, as the status bar's parts.
    attention: tuple | None = None
    #: The last progress report (OSC 9;4) while it lasts: percent or None.
    progress: object = None
    #: When the command now running started (monotonic), from the prompt
    #: marks; None at the prompt.
    command_since: float | None = None

    @property
    def state(self) -> str:
        """``at prompt``, ``running a command`` (both known from shell
        integration), ``running``, or ``exited`` (with the code)."""
        view = self.view
        if getattr(view, "running", False):
            if getattr(view, "idle_at_prompt", False):
                return "at prompt"
            if self.command_since is not None:
                return "running a command"
            return "running"
        code = getattr(view, "exit_code", None)
        return "exited" if code in (None, 0) else f"exited ({code})"

    @property
    def running(self) -> bool:
        return bool(getattr(self.view, "running", False))

    @property
    def busy(self) -> bool:
        """Whether closing it would interrupt something (see
        :attr:`xefm.terminal.TerminalView.busy`)."""
        return bool(getattr(self.view, "busy", self.running))

    @property
    def label(self) -> str:
        """The list row: the name, then where it started."""
        return f"{self.name} - {_short(self.cwd)}"


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


#: The file manager's own screen - the panes, with any viewer open over them -
#: as a row of :meth:`SessionRegistry.screens`.
FILES = "files"


class SessionRegistry:
    """The sessions, in the order they were started, and the screens - the
    file manager's (:data:`FILES`) and each session's - in the order they were
    last on screen, which is how the session list offers them."""

    def __init__(self) -> None:
        self._sessions: list[Session] = []
        #: Most recently on screen first; FILES is always in it.
        self._recent: list = [FILES]

    def __iter__(self):
        return iter(list(self._sessions))

    def __len__(self) -> int:
        return len(self._sessions)

    def add(self, session: Session) -> Session:
        self._sessions.append(session)
        self._recent.append(session)  # last until it is first shown
        return session

    def remove(self, session: Session) -> None:
        if session in self._sessions:
            self._sessions.remove(session)
        if session in self._recent:
            self._recent.remove(session)

    def touch(self, screen) -> None:
        """``screen`` (a session, or FILES) just came on screen."""
        if screen is FILES or screen in self._sessions:
            self._recent.remove(screen)
            self._recent.insert(0, screen)

    def screens(self) -> list:
        """FILES and the sessions, most recently on screen first."""
        return list(self._recent)

    def for_view(self, view) -> Session | None:
        return next((s for s in self._sessions if s.view is view), None)

    def running(self) -> list[Session]:
        """The sessions whose program still runs."""
        return [s for s in self._sessions if s.running]

    def busy(self) -> list[Session]:
        """The sessions quitting would interrupt: a program running, or a
        shell in the middle of a command - not a shell idle at its prompt."""
        return [s for s in self._sessions if s.busy]

    def next_name(self, base: str) -> str:
        """``base`` for the first session of that name, then ``base 2``, ...:
        two shells side by side stay apart in the list."""
        taken = {s.name for s in self._sessions}
        if base not in taken:
            return base
        for n in itertools.count(2):
            name = f"{base} {n}"
            if name not in taken:
                return name
        raise AssertionError("unreachable")
