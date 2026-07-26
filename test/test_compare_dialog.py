"""App-integration tests for Compare & Select: drives the real dialog through a
MemoryBackend + XeFMApp so the handler wiring (guards, dialog → criteria → applied
selection, replace/preserve, the content task path) and the keyboard model are
covered. Complements test_compare_selection.py, which unit-tests the pure engine."""

import os
import sys
import shutil
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.compare_dialog import CompareSelectDialog, ConditionRow  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402


def _key(k):
    return Event(EventType.KEY, key=k)


def _write(d, rel, data=b"x", mtime=None):
    p = os.path.join(d, rel)
    with open(p, "wb") as f:
        f.write(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def _enable(row, relation):
    """Turn a condition row on and set its relation (as the keyboard would)."""
    row.checkbox.checked = True
    row.set_index(row.options.index(relation))


class CompareDialogApp(unittest.TestCase):
    def setUp(self):
        self.left = tempfile.mkdtemp()
        self.right = tempfile.mkdtemp()
        _write(self.left, "same.txt", b"hello", mtime=1000.0)
        _write(self.right, "same.txt", b"hello", mtime=1000.0)         # identical
        _write(self.left, "newer.txt", b"AAAA", mtime=5000.0)
        _write(self.right, "newer.txt", b"BBBB", mtime=1000.0)         # same size, newer, diff bytes
        _write(self.left, "orphan.txt", b"z")                          # only on the left
        _write(self.right, "only_right.txt", b"y")

        self.state_dir = tempfile.mkdtemp()
        # Temp state DB, never the real ~/.xefm/state.db: the app restores each
        # pane's sort mode, sort direction and filter from it, so the developer's
        # own last-used settings would otherwise decide these panes' row order.
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.left, self.right,
                              left_provided=True, right_provided=True,
                              state_manager=self.sm)
        # These tests assert on the dialog's *content*, and the app restores
        # whichever theme was last used — which on a developer's machine may be
        # one carrying an arriving-text effect (see puikit.textfx), so a
        # freshly-drawn dialog's first frame is mid-animation rather than final.
        # Force the effect off: it is not what this file is about.
        self.app.panel.set_text_effect(False)
        # Nothing here needs the filesystem watcher, and a real watchdog observer
        # per test is flaky under the xdist/PyObjC runner (see
        # test_search_results_pane.py). Stop it and keep it off.
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
        except Exception:
            pass
        self.b.close()
        shutil.rmtree(self.left, ignore_errors=True)
        shutil.rmtree(self.right, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _open(self):
        self.app.compare_selection()
        dlg = self.app.panel._layers[-1].widget
        self.assertIsInstance(dlg, CompareSelectDialog)
        return dlg

    def _selected_names(self):
        return {os.path.basename(p) for p in self.app.active_pane()["selected_files"]}

    def _dialog_open(self):
        layers = self.app.panel._layers
        return bool(layers) and isinstance(layers[-1].widget, CompareSelectDialog)

    # --- draw / layout -------------------------------------------------------

    def test_dialog_draws_checkboxes_and_segments(self):
        self._open()
        self.app.panel.render()
        screen = "\n".join(self.b.snapshot())
        for token in ("Size", "Modified", "Content", "Preserve current selection",
                      "equal", "differs", "same", "newer", "older"):
            self.assertIn(token, screen, f"missing {token!r}")
        # each condition is a single line: label + its relations share one row
        line = next(ln for ln in self.b.snapshot() if "Modified" in ln)
        for opt in ("same", "newer", "older"):
            self.assertIn(opt, line)

    # --- applied selection ---------------------------------------------------

    def test_all_off_is_filename_only(self):
        dlg = self._open()
        dlg._accept()  # nothing enabled -> every common name
        self.assertEqual(self._selected_names(), {"same.txt", "newer.txt"})

    def test_mtime_newer(self):
        dlg = self._open()
        _enable(dlg._mtime, "newer")
        dlg._accept()
        self.assertEqual(self._selected_names(), {"newer.txt"})

    def test_size_and_mtime_anded(self):
        dlg = self._open()
        _enable(dlg._size, "equal")
        _enable(dlg._mtime, "newer")
        dlg._accept()  # newer.txt is same size + newer; same.txt is neither
        self.assertEqual(self._selected_names(), {"newer.txt"})

    def test_disabled_condition_is_any(self):
        dlg = self._open()
        dlg._mtime.set_index(dlg._mtime.options.index("newer"))  # index set but box OFF
        self.assertFalse(dlg._mtime.checkbox.checked)
        self.assertEqual(dlg._mtime.value, "any")
        dlg._accept()
        self.assertEqual(self._selected_names(), {"same.txt", "newer.txt"})

    def test_preserve_adds_to_selection(self):
        pane = self.app.active_pane()
        pane["selected_files"].add(os.path.join(self.left, "seed.marker"))
        dlg = self._open()
        dlg._preserve.checked = True          # union, don't clear
        _enable(dlg._mtime, "newer")
        dlg._accept()
        names = self._selected_names()
        self.assertIn("newer.txt", names)
        self.assertIn("seed.marker", names)   # prior selection preserved

    def test_replace_clears_prior_selection(self):
        pane = self.app.active_pane()
        pane["selected_files"].add(os.path.join(self.left, "seed.marker"))
        dlg = self._open()                    # preserve off (default) -> replace
        dlg._accept()
        names = self._selected_names()
        self.assertNotIn("seed.marker", names)
        self.assertEqual(names, {"same.txt", "newer.txt"})

    def test_cancel_leaves_selection_untouched(self):
        pane = self.app.active_pane()
        pane["selected_files"].add(os.path.join(self.left, "keep.marker"))
        dlg = self._open()
        dlg._finish(None)
        self.assertEqual(self._selected_names(), {"keep.marker"})

    def test_content_differs_runs_on_worker(self):
        dlg = self._open()
        _enable(dlg._content, "differs")
        dlg._accept()
        deadline = time.time() + 5
        while self.app.tasks.has_active() and time.time() < deadline:
            self.b.run_animation_ticks()
            time.sleep(0.01)
        self.b.run_animation_ticks()
        self.assertEqual(self._selected_names(), {"newer.txt"})

    # --- virtual (search-results) panes --------------------------------------

    def test_compare_from_virtual_pane(self):
        """A search-results pane compares like any other listing — its rows are
        real paths, joined by name to the other pane — and stays virtual."""
        sub = os.path.join(self.left, "sub")
        os.mkdir(sub)
        _write(sub, "newer.txt", b"CCCC", mtime=9000.0)   # scattered hit, newer
        self.app._feed_search_results(
            "filename",
            [Path(os.path.join(self.left, "same.txt")),
             Path(os.path.join(sub, "newer.txt"))],
            Path(self.left), "txt")
        pane = self.app.active_pane()
        self.assertIsNotNone(pane["virtual"])

        dlg = self._open()                    # no longer blocked
        _enable(dlg._mtime, "newer")
        dlg._accept()
        self.assertEqual(pane["selected_files"], {os.path.join(sub, "newer.txt")})
        self.assertIsNotNone(pane["virtual"])  # comparing doesn't leave the results

    def test_compare_against_virtual_other_pane(self):
        """Results on the *other* side: the active directory listing is joined to
        the scattered result set, and a name carrying several candidates matches
        when any of them satisfies the relation."""
        one, two = os.path.join(self.right, "one"), os.path.join(self.right, "two")
        os.mkdir(one); os.mkdir(two)
        _write(one, "newer.txt", b"AAAA", mtime=9000.0)   # newer than the left copy
        _write(two, "newer.txt", b"AAAA", mtime=1000.0)   # older than the left copy

        self.app.pm.switch_pane()             # feed the results into the right pane
        self.app._feed_search_results(
            "filename",
            [Path(os.path.join(one, "newer.txt")), Path(os.path.join(two, "newer.txt"))],
            Path(self.right), "newer.txt")
        self.assertIsNotNone(self.app.active_pane()["virtual"])
        self.app.pm.switch_pane()             # back to the left directory listing

        dlg = self._open()
        _enable(dlg._mtime, "newer")          # left copy is newer than two/newer.txt
        dlg._accept()
        self.assertEqual(self._selected_names(), {"newer.txt"})

    # --- cost (#245) ---------------------------------------------------------

    def _accept_counting_os_calls(self, dlg):
        """Accept the dialog and return how many per-file stat/lstat calls the
        comparison issued. Both bottom out every route a Path takes to the
        filesystem for attributes, so this counts round trips on a network mount."""
        from unittest import mock

        calls = []
        real_stat, real_lstat = os.stat, os.lstat

        def counted(inner):
            def wrapper(*a, **kw):
                calls.append(1)
                return inner(*a, **kw)
            return wrapper

        with mock.patch("os.stat", counted(real_stat)), \
             mock.patch("os.lstat", counted(real_lstat)):
            dlg._accept()
        return len(calls)

    def test_comparing_listed_panes_touches_no_files(self):
        """The panes already hold every attribute a stat-only comparison needs —
        their listings collected exactly these fields for exactly these entries —
        so accepting the dialog must not go back to the filesystem. Before #245 it
        asked per file per side, which on a NAS *was* the feature's cost."""
        for relation in (None, ("_size", "equal"), ("_mtime", "newer"),
                         ("_mtime", "older"), ("_size", "differs")):
            dlg = self._open()
            if relation is not None:
                _enable(getattr(dlg, relation[0]), relation[1])
            calls = self._accept_counting_os_calls(dlg)
            self.assertEqual(calls, 0, f"{relation} cost {calls} per-file calls")

    def test_a_virtual_pane_compares_from_its_snapshot_too(self):
        """A search-results pane keeps the same attribute snapshot a directory
        listing does, so comparing from one is just as free."""
        sub = os.path.join(self.left, "sub")
        os.mkdir(sub)
        _write(sub, "newer.txt", b"CCCC", mtime=9000.0)
        self.app._feed_search_results(
            "filename",
            [Path(os.path.join(self.left, "same.txt")),
             Path(os.path.join(sub, "newer.txt"))],
            Path(self.left), "txt")

        dlg = self._open()
        _enable(dlg._mtime, "newer")
        calls = self._accept_counting_os_calls(dlg)
        self.assertEqual(self.app.active_pane()["selected_files"],
                         {os.path.join(sub, "newer.txt")})
        self.assertEqual(calls, 0)

    def test_a_pane_with_no_snapshot_still_compares(self):
        """The fallback stays live: drop the snapshot and the engine reads the
        entries per file rather than reporting nothing."""
        pane = self.app.active_pane()
        pane["_listing_entries"] = None
        self.assertEqual(self.app._pane_attrs(pane), {})

        dlg = self._open()
        _enable(dlg._mtime, "newer")
        dlg._accept()
        self.assertEqual(self._selected_names(), {"newer.txt"})

    # --- keyboard model (no Tab, no buttons) ---------------------------------

    def test_up_down_move_focus_only(self):
        dlg = self._open()
        order = dlg.focus_children()
        self.assertEqual(order, [dlg._size, dlg._mtime, dlg._content, dlg._preserve])
        self.assertIs(dlg._focused, dlg._size)
        dlg.handle_event(_key("down"))
        self.assertIs(dlg._focused, dlg._mtime)
        dlg.handle_event(_key("down"))
        dlg.handle_event(_key("down"))
        self.assertIs(dlg._focused, dlg._preserve)
        dlg.handle_event(_key("down"))                 # wraps to the top
        self.assertIs(dlg._focused, dlg._size)
        before = dlg._focused
        dlg.handle_event(_key("tab"))                  # Tab does nothing
        self.assertIs(dlg._focused, before)

    def test_space_toggles_condition(self):
        dlg = self._open()                             # focus on Size, box off -> any
        self.assertEqual(dlg._size.value, "any")
        dlg.handle_event(_key("space"))               # on -> first relation
        self.assertTrue(dlg._size.checkbox.checked)
        self.assertEqual(dlg._size.value, "equal")
        dlg.handle_event(_key("space"))               # off -> any
        self.assertEqual(dlg._size.value, "any")

    def test_left_right_choose_relation(self):
        dlg = self._open()
        dlg.handle_event(_key("space"))               # enable Size (equal)
        self.assertEqual(dlg._size.value, "equal")
        dlg.handle_event(_key("right"))
        self.assertEqual(dlg._size.value, "differs")
        dlg.handle_event(_key("left"))
        self.assertEqual(dlg._size.value, "equal")
        # left/right on the preserve row (not a condition) is ignored
        for _ in range(3):
            dlg.handle_event(_key("down"))            # -> preserve
        self.assertIs(dlg._focused, dlg._preserve)
        dlg.handle_event(_key("right"))
        self.assertFalse(dlg._preserve.checked)

    def test_space_toggles_preserve(self):
        dlg = self._open()
        for _ in range(3):
            dlg.handle_event(_key("down"))            # -> preserve
        dlg.handle_event(_key("space"))
        self.assertTrue(dlg._preserve.checked)

    def test_enter_accepts_escape_cancels(self):
        dlg = self._open()
        dlg.handle_event(_key("space"))               # enable Size = equal
        dlg.handle_event(_key("enter"))               # accept -> closes
        self.assertFalse(self._dialog_open())
        self.assertEqual(self._selected_names(), {"same.txt", "newer.txt"})  # both equal-size

        pane = self.app.active_pane()
        pane["selected_files"].clear()
        pane["selected_files"].add(os.path.join(self.left, "keep.marker"))
        dlg = self._open()
        dlg.handle_event(_key("escape"))
        self.assertFalse(self._dialog_open())
        self.assertEqual(self._selected_names(), {"keep.marker"})


class ConditionRowUnit(unittest.TestCase):
    def test_value_is_any_until_enabled(self):
        r = ConditionRow("Size", ["equal", "differs"])
        self.assertEqual(r.value, "any")
        r.move(1)                        # relation moves, but still off
        self.assertEqual(r.value, "any")
        r.toggle()                       # enable
        self.assertEqual(r.value, "differs")
        r.toggle()                       # disable -> any (relation remembered)
        self.assertEqual(r.value, "any")
        r.toggle()
        self.assertEqual(r.value, "differs")

    def test_move_clamps(self):
        r = ConditionRow("Size", ["equal", "differs"])
        r.checkbox.checked = True
        r.move(-1)                       # already at first
        self.assertEqual(r.value, "equal")
        r.move(9)                        # past the end
        self.assertEqual(r.value, "differs")


if __name__ == "__main__":
    unittest.main()
