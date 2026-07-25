"""
Cross-session state persistence for the PuiKit XeFMApp.

Replaces the legacy ``test_state_restoration_*`` coverage, which targeted the
old curses ``FileManager`` (the old ``xefm_main.py``, since removed). Here we drive
the new ``XeFMApp`` state hooks directly against a real ``XeFMStateManager`` backed
by a temp database, so save/restore is exercised end to end without standing up
the whole PuiKit UI.

The hooks under test:
  * ``XeFMApp._restore_layout_and_paths`` - window layout + pane dir/sort/filter
  * ``XeFMApp._restore_cursor_positions``  - cursor moved to the remembered file
  * ``XeFMApp._save_application_state``     - the inverse, persisted on quit
"""

import os
import sys
import tempfile
import shutil
import unittest

# Run standalone or under `cd test && PYTHONPATH=.. pytest`: make both the
# src package and the repo root (for the top-level ``xefm`` module) importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm._config import Config  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.pane_manager import PaneManager  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


class _Splitter:
    """Minimal stand-in for a PuiKit Splitter: only ``.fraction`` is read."""

    def __init__(self, fraction):
        self.fraction = fraction


class _Backend:
    """Minimal backend exposing ``size`` for cursor-scroll math."""

    size = (80, 24)


class StatePersistenceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "state.db")
        self.sm = XeFMStateManager(db_path=self.db_path)
        self.config = Config()

        # Real directories the panes can point at.
        self.left_start = os.path.join(self.tmp, "left_start")
        self.right_start = os.path.join(self.tmp, "right_start")
        self.left_saved = os.path.join(self.tmp, "left_saved")
        self.right_saved = os.path.join(self.tmp, "right_saved")
        for d in (self.left_start, self.right_start, self.left_saved, self.right_saved):
            os.makedirs(d, exist_ok=True)

    def tearDown(self):
        try:
            self.sm.close() if hasattr(self.sm, "close") else None
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_app(self, left_provided=False, right_provided=False):
        """Build a XeFMApp shell without running its UI-heavy ``__init__``.

        Mirrors the legacy tests' ``patch('...__init__')`` approach: we wire up
        only the collaborators the state hooks touch."""
        app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
        app.config = self.config
        app.state_manager = self.sm
        app.backend = _Backend()
        app.flm = FileListManager(self.config)
        app.pm = PaneManager(
            self.config,
            Path(self.left_start),
            Path(self.right_start),
            state_manager=self.sm,
            file_list_manager=app.flm,
        )
        app._left_provided = left_provided
        app._right_provided = right_provided
        app.log_info = lambda *a, **k: None
        return app


class RestoreLayoutAndPaths(StatePersistenceTestBase):
    def test_pane_directory_restored_when_not_provided(self):
        self.sm.save_pane_state("left", {"path": self.left_saved})
        app = self.make_app(left_provided=False)

        app._restore_layout_and_paths()

        self.assertEqual(str(app.pm.left_pane["path"]), self.left_saved)

    def test_cmdline_directory_takes_precedence(self):
        self.sm.save_pane_state("left", {"path": self.left_saved})
        app = self.make_app(left_provided=True)

        app._restore_layout_and_paths()

        # Explicit --left wins: the saved directory is ignored.
        self.assertEqual(str(app.pm.left_pane["path"]), self.left_start)

    def test_sort_and_filter_restored_even_when_provided(self):
        self.sm.save_pane_state("left", {
            "path": self.left_saved,
            "sort_mode": "size",
            "sort_reverse": True,
            "filter_pattern": "*.py",
        })
        app = self.make_app(left_provided=True)

        app._restore_layout_and_paths()

        self.assertEqual(app.pm.left_pane["sort_mode"], "size")
        self.assertTrue(app.pm.left_pane["sort_reverse"])
        self.assertEqual(app.pm.left_pane["filter_pattern"], "*.py")

    def test_nonexistent_saved_directory_ignored(self):
        gone = os.path.join(self.tmp, "deleted")  # never created
        self.sm.save_pane_state("left", {"path": gone})
        app = self.make_app(left_provided=False)

        app._restore_layout_and_paths()

        self.assertEqual(str(app.pm.left_pane["path"]), self.left_start)

    def test_window_layout_restored(self):
        self.sm.save_window_layout(left_pane_ratio=0.3, log_height_ratio=0.4)
        app = self.make_app()

        app._restore_layout_and_paths()

        self.assertAlmostEqual(app.pm.left_pane_ratio, 0.3)
        # panes fraction is the complement of the log-height share.
        self.assertAlmostEqual(app._panes_fraction, 0.6)

    def test_out_of_range_layout_is_clamped(self):
        self.sm.save_window_layout(left_pane_ratio=1.5, log_height_ratio=-0.2)
        app = self.make_app()

        app._restore_layout_and_paths()

        self.assertLessEqual(app.pm.left_pane_ratio, 0.9)
        self.assertGreaterEqual(app.pm.left_pane_ratio, 0.1)
        self.assertLessEqual(app._panes_fraction, 0.95)

    def test_no_saved_state_uses_defaults(self):
        app = self.make_app()

        app._restore_layout_and_paths()

        self.assertEqual(app._panes_fraction, xefm_app.PANES_FRACTION)
        self.assertEqual(str(app.pm.left_pane["path"]), self.left_start)


