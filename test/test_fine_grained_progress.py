"""
Test fine-grained progress tracking for file operations

Run with: python -m pytest test/test_fine_grained_progress.py -v
"""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock

from xefm.progress_manager import ProgressManager, OperationType


class MockXeFM:
    """Mock XeFM class to test fine-grained progress tracking"""
    
    def __init__(self):
        self.progress_manager = ProgressManager()
        # Disable throttling for testing by setting throttle to 0
        self.progress_manager.callback_throttle_ms = 0
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
    
    def _copy_directory_with_progress(self, source_dir, dest_dir, processed_files, total_files):
        """Copy directory recursively with fine-grained progress updates"""
        try:
            # Create destination directory
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Walk through source directory and copy files one by one
            for root, dirs, files in os.walk(source_dir):
                root_path = Path(root)
                
                # Calculate relative path from source directory
                rel_path = root_path.relative_to(source_dir)
                dest_root = dest_dir / rel_path
                
                # Create subdirectories
                dest_root.mkdir(parents=True, exist_ok=True)
                
                # Copy files in current directory
                for file_name in files:
                    source_file = root_path / file_name
                    dest_file = dest_root / file_name
                    
                    processed_files += 1
                    if total_files > 1:
                        # Show relative path for files in subdirectories
                        display_name = str(rel_path / file_name) if rel_path != Path('.') else file_name
                        self.progress_manager.update_progress(display_name, processed_files)
                    
                    try:
                        if source_file.is_symlink():
                            # Copy symbolic link
                            link_target = os.readlink(str(source_file))
                            dest_file.symlink_to(link_target)
                        else:
                            # Copy regular file
                            shutil.copy2(source_file, dest_file)
                    except Exception as e:
                        print(f"Error copying {source_file}: {e}")
                        if total_files > 1:
                            self.progress_manager.increment_errors()
            
            return processed_files
            
        except Exception as e:
            print(f"Error copying directory {source_dir}: {e}")
            if total_files > 1:
                self.progress_manager.increment_errors()
            return processed_files
    
    def perform_copy_operation_simplified(self, files_to_copy, destination_dir):
        """Simplified copy operation for testing"""
        # Count total individual files for fine-grained progress
        total_individual_files = self._count_files_recursively(files_to_copy)
        
        # Start progress tracking
        if total_individual_files > 1:
            self.progress_manager.start_operation(
                OperationType.COPY, 
                total_individual_files, 
                f"to {destination_dir.name}",
                self._progress_callback
            )
        
        processed_files = 0
        
        try:
            for source_file in files_to_copy:
                dest_path = destination_dir / source_file.name
                
                if source_file.is_dir():
                    # Copy directory recursively with progress tracking
                    processed_files = self._copy_directory_with_progress(
                        source_file, dest_path, processed_files, total_individual_files
                    )
                else:
                    # Copy single file
                    processed_files += 1
                    if total_individual_files > 1:
                        self.progress_manager.update_progress(source_file.name, processed_files)
                    
                    shutil.copy2(source_file, dest_path)
        
        finally:
            # Finish progress tracking
            if total_individual_files > 1:
                self.progress_manager.finish_operation()


