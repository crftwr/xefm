"""
Test that directory creation and deletion events are detected and trigger reloads.

This test verifies that the file monitoring system detects when directories
are created or deleted in the monitored directory and triggers appropriate
reload events.
"""

import unittest
from unittest.mock import Mock
from pathlib import Path
import tempfile
import shutil

from xefm.file_monitor_observer import XeFMFileSystemEventHandler


class TestDirectoryEventDetection(unittest.TestCase):
    """Test directory creation and deletion event detection"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create temporary directory for testing
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
        # Track events received
        self.events_received = []
        
        def event_callback(event_type, filename):
            self.events_received.append((event_type, filename))
        
        self.event_callback = event_callback
    
    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_directory_creation_detected(self):
        """Test that directory creation in immediate directory is detected"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        # Simulate directory creation event
        event = MockEvent(str(self.temp_path / "newdir"), True)
        handler.on_created(event)
        
        # Verify event was detected
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("created", "newdir"))
    
    def test_directory_deletion_detected(self):
        """Test that directory deletion in immediate directory is detected"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        # Simulate directory deletion event
        event = MockEvent(str(self.temp_path / "olddir"), True)
        handler.on_deleted(event)
        
        # Verify event was detected
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("deleted", "olddir"))
    
    def test_directory_modification_detected(self):
        """Test that directory modification in immediate directory is detected"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        # Simulate directory modification event
        event = MockEvent(str(self.temp_path / "moddir"), True)
        handler.on_modified(event)
        
        # Verify event was detected
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("modified", "moddir"))
    
    def test_directory_rename_detected(self):
        """Test that directory rename in immediate directory is detected"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, dest_path, is_directory):
                self.src_path = src_path
                self.dest_path = dest_path
                self.is_directory = is_directory
        
        # Simulate directory rename event
        event = MockEvent(
            str(self.temp_path / "oldname"),
            str(self.temp_path / "newname"),
            True
        )
        handler.on_moved(event)
        
        # Verify event was detected (rename triggers modified event)
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("modified", "newname"))
    
    def test_subdirectory_events_ignored(self):
        """Test that events in subdirectories are ignored"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        # Simulate directory creation in subdirectory
        subdir = self.temp_path / "subdir" / "nested"
        event = MockEvent(str(subdir), True)
        handler.on_created(event)
        
        # Verify event was ignored (not an immediate child)
        self.assertEqual(len(self.events_received), 0)
    
    def test_file_and_directory_events_both_detected(self):
        """Test that both file and directory events are detected"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        # Create file event
        file_event = MockEvent(str(self.temp_path / "file.txt"), False)
        handler.on_created(file_event)
        
        # Create directory event
        dir_event = MockEvent(str(self.temp_path / "newdir"), True)
        handler.on_created(dir_event)
        
        # Verify both events were detected
        self.assertEqual(len(self.events_received), 2)
        self.assertEqual(self.events_received[0], ("created", "file.txt"))
        self.assertEqual(self.events_received[1], ("created", "newdir"))


if __name__ == '__main__':
    unittest.main()
