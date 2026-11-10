# VM Testing System

The suite and the hand checks, on Windows, macOS and Linux, without the
developer's own machine taking part: this working tree runs in a guest - a VM,
or for Linux a container - that starts clean every time and is put away
afterwards.

```bash
make test-vm GUEST=qa-win                           # the whole suite in the Windows VM
make test-vm GUEST=qa-mac ARGS="test/test_x.py -k name"
make test-vm GUEST=qa-mac PACKAGES=pypi             # ours from PyPI, as a release runs
make test-linux                                     # = make test-vm GUEST=qa-linux
make run-vm  GUEST=qa-win                           # the VM up, XeFM launchers on its desktop
make shell-vm GUEST=qa-linux                        # a shell on the stage
make release-test                                   # what make tag gates on
XEFM_QA_GUEST=qa-win make qa SCENARIO=01            # quality-loop, the live check's XeFM in the VM
```

`GUEST` names a table in `~/.config/quality-loop/guests.toml` that says what
guest it is, what folder it shares with this Mac, and the image's Python. For
a VM it is also an SSH host alias. `qa-linux` is a Docker container
(`python:3.15-slim`) and needs no table. The guest layer is quality-loop's
(`quality_loop.guest`, its `docs/guests.md`), and so are the suite runner and
the `desktop` / `host_only` marks; the VM images and aliases are shared with
Keyhac (crftwr/keyhac, `doc/dev/testing.md`, "In a VM"). This page is what
XeFM adds: `qa/guest.py` (what is staged), `tools/vm.py` (the make targets)
and the VM mode of the quality-loop adapter (`qa/run.py`, `tools/vm_live.py`).

---

## Where a test runs (#842)

The same policy as Keyhac's:

| When | Where | Our packages |
| --- | --- | --- |
| A release (`make release-test`, inside `make tag`) | `qa-mac`, `qa-win`, `qa-linux`, and the musl probe | PyPI's, as the requirements name them |
| Development, a test or a file | this machine is fine | this checkout's (`../puikit` editable) |
| A test marked `desktop` | a VM only | either |
| A hand check | a VM (`make run-vm`), or `make run-linux` | either |

- **`desktop`** marks a test that takes the foreground, opens or moves
  windows, sends real input, or changes the clipboard, the trash or the
  input source. pytest skips it unless given `--desktop`, which a VM run
  passes: it would get in the way of whatever the developer is doing.
  `test/conftest.py` keeps the rest away from the real thing - the trash
  (`no_real_trash`), the home and `XDG_DATA_HOME`.
- **`host_only`** marks a test of the host-side tooling - what stages a guest
  (`test_vm_guest.py`), what reviews a release (`test_release_review.py`),
  the clean room's `xefm` shim. A guest skips them; `pytest --host-only` runs
  them alone, which is the host's part of `release-test`.
- The built DMG, zip and MSIX are not launched by `release-test`: they are
  built after the tag.

---

## The image holds an OS and a Python, nothing else

Decided on xefm#750 for XeFM and Keyhac alike:

| | Windows (VMware Fusion) | macOS (Tart) |
| --- | --- | --- |
| Clean state | snapshot `QA-2026-10-31`, reverted each run | a clone of `qa-mac-2026-10-31`, deleted after |
| Python | python.org 3.14, **x64** (as the shipped app) | python.org 3.14, universal2 |
| Also | OpenSSH, the `qa` user's desktop session, an SMB share | Keyhac.app, which holds the Accessibility grant |
| Not there | Keyhac, git, libarchive, `LIBARCHIVE` | Homebrew, the command line tools |

The Linux container is `python:3.15-slim`: Debian, glibc, Python, nothing
else. The VMs run the Python the shipped apps carry; the container runs the
newest release, so a new Python is tested before the apps move to it.
`libarchive13` - the runtime package alone, the state a user's machine is
in - is installed at the start of each run.

Everything under test is **staged every run** rather than kept in the image:

- this working tree as git sees it — tracked files, and untracked ones that
  are not ignored, so an uncommitted change is what runs;
- with `PACKAGES=local` (the default), the packages we make ourselves,
  PuiKit, doc-files, similar-files and quality-loop, copied from this
  checkout's own environment (an editable `../puikit` included). With
  `PACKAGES=pypi` none of them: they are installed from PyPI with the rest;
- on Windows, the libarchive DLL from crftwr/xefm-bin-deps, at the tag and
  SHA-256 `windows_app/build.ps1` pins — read from that script, so the two
  cannot drift. macOS has the system's.

Third-party packages are **installed every run** into a fresh venv from the
image's Python: `requirements.txt`'s and `requirements-dev.txt`'s, and with
`PACKAGES=local` what the staged packages need (PuiKit's pyobjc or numpy;
doc-files' `pdf` extra; quality-loop's pyte). An editable PuiKit's
requirements come from its `pyproject.toml`, since an editable install's
metadata is as old as the install. pip's cache sits on the host side of the
share, so a revert does not throw the downloads away.

A macOS guest has no compiler, and a package without a wheel for its Python
does not install there (watchdog 6.0.0 has none for 3.14). So when this Mac's
Python is the guest's version, it builds the wheels into a wheelhouse on the
share (`.wheels-macos-cp314`) and the guest installs from it with
`--find-links` — as a `file://` URL, because the share is
`/Volumes/My Shared Files/…` and a requirements file ends an option's value at
a space.

