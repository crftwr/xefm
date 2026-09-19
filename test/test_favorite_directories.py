"""
The favorites picker lists what is configured, without touching the disk
(issue #430).

Checking each favorite before drawing the list meant three blocking calls per
row on the UI thread — ``resolve()``, ``exists()``, ``is_dir()`` — so a handful
of unreachable network shares stacked their timeouts into minutes of dead UI
just to open the picker. Now nothing is probed: a favorite is proved by being
selected, where the wait is one the user asked for.

Run with: python -m pytest test/test_favorite_directories.py -v
"""

import os
import tempfile
from types import SimpleNamespace

import pytest

from xefm.config import config_manager, get_favorite_directories
from xefm.path import Path


@pytest.fixture
def with_favorites():
    """Swap the loaded config for a stub carrying just FAVORITE_DIRECTORIES."""
    saved = config_manager.config

    def use(value):
        config_manager.config = SimpleNamespace(FAVORITE_DIRECTORIES=value)

    yield use
    config_manager.config = saved


@pytest.fixture
def no_filesystem(monkeypatch):
    """Make every stat-like syscall an error, so a probe cannot pass unnoticed."""
    def forbidden(*args, **kwargs):
        raise AssertionError("the favorites list touched the filesystem")

    for name in ("stat", "lstat", "readlink", "access"):
        monkeypatch.setattr(os, name, forbidden)
    yield


def test_a_missing_directory_is_still_listed(with_favorites, no_filesystem):
    """The whole point: a favorite nobody can reach is a row like any other."""
    with_favorites([{"name": "Gone", "path": "/no/such/place"}])
    assert get_favorite_directories() == [{"name": "Gone", "path": "/no/such/place"}]


def test_an_unreachable_share_costs_no_round_trip(with_favorites, no_filesystem):
    with_favorites([
        {"name": "NAS", "path": "/Volumes/nowhere"},
        {"name": "Dev", "path": "ssh://nowhere.invalid/var/www"},
        {"name": "Bucket", "path": "s3://nowhere-invalid/data"},
    ])
    assert [f["name"] for f in get_favorite_directories()] == ["NAS", "Dev", "Bucket"]


def test_remote_paths_are_listed_verbatim(with_favorites, no_filesystem):
    """Not even a Path is constructed for one — that alone pulls in the row's
    backend module for a row that may never be selected."""
    with_favorites([{"name": "Bucket", "path": "s3://my-bucket/data"}])
    assert get_favorite_directories() == [{"name": "Bucket", "path": "s3://my-bucket/data"}]


def test_tilde_is_expanded(with_favorites, no_filesystem):
    """Expansion is string work, not I/O, so it survives the ban above."""
    with_favorites([{"name": "Home", "path": "~"}])
    assert get_favorite_directories() == [{"name": "Home", "path": str(Path.home())}]


def test_a_symlinked_favorite_keeps_the_path_as_written(with_favorites):
    """``resolve()`` used to print the target instead. No other navigation in
    XeFM resolves the path it lands on, and the user named this one."""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "target")
        link = os.path.join(tmp, "link")
        os.mkdir(target)
        os.symlink(target, link)

        with_favorites([{"name": "Link", "path": link}])
        assert get_favorite_directories() == [{"name": "Link", "path": link}]


def test_malformed_entries_are_skipped_and_warned(with_favorites, no_filesystem):
    """Including the ``('Name', 'path')`` tuple form some older docs showed,
    which has never been accepted — it used to vanish without a word."""
    with_favorites([
        {"name": "NoPath"},
        ("Work", "~/work"),
        "not-a-dict",
        {"name": "Good", "path": "/somewhere"},
    ])
    assert get_favorite_directories() == [{"name": "Good", "path": "/somewhere"}]
