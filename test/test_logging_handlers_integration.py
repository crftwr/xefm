"""
Integration tests for XeFM logging handlers
Verifies all requirements from Task 1

Run with: python -m pytest test/test_logging_handlers_integration.py -v
"""

import sys
import logging
import threading
import time

from xefm.logging_handlers import LogPaneHandler, StreamOutputHandler



def _entry_text(entry):
    """Message text from a (formatted, record) LogPaneHandler entry."""
    formatted, record = entry
    return formatted if formatted is not None else record.getMessage()


def test_requirement_1_1_deque_storage():
    """
    Requirement 1.1: LogPaneHandler stores messages in a deque
    """
    print("Testing Requirement 1.1: LogPaneHandler stores messages in a deque")
    
    handler = LogPaneHandler(max_messages=5)
    
    # Verify it's using a deque by checking maxlen behavior
    for i in range(10):
        record = logging.LogRecord(
            name="Test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Message {i}",
            args=(),
            exc_info=None
        )
        handler.emit(record)
    
    messages = handler.get_messages()
    
    # Should only have 5 messages (deque maxlen behavior)
    assert len(messages) == 5, f"Expected 5 messages, got {len(messages)}"
    
    # Should have messages 5-9 (oldest discarded)
    assert "Message 5" in _entry_text(messages[0])
    assert "Message 9" in _entry_text(messages[4])
    
    print("  ✓ LogPaneHandler correctly uses deque with maxlen")


def test_requirement_1_2_is_stream_capture_flag():
    """
    Requirement 1.2: All handlers implement is_stream_capture flag handling
    """
    print("Testing Requirement 1.2: is_stream_capture flag handling")
    
    # Test LogPaneHandler
    log_pane = LogPaneHandler()
    
    # Stream capture message
    stream_record = logging.LogRecord(
        name="STDOUT",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Raw output",
        args=(),
        exc_info=None
    )
    stream_record.is_stream_capture = True
    log_pane.emit(stream_record)
    
    # Logger message
    logger_record = logging.LogRecord(
        name="Logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Formatted output",
        args=(),
        exc_info=None
    )
    logger_record.is_stream_capture = False
    log_pane.emit(logger_record)
    
    messages = log_pane.get_messages()
    
    # Stream capture should be raw
    assert _entry_text(messages[0]) == "Raw output", "Stream capture not handled correctly"
    
    # Logger message should be formatted
    assert "INFO:" in _entry_text(messages[1]), "Logger message not formatted correctly"
    
    print("  ✓ LogPaneHandler handles is_stream_capture flag")
    
    # Test StreamOutputHandler
    import io
    stream = io.StringIO()
    stream_handler = StreamOutputHandler(stream)
    stream_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    
    stream_record2 = logging.LogRecord(
        name="STDOUT",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Raw stream",
        args=(),
        exc_info=None
    )
    stream_record2.is_stream_capture = True
    stream_handler.emit(stream_record2)
    
    output = stream.getvalue()
    # Should be raw, not formatted
    assert "Raw stream" in output
    assert "INFO:" not in output or output.strip() == "Raw stream"
    
    print("  ✓ StreamOutputHandler handles is_stream_capture flag")


def test_requirement_2_1_log_pane_routing():
    """
    Requirement 2.1: LogPaneHandler routes messages to log pane display
    """
    print("Testing Requirement 2.1: Messages routed to log pane")
    
    handler = LogPaneHandler()
    
    # Emit various types of messages
    for level in [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]:
        record = logging.LogRecord(
            name="TestLogger",
            level=level,
            pathname="",
            lineno=0,
            msg=f"Message at {logging.getLevelName(level)}",
            args=(),
            exc_info=None
        )
        handler.emit(record)
    
    messages = handler.get_messages()
    
    # All messages should be stored
    assert len(messages) == 5, f"Expected 5 messages, got {len(messages)}"
    
    # Verify all levels are present
    levels_found = [_entry_text(msg) for msg in messages]
    assert any("DEBUG:" in msg for msg in levels_found)
    assert any("INFO:" in msg for msg in levels_found)
    assert any("WARNING:" in msg for msg in levels_found)
    assert any("ERROR:" in msg for msg in levels_found)
    assert any("CRITICAL:" in msg for msg in levels_found)
    
    print("  ✓ All log levels routed to log pane correctly")


def test_requirement_3_5_original_streams():
    """
    Requirement 3.5: StreamOutputHandler uses sys.__stdout__ and sys.__stderr__
    """
    print("Testing Requirement 3.5: Original streams usage")
    
    # Test with sys.__stdout__
    import io
    stdout_capture = io.StringIO()
    
    # Temporarily replace sys.__stdout__ for testing
    original_stdout = sys.__stdout__
    sys.__stdout__ = stdout_capture
    
    try:
        handler = StreamOutputHandler(sys.__stdout__)
        
        record = logging.LogRecord(
            name="Test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        handler.emit(record)
        
        output = stdout_capture.getvalue()
        assert "Test message" in output, "Message not written to stream"
        
        print("  ✓ StreamOutputHandler correctly uses provided stream")
    finally:
        sys.__stdout__ = original_stdout


def test_thread_safety():
    """
    Verify thread safety of handlers
    """
    print("Testing thread safety of handlers")
    
    handler = LogPaneHandler()
    
    def emit_messages(thread_id, count):
        for i in range(count):
            record = logging.LogRecord(
                name=f"Thread{thread_id}",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=f"Message {i}",
                args=(),
                exc_info=None
            )
            handler.emit(record)
    
    # Create multiple threads
    threads = []
    for i in range(5):
        thread = threading.Thread(target=emit_messages, args=(i, 10))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join()
    
    messages = handler.get_messages()
    
    # Should have 50 messages total (5 threads * 10 messages)
    assert len(messages) == 50, f"Expected 50 messages, got {len(messages)}"
    
    print("  ✓ Handlers are thread-safe")
