"""A destination that changes after the conflicts were decided (#887).

Conflicts are decided when an operation starts; what lands in the destination
after that is found again as the files are written, and asked about rather
than skipped or merged in silence. The change is staged between the plan and
the writes by wrapping ``_release_archives``, which runs right after the plan.

Run with: python -m pytest test/test_conflict_dest_change.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from xefm import _config
from xefm import file_operations as F
from xefm.file_operations import FileOperationService
from xefm.path import Path
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


@pytest.fixture
def after_plan(monkeypatch):
    """``after_plan(fn)``: run ``fn()`` once the plan is made, before any
    write — what another operation might have done meanwhile."""
    hooks = []
    original = FileOperationService._release_archives

    def release(kind, plan, result, log):
        for fn in hooks:
            fn()
        return original(kind, plan, result, log)
    monkeypatch.setattr(FileOperationService, "_release_archives",
                        staticmethod(release))
    return hooks.append


@pytest.fixture
def other_volume(monkeypatch, tmp_path):
    """Everything under ``tmp_path / "d"`` is another filesystem, so a move
    there copies and then deletes its source (test_parallel_copy's fiction)."""
    root = str(tmp_path / "d")
    monkeypatch.setattr(F, "_entry_device",
                        lambda path: 2 if str(path).startswith(root) else 1)


def _headless(svc, method, *args):
    result = {}
    method(None, *args, on_complete=result.update, background=False)
    return result


def _scripted(cfg, answers):
    """A task whose prompts are answered from ``answers`` in turn; the
    prompts it was asked are counted in ``task.asked``."""
    task = Task("Copy…", config=cfg)
    seq = iter(answers)
    task.asked = 0

    def ask(show_fn, headless):
        task.asked += 1
        return next(seq)
    task.ask = ask
    return task


def _run(svc, task, kind, targets, dest_dir, log=None):
    return svc._run(task, kind, targets, dest_dir, None, log, 70)


def _tree(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


# --- the issue's case: a folder moved across storages ------------------------

def test_folder_move_keeps_its_source_when_the_folder_appeared_since(
        tmp_path, svc, after_plan, other_volume):
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src / "photos", {"a.jpg": "mine-a", "b.jpg": "mine-b"})
    dst.mkdir()
    after_plan(lambda: _tree(dst / "photos", {"a.jpg": "theirs"}))
    res = _headless(svc, svc.move, [_P(src / "photos")], _P(dst))
    assert res["skipped"] == 1 and res["done"] == 0
    assert (src / "photos" / "a.jpg").read_text() == "mine-a"
    assert (src / "photos" / "b.jpg").read_text() == "mine-b"
    assert (dst / "photos" / "a.jpg").read_text() == "theirs"


def test_a_folder_that_appeared_since_merges_only_when_answered(
        tmp_path, cfg, svc, after_plan, other_volume):
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src / "photos", {"a.jpg": "mine-a", "b.jpg": "mine-b"})
    dst.mkdir()
    after_plan(lambda: _tree(dst / "photos", {"a.jpg": "theirs"}))
    task = _scripted(cfg, [("overwrite", False)])
    res = _run(svc, task, "move", [_P(src / "photos")], _P(dst))
    assert task.asked == 1
    assert res["done"] == 1
    assert (dst / "photos" / "a.jpg").read_text() == "mine-a"
    assert (dst / "photos" / "b.jpg").read_text() == "mine-b"
    assert not (src / "photos").exists()     # merged whole, so the source goes


def test_a_skip_inside_a_moved_folder_keeps_the_source(
        tmp_path, svc, monkeypatch, other_volume):
    """A file that turns up inside the folder after it was created (another
    program) is a conflict of its own; skipped, it keeps the source."""
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src / "photos", {"a.jpg": "mine-a", "b.jpg": "mine-b"})
    dst.mkdir()
    original = FileOperationService._carry_tags

    def carry(self, task, s, d):
        if str(d) == str(dst / "photos") and not (dst / "photos" / "a.jpg").exists():
            (dst / "photos" / "a.jpg").write_text("theirs")
        return original(self, task, s, d)
    monkeypatch.setattr(FileOperationService, "_carry_tags", carry)
    logs = []
    res = {}
    svc.move(None, [_P(src / "photos")], _P(dst), on_complete=res.update,
             log=logs.append, background=False)
    assert res["done"] == 1
    assert (dst / "photos" / "a.jpg").read_text() == "theirs"
    assert (dst / "photos" / "b.jpg").read_text() == "mine-b"
    assert (src / "photos" / "a.jpg").read_text() == "mine-a"   # not lost
    assert any("Skipped 'a.jpg'" in m for m in logs)


# --- files -------------------------------------------------------------------

def test_a_file_that_appeared_since_is_not_counted_as_done(tmp_path, svc, after_plan):
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src, {"c.txt": "mine"})
    dst.mkdir()
    after_plan(lambda: (dst / "c.txt").write_text("theirs"))
    res = _headless(svc, svc.copy, [_P(src / "c.txt")], _P(dst))
    assert res["skipped"] == 1 and res["done"] == 0
    assert (dst / "c.txt").read_text() == "theirs"


def test_a_file_that_appeared_since_is_asked_about(tmp_path, cfg, svc, after_plan):
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src, {"c.txt": "mine"})
    dst.mkdir()
    after_plan(lambda: (dst / "c.txt").write_text("theirs"))
    task = _scripted(cfg, [("overwrite", False)])
    res = _run(svc, task, "copy", [_P(src / "c.txt")], _P(dst))
    assert task.asked == 1 and res["done"] == 1
    assert (dst / "c.txt").read_text() == "mine"


