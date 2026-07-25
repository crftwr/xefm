#!/usr/bin/env python3
"""
Test file logging functionality

Run with: python -m pytest test/test_file_logging.py -v
"""

import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock
from xefm.log_manager import LogManager


class TestFileLogging(unittest.TestCase):
    """Test file logging handler functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create a temporary file for logging
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log')
        self.temp_file.close()
        self.log_file_path = self.temp_file.name
        
        # Create mock config
        self.mock_config = Mock()
        self.mock_config.MAX_LOG_MESSAGES = 100
    
    def tearDown(self):
        """Clean up test fixtures"""
        # Remove temporary log file
        if os.path.exists(self.log_file_path):
            os.unlink(self.log_file_path)
    
    def test_file_logging_enabled(self):
        """Test that file logging is enabled when log_file is provided"""
        log_manager = LogManager(
            self.mock_config,
            is_desktop_mode=False,
            log_file=self.log_file_path
        )
        
        # Verify file logging handler is created
        self.assertIsNotNone(log_manager._file_logging_handler)
        self.assertEqual(log_manager._config.file_logging_enabled, True)
        self.assertEqual(log_manager._config.file_logging_path, self.log_file_path)
        
        # Clean up
        log_manager.restore_stdio()
    
    def test_file_logging_disabled(self):
        """Test that file logging is disabled when log_file is None"""
        log_manager = LogManager(
            self.mock_config,
            is_desktop_mode=False,
            log_file=None
        )
        
        # Verify file logging handler is not created
        self.assertIsNone(log_manager._file_logging_handler)
        self.assertEqual(log_manager._config.file_logging_enabled, False)
        
        # Clean up
        log_manager.restore_stdio()
    
    def test_file_logging_writes_messages(self):
        """Test that log messages are written to file"""
        log_manager = LogManager(
            self.mock_config,
            is_desktop_mode=False,
            log_file=self.log_file_path
        )
        
        # Get a logger and write some messages
        logger = log_manager.getLogger("TestLogger")
        logger.info("Test info message")
        logger.warning("Test warning message")
        logger.error("Test error message")
        
        # Close the file handler to flush
        log_manager._file_logging_handler.close()
        
        # Read the log file
        with open(self.log_file_path, 'r') as f:
            content = f.read()
        
        # Verify messages were written
        self.assertIn("Test info message", content)
        self.assertIn("Test warning message", content)
        self.assertIn("Test error message", content)
        self.assertIn("[TestLogger]", content)
        self.assertIn("INFO:", content)
        self.assertIn("WARNING:", content)
        self.assertIn("ERROR:", content)
        
        # Clean up
        log_manager.restore_stdio()
    
    def test_file_logging_with_stdout_stderr(self):
        """Test that stdout/stderr are also written to file"""
        log_manager = LogManager(
            self.mock_config,
            is_desktop_mode=False,
            log_file=self.log_file_path
        )
        
        # Write to stdout and stderr
        print("Test stdout message")
        print("Test stderr message", file=__import__('sys').stderr)
        
        # Close the file handler to flush
        log_manager._file_logging_handler.close()
        
        # Read the log file
        with open(self.log_file_path, 'r') as f:
            content = f.read()
        
        # Verify stdout/stderr were written (without formatting)
        self.assertIn("Test stdout message", content)
        self.assertIn("Test stderr message", content)
        
        # Clean up
        log_manager.restore_stdio()
    
    def test_file_logging_invalid_path(self):
        """Test that invalid file path is handled gracefully"""
        # Try to create log file in non-existent directory
        invalid_path = "/nonexistent/directory/test.log"
        
        # Should not raise exception
        log_manager = LogManager(
            self.mock_config,
            is_desktop_mode=False,
            log_file=invalid_path
        )
        
        # File handler should be created but file_handle should be None
        self.assertIsNotNone(log_manager._file_logging_handler)
        self.assertIsNone(log_manager._file_logging_handler.file_handle)
        
        # Clean up
        log_manager.restore_stdio()


if __name__ == '__main__':
    unittest.main()
