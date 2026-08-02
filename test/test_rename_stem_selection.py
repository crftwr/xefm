"""The rename prompt pre-selects only the filename stem (issue #252): typing
replaces the name body while the extension survives. Directories, dotfiles, and
extensionless names keep the whole-name selection.

Run with: python -m pytest test/test_rename_stem_selection.py -v
"""

import unittest

from puikit.event import Event, EventType

from xefm.app import _stem_selection
from xefm.input_dialog import InputDialog


class TestStemSelection(unittest.TestCase):
    """The span the rename prompt selects for a given entry name."""

    def test_simple_extension(self):
        self.assertEqual(_stem_selection("photo.jpg", False), (0, 5))

    def test_only_last_extension_is_kept(self):
        self.assertEqual(_stem_selection("archive.tar.gz", False), (0, len("archive.tar")))

    def test_dotfile_selects_whole_name(self):
        self.assertIsNone(_stem_selection(".gitignore", False))

    def test_extensionless_selects_whole_name(self):
        self.assertIsNone(_stem_selection("README", False))

    def test_directory_selects_whole_name(self):
        self.assertIsNone(_stem_selection("photos.old", True))

    def test_trailing_dot(self):
        self.assertEqual(_stem_selection("notes.", False), (0, 5))


class TestInputDialogSelectRange(unittest.TestCase):
    """``select_range`` wires through to the field's anchor/cursor."""

    def test_range_selects_span(self):
        dlg = InputDialog(text="photo.jpg", select_range=(0, 5))
        self.assertEqual(dlg.edit._anchor, 0)
        self.assertEqual(dlg.edit.cursor, 5)
        self.assertEqual(dlg.edit.selection_text, "photo")

    def test_range_is_clamped(self):
        dlg = InputDialog(text="abc", select_range=(-2, 99))
        self.assertEqual(dlg.edit._anchor, 0)
        self.assertEqual(dlg.edit.cursor, 3)

    def test_default_still_selects_all(self):
        dlg = InputDialog(text="photo.jpg")
        self.assertEqual(dlg.edit._anchor, 0)
        self.assertEqual(dlg.edit.cursor, len("photo.jpg"))
        self.assertEqual(dlg.edit.selection_text, "photo.jpg")

    def test_typing_replaces_stem_and_keeps_extension(self):
        dlg = InputDialog(text="photo.jpg", select_range=(0, 5))
        dlg.handle_event(Event(type=EventType.KEY, key="x", char="x"))
        self.assertEqual(dlg.edit.text, "x.jpg")


if __name__ == "__main__":
    unittest.main()
