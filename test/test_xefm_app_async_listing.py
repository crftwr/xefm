"""Async directory listing for panes (XeFMApp._list_pane).

Every listing runs on a worker thread so the UI never blocks on iterdir/stat —
local, slow network mount, spun-down disk, or remote (ssh://, s3://) alike. The
result is installed on the UI-thread drain (_process_result_queue), with a
single-flight generation guard so a superseded navigation's result is dropped,
and a deferred "Loading…" indicator (_pump_loading_indicator) that only reveals
itself once a listing has been pending past the delay — so fast navs never flash.

Everything that re-lists goes through it, not just navigation (issue #203):
``_relist`` re-lists a pane in place (sort, filter, post-operation reload) with
the cursor untouched, ``_refresh`` adds the reset a directory change needs, and
``_start_initial_listings`` runs the two startup listings the same way — deferred
to the end of ``__init__``, because the worker path does not exist before it.

Run with: python -m pytest test/test_xefm_app_async_listing.py -v
"""

import contextlib
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import sort_keys  # noqa: E402


class FakePath:
    def __init__(self, s):
        self._s = s

    def __str__(self):
        return self._s


class StubFLM:
    """Stands in for FileListManager: canned listing, records compute calls."""

    def __init__(self, files):
        self._result = {"ok": True, "files": list(files),
                        "file_info": {str(f): {} for f in files}}
        self.compute_calls = 0
        self.last_filter = None
        self.refreshed = []

    def compute_listing(self, path, *, filter_pattern=None, sort_mode="name",
                        sort_reverse=False):
        self.compute_calls += 1
        self.last_filter = filter_pattern
        return self._result

    def apply_listing(self, pane, result):
        pane["files"] = result["files"]
        pane["file_info"] = result["file_info"]
        if pane["files"]:
            pane["focused_index"] = min(pane["focused_index"], len(pane["files"]) - 1)
        else:
            pane["focused_index"] = 0

    def recompute_listing(self, pane, *, filter_pattern=None, sort_mode="name",
                          sort_reverse=False):
        """These stub panes carry no listing snapshot, so this reports "nothing
        to reuse" exactly as FileListManager does — which is what keeps the
        worker-thread fallback below under test."""
        return None

    # --- the synchronous halves _relist / _apply_filter still lean on ---------

    def refresh_files(self, pane):
        """Only a virtual pane reaches this now — recorded so a test can prove a
        directory pane never does."""
        self.refreshed.append(pane)
        self.apply_listing(pane, self._result)

    def set_filter(self, pane, pattern):
        pane["filter_pattern"] = pattern
        pane["focused_index"] = 0
        pane["scroll_offset"] = 0
        pane["selected_files"].clear()


def _pane(path):
    return {
        "path": path, "files": [], "file_info": {},
        "focused_index": 0, "scroll_offset": 0,
        "filter_pattern": "", "sort_mode": "name", "sort_reverse": False,
        "selected_files": set(),
    }


class _PM:
    def __init__(self, left, right):
        self.left_pane, self.right_pane = left, right


def _app(left, right, files):
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app._result_queue = queue.Queue()
    app.flm = StubFLM(files)
    app.pm = _PM(left, right)
    return app


def _drain_next(app):
    """Wait for the worker to post its result, then apply it on the 'UI thread'."""
    item = app._result_queue.get(timeout=2)
    app._result_queue.put(item)
    return app._process_result_queue()


