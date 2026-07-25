"""Tests for the shared file-operation engine (xefm.file_operations) and the
central task system (xefm.task): recursive counting, per-file execution, the
conflict resolution (skip / overwrite / keep-both + apply-to-all),
cancellation, and the worker↔main-thread UI bridge."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from xefm import _config
from xefm import file_operations as F
from xefm.file_operations import FileOperationService, _unique_dest
from xefm.path import Path
from xefm.task import Cancelled, Task, TaskManager


def _P(p):
    return Path(str(p))


@pytest.fixture
def cfg():
    """Config with confirmation prompts off, so sync ops run without a panel."""
    c = _config.Config()
    c.CONFIRM_COPY = c.CONFIRM_MOVE = c.CONFIRM_DELETE = False
    c.CONFIRM_DUPLICATE = False
    return c


@pytest.fixture
def svc(cfg):
    return FileOperationService(cfg)


def _run_sync(svc, method, *args, **kw):
    """Invoke a service op synchronously and return its result dict."""
    result = {}
    method(None, *args, on_complete=lambda r: result.update(r), background=False, **kw)
    return result


# --- _unique_dest ------------------------------------------------------------

def test_unique_dest_free_name_unchanged(tmp_path):
    assert _unique_dest(_P(tmp_path), "new.txt").name == "new.txt"


def test_unique_dest_file_inserts_before_extension(tmp_path):
    (tmp_path / "foo.txt").write_text("x")
    assert _unique_dest(_P(tmp_path), "foo.txt").name == "foo (1).txt"
    (tmp_path / "foo (1).txt").write_text("x")
    assert _unique_dest(_P(tmp_path), "foo.txt").name == "foo (2).txt"


def test_unique_dest_multiple_dots_in_stem(tmp_path):
    # Only the last extension moves; dots in the stem stay put (the reported bug:
    # "Screenshot … 5.36.02 PM.png" must not become "… 5 (1).36.02 PM.png").
    name = "Screenshot 2026-06-27 at 5.36.02 PM.png"
    (tmp_path / name).write_text("x")
    assert _unique_dest(_P(tmp_path), name).name == "Screenshot 2026-06-27 at 5.36.02 PM (1).png"


def test_unique_dest_directory_appends(tmp_path):
    (tmp_path / "bar").mkdir()
    assert _unique_dest(_P(tmp_path), "bar", is_dir=True).name == "bar (1)"


def test_unique_dest_dotted_directory_appends(tmp_path):
    # A dotted directory name is not an extension — append, don't split.
    (tmp_path / "my.backup").mkdir()
    assert _unique_dest(_P(tmp_path), "my.backup", is_dir=True).name == "my.backup (1)"


def test_unique_dest_dotfile_appends(tmp_path):
    (tmp_path / ".bashrc").write_text("x")
    assert _unique_dest(_P(tmp_path), ".bashrc").name == ".bashrc (1)"


# --- synchronous copy / move / delete ---------------------------------------

def test_copy_tree_and_large_file(tmp_path, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "a.txt").write_text("hello")
    (src / "sub").mkdir()
    (src / "sub" / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))  # chunked path
    res = _run_sync(svc, svc.copy, [_P(src / "a.txt"), _P(src / "sub")], _P(dst))
    assert res["done"] == 2 and res["skipped"] == 0 and res["failed"] == 0
    assert res["cancelled"] is False and res["errors"] == []
    # 2 top-level items but 3 entries processed (a.txt, sub/, sub/big.bin).
    assert res["items"] == 3
    assert (dst / "a.txt").read_text() == "hello"
    assert (dst / "sub" / "big.bin").stat().st_size == 2 * 1024 * 1024


def test_move_same_storage_is_atomic(tmp_path, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "m.txt").write_text("move")
    res = _run_sync(svc, svc.move, [_P(src / "m.txt")], _P(dst))
    assert res["done"] == 1
    assert (dst / "m.txt").read_text() == "move"
    assert not (src / "m.txt").exists()


def test_duplicate_renames_file_in_place(tmp_path, svc):
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("hello")
    res = _run_sync(svc, svc.duplicate, [_P(d / "a.txt")], _P(d))
    assert res["done"] == 1 and res["failed"] == 0 and res["errors"] == []
    assert res["created"] == ["a (1).txt"]
    # Original untouched; the copy sits beside it with the same contents.
    assert (d / "a.txt").read_text() == "hello"
    assert (d / "a (1).txt").read_text() == "hello"


def test_duplicate_directory_appends_suffix(tmp_path, svc):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "f.txt").write_text("x")
    res = _run_sync(svc, svc.duplicate, [_P(d / "sub")], _P(d))
    assert res["created"] == ["sub (1)"]
    assert (d / "sub").is_dir() and (d / "sub (1)").is_dir()
    assert (d / "sub (1)" / "f.txt").read_text() == "x"


def test_duplicate_multiple_each_get_own_suffix(tmp_path, svc):
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("a")
    (d / "b.log").write_text("b")
    res = _run_sync(svc, svc.duplicate, [_P(d / "a.txt"), _P(d / "b.log")], _P(d))
    assert res["done"] == 2
    assert res["created"] == ["a (1).txt", "b (1).log"]
    assert (d / "a (1).txt").read_text() == "a"
    assert (d / "b (1).log").read_text() == "b"


def test_duplicate_logs_as_duplicated(tmp_path, svc):
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("x")
    logs = []
    svc.duplicate(None, [_P(d / "a.txt")], _P(d),
                  on_complete=lambda r: None, log=logs.append, background=False)
    # The rename is visible: source name → the ` (N)` destination name.
    assert any("Duplicated 'a.txt' → 'a (1).txt'" in m for m in logs)


def test_copy_logs_each_file_with_src_and_dest(tmp_path, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "a.txt").write_text("x")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("y")
    logs = []
    svc.copy(None, [_P(src / "a.txt"), _P(src / "sub")], _P(dst),
             on_complete=lambda r: None, log=logs.append, background=False)
    # One line per leaf file (not per directory): the name once + src/dest dirs.
    assert any("Copied 'a.txt'" in m and str(src) in m and str(dst) in m for m in logs)
    assert any("Copied 'b.txt'" in m and str(dst / "sub") in m for m in logs)
    # The full filename is not repeated in each path (compact form).
    assert all(m.count("a.txt") <= 1 for m in logs if "Copied 'a.txt'" in m)


def test_delete_logs_each_removal(tmp_path, svc):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "f.txt").write_text("x")
    logs = []
    svc.delete(None, [_P(d / "sub")], log=logs.append, background=False)
    assert any("Deleted 'f.txt'" in m for m in logs)
    assert any("Deleted 'sub'" in m for m in logs)


def test_keep_both_log_shows_renamed_name(tmp_path, cfg, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "c.txt").write_text("new")
    (dst / "c.txt").write_text("old")
    task = _scripted_task(cfg, [("keep_both", False)])
    plan, _ = svc._resolve(task, [_P(src / "c.txt")], _P(dst), 70, None)
    logs = []
    task.progress.start_operation(F._OP_TYPE["copy"], 1)
    svc._execute_one(task, "copy", plan[0][0], plan[0][1], plan[0][2],
                     _P(dst), task.progress, logs.append, [])
    # Both names shown (source → renamed), so the (1) result is visible.
    assert any("'c.txt' → 'c (1).txt'" in m for m in logs)


def test_delete_recurses(tmp_path, svc):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "f.txt").write_text("x")
    res = _run_sync(svc, svc.delete, [_P(d / "sub")])
    assert res["done"] >= 1
    assert not (d / "sub").exists()


# --- conflict resolution -----------------------------------------------------

def test_conflict_headless_defaults_to_skip(tmp_path, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "c.txt").write_text("NEW")
    (dst / "c.txt").write_text("OLD")
    res = _run_sync(svc, svc.copy, [_P(src / "c.txt")], _P(dst))
    assert res["skipped"] == 1 and res["done"] == 0
    assert (dst / "c.txt").read_text() == "OLD"  # untouched


def _scripted_task(cfg, answers):
    """A Task whose ``ask`` yields the given (action, apply_to_all) answers."""
    task = Task("Copy…", config=cfg)
    seq = iter(answers)
    task.ask = lambda show_fn, headless: next(seq)  # type: ignore[assignment]
    return task


def test_resolve_overwrite(tmp_path, cfg, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "c.txt").write_text("x")
    (dst / "c.txt").write_text("old")
    task = _scripted_task(cfg, [("overwrite", False)])
    plan, skipped = svc._resolve(task, [_P(src / "c.txt")], _P(dst), 70, None)
    assert skipped == 0
    assert plan[0][1].name == "c.txt" and plan[0][2] is True  # overwrite flag set


def test_resolve_keep_both(tmp_path, cfg, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "c.txt").write_text("x")
    (dst / "c.txt").write_text("old")
    task = _scripted_task(cfg, [("keep_both", False)])
    plan, skipped = svc._resolve(task, [_P(src / "c.txt")], _P(dst), 70, None)
    assert plan[0][1].name == "c (1).txt" and plan[0][2] is False


def test_resolve_apply_to_all(tmp_path, cfg, svc):
    """A single answer with apply_to_all=True governs every later conflict; ask is
    called exactly once."""
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    names = ["a.txt", "b.txt", "c.txt"]
    for n in names:
        (src / n).write_text("new")
        (dst / n).write_text("old")
    calls = {"n": 0}
    task = Task("Copy…", config=cfg)

    def ask(show_fn, headless):
        calls["n"] += 1
        return ("skip", True)  # skip, apply to all remaining
    task.ask = ask  # type: ignore[assignment]
    plan, skipped = svc._resolve(task, [_P(src / n) for n in names], _P(dst), 70, None)
    assert calls["n"] == 1          # asked only for the first conflict
    assert skipped == 3 and plan == []


def test_resolve_cancel_raises(tmp_path, cfg, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "c.txt").write_text("x")
    (dst / "c.txt").write_text("old")
    task = _scripted_task(cfg, [("cancel", False)])
    with pytest.raises(Cancelled):
        svc._resolve(task, [_P(src / "c.txt")], _P(dst), 70, None)


# --- counting + cancellation -------------------------------------------------

def test_count_nodes_and_bytes(tmp_path, svc):
    root = tmp_path / "r"
    (root / "sub").mkdir(parents=True)
    (root / "f1").write_bytes(b"ab")
    (root / "sub" / "f2").write_bytes(b"abcd")
    task = Task("Copy…")
    # nodes = root dir + sub dir + f1 + f2 = 4; bytes = 2 + 4 = 6
    items, nbytes = svc._count(task, "copy", _P(tmp_path / "d"), [_P(root)])
    assert items == 4 and nbytes == 6
    assert task.counted == 4


def test_count_atomic_move_is_one_item(tmp_path, svc):
    root = tmp_path / "r"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "f").write_text("x")
    task = Task("Move…")
    items, _ = svc._count(task, "move", _P(tmp_path), [_P(root)])
    assert items == 1  # same-storage move = one atomic rename


def test_failure_is_collected_in_errors(tmp_path, svc):
    # A top-level source that can't be copied -> counted as a wholesale failure,
    # recorded in result["errors"] rather than only logged.
    dst = tmp_path / "d"
    dst.mkdir()
    missing = _P(tmp_path / "gone.txt")  # never created
    res = _run_sync(svc, svc.copy, [missing], _P(dst))
    assert res["failed"] == 1 and res["done"] == 0
    assert len(res["errors"]) == 1
    path, msg = res["errors"][0]
    assert path.endswith("gone.txt") and msg  # full path + a non-empty reason


def test_inner_file_failure_is_skipped_not_fatal(tmp_path, svc):
    """One bad file inside a folder is skipped (recorded), the rest still copy, and
    the folder counts as done — not a wholesale failure."""
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    folder = src / "folder"
    folder.mkdir()
    (folder / "good.txt").write_text("ok")
    os.symlink(str(folder / "missing-target"), str(folder / "broken"))  # dangling
    res = _run_sync(svc, svc.copy, [_P(folder)], _P(dst))
    assert res["done"] == 1 and res["failed"] == 0        # folder still done
    assert (dst / "folder" / "good.txt").read_text() == "ok"  # sibling copied
    assert len(res["errors"]) == 1                        # the broken link
    assert res["errors"][0][0].endswith("broken")
    # Summary shows the per-file failure without sinking the folder.
    from xefm.file_operations import format_op_summary
    assert "1 file failed" in format_op_summary("Copy", res)


def test_op_summary_wording():
    from xefm.file_operations import format_op_summary
    # Flat, all done -> no top-level/total clutter.
    assert format_op_summary(
        "Copy", {"done": 3, "skipped": 0, "failed": 0, "items": 3, "errors": []}
    ) == "Copy: 3 done"
    # Nested with a failure -> clarifies top-level vs. total entries.
    s = format_op_summary(
        "Copy", {"done": 10, "skipped": 0, "failed": 1, "items": 247, "errors": []})
    assert s == "Copy: 10 done, 1 failed (11 top-level items, 247 items total)"


def test_code_wraps_markdown_specials():
    from xefm.file_operations import _code
    assert _code("photo.png") == "`photo.png`"
    assert _code("a_b*c[1].txt") == "`a_b*c[1].txt`"          # specials kept literal
    assert _code("weird`name") == "``weird`name``"            # longer fence for backtick
    assert _code("`edge`") == "`` `edge` ``"                  # pad when starts/ends with `


def test_conflict_dialog_renders_message_checkbox_and_buttons():
    """Regression: the 'apply to all' checkbox must render (a Checkbox clips at a
    fractional grid row), alongside the code-formatted name and all four buttons."""
    backend = MemoryBackend(width=76, height=24, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    from xefm.file_operations import ConflictDialog
    dlg = ConflictDialog("report.final.pdf", 2, 5, on_result=lambda a: None)
    dlg.show(panel)
    panel.render()
    text = "\n".join(backend.snapshot())
    assert "report.final.pdf" in text                 # the message / filename
    assert "Apply to all remaining" in text           # the checkbox
    for label in ("Overwrite", "Skip", "Keep both", "Cancel"):
        assert label in text


def test_conflict_dialog_accent_button_is_the_focused_default():
    """The accent ("primary") fill marks the button Enter presses, so exactly one
    button wears it and it is the one focus starts on — the safe Skip, matching
    the app's other destructive confirms."""
    from xefm.file_operations import ConflictDialog
    dlg = ConflictDialog("a.txt", 1, 1, on_result=lambda a: None)
    primary = [b for b in dlg._buttons if b.variant == "primary"]
    assert [b.label for b in primary] == ["Skip"]
    assert dlg._focused is primary[0]


