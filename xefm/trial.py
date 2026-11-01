"""``xefm try`` — XeFM in a throwaway home, by hand or from a script (#682).

Two jobs need XeFM running where nothing of the user's is: an automated test
that drives the real app and reads what it shows, and a demo recorded for a
README or a release note. An extension's author needs it too: ``xefm ext
check`` is static and the unit tests run against a fake ``ctx``, so menus,
dialogs, task progress and cancel go untested until a person tries them
(running the TUI like this caught #679, which both had missed). One command
serves all three:

- **A throwaway home.** ``HOME`` (and ``USERPROFILE``) point at a temporary
  directory, so the user's ``~/.xefm`` is never read or written. It holds
  XeFM's template config (or the one given), the packages given with
  ``--ext`` installed the way ``xefm ext install`` installs them, and nothing
  else. The keymap preset is chosen and the Tip of the Day is off, so no
  first-run dialog takes the first keys; the home is removed at exit.
- **Interactive** (no ``--keys``): the TUI in this terminal, for a person.
- **Scripted** (``--keys steps.json``): the TUI in a pseudo-terminal of a fixed
  size, read as text through a terminal emulator. Each step's keys go in, the
  screen settles, and its text is saved; the whole session can be recorded as
  an asciicast v2 file a player can replay. It exits when the script ends, so
  it can never block the shell that ran it — the one way an agent may launch
  XeFM.

Scripted mode needs ``pyte`` (the emulator) and quality-loop's key notation:
``pip install 'quality-loop[tui]'`` brings both. The pseudo-terminal is a pty
on macOS and Linux and a pseudoconsole (ConPTY) on Windows.
"""

from __future__ import annotations

import codecs
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from xefm import event_log
from xefm import extensions as ext
from xefm.external_programs import xefm_python


#: The fixture the left pane opens on when no ``--left`` is given: a few
#: files and a folder, enough for selection and navigation.
_FIXTURE = {"a.txt": "alpha\n", "b.txt": "bravo\n", "c.md": "# charlie\n",
            "folder/d.txt": "delta\n"}

#: Seconds after a lone Esc before the next key. A terminal app cannot tell
#: Esc followed quickly by a key from Alt+that key, so it waits a moment
#: (PuiKit 0.1s) for the rest of a sequence.
ESC_SETTLE = 0.3


class TryError(Exception):
    """A try that could not start, and why."""


# --- the home -----------------------------------------------------------------

class TryHome:
    """A temporary ``~`` holding the given packages and nothing of the
    user's."""

    def __init__(self, packages: list[str] = (), *, keymap: str = "afx",
                 config: Path | None = None):
        from xefm import keymap_presets
        from xefm.state_manager import StateManager
        if keymap_presets.canonical(keymap) not in keymap_presets.PRESETS:
            raise TryError(f"no keymap preset {keymap!r} "
                           f"({', '.join(sorted(keymap_presets.PRESETS))})")
        self.root = Path(tempfile.mkdtemp(prefix="xefm-try-")).resolve()
        try:
            self.xefm = self.root / ".xefm"
            self.xefm.mkdir()
            self.work = self.root / "work"
            for name, text in _FIXTURE.items():
                (self.work / name).parent.mkdir(parents=True, exist_ok=True)
                (self.work / name).write_text(text, encoding="utf-8")
            if config is not None:
                shutil.copyfile(config, self.xefm / "config.py")
            # The two dialogs a fresh home opens: each would take the first
            # keys a script sends (an Esc meant for something else picked a
            # keymap preset, and the rest of the script ran against it).
            state = StateManager(self.xefm / "state.db")
            state.set_state("tips.enabled", False)
            state.set_state("keymap.preset", keymap_presets.canonical(keymap))
            layout = ext.Layout(self.xefm)
            #: The installed packages' manifests, in the order given.
            self.manifests = [ext.install(str(source), layout) for source in packages]
            if any(m.requires.get("python_packages") for m in self.manifests):
                from xefm import python_packages as pp
                pp.sync(pp.Layout(layout.home), log=print)
        except BaseException:
            self.remove()
            raise

    def environment(self) -> dict:
        """For the XeFM that runs here: this home as ``~``, and this XeFM's
        own package first on the path, so the copy that runs is this one (the
        one that installed the packages)."""
        package_parent = str(Path(ext.__file__).resolve().parent.parent)
        path = os.pathsep.join(p for p in (package_parent, os.environ.get("PYTHONPATH"))
                               if p)
        return {"HOME": str(self.root), "USERPROFILE": str(self.root),
                "PYTHONPATH": path}

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def xefm_argv(left: Path, right: Path) -> list[str]:
    """The terminal XeFM, started by the interpreter that runs this one (not a
    bundle's launcher, which would open the desktop app)."""
    return [xefm_python, "-c",
            "import sys; sys.argv[0] = 'xefm'; from xefm.app import main; main()",
            "--backend", "tui", "--left", str(left), "--right", str(right)]


