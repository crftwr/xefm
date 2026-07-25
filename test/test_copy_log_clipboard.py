#!/usr/bin/env python3
"""
Tests for Copy Log Pane Contents to Clipboard Feature

Tests the new functionality to copy log pane contents to clipboard,
including both visible logs and all logs.
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xefm.log_manager import LogManager, getLogger, set_log_manager
from xefm._config import Config


class MockRenderer:
    """Mock renderer for testing"""
    def __init__(self):
        self.clipboard_text = None
        self.clipboard_supported = True
        self.desktop_mode = True
    
    def supports_clipboard(self):
        return self.clipboard_supported
    
    def set_clipboard_text(self, text):
        self.clipboard_text = text
        return True
    
    def get_clipboard_text(self):
        return self.clipboard_text
    
    def is_desktop_mode(self):
        return self.desktop_mode


class TestCopyLogClipboard(unittest.TestCase):
    """Test log clipboard copy functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = Config()
        self.log_manager = LogManager(self.config, is_desktop_mode=True)
        set_log_manager(self.log_manager)
        self.renderer = MockRenderer()
    
    def test_get_all_log_text_empty(self):
        """Test getting all log text when no logs exist"""
        text = self.log_manager.get_all_log_text()
        self.assertEqual(text, "")
    
    def test_get_all_log_text_with_messages(self):
        """Test getting all log text with multiple messages"""
        logger = getLogger("Test")
        logger.info("Message 1")
        logger.info("Message 2")
        logger.info("Message 3")
        
        text = self.log_manager.get_all_log_text()
        
        # Should contain all three messages
        self.assertIn("Message 1", text)
        self.assertIn("Message 2", text)
        self.assertIn("Message 3", text)
        
        # Should have newlines between messages
        lines = text.split('\n')
        self.assertEqual(len(lines), 3)
    
    def test_get_visible_log_text_all_visible(self):
        """Test getting visible log text when all messages fit"""
        logger = getLogger("Test")
        logger.info("Message 1")
        logger.info("Message 2")
        logger.info("Message 3")
        
        # Display height larger than message count
        text = self.log_manager.get_visible_log_text(display_height=10)
        
        # Should contain all messages
        self.assertIn("Message 1", text)
        self.assertIn("Message 2", text)
        self.assertIn("Message 3", text)
    
    def test_get_visible_log_text_partial(self):
        """Test getting visible log text when only some messages fit"""
        logger = getLogger("Test")
        for i in range(10):
            logger.info(f"Message {i+1}")
        
        # Display height smaller than message count
        text = self.log_manager.get_visible_log_text(display_height=3)
        
        # Should contain only the last 3 messages (most recent)
        lines = text.split('\n')
        self.assertEqual(len(lines), 3)
        self.assertIn("Message 8", text)
        self.assertIn("Message 9", text)
        self.assertIn("Message 10", text)
    
    def test_get_visible_log_text_with_scroll(self):
        """Test getting visible log text with scroll offset"""
        logger = getLogger("Test")
        for i in range(10):
            logger.info(f"Message {i+1}")
        
        # Scroll up by 2 lines
        self.log_manager.scroll_log_up(2)
        
        # Display height of 3
        text = self.log_manager.get_visible_log_text(display_height=3)
        
        # Should show messages 6, 7, 8 (scrolled up from 8, 9, 10)
        lines = text.split('\n')
        self.assertEqual(len(lines), 3)
        self.assertIn("Message 6", text)
        self.assertIn("Message 7", text)
        self.assertIn("Message 8", text)
    
    def test_get_visible_log_text_zero_height(self):
        """Test getting visible log text with zero display height"""
        logger = getLogger("Test")
        logger.info("Message 1")
        
        text = self.log_manager.get_visible_log_text(display_height=0)
        self.assertEqual(text, "")
    
    def test_log_text_preserves_formatting(self):
        """Test that log text preserves timestamp and logger name formatting"""
        logger = getLogger("TestLog")
        logger.info("Test message")
        
        text = self.log_manager.get_all_log_text()
        
        # Should contain logger name
        self.assertIn("TestLog", text)
        # Should contain log level
        self.assertIn("INFO", text)
        # Should contain message
        self.assertIn("Test message", text)
    
    def test_log_text_different_levels(self):
        """Test that log text includes different log levels"""
        logger = getLogger("Test")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        text = self.log_manager.get_all_log_text()
        
        # Should contain all levels
        self.assertIn("INFO", text)
        self.assertIn("WARNING", text)
        self.assertIn("ERROR", text)


if __name__ == '__main__':
    unittest.main()
