"""
Test performance optimizations for logging system.

Tests:
- Level checking before formatting (Requirement 11.1)
- Visibility checking for log pane (Requirement 11.3)
- Message retention limit (Requirement 11.4)

Run with: python -m pytest test/test_performance_optimizations.py -v
"""

import sys
import logging
import time
from collections import deque

from xefm.log_manager import LogManager, LoggingConfig
from xefm.logging_handlers import LogPaneHandler


def test_level_checking_before_formatting():
    """
    Test that level checking happens before expensive formatting.
    
    Requirement 11.1: When logging is disabled for a level, THE System SHALL
    skip message formatting.
    """
    print("Testing level checking before formatting...")
    
    # Create a simple config
    class SimpleConfig:
        MAX_LOG_MESSAGES = 100
    
    config = SimpleConfig()
    log_manager = LogManager(config)
    
    # Get a logger and set its level to WARNING (should skip DEBUG and INFO)
    logger = log_manager.getLogger("TestLogger")
    logger.setLevel(logging.WARNING)
    
    # Count messages before
    initial_count = len(log_manager._log_pane_handler.get_messages()) if log_manager._log_pane_handler else 0
    
    # Try to log DEBUG and INFO messages (should be skipped)
    logger.debug("This DEBUG message should be skipped")
    logger.info("This INFO message should be skipped")
    
    # Count messages after - should be the same
    after_skip_count = len(log_manager._log_pane_handler.get_messages()) if log_manager._log_pane_handler else 0
    
    assert after_skip_count == initial_count, f"Expected {initial_count} messages, got {after_skip_count}"
    # NOTE: no print() here — stdout is captured into the log pane, so a print
    # between the two counts would itself add a message and skew the assertion.

    # Re-read the count immediately before the warning to isolate its effect.
    before_warning_count = len(log_manager._log_pane_handler.get_messages()) if log_manager._log_pane_handler else 0

    # Now log a WARNING message (should be processed)
    logger.warning("This WARNING message should be processed")

    # Count messages after - should increase by exactly 1
    after_warning_count = len(log_manager._log_pane_handler.get_messages()) if log_manager._log_pane_handler else 0

    assert after_warning_count == before_warning_count + 1, f"Expected {before_warning_count + 1} messages, got {after_warning_count}"
    print(f"✓ WARNING message was processed (count increased to {after_warning_count})")
    
    # Verify the message content. Find our warning specifically — the print()
    # above is itself captured into the log pane, so it, not the warning, is the
    # last entry.
    messages = log_manager._log_pane_handler.get_messages()
    warning_msgs = [m for m, _ in messages
                    if m and "This WARNING message should be processed" in m]
    assert warning_msgs, "Warning message should be in the log pane"
    assert "WARNING" in warning_msgs[0], f"Expected WARNING level, got: {warning_msgs[0]}"
    print(f"✓ Message content verified: {warning_msgs[0]}")
    
    # Clean up
    log_manager.restore_stdio()
    
    print("✓ Level checking test passed\n")


def test_visibility_checking_for_log_pane():
    """
    Test that rendering operations are skipped when log pane is not visible.
    
    Requirement 11.3: When the log pane is not visible, THE System SHALL
    minimize rendering overhead.
    """
    print("Testing visibility checking for log pane...")
    
    # Create a simple config
    class SimpleConfig:
        MAX_LOG_MESSAGES = 100
    
    config = SimpleConfig()
    log_manager = LogManager(config)
    
    # Get a logger
    logger = log_manager.getLogger("TestLogger")
    
    # Set log pane as not visible
    log_manager.set_log_pane_visible(False)
    print("✓ Set log pane as not visible")
    
    # Log some messages while not visible
    logger.info("Message 1 while not visible")
    logger.warning("Message 2 while not visible")
    logger.error("Message 3 while not visible")
    
    # Get messages - they should be stored but unformatted (None in first element)
    messages = log_manager._log_pane_handler.messages
    unformatted_count = sum(1 for msg, _ in messages if msg is None)
    print(f"✓ {unformatted_count} messages stored unformatted while not visible")
    
    # Now set log pane as visible
    log_manager.set_log_pane_visible(True)
    print("✓ Set log pane as visible")
    
    # Get messages - they should be formatted now
    formatted_messages = log_manager._log_pane_handler.get_messages()
    all_formatted = all(msg is not None for msg, _ in formatted_messages)
    assert all_formatted, "Expected all messages to be formatted after becoming visible"
    print(f"✓ All {len(formatted_messages)} messages are now formatted")
    
    # Verify message content. Filter to the messages we logged — stdout is
    # captured into the log pane, so the test's own print() calls also appear as
    # entries and would otherwise shift a positional [-3:] slice.
    ours = [msg for msg, _ in formatted_messages if msg and "while not visible" in msg]
    assert len(ours) >= 3, f"Expected at least 3 of our messages, got {len(ours)}"
    assert "Message 1 while not visible" in ours[0]
    assert "Message 2 while not visible" in ours[1]
    assert "Message 3 while not visible" in ours[2]
    print("✓ Message content verified")
    
    # Clean up
    log_manager.restore_stdio()
    
    print("✓ Visibility checking test passed\n")


