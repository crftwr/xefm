"""
Cursor jumps to the next / previous selected item (#265).

``cursor_next_selected`` (Ctrl-Down) and ``cursor_prev_selected`` (Ctrl-Up)
move the cursor to the nearest selected entry below / above the position, so a
scattered selection can be walked without arrowing through everything in
between. No wrap-around: at the last (first) selected item the cursor stays
put and the log says why.

Run with: python -m pytest test/test_cursor_selection_jump.py -v
"""

import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class CursorSelectionJump(unittest.TestCase):
    NAMES = ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        for name in self.NAMES:
            open(os.path.join(self.tmp, name), "w").close()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app._settle_listings()
        self.pane = self.app.active_pane()
        # Pin a known name-sorted order; the temp state DB guarantees no
        # leftover per-directory sort settings interfere.
        self.assertEqual([f.name for f in self.pane["files"]], self.NAMES)

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _select(self, *names):
        self.pane["selected_files"] = {str(f) for f in self.pane["files"]
                                       if f.name in names}

    def _focused_name(self):
        return self.pane["files"][self.pane["focused_index"]].name

    def test_next_walks_down_the_selection(self):
        self._select("b.txt", "d.txt")
        self.pane["focused_index"] = 0
        self.app.dispatch("cursor_next_selected")
        self.assertEqual(self._focused_name(), "b.txt")
        self.app.dispatch("cursor_next_selected")
        self.assertEqual(self._focused_name(), "d.txt")

    def test_next_stops_at_last_selected(self):
        self._select("b.txt")
        self.pane["focused_index"] = 3
        self.app.dispatch("cursor_next_selected")
        self.assertEqual(self._focused_name(), "d.txt")  # unchanged

    def test_prev_walks_up_the_selection(self):
        self._select("b.txt", "d.txt")
        self.pane["focused_index"] = 4
        self.app.dispatch("cursor_prev_selected")
        self.assertEqual(self._focused_name(), "d.txt")
        self.app.dispatch("cursor_prev_selected")
        self.assertEqual(self._focused_name(), "b.txt")
        self.app.dispatch("cursor_prev_selected")
        self.assertEqual(self._focused_name(), "b.txt")  # no wrap

    def test_empty_selection_leaves_cursor_put(self):
        self.pane["focused_index"] = 2
        self.app.dispatch("cursor_next_selected")
        self.assertEqual(self._focused_name(), "c.txt")
        self.app.dispatch("cursor_prev_selected")
        self.assertEqual(self._focused_name(), "c.txt")

    def test_current_row_selected_still_jumps_to_neighbor(self):
        self._select("b.txt", "c.txt", "d.txt")
        self.pane["focused_index"] = 2
        self.app.dispatch("cursor_next_selected")
        self.assertEqual(self._focused_name(), "d.txt")
        self.app.dispatch("cursor_prev_selected")
        self.assertEqual(self._focused_name(), "c.txt")

    def test_default_bindings_exist(self):
        from xefm._config import Config
        self.assertEqual(Config.KEY_BINDINGS["cursor_next_selected"], ["Ctrl-DOWN"])
        self.assertEqual(Config.KEY_BINDINGS["cursor_prev_selected"], ["Ctrl-UP"])


if __name__ == "__main__":
    unittest.main()
