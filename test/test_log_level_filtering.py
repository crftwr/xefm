"""
Test log level filtering functionality.

Tests that log levels are correctly applied to loggers and that
messages are filtered based on the configured levels.

Run with: python -m pytest test/test_log_level_filtering.py -v
"""

import logging
from io import StringIO

from xefm.log_manager import LogManager, LoggingConfig


class MockConfig:
    """Mock configuration object for testing"""
    MAX_LOG_MESSAGES = 100


def test_default_log_level():
    """Test that default log level is applied to new loggers"""
    print("\n=== Test: Default Log Level ===")
    
    # Create LogManager with default level INFO
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Create a logger
    logger = log_manager.getLogger("TestLogger")
    
    # Verify default level is INFO
    assert logger.level == logging.INFO, f"Expected INFO level ({logging.INFO}), got {logger.level}"
    print(f"✓ Logger has default level INFO ({logging.INFO})")
    
    # Test that DEBUG messages are filtered out
    logger.debug("This should be filtered")
    logger.info("This should appear")
    
    print("✓ Default log level test passed")


def test_set_default_log_level():
    """Test changing the global default log level"""
    print("\n=== Test: Set Default Log Level ===")
    
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Change default level to DEBUG
    log_manager.set_default_log_level(logging.DEBUG)
    
    # Create a new logger - should have DEBUG level
    logger = log_manager.getLogger("DebugLogger")
    assert logger.level == logging.DEBUG, f"Expected DEBUG level ({logging.DEBUG}), got {logger.level}"
    print(f"✓ New logger has DEBUG level ({logging.DEBUG})")
    
    # Change default level to ERROR
    log_manager.set_default_log_level(logging.ERROR)
    
    # Create another logger - should have ERROR level
    logger2 = log_manager.getLogger("ErrorLogger")
    assert logger2.level == logging.ERROR, f"Expected ERROR level ({logging.ERROR}), got {logger2.level}"
    print(f"✓ New logger has ERROR level ({logging.ERROR})")
    
    # First logger should also be updated to ERROR (no per-logger override)
    assert logger.level == logging.ERROR, f"Expected first logger to be updated to ERROR ({logging.ERROR}), got {logger.level}"
    print(f"✓ Existing logger updated to ERROR level ({logging.ERROR})")
    
    print("✓ Set default log level test passed")


def test_per_logger_level_override():
    """Test per-logger level overrides"""
    print("\n=== Test: Per-Logger Level Override ===")
    
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Set default to INFO
    log_manager.set_default_log_level(logging.INFO)
    
    # Set per-logger override for "SpecialLogger" to DEBUG
    log_manager.set_logger_level("SpecialLogger", logging.DEBUG)
    
    # Create the special logger
    special_logger = log_manager.getLogger("SpecialLogger")
    assert special_logger.level == logging.DEBUG, f"Expected DEBUG level ({logging.DEBUG}), got {special_logger.level}"
    print(f"✓ Special logger has DEBUG level ({logging.DEBUG})")
    
    # Create a normal logger
    normal_logger = log_manager.getLogger("NormalLogger")
    assert normal_logger.level == logging.INFO, f"Expected INFO level ({logging.INFO}), got {normal_logger.level}"
    print(f"✓ Normal logger has INFO level ({logging.INFO})")
    
    # Change default to ERROR - special logger should keep DEBUG
    log_manager.set_default_log_level(logging.ERROR)
    assert special_logger.level == logging.DEBUG, f"Expected special logger to keep DEBUG ({logging.DEBUG}), got {special_logger.level}"
    print(f"✓ Special logger kept DEBUG level ({logging.DEBUG}) after default change")
    
    # Normal logger should be updated to ERROR
    assert normal_logger.level == logging.ERROR, f"Expected normal logger to be updated to ERROR ({logging.ERROR}), got {normal_logger.level}"
    print(f"✓ Normal logger updated to ERROR level ({logging.ERROR})")
    
    print("✓ Per-logger level override test passed")


