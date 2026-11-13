"""The guests of `make release-test`, all at once.

    python3 tools/release_test.py [--jobs N] <guest>...     # make release-test

Each guest runs `tools/vm.py test --packages pypi <guest>`, and the musl
probe runs `make test-linux-musl`, side by side: they share nothing but the
pip download cache on the share, which pip writes atomically. Run one after
another they took about half an hour; together they take as long as the
slowest guest (qa-win, ten minutes or so). ``--jobs 1`` runs them in turn,
for a host short of memory (each VM takes 8 GB).

Each job's output goes to its own log, temp/release-test-<time>/<name>.log,
so the guests' lines do not interleave here; a line says when each one
starts and ends. A failure does not stop the others: every job runs to its
end, the failed ones' logs are shown at the bottom, and the exit code is 1.
Docker is checked before anything starts, because a container guest is the
one that finds it down (#842's first 1.15.1 run stopped there, a quarter of
an hour in).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Guests that are Docker containers (qa/guest.py's default_guests), besides
#: the musl probe.
DOCKER_GUESTS = ("qa-linux", "qa-linux-floor")

#: The last lines of a failed job's log shown at the end.
TAIL = 40


@dataclasses.dataclass
class Job:
    name: str
    argv: list[str]
    log: pathlib.Path
    code: int | None = None
    seconds: float = 0.0


def jobs_for(guests: list[str], logs: pathlib.Path, musl: bool = True) -> list[Job]:
    make = shutil.which("make") or "make"
    jobs = [Job(guest, [sys.executable, str(ROOT / "tools" / "vm.py"), "test",
                        "--packages", "pypi", guest], logs / f"{guest}.log")
            for guest in guests]
    if musl:
        jobs.append(Job("musl", [make, "--no-print-directory", "test-linux-musl"],
                        logs / "musl.log"))
    return jobs


def _say(line: str) -> None:
    print(f"release-test: {line}", flush=True)


def _run(job: Job) -> Job:
    started = time.monotonic()
    with job.log.open("w", encoding="utf-8", errors="replace") as out:
        job.code = subprocess.run(job.argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                                  stdout=out, stderr=subprocess.STDOUT).returncode
    job.seconds = time.monotonic() - started
    return job


def run_jobs(jobs: list[Job], workers: int) -> int:
    """Every job to its end, ``workers`` at a time; 0 when all passed."""
    for job in jobs:
        job.log.parent.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        pending = {}
        for job in jobs:
            pending[pool.submit(_run, job)] = job
        _say(f"started {', '.join(j.name for j in jobs)}; logs in "
             f"{_shown(jobs[0].log.parent)}")
        for future in concurrent.futures.as_completed(pending):
            job = future.result()
            verdict = "passed" if job.code == 0 else f"FAILED (exit {job.code})"
            _say(f"{job.name} {verdict} in {job.seconds:.0f}s")
    failed = [j for j in jobs if j.code != 0]
    for job in failed:
        lines = job.log.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"\n----- {job.name}: last {TAIL} lines of {_shown(job.log)} -----")
        print("\n".join(lines[-TAIL:]))
    if failed:
        _say(f"FAILED in {', '.join(j.name for j in failed)}")
        return 1
    return 0


def _shown(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def docker_ready() -> bool:
    try:
        said = subprocess.run(["docker", "info"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return said.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--jobs", type=int, default=0,
                        help="how many at a time (default: all at once)")
    parser.add_argument("--no-musl", action="store_true", help="leave out the musl probe")
    parser.add_argument("guests", nargs="+")
    args = parser.parse_args()
    musl = not args.no_musl
    if (musl or set(args.guests) & set(DOCKER_GUESTS)) and not docker_ready():
        _say("the Docker daemon is not reachable (`docker info` failed): start "
             "Docker Desktop, then run this again")
        return 1
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    jobs = jobs_for(args.guests, ROOT / "temp" / f"release-test-{stamp}", musl)
    return run_jobs(jobs, args.jobs or len(jobs))


if __name__ == "__main__":
    sys.exit(main())
