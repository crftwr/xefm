"""tools/collect_dependencies.py refuses a venv the bundle should not be
built from (#809): a distribution not installed from a package index, or one
below a requirement on it."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import collect_dependencies as cd  # noqa: E402


class FakeDist:
    def __init__(self, name, version, requires=(), direct_url=None):
        self.metadata = {"Name": name}
        self.version = version
        self.requires = list(requires)
        self._direct_url = direct_url
        self.files = []

    def read_text(self, filename):
        if filename == "direct_url.json" and self._direct_url is not None:
            return json.dumps(self._direct_url)
        return None


EDITABLE = {"url": "file:///src/puikit", "dir_info": {"editable": True}}
LOCAL_WHEEL = {"url": "file:///src/dist/doc_files-0.1.0-py3-none-any.whl",
               "archive_info": {}}


@pytest.fixture
def venv(monkeypatch, tmp_path):
    """Install *dists* as the build venv's distributions; returns a function
    that runs the collector over *requirements* and says whether it passed."""
    dists = {}

    def distribution(name):
        try:
            return dists[cd._canonical(name)]
        except KeyError:
            raise cd.PackageNotFoundError(name)

    monkeypatch.setattr(cd.importlib_metadata, "distribution", distribution)
    monkeypatch.setattr(cd, "verify_pyobjc", lambda dest: True)
    monkeypatch.setattr(cd, "copy_distribution", lambda dist, dest: 1)
    monkeypatch.delenv("XEFM_BUNDLE_ALLOW_LOCAL", raising=False)

    def run(requirements, *installed, include_deps_of=("puikit",)):
        dists.clear()
        dists.update({cd._canonical(d.metadata["Name"]): d for d in installed})
        req = tmp_path / "requirements.txt"
        req.write_text("\n".join(requirements) + "\n")
        return cd.collect_dependencies(str(req), tmp_path / "out",
                                       include_deps_of=list(include_deps_of))
    return run


def test_released_versions_within_the_requirements_pass(venv):
    assert venv(["puikit>=1.16.1", "similar-files[image]>=0.3.0"],
                FakeDist("puikit", "1.16.1", ["numpy>=1.0"]),
                FakeDist("numpy", "2.1.0"),
                FakeDist("similar-files", "0.3.0"))


def test_a_version_below_requirements_txt_stops_it(venv):
    assert not venv(["puikit>=1.16.1"], FakeDist("puikit", "1.15.2"))


def test_a_version_below_a_dependencys_requirement_stops_it(venv):
    assert not venv(["puikit>=1.16.1"],
                    FakeDist("puikit", "1.16.1", ["numpy>=2.0"]),
                    FakeDist("numpy", "1.26.0"))


def test_a_requirement_whose_marker_does_not_apply_is_not_checked(venv):
    assert venv(["puikit>=1.16.1", "comtypes>=99; sys_platform == 'nonesuch'"],
                FakeDist("puikit", "1.16.1"), FakeDist("comtypes", "1.0"))


def test_an_editable_puikit_stops_it(venv):
    assert not venv(["puikit>=1.16.1"], FakeDist("puikit", "1.16.1", direct_url=EDITABLE))


def test_a_local_wheel_stops_it(venv):
    assert not venv(["puikit>=1.16.1", "doc-files[pdf]>=0.1.0"],
                    FakeDist("puikit", "1.16.1"),
                    FakeDist("doc-files", "0.1.0", direct_url=LOCAL_WHEEL))


def test_allow_local_lets_named_ones_through(venv, monkeypatch):
    monkeypatch.setenv("XEFM_BUNDLE_ALLOW_LOCAL", "puikit, doc_files")
    # An editable install's metadata keeps an old version; it is not checked.
    assert venv(["puikit>=1.16.1", "doc-files[pdf]>=0.1.0"],
                FakeDist("puikit", "1.7.3", direct_url=EDITABLE),
                FakeDist("doc-files", "0.1.0", direct_url=LOCAL_WHEEL))


def test_allow_local_does_not_cover_another_package(venv, monkeypatch):
    monkeypatch.setenv("XEFM_BUNDLE_ALLOW_LOCAL", "puikit")
    assert not venv(["puikit>=1.16.1", "doc-files[pdf]>=0.1.0"],
                    FakeDist("puikit", "1.16.1", direct_url=EDITABLE),
                    FakeDist("doc-files", "0.1.0", direct_url=LOCAL_WHEEL))


def test_allow_local_does_not_let_an_editable_dependency_through(venv, monkeypatch):
    # Its package would not be copied at all, only the shim that is skipped.
    monkeypatch.setenv("XEFM_BUNDLE_ALLOW_LOCAL", "similar-files")
    assert not venv(["similar-files>=0.3.0"],
                    FakeDist("similar-files", "0.3.0",
                             direct_url={"url": "file:///src/similar-files",
                                         "dir_info": {"editable": True}}),
                    include_deps_of=())


def test_a_local_but_allowed_version_is_still_checked(venv, monkeypatch):
    monkeypatch.setenv("XEFM_BUNDLE_ALLOW_LOCAL", "doc-files")
    assert not venv(["doc-files>=0.2.0"],
                    FakeDist("doc-files", "0.1.0", direct_url=LOCAL_WHEEL),
                    include_deps_of=())
