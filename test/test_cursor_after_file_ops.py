"""The cursor survives an operation that changes the listing (issue #414).

Deleting a file used to send the cursor back to the top of the pane: the
post-operation reload went through ``_refresh``, the *navigation* path, which
resets the cursor because a new directory has no meaningful old row. Nothing
navigated, so it now goes through ``_relist``, which anchors the cursor to the
focused **file** — and, when that file is one of the ones just removed, to the
row that took its place.

Covers the same anchoring for the other in-place reloads: an external change
picked up by a re-list, toggling hidden files, and a batch rename (where the
focused file survives under a new name).

Run with: python -m pytest test/test_cursor_after_file_ops.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.batch_rename_dialog import BatchRenameDialog  # noqa: E402


class _BatchRenameImmediately:
    """Stands in for ``show_batch_rename``: drives the real dialog headlessly,
    so the rename map the app relies on is the one the dialog really builds."""

    def __init__(self, search, replace):
        self.search = search
        self.replace = replace

    def __call__(self, panel, files, *, on_done=None, **kwargs):
        dialog = BatchRenameDialog(files, on_done=on_done)
        dialog.search_edit.text = self.search
        dialog.replace_edit.text = self.replace
        dialog._refresh_preview()
        dialog._accept()
        return dialog


class CursorTestBase(unittest.TestCase):
    """A headless XeFMApp on the memory backend over a real temp directory."""

    #: Created in the left pane's directory during setUp, in sort order.
    FILES = ("a.txt", "b.txt", "c.txt", "d.txt")

    def setUp(self):
        from xefm.state_manager import XeFMStateManager
        from puikit.backends import create_backend
        self.tmp = tempfile.mkdtemp()
        self.other = tempfile.mkdtemp()
        self.cfgdir = tempfile.mkdtemp()
        for name in self.FILES:
            open(os.path.join(self.tmp, name), "w").close()
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.other,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app._settle_listings()
        # Delete without the confirm dialog, and on this thread, so the whole
        # operation is done by the time delete_files() returns.
        self.app.config.CONFIRM_DELETE = False
        real_delete = self.app._fileops.delete
        self.app._fileops.delete = (
            lambda panel, targets, **kw: real_delete(panel, targets,
                                                     background=False, **kw))

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
        except Exception:
            pass
        try:
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        for d in (self.tmp, self.other, self.cfgdir):
            shutil.rmtree(d, ignore_errors=True)

    # --- helpers -------------------------------------------------------------

    def pane(self):
        return self.app.active_pane()

    def names(self):
        return [f.name for f in self.pane()["files"]]

    def focus_on(self, name):
        self.pane()["focused_index"] = self.names().index(name)

    def focused(self):
        pane = self.pane()
        return pane["files"][pane["focused_index"]].name

    def select(self, *names):
        pane = self.pane()
        pane["selected_files"] = {str(f) for f in pane["files"]
                                  if f.name in names}

    def delete(self):
        self.app.delete_files()
        self.app._settle_listings()


class DeleteKeepsTheCursor(CursorTestBase):
    def test_deleting_above_the_cursor_leaves_it_on_its_file(self):
        self.focus_on("c.txt")
        self.select("a.txt")

        self.delete()

        self.assertEqual(self.names(), ["b.txt", "c.txt", "d.txt"])
        self.assertEqual(self.focused(), "c.txt")

    def test_deleting_the_cursor_entry_lands_on_the_next_one(self):
        self.focus_on("b.txt")  # no selection: the cursor entry is the target

        self.delete()

        self.assertEqual(self.names(), ["a.txt", "c.txt", "d.txt"])
        self.assertEqual(self.focused(), "c.txt")

    def test_deleting_the_last_entry_falls_back_to_the_one_above(self):
        self.focus_on("d.txt")

        self.delete()

        self.assertEqual(self.focused(), "c.txt")

    def test_deleting_a_block_lands_below_it(self):
        self.focus_on("b.txt")
        self.select("b.txt", "c.txt")

        self.delete()

        self.assertEqual(self.names(), ["a.txt", "d.txt"])
        self.assertEqual(self.focused(), "d.txt")

    def test_deleting_everything_resets_the_cursor(self):
        self.focus_on("c.txt")
        self.select(*self.FILES)

        self.delete()

        pane = self.pane()
        self.assertEqual(pane["files"], [])
        self.assertEqual(pane["focused_index"], 0)
        self.assertEqual(pane["scroll_offset"], 0)

    def test_the_pane_is_not_recorded_as_navigated(self):
        # _refresh would push the directory onto the recent-directory history and
        # fire 'directory_changed'; a post-operation reload is neither.
        self.focus_on("b.txt")
        before = list(self.app._history)

        self.delete()

        self.assertEqual(self.app._history, before)


class RelistHoldsTheCursor(CursorTestBase):
    """Every in-place re-list — not just the one delete asks for."""

    def test_an_external_delete_above_the_cursor_leaves_it_alone(self):
        self.focus_on("c.txt")
        os.remove(os.path.join(self.tmp, "a.txt"))

        self.app._relist(self.pane())
        self.app._settle_listings()

        self.assertEqual(self.focused(), "c.txt")

    def test_the_landing_row_follows_the_sort_order_not_the_alphabet(self):
        # Reversed, the row below "c.txt" is "b.txt" — a nearest-name guess would
        # land on "d.txt", which is now the row *above*.
        pane = self.pane()
        pane["sort_reverse"] = True
        self.app._resort(pane)
        self.app._settle_listings()
        self.assertEqual(self.names(), ["d.txt", "c.txt", "b.txt", "a.txt"])
        self.focus_on("c.txt")
        os.remove(os.path.join(self.tmp, "c.txt"))

        self.app._relist(pane)
        self.app._settle_listings()

        self.assertEqual(self.focused(), "b.txt")

    def test_hiding_hidden_files_keeps_the_cursor(self):
        open(os.path.join(self.tmp, ".dot"), "w").close()
        self.app.flm.show_hidden = True
        self.app._relist(self.pane())
        self.app._settle_listings()
        self.assertIn(".dot", self.names())
        self.focus_on("c.txt")

        self.app._act_toggle_hidden()  # hidden files go away above the cursor
        self.app._settle_listings()

        self.assertNotIn(".dot", self.names())
        self.assertEqual(self.focused(), "c.txt")

    def test_a_navigation_still_resets_the_cursor(self):
        os.mkdir(os.path.join(self.tmp, "sub"))
        self.app._relist(self.pane())
        self.app._settle_listings()
        self.focus_on("c.txt")

        self.app._refresh(self.pane())
        self.app._settle_listings()

        self.assertEqual(self.pane()["focused_index"], 0)


class BatchRenameFollowsTheCursor(CursorTestBase):
    def test_the_cursor_follows_its_file_to_its_new_name(self):
        self.focus_on("b.txt")
        self.select("b.txt", "c.txt")

        with mock.patch.object(xefm_app, "show_batch_rename",
                               _BatchRenameImmediately(r"\.txt$", ".log")):
            self.app.rename()  # >1 selected ⇒ the batch dialog
        self.app._settle_listings()

        self.assertEqual(self.names(), ["a.txt", "b.log", "c.log", "d.txt"])
        self.assertEqual(self.focused(), "b.log")

    def test_a_rename_that_misses_the_cursor_leaves_it_put(self):
        # "d.txt" sorts last either way, so a cursor sent back to the top fails
        # here rather than passing by accident.
        self.focus_on("d.txt")
        self.select("b.txt", "c.txt")

        with mock.patch.object(xefm_app, "show_batch_rename",
                               _BatchRenameImmediately(r"\.txt$", ".log")):
            self.app.rename()
        self.app._settle_listings()

        self.assertEqual(self.focused(), "d.txt")


class TheDialogReportsWhatItRenamed(unittest.TestCase):
    """``on_done``'s third argument — old path → new name — is what lets the
    caller follow the cursor onto a file whose name it could not have known."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for name in ("a.txt", "b.txt"):
            open(os.path.join(self.tmp, name), "w").close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _files(self):
        from xefm.path import Path
        return [Path(os.path.join(self.tmp, n)) for n in ("a.txt", "b.txt")]

    def test_renamed_map_covers_every_rename(self):
        seen = {}
        files = self._files()
        dialog = BatchRenameDialog(
            files, on_done=lambda n, errs, renamed: seen.update(renamed))
        dialog.search_edit.text = r"\.txt$"
        dialog.replace_edit.text = ".log"
        dialog._refresh_preview()

        dialog._accept()

        self.assertEqual(seen, {str(files[0]): "a.log", str(files[1]): "b.log"})

    def test_untouched_names_are_not_in_the_map(self):
        seen = {}
        files = self._files()
        dialog = BatchRenameDialog(
            files, on_done=lambda n, errs, renamed: seen.update(renamed))
        dialog.search_edit.text = "^a"
        dialog.replace_edit.text = "z"
        dialog._refresh_preview()

        dialog._accept()

        self.assertEqual(seen, {str(files[0]): "z.txt"})


if __name__ == "__main__":
    unittest.main()