class ListingIsAsynchronous(unittest.TestCase):
    def test_any_path_lists_on_a_worker_and_installs_on_drain(self):
        # Even a plain local path now lists off the UI thread (no synchronous
        # blocking on iterdir/stat).
        left = _pane(FakePath("/home/me"))
        app = _app(left, _pane(FakePath("/tmp")), ["a", "b", "c"])
        ran = []
        app._list_pane("left", on_ready=lambda p: ran.append(len(p["files"])))
        # Synchronously: a pending loading state, files cleared, nothing applied.
        self.assertTrue(left["loading"])
        self.assertEqual(left["files"], [])
        self.assertEqual(ran, [])
        # The worker posts; drain it on the "UI thread".
        self.assertTrue(_drain_next(app))
        self.assertEqual(left["files"], ["a", "b", "c"])
        self.assertFalse(left["loading"])
        self.assertFalse(left["_loading_shown"])
        self.assertEqual(ran, [3])

    def test_remote_path_lists_the_same_way(self):
        left = _pane(FakePath("ssh://host/dir"))
        app = _app(left, _pane(FakePath("/tmp")), ["x"])
        app._list_pane("left")
        self.assertTrue(left["loading"])
        self.assertTrue(_drain_next(app))
        self.assertEqual(left["files"], ["x"])


class DeferredLoadingIndicator(unittest.TestCase):
    def test_fast_load_never_flashes_the_indicator(self):
        left = _pane(FakePath("/home/me"))
        app = _app(left, _pane(FakePath("/tmp")), ["a"])
        app._list_pane("left")
        # Just started: well under the delay, so the indicator stays hidden.
        self.assertFalse(app._pump_loading_indicator())
        self.assertFalse(left.get("_loading_shown"))

    def test_slow_load_reveals_the_indicator_once(self):
        left = _pane(FakePath("/mnt/slow"))
        app = _app(left, _pane(FakePath("/tmp")), ["a"])
        app._list_pane("left")
        # Backdate the start so the load looks slow, then pump.
        left["_load_started"] = time.monotonic() - 1.0
        self.assertTrue(app._pump_loading_indicator())   # crosses the threshold
        self.assertTrue(left["_loading_shown"])
        # Idempotent: it fires exactly once (no repeated forced re-renders).
        self.assertFalse(app._pump_loading_indicator())

    def test_indicator_state_clears_when_the_result_lands(self):
        left = _pane(FakePath("/mnt/slow"))
        app = _app(left, _pane(FakePath("/tmp")), ["a", "b"])
        app._list_pane("left")
        left["_load_started"] = time.monotonic() - 1.0
        app._pump_loading_indicator()
        self.assertTrue(left["_loading_shown"])
        _drain_next(app)
        self.assertFalse(left["loading"])
        self.assertFalse(left["_loading_shown"])


class SingleFlight(unittest.TestCase):
    def test_superseded_result_is_dropped(self):
        left = _pane(FakePath("ssh://host/a"))
        app = _app(left, _pane(FakePath("/tmp")), ["stale"])
        app._list_pane("left")                    # gen 1
        item = app._result_queue.get(timeout=2)   # wait until the worker posted
        left["_load_gen"] = 99                     # a newer navigation bumped gen
        app._result_queue.put(item)
        self.assertFalse(app._process_result_queue())  # stale result dropped
        self.assertEqual(left["files"], [])            # not clobbered
        self.assertTrue(left["loading"])               # newer load still pending

    def test_second_navigation_supersedes_the_first(self):
        left = _pane(FakePath("/dir/a"))
        app = _app(left, _pane(FakePath("/tmp")), ["first"])
        app._list_pane("left")                    # gen 1, worker posts gen 1
        first = app._result_queue.get(timeout=2)
        # User navigates again before the first result is drained.
        left["path"] = FakePath("/dir/b")
        app._list_pane("left")                    # gen 2, worker posts gen 2
        second = app._result_queue.get(timeout=2)
        # The stale gen-1 result is dropped; the gen-2 result installs.
        app._result_queue.put(first)
        self.assertFalse(app._process_result_queue())
        app._result_queue.put(second)
        self.assertTrue(app._process_result_queue())
        self.assertEqual(left["files"], ["first"])  # StubFLM returns the same list
        self.assertFalse(left["loading"])