## test-vm

pytest runs through quality-loop's runner
(`quality_loop.guest.suite.run_pytest`), **in a VM's desktop session** and
with `--desktop`. On Windows that is a scheduled task through quality-loop's
launcher, with `python.exe` - a console window opens on the guest's desktop,
which nobody watches, and the tests that run a console program need one to
inherit (under `pythonw` they saw code page 0, empty child output, and
standard handles that could not be duplicated) - and its output is a log on
the share printed here as it grows. On macOS it is SSH; in the container,
`docker exec`, without `--desktop`. The guest side writes pytest's exit code
to a file when it is done. Our packages and the tree go on `PYTHONPATH`
rather than `sys.path` alone, so a pytest-xdist worker finds them too.
`-p no:cacheprovider`, because the cache would land on the share.

The log and the JUnit XML are copied to `temp/vm-test-<guest>-<time>/`, and
`make test-vm` exits with pytest's code.

The host's `~/.xefm/config.py` is not involved: the guest's user has a home of
its own, empty in the image, and the revert throws away whatever a run wrote
there.

## run-vm and shell-vm

The same staging and venv, then two launchers on the guest's desktop, **XeFM
GUI** and **XeFM TUI**, running this tree from the stage. Then it waits for
Enter, and puts the VM away. In the Linux container (`make run-linux`) there
is no desktop: XeFM's TUI runs in this terminal, with the stage's tree on the
left and an empty, writable `/work` on the right. `shell-vm` is a shell on
the stage with XeFM's environment set (not on Windows).

- **Windows:** the VM is started headless (`vmrun start … nogui`), and a
  headless VM does not show in the Fusion app — so once the launchers are in
  place it is suspended, and opening it in the Fusion app resumes it there.
  The TUI launcher goes through `wt.exe`: a double-clicked `.cmd` reaches
  Windows Terminal by the defterm handoff, which leaves `WT_SESSION` unset,
  and PuiKit then draws a block cursor rather than its underline.
- **macOS:** the Tart window shows when the table says `visible = true`. The
  launchers are `.command` files.

## quality-loop in a VM

With `XEFM_QA_GUEST` naming a guest, `make qa` (or `quality-loop run`) runs a
scenario's **live check** in the VM. The room and the operator stay on this
Mac - Claude, the skill bundle and the evidence tools never enter the guest;
only the XeFM the operator drives does.

- `product()` brings the VM up for the run, stages the tree and builds the
  venv, as `test-vm` does.
- The run's home goes on the share, so the guest's XeFM loads the config and
  extensions the room left. Only what runs here - the room's `xefm` shim, its
  call log, the live app's settings - stays in a temporary directory on this
  Mac (`Home.host`).
- quality-loop's terminal driver runs its app in a pty here. The app it is
  given is `tools/vm_live.py`, which starts XeFM's TUI in the guest over
  `ssh -tt` (`tools/vm_guest_xefm.py` there) and passes the pty through:
  the operator reads and types into the guest's XeFM as it would a local one.
  This works on Windows too, where OpenSSH hosts the session in a ConPTY.
- XeFM's event log (`QUALITY_LOOP_EVENTS`) is written on the share by the
  guest and copied, whole lines at a time, to the file the driver named.
- The driver stops the app with SIGTERM to its process group. `vm_live.py`
  then ends the guest's XeFM by its pid, which `vm_guest_xefm.py` left on the
  stage: a closed session does not always end what it started.
- `platform()` answers the guest's, so the operator is told the right OS.

The first run, scenario 01 in `qa-win`, met every Must; the operator read the
help and pressed F12 in the guest's XeFM. A run on a laptop on battery can
spend most of its time asleep: idle sleep stopped that one three times.

## Timings

Seen on an M-series Mac, the Windows guest being x64 Python under emulation
on Windows 11 Arm:

| | Windows | macOS | Linux (Docker) |
| --- | --- | --- | --- |
| guest up | ~30 s (revert, resume, remount) | ~20 s (clone, boot) | ~2 s, plus ~15 s of apt |
| venv, cache warm | ~60 s | ~25 s | ~20 s |
| two test files (159 tests) | 146 s in all | 67 s in all | |
| the whole suite, run to end | ~9 min (pytest 6 min) | ~6 min (pytest 4 min) | ~3 min |

## Limits

- The stage is a copy of the working tree as it is when the run starts. Do
  not switch branches or edit files in that first minute - a checkout half
  way through the copy stages a mix of both branches, and the run then fails
  in ways neither has.
- One run per VM at a time: a VMware VM has one snapshot to revert to, and
  `run-vm` holds it until Enter. Keyhac uses the same VMs, so a hand check
  left open in one product holds them from the other's release test.
- The whole suite passes in all three guests (2026-11-02, #842/#843). The
  first runs on the minimal images had found tests that assumed the machine
  they were written on (#794, #787); the first Linux and Windows runs here,
  a trash test passing by accident, a race, a zombie, curses missing on
  Windows since PuiKit 1.19.0, and an S3 cache aged by the wall clock, which
  a VM's time sync sets back (#843).
- The quality-loop VM mode drives the TUI only; a desktop (GUI) live check
  would need a screen backend in the guest, as Keyhac's runs have.
