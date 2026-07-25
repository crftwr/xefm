"""
Tests for XeFM logging handlers

Run with: python -m pytest test/test_logging_handlers.py -v
"""

import logging
import time
from datetime import datetime

from xefm.logging_handlers import LogPaneHandler, StreamOutputHandler



def _entry_text(entry):
    """Message text from a (formatted, record) LogPaneHandler entry."""
    formatted, record = entry
    return formatted if formatted is not None else record.getMessage()


def test_log_pane_handler_basic():
    """Test basic LogPaneHandler functionality"""
    handler = LogPaneHandler(max_messages=10)
    
    # Create a logger message (not stream capture)
    record = logging.LogRecord(
        name="TestLogger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Test message",
        args=(),
        exc_info=None
    )
    record.is_stream_capture = False
    
    handler.emit(record)
    messages = handler.get_messages()
    
    assert len(messages) == 1
    source, message = messages[0][1].name, _entry_text(messages[0])
    assert source == "TestLogger"
    assert "INFO: Test message" in message
    print("✓ LogPaneHandler basic test passed")


def test_log_pane_handler_stream_capture():
    """Test LogPaneHandler with stream capture (stdout/stderr)"""
    handler = LogPaneHandler(max_messages=10)
    
    # Create a stream capture message
    record = logging.LogRecord(
        name="STDOUT",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Raw stdout output",
        args=(),
        exc_info=None
    )
    record.is_stream_capture = True
    
    handler.emit(record)
    messages = handler.get_messages()
    
    assert len(messages) == 1
    source, message = messages[0][1].name, _entry_text(messages[0])
    assert source == "STDOUT"
    assert message == "Raw stdout output"
    print("✓ LogPaneHandler stream capture test passed")


def test_log_pane_handler_multiline():
    """Test LogPaneHandler with multi-line stream capture"""
    handler = LogPaneHandler(max_messages=10)
    
    # Create a multi-line stream capture message
    record = logging.LogRecord(
        name="STDERR",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="Line 1\nLine 2\nLine 3",
        args=(),
        exc_info=None
    )
    record.is_stream_capture = True
    
    handler.emit(record)
    messages = handler.get_messages()
    
    # Stream output is kept as a single multi-line message (rendered across
    # lines in the pane) rather than split into one entry per line.
    assert len(messages) == 1
    text = _entry_text(messages[0])
    assert "Line 1" in text and "Line 2" in text and "Line 3" in text
    print("✓ LogPaneHandler multi-line test passed")


def test_log_pane_handler_max_messages():
    """Test LogPaneHandler message retention limit"""
    handler = LogPaneHandler(max_messages=3)
    
    # Add 5 messages
    for i in range(5):
        record = logging.LogRecord(
            name="TestLogger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Message {i}",
            args=(),
            exc_info=None
        )
        record.is_stream_capture = False
        handler.emit(record)
    
    messages = handler.get_messages()
    
    # Should only have 3 messages (oldest discarded)
    assert len(messages) == 3
    # Should have messages 2, 3, 4 (0 and 1 were discarded)
    assert "Message 2" in _entry_text(messages[0])
    assert "Message 3" in _entry_text(messages[1])
    assert "Message 4" in _entry_text(messages[2])
    print("✓ LogPaneHandler max messages test passed")


def test_stream_output_handler_logger_message():
    """Test StreamOutputHandler with logger message"""
    import io
    stream = io.StringIO()
    handler = StreamOutputHandler(stream)
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    
    # Create a logger message
    record = logging.LogRecord(
        name="TestLogger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Test message",
        args=(),
        exc_info=None
    )
    record.is_stream_capture = False
    
    handler.emit(record)
    output = stream.getvalue()
    
    assert "INFO: Test message" in output
    print("✓ StreamOutputHandler logger message test passed")


def test_stream_output_handler_stream_capture():
    """Test StreamOutputHandler with stream capture"""
    import io
    stream = io.StringIO()
    handler = StreamOutputHandler(stream)
    
    # Create a stream capture message
    record = logging.LogRecord(
        name="STDOUT",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Raw output",
        args=(),
        exc_info=None
    )
    record.is_stream_capture = True
    
    handler.emit(record)
    output = stream.getvalue()
    
    # Should be raw output without formatting
    assert output.strip() == "Raw output"
    print("✓ StreamOutputHandler stream capture test passed")


def test_is_stream_capture_flag():
    """Test that is_stream_capture flag is properly handled"""
    handler = LogPaneHandler(max_messages=10)
    
    # Test with flag set to True
    record1 = logging.LogRecord(
        name="STDOUT",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Stream output",
        args=(),
        exc_info=None
    )
    record1.is_stream_capture = True
    handler.emit(record1)
    
    # Test with flag set to False
    record2 = logging.LogRecord(
        name="Logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Logger output",
        args=(),
        exc_info=None
    )
    record2.is_stream_capture = False
    handler.emit(record2)
    
    # Test with flag missing (should default to False)
    record3 = logging.LogRecord(
        name="Logger2",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Default output",
        args=(),
        exc_info=None
    )
    # Don't set is_stream_capture
    handler.emit(record3)
    
    messages = handler.get_messages()
    assert len(messages) == 3
    
    # First should be raw stream output
    assert messages[0][1].name == "STDOUT"
    assert _entry_text(messages[0]) == "Stream output"
    
    # Second should be formatted logger output
    assert messages[1][1].name == "Logger"
    assert "INFO: Logger output" in _entry_text(messages[1])
    
    # Third should be formatted logger output (default)
    assert messages[2][1].name == "Logger2"
    assert "INFO: Default output" in _entry_text(messages[2])
    
    print("✓ is_stream_capture flag test passed")
