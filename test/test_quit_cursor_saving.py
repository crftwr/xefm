"""
Test suite for cursor position saving on XeFM quit

Tests that cursor positions are properly saved when XeFM quits,
ensuring they will be available for restoration on next startup.

Run with: python -m pytest test/test_quit_cursor_saving.py -v
"""

import tempfile
import time
from pathlib import Path

from xefm.state_manager import XeFMStateManager
from xefm.pane_manager import PaneManager
from xefm._config import Config


class MockStdscr:
    """Mock curses screen for testing."""
    def __init__(self, height=40, width=120):
        self.height = height
        self.width = width
    
    def getmaxyx(self):
        return self.height, self.width


class MockFileManager:
    """Mock FileManager for testing quit cursor saving."""
    def __init__(self, config, left_path, right_path, state_manager):
        self.config = config
        self.state_manager = state_manager
        self.pane_manager = PaneManager(config, left_path, right_path, state_manager)
        self.stdscr = MockStdscr()
        self.log_height_ratio = 0.25
        self.needs_full_redraw = False
    
    def refresh_files(self):
        """Mock file refresh - populate with test files."""
        # Left pane files
        left_path = self.pane_manager.left_pane['path']
        if left_path.exists():
            self.pane_manager.left_pane['files'] = sorted([
                f for f in left_path.iterdir() if f.is_file()
            ])
        
        # Right pane files
        right_path = self.pane_manager.right_pane['path']
        if right_path.exists():
            self.pane_manager.right_pane['files'] = sorted([
                f for f in right_path.iterdir() if f.is_file()
            ])
    
    def save_quit_cursor_positions(self):
        """Save current cursor positions when quitting XeFM."""
        saved_positions = []
        try:
            # Save left pane cursor position
            if (self.pane_manager.left_pane['files'] and 
                self.pane_manager.left_pane['focused_index'] < len(self.pane_manager.left_pane['files'])):
                
                self.pane_manager.save_cursor_position(self.pane_manager.left_pane)
                
                left_path = self.pane_manager.left_pane['path']
                selected_file = self.pane_manager.left_pane['files'][self.pane_manager.left_pane['focused_index']].name
                saved_positions.append(f"Left pane: {left_path} -> {selected_file}")
            
            # Save right pane cursor position
            if (self.pane_manager.right_pane['files'] and 
                self.pane_manager.right_pane['focused_index'] < len(self.pane_manager.right_pane['files'])):
                
                self.pane_manager.save_cursor_position(self.pane_manager.right_pane)
                
                right_path = self.pane_manager.right_pane['path']
                selected_file = self.pane_manager.right_pane['files'][self.pane_manager.right_pane['focused_index']].name
                saved_positions.append(f"Right pane: {right_path} -> {selected_file}")
        
        except Exception as e:
            print(f"Warning: Could not save cursor positions on quit: {e}")
        
        return saved_positions
    
    def save_application_state(self):
        """Mock application state saving with cursor position saving."""
        try:
            # Save window layout
            self.state_manager.save_window_layout(
                self.pane_manager.left_pane_ratio,
                self.log_height_ratio
            )
            
            # Save pane states
            self.state_manager.save_pane_state('left', self.pane_manager.left_pane)
            self.state_manager.save_pane_state('right', self.pane_manager.right_pane)
            
            # Save current cursor positions before quitting
            saved_positions = self.save_quit_cursor_positions()
            
            # Add current directories to recent directories
            left_path = str(self.pane_manager.left_pane['path'])
            right_path = str(self.pane_manager.right_pane['path'])
            
            self.state_manager.add_recent_directory(left_path)
            if left_path != right_path:  # Don't add duplicate
                self.state_manager.add_recent_directory(right_path)
            
            # Clean up session
            self.state_manager.cleanup_session()
            
            return saved_positions
            
        except Exception as e:
            print(f"Warning: Could not save application state: {e}")
            return []