def test_conflict_dialog_arrow_keys_move_focus():
    """Left/Right walk the button row (wrapping) like a regular message box;
    Up/Down hop to the checkbox and back to the button left behind."""
    from xefm.file_operations import ConflictDialog
    dlg = ConflictDialog("a.txt", 1, 1, on_result=lambda a: None)

    def key(name):
        dlg.handle_event(Event(EventType.KEY, key=name, char=None, modifiers=set()))

    key("left")
    assert dlg._focused.label == "Overwrite"
    key("left")                                   # wraps to the row's end
    assert dlg._focused.label == "Cancel"
    key("right")
    assert dlg._focused.label == "Overwrite"

    key("up")                                     # into the checkbox row
    assert dlg._focused is dlg._checkbox
    key("down")                                   # back where we left off
    assert dlg._focused.label == "Overwrite"

    key("up")
    key("right")                                  # from the checkbox, into the row
    assert dlg._focused.label == "Overwrite"


def test_op_errors_body_and_none():
    from xefm.file_operations import format_op_errors
    assert format_op_errors("Copy", {"errors": []}) is None
    body = format_op_errors(
        "Copy", {"errors": [("a.txt", "Permission denied"), ("b.txt", "No space")]})
    assert "**Copy** failed for 2 item(s):" in body
    assert "- `a.txt` — Permission denied" in body
    assert "- `b.txt` — No space" in body


