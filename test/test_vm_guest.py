"""qa/guest.py - what a VM run stages and installs - checked without a VM.

The VM itself is reached only by `make test-vm` / `make run-vm`
(doc/dev/VM_TESTING_SYSTEM.md). What can go wrong without one is the
bookkeeping: ours installed from PyPI instead of staged, an extra's
requirement dropped or one meant for another extra let in, the libarchive pin
drifting from the Windows build's, the stage picking up the venv.

Run with: python -m pytest test/test_vm_guest.py -v
"""

import pathlib
import re
import sys

import pytest

pytest.importorskip("quality_loop.guest", reason="quality-loop 0.4.0+ is not installed in this venv")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qa"))

import guest  # noqa: E402  (qa/guest.py)


def _names(requirements):
    return {re.split(r"[\s;<>=!~\[]", r, maxsplit=1)[0].lower() for r in requirements}


def test_our_packages_are_staged_not_installed():
    names = _names(guest.third_party_requirements(tests=True))
    assert not names & set(guest.STAGED)
    assert {"pygments", "libarchive-c"} <= names


def test_what_ours_need_is_installed_with_its_markers():
    requirements = guest.third_party_requirements()
    # PuiKit's own, for the guest's pip to choose by platform.
    assert any(r.startswith("numpy") and "win32" in r for r in requirements)
    assert any(r.startswith("pyobjc-framework-Cocoa") and "darwin" in r for r in requirements)


def test_a_requested_extra_comes_along_and_the_others_do_not():
    requirements = guest.third_party_requirements()
    # requirements.txt asks for doc-files[pdf]: pypdf, with no extra marker left.
    assert any(r.startswith("pypdf") and "extra" not in r for r in requirements)
    # doc-files[test], similar-files[whash], puikit[dev] are not asked for.
    assert not _names(requirements) & {"python-docx", "imagehash", "openpyxl"}
    assert all("extra" not in r for r in requirements)


def test_the_suite_s_plugins_only_for_tests():
    assert "pytest-xdist" not in guest.third_party_requirements()
    assert {"pytest", "pytest-xdist", "pytest-timeout"} <= set(
        guest.third_party_requirements(tests=True))


def test_the_libarchive_pin_is_the_windows_build_s():
    url, package, sha = guest.libarchive_pin()
    script = (ROOT / "windows_app" / "build.ps1").read_text(encoding="utf-8")
    assert f"'{sha}'" in script and f"'{package}'" in script
    assert url.startswith("https://github.com/crftwr/xefm-bin-deps/releases/download/")
    assert url.endswith(f"/{package}.zip")


def test_the_stage_is_the_tree_git_sees():
    files = guest.working_tree()
    assert "xefm/app.py" in files and "tools/vm_guest_pytest.py" in files
    assert not [f for f in files if f.startswith((".venv/", "cleanroom/", "temp/", ".git/"))]


def test_a_vm_run_keeps_what_runs_here_off_the_share(tmp_path):
    """The room's `xefm` shim and its log run on this machine; the home they
    serve is on the share. An SMB share is no place for an executable."""
    sys.path.insert(0, str(ROOT / "qa" / "checks"))
    import run  # noqa: E402  (qa/run.py)
    home = run.Home(tmp_path)
    try:
        assert home.root.parent == tmp_path.resolve()
        assert tmp_path.resolve() not in home.bin.parents
        assert tmp_path.resolve() not in home.calls.parents
        assert (home.bin / "xefm").exists()
    finally:
        home.remove()
    assert not home.host.exists() and not home.root.exists()
