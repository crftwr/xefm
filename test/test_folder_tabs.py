"""Folder tabs: several places kept open in each pane (#563).

Headless on the ``memory`` backend. A tab is a whole pane dict, and a side's
current tab *is* its pane, so what is under test is the switching: what each
tab keeps, that a listing never lands on the wrong tab, that a hidden tab is
re-read on the way back in, and that tabs survive a restart without being read.

Run with: python -m pytest test/test_folder_tabs.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit import Panel  # noqa: E402

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


class _Base(unittest.TestCase):

    def setUp(self):
        # Real paths: macOS's temp dir sits behind /var -> /private/var.
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.state_dir = tempfile.mkdtemp()
        self.db = os.path.join(self.state_dir, "state.db")
        for d in ("a", "b", os.path.join("a", "inner")):
            os.makedirs(os.path.join(self.tmp, d), exist_ok=True)
        for f in ("a/one.txt", "a/two.txt", "b/three.txt"):
            with open(os.path.join(self.tmp, f), "w") as fh:
                fh.write("x")
        self.app = self._open(os.path.join(self.tmp, "a"))
        self.pane = self.app.active_pane()

    def _open(self, left, *, provided=True):
        from puikit.backends import create_backend
        self.b = create_backend("memory")
        self.b.open()
        app = xefm_app.XeFMApp(self.b, left, self.tmp,
                               left_provided=provided, right_provided=True,
                               state_manager=XeFMStateManager(db_path=self.db))
        app.file_monitor.stop_monitoring()
        app.file_monitor.enabled = False
        app._settle_listings()
        return app

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _do(self, action):
        self.app.dispatch(action)
        self.app._settle_listings()

    def _names(self, pane=None):
        return sorted(f.name for f in (pane or self.app.active_pane())["files"])

    def _focus(self, name):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(name)

    def _last_log(self):
        text, _style = self.app.log.lines[-1]
        return text


class Tabs(_Base):

    def test_a_new_tab_opens_at_the_same_place_with_the_same_cursor(self):
        self._focus("two.txt")
        self._do("new_tab")
        tabs = self.app.pm.tabs["left"]
        self.assertEqual(len(tabs), 2)
        self.assertEqual(self.app.pm.tab_index["left"], 1)
        pane = self.app.active_pane()
        self.assertIsNot(pane, tabs[0])
        self.assertEqual(str(pane["path"]), str(tabs[0]["path"]))
        self.assertEqual(pane["files"][pane["focused_index"]].name, "two.txt")
        # The view draws the tab that is current.
        self.assertIs(self.app.left_view.pane, pane)

    def test_each_tab_keeps_its_own_place(self):
        self._do("new_tab")
        self.app._go_to_dir(self.app.active_pane(), Path(os.path.join(self.tmp, "b")), None)
        self.app._settle_listings()
        self.assertEqual(self._names(), ["three.txt"])
        self._do("prev_tab")
        self.assertEqual(self._names(), ["inner", "one.txt", "two.txt"])
        self._do("next_tab")
        self.assertEqual(self._names(), ["three.txt"])

    def test_selection_and_sort_belong_to_the_tab(self):
        first = self.app.active_pane()
        first["selected_files"].add(str(first["files"][0]))
        self._do("new_tab")
        self.assertFalse(self.app.active_pane()["selected_files"])
        self._do("prev_tab")
        self.assertEqual(len(self.app.active_pane()["selected_files"]), 1)

    def test_open_in_new_tab_goes_into_the_directory(self):
        self._focus("inner")
        self._do("open_in_new_tab")
        self.assertEqual(self.app.active_pane()["path"].name, "inner")
        self.assertEqual(self.app.pm.tabs["left"][0]["path"].name, "a")

    def test_open_in_new_tab_needs_a_directory(self):
        self._focus("one.txt")
        self._do("open_in_new_tab")
        self.assertEqual(len(self.app.pm.tabs["left"]), 1)
        self.assertIn("put the cursor on a directory", self._last_log())

    def test_close_shows_the_next_and_keeps_the_last_one(self):
        self._do("new_tab")
        self._do("new_tab")
        self.app.pm.select_tab("left", 1)
        self.app._show_tab("left")
        self._do("close_tab")
        self.assertEqual(len(self.app.pm.tabs["left"]), 2)
        self.assertEqual(self.app.pm.tab_index["left"], 1)
        self._do("close_tab")
        self._do("close_tab")
        self.assertEqual(len(self.app.pm.tabs["left"]), 1)
        self.assertIn("only tab", self._last_log())

    def test_tabs_are_per_pane(self):
        self._do("new_tab")
        self.assertEqual(len(self.app.pm.tabs["right"]), 1)
        self._do("switch_pane")
        self._do("next_tab")
        self.assertIn("one tab", self._last_log())

    def test_next_and_previous_wrap(self):
        self._do("new_tab")
        self._do("new_tab")
        self._do("next_tab")
        self.assertEqual(self.app.pm.tab_index["left"], 0)
        self._do("prev_tab")
        self.assertEqual(self.app.pm.tab_index["left"], 2)

    def test_a_virtual_tab_is_kept_as_it_was(self):
        target = os.path.join(self.tmp, "b", "three.txt")
        self.app.panel.set_clipboard(target)
        self._do("open_list_from_clipboard")
        listed = self.app.active_pane()
        self.assertEqual(listed["virtual"]["kind"], "list")
        self._do("new_tab")
        self.assertIsNone(self.app.active_pane()["virtual"])
        self._do("prev_tab")
        self.assertIs(self.app.active_pane(), listed)
        self.assertEqual([str(f) for f in listed["files"]], [target])


class HiddenTabs(_Base):

    def test_a_listing_never_lands_on_the_other_tab(self):
        a_tab = self.app.active_pane()
        self._do("new_tab")
        b_tab = self.app.active_pane()
        self.app._go_to_dir(b_tab, Path(os.path.join(self.tmp, "b")), None)
        # Switch before the listing is installed: it must not end up on a_tab.
        self.app.pm.select_tab("left", 0)
        self.app._show_tab("left")
        self.app._settle_listings()
        self.assertEqual(self._names(a_tab), ["inner", "one.txt", "two.txt"])
        self.app.pm.select_tab("left", 1)
        self.app._show_tab("left")
        self.app._settle_listings()
        self.assertEqual(self._names(b_tab), ["three.txt"])

    def test_a_hidden_directory_tab_is_reread_on_the_way_in(self):
        self._do("new_tab")
        self._do("prev_tab")
        with open(os.path.join(self.tmp, "a", "new.txt"), "w") as fh:
            fh.write("x")
        self._do("next_tab")
        self.assertIn("new.txt", self._names())

    def test_a_relist_of_a_hidden_tab_waits_for_it(self):
        hidden = self.app.active_pane()
        self._do("new_tab")
        self.app._relist(hidden)
        self.assertTrue(hidden.get("_stale"))
        self.assertIsNot(self.app.active_pane(), hidden)

    def test_the_side_of_a_hidden_tab(self):
        hidden = self.app.active_pane()
        self._do("new_tab")
        self.assertEqual(self.app._pane_name_of(hidden), "left")
        self.assertFalse(self.app.pm.is_shown(hidden))


class Strip(_Base):

    def _draw(self):
        panel = self.app.panel
        panel.render()
        return "\n".join(self.b.snapshot())

    def test_no_strip_with_one_tab(self):
        header = self.app._headers["left"]
        self._draw()
        self.assertIsNone(header._strip.row)

    def test_the_strip_names_every_tab(self):
        self._focus("inner")
        self._do("open_in_new_tab")
        screen = self._draw()
        self.assertIn(" a ", screen)
        self.assertIn(" inner ", screen)
        strip = self.app._headers["left"]._strip
        self.assertEqual(len(strip.hits), 3)  # two tabs and the + after them
        self.assertEqual(len(strip.close_hits), 2)
        self.assertNotIn("×", screen)  # shown only under the pointer
        self.assertIn("+", screen)

    def test_a_click_on_a_tab_shows_it(self):
        self._do("new_tab")
        self._draw()
        header = self.app._headers["left"]
        x0, x1, index = header._strip.hits[0]
        from puikit import Event, EventType
        y = header._strip.row[0]
        header.handle_event(Event(type=EventType.MOUSE_CLICK, x=(x0 + x1) / 2,
                                  y=y, button="left"))
        self.app._settle_listings()
        self.assertEqual(self.app.pm.tab_index["left"], 0)

    def _click(self, x, y):
        from puikit import Event, EventType
        header = self.app._headers["left"]
        header.handle_event(Event(type=EventType.MOUSE_CLICK, x=x, y=y, button="left"))
        self.app._settle_listings()

    def test_a_click_on_a_tabs_close_button_closes_it(self):
        self._do("new_tab")
        self._do("new_tab")
        self.assertEqual(self.app.pm.tab_index["left"], 2)
        self._draw()
        strip = self.app._headers["left"]._strip
        x0, x1, index = strip.close_hits[0]  # a tab out of view
        self._click(x1 - 0.5, strip.row[0])
        self.assertEqual(len(self.app.pm.tabs["left"]), 2)
        self.assertEqual(self.app.pm.tab_index["left"], 1)  # still the same tab
        self._draw()
        x0, x1, index = strip.close_hits[1]  # the current one
        self._click(x1 - 0.5, strip.row[0])
        self.assertEqual(len(self.app.pm.tabs["left"]), 1)

    def test_a_tab_dragged_along_the_strip_moves(self):
        from puikit import Event, EventType
        self._do("new_tab")
        self._do("new_tab")
        self._draw()
        header = self.app._headers["left"]
        strip = header._strip
        first = self.app.pm.tabs["left"][0]
        y = strip.row[0]
        x0, x1, _ = strip.hits[0]
        lx0, lx1, _ = strip.hits[2]

        def send(kind, x):
            header.handle_event(Event(type=kind, x=x, y=y, button="left"))
        send(EventType.MOUSE_DOWN, (x0 + x1) / 2)
        send(EventType.MOUSE_DRAG, lx1 - 0.5)
        self.assertIs(self.app.pm.tabs["left"][0], first)  # only a line, so far
        self.assertEqual(strip.drop_slot, 3)
        send(EventType.MOUSE_UP, lx1 - 0.5)
        send(EventType.MOUSE_CLICK, lx1 - 0.5)  # ends the drag, shows nothing
        self.assertIs(self.app.pm.tabs["left"][2], first)
        self.assertEqual(self.app.pm.tab_index["left"], 1)  # the current tab, moved up one
        self._do("move_tab_left")
        self.assertEqual(self.app.pm.tab_index["left"], 0)

    def test_a_click_on_plus_opens_a_tab(self):
        self._do("new_tab")
        self._draw()
        strip = self.app._headers["left"]._strip
        x0, x1, index = strip.hits[-1]
        self._click((x0 + x1) / 2, strip.row[0])
        self.assertEqual(len(self.app.pm.tabs["left"]), 3)

    def test_labels(self):
        pane = {"path": Path("/"), "virtual": None}
        self.assertEqual(xefm_app._tab_label(pane), str(Path("/")))
        pane = {"path": Path(self.tmp), "virtual": {"kind": "search", "query": "TODO"}}
        self.assertEqual(xefm_app._tab_label(pane), "⌕ TODO")
        self.assertEqual(xefm_app._tab_parts(pane), ("⌕", "TODO"))  # the icon says it


class Persistence(_Base):

    def test_tabs_come_back_unread_except_the_current_one(self):
        self._do("new_tab")
        self.app._go_to_dir(self.app.active_pane(), Path(os.path.join(self.tmp, "b")), None)
        self.app._settle_listings()
        self._do("new_tab")
        self.app.pm.select_tab("left", 1)
        self.app._show_tab("left")
        self.app._settle_listings()
        self.app._save_application_state()
        self.app.file_monitor.stop_monitoring()
        self.b.close()

        self.app = self._open(os.path.join(self.tmp, "a"), provided=False)
        tabs = self.app.pm.tabs["left"]
        self.assertEqual([t["path"].name for t in tabs], ["a", "b", "b"])
        self.assertEqual(self.app.pm.tab_index["left"], 1)
        self.assertEqual(self._names(), ["three.txt"])
        # The others have not been read yet.
        self.assertEqual(tabs[0]["files"], [])
        self._do("prev_tab")
        self.assertEqual(self._names(), ["inner", "one.txt", "two.txt"])

    def test_a_directory_on_the_command_line_opens_alone(self):
        self._do("new_tab")
        self.app._save_application_state()
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        self.app = self._open(os.path.join(self.tmp, "b"), provided=True)
        self.assertEqual(len(self.app.pm.tabs["left"]), 1)


if __name__ == "__main__":
    unittest.main()