def run_interactive(home: TryHome, argv: list[str]) -> int:
    """The TUI in this terminal, until the person quits it."""
    return subprocess.call(argv, cwd=str(home.root),
                           env={**os.environ, **home.environment()})


# --- the script ---------------------------------------------------------------

@dataclass
class Step:
    """One step of a script: keys sent, then a wait for the screen to settle.

    ``keys`` is in quality-loop's notation: ``"Ctrl-Shift-P"``, ``"Enter"``,
    ``"a"``, ``{"text": "..."}``, ``{"pause": 0.5}``. A timed sequence (keys
    while a task runs) goes in one step with pauses inside it: between steps
    the runner waits for quiet, which a progress dialog that keeps repainting
    never gives."""
    keys: list
    intent: str = ""
    quiet: float = 0.4
    patience: float = 10.0


def read_script(path: Path) -> list[Step]:
    """A JSON list of steps; each an object with ``keys`` and optionally
    ``intent``, ``quiet`` and ``patience`` (seconds)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise TryError(f"cannot read the script {path}: {e}") from None
    if not isinstance(data, list):
        raise TryError(f"{path}: a script is a JSON list of steps")
    keys = _keys_module()
    steps = []
    for n, item in enumerate(data, 1):
        if not isinstance(item, dict) or "keys" not in item:
            raise TryError(f"{path}: step {n} is not an object with \"keys\"")
        unknown = set(item) - {"keys", "intent", "quiet", "patience"}
        if unknown:
            raise TryError(f"{path}: step {n} has unknown fields: {', '.join(sorted(unknown))}")
        try:
            sequence = keys.sequence(item["keys"])
            for key in sequence:
                if isinstance(key, keys.Key):
                    keys.terminal_bytes(key)   # refuse what a terminal cannot send
        except keys.KeysError as e:
            raise TryError(f"{path}: step {n}: {e}") from None
        steps.append(Step(keys=sequence, intent=str(item.get("intent", "")),
                          quiet=float(item.get("quiet", 0.4)),
                          patience=float(item.get("patience", 10.0))))
    return steps


def _keys_module():
    try:
        from quality_loop.drive import keys
    except ImportError:
        raise TryError("--keys needs quality-loop's key notation and pyte: "
                       "pip install 'quality-loop[tui]'") from None
    return keys


def _pyte():
    try:
        import pyte
    except ImportError:
        raise TryError("--keys needs the pyte terminal emulator: "
                       "pip install 'quality-loop[tui]'") from None
    return pyte


# --- the recording ------------------------------------------------------------

class Recording:
    """An asciicast v2 file: a header, then ``[t, "o", text]`` for everything
    the app wrote and ``[t, "m", label]`` for each step, so a player shows the
    steps as chapters. The header carries the size the app draws at for the
    whole session (it is never resized), so a player lays every row where the
    app did."""

    def __init__(self, path: Path, rows: int, cols: int):
        self._file = open(path, "w", encoding="utf-8")
        self._start = time.monotonic()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._lock = threading.Lock()
        self._line({"version": 2, "width": cols, "height": rows,
                    "timestamp": int(time.time()),
                    "env": {"TERM": "xterm-256color"}})

    def _line(self, value) -> None:
        with self._lock:
            self._file.write(json.dumps(value, ensure_ascii=False) + "\n")

    def _now(self) -> float:
        return round(time.monotonic() - self._start, 6)

    def output(self, data: bytes) -> None:
        # Incremental: a read can end inside a multi-byte character.
        text = self._decoder.decode(data)
        if text:
            self._line([self._now(), "o", text])

    def marker(self, label: str) -> None:
        self._line([self._now(), "m", label])

    def close(self) -> None:
        self._file.close()


# --- what colour alone shows --------------------------------------------------

#: How far from grey a background must be to count as a highlight: the spread
#: between its strongest and weakest channel, 0 to 1. Panels, shadows and
#: separators are greys (spread near 0); the selection, the menu row under
#: the cursor and the status bars are tinted (0.3 and up in the themes XeFM
#: ships).
_TINT = 0.15

#: pyte's names for the 16-colour palette's greys.
_GREY_NAMES = {"default", "black", "white", "brightblack", "brightwhite"}


def _tinted(colour: str) -> bool:
    if colour in _GREY_NAMES:
        return False
    if len(colour) != 6:
        return True  # a named colour: red, blue, …
    try:
        channels = [int(colour[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return False
    return max(channels) - min(channels) >= _TINT


def highlights(screen) -> list[dict]:
    """The runs of a pyte screen drawn on a tinted background or in reverse
    video — what the text screen loses: which files are selected, which menu
    row is under the cursor. (The cursor row of a file list needs no help: it
    is drawn between ``[`` and ``]``.) Each is ``{"line", "from", "to",
    "text"}``, 1-based like the lines and columns of the screen file."""
    out = []
    for y in range(screen.lines):
        row = screen.buffer[y]
        run = None
        for x in range(screen.columns + 1):
            cell = row[x] if x < screen.columns else None
            key = (cell.bg, cell.reverse) if cell and (
                cell.reverse or _tinted(cell.bg)) else None
            if run and key != run["key"]:
                text = run["text"].strip()
                if text:
                    out.append({"line": y + 1, "from": run["x"] + 1, "to": x,
                                "text": text})
                run = None
            if key and run is None:
                run = {"key": key, "x": x, "text": ""}
            if run:
                run["text"] += cell.data
    return out


def screen_file(text: str, marks: list[dict]) -> str:
    """A step's screen file: the screen, then its highlights under a rule."""
    if not marks:
        return text + "\n"
    rows = [f"{m['line']}:{m['from']}-{m['to']}  {m['text']}" for m in marks]
    return (text + "\n\n--- highlighted (line:columns) ---\n"
            + "\n".join(rows) + "\n")


