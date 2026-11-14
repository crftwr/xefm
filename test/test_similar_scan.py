"""Similar-file scans that outlive XeFM (#571).

The scan is a real ``similar-files`` process, started the way XeFM starts it —
its own session, files for everything it says. States the scan reaches only
over hours (stale, lost) are written by hand into a job folder.

Skipped when similar-files with ``--status`` (0.2) is not installed.

Run with: python -m pytest test/test_similar_scan.py -v
"""

import json
import os
import shutil
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("similar_files.status")

from xefm import similar_scan  # noqa: E402


def _tree(root):
    data = os.urandom(4096)
    for rel in ("a.bin", os.path.join("sub", "b.bin")):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    with open(os.path.join(root, "c.bin"), "wb") as f:
        f.write(os.urandom(4096))


def _wait(job, timeout=30.0):
    deadline = time.monotonic() + timeout
    while job.state() not in similar_scan.FINISHED and time.monotonic() < deadline:
        time.sleep(0.1)
    return job.state()


@pytest.fixture
def dirs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _tree(str(src))
    return src, tmp_path / "scans"


def _start(src, base, method=similar_scan.IDENTICAL):
    # A cache of its own, so the test never touches the user's.
    env_cache = os.environ.get("SIMILAR_FILES_CACHE")
    os.environ["SIMILAR_FILES_CACHE"] = str(base.parent / "cache.db")
    try:
        return similar_scan.start([str(src)], method, base=base,
                                  python=sys.executable)
    finally:
        if env_cache is None:
            os.environ.pop("SIMILAR_FILES_CACHE", None)
        else:
            os.environ["SIMILAR_FILES_CACHE"] = env_cache


def test_an_identical_scan_runs_to_the_end_and_writes_its_groups(dirs):
    src, base = dirs
    job = _start(src, base)
    assert _wait(job) == similar_scan.DONE, job.log_path.read_text()
    from xefm import xft
    doc = xft.load(str(job.result_path))
    assert doc.final and doc.complete
    (group,) = doc.root.children
    assert sorted(c.name for c in group.children) == ["a.bin", "b.bin"]
    assert job.summary() == "1 group"
    info = job.info()
    assert info["method"] == "identical" and info["roots"] == [str(src)]
    assert not job.seen
    job.mark_seen()
    assert job.seen


@pytest.mark.skipif(sys.platform == "win32", reason="sessions are POSIX")
def test_the_scan_runs_in_its_own_session(dirs):
    src, base = dirs
    job = _start(src, base)
    pid = job.info()["pid"]
    try:
        assert os.getsid(pid) != os.getsid(0)
    except ProcessLookupError:
        pass  # already finished: nothing left to check, and nothing wrong
    _wait(job)


def test_jobs_are_listed_newest_first(dirs):
    src, base = dirs
    first = _start(src, base)
    _wait(first)
    time.sleep(1.1)  # ids are time-ordered to the second
    second = _start(src, base)
    _wait(second)
    assert [j.id for j in similar_scan.jobs(base)] == [second.id, first.id]


# --------------------------------------------------------------------------- #
# states written by hand
# --------------------------------------------------------------------------- #

def _job(base, name, *, status=None, pid=None, created=None):
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps(
        {"method": "video", "pid": pid, "created": created or time.time()}))
    if status is not None:
        data = {"version": 1, "pid": pid, "started": time.time(), "updated": time.time(),
                "phase": "extract", "done": 3, "total": 12, "out": str(folder / "groups")}
        data.update(status)
        (folder / "status.json").write_text(json.dumps(data))
    return similar_scan.ScanJob(folder)


def _dead_pid():
    import subprocess
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_running_with_a_fresh_heartbeat(tmp_path):
    job = _job(tmp_path, "a", status={"state": "running"}, pid=_dead_pid())
    assert job.state() == similar_scan.RUNNING
    assert job.progress_text() == "extract 25%"
    assert job.label == "Similar videos"


def test_a_stale_scan_whose_process_is_gone_is_lost(tmp_path):
    job = _job(tmp_path, "a", status={"state": "running",
                                      "updated": time.time() - 600}, pid=_dead_pid())
    assert job.state() == similar_scan.LOST


def test_a_stale_scan_whose_process_lives_is_running(tmp_path):
    # A machine that slept: quiet for a long time, but the process is there.
    job = _job(tmp_path, "a", status={"state": "running",
                                      "updated": time.time() - 600}, pid=os.getpid())
    assert job.state() == similar_scan.RUNNING


