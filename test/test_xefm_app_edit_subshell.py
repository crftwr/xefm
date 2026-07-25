"""
Editor / subshell hand-off for the PuiKit XeFMApp.

``edit_file`` (E) and ``subshell`` (Shift-X) both hand the terminal to a
full-screen child via ``backend.suspended()`` (a no-op on the headless memory
backend used here; the curses backend does the real endwin/reset_prog_mode
dance). We verify the wiring: the right argv/cwd, the suspend hand-off, the
post-run pane refresh, and the local-only guards. ``subprocess.run`` is mocked
so nothing actually launches.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class EditSubshellBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "note.txt")
        open(self.file, "w").close()
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                              left_provided=True, right_provided=True)

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _focus(self, name):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(name)


class EditFile(EditSubshellBase):
    def test_launches_editor_on_focused_file(self):
        self._focus("note.txt")
        with patch("subprocess.run") as run:
            self.app.edit_file()
        run.assert_called_once()
        argv = run.call_args.args[0]
        # The pane path is resolve()'d at startup (e.g. /var -> /private/var on
        # macOS), so compare against the actual focused entry, not self.file.
        self.assertEqual(argv[-1], str(self.app._focused_entry()))
        self.assertIn(self.app.config.TEXT_EDITOR.split()[0], argv[0])

    def test_hands_terminal_over_via_suspended(self):
        self._focus("note.txt")
        suspended_cm = MagicMock()
        suspended_cm.__enter__ = MagicMock()
        suspended_cm.__exit__ = MagicMock(return_value=False)
        with patch.object(self.app.backend, "suspended", return_value=suspended_cm), \
             patch("subprocess.run"):
            self.app.edit_file()
        suspended_cm.__enter__.assert_called_once()

    def test_refreshes_panes_after_edit(self):
        self._focus("note.txt")
        # A file created "while editing" should appear after the run.
        def fake_run(*a, **k):
            open(os.path.join(self.tmp, "created.txt"), "w").close()
        with patch("subprocess.run", side_effect=fake_run):
            self.app.edit_file()
        names = [f.name for f in self.app.pm.left_pane["files"]]
        self.assertIn("created.txt", names)

    def test_skips_directory(self):
        os.makedirs(os.path.join(self.tmp, "adir"))
        self.app._refresh(self.app.active_pane())
        self.app._settle_listings()  # _refresh lists on a worker; wait for it
        self._focus("adir")
        with patch("subprocess.run") as run:
            self.app.edit_file()
        run.assert_not_called()

    def test_skips_remote_path(self):
        pane = self.app.active_pane()
        pane["files"] = [Path("ssh://host/remote.txt")]
        pane["focused_index"] = 0
        with patch("subprocess.run") as run:
            self.app.edit_file()
        run.assert_not_called()


class Subshell(EditSubshellBase):
    def test_launches_shell_in_active_pane_dir(self):
        with patch.dict(os.environ, {"SHELL": "/bin/zsh"}, clear=False), \
             patch("subprocess.run") as run:
            self.app.subshell()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/bin/zsh"])
        self.assertEqual(run.call_args.kwargs["cwd"],
                         str(self.app.active_pane()["path"]))

    def test_skips_remote_directory(self):
        self.app.active_pane()["path"] = Path("s3://bucket/")
        with patch("subprocess.run") as run:
            self.app.subshell()
        run.assert_not_called()


class IsLocal(unittest.TestCase):
    def test_local_and_remote(self):
        self.assertTrue(xefm_app.XeFMApp._is_local(Path("/tmp/x")))
        for remote in ("ssh://h/p", "s3://b/k", "scp://h/p", "archive:///a"):
            self.assertFalse(xefm_app.XeFMApp._is_local(remote))


if __name__ == "__main__":
    unittest.main()
