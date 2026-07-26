"""
Recursive content (grep) search for the PuiKit XeFMApp.

Covers the pane-independent search core behind ``show_content_search`` — the
streaming tree walk (``_iter_content_matches``), the binary-file filter
(``_looks_textual``), and result navigation (``_go_to_content_hit``). The
results now stream into the progressive ``ProgressiveSearchDialog`` (see
``test_progressive_search_dialog.py``); the walk itself is a cancellable
generator, exercised here directly.
"""

import os
import re
import sys
import tempfile
import shutil
import threading
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


def _bare_app(show_hidden=False):
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app.flm = type("_FLM", (), {"show_hidden": show_hidden})()
    return app


class WalkGrep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, relpath, content, mode="w"):
        p = os.path.join(self.tmp, relpath)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode) as f:
            f.write(content)
        return p

    def _grep(self, pattern, **kw):
        app = _bare_app(**kw)
        return list(app._iter_content_matches(
            Path(self.tmp), re.compile(pattern, re.IGNORECASE), threading.Event()))

    def test_finds_matching_line_with_number(self):
        self._write("a.txt", "alpha\nneedle here\ngamma\n")
        hits = self._grep("needle")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line"], 2)
        self.assertEqual(hits[0]["text"], "needle here")
        self.assertEqual(hits[0]["path"].name, "a.txt")

    def test_recurses_into_subdirectories(self):
        self._write("sub/deep/b.txt", "TODO: fix this\n")
        hits = self._grep("todo")  # case-insensitive
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"].name, "b.txt")

    def test_skips_binary_files(self):
        self._write("bin.dat", "match\x00more match\n", mode="w")
        hits = self._grep("match")
        self.assertEqual(hits, [])

    def test_skips_hidden_unless_shown(self):
        self._write(".secret.txt", "password\n")
        self.assertEqual(self._grep("password"), [])
        self.assertEqual(len(self._grep("password", show_hidden=True)), 1)

    def test_walk_is_uncapped(self):
        # The walk yields every match; the result cap now lives in the dialog.
        self._write("big.txt", "hit\n" * 50)
        self.assertEqual(len(self._grep("hit")), 50)

    def test_cancel_stops_the_walk(self):
        self._write("big.txt", "hit\n" * 50)
        app = _bare_app()
        cancel = threading.Event()
        cancel.set()  # already cancelled -> generator yields nothing
        hits = list(app._iter_content_matches(
            Path(self.tmp), re.compile("hit"), cancel))
        self.assertEqual(hits, [])

    def test_no_matches_returns_empty(self):
        self._write("a.txt", "nothing interesting\n")
        self.assertEqual(self._grep("zzz"), [])


class LooksTextual(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, data):
        p = os.path.join(self.tmp, "f")
        with open(p, "wb") as fh:
            fh.write(data)
        return Path(p)

    def test_text_is_textual(self):
        self.assertTrue(xefm_app.XeFMApp._looks_textual(self._file(b"hello world")))

    def test_nul_byte_is_binary(self):
        self.assertFalse(xefm_app.XeFMApp._looks_textual(self._file(b"hello\x00world")))

    def test_empty_is_not_textual(self):
        self.assertFalse(xefm_app.XeFMApp._looks_textual(self._file(b"")))


class Navigation(unittest.TestCase):
    def test_go_to_hit_moves_pane_and_cursor(self):
        tmp = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()   # outside the pane dir: not a listed row
        try:
            os.makedirs(os.path.join(tmp, "sub"))
            target = os.path.join(tmp, "sub", "hit.txt")
            open(target, "w").close()
            open(os.path.join(tmp, "sub", "other.txt"), "w").close()

            from puikit.backends import create_backend
            b = create_backend("memory"); b.open()
            # Temp state DB, never the real ~/.xefm/state.db: the app restores
            # each pane's sort mode, sort direction and filter from it, so the
            # developer's own last-used settings would otherwise decide where
            # the cursor lands in this listing.
            sm = XeFMStateManager(db_path=os.path.join(state_dir, "state.db"))
            app = xefm_app.XeFMApp(b, tmp, tmp, left_provided=True,
                                   right_provided=True, state_manager=sm)
            try:
                app._go_to_content_hit({"path": Path(target), "line": 1, "text": "x"})
                app._settle_listings()  # navigation lists on a worker; wait for it
                pane = app.active_pane()
                self.assertEqual(str(pane["path"]), os.path.join(tmp, "sub"))
                self.assertEqual(pane["files"][pane["focused_index"]].name, "hit.txt")
            finally:
                app.file_monitor.stop_monitoring()
                b.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
