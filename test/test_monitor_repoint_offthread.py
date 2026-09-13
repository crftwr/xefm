"""
Regression tests for re-pointing a pane's watcher off the UI thread (issue #410).

Navigating to a directory on a slow mount froze the whole app for seconds: the
animation tick noticed the pane had moved and re-pointed the watcher inline, and
starting a watcher is filesystem work — watchdog runs on_thread_start() on
whichever thread calls observer.start(), which stats the directory and, in
polling mode, scandirs all of it. The stall detector from #407 caught 4.2 s in a
single os.path.exists() on an SMB share.

The work now runs on the manager's monitor worker. These cover the three things
that has to be true: the caller returns immediately, the UI thread's other
monitor call is not stuck behind the worker on state_lock (which would only move
the freeze), and a burst of navigation settles on the directory the user
actually ended on instead of starting one observer per directory passed through.
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


class RepointTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.manager = FileMonitorManager(MockConfig(), MockFileManager())

    def tearDown(self):
        self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestRepointDoesNotBlockTheUIThread(RepointTestBase):
    """A start that hangs on the mount must hang nothing the UI thread touches."""

    def test_caller_returns_while_the_start_is_still_blocked(self):
        entered = threading.Event()
        release = threading.Event()

        def stalled_start(observer):
            """Stand-in for a start waiting on an unreachable mount."""
            entered.set()
            release.wait(timeout=5.0)
            observer.monitoring_mode = "native"
            return True

        with patch.object(FileMonitorObserver, 'start', stalled_start):
            began = time.monotonic()
            self.manager.update_monitored_directory('left', self.temp_path)
            returned = time.monotonic() - began

            self.assertTrue(entered.wait(2.0), "the worker never began the start")
            self.assertLess(returned, 0.5,
                            "re-pointing blocked its caller - on the UI thread "
                            "that is the freeze #410 is about")

            # The pump's other monitor call takes state_lock, so holding that
            # lock across the start would have relocated the freeze, not fixed it.
            began = time.monotonic()
            self.manager.check_observer_health()
            self.assertLess(time.monotonic() - began, 0.5,
                            "the UI thread waited on state_lock behind a stalled start")

            release.set()
            self.assertTrue(self.manager.wait_for_idle(5.0))

        self.assertEqual(self.manager.monitoring_state['left']['path'], self.temp_path)


class TestNavigationBurstCoalesces(RepointTestBase):
    """Walking through directories must not start an observer for each one."""

    def test_only_the_directory_the_user_stopped_on_is_watched(self):
        visited = [self.temp_path / name for name in ("a", "b", "c")]
        for directory in visited:
            directory.mkdir()

        started = []
        first_start = threading.Event()
        release = threading.Event()
        real_start = FileMonitorObserver.start

        def recording_start(observer):
            started.append(observer.path)
            # Hold the worker inside the first start so the rest of the walk
            # queues up behind it, the way a slow mount would.
            if not first_start.is_set():
                first_start.set()
                release.wait(timeout=5.0)
            return real_start(observer)

        with patch.object(FileMonitorObserver, 'start', recording_start):
            self.manager.update_monitored_directory('left', visited[0])
            self.assertTrue(first_start.wait(2.0), "the worker never began the start")
            for directory in visited[1:]:
                self.manager.update_monitored_directory('left', directory)
            release.set()
            self.assertTrue(self.manager.wait_for_idle(5.0))

        self.assertEqual(started, [visited[0], visited[2]],
                         "a directory the user passed through was watched anyway")
        state = self.manager.monitoring_state['left']
        self.assertEqual(state['path'], visited[2])
        self.assertEqual(state['observer'].path, visited[2])


if __name__ == '__main__':
    unittest.main()