def test_finished_states_are_read_back(tmp_path):
    done = _job(tmp_path, "d", status={"state": "done", "groups": 4})
    stopped = _job(tmp_path, "s", status={"state": "cancelled", "groups": 2})
    failed = _job(tmp_path, "f", status={"state": "failed"})
    assert (done.state(), done.summary()) == ("done", "4 groups")
    assert stopped.state() == "cancelled" and "2 group(s) so far" in stopped.summary()
    assert failed.state() == "failed" and "log" in failed.summary()


def test_no_status_yet_is_starting_then_lost(tmp_path):
    fresh = _job(tmp_path, "a", pid=_dead_pid())
    assert fresh.state() == similar_scan.STARTING
    old = _job(tmp_path, "b", pid=_dead_pid(), created=time.time() - 600)
    assert old.state() == similar_scan.LOST


def test_stop_creates_the_stop_file(tmp_path):
    job = _job(tmp_path, "a", status={"state": "running"}, pid=os.getpid())
    job.stop()
    assert (job.folder / "stop").exists()


def test_prune_keeps_the_newest_finished_and_every_running_one(tmp_path):
    for i in range(5):
        _job(tmp_path, f"2026010{i}-000000-aaaaaa", status={"state": "done"})
    _job(tmp_path, "20250101-000000-running", status={"state": "running"}, pid=os.getpid())
    similar_scan.prune(tmp_path, keep=2)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["20250101-000000-running", "20260103-000000-aaaaaa",
                     "20260104-000000-aaaaaa"]


def test_prune_drops_seen_scans_before_unseen_ones(tmp_path):
    # #822: the newest finished scans used to be kept whether looked at or
    # not, so an unseen one could go before anyone opened it.
    old_unseen = _job(tmp_path, "20260101-000000-aaaaaa", status={"state": "done"})
    for i in (2, 3):
        _job(tmp_path, f"2026010{i}-000000-aaaaaa", status={"state": "done"}).mark_seen()
    similar_scan.prune(tmp_path, keep=2)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [old_unseen.id, "20260103-000000-aaaaaa"]


def test_remove_deletes_a_finished_scan_and_refuses_a_running_one(tmp_path):
    done = _job(tmp_path, "d", status={"state": "cancelled", "groups": 2})
    running = _job(tmp_path, "r", status={"state": "running"}, pid=os.getpid())
    done.remove()
    assert not done.folder.exists()
    with pytest.raises(ValueError):
        running.remove()
    assert running.folder.exists()


def test_threshold_steps_center_on_similar_files_default():
    from similar_files.registry import extractors
    for method in (similar_scan.IMAGE, similar_scan.VIDEO, similar_scan.AUDIO):
        default = extractors()[method].default_threshold
        steps = dict(similar_scan.threshold_steps(method))
        assert steps[similar_scan.STANDARD] == default
        assert steps[similar_scan.LOOSE] < default < steps[similar_scan.STRICT] <= 1.0
    assert similar_scan.threshold_steps(similar_scan.IDENTICAL) == []


def test_parse_threshold():
    assert similar_scan.parse_threshold(" 0.75 ") == 0.75
    assert similar_scan.parse_threshold("1") == 1.0
    for bad in ("", "x", "-0.1", "1.5"):
        assert similar_scan.parse_threshold(bad) is None


def test_identical_files_ignore_a_threshold(dirs):
    src, base = dirs
    os.environ["SIMILAR_FILES_CACHE"] = str(base.parent / "cache.db")
    try:
        job = similar_scan.start([str(src)], similar_scan.IDENTICAL, threshold=0.5,
                                 base=base, python=sys.executable)
    finally:
        os.environ.pop("SIMILAR_FILES_CACHE", None)
    assert "--threshold" not in job.info()["command"]
    assert job.threshold is None and job.title == "Identical files"
    assert _wait(job) == similar_scan.DONE, job.log_path.read_text()


