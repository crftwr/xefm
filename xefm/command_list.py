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
at the end (:func:`decode_output`), because the right encoding is a property of
the whole output, not of a line.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, NamedTuple, Optional

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


def decode_output(data: bytes) -> str:
    """Text from a command's stdout, read so that each path still addresses
    the file it names.

    UTF-8 first, and a byte-order mark dropped: what nearly every tool prints
    today. Where that fails:

    - **Windows** falls back to the OEM code page — what console programs
      write to a pipe, and what ``cmd``'s own ``dir /b`` writes (cp932 on a
      Japanese system, cp437 on an American one).
    - **POSIX** decodes with the filesystem encoding and ``surrogateescape``,
      exactly as :func:`os.fsdecode` does: a name that is not valid UTF-8 is
      still a name on disk, and the escaped form round-trips to the same bytes
      when it is opened.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    if _WINDOWS:
        return data.decode("oem", errors="replace")
    return data.decode(sys.getfilesystemencoding(), errors="surrogateescape")


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
    if not _WINDOWS:
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(command, shell=True, cwd=cwd, env=env,
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

    stderr_lines = decode_output(bytes(err)).splitlines()
    return CommandOutput(decode_output(bytes(out)), proc.returncode,
                         [line for line in stderr_lines if line.strip()][-_STDERR_TAIL:],
                         stopped)
