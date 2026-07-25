"""
Test directory existence check during startup.

This test verifies that XeFM checks the existence of directories
before restoring cursor positions and removes non-existing ones
from the cursor history.

Run with: python -m pytest test/test_directory_existence_check.py -v
"""

from pathlib import Path
import tempfile
import shutil

from xefm.state_manager import XeFMStateManager


def test_directory_existence_check():
    """Test that non-existing directories are removed from cursor history during startup."""
    
    # Create temporary directories for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test directories
        existing_dir = temp_path / "existing_dir"
        existing_dir.mkdir()
        
        non_existing_dir = temp_path / "non_existing_dir"
        non_existing_dir.mkdir()  # Create it first
        
        # Create a temporary state database
        state_db_path = temp_path / "test_state.db"
        state_manager = XeFMStateManager()
        # Override the database path for testing
        state_manager.db_path = state_db_path
        state_manager._initialize_database()
        
        # Save cursor positions for both directories
        state_manager.save_pane_cursor_position("left", str(existing_dir), "file1.txt")
        state_manager.save_pane_cursor_position("left", str(non_existing_dir), "file2.txt")
        
        # Verify both entries exist in history
        history_before = state_manager.get_pane_cursor_positions("left")
        assert str(existing_dir) in history_before
        assert str(non_existing_dir) in history_before
        print(f"Before cleanup - History entries: {len(history_before)}")
        
        # Now remove the non-existing directory
        shutil.rmtree(non_existing_dir)
        assert not non_existing_dir.exists()
        
        # This is where we need to implement the cleanup
        # For now, let's verify the current behavior
        history_after = state_manager.get_pane_cursor_positions("left")
        print(f"After directory removal - History entries: {len(history_after)}")
        
        # Currently, both entries still exist (this is the problem we need to fix)
        assert str(existing_dir) in history_after
        assert str(non_existing_dir) in history_after  # This should be removed
        
        print("Test shows current behavior: non-existing directories remain in history")
        return


def test_cleanup_non_existing_directories():
    """Test the cleanup function for non-existing directories."""
    
    # Create temporary directories for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test directories
        existing_dir1 = temp_path / "existing_dir1"
        existing_dir1.mkdir()
        
        existing_dir2 = temp_path / "existing_dir2"
        existing_dir2.mkdir()
        
        non_existing_dir1 = temp_path / "non_existing_dir1"
        non_existing_dir1.mkdir()  # Create it first
        
        non_existing_dir2 = temp_path / "non_existing_dir2"
        non_existing_dir2.mkdir()  # Create it first
        
        # Create a temporary state database
        state_db_path = temp_path / "test_state.db"
        state_manager = XeFMStateManager()
        # Override the database path for testing
        state_manager.db_path = state_db_path
        state_manager._initialize_database()
        
        # Save cursor positions for all directories
        state_manager.save_pane_cursor_position("left", str(existing_dir1), "file1.txt")
        state_manager.save_pane_cursor_position("left", str(existing_dir2), "file2.txt")
        state_manager.save_pane_cursor_position("left", str(non_existing_dir1), "file3.txt")
        state_manager.save_pane_cursor_position("left", str(non_existing_dir2), "file4.txt")
        
        state_manager.save_pane_cursor_position("right", str(existing_dir1), "file5.txt")
        state_manager.save_pane_cursor_position("right", str(non_existing_dir1), "file6.txt")
        
        # Verify all entries exist in history
        left_history_before = state_manager.get_pane_cursor_positions("left")
        right_history_before = state_manager.get_pane_cursor_positions("right")
        
        assert len(left_history_before) == 4
        assert len(right_history_before) == 2
        
        # Remove the non-existing directories
        shutil.rmtree(non_existing_dir1)
        shutil.rmtree(non_existing_dir2)
        
        # Call the cleanup function (to be implemented)
        state_manager.cleanup_non_existing_directories()
        
        # Verify only existing directories remain
        left_history_after = state_manager.get_pane_cursor_positions("left")
        right_history_after = state_manager.get_pane_cursor_positions("right")
        
        assert len(left_history_after) == 2
        assert len(right_history_after) == 1
        
        assert str(existing_dir1) in left_history_after
        assert str(existing_dir2) in left_history_after
        assert str(non_existing_dir1) not in left_history_after
        assert str(non_existing_dir2) not in left_history_after
        
        assert str(existing_dir1) in right_history_after
        assert str(non_existing_dir1) not in right_history_after
        
        print("Cleanup function successfully removed non-existing directories")
        return
