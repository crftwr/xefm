"""
Test that log updates trigger redraws

Run with: python -m pytest test/test_log_redraw_trigger.py -v
"""

import sys
import unittest
import tempfile
import time
from unittest.mock import Mock, patch

from xefm.log_manager import LogManager, LogCapture

class TestLogRedrawTrigger(unittest.TestCase):
    """Test log update detection and redraw triggering"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Mock config
        self.mock_config = Mock()
        self.mock_config.MAX_LOG_MESSAGES = 100
    
    def test_log_manager_tracks_updates(self):
        """Test that LogManager tracks when new messages are added"""
        log_manager = LogManager(self.mock_config)
        
        # Initially no updates
        self.assertFalse(log_manager.has_log_updates())
        
        # Add a message directly
        log_manager.add_message("TEST", "Test message")
        
        # Should detect update
        self.assertTrue(log_manager.has_log_updates())
        
        # Mark as processed
        log_manager.mark_log_updates_processed()
        
        # Should no longer detect update
        self.assertFalse(log_manager.has_log_updates())
    
    def test_log_capture_triggers_updates(self):
        """Test that LogCapture triggers update notifications"""
        log_manager = LogManager(self.mock_config)
        
        # Initially no updates
        self.assertFalse(log_manager.has_log_updates())
        
        # Simulate stdout write (which goes through LogCapture)
        print("Test stdout message")
        
        # Should detect update
        self.assertTrue(log_manager.has_log_updates())
        
        # Mark as processed
        log_manager.mark_log_updates_processed()
        
        # Should no longer detect update
        self.assertFalse(log_manager.has_log_updates())
    
    def test_stderr_capture_triggers_updates(self):
        """Test that stderr capture also triggers update notifications"""
        log_manager = LogManager(self.mock_config)
        
        # Initially no updates
        self.assertFalse(log_manager.has_log_updates())
        
        # Simulate stderr write
        print("Test stderr message", file=sys.stderr)
        
        # Should detect update
        self.assertTrue(log_manager.has_log_updates())
        
        # Mark as processed
        log_manager.mark_log_updates_processed()
        
        # Should no longer detect update
        self.assertFalse(log_manager.has_log_updates())
    
    def test_startup_messages_trigger_updates(self):
        """Test that startup messages trigger update notifications"""
        log_manager = LogManager(self.mock_config)
        
        # Initially no updates (startup messages are added during init)
        # But let's clear the flag first
        log_manager.mark_log_updates_processed()
        self.assertFalse(log_manager.has_log_updates())
        
        # Add startup messages
        log_manager.add_startup_messages("1.0", "https://github.com/test", "Test App")
        
        # Should detect update
        self.assertTrue(log_manager.has_log_updates())
    
    def test_multiple_messages_tracked_correctly(self):
        """Test that multiple messages are tracked correctly"""
        log_manager = LogManager(self.mock_config)
        
        # Clear initial state
        log_manager.mark_log_updates_processed()
        self.assertFalse(log_manager.has_log_updates())
        
        # Add multiple messages
        log_manager.add_message("TEST1", "Message 1")
        self.assertTrue(log_manager.has_log_updates())
        
        log_manager.add_message("TEST2", "Message 2")
        self.assertTrue(log_manager.has_log_updates())
        
        # Mark as processed
        log_manager.mark_log_updates_processed()
        self.assertFalse(log_manager.has_log_updates())
        
        # Add another message
        log_manager.add_message("TEST3", "Message 3")
        self.assertTrue(log_manager.has_log_updates())
    
    # (Removed) test_log_capture_callback_mechanism and
    # test_empty_messages_dont_trigger_updates: LogCapture no longer takes a
    # (messages, source, ?, update_callback) tuple or drives an update callback —
    # it redirects stdout/stderr into the logging system, and update tracking is
    # done by LogManager.has_log_updates (covered by the tests above).


    def test_message_count_tracking(self):
        """Test that message count is tracked correctly"""
        log_manager = LogManager(self.mock_config)
        
        # Get initial count
        initial_count = len(log_manager.log_messages)
        log_manager.mark_log_updates_processed()
        
        # Add a message
        log_manager.add_message("TEST", "Message")
        
        # Count should have changed
        self.assertEqual(len(log_manager.log_messages), initial_count + 1)
        self.assertTrue(log_manager.has_log_updates())
        
        # Mark as processed
        log_manager.mark_log_updates_processed()
        self.assertFalse(log_manager.has_log_updates())
        
        # Count should be updated
        self.assertEqual(log_manager.last_message_count, len(log_manager.log_messages))
    
    def tearDown(self):
        """Clean up after tests"""
        # Restore original stdout/stderr if they were modified
        # This is handled by LogManager.__del__ but let's be explicit
        pass
