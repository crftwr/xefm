"""
Cursor jumps to the first / last item (#352).

``cursor_top`` (Ctrl-Home) and ``cursor_bottom`` (Ctrl-End) land the cursor on
the ends of the active pane's listing, so a long directory does not have to be
paged through. Home / End keep their long-standing filer meaning (select all /
clear the selection), which is why the two defaults carry Ctrl.

Run with: python -m pytest test/test_cursor_top_bottom.py -v
"""

import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.actions import FILER, registry  # noqa: E402
from xefm.config import KeyBindings  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class CursorTopBottom(unittest.TestCase):
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
        self.assertEqual([f.name for f in self.pane["files"]], self.NAMES)

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _focused_name(self):
        return self.pane["files"][self.pane["focused_index"]].name

    def test_top_goes_to_the_first_item(self):
        self.pane["focused_index"] = 3
        self.app.dispatch("cursor_top")
        self.assertEqual(self._focused_name(), "a.txt")

    def test_bottom_goes_to_the_last_item(self):
        self.pane["focused_index"] = 1
        self.app.dispatch("cursor_bottom")
        self.assertEqual(self._focused_name(), "e.txt")

    def test_either_end_is_idempotent(self):
        self.app.dispatch("cursor_top")
        self.app.dispatch("cursor_top")
        self.assertEqual(self.pane["focused_index"], 0)
        self.app.dispatch("cursor_bottom")
        self.app.dispatch("cursor_bottom")
        self.assertEqual(self.pane["focused_index"], len(self.NAMES) - 1)

    def test_empty_pane_stays_at_zero(self):
        """An empty listing has no last row; the index must not go negative."""
        self.pane["files"] = []
        self.pane["focused_index"] = 0
        self.app.dispatch("cursor_bottom")
        self.assertEqual(self.pane["focused_index"], 0)
        self.app.dispatch("cursor_top")
        self.assertEqual(self.pane["focused_index"], 0)

    def test_registered_with_default_keys(self):
        """Registered in the filer context, and bound out of the box — a config
        written before this release never mentions them, so the defaults are
        what every existing install gets."""
        for name, key in (("cursor_top", "Ctrl-HOME"),
                          ("cursor_bottom", "Ctrl-END")):
            with self.subTest(name=name):
                self.assertIsNotNone(registry.resolve(FILER, name))
                keys, _selection = KeyBindings({})._context_binding(FILER, name)
                self.assertEqual(list(keys), [key])


if __name__ == "__main__":
    unittest.main()
