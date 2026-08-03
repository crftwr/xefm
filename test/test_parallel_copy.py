"""Tests for the two copy accelerations from GitHub issue #248: the APFS
clonefile fast path (a same-volume copy is one copy-on-write syscall) and the
parallel file-copy worker pool (multiple files in flight at once, per-target
accounting identical to the sequential path).

Run with: python -m pytest test/test_parallel_copy.py -v
"""

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from xefm import _config
from xefm import file_operations as F
from xefm.file_operations import FileOperationService, _clone_file
from xefm.path import Path
from xefm.progress_manager import OperationType, ProgressManager
from xefm.task import Task


def _P(p):
    return Path(str(p))


@pytest.fixture
def cfg():
    c = _config.Config()
    c.CONFIRM_COPY = c.CONFIRM_MOVE = c.CONFIRM_DELETE = False
    c.CONFIRM_DUPLICATE = False
    return c


@pytest.fixture
def svc(cfg):
    return FileOperationService(cfg)


def _run_sync(svc, method, *args, **kw):
    result = {}
    method(None, *args, on_complete=lambda r: result.update(r), background=False, **kw)
    return result


def _fake_devices(monkeypatch, other_root):
    """Everything under ``other_root`` reports as a different filesystem —
    the same fiction test_file_operations uses; it also (deliberately) makes
    ``_clone_file`` decline, the way a real second volume would."""
    def device(path):
        return 2 if str(path).startswith(str(other_root)) else 1
    monkeypatch.setattr(F, "_entry_device", device)


# --- the clonefile fast path ---------------------------------------------------

needs_macos = pytest.mark.skipif(sys.platform != "darwin",
                                 reason="clonefile is a macOS/APFS syscall")


@needs_macos
def test_clone_file_lands_with_content_and_mtime(tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"q" * 4096)
    os.utime(src, (1_000_000_000, 1_000_000_000))
    dest = tmp_path / "b.bin"
    assert _clone_file(_P(src), _P(dest), overwrite=False) is True
    assert dest.read_bytes() == b"q" * 4096
    assert int(dest.stat().st_mtime) == 1_000_000_000  # copystat parity


@needs_macos
def test_clone_is_a_copy_not_a_link(tmp_path):
    """Writing to the clone must not touch the original (copy-on-write)."""
    src = tmp_path / "a.txt"
    src.write_text("original")
    dest = tmp_path / "b.txt"
    assert _clone_file(_P(src), _P(dest), overwrite=False)
    dest.write_text("changed")
    assert src.read_text() == "original"


@needs_macos
def test_clone_respects_overwrite_flag(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("new")
    dest = tmp_path / "b.txt"
    dest.write_text("old")
    assert _clone_file(_P(src), _P(dest), overwrite=False) is False
    assert dest.read_text() == "old"
    assert _clone_file(_P(src), _P(dest), overwrite=True) is True
    assert dest.read_text() == "new"


def test_clone_declines_across_devices(tmp_path, monkeypatch):
    """A (faked) second volume must never even attempt the syscall."""
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "f.txt").write_text("x")
    _fake_devices(monkeypatch, dst)
    assert _clone_file(_P(src / "f.txt"), _P(dst / "f.txt"), overwrite=False) is False


def test_copy_still_works_when_clone_is_unavailable(tmp_path, svc, monkeypatch):
    """Non-APFS / non-macOS: the fast path declines and the ordinary copy
    runs — same bytes, same result counts."""
    monkeypatch.setattr(F, "_clonefile", False)
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "big.bin").write_bytes(b"z" * (2 * 1024 * 1024))
    res = _run_sync(svc, svc.copy, [_P(src / "big.bin")], _P(dst))
    assert res["done"] == 1 and res["errors"] == []
    assert (dst / "big.bin").read_bytes() == b"z" * (2 * 1024 * 1024)


def test_large_copy_reports_a_full_byte_bar(tmp_path, svc, monkeypatch):
    """Whether the file cloned (instant) or streamed, a >=1 MiB copy ends with
    the byte bar full — the dialog never shows a large file finishing at 0%."""
    seen = []
    original = ProgressManager.update_file_byte_progress

    def spy(self, copied, total, item=None):
        seen.append((copied, total))
        original(self, copied, total, item)
    monkeypatch.setattr(ProgressManager, "update_file_byte_progress", spy)

    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    big = 2 * 1024 * 1024
    (src / "big.bin").write_bytes(b"y" * big)
    res = _run_sync(svc, svc.copy, [_P(src / "big.bin")], _P(dst))
    assert res["done"] == 1
    assert (big, big) in seen


# --- the parallel worker pool ----------------------------------------------------