class TestMergeRoots:
    """#890: a place both panes hold is scanned once."""

    def test_the_same_folder_twice(self, tmp_path):
        a = str(tmp_path)
        assert similar_scan.merge_roots([a, a + os.sep]) == [a]

    def test_a_folder_inside_another_root_is_dropped_whichever_comes_first(self, tmp_path):
        inner = tmp_path / "x" / "y"
        inner.mkdir(parents=True)
        assert similar_scan.merge_roots([str(inner), str(tmp_path)]) == [str(tmp_path)]
        assert similar_scan.merge_roots([str(tmp_path), str(inner)]) == [str(tmp_path)]

    def test_siblings_and_prefixes_are_kept(self, tmp_path):
        a, ab = tmp_path / "a", tmp_path / "ab"
        a.mkdir()
        ab.mkdir()
        assert similar_scan.merge_roots([str(a), str(ab)]) == [str(a), str(ab)]

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges")
    def test_a_symlink_to_a_root_is_the_same_place(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        assert similar_scan.merge_roots([str(real), str(link)]) == [str(real)]


def test_unavailable(monkeypatch):
    assert similar_scan.unavailable(similar_scan.IDENTICAL) is None
    assert "no 'nonsense' method" in similar_scan.unavailable("nonsense")


# --------------------------------------------------------------------------- #
# the app
# --------------------------------------------------------------------------- #

def _key(name, char=None):
    from puikit import Event, EventType
    return Event(type=EventType.KEY, key=name, char=char)


@pytest.fixture
def app(dirs):
    from puikit.backends import create_backend
    from xefm import app as xefm_app
    from xefm.state_manager import XeFMStateManager
    src, base = dirs
    state = tempfile.mkdtemp()
    backend = create_backend("memory")
    backend.open()
    a = xefm_app.XeFMApp(backend, os.path.realpath(str(src)), os.path.realpath(str(src)),
                         left_provided=True, right_provided=True,
                         state_manager=XeFMStateManager(db_path=os.path.join(state, "s.db")))
    a.file_monitor.stop_monitoring()
    a.file_monitor.enabled = False
    a._settle_listings()
    a._scans_base = base
    a._refresh_scans()
    yield a
    backend.close()
    shutil.rmtree(state, ignore_errors=True)


def test_launching_watching_and_opening_a_scan(app, dirs, monkeypatch):
    src, base = dirs
    monkeypatch.setenv("SIMILAR_FILES_CACHE", str(base.parent / "cache.db"))
    monkeypatch.setattr(similar_scan, "xefm_python", sys.executable)
    app.find_similar()
    app.panel.dispatch_event(_key("enter"))          # Identical files
    # No threshold question for identical files (#889); the confirmation
    # names the folder, and both panes show it, so only one Scan button.
    box = app.panel._layers[-1].widget
    assert str(src) in box.message and "threshold" not in box.message
    assert tuple(box.buttons) == ("Scan", "Cancel")
    assert similar_scan.jobs(base) == []
    app.panel.dispatch_event(_key("enter"))          # Scan
    (job,) = similar_scan.jobs(base)
    assert job.info()["threshold"] is None
    assert "--threshold" not in job.info()["command"]
    assert _wait(job) == similar_scan.DONE
    app._scans_dirty = True
    app._pump_scans()
    assert any("1 group" in text for _kind, text in app._jobs_parts())
    assert any("1 group" in text for text, _s in app.log.lines)

    app.show_jobs()
    app.panel.dispatch_event(_key("enter"))          # the scan
    app._settle_listings()
    pane = app.active_pane()
    assert str(pane["path"]).startswith("xft://") and str(pane["path"]).endswith("#")
    assert [f.name for f in pane["files"]] == ["a.bin (1)"]
    assert job.seen
    assert app._jobs_parts() == []


def test_cancelling_the_confirmation_starts_nothing(app, dirs):
    _src, base = dirs
    app.find_similar()
    app.panel.dispatch_event(_key("enter"))          # Identical files
    app.panel.dispatch_event(_key("escape"))
    assert similar_scan.jobs(base) == []


def _start_from_app(app, keys):
    for key in keys:
        app.panel.dispatch_event(_key(key))


def test_a_threshold_is_asked_for_and_recorded(app, dirs, monkeypatch):
    # #889: Similar images asks loose / standard / strict, and the job
    # remembers which threshold produced its groups.
    src, base = dirs
    monkeypatch.setenv("SIMILAR_FILES_CACHE", str(base.parent / "cache.db"))
    monkeypatch.setattr(similar_scan, "xefm_python", sys.executable)
    from xefm.choice_dialog import ChoiceDialog
    app.find_similar()
    _start_from_app(app, ["down", "enter"])          # Similar images
    dialog = app.panel._layers[-1].widget
    assert isinstance(dialog, ChoiceDialog)
    steps = similar_scan.threshold_steps(similar_scan.IMAGE)
    assert [v for v, _l in dialog._rows] == [v for _s, v in steps] + ["other"]
    assert dialog._rows[dialog._index][0] == dict(steps)[similar_scan.STANDARD]
    _start_from_app(app, ["down", "enter"])          # Strict
    strict = dict(steps)[similar_scan.STRICT]
    box = app.panel._layers[-1].widget
    assert f"threshold {similar_scan.format_threshold(strict)}" in box.message
    app.panel.dispatch_event(_key("enter"))          # Scan
    (job,) = similar_scan.jobs(base)
    assert job.threshold == strict
    command = job.info()["command"]
    assert command[command.index("--threshold") + 1] == repr(strict)
    assert job.title == f"Similar images (threshold {similar_scan.format_threshold(strict)})"
    assert _wait(job) == similar_scan.DONE, job.log_path.read_text()


def test_another_threshold_can_be_typed(app, dirs, monkeypatch):
    src, base = dirs
    monkeypatch.setenv("SIMILAR_FILES_CACHE", str(base.parent / "cache.db"))
    monkeypatch.setattr(similar_scan, "xefm_python", sys.executable)
    app.find_similar()
    _start_from_app(app, ["down", "enter"])          # Similar images
    _start_from_app(app, ["down", "down", "enter"])  # Another value...
    dialog = app.panel._layers[-1].widget
    dialog.on_accept("0.65")
    app.panel.render()
    app.panel.dispatch_event(_key("enter"))          # Scan
    (job,) = similar_scan.jobs(base)
    assert job.threshold == 0.65
    _wait(job)


def test_the_other_pane_can_be_scanned_too(app, dirs, tmp_path, monkeypatch):
    # #890: the confirmation lists both panes and offers to scan both.
    src, base = dirs
    monkeypatch.setenv("SIMILAR_FILES_CACHE", str(base.parent / "cache.db"))
    monkeypatch.setattr(similar_scan, "xefm_python", sys.executable)
    there = tmp_path / "there"
    there.mkdir()
    shutil.copy(src / "a.bin", there / "copy.bin")
    from xefm.path import Path
    other = app.pm.get_inactive_pane()
    other["path"] = Path(os.path.realpath(str(there)))
    other["files"] = []
    other["selected_files"] = set()
    app.find_similar()
    app.panel.dispatch_event(_key("enter"))          # Identical files
    box = app.panel._layers[-1].widget
    assert tuple(box.buttons) == ("Scan This Pane", "Scan Both Panes", "Cancel")
    assert "there" in box.message
    _start_from_app(app, ["right", "enter"])         # Scan Both Panes
    (job,) = similar_scan.jobs(base)
    assert job.info()["roots"] == [os.path.realpath(str(src)),
                                   os.path.realpath(str(there))]
    assert _wait(job) == similar_scan.DONE, job.log_path.read_text()
    from xefm import xft
    (group,) = xft.load(str(job.result_path)).root.children
    assert sorted(c.name for c in group.children) == ["a.bin", "b.bin", "copy.bin"]


def test_a_pane_showing_a_list_is_left_out_of_both(app):
    other = app.pm.get_inactive_pane()
    other["virtual"] = {"kind": "list", "title": "picked", "root": None}
    app.find_similar()
    app.panel.dispatch_event(_key("enter"))          # Identical files
    box = app.panel._layers[-1].widget
    assert tuple(box.buttons) == ("Scan", "Cancel")
    assert "shows a list" in box.message
    app.panel.dispatch_event(_key("escape"))


def test_a_remote_pane_is_refused(app):
    from xefm.path import Path
    app.active_pane()["path"] = Path("s3://bucket/photos")
    app.find_similar()
    assert "local folders" in app.log.lines[-1][0]


def test_a_running_scan_offers_its_provisional_groups(app, dirs):
    src, base = dirs
    job = _job(base, "20260101-000000-run", status={"state": "running"}, pid=os.getpid())
    job.result_path.write_text(json.dumps({
        "format": "xft", "version": 1, "final": False,
        "progress": {"done": 1, "total": 4},
        "nodes": [{"name": "g (1)", "children": [
            {"name": "a.bin", "target": str(src / "a.bin"), "extra": {"role": "anchor"}},
            {"name": "b.bin", "target": str(src / "sub" / "b.bin")}]}]}))
    app._refresh_scans()
    app._open_scan(job)
    app.panel.render()
    assert "groups so far" in "\n".join(app.backend.snapshot())
    side = app.pm.active_pane
    before = app.active_pane()["path"]
    app.panel.dispatch_event(_key("enter"))          # Look at the groups so far
    app._settle_listings()
    pane = app.active_pane()
    assert [f.name for f in pane["files"]] == ["g (1)"]
    # In a tab of its own (#612): the folder the pane was in stays put.
    assert len(app.pm.tabs[side]) == 2
    assert app.pm.tabs[side][0]["path"] == before
    from xefm import app as xefm_app
    assert "groups may change" in xefm_app._xft_header_text(pane["path"], 200)


class TestMethods:
    """The launcher offers all four of similar-files' methods (#571):
    identical, images, video and audio. Images need only Pillow, which XeFM
    already ships; video and audio need an external program, and say which."""

    def test_every_method_is_a_similar_files_extractor(self):
        from similar_files.registry import extractors
        names = [m for m, _ in similar_scan.METHODS if m != similar_scan.IDENTICAL]
        assert names == [similar_scan.IMAGE, similar_scan.VIDEO, similar_scan.AUDIO]
        known = extractors()
        for name in names:
            assert name in known, name
            assert name in similar_scan.LABELS

    def test_images_need_nothing_beyond_pillow(self):
        assert similar_scan.unavailable(similar_scan.IMAGE) is None

    def test_audio_without_fpcalc_says_what_to_install(self):
        from unittest.mock import patch
        with patch("shutil.which", return_value=None):
            why = similar_scan.unavailable(similar_scan.AUDIO)
        assert why is not None and "fpcalc" in why


# --------------------------------------------------------------------------- #
# many scans (#822)
# --------------------------------------------------------------------------- #

def _rows(app):
    app._refresh_scans()
    return app._jobs_parts()


def test_one_stopped_scan_gets_the_done_mark_not_the_warning(app, dirs):
    _src, base = dirs
    _job(base, "20260101-000000-aaaaaa", status={"state": "cancelled", "groups": 3})
    assert _rows(app) == [("done", "Similar videos: stopped — 3 group(s) so far")]


def test_finished_scans_collapse_into_one_part(app, dirs):
    _src, base = dirs
    for i in range(3):
        _job(base, f"2026010{i}-000000-aaaaaa", status={"state": "done", "groups": 1})
    _job(base, "20260104-000000-aaaaaa", status={"state": "cancelled"})
    assert _rows(app) == [("done", "4 scans finished")]
    _job(base, "20260105-000000-aaaaaa", status={"state": "failed"})
    assert _rows(app) == [("failed", "5 scans finished, 1 failed")]


def test_running_scans_collapse_into_one_part(app, dirs):
    _src, base = dirs
    _job(base, "20260101-000000-aaaaaa", status={"state": "running"}, pid=os.getpid())
    assert _rows(app) == [("busy", "Similar videos extract 25%")]
    _job(base, "20260102-000000-aaaaaa", status={"state": "running"}, pid=os.getpid())
    _job(base, "20260103-000000-aaaaaa", status={"state": "done"})
    assert _rows(app) == [("busy", "2 scans running"),
                          ("done", "Similar videos: 0 groups")]


def _jobs_dialog(app):
    from xefm.choice_dialog import ChoiceDialog
    app.show_jobs()
    dialog = app.panel._layers[-1].widget
    assert isinstance(dialog, ChoiceDialog)
    return dialog


def test_the_jobs_list_marks_every_finished_scan_seen(app, dirs):
    _src, base = dirs
    for i in range(2):
        _job(base, f"2026010{i}-000000-aaaaaa", status={"state": "done"})
    dialog = _jobs_dialog(app)
    value, label = dialog._rows[-1]
    assert label == "Mark 2 finished scans as seen"
    tabs = len(app.pm.tabs[app.pm.active_pane])
    dialog._index = len(dialog._rows) - 1
    app.panel.dispatch_event(_key("enter"))
    assert _rows(app) == []
    assert len(app.pm.tabs[app.pm.active_pane]) == tabs     # nothing opened


def test_the_remove_key_deletes_a_finished_scan_but_not_a_running_one(app, dirs):
    from puikit import Event, EventType
    _src, base = dirs
    running = _job(base, "20260102-000000-aaaaaa", status={"state": "running"},
                   pid=os.getpid())
    done = _job(base, "20260101-000000-aaaaaa", status={"state": "done"})
    dialog = _jobs_dialog(app)
    remove = Event(type=EventType.KEY, key="delete", modifiers=frozenset({"shift"}))
    app.panel.dispatch_event(remove)                  # the running one, first
    assert running.folder.exists()
    assert "still running" in app.log.lines[-1][0]
    dialog._index = next(i for i, (v, _l) in enumerate(dialog._rows)
                         if v[0] == "scan" and v[1].id == done.id)
    app.panel.dispatch_event(remove)
    assert not done.folder.exists()
    assert [v[1].id for v, _l in dialog._rows if v[0] == "scan"] == [running.id]
