"""Jump-to-Path (Shift-J): input resolution, remote URIs (#318), and the file
destination (#351).

``XeFMApp._resolve_jump_target`` turns the dialog's text into a
:class:`xefm.path.Path` against the pane's current directory. Local input keeps
the historical rules (``~`` expansion, relative join, ``os.path.normpath``);
a remote URI (``s3://…``, ``ssh://…``) must be taken as-is — ``os.path.isabs``
calls it relative and ``normpath`` collapses ``scheme://`` to ``scheme:/``,
which is exactly the bug this guards against.

``jump_to_path`` itself then accepts a *file* path as well as a directory: the
pane goes to the file's directory and the cursor lands on the file.

Run with: python -m pytest test/test_jump_to_path.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.app import XeFMApp  # noqa: E402


def resolve(text, current):
    return str(XeFMApp._resolve_jump_target(text, current))


# --- local paths keep the historical behaviour --------------------------------


def test_absolute_local_path():
    assert resolve("/usr/lib", "/home/user") == os.path.normpath("/usr/lib")


def test_relative_local_path_joins_current():
    assert resolve("sub", "/home/user") == os.path.normpath("/home/user/sub")


def test_relative_local_path_normalizes_dotdot():
    assert resolve("../other", "/home/user/x") == os.path.normpath("/home/user/other")


def test_tilde_expands_to_home():
    assert resolve("~/sub", "/elsewhere") == os.path.normpath(
        os.path.join(os.path.expanduser("~"), "sub"))


def test_surrounding_whitespace_is_stripped():
    assert resolve("  /usr/lib  ", "/home/user") == os.path.normpath("/usr/lib")


# --- remote URIs are taken as-is (issue #318) ---------------------------------


def test_s3_uri_keeps_scheme():
    assert resolve("s3://bucket/key/path", "/home/user") == "s3://bucket/key/path"


def test_s3_uri_keeps_scheme_from_remote_pane():
    assert resolve("s3://other-bucket/x", "s3://bucket/dir") == "s3://other-bucket/x"


def test_ssh_uri_keeps_scheme():
    assert resolve("ssh://host/var/log", "/home/user") == "ssh://host/var/log"


def test_relative_input_joins_remote_current():
    # Typing a bare child name while the pane shows an S3 directory must stay
    # inside that S3 directory — and must not be normpath-mangled.
    result = resolve("sub", "s3://bucket/dir")
    assert result.startswith("s3://bucket/dir")
    assert result.rstrip("/").endswith("/sub")


def test_absolute_local_input_leaves_remote_pane():
    # An absolute local path typed while browsing S3 jumps to the local path.
    assert resolve("/usr/lib", "s3://bucket/dir") == os.path.normpath("/usr/lib")


# --- a file path is a destination too (#351) ----------------------------------


class _AcceptImmediately:
    """Stands in for ``show_input``: no dialog, just accept ``text``. Records
    the keyword arguments so the completer's configuration can be asserted."""

    def __init__(self, text):
        self.text = text
        self.kwargs = None
        self.error = "not called"

    def __call__(self, panel, *, on_accept, validate=None, **kwargs):
        self.kwargs = kwargs
        self.error = validate(self.text) if validate is not None else None
        if self.error is None:
            on_accept(self.text)


class JumpToAFile(unittest.TestCase):
    """A headless XeFMApp on the memory backend over a real temp tree."""

    def setUp(self):
        from xefm.state_manager import XeFMStateManager
        from puikit.backends import create_backend
        # realpath: on macOS /var is a symlink to /private/var, and the app
        # resolves the paths it is started with — so a raw mkdtemp() name would
        # not compare equal to the pane's own path.
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.cfgdir = tempfile.mkdtemp()
        self.sub = os.path.join(self.tmp, "sub")
        os.mkdir(self.sub)
        for n in ("a.txt", "b.txt", "c.txt"):
            open(os.path.join(self.sub, n), "w").close()
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        # Both panes start at the temp root, above the file being jumped to.
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

    def _jump(self, text):
        stub = _AcceptImmediately(text)
        with mock.patch.object(xefm_app, "show_input", stub):
            self.app.jump_to_path()
        self.app._settle_listings()
        return stub

    def _pane(self):
        return self.app.active_pane()

    def _focused_name(self):
        pane = self._pane()
        files = pane["files"]
        return files[pane["focused_index"]].name if files else None

    def test_file_path_enters_its_directory_and_focuses_it(self):
        stub = self._jump(os.path.join(self.sub, "b.txt"))
        self.assertIsNone(stub.error)
        self.assertEqual(str(self._pane()["path"]), self.sub)
        self.assertEqual(self._focused_name(), "b.txt")

    def test_directory_path_still_just_navigates(self):
        self._jump(self.sub)
        self.assertEqual(str(self._pane()["path"]), self.sub)
        # No name to land on: the cursor is left where the pane put it.
        self.assertEqual(self._pane()["focused_index"], 0)

    def test_relative_file_path_resolves_against_the_pane(self):
        self._jump(os.path.join("sub", "c.txt"))
        self.assertEqual(str(self._pane()["path"]), self.sub)
        self.assertEqual(self._focused_name(), "c.txt")

    def test_missing_path_is_still_rejected(self):
        stub = self._jump(os.path.join(self.sub, "nope.txt"))
        self.assertIsNotNone(stub.error)
        self.assertEqual(str(self._pane()["path"]), self.tmp)

    def test_empty_input_is_still_rejected(self):
        stub = self._jump("   ")
        self.assertIsNotNone(stub.error)
        self.assertEqual(str(self._pane()["path"]), self.tmp)

    def test_completion_offers_files(self):
        """A file is a valid destination, so it must be completable."""
        stub = self._jump(self.sub)
        self.assertFalse(stub.kwargs["completer"].directories_only)


if __name__ == "__main__":
    unittest.main()
