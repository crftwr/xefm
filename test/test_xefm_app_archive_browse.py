"""Archive virtual-directory browsing (XeFMApp).

Pressing Enter on a recognised archive file enters it as an ``archive://…#``
virtual directory: the normal listing/navigation machinery then browses it via
ArchivePathImpl (iterdir/is_dir/read_bytes) and returns the real containing
directory as the archive root's parent, so "up" exits on its own. Archives are
read-only, so the write-side operations (copy/move-in, move-out, create, rename,
delete, archive/extract) refuse an ``archive://`` path.

Run with: python -m pytest test/test_xefm_app_archive_browse.py -v
"""

import os
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402


class FakeEntry:
    """A stand-in pane entry: a name, a dir/file flag, and a string identity
    (used by ``_is_archive`` and the ``archive://`` URI construction)."""

    def __init__(self, name, *, is_dir=False, path_str=None, abspath=None):
        self.name = name
        self._is_dir = is_dir
        self._path_str = path_str if path_str is not None else name
        self._abspath = abspath if abspath is not None else "/abs/" + name

    def is_dir(self):
        return self._is_dir

    def absolute(self):
        return self._abspath

    def __str__(self):
        return self._path_str


def _pane(path, files=None):
    return {
        "path": path, "files": list(files or []), "file_info": {},
        "focused_index": 0, "scroll_offset": 0, "virtual": None,
        "filter_pattern": "", "sort_mode": "name", "sort_reverse": False,
        "selected_files": set(),
    }


class _RecordingFileOps:
    def __init__(self):
        self.calls = []

    def copy(self, *a, **k):
        self.calls.append("copy")

    def move(self, *a, **k):
        self.calls.append("move")

    def delete(self, *a, **k):
        self.calls.append("delete")


def _app():
    """A bare XeFMApp with just the collaborators the tested methods touch."""
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app.logs = []
    app.log_info = app.logs.append
    app._refresh_calls = []
    app._refresh = lambda pane, on_ready=None: app._refresh_calls.append((pane, on_ready))
    app._remember_cursor = lambda pane: None
    app._restore_remembered_cursor = lambda pane: None
    app._exit_virtual = lambda pane: pane.__setitem__("virtual", None)
    app._fileops = _RecordingFileOps()
    app.panel = object()
    app.state_manager = None  # viewer opens without per-type mode memory here
    return app


def _stub_config():
    return types.SimpleNamespace(
        SHOW_HIDDEN_FILES=True, DATE_FORMAT="%Y-%m-%d %H:%M",
        MAX_EXTENSION_LENGTH=5)


# --------------------------------------------------------------------------- #
# _open: entering archives
# --------------------------------------------------------------------------- #

class TestOpenEntersArchive(unittest.TestCase):
    def test_enters_recognised_archive_file(self):
        app = _app()
        pane = _pane("/home/me", [FakeEntry("foo.zip", abspath="/home/me/foo.zip")])
        app._open(pane)
        self.assertEqual(str(pane["path"]), "archive:///home/me/foo.zip#")
        self.assertTrue(app._is_archive(pane["path"]))
        self.assertEqual(len(app._refresh_calls), 1)

    def test_recognises_tar_gz(self):
        app = _app()
        pane = _pane("/d", [FakeEntry("bundle.tar.gz", abspath="/d/bundle.tar.gz")])
        app._open(pane)
        self.assertEqual(str(pane["path"]), "archive:///d/bundle.tar.gz#")

    def test_does_not_nest_archive_in_archive(self):
        # A .zip that itself lives inside a browsed archive must not be re-wrapped.
        app = _app()
        nested = FakeEntry("inner.zip", path_str="archive:///d/outer.zip#inner.zip")
        pane = _pane("archive:///d/outer.zip#", [nested])
        app._open(pane)
        self.assertEqual(pane["path"], "archive:///d/outer.zip#")  # unchanged
        self.assertEqual(app._refresh_calls, [])

    def test_plain_file_opens_builtin_viewer(self):
        # A non-directory, non-archive file opens in the built-in viewer (issue
        # #212) — it is not treated as a directory/archive (no path change, no
        # relist).
        app = _app()
        entry = FakeEntry("notes.txt", abspath="/d/notes.txt")
        pane = _pane("/d", [entry])
        with patch("xefm.app.show_text_viewer") as show:
            app._open(pane)
        show.assert_called_once()
        self.assertIs(show.call_args.args[1], entry)  # opened on the focused file
        self.assertEqual(pane["path"], "/d")
        self.assertEqual(app._refresh_calls, [])

    def test_directory_navigation_still_works(self):
        # Regression: a real directory still enters as itself, not as an archive.
        app = _app()
        sub = FakeEntry("sub", is_dir=True, path_str="/d/sub")
        pane = _pane("/d", [sub])
        app._open(pane)
        self.assertIs(pane["path"], sub)
        self.assertEqual(len(app._refresh_calls), 1)


