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
import time
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
        self.suppressed = []       # str paths, from suppress_path (#243)
        self.released = []

    def is_monitoring_enabled(self):
        return self.enabled

    def update_monitored_directory(self, pane_name, path):
        self.updated.append((pane_name, str(path)))

    def stop_monitoring(self):
        self.stopped = True

    # File operations bracket the directories they mutate (#243).
    def suppress_path(self, path):
        self.suppressed.append(str(path))

    def release_path(self, path):
        self.released.append(str(path))


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
        self.app._settle_listings()  # startup lists on workers; wait for it

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

    def test_fileops_get_the_monitor_attached(self):
        # File operations silence the watchers on the directories they mutate
        # (#243); the app wires its monitor into the shared operation service.
        self.assertIs(self.app._fileops.monitor, self.app.file_monitor)

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

        # The reload has to actually change the listing, or it is dropped before
        # the cursor restore runs (see ReloadIsDroppedWhenNothingChanged) — a
        # reload that installs nothing must not move the user's viewport either.
        # f30 sorts last, so the focused row keeps its index and only the offset
        # is under test.
        open(os.path.join(self.left_dir, "f30.dat"), "w").close()

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


class ReloadIsDroppedWhenNothingChanged(MonitoringTestBase):
    """A monitor reload whose listing matches what the pane already shows is
    discarded instead of swapped in (#239).

    macOS reports a metadata-only write — an xattr, a permission bit — as an
    ordinary "modified" event, so simply opening a file in an app fires one.
    Playing a video emits a stream of them. None change a single cell the pane
    draws, so none should cost a re-render, a cursor reconciliation, or the
    blank-then-repopulate that a re-list used to force.
    """

    def touch_metadata(self, name):
        """Change a file's metadata *only* — the exact shape of the spurious
        event this whole path exists to absorb. Its name, size and mtime are all
        left alone, so the listing must compare equal. macOS reports this
        through FSEvents identically to a real write."""
        path = os.path.join(self.left_dir, name)
        os.chmod(path, 0o600)
        os.chmod(path, 0o644)

    def test_unchanged_listing_leaves_the_pane_alone(self):
        self.touch_metadata("b.txt")
        before = self.app.pm.left_pane["files"]

        self.assertTrue(self.app._handle_reload_request("left"))
        self.app._settle_listings()

        # Same list object, not merely an equal one: nothing was swapped in.
        self.assertIs(self.app.pm.left_pane["files"], before)
        self.assertEqual(self.left_names(), ["a.txt", "b.txt", "c.txt"])

    def test_unchanged_listing_reports_nothing_applied(self):
        self.touch_metadata("b.txt")
        self.app.reload_queue.put("left")

        self.app._process_reload_queue()
        # Wait for the worker, then drain: the result must be dropped, so the
        # drain reports that it changed nothing.
        deadline = time.monotonic() + 2.0
        while self.app._listings_pending() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.app._process_result_queue())

    def test_pane_stays_populated_while_reloading(self):
        """The pane keeps its entries for the whole re-read. Previously
        _list_pane emptied files/file_info up front, so every spurious reload
        blanked the pane for the length of a full directory scan."""
        before = list(self.app.pm.left_pane["files"])

        self.app._handle_reload_request("left")

        # Checked *before* settling: the worker is still running here.
        self.assertEqual(self.app.pm.left_pane["files"], before)
        self.assertNotEqual(self.app.pm.left_pane["file_info"], {})
        self.assertFalse(self.app.pm.left_pane.get("loading"))
        self.app._settle_listings()

    def test_real_change_is_still_installed(self):
        os.remove(os.path.join(self.left_dir, "b.txt"))

        self.app._handle_reload_request("left")
        self.app._settle_listings()

        self.assertEqual(self.left_names(), ["a.txt", "c.txt"])

    def test_dropped_reload_still_refreshes_the_sort_snapshot(self):
        """Dropping the result must not leave a stale entry snapshot behind: a
        later sort or filter rebuilds from it without touching the disk."""
        self.touch_metadata("b.txt")

        self.app._handle_reload_request("left")
        self.app._settle_listings()

        entries = self.app.pm.left_pane["_listing_entries"]
        self.assertEqual(sorted(p.name for p, _ in entries),
                         ["a.txt", "b.txt", "c.txt"])

    def test_reload_does_not_supersede_an_in_flight_listing(self):
        """A navigation already reading the directory carries cursor placement in
        its on_ready; a monitor reload must not bump the generation out from
        under it just to read the same directory again."""
        self.app._list_pane("left", on_ready=lambda p: None)   # navigation in flight
        gen = self.app.pm.left_pane["_load_gen"]

        self.assertFalse(self.app._handle_reload_request("left"))

        self.assertEqual(self.app.pm.left_pane["_load_gen"], gen)
        self.app._settle_listings()

    def test_empty_directory_lands_on_a_blanked_pane(self):
        """An empty listing compares equal to a pane blanked by an in-flight
        navigation. It must still be installed, or the pane stays 'loading'
        forever with nothing to show."""
        for n in ("a.txt", "b.txt", "c.txt"):
            os.remove(os.path.join(self.left_dir, n))

        self.app._list_pane("left")                 # blanks the pane, loading=True
        self.app._settle_listings()

        self.assertEqual(self.app.pm.left_pane["files"], [])
        self.assertFalse(self.app.pm.left_pane["loading"])


if __name__ == "__main__":
    unittest.main()
