"""This working tree in a guest: the test suite, or the guest up for a hand check.

    python3 tools/vm.py test [--packages pypi] <guest> [pytest args...]   # make test-vm GUEST=...
    python3 tools/vm.py run <guest>                                       # make run-vm GUEST=...
    python3 tools/vm.py shell <guest>                                     # make shell-vm GUEST=...

<guest> is a table in ~/.config/quality-loop/guests.toml (qa-win, qa-mac -
the images are shared with Keyhac - and qa-linux, a Docker container, which
needs none). Each run starts the guest from its clean state - a VMware
snapshot reverted, a Tart clone, a new container - stages what is under test
and installs the third-party packages (qa/guest.py), and puts the guest away
afterwards. Nothing is left in the image.

**test** runs pytest there through quality-loop's runner
(`quality_loop.guest.suite`): in a VM's desktop session with ``--desktop``,
so the tests that take focus or change the clipboard run there and only
there; in a container without it. ``--packages pypi`` installs PuiKit,
doc-files, similar-files and quality-loop from PyPI as the requirements name
them - a release's run (#842) - instead of staging this checkout's. The log
and the JUnit XML are kept in temp/vm-test-<guest>-<time>/; the exit code is
pytest's.

**run** leaves a VM up with XeFM GUI and XeFM TUI launchers on its desktop,
and waits for Enter. A VMware VM is started headless and then suspended, for
you to open in the Fusion app (a headless VM does not show there); a Tart VM
shows its window when the table says `visible = true`. In a container, XeFM's
TUI runs in this terminal, on the stage's tree and an empty /work.

**shell** is a shell in the guest, in the stage's tree, with XeFM's
environment set.

The host's own ~/.xefm is never read: the guest's user has a home of its own,
and the revert after the run throws it away.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qa"))

import guest as xefm_guest  # noqa: E402  (qa/guest.py)
from quality_loop import guest as ql  # noqa: E402
from quality_loop.guest import suite  # noqa: E402


def _venv(guest, stage) -> str:
    print(f"vm:      installing the third-party packages in the guest "
          f"(ours: {guest.packages})...", flush=True)
    started = time.monotonic()
    python = guest.venv(stage, guest.requirements(tests=True))
    print(f"vm:      packages in {time.monotonic() - started:.0f}s", flush=True)
    return python


def run_tests(alias: str, pytest_args: list[str], patience: float, packages: str) -> int:
    guest = xefm_guest.Guest.for_alias(alias, packages)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    results = ROOT / "temp" / f"vm-test-{alias}-{stamp}"
    started = time.monotonic()
    code = 3
    with guest.machine():
        stage = guest.stage("xefm-test-")
        try:
            python = _venv(guest, stage)
            args = pytest_args or ["test"]
            if not guest.docker:
                args = ["--desktop", *args]
            environ = guest.environment(stage)
            print(f"vm:      pytest {' '.join(args)} in {alias}", flush=True)
            separator = ";" if guest.windows else ":"
            code = suite.run_pytest(guest, stage, python, args, cwd=guest.tree(stage),
                                    results=results, environ=environ,
                                    path=environ["PYTHONPATH"].split(separator),
                                    patience=patience, task="xefm-test")
        finally:
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


def _interactive(guest, stage, command: str) -> int:
    """``command`` in the guest's shell, in the stage's tree with XeFM's
    environment, on this terminal. TERM and COLORTERM are carried in: a TUI
    under the wrong terminfo tells you nothing about the TUI."""
    environ = {**guest.environment(stage), "LANG": "C.UTF-8",
               "TERM": os.environ.get("TERM", "xterm-256color"),
               "COLORTERM": os.environ.get("COLORTERM", "")}
    line = (f"cd {ql.sh_quote(guest.tree(stage))} && "
            + " ".join(f"export {name}={ql.sh_quote(value)};" for name, value in environ.items())
            + f" {command}")
    if guest.docker:
        argv = ["docker", "exec", "-it", guest.hostname, "sh", "-c", line]
    else:
        argv = ["ssh", "-t", *guest.ssh_options(), guest.alias, line]
    return subprocess.run(argv).returncode


def run_xefm(alias: str, packages: str) -> int:
    guest = xefm_guest.Guest.for_alias(alias, packages)
    machine = guest.machine()
    machine.__enter__()
    stage = None
    try:
        stage = guest.stage("xefm-run-")
        python = _venv(guest, stage)
        if guest.docker:
            # The stage's tree on the left and an empty /work on the right, the
            # pane to copy into, delete from, and make archives in.
            return _interactive(guest, stage, f"mkdir -p /work && exec {ql.sh_quote(python)} "
                                              f"-m xefm --left . --right /work")
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


def run_shell(alias: str, packages: str) -> int:
    guest = xefm_guest.Guest.for_alias(alias, packages)
    if guest.windows:
        raise SystemExit(f"{alias} is Windows: use `make run-vm` and its desktop")
    with guest.machine():
        stage = guest.stage("xefm-shell-")
        try:
            python = _venv(guest, stage)
            print(f"vm:      the venv's python is {python}; exit the shell to put "
                  f"{alias} away", flush=True)
            return _interactive(guest, stage, "exec sh" if guest.docker else "exec $SHELL -l")
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    test = commands.add_parser("test", help="run the test suite in the guest")
    running = commands.add_parser("run", help="the guest up with XeFM, for a hand check")
    shell = commands.add_parser("shell", help="a shell in the guest, on the stage")
    for command in (test, running, shell):
        command.add_argument("--packages", choices=xefm_guest.PACKAGES, default="local",
                             help="ours from this checkout (local, the default) or PyPI")
    test.add_argument("--patience", type=float, default=3600,
                      help="seconds to wait for pytest to end (default 3600)")
    for command in (test, running, shell):
        command.add_argument("guest")
    test.add_argument("pytest_args", nargs=argparse.REMAINDER,
                      help="for pytest (default: test)")
    args = parser.parse_args()
    if args.command == "test":
        return run_tests(args.guest, args.pytest_args, args.patience, args.packages)
    if args.command == "shell":
        return run_shell(args.guest, args.packages)
    return run_xefm(args.guest, args.packages)


if __name__ == "__main__":
    sys.exit(main())
