"""
Edit-config / reload-config wiring for the PuiKit XeFMApp (issue #218).

``edit_config`` opens ``~/.xefm/config.py`` in ``TEXT_EDITOR`` via the same
terminal hand-off as ``edit_file``, then reloads. ``reload_config`` re-reads
the file and applies what can change at runtime: the keymap (``self.keys``) is
rebuilt, and the config reference threaded through the long-lived subsystems is
re-pointed. ``subprocess.run`` is mocked so no editor launches, and the shared
``config_manager`` singleton is snapshotted/restored so tests stay isolated.
"""

import os
import sys
import tempfile
import shutil
import textwrap
import unittest
from unittest.mock import patch, MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.config import config_manager  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class ConfigReloadBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()          # pane directory (file-monitored)
        # The config file lives OUTSIDE the monitored pane dir: writing it must
        # not churn the watched directory, or the watchdog observer can deadlock
        # against its own shutdown during teardown.
        self.cfgdir = tempfile.mkdtemp()
        # Temp state DB so pane paths don't leak into the real ~/.xefm/state.db.
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                              left_provided=True, right_provided=True,
                              state_manager=self.sm)
        # Snapshot the shared config singleton so a reload against a temp file
        # can't leak into other tests.
        self._saved = (config_manager.config, config_manager._key_bindings,
                       config_manager.config_file)

    def tearDown(self):
        config_manager.config, config_manager._key_bindings, \
            config_manager.config_file = self._saved
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def _write_config(self, body: str):
        """Write a temp config.py and point the singleton at it."""
        path = os.path.join(self.cfgdir, "config.py")
        with open(path, "w") as f:
            f.write(textwrap.dedent(body))
        config_manager.config_file = Path(path)
        return path


class EditConfig(ConfigReloadBase):
    def test_terminal_mode_launches_editor_then_reloads(self):
        # Terminal editor (e.g. vim) blocks until quit, so we reload on return.
        self._write_config("""
            class Config:
                TEXT_EDITOR = 'vim'
        """)
        with patch("xefm.app.is_desktop_mode", return_value=False), \
             patch("subprocess.run") as run, \
             patch.object(self.app, "reload_config") as reload:
            self.app.edit_config()
        run.assert_called_once()
        argv = run.call_args.args[0]
        self.assertEqual(argv[-1], str(config_manager.config_file))
        self.assertIn(self.app.config.TEXT_EDITOR.split()[0], argv[0])
        reload.assert_called_once()

    def test_gui_mode_launches_editor_but_does_not_auto_reload(self):
        # A GUI editor (e.g. VS Code) opens in its own window and returns at
        # once, before any edit is saved — so we must NOT reload, and instead
        # hint the user to reload manually.
        self._write_config("""
            class Config:
                TEXT_EDITOR = 'code'
        """)
        with patch("xefm.app.is_desktop_mode", return_value=True), \
             patch("subprocess.run") as run, \
             patch.object(self.app, "reload_config") as reload, \
             patch.object(self.app, "log_info") as log:
            self.app.edit_config()
        run.assert_called_once()
        reload.assert_not_called()
        logged = " ".join(str(c.args[0]) for c in log.call_args_list)
        self.assertIn("Reload Configuration", logged)

    def test_creates_default_config_when_missing(self):
        missing = Path(os.path.join(self.cfgdir, "nope", "config.py"))
        config_manager.config_file = missing
        with patch("xefm.app.is_desktop_mode", return_value=False), \
             patch.object(config_manager, "create_default_config",
                          return_value=True) as create, \
             patch.object(self.app, "reload_config"), \
             patch("subprocess.run") as run:
            # create_default_config is mocked True but doesn't make the file;
            # edit_config still proceeds to launch the editor on the path.
            self.app.edit_config()
        create.assert_called_once()
        run.assert_called_once()

    def test_aborts_when_default_config_cannot_be_created(self):
        config_manager.config_file = Path(os.path.join(self.cfgdir, "x", "config.py"))
        with patch.object(config_manager, "create_default_config",
                          return_value=False), \
             patch.object(self.app, "reload_config") as reload, \
             patch("subprocess.run") as run:
            self.app.edit_config()
        run.assert_not_called()
        reload.assert_not_called()


class ReloadConfig(ConfigReloadBase):
    def test_applies_new_keymap_and_editor_live(self):
        # Rebind 'help' to 'N' and change the editor; a minimal Config still
        # loads because reload fills missing fields from the template.
        self._write_config("""
            class Config:
                TEXT_EDITOR = 'nano'
                KEY_BINDINGS = {'help': ['N']}
        """)
        self.app.reload_config()
        self.assertEqual(self.app.config.TEXT_EDITOR, 'nano')
        # New keymap object, and 'N' now resolves to help.
        ev = MagicMock(key='n', char='n', modifiers=frozenset())
        self.assertEqual(self.app.keys.find_action_for_event(ev), 'help')

    def test_repoints_config_on_subsystems(self):
        self._write_config("""
            class Config:
                TEXT_EDITOR = 'nano'
        """)
        self.app.reload_config()
        new = self.app.config
        for holder in (self.app._fileops, self.app.flm, self.app.pm,
                       self.app.file_monitor, self.app.left_view,
                       self.app.right_view):
            self.assertIs(holder.config, new)

    def test_reports_validation_warnings_but_still_applies(self):
        self._write_config("""
            class Config:
                DEFAULT_SORT_MODE = 'bogus'
        """)
        with patch.object(self.app, "log_info") as log:
            self.app.reload_config()
        logged = " ".join(str(c.args[0]) for c in log.call_args_list)
        self.assertIn("Config warning", logged)
        self.assertEqual(self.app.config.DEFAULT_SORT_MODE, 'bogus')


if __name__ == "__main__":
    unittest.main()
