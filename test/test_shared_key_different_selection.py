"""
Test file demonstrating shared key with different selection requirements.

Run with: python -m pytest test/test_shared_key_different_selection.py -v
"""

from pathlib import Path
import unittest
from xefm.config import ConfigManager
from xefm._config import Config


class TestSharedKeyDifferentSelection(unittest.TestCase):
    """Test that the same key can be used for different actions based on selection status."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config_manager = ConfigManager()
        self.config_manager.config = Config()
    
    def test_m_key_behavior_based_on_selection(self):
        """Test that 'M' key behaves differently based on selection status."""
        
        # Test move_files configuration
        move_keys = self.config_manager.get_key_for_action('move_files')
        move_requirement = self.config_manager.get_selection_requirement('move_files')
        self.assertIn('M', move_keys)
        self.assertEqual(move_requirement, 'required')
        
        # Test create_directory configuration
        create_keys = self.config_manager.get_key_for_action('create_directory')
        create_requirement = self.config_manager.get_selection_requirement('create_directory')
        self.assertEqual(create_keys, ['M'])  # keymap stores the upper form; 'm' matches at dispatch
        self.assertEqual(create_requirement, 'none')
    
    def test_m_key_availability_with_no_selection(self):
        """Test 'M' key behavior when no files are selected."""
        
        # When no files are selected:
        # - move_files should NOT be available (requires selection)
        # - create_directory should be available (requires no selection)
        
        move_available_m = self.config_manager.is_key_bound_to_action_with_selection('m', 'move_files', False)
        move_available_M = self.config_manager.is_key_bound_to_action_with_selection('M', 'move_files', False)
        create_available_m = self.config_manager.is_key_bound_to_action_with_selection('m', 'create_directory', False)
        create_available_M = self.config_manager.is_key_bound_to_action_with_selection('M', 'create_directory', False)
        
        self.assertFalse(move_available_m, "move_files should not be available without selection")
        self.assertFalse(move_available_M, "move_files should not be available without selection")
        self.assertTrue(create_available_m, "create_directory should be available without selection")
        self.assertTrue(create_available_M, "create_directory should be available without selection")
    
    def test_m_key_availability_with_selection(self):
        """Test 'M' key behavior when files are selected."""
        
        # When files are selected:
        # - move_files should be available (requires selection)
        # - create_directory should NOT be available (requires no selection)
        
        move_available_m = self.config_manager.is_key_bound_to_action_with_selection('m', 'move_files', True)
        move_available_M = self.config_manager.is_key_bound_to_action_with_selection('M', 'move_files', True)
        create_available_m = self.config_manager.is_key_bound_to_action_with_selection('m', 'create_directory', True)
        create_available_M = self.config_manager.is_key_bound_to_action_with_selection('M', 'create_directory', True)
        
        self.assertTrue(move_available_m, "move_files should be available with selection")
        self.assertTrue(move_available_M, "move_files should be available with selection")
        self.assertFalse(create_available_m, "create_directory should not be available with selection")
        self.assertFalse(create_available_M, "create_directory should not be available with selection")
    
    def test_unified_key_handling_simulation(self):
        """Test that unified key handling correctly routes to the right action."""
        
        # Mock file manager to test unified approach
        class MockFileManager:
            def __init__(self, config_manager):
                self.config_manager = config_manager
                self.left_pane = {'selected_files': set()}
                self.active_pane = 'left'
            
            def get_current_pane(self):
                return self.left_pane
            
            def is_key_for_action(self, key, action):
                """Unified method that respects selection requirements."""
                if 32 <= key <= 126:  # Printable ASCII
                    key_char = chr(key)
                    current_pane = self.get_current_pane()
                    has_selection = len(current_pane['selected_files']) > 0
                    return self.config_manager.is_key_bound_to_action_with_selection(key_char, action, has_selection)
                return False
        
        fm = MockFileManager(self.config_manager)
        
        # Scenario 1: No files selected - both 'm' and 'M' should trigger create_directory
        fm.left_pane['selected_files'] = set()
        
        move_triggered_m = fm.is_key_for_action(ord('m'), 'move_files')
        move_triggered_M = fm.is_key_for_action(ord('M'), 'move_files')
        create_triggered_m = fm.is_key_for_action(ord('m'), 'create_directory')
        create_triggered_M = fm.is_key_for_action(ord('M'), 'create_directory')
        
        self.assertFalse(move_triggered_m, "move_files should not be triggered without selection")
        self.assertFalse(move_triggered_M, "move_files should not be triggered without selection")
        self.assertTrue(create_triggered_m, "create_directory should be triggered without selection")
        self.assertTrue(create_triggered_M, "create_directory should be triggered without selection")
        
        # Scenario 2: Files selected - both 'm' and 'M' should trigger move_files
        fm.left_pane['selected_files'] = {'/path/file1.txt', '/path/file2.txt'}
        
        move_triggered_m = fm.is_key_for_action(ord('m'), 'move_files')
        move_triggered_M = fm.is_key_for_action(ord('M'), 'move_files')
        create_triggered_m = fm.is_key_for_action(ord('m'), 'create_directory')
        create_triggered_M = fm.is_key_for_action(ord('M'), 'create_directory')
        
        self.assertTrue(move_triggered_m, "move_files should be triggered with selection")
        self.assertTrue(move_triggered_M, "move_files should be triggered with selection")
        self.assertFalse(create_triggered_m, "create_directory should not be triggered with selection")
        self.assertFalse(create_triggered_M, "create_directory should not be triggered with selection")
    
    def test_key_conflict_resolution(self):
        """Test that there's no actual conflict - selection requirements resolve it."""
        
        # Both actions are bound to the shared 'M' key (lowercase 'm' matches it
        # case-insensitively at dispatch; the stored key list is the upper form).
        move_keys = self.config_manager.get_key_for_action('move_files')
        create_keys = self.config_manager.get_key_for_action('create_directory')

        self.assertIn('M', move_keys)
        self.assertIn('M', create_keys)
        
        # But they have different selection requirements
        move_req = self.config_manager.get_selection_requirement('move_files')
        create_req = self.config_manager.get_selection_requirement('create_directory')
        
        self.assertEqual(move_req, 'required')
        self.assertEqual(create_req, 'none')
        
        # This means they're mutually exclusive - no conflict!
        # When files are selected: only move_files is available
        # When no files are selected: only create_directory is available
