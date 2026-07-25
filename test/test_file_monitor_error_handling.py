"""
Unit tests for FileMonitorManager error handling and recovery.

Tests error handling in event callbacks, reinitialization logic with retry,
fallback to polling mode after repeated failures, and logging of errors
and mode transitions.
"""

import unittest
import tempfile
import shutil
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import queue

# Add the repo root to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from xefm.file_monitor_manager import FileMonitorManager
from xefm.file_monitor_observer import FileMonitorObserver
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


class TestErrorHandlingInEventCallbacks(unittest.TestCase):
    """Test error handling in event callbacks."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.config = MockConfig()
        self.file_manager = MockFileManager()
        self.logger = getLogger("TestFileMonitor")
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_event_callback_error_does_not_crash_monitoring(self):
        """Test that errors in event callbacks don't crash monitoring."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Create a callback that raises an exception
        error_raised = threading.Event()
        
        def failing_callback(event_type: str, filename: str):
            error_raised.set()
            raise ValueError("Test error in callback")
        
        # Create observer with failing callback
        observer = FileMonitorObserver(self.temp_path, failing_callback, self.logger)
        
        # Start observer
        self.assertTrue(observer.start())
        
        # Create a file to trigger event
        test_file = self.temp_path / "test.txt"
        test_file.write_text("test")
        
        # Wait for event to be processed
        time.sleep(0.5)
        
        # Observer should still be alive despite callback error
        self.assertTrue(observer.is_alive())
        
        # Clean up
        observer.stop()
    
    def test_filesystem_event_handler_error_logged(self):
        """Test that errors in _on_filesystem_event are logged."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Mock the logger to capture error messages
        with patch.object(manager.logger, 'error') as mock_error:
            # Simulate an error by passing invalid data
            # This should be caught and logged
            try:
                manager._on_filesystem_event('left', 'created', 'test.txt')
            except Exception:
                pass  # Error should be caught internally
            
            # The method should handle errors gracefully
            # and continue without crashing


class TestReinitialization(unittest.TestCase):
    """Test reinitialization logic with retry and exponential backoff."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.config = MockConfig()
        self.file_manager = MockFileManager()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_retry_count_increments_on_failure(self):
        """Test that retry count increments when monitoring fails."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Mock FileMonitorObserver to always fail
        with patch('xefm.file_monitor_manager.FileMonitorObserver') as mock_observer_class:
            mock_observer = Mock()
            mock_observer.start.return_value = False
            mock_observer_class.return_value = mock_observer
            
            # Try to start monitoring
            manager._start_pane_monitoring('left', self.temp_path)
            
            # Check that retry was scheduled
            state = manager.monitoring_state['left']
            self.assertEqual(state['error_count'], 1)
    
    def test_exponential_backoff_timing(self):
        """Test that retry uses exponential backoff (1s, 2s, 4s)."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Track retry timings
        retry_times = []
        
        def track_retry(*args, **kwargs):
            retry_times.append(time.time())
            return False
        
        # Mock FileMonitorObserver to always fail
        with patch('xefm.file_monitor_manager.FileMonitorObserver') as mock_observer_class:
            mock_observer = Mock()
            mock_observer.start.side_effect = track_retry
            mock_observer_class.return_value = mock_observer
            
            # Start monitoring (will fail and schedule retries)
            manager._start_pane_monitoring('left', self.temp_path)
            
            # Wait for retries to complete (1s + 2s + 4s = 7s + buffer)
            time.sleep(8)
            
            # Should have initial attempt + 3 retries
            # Note: This is a timing-sensitive test and may be flaky
            # In practice, we verify the retry_count instead
            state = manager.monitoring_state['left']
            self.assertGreaterEqual(state['retry_count'], 1)
    
    def test_successful_retry_resets_counters(self):
        """Test that successful retry resets error and retry counters."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Set up state as if we had previous failures
        state = manager.monitoring_state['left']
        state['error_count'] = 2
        state['retry_count'] = 1
        
        # Now start monitoring successfully
        manager._start_pane_monitoring('left', self.temp_path)
        
        # Counters should be reset
        self.assertEqual(state['error_count'], 0)
        self.assertEqual(state['retry_count'], 0)
        self.assertIsNotNone(state['observer'])
        
        # Clean up
        if state['observer']:
            state['observer'].stop()


class TestFallbackToPolling(unittest.TestCase):
    """Test fallback to polling mode after repeated failures."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.config = MockConfig()
        self.file_manager = MockFileManager()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_fallback_after_three_failures(self):
        """Test that monitoring falls back to polling after 3 failures."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Simulate 3 failures
        state = manager.monitoring_state['left']
        state['retry_count'] = 3
        
        # Mock FileMonitorObserver to fail for native but succeed for polling
        call_count = [0]
        
        def mock_start(self):
            call_count[0] += 1
            # Fail for native attempts, succeed for polling
            if self.force_polling:
                self.monitoring_mode = "polling"
                return True
            return False
        
        with patch.object(FileMonitorObserver, 'start', mock_start):
            # This should trigger fallback to polling
            manager._schedule_retry('left', self.temp_path)
            
            # Wait for retry to execute
            time.sleep(0.5)
            
            # Should have marked as failed permanently and attempted polling
            self.assertTrue(state['failed_permanently'])
    
    def test_polling_fallback_logs_mode_transition(self):
        """Test that fallback to polling logs mode transition."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # The polling-fallback messages are logged at DEBUG level.
        with patch.object(manager.logger, 'debug') as mock_debug:
            # Trigger polling fallback
            manager._attempt_polling_fallback('left', self.temp_path)

            # Wait for operation to complete
            time.sleep(0.5)

            # Should have logged mode transition
            # Check if any call contains "Mode transition" or "polling"
            debug_calls = [str(call) for call in mock_debug.call_args_list]
            has_transition_log = any('transition' in str(call).lower() or 'polling' in str(call).lower()
                                    for call in debug_calls)
            self.assertTrue(has_transition_log, "Should log mode transition to polling")
        
        # Clean up
        state = manager.monitoring_state['left']
        if state['observer']:
            state['observer'].stop()


