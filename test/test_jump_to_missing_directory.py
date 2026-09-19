"""
Picking a directory that isn't there (issue #430 follow-up).

Since the favorites / drives / history pickers stopped probing their rows before
showing them, a row can name a directory that is gone, asleep or off the
network. Choosing one must not leave the pane parked on it: the move is
provisional, and the pane goes back to what it was showing if the destination
cannot be read (``XeFMApp._jump_pane_to``).

The log that comes with it is one line — the listing's own "Directory not
found". The optimistic "Jumped to …" waits for the jump to have happened, the
retry ladder in the filesystem watcher stays at debug level, and History records
only directories the user actually reached.

Run with: python -m pytest test/test_jump_to_missing_directory.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import _config  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


class JumpToAMissingDirectory(unittest.TestCase):
    def setUp(self):
        from puikit.backends import create_backend
        # realpath: on macOS the app lands on /private/var..., and these tests
        # compare the pane's path against it.
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        for name in ("alpha.txt", "beta.txt"):
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write("x")
        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        # The watcher is not what these tests are about, and a real observer per
        # test is flaky under the xdist runner.
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.missing = os.path.join(self.tmp, "no-such-dir")

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _log_text(self):
        self.app.log._select_all()
        return self.app.log.selection_text()

    def test_the_pane_stays_where_it_was(self):
        pane = self.app.active_pane()
        before_names = [f.name for f in pane["files"]]
        pane["focused_index"] = 1

        self.app._jump_to_favorite({"name": "Gone", "path": self.missing})
        self.app._settle_listings()

        self.assertEqual(str(pane["path"]), self.tmp)
        self.assertEqual([f.name for f in pane["files"]], before_names)
        self.assertEqual(pane["focused_index"], 1)

    def test_the_failure_is_one_line_and_the_jump_is_not_announced(self):
        said = []
        original = self.app.flm.logger.error
        self.app.flm.logger.error = said.append
        try:
            self.app._jump_to_favorite({"name": "Gone", "path": self.missing})
            self.app._settle_listings()
        finally:
            self.app.flm.logger.error = original
        self.app.panel.render()

        # One line, naming the path once — not the three copies "{path}: {e}"
        # produced, nor the dozen the watcher's retry ladder added on top.
        self.assertEqual(said, [f"Directory not found: {self.missing}"])
        # And the move that did not happen is not reported as if it had.
        self.assertNotIn("Jumped to", self._log_text())

    def test_a_reachable_favorite_still_moves_and_says_so(self):
        sub = os.path.join(self.tmp, "sub")
        os.mkdir(sub)
        pane = self.app.active_pane()

        self.app._jump_to_favorite({"name": "Sub", "path": sub})
        self.app._settle_listings()
        self.app.panel.render()

        self.assertEqual(str(pane["path"]), sub)
        self.assertIn("Jumped to Sub", self._log_text())

    def test_marked_files_survive_a_failed_jump(self):
        """Nothing about the move happened, so nothing about it is undone by
        halves — the selection a jump would have cleared comes back too."""
        pane = self.app.active_pane()
        marked = str(Path(os.path.join(self.tmp, "alpha.txt")))
        pane["selected_files"].add(marked)

        self.app._jump_to_favorite({"name": "Gone", "path": self.missing})
        self.app._settle_listings()

        self.assertEqual(pane["selected_files"], {marked})

    def test_a_failed_jump_leaves_no_trace_in_history(self):
        self.app._jump_to_favorite({"name": "Gone", "path": self.missing})
        self.app._settle_listings()
        self.assertNotIn(self.missing, self.app._history)

    def test_drives_and_history_are_provisional_too(self):
        """All three pickers name a directory the user cannot see, so all three
        go through the same move."""
        pane = self.app.active_pane()

        self.app._go_to_drive({"name": "Gone", "path": self.missing})
        self.app._settle_listings()
        self.assertEqual(str(pane["path"]), self.tmp)

        self.app._go_to_history(self.missing)
        self.app._settle_listings()
        self.assertEqual(str(pane["path"]), self.tmp)

    def test_a_search_results_pane_survives_a_failed_jump(self):
        """A jump leaves virtual mode on the way out — and comes back to it when
        the destination turns out not to be there."""
        found = Path(os.path.join(self.tmp, "alpha.txt"))
        self.app._feed_search_results("filename", [found], Path(self.tmp), "alpha")
        pane = self.app.active_pane()
        self.assertIsNotNone(pane["virtual"])

        self.app._jump_to_favorite({"name": "Gone", "path": self.missing})
        self.app._settle_listings()

        self.assertIsNotNone(pane["virtual"])
        self.assertEqual([f.name for f in pane["files"]], ["alpha.txt"])


class ListingErrorsAreOneLine(unittest.TestCase):
    """``compute_listing`` writes what the log pane shows."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.flm = FileListManager(_config.Config())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _logged(self, path):
        said = []
        original = self.flm.logger.error
        self.flm.logger.error = said.append
        try:
            result = self.flm.compute_listing(Path(path))
        finally:
            self.flm.logger.error = original
        return result, said

    def test_a_missing_directory_names_itself_once(self):
        missing = os.path.join(self.tmp, "no-such-dir")
        result, said = self._logged(missing)

        self.assertFalse(result["ok"])
        self.assertEqual(said, [f"Directory not found: {missing}"])

    @unittest.skipIf(os.geteuid() == 0, "root reads an unreadable directory")
    def test_an_unreadable_directory_says_so_once(self):
        locked = os.path.join(self.tmp, "locked")
        os.mkdir(locked)
        os.chmod(locked, 0o000)
        try:
            result, said = self._logged(locked)
        finally:
            os.chmod(locked, 0o700)

        self.assertFalse(result["ok"])
        self.assertEqual(said, [f"Permission denied: {locked}"])


if __name__ == "__main__":
    unittest.main()
