"""Menu-bar keyboard activation and highlight lifecycle (issue #304).

Drives the real app through a MemoryBackend on the widget-menu (TUI) path,
covering the three reported problems: the menu could not be opened from the
keyboard at all (F10 / a bare Alt tap now open it), a bar title stayed
inverted after its pulldown was dismissed by an outside click (the bar took
focus it could never give back), and ←/→ did not walk between the bar's menus
while a pulldown was open.
"""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402


def _key(k, mods=frozenset()):
    return Event(EventType.KEY, key=k, modifiers=frozenset(mods))


class MenuBarActivation(unittest.TestCase):
    def setUp(self):
        self.left = tempfile.mkdtemp()
        self.right = tempfile.mkdtemp()
        open(os.path.join(self.left, "a.txt"), "w").close()
        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.left, self.right,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.panel.set_text_effect(False)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.app.panel.render()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
        except Exception:
            pass
        self.b.close()
        shutil.rmtree(self.left, ignore_errors=True)
        shutil.rmtree(self.right, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    # --- helpers -------------------------------------------------------------

    def _mouse(self, etype, x, y):
        self.app.on_event(Event(etype, x=x, y=y, button="left"))

    def _click(self, x, y):
        self._mouse(EventType.MOUSE_DOWN, x, y)
        self._mouse(EventType.MOUSE_UP, x, y)

    def _file_title_bgs(self):
        """Background colors under the "File" bar title (row 0)."""
        row = "".join(self.b._grid[0])
        i = row.find("File")
        self.assertGreaterEqual(i, 0, "File title not on the bar row")
        return {self.b.style_at(j, 0).bg for j in range(i, i + 4)}

    def _menu_open(self):
        return self.app.panel.has_layers

    # --- the reported problems ----------------------------------------------

    def test_startup_title_is_not_highlighted(self):
        # The bar used to be the panel's first focusable child, so [File]
        # rendered inverted from the very first frame.
        theme = self.app.panel.theme
        self.assertEqual(self._file_title_bgs(), {theme.popup_bg})

    def test_outside_click_dismiss_clears_the_highlight(self):
        # Issue #304: open [File] with the mouse, click a pane — the pulldown
        # closed but [File] stayed inverted as if still selected.
        theme = self.app.panel.theme
        fx = "".join(self.b._grid[0]).find("File") + 1
        self._click(fx, 0)
        self.assertTrue(self._menu_open())
        self.app.panel.render()
        self.assertEqual(self._file_title_bgs(), {theme.selection_bg})
        self._click(10, 5)  # a pane click dismisses the pulldown
        self.assertFalse(self._menu_open())
        self.app.panel.render()
        self.assertEqual(self._file_title_bgs(), {theme.popup_bg})
        # And the bar never took focus on the way.
        self.assertIsNot(self.app.panel.get_focused(), self.app.menu_bar)

    def test_f10_opens_walks_and_closes_the_menu(self):
        self.app.on_event(_key("f10"))
        self.assertTrue(self._menu_open())
        self.assertEqual(self.app.menu_bar._index, 0)
        self.app.on_event(_key("right"))   # walk to the next bar menu
        self.assertTrue(self._menu_open())
        self.assertEqual(self.app.menu_bar._index, 1)
        self.app.on_event(_key("left"))    # and back
        self.assertEqual(self.app.menu_bar._index, 0)
        self.app.on_event(_key("escape"))
        self.assertFalse(self._menu_open())
        self.assertFalse(self.app.menu_bar._open)

    def test_f10_toggles_the_open_menu_closed(self):
        self.app.on_event(_key("f10"))
        self.assertTrue(self._menu_open())
        self.app.on_event(_key("f10"))
        self.assertFalse(self._menu_open())

    def test_bare_alt_tap_opens_the_menu(self):
        # The Windows terminal delivers a bare Alt tap as the named key "alt"
        # (PuiKit keyboard contract §1); it is bound alongside F10.
        self.app.on_event(_key("alt"))
        self.assertTrue(self._menu_open())

    def test_arrows_after_mouse_open_walk_the_bar(self):
        # Issue #304's third point: after opening a menu with the mouse, ←/→
        # did nothing (← closed the pulldown outright).
        fx = "".join(self.b._grid[0]).find("File") + 1
        self._click(fx, 0)
        self.assertTrue(self._menu_open())
        self.app.on_event(_key("right"))
        self.assertTrue(self._menu_open())
        self.assertEqual(self.app.menu_bar._index, 1)

    # --- Alt+letter accelerators and item mnemonics ---------------------------

    def _bar_titles(self):
        return [item.label for item in self.app.menu_bar.menu.selectable]

    def test_alt_letter_opens_the_named_menu(self):
        # Alt+G opens Go directly (the bar titles' first letters are unique).
        self.assertEqual(self._bar_titles(),
                         ["File", "Go", "Select", "View", "Tools", "Help"])
        self.app.on_event(_key("g", mods={"alt"}))
        self.assertTrue(self._menu_open())
        self.assertEqual(self.app.menu_bar._index, 1)

    def test_alt_letter_without_match_does_nothing(self):
        self.app.on_event(_key("z", mods={"alt"}))
        self.assertFalse(self._menu_open())

    def test_alt_letter_switches_the_open_menu(self):
        self.app.on_event(_key("f10"))          # File open
        self.app.on_event(_key("v", mods={"alt"}))
        self.assertTrue(self._menu_open())
        self.assertEqual(self.app.menu_bar._index, 3)  # View

    def test_letter_activates_a_unique_item(self):
        # Go → "P" matches only "Parent Directory": it runs immediately and
        # the menu closes (the pane navigates to the parent directory).
        before = str(self.app.active_pane()["path"])
        self.app.on_event(_key("g", mods={"alt"}))
        self.app.on_event(_key("p"))
        self.assertFalse(self._menu_open())
        self.assertNotEqual(str(self.app.active_pane()["path"]), before)

    def test_letter_cycles_ambiguous_items(self):
        # File has several C… items: the letter only steps the highlight, so
        # nothing fires until Enter.
        self.app.on_event(_key("f10"))
        popup = self.app.panel._layers[-1].widget
        labels = [getattr(e, "label", None) for e in popup.menu.items]
        c_rows = [i for i, l in enumerate(labels)
                  if l and l.lower().startswith("c")]
        self.assertGreater(len(c_rows), 1)
        self.app.on_event(_key("c"))
        self.assertTrue(self._menu_open())      # nothing fired
        self.assertIn(popup.cursor, c_rows)
        first = popup.cursor
        self.app.on_event(_key("c"))
        self.assertTrue(self._menu_open())
        self.assertIn(popup.cursor, c_rows)
        self.assertNotEqual(popup.cursor, first)


if __name__ == "__main__":
    unittest.main()
