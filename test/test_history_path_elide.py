"""
Long-path abbreviation across the list dialogs (issue #211).

The pickers feed full paths to a ``FilterListDialog`` / ``ListView`` (and the
search dialog to its own ``ListView``). The default end-clip dropped the *tail*
of a long path — the very directory/file you were after. Now:

- ``show_filter_list`` marks a truncated row with a trailing "…" by default;
- the path pickers (History, Favorites, Drives) elide in the *middle* so both
  the name/root and the path tail survive;
- the progressive search dialog marks over-long result rows with "…".

We check the option threads through each dialog to its ``ListView`` and that the
callers request the right mode.
"""

import inspect
import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import filter_list_dialog as fld  # noqa: E402
from xefm.filter_list_dialog import FilterListDialog  # noqa: E402
from xefm.progressive_search_dialog import ProgressiveSearchDialog  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class DialogThreadsElideOption(unittest.TestCase):
    def test_dialog_class_default_is_plain_end_clip(self):
        # The low-level dialog stays neutral (hard clip); the app-level helper
        # opts into the friendlier "…" default (below).
        d = FilterListDialog(["/a/b/c"], title="X")
        self.assertEqual(d.list._ellipsis, "")
        self.assertEqual(d.list._elide_where, "end")

    def test_middle_elide_reaches_the_listview(self):
        d = FilterListDialog(["/a/b/c"], title="X",
                             ellipsis="…", elide_where="middle")
        self.assertEqual(d.list._ellipsis, "…")
        self.assertEqual(d.list._elide_where, "middle")

    def test_show_filter_list_defaults_to_trailing_ellipsis(self):
        sig = inspect.signature(fld.show_filter_list)
        self.assertEqual(sig.parameters["ellipsis"].default, "…")
        self.assertEqual(sig.parameters["elide_where"].default, "end")

    def test_progressive_dialog_marks_rows_with_ellipsis(self):
        d = ProgressiveSearchDialog(search_iter=lambda *a: iter(()),
                                    to_label=lambda m, v: str(v))
        self.assertEqual(d.list._ellipsis, "…")
        self.assertEqual(d.list._elide_where, "end")


class PathPickersRequestMiddleElide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfgdir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                              left_provided=True, right_provided=True,
                              state_manager=self.sm)

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def test_history_uses_middle(self):
        self.app._record_history_path("/some/very/long/path/to/a/deep/directory")
        with patch("xefm.app.show_filter_list") as show:
            self.app.show_history()
        show.assert_called_once()
        self.assertEqual(show.call_args.kwargs.get("elide_where"), "middle")

    def test_favorites_uses_middle(self):
        with patch("xefm.app.get_favorite_directories",
                   return_value=[{"name": "Home", "path": "/tmp"}]), \
             patch("xefm.app.show_filter_list") as show:
            self.app.show_favorites()
        show.assert_called_once()
        self.assertEqual(show.call_args.kwargs.get("elide_where"), "middle")

    def test_drives_uses_middle(self):
        # Local drives are always present; stub the remote scans out.
        with patch.object(self.app, "_ssh_drives", return_value=[]), \
             patch.object(self.app, "_s3_drives", return_value=[]), \
             patch("xefm.app.show_filter_list") as show:
            self.app.show_drives()
        show.assert_called_once()
        self.assertEqual(show.call_args.kwargs.get("elide_where"), "middle")


if __name__ == "__main__":
    unittest.main()
