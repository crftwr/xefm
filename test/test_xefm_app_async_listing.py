"""Async directory listing for panes (XeFMApp._list_pane).

Every listing runs on a worker thread so the UI never blocks on iterdir/stat —
local, slow network mount, spun-down disk, or remote (ssh://, s3://) alike. The
result is installed on the UI-thread drain (_process_result_queue), with a
single-flight generation guard so a superseded navigation's result is dropped,
and a deferred "Loading…" indicator (_pump_loading_indicator) that only reveals
itself once a listing has been pending past the delay — so fast navs never flash.

Run with: python -m pytest test/test_xefm_app_async_listing.py -v
"""

import os
import queue
import sys
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402


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

    def compute_listing(self, path, *, filter_pattern=None, sort_mode="name",
                        sort_reverse=False):
        self.compute_calls += 1
        return self._result

    def apply_listing(self, pane, result):
        pane["files"] = result["files"]
        pane["file_info"] = result["file_info"]
        if pane["files"]:
            pane["focused_index"] = min(pane["focused_index"], len(pane["files"]) - 1)
        else:
            pane["focused_index"] = 0


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


if __name__ == "__main__":
    unittest.main()
