#!/usr/bin/env python3
"""
Unit tests for file monitoring configuration.

Tests configuration loading, default values, and validation logic.
"""

import unittest
import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xefm.config import ConfigManager


class TestFileMonitoringConfig(unittest.TestCase):
    """Test file monitoring configuration schema and validation"""

    def setUp(self):
        """Set up test fixtures"""
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load_config()

    def test_default_values(self):
        """Test that default configuration values are set correctly"""
        # Test enabled flag
        self.assertTrue(hasattr(self.config, 'FILE_MONITORING_ENABLED'))
        self.assertEqual(self.config.FILE_MONITORING_ENABLED, True)

        # Test coalesce delay
        self.assertTrue(hasattr(self.config, 'FILE_MONITORING_COALESCE_DELAY_MS'))
        self.assertEqual(self.config.FILE_MONITORING_COALESCE_DELAY_MS, 200)

        # Test max reloads per second
        self.assertTrue(hasattr(self.config, 'FILE_MONITORING_MAX_RELOADS_PER_SECOND'))
        self.assertEqual(self.config.FILE_MONITORING_MAX_RELOADS_PER_SECOND, 5)

        # Test fallback poll interval
        self.assertTrue(hasattr(self.config, 'FILE_MONITORING_FALLBACK_POLL_INTERVAL_S'))
        self.assertEqual(self.config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S, 5)

    def test_validation_enabled_boolean(self):
        """Test validation of FILE_MONITORING_ENABLED as boolean"""
        # Create a mock config with invalid enabled value
        class MockConfig:
            FILE_MONITORING_ENABLED = "true"  # String instead of boolean
            FILE_MONITORING_COALESCE_DELAY_MS = 200
            FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
            FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5
            MONO_FONT_NAME = 'Menlo'
            FONT_SIZE = 12
            DEFAULT_LEFT_PANE_RATIO = 0.5
            DEFAULT_LOG_HEIGHT_RATIO = 0.25
            DEFAULT_SORT_MODE = 'name'

        errors = self.config_manager.validate_config(MockConfig())
        self.assertIn("FILE_MONITORING_ENABLED must be a boolean", errors)

    def test_validation_coalesce_delay_non_negative(self):
        """Test validation of FILE_MONITORING_COALESCE_DELAY_MS as non-negative integer"""
        # Create a mock config with negative coalesce delay
        class MockConfig:
            FILE_MONITORING_ENABLED = True
            FILE_MONITORING_COALESCE_DELAY_MS = -100  # Negative value
            FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
            FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5
            MONO_FONT_NAME = 'Menlo'
            FONT_SIZE = 12
            DEFAULT_LEFT_PANE_RATIO = 0.5
            DEFAULT_LOG_HEIGHT_RATIO = 0.25
            DEFAULT_SORT_MODE = 'name'

        errors = self.config_manager.validate_config(MockConfig())
        self.assertIn("FILE_MONITORING_COALESCE_DELAY_MS must be a non-negative integer", errors)

    def test_validation_max_reloads_positive(self):
        """Test validation of FILE_MONITORING_MAX_RELOADS_PER_SECOND as positive integer"""
        # Create a mock config with zero max reloads
        class MockConfig:
            FILE_MONITORING_ENABLED = True
            FILE_MONITORING_COALESCE_DELAY_MS = 200
            FILE_MONITORING_MAX_RELOADS_PER_SECOND = 0  # Zero value
            FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5
            MONO_FONT_NAME = 'Menlo'
            FONT_SIZE = 12
            DEFAULT_LEFT_PANE_RATIO = 0.5
            DEFAULT_LOG_HEIGHT_RATIO = 0.25
            DEFAULT_SORT_MODE = 'name'

        errors = self.config_manager.validate_config(MockConfig())
        self.assertIn("FILE_MONITORING_MAX_RELOADS_PER_SECOND must be a positive integer", errors)

    def test_validation_fallback_poll_interval_positive(self):
        """Test validation of FILE_MONITORING_FALLBACK_POLL_INTERVAL_S as positive number"""
        # Create a mock config with zero poll interval
        class MockConfig:
            FILE_MONITORING_ENABLED = True
            FILE_MONITORING_COALESCE_DELAY_MS = 200
            FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
            FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 0  # Zero value
            MONO_FONT_NAME = 'Menlo'
            FONT_SIZE = 12
            DEFAULT_LEFT_PANE_RATIO = 0.5
            DEFAULT_LOG_HEIGHT_RATIO = 0.25
            DEFAULT_SORT_MODE = 'name'

        errors = self.config_manager.validate_config(MockConfig())
        self.assertIn("FILE_MONITORING_FALLBACK_POLL_INTERVAL_S must be a positive number", errors)

    def test_validation_fallback_poll_interval_accepts_float(self):
        """Test that FILE_MONITORING_FALLBACK_POLL_INTERVAL_S accepts float values"""
        # Create a mock config with float poll interval
        class MockConfig:
            FILE_MONITORING_ENABLED = True
            FILE_MONITORING_COALESCE_DELAY_MS = 200
            FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5
            FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 2.5  # Float value
            MONO_FONT_NAME = 'Menlo'
            FONT_SIZE = 12
            DEFAULT_LEFT_PANE_RATIO = 0.5
            DEFAULT_LOG_HEIGHT_RATIO = 0.25
            DEFAULT_SORT_MODE = 'name'

        errors = self.config_manager.validate_config(MockConfig())
        # Should not have error for fallback poll interval
        self.assertNotIn("FILE_MONITORING_FALLBACK_POLL_INTERVAL_S must be a positive number", errors)

    def test_valid_configuration(self):
        """Test that a valid configuration passes validation"""
        # Use the loaded config which should have valid defaults
        errors = self.config_manager.validate_config(self.config)

        # Filter out any errors not related to file monitoring
        file_monitoring_errors = [e for e in errors if 'FILE_MONITORING' in e]

        # Should have no file monitoring validation errors
        self.assertEqual(len(file_monitoring_errors), 0)


if __name__ == '__main__':
    unittest.main()
