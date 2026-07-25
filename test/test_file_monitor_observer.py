#!/usr/bin/env python3
"""
Unit tests for FileMonitorObserver class.

Tests basic observer functionality, initialization, start/stop, and error handling.
"""

import unittest
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xefm.file_monitor_observer import FileMonitorObserver, WATCHDOG_AVAILABLE
from xefm.log_manager import getLogger


class TestFileMonitorObserver(unittest.TestCase):
    """Test FileMonitorObserver class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.logger = getLogger("TestObserver")
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.events_received = []
        
    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def event_callback(self, event_type: str, filename: str):
        """Callback to record events"""
        self.events_received.append((event_type, filename))
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_initialization(self):
        """Test observer initialization"""
        observer = FileMonitorObserver(self.temp_path, self.event_callback, self.logger)
        
        self.assertEqual(observer.path, self.temp_path)
        self.assertEqual(observer.event_callback, self.event_callback)
        self.assertEqual(observer.logger, self.logger)
        self.assertIsNone(observer.observer)
        self.assertEqual(observer.monitoring_mode, "disabled")
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_start_monitoring_success(self):
        """Test successful monitoring start"""
        observer = FileMonitorObserver(self.temp_path, self.event_callback, self.logger)
        
        result = observer.start()
        
        self.assertTrue(result)
        self.assertIsNotNone(observer.observer)
        self.assertIn(observer.monitoring_mode, ["native", "polling"])
        self.assertTrue(observer.is_alive())
        
        # Clean up
        observer.stop()
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_start_monitoring_nonexistent_directory(self):
        """Test monitoring start fails for non-existent directory"""
        nonexistent_path = Path(self.temp_dir) / "nonexistent"
        observer = FileMonitorObserver(nonexistent_path, self.event_callback, self.logger)
        
        result = observer.start()
        
        self.assertFalse(result)
        self.assertIsNone(observer.observer)
        self.assertEqual(observer.monitoring_mode, "disabled")
        self.assertFalse(observer.is_alive())
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_start_monitoring_file_path(self):
        """Test monitoring start fails for file path (not directory)"""
        # Create a file
        file_path = self.temp_path / "test_file.txt"
        file_path.write_text("test content")
        
        observer = FileMonitorObserver(file_path, self.event_callback, self.logger)
        
        result = observer.start()
        
        self.assertFalse(result)
        self.assertIsNone(observer.observer)
        self.assertEqual(observer.monitoring_mode, "disabled")
        self.assertFalse(observer.is_alive())
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_stop_monitoring(self):
        """Test stopping monitoring"""
        observer = FileMonitorObserver(self.temp_path, self.event_callback, self.logger)
        
        # Start monitoring
        observer.start()
        self.assertTrue(observer.is_alive())
        
        # Stop monitoring
        observer.stop()
        
        self.assertIsNone(observer.observer)
        self.assertEqual(observer.monitoring_mode, "disabled")
        self.assertFalse(observer.is_alive())
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_stop_monitoring_when_not_started(self):
        """Test stopping monitoring when it was never started"""
        observer = FileMonitorObserver(self.temp_path, self.event_callback, self.logger)
        
        # Should not raise an error
        observer.stop()
        
        self.assertIsNone(observer.observer)
        self.assertEqual(observer.monitoring_mode, "disabled")
        self.assertFalse(observer.is_alive())
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_is_alive_when_not_started(self):
        """Test is_alive returns False when observer not started"""
        observer = FileMonitorObserver(self.temp_path, self.event_callback, self.logger)
        
        self.assertFalse(observer.is_alive())
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_get_monitoring_mode_initial(self):
        """Test get_monitoring_mode returns 'disabled' initially"""
        observer = FileMonitorObserver(self.temp_path, self.event_callback, self.logger)
        
        self.assertEqual(observer.get_monitoring_mode(), "disabled")
    
    @unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
    def test_get_monitoring_mode_after_start(self):
        """Test get_monitoring_mode returns correct mode after start"""
        observer = FileMonitorObserver(self.temp_path, self.event_callback, self.logger)
        
        observer.start()
        mode = observer.get_monitoring_mode()
        
        self.assertIn(mode, ["native", "polling"])
        
        # Clean up
        observer.stop()
    
    def test_watchdog_not_available(self):
        """Test behavior when watchdog is not available"""
        # This test will only be meaningful if watchdog is actually not available
        # but we can still test the code path
        if not WATCHDOG_AVAILABLE:
            observer = FileMonitorObserver(self.temp_path, self.event_callback, self.logger)
            result = observer.start()
            self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
