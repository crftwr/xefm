"""XeFM in a VM: what is staged there, and what it runs with (xefm#750).

    make test-vm GUEST=qa-win            # the test suite in the VM
    make run-vm GUEST=qa-mac             # the VM up for a hand check

The VM layer - the guest over SSH, the shared folder, Tart and VMware
machines, the per-run venv, the desktop session - is quality-loop's
(`quality_loop.guest`, docs/guests.md there), shared with Keyhac. What is
left here is XeFM's own: what a run stages, and the environment XeFM runs
with from that stage. tools/vm.py runs the tests and the hand checks on it.

**What is staged, every run.** Whatever is under test, never the image:

- this working tree, as git sees it (tracked files and untracked ones that
  are not ignored, so an uncommitted change is tried too);
- with ``packages = "local"`` (development), the packages we make ourselves -
  PuiKit, doc-files, similar-files and, for the tests, quality-loop - as this
  checkout's own environment has them, an editable ../puikit included. With
  ``"pypi"`` (a release, #842) nothing of ours is staged: requirements.txt is
  installed as it reads, so the run gets what a user's pip gets;
- on Windows, the libarchive DLL from crftwr/xefm-bin-deps, pinned by tag and
  checksum exactly as windows_app/build.ps1 pins it. macOS has its own, and
  a Linux container gets the distribution's libarchive13, installed at the
  start of the run as a user's machine would have it.

**What is installed, every run.** The third-party packages: requirements.txt's
and those the staged packages need, into a fresh venv from the image's Python,
through a pip cache on the share (`Guest.venv`). So they always match the
working tree. A macOS guest has no compiler, and a package with no wheel for
its Python (watchdog 6.0.0 on 3.14) would not install, so there this Mac
builds the wheels into a wheelhouse on the share when its own Python is the
guest's version, and the guest installs from it.

The guest's settings - its share, its VM, the image's `python` - are its
table in ~/.config/quality-loop/guests.toml (`XEFM_QA_GUESTS` names another
file). The images are shared with Keyhac, and so are the aliases. `qa-linux`
and `qa-linux-floor`, Docker containers, work without a table
(:func:`default_guests`): Docker is all `make test-linux` needs.

**The image's free-threaded Python.** The macOS and Windows apps embed 3.15t
(#914, #915), so a VM guest runs on the image's free-threaded interpreter,
``free_threaded_python`` in the table when it names one (the key Keyhac's
runs read too), and `test-vm` stops on a Python with the GIL on. The Linux
containers stay on the regular build: there XeFM runs on whatever Python pip
or Homebrew gives it.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import ntpath
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request
import zipfile

from packaging.requirements import Requirement
from quality_loop import guest as ql
from quality_loop.guest import GuestError  # noqa: F401

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

#: Ours, so staged from this checkout's environment rather than installed
#: in a development run: distribution name -> the package it imports as.
STAGED = {"puikit": "puikit", "doc-files": "doc_files", "similar-files": "similar_files",
          "quality-loop": "quality_loop"}

#: Where a run's packages of ours come from: this checkout's environment, or
#: PyPI as requirements.txt names them (a release's run, #842).
PACKAGES = ("local", "pypi")

def floor_python() -> str:
    """The lowest Python XeFM declares, ``"3.11"`` from ``requires-python =
    ">=3.11"``, so the floor guest follows a bump of it."""
    with (ROOT / "pyproject.toml").open("rb") as f:
        spec = tomllib.load(f)["project"]["requires-python"]
    found = re.fullmatch(r">=\s*(3\.\d+)", spec.strip())
    if not found:
        raise SystemExit(f"pyproject.toml's requires-python is {spec!r}, not '>=3.N'")
    return found.group(1)


def default_guests() -> dict[str, dict[str, str]]:
    """Guests that need no table in guests.toml: Debian containers on the
    newest Python (`qa-linux`) and on the lowest XeFM declares
    (`qa-linux-floor`). The VMs run the Python the shipped apps carry."""
    def container(python):
        return {"share": "~/.cache/qa-guest=/qa", "python": "/usr/local/bin/python3",
                "docker": f"python:{python}-slim"}
    return {"qa-linux": container("3.15"), "qa-linux-floor": container(floor_python())}

#: What a Linux container installs before the venv: the runtime library alone,
#: the state a user's machine is in (doc/dev/LINUX_TESTING_SYSTEM.md).
LINUX_PACKAGES = ["libarchive13"]

#: Downloads kept between runs: the libarchive zip.
CACHE = pathlib.Path.home() / ".cache" / "xefm-qa"


def _requirement_lines(path: pathlib.Path) -> list[str]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requires(name: str) -> list[str]:
    """``name``'s requirements, markers and all. An editable install's
    metadata is as old as the install, so a checkout's (../puikit's) are read
    from its pyproject.toml instead."""
    distribution = importlib.metadata.distribution(name)
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    if direct.get("dir_info", {}).get("editable"):
        checkout = pathlib.Path(urllib.parse.urlsplit(direct["url"]).path)
        with (checkout / "pyproject.toml").open("rb") as f:
            project = tomllib.load(f)["project"]
        requires = list(project.get("dependencies", []))
        for extra, lines in project.get("optional-dependencies", {}).items():
            requires += [f'{line}; extra == "{extra}"' for line in lines]
        return requires
    return list(distribution.requires or ())


def test_requirements() -> list[str]:
    """What the test suite needs beyond requirements.txt, as
    requirements-dev.txt writes it down: the pytest plugins pytest.ini asks
    for by flag, and quality-loop - the marks' plugin, its key notation and
    pyte, without which the pseudo-terminal tests of `xefm try` skip (the
    ConPTY half, #801, runs nowhere but a Windows guest)."""
    return _requirement_lines(ROOT / "requirements-dev.txt")


def third_party_requirements(tests: bool = False, packages: str = "local") -> list[str]:
    """What the guest installs. With ``packages="pypi"``, requirements.txt as
    it reads - ours from PyPI too. With ``"local"``, its packages that are not
    ours, and what ours need - their plain requirements and those of the
    extras requirements.txt asks for (doc-files[pdf] needs pypdf). Platform
    markers stay: pip in the guest leaves out what is for another OS. With
    ``tests``, the suite's own requirements as well."""
    lines = _requirement_lines(ROOT / "requirements.txt")
    if tests:
        lines += test_requirements()
    if packages == "pypi":
        return list(dict.fromkeys(lines))
    wanted, extras = [], {}
    for line in lines:
        requirement = Requirement(line)
        name = _canonical(requirement.name)
        if name in STAGED:
            extras[name] = set(requirement.extras)
        else:
            wanted.append(line)
    for name, chosen in extras.items():
        for line in _requires(name):
            requirement = Requirement(line)
            marker = str(requirement.marker or "")
            if "extra" not in marker:
                wanted.append(line)
            elif any(requirement.marker.evaluate({"extra": extra}) for extra in chosen):
                # An extra's marker is only ever `extra == "..."` in these.
                requirement.marker = None
                wanted.append(str(requirement))
    out = []
    for line in wanted:
        if line not in out:
            out.append(line)
    return out


def libarchive_pin(arch: str = "x64") -> tuple[str, str, str]:
    """(url, package name, sha256) of the Windows libarchive for *arch*
    (x64 or arm64), read from windows_app/build.ps1 so that the two never
    disagree. x64 by default: a guest's Python is x64, emulated on an ARM64
    host, and the DLL has to match the Python rather than the machine."""
    script = (ROOT / "windows_app" / "build.ps1").read_text(encoding="utf-8")
    pin = re.search(rf"^\s*{arch}\s*=\s*@\{{\s*Tag\s*=\s*'([^']+)';\s*Sha256\s*=\s*'([^']+)'",
                    script, re.M)
    if not pin:
        raise SystemExit(f"windows_app/build.ps1 no longer pins libarchive for {arch} in $LibarchivePins")
    name = re.search(r'^\$LibarchivePkgName\s*=\s*"([^"]+)"', script, re.M)
    if not name:
        raise SystemExit("windows_app/build.ps1 no longer sets $LibarchivePkgName")
    tag, sha = pin.groups()
    package = name.group(1).replace("$Arch", arch)
    url = f"https://github.com/crftwr/xefm-bin-deps/releases/download/{tag}/{package}.zip"
    return url, package, sha


def libarchive_zip() -> pathlib.Path:
    """The pinned zip, downloaded once into CACHE and checked every time."""
    url, package, sha = libarchive_pin()
    CACHE.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE / f"{package}.zip"
    for attempt in (1, 2):
        if not zip_path.exists():
            with urllib.request.urlopen(url) as response, zip_path.open("wb") as out:
                shutil.copyfileobj(response, out)
        if hashlib.sha256(zip_path.read_bytes()).hexdigest() == sha:
            return zip_path
        zip_path.unlink()
    raise SystemExit(f"{url} does not have the SHA-256 windows_app/build.ps1 pins")


def working_tree() -> list[str]:
    """This checkout's files as git sees them: tracked, and untracked but not
    ignored - so .venv, cleanroom/ and temp/ stay behind."""
    said = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT,
                          capture_output=True, text=True, check=True)
    return [p for p in said.stdout.split("\0") if p and (ROOT / p).is_file()]


