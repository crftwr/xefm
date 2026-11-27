"""Terminal sessions in the desktop app (discussion #900).

A *terminal session* is one program in XeFM's terminal - a pty and
libghostty (:class:`xefm.terminal.TerminalView`). Everything the desktop app
runs in its terminal is one: the subshell, a command marked
``{'terminal': True}`` (``PROGRAMS``, ``TEXT_EDITOR``, ``TEXT_DIFF``,
``FILE_ASSOCIATIONS``, ``ctx.run_program``), and a shell started from the
session list. Each can be hidden behind the panes and keeps running there; a
clean exit ends it, a failed one keeps its last screen until Enter or Escape
closes it, then its ``on_done`` runs. What it ran decides only what counts as
failed: a shell's exit after the user typed into it never does (``exit``
passes on the last command's status), a program's non-zero exit does.

Terminal mode has none of this: it hands its own terminal over and waits.

This module is the registry, kept free of the UI so it can be tested on its
own: which sessions exist and what the screen switcher shows for each. Each
session has a screen (:mod:`xefm.screens`), which keeps the order screens were
on; the app owns the views and the layers they are pushed as.
"""

from __future__ import annotations

import itertools
import os
import re
import time
from dataclasses import dataclass, field

_ids = itertools.count(1)


def next_id() -> int:
    """A session id not used before in this process: what ``XEFM_SESSION``
    says, so it is known before the session's program starts."""
    return next(_ids)


#: Session kinds, as the session list names them.
SHELL = "shell"
PROGRAM = "program"
#: An AI agent session XeFM draws itself (#959): its view is an
#: :class:`xefm.agent_chat_view.ChatView`, not a terminal. It exists in
#: terminal mode too.
AGENT = "agent"