def test_message_retention_limit():
    """
    Test that oldest messages are discarded when limit is reached.
    
    Requirement 11.4: THE System SHALL limit the maximum number of stored
    log messages. When the limit is reached, oldest messages should be discarded.
    """
    print("Testing message retention limit...")
    
    # Create handler with small limit for testing
    max_messages = 10
    handler = LogPaneHandler(max_messages=max_messages)
    
    # Create logger and attach handler
    logger = logging.getLogger("TestRetention")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False
    
    # Add more messages than the limit
    num_messages = 20
    for i in range(num_messages):
        record = logging.LogRecord(
            name="TestRetention",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Message {i}",
            args=(),
            exc_info=None
        )
        record.is_stream_capture = False
        handler.emit(record)
    
    # Verify only max_messages are retained
    messages = handler.get_messages()
    assert len(messages) == max_messages, f"Expected {max_messages} messages, got {len(messages)}"
    print(f"✓ Message count capped at {max_messages}")
    
    # Verify oldest messages were discarded (should have messages 10-19)
    first_message = messages[0][0]
    last_message = messages[-1][0]
    
    assert "Message 10" in first_message, f"Expected 'Message 10' in first message, got: {first_message}"
    assert "Message 19" in last_message, f"Expected 'Message 19' in last message, got: {last_message}"
    print(f"✓ Oldest messages discarded correctly")
    print(f"  First message: {first_message}")
    print(f"  Last message: {last_message}")
    
    # Add one more message and verify it replaces the oldest
    record = logging.LogRecord(
        name="TestRetention",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Message 20",
        args=(),
        exc_info=None
    )
    record.is_stream_capture = False
    handler.emit(record)
    
    messages = handler.get_messages()
    assert len(messages) == max_messages, f"Expected {max_messages} messages, got {len(messages)}"
    
    first_message = messages[0][0]
    last_message = messages[-1][0]
    
    assert "Message 11" in first_message, f"Expected 'Message 11' in first message, got: {first_message}"
    assert "Message 20" in last_message, f"Expected 'Message 20' in last message, got: {last_message}"
    print(f"✓ New message replaced oldest correctly")
    print(f"  First message: {first_message}")
    print(f"  Last message: {last_message}")
    
    print("✓ Message retention limit test passed\n")


def test_deque_maxlen_behavior():
    """
    Verify that deque with maxlen automatically discards oldest items.
    
    This is a unit test to confirm the underlying data structure behavior.
    """
    print("Testing deque maxlen behavior...")
    
    # Create deque with maxlen
    max_size = 5
    d = deque(maxlen=max_size)
    
    # Add items up to limit
    for i in range(max_size):
        d.append(f"Item {i}")
    
    assert len(d) == max_size, f"Expected {max_size} items, got {len(d)}"
    assert list(d) == ["Item 0", "Item 1", "Item 2", "Item 3", "Item 4"]
    print(f"✓ Deque filled to limit: {list(d)}")
    
    # Add one more item - should discard oldest
    d.append("Item 5")
    
    assert len(d) == max_size, f"Expected {max_size} items, got {len(d)}"
    assert list(d) == ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5"]
    print(f"✓ Oldest item discarded: {list(d)}")
    
    # Add multiple items
    d.append("Item 6")
    d.append("Item 7")
    
    assert len(d) == max_size, f"Expected {max_size} items, got {len(d)}"
    assert list(d) == ["Item 3", "Item 4", "Item 5", "Item 6", "Item 7"]
    print(f"✓ Multiple oldest items discarded: {list(d)}")
    
    print("✓ Deque maxlen behavior test passed\n")