class RelistKeepsThePaneInPlace(unittest.TestCase):
    """``_relist`` re-lists the *same* directory off the UI thread; ``_refresh``
    is that plus the cursor reset and history record a navigation needs."""

    def test_relist_lists_on_a_worker_and_leaves_the_cursor_alone(self):
        left = _pane(FakePath("/mnt/slow"))
        left["focused_index"], left["scroll_offset"] = 2, 1
        app = _app(left, _pane(FakePath("/tmp")), ["a", "b", "c", "d"])
        app._relist(left)
        # Nothing was read on this thread, and the cursor did not move: this is
        # the same directory, not a navigation.
        self.assertTrue(left["loading"])
        self.assertEqual(left["files"], [])
        self.assertEqual(left["focused_index"], 2)
        self.assertEqual(left["scroll_offset"], 1)
        self.assertTrue(_drain_next(app))
        self.assertEqual(left["files"], ["a", "b", "c", "d"])
        self.assertEqual(left["focused_index"], 2)
        self.assertEqual(left["scroll_offset"], 1)
        self.assertEqual(app.flm.refreshed, [])  # never the synchronous path

    def test_refresh_resets_the_cursor_and_records_history(self):
        left = _pane(FakePath("/dir/new"))
        left["focused_index"], left["scroll_offset"] = 3, 2
        app = _app(left, _pane(FakePath("/tmp")), ["a", "b"])
        app._history = []
        app._refresh(left)
        self.assertEqual(left["focused_index"], 0)
        self.assertEqual(left["scroll_offset"], 0)
        self.assertEqual(app._history, ["/dir/new"])
        self.assertTrue(_drain_next(app))

    def test_virtual_pane_rebuilds_in_memory_with_no_worker(self):
        # A search-results feed has no directory to read: it must not be listed.
        left = _pane(FakePath("/dir"))
        left["virtual"] = {"kind": "search", "results": []}
        app = _app(left, _pane(FakePath("/tmp")), ["a"])
        ran = []
        app._relist(left, on_ready=ran.append)
        self.assertEqual(app.flm.compute_calls, 0)
        self.assertEqual(app.flm.refreshed, [left])
        self.assertEqual(ran, [left])  # on_ready fires synchronously
        self.assertTrue(app._result_queue.empty())


class FilterAppliesAsynchronously(unittest.TestCase):
    def test_the_knobs_land_at_once_but_the_count_waits_for_the_listing(self):
        left = _pane(FakePath("/mnt/slow"))
        left["focused_index"], left["scroll_offset"] = 4, 2
        left["selected_files"].add("/mnt/slow/x")
        app = _app(left, _pane(FakePath("/tmp")), ["a.py", "b.py"])
        counts = []
        app._apply_filter(left, "*.py", on_count=counts.append)
        # Filter state is pane state — immediate. The item count is a property of
        # the listing, so it only exists once that lands.
        self.assertEqual(left["filter_pattern"], "*.py")
        self.assertEqual(left["focused_index"], 0)
        self.assertEqual(left["scroll_offset"], 0)
        self.assertEqual(left["selected_files"], set())
        self.assertEqual(counts, [])
        self.assertTrue(_drain_next(app))
        self.assertEqual(counts, [2])
        self.assertEqual(app.flm.last_filter, "*.py")  # the worker saw the new one

    def test_clearing_needs_no_count_callback(self):
        left = _pane(FakePath("/mnt/slow"))
        left["filter_pattern"] = "*.py"
        app = _app(left, _pane(FakePath("/tmp")), ["a", "b"])
        app._apply_filter(left, "")
        self.assertEqual(left["filter_pattern"], "")
        self.assertTrue(_drain_next(app))
        self.assertEqual(left["files"], ["a", "b"])


class StartupListsAsynchronously(unittest.TestCase):
    def test_both_panes_list_on_workers_carrying_the_cursor_hook(self):
        left, right = _pane(FakePath("/l")), _pane(FakePath("/r"))
        app = _app(left, right, ["a", "b"])
        restored = []
        app._restore_remembered_cursor = restored.append
        app._start_initial_listings()
        self.assertTrue(left["loading"])
        self.assertTrue(right["loading"])
        self.assertEqual(left["files"], [])
        app._settle_listings()
        self.assertEqual(left["files"], ["a", "b"])
        self.assertEqual(right["files"], ["a", "b"])
        # The saved cursor is matched by filename, so it can only be placed once
        # the files are in — it rides the listing rather than running inline.
        self.assertEqual(restored, [left, right])


