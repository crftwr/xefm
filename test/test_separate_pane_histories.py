"""
Test suite for separate pane cursor histories

Tests that left and right panes maintain completely separate cursor histories
and do not interfere with each other.

Run with: python -m pytest test/test_separate_pane_histories.py -v
"""

import tempfile
import time
from pathlib import Path

from xefm.state_manager import XeFMStateManager
from xefm.pane_manager import PaneManager
from xefm._config import Config


class TestConfig(Config):
    """Test configuration with custom cursor history limit"""
    MAX_CURSOR_HISTORY_ENTRIES = 5  # Small limit for testing


def test_separate_pane_histories_basic():
    """Test that left and right panes maintain separate cursor histories."""
    print("Testing separate pane histories...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_separate_basic")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Test saving cursor positions for different panes
        left_entries = [
            ("/left/path1", "left_file1.txt"),
            ("/left/path2", "left_file2.py"),
            ("/left/path3", "left_file3.log"),
        ]
        
        right_entries = [
            ("/right/path1", "right_file1.txt"),
            ("/right/path2", "right_file2.py"),
            ("/right/path3", "right_file3.log"),
        ]
        
        print("Saving cursor positions for left pane...")
        for i, (path, filename) in enumerate(left_entries):
            time.sleep(0.01)  # Ensure different timestamps
            success = state_manager.save_pane_cursor_position('left', path, filename, max_entries=10)
            assert success
            print(f"  {i+1}. {path} -> {filename}")
        
        print("Saving cursor positions for right pane...")
        for i, (path, filename) in enumerate(right_entries):
            time.sleep(0.01)  # Ensure different timestamps
            success = state_manager.save_pane_cursor_position('right', path, filename, max_entries=10)
            assert success
            print(f"  {i+1}. {path} -> {filename}")
        
        # Verify left pane history
        left_history = state_manager.get_ordered_pane_history('left')
        left_paths = [entry['path'] for entry in left_history]
        expected_left_paths = [path for path, _ in left_entries]
        assert left_paths == expected_left_paths
        
        # Verify right pane history
        right_history = state_manager.get_ordered_pane_history('right')
        right_paths = [entry['path'] for entry in right_history]
        expected_right_paths = [path for path, _ in right_entries]
        assert right_paths == expected_right_paths
        
        # Verify histories are completely separate
        for left_entry in left_history:
            assert left_entry['path'] not in right_paths
        
        for right_entry in right_history:
            assert right_entry['path'] not in left_paths
        
        print("✓ Left and right pane histories are completely separate")
        
        # Test loading specific positions
        left_file = state_manager.load_pane_cursor_position('left', '/left/path2')
        right_file = state_manager.load_pane_cursor_position('right', '/right/path2')
        
        assert left_file == 'left_file2.py'
        assert right_file == 'right_file2.py'
        
        # Cross-pane queries should return None
        assert state_manager.load_pane_cursor_position('left', '/right/path1') is None
        assert state_manager.load_pane_cursor_position('right', '/left/path1') is None
        
        print("✓ Cross-pane queries correctly return None")
        
        # Clean up
        state_manager.cleanup_session()
        print("✓ Basic separate histories test completed\n")


