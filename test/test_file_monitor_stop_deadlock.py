"""
Regression test for the watcher re-point deadlock.

Navigating a pane re-points its watcher: _start_pane_monitoring, holding
state_lock, used to call observer.stop() in-line. watchdog's BaseObserver.stop()
acquires the observer's internal dispatch lock — the same lock its dispatch
thread holds while delivering an event into _on_filesystem_event, which acquires
state_lock. When an event was mid-dispatch at the moment of navigation, the two
threads deadlocked in opposite lock orders and froze the whole app (observed on
the MS Store v1.0.1 build; the mechanism is platform-independent).

The test recreates that exact interleaving with a mock observer whose stop()
blocks on a stand-in for watchdog's dispatch lock while a fake dispatch thread,
holding that lock, delivers an event into _on_filesystem_event. With the fix
(observers are detached under state_lock but stopped off-thread),
update_monitored_directory completes; with the old code it deadlocks forever,
which the join timeout turns into a failure.
"""

import unittest
import tempfile
import shutil
import queue
import threading
from pathlib import Path
from unittest.mock import Mock
from xefm.file_monitor_manager import FileMonitorManager


class TestStopObserverDeadlock(unittest.TestCase):
    """The watcher re-point must not deadlock against an in-flight event."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.new_path = Path(self.temp_dir) / "new"
        self.new_path.mkdir()

        self.config = Mock()
        self.config.FILE_MONITORING_ENABLED = True
        self.config.FILE_MONITORING_COALESCE_DELAY_MS = 200
        self.config.FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
        self.config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5

        self.file_manager = Mock()
        self.file_manager.reload_queue = queue.Queue()

        self.manager = FileMonitorManager(self.config, self.file_manager)
        self.deadlocked = False

    def tearDown(self):
        # A deadlocked navigator thread holds state_lock forever; calling
        # stop_monitoring() then would hang the whole test run instead of
        # letting the failure report.
        if not self.deadlocked:
            self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir)

    def test_update_monitored_directory_with_event_in_flight(self):
        # Stand-in for watchdog's internal dispatch lock: held by the dispatch
        # thread across event delivery, required by observer.stop().
        dispatch_lock = threading.Lock()
        stop_entered = threading.Event()
        stop_finished = threading.Event()

        def blocking_stop():
            stop_entered.set()
            with dispatch_lock:
                pass
            stop_finished.set()

        old_observer = Mock()
        old_observer.stop = blocking_stop

        state = self.manager.monitoring_state['left']
        state['observer'] = old_observer
        state['path'] = Path(self.temp_dir) / "old"

        def dispatch_thread():
            with dispatch_lock:
                # Delivering an event mid-stop: stop() is now blocked on
                # dispatch_lock, and (in the old code) the UI thread still
                # holds state_lock — which this call needs.
                stop_entered.wait(timeout=5.0)
                self.manager._on_filesystem_event('left', 'modified', 'x.txt')

        dispatcher = threading.Thread(target=dispatch_thread, daemon=True)
        dispatcher.start()

        # Give the dispatcher the lock before navigation re-points the watcher.
        while not dispatch_lock.locked():
            pass

        navigator = threading.Thread(
            target=self.manager.update_monitored_directory,
            args=('left', self.new_path), daemon=True)
        navigator.start()
        navigator.join(timeout=5.0)

        self.deadlocked = navigator.is_alive()
        self.assertFalse(self.deadlocked,
                         "update_monitored_directory deadlocked against an "
                         "in-flight filesystem event")
        dispatcher.join(timeout=5.0)
        self.assertFalse(dispatcher.is_alive())
        self.assertTrue(stop_finished.wait(timeout=5.0),
                        "old observer was never stopped")


if __name__ == '__main__':
    unittest.main()