#: The groups the screens fall into (discussion #1019), besides the file
#: manager's: what a terminal runs - shells, terminal programs, an editor -
#: and AI agent sessions, drawn by XeFM or run in its terminal.
GROUP_TERMINAL = "terminal"
GROUP_AGENT = "agent"


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
    #: Called once when the session ends, XeFM quitting included: what was made
    #: for it alone goes.
    cleanup: object = None
    #: An AI agent's own sandbox (``on``, ``off``, ``not known``), "" for what
    #: is no agent.
    sandbox: str = ""
    #: What a hidden session has to say - a notification, a long command
    #: that finished - until it is next shown: ``(kind, text)`` with kind
    #: ``done``, ``failed`` or ``attention``, as the status bar's parts.
    attention: tuple | None = None
    #: The last progress report (OSC 9;4) while it lasts: percent or None.
    progress: object = None
    #: When the command now running started (monotonic), from the prompt
    #: marks; None at the prompt.
    command_since: float | None = None
    #: The command line now running, from shell integration (OSC 133;C
    #: with ``cmdline_url``); "" when unknown or at the prompt.
    command: str = ""
    #: The last title (OSC 0/2) set while it runs: ``(title, when
    #: (monotonic), the foreground program then, whether the session's own
    #: process held the foreground)``, or None. What the program calls itself
    #: (``* Claude``), as a terminal's tab shows.
    job_title: tuple | None = None
    #: Whether its name was chosen (``name=``) rather than made up from the
    #: program (``zsh``, ``zsh 2``): a chosen name heads its row in the
    #: switcher, a made-up one only when nothing else tells rows apart.
    named: bool = False
    #: The program it started, by file name without extension (``zsh``).
    program: str = ""
    #: When it was started (time.time()).
    started_at: float = field(default_factory=time.time)
    #: Its screen (:class:`xefm.screens.Screen`) while it has one.
    screen: object = None
    #: An AI agent's session run in XeFM's terminal (``'terminal': True``):
    #: a program, but one of the agent group's screens.
    agent: bool = False
    #: What an agent session is about (#1019): decided once - after its first
    #: turn, from the agent's own title or the first request - then fixed,
    #: changed only by the user's rename. "" until then.
    title: str = ""
    #: When it was last on screen (time.time()); its start until then.
    last_used_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.last_used_at:
            self.last_used_at = self.started_at

    @property
    def group(self) -> str:
        """Which group of screens it is in: :data:`GROUP_AGENT` or
        :data:`GROUP_TERMINAL`."""
        return GROUP_AGENT if self.kind == AGENT or self.agent else GROUP_TERMINAL

    @property
    def tab_label(self) -> str:
        """Its tab in the screen strip: short, and steady enough to find
        again - the title, else a chosen name, else what runs in it now, else
        the program."""
        if self.title:
            return self.title
        if self.named:
            return self.name
        return self.activity or (self.program if self.kind == SHELL and self.program
                                 else self.name)

    @property
    def state(self) -> str:
        """``at prompt``, ``running a command`` (both known from shell
        integration), ``running``, or ``exited`` (with the code)."""
        view = self.view
        chat = getattr(view, "chat_state", None)
        if chat:
            return chat  # a drawn agent session: what the conversation is doing
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

    def title_changed(self, title: str) -> None:
        """The terminal's title changed (OSC 0/2)."""
        view = self.view
        title = title.strip()
        self.job_title = (title, time.monotonic(),
                          getattr(view, "foreground_program", None),
                          getattr(view, "child_in_foreground", None) is True) \
            if title else None

    def _job_title(self) -> str:
        """The title of what runs now, or "" when there is none or it is
        stale. With shell integration, one set since the command started
        (the shell's own title at its prompt is not). Without, one set by
        the program still in the foreground - or by the session's own
        process while it still holds it: a shell that runs its jobs on ptys
        of its own (eosh) passes their titles on, and is the only one that
        can."""
        if self.job_title is None:
            return ""
        title, at, fg, own = self.job_title
        if self.command_since is not None:
            return title if at >= self.command_since else ""
        view = self.view
        if getattr(view, "idle_at_prompt", False):
            return ""
        in_front = getattr(view, "child_in_foreground", None) is True
        if own:
            return title if in_front else ""
        if in_front:
            return ""
        return title if getattr(view, "foreground_program", None) == fg else ""

    @property
    def activity(self) -> str:
        """What runs in it now, for the switcher (#954), or "": the title the
        running program set (what a terminal's tab shows), else the command
        line shell integration reported, else the program holding the pty's
        foreground (POSIX) when it is not the session's own process, else the title a
        program set (the only word from cmd or PowerShell). A program
        session's own name already says what it runs."""
        view = self.view
        if not getattr(view, "running", False):
            return ""
        own = self._job_title()
        if own:
            return own
        if self.command_since is not None and self.command:
            return self.command
        if getattr(view, "idle_at_prompt", False):
            return ""
        fg = getattr(view, "foreground_program", None)
        if fg:
            # The session's own process holds the foreground: the shell
            # itself, whatever its executable is called - a shell written in
            # Python reads as "python3.14". By name too, for a view that
            # cannot compare process ids.
            if getattr(view, "child_in_foreground", None) is True \
                    or _same_program(fg, self.program):
                return ""
            return fg
        if self.kind == SHELL:
            title = getattr(view, "title", "") or ""
            return title.strip()
        return ""

    @property
    def directory(self) -> str:
        """Where it is now: the directory the shell last reported (OSC 7,
        which XeFM's zsh and bash integration sends at every prompt), else
        where it started. A directory on another machine (a shell over ssh)
        reads ``host:/path``."""
        reported = _pwd_path(getattr(self.view, "pwd", "") or "")
        return reported or self.cwd

    @property
    def label(self) -> str:
        """The list row: what runs now (``claude``), else what the session
        is (``zsh``), then where it is - a chosen name first. Two rows that
        read the same are told apart with :attr:`full_label`."""
        doing = self.activity
        if self.title:
            parts = [self.title] + ([doing] if doing and doing != self.title else [])
            return " - ".join(parts + [_short(self.directory)])
        if self.named:
            return self.full_label
        what = doing or (self.program if self.kind == SHELL and self.program else self.name)
        return f"{what} - {_short(self.directory)}"

    @property
    def full_label(self) -> str:
        """The name, what runs now, then where it is (``zsh 2 - make - ~``)."""
        doing = self.activity
        parts = [self.name] + ([self.title] if self.title else []) \
            + ([doing] if doing and doing != self.title else []) + [_short(self.directory)]
        return " - ".join(parts)


