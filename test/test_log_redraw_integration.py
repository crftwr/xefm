"""
Integration test for log redraw trigger functionality

Run with: python -m pytest test/test_log_redraw_integration.py -v
"""

import sys
import unittest
from unittest.mock import Mock, patch

class TestLogRedrawIntegration(unittest.TestCase):
    """Test integration of log redraw trigger with main application logic"""
    
    def test_main_loop_logic_simulation(self):
        """Test the main loop logic for log redraw triggering"""
        from xefm.log_manager import LogManager
        
        # Mock config
        mock_config = Mock()
        mock_config.MAX_LOG_MESSAGES = 100
        
        # Create LogManager
        log_manager = LogManager(mock_config)
        
        # Simulate main loop state
        needs_full_redraw = False
        
        # Initial state - no redraw needed
        if log_manager.has_log_updates():
            needs_full_redraw = True
        
        # Should not need redraw initially (after startup messages are processed)
        log_manager.mark_log_updates_processed()
        self.assertFalse(log_manager.has_log_updates())
        
        # Simulate log message being added
        log_manager.add_message("TEST", "Test message")
        
        # Check for updates (main loop logic)
        if log_manager.has_log_updates():
            needs_full_redraw = True
        
        # Should need redraw now
        self.assertTrue(needs_full_redraw)
        
        # Simulate redraw completion
        if needs_full_redraw:
            # ... redraw would happen here ...
            needs_full_redraw = False
            log_manager.mark_log_updates_processed()
        
        # Should not need redraw after processing
        self.assertFalse(log_manager.has_log_updates())
        self.assertFalse(needs_full_redraw)
        
        # Clean up
        log_manager.restore_stdio()
    
    def test_stdout_stderr_integration(self):
        """Test that stdout/stderr output triggers redraw logic"""
        from xefm.log_manager import LogManager
        
        # Mock config
        mock_config = Mock()
        mock_config.MAX_LOG_MESSAGES = 100
        
        # Create LogManager (this redirects stdout/stderr)
        log_manager = LogManager(mock_config)
        
        # Clear initial state
        log_manager.mark_log_updates_processed()
        
        # Simulate stdout output
        print("Test stdout message")
        
        # Should trigger update detection
        self.assertTrue(log_manager.has_log_updates())
        
        # Mark as processed
        log_manager.mark_log_updates_processed()
        
        # Simulate stderr output
        print("Test stderr message", file=sys.stderr)
        
        # Should trigger update detection again
        self.assertTrue(log_manager.has_log_updates())
        
        # Clean up
        log_manager.restore_stdio()
    
    def test_multiple_updates_before_processing(self):
        """Test that multiple updates before processing are handled correctly"""
        from xefm.log_manager import LogManager
        
        # Mock config
        mock_config = Mock()
        mock_config.MAX_LOG_MESSAGES = 100
        
        # Create LogManager
        log_manager = LogManager(mock_config)
        log_manager.mark_log_updates_processed()
        
        # Add multiple messages without processing
        log_manager.add_message("TEST1", "Message 1")
        self.assertTrue(log_manager.has_log_updates())
        
        log_manager.add_message("TEST2", "Message 2")
        self.assertTrue(log_manager.has_log_updates())
        
        log_manager.add_message("TEST3", "Message 3")
        self.assertTrue(log_manager.has_log_updates())
        
        # Should still detect updates
        self.assertTrue(log_manager.has_log_updates())
        
        # Process all updates at once
        log_manager.mark_log_updates_processed()
        
        # Should no longer detect updates
        self.assertFalse(log_manager.has_log_updates())
        
        # Clean up
        log_manager.restore_stdio()
    
    def test_redraw_efficiency(self):
        """Test that redraws are only triggered when necessary"""
        from xefm.log_manager import LogManager
        
        # Mock config
        mock_config = Mock()
        mock_config.MAX_LOG_MESSAGES = 100
        
        # Create LogManager
        log_manager = LogManager(mock_config)
        log_manager.mark_log_updates_processed()
        
        # No updates initially
        redraw_count = 0
        
        # Simulate main loop iterations without log updates
        for _ in range(10):
            if log_manager.has_log_updates():
                redraw_count += 1
                log_manager.mark_log_updates_processed()
        
        # Should not have triggered any redraws
        self.assertEqual(redraw_count, 0)
        
        # Add a message
        log_manager.add_message("TEST", "Message")
        
        # Should trigger one redraw
        if log_manager.has_log_updates():
            redraw_count += 1
            log_manager.mark_log_updates_processed()
        
        self.assertEqual(redraw_count, 1)
        
        # Multiple iterations without new messages
        for _ in range(10):
            if log_manager.has_log_updates():
                redraw_count += 1
                log_manager.mark_log_updates_processed()
        
        # Should still be only one redraw
        self.assertEqual(redraw_count, 1)
        
        # Clean up
        log_manager.restore_stdio()
    
    def test_startup_message_handling(self):
        """Test that startup messages are handled correctly"""
        from xefm.log_manager import LogManager
        
        # Mock config
        mock_config = Mock()
        mock_config.MAX_LOG_MESSAGES = 100
        
        # Create LogManager (startup messages added during init)
        log_manager = LogManager(mock_config)
        
        # Should have startup messages and detect updates
        initial_updates = log_manager.has_log_updates()
        
        # Add more startup messages
        log_manager.add_startup_messages("1.0", "https://github.com/test", "Test App")
        
        # Should still detect updates
        self.assertTrue(log_manager.has_log_updates())
        
        # Process updates
        log_manager.mark_log_updates_processed()
        
        # Should no longer detect updates
        self.assertFalse(log_manager.has_log_updates())
        
        # Clean up
        log_manager.restore_stdio()
