"""
Test PaneManager integration with the XeFM system.

This test verifies that PaneManager works correctly with the
xefm_main.py and that all pane management functionality is intact.

Run with: python -m pytest test/test_pane_manager.py -v
"""

import unittest
import tempfile
import shutil
from pathlib import Path

# Import XeFM components
from xefm.path import Path as XeFMPath
from xefm.pane_manager import PaneManager
from xefm.config import get_config


class TestPaneManagerIntegration(unittest.TestCase):
    """Test PaneManager integration"""
    
    def setUp(self):
        """Set up test environment"""
        # Create temporary directories for testing
        self.test_dir = tempfile.mkdtemp()
        self.left_dir = Path(self.test_dir) / "left"
        self.right_dir = Path(self.test_dir) / "right"
        self.left_dir.mkdir()
        self.right_dir.mkdir()
        
        # Create some test files
        (self.left_dir / "file1.txt").touch()
        (self.left_dir / "file2.txt").touch()
        (self.left_dir / "subdir").mkdir()
        
        (self.right_dir / "file3.txt").touch()
        (self.right_dir / "file4.txt").touch()
        
        # Get config
        self.config = get_config()
        
        # Create PaneManager instance
        self.pane_manager = PaneManager(
            self.config,
            XeFMPath(str(self.left_dir)),
            XeFMPath(str(self.right_dir))
        )
    
    def tearDown(self):
        """Clean up test environment"""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_pane_manager_initialization(self):
        """Test that PaneManager initializes correctly"""
        self.assertIsNotNone(self.pane_manager)
        self.assertEqual(self.pane_manager.active_pane, 'left')
        self.assertIsNotNone(self.pane_manager.left_pane)
        self.assertIsNotNone(self.pane_manager.right_pane)
    
    def test_pane_data_structure(self):
        """Test that pane data structures are correct"""
        left_pane = self.pane_manager.left_pane
        right_pane = self.pane_manager.right_pane
        
        # Check required fields exist
        required_fields = ['path', 'focused_index', 'scroll_offset', 'files', 
                          'selected_files', 'sort_mode', 'sort_reverse', 'filter_pattern']
        
        for field in required_fields:
            self.assertIn(field, left_pane)
            self.assertIn(field, right_pane)
    
    def test_get_current_pane(self):
        """Test getting current pane"""
        # Initially left pane is active
        current = self.pane_manager.get_current_pane()
        self.assertEqual(current, self.pane_manager.left_pane)
        
        # Switch to right pane
        self.pane_manager.switch_pane()
        current = self.pane_manager.get_current_pane()
        self.assertEqual(current, self.pane_manager.right_pane)
    
    def test_get_inactive_pane(self):
        """Test getting inactive pane"""
        # Initially right pane is inactive
        inactive = self.pane_manager.get_inactive_pane()
        self.assertEqual(inactive, self.pane_manager.right_pane)
        
        # Switch to right pane
        self.pane_manager.switch_pane()
        inactive = self.pane_manager.get_inactive_pane()
        self.assertEqual(inactive, self.pane_manager.left_pane)
    
    def test_switch_pane(self):
        """Test switching between panes"""
        self.assertEqual(self.pane_manager.active_pane, 'left')
        
        self.pane_manager.switch_pane()
        self.assertEqual(self.pane_manager.active_pane, 'right')
        
        self.pane_manager.switch_pane()
        self.assertEqual(self.pane_manager.active_pane, 'left')
    
    def test_adjust_scroll_for_focus(self):
        """Test scroll adjustment for selection"""
        pane = self.pane_manager.left_pane
        pane['focused_index'] = 10
        pane['scroll_offset'] = 0
        
        # Adjust scroll for display height of 5
        self.pane_manager.adjust_scroll_for_focus(pane, 5)
        
        # Scroll should be adjusted to keep selection visible
        self.assertGreaterEqual(pane['scroll_offset'], 6)
    
    def test_count_files_and_dirs(self):
        """Test counting files and directories"""
        pane = self.pane_manager.left_pane
        
        # Add some test files to pane
        pane['files'] = [
            XeFMPath(str(self.left_dir / "file1.txt")),
            XeFMPath(str(self.left_dir / "file2.txt")),
            XeFMPath(str(self.left_dir / "subdir")),
        ]
        
        dir_count, file_count = self.pane_manager.count_files_and_dirs(pane)
        
        self.assertEqual(dir_count, 1)  # subdir
        self.assertEqual(file_count, 2)  # file1.txt, file2.txt
    
    def test_sync_current_to_other(self):
        """Test syncing current pane to other pane's directory"""
        # Set different paths
        self.pane_manager.left_pane['path'] = XeFMPath(str(self.left_dir))
        self.pane_manager.right_pane['path'] = XeFMPath(str(self.right_dir))
        self.pane_manager.active_pane = 'left'
        
        # Sync left to right's directory
        result = self.pane_manager.sync_current_to_other()
        
        self.assertTrue(result)
        self.assertEqual(
            str(self.pane_manager.left_pane['path']),
            str(self.right_dir)
        )
    
    def test_sync_other_to_current(self):
        """Test syncing other pane to current pane's directory"""
        # Set different paths
        self.pane_manager.left_pane['path'] = XeFMPath(str(self.left_dir))
        self.pane_manager.right_pane['path'] = XeFMPath(str(self.right_dir))
        self.pane_manager.active_pane = 'left'
        
        # Sync right to left's directory
        result = self.pane_manager.sync_other_to_current()
        
        self.assertTrue(result)
        self.assertEqual(
            str(self.pane_manager.right_pane['path']),
            str(self.left_dir)
        )
    
    def test_sync_cursor_to_other_pane(self):
        """Test syncing cursor to other pane's filename"""
        # Setup files in both panes
        common_file = "common.txt"
        (self.left_dir / common_file).touch()
        (self.right_dir / common_file).touch()
        
        self.pane_manager.left_pane['files'] = [
            XeFMPath(str(self.left_dir / "file1.txt")),
            XeFMPath(str(self.left_dir / common_file)),
        ]
        self.pane_manager.right_pane['files'] = [
            XeFMPath(str(self.right_dir / common_file)),
            XeFMPath(str(self.right_dir / "file3.txt")),
        ]
        
        # Set right pane cursor to common file
        self.pane_manager.right_pane['focused_index'] = 0
        self.pane_manager.active_pane = 'left'
        
        # Sync left cursor to right's selection
        result = self.pane_manager.sync_cursor_to_other_pane()
        
        self.assertTrue(result)
        self.assertEqual(self.pane_manager.left_pane['focused_index'], 1)
    
    def test_sync_cursor_from_current_pane(self):
        """Test syncing cursor from current pane to other pane"""
        # Setup files in both panes
        common_file = "common.txt"
        (self.left_dir / common_file).touch()
        (self.right_dir / common_file).touch()
        
        self.pane_manager.left_pane['files'] = [
            XeFMPath(str(self.left_dir / "file1.txt")),
            XeFMPath(str(self.left_dir / common_file)),
        ]
        self.pane_manager.right_pane['files'] = [
            XeFMPath(str(self.right_dir / common_file)),
            XeFMPath(str(self.right_dir / "file3.txt")),
        ]
        
        # Set left pane cursor to common file
        self.pane_manager.left_pane['focused_index'] = 1
        self.pane_manager.active_pane = 'left'
        
        # Sync right cursor to left's selection
        result = self.pane_manager.sync_cursor_from_current_pane()
        
        self.assertTrue(result)
        self.assertEqual(self.pane_manager.right_pane['focused_index'], 0)
    
    def test_pane_ratio(self):
        """Test pane width ratio"""
        # Check default ratio
        self.assertGreater(self.pane_manager.left_pane_ratio, 0)
        self.assertLess(self.pane_manager.left_pane_ratio, 1)
        
        # Test ratio can be changed
        self.pane_manager.left_pane_ratio = 0.6
        self.assertEqual(self.pane_manager.left_pane_ratio, 0.6)
    
    def test_selected_files_tracking(self):
        """Test multi-selection tracking"""
        pane = self.pane_manager.left_pane
        
        # Initially empty
        self.assertEqual(len(pane['selected_files']), 0)
        
        # Add selections
        pane['selected_files'].add('file1.txt')
        pane['selected_files'].add('file2.txt')
        
        self.assertEqual(len(pane['selected_files']), 2)
        self.assertIn('file1.txt', pane['selected_files'])
        self.assertIn('file2.txt', pane['selected_files'])
    
    def test_filter_pattern_tracking(self):
        """Test filter pattern tracking"""
        pane = self.pane_manager.left_pane
        
        # Initially empty
        self.assertEqual(pane['filter_pattern'], "")
        
        # Set filter
        pane['filter_pattern'] = "*.txt"
        self.assertEqual(pane['filter_pattern'], "*.txt")
    
    def test_sort_mode_tracking(self):
        """Test sort mode tracking"""
        pane = self.pane_manager.left_pane
        
        # Check default
        self.assertIn(pane['sort_mode'], ['filename', 'extension', 'size', 'timestamp'])
        
        # Change sort mode
        pane['sort_mode'] = 'size'
        self.assertEqual(pane['sort_mode'], 'size')
        
        # Change sort direction
        pane['sort_reverse'] = True
        self.assertTrue(pane['sort_reverse'])


class TestPaneManagerWithoutStateManager(unittest.TestCase):
    """Test PaneManager without state manager (cursor history disabled)"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.left_dir = Path(self.test_dir) / "left"
        self.right_dir = Path(self.test_dir) / "right"
        self.left_dir.mkdir()
        self.right_dir.mkdir()
        
        config = get_config()
        
        # Create PaneManager without state manager
        self.pane_manager = PaneManager(
            config,
            XeFMPath(str(self.left_dir)),
            XeFMPath(str(self.right_dir)),
            state_manager=None
        )
    
    def tearDown(self):
        """Clean up test environment"""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_save_cursor_position_without_state_manager(self):
        """Test that save_cursor_position doesn't crash without state manager"""
        pane = self.pane_manager.left_pane
        pane['files'] = [XeFMPath(str(self.left_dir / "file1.txt"))]
        pane['focused_index'] = 0
        
        # Should not crash
        self.pane_manager.save_cursor_position(pane)
    
    def test_restore_cursor_position_without_state_manager(self):
        """Test that restore_cursor_position returns False without state manager"""
        pane = self.pane_manager.left_pane
        
        # Should return False (no restoration possible)
        result = self.pane_manager.restore_cursor_position(pane, 10)
        self.assertFalse(result)
