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
group and the whole group is signalled; on Windows the shell starts in a job
object and the job is terminated. ``taskkill /T`` walked the tree once, but it
is refused — ``Access denied`` after 5 s — in an OpenSSH session, and leaves the
command running (#793); a job holds every descendant whoever its parent, and
ending it needs no rights over them. The shell is created suspended and joins
the job before it runs, so nothing it starts can escape.

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


#: ``CreateProcess``'s flag, which :mod:`subprocess` does not name.
_CREATE_SUSPENDED = 0x00000004


class _Job:
    """A Windows job object holding a process started suspended, and all it
    starts. :meth:`attach` resumes the process whether or not it could join;
    when it could not, :meth:`terminate` returns False and the caller falls
    back to ``taskkill``."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        k = self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenThread.restype = wintypes.HANDLE
        k.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.ResumeThread.argtypes = [wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.Thread32First.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        k.Thread32Next.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        self._handle = k.CreateJobObjectW(None, None)
        self._joined = False

    def attach(self, pid: int) -> None:
        k = self._k32
        if self._handle:
            process = k.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
            if process:
                self._joined = bool(k.AssignProcessToJobObject(self._handle, process))
                k.CloseHandle(process)
        if not self._joined:
            logger.warning(f"The command could not join a job object "
                           f"(error {self._ctypes.get_last_error()})")
        self._resume(pid)

    def _resume(self, pid: int) -> None:
        """Resume the threads of ``pid`` — a process created suspended has one."""
        ctypes, k = self._ctypes, self._k32
        from ctypes import wintypes

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ThreadID", wintypes.DWORD),
                        ("th32OwnerProcessID", wintypes.DWORD),
                        ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                        ("dwFlags", wintypes.DWORD)]

        snapshot = k.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if snapshot in (None, wintypes.HANDLE(-1).value):
            logger.error(f"Could not list the command's threads to start it "
                         f"(error {ctypes.get_last_error()})")
            return
        try:
            entry = THREADENTRY32(dwSize=ctypes.sizeof(THREADENTRY32))
            more = k.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32OwnerProcessID == pid:
                    thread = k.OpenThread(0x0002, False, entry.th32ThreadID)  # SUSPEND_RESUME
                    if thread:
                        k.ResumeThread(thread)
                        k.CloseHandle(thread)
                more = k.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            k.CloseHandle(snapshot)

    def terminate(self) -> bool:
        return self._joined and bool(self._k32.TerminateJobObject(self._handle, 1))

    def close(self) -> None:
        if self._handle:
            self._k32.CloseHandle(self._handle)
            self._handle = None


def _kill_tree(proc: subprocess.Popen, job: Optional[_Job]) -> None:
    """Stop ``proc`` and everything it started."""
    try:
        if _WINDOWS:
            if not (job and job.terminate()):
                said = subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                                      capture_output=True, **SUBPROCESS_NO_WINDOW)
                if said.returncode != 0:
                    logger.warning("taskkill could not stop the command's process tree: "
                                   + said.stderr.decode("mbcs", errors="replace").strip())
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
    job = None
    if _WINDOWS:
        env = dict(env, **{_COMMAND_VAR: command})
        args, shell = _windows_command_line(env), False
        popen_kwargs["creationflags"] = (popen_kwargs.get("creationflags", 0)
                                         | _CREATE_SUSPENDED)
        job = _Job()
    else:
        args, shell = command, True
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(args, shell=shell, cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **popen_kwargs)
    except OSError as e:
        if job:
            job.close()
        return CommandOutput("", None, [], False, error=str(e))
    if job:
        job.attach(proc.pid)
    try:
        return _collect(proc, job, cancelled, on_count)
    finally:
        if job:
            job.close()


def _collect(proc: subprocess.Popen, job: Optional[_Job],
             cancelled: Callable[[], bool],
             on_count: Callable[[int], None]) -> CommandOutput:
    """Read ``proc``'s output until it exits or ``cancelled()``, for :func:`run`."""

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
            _kill_tree(proc, job)
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
