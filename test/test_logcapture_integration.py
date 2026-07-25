"""
Integration test to verify LogCapture works with LogManager

Run with: python -m pytest test/test_logcapture_integration.py -v
"""

import sys
import logging
from collections import deque

from xefm.log_manager import LogManager


class MockConfig:
    """Mock configuration for testing"""
    MAX_LOG_MESSAGES = 100


def test_logmanager_with_logcapture():
    """Test that LogManager creates LogCapture with logger"""
    config = MockConfig()
    
    # Store original streams
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    # Create LogManager
    log_manager = LogManager(config)
    
    # Verify stdout and stderr are LogCapture instances
    assert hasattr(sys.stdout, 'logger')
    assert hasattr(sys.stderr, 'logger')
    
    # Verify they have the stream logger
    assert sys.stdout.logger is not None
    assert sys.stderr.logger is not None
    
    # Verify the stream logger is configured
    assert log_manager._stream_logger.name == "XEFM_STREAM_CAPTURE"
    assert log_manager._stream_logger.level == logging.DEBUG
    assert log_manager._stream_logger.propagate is False
    
    # Restore original streams
    log_manager.restore_stdio()
    
    # Now we can print
    print("✓ LogManager creates LogCapture with logger")


def test_print_still_works():
    """Test that print() still works after LogCapture modification"""
    config = MockConfig()
    
    # Create LogManager
    log_manager = LogManager(config)
    
    # Test print (should not crash)
    # Note: Since we don't have handlers attached yet, the message won't
    # appear in log_messages, but it should not crash
    print("Test message from print()")
    
    # Restore original streams
    log_manager.restore_stdio()
    
    # Now we can print
    print("✓ print() still works")


def test_getlogger_returns_logger():
    """Test that getLogger returns a logger instance"""
    config = MockConfig()
    
    # Create LogManager
    log_manager = LogManager(config)
    
    # Get a logger
    logger = log_manager.getLogger("Test")
    
    # Verify it's a Logger instance
    assert isinstance(logger, logging.Logger)
    assert logger.name == "Test"
    
    # Restore original streams
    log_manager.restore_stdio()
    
    # Now we can print
    print("✓ getLogger returns logger instance")
