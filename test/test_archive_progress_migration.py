"""
Test that archive progress migration works correctly

Run with: python -m pytest test/test_archive_progress_migration.py -v
"""

from unittest.mock import Mock, MagicMock

from xefm.progress_manager import ProgressManager, OperationType


class MockFileManager:
    """Mock FileManager class to test archive progress migration"""
    
    def __init__(self):
        self.progress_manager = ProgressManager()
        self.stdscr = Mock()
        
    def _progress_callback(self, progress_data):
        """Mock progress callback"""
        pass
        
    def draw_status(self):
        """Mock draw_status method"""
        pass
        
    def update_archive_progress(self, current_file, processed, total):
        """Update status bar with archive creation progress (legacy method - now uses ProgressManager)"""
        # Update the progress manager if an operation is active
        if self.progress_manager.is_operation_active():
            self.progress_manager.update_progress(current_file, processed)
        
        # Force a screen refresh to show progress
        try:
            self.draw_status()
            self.stdscr.refresh()
        except:
            pass  # Ignore drawing errors during progress updates


def test_archive_progress_migration():
    """Test that the legacy update_archive_progress method works with new ProgressManager"""
    print("Testing archive progress migration...")
    
    # Create mock file manager
    fm = MockFileManager()
    
    # Test that legacy method works when no operation is active
    fm.update_archive_progress("test.txt", 1, 10)
    # Should not crash, but also should not update anything since no operation is active
    assert not fm.progress_manager.is_operation_active()
    
    # Start an archive operation
    fm.progress_manager.start_operation(
        OperationType.ARCHIVE_CREATE,
        10,
        "ZIP: test.zip",
        fm._progress_callback
    )
    
    # Test that legacy method updates the progress manager
    fm.update_archive_progress("file1.txt", 1, 10)
    
    operation = fm.progress_manager.get_current_operation()
    assert operation is not None
    assert operation['processed_items'] == 1
    assert operation['current_item'] == "file1.txt"
    
    # Test multiple updates
    fm.update_archive_progress("file2.txt", 2, 10)
    operation = fm.progress_manager.get_current_operation()
    assert operation['processed_items'] == 2
    assert operation['current_item'] == "file2.txt"
    
    # Test progress percentage
    assert fm.progress_manager.get_progress_percentage() == 20
    
    # Test progress text generation
    progress_text = fm.progress_manager.get_progress_text(80)
    assert "Creating archive" in progress_text
    assert "2/10" in progress_text
    assert "file2.txt" in progress_text
    
    # Finish the operation
    fm.progress_manager.finish_operation()
    assert not fm.progress_manager.is_operation_active()
    
    print("✅ Archive progress migration test passed!")


def test_legacy_compatibility():
    """Test that legacy archive progress calls still work"""
    print("Testing legacy compatibility...")
    
    fm = MockFileManager()
    
    # Simulate archive creation workflow
    files_to_archive = ["file1.txt", "file2.txt", "file3.txt", "file4.txt", "file5.txt"]
    
    # Start operation (this would be done in create_zip_archive or create_tar_archive)
    fm.progress_manager.start_operation(
        OperationType.ARCHIVE_CREATE,
        len(files_to_archive),
        "ZIP: backup.zip",
        fm._progress_callback
    )
    
    # Simulate legacy progress updates (as would be called from archive creation code)
    for i, filename in enumerate(files_to_archive, 1):
        fm.update_archive_progress(filename, i, len(files_to_archive))
        
        # Verify progress is being tracked correctly
        operation = fm.progress_manager.get_current_operation()
        assert operation['processed_items'] == i
        assert operation['current_item'] == filename
        
        expected_percentage = int((i / len(files_to_archive)) * 100)
        assert fm.progress_manager.get_progress_percentage() == expected_percentage
    
    # Verify final state
    operation = fm.progress_manager.get_current_operation()
    assert operation['processed_items'] == 5
    assert operation['current_item'] == "file5.txt"
    assert fm.progress_manager.get_progress_percentage() == 100
    
    # Finish operation
    fm.progress_manager.finish_operation()
    assert not fm.progress_manager.is_operation_active()
    
    print("✅ Legacy compatibility test passed!")
