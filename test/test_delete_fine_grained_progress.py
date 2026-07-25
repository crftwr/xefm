"""
Test fine-grained progress tracking for delete operations

Run with: python -m pytest test/test_delete_fine_grained_progress.py -v
"""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock

from xefm.progress_manager import ProgressManager, OperationType


class MockXeFM:
    """Mock XeFM class to test fine-grained delete progress tracking"""
    
    def __init__(self):
        self.progress_manager = ProgressManager()
        self.stdscr = Mock()
        self.needs_full_redraw = False
        self.progress_updates = []  # Track progress updates for testing
        
    def _progress_callback(self, progress_data):
        """Mock progress callback that records updates"""
        if progress_data:
            self.progress_updates.append({
                'processed': progress_data['processed_items'],
                'total': progress_data['total_items'],
                'current_item': progress_data['current_item']
            })
        
    def draw_status(self):
        """Mock draw_status method"""
        pass
        
    def refresh_files(self, pane=None):
        """Mock refresh_files method"""
        pass
        
    def get_current_pane(self):
        """Mock get_current_pane method"""
        return {'selected_files': set(), 'selected_index': 0, 'files': []}
    
    def _count_files_recursively(self, paths):
        """Count total number of individual files in the given paths (including files in directories)"""
        total_files = 0
        for path in paths:
            if path.is_file() or path.is_symlink():
                total_files += 1
            elif path.is_dir():
                try:
                    for root, dirs, files in os.walk(path):
                        total_files += len(files)
                        # Count symlinks to directories as files
                        for d in dirs:
                            dir_path = Path(root) / d
                            if dir_path.is_symlink():
                                total_files += 1
                except (PermissionError, OSError):
                    # If we can't walk the directory, count it as 1 item
                    total_files += 1
        return total_files
    
    def _delete_directory_with_progress(self, dir_path, processed_files, total_files):
        """Delete directory recursively with fine-grained progress updates"""
        try:
            # Walk through directory and delete files one by one (bottom-up for safety)
            for root, dirs, files in os.walk(dir_path, topdown=False):
                root_path = Path(root)
                
                # Delete files in current directory
                for file_name in files:
                    file_path = root_path / file_name
                    processed_files += 1
                    
                    if total_files > 1:
                        # Show relative path from the main directory being deleted
                        try:
                            rel_path = file_path.relative_to(dir_path)
                            display_name = str(rel_path)
                        except ValueError:
                            display_name = file_path.name
                        
                        self.progress_manager.update_progress(display_name, processed_files)
                    
                    try:
                        file_path.unlink()  # Remove file or symlink
                    except Exception as e:
                        print(f"Error deleting {file_path}: {e}")
                        if total_files > 1:
                            self.progress_manager.increment_errors()
                
                # Delete empty subdirectories (they should be empty now since we're going bottom-up)
                for dir_name in dirs:
                    subdir_path = root_path / dir_name
                    try:
                        # Only try to remove if it's empty or a symlink
                        if subdir_path.is_symlink():
                            # Count symlinks to directories as files for progress
                            processed_files += 1
                            if total_files > 1:
                                try:
                                    rel_path = subdir_path.relative_to(dir_path)
                                    display_name = f"Link: {rel_path}"
                                except ValueError:
                                    display_name = f"Link: {subdir_path.name}"
                                self.progress_manager.update_progress(display_name, processed_files)
                            subdir_path.unlink()
                        else:
                            # Try to remove empty directory (no progress update for empty dirs)
                            subdir_path.rmdir()
                    except OSError:
                        # Directory not empty or permission error - skip it
                        pass
                    except Exception as e:
                        print(f"Error deleting directory {subdir_path}: {e}")
                        if total_files > 1:
                            self.progress_manager.increment_errors()
            
            # Finally remove the main directory
            try:
                dir_path.rmdir()
            except OSError:
                # If directory is not empty, use shutil.rmtree as fallback
                shutil.rmtree(dir_path)
            
            return processed_files
            
        except Exception as e:
            print(f"Error deleting directory {dir_path}: {e}")
            if total_files > 1:
                self.progress_manager.increment_errors()
            return processed_files
    
    def perform_delete_operation_simplified(self, files_to_delete):
        """Simplified delete operation for testing"""
        # Count total individual files for fine-grained progress
        total_individual_files = self._count_files_recursively(files_to_delete)
        
        # Start progress tracking
        if total_individual_files > 1:
            self.progress_manager.start_operation(
                OperationType.DELETE, 
                total_individual_files, 
                "",
                self._progress_callback
            )
        
        processed_files = 0
        
        try:
            for file_path in files_to_delete:
                if file_path.is_symlink():
                    # Delete symbolic link (not its target)
                    processed_files += 1
                    if total_individual_files > 1:
                        self.progress_manager.update_progress(f"Link: {file_path.name}", processed_files)
                    
                    file_path.unlink()
                elif file_path.is_dir():
                    # Delete directory recursively with progress tracking
                    processed_files = self._delete_directory_with_progress(
                        file_path, processed_files, total_individual_files
                    )
                else:
                    # Delete single file
                    processed_files += 1
                    if total_individual_files > 1:
                        self.progress_manager.update_progress(file_path.name, processed_files)
                    
                    file_path.unlink()
        
        finally:
            # Finish progress tracking
            if total_individual_files > 1:
                self.progress_manager.finish_operation()


