"""
Test that file monitoring is updated when paths are synchronized between panes.

This test verifies that when the O key is used to synchronize paths between
left and right panes, the file monitoring is correctly updated for the pane
whose path changed.
"""

import unittest
from pathlib import Path
import tempfile
import shutil
import time
import queue
from unittest.mock import Mock, MagicMock, patch
from xefm.file_monitor_manager import FileMonitorManager


class TestPathSyncMonitoringUpdate(unittest.TestCase):
    """Test cases for monitoring updates during path synchronization."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directories for testing
        self.left_dir = Path(tempfile.mkdtemp())
        self.right_dir = Path(tempfile.mkdtemp())
        
        # Create mock config with monitoring enabled
        self.config = Mock()
        self.config.FILE_MONITORING_ENABLED = True
        self.config.FILE_MONITORING_COALESCE_DELAY_MS = 200
        self.config.FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
        self.config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5
        
        # Create mock file_manager with reload_queue
        self.file_manager = Mock()
        self.file_manager.reload_queue = queue.Queue()
        
        # Create FileMonitorManager instance
        self.monitor_manager = FileMonitorManager(self.config, self.file_manager)
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Stop monitoring
        self.monitor_manager.stop_monitoring()
        
        # Remove temporary directories
        shutil.rmtree(self.left_dir)
        shutil.rmtree(self.right_dir)
    
    def test_sync_other_to_current_updates_monitoring(self):
        """Test that syncing other pane to current updates monitoring for other pane."""
        # Start monitoring with different directories
        self.monitor_manager.start_monitoring(self.left_dir, self.right_dir)
        
        # Give observers time to start
        time.sleep(0.5)
        
        # Verify initial state - different directories
        left_state = self.monitor_manager.monitoring_state['left']
        right_state = self.monitor_manager.monitoring_state['right']
        
        self.assertEqual(left_state['path'], self.left_dir)
        self.assertEqual(right_state['path'], self.right_dir)
        self.assertIsNotNone(left_state['observer'])
        self.assertIsNotNone(right_state['observer'])
        
        # Get initial observer references
        initial_left_observer = left_state['observer']
        initial_right_observer = right_state['observer']
        
        # Simulate sync_other_to_current: right pane (other) syncs to left pane (current)
        # This should update right pane's monitoring to left_dir
        self.monitor_manager.update_monitored_directory('right', self.left_dir)
        
        # Give time for update
        time.sleep(0.5)
        
        # Verify right pane now monitors left_dir
        right_state = self.monitor_manager.monitoring_state['right']
        self.assertEqual(right_state['path'], self.left_dir)
        
        # Verify both panes now share the same observer (since they monitor same directory)
        left_state = self.monitor_manager.monitoring_state['left']
        self.assertIs(left_state['observer'], right_state['observer'],
                     "Both panes should share observer after sync")
    
    def test_sync_current_to_other_updates_monitoring(self):
        """Test that syncing current pane to other updates monitoring for current pane."""
        # Start monitoring with different directories
        self.monitor_manager.start_monitoring(self.left_dir, self.right_dir)
        
        # Give observers time to start
        time.sleep(0.5)
        
        # Verify initial state - different directories
        left_state = self.monitor_manager.monitoring_state['left']
        right_state = self.monitor_manager.monitoring_state['right']
        
        self.assertEqual(left_state['path'], self.left_dir)
        self.assertEqual(right_state['path'], self.right_dir)
        
        # Simulate sync_current_to_other: left pane (current) syncs to right pane (other)
        # This should update left pane's monitoring to right_dir
        self.monitor_manager.update_monitored_directory('left', self.right_dir)
        
        # Give time for update
        time.sleep(0.5)
        
        # Verify left pane now monitors right_dir
        left_state = self.monitor_manager.monitoring_state['left']
        self.assertEqual(left_state['path'], self.right_dir)
        
        # Verify both panes now share the same observer (since they monitor same directory)
        right_state = self.monitor_manager.monitoring_state['right']
        self.assertIs(left_state['observer'], right_state['observer'],
                     "Both panes should share observer after sync")
    
    def test_synced_panes_both_receive_events(self):
        """Test that after sync, both panes receive filesystem events."""
        # Start monitoring with different directories
        self.monitor_manager.start_monitoring(self.left_dir, self.right_dir)
        
        # Give observers time to start
        time.sleep(0.5)
        
        # Drain any initialization events
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Sync right pane to left pane's directory
        self.monitor_manager.update_monitored_directory('right', self.left_dir)
        
        # Give time for update
        time.sleep(0.5)
        
        # Drain any events from the sync
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Create a file in the shared directory
        test_file = self.left_dir / "test_file.txt"
        test_file.write_text("test content")
        
        # Wait for event detection and coalescing
        time.sleep(0.5)
        
        # Check reload queue - should have reload requests for both panes
        reload_requests = []
        while not self.file_manager.reload_queue.empty():
            reload_requests.append(self.file_manager.reload_queue.get_nowait())
        
        # Both panes should receive reload requests
        self.assertGreaterEqual(len(reload_requests), 2,
                               "Both panes should receive reload requests after sync")
        self.assertIn('left', reload_requests, "Left pane should receive reload request")
        self.assertIn('right', reload_requests, "Right pane should receive reload request")
        
        # Clean up
        test_file.unlink()
    
    def test_multiple_syncs_maintain_correct_monitoring(self):
        """Test that multiple path syncs maintain correct monitoring state."""
        # Start monitoring with different directories
        self.monitor_manager.start_monitoring(self.left_dir, self.right_dir)
        
        # Give observers time to start
        time.sleep(0.5)
        
        # Sync right to left
        self.monitor_manager.update_monitored_directory('right', self.left_dir)
        time.sleep(0.5)
        
        # Verify both monitor left_dir
        left_state = self.monitor_manager.monitoring_state['left']
        right_state = self.monitor_manager.monitoring_state['right']
        self.assertEqual(left_state['path'], self.left_dir)
        self.assertEqual(right_state['path'], self.left_dir)
        self.assertIs(left_state['observer'], right_state['observer'])
        
        # Now sync right back to right_dir (navigate away from shared directory)
        self.monitor_manager.update_monitored_directory('right', self.right_dir)
        time.sleep(0.5)
        
        # Verify left still monitors left_dir and right monitors right_dir
        left_state = self.monitor_manager.monitoring_state['left']
        right_state = self.monitor_manager.monitoring_state['right']
        self.assertEqual(left_state['path'], self.left_dir)
        self.assertEqual(right_state['path'], self.right_dir)
        # They should have different observers now
        self.assertIsNot(left_state['observer'], right_state['observer'])


if __name__ == '__main__':
    unittest.main()