# --------------------------------------------------------------------------- #
# helpers: _is_archive + header label
# --------------------------------------------------------------------------- #

class TestArchiveHelpers(unittest.TestCase):
    def test_is_archive(self):
        self.assertTrue(xefm_app.XeFMApp._is_archive("archive:///d/foo.zip#sub"))
        self.assertFalse(xefm_app.XeFMApp._is_archive("/d/foo.zip"))
        self.assertFalse(xefm_app.XeFMApp._is_archive("ssh://host/d"))

    def test_header_label_root(self):
        self.assertEqual(xefm_app._archive_header_label("archive:///d/foo.zip#"), "[foo.zip]")

    def test_header_label_nested(self):
        self.assertEqual(
            xefm_app._archive_header_label("archive:///d/foo.zip#src/x"), "[foo.zip]/src/x")

    def test_header_label_malformed_falls_back(self):
        raw = "archive:///d/foo.zip"  # no '#'
        self.assertEqual(xefm_app._archive_header_label(raw), raw)


# --------------------------------------------------------------------------- #
# read-only write guards
# --------------------------------------------------------------------------- #

class TestWriteGuards(unittest.TestCase):
    def _transfer_app(self, src_path, dst_path):
        app = _app()
        src, dst = _pane(src_path), _pane(dst_path)
        app.active_pane = lambda: src

        class _PM:
            def get_inactive_pane(self_inner):
                return dst
        app.pm = _PM()
        app._selected_or_focused = lambda pane: [FakeEntry("x", abspath="/abs/x")]
        return app, src, dst

    def test_copy_into_archive_refused(self):
        app, src, dst = self._transfer_app("/real", "archive:///d/foo.zip#")
        app._transfer("copy")
        self.assertEqual(app._fileops.calls, [])
        self.assertTrue(any("read-only archive" in m for m in app.logs))

    def test_move_out_of_archive_refused(self):
        app, src, dst = self._transfer_app("archive:///d/foo.zip#", "/real")
        app._transfer("move")
        self.assertEqual(app._fileops.calls, [])
        self.assertTrue(any("use copy instead" in m for m in app.logs))

    def test_copy_out_of_archive_allowed(self):
        # Copy (not move) out of an archive to a real pane reaches the file ops.
        app, src, dst = self._transfer_app("archive:///d/foo.zip#", "/real")
        app._transfer("copy")
        self.assertEqual(app._fileops.calls, ["copy"])

    def test_delete_inside_archive_refused(self):
        app = _app()
        pane = _pane("archive:///d/foo.zip#")
        app.active_pane = lambda: pane
        app._selected_or_focused = lambda p: [
            FakeEntry("x", path_str="archive:///d/foo.zip#x")]
        app.delete_files()
        self.assertEqual(app._fileops.calls, [])
        self.assertTrue(any("read-only archive" in m for m in app.logs))

    def test_rename_inside_archive_refused(self):
        app = _app()
        pane = _pane("archive:///d/foo.zip#",
                     [FakeEntry("x", path_str="archive:///d/foo.zip#x")])
        app.active_pane = lambda: pane
        app.rename()
        self.assertTrue(any("read-only archive" in m for m in app.logs))


# --------------------------------------------------------------------------- #
# integration: a real zip, entered and listed through the real machinery
# --------------------------------------------------------------------------- #

class TestRealArchiveIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.tmp, "sample.zip")
        with zipfile.ZipFile(self.zip_path, "w") as zf:
            zf.writestr("readme.txt", "hello archive\n")
            zf.writestr("src/main.py", "print('hi')\n")

    def test_open_builds_listable_uri(self):
        app = _app()
        entry = FakeEntry("sample.zip", abspath=self.zip_path)
        pane = _pane(self.tmp, [entry])
        app._open(pane)

        # The URI _open built lists the archive's top level via the real FLM.
        flm = FileListManager(_stub_config())
        flm.show_hidden = True
        result = flm.compute_listing(Path(str(pane["path"])))
        self.assertTrue(result["ok"])
        names = sorted(p.name for p in result["files"])
        self.assertEqual(names, ["readme.txt", "src"])

    def test_file_inside_archive_reads_back(self):
        uri = f"archive://{self.zip_path}#readme.txt"
        self.assertEqual(Path(uri).read_text(), "hello archive\n")

    def test_archive_root_parent_is_real_dir(self):
        # "Up" out of the archive root lands on the real containing directory.
        root = Path(f"archive://{self.zip_path}#")
        self.assertEqual(str(root.parent), str(Path(self.tmp)))


if __name__ == "__main__":
    unittest.main()
