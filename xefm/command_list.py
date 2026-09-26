#!/usr/bin/env python3
"""Run a command and keep what it prints: the command source for a file list.

Midnight Commander calls this *External panelize*: run ``find``, ``fd``,
``rg -l``, ``git ls-files`` or Everything's ``es.exe``, and whatever lines it
prints to stdout become the pane (#453 ③). This module is the blocking half —
start the command, read its output, stop it when asked — with no pane and no
panel in sight, so it runs on a task worker and is tested on its own. What the
lines mean is :mod:`xefm.path_list`'s business.

**Through the shell.** The command is a line the user typed, so it is handed to
the platform's shell (``/bin/sh`` or ``cmd.exe``) as one: pipes, globs and
quoting mean what they mean at a prompt.

**Stopping stops the tree.** A shell runs the command as its child, and a
pipeline as several; killing the shell alone leaves them running, still
writing into a pipe nobody reads. On POSIX the command gets its own process
group and the whole group is signalled; on Windows ``taskkill /T`` walks the
tree.

**Bytes in, text out, paths intact.** Output is read as bytes and decoded once
at the end (:func:`xefm.path_list.decode`), because the right encoding is a property of
the whole output, not of a line.

**UTF-8 on Windows, asked for.** A console program writes to a pipe in its
console's output code page, and a GUI process's child gets a console whose code
page is the system OEM one — cp437 on an English system, where every Japanese
name comes out as ``????`` and is lost before XeFM sees a byte. Everything's
``es.exe`` and ``cmd``'s own ``dir /b`` both behave so.

``chcp 65001`` switches the console to UTF-8, but ``cmd`` reads the code page
once, when it starts: a program started after ``chcp`` writes UTF-8, and the
``cmd`` that ran ``chcp`` goes on writing its built-ins (``dir``, ``echo``,
``for``) in cp437. So the user's command runs in a *second* ``cmd``, started
after ``chcp`` (:func:`_windows_command_line`). The obvious spelling,
``chcp 65001 & cmd /c <command>``, has the outer ``cmd`` parse the command
first and split its ``&&`` and ``|`` wrongly. Instead the command travels in
an environment variable and reaches the inner ``cmd`` through *delayed*
expansion, ``!XEFM_LIST_COMMAND!``, which happens after the outer ``cmd`` has
finished parsing — so the only ``cmd`` that parses it is the one that runs it,
exactly as at a prompt: ``%VAR%`` expands, ``!`` stays literal, ``^`` escapes.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, NamedTuple, Optional

from xefm import path_list
from xefm.external_programs import SUBPROCESS_NO_WINDOW
from xefm.log_manager import getLogger

logger = getLogger("ListCmd")

_WINDOWS = sys.platform == "win32"

#: How often the run loop looks at the cancel flag while the command runs.
_POLL = 0.05

#: How many trailing stderr lines are kept to report. A command that fails
#: usually says why at the end; one that writes a megabyte of warnings does not
#: need all of it in the log pane.
_STDERR_TAIL = 5


class CommandOutput(NamedTuple):
    """:func:`run`'s answer. ``code`` is ``None`` when the command could not be
    started at all, in which case ``error`` says why."""
    stdout: str
    code: Optional[int]
    stderr_tail: list
    cancelled: bool
    error: str = ""


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop ``proc`` and everything it started."""
    try:
        if _WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           **SUBPROCESS_NO_WINDOW)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError) as e:
        logger.warning(f"Could not stop the command's process tree: {e}")
    try:
        proc.kill()
    except OSError:
        pass


#: The environment variable the command reaches the inner ``cmd`` through.
_COMMAND_VAR = "XEFM_LIST_COMMAND"


def _windows_command_line(env: dict) -> str:
    """The ``CreateProcess`` command line that runs ``env[_COMMAND_VAR]`` in a
    ``cmd`` started after ``chcp 65001`` — see the module docstring.

    ``/s /c "…"`` makes each ``cmd`` strip exactly the outer pair of quotes and
    run what is inside as written. ``/d`` skips AutoRun, whose output would
    otherwise land in the list. ``/v:on`` is the outer ``cmd``'s alone: the
    inner one keeps delayed expansion off, so a ``!`` in the user's command —
    Everything's NOT operator — is left as typed."""
    comspec = env.get("COMSPEC") or os.environ.get("COMSPEC") or "cmd.exe"
    return (f'"{comspec}" /d /v:on /s /c "chcp 65001>nul & '
            f'"{comspec}" /d /s /c "!{_COMMAND_VAR}!""')


def run(command: str, *, cwd: str, env: dict,
        cancelled: Callable[[], bool] = lambda: False,
        on_count: Callable[[int], None] = lambda n: None) -> CommandOutput:
    """Run ``command`` through the shell in ``cwd`` and return its output.

    Blocks until the command exits or ``cancelled()`` turns true, so call it
    on a worker. stdin reads EOF, so a command that waits for input ends
    instead of hanging. ``on_count(n)`` reports how many lines stdout has
    produced so far, for a progress display.
    """
    popen_kwargs = dict(SUBPROCESS_NO_WINDOW)
    if _WINDOWS:
        env = dict(env, **{_COMMAND_VAR: command})
        args, shell = _windows_command_line(env), False
    else:
        args, shell = command, True
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(args, shell=shell, cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **popen_kwargs)
    except OSError as e:
        return CommandOutput("", None, [], False, error=str(e))

    out = bytearray()
    err = bytearray()

    def read_out() -> None:
        lines = 0
        for chunk in iter(lambda: proc.stdout.read1(65536), b""):
            out.extend(chunk)
            lines += chunk.count(b"\n")
            on_count(lines)
        proc.stdout.close()

    def read_err() -> None:
        for chunk in iter(lambda: proc.stderr.read1(65536), b""):
            err.extend(chunk)
        proc.stderr.close()

    readers = [threading.Thread(target=read_out, name="xefm-listcmd-out", daemon=True),
               threading.Thread(target=read_err, name="xefm-listcmd-err", daemon=True)]
    for t in readers:
        t.start()

    stopped = False
    while proc.poll() is None:
        if cancelled():
            _kill_tree(proc)
            stopped = True
            break
        time.sleep(_POLL)
    proc.wait()
    for t in readers:
        t.join(timeout=5)

    stderr_lines = path_list.decode(bytes(err)).splitlines()
    return CommandOutput(path_list.decode(bytes(out)), proc.returncode,
                         [line for line in stderr_lines if line.strip()][-_STDERR_TAIL:],
                         stopped)