class _RealAppBase(unittest.TestCase):
    """A headless XeFMApp on the memory backend over a real temp directory."""

    def setUp(self):
        from xefm.state_manager import XeFMStateManager
        from puikit.backends import create_backend
        self.tmp = tempfile.mkdtemp()
        self.cfgdir = tempfile.mkdtemp()
        for n in ("a.txt", "b.txt", "c.txt"):
            open(os.path.join(self.tmp, n), "w").close()
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
        except Exception:
            pass
        try:
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def _build(self):
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        return self.app


class StartupOnARealApp(_RealAppBase):
    """End-to-end: constructing XeFMApp reads no directory on the calling
    thread, and the remembered cursor still lands once the listings do."""

    def test_construction_does_not_block_on_the_directory(self):
        app = self._build()
        # Launch does not wait for iterdir/stat — both panes are still loading.
        self.assertTrue(app.pm.left_pane["loading"])
        self.assertTrue(app.pm.right_pane["loading"])
        app._settle_listings()
        self.assertEqual([f.name for f in app.pm.left_pane["files"]],
                         ["a.txt", "b.txt", "c.txt"])
        self.assertFalse(app.pm.left_pane["loading"])

    def test_remembered_cursor_still_lands_after_the_listing(self):
        # Resolve the directory the way the app does, so the saved key matches.
        directory = str(xefm_app.Path(self.tmp).resolve())
        self.sm.save_pane_cursor_position("left", directory, "b.txt")
        app = self._build()
        app._settle_listings()
        pane = app.pm.left_pane
        self.assertEqual(pane["files"][pane["focused_index"]].name, "b.txt")


class SortOnARealApp(_RealAppBase):
    """Sorting re-orders the entries already in hand — no directory read at all
    (#183).

    The original design re-listed on a worker, which kept the UI responsive but
    still paid a full re-read: on a NAS that is one network round trip per file,
    for information the pane had already collected. Reusing the snapshot removed
    the read; the ordering itself then ran on the UI thread, because it was
    microseconds of arithmetic and landing on the tick avoided a blank pane.

    It is back on a worker now that a config can supply the key
    (:mod:`xefm.sort_keys`) — arbitrary code, once per entry. The pane is not
    blanked this time, so the flicker that argued for the synchronous version
    does not come back with it.
    """

    @contextlib.contextmanager
    def _no_directory_reads(self, app):
        """Fail the test if anything re-reads the directory inside the block."""
        def boom(*a, **kw):
            raise AssertionError("re-read the directory to sort")
        original = app.flm.compute_listing
        app.flm.compute_listing = boom
        try:
            yield
        finally:
            app.flm.compute_listing = original

    def test_quick_sort_reorders_without_reading_the_directory(self):
        app = self._build()
        app._settle_listings()
        with self._no_directory_reads(app):
            app.dispatch("quick_sort_size")
        self.assertFalse(app.pm.left_pane["loading"])  # nothing to wait for
        self.assertEqual(app.pm.left_pane["sort_mode"], "size")
        self.assertEqual(len(app.pm.left_pane["files"]), 3)

    def test_toggle_reverse_reorders_without_reading_the_directory(self):
        app = self._build()
        app._settle_listings()
        with self._no_directory_reads(app):
            app._toggle_reverse()
            # Settled inside the guard, so "no directory reads" covers the
            # worker's whole re-sort, not just the request.
            app._settle_listings()
        self.assertEqual([f.name for f in app.pm.left_pane["files"]],
                         ["c.txt", "b.txt", "a.txt"])
        self.assertFalse(app.pm.left_pane["loading"])

    def test_sort_keeps_the_cursor_on_the_same_file(self):
        app = self._build()
        app._settle_listings()
        pane = app.pm.left_pane
        pane["focused_index"] = next(i for i, f in enumerate(pane["files"])
                                     if f.name == "a.txt")
        app._toggle_reverse()
        app._settle_listings()
        # a.txt moved from the top to the bottom; the cursor went with it rather
        # than staying on row 0.
        self.assertEqual(pane["files"][pane["focused_index"]].name, "a.txt")

    def test_filter_reuses_the_snapshot_and_widening_restores_entries(self):
        app = self._build()
        app._settle_listings()
        pane = app.pm.left_pane
        with self._no_directory_reads(app):
            app._apply_filter(pane, "a*")
            app._settle_listings()
            self.assertEqual([f.name for f in pane["files"]], ["a.txt"])
            # The snapshot is kept pre-filter, so clearing restores the rest
            # without going back to the directory.
            app._apply_filter(pane, "")
            app._settle_listings()
        self.assertEqual([f.name for f in pane["files"]],
                         ["a.txt", "b.txt", "c.txt"])

    def test_a_pane_with_no_snapshot_still_falls_back_to_a_real_listing(self):
        app = self._build()
        app._settle_listings()
        pane = app.pm.left_pane
        pane["_listing_entries"] = None  # e.g. the last listing failed
        app._toggle_reverse()
        self.assertTrue(pane["loading"])  # went to a worker after all
        app._settle_listings()
        self.assertEqual([f.name for f in pane["files"]],
                         ["c.txt", "b.txt", "a.txt"])


