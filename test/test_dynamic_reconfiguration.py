"""
Test dynamic reconfiguration of handlers

Run with: python -m pytest test/test_dynamic_reconfiguration.py -v
"""

import logging

from xefm.log_manager import LogManager, LoggingConfig


class MockConfig:
    """Mock configuration object"""
    MAX_LOG_MESSAGES = 100


def test_configure_handlers_enables_log_pane():
    """Test that configure_handlers can enable log pane handler"""
    mock_config = MockConfig()
    # Start with the log pane disabled so we can exercise enabling it dynamically;
    # the default construction now creates the handler up front.
    log_manager = LogManager(mock_config, no_log_pane=True)

    # Initially, log pane handler should be None
    assert log_manager._log_pane_handler is None
    
    # Enable log pane
    log_manager.configure_handlers(log_pane_enabled=True)
    
    # Now log pane handler should exist
    assert log_manager._log_pane_handler is not None
    
    # Verify it's attached to stream logger
    assert log_manager._log_pane_handler in log_manager._stream_logger.handlers
    
    # Cleanup
    log_manager.restore_stdio()
    
    print("✓ configure_handlers can enable log pane handler")


def test_configure_handlers_disables_log_pane():
    """Test that configure_handlers can disable log pane handler"""
    mock_config = MockConfig()
    log_manager = LogManager(mock_config)
    
    # Enable log pane first
    log_manager.configure_handlers(log_pane_enabled=True)
    assert log_manager._log_pane_handler is not None
    
    # Now disable it
    log_manager.configure_handlers(log_pane_enabled=False)
    
    # Handler should be None
    assert log_manager._log_pane_handler is None
    
    # Cleanup
    log_manager.restore_stdio()
    
    print("✓ configure_handlers can disable log pane handler")


def test_configure_handlers_enables_stream_output():
    """Test that configure_handlers can enable stream output handler"""
    mock_config = MockConfig()
    log_manager = LogManager(mock_config)
    
    # Initially, stream output handler should be None
    assert log_manager._stream_output_handler is None
    
    # Enable stream output
    log_manager.configure_handlers(stream_output_enabled=True)
    
    # Now stream output handler should exist
    assert log_manager._stream_output_handler is not None
    
    # Verify it's attached to stream logger
    assert log_manager._stream_output_handler in log_manager._stream_logger.handlers
    
    # Cleanup
    log_manager.restore_stdio()
    
    print("✓ configure_handlers can enable stream output handler")


def test_configure_handlers_disables_stream_output():
    """Test that configure_handlers can disable stream output handler"""
    mock_config = MockConfig()
    log_manager = LogManager(mock_config)
    
    # Enable stream output first
    log_manager.configure_handlers(stream_output_enabled=True)
    assert log_manager._stream_output_handler is not None
    
    # Now disable it
    log_manager.configure_handlers(stream_output_enabled=False)
    
    # Handler should be None
    assert log_manager._stream_output_handler is None
    
    # Cleanup
    log_manager.restore_stdio()
    
    print("✓ configure_handlers can disable stream output handler")


def test_configure_handlers_attaches_to_existing_loggers():
    """Test that configure_handlers attaches handlers to existing loggers"""
    mock_config = MockConfig()
    log_manager = LogManager(mock_config, no_log_pane=True)
    
    # Create a logger before enabling handlers
    logger1 = log_manager.getLogger("TestLogger1")
    logger2 = log_manager.getLogger("TestLogger2")
    
    # Initially, loggers should have no handlers
    assert len(logger1.handlers) == 0
    assert len(logger2.handlers) == 0
    
    # Enable log pane handler
    log_manager.configure_handlers(log_pane_enabled=True)
    
    # Now both loggers should have the log pane handler
    assert log_manager._log_pane_handler in logger1.handlers
    assert log_manager._log_pane_handler in logger2.handlers
    
    # Cleanup
    log_manager.restore_stdio()
    
    print("✓ configure_handlers attaches handlers to existing loggers")


def test_configure_handlers_removes_from_existing_loggers():
    """Test that configure_handlers removes handlers from existing loggers"""
    mock_config = MockConfig()
    log_manager = LogManager(mock_config)
    
    # Enable log pane handler first
    log_manager.configure_handlers(log_pane_enabled=True)
    
    # Create loggers after enabling handler
    logger1 = log_manager.getLogger("TestLogger1")
    logger2 = log_manager.getLogger("TestLogger2")
    
    # Loggers should have the handler
    handler_before = log_manager._log_pane_handler
    assert handler_before in logger1.handlers
    assert handler_before in logger2.handlers
    
    # Disable log pane handler
    log_manager.configure_handlers(log_pane_enabled=False)
    
    # The old handler should be removed from loggers
    # Note: handler_before is the old handler instance
    assert handler_before not in logger1.handlers
    assert handler_before not in logger2.handlers
    
    # Cleanup
    log_manager.restore_stdio()
    
    print("✓ configure_handlers removes handlers from existing loggers")


def test_configure_handlers_multiple_changes():
    """Test that configure_handlers can handle multiple configuration changes"""
    mock_config = MockConfig()
    log_manager = LogManager(mock_config)
    
    # Enable both log pane and stream output
    log_manager.configure_handlers(log_pane_enabled=True, stream_output_enabled=True)
    
    assert log_manager._log_pane_handler is not None
    assert log_manager._stream_output_handler is not None
    
    # Create a logger
    logger = log_manager.getLogger("TestLogger")
    assert len(logger.handlers) == 2
    
    # Disable log pane, keep stream output
    log_manager.configure_handlers(log_pane_enabled=False)
    
    assert log_manager._log_pane_handler is None
    assert log_manager._stream_output_handler is not None
    assert len(logger.handlers) == 1
    
    # Re-enable log pane
    log_manager.configure_handlers(log_pane_enabled=True)
    
    assert log_manager._log_pane_handler is not None
    assert log_manager._stream_output_handler is not None
    assert len(logger.handlers) == 2
    
    # Cleanup
    log_manager.restore_stdio()
    
    print("✓ configure_handlers handles multiple configuration changes")


def test_getlogger_attaches_current_handlers():
    """Test that getLogger attaches currently configured handlers to new loggers"""
    mock_config = MockConfig()
    log_manager = LogManager(mock_config)
    
    # Enable log pane and stream output
    log_manager.configure_handlers(log_pane_enabled=True, stream_output_enabled=True)
    
    # Create a new logger
    logger = log_manager.getLogger("NewLogger")
    
    # Logger should have both handlers
    assert log_manager._log_pane_handler in logger.handlers
    assert log_manager._stream_output_handler in logger.handlers
    assert len(logger.handlers) == 2
    
    # Cleanup
    log_manager.restore_stdio()
    
    print("✓ getLogger attaches currently configured handlers to new loggers")
