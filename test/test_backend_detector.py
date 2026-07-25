"""
Backend detection (xefm.backend_detector.is_desktop_mode).

The config keys its GUI-vs-terminal defaults off is_desktop_mode() — most
importantly TEXT_EDITOR ('code' on the desktop, 'vim' in a terminal). XeFM (and
the macOS .app bundle) launch with ``--backend gui``/``--backend macos``, and
main() also publishes the resolved backend via the XEFM_BACKEND env var. This
verifies the detector recognizes the current PuiKit backend names (not just the
legacy 'coregraphics' string) via both signals. See issue #199 — the stale
detector returned False in GUI mode, so 'vim' was launched under the windowed
backend where it can't run.
"""

import os
import sys
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import backend_detector as bd  # noqa: E402


class DesktopModeDetection(unittest.TestCase):
    def setUp(self):
        # The detector caches its result module-wide; start each test clean.
        bd._cached_backend = None

    def tearDown(self):
        bd._cached_backend = None

    def _detect(self, argv, env):
        with patch.object(sys, "argv", argv), \
             patch.dict(os.environ, env, clear=True):
            return bd.is_desktop_mode()

    # --- env var (Method 1, set by main()) --------------------------------
    def test_env_gui_is_desktop(self):
        self.assertTrue(self._detect(["XeFM"], {"XEFM_BACKEND": "gui"}))

    def test_env_macos_is_desktop(self):
        self.assertTrue(self._detect(["XeFM"], {"XEFM_BACKEND": "macos"}))

    def test_env_tui_is_terminal(self):
        self.assertFalse(self._detect(["XeFM"], {"XEFM_BACKEND": "tui"}))

    def test_env_windows_is_desktop(self):
        self.assertTrue(self._detect(["XeFM"], {"XEFM_BACKEND": "windows"}))

    def test_env_memory_is_terminal(self):
        # The headless test backend is not desktop mode.
        self.assertFalse(self._detect(["XeFM"], {"XEFM_BACKEND": "memory"}))

    # --- --backend argv (Method 2, the .app bundle path) ------------------
    def test_argv_backend_gui_is_desktop(self):
        self.assertTrue(self._detect(["XeFM", "--backend", "gui"], {}))

    def test_argv_backend_macos_is_desktop(self):
        self.assertTrue(self._detect(["XeFM", "--backend", "macos"], {}))

    def test_argv_backend_tui_is_terminal(self):
        self.assertFalse(self._detect(["XeFM", "--backend", "tui"], {}))

    def test_argv_backend_curses_is_terminal(self):
        self.assertFalse(self._detect(["xefm/app.py", "--backend", "curses"], {}))

    # --- defaults ---------------------------------------------------------
    def test_no_signal_defaults_to_terminal(self):
        self.assertFalse(self._detect(["XeFM"], {}))

    def test_env_takes_priority_over_argv(self):
        # main() sets XEFM_BACKEND from the resolved backend; trust it first.
        self.assertTrue(
            self._detect(["XeFM", "--backend", "tui"], {"XEFM_BACKEND": "gui"}))

    def test_get_backend_name(self):
        with patch.object(sys, "argv", ["XeFM", "--backend", "gui"]), \
             patch.dict(os.environ, {}, clear=True):
            bd._cached_backend = None
            self.assertEqual(bd.get_backend_name(), "gui")
        bd._cached_backend = None
        with patch.object(sys, "argv", ["XeFM"]), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(bd.get_backend_name(), "curses")


if __name__ == "__main__":
    unittest.main()
