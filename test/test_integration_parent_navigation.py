"""
Integration test for parent directory navigation cursor positioning.

This test verifies the complete integration of the parent directory navigation
feature within the XeFM application context.

Run with: python -m pytest test/test_integration_parent_navigation.py -v
"""

import unittest
import tempfile
from pathlib import Path

from xefm.path import Path as XeFMPath
from xefm.pane_manager import PaneManager
from xefm.file_list_manager import FileListManager


class MockConfig:
    """Mock configuration for testing"""
    DEFAULT_SORT_MODE = 'name'
    DEFAULT_SORT_REVERSE = False
    DEFAULT_LEFT_PANE_RATIO = 0.5
    MAX_HISTORY_ENTRIES = 100
    SHOW_HIDDEN_FILES = False


class TestIntegrationParentNavigation(unittest.TestCase):
    """Integration test for parent directory navigation"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.config = MockConfig()
        
        # Create test directory structure
        # temp_dir/
        #   ├── alpha/
        #   │   └── file1.txt
        #   ├── beta/
        #   │   └── file2.txt
        #   ├── gamma/
        #   │   └── file3.txt
        #   └── root_file.txt
        
        self.alpha_path = Path(self.temp_dir) / "alpha"
        self.beta_path = Path(self.temp_dir) / "beta"
        self.gamma_path = Path(self.temp_dir) / "gamma"
        
        self.alpha_path.mkdir()
        self.beta_path.mkdir()
        self.gamma_path.mkdir()
        
        # Create files
        (self.alpha_path / "file1.txt").write_text("content1")
        (self.beta_path / "file2.txt").write_text("content2")
        (self.gamma_path / "file3.txt").write_text("content3")
        (Path(self.temp_dir) / "root_file.txt").write_text("root content")
        
        # Initialize components
        self.pane_manager = PaneManager(
            self.config,
            XeFMPath(self.beta_path),  # Start in beta directory
            XeFMPath(self.temp_dir),
            state_manager=None
        )
        self.file_list_manager = FileListManager(self.config)
    
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_complete_navigation_cycle(self):
        """Test complete navigation cycle with cursor positioning"""
        # Get left pane (starting in beta directory)
        left_pane = self.pane_manager.left_pane
        
        # Refresh files to populate the pane
        self.file_list_manager.refresh_files(left_pane)
        
        # Verify we're in beta directory
        self.assertEqual(str(left_pane['path']), str(self.beta_path))
        self.assertTrue(len(left_pane['files']) > 0)
        
        # Simulate the parent directory navigation logic
        # (This is what happens when Backspace is pressed)
        
        # 1. Save current cursor position (normally done by save_cursor_position)
        # 2. Remember child directory name
        child_directory_name = left_pane['path'].name  # Should be "beta"
        
        # 3. Navigate to parent
        left_pane['path'] = left_pane['path'].parent
        left_pane['focused_index'] = 0
        left_pane['scroll_offset'] = 0
        left_pane['selected_files'].clear()
        
        # 4. Refresh files in parent directory
        self.file_list_manager.refresh_files(left_pane)
        
        # 5. Try to set cursor to the child directory we came from
        cursor_set = False
        for i, file_path in enumerate(left_pane['files']):
            if file_path.name == child_directory_name and file_path.is_dir():
                left_pane['focused_index'] = i
                cursor_set = True
                break
        
        # Verify the navigation worked correctly
        self.assertTrue(cursor_set, "Cursor should be positioned on beta directory")
        self.assertEqual(str(left_pane['path']), str(self.temp_dir))
        
        # Verify the selected file is the beta directory
        selected_file = left_pane['files'][left_pane['focused_index']]
        self.assertEqual(selected_file.name, "beta")
        self.assertTrue(selected_file.is_dir())
        
        # Test that we can easily navigate back by "pressing Enter"
        # (Simulate entering the selected directory)
        if selected_file.is_dir():
            left_pane['path'] = selected_file
            left_pane['focused_index'] = 0
            left_pane['scroll_offset'] = 0
            left_pane['selected_files'].clear()
            self.file_list_manager.refresh_files(left_pane)
        
        # Verify we're back in beta directory
        self.assertEqual(str(left_pane['path']), str(self.beta_path))
    
    def test_navigation_with_file_operations(self):
        """Test navigation with actual file operations integration"""
        left_pane = self.pane_manager.left_pane
        
        # Start in alpha directory
        left_pane['path'] = XeFMPath(self.alpha_path)
        self.file_list_manager.refresh_files(left_pane)
        
        # Verify initial state
        self.assertEqual(str(left_pane['path']), str(self.alpha_path))
        
        # Simulate parent navigation
        child_name = left_pane['path'].name
        left_pane['path'] = left_pane['path'].parent
        left_pane['focused_index'] = 0
        left_pane['scroll_offset'] = 0
        left_pane['selected_files'].clear()
        
        # Use file operations to refresh
        self.file_list_manager.refresh_files(left_pane)
        
        # Find and select the child directory
        for i, file_path in enumerate(left_pane['files']):
            if file_path.name == child_name and file_path.is_dir():
                left_pane['focused_index'] = i
                break
        
        # Verify correct positioning
        selected_file = left_pane['files'][left_pane['focused_index']]
        self.assertEqual(selected_file.name, "alpha")
        self.assertTrue(selected_file.is_dir())
    
    def test_multiple_level_navigation(self):
        """Test navigation through multiple directory levels"""
        # Create deeper directory structure
        deep_path = self.alpha_path / "deep" / "deeper"
        deep_path.mkdir(parents=True)
        (deep_path / "deep_file.txt").write_text("deep content")
        
        left_pane = self.pane_manager.left_pane
        
        # Start in the deepest directory
        left_pane['path'] = XeFMPath(deep_path)
        self.file_list_manager.refresh_files(left_pane)
        
        # Navigate up one level (deeper -> deep)
        child_name = left_pane['path'].name  # "deeper"
        left_pane['path'] = left_pane['path'].parent
        left_pane['focused_index'] = 0
        left_pane['scroll_offset'] = 0
        left_pane['selected_files'].clear()
        self.file_list_manager.refresh_files(left_pane)
        
        # Find the child directory
        for i, file_path in enumerate(left_pane['files']):
            if file_path.name == child_name and file_path.is_dir():
                left_pane['focused_index'] = i
                break
        
        # Verify we're positioned on "deeper" directory
        selected_file = left_pane['files'][left_pane['focused_index']]
        self.assertEqual(selected_file.name, "deeper")
        
        # Navigate up another level (deep -> alpha)
        child_name = left_pane['path'].name  # "deep"
        left_pane['path'] = left_pane['path'].parent
        left_pane['focused_index'] = 0
        left_pane['scroll_offset'] = 0
        left_pane['selected_files'].clear()
        self.file_list_manager.refresh_files(left_pane)
        
        # Find the child directory
        for i, file_path in enumerate(left_pane['files']):
            if file_path.name == child_name and file_path.is_dir():
                left_pane['focused_index'] = i
                break
        
        # Verify we're positioned on "deep" directory
        selected_file = left_pane['files'][left_pane['focused_index']]
        self.assertEqual(selected_file.name, "deep")
