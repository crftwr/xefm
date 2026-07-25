"""
Test inverse selection behavior for select_all_files and select_all_items

Run with: python -m pytest test/test_inverse_selection.py -v
"""

from pathlib import Path

from xefm.file_list_manager import FileListManager


def test_inverse_files_selection():
    """Test that select_all_files inverses selection status of each file"""
    print("Testing inverse files selection...")
    
    # Create a mock config object
    class MockConfig:
        SHOW_HIDDEN_FILES = False
        DEFAULT_SORT_MODE = 'name'
        DEFAULT_SORT_REVERSE = False
        MAX_HISTORY_ENTRIES = 100
    
    file_ops = FileListManager(MockConfig())
    
    # Create mock Path objects
    class MockPath:
        def __init__(self, path, is_directory=False):
            self.path = path
            self._is_directory = is_directory
        
        def is_dir(self):
            return self._is_directory
        
        def __str__(self):
            return self.path
    
    # Create mock pane data with files and directories
    pane_data = {
        'files': [
            MockPath('/test/file1.txt', False),
            MockPath('/test/file2.txt', False),
            MockPath('/test/dir1', True),
            MockPath('/test/file3.txt', False),
        ],
        'selected_files': set()
    }
    
    # Test 1: No files selected initially - should select all files
    print("\nTest 1: No files selected initially")
    success, message = file_ops.toggle_all_files_selection(pane_data)
    print(f"  Result: {message}")
    assert success, "Operation should succeed"
    assert len(pane_data['selected_files']) == 3, "Should select 3 files"
    assert '/test/file1.txt' in pane_data['selected_files']
    assert '/test/file2.txt' in pane_data['selected_files']
    assert '/test/file3.txt' in pane_data['selected_files']
    assert '/test/dir1' not in pane_data['selected_files'], "Should not select directory"
    print("  ✓ All files selected, directory not selected")
    
    # Test 2: All files selected - should deselect all files
    print("\nTest 2: All files selected")
    success, message = file_ops.toggle_all_files_selection(pane_data)
    print(f"  Result: {message}")
    assert success, "Operation should succeed"
    assert len(pane_data['selected_files']) == 0, "Should deselect all files"
    print("  ✓ All files deselected")
    
    # Test 3: Some files selected - should inverse selection
    print("\nTest 3: Some files selected (file1 and file2)")
    pane_data['selected_files'] = {'/test/file1.txt', '/test/file2.txt'}
    success, message = file_ops.toggle_all_files_selection(pane_data)
    print(f"  Result: {message}")
    assert success, "Operation should succeed"
    assert len(pane_data['selected_files']) == 1, "Should have 1 file selected"
    assert '/test/file3.txt' in pane_data['selected_files'], "file3 should be selected"
    assert '/test/file1.txt' not in pane_data['selected_files'], "file1 should be deselected"
    assert '/test/file2.txt' not in pane_data['selected_files'], "file2 should be deselected"
    print("  ✓ Selection inversed correctly")
    
    print("\n✓ All inverse files selection tests passed!")


def test_inverse_items_selection():
    """Test that select_all_items inverses selection status of all items"""
    print("\nTesting inverse items selection...")
    
    # Create a mock config object
    class MockConfig:
        SHOW_HIDDEN_FILES = False
        DEFAULT_SORT_MODE = 'name'
        DEFAULT_SORT_REVERSE = False
        MAX_HISTORY_ENTRIES = 100
    
    file_ops = FileListManager(MockConfig())
    
    # Create mock Path objects
    class MockPath:
        def __init__(self, path, is_directory=False):
            self.path = path
            self._is_directory = is_directory
        
        def is_dir(self):
            return self._is_directory
        
        def __str__(self):
            return self.path
    
    # Create mock pane data with files and directories
    pane_data = {
        'files': [
            MockPath('/test/file1.txt', False),
            MockPath('/test/dir1', True),
            MockPath('/test/file2.txt', False),
            MockPath('/test/dir2', True),
        ],
        'selected_files': set()
    }
    
    # Test 1: No items selected initially - should select all items
    print("\nTest 1: No items selected initially")
    success, message = file_ops.toggle_all_items_selection(pane_data)
    print(f"  Result: {message}")
    assert success, "Operation should succeed"
    assert len(pane_data['selected_files']) == 4, "Should select all 4 items"
    print("  ✓ All items selected")
    
    # Test 2: All items selected - should deselect all items
    print("\nTest 2: All items selected")
    success, message = file_ops.toggle_all_items_selection(pane_data)
    print(f"  Result: {message}")
    assert success, "Operation should succeed"
    assert len(pane_data['selected_files']) == 0, "Should deselect all items"
    print("  ✓ All items deselected")
    
    # Test 3: Some items selected - should inverse selection
    print("\nTest 3: Some items selected (file1 and dir1)")
    pane_data['selected_files'] = {'/test/file1.txt', '/test/dir1'}
    success, message = file_ops.toggle_all_items_selection(pane_data)
    print(f"  Result: {message}")
    assert success, "Operation should succeed"
    assert len(pane_data['selected_files']) == 2, "Should have 2 items selected"
    assert '/test/file2.txt' in pane_data['selected_files'], "file2 should be selected"
    assert '/test/dir2' in pane_data['selected_files'], "dir2 should be selected"
    assert '/test/file1.txt' not in pane_data['selected_files'], "file1 should be deselected"
    assert '/test/dir1' not in pane_data['selected_files'], "dir1 should be deselected"
    print("  ✓ Selection inversed correctly")
    
    print("\n✓ All inverse items selection tests passed!")
