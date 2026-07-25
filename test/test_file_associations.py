"""
Test file extension associations functionality

Run with: python -m pytest test/test_file_associations.py -v
"""


from xefm.config import get_file_associations, get_program_for_file, has_action_for_file


def test_get_file_associations():
    """Test getting file associations from config"""
    associations = get_file_associations()
    assert isinstance(associations, list), "FILE_ASSOCIATIONS should be a list"
    assert len(associations) > 0, "FILE_ASSOCIATIONS should not be empty"
    print("✓ get_file_associations() returns a list with entries")


def test_pattern_matching():
    """Test pattern matching for different file extensions"""
    # Test PDF files
    command = get_program_for_file('document.pdf', 'open')
    assert command is not None, "Should find program for PDF files"
    assert isinstance(command, list), "Command should be a list"
    print(f"✓ PDF open command: {command}")
    
    # Test case-insensitive matching
    command_upper = get_program_for_file('DOCUMENT.PDF', 'open')
    assert command_upper == command, "Pattern matching should be case-insensitive"
    print("✓ Case-insensitive matching works")
    
    # Test image files
    jpg_command = get_program_for_file('photo.jpg', 'view')
    assert jpg_command is not None, "Should find program for JPG files"
    print(f"✓ JPG view command: {jpg_command}")
    
    # Test video files
    mp4_command = get_program_for_file('video.mp4', 'open')
    assert mp4_command is not None, "Should find program for MP4 files"
    print(f"✓ MP4 open command: {mp4_command}")


def test_multiple_actions():
    """Test that same file can have different programs for different actions"""
    # For image files, open and view should use Preview, edit should use different program
    open_cmd = get_program_for_file('image.jpg', 'open')
    view_cmd = get_program_for_file('image.jpg', 'view')
    edit_cmd = get_program_for_file('image.jpg', 'edit')
    
    assert open_cmd is not None, "Should have open command for JPG"
    assert view_cmd is not None, "Should have view command for JPG"
    assert edit_cmd is not None, "Should have edit command for JPG"
    
    # Open and view should be the same for images (Preview)
    assert open_cmd == view_cmd, "Open and view should use same program for images"
    
    # Edit should be different (image editor)
    assert edit_cmd != open_cmd, "Edit should use different program than open/view"
    
    print(f"✓ JPG open: {open_cmd}")
    print(f"✓ JPG view: {view_cmd}")
    print(f"✓ JPG edit: {edit_cmd}")


def test_has_action():
    """Test checking if action is available for file"""
    # PDF has open/view; its edit is None in the default config (no editor).
    assert has_action_for_file('doc.pdf', 'open'), "PDF should have open action"
    assert has_action_for_file('doc.pdf', 'view'), "PDF should have view action"
    assert not has_action_for_file('doc.pdf', 'edit'), "PDF edit is None in default config"
    print("✓ has_action_for_file() works for available actions")
    
    # Unknown extension should not have actions
    assert not has_action_for_file('file.xyz', 'open'), "Unknown extension should not have actions"
    print("✓ has_action_for_file() returns False for unknown extensions")


def test_no_match():
    """Test behavior when no pattern matches"""
    command = get_program_for_file('unknown.xyz', 'open')
    assert command is None, "Should return None for unknown extensions"
    print("✓ Returns None for unknown file extensions")


def test_none_action():
    """Test files with None action (action not available)"""
    # AVI files have edit set to None in default config
    edit_cmd = get_program_for_file('video.mp4', 'edit')
    assert edit_cmd is None, "mp4 edit is None (not configured)"
    
    # But open and view should work
    open_cmd = get_program_for_file('video.mp4', 'open')
    assert open_cmd is not None, "mp4 open should be available"
    
    print("✓ None actions handled correctly")


def main():
    """Run all tests"""
    print("Testing File Extension Associations\n")
    
    try:
        test_get_file_associations()
        test_pattern_matching()
        test_multiple_actions()
        test_has_action()
        test_no_match()
        test_none_action()
        
        print("\n✅ All tests passed!")
        return 0
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
