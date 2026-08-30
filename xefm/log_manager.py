#!/usr/bin/env python3
"""
XeFM Log Manager - Handles logging and log display functionality
"""

import sys
import threading
import logging
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional
from xefm.const import LOG_TIME_FORMAT, MAX_LOG_MESSAGES
from xefm.colors import get_log_color, get_status_color
from xefm.logging_handlers import (FileLoggingHandler, LogPaneHandler,
                                   StreamOutputHandler, format_logger_message,
                                   should_format_record)


@dataclass
class LoggingConfig:
    """Configuration for logging system."""
    
    # Log pane settings
    log_pane_enabled: bool = True
    max_log_messages: int = 1000
    
    # Stream output settings
    stream_output_enabled: Optional[bool] = None  # None = auto-detect based on mode
    stream_output_desktop_default: bool = True
    stream_output_terminal_default: bool = False
    
    # File logging settings
    file_logging_enabled: bool = False
    file_logging_path: Optional[str] = None
    
    # Log level settings
    default_log_level: int = logging.INFO
    logger_levels: Dict[str, int] = field(default_factory=dict)
    
    # Format settings
    timestamp_format: str = "%H:%M:%S"
    message_format: str = "%(asctime)s [%(name)s] %(message)s"


class LogCapture:
    """Capture stdout/stderr and redirect to log pane with line buffering"""
    def __init__(self, source, original_stream=None, is_desktop_mode=False, logger=None):
        self.source = source
        self.original_stream = original_stream
        self.is_desktop_mode = is_desktop_mode  # Only write to original streams in desktop mode
        self.logger = logger  # Logger instance for routing through handler pipeline
        self.buffer = ""  # Line buffer - accumulates text until newline
        self.lock = threading.RLock()  # Thread safety for buffer access
        
    def write(self, text):
        with self.lock:
            # Add text to buffer
            self.buffer += text
            
            # Process complete lines (split on newlines)
            while '\n' in self.buffer:
                line, self.buffer = self.buffer.split('\n', 1)
                
                # Emit all lines, including empty ones (empty lines are meaningful output)
                self._emit_log_record(line)
    
    def _emit_log_record(self, text):
        """Emit a single log record for the given text"""
        # Route through logging infrastructure
        # INFO for stdout, WARNING for stderr
        level = logging.INFO if self.source == "STDOUT" else logging.WARNING
        
        # Requirement 11.1: Performance optimization - check if level is enabled
        # Skip expensive LogRecord creation and formatting if level is disabled
        if not self.logger.isEnabledFor(level):
            return
        
        # Create LogRecord - preserve raw text without stripping or modifying
        record = logging.LogRecord(
            name=self.source,  # "STDOUT" or "STDERR"
            level=level,
            pathname="",
            lineno=0,
            msg=text,  # Raw text, not stripped or modified
            args=(),
            exc_info=None
        )
        
        # CRITICAL: Mark this as a stream capture (not a formatted logger message)
        # Handlers will check this flag to determine formatting behavior
        record.is_stream_capture = True
        
        # Route through the logger's handler pipeline
        self.logger.handle(record)
    
    def flush(self):
        # flush() is called to ensure buffered data is written
        # However, we should NOT emit incomplete lines (lines without newline)
        # The buffer will be emitted when a newline is eventually received
        # This matches standard stream behavior where flush() doesn't add newlines
        pass


