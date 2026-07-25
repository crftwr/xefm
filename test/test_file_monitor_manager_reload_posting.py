"""
Unit tests for FileMonitorManager reload request posting.

Tests the _post_reload_request method to verify:
- Thread-safe queue operations
- Proper state management
- Logging for reload requests
"""

import unittest
import queue
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch
from xefm.file_monitor_manager import FileMonitorManager


class TestFileMonitorManagerReloadPosting(unittest.TestCase):
    """Test FileMonitorManager reload request posting"""
    
    def setUp(self):
        """Set up test fixtures"""
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
        self.manager.stop_monitoring()
    
    def test_post_reload_request_posts_to_queue(self):
        """Test that _post_reload_request posts pane name to reload queue"""
        # Post reload request for left pane
        self.manager._post_reload_request('left')
        
        # Verify pane name was posted to queue
        self.assertFalse(self.file_manager.reload_queue.empty())
        pane_name = self.file_manager.reload_queue.get_nowait()
        self.assertEqual(pane_name, 'left')
        
        # Queue should be empty now
        self.assertTrue(self.file_manager.reload_queue.empty())
    
    def test_post_reload_request_clears_pending_flag(self):
        """Test that _post_reload_request clears pending_reload flag"""
        # Set pending_reload flag
        self.manager.monitoring_state['left']['pending_reload'] = True
        
        # Post reload request
        self.manager._post_reload_request('left')
        
        # Verify pending_reload flag was cleared
        self.assertFalse(self.manager.monitoring_state['left']['pending_reload'])
    
    def test_post_reload_request_records_reload_time(self):
        """Test that _post_reload_request records reload time for rate limiting"""
        # Get initial reload time
        initial_time = self.manager.monitoring_state['left']['last_reload_time']
        
        # Post reload request
        time.sleep(0.01)  # Small delay to ensure time difference
        self.manager._post_reload_request('left')
        
        # Verify reload time was updated
        new_time = self.manager.monitoring_state['left']['last_reload_time']
        self.assertGreater(new_time, initial_time)
        
        # Verify reload time was added to reload_times list
        self.assertGreater(len(self.manager.reload_times['left']), 0)
        self.assertEqual(self.manager.reload_times['left'][-1], new_time)
    
    def test_post_reload_request_thread_safety(self):
        """Test that _post_reload_request is thread-safe"""
        # Number of threads to use
        num_threads = 10
        
        # Function to post reload requests from multiple threads
        def post_requests():
            for _ in range(5):
                self.manager._post_reload_request('left')
                time.sleep(0.001)
        
        # Create and start threads
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=post_requests)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Count items in queue
        reload_count = 0
        while not self.file_manager.reload_queue.empty():
            self.file_manager.reload_queue.get_nowait()
            reload_count += 1
        
        # Should have exactly num_threads * 5 reload requests
        self.assertEqual(reload_count, num_threads * 5)
    
    @patch('xefm.file_monitor_manager.getLogger')
    def test_post_reload_request_logs_message(self, mock_get_logger):
        """Test that _post_reload_request logs reload request"""
        # Create mock logger
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        # Create new manager with mocked logger
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Post reload request
        manager._post_reload_request('left')
        
        # Verify logger.info was called with appropriate message
        mock_logger.debug.assert_called()
        call_args = mock_logger.debug.call_args[0][0]
        self.assertIn('left', call_args.lower())
        self.assertIn('reload', call_args.lower())
    
    def test_post_reload_request_both_panes(self):
        """Test posting reload requests for both panes independently"""
        # Post reload request for left pane
        self.manager._post_reload_request('left')
        
        # Post reload request for right pane
        self.manager._post_reload_request('right')
        
        # Verify both requests were posted
        self.assertFalse(self.file_manager.reload_queue.empty())
        
        # Get first request
        pane1 = self.file_manager.reload_queue.get_nowait()
        self.assertEqual(pane1, 'left')
        
        # Get second request
        pane2 = self.file_manager.reload_queue.get_nowait()
        self.assertEqual(pane2, 'right')
        
        # Queue should be empty now
        self.assertTrue(self.file_manager.reload_queue.empty())
    
    def test_post_reload_request_multiple_times_same_pane(self):
        """Test posting multiple reload requests for same pane"""
        # Post multiple reload requests
        for _ in range(3):
            self.manager._post_reload_request('left')
        
        # Verify all requests were posted
        reload_count = 0
        while not self.file_manager.reload_queue.empty():
            pane_name = self.file_manager.reload_queue.get_nowait()
            self.assertEqual(pane_name, 'left')
            reload_count += 1
        
        self.assertEqual(reload_count, 3)
    
    def test_post_reload_request_updates_state_atomically(self):
        """Test that _post_reload_request updates state atomically"""
        # Set initial state
        self.manager.monitoring_state['left']['pending_reload'] = True
        initial_time = self.manager.monitoring_state['left']['last_reload_time']
        
        # Post reload request
        self.manager._post_reload_request('left')
        
        # Verify all state changes occurred
        self.assertFalse(self.manager.monitoring_state['left']['pending_reload'])
        self.assertGreater(self.manager.monitoring_state['left']['last_reload_time'], initial_time)
        self.assertFalse(self.file_manager.reload_queue.empty())


if __name__ == '__main__':
    unittest.main()
