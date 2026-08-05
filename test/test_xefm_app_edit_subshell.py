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
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class EditSubshellBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "note.txt")
        open(self.file, "w").close()
        # Temp state DB, never the real ~/.xefm/state.db: the app restores each
        # pane's sort mode, sort direction and filter from it, so the developer's
        # own last-used settings would otherwise decide these panes' row order.
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
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
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _focus(self, name):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(name)


class EditFile(EditSubshellBase):
    def test_launches_editor_on_focused_file(self):
        self._focus("note.txt")
        # The pane path is resolve()'d at startup (e.g. /var -> /private/var on
        # macOS), so compare against the actual focused entry, not self.file.
        # Read before the call: returning re-lists both panes on workers, which
        # empties them until the results land.
        entry = self.app._focused_entry()
        with patch("subprocess.run") as run:
            self.app.edit_file()
        run.assert_called_once()
        argv = run.call_args.args[0]
        self.assertEqual(argv[-1], str(entry))
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
        self.app._settle_listings()  # the post-edit re-list runs on a worker
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


class EditSelectedFiles(EditSubshellBase):
    """E opens *all* selected files, not just the focused one (#273)."""

    def _make(self, *names):
        for name in names:
            open(os.path.join(self.tmp, name), "w").close()
        self.app._refresh(self.app.active_pane())
        self.app._settle_listings()

    def _select(self, *names):
        pane = self.app.active_pane()
        pane["selected_files"] = {str(f) for f in pane["files"]
                                  if f.name in names}

    def test_opens_all_selected_in_one_editor_run(self):
        self._make("a.txt", "b.txt")
        self._select("a.txt", "b.txt")
        pane = self.app.active_pane()
        expected = [str(f) for f in pane["files"] if f.name in ("a.txt", "b.txt")]
        with patch("subprocess.run") as run:
            self.app.edit_file()
        run.assert_called_once()
        argv = run.call_args.args[0]
        self.assertEqual(argv[-2:], expected)
        self.assertIn(self.app.config.TEXT_EDITOR.split()[0], argv[0])

    def test_selection_skips_directories(self):
        self._make("a.txt")
        os.makedirs(os.path.join(self.tmp, "adir"))
        self.app._refresh(self.app.active_pane())
        self.app._settle_listings()
        self._select("a.txt", "adir")
        pane = self.app.active_pane()
        expected = [str(f) for f in pane["files"] if f.name == "a.txt"]
        with patch("subprocess.run") as run:
            self.app.edit_file()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-1:], expected)

    def test_association_batches_share_one_launch(self):
        self._make("a.md", "b.md", "c.txt")
        self._select("a.md", "b.md", "c.txt")
        pane = self.app.active_pane()
        md = [str(f) for f in pane["files"] if f.name.endswith(".md")]
        txt = [str(f) for f in pane["files"] if f.name == "c.txt"]

        def assoc(name, verb):
            return ["mdedit"] if name.endswith(".md") else None

        # Pin terminal mode (is_desktop_mode caches process-global detection
        # other tests can pollute) so both launches go through subprocess.run.
        with patch("xefm.app.get_program_for_file", side_effect=assoc), \
             patch("xefm.app.has_explicit_association", return_value=False), \
             patch("xefm.app.is_desktop_mode", return_value=False), \
             patch("subprocess.run") as run:
            self.app.edit_file()
        # One run for the .md pair (mdedit a.md b.md), one TEXT_EDITOR run
        # for the leftover .txt.
        argvs = [c.args[0] for c in run.call_args_list]
        self.assertEqual(len(argvs), 2)
        self.assertEqual(argvs[0], ["mdedit"] + md)
        self.assertEqual(argvs[1][-1:], txt)

    def test_explicit_none_association_is_skipped(self):
        self._make("a.pdf")
        self._select("a.pdf")
        with patch("xefm.app.get_program_for_file", return_value=None), \
             patch("xefm.app.has_explicit_association", return_value=True), \
             patch("subprocess.run") as run:
            self.app.edit_file()
        run.assert_not_called()


class Subshell(EditSubshellBase):
    # is_desktop_mode() caches process-global detection that other tests in the
    # same worker can pollute (XEFM_BACKEND, loaded GUI modules); pin it so the
    # terminal-only guard doesn't fire order-dependently.
    def test_launches_shell_in_active_pane_dir(self):
        with patch.dict(os.environ, {"SHELL": "/bin/zsh"}, clear=False), \
             patch("xefm.app.is_desktop_mode", return_value=False), \
             patch("subprocess.run") as run:
            self.app.subshell()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/bin/zsh"])
        self.assertEqual(run.call_args.kwargs["cwd"],
                         str(self.app.active_pane()["path"]))

    def test_skips_remote_directory(self):
        self.app.active_pane()["path"] = Path("s3://bucket/")
        with patch("xefm.app.is_desktop_mode", return_value=False), \
             patch("subprocess.run") as run:
            self.app.subshell()
        run.assert_not_called()


class IsLocal(unittest.TestCase):
    def test_local_and_remote(self):
        self.assertTrue(xefm_app.XeFMApp._is_local(Path("/tmp/x")))
        for remote in ("ssh://h/p", "s3://b/k", "scp://h/p", "archive:///a"):
            self.assertFalse(xefm_app.XeFMApp._is_local(remote))


if __name__ == "__main__":
    unittest.main()
