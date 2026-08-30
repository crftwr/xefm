#!/usr/bin/env python3
"""
XeFM Logging Handlers - Custom handlers for Python's logging module

This module provides custom logging handlers that integrate Python's standard
logging framework with XeFM's unique requirements:
- LogPaneHandler: Routes messages to XeFM's visual log display
- StreamOutputHandler: Routes messages to original stdout/stderr streams
- FileLoggingHandler: Writes messages to a log file
"""

import sys
import threading
import logging
from datetime import datetime
from collections import deque
from typing import List, Tuple, Optional, Dict
from xefm.const import LOG_TIME_FORMAT


def should_format_record(record: logging.LogRecord) -> bool:
    """
    Determine if a log record should be formatted with timestamp.
    
    Formatting rules:
    - Logger API records (logger.info(), etc.): Always format with timestamp
    - stdout/stderr records (print(), subprocess output): Never format, output raw
    
    Args:
        record: Log record to check
        
    Returns:
        True if record should be formatted, False if raw output
    """
    # Check if this is a stream capture (stdout/stderr from print() or subprocess)
    # If is_stream_capture is True, it means the message came from stdout/stderr
    # and should be displayed as raw output without formatting
    return not getattr(record, 'is_stream_capture', False)


def format_logger_message(record: logging.LogRecord) -> str:
    """Format a logger record for the log pane.

    Returns:
        Formatted string: "HH:MM:SS [LoggerName] LEVEL: message"

    Module level so every route into the pane formats a record identically:
    :class:`LogPaneHandler` below, and the sink handler in
    :mod:`xefm.log_manager` that carries records to the running app's pane.
    """
    timestamp = datetime.fromtimestamp(record.created).strftime(LOG_TIME_FORMAT)
    # Pad logger name to 6 chars if shorter, keep as-is if longer
    logger_name = record.name.ljust(6) if len(record.name) < 6 else record.name
    return f"{timestamp} [{logger_name}] {record.levelname}: {record.getMessage()}"