def test_cancelled_before_run_reports_cancelled(tmp_path, svc):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "a.txt").write_text("x")
    task = Task("Copy…", config=svc.config)
    task.request_cancel()  # cancel before it starts
    res = svc._run(task, "copy", [_P(src / "a.txt")], _P(dst), None, None, 70)
    assert res["cancelled"] is True
    assert not (dst / "a.txt").exists()


# --- TaskManager + UI bridge -------------------------------------------------

def test_manager_sync_submit_runs_inline():
    tm = TaskManager()
    task = Task("Job…")
    calls = {"done": None}

    def run(t):
        return {"done": 7, "skipped": 0, "failed": 0, "cancelled": False}
    tm.submit(task, None, run=run, on_done=lambda r: calls.update(done=r),
              background=False)
    assert calls["done"]["done"] == 7
    assert not tm.has_active()  # finished tasks are dropped from the registry


def test_ask_headless_returns_default():
    task = Task("Job…")
    task._headless = True
    assert task.ask(lambda p, d: None, headless=("skip", False)) == ("skip", False)


# --- background path: threaded worker + conflict dialog over the bridge -------

import time  # noqa: E402

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402


def _panel():
    backend = MemoryBackend(width=100, height=30, capabilities=PROFILE_GUI_DESKTOP)
    return backend, Panel(backend)


