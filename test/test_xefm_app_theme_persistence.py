"""The active theme is remembered across restarts (no config setting).

Switching theme (View > Theme / the T key) persists the choice to the state
store via ``set_state('theme', ...)``; a fresh ``XeFMApp`` built on the same state
manager reopens on it, and a clean profile defaults to Dark+. Monitoring is faked
and the app runs on the headless ``memory`` backend with a temp-db state manager,
mirroring ``test_xefm_app_file_monitoring``.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class _FakeMonitor:
    """Inert monitor so construction never spawns watchdog threads."""

    def __init__(self, config, file_manager):
        self.reload_queue = file_manager.reload_queue

    def is_monitoring_enabled(self):
        return False

    def update_monitored_directory(self, *args):
        pass

    def stop_monitoring(self):
        pass


class ThemePersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.left = os.path.join(self.tmp, "l")
        self.right = os.path.join(self.tmp, "r")
        os.makedirs(self.left)
        os.makedirs(self.right)
        self.db = os.path.join(self.tmp, "state.db")
        self._patcher = patch.object(xefm_app, "FileMonitorManager", _FakeMonitor)
        self._patcher.start()
        self._backends = []

    def tearDown(self):
        self._patcher.stop()
        for be in self._backends:
            try:
                be.close()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_app(self):
        """Build a XeFMApp on a fresh state manager over the *same* temp db, so two
        calls model a quit + relaunch."""
        sm = XeFMStateManager(db_path=self.db)
        backend = create_backend("memory")
        backend.open()
        self._backends.append(backend)
        app = xefm_app.XeFMApp(backend, self.left, self.right, state_manager=sm)
        # __init__ redirects stdout/stderr into the log pane; restore them so a
        # test assertion failure prints to the real terminal.
        sys.stdout, sys.stderr = app._orig_stdout, app._orig_stderr
        return app

    @staticmethod
    def _active(app):
        return app.themes[app._theme_index][0]

    def _index_of(self, app, name):
        return next(i for i, (n, _t) in enumerate(app.themes) if n == name)

    def test_defaults_to_dark_plus_on_fresh_profile(self):
        self.assertEqual(self._active(self._make_app()), "Dark+")

    def test_switch_is_remembered_across_restart(self):
        app = self._make_app()
        app._select_theme(self._index_of(app, "Solarized"))
        self.assertEqual(self._active(app), "Solarized")

        # Relaunch on the same state db: reopens on the remembered theme, and the
        # live panel actually carries it.
        app2 = self._make_app()
        self.assertEqual(self._active(app2), "Solarized")
        self.assertIs(app2.panel.theme, app2.themes[app2._theme_index][1])

    def test_unknown_saved_theme_falls_back_to_dark_plus(self):
        # A saved name that no longer exists (e.g. a user theme removed from
        # config) must not break startup — it falls back to Dark+.
        XeFMStateManager(db_path=self.db).set_state("theme", "No Such Theme")
        self.assertEqual(self._active(self._make_app()), "Dark+")


if __name__ == "__main__":
    unittest.main()
