"""The U key extracts the *selection*, not just the cursor entry (issue #408).

Covers what ``XeFMApp.extract_archive`` makes of a multi-item selection: every
archive in it is extracted, entries that are not readable archives are skipped
and reported, a single target keeps its own diagnosis, and one archive failing
does not sink the rest of the batch.

Run with: python -m pytest test/test_extract_archive_selection.py -v
"""

import io
import os
import sys
import tarfile
import types
import zipfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.progress_manager import ProgressManager  # noqa: E402
from xefm.task import TaskManager  # noqa: E402


class _InlineTasks(TaskManager):
    """The real task manager forced into synchronous mode: these tests drive a
    bare app with no live panel to host a progress dialog, and none of their
    archives is encrypted, so nothing needs the worker's UI bridge."""

    def submit(self, task, panel, **kw):
        kw["background"] = False
        return super().submit(task, panel, **kw)


def _zip(tmp_path, name, member="a.txt", data=b"hello"):
    p = tmp_path / name
    with zipfile.ZipFile(str(p), "w") as zf:
        zf.writestr(member, data)
    return Path(str(p))


def _targz(tmp_path, name, member="a.txt", data=b"hello"):
    p = tmp_path / name
    with tarfile.open(str(p), "w:gz") as tf:
        info = tarfile.TarInfo(name=member)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return Path(str(p))


def _app(files, selected, dest_dir, *, focused=0, confirm=False):
    """A bare XeFMApp whose active pane holds ``files`` with ``selected`` marked
    and the cursor on ``files[focused]``, extracting into ``dest_dir``."""
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app.logs = []
    app.log_info = app.logs.append
    app.panel = types.SimpleNamespace(render=lambda: None)
    app._active_pane_region = lambda: (0.0, 80.0)
    app.state_manager = None
    pane = {"files": list(files), "focused_index": focused,
            "selected_files": {str(f) for f in selected}}
    app.active_pane = lambda: pane
    app.pm = types.SimpleNamespace(get_inactive_pane=lambda: {"path": dest_dir})
    app._relist = lambda pane_, **kw: None
    app.config = types.SimpleNamespace(CONFIRM_EXTRACT_ARCHIVE=confirm)
    app.tasks = _InlineTasks()
    return app


@pytest.fixture
def dest(tmp_path):
    d = tmp_path / "dest"
    d.mkdir()
    return Path(str(d))


def test_every_selected_archive_is_extracted(tmp_path, dest):
    one = _zip(tmp_path, "one.zip", "x.txt", b"1")
    two = _zip(tmp_path, "two.zip", "y.txt", b"2")
    app = _app([one, two], [one, two], dest)

    assert app.extract_archive() is False
    assert (tmp_path / "dest" / "one" / "x.txt").read_bytes() == b"1"
    assert (tmp_path / "dest" / "two" / "y.txt").read_bytes() == b"2"
    assert any("Extracted 2 archive(s)" in m for m in app.logs)


def test_the_batch_runs_as_one_operation_counted_up_front(tmp_path, dest, monkeypatch):
    """A batch is counted once, in full, before any of it is written.

    The bar used to be restarted for each archive and rewind to zero every time,
    with a total that was a member count — so one 4 GiB member went past at the
    same speed as a 4 KiB one. Now the survey opens every archive first (the
    encryption gate had to open them anyway), one total covers the lot, and the
    bytes published alongside it weight the bar. It lands exactly on full."""
    one = _zip(tmp_path, "one.zip", "x.txt", b"1" * 100)
    two = _zip(tmp_path, "two.zip", "y.txt", b"2" * 250)
    app = _app([one, two], [one, two], dest)

    starts, totals, finished = [], [], []
    real_start = ProgressManager.start_operation
    real_total = ProgressManager.update_operation_total
    real_finish = ProgressManager.finish_operation

    def start_operation(self, *a, **kw):
        starts.append(a)
        return real_start(self, *a, **kw)

    def update_operation_total(self, items, description="", total_bytes=0):
        totals.append((items, total_bytes))
        return real_total(self, items, description, total_bytes)

    def finish_operation(self):
        finished.append(dict(self.current_operation or {}))
        return real_finish(self)

    monkeypatch.setattr(ProgressManager, "start_operation", start_operation)
    monkeypatch.setattr(ProgressManager, "update_operation_total",
                        update_operation_total)
    monkeypatch.setattr(ProgressManager, "finish_operation", finish_operation)

    app.extract_archive()

    assert len(starts) == 1                 # one operation, not one per archive
    assert totals == [(2, 350)]             # both archives' members and payloads
    end = finished[-1]
    assert end["processed_items"] == end["total_items"] == 2
    assert end["processed_bytes"] == end["total_bytes"] == 350


