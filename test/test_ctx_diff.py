"""``ctx.diff(left, right)`` (#824): the diff viewer opened on two paths an
action names, rather than on the two selected files. Text pairs get the
side-by-side viewer, binary pairs the byte comparison, and a side may be a
virtual folder's file — an older version of a file, served by PATH_SCHEMES.

Run with: python -m pytest test/test_ctx_diff.py -v
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xefm import path_schemes  # noqa: E402
from xefm.diff_viewer import DiffViewer  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.path_base import ReadOnlyPathImpl, UriStatResult  # noqa: E402
from xefm.user_api import ActionContext  # noqa: E402

OLD = "one\ntwo\n"


class OldPathImpl(ReadOnlyPathImpl):
    """``old://a.txt`` — a.txt as it was."""

    SCHEME = "old"

    def exists(self):
        return self.key in ("", "a.txt")

    def is_dir(self):
        return self.key == ""

    def iterdir(self):
        if self.key == "":
            yield self.child("a.txt")

    def stat(self):
        return UriStatResult(size=len(OLD), mtime=0.0, is_dir=self.is_dir())

    def open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        return io.BytesIO(OLD.encode()) if "b" in mode else io.StringIO(OLD)


@pytest.fixture
def app(tmp_path):
    from puikit.backends import create_backend
    from xefm import app as xefm_app
    from xefm.state_manager import XeFMStateManager
    root = os.path.realpath(str(tmp_path))
    files = {"a.txt": "one\nthree\n", "b.txt": "one\ntwo\n",
             "x.bin": b"\x00\x01\x02", "y.bin": b"\x00\x01\x03"}
    for name, body in files.items():
        with open(os.path.join(root, name), "wb") as fh:
            fh.write(body if isinstance(body, bytes) else body.encode())
    os.mkdir(os.path.join(root, "sub"))
    backend = create_backend("memory")
    backend.open()
    a = xefm_app.XeFMApp(backend, root, root, left_provided=True,
                         right_provided=True,
                         state_manager=XeFMStateManager(
                             db_path=os.path.join(root, "state.db")))
    a.file_monitor.stop_monitoring()
    a.file_monitor.enabled = False
    a._settle_listings()
    a.root = root
    yield a
    backend.close()


def _viewer(app):
    layers = [layer for layer in app.panel._layers
              if isinstance(getattr(layer, "widget", layer), DiffViewer)]
    return getattr(layers[-1], "widget", layers[-1]) if layers else None


def _spy(monkeypatch, app):
    calls = []
    monkeypatch.setattr(app, "open_diff",
                        lambda left, right, titles=(None, None):
                        calls.append((str(left), str(right), titles)))
    return calls


def test_two_text_files_open_the_side_by_side_viewer(app):
    ActionContext(app).diff(os.path.join(app.root, "a.txt"),
                            os.path.join(app.root, "b.txt"))
    viewer = _viewer(app)
    assert viewer is not None
    assert viewer.titles == ("a.txt", "b.txt")


def test_titles_name_the_sides(app):
    ActionContext(app).diff(os.path.join(app.root, "a.txt"),
                            os.path.join(app.root, "b.txt"),
                            left_title="HEAD", right_title="Working tree")
    assert _viewer(app).titles == ("HEAD", "Working tree")


def test_entries_and_paths_are_accepted(app, monkeypatch):
    calls = _spy(monkeypatch, app)
    ctx = ActionContext(app)
    entry = next(e for e in ctx.pane.entries if e.name == "a.txt")
    ctx.diff(entry, Path(os.path.join(app.root, "b.txt")))
    assert calls == [(os.path.join(app.root, "a.txt"),
                      os.path.join(app.root, "b.txt"), (None, None))]


def test_binary_files_get_the_byte_comparison(app, monkeypatch):
    import xefm.app as module
    compared = []
    monkeypatch.setattr(module, "show_byte_comparison",
                        lambda panel, tasks, left, right, **kw:
                        compared.append((left.name, right.name)))
    ActionContext(app).diff(os.path.join(app.root, "x.bin"),
                            os.path.join(app.root, "y.bin"))
    assert compared == [("x.bin", "y.bin")]
    assert _viewer(app) is None


def test_a_virtual_folder_file_can_be_one_side(app):
    path_schemes.register("old", OldPathImpl, source="test-ctx-diff")
    try:
        ActionContext(app).diff("old://a.txt", os.path.join(app.root, "a.txt"),
                                left_title="HEAD")
        viewer = _viewer(app)
        assert viewer.titles == ("HEAD", "a.txt")
        assert viewer.lines1 == ["one", "two"]
    finally:
        path_schemes.unregister_source("test-ctx-diff")


@pytest.mark.parametrize("name", ["sub", "missing.txt"])
def test_a_folder_or_missing_file_is_not_compared(app, monkeypatch, name):
    calls = _spy(monkeypatch, app)
    logged = []
    monkeypatch.setattr(app, "log_info", logged.append)
    ActionContext(app).diff(os.path.join(app.root, name),
                            os.path.join(app.root, "a.txt"))
    assert calls == []
    assert logged and "is not a file" in logged[-1]


def test_a_relative_path_is_refused(app):
    with pytest.raises(ValueError, match="not an absolute path"):
        ActionContext(app).diff("a.txt", os.path.join(app.root, "b.txt"))


def test_diff_files_goes_through_open_diff(app, monkeypatch):
    calls = _spy(monkeypatch, app)
    pane = app.active_pane()
    pane["selected_files"] = {os.path.join(app.root, "a.txt"),
                              os.path.join(app.root, "b.txt")}
    app.diff_files()
    assert [(os.path.basename(a), os.path.basename(b)) for a, b, _ in calls] \
        == [("a.txt", "b.txt")]