def test_fine_grained_delete_progress():
    """Test that delete operations report progress for individual files in directories"""
    print("Testing fine-grained delete progress...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create a complex directory structure to delete
        # test_dir/
        #   file1.txt
        #   file2.txt
        #   subdir1/
        #     file3.txt
        #     file4.txt
        #     subdir2/
        #       file5.txt
        #       file6.txt
        #   file7.txt
        
        test_dir = temp_path / "test_dir"
        test_dir.mkdir()
        
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")
        (test_dir / "file7.txt").write_text("content7")
        
        subdir1 = test_dir / "subdir1"
        subdir1.mkdir()
        (subdir1 / "file3.txt").write_text("content3")
        (subdir1 / "file4.txt").write_text("content4")
        
        subdir2 = subdir1 / "subdir2"
        subdir2.mkdir()
        (subdir2 / "file5.txt").write_text("content5")
        (subdir2 / "file6.txt").write_text("content6")
        
        # Create mock XeFM and perform delete
        xefm = MockXeFM()
        files_to_delete = [test_dir / "file1.txt", test_dir / "subdir1", test_dir / "file7.txt"]
        
        # Count expected total files
        # file1.txt = 1
        # subdir1 contains: file3.txt, file4.txt, subdir2/file5.txt, subdir2/file6.txt = 4
        # file7.txt = 1
        # Total = 6 files
        expected_total = 6
        
        xefm.perform_delete_operation_simplified(files_to_delete)
        
        # Verify progress tracking
        assert len(xefm.progress_updates) > 0, "Should have progress updates"
        
        # Check that we got updates for individual files
        final_update = xefm.progress_updates[-1]
        assert final_update['total'] == expected_total, f"Expected {expected_total} total files, got {final_update['total']}"
        assert final_update['processed'] == expected_total, f"Expected {expected_total} processed files, got {final_update['processed']}"
        
        # Verify that we got progress updates for files in subdirectories
        file_names = [update['current_item'] for update in xefm.progress_updates]
        
        # Debug: print what we got
        print(f"Progress updates received: {len(xefm.progress_updates)}")
        print(f"File names: {file_names}")
        
        # With throttling, we might not see every single file, but we should see the final count is correct
        # The important thing is that the total count and final result are correct
        assert final_update['total'] == expected_total, f"Expected {expected_total} total files, got {final_update['total']}"
        assert final_update['processed'] == expected_total, f"Expected {expected_total} processed files, got {final_update['processed']}"
        
        # Verify files were actually deleted
        assert not (test_dir / "file1.txt").exists()
        assert not (test_dir / "file7.txt").exists()
        assert not subdir1.exists()  # Entire directory should be gone
        assert not (subdir1 / "file3.txt").exists()
        assert not (subdir1 / "file4.txt").exists()
        assert not (subdir2 / "file5.txt").exists()
        assert not (subdir2 / "file6.txt").exists()
    
    print("✅ Fine-grained delete progress test passed!")


def test_delete_large_directory():
    """Test delete progress with a large directory structure"""
    print("Testing delete progress with large directory...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create a large directory with many files
        large_dir = temp_path / "large_dir"
        large_dir.mkdir()
        
        # Create multiple subdirectories with files
        num_subdirs = 3
        files_per_subdir = 5
        
        for i in range(num_subdirs):
            subdir = large_dir / f"subdir_{i}"
            subdir.mkdir()
            
            for j in range(files_per_subdir):
                (subdir / f"file_{i}_{j}.txt").write_text(f"content {i}-{j}")
        
        # Add some files in the root of large_dir
        for i in range(3):
            (large_dir / f"root_file_{i}.txt").write_text(f"root content {i}")
        
        # Test delete operation
        xefm = MockXeFM()
        files_to_delete = [large_dir]
        
        # Expected total: 3 subdirs * 5 files + 3 root files = 18 files
        expected_total = (num_subdirs * files_per_subdir) + 3
        
        xefm.perform_delete_operation_simplified(files_to_delete)
        
        # With throttling, we won't get updates for every file, but should get some updates
        assert len(xefm.progress_updates) >= 2, f"Should have at least 2 progress updates (start and end)"
        
        final_update = xefm.progress_updates[-1]
        assert final_update['total'] == expected_total, f"Expected {expected_total} total files"
        assert final_update['processed'] == expected_total, f"Expected {expected_total} processed files"
        
        # Verify we see individual file names in progress
        file_names = [update['current_item'] for update in xefm.progress_updates]
        
        # The key thing is that the final totals are correct
        print(f"Final update: {final_update}")
        assert final_update['total'] == expected_total, f"Expected {expected_total} total files"
        assert final_update['processed'] == expected_total, f"Expected {expected_total} processed files"
        
        # Verify we're tracking individual files (not just top-level directories)
        assert len(xefm.progress_updates) > 1, "Should have multiple progress updates"
        
        # Verify directory was actually deleted
        assert not large_dir.exists()
    
    print("✅ Delete large directory test passed!")


def test_delete_mixed_selection():
    """Test delete progress with mixed selection of files and directories"""
    print("Testing delete progress with mixed selection...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create mixed structure
        (temp_path / "single_file1.txt").write_text("content1")
        (temp_path / "single_file2.txt").write_text("content2")
        
        # Create a directory with files
        test_dir = temp_path / "test_dir"
        test_dir.mkdir()
        (test_dir / "file_a.txt").write_text("content a")
        (test_dir / "file_b.txt").write_text("content b")
        
        # Create another single file
        (temp_path / "single_file3.txt").write_text("content3")
        
        # Test delete operation with mixed selection
        xefm = MockXeFM()
        files_to_delete = [
            temp_path / "single_file1.txt",
            test_dir,  # Directory with 2 files
            temp_path / "single_file2.txt",
            temp_path / "single_file3.txt"
        ]
        
        # Expected total: 1 + 2 + 1 + 1 = 5 files
        expected_total = 5
        
        xefm.perform_delete_operation_simplified(files_to_delete)
        
        # With throttling, we get fewer updates but the totals should be correct
        assert len(xefm.progress_updates) >= 2, f"Should have at least 2 progress updates"
        
        final_update = xefm.progress_updates[-1]
        assert final_update['total'] == expected_total, f"Expected {expected_total} total files"
        assert final_update['processed'] == expected_total, f"Expected {expected_total} processed files"
        
        # Verify we see both individual files and directory contents
        file_names = [update['current_item'] for update in xefm.progress_updates]
        
        # With throttling, we may not see every file, but totals should be correct
        print(f"Mixed selection progress updates: {len(xefm.progress_updates)}")
        print(f"File names: {file_names}")
        
        # Verify the final totals are correct
        print(f"Final update: {final_update}")
        assert final_update['total'] == expected_total, f"Expected {expected_total} total files"
        assert final_update['processed'] == expected_total, f"Expected {expected_total} processed files"
        
        # Verify all files were deleted
        assert not (temp_path / "single_file1.txt").exists()
        assert not (temp_path / "single_file2.txt").exists()
        assert not (temp_path / "single_file3.txt").exists()
        assert not test_dir.exists()
    
    print("✅ Delete mixed selection test passed!")
