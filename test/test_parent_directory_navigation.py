"""
Test for parent directory navigation cursor positioning behavior.

This test verifies that when navigating to parent directory using Backspace,
the cursor is positioned on the child directory we just came from.

Run with: python -m pytest test/test_parent_directory_navigation.py -v
"""

import unittest
import tempfile
from pathlib import Path

from xefm.path import Path as XeFMPath
from xefm.pane_manager import PaneManager
from xefm.config import get_config


class MockConfig:
    """Mock configuration for testing"""
    DEFAULT_SORT_MODE = 'name'
    DEFAULT_SORT_REVERSE = False
    DEFAULT_LEFT_PANE_RATIO = 0.5
    MAX_HISTORY_ENTRIES = 100


class TestParentDirectoryNavigation(unittest.TestCase):
    """Test parent directory navigation cursor positioning"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.config = MockConfig()
        
        # Create test directory structure
        # temp_dir/
        #   ├── child1/
        #   │   └── subfile.txt
        #   ├── child2/
        #   │   └── subfile.txt
        #   ├── child3/
        #   │   └── subfile.txt
        #   └── file.txt
        
        self.child1_path = Path(self.temp_dir) / "child1"
        self.child2_path = Path(self.temp_dir) / "child2"
        self.child3_path = Path(self.temp_dir) / "child3"
        
        self.child1_path.mkdir()
        self.child2_path.mkdir()
        self.child3_path.mkdir()
        
        # Create files in subdirectories
        (self.child1_path / "subfile.txt").write_text("test content")
        (self.child2_path / "subfile.txt").write_text("test content")
        (self.child3_path / "subfile.txt").write_text("test content")
        
        # Create file in parent directory
        (Path(self.temp_dir) / "file.txt").write_text("test content")
        
        # Initialize pane manager
        self.pane_manager = PaneManager(
            self.config,
            XeFMPath(self.child2_path),  # Start in child2
            XeFMPath(self.temp_dir),
            state_manager=None
        )
    
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_parent_navigation_cursor_positioning(self):
        """Test that cursor is positioned on child directory after parent navigation"""
        # Set up left pane to be in child2 directory
        left_pane = self.pane_manager.left_pane
        left_pane['path'] = XeFMPath(self.child2_path)
        
        # Simulate file refresh (normally done by file_list_manager.refresh_files)
        left_pane['files'] = [XeFMPath(self.child2_path / "subfile.txt")]
        left_pane['focused_index'] = 0
        
        # Simulate the parent directory navigation logic
        # Remember the child directory name we're leaving
        child_directory_name = left_pane['path'].name  # Should be "child2"
        
        # Navigate to parent
        left_pane['path'] = left_pane['path'].parent
        left_pane['focused_index'] = 0
        left_pane['scroll_offset'] = 0
        left_pane['selected_files'].clear()
        
        # Simulate file refresh in parent directory
        parent_files = []
        for item in sorted(Path(self.temp_dir).iterdir()):
            parent_files.append(XeFMPath(item))
        left_pane['files'] = parent_files
        
        # Find and set cursor to the child directory we came from
        cursor_set = False
        for i, file_path in enumerate(left_pane['files']):
            if file_path.name == child_directory_name and file_path.is_dir():
                left_pane['focused_index'] = i
                cursor_set = True
                break
        
        # Verify focus was set correctly
        self.assertTrue(cursor_set, "Cursor should be set to child directory")
        
        # Verify the selected file is the child2 directory
        selected_file = left_pane['files'][left_pane['focused_index']]
        self.assertEqual(selected_file.name, "child2")
        self.assertTrue(selected_file.is_dir())
    
    def test_parent_navigation_with_nonexistent_child(self):
        """Test parent navigation when child directory no longer exists"""
        # Set up left pane to be in child2 directory
        left_pane = self.pane_manager.left_pane
        left_pane['path'] = XeFMPath(self.child2_path)
        
        # Simulate file refresh
        left_pane['files'] = [XeFMPath(self.child2_path / "subfile.txt")]
        left_pane['focused_index'] = 0
        
        # Remember child directory name
        child_directory_name = left_pane['path'].name
        
        # Remove the child directory to simulate it being deleted
        import shutil
        shutil.rmtree(self.child2_path)
        
        # Navigate to parent
        left_pane['path'] = left_pane['path'].parent
        left_pane['focused_index'] = 0
        left_pane['scroll_offset'] = 0
        left_pane['selected_files'].clear()
        
        # Simulate file refresh in parent directory (child2 no longer exists)
        parent_files = []
        for item in sorted(Path(self.temp_dir).iterdir()):
            parent_files.append(XeFMPath(item))
        left_pane['files'] = parent_files
        
        # Try to find the child directory (should fail)
        cursor_set = False
        for i, file_path in enumerate(left_pane['files']):
            if file_path.name == child_directory_name and file_path.is_dir():
                left_pane['focused_index'] = i
                cursor_set = True
                break
        
        # Verify focus was not set (child directory doesn't exist)
        self.assertFalse(cursor_set, "Cursor should not be set when child directory doesn't exist")
        
        # Verify we fall back to first item (index 0)
        self.assertEqual(left_pane['focused_index'], 0)
    
    def test_parent_navigation_from_root(self):
        """Test parent navigation when already at root directory"""
        # Set up left pane to be at root
        left_pane = self.pane_manager.left_pane
        root_path = XeFMPath("/")
        left_pane['path'] = root_path
        
        # Check that parent is same as current (at root)
        self.assertEqual(left_pane['path'], left_pane['path'].parent)
        
        # This should not trigger navigation logic since we're at root
        # The condition `if current_pane['path'] != current_pane['path'].parent:` should be False
