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
- the packages we make ourselves - PuiKit, doc-files and similar-files - as
  this checkout's own environment has them, an editable ../puikit included;
- on Windows, the libarchive DLL from crftwr/xefm-bin-deps, pinned by tag and
  checksum exactly as windows_app/build.ps1 pins it. macOS has its own.

**What is installed, every run.** The third-party packages: requirements.txt's
and those the staged packages need, into a fresh venv from the image's Python,
through a pip cache on the share (`Guest.venv`). So they always match the
working tree. A macOS guest has no compiler, and a package with no wheel for
its Python (watchdog 6.0.0 on 3.14) would not install, so there this Mac
builds the wheels into a wheelhouse on the share when its own Python is the
guest's version, and the guest installs from it.

The guest's settings - its share, its VM, the image's `python` - are its
table in ~/.config/quality-loop/guests.toml (`XEFM_QA_GUESTS` names another
file). The images are shared with Keyhac, and so are the aliases.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
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

#: Ours, so staged from this checkout's environment rather than installed:
#: distribution name -> the package it imports as.
STAGED = {"puikit": "puikit", "doc-files": "doc_files", "similar-files": "similar_files"}

#: What the test suite needs beyond requirements.txt: requirements-dev.txt's
#: pytest plugins, which pytest.ini asks for by flag, and quality-loop's key
#: notation and pyte, without which the pseudo-terminal tests of `xefm try`
#: skip — the ConPTY half (#801) runs nowhere but a Windows guest.
TEST_REQUIREMENTS = ["pytest", "pytest-xdist", "pytest-timeout",
                     "quality-loop[tui]>=0.4.1"]

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


def third_party_requirements(tests: bool = False) -> list[str]:
    """What the guest installs: requirements.txt's packages that are not ours,
    and what ours need - their plain requirements and those of the extras
    requirements.txt asks for (doc-files[pdf] needs pypdf). Platform markers
    stay: pip in the guest leaves out what is for another OS. With ``tests``,
    the suite's own plugins as well."""
    wanted, extras = [], {}
    for line in _requirement_lines(ROOT / "requirements.txt"):
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
    if tests:
        wanted += TEST_REQUIREMENTS
    out = []
    for line in wanted:
        if line not in out:
            out.append(line)
    return out


def libarchive_pin() -> tuple[str, str, str]:
    """(url, package name, sha256) of the Windows libarchive, read from
    windows_app/build.ps1 so that the two never disagree."""
    script = (ROOT / "windows_app" / "build.ps1").read_text(encoding="utf-8")

    def value(name):
        found = re.search(rf"^\${name}\s*=\s*'([^']+)'", script, re.M)
        if not found:
            raise SystemExit(f"windows_app/build.ps1 no longer sets ${name}")
        return found.group(1)

    tag, package, sha = value("LibarchiveTag"), value("LibarchivePkgName"), value("LibarchiveSha256")
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

    @classmethod
    def for_alias(cls, alias: str) -> "Guest":
        try:
            return cls.from_settings(alias, ql.settings_for(alias, os.environ.get("XEFM_QA_GUESTS")),
                                     os.environ.get("XEFM_QA_SHARE"))
        except GuestError as error:
            raise SystemExit(f"{alias}: {error}") from None

    def stage(self, prefix: str = "xefm-qa-stage-") -> pathlib.Path:
        """This working tree as <stage>/tree, our packages in <stage>/lib, and
        on Windows the libarchive DLL in <stage>/libarchive."""
        stage = super().stage(prefix)
        tree = stage / "tree"
        for name in working_tree():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        lib = stage / "lib"
        lib.mkdir()
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for package in STAGED.values():
            source = pathlib.Path(__import__(package).__file__).parent
            shutil.copytree(source, lib / package, ignore=ignore)
        if self.windows:
            with zipfile.ZipFile(libarchive_zip()) as archive:
                archive.extractall(stage / "libarchive")
        return stage

    def requirements(self, tests: bool = False) -> list[str]:
        """:func:`third_party_requirements`, with a macOS guest pointed at
        wheels this Mac built (see the module's docstring)."""
        wanted = third_party_requirements(tests)
        if self.windows or sys.platform != "darwin":
            return wanted
        said = self.ssh(f"{ql.sh_quote(self.python)} -c "
                        "'import sys; print(*sys.version_info[:2])'")
        if said.stdout.split() != [str(n) for n in sys.version_info[:2]]:
            return wanted
        house = self.host_share / f".wheels-macos-cp{sys.version_info[0]}{sys.version_info[1]}"
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
