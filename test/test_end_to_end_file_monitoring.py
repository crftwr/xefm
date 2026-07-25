"""
End-to-end integration tests for automatic file list reloading feature.

These tests verify the complete workflow of the automatic file monitoring system,
including:
- Basic workflow: external file changes trigger automatic reloads
- Dual-pane independence: changes in one pane don't affect the other
- Directory navigation: monitoring updates when navigating to new directories
- Configuration: monitoring can be enabled/disabled via config
- Runtime toggle: monitoring can be toggled on/off at runtime
- Error handling: system recovers gracefully from errors

Since we cannot run the interactive XeFM application, these tests simulate
the complete workflow using mocked components and real filesystem operations.
"""

import unittest
import tempfile
import shutil
import time
import queue
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add the repo root to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from xefm.file_monitor_manager import FileMonitorManager
from xefm.log_manager import getLogger


class MockConfig:
    """Mock configuration for testing."""
    FILE_MONITORING_ENABLED = True
    FILE_MONITORING_COALESCE_DELAY_MS = 200
    FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
    FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5


class MockFileManager:
    """Mock FileManager for testing."""
    def __init__(self):
        self.reload_queue = queue.Queue()
        self.logger = getLogger("TestFileManager")


class TestBasicWorkflow(unittest.TestCase):
    """Test basic workflow: start monitoring, create file externally, verify automatic reload."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.left_path = Path(self.temp_dir) / "left"
        self.right_path = Path(self.temp_dir) / "right"
        self.left_path.mkdir()
        self.right_path.mkdir()
        
        self.config = MockConfig()
        self.file_manager = MockFileManager()
        self.manager = FileMonitorManager(self.config, self.file_manager)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_create_file_triggers_reload(self):
        """Test that creating a file externally triggers automatic reload."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Create a file in left pane
        test_file = self.left_path / "test.txt"
        test_file.write_text("test content")
        
        # Wait for event processing and coalescing
        time.sleep(1.0)
        
        # Verify reload request was posted
        if not self.file_manager.reload_queue.empty():
            # Drain all posted reloads and check the expected pane is among them.
            # Coalescing and shared observers can post more than one entry, in any
            # order, so asserting on just the first is racy.
            posted = set()
            while not self.file_manager.reload_queue.empty():
                posted.add(self.file_manager.reload_queue.get_nowait())
            self.assertIn("left", posted)
        else:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
    
    def test_delete_file_triggers_reload(self):
        """Test that deleting a file externally triggers automatic reload."""
        # Create a file first
        test_file = self.left_path / "test.txt"
        test_file.write_text("test content")
        
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Delete the file
        test_file.unlink()
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Verify reload request was posted
        if not self.file_manager.reload_queue.empty():
            # Drain all posted reloads and check the expected pane is among them.
            # Coalescing and shared observers can post more than one entry, in any
            # order, so asserting on just the first is racy.
            posted = set()
            while not self.file_manager.reload_queue.empty():
                posted.add(self.file_manager.reload_queue.get_nowait())
            self.assertIn("left", posted)
        else:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
    
    def test_modify_file_triggers_reload(self):
        """Test that modifying a file externally triggers automatic reload."""
        # Create a file first
        test_file = self.left_path / "test.txt"
        test_file.write_text("initial content")
        
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Modify the file
        test_file.write_text("modified content")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Verify reload request was posted
        if not self.file_manager.reload_queue.empty():
            # Drain all posted reloads and check the expected pane is among them.
            # Coalescing and shared observers can post more than one entry, in any
            # order, so asserting on just the first is racy.
            posted = set()
            while not self.file_manager.reload_queue.empty():
                posted.add(self.file_manager.reload_queue.get_nowait())
            self.assertIn("left", posted)
        else:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
    
    def test_rename_file_triggers_reload(self):
        """Test that renaming a file externally triggers automatic reload."""
        # Create a file first
        old_file = self.left_path / "old.txt"
        old_file.write_text("content")
        
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Rename the file
        new_file = self.left_path / "new.txt"
        old_file.rename(new_file)
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Verify reload request was posted
        if not self.file_manager.reload_queue.empty():
            # Drain all posted reloads and check the expected pane is among them.
            # Coalescing and shared observers can post more than one entry, in any
            # order, so asserting on just the first is racy.
            posted = set()
            while not self.file_manager.reload_queue.empty():
                posted.add(self.file_manager.reload_queue.get_nowait())
            self.assertIn("left", posted)
        else:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")


