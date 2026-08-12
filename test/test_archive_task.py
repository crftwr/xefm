"""Archive create / extract run as background tasks (issue #280).

Compressing a tree — or decompressing one — used to happen inline in the dialog
callback that started it, freezing the UI for the whole operation: no repaint, no
keys, no way out. Both now go through :class:`~xefm.task.Task` like copy / move /
delete, so this file covers the three things that buys:

- the work happens on the task worker, with the app's task registry seeing it;
- every entry is a progress update, so the bar is determinate rather than a hang;
- every entry is a cancellation point, and a cancelled *create* leaves no
  half-written archive behind.

The password/AES dispatch around extraction lives in
test_xefm_app_archive_password.py.

Run with: python -m pytest test/test_archive_task.py -v
"""

import io
import os
import shutil
import sys
import tarfile
import tempfile
import time
import types
import unittest
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.progress_manager import OperationType, ProgressManager  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from xefm.task import Cancelled, ProgressDialog, Task, TaskManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


def _tree(root, names):
    """Create ``names`` (relative, '/' separated) as files under ``root``."""
    for name in names:
        p = os.path.join(root, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"payload-" + name.encode())


class _InlineTasks(TaskManager):
    """The real task manager forced to run inline, for the flow tests that drive a
    bare app with no live panel to host a progress dialog. The genuine worker
    thread is exercised by ArchiveTaskIntegration below."""

    def submit(self, task, panel, **kw):
        kw["background"] = False
        return super().submit(task, panel, **kw)


# --- the core loops: progress + cancellation ---------------------------------


