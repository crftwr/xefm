"""
Test file for integration of extended key bindings with XeFM main functionality.

Run with: python -m pytest test/test_main_integration.py -v
"""

import unittest
from unittest.mock import Mock, patch
from xefm._config import Config


class MockFileManager:
    """Mock FileManager class for testing key binding integration."""
    
    def __init__(self):
        self.config = Config()
        # Mock pane data
        self.left_pane = {'selected_files': set()}
        self.right_pane = {'selected_files': set()}
        self.active_pane = 'left'
    
    def get_current_pane(self):
        """Get the currently active pane."""
        return self.left_pane if self.active_pane == 'left' else self.right_pane
    
    def is_key_for_action(self, key, action):
        """Check if a key matches a configured action and respects selection requirements."""
        if 32 <= key <= 126:  # Printable ASCII
            key_char = chr(key)
            current_pane = self.get_current_pane()
            has_selection = len(current_pane['selected_files']) > 0
            from xefm.config import is_key_bound_to_with_selection
            return is_key_bound_to_with_selection(key_char, action, has_selection)
        return False
    
    def is_key_for_action_original(self, key, action):
        """Check if a key matches a configured action (original method without selection awareness)."""
        if 32 <= key <= 126:  # Printable ASCII
            key_char = chr(key)
            from xefm.config import is_key_bound_to
            return is_key_bound_to(key_char, action)
        return False


class TestMainIntegration(unittest.TestCase):
    """Test the integration of extended key bindings with main XeFM functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.file_manager = MockFileManager()
    
    def test_key_binding_without_selection(self):
        """Test key binding behavior when no files are selected."""
        # No files selected
        self.file_manager.left_pane['selected_files'] = set()
        
        # Actions that work regardless of selection
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('q'), 'quit'))  # Key is bound
        self.assertTrue(self.file_manager.is_key_for_action(ord('q'), 'quit'))  # And available
        
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('?'), 'help'))  # Key is bound
        self.assertTrue(self.file_manager.is_key_for_action(ord('?'), 'help'))  # And available
        
        # Actions that require selection - should not be available
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('c'), 'copy_files'))  # Key is bound
        self.assertFalse(self.file_manager.is_key_for_action(ord('c'), 'copy_files'))  # But not available
        
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('k'), 'delete_files'))  # Key is bound
        self.assertFalse(self.file_manager.is_key_for_action(ord('k'), 'delete_files'))  # But not available
    
    def test_key_binding_with_selection(self):
        """Test key binding behavior when files are selected."""
        # Files selected
        self.file_manager.left_pane['selected_files'] = {'/path/to/file1.txt', '/path/to/file2.txt'}
        
        # Actions that work regardless of selection
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('q'), 'quit'))  # Key is bound
        self.assertTrue(self.file_manager.is_key_for_action(ord('q'), 'quit'))  # And available
        
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('?'), 'help'))  # Key is bound
        self.assertTrue(self.file_manager.is_key_for_action(ord('?'), 'help'))  # And available
        
        # Actions that require selection - should be available
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('c'), 'copy_files'))  # Key is bound
        self.assertTrue(self.file_manager.is_key_for_action(ord('c'), 'copy_files'))  # And available
        
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('k'), 'delete_files'))  # Key is bound
        self.assertTrue(self.file_manager.is_key_for_action(ord('k'), 'delete_files'))  # And available
    
    def test_different_keys_same_action(self):
        """Test that alphabet keys are case-insensitive (both 'c' and 'C' map to KeyCode.C)."""
        # No selection
        self.file_manager.left_pane['selected_files'] = set()
        
        # Both 'c' and 'C' map to KeyCode.C (case-insensitive for alphabet)
        # So both should be bound to copy_files
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('c'), 'copy_files'))
        self.assertTrue(self.file_manager.is_key_for_action_original(ord('C'), 'copy_files'))
        
        # But neither should be available without selection
        self.assertFalse(self.file_manager.is_key_for_action(ord('c'), 'copy_files'))
        self.assertFalse(self.file_manager.is_key_for_action(ord('C'), 'copy_files'))
        
        # With selection
        self.file_manager.left_pane['selected_files'] = {'/path/to/file.txt'}
        
        # Both should be available with selection (case-insensitive)
        self.assertTrue(self.file_manager.is_key_for_action(ord('c'), 'copy_files'))
        self.assertTrue(self.file_manager.is_key_for_action(ord('C'), 'copy_files'))
    
    def test_active_pane_switching(self):
        """Test that selection status is checked for the active pane."""
        # Left pane has selection, right pane doesn't
        self.file_manager.left_pane['selected_files'] = {'/path/to/file.txt'}
        self.file_manager.right_pane['selected_files'] = set()
        
        # Active pane is left - should have selection
        self.file_manager.active_pane = 'left'
        self.assertTrue(self.file_manager.is_key_for_action(ord('c'), 'copy_files'))
        
        # Active pane is right - should not have selection
        self.file_manager.active_pane = 'right'
        self.assertFalse(self.file_manager.is_key_for_action(ord('c'), 'copy_files'))
    
    def test_non_printable_keys(self):
        """Test that non-printable keys return False."""
        # Non-printable keys should return False
        self.assertFalse(self.file_manager.is_key_for_action(27, 'quit'))  # ESC
        self.assertFalse(self.file_manager.is_key_for_action_original(27, 'quit'))  # ESC
        
        self.assertFalse(self.file_manager.is_key_for_action(259, 'quit'))  # Up arrow
        self.assertFalse(self.file_manager.is_key_for_action_original(259, 'quit'))  # Up arrow
    
    def test_unbound_keys(self):
        """Test behavior with keys that aren't bound to any action."""
        # Key 'z' is not bound to copy_files
        self.assertFalse(self.file_manager.is_key_for_action_original(ord('z'), 'copy_files'))
        self.assertFalse(self.file_manager.is_key_for_action(ord('z'), 'copy_files'))
        
        # Even with selection
        self.file_manager.left_pane['selected_files'] = {'/path/to/file.txt'}
        self.assertFalse(self.file_manager.is_key_for_action_original(ord('z'), 'copy_files'))
        self.assertFalse(self.file_manager.is_key_for_action(ord('z'), 'copy_files'))
