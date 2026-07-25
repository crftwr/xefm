"""
Test startup directory cleanup integration.

This test verifies that XeFM properly cleans up non-existing directories
from cursor history during the startup process.

Run with: python -m pytest test/test_startup_directory_cleanup.py -v
"""

import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from xefm.state_manager import XeFMStateManager


class MockFileManager:
    """Mock FileManager class for testing startup behavior."""
    
    def __init__(self, temp_dir):
        self.temp_dir = Path(temp_dir)
        
        # Create a temporary state database
        state_db_path = self.temp_dir / "test_state.db"
        self.state_manager = XeFMStateManager()
        self.state_manager.db_path = state_db_path
        self.state_manager._initialize_database()
        
        # Mock pane manager
        self.pane_manager = Mock()
        self.pane_manager.left_pane = {'path': self.temp_dir / 'left_start'}
        self.pane_manager.right_pane = {'path': self.temp_dir / 'right_start'}
        
        # Mock other components
        self.log_height_ratio = 0.25
        
    def refresh_files(self):
        """Mock refresh files method."""
        pass
        
    def restore_startup_cursor_positions(self):
        """Mock cursor position restoration."""
        pass
    
    def load_application_state(self):
        """Load saved application state from persistent storage."""
        try:
            # Update session heartbeat
            self.state_manager.update_session_heartbeat()
            
            # Clean up non-existing directories from cursor history before restoring state
            self.state_manager.cleanup_non_existing_directories()
            
            # Load window layout (simplified for test)
            layout = self.state_manager.load_window_layout()
            if layout:
                self.log_height_ratio = layout.get('log_height_ratio', 0.25)
                print(f"Restored window layout: log {int(self.log_height_ratio*100)}%")
            
            # Load pane states (simplified for test)
            left_state = self.state_manager.load_pane_state('left')
            if left_state and Path(left_state['path']).exists():
                self.pane_manager.left_pane['path'] = Path(left_state['path'])
                print(f"Restored left pane: {left_state['path']}")
            
            right_state = self.state_manager.load_pane_state('right')
            if right_state and Path(right_state['path']).exists():
                self.pane_manager.right_pane['path'] = Path(right_state['path'])
                print(f"Restored right pane: {right_state['path']}")
            
            # Refresh file lists after loading state
            self.refresh_files()
            
            # Restore cursor positions after files are loaded
            self.restore_startup_cursor_positions()
            
        except Exception as e:
            print(f"Warning: Could not load application state: {e}")


def test_startup_directory_cleanup():
    """Test that startup process cleans up non-existing directories."""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test directories
        existing_dir1 = temp_path / "existing_dir1"
        existing_dir1.mkdir()
        
        existing_dir2 = temp_path / "existing_dir2"
        existing_dir2.mkdir()
        
        non_existing_dir1 = temp_path / "non_existing_dir1"
        non_existing_dir1.mkdir()
        
        non_existing_dir2 = temp_path / "non_existing_dir2"
        non_existing_dir2.mkdir()
        
        # Create mock file manager
        fm = MockFileManager(temp_dir)
        
        # Save cursor positions for all directories
        fm.state_manager.save_pane_cursor_position("left", str(existing_dir1), "file1.txt")
        fm.state_manager.save_pane_cursor_position("left", str(existing_dir2), "file2.txt")
        fm.state_manager.save_pane_cursor_position("left", str(non_existing_dir1), "file3.txt")
        fm.state_manager.save_pane_cursor_position("left", str(non_existing_dir2), "file4.txt")
        
        fm.state_manager.save_pane_cursor_position("right", str(existing_dir1), "file5.txt")
        fm.state_manager.save_pane_cursor_position("right", str(non_existing_dir1), "file6.txt")
        
        # Save some pane states
        fm.state_manager.save_pane_state('left', {'path': str(existing_dir1)})
        fm.state_manager.save_pane_state('right', {'path': str(existing_dir2)})
        
        # Verify all entries exist in history before cleanup
        left_history_before = fm.state_manager.get_pane_cursor_positions("left")
        right_history_before = fm.state_manager.get_pane_cursor_positions("right")
        
        print(f"Before startup - Left history: {len(left_history_before)} entries")
        print(f"Before startup - Right history: {len(right_history_before)} entries")
        
        assert len(left_history_before) == 4
        assert len(right_history_before) == 2
        
        # Remove some directories to simulate them being deleted
        shutil.rmtree(non_existing_dir1)
        shutil.rmtree(non_existing_dir2)
        
        # Simulate startup process
        print("\n--- Simulating XeFM startup ---")
        fm.load_application_state()
        
        # Verify cleanup occurred
        left_history_after = fm.state_manager.get_pane_cursor_positions("left")
        right_history_after = fm.state_manager.get_pane_cursor_positions("right")
        
        print(f"\nAfter startup - Left history: {len(left_history_after)} entries")
        print(f"After startup - Right history: {len(right_history_after)} entries")
        
        # Should only have entries for existing directories
        assert len(left_history_after) == 2
        assert len(right_history_after) == 1
        
        # Verify correct entries remain
        assert str(existing_dir1) in left_history_after
        assert str(existing_dir2) in left_history_after
        assert str(non_existing_dir1) not in left_history_after
        assert str(non_existing_dir2) not in left_history_after
        
        assert str(existing_dir1) in right_history_after
        assert str(non_existing_dir1) not in right_history_after
        
        print("✓ Startup directory cleanup working correctly")
        return


def test_startup_with_no_cleanup_needed():
    """Test startup when no cleanup is needed."""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test directories (all will exist)
        existing_dir1 = temp_path / "existing_dir1"
        existing_dir1.mkdir()
        
        existing_dir2 = temp_path / "existing_dir2"
        existing_dir2.mkdir()
        
        # Create mock file manager
        fm = MockFileManager(temp_dir)
        
        # Save cursor positions for existing directories only
        fm.state_manager.save_pane_cursor_position("left", str(existing_dir1), "file1.txt")
        fm.state_manager.save_pane_cursor_position("left", str(existing_dir2), "file2.txt")
        fm.state_manager.save_pane_cursor_position("right", str(existing_dir1), "file3.txt")
        
        # Verify entries before startup
        left_history_before = fm.state_manager.get_pane_cursor_positions("left")
        right_history_before = fm.state_manager.get_pane_cursor_positions("right")
        
        assert len(left_history_before) == 2
        assert len(right_history_before) == 1
        
        # Simulate startup process
        print("\n--- Simulating XeFM startup (no cleanup needed) ---")
        fm.load_application_state()
        
        # Verify no entries were removed
        left_history_after = fm.state_manager.get_pane_cursor_positions("left")
        right_history_after = fm.state_manager.get_pane_cursor_positions("right")
        
        assert len(left_history_after) == 2
        assert len(right_history_after) == 1
        
        # All entries should still be there
        assert str(existing_dir1) in left_history_after
        assert str(existing_dir2) in left_history_after
        assert str(existing_dir1) in right_history_after
        
        print("✓ Startup with no cleanup needed working correctly")
        return
