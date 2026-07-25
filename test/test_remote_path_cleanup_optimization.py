"""
Test for remote path cleanup optimization.

This test verifies that the cleanup_non_existing_directories() function
skips existence checks for remote storage paths to improve performance.

Run with: python -m pytest test/test_remote_path_cleanup_optimization.py -v
"""

import time
from unittest.mock import patch

from xefm.state_manager import XeFMStateManager
from xefm.path import Path


def test_remote_path_cleanup_optimization(tmp_path):
    """Test that remote paths are skipped during cleanup for performance."""

    print("Testing remote path cleanup optimization...")

    # Own database: the bare XeFMStateManager() opens the real shared ~/.xefm/state.db,
    # so cleanup would also walk whatever history another test (or a real XeFM
    # session) left there and the assertion on which paths were checked would
    # depend on run order.
    state_manager = XeFMStateManager(db_path=str(tmp_path / "state.db"))

    # Create test history with mix of local and remote paths
    test_history = [
        [time.time(), "/tmp/existing_local", "file1.txt"],
        [time.time(), "/tmp/non_existing_local", "file2.txt"],
        [time.time(), "s3://test-bucket/existing", "file3.txt"],
        [time.time(), "s3://test-bucket/non-existing", "file4.txt"],
    ]
    
    # Set up the test history
    state_manager.set_state("path_history_left", test_history, "test_instance")
    
    # Mock Path.exists() to track calls and simulate behavior
    exists_calls = []
    
    def mock_exists(self):
        path_str = str(self)
        exists_calls.append(path_str)
        # Simulate that only /tmp/existing_local exists
        return path_str == "/tmp/existing_local"
    
    # Mock Path.is_remote() to identify remote paths
    def mock_is_remote(self):
        path_str = str(self)
        return path_str.startswith(('s3://', 'scp://', 'ftp://'))
    
    # Apply mocks
    with patch.object(Path, 'exists', mock_exists), \
         patch.object(Path, 'is_remote', mock_is_remote):
        
        # Run cleanup
        print("Running cleanup_non_existing_directories()...")
        result = state_manager.cleanup_non_existing_directories()
        
        assert result, "Cleanup should succeed"
        
        # Verify that exists() was only called for local paths
        print(f"exists() was called for: {exists_calls}")
        
        # Should only check existence of local paths
        expected_exists_calls = ["/tmp/existing_local", "/tmp/non_existing_local"]
        assert set(exists_calls) == set(expected_exists_calls), \
            f"Expected exists() calls for {expected_exists_calls}, got {exists_calls}"
        
        # Verify the cleaned history
        cleaned_history = state_manager.get_state("path_history_left", [])
        print(f"Cleaned history has {len(cleaned_history)} entries")
        
        # Should have: existing local + all remote paths (skipped)
        expected_paths = [
            "/tmp/existing_local",  # Local path that exists
            "s3://test-bucket/existing",  # Remote path (skipped check)
            "s3://test-bucket/non-existing",  # Remote path (skipped check)
        ]
        
        actual_paths = [entry[1] for entry in cleaned_history]
        assert set(actual_paths) == set(expected_paths), \
            f"Expected paths {expected_paths}, got {actual_paths}"
        
        print("✓ Remote paths were preserved without existence checks")
        print("✓ Local non-existing paths were removed")
        print("✓ Local existing paths were preserved")


def test_performance_improvement(tmp_path):
    """Test that remote path cleanup is significantly faster."""

    print("\nTesting performance improvement...")

    state_manager = XeFMStateManager(db_path=str(tmp_path / "state.db"))

    # Create history with many remote paths
    large_history = []
    for i in range(20):  # Reduced for faster testing
        large_history.append([time.time(), f"s3://bucket/path{i}", f"file{i}.txt"])
    
    state_manager.set_state("path_history_left", large_history, "test_instance")
    
    # Mock slow network exists() calls
    def slow_exists(self):
        time.sleep(0.01)  # Simulate slow network call
        return True
    
    def mock_is_remote(self):
        return str(self).startswith('s3://')
    
    # Test with optimization (should be fast)
    start_time = time.time()
    with patch.object(Path, 'exists', slow_exists), \
         patch.object(Path, 'is_remote', mock_is_remote):
        
        result = state_manager.cleanup_non_existing_directories()
        
    elapsed_time = time.time() - start_time
    
    assert result, "Cleanup should succeed"
    print(f"Cleanup with optimization took {elapsed_time:.2f} seconds")
    
    # Should be fast (under 0.2 seconds) because remote paths are skipped
    assert elapsed_time < 0.2, f"Cleanup took too long: {elapsed_time:.2f}s"
    
    # Verify all remote paths are still there
    cleaned_history = state_manager.get_state("path_history_left", [])
    assert len(cleaned_history) == 20, f"Expected 20 entries, got {len(cleaned_history)}"
    
    print("✓ Performance optimization working - remote paths skipped")
