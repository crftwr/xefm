"""Run `msstore publish` and return once the Store submission is committed.

`msstore publish` uploads the package, commits the submission, prints
"Submission commit success!" with the package list -- and then never exits.
Certification takes hours and needs nothing from this machine, so a release
target that waits on the CLI hangs indefinitely (and every past release left
one such process behind). This wrapper streams the CLI's output unchanged,
and once the commit-success line has appeared it gives the CLI a short grace
period to exit by itself, then ends its process tree and reports success.

If the CLI exits before committing, its exit code is passed through (a
zero exit without the success line is reported as a failure: nothing
confirmed the submission). Poll certification afterwards with
`msstore submission status <product id>`.

Usage: python tools/msstore_publish.py <msstore publish arguments...>
"""

import shutil
import subprocess
import sys
import threading

SUCCESS_MARKER = b"Submission commit success!"
# After the marker the CLI prints the package list; allow it to finish
# printing (and to exit, should a future version fix the hang).
GRACE_SECONDS = 20


def _kill_tree(proc):
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.kill()
    proc.wait()


def main(argv):
    exe = shutil.which("msstore")
    if exe is None:
        print("ERROR: msstore CLI not found on PATH.", file=sys.stderr)
        return 1

    proc = subprocess.Popen(
        [exe, "publish", *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    committed = threading.Event()

    def pump():
        out = sys.stdout.buffer
        for line in iter(proc.stdout.readline, b""):
            out.write(line)
            out.flush()
            if SUCCESS_MARKER in line:
                committed.set()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    # Wait for either the CLI to exit or the commit to be confirmed.
    while proc.poll() is None and not committed.wait(timeout=1):
        pass
    if not committed.is_set():
        # The CLI exited; drain what it printed last before judging it.
        reader.join(timeout=5)

    if committed.is_set():
        try:
            proc.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
        reader.join(timeout=5)
        print()
        print("Submission committed; certification continues in Partner Center.")
        print("Poll it with: msstore submission status <product id>")
        return 0

    code = proc.returncode
    if code == 0:
        print(
            "ERROR: msstore exited without reporting a committed submission.",
            file=sys.stderr,
        )
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
