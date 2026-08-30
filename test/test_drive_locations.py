"""
Configurable fixed rows in the drives picker (issue #356).

``DRIVE_LOCATIONS`` in ~/.xefm/config.py replaces the built-in Home / Root /
Documents / Downloads / Desktop set; left at None, the built-in set is what the
picker has always shown.

Run with: python -m pytest test/test_drive_locations.py -v
"""

import os
import platform
import tempfile
from types import SimpleNamespace

import pytest

from xefm import app as xefm_app
from xefm.config import config_manager, get_drive_locations
from xefm.path import Path


@pytest.fixture
def with_drive_locations():
    """Swap the loaded config for a stub carrying just DRIVE_LOCATIONS."""
    saved = config_manager.config

    def use(value):
        config_manager.config = SimpleNamespace(DRIVE_LOCATIONS=value)

    yield use
    config_manager.config = saved


def test_default_is_the_builtin_set(with_drive_locations):
    with_drive_locations(None)
    rows = get_drive_locations()

    names = [r["name"] for r in rows]
    assert names[0] == "Home"
    assert rows[0]["path"] == str(Path.home())
    if platform.system() == "Windows":
        assert "Root" not in names
    else:
        assert {"name": "Root", "path": "/"} in rows
    # Only folders that actually exist are offered.
    assert all(Path(r["path"]).is_dir() for r in rows)


def test_config_list_replaces_the_builtin_set(with_drive_locations):
    with tempfile.TemporaryDirectory() as tmp:
        with_drive_locations([{"name": "Work", "path": tmp}])
        assert get_drive_locations() == [{"name": "Work", "path": tmp}]


def test_empty_list_removes_every_fixed_row(with_drive_locations):
    with_drive_locations([])
    assert get_drive_locations() == []


def test_tilde_is_expanded(with_drive_locations):
    with_drive_locations([{"name": "Home", "path": "~"}])
    assert get_drive_locations() == [{"name": "Home", "path": str(Path.home())}]


def test_remote_location_is_listed_without_probing(with_drive_locations):
    """No connection is made for an ssh:// row — it would block the UI thread,
    and the picker exists to offer a connection, not to make one."""
    with_drive_locations([{"name": "NAS", "path": "ssh://nowhere.invalid/"}])
    assert get_drive_locations() == [{"name": "NAS", "path": "ssh://nowhere.invalid/"}]


def test_missing_and_malformed_entries_are_skipped(with_drive_locations):
    with tempfile.TemporaryDirectory() as tmp:
        with_drive_locations([
            {"name": "Gone", "path": os.path.join(tmp, "no-such-dir")},
            {"name": "NoPath"},
            "not-a-dict",
            {"name": "Good", "path": tmp},
        ])
        assert get_drive_locations() == [{"name": "Good", "path": tmp}]


def test_a_file_is_not_a_drive_location(with_drive_locations):
    with tempfile.NamedTemporaryFile() as fh:
        with_drive_locations([{"name": "File", "path": fh.name}])
        assert get_drive_locations() == []


def test_local_drives_starts_from_the_configured_rows(with_drive_locations):
    """The picker's local rows are the configured ones plus the mounted volumes,
    which are discovered regardless."""
    with tempfile.TemporaryDirectory() as tmp:
        with_drive_locations([{"name": "Work", "path": tmp}])
        rows = xefm_app.XeFMApp._local_drives(
            SimpleNamespace(_windows_drive_roots=lambda: []))

    assert rows[0] == {"name": "Work", "path": tmp}
    assert "Home" not in [r["name"] for r in rows]