def _pwd_path(pwd: str) -> str:
    """The path in an OSC 7 report: a ``file://host/path`` URL, its path
    percent-encoded (some shells send a bare path). "" when it says none."""
    pwd = pwd.strip()
    if not pwd.startswith("file://"):
        return pwd
    from urllib.parse import unquote, urlsplit
    url = urlsplit(pwd)
    path = unquote(url.path)
    if os.name == "nt" and len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]  # file:///C:/Users -> C:/Users
    host = url.hostname or ""
    if host and host != "localhost" and not _is_this_host(host):
        return f"{host}:{path}"
    return path


def _is_this_host(host: str) -> bool:
    import socket
    names = {socket.gethostname().lower()}
    names.add(next(iter(names)).split(".")[0])
    return host.lower() in names or host.lower().split(".")[0] in names


def _same_program(a: str, b: str) -> bool:
    """Whether two program names name the same thing (``-zsh``, ``zsh.exe``)."""
    def norm(n: str) -> str:
        return os.path.splitext(os.path.basename(n))[0].lstrip("-").lower()
    return bool(b) and norm(a) == norm(b)


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


#: The longest title a session takes from its first request (#1019).
TITLE_MAX = 40


def title_from_request(text: str, limit: int = TITLE_MAX) -> str:
    """A session's title from a request: its first line that says something,
    spaces run together, cut at a word to ``limit`` characters with ``…``."""
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    line = " ".join(line.split())
    if len(line) <= limit:
        return line
    cut = line[:limit - 1]
    if " " in cut[limit // 2:]:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,.;:") + "…"


#: The marks a program puts in front of its terminal title - a spinner, a
#: star - which are no part of what the title says.
_TITLE_MARKS = re.compile(r"^[^\w(\[\"'`]+")


def title_from_terminal(title: str, generic: set[str]) -> str:
    """What an agent's terminal title (OSC 0/2) says the session is about, or
    "" when it says only what the program is (one of ``generic``, compared
    without case): ``✳ Fix the login bug`` gives ``Fix the login bug``,
    ``✳ Claude Code`` nothing."""
    text = _TITLE_MARKS.sub("", title or "").strip()
    if not text or text.lower() in {g.lower() for g in generic}:
        return ""
    return title_from_request(text)


@dataclass(eq=False)
class ClosedAgent:
    """An AI agent conversation closed in XeFM, kept to resume (#1019):
    which agent (its ``AGENTS`` name), where, the agent's own id for the
    conversation, its title, and - closed in this run - the conversation
    itself, so it comes back as it was."""

    agent: str
    cwd: str
    session_id: str
    title: str
    closed_at: float
    conversation: object = None

    def to_state(self) -> dict:
        return {"agent": self.agent, "cwd": self.cwd, "session_id": self.session_id,
                "title": self.title, "closed_at": self.closed_at}

    @classmethod
    def from_state(cls, raw) -> "ClosedAgent | None":
        if not isinstance(raw, dict):
            return None
        try:
            record = cls(agent=str(raw["agent"]), cwd=str(raw["cwd"]),
                         session_id=str(raw["session_id"]), title=str(raw["title"]),
                         closed_at=float(raw.get("closed_at") or 0.0))
        except (KeyError, TypeError, ValueError):
            return None
        return record if record.agent and record.session_id else None


def ago(when: float, now: float | None = None) -> str:
    """How long ago ``when`` was, in a word: ``now``, ``5m ago``, ``3h ago``,
    ``2d ago``."""
    secs = max(0.0, (now if now is not None else time.time()) - when)
    if secs < 60:
        return "now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


class SessionRegistry:
    """The sessions, in the order they were started."""

    def __init__(self) -> None:
        self._sessions: list[Session] = []

    def __iter__(self):
        return iter(list(self._sessions))

    def __len__(self) -> int:
        return len(self._sessions)

    def add(self, session: Session) -> Session:
        self._sessions.append(session)
        return session

    def remove(self, session: Session) -> None:
        if session in self._sessions:
            self._sessions.remove(session)

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
