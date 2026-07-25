#!/usr/bin/env python3
"""
Unit tests for XeFMFileSystemEventHandler class.

Tests event detection, filtering, and move operation handling.
"""

import unittest
import sys
import os
import tempfile
import shutil
import time
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xefm.file_monitor_observer import XeFMFileSystemEventHandler, WATCHDOG_AVAILABLE


@unittest.skipIf(not WATCHDOG_AVAILABLE, "watchdog library not available")
class TestXeFMFileSystemEventHandler(unittest.TestCase):
    """Test XeFMFileSystemEventHandler class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.events_received = []
        
        # Create a subdirectory for testing subdirectory filtering
        self.subdir = self.temp_path / "subdir"
        self.subdir.mkdir()
        
    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def event_callback(self, event_type: str, filename: str):
        """Callback to record events"""
        self.events_received.append((event_type, filename))
    
    def test_initialization(self):
        """Test event handler initialization"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        self.assertEqual(handler.callback, self.event_callback)
        self.assertEqual(handler.watched_path, self.temp_path)
        self.assertIsNotNone(handler.logger)
    
    def test_is_immediate_child_true(self):
        """Test _is_immediate_child returns True for immediate children"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        # File in watched directory
        file_path = str(self.temp_path / "test.txt")
        self.assertTrue(handler._is_immediate_child(file_path))
    
    def test_is_immediate_child_false(self):
        """Test _is_immediate_child returns False for subdirectory files"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        # File in subdirectory
        file_path = str(self.temp_path / "subdir" / "test.txt")
        self.assertFalse(handler._is_immediate_child(file_path))
    
    def test_get_filename(self):
        """Test _get_filename extracts filename correctly"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        file_path = str(self.temp_path / "test.txt")
        filename = handler._get_filename(file_path)
        
        self.assertEqual(filename, "test.txt")
    
    def test_on_created_file(self):
        """Test on_created handles file creation"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        # Create a mock event
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        event = MockEvent(str(self.temp_path / "test.txt"), False)
        handler.on_created(event)
        
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("created", "test.txt"))
    
    def test_on_created_directory_detected(self):
        """Test on_created detects directory creation in immediate directory"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        event = MockEvent(str(self.temp_path / "newdir"), True)
        handler.on_created(event)
        
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("created", "newdir"))
    
    def test_on_created_subdirectory_file_ignored(self):
        """Test on_created ignores files in subdirectories"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        event = MockEvent(str(self.temp_path / "subdir" / "test.txt"), False)
        handler.on_created(event)
        
        self.assertEqual(len(self.events_received), 0)
    
    def test_on_deleted_file(self):
        """Test on_deleted handles file deletion"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        event = MockEvent(str(self.temp_path / "test.txt"), False)
        handler.on_deleted(event)
        
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("deleted", "test.txt"))
    
    def test_on_modified_file(self):
        """Test on_modified handles file modification"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, is_directory):
                self.src_path = src_path
                self.is_directory = is_directory
        
        event = MockEvent(str(self.temp_path / "test.txt"), False)
        handler.on_modified(event)
        
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("modified", "test.txt"))
    
    def test_on_moved_rename_within_directory(self):
        """Test on_moved handles rename within watched directory"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, dest_path, is_directory):
                self.src_path = src_path
                self.dest_path = dest_path
                self.is_directory = is_directory
        
        event = MockEvent(
            str(self.temp_path / "old.txt"),
            str(self.temp_path / "new.txt"),
            False
        )
        handler.on_moved(event)
        
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("modified", "new.txt"))
    
    def test_on_moved_move_in(self):
        """Test on_moved handles file moved into watched directory"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, dest_path, is_directory):
                self.src_path = src_path
                self.dest_path = dest_path
                self.is_directory = is_directory
        
        # Move from subdirectory to watched directory
        event = MockEvent(
            str(self.temp_path / "subdir" / "test.txt"),
            str(self.temp_path / "test.txt"),
            False
        )
        handler.on_moved(event)
        
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("created", "test.txt"))
    
    def test_on_moved_move_out(self):
        """Test on_moved handles file moved out of watched directory"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, dest_path, is_directory):
                self.src_path = src_path
                self.dest_path = dest_path
                self.is_directory = is_directory
        
        # Move from watched directory to subdirectory
        event = MockEvent(
            str(self.temp_path / "test.txt"),
            str(self.temp_path / "subdir" / "test.txt"),
            False
        )
        handler.on_moved(event)
        
        self.assertEqual(len(self.events_received), 1)
        self.assertEqual(self.events_received[0], ("deleted", "test.txt"))
    
    def test_on_moved_within_subdirectory_ignored(self):
        """Test on_moved ignores moves within subdirectories"""
        handler = XeFMFileSystemEventHandler(self.event_callback, str(self.temp_path))
        
        class MockEvent:
            def __init__(self, src_path, dest_path, is_directory):
                self.src_path = src_path
                self.dest_path = dest_path
                self.is_directory = is_directory
        
        # Move within subdirectory
        event = MockEvent(
            str(self.temp_path / "subdir" / "old.txt"),
            str(self.temp_path / "subdir" / "new.txt"),
            False
        )
        handler.on_moved(event)
        
        self.assertEqual(len(self.events_received), 0)


if __name__ == '__main__':
    unittest.main()
