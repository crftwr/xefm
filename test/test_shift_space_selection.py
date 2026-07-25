"""Test Shift+Space key binding for selecting and moving up.

Run with: python -m pytest test/test_shift_space_selection.py -v
"""

import pytest
from pathlib import Path
from xefm.file_list_manager import FileListManager


class MockConfig:
    """Mock configuration for testing"""
    SHOW_HIDDEN_FILES = False
    MAX_EXTENSION_LENGTH = 5


class TestShiftSpaceSelection:
    """Test suite for Shift+Space selection functionality."""
    
    def test_toggle_selection_up_moves_cursor_up(self, tmp_path):
        """Test that toggle_selection with direction=-1 moves cursor up."""
        # Create test files
        for i in range(5):
            (tmp_path / f"file{i}.txt").touch()
        
        # Setup pane data
        pane_data = {
            'path': tmp_path,
            'files': sorted(tmp_path.iterdir()),
            'focused_index': 2,  # Start at middle file
            'selected_files': set()
        }
        
        file_ops = FileListManager(MockConfig())
        
        # Toggle selection and move up
        success, message = file_ops.toggle_selection(pane_data, move_cursor=True, direction=-1)
        
        assert success
        assert pane_data['focused_index'] == 1  # Moved up from 2 to 1
        assert str(pane_data['files'][2]) in pane_data['selected_files']  # Original file selected
    
    def test_toggle_selection_up_at_top(self, tmp_path):
        """Test that toggle_selection at top doesn't move cursor below 0."""
        # Create test files
        for i in range(3):
            (tmp_path / f"file{i}.txt").touch()
        
        # Setup pane data at top
        pane_data = {
            'path': tmp_path,
            'files': sorted(tmp_path.iterdir()),
            'focused_index': 0,  # At top
            'selected_files': set()
        }
        
        file_ops = FileListManager(MockConfig())
        
        # Toggle selection and try to move up
        success, message = file_ops.toggle_selection(pane_data, move_cursor=True, direction=-1)
        
        assert success
        assert pane_data['focused_index'] == 0  # Stays at 0
        assert str(pane_data['files'][0]) in pane_data['selected_files']
    
    def test_toggle_selection_down_moves_cursor_down(self, tmp_path):
        """Test that toggle_selection with direction=1 moves cursor down (Space key)."""
        # Create test files
        for i in range(5):
            (tmp_path / f"file{i}.txt").touch()
        
        # Setup pane data
        pane_data = {
            'path': tmp_path,
            'files': sorted(tmp_path.iterdir()),
            'focused_index': 2,  # Start at middle file
            'selected_files': set()
        }
        
        file_ops = FileListManager(MockConfig())
        
        # Toggle selection and move down
        success, message = file_ops.toggle_selection(pane_data, move_cursor=True, direction=1)
        
        assert success
        assert pane_data['focused_index'] == 3  # Moved down from 2 to 3
        assert str(pane_data['files'][2]) in pane_data['selected_files']  # Original file selected
    
    def test_toggle_selection_deselects_on_second_press(self, tmp_path):
        """Test that pressing Shift+Space twice toggles selection off."""
        # Create test files
        for i in range(3):
            (tmp_path / f"file{i}.txt").touch()
        
        # Setup pane data
        pane_data = {
            'path': tmp_path,
            'files': sorted(tmp_path.iterdir()),
            'focused_index': 1,
            'selected_files': set()
        }
        
        file_ops = FileListManager(MockConfig())
        
        # First press - select and move up
        success1, message1 = file_ops.toggle_selection(pane_data, move_cursor=True, direction=-1)
        assert success1
        assert pane_data['focused_index'] == 0
        file_path = str(pane_data['files'][1])
        assert file_path in pane_data['selected_files']
        
        # Move back to the selected file
        pane_data['focused_index'] = 1
        
        # Second press - deselect and move up
        success2, message2 = file_ops.toggle_selection(pane_data, move_cursor=True, direction=-1)
        assert success2
        assert pane_data['focused_index'] == 0
        assert file_path not in pane_data['selected_files']  # Deselected
