"""
Test script for cursor position history feature

Run with: python -m pytest test/test_cursor_history.py -v
"""

from pathlib import Path
import tempfile
import shutil

def create_test_structure():
    """Create a test directory structure"""
    # Create temporary directory
    test_dir = Path(tempfile.mkdtemp(prefix="xefm_cursor_test_"))
    
    # Create subdirectories
    (test_dir / "dir1").mkdir()
    (test_dir / "dir2").mkdir()
    (test_dir / "dir3").mkdir()
    
    # Create files in main directory
    (test_dir / "file1.txt").write_text("Test file 1")
    (test_dir / "file2.txt").write_text("Test file 2")
    (test_dir / "file3.txt").write_text("Test file 3")
    
    # Create files in subdirectories
    (test_dir / "dir1" / "subfile1.txt").write_text("Sub file 1")
    (test_dir / "dir1" / "subfile2.txt").write_text("Sub file 2")
    (test_dir / "dir2" / "subfile3.txt").write_text("Sub file 3")
    
    return test_dir

def test_cursor_history():
    """Test the cursor history functionality"""
    from collections import deque
    
    # Simulate pane data structure
    test_dir = create_test_structure()
    
    pane_data = {
        'path': test_dir,
        'selected_index': 0,
        'scroll_offset': 0,
        'files': [],
        'selected_files': set(),
        'sort_mode': 'name',
        'sort_reverse': False,
        'filter_pattern': "",
        'cursor_history': deque(maxlen=100)
    }
    
    # Simulate file listing
    pane_data['files'] = sorted(list(test_dir.iterdir()), key=lambda x: x.name)
    
    print(f"Test directory: {test_dir}")
    print(f"Files in directory: {[f.name for f in pane_data['files']]}")
    
    # Test saving cursor position
    pane_data['focused_index'] = 2  # Select file3.txt
    print(f"Selected file: {pane_data['files'][pane_data['focused_index']].name}")
    
    # Simulate save_cursor_position
    current_file = pane_data['files'][pane_data['focused_index']]
    current_dir = pane_data['path']
    cursor_entry = (current_file.name, str(current_dir))
    pane_data['cursor_history'].append(cursor_entry)
    
    print(f"Saved cursor position: {cursor_entry}")
    
    # Simulate changing to subdirectory
    pane_data['path'] = test_dir / "dir1"
    pane_data['files'] = sorted(list(pane_data['path'].iterdir()), key=lambda x: x.name)
    pane_data['focused_index'] = 0
    
    print(f"Changed to: {pane_data['path']}")
    print(f"Files in new directory: {[f.name for f in pane_data['files']]}")
    
    # Save position in subdirectory
    pane_data['focused_index'] = 1  # Select subfile2.txt
    current_file = pane_data['files'][pane_data['focused_index']]
    current_dir = pane_data['path']
    cursor_entry = (current_file.name, str(current_dir))
    pane_data['cursor_history'].append(cursor_entry)
    
    print(f"Saved cursor position in subdir: {cursor_entry}")
    
    # Simulate going back to parent directory
    pane_data['path'] = test_dir
    pane_data['files'] = sorted(list(pane_data['path'].iterdir()), key=lambda x: x.name)
    pane_data['focused_index'] = 0
    
    print(f"Returned to: {pane_data['path']}")
    
    # Test restore_cursor_position
    current_dir = str(pane_data['path'])
    restored = False
    
    for filename, saved_dir in reversed(pane_data['cursor_history']):
        if saved_dir == current_dir:
            # Try to find this filename in current files
            for i, file_path in enumerate(pane_data['files']):
                if file_path.name == filename:
                    pane_data['focused_index'] = i
                    restored = True
                    print(f"Restored cursor to: {filename} (index {i})")
                    break
            if restored:
                break
    
    if not restored:
        print("No cursor position found in history")
    
    print(f"Final selected file: {pane_data['files'][pane_data['focused_index']].name}")
    print(f"Cursor history: {list(pane_data['cursor_history'])}")
    
    # Cleanup
    shutil.rmtree(test_dir)
    print(f"Cleaned up test directory: {test_dir}")