def test_clear_logger_level_override():
    """Test clearing per-logger level overrides"""
    print("\n=== Test: Clear Logger Level Override ===")
    
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Set default to INFO
    log_manager.set_default_log_level(logging.INFO)
    
    # Set per-logger override to DEBUG
    log_manager.set_logger_level("TestLogger", logging.DEBUG)
    
    # Create logger
    logger = log_manager.getLogger("TestLogger")
    assert logger.level == logging.DEBUG, f"Expected DEBUG level ({logging.DEBUG}), got {logger.level}"
    print(f"✓ Logger has DEBUG level ({logging.DEBUG})")
    
    # Clear the override
    log_manager.clear_logger_level("TestLogger")
    
    # Logger should now use default (INFO)
    assert logger.level == logging.INFO, f"Expected INFO level ({logging.INFO}) after clearing override, got {logger.level}"
    print(f"✓ Logger reverted to INFO level ({logging.INFO}) after clearing override")
    
    print("✓ Clear logger level override test passed")


def test_get_logger_level():
    """Test getting effective log level for a logger"""
    print("\n=== Test: Get Logger Level ===")
    
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Set default to INFO
    log_manager.set_default_log_level(logging.INFO)
    
    # Get level for non-existent logger (should return default)
    level = log_manager.get_logger_level("NonExistent")
    assert level == logging.INFO, f"Expected INFO level ({logging.INFO}), got {level}"
    print(f"✓ Non-existent logger returns default level INFO ({logging.INFO})")
    
    # Set per-logger override
    log_manager.set_logger_level("SpecialLogger", logging.DEBUG)
    
    # Get level for logger with override
    level = log_manager.get_logger_level("SpecialLogger")
    assert level == logging.DEBUG, f"Expected DEBUG level ({logging.DEBUG}), got {level}"
    print(f"✓ Logger with override returns DEBUG level ({logging.DEBUG})")
    
    print("✓ Get logger level test passed")


def test_level_filtering_behavior():
    """Test that messages are actually filtered based on level"""
    print("\n=== Test: Level Filtering Behavior ===")
    
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Configure handlers to capture messages
    log_manager.configure_handlers(log_pane_enabled=True, stream_output_enabled=False)
    
    # Set default to WARNING
    log_manager.set_default_log_level(logging.WARNING)
    
    # Create logger
    logger = log_manager.getLogger("FilterTest")
    
    # Log messages at different levels
    logger.debug("Debug message - should be filtered")
    logger.info("Info message - should be filtered")
    logger.warning("Warning message - should appear")
    logger.error("Error message - should appear")
    
    # Check that only WARNING and ERROR messages appear
    # Note: We can't easily check the actual messages without accessing handler internals,
    # but we can verify the logger's level is set correctly
    assert logger.level == logging.WARNING, f"Expected WARNING level ({logging.WARNING}), got {logger.level}"
    print(f"✓ Logger level set to WARNING ({logging.WARNING})")
    
    # Verify isEnabledFor works correctly
    assert not logger.isEnabledFor(logging.DEBUG), "DEBUG should be disabled"
    assert not logger.isEnabledFor(logging.INFO), "INFO should be disabled"
    assert logger.isEnabledFor(logging.WARNING), "WARNING should be enabled"
    assert logger.isEnabledFor(logging.ERROR), "ERROR should be enabled"
    print("✓ isEnabledFor() correctly reflects level filtering")
    
    print("✓ Level filtering behavior test passed")


def test_pre_configured_logger_level():
    """Test setting level before logger is created"""
    print("\n=== Test: Pre-Configured Logger Level ===")
    
    config = MockConfig()
    log_manager = LogManager(config)
    
    # Set level for a logger that doesn't exist yet
    log_manager.set_logger_level("FutureLogger", logging.DEBUG)
    
    # Now create the logger
    logger = log_manager.getLogger("FutureLogger")
    
    # Should have the pre-configured level
    assert logger.level == logging.DEBUG, f"Expected DEBUG level ({logging.DEBUG}), got {logger.level}"
    print(f"✓ Pre-configured logger has DEBUG level ({logging.DEBUG})")
    
    print("✓ Pre-configured logger level test passed")


def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing Log Level Filtering")
    print("=" * 60)
    
    try:
        test_default_log_level()
        test_set_default_log_level()
        test_per_logger_level_override()
        test_clear_logger_level_override()
        test_get_logger_level()
        test_level_filtering_behavior()
        test_pre_configured_logger_level()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