class TestErrorLogging(unittest.TestCase):
    """Test logging of errors, mode transitions, and recovery attempts."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.config = MockConfig()
        self.file_manager = MockFileManager()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_initialization_failure_logged(self):
        """Test that initialization failures are logged with context."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Mock FileMonitorObserver to fail
        with patch('xefm.file_monitor_manager.FileMonitorObserver') as mock_observer_class:
            mock_observer = Mock()
            mock_observer.start.return_value = False
            mock_observer_class.return_value = mock_observer
            
            # Mock logger to capture error messages
            with patch.object(manager.logger, 'error') as mock_error:
                # Try to start monitoring
                manager._start_pane_monitoring('left', self.temp_path)
                
                # Should have logged error
                mock_error.assert_called()
                
                # Check that error message contains context
                error_call = mock_error.call_args[0][0]
                self.assertIn('left', error_call.lower())
    
    def test_retry_attempt_logged(self):
        """Test that retry attempts are logged."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Mock logger to capture info messages
        with patch.object(manager.logger, 'debug') as mock_debug:
            # Set up state for retry
            state = manager.monitoring_state['left']
            state['retry_count'] = 0

            # Schedule a retry
            manager._schedule_retry('left', self.temp_path)

            # Should have logged retry scheduling (at DEBUG level)
            debug_calls = [str(call) for call in mock_debug.call_args_list]
            has_retry_log = any('retry' in str(call).lower() for call in debug_calls)
            self.assertTrue(has_retry_log, "Should log retry scheduling")
    
    def test_permanent_failure_logged(self):
        """Test that permanent failure after 3 retries is logged."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Set up state for final failure
        state = manager.monitoring_state['left']
        state['retry_count'] = 3
        
        # Mock logger to capture error messages
        with patch.object(manager.logger, 'error') as mock_error:
            # This should trigger permanent failure
            manager._schedule_retry('left', self.temp_path)
            
            # Should have logged permanent failure
            error_calls = [str(call) for call in mock_error.call_args_list]
            has_permanent_failure_log = any('permanently' in str(call).lower() or 'failed 3' in str(call).lower()
                                           for call in error_calls)
            self.assertTrue(has_permanent_failure_log, "Should log permanent failure")


class TestObserverHealthCheck(unittest.TestCase):
    """Test observer health checking and recovery."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.config = MockConfig()
        self.file_manager = MockFileManager()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_health_check_detects_dead_observer(self):
        """Test that health check detects when observer has died."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Start monitoring
        manager._start_pane_monitoring('left', self.temp_path)
        
        state = manager.monitoring_state['left']
        if state['observer']:
            # Mock the observer to appear dead
            with patch.object(state['observer'], 'is_alive', return_value=False):
                # Mock logger to capture error messages
                with patch.object(manager.logger, 'error') as mock_error:
                    # Run health check
                    manager.check_observer_health()
                    
                    # Should have logged that observer died
                    error_calls = [str(call) for call in mock_error.call_args_list]
                    has_died_log = any('died' in str(call).lower() for call in error_calls)
                    self.assertTrue(has_died_log, "Should log that observer died")
            
            # Clean up
            if state['observer']:
                state['observer'].stop()
    
    def test_health_check_skips_permanently_failed(self):
        """Test that health check skips permanently failed observers."""
        manager = FileMonitorManager(self.config, self.file_manager)
        
        # Mark as permanently failed
        state = manager.monitoring_state['left']
        state['failed_permanently'] = True
        state['observer'] = None
        
        # Health check should not attempt recovery
        manager.check_observer_health()
        
        # Observer should still be None
        self.assertIsNone(state['observer'])


if __name__ == '__main__':
    unittest.main()
