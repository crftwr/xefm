"""Unselected list rows in the modal dialogs inherit the popup surface.

A ListView draws its non-selected rows with ``bg=None``, trusting the host to
hand down the pane background; a dialog that forgets the ``draw_child``
``"bg"`` hint leaves those rows on the *terminal's default* colors on a grid
backend — dark bands cutting across the popup (the Favorites/Drives picker
regression). Each list-bearing dialog is rendered here on the MemoryBackend
(TUI profile) and an unselected row's cell background is checked against the
theme's popup surface.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit import Panel  # noqa: E402
from puikit.backends import create_backend  # noqa: E402

from xefm.batch_rename_dialog import show_batch_rename  # noqa: E402
from xefm.filter_list_dialog import show_filter_list  # noqa: E402
from xefm.progressive_search_dialog import show_progressive_search  # noqa: E402


class _Entry:  # the batch-rename dialog reads only .name off each file
    def __init__(self, name):
        self.name = name


class DialogRowsInheritPopupSurface(unittest.TestCase):
    def setUp(self):
        self.b = create_backend("memory")
        self.b.open()
        self.panel = Panel(self.b)

    def _row_bg(self, needle):
        """Background of the first cell of ``needle`` in the rendered grid."""
        for y, line in enumerate(self.b.snapshot()):
            x = line.find(needle)
            if x >= 0:
                return self.b._styles[y][x].bg
        self.fail(f"row {needle!r} not rendered")

    def _assert_row_on_popup(self, needle):
        self.panel.render()
        self.assertEqual(self._row_bg(needle), self.panel.theme.popup_bg)

    def test_filter_list_dialog(self):
        show_filter_list(self.panel, ["alpha", "beta"], title="Pick")
        self._assert_row_on_popup("beta")  # row 1: not the selected row

    def test_progressive_search_dialog(self):
        dlg = show_progressive_search(
            self.panel,
            search_iter=lambda mode, q, cancel: iter(()),
            to_label=lambda mode, v: str(v),
        )
        dlg.list.set_items(["alpha", "beta"])
        self._assert_row_on_popup("beta")

    def test_batch_rename_dialog(self):
        show_batch_rename(self.panel, [_Entry("a.txt"), _Entry("b.txt")])
        self._assert_row_on_popup("b.txt")


if __name__ == "__main__":
    unittest.main()
