"""
Enter opens the built-in viewer on a plain file (issue #212).

Pressing Enter (the ``open_item`` action) used to be a no-op on a regular file —
only directories and archives responded. It now opens the file in the built-in
("embedded") viewer, the same one ``V`` (``view_file``) uses. Directories still
navigate. Driven against the headless memory backend.
"""

import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class OpenItemViewer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfgdir = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "note.txt"), "w") as f:
            f.write("hello world\n")
        os.makedirs(os.path.join(self.tmp, "adir"))
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                              left_provided=True, right_provided=True,
                              state_manager=self.sm)
        self.app._settle_listings()  # startup lists on workers; wait for it

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

    def _focus(self, name):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(name)

    def _top_layer_name(self):
        layers = self.app.panel._layers
        return type(layers[-1].widget).__name__ if layers else None

    def test_enter_on_file_opens_text_viewer(self):
        self._focus("note.txt")
        self.assertFalse(self.app.panel.has_layers)
        self.app.dispatch("open_item")
        self.assertTrue(self.app.panel.has_layers)
        self.assertEqual(self._top_layer_name(), "TextViewer")

    def test_enter_on_directory_navigates_not_views(self):
        self._focus("adir")
        self.app.dispatch("open_item")
        self.app._settle_listings()  # _refresh lists on a worker
        self.assertFalse(self.app.panel.has_layers)          # no viewer opened
        self.assertEqual(self.app.active_pane()["path"].name, "adir")


if __name__ == "__main__":
    unittest.main()
