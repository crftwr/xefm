"""Similar-file scans that outlive XeFM (#571).

Detection is `similar-files <https://github.com/crftwr/similar-files>`_'s; this
module launches its command line, keeps a folder per scan, and reads back how
the scan is going. A video scan can take hours, so a scan is **its own
process**, started in its own session: closing XeFM does not stop it, and the
next XeFM finds it again.

One folder per scan, under :func:`scans_dir`::

    <id>/
      job.json      what was asked: method, roots, command, pid, created, seen
      status.json   what similar-files says (its --status file)
      stop          created to stop the scan (its --stop-file)
      scan.log      the scan's stdout and stderr
      result.xft  every group, one tree file (its --out, --format tree)

The tree is rewritten every few minutes while the scan runs, with
provisional groups (#549, #573), so the groups can be looked at long before a
video scan ends.

The watcher and the scan share nothing but these files — no pipe, no signal —
so it works the same on every platform and across XeFM restarting. Nothing is
written beside the scanned files.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path as _StdPath
from typing import Optional

from xefm.external_programs import xefm_python
from xefm.log_manager import getLogger

logger = getLogger("SimilarScan")

IDENTICAL = "identical"
IMAGE = "image"
VIDEO = "video"
AUDIO = "audio"

#: The methods the launcher offers, in its order: (name, label). The names are
#: similar-files' own extractor names, passed to its CLI as they are.
METHODS = (
    (IDENTICAL, "Identical files — the same content"),
    (IMAGE, "Similar images — resized, re-encoded or lightly edited"),
    (VIDEO, "Similar videos — re-encoded, resized, or cut from a longer one"),
    (AUDIO, "Similar audio — re-encoded, re-tagged, or cut from a longer one"),
)
LABELS = {IDENTICAL: "Identical files", IMAGE: "Similar images",
          VIDEO: "Similar videos", AUDIO: "Similar audio"}

#: A running scan rewrites its status every few seconds (similar_files.status
#: HEARTBEAT is 5). One quiet for this long, whose process is gone, is lost.
STALE_S = 30.0
#: Finished scans kept; older ones are removed when a new one starts.
KEEP = 10

RUNNING = "running"
STARTING = "starting"
DONE = "done"
CANCELLED = "cancelled"
FAILED = "failed"
LOST = "lost"
FINISHED = frozenset({DONE, CANCELLED, FAILED, LOST})


def scans_dir() -> _StdPath:
    """Where scan folders live: ``~/.xefm/scans``."""
    from xefm.config import config_manager
    return _StdPath(str(config_manager.config_dir)) / "scans"


def unavailable(method: str) -> Optional[str]:
    """Why ``method`` cannot run here — what to install — or None when it can."""
    try:
        import similar_files  # noqa: F401
        import similar_files.status  # noqa: F401 — 0.2's --status / --stop-file
        import similar_files.tree  # noqa: F401 — 0.2's --format tree
    except ImportError:
        return ("needs similar-files 0.2 or later: "
                "pip install 'similar-files>=0.2'")
    if method == IDENTICAL:
        return None
    try:
        from similar_files.registry import extractors
        cls = extractors().get(method)
    except Exception as e:  # noqa: BLE001 — a broken install says so, not crashes
        return f"similar-files could not list its methods: {e}"
    if cls is None:
        return f"this similar-files has no '{method}' method"
    if not cls.is_available():
        return cls.install_hint()
    return None


def _package_root() -> str:
    """The directory holding the ``similar_files`` package, for the child's
    ``PYTHONPATH``: in the desktop builds the bundled interpreter does not see
    the packages the app was built with on its own."""
    import similar_files
    return os.path.dirname(os.path.dirname(os.path.abspath(similar_files.__file__)))


def pid_alive(pid: Optional[int]) -> bool:
    """Whether a process ``pid`` is still running."""
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class ScanJob:
    """One scan's folder, and what can be read from it."""

    folder: _StdPath

    @property
    def id(self) -> str:
        return self.folder.name

    @property
    def result_path(self) -> _StdPath:
        """The scan's tree file — written while it runs, final at the end."""
        return self.folder / "result.xft"

    @property
    def log_path(self) -> _StdPath:
        return self.folder / "scan.log"

    def info(self) -> dict:
        try:
            data = json.loads((self.folder / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_info(self, info: dict) -> None:
        tmp = self.folder / "job.json.tmp"
        tmp.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.folder / "job.json")

    def status(self) -> Optional[dict]:
        try:
            from similar_files.status import read_status
        except ImportError:
            return None
        return read_status(self.folder / "status.json")

    def state(self, now: Optional[float] = None) -> str:
        """``starting`` (no status yet), ``running``, ``done``, ``cancelled``,
        ``failed``, or ``lost`` — the process is gone without saying how it
        ended, or has not written for :data:`STALE_S` and is not running."""
        now = time.time() if now is None else now
        status = self.status()
        info = self.info()
        if status is None:
            if pid_alive(info.get("pid")):
                return STARTING
            return LOST if now - info.get("created", now) > STALE_S else STARTING
        state = status.get("state")
        if state != RUNNING:
            return state if state in FINISHED else FAILED
        if now - status.get("updated", 0) <= STALE_S:
            return RUNNING
        # Quiet. A machine that slept shows this too, with the process alive.
        return RUNNING if pid_alive(status.get("pid")) else LOST

    @property
    def label(self) -> str:
        return LABELS.get(self.info().get("method"), "Scan")

    def progress_text(self) -> str:
        """``hash 120/400``-style progress of a running scan."""
        status = self.status() or {}
        phase, done, total = status.get("phase"), status.get("done", 0), status.get("total", 0)
        if not phase:
            return "starting"
        if total:
            return f"{phase} {int(100 * done / total)}%"
        return f"{phase} {done}"

    def summary(self) -> str:
        """What a finished scan found, or why it did not finish."""
        state = self.state()
        status = self.status() or {}
        if state == DONE:
            n = status.get("groups", 0)
            return f"{n} group{'' if n == 1 else 's'}"
        if state == CANCELLED:
            return f"stopped — {status.get('groups', 0)} group(s) so far"
        if state == LOST:
            return "ended without finishing — see its log"
        if state == FAILED:
            return "failed — see its log"
        return self.progress_text()

    @property
    def seen(self) -> bool:
        return bool(self.info().get("seen"))

    def mark_seen(self) -> None:
        info = self.info()
        if info and not info.get("seen"):
            info["seen"] = True
            self._write_info(info)

    def stop(self) -> None:
        """Ask the scan to stop: it writes the groups found so far and ends
        as ``cancelled``."""
        (self.folder / "stop").write_text("", encoding="utf-8")

    def remove(self) -> None:
        """Delete the scan's folder — its groups and its log. A running scan
        is refused with ``ValueError``: it would only write them again."""
        if self.state() not in FINISHED:
            raise ValueError("the scan is still running")
        shutil.rmtree(self.folder)


def start(roots: list, method: str, *, base: Optional[_StdPath] = None,
          python: Optional[str] = None) -> ScanJob:
    """Start a scan of ``roots`` (local paths) with ``method`` in its own
    session, and return its job. Raises ``OSError`` when it cannot start."""
    base = scans_dir() if base is None else base
    base.mkdir(parents=True, exist_ok=True)
    prune(base)
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    folder = base / job_id
    folder.mkdir()
    job = ScanJob(folder)
    python = python or xefm_python
    command = [python, "-m", "similar_files", "scan", *[str(r) for r in roots],
               "--out", str(job.result_path), "--format", "tree", "--method", method,
               "--status", str(folder / "status.json"),
               "--stop-file", str(folder / "stop")]
    env = dict(os.environ)
    root = _package_root()
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    kwargs: dict = {}
    if sys.platform == "win32":
        # A hidden console, not none: a venv's python.exe is a launcher that
        # starts the real interpreter as its child, and a console program
        # started with no console to inherit gets a new, visible one — a
        # window that flashed at every scan (#620). DETACHED_PROCESS gave the
        # launcher none; CREATE_NO_WINDOW gives it one it lends on, unseen.
        # Its own process group keeps XeFM's Ctrl-C events away from it.
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        # Its own session: not in XeFM's process group, so neither closing the
        # terminal nor quitting XeFM signals it.
        kwargs["start_new_session"] = True
    with open(job.log_path, "wb") as log:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, env=env,
                                cwd=str(folder), close_fds=True, **kwargs)
    job._write_info({"method": method, "roots": [str(r) for r in roots],
                     "command": command, "pid": proc.pid, "created": time.time(),
                     "seen": False})
    logger.info(f"Started {method} scan {job_id} (pid {proc.pid}) of {len(roots)} root(s)")
    return job


def jobs(base: Optional[_StdPath] = None) -> list[ScanJob]:
    """Every scan folder, newest first."""
    base = scans_dir() if base is None else base
    try:
        folders = [p for p in base.iterdir() if (p / "job.json").exists()]
    except OSError:
        return []
    return [ScanJob(p) for p in sorted(folders, key=lambda p: p.name, reverse=True)]


def prune(base: _StdPath, keep: int = KEEP) -> None:
    """Remove finished scans beyond the ``keep`` newest, the ones already
    looked at first, so an unseen one is not dropped while a seen one stays
    (#822). A running scan is never touched."""
    finished = [j for j in jobs(base) if j.state() in FINISHED]
    finished.sort(key=lambda j: j.seen)  # stable: newest first within each
    for job in finished[keep:]:
        shutil.rmtree(job.folder, ignore_errors=True)
