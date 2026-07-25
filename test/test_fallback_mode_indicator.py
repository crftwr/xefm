"""
Test fallback mode indicator in UI.

This test verifies that the status bar shows a visual indicator when file monitoring
is operating in fallback (polling) mode.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from xefm.file_monitor_manager import FileMonitorManager


def test_is_in_fallback_mode_returns_false_when_disabled():
    """Test that is_in_fallback_mode returns False when monitoring is disabled."""
    # Create mock config with monitoring disabled
    config = Mock()
    config.FILE_MONITORING_ENABLED = False
    
    # Create mock file_manager
    file_manager = Mock()
    file_manager.reload_queue = Mock()
    
    # Create FileMonitorManager
    manager = FileMonitorManager(config, file_manager)
    
    # Should return False when monitoring is disabled
    assert manager.is_in_fallback_mode() is False


def test_is_in_fallback_mode_returns_false_when_no_observers():
    """Test that is_in_fallback_mode returns False when no observers are active."""
    # Create mock config with monitoring enabled
    config = Mock()
    config.FILE_MONITORING_ENABLED = True
    
    # Create mock file_manager
    file_manager = Mock()
    file_manager.reload_queue = Mock()
    
    # Create FileMonitorManager
    manager = FileMonitorManager(config, file_manager)
    
    # Should return False when no observers are active
    assert manager.is_in_fallback_mode() is False


def test_is_in_fallback_mode_returns_true_when_polling():
    """Test that is_in_fallback_mode returns True when any pane is in polling mode."""
    # Create mock config with monitoring enabled
    config = Mock()
    config.FILE_MONITORING_ENABLED = True
    
    # Create mock file_manager
    file_manager = Mock()
    file_manager.reload_queue = Mock()
    
    # Create FileMonitorManager
    manager = FileMonitorManager(config, file_manager)
    
    # Create mock observer in polling mode
    mock_observer = Mock()
    mock_observer.get_monitoring_mode.return_value = "polling"
    
    # Set up monitoring state with polling observer
    manager.monitoring_state['left']['observer'] = mock_observer
    
    # Should return True when any pane is in polling mode
    assert manager.is_in_fallback_mode() is True


def test_is_in_fallback_mode_returns_false_when_native():
    """Test that is_in_fallback_mode returns False when all panes are in native mode."""
    # Create mock config with monitoring enabled
    config = Mock()
    config.FILE_MONITORING_ENABLED = True
    
    # Create mock file_manager
    file_manager = Mock()
    file_manager.reload_queue = Mock()
    
    # Create FileMonitorManager
    manager = FileMonitorManager(config, file_manager)
    
    # Create mock observers in native mode
    mock_observer_left = Mock()
    mock_observer_left.get_monitoring_mode.return_value = "native"
    
    mock_observer_right = Mock()
    mock_observer_right.get_monitoring_mode.return_value = "native"
    
    # Set up monitoring state with native observers
    manager.monitoring_state['left']['observer'] = mock_observer_left
    manager.monitoring_state['right']['observer'] = mock_observer_right
    
    # Should return False when all panes are in native mode
    assert manager.is_in_fallback_mode() is False


def test_is_in_fallback_mode_returns_true_when_one_pane_polling():
    """Test that is_in_fallback_mode returns True when one pane is polling and one is native."""
    # Create mock config with monitoring enabled
    config = Mock()
    config.FILE_MONITORING_ENABLED = True
    
    # Create mock file_manager
    file_manager = Mock()
    file_manager.reload_queue = Mock()
    
    # Create FileMonitorManager
    manager = FileMonitorManager(config, file_manager)
    
    # Create mock observers - one native, one polling
    mock_observer_left = Mock()
    mock_observer_left.get_monitoring_mode.return_value = "native"
    
    mock_observer_right = Mock()
    mock_observer_right.get_monitoring_mode.return_value = "polling"
    
    # Set up monitoring state
    manager.monitoring_state['left']['observer'] = mock_observer_left
    manager.monitoring_state['right']['observer'] = mock_observer_right
    
    # Should return True when any pane is in polling mode
    assert manager.is_in_fallback_mode() is True