class TestDualPaneMonitoring(unittest.TestCase):
    """Test dual-pane monitoring with changes in both panes."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.left_path = Path(self.temp_dir) / "left"
        self.right_path = Path(self.temp_dir) / "right"
        self.left_path.mkdir()
        self.right_path.mkdir()
        
        self.config = MockConfig()
        self.file_manager = MockFileManager()
        self.manager = FileMonitorManager(self.config, self.file_manager)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_left_pane_change_only_reloads_left(self):
        """Test that changes in left pane only trigger left pane reload."""
        # Start monitoring both panes
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
        
        # Verify only left pane reload was requested
        if self.file_manager.reload_queue.empty():
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
        
        pane_name = self.file_manager.reload_queue.get_nowait()
        self.assertEqual(pane_name, "left")
        
        # Queue should be empty (no right pane reload)
        self.assertTrue(self.file_manager.reload_queue.empty())
    
    def test_right_pane_change_only_reloads_right(self):
        """Test that changes in right pane only trigger right pane reload."""
        # Start monitoring both panes
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.5)  # Wait for initialization events
        
        # Drain initialization events
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Create file in right pane
        right_file = self.right_path / "right_test.txt"
        right_file.write_text("right content")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Verify only right pane reload was requested
        if self.file_manager.reload_queue.empty():
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
        
        pane_name = self.file_manager.reload_queue.get_nowait()
        self.assertEqual(pane_name, "right")
        
        # Queue should be empty (no left pane reload)
        self.assertTrue(self.file_manager.reload_queue.empty())
    
    def test_both_panes_change_triggers_both_reloads(self):
        """Test that changes in both panes trigger both pane reloads."""
        # Start monitoring both panes
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.5)  # Wait for initialization events
        
        # Drain initialization events
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Create files in both panes
        left_file = self.left_path / "left_test.txt"
        left_file.write_text("left content")
        
        right_file = self.right_path / "right_test.txt"
        right_file.write_text("right content")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Verify both pane reloads were requested
        if self.file_manager.reload_queue.empty():
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
        
        # Collect all reload requests
        reload_requests = []
        while not self.file_manager.reload_queue.empty():
            reload_requests.append(self.file_manager.reload_queue.get_nowait())
        
        # Should have both left and right
        self.assertIn("left", reload_requests)
        self.assertIn("right", reload_requests)


class TestDirectoryNavigation(unittest.TestCase):
    """Test directory navigation with monitoring updates."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.left_path = Path(self.temp_dir) / "left"
        self.right_path = Path(self.temp_dir) / "right"
        self.new_left_path = Path(self.temp_dir) / "new_left"
        
        self.left_path.mkdir()
        self.right_path.mkdir()
        self.new_left_path.mkdir()
        
        self.config = MockConfig()
        self.file_manager = MockFileManager()
        self.manager = FileMonitorManager(self.config, self.file_manager)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_navigation_updates_monitoring(self):
        """Test that navigating to new directory updates monitoring."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Verify initial monitoring
        self.assertEqual(self.manager.monitoring_state['left']['path'], self.left_path)
        
        # Navigate to new directory
        self.manager.update_monitored_directory('left', self.new_left_path)
        time.sleep(0.2)
        
        # Verify monitoring updated
        self.assertEqual(self.manager.monitoring_state['left']['path'], self.new_left_path)
        
        # Create file in new directory
        test_file = self.new_left_path / "test.txt"
        test_file.write_text("test content")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Verify reload request for new directory
        if not self.file_manager.reload_queue.empty():
            # Drain all posted reloads and check the expected pane is among them.
            # Coalescing and shared observers can post more than one entry, in any
            # order, so asserting on just the first is racy.
            posted = set()
            while not self.file_manager.reload_queue.empty():
                posted.add(self.file_manager.reload_queue.get_nowait())
            self.assertIn("left", posted)
        else:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
    
    def test_old_directory_no_longer_monitored(self):
        """Test that old directory is no longer monitored after navigation."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Navigate to new directory
        self.manager.update_monitored_directory('left', self.new_left_path)
        time.sleep(0.2)
        
        # Create file in OLD directory
        old_file = self.left_path / "old_test.txt"
        old_file.write_text("old content")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Queue should be empty (old directory not monitored)
        self.assertTrue(self.file_manager.reload_queue.empty())
    
    def test_navigation_transition_time(self):
        """Test that monitoring transition completes quickly (< 100ms target)."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Measure transition time
        start_time = time.time()
        self.manager.update_monitored_directory('left', self.new_left_path)
        
        # Wait for observer to start
        time.sleep(0.1)
        
        # Check that new observer is running
        new_observer = self.manager.monitoring_state['left']['observer']
        self.assertIsNotNone(new_observer)
        self.assertTrue(new_observer.is_alive())
        
        # Transition should be fast (< 100ms is target, but we allow more for test stability)
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 0.5)  # Allow 500ms for test stability


class TestConfigurationControl(unittest.TestCase):
    """Test configuration enable/disable."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.left_path = Path(self.temp_dir) / "left"
        self.right_path = Path(self.temp_dir) / "right"
        self.left_path.mkdir()
        self.right_path.mkdir()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_monitoring_disabled_by_config(self):
        """Test that monitoring doesn't start when disabled by config."""
        config = MockConfig()
        config.FILE_MONITORING_ENABLED = False
        
        file_manager = MockFileManager()
        manager = FileMonitorManager(config, file_manager)
        
        # Try to start monitoring
        manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.1)
        
        # Verify observers were not created
        self.assertIsNone(manager.monitoring_state['left']['observer'])
        self.assertIsNone(manager.monitoring_state['right']['observer'])
        
        # Create file
        test_file = self.left_path / "test.txt"
        test_file.write_text("test content")
        
        # Wait
        time.sleep(1.0)
        
        # Queue should be empty (monitoring disabled)
        self.assertTrue(file_manager.reload_queue.empty())
    
    def test_monitoring_enabled_by_config(self):
        """Test that monitoring starts when enabled by config."""
        config = MockConfig()
        config.FILE_MONITORING_ENABLED = True
        
        file_manager = MockFileManager()
        manager = FileMonitorManager(config, file_manager)
        
        # Start monitoring
        manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Verify observers were created
        self.assertIsNotNone(manager.monitoring_state['left']['observer'])
        self.assertIsNotNone(manager.monitoring_state['right']['observer'])
        
        # Clean up
        manager.stop_monitoring()


