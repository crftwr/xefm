"""tools/release_test.py - the release's guests side by side - checked with
stand-in jobs instead of guests.

Run with: python -m pytest test/test_release_test.py -v
"""

import pathlib
import sys
import time

import pytest

# The host's tooling: in a guest there is no tools/vm.py to run (#836).
pytestmark = pytest.mark.host_only

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import release_test  # noqa: E402  (tools/release_test.py)


def _job(tmp_path, name, code, seconds=0.0):
    script = f"import time; print('hello from {name}'); time.sleep({seconds}); raise SystemExit({code})"
    return release_test.Job(name, [sys.executable, "-c", script], tmp_path / f"{name}.log")


def test_every_guest_and_the_musl_probe_get_a_job(tmp_path):
    jobs = release_test.jobs_for(["qa-mac", "qa-win"], tmp_path)
    assert [j.name for j in jobs] == ["qa-mac", "qa-win", "musl"]
    assert jobs[0].argv[-4:] == ["test", "--packages", "pypi", "qa-mac"]
    assert jobs[2].argv[-1] == "test-linux-musl"
    assert {j.log for j in jobs} == {tmp_path / f"{n}.log" for n in ("qa-mac", "qa-win", "musl")}
    assert [j.name for j in release_test.jobs_for(["qa-mac"], tmp_path, musl=False)] == ["qa-mac"]


def test_jobs_run_side_by_side(tmp_path):
    jobs = [_job(tmp_path, f"g{i}", 0, seconds=1.0) for i in range(3)]
    started = time.monotonic()
    assert release_test.run_jobs(jobs, workers=3) == 0
    assert time.monotonic() - started < 2.5
    assert all(j.code == 0 for j in jobs)


def test_each_job_writes_its_own_log(tmp_path):
    jobs = [_job(tmp_path / "logs", "a", 0), _job(tmp_path / "logs", "b", 0)]
    release_test.run_jobs(jobs, workers=2)
    assert (tmp_path / "logs" / "a.log").read_text().strip() == "hello from a"
    assert (tmp_path / "logs" / "b.log").read_text().strip() == "hello from b"


def test_a_failure_lets_the_others_finish_and_fails_the_run(tmp_path, capsys):
    jobs = [_job(tmp_path, "bad", 3), _job(tmp_path, "slow", 0, seconds=0.5)]
    assert release_test.run_jobs(jobs, workers=2) == 1
    assert [j.code for j in jobs] == [3, 0]
    out = capsys.readouterr().out
    assert "bad FAILED (exit 3)" in out
    assert "slow passed" in out
    assert "hello from bad" in out          # the failed job's log tail is shown
    assert "hello from slow" not in out     # a passing one's is not


def test_one_at_a_time_when_asked(tmp_path):
    jobs = [_job(tmp_path, f"g{i}", 0, seconds=0.4) for i in range(3)]
    started = time.monotonic()
    assert release_test.run_jobs(jobs, workers=1) == 0
    assert time.monotonic() - started >= 1.2