def test_fine_grained_copy_progress():
    """Test that copy operations report progress for individual files in directories"""
    print("Testing fine-grained copy progress...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_dir = temp_path / "source"
        dest_dir = temp_path / "dest"
        
        source_dir.mkdir()
        dest_dir.mkdir()
        
        # Create a complex directory structure
        # source/
        #   file1.txt
        #   file2.txt
        #   subdir1/
        #     file3.txt
        #     file4.txt
        #     subdir2/
        #       file5.txt
        #   file6.txt
        
        (source_dir / "file1.txt").write_text("content1")
        (source_dir / "file2.txt").write_text("content2")
        (source_dir / "file6.txt").write_text("content6")
        
        subdir1 = source_dir / "subdir1"
        subdir1.mkdir()
        (subdir1 / "file3.txt").write_text("content3")
        (subdir1 / "file4.txt").write_text("content4")
        
        subdir2 = subdir1 / "subdir2"
        subdir2.mkdir()
        (subdir2 / "file5.txt").write_text("content5")
        
        # Create mock XeFM and perform copy
        xefm = MockXeFM()
        files_to_copy = [source_dir / "file1.txt", source_dir / "subdir1", source_dir / "file6.txt"]
        
        # Count expected total files
        expected_total = 5  # file1.txt + (file3.txt, file4.txt, file5.txt from subdir1) + file6.txt
        
        xefm.perform_copy_operation_simplified(files_to_copy, dest_dir)
        
        # Verify progress tracking
        assert len(xefm.progress_updates) > 0, "Should have progress updates"
        
        # Check that we got updates for individual files
        final_update = xefm.progress_updates[-1]
        assert final_update['total'] == expected_total, f"Expected {expected_total} total files, got {final_update['total']}"
        assert final_update['processed'] == expected_total, f"Expected {expected_total} processed files, got {final_update['processed']}"
        
        # Verify that we got progress updates for files in subdirectories
        file_names = [update['current_item'] for update in xefm.progress_updates]
        
        # Should see individual files from the directory
        assert any("file3.txt" in name for name in file_names), "Should track file3.txt in subdirectory"
        assert any("file4.txt" in name for name in file_names), "Should track file4.txt in subdirectory"
        assert any("file5.txt" in name for name in file_names), "Should track file5.txt in nested subdirectory"
        
        # Verify files were actually copied
        assert (dest_dir / "file1.txt").exists()
        assert (dest_dir / "file6.txt").exists()
        assert (dest_dir / "subdir1" / "file3.txt").exists()
        assert (dest_dir / "subdir1" / "file4.txt").exists()
        assert (dest_dir / "subdir1" / "subdir2" / "file5.txt").exists()
    
    print("✅ Fine-grained copy progress test passed!")


def test_file_counting():
    """Test that file counting works correctly for complex directory structures"""
    print("Testing recursive file counting...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test structure
        # test/
        #   file1.txt
        #   dir1/
        #     file2.txt
        #     file3.txt
        #     dir2/
        #       file4.txt
        #   file5.txt
        
        test_dir = temp_path / "test"
        test_dir.mkdir()
        
        (test_dir / "file1.txt").write_text("content")
        (test_dir / "file5.txt").write_text("content")
        
        dir1 = test_dir / "dir1"
        dir1.mkdir()
        (dir1 / "file2.txt").write_text("content")
        (dir1 / "file3.txt").write_text("content")
        
        dir2 = dir1 / "dir2"
        dir2.mkdir()
        (dir2 / "file4.txt").write_text("content")
        
        # Test counting
        xefm = MockXeFM()
        
        # Count individual files
        single_file_count = xefm._count_files_recursively([test_dir / "file1.txt"])
        assert single_file_count == 1, f"Single file should count as 1, got {single_file_count}"
        
        # Count directory
        dir_count = xefm._count_files_recursively([dir1])
        assert dir_count == 3, f"dir1 should contain 3 files, got {dir_count}"
        
        # Count entire structure
        total_count = xefm._count_files_recursively([test_dir])
        assert total_count == 5, f"Total should be 5 files, got {total_count}"
        
        # Count mixed selection
        mixed_count = xefm._count_files_recursively([test_dir / "file1.txt", dir1, test_dir / "file5.txt"])
        assert mixed_count == 5, f"Mixed selection should be 5 files, got {mixed_count}"
    
    print("✅ File counting test passed!")


def test_progress_granularity():
    """Test that progress updates are granular enough for large directories"""
    print("Testing progress granularity...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_dir = temp_path / "source"
        dest_dir = temp_path / "dest"
        
        source_dir.mkdir()
        dest_dir.mkdir()
        
        # Create a directory with many files
        large_dir = source_dir / "large_dir"
        large_dir.mkdir()
        
        num_files = 20
        for i in range(num_files):
            (large_dir / f"file_{i:03d}.txt").write_text(f"content {i}")
        
        # Also add a single file
        (source_dir / "single_file.txt").write_text("single content")
        
        # Test copy operation
        xefm = MockXeFM()
        files_to_copy = [source_dir / "single_file.txt", large_dir]
        
        xefm.perform_copy_operation_simplified(files_to_copy, dest_dir)
        
        # Verify we got progress updates for each individual file
        expected_total = num_files + 1  # 20 files in directory + 1 single file
        
        assert len(xefm.progress_updates) >= expected_total, f"Should have at least {expected_total} progress updates"
        
        final_update = xefm.progress_updates[-1]
        assert final_update['total'] == expected_total, f"Expected {expected_total} total files"
        assert final_update['processed'] == expected_total, f"Expected {expected_total} processed files"
        
        # Verify we see individual file names in progress
        file_names = [update['current_item'] for update in xefm.progress_updates]
        assert "single_file.txt" in file_names, "Should see single file in progress"
        
        # Should see some of the numbered files
        numbered_files = [name for name in file_names if "file_" in name and ".txt" in name]
        assert len(numbered_files) >= 10, f"Should see multiple numbered files, got {len(numbered_files)}"
    
    print("✅ Progress granularity test passed!")