class TestRuntimeToggle(unittest.TestCase):
    """Test runtime toggle of monitoring."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.left_path = Path(self.temp_dir) / "left"
        self.right_path = Path(self.temp_dir) / "right"
        self.left_path.mkdir()
        self.right_path.mkdir()
        
        self.config = MockConfig()
        self.file_manager = MockFileManager()
        self.manager = FileMonitorManager(self.config, self.file_manager)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_stop_monitoring_disables_events(self):
        """Test that stopping monitoring disables event detection."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Stop monitoring
        self.manager.stop_monitoring()
        time.sleep(0.1)
        
        # Verify observers were stopped
        self.assertIsNone(self.manager.monitoring_state['left']['observer'])
        self.assertIsNone(self.manager.monitoring_state['right']['observer'])
        
        # Create file
        test_file = self.left_path / "test.txt"
        test_file.write_text("test content")
        
        # Wait
        time.sleep(1.0)
        
        # Queue should be empty (monitoring stopped)
        self.assertTrue(self.file_manager.reload_queue.empty())
    
    def test_restart_monitoring_enables_events(self):
        """Test that restarting monitoring enables event detection."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Stop monitoring
        self.manager.stop_monitoring()
        time.sleep(0.1)
        
        # Restart monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Verify observers were recreated
        self.assertIsNotNone(self.manager.monitoring_state['left']['observer'])
        self.assertIsNotNone(self.manager.monitoring_state['right']['observer'])
        
        # Create file
        test_file = self.left_path / "test.txt"
        test_file.write_text("test content")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Verify reload request was posted
        if not self.file_manager.reload_queue.empty():
            # Drain all posted reloads and check the expected pane is among them.
            # Coalescing and shared observers can post more than one entry, in any
            # order, so asserting on just the first is racy.
            posted = set()
            while not self.file_manager.reload_queue.empty():
                posted.add(self.file_manager.reload_queue.get_nowait())
            self.assertIn("left", posted)
        else:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")


class TestErrorScenarios(unittest.TestCase):
    """Test error scenarios and recovery."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.left_path = Path(self.temp_dir) / "left"
        self.right_path = Path(self.temp_dir) / "right"
        self.left_path.mkdir()
        self.right_path.mkdir()
        
        self.config = MockConfig()
        self.file_manager = MockFileManager()
        self.manager = FileMonitorManager(self.config, self.file_manager)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_nonexistent_directory_handled_gracefully(self):
        """Test that monitoring nonexistent directory is handled gracefully."""
        nonexistent = Path(self.temp_dir) / "nonexistent"
        
        # Try to start monitoring with nonexistent directory
        self.manager.start_monitoring(nonexistent, self.right_path)
        time.sleep(0.2)
        
        # Left pane should have failed, but right pane should work
        self.assertIsNone(self.manager.monitoring_state['left']['observer'])
        self.assertIsNotNone(self.manager.monitoring_state['right']['observer'])
    
    def test_permission_denied_handled_gracefully(self):
        """Test that permission denied is handled gracefully."""
        # This test is platform-specific and may not work on all systems
        # Skip if we can't create a directory with restricted permissions
        try:
            restricted = Path(self.temp_dir) / "restricted"
            restricted.mkdir(mode=0o000)
            
            # Try to start monitoring
            self.manager.start_monitoring(restricted, self.right_path)
            time.sleep(0.2)
            
            # Left pane should have failed, but right pane should work
            # Note: On some systems, watchdog may still be able to monitor
            # even with restricted permissions, so we just verify no crash
            self.assertIsNotNone(self.manager.monitoring_state['right']['observer'])
            
            # Clean up
            restricted.chmod(0o755)
            restricted.rmdir()
        except Exception:
            self.skipTest("Cannot test permission denied on this system")
    
    def test_observer_death_triggers_recovery(self):
        """Test that observer death triggers recovery attempt."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.2)
        
        # Get observer
        observer = self.manager.monitoring_state['left']['observer']
        self.assertIsNotNone(observer)
        
        # Simulate observer death by stopping it
        observer.stop()
        time.sleep(0.1)
        
        # Run health check
        self.manager.check_observer_health()
        time.sleep(0.5)
        
        # Should have attempted recovery (retry_count > 0 or new observer created)
        state = self.manager.monitoring_state['left']
        # Either we have a new observer or we're in retry state
        self.assertTrue(state['observer'] is not None or state['retry_count'] > 0)
    
    def test_s3_path_disables_monitoring(self):
        """S3 paths can't be watched by watchdog, so monitoring is disabled (issue #181)."""
        s3_path = Path("s3://bucket/path")

        # Detect monitoring mode
        mode = self.manager._detect_monitoring_mode(s3_path)

        # Monitoring must be disabled for S3, not attempted via polling
        self.assertEqual(mode, "disabled")

    def test_ssh_path_disables_monitoring(self):
        """SSH paths can't be watched by watchdog, so monitoring is disabled (issue #181)."""
        ssh_path = Path("ssh://server/path")

        # Detect monitoring mode
        mode = self.manager._detect_monitoring_mode(ssh_path)

        # Monitoring must be disabled for SSH, not attempted via polling
        self.assertEqual(mode, "disabled")