def test_pane_manager_integration_separate():
    """Test PaneManager integration with separate pane histories."""
    print("Testing PaneManager integration with separate histories...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test directory structure
        left_dirs = []
        right_dirs = []
        
        for i in range(3):
            # Left pane directories
            left_dir = Path(temp_dir) / f"left_dir_{i}"
            left_dir.mkdir()
            for j in range(3):
                (left_dir / f"left_file_{j}.txt").touch()
            left_dirs.append(left_dir)
            
            # Right pane directories
            right_dir = Path(temp_dir) / f"right_dir_{i}"
            right_dir.mkdir()
            for j in range(3):
                (right_dir / f"right_file_{j}.txt").touch()
            right_dirs.append(right_dir)
        
        # Create state manager and pane manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_pane_separate")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        config = TestConfig()
        pane_manager = PaneManager(config, left_dirs[0], right_dirs[0], state_manager)
        
        # Navigate left pane through directories
        print("Navigating left pane:")
        left_navigation = [
            (left_dirs[0], 1),  # left_file_1.txt
            (left_dirs[1], 2),  # left_file_2.txt
            (left_dirs[2], 0),  # left_file_0.txt
        ]
        
        for i, (directory, file_index) in enumerate(left_navigation):
            pane_manager.left_pane['path'] = directory
            pane_manager.left_pane['files'] = [directory / f"left_file_{j}.txt" for j in range(3)]
            pane_manager.left_pane['focused_index'] = file_index
            
            pane_manager.save_cursor_position(pane_manager.left_pane)
            
            selected_file = pane_manager.left_pane['files'][file_index].name
            print(f"  {i+1}. {directory} -> {selected_file}")
            time.sleep(0.01)
        
        # Navigate right pane through directories
        print("Navigating right pane:")
        right_navigation = [
            (right_dirs[0], 2),  # right_file_2.txt
            (right_dirs[1], 0),  # right_file_0.txt
            (right_dirs[2], 1),  # right_file_1.txt
        ]
        
        for i, (directory, file_index) in enumerate(right_navigation):
            pane_manager.right_pane['path'] = directory
            pane_manager.right_pane['files'] = [directory / f"right_file_{j}.txt" for j in range(3)]
            pane_manager.right_pane['focused_index'] = file_index
            
            pane_manager.save_cursor_position(pane_manager.right_pane)
            
            selected_file = pane_manager.right_pane['files'][file_index].name
            print(f"  {i+1}. {directory} -> {selected_file}")
            time.sleep(0.01)
        
        # Test restoration for left pane
        print("\nTesting left pane restoration:")
        for directory, expected_file_index in left_navigation:
            pane_manager.left_pane['path'] = directory
            pane_manager.left_pane['files'] = [directory / f"left_file_{j}.txt" for j in range(3)]
            pane_manager.left_pane['focused_index'] = 0  # Start at first file
            
            restored = pane_manager.restore_cursor_position(pane_manager.left_pane, 20)
            
            assert restored is True
            assert pane_manager.left_pane['focused_index'] == expected_file_index
            
            restored_file = pane_manager.left_pane['files'][expected_file_index].name
            print(f"  ✓ {directory} -> {restored_file} (index {expected_file_index})")
        
        # Test restoration for right pane
        print("Testing right pane restoration:")
        for directory, expected_file_index in right_navigation:
            pane_manager.right_pane['path'] = directory
            pane_manager.right_pane['files'] = [directory / f"right_file_{j}.txt" for j in range(3)]
            pane_manager.right_pane['focused_index'] = 0  # Start at first file
            
            restored = pane_manager.restore_cursor_position(pane_manager.right_pane, 20)
            
            assert restored is True
            assert pane_manager.right_pane['focused_index'] == expected_file_index
            
            restored_file = pane_manager.right_pane['files'][expected_file_index].name
            print(f"  ✓ {directory} -> {restored_file} (index {expected_file_index})")
        
        # Verify histories are separate
        left_history = state_manager.get_ordered_pane_history('left')
        right_history = state_manager.get_ordered_pane_history('right')
        
        left_paths = [entry['path'] for entry in left_history]
        right_paths = [entry['path'] for entry in right_history]
        
        # No overlap between left and right histories
        assert not any(path in right_paths for path in left_paths)
        assert not any(path in left_paths for path in right_paths)
        
        print(f"✓ Left pane history: {len(left_history)} entries")
        print(f"✓ Right pane history: {len(right_history)} entries")
        print("✓ No overlap between pane histories")
        
        # Clean up
        state_manager.cleanup_session()
        print("✓ PaneManager integration test completed\n")


def test_pane_history_size_limits():
    """Test that each pane respects its own size limits independently."""
    print("Testing independent pane history size limits...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_size_limits")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        max_entries = 3
        
        # Add entries to left pane (more than limit)
        print(f"Adding entries to left pane (limit: {max_entries}):")
        for i in range(5):
            path = f"/left/path_{i}"
            filename = f"left_file_{i}.txt"
            success = state_manager.save_pane_cursor_position('left', path, filename, max_entries=max_entries)
            assert success
            print(f"  {i+1}. {path} -> {filename}")
            time.sleep(0.01)
        
        # Add entries to right pane (more than limit)
        print(f"Adding entries to right pane (limit: {max_entries}):")
        for i in range(4):
            path = f"/right/path_{i}"
            filename = f"right_file_{i}.txt"
            success = state_manager.save_pane_cursor_position('right', path, filename, max_entries=max_entries)
            assert success
            print(f"  {i+1}. {path} -> {filename}")
            time.sleep(0.01)
        
        # Check left pane history size
        left_history = state_manager.get_ordered_pane_history('left')
        assert len(left_history) == max_entries
        
        # Should contain the last 3 entries (paths 2, 3, 4)
        left_paths = [entry['path'] for entry in left_history]
        expected_left = ["/left/path_2", "/left/path_3", "/left/path_4"]
        assert left_paths == expected_left
        
        # Check right pane history size
        right_history = state_manager.get_ordered_pane_history('right')
        assert len(right_history) == max_entries
        
        # Should contain the last 3 entries (paths 1, 2, 3)
        right_paths = [entry['path'] for entry in right_history]
        expected_right = ["/right/path_1", "/right/path_2", "/right/path_3"]
        assert right_paths == expected_right
        
        print(f"✓ Left pane limited to {len(left_history)} entries: {[Path(p).name for p in left_paths]}")
        print(f"✓ Right pane limited to {len(right_history)} entries: {[Path(p).name for p in right_paths]}")
        
        # Clean up
        state_manager.cleanup_session()
        print("✓ Size limits test completed\n")


def test_pane_history_persistence():
    """Test that separate pane histories persist across sessions."""
    print("Testing pane history persistence across sessions...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test_state.db"
        
        # === Session 1: Create separate histories ===
        print("--- Session 1: Creating separate histories ---")
        state_manager1 = XeFMStateManager("session1")
        state_manager1.db_path = db_path
        state_manager1._initialize_database()
        
        # Left pane entries
        left_entries = [
            ("/home/user/left", "left_doc.txt"),
            ("/tmp/left", "left_temp.log"),
        ]
        
        # Right pane entries
        right_entries = [
            ("/home/user/right", "right_doc.txt"),
            ("/tmp/right", "right_temp.log"),
        ]
        
        for path, filename in left_entries:
            state_manager1.save_pane_cursor_position('left', path, filename, max_entries=10)
            print(f"  Left: {path} -> {filename}")
            time.sleep(0.01)
        
        for path, filename in right_entries:
            state_manager1.save_pane_cursor_position('right', path, filename, max_entries=10)
            print(f"  Right: {path} -> {filename}")
            time.sleep(0.01)
        
        # Get histories from session 1
        left_history1 = state_manager1.get_ordered_pane_history('left')
        right_history1 = state_manager1.get_ordered_pane_history('right')
        
        # Clean up session 1
        state_manager1.cleanup_session()
        print("Session 1 ended")
        
        # === Session 2: Verify persistence ===
        print("\n--- Session 2: Verifying persistence ---")
        state_manager2 = XeFMStateManager("session2")
        state_manager2.db_path = db_path
        
        # Load histories from session 2
        left_history2 = state_manager2.get_ordered_pane_history('left')
        right_history2 = state_manager2.get_ordered_pane_history('right')
        
        # Verify left pane history persisted
        left_paths1 = [entry['path'] for entry in left_history1]
        left_paths2 = [entry['path'] for entry in left_history2]
        assert left_paths1 == left_paths2
        
        # Verify right pane history persisted
        right_paths1 = [entry['path'] for entry in right_history1]
        right_paths2 = [entry['path'] for entry in right_history2]
        assert right_paths1 == right_paths2
        
        print(f"✓ Left pane history persisted: {left_paths2}")
        print(f"✓ Right pane history persisted: {right_paths2}")
        
        # Verify they're still separate
        assert not any(path in right_paths2 for path in left_paths2)
        assert not any(path in left_paths2 for path in right_paths2)
        
        print("✓ Histories remain separate after persistence")
        
        # Clean up session 2
        state_manager2.cleanup_session()
        print("Session 2 ended")
        
        print("✓ Persistence test completed\n")


def test_clear_individual_pane_histories():
    """Test clearing individual pane histories without affecting the other."""
    print("Testing individual pane history clearing...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_clear_individual")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Add entries to both panes
        state_manager.save_pane_cursor_position('left', '/left/path1', 'left_file1.txt')
        state_manager.save_pane_cursor_position('left', '/left/path2', 'left_file2.txt')
        state_manager.save_pane_cursor_position('right', '/right/path1', 'right_file1.txt')
        state_manager.save_pane_cursor_position('right', '/right/path2', 'right_file2.txt')
        
        # Verify both panes have entries
        left_history = state_manager.get_ordered_pane_history('left')
        right_history = state_manager.get_ordered_pane_history('right')
        
        assert len(left_history) == 2
        assert len(right_history) == 2
        print("✓ Both panes have entries")
        
        # Clear only left pane
        success = state_manager.clear_pane_history('left')
        assert success
        
        # Verify left pane is cleared but right pane is intact
        left_history_after = state_manager.get_ordered_pane_history('left')
        right_history_after = state_manager.get_ordered_pane_history('right')
        
        assert len(left_history_after) == 0
        assert len(right_history_after) == 2
        
        print("✓ Left pane cleared, right pane intact")
        
        # Clear right pane
        success = state_manager.clear_pane_history('right')
        assert success
        
        # Verify right pane is now cleared
        right_history_final = state_manager.get_ordered_pane_history('right')
        assert len(right_history_final) == 0
        
        print("✓ Right pane cleared")
        
        # Clean up
        state_manager.cleanup_session()
        print("✓ Individual clearing test completed\n")


def run_all_tests():
    """Run all separate pane history tests."""
    print("Running separate pane cursor history tests...\n")
    
    try:
        test_separate_pane_histories_basic()
        test_pane_manager_integration_separate()
        test_pane_history_size_limits()
        test_pane_history_persistence()
        test_clear_individual_pane_histories()
        
        print("=" * 60)
        print("✓ All separate pane history tests passed!")
        print("\nKey features verified:")
        print("  • Left and right panes maintain completely separate histories")
        print("  • No cross-contamination between pane histories")
        print("  • Independent size limits for each pane")
        print("  • Separate persistence across XeFM sessions")
        print("  • Individual pane history clearing")
        print("  • PaneManager integration with separate histories")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
