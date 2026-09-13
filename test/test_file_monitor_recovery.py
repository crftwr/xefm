"""
Regression tests for monitoring recovery after a failed directory (issue #416).

A directory that cannot be watched - it vanished, it was unmounted, the OS
refused the stream — used to switch monitoring off for the *pane*, for the rest
of the session: browsing back to an ordinary local directory only reprinted
"has failed permanently, not retrying". These cover the three parts of the fix:
the give-up verdict is scoped to the directory, a retry is abandoned once the
pane navigates away, and a dead observer is noticed by the health check.
"""

import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Add the repo root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from xefm.file_monitor_manager import FileMonitorManager
from xefm.file_monitor_observer import FileMonitorObserver


class MockConfig:
    FILE_MONITORING_ENABLED = True
    FILE_MONITORING_COALESCE_DELAY_MS = 200
    FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
    FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5


class MockFileManager:
    def __init__(self):
        self.reload_queue = queue.Queue()


class RecoveryTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.manager = FileMonitorManager(MockConfig(), MockFileManager())

    def tearDown(self):
        self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _give_up_on(self, pane_name, path):
        """Put a pane in the state the retry chain ends in: every attempt and the
        polling fallback failed for ``path``. Driven through the real code rather
        than by writing the state, but without waiting out the 1s/2s/4s backoff."""
        state = self.manager.monitoring_state[pane_name]
        state['path'] = path
        state['retry_count'] = 3
        with patch.object(FileMonitorObserver, 'start', lambda self: False):
            self.manager._schedule_retry(pane_name, path)
        self.assertEqual(state['failed_path'], path)


class TestFailureIsScopedToDirectory(RecoveryTestBase):
    """The pane resumes monitoring as soon as it leaves the bad directory."""

    def test_navigating_elsewhere_resumes_monitoring(self):
        gone = self.temp_path / "unmounted"
        self._give_up_on('right', gone)

        self.manager.update_monitored_directory('right', self.temp_path)

        state = self.manager.monitoring_state['right']
        self.assertIsNotNone(state['observer'], "pane must monitor again after leaving")
        self.assertEqual(state['path'], self.temp_path)
        self.assertIsNone(state['failed_path'])
        self.assertEqual(state['retry_count'], 0)

    def test_staying_on_the_bad_directory_is_not_retried(self):
        gone = self.temp_path / "unmounted"
        self._give_up_on('right', gone)

        with patch.object(FileMonitorObserver, 'start') as start:
            self.manager.update_monitored_directory('right', gone)
            start.assert_not_called()

    def test_returning_to_the_directory_gets_a_fresh_chance(self):
        """The directory may be back - remounted, recreated - by the time the
        user browses to it again, so the old verdict must not outlive the visit."""
        gone = self.temp_path / "remounted"
        self._give_up_on('right', gone)
        self.manager.update_monitored_directory('right', self.temp_path)

        gone.mkdir()
        self.manager.update_monitored_directory('right', gone)

        state = self.manager.monitoring_state['right']
        self.assertIsNotNone(state['observer'])
        self.assertEqual(state['path'], gone)

    def test_other_pane_is_untouched(self):
        gone = self.temp_path / "unmounted"
        self._give_up_on('right', gone)

        self.manager.update_monitored_directory('left', self.temp_path)

        self.assertIsNotNone(self.manager.monitoring_state['left']['observer'])


class TestRetryDoesNotOutliveNavigation(RecoveryTestBase):
    """A retry that comes back after the pane moved on must not install itself."""

    def test_stale_retry_is_abandoned(self):
        old = self.temp_path / "old"
        new = self.temp_path / "new"
        new.mkdir()

        # Fails: "old" does not exist yet, so a retry chain starts for it
        self.manager.update_monitored_directory('right', old)
        # ... the user navigates on before the first backoff elapses
        self.manager.update_monitored_directory('right', new)
        current = self.manager.monitoring_state['right']['observer']
        self.assertIsNotNone(current)

        old.mkdir()          # the old directory comes back; the retry would succeed
        time.sleep(1.5)      # let the 1s retry fire

        state = self.manager.monitoring_state['right']
        self.assertIs(state['observer'], current,
                      "a retry for a directory the pane left must not swap the observer")
        self.assertEqual(state['path'], new)
        self.assertTrue(current.is_alive(), "the live observer must not be orphaned")


class TestObserverHealthCheck(RecoveryTestBase):
    """A watcher that dies is silent about it; only the health check finds it."""

    def test_dead_observer_is_restarted(self):
        self.manager.update_monitored_directory('left', self.temp_path)
        dead = self.manager.monitoring_state['left']['observer']
        dead.stop()                       # as if the OS dropped the stream
        self.assertFalse(dead.is_alive())

        self.manager.check_observer_health()
        time.sleep(1.5)                   # recovery goes through the 1s backoff

        state = self.manager.monitoring_state['left']
        self.assertIsNotNone(state['observer'])
        self.assertIsNot(state['observer'], dead)
        self.assertTrue(state['observer'].is_alive())

    def test_repeated_calls_are_rate_limited(self):
        """The UI pump calls this on every drain, so it must not walk the state
        (nor take the lock's work) at that rate."""
        self.manager.update_monitored_directory('left', self.temp_path)
        observer = self.manager.monitoring_state['left']['observer']

        with patch.object(observer, 'is_alive', return_value=True) as is_alive:
            for _ in range(50):
                self.manager.check_observer_health()
            self.assertLessEqual(is_alive.call_count, 1)

    def test_shared_observer_is_stopped_once(self):
        self.manager.update_monitored_directory('left', self.temp_path)
        self.manager.update_monitored_directory('right', self.temp_path)
        shared = self.manager.monitoring_state['left']['observer']
        self.assertIs(self.manager.monitoring_state['right']['observer'], shared)

        stops = []
        with patch.object(self.manager, '_stop_observer_async', stops.append):
            with patch.object(shared, 'is_alive', return_value=False):
                self.manager.check_observer_health()

        self.assertEqual(stops, [shared], "a shared observer must be stopped once")

    def test_disabled_monitoring_does_nothing(self):
        self.manager.enabled = False
        self.manager.check_observer_health()     # must not raise


if __name__ == '__main__':
    unittest.main()
