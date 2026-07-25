"""
Filesystem-monitoring wiring for the PuiKit XeFMApp.

Replaces the legacy ``test_reload_*`` coverage, which targeted the old curses
``FileManager._handle_reload_request`` / reload queue (the old curses
``xefm_main.py``, since removed). Here we drive the ported wiring on ``XeFMApp``:

  * observer threads post pane names to ``XeFMApp.reload_queue``
  * ``_process_reload_queue`` drains them on the main thread
  * ``_handle_reload_request`` reloads a pane while preserving cursor context
  * ``_sync_monitored_dirs`` re-points the watchers as panes navigate
  * ``_quit`` tears monitoring down

Monitoring is faked (``FakeMonitor``) so tests stay deterministic and never
spawn watchdog threads; the app is built on the headless ``memory`` backend
with a temp-db state manager so the real ``~/.xefm/state.db`` is untouched.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class FakeMonitor:
    """Records interactions instead of watching the filesystem."""

    def __init__(self, config, file_manager):
        self.reload_queue = file_manager.reload_queue
        self.enabled = True
        self.updated = []          # [(pane_name, path_str), ...]
        self.stopped = False

    def is_monitoring_enabled(self):
        return self.enabled

    def update_monitored_directory(self, pane_name, path):
        self.updated.append((pane_name, str(path)))

    def stop_monitoring(self):
        self.stopped = True


class MonitoringTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.left_dir = os.path.join(self.tmp, "left")
        self.right_dir = os.path.join(self.tmp, "right")
        os.makedirs(self.left_dir)
        os.makedirs(self.right_dir)
        for n in ("a.txt", "b.txt", "c.txt"):
            open(os.path.join(self.left_dir, n), "w").close()

        self.sm = XeFMStateManager(db_path=os.path.join(self.tmp, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        # Patch the monitor class so construction wires up a FakeMonitor.
        self._patcher = patch.object(xefm_app, "FileMonitorManager", FakeMonitor)
        self._patcher.start()
        self.app = xefm_app.XeFMApp(
            self.backend, self.left_dir, self.right_dir,
            left_provided=True, right_provided=True,
            state_manager=self.sm,
        )

    def tearDown(self):
        self._patcher.stop()
        try:
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def left_names(self):
        return [f.name for f in self.app.pm.left_pane["files"]]

    def focus_left_on(self, name):
        self.app.pm.left_pane["focused_index"] = self.left_names().index(name)


class MonitorLifecycle(MonitoringTestBase):
    def test_both_panes_monitored_on_construction(self):
        panes = {name for name, _ in self.app.file_monitor.updated}
        self.assertEqual(panes, {"left", "right"})

    def test_navigation_repoints_watcher(self):
        self.app.file_monitor.updated.clear()
        self.app.pm.left_pane["path"] = xefm_app.Path(self.right_dir)

        self.app._sync_monitored_dirs()

        self.assertIn(("left", self.right_dir), self.app.file_monitor.updated)

    def test_unchanged_dirs_are_not_repointed(self):
        self.app.file_monitor.updated.clear()

        self.app._sync_monitored_dirs()

        self.assertEqual(self.app.file_monitor.updated, [])

    def test_quit_stops_monitoring(self):
        self.app._quit()
        self.assertTrue(self.app.file_monitor.stopped)


class ReloadQueue(MonitoringTestBase):
    def test_queued_request_is_applied(self):
        os.remove(os.path.join(self.left_dir, "b.txt"))
        self.app.reload_queue.put("left")

        reloaded = self.app._process_reload_queue()
        self.app._settle_listings()

        self.assertTrue(reloaded)
        self.assertEqual(self.left_names(), ["a.txt", "c.txt"])

    def test_empty_queue_is_a_noop(self):
        self.assertFalse(self.app._process_reload_queue())

    def test_multiple_requests_all_applied(self):
        for n in ("x.txt", "y.txt"):
            open(os.path.join(self.right_dir, n), "w").close()
        os.remove(os.path.join(self.left_dir, "a.txt"))
        self.app.reload_queue.put("left")
        self.app.reload_queue.put("right")

        reloaded = self.app._process_reload_queue()
        self.app._settle_listings()

        self.assertTrue(reloaded)
        self.assertEqual(self.left_names(), ["b.txt", "c.txt"])
        self.assertEqual([f.name for f in self.app.pm.right_pane["files"]],
                         ["x.txt", "y.txt"])


class ContextPreservation(MonitoringTestBase):
    def test_cursor_stays_on_same_file(self):
        self.focus_left_on("b.txt")
        open(os.path.join(self.left_dir, "a2.txt"), "w").close()  # list grows

        self.app._handle_reload_request("left")
        self.app._settle_listings()

        self.assertEqual(
            self.left_names()[self.app.pm.left_pane["focused_index"]], "b.txt")

    def test_cursor_moves_to_nearest_when_deleted(self):
        self.focus_left_on("b.txt")
        os.remove(os.path.join(self.left_dir, "b.txt"))

        self.app._handle_reload_request("left")
        self.app._settle_listings()

        # Nearest name after 'b.txt' in the sorted list is 'c.txt'.
        self.assertEqual(
            self.left_names()[self.app.pm.left_pane["focused_index"]], "c.txt")

    def test_cursor_resets_when_all_files_gone(self):
        self.focus_left_on("b.txt")
        for n in ("a.txt", "b.txt", "c.txt"):
            os.remove(os.path.join(self.left_dir, n))

        self.app._handle_reload_request("left")
        self.app._settle_listings()

        self.assertEqual(self.app.pm.left_pane["files"], [])
        self.assertEqual(self.app.pm.left_pane["focused_index"], 0)
        self.assertEqual(self.app.pm.left_pane["scroll_offset"], 0)

    def test_cursor_clamps_to_last_when_last_file_deleted(self):
        self.focus_left_on("c.txt")  # last of a/b/c
        os.remove(os.path.join(self.left_dir, "c.txt"))

        self.app._handle_reload_request("left")
        self.app._settle_listings()

        self.assertEqual(
            self.left_names()[self.app.pm.left_pane["focused_index"]], "b.txt")

    def test_scroll_offset_preserved_when_possible(self):
        # A long list so the scroll offset is meaningful (display_height == 20).
        for i in range(30):
            open(os.path.join(self.left_dir, f"f{i:02d}.dat"), "w").close()
        for n in ("a.txt", "b.txt", "c.txt"):
            os.remove(os.path.join(self.left_dir, n))
        pane = self.app.pm.left_pane
        self.app.flm.refresh_files(pane)
        pane["focused_index"] = 15
        pane["scroll_offset"] = 5

        self.app._handle_reload_request("left")  # nothing changed on disk
        self.app._settle_listings()

        self.assertEqual(pane["scroll_offset"], 5)
        self.assertEqual(pane["files"][pane["focused_index"]].name, "f15.dat")

    def test_scroll_adjusts_when_focused_item_not_visible(self):
        for i in range(30):
            open(os.path.join(self.left_dir, f"f{i:02d}.dat"), "w").close()
        for n in ("a.txt", "b.txt", "c.txt"):
            os.remove(os.path.join(self.left_dir, n))
        pane = self.app.pm.left_pane
        self.app.flm.refresh_files(pane)
        pane["focused_index"] = 2      # near the top
        pane["scroll_offset"] = 12     # ...but scrolled far down (focus off-screen)

        self.app._handle_reload_request("left")
        self.app._settle_listings()

        # Offset pulled up so the focused row is visible again.
        self.assertLessEqual(pane["scroll_offset"], pane["focused_index"])

    def test_right_pane_context_preserved(self):
        for n in ("r1.txt", "r2.txt", "r3.txt"):
            open(os.path.join(self.right_dir, n), "w").close()
        pane = self.app.pm.right_pane
        self.app.flm.refresh_files(pane)
        pane["focused_index"] = [f.name for f in pane["files"]].index("r2.txt")
        open(os.path.join(self.right_dir, "r0.txt"), "w").close()  # shifts indices

        self.app._handle_reload_request("right")
        self.app._settle_listings()

        self.assertEqual(
            pane["files"][pane["focused_index"]].name, "r2.txt")

    def test_unknown_pane_name_is_ignored(self):
        self.assertFalse(self.app._handle_reload_request("middle"))


if __name__ == "__main__":
    unittest.main()