def test_formats_with_different_totals_still_add_up(tmp_path, dest, monkeypatch):
    """Each format counts its own members its own way — a zip from ``infolist()``,
    a tar from ``getmembers()``, a 7z off the headers it walked at open. One
    batch bar is scaled from the *sum*, so any one of them over- or
    under-promising leaves it stuck short of full or clipped at it."""
    z = _zip(tmp_path, "one.zip", "x.txt", b"1" * 100)
    t = _targz(tmp_path, "two.tar.gz", "y.bin", b"2" * 250)
    app = _app([z, t], [z, t], dest)

    ends = []
    real_finish = ProgressManager.finish_operation

    def finish_operation(self):
        ends.append(dict(self.current_operation or {}))
        return real_finish(self)

    monkeypatch.setattr(ProgressManager, "finish_operation", finish_operation)

    app.extract_archive()
    end = ends[-1]
    assert end["processed_items"] == end["total_items"] == 2
    assert end["processed_bytes"] == end["total_bytes"] == 350


def test_an_unreadable_archive_is_left_out_of_the_total(tmp_path, dest):
    """A file the survey cannot open promises nothing rather than promising
    bytes that will never arrive — a bar told about them would stick short of
    full. The extraction that follows is what reports why it failed."""
    good = _zip(tmp_path, "good.zip", "x.txt", b"1" * 100)
    bad = tmp_path / "broken.zip"
    bad.write_bytes(b"not a zip at all")
    app = _app([good, Path(str(bad))], [good, Path(str(bad))], dest)

    surveys = app._survey_archives([(good, None, "zip"),
                                    (Path(str(bad)), None, "zip")])
    assert surveys == [("none", 1, 100), ("none", 0, 0)]

    app.extract_archive()
    assert (tmp_path / "dest" / "good" / "x.txt").read_bytes() == b"1" * 100
    assert any("Extraction failed for broken.zip" in m for m in app.logs)


def test_cursor_entry_is_used_when_nothing_is_selected(tmp_path, dest):
    one = _zip(tmp_path, "one.zip", "x.txt", b"1")
    two = _zip(tmp_path, "two.zip", "y.txt", b"2")
    app = _app([one, two], [], dest, focused=1)

    app.extract_archive()
    assert not (tmp_path / "dest" / "one").exists()
    assert (tmp_path / "dest" / "two" / "y.txt").read_bytes() == b"2"
    # A single archive keeps the single-item wording, naming what it unpacked.
    assert any("Extracted two.zip → two/ (1 entries)" in m for m in app.logs)


def test_non_archives_in_the_selection_are_skipped_and_reported(tmp_path, dest):
    arc = _zip(tmp_path, "one.zip", "x.txt", b"1")
    notes = tmp_path / "notes.txt"
    notes.write_text("hi")
    folder = tmp_path / "folder"
    folder.mkdir()
    picked = [arc, Path(str(notes)), Path(str(folder))]
    app = _app(picked, picked, dest)

    app.extract_archive()
    assert (tmp_path / "dest" / "one" / "x.txt").read_bytes() == b"1"
    assert not (tmp_path / "dest" / "notes").exists()
    assert any("Skipping 2 selected item(s) that are not archives" in m
               for m in app.logs)


def test_a_selection_with_no_archive_at_all_extracts_nothing(tmp_path, dest):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a")
    b.write_text("b")
    picked = [Path(str(a)), Path(str(b))]
    app = _app(picked, picked, dest)

    assert app.extract_archive() is True     # a guard bailed out synchronously
    assert not app.tasks.tasks               # nothing was ever submitted
    assert any("None of the 2 selected items is an archive" in m for m in app.logs)


def test_a_single_target_keeps_its_own_diagnosis(tmp_path, dest):
    notes = tmp_path / "notes.txt"
    notes.write_text("hi")
    entry = Path(str(notes))
    app = _app([entry], [], dest)

    assert app.extract_archive() is True
    assert any("'notes.txt' is not a supported archive" in m for m in app.logs)


def test_a_single_directory_target_says_it_is_not_a_file(tmp_path, dest):
    folder = tmp_path / "folder"
    folder.mkdir()
    entry = Path(str(folder))
    app = _app([entry], [], dest)

    assert app.extract_archive() is True
    assert any("folder is not a file" in m for m in app.logs)


def test_one_failing_archive_does_not_sink_the_batch(tmp_path, dest):
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip at all")
    good = _zip(tmp_path, "good.zip", "y.txt", b"2")
    picked = [Path(str(broken)), good]
    app = _app(picked, picked, dest)

    app.extract_archive()
    # The good one still landed, and the bad one was named in its own line.
    assert (tmp_path / "dest" / "good" / "y.txt").read_bytes() == b"2"
    assert any("Extraction failed for broken.zip" in m for m in app.logs)
    assert any("Extracted 1 archive(s)" in m for m in app.logs)


def test_the_confirm_box_counts_the_archives(tmp_path, dest, monkeypatch):
    one = _zip(tmp_path, "one.zip")
    two = _zip(tmp_path, "two.zip")
    app = _app([one, two], [one, two], dest, confirm=True)

    boxes = []
    monkeypatch.setattr(xefm_app, "show_message_box",
                        lambda panel, message, **kw: boxes.append((message, kw)))

    app.extract_archive()
    assert not (tmp_path / "dest" / "one").exists()  # nothing until it is confirmed
    message, kw = boxes[-1]
    assert "Extract 2 archives to" in message
    kw["on_result"]("Extract")
    assert (tmp_path / "dest" / "one" / "a.txt").exists()
    assert (tmp_path / "dest" / "two" / "a.txt").exists()
