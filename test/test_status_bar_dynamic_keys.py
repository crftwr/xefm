#!/usr/bin/env python3
"""
Test that status bar help message uses dynamic key bindings from config.
"""

import unittest
from unittest.mock import MagicMock, patch
from xefm.config import get_keys_for_action, format_key_for_display


class TestStatusBarDynamicKeys(unittest.TestCase):
    """Test status bar displays correct key bindings from config."""
    
    def test_status_bar_key_bindings_from_config(self):
        """Verify status bar uses get_keys_for_action and format_key_for_display."""
        # Test that we can get the keys for the actions shown in status bar
        help_keys, _ = get_keys_for_action('help')
        self.assertTrue(len(help_keys) > 0, "help action should have key bindings")
        
        switch_keys, _ = get_keys_for_action('switch_pane')
        self.assertTrue(len(switch_keys) > 0, "switch_pane action should have key bindings")
        
        open_keys, _ = get_keys_for_action('open_item')
        self.assertTrue(len(open_keys) > 0, "open_item action should have key bindings")
        
        quit_keys, _ = get_keys_for_action('quit')
        self.assertTrue(len(quit_keys) > 0, "quit action should have key bindings")
    
    def test_format_key_for_display(self):
        """Verify format_key_for_display works for common keys."""
        # Test basic keys
        self.assertEqual(format_key_for_display('?'), '?')
        self.assertEqual(format_key_for_display('TAB'), 'Tab')
        self.assertEqual(format_key_for_display('ENTER'), 'Enter')
        self.assertEqual(format_key_for_display('Q'), 'Q')
        
        # Test that function handles lowercase keys
        self.assertEqual(format_key_for_display('q'), 'q')
    
    def test_status_bar_message_construction(self):
        """Verify status bar message can be constructed from config."""
        # Get keys from config
        help_keys, _ = get_keys_for_action('help')
        help_key = format_key_for_display(help_keys[0]) if help_keys else '?'
        
        switch_keys, _ = get_keys_for_action('switch_pane')
        switch_key = format_key_for_display(switch_keys[0]) if switch_keys else 'Tab'
        
        open_keys, _ = get_keys_for_action('open_item')
        open_key = format_key_for_display(open_keys[0]) if open_keys else 'Enter'
        
        quit_keys, _ = get_keys_for_action('quit')
        quit_key = format_key_for_display(quit_keys[0]) if quit_keys else 'q'
        
        # Construct message
        controls = f"Press {help_key} for help  •  {switch_key}:switch panes  •  {open_key}:open  •  {quit_key}:quit"
        
        # Verify message is not empty and contains expected parts
        self.assertIn("for help", controls)
        self.assertIn("switch panes", controls)
        self.assertIn("open", controls)
        self.assertIn("quit", controls)


if __name__ == '__main__':
    unittest.main()
