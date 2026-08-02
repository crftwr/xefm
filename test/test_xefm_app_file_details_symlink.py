"""
The Info/Details dialog must identify a symlink as a symlink, not follow it
(issue #228).

``Path.is_dir()``/``is_file()`` follow symlinks, so a symlink pointing at a
directory used to render as Type "Directory" in the details dialog. The type
check now tests ``is_symlink()`` first. Driven against the headless memory
backend over a real local temp directory (so real symlinks exist on disk).
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


class FileDetailsSymlink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfgdir = tempfile.mkdtemp()
        # A real directory, a real file, and symlinks pointing at each — plus a
        # dangling symlink whose target never existed.
        os.makedirs(os.path.join(self.tmp, "realdir"))
        with open(os.path.join(self.tmp, "realfile.txt"), "w") as f:
            f.write("hi\n")
        os.symlink(os.path.join(self.tmp, "realdir"), os.path.join(self.tmp, "link_to_dir"))
        os.symlink(os.path.join(self.tmp, "realfile.txt"), os.path.join(self.tmp, "link_to_file"))
        os.symlink(os.path.join(self.tmp, "nope"), os.path.join(self.tmp, "link_broken"))

        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                              left_provided=True, right_provided=True,
                              state_manager=self.sm)
        self.app._settle_listings()  # startup lists on workers; wait for it

        # Capture the markdown the dialog would render instead of showing it.
        self._captured = []
        self._orig_show = xefm_app.show_markdown
        xefm_app.show_markdown = \
            lambda panel, text, title=None, **kw: self._captured.append(text)

    def tearDown(self):
        xefm_app.show_markdown = self._orig_show
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def _type_for(self, name):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(name)
        pane["selected_files"] = set()
        self._captured.clear()
        self.app.file_details()
        self.assertTrue(self._captured, "details dialog produced no markdown")
        for line in self._captured[-1].splitlines():
            if line.startswith("| Type |"):
                return line.split("|")[2].strip()
        self.fail(f"no Type row in details for {name}")

    def test_symlink_to_directory_is_not_a_directory(self):
        self.assertEqual(self._type_for("link_to_dir"), "Symlink → Directory")

    def test_symlink_to_file(self):
        self.assertEqual(self._type_for("link_to_file"), "Symlink → File")

    def test_broken_symlink(self):
        self.assertEqual(self._type_for("link_broken"), "Symlink (broken)")

    def test_plain_directory_and_file_unchanged(self):
        self.assertEqual(self._type_for("realdir"), "Directory")
        self.assertEqual(self._type_for("realfile.txt"), "File")


if __name__ == "__main__":
    unittest.main()