class Guest(ql.Guest):
    """quality-loop's guest, with XeFM staged in it."""

    #: Where our packages come from in this run (:data:`PACKAGES`).
    packages = "local"

    @classmethod
    def for_alias(cls, alias: str, packages: str = "local") -> "Guest":
        if packages not in PACKAGES:
            raise SystemExit(f"packages is one of {', '.join(PACKAGES)}, not {packages!r}")
        settings = ql.settings_for(alias, os.environ.get("XEFM_QA_GUESTS"))
        if not settings and alias in default_guests():
            settings = default_guests()[alias]
            host = pathlib.Path(settings["share"].partition("=")[0]).expanduser()
            host.mkdir(parents=True, exist_ok=True)
        try:
            guest = cls.from_settings(alias, settings, os.environ.get("XEFM_QA_SHARE"))
        except GuestError as error:
            raise SystemExit(f"{alias}: {error}") from None
        guest.packages = packages
        return guest

    @property
    def python(self) -> str:
        """The image's free-threaded interpreter, ``free_threaded_python`` in
        the table - what the apps embed - or, where the table names none, its
        ``python``. :meth:`require_free_threaded` refuses the second for a
        run that has to be on the first."""
        return self.settings.get("free_threaded_python") or super().python

    def require_free_threaded(self) -> None:
        """Stop unless `python` is a free-threaded build with the GIL off: the
        suite on a GIL Python would pass without testing what the apps ship.
        A Linux container is exempt (see the module's docstring)."""
        if self.docker:
            return
        # No quotes inside -c: through SSH into PowerShell they get mangled.
        code = "import sys; print(int(not sys._is_gil_enabled()))"
        if self.windows:
            said = self.ssh(f"& {ql.ps_quote(self.python)} -c \"{code}\"")
        else:
            said = self.ssh(f"{ql.sh_quote(self.python)} -c {ql.sh_quote(code)}")
        if said.returncode != 0 or said.stdout.strip().splitlines()[-1:] != ["1"]:
            raise SystemExit(
                f"{self.alias}: {self.python} is not a free-threaded Python with the GIL "
                f"off, and the apps ship one. Name the image's in "
                f"~/.config/quality-loop/guests.toml as free_threaded_python, or as "
                f"python.\n{said.stdout}{said.stderr}")

    def windowless(self, python: str) -> str:
        """``pythonw.exe`` beside ``python.exe`` (quality-loop's), and
        ``pythonw3.15t.exe`` beside ``python3.15t.exe``: the free-threaded
        build installs beside a regular one under those names."""
        name = ntpath.basename(python) if self.windows else ""
        if re.fullmatch(r"python3\.\d+t\.exe", name, re.IGNORECASE):
            return python[:-len(name)] + "pythonw" + name[len("python"):]
        return super().windowless(python)

    def stage(self, prefix: str = "xefm-qa-stage-") -> pathlib.Path:
        """This working tree as <stage>/tree, our packages in <stage>/lib in a
        development run, and on Windows the libarchive DLL in
        <stage>/libarchive. A Linux container gets its libarchive13 here."""
        stage = super().stage(prefix)
        tree = stage / "tree"
        for name in working_tree():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        lib = stage / "lib"
        lib.mkdir()
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        if self.packages == "local":
            for package in STAGED.values():
                source = pathlib.Path(__import__(package).__file__).parent
                shutil.copytree(source, lib / package, ignore=ignore)
        if self.windows:
            with zipfile.ZipFile(libarchive_zip()) as archive:
                archive.extractall(stage / "libarchive")
        if self.system == "Linux":
            said = self.ssh("apt-get update -qq && DEBIAN_FRONTEND=noninteractive "
                            "apt-get install -y -qq --no-install-recommends "
                            + " ".join(LINUX_PACKAGES), timeout=600)
            if said.returncode != 0:
                raise SystemExit(f"could not install {', '.join(LINUX_PACKAGES)} in "
                                 f"{self.alias}:\n{said.stdout[-1500:]}{said.stderr[-1500:]}")
        return stage

    def requirements(self, tests: bool = False) -> list[str]:
        """:func:`third_party_requirements`, with a macOS guest pointed at
        wheels this Mac built (see the module's docstring)."""
        wanted = third_party_requirements(tests, self.packages)
        if self.system != "Darwin" or sys.platform != "darwin":
            return wanted
        # The ABI as well as the version: a free-threaded Python loads only
        # cp3XXt wheels, and a regular one only cp3XX.
        said = self.ssh(f"{ql.sh_quote(self.python)} -c "
                        "'import sys; print(*sys.version_info[:2], sys.abiflags or \"-\")'")
        if said.stdout.split() != [*map(str, sys.version_info[:2]), sys.abiflags or "-"]:
            return wanted
        house = self.host_share / (f".wheels-macos-cp{sys.version_info[0]}"
                                   f"{sys.version_info[1]}{sys.abiflags}")
        built = subprocess.run([sys.executable, "-m", "pip", "wheel", "-q",
                                "--disable-pip-version-check", "-w", str(house), *wanted],
                               capture_output=True, text=True)
        if built.returncode != 0:
            raise SystemExit(f"could not build the guest's wheels here:\n{built.stderr[-1500:]}")
        # A URL: in a requirements file an option's value ends at a space,
        # and the share is /Volumes/My Shared Files/... on a Mac.
        return [f"--find-links file://{urllib.parse.quote(self.path(house))}", *wanted]

    def tree(self, stage: pathlib.Path) -> str:
        return self.path(stage / "tree")

    def environment(self, stage: pathlib.Path) -> dict:
        """What XeFM, and its tests, run with from ``stage``: our packages and
        the tree on PYTHONPATH - a subprocess, a pytest-xdist worker among
        them, has to find them too - and on Windows the staged libarchive.
        Nothing machine-wide: the image sets no LIBARCHIVE."""
        separator = ";" if self.windows else ":"
        environ = {"PYTHONPATH": separator.join([self.path(stage / "lib"), self.tree(stage)]),
                   "PYTHONIOENCODING": "utf-8"}
        if self.windows:
            _, package, _ = libarchive_pin()
            environ["LIBARCHIVE"] = self.path(stage / "libarchive" / package / "bin" / "archive.dll")
        return environ