class LogPaneHandler(logging.Handler):
    """
    Custom handler that stores log messages in a deque for display in XeFM's log pane.
    
    This handler distinguishes between:
    - Logger messages: Formatted with timestamp, logger name, level, and message
    - Stdout/stderr: Displayed as raw text without any formatting
    
    The distinction is made using the `is_stream_capture` attribute on LogRecord.
    """
    
    def __init__(self, max_messages: int = 1000):
        """
        Initialize log pane handler.
        
        Args:
            max_messages: Maximum messages to retain (oldest discarded when limit reached)
        """
        super().__init__()
        self.messages = deque(maxlen=max_messages)
        self.lock = threading.RLock()  # Use RLock to allow recursive acquisition
        self.is_visible = True  # Track whether log pane is visible (Requirement 11.3)
        
    def emit(self, record: logging.LogRecord):
        """
        Process a log record and add to display queue.
        
        Formatting is determined by record source:
        - Logger API: Format with timestamp, name, level, message
        - stdout/stderr: Display raw message without formatting (multi-line allowed)
        
        Error handling: All exceptions are caught and logged to sys.__stderr__
        to prevent logging failures from crashing the application. The handler
        continues operating with remaining handlers even if this one fails.
        
        Args:
            record: Log record to process
        """
        try:
            # Requirement 11.3: Performance optimization - skip rendering when not visible
            # Messages are still stored (for when pane becomes visible), but we skip
            # expensive formatting operations when the log pane is not visible
            if not self.is_visible:
                # Still store the record for later display, but skip formatting
                with self.lock:
                    # Store unformatted - will be formatted when pane becomes visible
                    self.messages.append((None, record))
                return
            
            with self.lock:
                if should_format_record(record):
                    # Logger API: format with timestamp, name, level, message
                    formatted = self.format_logger_message(record)
                    self.messages.append((formatted, record))
                else:
                    # stdout/stderr: display raw message without formatting
                    # Note: LogCapture already handles line buffering, so we receive
                    # complete lines here. No need to split on newlines again.
                    # Empty lines are meaningful output and should be preserved.
                    raw_message = record.getMessage()
                    self.messages.append((raw_message, record))
        except Exception as e:
            # Requirement 12.1: Handler failure isolation
            # Requirement 12.5: Log errors using fallback mechanism
            # Error isolation: Log to fallback (sys.__stderr__) and continue
            # This prevents handler failures from crashing the application
            try:
                sys.__stderr__.write(f"[LogPaneHandler] Error processing log record: {e}\n")
                sys.__stderr__.flush()
            except Exception:
                # Even fallback failed, but continue silently
                pass
    
    def format_logger_message(self, record: logging.LogRecord) -> str:
        """
        Format a logger message with full formatting.
        
        Args:
            record: Log record from a logger
            
        Returns:
            Formatted string: "HH:MM:SS [LoggerName] LEVEL: message"
        """
        return format_logger_message(record)
    
    def get_messages(self) -> List[Tuple[str, logging.LogRecord]]:
        """
        Get messages for display.
        
        Formats any unformatted messages (those added while pane was not visible).
        
        Returns:
            List of (formatted_message, record) tuples
        """
        with self.lock:
            # Format any unformatted messages (None in first element of tuple)
            formatted_messages = []
            for formatted_msg, record in self.messages:
                if formatted_msg is None:
                    # Format the message now
                    if should_format_record(record):
                        # Logger API: format with timestamp
                        formatted = self.format_logger_message(record)
                        formatted_messages.append((formatted, record))
                    else:
                        # stdout/stderr: display raw message
                        # Note: LogCapture already handles line buffering
                        # Empty lines are meaningful output and should be preserved.
                        raw_message = record.getMessage()
                        formatted_messages.append((raw_message, record))
                else:
                    formatted_messages.append((formatted_msg, record))
            return formatted_messages
    
    def set_visible(self, visible: bool):
        """
        Set whether the log pane is visible.
        
        When set to False, formatting operations are skipped for performance.
        Messages are still stored and will be formatted when pane becomes visible.
        
        Args:
            visible: True if log pane is visible, False otherwise
        """
        self.is_visible = visible
    
    def get_color_for_record(self, record: logging.LogRecord) -> Tuple[int, int]:
        """
        Determine color pair and attributes for a log record.
        
        For logger messages: Uses record.levelno to determine color
        For stdout/stderr: Uses record.name ("STDOUT"/"STDERR") to determine color
        
        Args:
            record: Log record
            
        Returns:
            (color_pair, attributes) tuple
        """
        # Import here to avoid circular dependency
        from xefm.colors import get_log_color, COLOR_ERROR, COLOR_LOG_WARNING, TextAttribute

        # Check if this is a stream capture (stdout/stderr) or logger message
        if not should_format_record(record):
            # For stdout/stderr: use record.name ("STDOUT"/"STDERR") to determine color
            return get_log_color(record.name)
        else:
            # For logger messages: use record.levelno to determine color
            # Map log levels to colors:
            # DEBUG (10) -> STDOUT color (gray)
            # INFO (20) -> STDOUT color (gray)
            # WARNING (30) -> WARNING color (orange)
            # ERROR (40) -> ERROR color (red)
            # CRITICAL (50) -> ERROR color (red)
            
            if record.levelno >= logging.ERROR:  # ERROR (40) or CRITICAL (50)
                return COLOR_ERROR, TextAttribute.NORMAL
            elif record.levelno >= logging.WARNING:  # WARNING (30)
                return COLOR_LOG_WARNING, TextAttribute.NORMAL
            else:  # DEBUG (10) or INFO (20)
                return get_log_color("STDOUT")