class RegisteredSortKeyOnARealApp(_RealAppBase):
    """A config-supplied key sorts the pane, and does it off the UI thread."""

    def setUp(self):
        super().setUp()
        sort_keys.clear()

    def tearDown(self):
        sort_keys.clear()
        super().tearDown()

    def test_a_registered_key_orders_the_pane(self):
        app = self._build()
        app._settle_listings()
        sort_keys.register("backwards", lambda e: [-ord(c) for c in e.name],
                           label="Backwards")
        app.pm.left_pane["sort_mode"] = "backwards"
        app._resort(app.pm.left_pane)
        app._settle_listings()
        self.assertEqual([f.name for f in app.pm.left_pane["files"]],
                         ["c.txt", "b.txt", "a.txt"])

    def test_the_key_runs_off_the_ui_thread(self):
        app = self._build()
        app._settle_listings()
        started, release = threading.Event(), threading.Event()
        ui_thread = threading.current_thread()
        ran_on = []

        def slow(entry):
            ran_on.append(threading.current_thread())
            started.set()
            release.wait(2.0)
            return entry.name

        sort_keys.register("slow", slow, label="Slow")
        pane = app.pm.left_pane
        before = list(pane["files"])
        pane["sort_mode"] = "slow"
        app._resort(pane)

        # The call returned while the key is still running, and the pane kept the
        # rows it had rather than blanking — they stay actionable throughout.
        self.assertTrue(started.wait(2.0), "the sort key never started")
        self.assertEqual(pane["files"], before)
        self.assertFalse(pane["loading"])
        self.assertTrue(pane["_load_pending"])
        self.assertNotIn(ui_thread, ran_on)

        release.set()
        app._settle_listings()
        self.assertEqual([f.name for f in pane["files"]],
                         ["a.txt", "b.txt", "c.txt"])

    def test_a_remembered_mode_that_no_longer_exists_falls_back(self):
        app = self._build()
        pane = app.pm.left_pane
        # The config that defined "explorer" was edited away; the saved state
        # still names it.
        app.state_manager.save_pane_state("left", dict(pane, sort_mode="explorer"))

        pane["sort_mode"] = "name"
        app._restore_one_pane("left", pane, cmdline_provided=True)
        self.assertEqual(pane["sort_mode"], "name")

        sort_keys.register("explorer", lambda e: e.name, label="Explorer order")
        app._restore_one_pane("left", pane, cmdline_provided=True)
        self.assertEqual(pane["sort_mode"], "explorer")


if __name__ == "__main__":
    unittest.main()
