"""Regression for #253: activating the app-menu "Copy Name(s)" / "Copy Full
Path(s)" items must put the "Copied ..." log line ON SCREEN, not just in the
log buffer.

A native macOS menu fires an item's callback straight from AppKit — nothing
renders afterward unless the callback renders. These two items' only feedback
is a log line, so before the fix the line sat unpainted until the next event
(the reported "I don't see the log output until I hit another key"). Routing
them through XeFMApp._menu makes any activation dispatch AND render.

Run with: python -m pytest test/test_menu_copy_log_render.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit.backends import create_backend  # noqa: E402
from puikit.menu import Menu, MenuItem  # noqa: E402

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


def _find_item(menu: Menu, label: str) -> MenuItem:
    for entry in menu.items:
        if isinstance(entry, MenuItem):
            if entry.label == label:
                return entry
            if entry.submenu is not None:
                found = _find_item(entry.submenu, label)
                if found is not None:
                    return found
    return None


class MenuCopyRendersLog(unittest.TestCase):
    def setUp(self):
        self.left = tempfile.mkdtemp()
        self.right = tempfile.mkdtemp()
        with open(os.path.join(self.left, "hello.txt"), "w") as f:
            f.write("x")
        self.state_dir = tempfile.mkdtemp()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.left, self.right,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        # A restored theme may carry an arriving-text effect; the assertion
        # reads the first frame, so force text to land complete.
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

    def _activate(self, label: str) -> None:
        item = _find_item(self.app._build_menu(), label)
        self.assertIsNotNone(item, f"menu item {label!r} not found")
        # A native menu invokes on_select directly, with no render around it —
        # the item itself must leave the screen current.
        item.on_select()

    def test_copy_names_item_puts_log_line_on_screen(self):
        self._activate("Copy Name(s)")
        screen = "\n".join(self.b.snapshot())
        self.assertIn("Copied 1 name to clipboard", screen)

    def test_copy_paths_item_puts_log_line_on_screen(self):
        self._activate("Copy Full Path(s)")
        screen = "\n".join(self.b.snapshot())
        self.assertIn("Copied 1 path to clipboard", screen)


if __name__ == "__main__":
    unittest.main()
