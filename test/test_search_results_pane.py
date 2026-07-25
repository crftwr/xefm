"""
Search-results (virtual) pane for the PuiKit XeFMApp.

Feeding a filename / content search result set into the active pane as a flat,
virtual listing (``_feed_search_results``) lets every file operation act on the
found files, wherever they live. These tests cover the model + guards
(``pane['virtual']``, virtual-aware ``FileListManager.refresh_files``), the
feed itself (filename + content, content dedupe + line metadata), post-op
reconciliation (a vanished path drops from the set), navigation-clears-virtual,
the O / Shift-O reveal, and that monitoring reloads are suspended while virtual.

The app is driven headless through the ``memory`` backend, as in
``test_progressive_search_dialog.py``.
"""

import os
import sys
import shutil
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm import _config  # noqa: E402


class FLMVirtual(unittest.TestCase):
    """The virtual listing path in FileListManager, in isolation."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.flm = FileListManager(_config.Config())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, rel):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")
        return Path(p)

    def _pane(self, paths, **kw):
        pane = {
            "path": Path(self.tmp), "focused_index": 0, "scroll_offset": 0,
            "files": [], "selected_files": set(), "sort_mode": "name",
            "sort_reverse": False, "filter_pattern": "",
            "virtual": {"kind": "search", "root": Path(self.tmp), "mode": "filename",
                        "query": "q", "results": list(paths), "meta": {}},
        }
        pane.update(kw)
        return pane

    def test_refresh_builds_flat_listing_from_paths(self):
        a = self._touch("one/a.txt")
        b = self._touch("two/b.txt")
        pane = self._pane([a, b])
        self.flm.refresh_files(pane)
        self.assertEqual({f.name for f in pane["files"]}, {"a.txt", "b.txt"})
        # file_info cache is populated (rendering never stats).
        self.assertIn(str(a), pane["file_info"])

    def test_refresh_drops_vanished_paths(self):
        a = self._touch("one/a.txt")
        b = self._touch("two/b.txt")
        pane = self._pane([a, b])
        self.flm.refresh_files(pane)
        os.remove(str(b))
        self.flm.refresh_files(pane)
        self.assertEqual([f.name for f in pane["files"]], ["a.txt"])
        self.assertEqual([p.name for p in pane["virtual"]["results"]], ["a.txt"])

    def test_filter_applies_in_memory(self):
        self._touch("one/a.txt")
        keep = self._touch("two/keep.log")
        pane = self._pane([Path(os.path.join(self.tmp, "one/a.txt")), keep],
                          filter_pattern="*.log")
        self.flm.refresh_files(pane)
        self.assertEqual([f.name for f in pane["files"]], ["keep.log"])

    def test_sort_applies_in_memory(self):
        a = self._touch("one/aaa.txt")
        z = self._touch("two/zzz.txt")
        pane = self._pane([z, a], sort_mode="name", sort_reverse=True)
        self.flm.refresh_files(pane)
        self.assertEqual([f.name for f in pane["files"]], ["zzz.txt", "aaa.txt"])


class AppVirtual(unittest.TestCase):
    """End-to-end through a headless XeFMApp on the memory backend."""

    def setUp(self):
        from puikit.backends import create_backend
        self.tmp = tempfile.mkdtemp()
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                              left_provided=True, right_provided=True)
        # These tests exercise pane state, not the filesystem watcher; spinning up
        # a real watchdog observer per test (8 of them) is both unnecessary and
        # flaky under the xdist/PyObjC runner. Stop it and keep it off.
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel, content="x"):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        return Path(p)

    def test_feed_filename_results_makes_virtual_pane(self):
        a = self._write("sub/a.txt")
        b = self._write("sub2/b.txt")
        self.app._feed_search_results("filename", [a, b], Path(self.tmp), "txt")
        pane = self.app.active_pane()
        self.assertIsNotNone(pane["virtual"])
        self.assertEqual(pane["virtual"]["mode"], "filename")
        self.assertEqual({f.name for f in pane["files"]}, {"a.txt", "b.txt"})

    def test_feed_content_dedupes_and_keeps_first_line(self):
        f = self._write("x.txt", "a\nneedle\nneedle\n")
        hits = [
            {"path": f, "line": 2, "text": "needle"},
            {"path": f, "line": 3, "text": "needle"},
        ]
        self.app._feed_search_results("content", hits, Path(self.tmp), "needle")
        pane = self.app.active_pane()
        self.assertEqual([p.name for p in pane["files"]], ["x.txt"])  # one entry
        self.assertEqual(pane["virtual"]["meta"][str(f)]["line"], 2)  # first match

    def test_feed_lands_cursor_on_accepted_hit(self):
        # Issue #224: accepting a hit feeds the whole set, but the cursor must
        # land on the file that was picked — not on the top row.
        a = self._write("one/a.txt")
        z = self._write("two/z.txt")
        self.app._feed_search_results("filename", [a, z], Path(self.tmp), "txt",
                                      focus=z)
        pane = self.app.active_pane()
        self.assertEqual(pane["files"][pane["focused_index"]].name, "z.txt")

    def test_feed_lands_cursor_on_accepted_content_hit(self):
        # A content hit is a {path, line, text} dict; the cursor lands on its file.
        a = self._write("one/a.txt", "needle\n")
        z = self._write("two/z.txt", "needle\n")
        hits = [{"path": a, "line": 1, "text": "needle"},
                {"path": z, "line": 1, "text": "needle"}]
        self.app._feed_search_results("content", hits, Path(self.tmp), "needle",
                                      focus=hits[1])
        pane = self.app.active_pane()
        self.assertEqual(pane["files"][pane["focused_index"]].name, "z.txt")

    def test_feed_matches_focus_by_full_path_not_name(self):
        # Same basename in two directories: the accepted one wins.
        first = self._write("one/dup.txt")
        second = self._write("two/dup.txt")
        self.app._feed_search_results("filename", [first, second],
                                      Path(self.tmp), "dup", focus=second)
        pane = self.app.active_pane()
        self.assertEqual(str(pane["files"][pane["focused_index"]]), str(second))

    def test_feed_without_focus_stays_at_top(self):
        a = self._write("one/a.txt")
        z = self._write("two/z.txt")
        self.app._feed_search_results("filename", [a, z], Path(self.tmp), "txt")
        pane = self.app.active_pane()
        self.assertEqual(pane["focused_index"], 0)

    def test_feed_scrolls_accepted_hit_into_view(self):
        paths = [self._write(f"d{i:03d}/f.txt") for i in range(200)]
        self.app._feed_search_results("filename", paths, Path(self.tmp), "txt",
                                      focus=paths[-1])
        pane = self.app.active_pane()
        idx = pane["focused_index"]
        self.assertEqual(str(pane["files"][idx]), str(paths[-1]))
        # The cursor is on screen, not below a stale offset of 0.
        height = self.app._display_height()
        self.assertTrue(pane["scroll_offset"] <= idx < pane["scroll_offset"] + height)

    def test_delete_reconciles_virtual_set(self):
        a = self._write("sub/a.txt")
        b = self._write("sub2/b.txt")
        self.app._feed_search_results("filename", [a, b], Path(self.tmp), "txt")
        pane = self.app.active_pane()
        # Simulate the file being removed by an op, then reconcile via _refresh.
        os.remove(str(a))
        self.app._refresh(pane)
        self.assertEqual([f.name for f in pane["files"]], ["b.txt"])

    def test_navigation_clears_virtual(self):
        sub = self._write("sub/a.txt")
        self.app._feed_search_results("filename", [sub], Path(self.tmp), "txt")
        pane = self.app.active_pane()
        self.assertIsNotNone(pane["virtual"])
        # Jumping to a directory (favorite path) exits virtual mode.
        self.app._jump_to_favorite({"name": "root", "path": str(self.tmp)})
        self.app._settle_listings()
        self.assertIsNone(pane["virtual"])

    def test_O_on_results_pane_goes_to_other_pane_dir(self):
        # Standing ON the results pane, O behaves like a normal pane: leave the
        # results and open the OTHER pane's directory, cursor synced to it.
        a = self._write("sub/a.txt")
        other = self.app.pm.get_inactive_pane()
        other["path"] = Path(os.path.join(self.tmp, "sub"))
        self.app.flm.refresh_files(other)
        other["focused_index"] = 0
        self.app._feed_search_results("filename", [a], Path(self.tmp), "txt")
        active = self.app.active_pane()
        self.assertIsNotNone(active["virtual"])
        self.assertTrue(self.app.dispatch("sync_current_to_other"))
        self.app._settle_listings()
        self.assertIsNone(active["virtual"])                       # left the results
        self.assertEqual(str(active["path"]), str(other["path"]))  # went to other's dir
        self.assertEqual(active["files"][active["focused_index"]].name, "a.txt")

    def test_reveal_other_keeps_virtual(self):
        a = self._write("sub/a.txt")
        self.app._feed_search_results("filename", [a], Path(self.tmp), "txt")
        pane = self.app.active_pane()
        other = self.app.pm.get_inactive_pane()
        pane["focused_index"] = 0
        self.app._reveal_result_other()
        self.app._settle_listings()
        self.assertIsNotNone(pane["virtual"])                 # source stays virtual
        self.assertEqual(str(other["path"]), str(a.parent))   # other jumped there

    def test_O_from_normal_pane_targets_other_virtual_cursor(self):
        # Feed results into the active pane, then stand on the OTHER (normal) pane
        # and press O — it should pull the virtual pane's *highlighted* result's
        # location into the pane we're standing on, landing on that file.
        a = self._write("one/a.txt")
        z = self._write("two/z.txt")
        self.app._feed_search_results("filename", [a, z], Path(self.tmp), "txt")
        virt = self.app.active_pane()
        virt["sort_mode"] = "name"
        self.app.flm.refresh_files(virt)
        # Highlight the second result (z.txt) in the virtual pane.
        names = [f.name for f in virt["files"]]
        virt["focused_index"] = names.index("z.txt")
        # Switch active pane to the normal one and press O (sync_current_to_other).
        self.app.pm.active_pane = "right" if self.app.pm.active_pane == "left" else "left"
        normal = self.app.active_pane()
        self.assertIsNone(normal["virtual"])
        self.assertTrue(self.app.dispatch("sync_current_to_other"))
        self.app._settle_listings()
        self.assertEqual(str(normal["path"]), str(z.parent))  # went to z's dir
        self.assertIsNotNone(virt["virtual"])                 # results untouched
        # cursor landed on z.txt
        self.assertEqual(normal["files"][normal["focused_index"]].name, "z.txt")

    def test_file_pane_shows_root_relative_paths(self):
        deep = self._write("a/b/deep.txt")
        top = self._write("top.txt")
        self.app._feed_search_results("filename", [deep, top], Path(self.tmp), "txt")
        # The name column shows each hit's path relative to the search root (so a
        # scattered result reveals *where* it lives), via FilePane._display_name.
        fp = self.app._active_view()
        names = {fp._display_name(e) for e in self.app.active_pane()["files"]}
        self.assertEqual(names, {"a/b/deep.txt", "top.txt"})

    def test_monitoring_reload_suspended_while_virtual(self):
        a = self._write("sub/a.txt")
        self.app._feed_search_results("filename", [a], Path(self.tmp), "txt")
        pane = self.app.active_pane()
        name = self.app._pane_name_of(pane)
        # A reload request for a virtual pane is a no-op (returns False), so the
        # result set is never blown away by a filesystem event.
        self.assertFalse(self.app._handle_reload_request(name))
        self.assertIsNotNone(pane["virtual"])


if __name__ == "__main__":
    unittest.main()
