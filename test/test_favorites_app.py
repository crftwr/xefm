"""Adding a favorite from the file list (B), and jumping to a file favorite.

Drives the real app on the memory backend: ``add_favorite`` offers the pane's
directory and the item under the cursor, the name prompt saves the choice to
the state DB, and a favorite that names a file lands the cursor on it.

Run with: python -m pytest test/test_favorites_app.py -v
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from xefm import app as xefm_app
from xefm import favorites
from xefm.choice_dialog import ChoiceDialog
from xefm.input_dialog import InputDialog
from xefm.state_manager import XeFMStateManager


class AddFavoriteTest(unittest.TestCase):
    def setUp(self):
        from puikit.backends import create_backend
        # realpath: on macOS the app lands on /private/var..., and these tests
        # compare paths against it (#505).
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        os.mkdir(os.path.join(self.tmp, "sub"))
        with open(os.path.join(self.tmp, "notes.txt"), "w") as f:
            f.write("x")
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

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def top(self):
        return self.app.panel._layers[-1].widget

    def focus(self, name):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(name)

    def choose(self, index):
        dialog = self.top()
        self.assertIsInstance(dialog, ChoiceDialog)
        dialog._index = index
        dialog._accept()

    def name_it(self, text=None):
        dialog = self.top()
        self.assertIsInstance(dialog, InputDialog)
        if text is not None:
            dialog.edit.text = text
        dialog._accept()

    def saved(self):
        return [(e.name, e.path, e.is_file) for e in favorites.get_favorites()]

    def test_enter_adds_the_current_directory(self):
        self.focus("notes.txt")
        self.app.add_favorite()
        self.choose(0)
        self.name_it("Here")
        self.assertEqual(self.saved(), [("Here", self.tmp, False)])

    def test_the_cursor_item_can_be_a_file(self):
        self.focus("notes.txt")
        self.app.add_favorite()
        self.choose(1)
        self.name_it()  # the default name is the file's own
        self.assertEqual(self.saved(),
                         [("notes.txt", os.path.join(self.tmp, "notes.txt"), True)])

    def test_a_directory_under_the_cursor_is_not_a_file(self):
        self.focus("sub")
        self.app.add_favorite()
        self.choose(1)
        self.name_it()
        self.assertEqual(self.saved(), [("sub", os.path.join(self.tmp, "sub"), False)])

    def test_an_empty_directory_skips_the_choice(self):
        empty = os.path.join(self.tmp, "sub")
        pane = self.app.active_pane()
        self.app._go_to_dir(pane, xefm_app.Path(empty), None)
        self.app._settle_listings()
        self.app.add_favorite()
        self.name_it()
        self.assertEqual(self.saved(), [("sub", empty, False)])

    def test_adding_again_opens_a_rename(self):
        favorites.add_favorite("Old", self.tmp)
        self.app.add_favorite()
        self.choose(0)
        dialog = self.top()
        self.assertEqual(dialog.edit.text, "Old")
        self.name_it("New")
        self.assertEqual(self.saved(), [("New", self.tmp, False)])

    def test_jumping_to_a_file_favorite_lands_on_the_file(self):
        target = os.path.join(self.tmp, "sub", "deep.txt")
        with open(target, "w") as f:
            f.write("x")
        pane = self.app.active_pane()
        self.app._jump_to_favorite(favorites.FavoriteEntry("Deep", target, is_file=True))
        self.app._settle_listings()
        self.assertEqual(str(pane["path"]), os.path.join(self.tmp, "sub"))
        self.assertEqual(pane["files"][pane["focused_index"]].name, "deep.txt")

    def test_the_context_menu_adds_the_clicked_row(self):
        """A right-click names its row, so there is no directory-or-row choice:
        the menu item goes straight to the name prompt for that row."""
        pane = self.app.active_pane()
        index = [f.name for f in pane["files"]].index("notes.txt")
        shown = []
        with patch.object(self.app.panel, "popup_menu",
                          lambda menu, x, y: shown.append(menu)):
            self.app._show_context_menu(self.app.pm.active_pane, index, 0, 0)
        item = next(i for i in shown[0].items
                    if getattr(i, "label", "") == "Add to Favorites…")
        item.activate()
        self.name_it()
        self.assertEqual(self.saved(),
                         [("notes.txt", os.path.join(self.tmp, "notes.txt"), True)])

    def test_the_picker_forgets_an_added_favorite(self):
        favorites.add_favorite("Here", self.tmp)
        entry = favorites.get_favorites()[0]
        self.assertTrue(self.app._forget_favorite(entry))
        self.assertEqual(self.saved(), [])


if __name__ == "__main__":
    unittest.main()
