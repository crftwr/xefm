"""
Test visual progress updates during delete operations

Run with: python -m pytest test/test_visual_progress_updates.py -v
"""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock

from xefm.progress_manager import ProgressManager, OperationType


class VisualTestXeFM:
    """Test XeFM class that simulates visual progress updates"""
    
    def __init__(self):
        self.progress_manager = ProgressManager()
        self.stdscr = Mock()
        self.progress_updates = []
        self.status_draws = []
        
    def draw_status(self):
        """Mock draw_status that records when it's called"""
        if self.progress_manager.is_operation_active():
            progress_text = self.progress_manager.get_progress_text(80)
            self.status_draws.append(progress_text)
            print(f"Status: {progress_text}")
        
    def _progress_callback(self, progress_data):
        """Progress callback that simulates the real XeFM behavior"""
        if progress_data:
            self.progress_updates.append(progress_data.copy())
        
        try:
            # Draw the status line with progress
            self.draw_status()
            
            # Simulate screen refresh
            self.stdscr.refresh()
            
            # Add a tiny delay to simulate real screen update time
            time.sleep(0.01)
            
        except:
            pass
    
    def _count_files_recursively(self, paths):
        """Count total number of individual files in the given paths"""
        total_files = 0
        for path in paths:
            if path.is_file() or path.is_symlink():
                total_files += 1
            elif path.is_dir():
                try:
                    for root, dirs, files in os.walk(path):
                        total_files += len(files)
                        for d in dirs:
                            dir_path = Path(root) / d
                            if dir_path.is_symlink():
                                total_files += 1
                except (PermissionError, OSError):
                    total_files += 1
        return total_files
    
    def _delete_directory_with_progress(self, dir_path, processed_files, total_files):
        """Delete directory with visual progress updates"""
        for root, dirs, files in os.walk(dir_path, topdown=False):
            root_path = Path(root)
            
            # Delete files in current directory
            for file_name in files:
                file_path = root_path / file_name
                processed_files += 1
                
                if total_files > 1:
                    try:
                        rel_path = file_path.relative_to(dir_path)
                        display_name = str(rel_path)
                    except ValueError:
                        display_name = file_path.name
                    
                    # This should trigger visual update
                    self.progress_manager.update_progress(display_name, processed_files)
                
                # Simulate file deletion time
                time.sleep(0.05)
                file_path.unlink()
            
            # Handle symbolic links to directories
            for dir_name in dirs:
                subdir_path = root_path / dir_name
                try:
                    if subdir_path.is_symlink():
                        processed_files += 1
                        if total_files > 1:
                            try:
                                rel_path = subdir_path.relative_to(dir_path)
                                display_name = f"Link: {rel_path}"
                            except ValueError:
                                display_name = f"Link: {subdir_path.name}"
                            self.progress_manager.update_progress(display_name, processed_files)
                        time.sleep(0.05)
                        subdir_path.unlink()
                    else:
                        subdir_path.rmdir()
                except OSError:
                    pass
        
        # Remove the main directory
        try:
            dir_path.rmdir()
        except OSError:
            import shutil
            shutil.rmtree(dir_path)
        
        return processed_files
    
    def test_delete_with_visual_progress(self, files_to_delete):
        """Test delete operation with visual progress tracking"""
        total_individual_files = self._count_files_recursively(files_to_delete)
        
        print(f"Starting delete operation for {total_individual_files} files...")
        
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
                    processed_files += 1
                    if total_individual_files > 1:
                        self.progress_manager.update_progress(f"Link: {file_path.name}", processed_files)
                    
                    time.sleep(0.05)
                    file_path.unlink()
                elif file_path.is_dir():
                    processed_files = self._delete_directory_with_progress(
                        file_path, processed_files, total_individual_files
                    )
                else:
                    processed_files += 1
                    if total_individual_files > 1:
                        self.progress_manager.update_progress(file_path.name, processed_files)
                    
                    time.sleep(0.05)
                    file_path.unlink()
        
        finally:
            if total_individual_files > 1:
                self.progress_manager.finish_operation()
        
        print(f"Delete operation completed!")
        return len(self.progress_updates), len(self.status_draws)


def test_visual_progress_updates():
    """Test that progress updates trigger visual status updates"""
    print("Testing visual progress updates during delete operations...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create a test directory structure
        test_dir = temp_path / "test_dir"
        test_dir.mkdir()
        
        # Create files in main directory
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")
        
        # Create subdirectory with files
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("content3")
        (subdir / "file4.txt").write_text("content4")
        (subdir / "file5.txt").write_text("content5")
        
        # Create another file
        (test_dir / "file6.txt").write_text("content6")
        
        # Test delete operation
        xefm = VisualTestXeFM()
        files_to_delete = [test_dir]
        
        progress_updates, status_draws = xefm.test_delete_with_visual_progress(files_to_delete)
        
        print(f"\nResults:")
        print(f"Progress updates: {progress_updates}")
        print(f"Status draws: {status_draws}")
        
        # Verify we got visual updates
        assert progress_updates > 0, "Should have progress updates"
        assert status_draws > 0, "Should have status draws"
        assert status_draws >= progress_updates, "Should have at least as many status draws as progress updates"
        
        # Verify we see individual files in the status draws
        status_text = " ".join(xefm.status_draws)
        assert "file1.txt" in status_text or "file2.txt" in status_text, "Should see individual files in status"
        
        print("✅ Visual progress updates test passed!")


def test_progress_callback_frequency():
    """Test that progress callbacks are called at appropriate frequency"""
    print("\nTesting progress callback frequency...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create a directory with many files
        large_dir = temp_path / "large_dir"
        large_dir.mkdir()
        
        # Create 10 files
        for i in range(10):
            (large_dir / f"file_{i:02d}.txt").write_text(f"content {i}")
        
        # Test delete operation
        xefm = VisualTestXeFM()
        files_to_delete = [large_dir]
        
        start_time = time.time()
        progress_updates, status_draws = xefm.test_delete_with_visual_progress(files_to_delete)
        end_time = time.time()
        
        duration = end_time - start_time
        
        print(f"Operation took {duration:.2f} seconds")
        print(f"Progress updates: {progress_updates}")
        print(f"Status draws: {status_draws}")
        print(f"Updates per second: {progress_updates / duration:.1f}")
        
        # Verify reasonable update frequency
        assert progress_updates >= 10, f"Should have at least 10 progress updates for 10 files, got {progress_updates}"
        assert status_draws >= 10, f"Should have at least 10 status draws, got {status_draws}"
        
        # Verify updates aren't too fast (should take some time due to delays)
        assert duration > 0.5, f"Operation should take at least 0.5 seconds with delays, took {duration:.2f}"
        
        print("✅ Progress callback frequency test passed!")
