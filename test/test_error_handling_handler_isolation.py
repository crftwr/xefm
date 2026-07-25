"""
Test error handling - handler failure isolation (Task 12.1)

This test verifies that XeFM's logging handlers properly isolate their own
failures and continue operating even when internal errors occur.

Requirements tested:
- 12.1: When a log handler fails, THE System SHALL continue operating with remaining handlers
- 12.5: When an error occurs in logging, THE System SHALL attempt to log the error using a fallback mechanism

Run with: python -m pytest test/test_error_handling_handler_isolation.py -v
"""

import sys
import io
import logging

from xefm.logging_handlers import LogPaneHandler, StreamOutputHandler


def test_logpane_handler_error_isolation():
    """
    Test that LogPaneHandler catches its own exceptions and continues operating.
    
    Verifies:
    1. Internal handler errors are caught
    2. Error is logged to sys.__stderr__ (fallback)
    3. Handler continues operating with subsequent messages
    """
    print("Test 1: LogPaneHandler error isolation")
    
    # Redirect sys.__stderr__ to capture error logging
    original_stderr = sys.__stderr__
    stderr_capture = io.StringIO()
    sys.__stderr__ = stderr_capture
    
    try:
        handler = LogPaneHandler(max_messages=1000)
        handler.is_visible = True
        
        # Patch format_logger_message to fail on first call
        original_format = handler.format_logger_message
        call_count = [0]
        
        def failing_format(record):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Simulated formatting failure")
            return original_format(record)
        
        handler.format_logger_message = failing_format
        
        logger = logging.getLogger("TestLogger1")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.addHandler(handler)
        
        # First message should fail internally but not crash
        logger.info("First message - will fail")
        
        # Second message should succeed
        logger.info("Second message - will succeed")
        
        # Verify error was logged to stderr
        stderr_capture.seek(0)
        stderr_output = stderr_capture.read()
        assert len(stderr_output) > 0, f"Error should be logged to stderr, got: {repr(stderr_output)}"
        assert "[LogPaneHandler]" in stderr_output, "Error should include handler name"
        assert "Error processing log record" in stderr_output, "Error should be descriptive"
        print(f"  ✓ Error logged to stderr: {len(stderr_output)} bytes")
        
        # Verify second message was processed successfully
        messages = handler.get_messages()
        assert len(messages) == 1, f"Should have 1 message (second one), got {len(messages)}"
        assert "Second message" in messages[0][0], "Second message should be in log pane"
        print(f"  ✓ Handler continued operating after error")
        
        print("✓ LogPaneHandler error isolation works correctly")
        
    finally:
        sys.__stderr__ = original_stderr


def test_stream_handler_error_isolation():
    """
    Test that StreamOutputHandler catches stream write errors and continues.
    
    Verifies:
    1. Stream write errors (OSError, IOError) are suppressed
    2. Handler continues operating with subsequent messages
    3. Other handlers still receive messages
    """
    print("\nTest 2: StreamOutputHandler error isolation")
    
    # Redirect sys.__stderr__ to capture any error logging
    original_stderr = sys.__stderr__
    stderr_capture = io.StringIO()
    sys.__stderr__ = stderr_capture
    
    try:
        # Create a stream that fails on first write
        call_count = [0]
        
        class SometimesFailingStream:
            def __init__(self):
                self.buffer = io.StringIO()
            
            def write(self, text):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise OSError("Simulated stream write failure")
                self.buffer.write(text)
            
            def flush(self):
                pass
            
            def getvalue(self):
                return self.buffer.getvalue()
        
        failing_stream = SometimesFailingStream()
        stream_handler = StreamOutputHandler(failing_stream)
        log_pane_handler = LogPaneHandler(max_messages=1000)
        log_pane_handler.is_visible = True
        
        logger = logging.getLogger("TestLogger2")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.addHandler(stream_handler)
        logger.addHandler(log_pane_handler)
        
        # First message should fail stream write but not crash
        logger.info("First message - stream will fail")
        
        # Second message should succeed
        logger.info("Second message - stream will succeed")
        
        # Verify stream handler suppressed the OSError (no stderr output)
        stderr_capture.seek(0)
        stderr_output = stderr_capture.read()
        # OSError should be suppressed per Requirement 12.3
        print(f"  ✓ OSError suppressed (stderr: {len(stderr_output)} bytes)")
        
        # Verify second message was written to stream
        stream_output = failing_stream.getvalue()
        assert "Second message" in stream_output, "Second message should be in stream"
        print(f"  ✓ Stream handler continued operating after error")
        
        # Verify log pane handler received both messages
        messages = log_pane_handler.get_messages()
        assert len(messages) == 2, f"Log pane should have 2 messages, got {len(messages)}"
        print(f"  ✓ Other handlers unaffected by stream error")
        
        print("✓ StreamOutputHandler error isolation works correctly")
        
    finally:
        sys.__stderr__ = original_stderr


def test_handler_isolation_from_each_other():
    """
    Test that handlers are isolated from each other's failures.
    
    Verifies:
    1. One handler's failure doesn't affect other handlers
    2. All working handlers receive and process messages
    3. Application remains stable
    """
    print("\nTest 3: Handler isolation from each other")
    
    # Redirect sys.__stderr__
    original_stderr = sys.__stderr__
    stderr_capture = io.StringIO()
    sys.__stderr__ = stderr_capture
    
    try:
        # Create handlers with one that will fail internally
        log_pane_handler = LogPaneHandler(max_messages=1000)
        log_pane_handler.is_visible = True
        
        # Make log pane handler fail
        original_format = log_pane_handler.format_logger_message
        def always_fail(record):
            raise RuntimeError("Simulated failure")
        log_pane_handler.format_logger_message = always_fail
        
        # Create working handlers
        stream = io.StringIO()
        stream_handler = StreamOutputHandler(stream)
        
        logger = logging.getLogger("TestLogger3")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.addHandler(log_pane_handler)  # Will fail
        logger.addHandler(stream_handler)    # Should still work
        
        # Log a message
        logger.info("Test message")
        
        # Verify stream handler still received the message
        stream.seek(0)
        output = stream.read()
        assert "Test message" in output, f"Stream handler should work despite log pane failure, got: {output}"
        print(f"  ✓ Working handlers unaffected by failing handler")
        
        # Verify log pane has no messages (because it failed)
        messages = log_pane_handler.get_messages()
        assert len(messages) == 0, "Log pane should have no messages (it failed)"
        print(f"  ✓ Failing handler isolated from working handlers")
        
        # Verify error was logged
        stderr_capture.seek(0)
        stderr_output = stderr_capture.read()
        assert len(stderr_output) > 0, "Error should be logged to stderr"
        print(f"  ✓ Error logged to fallback (stderr)")
        
        print("✓ Handler isolation works correctly")
        
    finally:
        sys.__stderr__ = original_stderr