class StreamOutputHandler(logging.Handler):
    """
    Custom handler that writes log messages to original stdout/stderr streams.
    
    This handler respects the record source:
    - Logger messages: Written with full formatting (timestamp, name, level, message)
    - Stdout/stderr: Written as raw text without any formatting
    """
    
    def __init__(self, stream):
        """
        Initialize stream output handler.
        
        Args:
            stream: Output stream (sys.__stdout__ or sys.__stderr__)
        """
        super().__init__()
        self.stream = stream
        self.lock = threading.RLock()  # Use RLock to allow recursive acquisition
        
    def emit(self, record: logging.LogRecord):
        """
        Write log record to stream.
        
        Formatting is determined by record source:
        - Logger API: Write with full formatting (timestamp, name, level, message)
        - stdout/stderr: Write raw message without any formatting (multi-line allowed)
        
        Error handling: Stream write failures (OSError, IOError) are suppressed
        to prevent logging from crashing the application. Other exceptions are
        logged to fallback. The handler continues operating with remaining
        handlers even if this one fails.
        
        Args:
            record: Log record to write
        """
        try:
            with self.lock:
                if should_format_record(record):
                    # Logger API: write with full formatting
                    timestamp = datetime.fromtimestamp(record.created).strftime(LOG_TIME_FORMAT)
                    formatted = f"{timestamp} [{record.name}] {record.levelname}: {record.getMessage()}"
                    self.stream.write(formatted + '\n')
                else:
                    # stdout/stderr: write raw message without any formatting
                    msg = record.getMessage()
                    self.stream.write(msg)
                    if not msg.endswith('\n'):
                        self.stream.write('\n')
                self.stream.flush()
        except (OSError, IOError):
            # Requirement 12.3: Stream write failure suppression
            # Suppress stream write errors to prevent logging from crashing application
            pass
        except Exception as e:
            # Requirement 12.1: Handler failure isolation
            # Requirement 12.5: Log errors using fallback mechanism
            # Log unexpected errors to fallback stream
            try:
                sys.__stderr__.write(f"[StreamOutputHandler] Error writing to stream: {e}\n")
                sys.__stderr__.flush()
            except:
                # Even fallback failed, silently continue
                pass


class FileLoggingHandler(logging.Handler):
    """
    Custom handler that writes log messages to a file.
    
    This handler:
    - Writes formatted messages to a specified file
    - Handles file I/O errors gracefully
    - Formats messages consistently with other handlers
    """
    
    def __init__(self, filename: str):
        """
        Initialize file logging handler.
        
        Args:
            filename: Path to log file
        """
        super().__init__()
        self.filename = filename
        self.file_handle = None
        self.lock = threading.RLock()
        
        # Open file for writing (append mode)
        try:
            self.file_handle = open(filename, 'a', encoding='utf-8')
        except (OSError, IOError) as e:
            # Log error to fallback stream
            try:
                sys.__stderr__.write(f"[FileLoggingHandler] Failed to open log file '{filename}': {e}\n")
                sys.__stderr__.flush()
            except:
                pass
    
    def emit(self, record: logging.LogRecord):
        """
        Write log record to file.
        
        Formatting is determined by record source:
        - Logger API: Write with full formatting (timestamp, name, level, message)
        - stdout/stderr: Write raw message without any formatting
        
        Error handling: File write failures are logged to fallback stream.
        The handler continues operating with remaining handlers even if this one fails.
        
        Args:
            record: Log record to write
        """
        if self.file_handle is None:
            return
        
        try:
            with self.lock:
                if should_format_record(record):
                    # Logger API: write with full formatting
                    timestamp = datetime.fromtimestamp(record.created).strftime(LOG_TIME_FORMAT)
                    formatted = f"{timestamp} [{record.name}] {record.levelname}: {record.getMessage()}"
                    self.file_handle.write(formatted + '\n')
                else:
                    # stdout/stderr: write raw message without any formatting
                    msg = record.getMessage()
                    self.file_handle.write(msg)
                    if not msg.endswith('\n'):
                        self.file_handle.write('\n')
                self.file_handle.flush()
        except (OSError, IOError) as e:
            # File write error - log to fallback stream
            try:
                sys.__stderr__.write(f"[FileLoggingHandler] Error writing to log file: {e}\n")
                sys.__stderr__.flush()
            except:
                pass
        except Exception as e:
            # Unexpected error - log to fallback stream
            try:
                sys.__stderr__.write(f"[FileLoggingHandler] Unexpected error: {e}\n")
                sys.__stderr__.flush()
            except:
                pass
    
    def close(self):
        """Close the log file."""
        with self.lock:
            if self.file_handle is not None:
                try:
                    self.file_handle.close()
                except Exception:
                    pass
                self.file_handle = None
        super().close()
