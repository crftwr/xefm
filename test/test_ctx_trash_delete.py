"""``ctx.trash`` / ``ctx.delete`` — removing files from an action (#782).

They run what K (with the trash on) and Shift-K run — the confirmation,
progress, the offer to delete for good what has no trash — on items the action
chose, and report through ``on_done(ctx, outcome)`` as ``ctx.copy`` does: on
the UI thread, once it is over, never before the call returns, with a list of
``ItemResult`` (``dest`` None, ``permanent`` set for what was deleted for
good).

A headless XeFMApp on the memory backend over a real temp tree. The system's
trash is never touched: ``trash.available`` / ``trash.send`` are replaced by a
folder in the temp tree.

Run with: python -m pytest test/test_ctx_trash_delete.py -v
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import file_operations  # noqa: E402
from xefm import trash  # noqa: E402
from xefm.file_operations import FileOperationService  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.user_api import ActionContext, ItemResult  # noqa: E402


class CtxTrashDelete(unittest.TestCase):

    def setUp(self):
        from xefm.state_manager import XeFMStateManager
        from puikit.backends import create_backend
        # realpath: macOS /var is a symlink to /private/var (xefm#505).
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.cfgdir = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        self.other = os.path.join(self.tmp, "other")
        self.bin = os.path.join(self.tmp, "bin")
        for d in (self.src, self.other, self.bin):
            os.mkdir(d)
        for name in ("a.txt", "b.txt"):
            with open(os.path.join(self.src, name), "w") as f:
                f.write(name)
        os.mkdir(os.path.join(self.src, "dir"))
        with open(os.path.join(self.src, "dir", "inner.txt"), "w") as f:
            f.write("inner")
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.src, self.other,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app._settle_listings()
        # No confirmation, so the operation starts on the call; the tests that
        # are about the confirmation turn it back on.
        for flag in ("CONFIRM_DELETE", "CONFIRM_TRASH"):
            patcher = mock.patch.object(self.app.config, flag, False, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        #: Names ``send`` refuses as online-only (NoTrashError).
        self.online_only = set()
        self.has_trash = True
        for name, fake in (("available", lambda path: self.has_trash),
                           ("send", self.fake_send)):
            patcher = mock.patch.object(trash, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.outcomes = []

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
            self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def fake_send(self, path):
        if path.name in self.online_only:
            raise trash.NoTrashError(0, "online-only")
        shutil.move(str(path), os.path.join(self.bin, path.name))

    def ctx(self):
        return ActionContext(self.app)

    def on_done(self, ctx, outcome):
        self.assertIsInstance(ctx, ActionContext)
        self.outcomes.append(outcome)

    def settle(self, timeout=10.0):
        """Drive ticks and the pump until ``on_done`` has run."""
        deadline = time.monotonic() + timeout
        while not self.outcomes and time.monotonic() < deadline:
            self.backend.run_animation_ticks()
            self.app._pump_monitoring()
            time.sleep(0.01)
        self.assertEqual(len(self.outcomes), 1, "on_done did not run once")
        return self.outcomes[0]

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def answering(self, *labels):
        """A ``show_message_box`` that answers each box with the next label
        (a button's label, or ``-1`` for the last button, Cancel), recording
        the messages it was shown."""
        answers = list(labels)
        self.shown = []

        def answer(panel, message, *, buttons, on_result, **kw):
            self.shown.append((message, buttons, kw.get("default")))
            label = answers.pop(0)
            on_result(buttons[-1] if label == -1 else label)

        return mock.patch.object(file_operations, "show_message_box", answer)

    # --- trash ----------------------------------------------------------------

    def test_trash_reports_each_item_in_order(self):
        entries = sorted(self.ctx().pane.entries, key=lambda e: e.name)
        self.ctx().trash(entries, on_done=self.on_done)
        self.assertEqual(self.outcomes, [], "on_done ran before trash returned")
        outcome = self.settle()
        self.assertEqual(outcome.status, "done")
        self.assertEqual([(r.source.name, r.status, r.dest, r.permanent)
                          for r in outcome.value],
                         [("a.txt", "done", None, False),
                          ("b.txt", "done", None, False),
                          ("dir", "done", None, False)])
        self.assertTrue(all(isinstance(r, ItemResult) for r in outcome.value))
        self.assertEqual(sorted(os.listdir(self.bin)), ["a.txt", "b.txt", "dir"])

    def test_trash_ignores_delete_to_trash(self):
        with mock.patch.object(self.app.config, "DELETE_TO_TRASH", False,
                               create=True):
            self.ctx().trash([self.path("src", "a.txt")], on_done=self.on_done)
            outcome = self.settle()
        self.assertFalse(outcome.value[0].permanent)
        self.assertTrue(os.path.exists(self.path("bin", "a.txt")))

    def test_no_trash_deletes_for_good_after_saying_so(self):
        self.has_trash = False
        with mock.patch.object(self.app.config, "CONFIRM_DELETE", True), \
                self.answering("Delete"):
            self.ctx().trash([self.path("src", "a.txt")], on_done=self.on_done)
            outcome = self.settle()
        self.assertIn(f"There is no {trash.NAME} here", self.shown[0][0])
        self.assertEqual([(r.status, r.permanent) for r in outcome.value],
                         [("done", True)])
        self.assertFalse(os.path.exists(self.path("src", "a.txt")))
        self.assertEqual(os.listdir(self.bin), [])

    def test_online_only_is_offered_a_permanent_delete(self):
        self.online_only = {"b.txt"}
        with mock.patch.object(self.app.config, "CONFIRM_DELETE", True), \
                self.answering("Delete"):
            self.ctx().trash([self.path("src", "a.txt"), self.path("src", "b.txt")],
                             on_done=self.on_done)
            outcome = self.settle()
        self.assertIn("online-only", self.shown[0][0])
        self.assertEqual([(r.source.name, r.status, r.permanent, r.errors)
                          for r in outcome.value],
                         [("a.txt", "done", False, []), ("b.txt", "done", True, [])])
        self.assertFalse(os.path.exists(self.path("src", "b.txt")))

    def test_declining_the_offer_keeps_the_item(self):
        self.online_only = {"b.txt"}
        with mock.patch.object(self.app.config, "CONFIRM_DELETE", True), \
                self.answering(-1):
            self.ctx().trash([self.path("src", "a.txt"), self.path("src", "b.txt")],
                             on_done=self.on_done)
            outcome = self.settle()
        self.assertEqual(outcome.status, "done")
        self.assertEqual([(r.source.name, r.status, r.permanent)
                          for r in outcome.value],
                         [("a.txt", "done", False), ("b.txt", "skipped", False)])
        self.assertTrue(os.path.exists(self.path("src", "b.txt")))

    def test_trash_confirmation_defaults_to_moving(self):
        with mock.patch.object(self.app.config, "CONFIRM_TRASH", True), \
                self.answering(f"Move to {trash.NAME}"):
            self.ctx().trash([self.path("src", "a.txt")], on_done=self.on_done)
            outcome = self.settle()
        _message, buttons, default = self.shown[0]
        self.assertEqual(buttons[default], f"Move to {trash.NAME}")
        self.assertEqual(outcome.status, "done")

    # --- delete ---------------------------------------------------------------

    def test_delete_removes_for_good(self):
        self.ctx().delete([Path(self.path("src", "dir")), self.path("src", "a.txt")],
                          on_done=self.on_done)
        outcome = self.settle()
        self.assertEqual([(r.source.name, r.status, r.dest, r.permanent)
                          for r in outcome.value],
                         [("dir", "done", None, True), ("a.txt", "done", None, True)])
        self.assertFalse(os.path.exists(self.path("src", "dir")))
        self.assertEqual(os.listdir(self.bin), [])

    def test_delete_confirmation_defaults_to_cancel(self):
        with mock.patch.object(self.app.config, "CONFIRM_DELETE", True), \
                self.answering(-1):
            self.ctx().delete([self.path("src", "a.txt")], on_done=self.on_done)
            outcome = self.settle()
        _message, buttons, default = self.shown[0]
        self.assertEqual(buttons[default], "Cancel")
        self.assertEqual((outcome.status, outcome.value), ("cancelled", []))
        self.assertTrue(os.path.exists(self.path("src", "a.txt")))

    def test_a_failed_item_is_failed(self):
        self.ctx().delete([self.path("src", "gone.txt")], on_done=self.on_done)
        outcome = self.settle()
        (result,) = outcome.value
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.permanent)
        self.assertTrue(result.errors)

    def test_panes_showing_the_folder_are_relisted(self):
        self.ctx().delete([self.path("src", "a.txt")], on_done=self.on_done)
        self.settle()
        self.app._settle_listings()
        names = [f.name for f in self.app.pm.left_pane["files"]]
        self.assertNotIn("a.txt", names)
        self.assertIn("b.txt", names)

    def test_a_broken_operation_is_failed(self):
        def boom(*args, **kwargs):
            raise OSError("disk on fire")

        with mock.patch.object(FileOperationService, "_run", boom):
            self.ctx().delete([self.path("src", "a.txt")], on_done=self.on_done)
            outcome = self.settle()
        self.assertEqual(outcome.status, "failed")
        self.assertIsInstance(outcome.error, OSError)

    def test_an_empty_list_is_done_with_nothing(self):
        for call in (self.ctx().trash, self.ctx().delete):
            self.outcomes = []
            call([], on_done=self.on_done)
            self.assertEqual(self.outcomes, [])
            outcome = self.settle()
            self.assertEqual((outcome.status, outcome.value), ("done", []))

    # --- arguments ----------------------------------------------------------

    def test_a_relative_string_is_an_error(self):
        for call in (self.ctx().trash, self.ctx().delete):
            with self.assertRaises(ValueError):
                call(["a.txt"])

    def test_an_archive_item_is_an_error(self):
        for call in (self.ctx().trash, self.ctx().delete):
            with self.assertRaises(ValueError):
                call(["archive:///x.zip/a.txt"])

    def test_off_the_ui_thread_is_an_error(self):
        errors = []

        def worker():
            try:
                self.ctx().delete([self.path("src", "a.txt")])
            except RuntimeError as exc:
                errors.append(exc)

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(len(errors), 1)
        self.assertTrue(os.path.exists(self.path("src", "a.txt")))


if __name__ == "__main__":
    unittest.main()