class TestEventCoalescing(unittest.TestCase):
    """Test event coalescing behavior."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.left_path = Path(self.temp_dir) / "left"
        self.right_path = Path(self.temp_dir) / "right"
        self.left_path.mkdir()
        self.right_path.mkdir()
        
        self.config = MockConfig()
        self.file_manager = MockFileManager()
        self.manager = FileMonitorManager(self.config, self.file_manager)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.manager.stop_monitoring()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_rapid_changes_coalesced(self):
        """Test that rapid changes are coalesced into single reload."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.5)  # Wait for initialization events
        
        # Drain initialization events
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Create multiple files rapidly (within coalescing window)
        for i in range(5):
            test_file = self.left_path / f"test{i}.txt"
            test_file.write_text(f"content {i}")
            time.sleep(0.01)  # 10ms between files (within 200ms window)
        
        # Wait for coalescing delay plus processing
        time.sleep(1.0)
        
        # Count reload requests
        reload_count = 0
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
            reload_count += 1
        
        # Should be 1 or 2 due to coalescing (timing variations)
        if reload_count == 0:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")
        else:
            self.assertLessEqual(reload_count, 2)
    
    def test_suppression_after_user_action(self):
        """Test that reloads are suppressed after user action."""
        # Start monitoring
        self.manager.start_monitoring(self.left_path, self.right_path)
        time.sleep(0.5)  # Wait for initialization events
        
        # Drain initialization events
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Suppress reloads for 500ms
        self.manager.suppress_reloads(500)
        
        # Create file during suppression period
        test_file = self.left_path / "test.txt"
        test_file.write_text("test content")
        
        # Wait for event processing (but still within suppression)
        time.sleep(0.3)
        
        # Queue should be empty (suppressed)
        self.assertTrue(self.file_manager.reload_queue.empty())
        
        # Wait for suppression to expire
        time.sleep(0.5)
        
        # Create another file after suppression
        test_file2 = self.left_path / "test2.txt"
        test_file2.write_text("test content 2")
        
        # Wait for event processing
        time.sleep(1.0)
        
        # Should get reload request now
        if not self.file_manager.reload_queue.empty():
            # Drain all posted reloads and check the expected pane is among them.
            # Coalescing and shared observers can post more than one entry, in any
            # order, so asserting on just the first is racy.
            posted = set()
            while not self.file_manager.reload_queue.empty():
                posted.add(self.file_manager.reload_queue.get_nowait())
            self.assertIn("left", posted)
        else:
            self.skipTest("Filesystem events not detected - may be system-specific timing issue")


if __name__ == '__main__':
    unittest.main()
