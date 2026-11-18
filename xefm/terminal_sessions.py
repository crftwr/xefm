"""Terminal sessions: the persistent side of XeFM's terminal (discussion #900).

A *terminal session* is one program in a terminal - a pty and libghostty in
the desktop app (:class:`xefm.terminal.TerminalView`). One-shot and persistent
are two launch policies of the same thing:

- **One-shot** (the subshell, a ``{'terminal': True}`` program, a terminal
  editor): modal, XeFM waits, and on exit the session closes and the panes
  re-read. Those never come here; ``XeFMApp._run_in_terminal_view`` runs them.
- **Persistent** (the console): toggled in and out of view, it keeps running
  while hidden and stays after its program exits, until it is closed.

This module is the registry of the persistent ones, kept free of the UI so it
can be tested on its own: which sessions exist, which one the toggle returns
to, and what the session list shows for each. The app owns the views and the
layers they are pushed as.

A one-shot never runs *inside* a persistent shell: typing a command into a
long-lived shell works only while it is idle at a prompt, and Subshell Here or
a terminal program must work whatever the console is doing, so each gets a
session of its own.
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
    """One persistent session: its view, what it runs and where."""

    view: object
    kind: str
    name: str
    cwd: str
    id: int = field(default_factory=next_id)
    #: Text to type at the prompt once the shell first reaches it: inserting
    #: into a session that is still starting (#900).
    pending_insert: str = ""
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


class SessionRegistry:
    """The persistent sessions, in the order they were started, and which one
    was used last - the one the console toggle shows."""

    def __init__(self) -> None:
        self._sessions: list[Session] = []
        self._last: Session | None = None

    def __iter__(self):
        return iter(list(self._sessions))

    def __len__(self) -> int:
        return len(self._sessions)

    def add(self, session: Session) -> Session:
        self._sessions.append(session)
        self._last = session
        return session

    def remove(self, session: Session) -> None:
        if session in self._sessions:
            self._sessions.remove(session)
        if self._last is session:
            self._last = self._sessions[-1] if self._sessions else None

    def touch(self, session: Session) -> None:
        """``session`` was just shown: the toggle returns to it next."""
        if session in self._sessions:
            self._last = session

    @property
    def last(self) -> Session | None:
        return self._last

    def for_view(self, view) -> Session | None:
        return next((s for s in self._sessions if s.view is view), None)

    def running(self) -> list[Session]:
        """The sessions whose program still runs: what quitting would stop."""
        return [s for s in self._sessions if s.running]

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
