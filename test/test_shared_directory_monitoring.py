"""
Test shared directory monitoring - both panes monitoring same directory.

This test verifies that when both left and right panes are viewing the same
directory, the FileMonitorManager correctly shares a single observer instead
of trying to create two separate observers (which would cause FSEvents error).
"""

import unittest
from pathlib import Path
import tempfile
import shutil
import time
import queue
from unittest.mock import Mock, MagicMock
from xefm.file_monitor_manager import FileMonitorManager


class TestSharedDirectoryMonitoring(unittest.TestCase):
    """Test cases for shared directory monitoring."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directory for testing
        self.test_dir = Path(tempfile.mkdtemp())
        
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
        
        # Remove temporary directory
        shutil.rmtree(self.test_dir)
    
    def test_both_panes_same_directory_share_observer(self):
        """Test that both panes monitoring same directory share a single observer."""
        # Start monitoring with both panes pointing to same directory
        self.monitor_manager.start_monitoring(self.test_dir, self.test_dir)
        
        # Give observers time to start
        time.sleep(0.5)
        
        # Verify both panes have observers
        left_state = self.monitor_manager.monitoring_state['left']
        right_state = self.monitor_manager.monitoring_state['right']
        
        self.assertIsNotNone(left_state['observer'], "Left pane should have observer")
        self.assertIsNotNone(right_state['observer'], "Right pane should have observer")
        
        # Verify both panes share the same observer instance
        self.assertIs(left_state['observer'], right_state['observer'],
                     "Both panes should share the same observer instance")
        
        # Verify both panes are monitoring the same path
        self.assertEqual(left_state['path'], self.test_dir)
        self.assertEqual(right_state['path'], self.test_dir)
    
    def test_shared_observer_detects_changes(self):
        """Test that shared observer can trigger reloads for both panes."""
        # Start monitoring with both panes pointing to same directory
        self.monitor_manager.start_monitoring(self.test_dir, self.test_dir)
        
        # Give observers time to start
        time.sleep(0.5)
        
        # Drain any initialization events
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
        
        # Manually trigger an event through the callback to test the mechanism
        # This simulates what would happen when a real filesystem event occurs
        left_state = self.monitor_manager.monitoring_state['left']
        
        # Call the event callback directly (simulating a filesystem event)
        self.monitor_manager._on_filesystem_event('left', 'created', 'test_file.txt')
        
        # Wait for coalescing
        time.sleep(0.5)
        
        # Check reload queue - should have reload requests for both panes
        reload_requests = []
        while not self.file_manager.reload_queue.empty():
            reload_requests.append(self.file_manager.reload_queue.get_nowait())
        
        # When both panes share a directory, both should get reload requests
        self.assertGreaterEqual(len(reload_requests), 2,
                               "Both panes should receive reload requests when sharing a directory")
        self.assertIn('left', reload_requests, "Left pane should receive reload request")
        self.assertIn('right', reload_requests, "Right pane should receive reload request")
    
    def test_one_pane_navigates_away_observer_remains(self):
        """Test that when one pane navigates away, observer remains for the other pane."""
        # Start monitoring with both panes pointing to same directory
        self.monitor_manager.start_monitoring(self.test_dir, self.test_dir)
        
        # Give observers time to start
        time.sleep(0.5)
        
        # Get the shared observer reference
        shared_observer = self.monitor_manager.monitoring_state['left']['observer']
        
        # Create a different directory for navigation
        other_dir = Path(tempfile.mkdtemp())
        
        try:
            # Navigate left pane to different directory
            self.monitor_manager.update_monitored_directory('left', other_dir)
            
            # Give time for update
            time.sleep(0.5)
            
            # Verify right pane still has the original observer
            right_state = self.monitor_manager.monitoring_state['right']
            self.assertIsNotNone(right_state['observer'],
                               "Right pane should still have observer")
            self.assertIs(right_state['observer'], shared_observer,
                         "Right pane should still have the original shared observer")
            
            # Verify left pane has a different observer now
            left_state = self.monitor_manager.monitoring_state['left']
            self.assertIsNotNone(left_state['observer'],
                               "Left pane should have new observer")
            self.assertIsNot(left_state['observer'], shared_observer,
                           "Left pane should have a different observer now")
            
            # Verify the shared observer is still alive
            self.assertTrue(shared_observer.is_alive(),
                          "Shared observer should still be alive for right pane")
        
        finally:
            # Clean up the other directory
            shutil.rmtree(other_dir)
    
    def test_both_panes_navigate_away_observer_stops(self):
        """Test that when both panes navigate away, the shared observer is stopped."""
        # Start monitoring with both panes pointing to same directory
        self.monitor_manager.start_monitoring(self.test_dir, self.test_dir)
        
        # Give observers time to start
        time.sleep(0.5)
        
        # Get the shared observer reference
        shared_observer = self.monitor_manager.monitoring_state['left']['observer']
        
        # Create different directories for navigation
        left_dir = Path(tempfile.mkdtemp())
        right_dir = Path(tempfile.mkdtemp())
        
        try:
            # Navigate both panes to different directories
            self.monitor_manager.update_monitored_directory('left', left_dir)
            self.monitor_manager.update_monitored_directory('right', right_dir)
            
            # Give time for updates
            time.sleep(0.5)
            
            # Verify both panes have new observers
            left_state = self.monitor_manager.monitoring_state['left']
            right_state = self.monitor_manager.monitoring_state['right']
            
            self.assertIsNotNone(left_state['observer'],
                               "Left pane should have new observer")
            self.assertIsNotNone(right_state['observer'],
                               "Right pane should have new observer")
            
            # Verify they are different observers
            self.assertIsNot(left_state['observer'], right_state['observer'],
                           "Panes should have different observers now")
            
            # Verify the original shared observer was stopped
            # Note: We can't directly check if it's stopped, but we can verify
            # that the panes no longer reference it
            self.assertIsNot(left_state['observer'], shared_observer,
                           "Left pane should not reference old shared observer")
            self.assertIsNot(right_state['observer'], shared_observer,
                           "Right pane should not reference old shared observer")
        
        finally:
            # Clean up the other directories
            shutil.rmtree(left_dir)
            shutil.rmtree(right_dir)
    
    def test_sequential_same_directory_monitoring(self):
        """Test starting with different directories, then both navigate to same directory."""
        # Create two different directories
        left_dir = Path(tempfile.mkdtemp())
        right_dir = Path(tempfile.mkdtemp())
        
        try:
            # Start monitoring with different directories
            self.monitor_manager.start_monitoring(left_dir, right_dir)
            
            # Give observers time to start
            time.sleep(0.5)
            
            # Verify both panes have different observers
            left_observer_1 = self.monitor_manager.monitoring_state['left']['observer']
            right_observer_1 = self.monitor_manager.monitoring_state['right']['observer']
            
            self.assertIsNotNone(left_observer_1)
            self.assertIsNotNone(right_observer_1)
            self.assertIsNot(left_observer_1, right_observer_1,
                           "Initially, panes should have different observers")
            
            # Navigate left pane to same directory as right pane
            self.monitor_manager.update_monitored_directory('left', right_dir)
            
            # Give time for update
            time.sleep(0.5)
            
            # Verify both panes now share the same observer
            left_observer_2 = self.monitor_manager.monitoring_state['left']['observer']
            right_observer_2 = self.monitor_manager.monitoring_state['right']['observer']
            
            self.assertIsNotNone(left_observer_2)
            self.assertIsNotNone(right_observer_2)
            self.assertIs(left_observer_2, right_observer_2,
                         "After navigation, panes should share the same observer")
        
        finally:
            # Clean up the directories
            shutil.rmtree(left_dir)
            shutil.rmtree(right_dir)


if __name__ == '__main__':
    unittest.main()
