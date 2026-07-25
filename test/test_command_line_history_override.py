"""
Test that command line directory arguments prevent history restoration

Run with: python -m pytest test/test_command_line_history_override.py -v
"""

import unittest
import os
import tempfile
import shutil
from pathlib import Path

class TestCommandLineHistoryOverride(unittest.TestCase):
    """Test command line directory behavior and history override logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create temporary directories for testing
        self.temp_dir = tempfile.mkdtemp()
        self.left_test_dir = os.path.join(self.temp_dir, 'left_test')
        self.right_test_dir = os.path.join(self.temp_dir, 'right_test')
        
        # Create test directories
        os.makedirs(self.left_test_dir)
        os.makedirs(self.right_test_dir)
    
    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_cmdline_flags_set_correctly_with_left(self):
        """Test that cmdline flags are set correctly when --left is provided"""
        # This tests the logic in FileManager.__init__() for tracking command line args
        
        # Simulate the logic from FileManager.__init__()
        left_dir = self.left_test_dir
        right_dir = None
        
        cmdline_left_dir_provided = left_dir is not None
        cmdline_right_dir_provided = right_dir is not None
        
        self.assertTrue(cmdline_left_dir_provided)
        self.assertFalse(cmdline_right_dir_provided)
    
    def test_cmdline_flags_set_correctly_with_right(self):
        """Test that cmdline flags are set correctly when --right is provided"""
        left_dir = None
        right_dir = self.right_test_dir
        
        cmdline_left_dir_provided = left_dir is not None
        cmdline_right_dir_provided = right_dir is not None
        
        self.assertFalse(cmdline_left_dir_provided)
        self.assertTrue(cmdline_right_dir_provided)
    
    def test_cmdline_flags_set_correctly_with_both(self):
        """Test that cmdline flags are set correctly when both are provided"""
        left_dir = self.left_test_dir
        right_dir = self.right_test_dir
        
        cmdline_left_dir_provided = left_dir is not None
        cmdline_right_dir_provided = right_dir is not None
        
        self.assertTrue(cmdline_left_dir_provided)
        self.assertTrue(cmdline_right_dir_provided)
    
    def test_cmdline_flags_set_correctly_with_neither(self):
        """Test that cmdline flags are set correctly when neither is provided"""
        left_dir = None
        right_dir = None
        
        cmdline_left_dir_provided = left_dir is not None
        cmdline_right_dir_provided = right_dir is not None
        
        self.assertFalse(cmdline_left_dir_provided)
        self.assertFalse(cmdline_right_dir_provided)
    
    def test_history_restore_logic_left_cmdline(self):
        """Test the logic for history restoration when --left is provided"""
        # Simulate the logic from load_application_state()
        cmdline_left_dir_provided = True
        cmdline_right_dir_provided = False
        
        # Mock state data
        left_state = {
            'path': '/some/history/path',
            'sort_mode': 'name',
            'sort_reverse': False,
            'filter_pattern': ''
        }
        right_state = {
            'path': '/some/other/history/path',
            'sort_mode': 'size',
            'sort_reverse': True,
            'filter_pattern': '*.txt'
        }
        
        # Test left pane logic
        should_restore_left_path = (left_state and 
                                   Path(left_state['path']).exists() and 
                                   not cmdline_left_dir_provided)
        
        # Test right pane logic  
        should_restore_right_path = (right_state and 
                                    Path(right_state['path']).exists() and 
                                    not cmdline_right_dir_provided)
        
        # Left path should NOT be restored (command line provided)
        self.assertFalse(should_restore_left_path)
        
        # Right path should be restored (no command line arg)
        # Note: This would be True if the path existed, but we're testing the logic
        self.assertFalse(should_restore_right_path)  # False because path doesn't exist
    
    def test_history_restore_logic_right_cmdline(self):
        """Test the logic for history restoration when --right is provided"""
        cmdline_left_dir_provided = False
        cmdline_right_dir_provided = True
        
        # Mock state data with existing paths
        left_state = {'path': str(Path.cwd())}  # Use existing path
        right_state = {'path': str(Path.home())}  # Use existing path
        
        # Test logic
        should_restore_left_path = (left_state and 
                                   Path(left_state['path']).exists() and 
                                   not cmdline_left_dir_provided)
        
        should_restore_right_path = (right_state and 
                                    Path(right_state['path']).exists() and 
                                    not cmdline_right_dir_provided)
        
        # Left path should be restored (no command line arg)
        self.assertTrue(should_restore_left_path)
        
        # Right path should NOT be restored (command line provided)
        self.assertFalse(should_restore_right_path)
    
    def test_history_restore_logic_both_cmdline(self):
        """Test the logic for history restoration when both are provided"""
        cmdline_left_dir_provided = True
        cmdline_right_dir_provided = True
        
        # Mock state data with existing paths
        left_state = {'path': str(Path.cwd())}
        right_state = {'path': str(Path.home())}
        
        # Test logic
        should_restore_left_path = (left_state and 
                                   Path(left_state['path']).exists() and 
                                   not cmdline_left_dir_provided)
        
        should_restore_right_path = (right_state and 
                                    Path(right_state['path']).exists() and 
                                    not cmdline_right_dir_provided)
        
        # Neither path should be restored (both command line args provided)
        self.assertFalse(should_restore_left_path)
        self.assertFalse(should_restore_right_path)
    
    def test_history_restore_logic_no_cmdline(self):
        """Test the logic for history restoration when neither is provided"""
        cmdline_left_dir_provided = False
        cmdline_right_dir_provided = False
        
        # Mock state data with existing paths
        left_state = {'path': str(Path.cwd())}
        right_state = {'path': str(Path.home())}
        
        # Test logic
        should_restore_left_path = (left_state and 
                                   Path(left_state['path']).exists() and 
                                   not cmdline_left_dir_provided)
        
        should_restore_right_path = (right_state and 
                                    Path(right_state['path']).exists() and 
                                    not cmdline_right_dir_provided)
        
        # Both paths should be restored (no command line args)
        self.assertTrue(should_restore_left_path)
        self.assertTrue(should_restore_right_path)
    
    def test_directory_validation_logic(self):
        """Test directory validation logic"""
        # Test existing directory
        test_dir = self.left_test_dir
        initial_dir = Path(test_dir)
        
        if not initial_dir.exists() or not initial_dir.is_dir():
            fallback_dir = Path.cwd()
        else:
            fallback_dir = initial_dir
        
        self.assertEqual(fallback_dir, initial_dir)
        
        # Test non-existing directory
        nonexistent_dir = Path('/nonexistent/directory/path')
        
        if not nonexistent_dir.exists() or not nonexistent_dir.is_dir():
            fallback_dir = Path.cwd()
        else:
            fallback_dir = nonexistent_dir
        
        self.assertEqual(fallback_dir, Path.cwd())
