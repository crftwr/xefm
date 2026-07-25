"""
Integration test for XeFM State Manager with main application

Tests the integration of state management with the main XeFM application.

Run with: python -m pytest test/test_state_integration.py -v
"""

from pathlib import Path
import tempfile

from xefm.path import Path

from xefm.state_manager import XeFMStateManager


def test_state_manager_integration():
    """Test basic integration of state manager with XeFM-like operations."""
    print("Testing state manager integration...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test state manager with custom database path
        db_path = Path(temp_dir) / "test_state.db"
        state_manager = XeFMStateManager("test_integration")
        state_manager.db_path = db_path
        state_manager._initialize_database()
        state_manager._register_session()  # Explicitly register session for test
        
        # Test pane state operations
        test_pane_data = {
            'path': Path('/tmp'),
            'focused_index': 3,
            'scroll_offset': 5,
            'sort_mode': 'size',
            'sort_reverse': True,
            'filter_pattern': '*.txt',
            'selected_files': {'/tmp/file1.txt', '/tmp/file2.txt'}
        }
        
        # Save pane state
        assert state_manager.save_pane_state('left', test_pane_data)
        print("✓ Pane state saved successfully")
        
        # Load pane state
        loaded_state = state_manager.load_pane_state('left')
        assert loaded_state is not None
        assert loaded_state['path'] == str(test_pane_data['path'])
        assert loaded_state['selected_index'] == test_pane_data['focused_index']
        assert loaded_state['sort_mode'] == test_pane_data['sort_mode']
        print("✓ Pane state loaded successfully")
        
        # Test window layout
        assert state_manager.save_window_layout(0.7, 0.2)
        layout = state_manager.load_window_layout()
        assert layout['left_pane_ratio'] == 0.7
        assert layout['log_height_ratio'] == 0.2
        print("✓ Window layout saved and loaded successfully")
        
        # Test recent directories
        test_dirs = ['/home/user', '/tmp', '/var/log', '/usr/local']
        for dir_path in test_dirs:
            assert state_manager.add_recent_directory(dir_path)
        
        recent_dirs = state_manager.load_recent_directories()
        assert len(recent_dirs) == len(test_dirs)
        assert recent_dirs[0] == test_dirs[-1]  # Most recent should be first
        print("✓ Recent directories managed successfully")
        
        # Test search history
        search_terms = ['*.py', 'TODO', 'function', 'class']
        for term in search_terms:
            assert state_manager.add_search_term(term)
        
        history = state_manager.load_search_history()
        assert len(history) == len(search_terms)
        assert history[0] == search_terms[-1]  # Most recent should be first
        print("✓ Search history managed successfully")
        
        # Test pane-specific cursor history methods
        assert state_manager.save_pane_cursor_position('left', '/test/path', 'cursor_file.txt')
        loaded_cursor = state_manager.load_pane_cursor_position('left', '/test/path')
        assert loaded_cursor == 'cursor_file.txt'
        
        # Test multiple cursor positions for different panes
        assert state_manager.save_pane_cursor_position('right', '/another/path', 'another_file.py')
        left_cursors = state_manager.get_pane_cursor_positions('left')
        right_cursors = state_manager.get_pane_cursor_positions('right')
        assert '/test/path' in left_cursors
        assert '/another/path' in right_cursors
        assert left_cursors['/test/path'] == 'cursor_file.txt'
        assert right_cursors['/another/path'] == 'another_file.py'
        
        # Verify panes have separate histories
        assert '/another/path' not in left_cursors
        assert '/test/path' not in right_cursors
        print("✓ Pane-specific cursor history managed successfully")
        
        # Test session management
        sessions = state_manager.get_active_sessions()
        assert len(sessions) >= 1
        assert any(s['instance_id'] == 'test_integration' for s in sessions)
        print("✓ Session management working")
        
        # Test cleanup
        state_manager.cleanup_session()
        sessions = state_manager.get_active_sessions()
        session_ids = [s['instance_id'] for s in sessions]
        assert 'test_integration' not in session_ids
        print("✓ Session cleanup working")
        
        print("✓ All integration tests passed!")
        return


def test_state_persistence():
    """Test that state persists across different manager instances."""
    print("Testing state persistence...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "persistence_test.db"
        
        # Create first instance and save some state
        state_manager1 = XeFMStateManager("instance1")
        state_manager1.db_path = db_path
        state_manager1._initialize_database()
        
        test_data = {
            'path': '/test/path',
            'focused_index': 10,
            'scroll_offset': 20,
            'sort_mode': 'date',
            'sort_reverse': False,
            'filter_pattern': '*.log',
            'selected_files': []
        }
        
        assert state_manager1.save_pane_state('right', test_data)
        assert state_manager1.save_window_layout(0.3, 0.4)
        assert state_manager1.add_recent_directory('/persistent/path')
        
        # Clean up first instance
        state_manager1.cleanup_session()
        
        # Create second instance and verify state persists
        state_manager2 = XeFMStateManager("instance2")
        state_manager2.db_path = db_path
        
        # Load state from second instance
        loaded_pane = state_manager2.load_pane_state('right')
        assert loaded_pane is not None
        assert loaded_pane['path'] == test_data['path']
        assert loaded_pane['selected_index'] == test_data['focused_index']
        assert loaded_pane['sort_mode'] == test_data['sort_mode']
        
        loaded_layout = state_manager2.load_window_layout()
        assert loaded_layout is not None
        assert loaded_layout['left_pane_ratio'] == 0.3
        assert loaded_layout['log_height_ratio'] == 0.4
        
        recent_dirs = state_manager2.load_recent_directories()
        assert '/persistent/path' in recent_dirs
        
        # Clean up second instance
        state_manager2.cleanup_session()
        
        print("✓ State persistence across instances working!")
        return


def test_concurrent_state_access():
    """Test concurrent access to state from multiple instances."""
    print("Testing concurrent state access...")
    
    import threading
    import time
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "concurrent_test.db"
        
        results = []
        errors = []
        
        def worker_instance(instance_id, iterations=20):
            """Worker function that simulates a XeFM instance."""
            try:
                state_manager = XeFMStateManager(f"worker_{instance_id}")
                state_manager.db_path = db_path
                state_manager._initialize_database()  # Ensure database is initialized
                
                for i in range(iterations):
                    # Simulate typical XeFM operations
                    pane_data = {
                        'path': f'/worker/{instance_id}/path/{i}',
                        'focused_index': i,
                        'scroll_offset': i * 2,
                        'sort_mode': 'name',
                        'sort_reverse': i % 2 == 0,
                        'filter_pattern': '',
                        'selected_files': []
                    }
                    
                    # Save pane state
                    if not state_manager.save_pane_state(f'worker_{instance_id}', pane_data):
                        errors.append(f"Worker {instance_id}: Failed to save pane state {i}")
                        continue
                    
                    # Add to recent directories
                    if not state_manager.add_recent_directory(pane_data['path']):
                        errors.append(f"Worker {instance_id}: Failed to add recent directory {i}")
                        continue
                    
                    # Update session heartbeat
                    state_manager.update_session_heartbeat()
                    
                    results.append(f"Worker {instance_id}: Success for iteration {i}")
                    
                    # Small delay to increase chance of concurrent access
                    time.sleep(0.001)
                
                # Clean up
                state_manager.cleanup_session()
                
            except Exception as e:
                errors.append(f"Worker {instance_id}: Exception {e}")
        
        # Start multiple worker threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=worker_instance, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Check results
        if errors:
            print(f"Errors during concurrent access: {errors[:3]}...")
            return
        
        print(f"✓ Concurrent access successful ({len(results)} operations)")
        return


def run_integration_tests():
    """Run all integration tests."""
    print("Running XeFM State Manager integration tests...\n")
    
    try:
        if not test_state_manager_integration():
            return False
            
        if not test_state_persistence():
            return False
            
        if not test_concurrent_state_access():
            return False
        
        print("\n✓ All integration tests passed!")
        return True
        
    except Exception as e:
        print(f"\n✗ Integration test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
