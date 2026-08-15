"""FilterListDialog background loader — streamed rows land in an open dialog.

The drives picker opens with its local/SSH rows and hands the S3 bucket scan to
the dialog's ``load_more`` loader (issue #274). Covered here without an app:
with no panel attached the loader settles synchronously (join + drain), so the
streaming logic runs deterministically — values append below the eager rows,
the active filter applies to them, and the selection/scroll survive the append.
Closing the dialog sets the loader's cancel event. One test drives the real
tick path through a MemoryBackend panel: the dialog opens before the loader
finishes, and ``run_animation_ticks`` installs the streamed rows afterwards.
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit import Panel  # noqa: E402
from puikit.backends import create_backend  # noqa: E402

from xefm.filter_list_dialog import FilterListDialog, show_filter_list  # noqa: E402


class SettledStreaming(unittest.TestCase):
    """No panel -> ``_ensure_ticking`` settles synchronously, exercising the
    worker/queue/drain pipeline in one deterministic shot."""

    def test_streamed_rows_append_after_eager_ones(self):
        d = FilterListDialog(["alpha"], load_more=lambda cancel: iter(["beta", "gamma"]))
        d._start_load_more()
        self.assertEqual(d.all_items, ["alpha", "beta", "gamma"])
        self.assertEqual(d.list.items, ["alpha", "beta", "gamma"])
        self.assertFalse(d._loading)

    def test_active_filter_applies_to_streamed_rows(self):
        d = FilterListDialog(["apple", "banana"],
                             load_more=lambda cancel: iter(["apricot", "berry"]))
        d.filter_edit.text = "ap"
        d._refilter("ap")  # the user had already typed before the scan landed
        d._start_load_more()
        self.assertEqual(d.filtered, ["apple", "apricot"])
        self.assertEqual(d.list.items, ["apple", "apricot"])
        self.assertEqual(d.all_items, ["apple", "banana", "apricot", "berry"])

    def test_selection_survives_streamed_append(self):
        d = FilterListDialog(["alpha", "beta"], load_more=lambda cancel: iter(["gamma"]))
        d.list.selected = 1  # user is on "beta" when the scan lands
        d._start_load_more()
        self.assertEqual(d.list.selected, 1)
        self.assertEqual(d.list.items, ["alpha", "beta", "gamma"])

    def test_loader_error_keeps_rows_yielded_so_far(self):
        def load(cancel):
            yield "beta"
            raise RuntimeError("network gone")

        d = FilterListDialog(["alpha"], load_more=load)
        d._start_load_more()
        self.assertEqual(d.list.items, ["alpha", "beta"])
        self.assertFalse(d._loading)  # the spinner never sticks after a failure

    def test_no_loader_means_no_thread(self):
        d = FilterListDialog(["alpha"])
        d._start_load_more()
        self.assertIsNone(d._load_thread)
        self.assertFalse(d._loading)


class CloseCancelsLoader(unittest.TestCase):
    def test_close_sets_cancel_and_the_worker_stops(self):
        # A ticking panel (mocked) keeps _start_load_more from settling, so the
        # worker runs free until _close cancels it.
        def load(cancel):
            yield "one"
            cancel.wait(2.0)
            if not cancel.is_set():
                yield "late"

        panel = MagicMock()
        panel.request_animation_ticks.return_value = True
        d = FilterListDialog(["alpha"], load_more=load)
        d._panel = panel
        d._start_load_more()
        d._close()
        self.assertTrue(d._load_cancel.is_set())
        d._load_thread.join(timeout=2.0)
        self.assertFalse(d._load_thread.is_alive())


class StreamsIntoOpenDialog(unittest.TestCase):
    """The real tick path on a MemoryBackend panel: the dialog is open and
    usable before the loader finishes; the tick installs the rows after."""

    def setUp(self):
        self.b = create_backend("memory")
        self.b.open()
        self.panel = Panel(self.b)

    def tearDown(self):
        self.b.close()

    def test_dialog_opens_before_rows_arrive(self):
        gate = threading.Event()

        def load(cancel):
            gate.wait(2.0)  # a slow network scan
            yield "gamma"

        d = show_filter_list(self.panel, ["alpha", "beta"], title="Drives",
                             load_more=load)
        # Open immediately, scan still in flight: eager rows only, spinner on.
        self.assertEqual(d.list.items, ["alpha", "beta"])
        self.assertTrue(d._loading)
        self.panel.render()  # the loading title draws without incident

        gate.set()
        d._load_thread.join(timeout=2.0)
        self.b.run_animation_ticks()  # the drain tick installs the rows
        self.assertEqual(d.list.items, ["alpha", "beta", "gamma"])
        self.assertFalse(d._loading)


if __name__ == "__main__":
    unittest.main()