class ArchiveLoops(unittest.TestCase):
    """``_write_archive`` / ``_extract_archive`` with a Task attached: one progress
    update and one cancellation point per entry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        _tree(self.src, ["a.txt", "b.txt", "sub/c.txt", "sub/deep/d.txt"])
        self.app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
        self.sources = [Path(self.src)]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _task(self, cancel_after=None):
        """A headless task; ``cancel_after`` requests cancellation once that many
        progress updates have been seen (the deterministic stand-in for the user
        hitting Esc mid-run)."""
        task = Task("test", kind="archive")
        task._headless = True
        seen = []
        prog = task.progress

        def on_progress(op):
            if op is None or op.get("counting"):
                return
            item = op.get("current_item")
            if item and (not seen or seen[-1] != item):
                seen.append(item)
                if cancel_after is not None and len(seen) >= cancel_after:
                    task.request_cancel()

        prog.start_operation(OperationType.ARCHIVE_CREATE, 0,
                             progress_callback=on_progress)
        prog.callback_throttle_ms = 0  # report every entry, not one per 50ms
        return task, prog, seen

    # --- counting ------------------------------------------------------------

    def test_count_counts_files_for_zip_and_dirs_too_for_tar(self):
        count = xefm_app.XeFMApp._count_archive_entries
        # 4 files; the tree also has src/, src/sub/ and src/sub/deep/.
        self.assertEqual(count(self.sources, include_dirs=False), 4)
        self.assertEqual(count(self.sources, include_dirs=True), 7)

    def test_count_matches_what_each_writer_actually_adds(self):
        """The bar reaches 100% only if the total and the writer agree."""
        count = xefm_app.XeFMApp._count_archive_entries
        zip_path = Path(os.path.join(self.tmp, "out.zip"))
        self.assertEqual(self.app._write_archive(self.sources, zip_path, "zip"),
                         count(self.sources, include_dirs=False))
        tar_path = Path(os.path.join(self.tmp, "out.tar"))
        self.assertEqual(self.app._write_archive(self.sources, tar_path, "tar"),
                         count(self.sources, include_dirs=True))

    def test_count_survives_an_unreadable_directory(self):
        locked = os.path.join(self.src, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0o000)
        try:
            total = xefm_app.XeFMApp._count_archive_entries(
                self.sources, include_dirs=True)
        finally:
            os.chmod(locked, 0o755)
        self.assertEqual(total, 8)  # counted as itself, not descended into

    # --- create --------------------------------------------------------------

    def test_zip_write_reports_every_file(self):
        task, prog, seen = self._task()
        added = self.app._write_archive(self.sources,
                                        Path(os.path.join(self.tmp, "out.zip")),
                                        "zip", task=task, prog=prog)
        self.assertEqual(added, 4)
        self.assertEqual(len(seen), 4)
        self.assertEqual(prog.get_current_operation()["processed_items"], 4)

    def test_tar_write_reports_every_member(self):
        task, prog, seen = self._task()
        added = self.app._write_archive(self.sources,
                                        Path(os.path.join(self.tmp, "out.tar.gz")),
                                        "tar.gz", task=task, prog=prog)
        self.assertEqual(added, 7)          # 4 files + 3 directories
        self.assertEqual(len(seen), 7)
        with tarfile.open(os.path.join(self.tmp, "out.tar.gz")) as tf:
            self.assertEqual(len(tf.getmembers()), 7)

    def test_zip_write_cancels_mid_archive(self):
        task, prog, seen = self._task(cancel_after=2)
        with self.assertRaises(Cancelled):
            self.app._write_archive(self.sources,
                                    Path(os.path.join(self.tmp, "out.zip")),
                                    "zip", task=task, prog=prog)
        self.assertEqual(len(seen), 2)  # stopped at the checkpoint, didn't finish

    def test_tar_write_cancels_mid_archive(self):
        task, prog, seen = self._task(cancel_after=2)
        with self.assertRaises(Cancelled):
            self.app._write_archive(self.sources,
                                    Path(os.path.join(self.tmp, "out.tar.xz")),
                                    "tar.xz", task=task, prog=prog)
        self.assertEqual(len(seen), 2)

    def test_write_without_a_task_is_unchanged(self):
        """The no-task call is the one the direct callers (and tests) still use."""
        plain = Path(os.path.join(self.tmp, "plain.zip"))
        self.assertEqual(self.app._write_archive(self.sources, plain, "zip"), 4)
        with zipfile.ZipFile(str(plain)) as zf:
            self.assertEqual(sorted(zf.namelist()),
                             ["src/a.txt", "src/b.txt", "src/sub/c.txt",
                              "src/sub/deep/d.txt"])

    # --- extract -------------------------------------------------------------

    def _make(self, fmt):
        path = Path(os.path.join(self.tmp, f"arc.{fmt}"))
        self.app._write_archive(self.sources, path, fmt)
        return path

    def test_zip_extract_reports_every_member(self):
        arc = self._make("zip")
        task, prog, seen = self._task()
        dest = Path(os.path.join(self.tmp, "out"))
        count = self.app._extract_archive(arc, dest, "zip", task=task, prog=prog)
        self.assertEqual(count, 4)
        self.assertEqual(len(seen), 4)
        # The total is set from the member list, so the bar is determinate.
        self.assertEqual(prog.get_current_operation()["total_items"], 4)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "out", "src", "a.txt")))

    def test_tar_extract_reports_every_member_and_keeps_dir_perms(self):
        arc = self._make("tar")
        task, prog, seen = self._task()
        dest = Path(os.path.join(self.tmp, "out"))
        count = self.app._extract_archive(arc, dest, "tar", task=task, prog=prog)
        self.assertEqual(count, 7)
        self.assertEqual(len(seen), 7)
        # Extraction still goes through extractall(), so its deferred directory
        # fix-up still runs: a directory's contents are readable afterwards.
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp, "out", "src", "sub", "deep", "d.txt")))

    def test_extract_cancels_mid_archive(self):
        arc = self._make("zip")
        task, prog, seen = self._task(cancel_after=2)
        dest = Path(os.path.join(self.tmp, "out"))
        with self.assertRaises(Cancelled):
            self.app._extract_archive(arc, dest, "zip", task=task, prog=prog)
        self.assertEqual(len(seen), 2)

    def test_extract_without_a_task_is_unchanged(self):
        arc = self._make("tar.gz")
        dest = Path(os.path.join(self.tmp, "out"))
        self.assertEqual(self.app._extract_archive(arc, dest, "tar.gz"), 7)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "out", "src", "a.txt")))


# --- byte-level progress within one member -----------------------------------


class ArchiveByteProgress(unittest.TestCase):
    """The secondary (byte) bar. A member big enough to matter has to move it
    while it is being written or read, not just before and after — that is the
    whole reason the bar exists, since the item bar sits still for the duration
    of a single large file."""

    #: Big enough for several reports and several compression buffers, small
    #: enough to stay a fast test. Zero bytes compress to nothing, so the write
    #: is quick despite the size.
    SIZE = 8 * 1024 * 1024

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)
        with open(os.path.join(self.src, "big.bin"), "wb") as f:
            f.write(bytes(self.SIZE))
        with open(os.path.join(self.src, "tiny.txt"), "wb") as f:
            f.write(b"x")
        os.makedirs(os.path.join(self.src, "emptydir"))
        self.app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
        self.sources = [Path(self.src)]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _recording_task(self):
        """A headless task that records every `(item, copied, total)` byte sample
        its progress manager publishes."""
        task = Task("test", kind="archive")
        task._headless = True
        samples = []

        def cb(op):
            if op and op.get("file_bytes_total"):
                samples.append((op["current_item"], op["file_bytes_copied"],
                                op["file_bytes_total"]))

        task.progress.start_operation(OperationType.ARCHIVE_CREATE, 0,
                                      progress_callback=cb)
        task.progress.callback_throttle_ms = 0   # keep every sample, not one per 50ms
        return task, task.progress, samples

    def _assert_streams(self, samples, name):
        """The samples for ``name`` must start at zero, only ever move forward,
        and finish exactly on the member's size."""
        mine = [s for s in samples if name in s[0]]
        self.assertGreater(len(mine), 2,
                           f"{name} reported no progress *during* the transfer")
        self.assertEqual(mine[0][1], 0)
        self.assertEqual(mine[-1][1], self.SIZE)
        self.assertEqual(mine[-1][2], self.SIZE)
        self.assertEqual([c for _n, c, _t in mine],
                         sorted(c for _n, c, _t in mine))   # monotonic

    def test_zip_create_streams_the_byte_bar(self):
        task, prog, samples = self._recording_task()
        self.app._write_archive(self.sources, Path(os.path.join(self.tmp, "a.zip")),
                                "zip", task=task, prog=prog)
        self._assert_streams(samples, "big.bin")

    def test_tar_create_streams_the_byte_bar(self):
        task, prog, samples = self._recording_task()
        self.app._write_archive(self.sources, Path(os.path.join(self.tmp, "a.tar.gz")),
                                "tar.gz", task=task, prog=prog)
        self._assert_streams(samples, "big.bin")

    def test_zip_extract_streams_the_byte_bar(self):
        arc = Path(os.path.join(self.tmp, "a.zip"))
        self.app._write_archive(self.sources, arc, "zip")
        task, prog, samples = self._recording_task()
        self.app._extract_archive(arc, Path(os.path.join(self.tmp, "out")), "zip",
                                  task=task, prog=prog)
        self._assert_streams(samples, "big.bin")

    def test_tar_extract_streams_the_byte_bar(self):
        arc = Path(os.path.join(self.tmp, "a.tar.gz"))
        self.app._write_archive(self.sources, arc, "tar.gz")
        task, prog, samples = self._recording_task()
        self.app._extract_archive(arc, Path(os.path.join(self.tmp, "out")), "tar.gz",
                                  task=task, prog=prog)
        self._assert_streams(samples, "big.bin")

    def test_payloadless_members_show_no_byte_bar(self):
        """A directory or an empty file has no bytes to report, and the dialog
        draws the secondary bar only while a total is set — so nothing must set
        one for them."""
        with open(os.path.join(self.src, "empty.bin"), "wb"):
            pass
        task, prog, samples = self._recording_task()
        self.app._write_archive(self.sources, Path(os.path.join(self.tmp, "a.tar")),
                                "tar", task=task, prog=prog)
        for name, _copied, total in samples:
            self.assertNotIn("emptydir", name)
            self.assertNotIn("empty.bin", name)
            self.assertGreater(total, 0)

    def test_reports_are_rate_limited(self):
        """Counting happens per buffer (8 KiB for zip); reporting must not, or a
        large member would take a six-figure number of locks to copy."""
        task, prog, samples = self._recording_task()
        self.app._write_archive(self.sources, Path(os.path.join(self.tmp, "a.zip")),
                                "zip", task=task, prog=prog)
        big = [s for s in samples if "big.bin" in s[0]]
        self.assertLess(len(big), 250)             # ~200 by design, not 1024
        self.assertGreater(len(big), 10)           # but still a moving bar

    # --- what the stdlib hooks must not have broken --------------------------

    def _marked_file(self):
        """A source file with distinctive mode and mtime to trace through."""
        marked = os.path.join(self.src, "marked.sh")
        with open(marked, "wb") as f:
            f.write(b"#!/bin/sh\n")
        os.chmod(marked, 0o750)
        os.utime(marked, (1000000000, 1000000000))
        return marked

    def test_zip_members_match_a_stock_write(self):
        """The byte counting hangs off `ZipFile.open` so `zf.write()` keeps
        deriving each member's metadata itself; a hand-rolled copy loop would have
        to rebuild all of it. Compared against stock zipfile rather than against
        expectations, so the bar is "identical", not "plausible". (Restoring the
        mode on *extract* is not tested because zipfile never has — extractall
        leaves the umask default either way.)"""
        self._marked_file()
        arc = Path(os.path.join(self.tmp, "hooked.zip"))
        task, prog, _ = self._recording_task()
        self.app._write_archive(self.sources, arc, "zip", task=task, prog=prog)

        stock = os.path.join(self.tmp, "stock.zip")
        with zipfile.ZipFile(stock, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(os.path.join(self.src, "marked.sh"), "src/marked.sh")

        def fields(path):
            with zipfile.ZipFile(path) as zf:
                i = zf.getinfo("src/marked.sh")
                return (i.external_attr, i.date_time, i.CRC, i.file_size,
                        i.compress_type, i.create_system)

        self.assertEqual(fields(str(arc)), fields(stock))
        self.assertEqual(fields(str(arc))[0] >> 16, 0o100750)   # mode really is in there

    def test_tar_round_trip_preserves_mode_and_mtime(self):
        """tar *does* restore attributes on extract (the `data` filter keeps the
        mode bits it does not consider unsafe), so this one runs end to end."""
        self._marked_file()
        arc = Path(os.path.join(self.tmp, "meta.tar"))
        dest = Path(os.path.join(self.tmp, "meta-out"))
        task, prog, _ = self._recording_task()
        self.app._write_archive(self.sources, arc, "tar", task=task, prog=prog)
        task, prog, _ = self._recording_task()
        self.app._extract_archive(arc, dest, "tar", task=task, prog=prog)
        out = os.path.join(str(dest), "src", "marked.sh")
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o750)
        self.assertEqual(int(os.stat(out).st_mtime), 1000000000)

    def test_zip_extraction_still_sanitizes_member_paths(self):
        """Extraction goes through `extractall`/`_extract_member` precisely so its
        path sanitization still applies; a member naming its way out of the
        destination must land inside it anyway."""
        arc = os.path.join(self.tmp, "evil.zip")
        with zipfile.ZipFile(arc, "w") as zf:
            zf.writestr("../escaped.txt", b"nope")
        dest = Path(os.path.join(self.tmp, "out"))
        task, prog, _ = self._recording_task()
        self.app._extract_archive(Path(arc), dest, "zip", task=task, prog=prog)
        self.assertTrue(os.path.exists(os.path.join(str(dest), "escaped.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escaped.txt")))

    def test_tar_extraction_still_applies_the_data_filter(self):
        """Likewise `filter="data"` — passing `members=` must not have dropped it."""
        arc = os.path.join(self.tmp, "evil.tar")
        with tarfile.open(arc, "w") as tf:
            info = tarfile.TarInfo("../escaped.txt")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"nope"))
        dest = Path(os.path.join(self.tmp, "out"))
        task, prog, _ = self._recording_task()
        with self.assertRaises(tarfile.OutsideDestinationError):
            self.app._extract_archive(Path(arc), dest, "tar", task=task, prog=prog)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escaped.txt")))


