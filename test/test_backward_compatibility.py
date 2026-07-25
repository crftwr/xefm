"""
Test backward compatibility of add_message() routing through logging infrastructure.

This test verifies that the legacy add_message() method correctly routes messages
through the new logging infrastructure, ensuring consistent handling with logger messages.

Run with: python -m pytest test/test_backward_compatibility.py -v
"""

import sys
import logging
from collections import deque

from xefm.log_manager import LogManager, LoggingConfig


class MockConfig:
    """Mock configuration for testing"""
    MAX_LOG_MESSAGES = 1000


def test_add_message_routes_through_logging():
    """Test that add_message() routes through logging infrastructure"""
    print("\n=== Test: add_message() routes through logging infrastructure ===")
    
    # Create LogManager with log pane enabled, no remote monitoring
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Verify LogPaneHandler is created
    assert log_manager._log_pane_handler is not None, "LogPaneHandler should be created"
    
    # Add a message using the legacy method
    log_manager.add_message("TEST", "Test message via add_message")
    
    # Verify message appears in LogPaneHandler
    messages = log_manager._log_pane_handler.get_messages()
    assert len(messages) > 0, "Message should appear in LogPaneHandler"
    
    # Find our test message
    found = False
    for formatted_msg, record in messages:
        if "Test message via add_message" in formatted_msg:
            found = True
            # Verify it's formatted as a logger message (not stream capture)
            assert not getattr(record, 'is_stream_capture', False), \
                "add_message() should create logger messages, not stream captures"
            # Verify source is preserved in logger name
            assert record.name == "TEST", f"Logger name should be 'TEST', got '{record.name}'"
            # Verify level is INFO (default for non-error sources)
            assert record.levelno == logging.INFO, \
                f"Level should be INFO ({logging.INFO}), got {record.levelno}"
            print(f"✓ Message found with correct formatting: {formatted_msg}")
            break
    
    assert found, "Test message should be found in handler messages"
    
    # Clean up
    log_manager.restore_stdio()
    print("✓ Test passed: add_message() routes through logging infrastructure")


def test_add_message_error_source_uses_warning_level():
    """Test that add_message() with ERROR source uses WARNING level"""
    print("\n=== Test: add_message() with ERROR source uses WARNING level ===")
    
    # Create LogManager
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Add an error message
    log_manager.add_message("ERROR", "This is an error message")
    
    # Verify message uses WARNING level
    messages = log_manager._log_pane_handler.get_messages()
    found = False
    for formatted_msg, record in messages:
        if "This is an error message" in formatted_msg:
            found = True
            assert record.levelno == logging.WARNING, \
                f"ERROR source should use WARNING level, got {record.levelno}"
            print(f"✓ Error message uses WARNING level: {formatted_msg}")
            break
    
    assert found, "Error message should be found"
    
    # Clean up
    log_manager.restore_stdio()
    print("✓ Test passed: ERROR source uses WARNING level")


def test_add_message_reaches_all_handlers():
    """Test that add_message() reaches all configured handlers"""
    print("\n=== Test: add_message() reaches all configured handlers ===")
    
    # Create LogManager with stream output enabled (desktop mode enables the
    # stream-output handler that echoes to the original stdout/stderr).
    config = MockConfig()
    log_manager = LogManager(config, is_desktop_mode=True)

    # Verify both handlers are created
    assert log_manager._log_pane_handler is not None, "LogPaneHandler should be created"
    assert log_manager._stream_output_handler is not None, "StreamOutputHandler should be created"
    print("✓ Both handlers created")
    
    # Verify handlers are attached to stream logger
    assert log_manager._log_pane_handler in log_manager._stream_logger.handlers, \
        "LogPaneHandler should be attached to stream logger"
    assert log_manager._stream_output_handler in log_manager._stream_logger.handlers, \
        "StreamOutputHandler should be attached to stream logger"
    print("✓ Handlers attached to stream logger")
    
    # Add a message
    log_manager.add_message("MULTI", "Message to all handlers")
    
    # Verify message in LogPaneHandler
    messages = log_manager._log_pane_handler.get_messages()
    found_in_pane = any("Message to all handlers" in msg[0] for msg in messages)
    assert found_in_pane, "Message should appear in LogPaneHandler"
    print("✓ Message found in LogPaneHandler")
    
    # Verify the message was processed by checking the record
    for formatted_msg, record in messages:
        if "Message to all handlers" in formatted_msg:
            # Verify it's a logger message (not stream capture)
            assert not getattr(record, 'is_stream_capture', False), \
                "add_message() should create logger messages"
            # Verify it went through the stream logger
            assert record.name == "MULTI", "Source should be preserved as logger name"
            print("✓ Message correctly routed through logging infrastructure")
            break
    
    # Clean up
    log_manager.restore_stdio()
    print("✓ Test passed: add_message() reaches all handlers")


def test_add_startup_messages_uses_add_message():
    """Test that add_startup_messages() uses add_message() internally"""
    print("\n=== Test: add_startup_messages() uses add_message() ===")
    
    # Create LogManager
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Add startup messages
    log_manager.add_startup_messages("1.0.0", "https://github.com/test/repo", "TestApp")
    
    # Verify all startup messages appear in LogPaneHandler
    messages = log_manager._log_pane_handler.get_messages()
    
    expected_messages = [
        "XeFM 1.0.0",
        "GitHub: https://github.com/test/repo",
        "TestApp started successfully",
        "Configuration loaded"
    ]
    
    for expected in expected_messages:
        found = any(expected in msg[0] for msg in messages)
        assert found, f"Startup message '{expected}' should be found"
        print(f"✓ Found startup message: {expected}")
    
    # Verify they're formatted as logger messages
    for formatted_msg, record in messages:
        if any(expected in formatted_msg for expected in expected_messages):
            assert not getattr(record, 'is_stream_capture', False), \
                "Startup messages should be logger messages, not stream captures"
    
    # Clean up
    log_manager.restore_stdio()
    print("✓ Test passed: add_startup_messages() uses add_message()")


def test_backward_compatibility_with_existing_code():
    """Test that existing code patterns continue to work"""
    print("\n=== Test: Backward compatibility with existing code patterns ===")
    
    # Create LogManager
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Simulate existing code patterns
    log_manager.add_message("FileOp", "File copied successfully")
    log_manager.add_message("DirDiff", "Comparison complete")
    log_manager.add_message("Archive", "Archive extracted")
    log_manager.add_message("SYSTEM", "Operation completed")
    
    # Verify all messages appear
    messages = log_manager._log_pane_handler.get_messages()
    
    expected_sources = ["FileOp", "DirDiff", "Archive", "SYSTEM"]
    for source in expected_sources:
        found = any(record.name == source for _, record in messages)
        assert found, f"Message from source '{source}' should be found"
        print(f"✓ Found message from source: {source}")
    
    # Clean up
    log_manager.restore_stdio()
    print("✓ Test passed: Backward compatibility maintained")