def test_quit_cursor_saving_basic():
    """Test basic cursor position saving on quit."""
    print("Testing cursor position saving on quit...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test directory structure
        left_dir = Path(temp_dir) / "left_quit"
        right_dir = Path(temp_dir) / "right_quit"
        
        left_dir.mkdir()
        right_dir.mkdir()
        
        # Create test files
        left_files = ["alpha.txt", "beta.py", "gamma.log", "delta.md"]
        right_files = ["one.txt", "two.py", "three.log"]
        
        for filename in left_files:
            (left_dir / filename).touch()
        
        for filename in right_files:
            (right_dir / filename).touch()
        
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_quit_basic")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Create file manager and set up files
        config = Config()
        fm = MockFileManager(config, left_dir, right_dir, state_manager)
        fm.refresh_files()
        
        # Set focus positions
        fm.pane_manager.left_pane['focused_index'] = 2   # gamma.log
        fm.pane_manager.right_pane['focused_index'] = 1  # two.py
        
        left_file = fm.pane_manager.left_pane['files'][2].name
        right_file = fm.pane_manager.right_pane['files'][1].name
        
        print(f"Current positions before quit:")
        print(f"  Left pane: {left_file} (index 2)")
        print(f"  Right pane: {right_file} (index 1)")
        
        # Simulate quitting XeFM (save application state)
        saved_positions = fm.save_application_state()
        
        print(f"Positions saved on quit:")
        for position in saved_positions:
            print(f"  {position}")
        
        # Verify positions were saved
        assert len(saved_positions) == 2
        
        # Check that the correct files were saved (order may vary)
        saved_text = " ".join(saved_positions)
        assert left_file in saved_text
        assert right_file in saved_text
        
        # Verify they can be loaded back
        left_cursor = state_manager.load_pane_cursor_position('left', str(left_dir))
        right_cursor = state_manager.load_pane_cursor_position('right', str(right_dir))
        
        assert left_cursor == left_file
        assert right_cursor == right_file
        
        print("✓ Cursor positions correctly saved on quit")
        print("✓ Basic quit cursor saving test completed\n")


def test_quit_saving_with_empty_panes():
    """Test quit cursor saving with empty panes."""
    print("Testing quit cursor saving with empty panes...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create empty directories
        left_dir = Path(temp_dir) / "empty_left"
        right_dir = Path(temp_dir) / "empty_right"
        
        left_dir.mkdir()
        right_dir.mkdir()
        
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_quit_empty")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Create file manager with empty directories
        config = Config()
        fm = MockFileManager(config, left_dir, right_dir, state_manager)
        fm.refresh_files()
        
        # Panes should be empty
        assert len(fm.pane_manager.left_pane['files']) == 0
        assert len(fm.pane_manager.right_pane['files']) == 0
        
        # Simulate quitting XeFM
        saved_positions = fm.save_application_state()
        
        # Should not save any cursor positions for empty panes
        assert len(saved_positions) == 0
        
        print("✓ Empty panes handled correctly on quit")
        print("✓ Empty panes test completed\n")


def test_quit_saving_with_invalid_cursor():
    """Test quit cursor saving with invalid cursor positions."""
    print("Testing quit cursor saving with invalid cursor positions...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test directory
        test_dir = Path(temp_dir) / "invalid_cursor"
        test_dir.mkdir()
        
        # Create test files
        test_files = ["file1.txt", "file2.py"]
        for filename in test_files:
            (test_dir / filename).touch()
        
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_quit_invalid")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Create file manager
        config = Config()
        fm = MockFileManager(config, test_dir, test_dir, state_manager)
        fm.refresh_files()
        
        # Set invalid cursor positions (beyond file list)
        fm.pane_manager.left_pane['focused_index'] = 10   # Invalid (only 2 files)
        fm.pane_manager.right_pane['focused_index'] = 5   # Invalid (only 2 files)
        
        print(f"Set invalid cursor positions:")
        print(f"  Left pane: index 10 (only {len(fm.pane_manager.left_pane['files'])} files)")
        print(f"  Right pane: index 5 (only {len(fm.pane_manager.right_pane['files'])} files)")
        
        # Simulate quitting XeFM
        saved_positions = fm.save_application_state()
        
        # Should not save cursor positions for invalid indices
        assert len(saved_positions) == 0
        
        print("✓ Invalid cursor positions handled correctly on quit")
        print("✓ Invalid cursor test completed\n")


def test_quit_saving_integration_with_startup():
    """Test complete integration: quit saving + startup restoration."""
    print("Testing quit saving integration with startup restoration...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test directory structure
        work_dir = Path(temp_dir) / "work_project"
        docs_dir = Path(temp_dir) / "documentation"
        
        work_dir.mkdir()
        docs_dir.mkdir()
        
        # Create work files
        work_files = ["main.py", "utils.py", "config.json", "tests.py"]
        for filename in work_files:
            (work_dir / filename).touch()
        
        # Create doc files
        doc_files = ["README.md", "API.md", "GUIDE.md"]
        for filename in doc_files:
            (docs_dir / filename).touch()
        
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        
        # === Session 1: Work and quit ===
        print("--- Session 1: Working and quitting ---")
        
        state_manager1 = XeFMStateManager("integration_session1")
        state_manager1.db_path = db_path
        state_manager1._initialize_database()
        
        fm1 = MockFileManager(Config(), work_dir, docs_dir, state_manager1)
        fm1.refresh_files()
        
        # Set focus positions during work
        fm1.pane_manager.left_pane['focused_index'] = 1   # utils.py
        fm1.pane_manager.right_pane['focused_index'] = 2  # GUIDE.md
        
        work_file = fm1.pane_manager.left_pane['files'][1].name
        doc_file = fm1.pane_manager.right_pane['files'][2].name
        
        print(f"Working on:")
        print(f"  Left pane: {work_file}")
        print(f"  Right pane: {doc_file}")
        
        # Quit XeFM (save state including cursor positions)
        saved_positions = fm1.save_application_state()
        
        print(f"Saved on quit:")
        for position in saved_positions:
            print(f"  {position}")
        
        # === Session 2: Startup and verify restoration ===
        print("\n--- Session 2: Startup and restoration ---")
        
        state_manager2 = XeFMStateManager("integration_session2")
        state_manager2.db_path = db_path
        
        fm2 = MockFileManager(Config(), work_dir, docs_dir, state_manager2)
        fm2.refresh_files()
        
        # Initially cursors should be at default positions
        assert fm2.pane_manager.left_pane['focused_index'] == 0
        assert fm2.pane_manager.right_pane['focused_index'] == 0
        
        # Restore cursor positions (simulate startup)
        height, width = fm2.stdscr.getmaxyx()
        display_height = height - int(height * fm2.log_height_ratio) - 3
        
        left_restored = fm2.pane_manager.restore_cursor_position(fm2.pane_manager.left_pane, display_height)
        right_restored = fm2.pane_manager.restore_cursor_position(fm2.pane_manager.right_pane, display_height)
        
        # Verify restoration
        assert left_restored is True
        assert right_restored is True
        
        assert fm2.pane_manager.left_pane['focused_index'] == 1
        assert fm2.pane_manager.right_pane['focused_index'] == 2
        
        restored_work_file = fm2.pane_manager.left_pane['files'][1].name
        restored_doc_file = fm2.pane_manager.right_pane['files'][2].name
        
        assert restored_work_file == work_file
        assert restored_doc_file == doc_file
        
        print(f"Restored on startup:")
        print(f"  Left pane: {restored_work_file}")
        print(f"  Right pane: {restored_doc_file}")
        
        print("✓ Complete quit-save + startup-restore cycle works perfectly!")
        
        # Clean up
        state_manager2.cleanup_session()
        
        print("✓ Integration test completed\n")


def test_quit_saving_separate_pane_histories():
    """Test that quit saving maintains separate pane histories."""
    print("Testing quit saving with separate pane histories...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create different directories for each pane
        left_dir = Path(temp_dir) / "left_separate"
        right_dir = Path(temp_dir) / "right_separate"
        
        left_dir.mkdir()
        right_dir.mkdir()
        
        # Create different files
        left_files = ["left_a.txt", "left_b.py", "left_c.log"]
        right_files = ["right_x.txt", "right_y.py", "right_z.log", "right_w.md"]
        
        for filename in left_files:
            (left_dir / filename).touch()
        
        for filename in right_files:
            (right_dir / filename).touch()
        
        # Create state manager
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_quit_separate")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        
        # Create file manager
        config = Config()
        fm = MockFileManager(config, left_dir, right_dir, state_manager)
        fm.refresh_files()
        
        # Set different cursor positions
        fm.pane_manager.left_pane['focused_index'] = 1   # left_b.py
        fm.pane_manager.right_pane['focused_index'] = 3  # right_w.md
        
        left_file = fm.pane_manager.left_pane['files'][1].name
        right_file = fm.pane_manager.right_pane['files'][3].name
        
        print(f"Set positions:")
        print(f"  Left pane: {left_file}")
        print(f"  Right pane: {right_file}")
        
        # Quit and save
        saved_positions = fm.save_application_state()
        
        # Verify separate histories
        left_history = state_manager.get_pane_cursor_positions('left')
        right_history = state_manager.get_pane_cursor_positions('right')
        
        assert str(left_dir) in left_history
        assert str(right_dir) in right_history
        assert left_history[str(left_dir)] == left_file
        assert right_history[str(right_dir)] == right_file
        
        # Verify separation
        assert str(right_dir) not in left_history
        assert str(left_dir) not in right_history
        
        print("✓ Separate pane histories maintained on quit")
        print("✓ Separate histories test completed\n")


def run_all_tests():
    """Run all quit cursor saving tests."""
    print("Running quit cursor saving tests...\n")
    
    try:
        test_quit_cursor_saving_basic()
        test_quit_saving_with_empty_panes()
        test_quit_saving_with_invalid_cursor()
        test_quit_saving_integration_with_startup()
        test_quit_saving_separate_pane_histories()
        
        print("=" * 60)
        print("✓ All quit cursor saving tests passed!")
        print("\nKey features verified:")
        print("  • Cursor positions saved automatically on XeFM quit")
        print("  • Separate pane histories maintained")
        print("  • Empty panes handled gracefully")
        print("  • Invalid cursor positions handled safely")
        print("  • Complete integration with startup restoration")
        print("  • Seamless quit-save + startup-restore cycle")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
