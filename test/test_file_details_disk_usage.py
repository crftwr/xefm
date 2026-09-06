"""
The Info/Details dialog's live "Disk usage" rows: a background walk fills in a
directory's recursive size and item counts after the dialog is already open,
via throttled animation ticks that swap updated Markdown in place.

Driven end-to-end on the headless memory backend (PROFILE_TUI: animation
ticks supported, pumped manually with ``run_animation_ticks``) over a real
local temp directory.
"""

import os
import sys
import tempfile
import shutil
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class FileDetailsDiskUsage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfgdir = tempfile.mkdtemp()
        # A directory holding 350 bytes across 3 files and 1 subdirectory,
        # plus a plain file beside it for the multi-selection case.
        d = os.path.join(self.tmp, "adir")
        os.makedirs(os.path.join(d, "sub"))
        for name, size in (("f1.bin", 100), ("f2.bin", 200)):
            with open(os.path.join(d, name), "wb") as f:
                f.write(b"x" * size)
        with open(os.path.join(d, "sub", "f3.bin"), "wb") as f:
            f.write(b"z" * 50)
        with open(os.path.join(self.tmp, "beside.bin"), "wb") as f:
            f.write(b"b" * 10)

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
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def _open_details(self, focus, selected=()):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(focus)
        pane["selected_files"] = {
            str(f) for f in pane["files"] if f.name in selected}
        self.app.file_details()
        dialog = self.app.panel._layers[-1].widget
        # Spy on the in-place updates while keeping the real behavior (which
        # resets the scroll offset that refresh() must then restore).
        sources = []
        orig = dialog.md.set_source

        def spy(src):
            orig(src)
            sources.append(src)
        dialog.md.set_source = spy
        return dialog, sources

    def _pump_until_settled(self, sources):
        """Run tick rounds until the walk's final update lands (no 'scanning'
        marker left), failing rather than hanging if it never does."""
        for _ in range(200):
            self.backend.run_animation_ticks()
            if sources and "scanning" not in sources[-1]:
                return sources[-1]
            time.sleep(0.01)
        self.fail("disk usage scan never settled")

    def test_directory_rows_fill_in(self):
        dialog, sources = self._open_details("adir")
        # Scroll by one line, not three. The widget clamps to what the content
        # allows, and the content's height here turns on how many lines the
        # temp directory's *path* wraps to — long under macOS's /var/folders
        # TMPDIR, short under /tmp, so an offset of 3.0 survived on one machine
        # and came back clamped to 2.0 on another. What the assertion is for is
        # that the swap does not reset the position, and one line shows that.
        dialog.md.offset = 1.0
        final = self._pump_until_settled(sources)
        self.assertIn("| Disk usage | 350 B (350 bytes) |", final)
        self.assertIn("| Contents | 3 files, 1 folders |", final)
        # The in-place swap must not yank the scroll position.
        self.assertEqual(dialog.md.offset, 1.0)

    def test_multi_selection_aggregates(self):
        dialog, sources = self._open_details(
            "adir", selected=("adir", "beside.bin"))
        final = self._pump_until_settled(sources)
        # 360 = the directory's recursive 350 + the plain file's 10; items
        # count the 2 selected entries plus everything inside the directory.
        self.assertIn("**Total size:** 360 B (360 bytes)", final)
        self.assertIn("**Total items:** 6 (4 files, 2 folders)", final)
        self.assertIn("| Disk usage | 350 B (350 bytes) |", final)


if __name__ == "__main__":
    unittest.main()
