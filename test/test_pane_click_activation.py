"""Clicking a pane makes it the active one — with or without a row under the
pointer (issue #371).

Two levels: the FilePane's own hit test, which now answers ``-1`` for "no row
here" the way the drop path always has, and the controller, where that ``-1``
means "activate, leave the cursor alone". The app-level test drives a real
click through the rendered layout, so it also covers the geometry — the empty
space under a short listing belongs to the pane widget.

Run with: python -m pytest test/test_pane_click_activation.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.file_pane import FilePane  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402


def _pane(files):
    """A minimal pane-data dict the FilePane reads for pointer routing."""
    return {
        "files": list(files),
        "file_info": {},
        "selected_files": set(),
        "path": Path("/tmp"),
        "focused_index": 0,
        "scroll_offset": 0,
    }


class _F:
    """A file entry the pane renders — only ``.name`` / ``str()`` are read here."""

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return "/a/" + self.name


def _click(view, y, button="left"):
    return view.handle_event(
        Event(type=EventType.MOUSE_CLICK, x=1.0, y=y, button=button))


class FilePaneClick(unittest.TestCase):
    def _widget(self, files, **cb):
        view = FilePane(_pane(files), **cb)
        view._margin_y = 0.0  # no inset: row index == floor(y)
        return view

    def test_a_click_on_a_row_reports_it(self):
        seen = []
        view = self._widget([_F("one"), _F("two")], on_click=seen.append)
        self.assertTrue(_click(view, 1.0))
        self.assertEqual(seen, [1])

    def test_a_click_below_the_rows_reports_no_row(self):
        seen = []
        view = self._widget([_F("one")], on_click=seen.append)
        self.assertTrue(_click(view, 9.0))
        self.assertEqual(seen, [-1])

    def test_a_click_in_an_empty_pane_reports_no_row(self):
        seen = []
        view = self._widget([], on_click=seen.append)
        self.assertTrue(_click(view, 0.0))
        self.assertEqual(seen, [-1])

    def test_the_scroll_offset_still_counts(self):
        seen = []
        view = self._widget([_F(str(i)) for i in range(20)], on_click=seen.append)
        view.offset = 5.0
        _click(view, 2.0)
        self.assertEqual(seen, [7])

    def test_a_right_click_below_the_rows_opens_no_menu(self):
        """The context menu is a menu *for an item*; there is no item here."""
        seen = []
        view = self._widget([_F("one")],
                            on_context=lambda i, x, y: seen.append(i))
        _click(view, 9.0, button="right")
        self.assertEqual(seen, [])


class AppPaneActivation(unittest.TestCase):
    """A click through the live layout, on the memory backend."""

    def setUp(self):
        self.left = tempfile.mkdtemp()
        self.right = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        for name in ("a.txt", "b.txt", "c.txt"):
            open(os.path.join(self.left, name), "w").close()
            open(os.path.join(self.right, name), "w").close()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.left, self.right,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.app.panel.render()          # lays the panes out (captures _abs)
        self.assertEqual(self.app.pm.active_pane, "left")

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        for d in (self.left, self.right, self.state_dir):
            shutil.rmtree(d, ignore_errors=True)

    def _click_row(self, view, row):
        """Click ``row`` of a laid-out pane in screen coordinates (``row`` may
        be past the end of the listing — that is the point)."""
        x, y, w, h = view._abs
        cy = y + view._margin_y + row + 0.5
        self.assertLess(cy, y + h, "click fell outside the pane")
        self.app.panel.dispatch_event(
            Event(type=EventType.MOUSE_CLICK, x=x + 1.0, y=cy, button="left"))

    def test_clicking_empty_space_activates_the_pane(self):
        pane = self.app.pane("right")
        pane["focused_index"] = 2
        self._click_row(self.app.right_view, len(pane["files"]) + 1)
        self.assertEqual(self.app.pm.active_pane, "right")
        self.assertTrue(self.app.right_view.active)
        self.assertFalse(self.app.left_view.active)
        self.assertEqual(pane["focused_index"], 2)   # cursor left alone

    def test_clicking_a_row_still_moves_the_cursor(self):
        self._click_row(self.app.right_view, 1)
        self.assertEqual(self.app.pm.active_pane, "right")
        self.assertEqual(self.app.pane("right")["focused_index"], 1)

    def test_clicking_empty_space_in_an_empty_directory_activates_it(self):
        """The reason this matters: an empty pane has no row to click at all."""
        empty = tempfile.mkdtemp()
        try:
            self.app.pane("right")["path"] = Path(empty)
            self.app._list_pane("right")
            self.app._settle_listings()
            self.app.panel.render()
            self.assertEqual(self.app.pane("right")["files"], [])
            self._click_row(self.app.right_view, 0)
            self.assertEqual(self.app.pm.active_pane, "right")
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
