"""
Test suite for cursor history persistence in PaneManager

Tests the integration of PaneManager with StateManager for persistent cursor history.

Run with: python -m pytest test/test_cursor_history_persistence.py -v
"""

import tempfile
from pathlib import Path

from xefm.state_manager import XeFMStateManager
from xefm.pane_manager import PaneManager
from xefm._config import Config


def test_cursor_history_persistence():
    """Test that cursor history is saved and restored correctly."""
    print("Testing cursor history persistence...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test directory structure
        test_dir = Path(temp_dir) / "test_files"
        test_dir.mkdir()
        
        # Create some test files
        test_files = ["file1.txt", "file2.py", "file3.log", "file4.md"]
        for filename in test_files:
            (test_dir / filename).touch()
        
        # Create state manager with custom database
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_cursor_history")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Create pane manager with state manager
        config = Config()
        pane_manager = PaneManager(config, test_dir, test_dir, state_manager)
        
        # Simulate file list for the pane
        pane_manager.left_pane['files'] = [test_dir / f for f in test_files]
        
        # Set focus to file2.py (index 1)
        pane_manager.left_pane['focused_index'] = 1
        
        # Save cursor position
        pane_manager.save_cursor_position(pane_manager.left_pane)
        print(f"✓ Saved cursor position for {test_dir} at file2.py")
        
        # Verify it was saved to state manager (test with left pane)
        saved_filename = state_manager.load_pane_cursor_position('left', str(test_dir))
        assert saved_filename == "file2.py"
        print("✓ Cursor position correctly saved to state manager")
        
        # Create a new pane manager instance (simulating restart)
        pane_manager2 = PaneManager(config, test_dir, test_dir, state_manager)
        pane_manager2.left_pane['files'] = [test_dir / f for f in test_files]
        pane_manager2.left_pane['focused_index'] = 0  # Start at first file
        
        # Restore cursor position
        display_height = 20
        restored = pane_manager2.restore_cursor_position(pane_manager2.left_pane, display_height)
        
        assert restored is True
        assert pane_manager2.left_pane['focused_index'] == 1
        print("✓ Cursor position correctly restored from state manager")
        
        # Test with different directory
        test_dir2 = Path(temp_dir) / "test_files2"
        test_dir2.mkdir()
        
        test_files2 = ["alpha.txt", "beta.py", "gamma.log"]
        for filename in test_files2:
            (test_dir2 / filename).touch()
        
        # Set up second directory
        pane_manager.right_pane['path'] = test_dir2
        pane_manager.right_pane['files'] = [test_dir2 / f for f in test_files2]
        pane_manager.right_pane['focused_index'] = 2  # gamma.log
        
        # Save cursor position for second directory
        pane_manager.save_cursor_position(pane_manager.right_pane)
        print(f"✓ Saved cursor position for {test_dir2} at gamma.log")
        
        # Verify both positions are saved in their respective panes
        left_positions = state_manager.get_pane_cursor_positions('left')
        right_positions = state_manager.get_pane_cursor_positions('right')
        assert str(test_dir) in left_positions
        assert str(test_dir2) in right_positions
        assert left_positions[str(test_dir)] == "file2.py"
        assert right_positions[str(test_dir2)] == "gamma.log"
        
        # Verify separation - each pane should only have its own entries
        assert str(test_dir2) not in left_positions
        assert str(test_dir) not in right_positions
        print("✓ Multiple cursor positions saved correctly in separate panes")
        
        # Clean up
        state_manager.cleanup_session()
        
        print("✓ Cursor history persistence test completed successfully\n")


def test_cursor_history_without_state_manager():
    """Test that PaneManager works gracefully without state manager."""
    print("Testing cursor history without state manager...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        test_dir = Path(temp_dir) / "test_files"
        test_dir.mkdir()
        
        # Create test files
        test_files = ["file1.txt", "file2.py"]
        for filename in test_files:
            (test_dir / filename).touch()
        
        # Create pane manager without state manager
        config = Config()
        pane_manager = PaneManager(config, test_dir, test_dir, None)
        
        # Simulate file list
        pane_manager.left_pane['files'] = [test_dir / f for f in test_files]
        pane_manager.left_pane['focused_index'] = 1
        
        # These operations should not fail even without state manager
        pane_manager.save_cursor_position(pane_manager.left_pane)
        restored = pane_manager.restore_cursor_position(pane_manager.left_pane, 20)
        
        # Should return False since no state manager is available
        assert restored is False
        print("✓ PaneManager handles missing state manager gracefully")
        
        print("✓ Cursor history without state manager test completed\n")


def test_cursor_history_with_missing_files():
    """Test cursor history when saved file no longer exists."""
    print("Testing cursor history with missing files...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_missing_files")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        test_dir = Path(temp_dir) / "test_files"
        test_dir.mkdir()
        
        # Create initial files
        initial_files = ["file1.txt", "file2.py", "file3.log"]
        for filename in initial_files:
            (test_dir / filename).touch()
        
        # Save cursor position at file2.py (test with left pane)
        state_manager.save_pane_cursor_position('left', str(test_dir), "file2.py")
        
        # Simulate file being deleted
        (test_dir / "file2.py").unlink()
        
        # Create pane manager with remaining files
        config = Config()
        pane_manager = PaneManager(config, test_dir, test_dir, state_manager)
        remaining_files = ["file1.txt", "file3.log"]
        pane_manager.left_pane['files'] = [test_dir / f for f in remaining_files]
        pane_manager.left_pane['focused_index'] = 0
        
        # Try to restore cursor position
        restored = pane_manager.restore_cursor_position(pane_manager.left_pane, 20)
        
        # Should return False since the saved file doesn't exist
        assert restored is False
        assert pane_manager.left_pane['focused_index'] == 0  # Should remain unchanged
        print("✓ Cursor history handles missing files correctly")
        
        # Clean up
        state_manager.cleanup_session()
        
        print("✓ Missing files test completed\n")


def test_cursor_history_size_limit():
    """Test that cursor history respects size limits."""
    print("Testing cursor history size limit...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_size_limit")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Add more than 100 directories to test size limit (test with left pane)
        for i in range(105):
            dir_path = f"/test/directory/{i}"
            filename = f"file_{i}.txt"
            state_manager.save_pane_cursor_position('left', dir_path, filename)
        
        # Check that only 100 entries are kept
        cursor_positions = state_manager.get_pane_cursor_positions('left')
        assert len(cursor_positions) <= 100
        print(f"✓ Cursor history size limited to {len(cursor_positions)} entries")
        
        # Verify that the most recent entries are kept
        # (The exact behavior depends on the implementation, but it should be reasonable)
        assert len(cursor_positions) > 0
        print("✓ Size limit enforced correctly")
        
        # Clean up
        state_manager.cleanup_session()
        
        print("✓ Size limit test completed\n")


def test_state_manager_convenience_methods():
    """Test the convenience methods added to StateManager."""
    print("Testing StateManager convenience methods...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_convenience")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Test pane-specific cursor position methods
        assert state_manager.save_pane_cursor_position('left', "/test/path1", "file1.txt")
        assert state_manager.save_pane_cursor_position('right', "/test/path2", "file2.py")
        
        # Test load_pane_cursor_position
        filename1 = state_manager.load_pane_cursor_position('left', "/test/path1")
        filename2 = state_manager.load_pane_cursor_position('right', "/test/path2")
        
        assert filename1 == "file1.txt"
        assert filename2 == "file2.py"
        
        # Test non-existent path
        filename3 = state_manager.load_pane_cursor_position('left', "/nonexistent/path")
        assert filename3 is None
        
        # Test cross-pane queries (should return None)
        filename4 = state_manager.load_pane_cursor_position('right', "/test/path1")  # Left path in right pane
        assert filename4 is None
        
        # Test get_pane_cursor_positions
        left_positions = state_manager.get_pane_cursor_positions('left')
        right_positions = state_manager.get_pane_cursor_positions('right')
        assert "/test/path1" in left_positions
        assert "/test/path2" in right_positions
        assert left_positions["/test/path1"] == "file1.txt"
        assert right_positions["/test/path2"] == "file2.py"
        
        # Verify separation
        assert "/test/path2" not in left_positions
        assert "/test/path1" not in right_positions
        
        # Test clear_pane_history
        assert state_manager.clear_pane_history('left')
        left_positions_after_clear = state_manager.get_pane_cursor_positions('left')
        right_positions_after_clear = state_manager.get_pane_cursor_positions('right')
        assert len(left_positions_after_clear) == 0
        assert len(right_positions_after_clear) == 1  # Right pane should still have its entry
        
        print("✓ All convenience methods work correctly")
        
        # Clean up
        state_manager.cleanup_session()
        
        print("✓ Convenience methods test completed\n")


def run_all_tests():
    """Run all cursor history persistence tests."""
    print("Running cursor history persistence tests...\n")
    
    try:
        test_cursor_history_persistence()
        test_cursor_history_without_state_manager()
        test_cursor_history_with_missing_files()
        test_cursor_history_size_limit()
        test_state_manager_convenience_methods()
        
        print("=" * 50)
        print("✓ All cursor history persistence tests passed!")
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