class LogManager:
    """Manages logging system and log display"""
    
    def __init__(self, config, is_desktop_mode=False, log_file=None, no_log_pane=False):
        # Log scroll state
        self.log_scroll_offset = 0
        
        # Track log updates for redraw triggering
        self.has_new_messages = False
        self.last_message_count = 0
        
        # Logger caching - stores created loggers by name
        self._loggers = {}
        
        # Create a root logger for stream capture routing
        # This logger will be used by LogCapture to route stdout/stderr through the handler pipeline
        self._stream_logger = logging.getLogger("XEFM_STREAM_CAPTURE")
        self._stream_logger.setLevel(logging.DEBUG)  # Accept all levels
        self._stream_logger.propagate = False
        
        # Store configuration for handler management
        max_log_messages = config.MAX_LOG_MESSAGES
        self._config = LoggingConfig()
        self._config.max_log_messages = max_log_messages
        # Enable stream output in desktop mode, disable in terminal mode
        self._config.stream_output_enabled = is_desktop_mode
        # Configure file logging
        self._config.file_logging_enabled = log_file is not None
        self._config.file_logging_path = log_file
        # Configure log pane (disabled if no_log_pane is True)
        self._config.log_pane_enabled = not no_log_pane
        
        # Log level configuration
        # Global default level (defaults to INFO)
        self._default_log_level = logging.INFO
        # Per-logger level overrides (logger_name -> level)
        self._logger_levels = {}
        
        # Handler instances
        self._log_pane_handler = None
        self._stream_output_handler = None
        self._file_logging_handler = None
        
        # Store desktop mode flag
        self.is_desktop_mode = is_desktop_mode
        
        # Store original streams
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
        # Redirect stdout and stderr
        sys.stdout = LogCapture("STDOUT", self.original_stdout, is_desktop_mode, logger=self._stream_logger)
        sys.stderr = LogCapture("STDERR", self.original_stderr, is_desktop_mode, logger=self._stream_logger)
        
        # Initialize handlers based on configuration
        # This creates the LogPaneHandler by default unless no_log_pane is True
        self.configure_handlers()
    
    def configure_handlers(self,
                          log_pane_enabled: Optional[bool] = None,
                          stream_output_enabled: Optional[bool] = None):
        """
        Configure which handlers are active.
        Supports dynamic reconfiguration without restart.
        
        Args:
            log_pane_enabled: Enable log pane display (None = keep current)
            stream_output_enabled: Enable original stream output (None = keep current)
        """
        # Update configuration
        if log_pane_enabled is not None:
            self._config.log_pane_enabled = log_pane_enabled
        if stream_output_enabled is not None:
            self._config.stream_output_enabled = stream_output_enabled

        # Configure log pane handler
        if self._config.log_pane_enabled:
            if self._log_pane_handler is None:
                # Create new handler
                self._log_pane_handler = LogPaneHandler(max_messages=self._config.max_log_messages)
                # Add to stream logger
                if self._log_pane_handler not in self._stream_logger.handlers:
                    self._stream_logger.addHandler(self._log_pane_handler)
                # Add to all existing loggers
                for logger in self._loggers.values():
                    if self._log_pane_handler not in logger.handlers:
                        logger.addHandler(self._log_pane_handler)
        else:
            if self._log_pane_handler is not None:
                # Remove from stream logger
                if self._log_pane_handler in self._stream_logger.handlers:
                    self._stream_logger.removeHandler(self._log_pane_handler)
                # Remove from all existing loggers
                for logger in self._loggers.values():
                    if self._log_pane_handler in logger.handlers:
                        logger.removeHandler(self._log_pane_handler)
                self._log_pane_handler = None
        
        # Configure stream output handler
        if self._config.stream_output_enabled:
            if self._stream_output_handler is None:
                # Create new handler
                self._stream_output_handler = StreamOutputHandler(self.original_stdout)
                # Add to stream logger
                if self._stream_output_handler not in self._stream_logger.handlers:
                    self._stream_logger.addHandler(self._stream_output_handler)
                # Add to all existing loggers
                for logger in self._loggers.values():
                    if self._stream_output_handler not in logger.handlers:
                        logger.addHandler(self._stream_output_handler)
        else:
            if self._stream_output_handler is not None:
                # Remove from stream logger
                if self._stream_output_handler in self._stream_logger.handlers:
                    self._stream_logger.removeHandler(self._stream_output_handler)
                # Remove from all existing loggers
                for logger in self._loggers.values():
                    if self._stream_output_handler in logger.handlers:
                        logger.removeHandler(self._stream_output_handler)
                self._stream_output_handler = None
        
        # Configure file logging handler
        if self._config.file_logging_enabled:
            if self._file_logging_handler is None and self._config.file_logging_path:
                # Create new handler
                self._file_logging_handler = FileLoggingHandler(self._config.file_logging_path)
                # Add to stream logger
                if self._file_logging_handler not in self._stream_logger.handlers:
                    self._stream_logger.addHandler(self._file_logging_handler)
                # Add to all existing loggers
                for logger in self._loggers.values():
                    if self._file_logging_handler not in logger.handlers:
                        logger.addHandler(self._file_logging_handler)
        else:
            if self._file_logging_handler is not None:
                # Close the file
                self._file_logging_handler.close()
                # Remove from stream logger
                if self._file_logging_handler in self._stream_logger.handlers:
                    self._stream_logger.removeHandler(self._file_logging_handler)
                # Remove from all existing loggers
                for logger in self._loggers.values():
                    if self._file_logging_handler in logger.handlers:
                        logger.removeHandler(self._file_logging_handler)
                self._file_logging_handler = None
    
    def _configure_pending_logger(self, name: str, logger: logging.Logger):
        """
        Configure a pending logger with handlers.
        
        This is called by set_log_manager() to attach handlers to loggers
        that were created before LogManager initialization.
        
        Args:
            name: Logger name
            logger: Logger instance to configure
        """
        # Set level based on configuration
        # Check for per-logger override first, then use default
        if name in self._logger_levels:
            logger.setLevel(self._logger_levels[name])
        else:
            logger.setLevel(self._default_log_level)
        
        # Attach configured handlers based on current configuration
        if self._log_pane_handler is not None:
            logger.addHandler(self._log_pane_handler)
        if self._stream_output_handler is not None:
            logger.addHandler(self._stream_output_handler)
        if self._file_logging_handler is not None:
            logger.addHandler(self._file_logging_handler)
        
        # Cache the logger
        self._loggers[name] = logger
    
    def getLogger(self, name: str) -> logging.Logger:
        """
        Get or create a logger with XeFM handlers configured.
        
        Returns existing logger if name was already used. This ensures that
        multiple calls with the same name return the same Logger instance.
        
        XeFM creates multiple loggers for different purposes:
        - "Main": Main application logging
        - "FileOp": File operation logging
        - "DirDiff": Directory diff viewer logging
        - "Archive": Archive operations logging
        - etc.
        
        Args:
            name: Logger name (e.g., "Main", "FileOp", "DirDiff")
            
        Returns:
            Configured logging.Logger instance (existing or newly created)
        """
        # Return cached logger if it exists
        if name in self._loggers:
            return self._loggers[name]
        
        # Create new logger using Python's standard logging
        logger = logging.getLogger(name)
        
        # Set level based on configuration
        # Check for per-logger override first, then use default
        if name in self._logger_levels:
            logger.setLevel(self._logger_levels[name])
        else:
            logger.setLevel(self._default_log_level)
        
        # Prevent propagation to root logger to avoid duplicate messages
        logger.propagate = False
        
        # Attach configured handlers based on current configuration
        if self._log_pane_handler is not None:
            logger.addHandler(self._log_pane_handler)
        if self._stream_output_handler is not None:
            logger.addHandler(self._stream_output_handler)
        if self._file_logging_handler is not None:
            logger.addHandler(self._file_logging_handler)
        
        # Cache the logger
        self._loggers[name] = logger
        
        return logger
    
    def set_default_log_level(self, level: int):
        """
        Set the global default log level for all loggers.
        
        This affects all loggers that don't have a per-logger override.
        Existing loggers without overrides will be updated to the new level.
        
        Args:
            level: Log level (logging.DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self._default_log_level = level
        
        # Update existing loggers that don't have per-logger overrides
        for name, logger in self._loggers.items():
            if name not in self._logger_levels:
                logger.setLevel(level)
    
    def set_logger_level(self, logger_name: str, level: int):
        """
        Set the log level for a specific logger (per-logger override).
        
        This overrides the global default level for the specified logger.
        If the logger already exists, its level is updated immediately.
        If the logger doesn't exist yet, the override is stored and will
        be applied when the logger is created.
        
        Args:
            logger_name: Name of the logger to configure
            level: Log level (logging.DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self._logger_levels[logger_name] = level
        
        # Update existing logger if it exists
        if logger_name in self._loggers:
            self._loggers[logger_name].setLevel(level)
    
    def get_logger_level(self, logger_name: str) -> int:
        """
        Get the effective log level for a logger.
        
        Returns the per-logger override if set, otherwise the default level.
        
        Args:
            logger_name: Name of the logger
            
        Returns:
            Log level (logging.DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        return self._logger_levels.get(logger_name, self._default_log_level)
    
    def clear_logger_level(self, logger_name: str):
        """
        Clear the per-logger level override for a specific logger.
        
        After clearing, the logger will use the global default level.
        If the logger exists, its level is updated to the default immediately.
        
        Args:
            logger_name: Name of the logger to clear override for
        """
        if logger_name in self._logger_levels:
            del self._logger_levels[logger_name]
            
            # Update existing logger to use default level
            if logger_name in self._loggers:
                self._loggers[logger_name].setLevel(self._default_log_level)
    
    def set_log_pane_visible(self, visible: bool):
        """
        Set whether the log pane is visible.
        
        When set to False, the LogPaneHandler skips expensive formatting operations
        for performance. Messages are still stored and will be formatted when the
        pane becomes visible again.
        
        Args:
            visible: True if log pane is visible, False otherwise
        """
        if self._log_pane_handler is not None:
            self._log_pane_handler.set_visible(visible)
    
    @property
    def log_pane_handler(self):
        """Get the log pane handler instance."""
        return self._log_pane_handler
    
    @property
    def stream_output_handler(self):
        """Get the stream output handler instance."""
        return self._stream_output_handler
    
    def has_log_updates(self):
        """Check if there are new log messages since last check"""
        if self._log_pane_handler is None:
            return False
        current_count = len(self._log_pane_handler.messages)
        if current_count != self.last_message_count or self.has_new_messages:
            return True
        return False
    
    def mark_log_updates_processed(self):
        """Mark that log updates have been processed (redraw completed)"""
        if self._log_pane_handler is None:
            return
        self.has_new_messages = False
        self.last_message_count = len(self._log_pane_handler.messages)
    
    def add_message(self, source, message):
        """
        Add a message directly to the log (backward compatibility method).
        
        This method maintains backward compatibility with existing code that uses
        add_message() instead of getLogger(). Messages are routed through the
        new logging infrastructure to ensure consistent handling.
        
        Args:
            source: Message source identifier (e.g., "System", "Config", "FileOp")
            message: Message text
        """
        # Route through logging infrastructure for consistent handling
        # Create a LogRecord with appropriate level based on source
        # Use INFO level for most sources, WARNING for error-related sources
        if source.upper() in ("ERROR", "STDERR"):
            level = logging.WARNING
        else:
            level = logging.INFO
        
        # Requirement 11.1: Performance optimization - check if level is enabled
        # Skip expensive LogRecord creation if level is disabled
        if not self._stream_logger.isEnabledFor(level):
            return
        
        # Create LogRecord
        record = logging.LogRecord(
            name=source,  # Use source as logger name
            level=level,
            pathname="",
            lineno=0,
            msg=message,
            args=(),
            exc_info=None
        )
        
        # Mark this as NOT a stream capture (it's a direct log message)
        # This ensures it gets formatted like a logger message, not stdout/stderr
        record.is_stream_capture = False
        
        # Route through the stream logger's handler pipeline
        # This ensures the message goes through all configured handlers
        # (LogPaneHandler, StreamOutputHandler, FileLoggingHandler)
        self._stream_logger.handle(record)
    
    def add_startup_messages(self, version, github_url, app_name):
        """
        Add startup messages directly to log pane.
        
        Routes through logging infrastructure for consistent handling.
        
        Args:
            version: Application version string
            github_url: GitHub repository URL
            app_name: Application name
        """
        # Use add_message() which now routes through logging infrastructure
        self.add_message("System", f"XeFM {version}")
        self.add_message("System", f"GitHub: {github_url}")
        self.add_message("System", f"{app_name} started successfully")
        self.add_message("Config", "Configuration loaded")
    
    def get_log_scroll_percentage(self, display_height=None):
        """Calculate the current log scroll position as a percentage"""
        total_messages = len(self._log_pane_handler.messages)
        
        if total_messages <= 1:
            return 0
        
        # Calculate max scroll based on display height if available
        if display_height is not None:
            max_scroll = max(0, total_messages - display_height)
        else:
            # Fallback to conservative estimate
            max_scroll = max(0, total_messages - 1)
        
        if max_scroll == 0:
            return 0
        
        # Calculate percentage
        percentage = (self.log_scroll_offset / max_scroll) * 100
        return max(0, min(100, percentage))
    
    def scroll_log_up(self, lines=1):
        """Scroll log up by specified number of lines (toward older messages)"""
        total_messages = len(self._log_pane_handler.messages)
        
        if total_messages > 0:
            # Allow scrolling up to the total number of messages
            # The draw method will cap this properly based on display height
            self.log_scroll_offset += lines
            return True
        return False
    
    def scroll_log_down(self, lines=1):
        """Scroll log down by specified number of lines (toward newer messages)"""
        if self.log_scroll_offset > 0:
            self.log_scroll_offset = max(0, self.log_scroll_offset - lines)
            return True
        return False
    
    @property
    def log_messages(self):
        """Live view of captured messages — the pane handler's ``(formatted,
        record)`` deque. Backward-compatible accessor supporting ``len()``,
        indexing, and ``clear()`` on the underlying store."""
        return self._log_pane_handler.messages if self._log_pane_handler else []

    def get_log_messages(self):
        """
        Get all log messages as a list of formatted strings (backward compatibility).

        This method is provided for backward compatibility with tests that expect
        a simple list of message strings. In production, messages are accessed
        through the handler's get_messages() method which returns (formatted, record) tuples.
        
        Returns:
            List of formatted message strings
        """
        # Get messages from handler and extract just the formatted strings
        handler_messages = self._log_pane_handler.get_messages()
        return [formatted_msg for formatted_msg, record in handler_messages]
    
    def get_visible_log_text(self, display_height):
        """
        Get visible log lines as text for clipboard copy.
        
        Returns the currently visible log lines based on scroll position,
        with line wrapping applied as it appears on screen.
        
        Args:
            display_height: Number of lines visible in the log pane
            
        Returns:
            String containing visible log lines (one per line)
        """
        if self._log_pane_handler is None or display_height <= 0:
            return ""
        
        # Get all messages
        handler_messages = self._log_pane_handler.get_messages()
        total_messages = len(handler_messages)
        
        if total_messages == 0:
            return ""
        
        # For clipboard copy, we don't need to wrap - just get the visible messages
        # Calculate which messages are visible based on scroll offset
        max_scroll = max(0, total_messages - display_height)
        scroll_offset = min(self.log_scroll_offset, max_scroll)
        
        start_idx = max(0, total_messages - display_height - scroll_offset)
        end_idx = min(total_messages, start_idx + display_height)
        
        visible_messages = handler_messages[start_idx:end_idx]
        
        # Extract formatted text from tuples
        lines = [formatted_msg for formatted_msg, record in visible_messages]
        
        return '\n'.join(lines)
    
    def get_all_log_text(self):
        """
        Get all log lines as text for clipboard copy.
        
        Returns all log messages including those not currently visible.
        
        Returns:
            String containing all log lines (one per line)
        """
        if self._log_pane_handler is None:
            return ""
        
        # Get all messages
        handler_messages = self._log_pane_handler.get_messages()
        
        if not handler_messages:
            return ""
        
        # Extract formatted text from tuples
        lines = [formatted_msg for formatted_msg, record in handler_messages]
        
        return '\n'.join(lines)
    
    def _wrap_line(self, text, width):
        """
        Wrap a single line of text to fit within the specified width.
        
        Args:
            text: Text to wrap
            width: Maximum width per line
            
        Returns:
            List of wrapped lines
        """
        if len(text) <= width:
            return [text]
        
        wrapped = []
        while text:
            if len(text) <= width:
                wrapped.append(text)
                break
            else:
                # Split at width
                wrapped.append(text[:width])
                text = text[width:]
        
        return wrapped

    def restore_stdio(self):
        """Restore stdout/stderr to original state"""
        if hasattr(self, 'original_stdout') and sys.stdout != self.original_stdout:
            sys.stdout = self.original_stdout
        if hasattr(self, 'original_stderr') and sys.stderr != self.original_stderr:
            sys.stderr = self.original_stderr
    
    def __del__(self):
        """Cleanup when object is destroyed"""
        # Close file logging handler if active
        if hasattr(self, '_file_logging_handler') and self._file_logging_handler:
            self._file_logging_handler.close()
        
        # Restore stdout/stderr
        self.restore_stdio()


# Module-level singleton instance
_log_manager_instance: Optional[LogManager] = None

# Pending loggers dictionary - stores loggers created before LogManager initialization
# Key: logger name, Value: logger instance
_pending_loggers: Dict[str, logging.Logger] = {}


# --------------------------------------------------------------------------- #
# Log sink - the route from every XeFM logger to the running app's log pane.
#
# XeFM does not build a LogManager in production (it is exercised by the tests
# only), so without this every logger returned below would be handler-less:
# Python then falls back to ``logging.lastResort``, which drops everything under
# WARNING and writes the rest, unformatted, to ``sys.stderr``. That silently
# discarded every ``logger.info`` in the codebase, and under the GUI backends -
# where a Windows GUI-subsystem process has no stderr at all - discarded the
# warnings and errors too.
#
# Instead a single handler is attached to every logger the moment it is created,
# formats each record like the log pane's own handler, and hands the line to the
# installed sink. Until an app installs one - the whole of module import, config
# loading and app construction happens before the log pane exists - lines are
# buffered and replayed on install, so a startup diagnostic reaches the pane
# instead of vanishing.
# --------------------------------------------------------------------------- #

#: Log-pane source tags for records carried by the sink, mirroring the "STDOUT" /
#: "STDERR" tags of captured streams: the app maps them to a style.
LOG_SOURCE = "LOG"
LOG_ERROR_SOURCE = "LOGERR"

#: Ceiling on lines held before a sink is installed. Startup produces a few dozen;
#: this only bounds a process that logs heavily and never opens a log pane.
_EARLY_LINE_LIMIT = 1000

_log_sink: Optional[Callable[[str, str], None]] = None
_early_lines: deque = deque(maxlen=_EARLY_LINE_LIMIT)
#: Guards _log_sink and _early_lines together, so a record emitted on a worker
#: thread is either buffered or delivered - never dropped between the two - and
#: replay stays in order. Reentrant: the sink runs under it and must tolerate a
#: (mis)behaving handler logging from the same thread.
_sink_lock = threading.RLock()


class _LogSinkHandler(logging.Handler):
    """Carries every record to the installed sink, buffering until there is one.

    Failures are swallowed the way a logging handler must be: a broken log pane
    may not take down a file manager mid-operation."""

    def emit(self, record: logging.LogRecord):
        try:
            line = (format_logger_message(record) if should_format_record(record)
                    else record.getMessage())
            source = (LOG_ERROR_SOURCE if record.levelno >= logging.WARNING
                      else LOG_SOURCE)
            with _sink_lock:
                if _log_sink is None:
                    _early_lines.append((source, line))
                    # No pane yet, so keep lastResort's safety net: a warning or
                    # error still reaches a terminal if there is one behind us
                    # (there is none in a GUI-subsystem process, hence the guard).
                    if record.levelno >= logging.WARNING and sys.stderr is not None:
                        sys.stderr.write(line + "\n")
                    return
                _log_sink(source, line)
        except Exception:
            pass


#: The one handler instance shared by every logger, so attaching it is cheap and
#: removing it (see set_log_manager) is exact.
_sink_handler = _LogSinkHandler()


def set_log_sink(sink: Callable[[str, str], None]) -> None:
    """Route log records to ``sink(source, line)`` and replay what was buffered.

    Called by the app once its log pane and drain queue exist. ``source`` is
    :data:`LOG_SOURCE` or :data:`LOG_ERROR_SOURCE`; ``line`` is fully formatted.
    The sink is called from whichever thread logged, so it must be thread-safe -
    the app's is a queue put picked up by the UI thread's pump."""
    global _log_sink
    with _sink_lock:
        _log_sink = sink
        # Under the lock, so a record logged on a worker thread right now lands
        # after the backlog rather than in the middle of it.
        while _early_lines:
            source, line = _early_lines.popleft()
            try:
                sink(source, line)
            except Exception:
                pass


def clear_log_sink() -> None:
    """Stop routing to the installed sink and go back to buffering.

    Called when the app tears its streams down, so a shutdown message does not
    reach a log pane that is no longer being drawn."""
    global _log_sink
    with _sink_lock:
        _log_sink = None


def set_log_manager(log_manager: Optional[LogManager]):
    """
    Set the global LogManager instance.
    
    This should be called once during application initialization.
    When called, all pending loggers will have their handlers attached.
    
    Passing None removes it again and leaves getLogger() to the log sink, which
    is how XeFM itself runs. A caller that installs a manager and does not take
    it back out redirects every logger in the process for good — including the
    ones a later, unrelated caller creates.
    
    Args:
        log_manager: The LogManager instance to use globally, or None to remove
    """
    global _log_manager_instance
    _log_manager_instance = log_manager
    if log_manager is None:
        return
    
    # Attach handlers to all pending loggers
    for name, logger in _pending_loggers.items():
        # The LogManager owns this logger's handlers from here on; drop the sink
        # handler so records are not reported through both routes at once.
        if _sink_handler in logger.handlers:
            logger.removeHandler(_sink_handler)
        # Configure the pending logger with handlers
        _log_manager_instance._configure_pending_logger(name, logger)
    
    # Clear pending loggers dictionary since they're now configured
    _pending_loggers.clear()


def getLogger(name: str) -> logging.Logger:
    """
    Get or create a logger with XeFM handlers configured.
    
    This is a module-level function that can be called without a LogManager instance.
    If a LogManager has been set via set_log_manager(), it will use that instance.
    Otherwise - which is the case throughout XeFM itself - it creates a "pending"
    logger handled by the log sink above, so its records reach the app's log pane
    (or wait in the early buffer for one) rather than being dropped.

    Pending loggers are stored in a dictionary so that multiple calls with the same
    name return the same logger instance, ensuring consistency.
    
    Args:
        name: Logger name (e.g., "Main", "FileOp", "Archive")
        
    Returns:
        Configured logging.Logger instance (or pending logger if LogManager not yet initialized)
    """
    if _log_manager_instance is not None:
        return _log_manager_instance.getLogger(name)
    else:
        # No LogManager available yet - create or return pending logger
        if name in _pending_loggers:
            # Return existing pending logger
            return _pending_loggers[name]
        
        # Create new pending logger, handled by the sink until (and unless) a
        # LogManager takes it over. Without it the logger would be handler-less,
        # and everything below WARNING would be dropped by logging.lastResort.
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)  # Default level, will be updated when LogManager is created
        logger.propagate = False
        logger.addHandler(_sink_handler)
        
        # Store in pending loggers dictionary
        _pending_loggers[name] = logger
        
        return logger
