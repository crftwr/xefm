"""The context menus from the keyboard: '/' (and the Menu key) for the item
under the cursor, '?' (and Shift + the Menu key) for the directory — cfiler's
pair — plus a right-click below the last row, which is on the directory.

Run with: python -m pytest test/test_context_menu_keys.py -v
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from xefm import app as xefm_app
from xefm import favorites
from xefm.input_dialog import InputDialog
from xefm.state_manager import XeFMStateManager


def _labels(menu):
    return [getattr(i, "label", None) for i in menu.items]


def _item(menu, label):
    return next(i for i in menu.items if getattr(i, "label", None) == label)


class ContextMenuKeysTest(unittest.TestCase):
    def setUp(self):
        from puikit.backends import create_backend
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        for name in ("a.txt", "b.txt", "c.txt"):
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write("x")
        os.mkdir(os.path.join(self.tmp, "empty"))
        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        for target, value in (("get_state_manager", lambda: self.sm),
                              ("get_favorite_directories", lambda: [])):
            patcher = patch.object(favorites, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.app.panel.render()  # lays the panes out, so anchors are real
        self.shown = []
        patcher = patch.object(self.app.panel, "popup_menu",
                               lambda menu, x, y: self.shown.append((menu, x, y)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def test_the_item_menu_opens_under_the_cursor_row(self):
        pane = self.app.active_pane()
        pane["focused_index"] = 0
        self.app.context_menu()
        pane["focused_index"] = 2
        self.app.context_menu()
        (menu0, _x0, y0), (menu2, _x2, y2) = self.shown
        self.assertIn("Rename…", _labels(menu0))
        self.assertAlmostEqual(y2 - y0, 2.0)

    def test_the_directory_menu_is_its_own(self):
        self.app.context_menu_dir()
        menu, _x, _y = self.shown[0]
        labels = _labels(menu)
        self.assertIn("New Directory…", labels)
        self.assertNotIn("Rename…", labels)

    def test_the_directory_menu_hangs_from_the_path_bar(self):
        """Not from the first row: opened there it read as that file's menu."""
        pane = self.app.active_pane()
        pane["focused_index"] = 0
        self.app.context_menu()
        self.app.context_menu_dir()
        (_m, _x, row_y), (_d, _dx, dir_y) = self.shown
        header = self.app._headers[self.app.pm.active_pane]
        hx, hy, _hw, hh = header._abs
        self.assertEqual(dir_y, hy + hh)
        self.assertLess(dir_y, row_y)

    def test_an_empty_pane_gets_the_directory_menu(self):
        pane = self.app.active_pane()
        self.app._go_to_dir(pane, xefm_app.Path(os.path.join(self.tmp, "empty")), None)
        self.app._settle_listings()
        self.app.context_menu()
        self.assertIn("New Directory…", _labels(self.shown[0][0]))

    def test_a_right_click_shows_the_cursor_on_the_row_before_the_menu(self):
        """A native menu holds the UI thread until it closes, so the frame with
        the cursor on the clicked row has to be rendered before it opens."""
        pane = self.app.active_pane()
        pane["focused_index"] = 0
        order = []
        real_render = self.app.panel.render

        def render():
            order.append(("render", pane["focused_index"]))
            real_render()

        with patch.object(self.app.panel, "render", render), \
                patch.object(self.app.panel, "popup_menu",
                             lambda menu, x, y: order.append(("popup", None))):
            self.app._show_context_menu(self.app.pm.active_pane, 2, 3.0, 4.0)
        self.assertEqual(order[:2], [("render", 2), ("popup", None)])

    def test_select_from_the_menu_leaves_the_cursor_on_the_row(self):
        """SPACE toggles and moves down; the menu names one row and stays on it."""
        pane = self.app.active_pane()
        self.app._show_context_menu(self.app.pm.active_pane, 1, 0.0, 0.0)
        _item(self.shown[0][0], "Select").activate()
        entry = pane["files"][1]
        self.assertEqual(pane["focused_index"], 1)
        self.assertIn(str(entry), pane["selected_files"])
        self.app._show_context_menu(self.app.pm.active_pane, 1, 0.0, 0.0)
        _item(self.shown[1][0], "Deselect").activate()
        self.assertEqual(pane["focused_index"], 1)
        self.assertNotIn(str(entry), pane["selected_files"])

    def test_a_right_click_below_the_rows_gets_the_directory_menu(self):
        self.app._show_context_menu(self.app.pm.active_pane, -1, 3.0, 9.0)
        menu, x, y = self.shown[0]
        self.assertIn("New Directory…", _labels(menu))
        self.assertEqual((x, y), (3.0, 9.0))

    def test_the_directory_menu_adds_the_directory_to_favorites(self):
        pane = self.app.active_pane()
        pane["focused_index"] = 1  # a file under the cursor must not matter
        self.app.context_menu_dir()
        _item(self.shown[0][0], "Add to Favorites…").activate()
        dialog = self.app.panel._layers[-1].widget
        self.assertIsInstance(dialog, InputDialog)
        dialog._accept()
        self.assertEqual([(e.path, e.is_file) for e in favorites.get_favorites()],
                         [(self.tmp, False)])

    def test_a_results_pane_disables_the_directory_items(self):
        pane = self.app.active_pane()
        pane["virtual"] = {"kind": "list", "title": "x", "results": [], "root": None}
        self.app.context_menu_dir()
        menu = self.shown[0][0]
        self.assertFalse(_item(menu, "New Directory…").is_enabled())
        self.assertFalse(_item(menu, "Add to Favorites…").is_enabled())
        self.assertTrue(_item(menu, "Sort…").is_enabled())


if __name__ == "__main__":
    unittest.main()
