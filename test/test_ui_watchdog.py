"""
XeFM's side of the UI-thread stall detector (issue #407).

The detector itself lives in PuiKit — it brackets the event loop, so it has to.
XeFM contributes the two things that make it usable here: a command-line switch
that turns it on for one run, and a route from PuiKit's logger into the log
pane, without which the reports would fall to ``logging.lastResort`` and land
unformatted on a stderr the GUI backends do not have.

Run with: python -m pytest test/test_ui_watchdog.py -v
"""

import logging
import os
import sys
import threading
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import log_manager  # noqa: E402
from xefm.app import create_parser, main  # noqa: E402
from xefm.log_manager import (LOG_ERROR_SOURCE, clear_log_sink,  # noqa: E402
                              route_library_logger, set_log_sink)
from puikit import _watchdog  # noqa: E402


class TestCommandLineSwitch(unittest.TestCase):
    """``--ui-watchdog`` is a switch with an optional threshold."""

    def test_absent_by_default(self):
        args = create_parser().parse_args([])
        self.assertIsNone(args.ui_watchdog)

    def test_bare_switch_means_the_default_threshold(self):
        args = create_parser().parse_args(["--ui-watchdog"])
        self.assertEqual(args.ui_watchdog, "1")

    def test_a_threshold_in_milliseconds_is_carried_through(self):
        args = create_parser().parse_args(["--ui-watchdog", "500"])
        self.assertEqual(args.ui_watchdog, "500")

    def test_it_does_not_consume_the_pane_flags(self):
        args = create_parser().parse_args(["--ui-watchdog", "--left", "/tmp"])
        self.assertEqual(args.ui_watchdog, "1")
        self.assertEqual(args.left, "/tmp")


class TestMainPublishesTheSwitch(unittest.TestCase):
    """PuiKit reads the variable when the backend opens, so ``main`` must set it
    before creating one — not after."""

    def setUp(self):
        self._saved = os.environ.get("PUIKIT_UI_WATCHDOG")
        os.environ.pop("PUIKIT_UI_WATCHDOG", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("PUIKIT_UI_WATCHDOG", None)
        else:
            os.environ["PUIKIT_UI_WATCHDOG"] = self._saved

    def _run_main(self, argv):
        seen = {}

        def create_backend(name, **kwargs):
            # Sampled at the moment PuiKit would read it.
            seen["env"] = os.environ.get("PUIKIT_UI_WATCHDOG")
            return mock.MagicMock()

        with mock.patch("sys.argv", ["xefm"] + argv), \
                mock.patch("xefm.app.create_backend", create_backend), \
                mock.patch("xefm.app.XeFMApp"):
            main()
        return seen["env"]

    def test_the_threshold_reaches_puikit(self):
        self.assertEqual(self._run_main(["--ui-watchdog", "500"]), "500")

    def test_off_unless_asked_for(self):
        self.assertIsNone(self._run_main([]))


class LogRouteBase(unittest.TestCase):
    """Start and finish the way XeFM runs: no LogManager, no sink, no backlog.
    All three are process-wide, as is the handler this attaches to a logger that
    belongs to another package."""

    def setUp(self):
        self._saved_manager = log_manager._log_manager_instance
        log_manager._log_manager_instance = None
        clear_log_sink()
        log_manager._early_lines.clear()

    def tearDown(self):
        clear_log_sink()
        log_manager._early_lines.clear()
        log_manager._log_manager_instance = self._saved_manager
        logging.getLogger("puikit").removeHandler(log_manager._sink_handler)


class TestPuiKitLogsReachThePane(LogRouteBase):
    def test_a_puikit_record_is_formatted_into_the_sink(self):
        route_library_logger("puikit")
        seen = []
        set_log_sink(lambda source, line: seen.append((source, line)))

        logging.getLogger("puikit._watchdog").warning("UI thread blocked 312 ms in key 'f5'")

        self.assertEqual(len(seen), 1)
        source, line = seen[0]
        self.assertEqual(source, LOG_ERROR_SOURCE)
        self.assertIn("[puikit._watchdog] WARNING: ", line)
        self.assertTrue(line.endswith("UI thread blocked 312 ms in key 'f5'"))

    def test_records_from_before_the_pane_existed_are_replayed(self):
        # The watchdog announces itself when the backend opens, which is before
        # XeFMApp exists to install a sink.
        route_library_logger("puikit")
        logging.getLogger("puikit._watchdog").info("UI-thread watchdog on")

        seen = []
        set_log_sink(lambda source, line: seen.append((source, line)))
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0][1].endswith("UI-thread watchdog on"))

    def test_routing_twice_does_not_double_the_records(self):
        route_library_logger("puikit")
        route_library_logger("puikit")
        seen = []
        set_log_sink(lambda source, line: seen.append((source, line)))

        logging.getLogger("puikit.backend").warning("once")
        self.assertEqual(len(seen), 1)


class TestTheWholeRouteEndToEnd(LogRouteBase):
    """A real stall, reported by PuiKit, arriving where XeFM shows its log."""

    def tearDown(self):
        _watchdog.uninstall()
        super().tearDown()

    def test_a_blocked_ui_thread_lands_in_the_log_pane_route(self):
        os.environ["PUIKIT_UI_WATCHDOG"] = "60"
        try:
            route_library_logger("puikit")
            seen = []
            set_log_sink(lambda source, line: seen.append((source, line)))
            _watchdog.install(threading.current_thread())

            def a_slow_file_operation():
                time.sleep(0.35)

            _watchdog.enter("key 'f5'")
            a_slow_file_operation()
            _watchdog.leave()
        finally:
            os.environ.pop("PUIKIT_UI_WATCHDOG", None)

        lines = [line for _, line in seen]
        self.assertTrue(any("UI thread blocked" in line for line in lines),
                        f"no stall report reached the pane: {lines}")
        self.assertTrue(any("a_slow_file_operation" in line for line in lines),
                        f"the report named no call site: {lines}")


if __name__ == "__main__":
    unittest.main()
