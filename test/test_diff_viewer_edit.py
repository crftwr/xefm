"""The file diff viewer's ``edit_file`` action launches the TEXT_DIFF tool.

Previously the configured ``TEXT_DIFF`` tool was reachable only from the
directory diff viewer's merge action; the per-file diff viewer offered no way
to edit the two sides it was showing. The ``edit_file`` binding now launches
the tool on both files, re-reads them when it returns (so the diff reflects
the merge), and notifies the opener via ``on_edited`` (the directory diff
viewer rescans, flipping a merged file's verdict live).
"""

from contextlib import contextmanager

import pytest

import xefm.diff_viewer as dv
from xefm.diff_viewer import DiffViewer


class _FakeBackend:
    def __init__(self):
        self.suspend_count = 0

    @contextmanager
    def suspended(self):
        self.suspend_count += 1
        yield


class _FakePanel:
    def __init__(self):
        self.backend = _FakeBackend()
        self.render_count = 0

    def render(self):
        self.render_count += 1


class _Config:
    def __init__(self, tool):
        if tool is not None:
            self.TEXT_DIFF = tool


@pytest.fixture
def files(tmp_path):
    p1, p2 = tmp_path / "a.txt", tmp_path / "b.txt"
    p1.write_text("one\ntwo\n")
    p2.write_text("one\nTWO\n")
    return p1, p2


def _viewer(files, monkeypatch, tool, run=None, on_edited=None):
    """A DiffViewer on ``files`` with the config, subprocess, and panel faked."""
    monkeypatch.setattr(dv, "get_config", lambda: _Config(tool))
    calls = []
    monkeypatch.setattr(dv.subprocess, "run",
                        run if run is not None else lambda argv: calls.append(argv))
    viewer = DiffViewer(files[0], files[1], on_edited=on_edited)
    viewer._panel = _FakePanel()
    return viewer, calls


def test_edit_runs_tool_on_both_files_and_reloads(files, monkeypatch):
    p1, p2 = files
    edited = []

    def run(argv):
        p2.write_text(p1.read_text())  # the tool merges right := left

    viewer, _ = _viewer(files, monkeypatch, ["difftool", "--flag"], run=run,
                        on_edited=lambda: edited.append(True))
    assert viewer.blocks  # the files differ before the edit
    viewer._edit_in_tool()
    assert viewer.blocks == []          # reloaded: sides now identical
    assert viewer.lines1 == viewer.lines2 == ["one", "two"]
    assert edited == [True]
    assert viewer._panel.backend.suspend_count == 1
    assert viewer._panel.render_count == 1


def test_list_tool_gets_both_paths_appended(files, monkeypatch):
    viewer, calls = _viewer(files, monkeypatch, ["difftool", "--flag"])
    viewer._edit_in_tool()
    assert calls == [["difftool", "--flag", str(files[0]), str(files[1])]]


def test_string_tool_is_shlex_split(files, monkeypatch):
    viewer, calls = _viewer(files, monkeypatch, 'difftool --opt "a b"')
    viewer._edit_in_tool()
    assert calls == [["difftool", "--opt", "a b", str(files[0]), str(files[1])]]


def test_missing_tool_notifies_and_does_not_run(files, monkeypatch):
    viewer, calls = _viewer(files, monkeypatch, None)
    notes = []
    monkeypatch.setattr(viewer, "_notify", notes.append)
    viewer._edit_in_tool()
    assert calls == []
    assert notes == ["No TEXT_DIFF tool is configured."]


def test_remote_path_notifies_and_does_not_run(files, monkeypatch):
    viewer, calls = _viewer(files, monkeypatch, ["difftool"])
    viewer.path2 = "s3://bucket/b.txt"
    notes = []
    monkeypatch.setattr(viewer, "_notify", notes.append)
    viewer._edit_in_tool()
    assert calls == []
    assert notes == ["Editing is only available for local files."]


def test_command_not_found_notifies(files, monkeypatch):
    def run(argv):
        raise FileNotFoundError(argv[0])

    viewer, _ = _viewer(files, monkeypatch, ["nosuchtool"], run=run)
    notes = []
    monkeypatch.setattr(viewer, "_notify", notes.append)
    viewer._edit_in_tool()
    assert notes == ["Command not found: nosuchtool"]