# --- the terminal -------------------------------------------------------------

class _PosixTerminal:
    """A pseudo-terminal pair: the app on the slave side in a session of its
    own, this side reading and writing the master."""

    def __init__(self, argv: list[str], *, rows: int, cols: int, env: dict, cwd: str):
        import fcntl
        import struct
        import termios
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self._master = master
        self.process = subprocess.Popen(
            argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
            start_new_session=True, close_fds=True)
        os.close(slave)

    def read(self) -> bytes | None:
        """What the app wrote: None when nothing came within a moment, b"" once
        the terminal is gone."""
        try:
            ready, _w, _x = select.select([self._master], [], [], 0.1)
            if not ready:
                return None
            return os.read(self._master, 65536)
        except OSError:
            return b""

    def write(self, data: bytes) -> None:
        os.write(self._master, data)

    def stop(self, grace: float) -> None:
        """End the app: its process group, politely and then not."""
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                self.process.wait(grace)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except OSError:
                    pass
                self.process.wait()

    def close(self) -> None:
        try:
            os.close(self._master)
        except OSError:
            pass


class _WindowsProcess:
    """The little of :class:`subprocess.Popen` the runner uses, over a process
    handle from ``CreateProcessW`` (which Popen cannot start: it has no way to
    pass the pseudoconsole attribute)."""

    _WAIT_TIMEOUT = 0x102

    def __init__(self, k32, handle, pid: int):
        self._k32, self._handle, self.pid = k32, handle, pid
        self.returncode: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        if self.returncode is None and \
                self._k32.WaitForSingleObject(self._handle, ms) == self._WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired("xefm", timeout)
        return self.poll()

    def poll(self) -> int | None:
        if self.returncode is None and self._k32.WaitForSingleObject(self._handle, 0) == 0:
            import ctypes
            code = ctypes.c_ulong()
            self._k32.GetExitCodeProcess(self._handle, ctypes.byref(code))
            self.returncode = code.value
        return self.returncode


