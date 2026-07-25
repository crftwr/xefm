"""
Tests for polling interval configuration in FileMonitorObserver.

This test verifies that the configured polling interval is properly passed
to the PollingObserver when fallback mode is used.
"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from xefm.log_manager import getLogger


class TestPollingInterval(unittest.TestCase):
    """Test polling interval configuration."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.logger = getLogger("TestPolling")
        self.test_path = Path("/tmp/test_dir")
        self.callback = Mock()
    
    @patch('xefm.file_monitor_observer.PollingObserver')
    @patch('xefm.file_monitor_observer.XeFMFileSystemEventHandler')
    def test_polling_observer_uses_configured_interval(self, mock_handler, mock_polling_observer):
        """Test that PollingObserver is created with the configured interval."""
        from xefm.file_monitor_observer import FileMonitorObserver
        
        # Create a mock observer instance
        mock_observer_instance = MagicMock()
        mock_polling_observer.return_value = mock_observer_instance
        
        # Create FileMonitorObserver with custom polling interval
        custom_interval = 10.0
        observer = FileMonitorObserver(
            self.test_path,
            self.callback,
            self.logger,
            force_polling=True,
            polling_interval=custom_interval
        )
        
        # Mock the path to exist
        with patch.object(Path, 'exists', return_value=True):
            with patch.object(Path, 'is_dir', return_value=True):
                # Start monitoring
                result = observer.start()
        
        # Verify PollingObserver was called with the correct timeout
        mock_polling_observer.assert_called_once_with(timeout=custom_interval)
        
        # Verify start was successful
        self.assertTrue(result)
    
    @patch('xefm.file_monitor_observer.PollingObserver')
    @patch('xefm.file_monitor_observer.XeFMFileSystemEventHandler')
    def test_default_polling_interval(self, mock_handler, mock_polling_observer):
        """Test that default polling interval is used when not specified."""
        from xefm.file_monitor_observer import FileMonitorObserver
        
        # Create a mock observer instance
        mock_observer_instance = MagicMock()
        mock_polling_observer.return_value = mock_observer_instance
        
        # Create FileMonitorObserver without specifying polling interval
        observer = FileMonitorObserver(
            self.test_path,
            self.callback,
            self.logger,
            force_polling=True
            # polling_interval not specified, should use default 5.0
        )
        
        # Mock the path to exist
        with patch.object(Path, 'exists', return_value=True):
            with patch.object(Path, 'is_dir', return_value=True):
                # Start monitoring
                result = observer.start()
        
        # Verify PollingObserver was called with the default timeout
        mock_polling_observer.assert_called_once_with(timeout=5.0)
        
        # Verify start was successful
        self.assertTrue(result)
    
    @patch('xefm.file_monitor_observer.Observer')
    @patch('xefm.file_monitor_observer.PollingObserver')
    @patch('xefm.file_monitor_observer.XeFMFileSystemEventHandler')
    def test_fallback_to_polling_uses_interval(self, mock_handler, mock_polling_observer, mock_observer):
        """Test that fallback to polling uses the configured interval."""
        from xefm.file_monitor_observer import FileMonitorObserver
        
        # Make native observer fail
        mock_observer.side_effect = Exception("Native monitoring failed")
        
        # Create a mock polling observer instance
        mock_polling_instance = MagicMock()
        mock_polling_observer.return_value = mock_polling_instance
        
        # Create FileMonitorObserver with custom polling interval
        custom_interval = 7.5
        observer = FileMonitorObserver(
            self.test_path,
            self.callback,
            self.logger,
            force_polling=False,  # Try native first
            polling_interval=custom_interval
        )
        
        # Mock the path to exist
        with patch.object(Path, 'exists', return_value=True):
            with patch.object(Path, 'is_dir', return_value=True):
                # Mock _detect_platform_and_api to return a valid platform without importing
                with patch.object(observer, '_detect_platform_and_api', return_value=('Linux', 'inotify')):
                    # Start monitoring (should fail native and fallback to polling)
                    result = observer.start()
        
        # Verify PollingObserver was called with the correct timeout
        mock_polling_observer.assert_called_once_with(timeout=custom_interval)
        
        # Verify start was successful
        self.assertTrue(result)
        
        # Verify monitoring mode is polling
        self.assertEqual(observer.get_monitoring_mode(), "polling")


if __name__ == '__main__':
    unittest.main()
