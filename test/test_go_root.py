"""``go_root`` — jump to the top of whatever the pane is showing (issue #353).

The point of the action is that one behavior is right everywhere: ``Path.anchor``
names the drive root on Windows, ``/`` on POSIX, the bucket root on S3 and the
host root over SFTP, so nothing here branches on the platform. These tests pin
that, the cursor landing, and the default binding reaching an old config.
"""

import os
import sys
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit import Event, EventType  # noqa: E402

from xefm import _config  # noqa: E402
from xefm import actions as _ctx  # noqa: E402
from xefm import app as xefm_app  # noqa: E402
from xefm.config import KeyBindings  # noqa: E402
from xefm.path import Path  # noqa: E402


def _bare_app():
    """A XeFMApp shell — ``_go_root`` needs no backend, only a pane dict."""
    return xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)


def _pane(path, **extra):
    pane = {"path": Path(path), "files": [], "focused_index": 0,
            "selected_files": set()}
    pane.update(extra)
    return pane


class TopLevelName(unittest.TestCase):
    """The branch under the root that the pane came up through — what the cursor
    lands on, the way ``go_parent`` lands on the child it left."""

    def _name(self, path):
        p = Path(path)
        return _bare_app()._top_level_name(p, Path(p.anchor))

    def test_local_path(self):
        self.assertEqual(self._name("/Users/someone/projects"), "Users")

    def test_directly_under_root(self):
        self.assertEqual(self._name("/Users"), "Users")

    def test_root_itself_has_no_branch(self):
        self.assertIsNone(self._name("/"))

    def test_s3_key_lands_on_the_top_prefix(self):
        self.assertEqual(self._name("s3://bucket/logs/2026/app.log"), "logs")

    def test_walk_is_bounded(self):
        """A backend whose parents never reach the root must not hang the UI
        thread — the walk gives up instead of looping."""
        class _Endless:
            name = "x"

            def __init__(self, depth=0):
                self._depth = depth

            @property
            def parent(self):
                return _Endless(self._depth + 1)

            def __str__(self):
                return f"endless:{self._depth}"

        self.assertIsNone(_bare_app()._top_level_name(_Endless(), Path("/")))


class GoRoot(unittest.TestCase):
    def _run(self, pane):
        app = _bare_app()
        calls = []
        with patch.object(xefm_app.XeFMApp, "_go_to_dir",
                          side_effect=lambda *a: calls.append(a)), \
             patch.object(xefm_app.XeFMApp, "log_info"):
            app._go_root(pane)
        return calls

    def test_jumps_to_the_anchor_and_lands_on_the_branch(self):
        pane = _pane("/Users/someone/projects")
        (dest, target, focus), = self._run(pane)
        self.assertIs(dest, pane)
        self.assertEqual(str(target), "/")
        self.assertEqual(focus, "Users")

    def test_s3_stops_at_the_bucket(self):
        """``s3://`` alone names nothing XeFM can list, so the bucket is the top."""
        (dest, target, focus), = self._run(_pane("s3://bucket/logs/2026/"))
        self.assertEqual(str(target), "s3://bucket/")
        self.assertEqual(focus, "logs")

    def test_sftp_stops_at_the_host_root(self):
        (dest, target, focus), = self._run(_pane("ssh://myhost/var/log"))
        self.assertEqual(str(target), "ssh://myhost/")
        self.assertEqual(focus, "var")

    def test_already_at_root_does_not_navigate(self):
        self.assertEqual(self._run(_pane("/")), [])

    def test_virtual_pane_at_root_still_navigates(self):
        """A search-results pane shows a result set, not its path — jumping to
        the root has to leave virtual mode even when the path already is one."""
        (dest, target, focus), = self._run(_pane("/", virtual=True))
        self.assertEqual(str(target), "/")


class DefaultBinding(unittest.TestCase):
    """Resolved through the ``filer`` context, the way the file list asks."""

    BACKSLASH = Event(type=EventType.KEY, key="\\", char="\\",
                      modifiers=frozenset())

    def test_backslash_resolves_to_go_root(self):
        kb = KeyBindings(_config.Config.KEY_BINDINGS)
        self.assertEqual(
            kb.find_action_for_event(self.BACKSLASH, context=_ctx.FILER),
            "go_root")

    def test_config_predating_the_action_still_gets_the_key(self):
        """``_copy_missing_fields`` can add a missing config *field* but never a
        missing key inside ``KEY_BINDINGS``, so the registry default is what has
        to reach an existing ~/.xefm/config.py — and only the context lookup
        consults it, which is the one the file list uses."""
        older = {name: keys for name, keys in _config.Config.KEY_BINDINGS.items()
                 if name != "go_root"}
        kb = KeyBindings(older)
        self.assertEqual(
            kb.find_action_for_event(self.BACKSLASH, context=_ctx.FILER),
            "go_root")


if __name__ == "__main__":
    unittest.main()