def test_a_rename_onto_a_file_that_appeared_since_is_asked_about(
        tmp_path, cfg, svc, after_plan):
    """Within one volume a move is a rename, which refuses the existing name;
    that refusal is a conflict, not a failure."""
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src, {"c.txt": "mine"})
    dst.mkdir()
    after_plan(lambda: (dst / "c.txt").write_text("theirs"))
    res = _headless(svc, svc.move, [_P(src / "c.txt")], _P(dst))
    assert res["skipped"] == 1 and res["failed"] == 0 and res["errors"] == []
    assert (src / "c.txt").read_text() == "mine"

    task = _scripted(cfg, [("overwrite", False)])
    res = _run(svc, task, "move", [_P(src / "c.txt")], _P(dst))
    assert task.asked == 1 and res["done"] == 1
    assert (dst / "c.txt").read_text() == "mine" and not (src / "c.txt").exists()


def test_keep_both_written_now_picks_a_free_name(tmp_path, cfg, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src, {"c.txt": "mine"})
    _tree(dst, {"c.txt": "theirs"})
    task = _scripted(cfg, [("keep_both", False)])
    plan, _ = svc._resolve(task, [_P(src / "c.txt")], _P(dst), 70, None)
    assert plan[0][1].name == "c (1).txt"
    (dst / "c (1).txt").write_text("taken meanwhile")
    res = _run(svc, _scripted(cfg, [("keep_both", False)]), "copy",
               [_P(src / "c.txt")], _P(dst))
    assert res["done"] == 1
    assert (dst / "c (1).txt").read_text() == "taken meanwhile"
    assert (dst / "c (2).txt").read_text() == "mine"


def test_keep_both_from_the_plan_moves_on_when_its_name_is_taken(
        tmp_path, cfg, svc, after_plan):
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src, {"c.txt": "mine"})
    _tree(dst, {"c.txt": "theirs"})
    after_plan(lambda: (dst / "c (1).txt").write_text("taken meanwhile"))
    task = _scripted(cfg, [("keep_both", False)])
    res = _run(svc, task, "copy", [_P(src / "c.txt")], _P(dst))
    assert task.asked == 1                  # only the plan's question
    assert res["done"] == 1
    assert (dst / "c (1).txt").read_text() == "taken meanwhile"
    assert (dst / "c (2).txt").read_text() == "mine"


def test_a_duplicate_moves_on_when_its_name_is_taken(tmp_path, svc, after_plan):
    _tree(tmp_path, {"c.txt": "mine"})
    after_plan(lambda: (tmp_path / "c (1).txt").write_text("taken meanwhile"))
    res = _headless(svc, svc.duplicate, [_P(tmp_path / "c.txt")], _P(tmp_path))
    assert res["done"] == 1
    assert (tmp_path / "c (1).txt").read_text() == "taken meanwhile"
    assert (tmp_path / "c (2).txt").read_text() == "mine"
    assert res["created"] == ["c (2).txt"]


def test_a_destination_gone_by_the_answer_is_simply_written(tmp_path, cfg, svc,
                                                           after_plan):
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src, {"c.txt": "mine"})
    dst.mkdir()
    after_plan(lambda: (dst / "c.txt").write_text("theirs"))
    task = Task("Copy…", config=cfg)

    def ask(show_fn, headless):
        (dst / "c.txt").unlink()            # removed while the prompt waited
        return ("skip", False)
    task.ask = ask
    res = _run(svc, task, "copy", [_P(src / "c.txt")], _P(dst))
    assert res["done"] == 1
    assert (dst / "c.txt").read_text() == "mine"


# --- never asking twice ------------------------------------------------------

def test_apply_to_all_from_the_start_covers_the_writes(tmp_path, cfg, svc,
                                                      after_plan):
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src, {"x.txt": "mine-x", "y.txt": "mine-y"})
    _tree(dst, {"x.txt": "theirs-x"})
    after_plan(lambda: (dst / "y.txt").write_text("theirs-y"))
    task = _scripted(cfg, [("skip", True)])
    res = _run(svc, task, "copy", [_P(src / "x.txt"), _P(src / "y.txt")], _P(dst))
    assert task.asked == 1
    assert res["skipped"] == 2 and res["done"] == 0
    assert (dst / "y.txt").read_text() == "theirs-y"


def test_apply_to_all_while_writing_covers_the_rest(tmp_path, cfg, svc, after_plan):
    """Many files appear at once; the parallel pool asks once and every other
    worker finds the answer when its turn comes."""
    src, dst = tmp_path / "s", tmp_path / "d"
    names = [f"f{i:02d}.txt" for i in range(30)]
    _tree(src, {n: "mine" for n in names})
    dst.mkdir()
    after_plan(lambda: _tree(dst, {n: "theirs" for n in names[::2]}))
    task = _scripted(cfg, [("overwrite", True)])
    res = _run(svc, task, "copy", [_P(src / n) for n in names], _P(dst))
    assert task.asked == 1
    assert res["done"] == 30
    assert all((dst / n).read_text() == "mine" for n in names)


def test_the_sync_plan_is_checked_again_too(tmp_path, svc, after_plan):
    """A Directory Diff sync copies what was missing; a file that has arrived
    since is a conflict there as well."""
    src, dst = tmp_path / "s", tmp_path / "d"
    _tree(src, {"new.txt": "mine"})
    dst.mkdir()
    after_plan(lambda: (dst / "new.txt").write_text("theirs"))
    res = {}
    svc.sync(None, [(_P(src / "new.txt"), _P(dst / "new.txt"), False)], [],
             on_complete=res.update, background=False)
    assert res["skipped"] == 1 and res["done"] == 0
    assert (dst / "new.txt").read_text() == "theirs"