def test_parallel_copy_many_files(tmp_path, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    names = [f"f{i:03d}.bin" for i in range(60)]
    for i, n in enumerate(names):
        (src / n).write_bytes(bytes([i % 251]) * (i * 137 % 4096 + 1))
    logs = []
    result = {}
    svc.copy(None, [_P(src / n) for n in names], _P(dst),
             on_complete=lambda r: result.update(r), log=logs.append,
             background=False)
    assert result["done"] == 60 and result["failed"] == 0
    assert result["items"] == 60 and result["errors"] == []
    for i, n in enumerate(names):
        assert (dst / n).read_bytes() == bytes([i % 251]) * (i * 137 % 4096 + 1)
    # One log line per file — completion order may differ, coverage may not.
    assert sorted(m.split("'")[1] for m in logs if m.startswith("Copied")) == names


def test_parallel_copy_nested_folder(tmp_path, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    folder = src / "folder"
    for sub in ("x", "y", "z"):
        (folder / sub).mkdir(parents=True)
        for i in range(10):
            (folder / sub / f"{sub}{i}.txt").write_text(f"{sub}{i}")
    res = _run_sync(svc, svc.copy, [_P(folder)], _P(dst))
    assert res["done"] == 1 and res["errors"] == []
    # folder + 3 subdirs + 30 files
    assert res["items"] == 34
    assert (dst / "folder" / "y" / "y7.txt").read_text() == "y7"


def test_parallel_inner_failure_keeps_folder_done(tmp_path, svc):
    """Same rule as sequential: one bad file inside a folder is recorded, the
    rest copy, and the folder still counts as done."""
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    folder = src / "folder"
    folder.mkdir()
    for i in range(20):
        (folder / f"good{i}.txt").write_text("ok")
    os.symlink(str(folder / "missing"), str(folder / "broken"))  # dangling
    res = _run_sync(svc, svc.copy, [_P(folder)], _P(dst))
    assert res["done"] == 1 and res["failed"] == 0
    assert len(res["errors"]) == 1 and res["errors"][0][0].endswith("broken")
    assert res["items"] == 21  # the folder + 20 good files


def test_parallel_failed_targets_counted_per_target(tmp_path, svc):
    dst = tmp_path / "d"
    dst.mkdir()
    src = tmp_path / "s"
    src.mkdir()
    good = []
    for i in range(5):
        p = src / f"ok{i}.txt"
        p.write_text("x")
        good.append(_P(p))
    missing = [_P(src / f"gone{i}.txt") for i in range(3)]
    res = _run_sync(svc, svc.copy, good + missing, _P(dst))
    assert res["done"] == 5 and res["failed"] == 3
    assert len(res["errors"]) == 3


def test_parallel_duplicate(tmp_path, svc):
    d = tmp_path / "d"
    d.mkdir()
    for i in range(12):
        (d / f"n{i}.txt").write_text(str(i))
    res = _run_sync(svc, svc.duplicate, [_P(d / f"n{i}.txt") for i in range(12)], _P(d))
    assert res["done"] == 12
    assert sorted(res["created"]) == sorted(f"n{i} (1).txt" for i in range(12))
    for i in range(12):
        assert (d / f"n{i} (1).txt").read_text() == str(i)


def test_parallel_move_across_filesystems_files(tmp_path, svc, monkeypatch):
    """Many single-file cross-filesystem move targets: every job carries its
    own copy-then-drop-source, so the sources are gone and the copies whole."""
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    names = [f"m{i}.bin" for i in range(20)]
    for n in names:
        (src / n).write_bytes(n.encode())
    _fake_devices(monkeypatch, dst)
    res = _run_sync(svc, svc.move, [_P(src / n) for n in names], _P(dst))
    assert res["done"] == 20 and res["errors"] == []
    for n in names:
        assert (dst / n).read_bytes() == n.encode()
        assert not (src / n).exists()


def test_parallel_move_dir_keeps_source_on_partial_copy(tmp_path, svc, monkeypatch):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    folder = src / "folder"
    folder.mkdir()
    for i in range(10):
        (folder / f"good{i}.txt").write_text("ok")
    os.symlink(str(folder / "missing"), str(folder / "broken"))  # dangling
    _fake_devices(monkeypatch, dst)
    res = _run_sync(svc, svc.move, [_P(folder)], _P(dst))
    assert res["errors"]
    assert folder.exists() and (folder / "good3.txt").exists()  # source kept


def test_parallel_move_dir_drops_source_when_clean(tmp_path, svc, monkeypatch):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    folder = src / "folder"
    folder.mkdir()
    for i in range(10):
        (folder / f"f{i}.txt").write_text(str(i))
    _fake_devices(monkeypatch, dst)
    res = _run_sync(svc, svc.move, [_P(folder)], _P(dst))
    assert res["done"] == 1 and res["errors"] == []
    assert not folder.exists()
    assert (dst / "folder" / "f9.txt").read_text() == "9"


def test_parallel_cancel_stops_short(tmp_path, svc, monkeypatch):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    names = [f"c{i:03d}.txt" for i in range(100)]
    for n in names:
        (src / n).write_text("x")

    calls = {"n": 0}
    original = FileOperationService._copy_file

    def counting(self, task, s, d, overwrite, prog):
        calls["n"] += 1
        if calls["n"] == 5:
            task.request_cancel()
        return original(self, task, s, d, overwrite, prog)
    monkeypatch.setattr(FileOperationService, "_copy_file", counting)

    res = _run_sync(svc, svc.copy, [_P(src / n) for n in names], _P(dst))
    assert res["cancelled"] is True
    assert len(os.listdir(dst)) < 100  # it stopped, mid-batch


def test_parallel_progress_increments_are_not_lost(tmp_path, svc, monkeypatch):
    """N workers increment one processed-items counter; with the lock, the
    final count equals the number of nodes exactly."""
    final = {}
    original = ProgressManager.finish_operation

    def capture(self):
        if self.current_operation:
            final["processed"] = self.current_operation["processed_items"]
            final["total"] = self.current_operation["total_items"]
        original(self)
    monkeypatch.setattr(ProgressManager, "finish_operation", capture)

    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    for i in range(80):
        (src / f"p{i}.txt").write_text("x")
    res = _run_sync(svc, svc.copy,
                    [_P(src / f"p{i}.txt") for i in range(80)], _P(dst))
    assert res["done"] == 80
    assert final["processed"] == final["total"] == 80


# --- worker-count selection ------------------------------------------------------

class _Scheme:
    """A stand-in path that only answers get_scheme()."""

    def __init__(self, scheme):
        self._scheme = scheme

    def get_scheme(self):
        return self._scheme


def _plan(*schemes):
    return [(_Scheme(s), None, False) for s in schemes]


def test_copy_workers_local(svc):
    assert svc._copy_workers("copy", _plan("file", "file"), _Scheme("file")) == F._WORKERS_LOCAL


def test_copy_workers_s3(svc):
    assert svc._copy_workers("copy", _plan("file"), _Scheme("s3")) == F._WORKERS_REMOTE
    assert svc._copy_workers("copy", _plan("s3"), _Scheme("file")) == F._WORKERS_REMOTE


def test_copy_workers_ssh_stays_sequential(svc):
    assert svc._copy_workers("copy", _plan("file"), _Scheme("ssh")) == 1
    assert svc._copy_workers("copy", _plan("ssh"), _Scheme("file")) == 1


def test_copy_workers_delete_stays_sequential(svc):
    assert svc._copy_workers("delete", _plan("file"), None) == 1


def test_copy_workers_config_knobs_are_independent(cfg):
    svc = FileOperationService(cfg)
    cfg.FILE_OP_WORKERS_LOCAL = 2
    cfg.FILE_OP_WORKERS_S3 = 12
    assert svc._copy_workers("copy", _plan("file"), _Scheme("file")) == 2
    assert svc._copy_workers("copy", _plan("file"), _Scheme("s3")) == 12
    # ...but neither knob ever forces a scheme that isn't thread-safe.
    assert svc._copy_workers("copy", _plan("ssh"), _Scheme("file")) == 1


def test_copy_workers_nonsense_knob_falls_back_to_default(cfg):
    svc = FileOperationService(cfg)
    cfg.FILE_OP_WORKERS_LOCAL = 0
    assert svc._copy_workers("copy", _plan("file"), _Scheme("file")) == F._WORKERS_LOCAL
    cfg.FILE_OP_WORKERS_LOCAL = "many"
    assert svc._copy_workers("copy", _plan("file"), _Scheme("file")) == F._WORKERS_LOCAL


def test_workers_one_takes_the_sequential_path(tmp_path, cfg, monkeypatch):
    cfg.FILE_OP_WORKERS_LOCAL = 1
    svc = FileOperationService(cfg)

    def boom(*a, **kw):
        raise AssertionError("_run_parallel must not run with workers=1")
    monkeypatch.setattr(FileOperationService, "_run_parallel", boom)

    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    for i in range(5):
        (src / f"f{i}.txt").write_text("x")
    res = _run_sync(svc, svc.copy, [_P(src / f"f{i}.txt") for i in range(5)], _P(dst))
    assert res["done"] == 5


# --- byte-bar ownership under concurrency ---------------------------------------

def test_byte_bar_ignores_a_non_current_file():
    pm = ProgressManager()
    pm.start_operation(OperationType.COPY, 2)
    pm.update_progress("current.bin")
    pm.update_file_byte_progress(10, 100, "other.bin")   # a different worker's file
    assert pm.current_operation["file_bytes_copied"] == 0
    pm.update_file_byte_progress(10, 100, "current.bin")  # the owner
    assert pm.current_operation["file_bytes_copied"] == 10
    pm.update_file_byte_progress(50, 100)                 # untagged: always applies
    assert pm.current_operation["file_bytes_copied"] == 50
