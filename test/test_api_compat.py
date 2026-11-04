"""tools/api_compat.py installs what a real extension declares before running
its tests, and a sync that fails is the package's failure."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import api_compat  # noqa: E402

from xefm import python_packages  # noqa: E402

pytestmark = pytest.mark.host_only

MANIFEST = """\
[extension]
id = "needs-lib"
version = "0.1.0"
api_version = 1
name = "Needs Lib"
description = "A package whose test imports what it declares"
min_xefm = "1.0.0"
{requires}
"""


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "needs-lib"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_lib.py").write_text(
        "import declared_lib\n\n\ndef test_it():\n    assert declared_lib.VALUE == 1\n",
        encoding="utf-8")

    def write(requires=""):
        (root / "xefm-extension.toml").write_text(MANIFEST.format(requires=requires),
                                                  encoding="utf-8")
        return str(root)
    return write


def _fake_sync(calls):
    """Stands in for pip: the network is the one thing this test does not need."""
    def sync(layout, python=None, extensions=None, **_):
        calls.append(extensions)
        layout.target.mkdir(parents=True)
        (layout.target / "declared_lib.py").write_text("VALUE = 1\n", encoding="utf-8")
    return sync


def test_a_declared_package_is_there_for_the_tests(package, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(python_packages, "sync", _fake_sync(calls))
    root = package('[requires]\npython_packages = ["declared-lib>=1"]')
    assert api_compat.main([root]) == 0
    assert calls == [{"needs-lib": ["declared-lib>=1"]}]
    assert "1 passed" in capsys.readouterr().out


def test_nothing_declared_syncs_nothing(package, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(python_packages, "sync", _fake_sync(calls))
    assert api_compat.main([package()]) == 1  # the test's import fails: nothing put it there
    assert calls == []
    assert "FAILED: needs-lib (tests)" in capsys.readouterr().err


def test_a_failed_sync_fails_the_package(package, monkeypatch, capsys):
    def sync(*_, **__):
        raise python_packages.SyncError("pip exited with code 1")
    monkeypatch.setattr(python_packages, "sync", sync)
    root = package('[requires]\npython_packages = ["declared-lib>=1"]')
    assert api_compat.main([root]) == 1
    captured = capsys.readouterr()
    assert "pip exited with code 1" in captured.out
    assert "FAILED: needs-lib (python_packages)" in captured.err