# --- the flow: what a cancelled / failed run leaves behind ---------------------


class ArchiveFlowOutcomes(unittest.TestCase):
    """``create_archive``'s task body, driven inline: what lands on disk and in the
    log when the write is cancelled or fails."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        self.dest = os.path.join(self.tmp, "dest")
        os.makedirs(self.dest)
        _tree(self.src, ["a.txt"])

        app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
        app.logs = []
        app.log_info = app.logs.append
        app.panel = types.SimpleNamespace(render=lambda: None)
        app._active_pane_region = lambda: (0.0, 80.0)
        app.config = types.SimpleNamespace()
        app.tasks = _InlineTasks()
        app.pm = types.SimpleNamespace(
            get_inactive_pane=lambda: {"path": Path(self.dest)})
        app.active_pane = lambda: {"files": [], "selected_files": set()}
        app._selected_or_focused = lambda pane: [Path(self.src)]
        app._is_archive = lambda p: False
        app._relist = lambda pane, **kw: None
        app.flm = types.SimpleNamespace(show_hidden=False)
        self.app = app

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create(self, name, monkeypatched=None):
        """Run create_archive up to and including its write, answering the filename
        prompt with ``name``."""
        captured = []
        real_show_input = xefm_app.show_input
        xefm_app.show_input = lambda panel, **kw: captured.append(kw)
        try:
            if monkeypatched is not None:
                self.app._write_archive = monkeypatched
            self.app.create_archive()
            captured[-1]["on_accept"](name)
        finally:
            xefm_app.show_input = real_show_input

    def test_cancelled_create_removes_the_partial_archive(self):
        target = os.path.join(self.dest, "out.zip")

        def half_write(sources, archive_path, fmt, *, task=None, prog=None):
            with open(str(archive_path), "wb") as f:   # a truncated archive
                f.write(b"PK\x03\x04partial")
            raise Cancelled()

        self._create("out.zip", monkeypatched=half_write)
        self.assertFalse(os.path.exists(target))       # rubble cleared
        self.assertIn("Archive creation cancelled — out.zip removed", self.app.logs)

    def test_cancelling_during_the_count_claims_no_removal(self):
        """Cancelling before the write means there is no file to have removed, and
        the log should not say otherwise."""
        def no_count(sources, *, include_dirs, task=None):
            raise Cancelled()

        self.app._count_archive_entries = no_count
        self._create("out.zip")
        self.assertFalse(os.path.exists(os.path.join(self.dest, "out.zip")))
        self.assertIn("Archive creation cancelled", self.app.logs)

    def test_failed_create_is_reported(self):
        def boom(sources, archive_path, fmt, *, task=None, prog=None):
            raise OSError("No space left on device")

        self._create("out.zip", monkeypatched=boom)
        self.assertTrue(any("Archive creation failed: No space left" in m
                            for m in self.app.logs))

    def test_successful_create_writes_and_logs(self):
        self._create("out.zip")
        self.assertTrue(os.path.exists(os.path.join(self.dest, "out.zip")))
        self.assertTrue(any("Created out.zip (1 file(s))" in m for m in self.app.logs))


# --- integration: it really runs off the UI thread ----------------------------


class ArchiveTaskIntegration(unittest.TestCase):
    """A real XeFMApp on a MemoryBackend: create and extract through the actual
    task manager, worker thread and progress dialog."""

    def setUp(self):
        self.left = tempfile.mkdtemp()
        self.right = tempfile.mkdtemp()
        _tree(self.left, ["one.txt", "two.txt", "sub/three.txt"])

        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.left, self.right,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.panel.set_text_effect(False)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self._captured = []
        self._real_show_input = xefm_app.show_input
        xefm_app.show_input = lambda panel, **kw: self._captured.append(kw)

    def tearDown(self):
        xefm_app.show_input = self._real_show_input
        try:
            self.app.file_monitor.stop_monitoring()
        except Exception:
            pass
        self.b.close()
        for d in (self.left, self.right, self.state_dir):
            shutil.rmtree(d, ignore_errors=True)

    def _drain(self):
        """Pump the UI until the task finishes, as the event loop would."""
        deadline = time.time() + 5
        while self.app.tasks.has_active() and time.time() < deadline:
            self.b.run_animation_ticks()
            time.sleep(0.005)
        self.b.run_animation_ticks()
        self.assertFalse(self.app.tasks.has_active(), "task did not finish")

    def _select_all(self):
        pane = self.app.active_pane()
        pane["selected_files"] = {str(f) for f in pane["files"] if f.name != ".."}
        return pane

    def test_create_archive_runs_on_the_worker(self):
        self._select_all()
        self.app.create_archive()
        self.assertTrue(self._captured, "no filename prompt")
        self._captured[-1]["on_accept"]("bundle.zip")

        # The work is submitted, not done: a task is live and the UI is still
        # being pumped — which is the whole point of the issue.
        self.assertTrue(self.app.tasks.has_active())
        self.assertIsInstance(self.app.panel._layers[-1].widget, ProgressDialog)
        depth = len(self.app.panel._layers)
        self._drain()
        # …and the dialog takes itself back off again (it pops only while it is
        # the top layer, so being pushed from a dialog callback that had not yet
        # closed would strand it on screen).
        self.assertEqual(len(self.app.panel._layers), depth - 1)

        out = os.path.join(self.right, "bundle.zip")
        self.assertTrue(os.path.exists(out))
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(sorted(n for n in zf.namelist()),
                             ["one.txt", "sub/three.txt", "two.txt"])

    def test_extract_archive_runs_on_the_worker(self):
        arc = os.path.join(self.left, "packed.zip")
        with zipfile.ZipFile(arc, "w") as zf:
            zf.writestr("x.txt", b"hello")
            zf.writestr("nested/y.txt", b"world")
        self.app._refresh(self.app.active_pane())
        self.app._settle_listings()          # listings are async; wait for the row
        pane = self.app.active_pane()
        pane["focused_index"] = next(i for i, f in enumerate(pane["files"])
                                     if f.name == "packed.zip")
        self.app.config.CONFIRM_EXTRACT_ARCHIVE = False

        self.app.extract_archive()
        self.assertTrue(self.app.tasks.has_active())
        self._drain()

        self.assertEqual(
            open(os.path.join(self.right, "packed", "nested", "y.txt")).read(),
            "world")


if __name__ == "__main__":
    unittest.main()
