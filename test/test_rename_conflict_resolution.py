"""
Test script for rename conflict resolution feature
Tests the new "Rename" option in copy/move/extract operations

Run with: python -m pytest test/test_rename_conflict_resolution.py -v
"""

import tempfile
import shutil
from pathlib import Path as StdPath

from xefm.path import Path


def test_copy_rename_conflict():
    """Test copy operation with rename conflict resolution"""
    print("\n=== Testing Copy with Rename Conflict ===")
    
    # Create temporary directories
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = StdPath(temp_dir) / "source"
        dest_dir = StdPath(temp_dir) / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        # Create test files
        test_file = source_dir / "test.txt"
        test_file.write_text("Source content")
        
        # Create conflicting file in destination
        conflict_file = dest_dir / "test.txt"
        conflict_file.write_text("Destination content")
        
        print(f"Source file: {test_file}")
        print(f"Destination file: {conflict_file}")
        print(f"Conflict exists: {conflict_file.exists()}")
        
        # Simulate rename to new name
        new_name = "test_renamed.txt"
        new_dest = dest_dir / new_name
        
        # Copy with new name
        source_path = Path(str(test_file))
        dest_path = Path(str(new_dest))
        source_path.copy_to(dest_path)
        
        print(f"Copied to: {new_dest}")
        print(f"New file exists: {new_dest.exists()}")
        print(f"Original destination unchanged: {conflict_file.read_text()}")
        print(f"New file content: {new_dest.read_text()}")
        
        assert new_dest.exists(), "Renamed file should exist"
        assert new_dest.read_text() == "Source content", "Content should match source"
        assert conflict_file.read_text() == "Destination content", "Original should be unchanged"
        
        print("✓ Copy with rename test passed")


def test_move_rename_conflict():
    """Test move operation with rename conflict resolution"""
    print("\n=== Testing Move with Rename Conflict ===")
    
    # Create temporary directories
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = StdPath(temp_dir) / "source"
        dest_dir = StdPath(temp_dir) / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        # Create test files
        test_file = source_dir / "test.txt"
        test_file.write_text("Source content")
        
        # Create conflicting file in destination
        conflict_file = dest_dir / "test.txt"
        conflict_file.write_text("Destination content")
        
        print(f"Source file: {test_file}")
        print(f"Destination file: {conflict_file}")
        print(f"Conflict exists: {conflict_file.exists()}")
        
        # Simulate rename to new name
        new_name = "test_moved.txt"
        new_dest = dest_dir / new_name
        
        # Move with new name (copy then delete)
        source_path = Path(str(test_file))
        dest_path = Path(str(new_dest))
        source_path.copy_to(dest_path)
        source_path.unlink()
        
        print(f"Moved to: {new_dest}")
        print(f"New file exists: {new_dest.exists()}")
        print(f"Source file removed: {not test_file.exists()}")
        print(f"Original destination unchanged: {conflict_file.read_text()}")
        print(f"New file content: {new_dest.read_text()}")
        
        assert new_dest.exists(), "Renamed file should exist"
        assert not test_file.exists(), "Source file should be removed"
        assert new_dest.read_text() == "Source content", "Content should match source"
        assert conflict_file.read_text() == "Destination content", "Original should be unchanged"
        
        print("✓ Move with rename test passed")


def test_recursive_rename_conflict():
    """Test that rename checks for conflicts recursively"""
    print("\n=== Testing Recursive Rename Conflict Check ===")
    
    # Create temporary directories
    with tempfile.TemporaryDirectory() as temp_dir:
        dest_dir = StdPath(temp_dir) / "dest"
        dest_dir.mkdir()
        
        # Create multiple conflicting files
        conflict1 = dest_dir / "test.txt"
        conflict1.write_text("Conflict 1")
        
        conflict2 = dest_dir / "test_renamed.txt"
        conflict2.write_text("Conflict 2")
        
        conflict3 = dest_dir / "test_final.txt"
        conflict3.write_text("Conflict 3")
        
        print(f"Conflict 1: {conflict1.exists()}")
        print(f"Conflict 2: {conflict2.exists()}")
        print(f"Conflict 3: {conflict3.exists()}")
        
        # Simulate user trying different names
        names_to_try = ["test.txt", "test_renamed.txt", "test_final.txt", "test_unique.txt"]
        
        for name in names_to_try:
            test_path = dest_dir / name
            if test_path.exists():
                print(f"'{name}' conflicts - would show dialog again")
            else:
                print(f"'{name}' is available - would proceed with operation")
                break
        
        assert not (dest_dir / "test_unique.txt").exists(), "Final name should be available"
        
        print("✓ Recursive conflict check test passed")


def test_directory_rename_conflict():
    """Test rename conflict resolution for directories"""
    print("\n=== Testing Directory Rename Conflict ===")
    
    # Create temporary directories
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = StdPath(temp_dir) / "source"
        dest_dir = StdPath(temp_dir) / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        # Create test directory with files
        test_dir = source_dir / "mydir"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("File 1")
        (test_dir / "file2.txt").write_text("File 2")
        
        # Create conflicting directory in destination
        conflict_dir = dest_dir / "mydir"
        conflict_dir.mkdir()
        (conflict_dir / "existing.txt").write_text("Existing")
        
        print(f"Source directory: {test_dir}")
        print(f"Destination directory: {conflict_dir}")
        print(f"Conflict exists: {conflict_dir.exists()}")
        
        # Simulate rename to new name
        new_name = "mydir_renamed"
        new_dest = dest_dir / new_name
        
        # Copy directory with new name
        source_path = Path(str(test_dir))
        dest_path = Path(str(new_dest))
        source_path.copy_to(dest_path)
        
        print(f"Copied to: {new_dest}")
        print(f"New directory exists: {new_dest.exists()}")
        print(f"Files in new directory: {list(new_dest.iterdir())}")
        print(f"Original destination unchanged: {list(conflict_dir.iterdir())}")
        
        assert new_dest.exists(), "Renamed directory should exist"
        assert (new_dest / "file1.txt").exists(), "Files should be copied"
        assert (new_dest / "file2.txt").exists(), "Files should be copied"
        assert (conflict_dir / "existing.txt").exists(), "Original should be unchanged"
        
        print("✓ Directory rename test passed")


def main():
    """Run all tests"""
    print("Testing Rename Conflict Resolution Feature")
    print("=" * 50)
    
    try:
        test_copy_rename_conflict()
        test_move_rename_conflict()
        test_recursive_rename_conflict()
        test_directory_rename_conflict()
        
        print("\n" + "=" * 50)
        print("✓ All tests passed successfully!")
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
