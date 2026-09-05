"""App-integration tests for the sort dialog (issue #237): drives the real
dialog through a MemoryBackend + XeFMApp so the handler wiring (S opens it,
seeded from the pane; Enter/hotkeys apply mode + order and re-sort the listing;
Esc leaves the pane untouched) and the keyboard model are covered."""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.sort_dialog import SortDialog  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402


def _key(k, mods=frozenset()):
    return Event(EventType.KEY, key=k, modifiers=frozenset(mods))


def _write(d, rel, data=b"x", mtime=None):
    p = os.path.join(d, rel)
    with open(p, "wb") as f:
        f.write(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


class SortDialogApp(unittest.TestCase):
    def setUp(self):
        self.left = tempfile.mkdtemp()
        self.right = tempfile.mkdtemp()
        # Names, extensions, sizes and mtimes each order these three differently,
        # so every sort key's effect (and its reverse) is distinguishable:
        #   name:  alpha.md < mid.txt < zeta.c
        #   ext:   zeta.c < alpha.md < mid.txt
        #   size:  mid.txt(1) < zeta.c(2) < alpha.md(3)
        #   date:  zeta.c(1000) < alpha.md(2000) < mid.txt(3000)
        _write(self.left, "alpha.md", b"xxx", mtime=2000.0)
        _write(self.left, "zeta.c", b"xx", mtime=1000.0)
        _write(self.left, "mid.txt", b"x", mtime=3000.0)

        self.state_dir = tempfile.mkdtemp()
        # Temp state DB, never the real ~/.xefm/state.db: the app restores each
        # pane's sort mode and direction from it, so the developer's own
        # last-used settings would otherwise decide these panes' row order.
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
        pane = self.app.active_pane()
        pane["sort_mode"] = "filename"
        pane["sort_reverse"] = False
        self.app._resort(pane)
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
        self.app.show_sort_menu()
        dlg = self.app.panel._layers[-1].widget
        self.assertIsInstance(dlg, SortDialog)
        return dlg

    def _dialog_open(self):
        layers = self.app.panel._layers
        return bool(layers) and isinstance(layers[-1].widget, SortDialog)

    def _names(self):
        # A sort change lands on a worker now, so read the order only once it has.
        self.app._settle_listings()
        return [os.path.basename(str(p)) for p in self.app.active_pane()["files"]]

    # --- draw / layout -------------------------------------------------------

    def test_dialog_draws_keys_orders_and_explanation(self):
        self._open()
        self.app.panel.render()
        screen = "\n".join(self.b.snapshot())
        for token in ("Sort By", "Filename", "Extension", "Size", "Timestamp",
                      "Ascending", "Descending", "A to Z"):
            self.assertIn(token, screen, f"missing {token!r}")
        for gone in ("(F)", "(E)", "(S)", "(T)", "Order ", "Example:"):
            self.assertNotIn(gone, screen, f"stray {gone!r}")

    def test_explanation_follows_key_and_order(self):
        dlg = self._open()
        self.assertIn("A to Z", dlg.explanation())      # name, ascending
        dlg.handle_event(_key("right"))
        self.assertIn("Z to A", dlg.explanation())      # name, descending
        dlg.handle_event(_key("down"))
        dlg.handle_event(_key("down"))                  # -> Size
        self.assertIn("largest first", dlg.explanation())
        dlg.handle_event(_key("left"))
        self.assertIn("smallest first", dlg.explanation())
        dlg.handle_event(_key("down"))                  # -> Timestamp
        self.assertIn("oldest first", dlg.explanation())
        self.app.panel.render()
        screen = "\n".join(self.b.snapshot())
        self.assertIn("oldest first", screen)           # the explanation is on screen

    def test_gui_rows_get_more_pitch_than_grid(self):
        dlg = SortDialog()
        grid, gui = dlg._row_pitch(False), dlg._row_pitch(True)
        self.assertEqual(grid, 1.0)                     # whole rows on a grid
        self.assertGreater(gui, grid)                   # extra air on vector
        self.assertGreater(dlg._box_height(3.0, gui), dlg._box_height(3.0, grid))

    # --- seeding -------------------------------------------------------------

    def test_seeded_from_pane(self):
        pane = self.app.active_pane()
        pane["sort_mode"] = "timestamp"
        pane["sort_reverse"] = True
        dlg = self._open()
        self.assertEqual(dlg._index, 3)                 # Timestamp row
        self.assertTrue(dlg._reverse)

    def test_legacy_type_mode_seeds_as_extension(self):
        pane = self.app.active_pane()
        pane["sort_mode"] = "type"                      # pre-dialog menu value
        dlg = self._open()
        self.assertEqual(dlg._index, 1)                 # Extension row

    # --- keyboard model ------------------------------------------------------

    def test_up_down_choose_key_with_wrap(self):
        dlg = self._open()
        self.assertEqual(dlg._index, 0)
        dlg.handle_event(_key("up"))                    # wraps to the bottom
        self.assertEqual(dlg._index, 3)
        dlg.handle_event(_key("down"))
        self.assertEqual(dlg._index, 0)
        dlg.handle_event(_key("down"))
        self.assertEqual(dlg._index, 1)

    def test_left_right_choose_order(self):
        dlg = self._open()
        self.assertFalse(dlg._reverse)
        dlg.handle_event(_key("right"))
        self.assertTrue(dlg._reverse)
        dlg.handle_event(_key("right"))                 # absolute, not a toggle
        self.assertTrue(dlg._reverse)
        dlg.handle_event(_key("left"))
        self.assertFalse(dlg._reverse)

    def test_enter_applies_key_and_order(self):
        dlg = self._open()
        dlg.handle_event(_key("down"))                  # -> Extension
        dlg.handle_event(_key("right"))                 # -> Descending
        dlg.handle_event(_key("enter"))
        self.assertFalse(self._dialog_open())
        pane = self.app.active_pane()
        self.assertEqual(pane["sort_mode"], "extension")
        self.assertTrue(pane["sort_reverse"])
        self.assertEqual(self._names(), ["mid.txt", "alpha.md", "zeta.c"])

    def test_escape_leaves_pane_untouched(self):
        dlg = self._open()
        dlg.handle_event(_key("down"))
        dlg.handle_event(_key("right"))
        dlg.handle_event(_key("escape"))
        self.assertFalse(self._dialog_open())
        pane = self.app.active_pane()
        self.assertEqual(pane["sort_mode"], "filename")
        self.assertFalse(pane["sort_reverse"])
        self.assertEqual(self._names(), ["alpha.md", "mid.txt", "zeta.c"])

    # --- hotkeys -------------------------------------------------------------

    def test_hotkey_applies_and_closes_immediately(self):
        dlg = self._open()
        dlg.handle_event(_key("t"))                     # Timestamp
        self.assertFalse(self._dialog_open())
        pane = self.app.active_pane()
        self.assertEqual(pane["sort_mode"], "timestamp")
        self.assertFalse(pane["sort_reverse"])          # order kept
        self.assertEqual(self._names(), ["zeta.c", "alpha.md", "mid.txt"])
        self.app.panel.render()                         # footer speaks the same name
        self.assertIn("Timestamp ↑", "\n".join(self.b.snapshot()))

    def test_hotkey_keeps_chosen_order(self):
        dlg = self._open()
        dlg.handle_event(_key("right"))                 # Descending first…
        dlg.handle_event(_key("s"))                     # …then Size applies both
        self.assertFalse(self._dialog_open())
        pane = self.app.active_pane()
        self.assertEqual(pane["sort_mode"], "size")
        self.assertTrue(pane["sort_reverse"])
        self.assertEqual(self._names(), ["alpha.md", "zeta.c", "mid.txt"])

    def test_each_hotkey_maps_to_its_key(self):
        for hotkey, mode in (("f", "filename"), ("e", "extension"),
                             ("s", "size"), ("t", "timestamp")):
            dlg = self._open()
            dlg.handle_event(_key(hotkey))
            self.assertFalse(self._dialog_open())
            self.assertEqual(self.app.active_pane()["sort_mode"], mode, hotkey)

    def test_modified_letter_is_not_a_hotkey(self):
        dlg = self._open()
        dlg.handle_event(_key("t", {"ctrl"}))
        self.assertTrue(self._dialog_open())            # still open, nothing applied
        self.assertEqual(self.app.active_pane()["sort_mode"], "filename")
        dlg.handle_event(_key("escape"))

    # --- mouse ---------------------------------------------------------------

    def test_click_on_key_row_applies(self):
        dlg = self._open()
        self.app.panel.render()                         # populate the hit rects
        i, y0, y1 = dlg._row_hits[2]                    # the Size row
        dlg.handle_event(Event(EventType.MOUSE_CLICK, x=4.0, y=(y0 + y1) / 2.0))
        self.assertFalse(self._dialog_open())
        self.assertEqual(self.app.active_pane()["sort_mode"], "size")

    def test_click_on_order_segment_switches_order_only(self):
        dlg = self._open()
        self.app.panel.render()
        x0, x1, y0, y1, rev = dlg._order_hits[1]        # the Descending segment
        self.assertTrue(rev)
        dlg.handle_event(Event(EventType.MOUSE_CLICK,
                               x=(x0 + x1) / 2.0, y=(y0 + y1) / 2.0))
        self.assertTrue(self._dialog_open())            # stays open
        self.assertTrue(dlg._reverse)
        dlg.handle_event(_key("escape"))

    def test_click_outside_cancels(self):
        dlg = self._open()
        self.app.panel.render()
        dlg.handle_event(Event(EventType.MOUSE_CLICK, x=-1.0, y=-1.0))
        self.assertFalse(self._dialog_open())
        self.assertEqual(self.app.active_pane()["sort_mode"], "filename")


if __name__ == "__main__":
    unittest.main()
