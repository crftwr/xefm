"""The live check's XeFM, in the VM: what quality-loop's terminal driver runs.

The driver runs a terminal app in a pty on this machine and reads its screen.
In a VM run (qa/run.py, XEFM_QA_GUEST) the app it is given is this script,
which puts XeFM's TUI up in the guest over `ssh -tt` and passes the pty
through, so the operator reads and types into the guest's XeFM exactly as it
would a local one:

    python tools/vm_live.py <settings.json>

The settings (written by qa/run.py) name the guest, the stage, the venv's
Python and XeFM's environment and arguments there. This script adds what
only exists once the driver has started it:

- **the event log.** The driver starts the app with QUALITY_LOOP_EVENTS
  naming a file here; XeFM in the guest writes to one on the share instead,
  and its lines are copied across as they arrive.
- **the end.** The driver stops the app with SIGTERM to its process group,
  which ends the ssh client; XeFM in the guest is then ended by its pid, since
  a closed session does not always end what it started.
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qa"))

import guest as xefm_guest  # noqa: E402  (qa/guest.py)
from quality_loop import guest as ql  # noqa: E402

EVENTS = "QUALITY_LOOP_EVENTS"


def _copy_events(source: pathlib.Path, target: str, done: threading.Event) -> None:
    position = 0
    while True:
        finished = done.wait(0.3)
        try:
            with source.open("rb") as f:
                f.seek(position)
                chunk = f.read()
        except OSError:
            chunk = b""
        # Whole lines only: the guest may be half way through one.
        end = chunk.rfind(b"\n") + 1
        if end:
            with open(target, "ab") as out:
                out.write(chunk[:end])
            position += end
        if finished:
            return


def main() -> int:
    settings = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    guest = xefm_guest.Guest.from_screen_settings(settings["guest"])
    stage = pathlib.Path(settings["stage"])
    name = f"live-{uuid.uuid4().hex[:8]}"
    launch, pid_file, events = (stage / f"{name}.json", stage / f"{name}.pid",
                                stage / f"{name}.events")
    environ = dict(settings["environ"])
    host_events = os.environ.get(EVENTS)
    if host_events:
        environ[EVENTS] = guest.path(events)
    launch.write_text(json.dumps({"environ": environ, "path": settings["path"],
                                  "cwd": settings["cwd"], "argv": settings["argv"],
                                  "pid": guest.path(pid_file)}), encoding="utf-8")
    python, script = settings["python"], settings["script"]
    if guest.windows:
        command = f"& {ql.ps_quote(python)} {ql.ps_quote(script)} {ql.ps_quote(guest.path(launch))}"
    else:
        command = (f"exec {ql.sh_quote(python)} {ql.sh_quote(script)} "
                   f"{ql.sh_quote(guest.path(launch))}")
    ssh = subprocess.Popen(["ssh", "-tt", "-o", "BatchMode=yes", *guest.ssh_options(),
                            guest.alias, command])

    def end_in_guest():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        if guest.windows:
            guest.ssh(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue", timeout=15)
        else:
            guest.ssh(f"kill -TERM {pid} 2>/dev/null; true", timeout=15)

    def stop(signum, frame):
        ssh.terminate()
        end_in_guest()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    done = threading.Event()
    copier = None
    if host_events:
        copier = threading.Thread(target=_copy_events, args=(events, host_events, done),
                                  daemon=True)
        copier.start()
    code = ssh.wait()
    done.set()
    if copier is not None:
        copier.join(5)
    for leftover in (launch, pid_file, events):
        leftover.unlink(missing_ok=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
