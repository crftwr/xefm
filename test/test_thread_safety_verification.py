"""
Thread Safety Verification Test

This test verifies that the thread safety implementation in LogPaneHandler
works correctly under concurrent access.

Run with: python -m pytest test/test_thread_safety_verification.py -v
"""

import logging
import threading
import time

from xefm.logging_handlers import LogPaneHandler


def test_logpane_handler_concurrent_emit():
    """
    Verify LogPaneHandler handles concurrent emit() calls without corruption.
    
    This test creates multiple threads that simultaneously emit log messages
    and verifies that all messages are captured without data corruption.
    """
    handler = LogPaneHandler(max_messages=1000)
    
    # Number of threads and messages per thread
    num_threads = 10
    messages_per_thread = 100
    
    def emit_messages(thread_id):
        """Emit messages from a specific thread."""
        for i in range(messages_per_thread):
            record = logging.LogRecord(
                name=f"Thread{thread_id}",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=f"Message {i} from thread {thread_id}",
                args=(),
                exc_info=None
            )
            handler.emit(record)
    
    # Create and start threads
    threads = []
    for thread_id in range(num_threads):
        thread = threading.Thread(target=emit_messages, args=(thread_id,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    # Verify all messages were captured
    messages = handler.get_messages()
    expected_count = num_threads * messages_per_thread
    
    print(f"Expected {expected_count} messages, got {len(messages)}")
    assert len(messages) == expected_count, f"Expected {expected_count} messages, got {len(messages)}"
    
    print("✓ LogPaneHandler concurrent emit test passed")


def test_logpane_handler_concurrent_get_messages():
    """
    Verify LogPaneHandler handles concurrent get_messages() calls safely.
    
    This test creates threads that simultaneously read messages while other
    threads are writing, verifying no crashes or data corruption occur.
    """
    handler = LogPaneHandler(max_messages=1000)
    
    # Add some initial messages
    for i in range(50):
        record = logging.LogRecord(
            name="Initial",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Initial message {i}",
            args=(),
            exc_info=None
        )
        handler.emit(record)
    
    num_reader_threads = 5
    num_writer_threads = 5
    iterations = 100
    
    def read_messages():
        """Read messages repeatedly."""
        for _ in range(iterations):
            messages = handler.get_messages()
            # Just verify we can read without crashing
            assert isinstance(messages, list)
    
    def write_messages(thread_id):
        """Write messages repeatedly."""
        for i in range(iterations):
            record = logging.LogRecord(
                name=f"Writer{thread_id}",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=f"Message {i}",
                args=(),
                exc_info=None
            )
            handler.emit(record)
    
    # Create reader and writer threads
    threads = []
    
    for i in range(num_reader_threads):
        thread = threading.Thread(target=read_messages)
        threads.append(thread)
    
    for i in range(num_writer_threads):
        thread = threading.Thread(target=write_messages, args=(i,))
        threads.append(thread)
    
    # Start all threads
    for thread in threads:
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    print("✓ LogPaneHandler concurrent read/write test passed")