class _ConPtyTerminal:
    """A Windows pseudoconsole (ConPTY): the app attached to a console of a
    fixed size that turns what it draws into VT sequences on one pipe and the
    VT input written to the other into key events. A job object holds the app
    and anything it starts, so the end of a run takes them all."""

    _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
    _EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400
    _CREATE_SUSPENDED = 0x00000004
    _STARTF_USESTDHANDLES = 0x00000100
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JobObjectExtendedLimitInformation = 9

    def __init__(self, argv: list[str], *, rows: int, cols: int, env: dict, cwd: str):
        import ctypes
        import msvcrt
        from ctypes import wintypes
        self._ctypes = ctypes
        k32 = self._k32 = _kernel32()
        self._hpc = self._job = self._attributes = None
        self._handles: list = []
        self._fds: list[int] = []
        try:
            # Ours: we write the app's input to one and read its screen from
            # the other. The ends handed to the pseudoconsole are duplicated
            # into it, so they are closed here once it has them.
            in_read, self._in_write = os.pipe()
            self._out_read, out_write = os.pipe()
            self._fds = [self._in_write, self._out_read]
            hpc = wintypes.HANDLE()
            hr = k32.CreatePseudoConsole(_COORD(cols, rows), msvcrt.get_osfhandle(in_read),
                                         msvcrt.get_osfhandle(out_write), 0,
                                         ctypes.byref(hpc))
            os.close(in_read)
            os.close(out_write)
            if hr != 0:
                raise TryError(f"CreatePseudoConsole failed (0x{hr & 0xFFFFFFFF:08x})")
            self._hpc = hpc

            size = ctypes.c_size_t()
            k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            self._attributes = ctypes.create_string_buffer(size.value)
            if not k32.InitializeProcThreadAttributeList(self._attributes, 1, 0,
                                                         ctypes.byref(size)):
                raise _win_error("InitializeProcThreadAttributeList")
            if not k32.UpdateProcThreadAttribute(
                    self._attributes, 0, self._PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                    hpc, ctypes.sizeof(hpc), None, None):
                raise _win_error("UpdateProcThreadAttribute")

            info = _STARTUPINFOEXW()
            info.StartupInfo.cb = ctypes.sizeof(info)
            # Null standard handles, explicitly: left unset, a child of a
            # process whose own output is redirected (an agent's shell) can
            # inherit those handles and write past the pseudoconsole.
            info.StartupInfo.dwFlags = self._STARTF_USESTDHANDLES
            info.lpAttributeList = ctypes.cast(self._attributes, ctypes.c_void_p)
            block = "".join(f"{k}={v}\0" for k, v in
                            sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"
            environment = (ctypes.c_wchar * len(block)).from_buffer_copy(
                block.encode("utf-16-le"))
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            process = _PROCESS_INFORMATION()
            if not k32.CreateProcessW(
                    None, command, None, None, False,
                    self._EXTENDED_STARTUPINFO_PRESENT | self._CREATE_UNICODE_ENVIRONMENT
                    | self._CREATE_SUSPENDED,
                    environment, cwd, ctypes.byref(info.StartupInfo),
                    ctypes.byref(process)):
                raise _win_error("CreateProcessW")
            self._handles = [process.hProcess, process.hThread]
            self._job = self._kill_on_close_job()
            if not k32.AssignProcessToJobObject(self._job, process.hProcess):
                raise _win_error("AssignProcessToJobObject")
            k32.ResumeThread(process.hThread)
            self.process = _WindowsProcess(k32, process.hProcess, process.dwProcessId)
        except BaseException:
            if self._handles:
                k32.TerminateProcess(self._handles[0], 1)
            self.close()
            raise

    def _kill_on_close_job(self):
        ctypes = self._ctypes
        job = self._k32.CreateJobObjectW(None, None)
        if not job:
            raise _win_error("CreateJobObjectW")
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self._k32.SetInformationJobObject(job, self._JobObjectExtendedLimitInformation,
                                          ctypes.byref(limits), ctypes.sizeof(limits))
        return job

    def read(self) -> bytes | None:
        # A blocking read on the reader thread; it ends when the
        # pseudoconsole closes, which close() and stop() see to.
        try:
            return os.read(self._out_read, 65536)
        except OSError:
            return b""

    def write(self, data: bytes) -> None:
        os.write(self._in_write, data)

    def stop(self, grace: float) -> None:
        """End the app: closing the pseudoconsole sends it CTRL_CLOSE_EVENT,
        as closing a console window does; then the job takes what is left."""
        if self.process.poll() is None:
            self._close_console()
            try:
                self.process.wait(grace)
            except subprocess.TimeoutExpired:
                self._k32.TerminateJobObject(self._job, 1)
                self.process.wait()
        self._close_console()

    def _close_console(self) -> None:
        if self._hpc is not None:
            # Blocks until the screen pipe is drained on older Windows, which
            # the reader thread is still doing.
            self._k32.ClosePseudoConsole(self._hpc)
            self._hpc = None

    def close(self) -> None:
        self._close_console()
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds = []
        for handle in self._handles + ([self._job] if self._job else []):
            self._k32.CloseHandle(handle)
        self._handles, self._job = [], None
        if self._attributes is not None:
            self._k32.DeleteProcThreadAttributeList(self._attributes)
            self._attributes = None


def _win_error(what: str) -> TryError:
    import ctypes
    return TryError(f"{what} failed: {ctypes.FormatError(ctypes.get_last_error())}")


_K32 = None


def _kernel32():
    """kernel32 with a prototype for every call above: ctypes would take each
    handle for a C int, which truncates it on 64-bit Windows."""
    global _K32, _COORD, _STARTUPINFOEXW, _PROCESS_INFORMATION, \
        _JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    if _K32 is not None:
        return _K32
    import ctypes
    from ctypes import wintypes

    class COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                    ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                    ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                    ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                    ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _COORD, _STARTUPINFOEXW, _PROCESS_INFORMATION = COORD, STARTUPINFOEXW, PROCESS_INFORMATION
    _JOBOBJECT_EXTENDED_LIMIT_INFORMATION = JOBOBJECT_EXTENDED_LIMIT_INFORMATION

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    H, DWORD, BOOL = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    prototypes = {
        "CreatePseudoConsole": (ctypes.c_long, [COORD, H, H, DWORD, ctypes.POINTER(H)]),
        "ClosePseudoConsole": (None, [H]),
        "InitializeProcThreadAttributeList": (
            BOOL, [ctypes.c_void_p, DWORD, DWORD, ctypes.POINTER(ctypes.c_size_t)]),
        "UpdateProcThreadAttribute": (
            BOOL, [ctypes.c_void_p, DWORD, ctypes.c_size_t, H, ctypes.c_size_t,
                   ctypes.c_void_p, ctypes.c_void_p]),
        "DeleteProcThreadAttributeList": (None, [ctypes.c_void_p]),
        "CreateProcessW": (
            BOOL, [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                   BOOL, DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                   ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]),
        "CreateJobObjectW": (H, [ctypes.c_void_p, wintypes.LPCWSTR]),
        "SetInformationJobObject": (BOOL, [H, ctypes.c_int, ctypes.c_void_p, DWORD]),
        "AssignProcessToJobObject": (BOOL, [H, H]),
        "TerminateJobObject": (BOOL, [H, wintypes.UINT]),
        "TerminateProcess": (BOOL, [H, wintypes.UINT]),
        "ResumeThread": (DWORD, [H]),
        "WaitForSingleObject": (DWORD, [H, DWORD]),
        "GetExitCodeProcess": (BOOL, [H, ctypes.POINTER(DWORD)]),
        "CloseHandle": (BOOL, [H]),
    }
    for name, (restype, argtypes) in prototypes.items():
        function = getattr(k32, name)
        function.restype, function.argtypes = restype, argtypes
    _K32 = k32
    return k32


class PtyApp:
    """One terminal app under a pseudo-terminal of a fixed size — a pty on
    POSIX, a pseudoconsole on Windows — its screen kept as text by a terminal
    emulator kept in step with everything it writes."""

    def __init__(self, argv: list[str], *, rows: int, cols: int, env: dict,
                 cwd: str, recording: Recording | None = None):
        pyte = _pyte()
        self.rows, self.cols = rows, cols
        self.screen = pyte.Screen(cols, rows)
        self._stream = pyte.ByteStream(self.screen)
        self._recording = recording
        # The app's answers to queries (cursor position, device attributes)
        # go back down the pty, or an app that asks waits forever.
        self.screen.write_process_input = lambda data: self._write(data.encode("utf-8"))
        terminal = _ConPtyTerminal if os.name == "nt" else _PosixTerminal
        self._terminal = terminal(
            argv, rows=rows, cols=cols, cwd=cwd,
            env={**os.environ, **env, "TERM": "xterm-256color",
                 "LINES": str(rows), "COLUMNS": str(cols)})
        self.process = self._terminal.process
        self._lock = threading.Lock()
        self._changed = self._sent = time.monotonic()
        self._closed = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        while not self._closed:
            data = self._terminal.read()
            if data is None:
                continue
            if not data:
                break
            with self._lock:
                if self._recording is not None:
                    self._recording.output(data)
                self._stream.feed(data)
                self._changed = time.monotonic()

    def _write(self, data: bytes) -> None:
        if not self._closed:
            try:
                self._terminal.write(data)
            except OSError:
                pass  # the app is gone; what it would have read goes nowhere

    def send(self, items: list) -> None:
        keys = _keys_module()
        for item in items:
            if isinstance(item, keys.Pause):
                time.sleep(item.seconds)
            elif isinstance(item, keys.Text):
                self._write(item.text.encode("utf-8"))
            else:
                self._write(keys.terminal_bytes(item))
                if item.name == "Esc" and not item.mods:
                    time.sleep(ESC_SETTLE)
            time.sleep(0.02)
        self._sent = time.monotonic()

    def text(self) -> str:
        """The screen, one line per row, trailing blanks trimmed."""
        with self._lock:
            lines = [line.rstrip() for line in self.screen.display]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    def highlights(self) -> list[dict]:
        with self._lock:
            return highlights(self.screen)

    def wait_quiet(self, quiet: float, patience: float) -> bool:
        """Wait until the app has written nothing for ``quiet`` seconds, counted
        from the last key as well as the last output (a key answered with
        nothing would otherwise be "settled" on the silence before it). False
        if it was still writing when ``patience`` ran out."""
        deadline = time.monotonic() + patience
        while time.monotonic() < deadline:
            with self._lock:
                since = time.monotonic() - max(self._changed, self._sent)
            if since >= quiet or self.process.poll() is not None:
                return True
            time.sleep(min(quiet / 4, 0.1))
        return False

    def stop(self, grace: float = 3.0) -> int | None:
        """End the app, politely and then not, and the terminal with it."""
        self._terminal.stop(grace)
        self._closed = True
        self._reader.join(1.0)
        self._terminal.close()
        return self.process.returncode


@dataclass
class ScriptResult:
    steps: int = 0
    unsettled: list = field(default_factory=list)
    exited: int | None = None


def run_script(home: TryHome, argv: list[str], steps: list[Step], *, screens: Path,
               record: Path | None = None, rows: int = 40, cols: int = 120,
               startup: float = 20.0) -> ScriptResult:
    """Drive the TUI through ``steps``. ``screens`` gets ``00.txt`` (the screen
    once XeFM has started), ``NN.txt`` after each step, and ``steps.jsonl``:
    per step its intent, the keys as sent, whether the screen settled, what
    was highlighted, and the event-log lines (messages, exceptions) XeFM wrote
    during it."""
    keys = _keys_module()
    screens.mkdir(parents=True, exist_ok=True)
    events_path = home.root / "events.jsonl"
    events_path.touch()
    recording = Recording(record, rows, cols) if record else None
    result = ScriptResult()
    app = PtyApp(argv, rows=rows, cols=cols, cwd=str(home.root), recording=recording,
                 env={**home.environment(), event_log.EVENTS_ENV: str(events_path)})
    seen = 0

    def new_events() -> list:
        nonlocal seen
        try:
            with open(events_path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        fresh, seen = lines[seen:], len(lines)
        out = []
        for line in fresh:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    try:
        with open(screens / "steps.jsonl", "w", encoding="utf-8") as log:
            settled = app.wait_quiet(quiet=1.0, patience=startup)
            marks = app.highlights()
            (screens / "00.txt").write_text(screen_file(app.text(), marks),
                                            encoding="utf-8")
            log.write(json.dumps({"step": 0, "intent": "start", "settled": settled,
                                  "screen": "00.txt", "highlighted": marks,
                                  "events": new_events()},
                                 ensure_ascii=False) + "\n")
            for n, step in enumerate(steps, 1):
                if app.process.poll() is not None:
                    break
                label = step.intent or " ".join(map(str, keys.describe(step.keys)))
                if recording:
                    recording.marker(f"{n}: {label}")
                started = time.monotonic()
                app.send(step.keys)
                settled = app.wait_quiet(quiet=step.quiet, patience=step.patience)
                name = f"{n:02d}.txt"
                marks = app.highlights()
                (screens / name).write_text(screen_file(app.text(), marks),
                                            encoding="utf-8")
                log.write(json.dumps({
                    "step": n, "intent": step.intent, "keys": keys.describe(step.keys),
                    "settled": settled, "waited": round(time.monotonic() - started, 2),
                    "screen": name, "highlighted": marks, "events": new_events()},
                    ensure_ascii=False) + "\n")
                log.flush()
                result.steps = n
                if not settled:
                    result.unsettled.append(n)
            result.exited = app.process.poll()
    finally:
        app.stop()
        if recording:
            recording.close()
    return result
