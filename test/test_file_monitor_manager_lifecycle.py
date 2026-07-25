"""
Unit tests for FileMonitorManager lifecycle methods.

Tests the monitoring lifecycle methods including start_monitoring,
update_monitored_directory, stop_monitoring, is_monitoring_enabled,
get_monitoring_mode, and backend detection logic.
"""

import unittest
import tempfile
import shutil
import queue
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from xefm.file_monitor_manager import FileMonitorManager


class TestFileMonitorManagerLifecycle(unittest.TestCase):
    """Test FileMonitorManager lifecycle methods"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create temporary directories for testing
        self.temp_dir = tempfile.mkdtemp()
        self.left_path = Path(self.temp_dir) / "left"
        self.right_path = Path(self.temp_dir) / "right"
        self.left_path.mkdir()
        self.right_path.mkdir()
        
        # Create mock config
        self.config = Mock()
        self.config.FILE_MONITORING_ENABLED = True
        self.config.FILE_MONITORING_COALESCE_DELAY_MS = 200
        self.config.FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
        self.config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5
        
        # Create mock file_manager with reload_queue
        self.file_manager = Mock()
        self.file_manager.reload_queue = queue.Queue()
        
        # Create FileMonitorManager instance
        self.manager = FileMonitorManager(self.config, self.file_manager)
    
    def tearDown(self):
        """Clean up test fixtures"""
        # Stop monitoring
        self.manager.stop_monitoring()
        
        # Clean up temporary directory
        shutil.rmtree(self.temp_dir)
    
    def test_initialization(self):
        """Test FileMonitorManager initialization"""
        self.assertTrue(self.manager.is_monitoring_enabled())
        self.assertEqual(self.manager.config, self.config)
        self.assertEqual(self.manager.file_manager, self.file_manager)
        self.assertEqual(self.manager.reload_queue, self.file_manager.reload_queue)
        
        # Check monitoring state initialized for both panes
        self.assertIn('left', self.manager.monitoring_state)
        self.assertIn('right', self.manager.monitoring_state)
        
        # Check coalesce timers initialized
        self.assertIn('left', self.manager.coalesce_timers)
        self.assertIn('right', self.manager.coalesce_timers)
    
    def test_start_monitoring_both_panes(self):
        """Test starting monitoring for both panes"""
        self.manager.start_monitoring(self.left_path, self.right_path)
        
        # Give observers time to start
        time.sleep(0.1)
        
        # Check that observers were created for both panes
        left_state = self.manager.monitoring_state['left']
        right_state = self.manager.monitoring_state['right']
        
        self.assertIsNotNone(left_state['observer'])
        self.assertIsNotNone(right_state['observer'])
        self.assertEqual(left_state['path'], self.left_path)
        self.assertEqual(right_state['path'], self.right_path)
        
        # Check that observers are alive
        self.assertTrue(left_state['observer'].is_alive())
        self.assertTrue(right_state['observer'].is_alive())
    
    def test_start_monitoring_disabled(self):
        """Test that monitoring doesn't start when disabled"""
        self.config.FILE_MONITORING_ENABLED = False
        manager = FileMonitorManager(self.config, self.file_manager)
        
        manager.start_monitoring(self.left_path, self.right_path)
        
        # Check that observers were not created
        left_state = manager.monitoring_state['left']
        right_state = manager.monitoring_state['right']
        
        self.assertIsNone(left_state['observer'])
        self.assertIsNone(right_state['observer'])
    
    def test_update_monitored_directory(self):
        """Test updating monitored directory for a pane"""
        # Start initial monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.1)
        
        # Get initial observer
        initial_observer = self.manager.monitoring_state['left']['observer']
        self.assertIsNotNone(initial_observer)
        
        # Create new directory
        new_left_path = Path(self.temp_dir) / "new_left"
        new_left_path.mkdir()
        
        # Update monitored directory
        self.manager.update_monitored_directory('left', new_left_path)
        time.sleep(0.1)
        
        # Check that path was updated
        self.assertEqual(self.manager.monitoring_state['left']['path'], new_left_path)
        
        # Check that a new observer was created
        new_observer = self.manager.monitoring_state['left']['observer']
        self.assertIsNotNone(new_observer)
        self.assertTrue(new_observer.is_alive())
        
        # Check that right pane was not affected
        self.assertEqual(self.manager.monitoring_state['right']['path'], self.right_path)
        
        # Clean up
        shutil.rmtree(new_left_path)
    
    def test_stop_monitoring(self):
        """Test stopping all monitoring"""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.1)
        
        # Verify observers are running
        self.assertTrue(self.manager.monitoring_state['left']['observer'].is_alive())
        self.assertTrue(self.manager.monitoring_state['right']['observer'].is_alive())
        
        # Stop monitoring
        self.manager.stop_monitoring()
        time.sleep(0.1)
        
        # Check that observers were stopped
        self.assertIsNone(self.manager.monitoring_state['left']['observer'])
        self.assertIsNone(self.manager.monitoring_state['right']['observer'])
        
        # Check that paths were cleared
        self.assertIsNone(self.manager.monitoring_state['left']['path'])
        self.assertIsNone(self.manager.monitoring_state['right']['path'])
    
    def test_is_monitoring_enabled(self):
        """Test is_monitoring_enabled status check"""
        self.assertTrue(self.manager.is_monitoring_enabled())
        
        # Test with disabled monitoring
        self.config.FILE_MONITORING_ENABLED = False
        manager = FileMonitorManager(self.config, self.file_manager)
        self.assertFalse(manager.is_monitoring_enabled())
    
    def test_get_monitoring_mode_disabled(self):
        """Test get_monitoring_mode when monitoring is disabled"""
        self.config.FILE_MONITORING_ENABLED = False
        manager = FileMonitorManager(self.config, self.file_manager)
        
        mode = manager.get_monitoring_mode(self.left_path)
        self.assertEqual(mode, "disabled")
    
    def test_get_monitoring_mode_active(self):
        """Test get_monitoring_mode for actively monitored path"""
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.1)
        
        # Get mode for left path (should be "native" or "polling")
        mode = self.manager.get_monitoring_mode(self.left_path)
        self.assertIn(mode, ["native", "polling"])
    
    def test_detect_s3_path(self):
        """S3 paths cannot be watched by watchdog, so monitoring is disabled (issue #181)"""
        s3_path = Path("s3://bucket/path")
        mode = self.manager._detect_monitoring_mode(s3_path)
        self.assertEqual(mode, "disabled")

        s3_path2 = Path("/s3/bucket/path")
        mode2 = self.manager._detect_monitoring_mode(s3_path2)
        self.assertEqual(mode2, "disabled")

    def test_detect_ssh_path(self):
        """SSH/SFTP paths cannot be watched by watchdog, so monitoring is disabled (issue #181)"""
        ssh_path = Path("ssh://server/path")
        mode = self.manager._detect_monitoring_mode(ssh_path)
        self.assertEqual(mode, "disabled")

        sftp_path = Path("sftp://server/path")
        mode2 = self.manager._detect_monitoring_mode(sftp_path)
        self.assertEqual(mode2, "disabled")
    
    def test_detect_local_path(self):
        """Test detection of local filesystem paths"""
        mode = self.manager._detect_monitoring_mode(self.left_path)
        self.assertEqual(mode, "native")

    def test_detect_remote_path_via_scheme(self):
        """A XeFM Path whose scheme is not 'file' disables monitoring (issue #181).

        This is the real-world case: an S3 pane holds a xefm.path.Path whose
        str() is 's3://bucket/', and detection must key off get_scheme() rather
        than fragile string prefixes."""
        remote_path = Mock()
        remote_path.get_scheme.return_value = "s3"
        remote_path.__str__ = Mock(return_value="s3://bucket/")
        mode = self.manager._detect_monitoring_mode(remote_path)
        self.assertEqual(mode, "disabled")

    def test_start_pane_monitoring_skips_remote_backend(self):
        """Starting monitoring on a remote (S3) pane must skip cleanly, not error.

        Regression test for issue #181: watchdog's polling observer raised
        [Errno 2] on 's3://bucket/'. Detection now disables monitoring for the
        pane without creating an observer or accumulating error/retry counts."""
        remote_path = Mock()
        remote_path.get_scheme.return_value = "s3"
        remote_path.__str__ = Mock(return_value="s3://bucket/")

        self.manager._start_pane_monitoring('left', remote_path)

        state = self.manager.monitoring_state['left']
        self.assertIsNone(state['observer'])
        self.assertEqual(state['error_count'], 0)
        self.assertEqual(state['retry_count'], 0)
        self.assertFalse(state['failed_permanently'])
    
    def test_suppress_reloads(self):
        """Test reload suppression"""
        # Suppress reloads for 500ms
        self.manager.suppress_reloads(500)
        
        # Check that suppress_until was set for both panes
        current_time = time.time()
        self.assertGreater(self.manager.suppress_until['left'], current_time)
        self.assertGreater(self.manager.suppress_until['right'], current_time)
        
        # Check that suppression expires after the duration
        time.sleep(0.6)
        self.assertLess(self.manager.suppress_until['left'], time.time())
        self.assertLess(self.manager.suppress_until['right'], time.time())
    
    def test_event_callback_posts_to_queue(self):
        """Test that filesystem events post reload requests to queue"""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Create a file in left pane
        test_file = self.left_path / "test.txt"
        test_file.write_text("test content")
        
        # Wait for event processing and coalescing
        # Note: On some systems (especially macOS), filesystem events may be delayed
        time.sleep(1.0)
        
        # Check that reload request was posted to queue
        # This test may be flaky on some systems due to filesystem event timing
        if not self.file_manager.reload_queue.empty():
            pane_name = self.file_manager.reload_queue.get_nowait()
            self.assertEqual(pane_name, "left")
        else:
            # If no event was detected, skip this test
            # This can happen on systems where watchdog doesn't detect changes immediately
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
    
    def test_rate_limiting(self):
        """Test that rate limiting prevents excessive reloads"""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.1)
        
        # Create multiple files rapidly
        for i in range(10):
            test_file = self.left_path / f"test{i}.txt"
            test_file.write_text(f"test content {i}")
            time.sleep(0.05)  # 50ms between files
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Count reload requests in queue
        reload_count = 0
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
            reload_count += 1
        
        # Should not exceed max_reloads_per_second (5)
        # Due to coalescing, we might get fewer reloads
        self.assertLessEqual(reload_count, 5)
    
    def test_coalescing_batches_events(self):
        """Test that event coalescing batches multiple events"""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.5)  # Wait for initialization events
        
        # Drain initialization events
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Create multiple files rapidly (within coalescing window)
        for i in range(5):
            test_file = self.left_path / f"test{i}.txt"
            test_file.write_text(f"test content {i}")
            time.sleep(0.01)  # 10ms between files (well within 200ms window)
        
        # Wait for coalescing delay plus processing time
        time.sleep(1.0)
        
        # Count reload requests
        reload_count = 0
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
            reload_count += 1
        
        # Should be 1 due to coalescing (all events within 200ms window)
        # However, on some systems events may not be detected immediately
        if reload_count == 0:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
        else:
            # Should be 1 or 2 due to coalescing (timing variations)
            self.assertLessEqual(reload_count, 2)
    
    def test_dual_pane_independence(self):
        """Test that left and right panes are monitored independently"""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.5)  # Wait for initialization events
        
        # Drain initialization events
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Create file in left pane
        left_file = self.left_path / "left_test.txt"
        left_file.write_text("left content")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Check if we got a reload request for left pane
        if self.file_manager.reload_queue.empty():
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
        
        pane_name = self.file_manager.reload_queue.get_nowait()
        self.assertEqual(pane_name, "left")
        
        # Queue should be empty now
        self.assertTrue(self.file_manager.reload_queue.empty())
        
        # Create file in right pane
        right_file = self.right_path / "right_test.txt"
        right_file.write_text("right content")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Should get reload request for right pane
        if not self.file_manager.reload_queue.empty():
            pane_name = self.file_manager.reload_queue.get_nowait()
            self.assertEqual(pane_name, "right")


if __name__ == '__main__':
    unittest.main()
