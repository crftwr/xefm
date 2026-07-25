"""
Test the progress manager functionality

Run with: python -m pytest test/test_progress_manager.py -v
"""


from pathlib import Path
from xefm.progress_manager import ProgressManager, OperationType


def test_progress_manager():
    """Test the progress manager functionality"""
    print("Testing Progress Manager...")
    
    # Test basic functionality
    progress_manager = ProgressManager()
    
    # Test initial state
    assert not progress_manager.is_operation_active()
    assert progress_manager.get_current_operation() is None
    assert progress_manager.get_progress_percentage() == 0
    
    # Test starting an operation
    progress_manager.start_operation(OperationType.COPY, 10, "test files")
    
    assert progress_manager.is_operation_active()
    operation = progress_manager.get_current_operation()
    assert operation is not None
    assert operation['type'] == OperationType.COPY
    assert operation['total_items'] == 10
    assert operation['processed_items'] == 0
    assert operation['description'] == "test files"
    
    # Test updating progress
    progress_manager.update_progress("file1.txt")
    operation = progress_manager.get_current_operation()
    assert operation['processed_items'] == 1
    assert operation['current_item'] == "file1.txt"
    assert progress_manager.get_progress_percentage() == 10
    
    # Test manual progress count
    progress_manager.update_progress("file5.txt", 5)
    operation = progress_manager.get_current_operation()
    assert operation['processed_items'] == 5
    assert operation['current_item'] == "file5.txt"
    assert progress_manager.get_progress_percentage() == 50
    
    # Test error tracking
    progress_manager.increment_errors()
    operation = progress_manager.get_current_operation()
    assert operation['errors'] == 1
    
    # Test progress text generation
    progress_text = progress_manager.get_progress_text(80)
    assert "Copying" in progress_text
    assert "5/10" in progress_text
    assert "file5.txt" in progress_text
    
    # Test finishing operation
    progress_manager.finish_operation()
    assert not progress_manager.is_operation_active()
    assert progress_manager.get_current_operation() is None
    
    print("✅ Progress Manager tests passed!")


def test_operation_types():
    """Test different operation types"""
    print("Testing operation types...")
    
    progress_manager = ProgressManager()
    
    # Test each operation type
    operations = [
        (OperationType.COPY, "Copying"),
        (OperationType.MOVE, "Moving"),
        (OperationType.DELETE, "Deleting"),
        (OperationType.ARCHIVE_CREATE, "Creating archive"),
        (OperationType.ARCHIVE_EXTRACT, "Extracting archive")
    ]
    
    for op_type, expected_verb in operations:
        progress_manager.start_operation(op_type, 5, "test")
        progress_manager.update_progress("test_file.txt", 1)
        
        progress_text = progress_manager.get_progress_text(80)
        assert expected_verb in progress_text
        
        progress_manager.finish_operation()
    
    print("✅ Operation types tests passed!")


def test_progress_text_formatting():
    """Test progress text formatting with different widths"""
    print("Testing progress text formatting...")
    
    progress_manager = ProgressManager()
    progress_manager.start_operation(OperationType.COPY, 100, "many files")
    progress_manager.update_progress("very_long_filename_that_should_be_truncated.txt", 50)
    
    # Test with narrow width
    narrow_text = progress_manager.get_progress_text(40)
    assert len(narrow_text) <= 40
    assert "50/100" in narrow_text
    
    # Test with wide width
    wide_text = progress_manager.get_progress_text(120)
    assert "very_long_filename" in wide_text
    
    progress_manager.finish_operation()
    
    print("✅ Progress text formatting tests passed!")
