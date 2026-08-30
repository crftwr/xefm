"""
The route from a XeFM logger to the log pane (issue #358 fallout).

XeFM never builds a ``LogManager`` in production, so every logger
``getLogger`` handed back used to have no handlers at all: Python fell back to
``logging.lastResort``, which drops everything below WARNING and writes the rest
to ``sys.stderr`` — a stream the GUI backends do not have (a Windows
GUI-subsystem process has none). Every ``logger.info`` in the codebase was
discarded, and warnings and errors raised before the log pane existed — the
config load among them — were invisible.

A sink handler on every logger fixes both halves: records are formatted and
handed to the app's queue, and buffered until an app installs one so a startup
diagnostic is replayed into the pane rather than lost.
"""

import logging
import io
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import log_manager  # noqa: E402
from xefm.log_manager import (LOG_ERROR_SOURCE, LOG_SOURCE, clear_log_sink,  # noqa: E402
                              getLogger, set_log_sink)
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class LogSinkBase(unittest.TestCase):
    """Every test starts the way XeFM itself runs — no LogManager, no sink
    installed, an empty backlog — and leaves the module globals that way, since
    all three are process-wide.

    Logger names are unique per test: a ``logging.Logger`` is global and keeps
    whatever handlers another test hung on it.
    """

    def setUp(self):
        self._saved_manager = log_manager._log_manager_instance
        log_manager._log_manager_instance = None
        clear_log_sink()
        log_manager._early_lines.clear()

    def tearDown(self):
        clear_log_sink()
        log_manager._early_lines.clear()
        log_manager._log_manager_instance = self._saved_manager


class TestLoggersAreHandled(LogSinkBase):
    def test_getLogger_attaches_the_sink_handler(self):
        """The regression itself: a logger with no handlers loses every INFO."""
        logger = getLogger("SinkA1")
        self.assertIn(log_manager._sink_handler, logger.handlers)

    def test_info_reaches_the_sink_formatted(self):
        seen = []
        set_log_sink(lambda source, line: seen.append((source, line)))
        getLogger("SinkB2").info("Loaded configuration from: /home/u/.xefm/config.py")

        self.assertEqual(len(seen), 1)
        source, line = seen[0]
        self.assertEqual(source, LOG_SOURCE)
        # "HH:MM:SS [Config] INFO: <message>" — the log pane's own format.
        self.assertIn("[SinkB2] INFO: ", line)
        self.assertTrue(line.endswith("Loaded configuration from: /home/u/.xefm/config.py"))

    def test_warning_and_error_are_tagged_as_errors(self):
        seen = []
        set_log_sink(lambda source, line: seen.append((source, line)))
        log = getLogger("SinkC3")
        log.warning("degraded")
        log.error("Error loading configuration: boom")

        self.assertEqual([s for s, _ in seen], [LOG_ERROR_SOURCE, LOG_ERROR_SOURCE])

    def test_clear_log_sink_stops_delivery(self):
        seen = []
        set_log_sink(lambda source, line: seen.append((source, line)))
        clear_log_sink()
        getLogger("SinkD4").info("after teardown")

        self.assertEqual(seen, [])


class TestEarlyRecordsSurvive(LogSinkBase):
    """The #358 half: config loading happens long before the log pane exists."""

    def test_records_logged_before_a_sink_are_replayed_in_order(self):
        log = getLogger("SinkE5")
        log.info("first")
        log.error("Error loading configuration: boom")
        log.info("third")

        seen = []
        set_log_sink(lambda source, line: seen.append((source, line)))

        self.assertEqual([s for s, _ in seen],
                         [LOG_SOURCE, LOG_ERROR_SOURCE, LOG_SOURCE])
        self.assertTrue(seen[0][1].endswith("first"))
        self.assertTrue(seen[1][1].endswith("Error loading configuration: boom"))
        self.assertTrue(seen[2][1].endswith("third"))
        # Replayed once, not once per install.
        seen.clear()
        set_log_sink(lambda source, line: seen.append((source, line)))
        self.assertEqual(seen, [])

    def test_warnings_still_reach_stderr_while_buffering(self):
        """lastResort's safety net, kept: with no pane yet, a warning must still
        show up on a terminal if the process has one. INFO stays quiet."""
        captured = io.StringIO()
        saved, sys.stderr = sys.stderr, captured
        try:
            log = getLogger("SinkF6")
            log.info("routine")
            log.error("Error loading configuration: boom")
        finally:
            sys.stderr = saved

        text = captured.getvalue()
        self.assertNotIn("routine", text)
        self.assertIn("Error loading configuration: boom", text)

    def test_a_null_stderr_does_not_break_logging(self):
        """A Windows GUI-subsystem process has ``sys.stderr is None``."""
        saved, sys.stderr = sys.stderr, None
        try:
            getLogger("SinkG7").error("Error loading configuration: boom")
        finally:
            sys.stderr = saved

        # Buffered regardless, so the pane still gets it once one exists.
        seen = []
        set_log_sink(lambda source, line: seen.append((source, line)))
        self.assertEqual(len(seen), 1)


class TestRecordsReachTheLogPane(LogSinkBase):
    """End to end through the real app: sink -> queue -> pump -> LogView."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.tmp, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            # Puts stdout/stderr back and drops the sink pointing at this app.
            self.app._restore_streams()
        except Exception:
            pass
        try:
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def _pane_text(self):
        return [text for text, _style in self.app.log.lines]

    def test_a_startup_diagnostic_is_replayed_into_the_pane(self):
        # Logged before the app exists — exactly where get_config() runs.
        getLogger("SinkH8").error("Error loading configuration: boom")

        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    state_manager=self.sm)
        self.app._drain_captured_output()

        self.assertTrue(any("Error loading configuration: boom" in line
                            for line in self._pane_text()),
                        f"not replayed into the pane: {self._pane_text()}")

    def test_a_record_logged_while_running_reaches_the_pane(self):
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    state_manager=self.sm)
        self.app._drain_captured_output()
        before = len(self.app.log.lines)

        getLogger("SinkI9").info("Loaded configuration from: /home/u/.xefm/config.py")
        self.app._drain_captured_output()

        added = [text for text, _ in self.app.log.lines[before:]]
        self.assertEqual(len(added), 1, added)
        self.assertIn("[SinkI9] INFO: ", added[0])

    def test_an_error_is_styled_like_stderr(self):
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    state_manager=self.sm)
        self.app._drain_captured_output()
        before = len(self.app.log.lines)

        getLogger("SinkJ0").error("boom")
        self.app._drain_captured_output()

        _text, style = self.app.log.lines[before]
        self.assertEqual(style.fg, xefm_app.XeFMApp._STDERR_STYLE.fg)


if __name__ == "__main__":
    unittest.main()