def _pump_until(backend, panel, pred, limit=400):
    """Run tick rounds until ``pred()`` or a bound is hit (guards against a hang)."""
    for _ in range(limit):
        backend.run_animation_ticks()
        if pred():
            return True
        time.sleep(0.002)
    return False


def _top(panel):
    return type(panel._layers[-1].widget).__name__ if panel._layers else None


def test_background_conflict_dialog_overwrite(tmp_path, cfg):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    (src / "c.txt").write_text("NEW")
    (dst / "c.txt").write_text("OLD")
    backend, panel = _panel()
    svc = FileOperationService(cfg)
    done = {}
    svc.copy(panel, [_P(src / "c.txt")], _P(dst),
             on_complete=lambda r: done.update(r), background=True)

    assert _pump_until(backend, panel, lambda: _top(panel) == "ConflictDialog")
    panel.dispatch_event(Event(EventType.KEY, key="o", char="o", modifiers=set()))
    assert _pump_until(backend, panel, lambda: bool(done))
    assert done["done"] == 1
    assert (dst / "c.txt").read_text() == "NEW"  # overwritten
    assert panel._layers == []  # dialog torn down


def test_background_cancel_stops_and_cleans_up(tmp_path, cfg):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir(); dst.mkdir()
    # Many files so the op is reliably still running when we request cancel.
    for i in range(400):
        (src / f"f{i:03d}.bin").write_bytes(b"x" * (256 * 1024))
    backend, panel = _panel()
    svc = FileOperationService(cfg)
    done = {}
    svc.copy(panel, [_P(src / n) for n in sorted(os.listdir(src))], _P(dst),
             on_complete=lambda r: done.update(r), background=True)

    assert _pump_until(backend, panel, lambda: _top(panel) == "ProgressDialog")
    # Request cancellation on the live task (same effect as the Esc→confirm path).
    active = svc.tasks.active_tasks()
    assert active, "expected a running task"
    active[0].request_cancel()
    assert _pump_until(backend, panel, lambda: bool(done))
    assert done["cancelled"] is True
    assert panel._layers == []           # progress dialog torn down
    assert not svc.tasks.has_active()    # task dropped from the registry
    # It stopped early — not every file made it across.
    assert len(os.listdir(dst)) < 400
