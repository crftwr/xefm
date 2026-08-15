"""After create/rename, the cursor lands on the new entry (issue #279).

``_refresh`` lists on a worker thread and empties ``pane["files"]``
immediately, so placing the cursor by name must ride the listing's
``on_ready`` hook — calling ``_select_by_name`` synchronously right after
``_refresh`` always ran over an empty list and left the cursor at the top.

Each fixture directory contains a decoy entry that sorts *before* the new
one (directories sort first), so a cursor stuck at row 0 fails the test
rather than passing by accident.

Run with: python -m pytest test/test_create_rename_cursor.py -v
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


class _AcceptImmediately:
    """Stands in for ``show_input``: no dialog, just accept ``text``."""

    def __init__(self, text):
        self.text = text

    def __call__(self, panel, *, on_accept, validate=None, **kwargs):
        if validate is not None:
            assert validate(self.text) is None
        on_accept(self.text)


class CursorLandsOnTheNewEntry(unittest.TestCase):
    """A headless XeFMApp on the memory backend over a real temp directory."""

    def setUp(self):
        from xefm.state_manager import XeFMStateManager
        from puikit.backends import create_backend
        self.tmp = tempfile.mkdtemp()
        self.cfgdir = tempfile.mkdtemp()
        # "adir" sorts before any name created below, in the dirs-first block.
        os.mkdir(os.path.join(self.tmp, "adir"))
        for n in ("a.txt", "c.txt"):
            open(os.path.join(self.tmp, n), "w").close()
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app._settle_listings()

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
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def _focused(self):
        pane = self.app.active_pane()
        return pane["files"][pane["focused_index"]], pane["focused_index"]

    def test_create_directory_lands_on_it(self):
        with mock.patch.object(xefm_app, "show_input", _AcceptImmediately("zdir")):
            self.app.create_directory()
        self.app._settle_listings()
        entry, index = self._focused()
        self.assertEqual(entry.name, "zdir")
        self.assertNotEqual(index, 0)

    def test_create_nested_directory_lands_on_the_first_component(self):
        # mkdir(parents=True) accepts "sub/child"; what appears in this pane
        # is "sub".
        with mock.patch.object(xefm_app, "show_input",
                               _AcceptImmediately(os.path.join("sub", "child"))):
            self.app.create_directory()
        self.app._settle_listings()
        entry, index = self._focused()
        self.assertEqual(entry.name, "sub")
        self.assertNotEqual(index, 0)

    def test_create_file_lands_on_it(self):
        with mock.patch.object(xefm_app, "show_input", _AcceptImmediately("b.txt")):
            self.app.create_file()
        self.app._settle_listings()
        entry, index = self._focused()
        self.assertEqual(entry.name, "b.txt")
        self.assertNotEqual(index, 0)

    def test_rename_lands_on_the_new_name(self):
        pane = self.app.active_pane()
        pane["focused_index"] = next(i for i, f in enumerate(pane["files"])
                                     if f.name == "a.txt")
        with mock.patch.object(xefm_app, "show_input", _AcceptImmediately("z.txt")):
            self.app.rename()
        self.app._settle_listings()
        entry, index = self._focused()
        self.assertEqual(entry.name, "z.txt")
        self.assertNotEqual(index, 0)


if __name__ == "__main__":
    unittest.main()
