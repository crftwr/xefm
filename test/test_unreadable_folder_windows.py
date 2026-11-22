"""A folder Windows will not let a non-elevated process list (#909).

``C:\\System Volume Information`` and a profile's ``Application Data``
compatibility junction exist but cannot be listed. The pane shows why
("Permission denied") rather than "(empty)", the listing logs that once, and
the filesystem watcher gives up at once and quietly instead of logging
fourteen errors while it retries.

These run against the real folders, so only on Windows, and only where the
folder really is unreadable (an elevated run lists it, and is skipped). The
mocked counterparts that run everywhere are in
``test_file_monitor_error_handling.py`` and ``test_jump_to_missing_directory.py``.

Run with: python -m pytest test/test_unreadable_folder_windows.py -v
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path as PlainPath
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm import _config  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.path import Path  # noqa: E402


def _unreadable_candidates():
    if sys.platform != "win32":
        return []
    out = [os.path.join(os.environ.get("SystemDrive", "C:") + "\\",
                        "System Volume Information"),
           os.path.join(os.path.expanduser("~"), "Application Data")]
    return out


def _is_unreadable(path):
    if not os.path.isdir(path):
        return False
    try:
        os.listdir(path)
    except PermissionError:
        return True
    return False


UNREADABLE = [p for p in _unreadable_candidates() if _is_unreadable(p)]

pytestmark = pytest.mark.skipif(
    not UNREADABLE,
    reason="needs Windows, unelevated, with a folder it may not list")


class _Logs:
    """A logger that keeps what it is told, by level."""

    def __init__(self):
        self.lines = {"error": [], "warning": [], "info": [], "debug": []}
        for level in self.lines:
            setattr(self, level, self.lines[level].append)


@pytest.fixture(params=UNREADABLE or [None])
def folder(request):
    return request.param


def test_the_listing_says_permission_denied_once(folder):
    flm = FileListManager(_config.Config())
    logs = _Logs()
    flm.logger = logs
    result = flm.compute_listing(Path(folder))
    assert not result["ok"]
    assert result["error"] == "Permission denied"
    assert logs.lines["error"] == [f"Permission denied: {folder}"]

    pane = {"path": Path(folder), "files": [], "focused_index": 0,
            "selected_files": set()}
    flm.apply_listing(pane, result)
    assert pane["error"] == "Permission denied"


def test_the_observer_gives_up_quietly(folder):
    from xefm.file_monitor_observer import FileMonitorObserver, WATCHDOG_AVAILABLE
    if not WATCHDOG_AVAILABLE:
        pytest.skip("watchdog not installed")
    logs = _Logs()
    observer = FileMonitorObserver(PlainPath(folder), Mock(), logs)
    try:
        assert observer.start() is False
    finally:
        observer.stop()
    assert observer.unreadable is True
    assert logs.lines["error"] == [] and logs.lines["warning"] == []


def test_the_manager_does_not_walk_its_retry_ladder(folder):
    from xefm.file_monitor_manager import FileMonitorManager
    from xefm.file_monitor_observer import WATCHDOG_AVAILABLE
    if not WATCHDOG_AVAILABLE:
        pytest.skip("watchdog not installed")
    manager = FileMonitorManager(_config.Config(), Mock())
    logs = _Logs()
    manager.logger = logs
    try:
        manager._start_pane_monitoring("left", PlainPath(folder))
        # The first retry would fire after 1 s: wait past it.
        time.sleep(1.5)
        manager.wait_for_idle(5.0)
        state = manager.monitoring_state["left"]
        assert state["failed_path"] == PlainPath(folder)
        assert state["observer"] is None
        assert state["retry_count"] == 0
        assert logs.lines["error"] == [] and logs.lines["warning"] == []
    finally:
        manager.stop_monitoring()


def test_entering_it_in_the_app_shows_why(folder):
    """Enter (``_go_to_dir``) keeps the pane on the folder; it shows
    "Permission denied" there, not "(empty)"."""
    from puikit.backends import create_backend
    from xefm import app as xefm_app
    from xefm.state_manager import XeFMStateManager

    tmp = os.path.realpath(tempfile.mkdtemp())
    state_dir = tempfile.mkdtemp()
    b = create_backend("memory")
    b.open()
    try:
        sm = XeFMStateManager(db_path=os.path.join(state_dir, "state.db"))
        app = xefm_app.XeFMApp(b, tmp, tmp, left_provided=True,
                               right_provided=True, state_manager=sm)
        app.file_monitor.stop_monitoring()
        app.file_monitor.enabled = False
        app._settle_listings()
        pane = app.active_pane()
        app._go_to_dir(pane, Path(folder), None)
        app._settle_listings()
        assert str(pane["path"]) == folder
        assert pane["files"] == []
        assert pane["error"] == "Permission denied"
        app.file_monitor.stop_monitoring()
    finally:
        b.close()
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(state_dir, ignore_errors=True)
