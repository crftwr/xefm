"""This working tree in a VM: the test suite, or the VM up for a hand check.

    python3 tools/vm.py test <guest> [pytest args...]    # make test-vm GUEST=...
    python3 tools/vm.py run <guest>                      # make run-vm GUEST=...

<guest> is an SSH host alias with a table in ~/.config/quality-loop/guests.toml
(qa-win, qa-mac; the images are shared with Keyhac). Each run starts
the VM from its clean state - a VMware snapshot reverted, or a Tart clone -
stages what is under test and installs the third-party packages (qa/guest.py),
and puts the VM away afterwards. Nothing is left in the image.

**test** runs pytest in the guest's desktop session (on Windows from a
scheduled task, so a test that opens a window can, with a console of its own)
and prints its output as
it comes. The log and the JUnit XML are kept in temp/vm-test-<guest>-<time>/;
the exit code is pytest's.

**run** leaves the VM up with XeFM GUI and XeFM TUI launchers on its desktop,
and waits for Enter. A VMware VM is started headless and then suspended, for
you to open in the Fusion app (a headless VM does not show there); a Tart VM
shows its window when the table says `visible = true`.

The host's own ~/.xefm is never read: the guest's user has a home of its own,
and the revert after the run throws it away.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qa"))

import guest as xefm_guest  # noqa: E402  (qa/guest.py)
from quality_loop import guest as ql  # noqa: E402


def _venv(guest, stage) -> str:
    print("vm:      installing the third-party packages in the guest...", flush=True)
    started = time.monotonic()
    python = guest.venv(stage, guest.requirements(tests=True))
    print(f"vm:      packages in {time.monotonic() - started:.0f}s", flush=True)
    return python


def _follow(log: pathlib.Path, done: pathlib.Path, patience: float) -> int:
    """Print ``log`` as it grows until ``done`` holds an exit code."""
    position, deadline, finished_at = 0, time.monotonic() + patience, None
    while True:
        finished = done.exists()
        chunk = ""
        if log.exists():
            with log.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(position)
                chunk = f.read()
                position = f.tell()
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()
        if finished:
            # Over SMB the log's last writes can show up after the exit code
            # does: read on until it has stopped growing.
            if chunk or (time.monotonic() - finished_at if finished_at else 0) < 3:
                finished_at = finished_at or time.monotonic()
                time.sleep(1)
                continue
            return int(done.read_text(encoding="utf-8").strip() or 3)
        if time.monotonic() > deadline:
            print(f"\nvm:      no end within {patience:.0f}s", flush=True)
            return 3
        time.sleep(1)


def _sh_environment(environ: dict) -> str:
    return " ".join(f"{name}={ql.sh_quote(value)}" for name, value in environ.items())


def run_tests(alias: str, pytest_args: list[str], patience: float) -> int:
    guest = xefm_guest.Guest.for_alias(alias)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    results = ROOT / "temp" / f"vm-test-{alias}-{stamp}"
    started = time.monotonic()
    code = 3
    with guest.machine():
        stage = guest.stage("xefm-test-")
        task = f"xefm-test-{stage.name}"
        log, done, junit = stage / "pytest.log", stage / "exit-code", stage / "junit.xml"
        try:
            python = _venv(guest, stage)
            args = ["-p", "no:cacheprovider", f"--junitxml={guest.path(junit)}",
                    *(pytest_args or ["test"])]
            runner = guest.path(stage / "tree" / "tools" / "vm_guest_pytest.py")
            environ = guest.environment(stage)
            print(f"vm:      pytest {' '.join(pytest_args or ['test'])} in {alias}", flush=True)
            if guest.windows:
                # python.exe, not pythonw: nobody watches this desktop, and a
                # test that runs a console program needs a console to inherit
                # (pythonw gave code page 0, empty child output, and handles
                # that cannot be duplicated).
                guest.launch(stage, task, python, script=runner, log=log,
                             environ=environ, path=environ["PYTHONPATH"].split(";"),
                             cwd=guest.tree(stage), argv=[guest.path(done), *args])
                code = _follow(log, done, patience)
            else:
                command = (f"cd {ql.sh_quote(guest.tree(stage))} && {_sh_environment(environ)} "
                           f"{ql.sh_quote(python)} {ql.sh_quote(runner)} "
                           f"{ql.sh_quote(guest.path(done))} "
                           + " ".join(ql.sh_quote(a) for a in args))
                with log.open("w", encoding="utf-8") as out:
                    process = subprocess.Popen(
                        ["ssh", "-o", "BatchMode=yes", *guest.ssh_options(), guest.alias, command],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, errors="replace")
                    for line in process.stdout:
                        sys.stdout.write(line)
                        out.write(line)
                    process.wait()
                code = int(done.read_text().strip()) if done.exists() else 3
        finally:
            results.mkdir(parents=True, exist_ok=True)
            for kept in (log, junit):
                if kept.exists():
                    shutil.copy2(kept, results / kept.name)
            if guest.windows:
                guest.forget_task(task)
            shutil.rmtree(stage, ignore_errors=True)
    print(f"vm:      pytest exited {code} in {time.monotonic() - started:.0f}s; "
          f"log and JUnit XML in {results.relative_to(ROOT)}")
    return code


def _windows_launchers(guest, stage, python) -> list[pathlib.Path]:
    environ = guest.environment(stage)
    head = "@echo off\r\n" f'cd /d "{guest.tree(stage)}"\r\n' + "".join(
        f'set "{name}={value}"\r\n' for name, value in environ.items())
    (stage / "run-gui.cmd").write_text(
        head + f'start "" "{guest.windowless(python)}" -m xefm --backend gui\r\n', encoding="ascii")
    (stage / "run-tui.cmd").write_text(head + f'"{python}" -m xefm\r\n', encoding="ascii")
    # On the desktop, the TUI goes through wt.exe: Windows Terminal's defterm
    # handoff from a double-clicked .cmd leaves WT_SESSION unset, and PuiKit
    # then draws a block cursor rather than its underline.
    gui = stage / "XeFM GUI.cmd"
    gui.write_text(f'@call "{guest.path(stage / "run-gui.cmd")}"\r\n', encoding="ascii")
    tui = stage / "XeFM TUI.cmd"
    tui.write_text(f'@start "" wt.exe "{guest.path(stage / "run-tui.cmd")}"\r\n', encoding="ascii")
    return [gui, tui]


def _mac_launchers(guest, stage, python) -> list[pathlib.Path]:
    environ = guest.environment(stage)
    head = ("#!/bin/bash\n" f"cd {ql.sh_quote(guest.tree(stage))}\n"
            + "".join(f"export {name}={ql.sh_quote(value)}\n" for name, value in environ.items()))
    gui = stage / "XeFM GUI.command"
    gui.write_text(head + f"exec {ql.sh_quote(python)} -m xefm --backend gui\n", encoding="utf-8")
    tui = stage / "XeFM TUI.command"
    tui.write_text(head + f"exec {ql.sh_quote(python)} -m xefm\n", encoding="utf-8")
    return [gui, tui]


def run_xefm(alias: str) -> int:
    guest = xefm_guest.Guest.for_alias(alias)
    machine = guest.machine()
    machine.__enter__()
    stage = None
    try:
        stage = guest.stage("xefm-run-")
        python = _venv(guest, stage)
        if guest.windows:
            launchers = _windows_launchers(guest, stage, python)
            names = ", ".join(ql.ps_quote(guest.path(p)) for p in launchers)
            said = guest.ssh(f"Copy-Item {names} ([Environment]::GetFolderPath('Desktop'))")
        else:
            launchers = _mac_launchers(guest, stage, python)
            names = " ".join(ql.sh_quote(guest.path(p)) for p in launchers)
            said = guest.ssh(f"cp {names} ~/Desktop/ && chmod +x ~/Desktop/*.command")
        if said.returncode != 0:
            raise SystemExit(f"could not put the launchers on the guest's desktop:\n{said.stderr}")
        print(f"vm:      XeFM GUI and XeFM TUI are on {alias}'s desktop, running this "
              f"working tree from {guest.tree(stage)}")
        if isinstance(machine, ql.VMwareMachine):
            # A headless VM does not show in the Fusion app; a suspended one
            # does, and resumes there.
            machine._vmrun("suspend", machine.vmx)
            print("vm:      suspended - open it in the VMware Fusion app to resume it there")
        elif isinstance(machine, ql.TartMachine) and not guest.settings.get("visible"):
            print("vm:      the table does not say visible = true, so there is no window: "
                  f"reach it with `ssh {alias}`")
        input("vm:      press Enter here when you are done, to put the VM away... ")
        return 0
    except (KeyboardInterrupt, EOFError):
        print()
        return 0
    finally:
        with contextlib.suppress(Exception):
            machine.__exit__(None, None, None)
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    test = commands.add_parser("test", help="run the test suite in the VM")
    test.add_argument("guest")
    test.add_argument("--patience", type=float, default=3600,
                      help="seconds to wait for pytest to end (default 3600)")
    test.add_argument("pytest_args", nargs=argparse.REMAINDER,
                      help="for pytest (default: test)")
    running = commands.add_parser("run", help="the VM up with launchers, for a hand check")
    running.add_argument("guest")
    args = parser.parse_args()
    if args.command == "test":
        return run_tests(args.guest, args.pytest_args, args.patience)
    return run_xefm(args.guest)


if __name__ == "__main__":
    sys.exit(main())