class RestoreCursor(StatePersistenceTestBase):
    def test_cursor_moved_to_remembered_file(self):
        app = self.make_app()
        pane = app.pm.left_pane
        directory = str(pane["path"])
        pane["files"] = [Path(os.path.join(directory, n))
                         for n in ("a.txt", "b.txt", "c.txt")]
        self.sm.save_pane_cursor_position("left", directory, "b.txt")

        app._restore_cursor_positions()

        self.assertEqual(pane["focused_index"], 1)

    def test_missing_cursor_leaves_focus_at_top(self):
        app = self.make_app()
        pane = app.pm.left_pane
        directory = str(pane["path"])
        pane["files"] = [Path(os.path.join(directory, n)) for n in ("a.txt", "b.txt")]

        app._restore_cursor_positions()

        self.assertEqual(pane["focused_index"], 0)


class SaveApplicationState(StatePersistenceTestBase):
    def _app_ready_to_save(self):
        app = self.make_app()
        app.pane_splitter = _Splitter(0.35)
        app.content_splitter = _Splitter(0.70)
        for name in ("left", "right"):
            pane = app.pm.left_pane if name == "left" else app.pm.right_pane
            directory = str(pane["path"])
            pane["files"] = [Path(os.path.join(directory, n)) for n in ("x", "y", "z")]
            pane["focused_index"] = 1
        # __init__ isn't run in this shell; seed the history the way it would.
        app._seed_history()
        return app

    def test_layout_saved_from_live_splitter_fractions(self):
        app = self._app_ready_to_save()

        app._save_application_state()

        layout = self.sm.load_window_layout()
        self.assertAlmostEqual(layout["left_pane_ratio"], 0.35)
        self.assertAlmostEqual(layout["log_height_ratio"], 0.30)  # 1 - 0.70

    def test_pane_state_and_recent_dirs_saved(self):
        app = self._app_ready_to_save()

        app._save_application_state()

        left = self.sm.load_pane_state("left")
        self.assertEqual(left["path"], str(app.pm.left_pane["path"]))
        recent = self.sm.load_recent_directories()
        self.assertIn(str(app.pm.left_pane["path"]), recent)
        self.assertIn(str(app.pm.right_pane["path"]), recent)

    def test_full_history_trail_persisted_most_recent_first(self):
        app = self._app_ready_to_save()
        # Simulate navigation beyond the two starting panes, including a revisit.
        for d in (self.left_saved, self.right_saved, self.left_saved):
            app._record_history_path(d)

        app._save_application_state()

        recent = self.sm.load_recent_directories()
        # Most-recent-first, de-duplicated: the revisited dir collapses to a
        # single, front-most entry rather than only the two panes' final paths.
        self.assertEqual(recent[0], self.left_saved)
        self.assertEqual(recent[1], self.right_saved)
        self.assertEqual(recent.count(self.left_saved), 1)
        # The two starting panes are still present, now older in the trail.
        self.assertIn(str(app.pm.left_pane["path"]), recent)
        self.assertIn(str(app.pm.right_pane["path"]), recent)

    def test_history_seeded_from_db_on_startup(self):
        # A prior session persisted a most-recent-first trail.
        self.sm.save_recent_directories(
            [self.right_saved, self.left_saved], xefm_app._HISTORY_MAX)
        app = self.make_app()  # panes point at left_start / right_start

        app._seed_history()

        items = app._recent_dirs_most_recent_first()
        # The two starting dirs are the most-recent entries...
        self.assertEqual(items[0], self.right_start)
        self.assertEqual(items[1], self.left_start)
        # ...and the persisted trail is restored beneath them, in order.
        self.assertLess(items.index(self.right_saved), items.index(self.left_saved))

    def test_cursor_saved_then_restored_roundtrip(self):
        app = self._app_ready_to_save()
        # 'y' is at index 1 in both panes.
        app._save_application_state()

        # Fresh app pointed at the same dirs restores the same cursor file.
        restored = self.make_app()
        pane = restored.pm.left_pane
        directory = str(pane["path"])
        pane["files"] = [Path(os.path.join(directory, n)) for n in ("x", "y", "z")]
        restored._restore_cursor_positions()

        self.assertEqual(pane["files"][pane["focused_index"]].name, "y")


if __name__ == "__main__":
    unittest.main()
