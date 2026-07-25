"""
Test file extension associations functionality

Run with: python -m pytest test/test_file_associations.py -v
"""


import pytest

from xefm._config import Config as DefaultConfig
from xefm.config import (config_manager, get_file_associations,
                         get_program_for_file, has_action_for_file)


@pytest.fixture(autouse=True)
def shipped_config(monkeypatch):
    """Assert against the shipped defaults, not against ~/.xefm/config.py.

    These lookups read the *active* configuration, which is the developer's own
    file whenever one exists — so without this the suite (and the `make release`
    gate that runs it) would pass or fail depending on whose machine it ran on.
    Pinning the template keeps these tests a check on xefm/_config.py.
    """
    monkeypatch.setattr(config_manager, "config", DefaultConfig())


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
    
    # Test image files. 'view' is deliberately unset for images in the default
    # config so V opens XeFM's own image viewer instead of handing the file to
    # Preview; 'open' still routes to the OS app.
    jpg_command = get_program_for_file('photo.jpg', 'open')
    assert jpg_command is not None, "Should find program for JPG files"
    assert get_program_for_file('photo.jpg', 'view') is None, \
        "JPG view stays with the built-in image viewer"
    print(f"✓ JPG open command: {jpg_command}")

    # Test video files
    mp4_command = get_program_for_file('video.mp4', 'open')
    assert mp4_command is not None, "Should find program for MP4 files"
    print(f"✓ MP4 open command: {mp4_command}")


def test_multiple_actions():
    """Test that same file can have different programs for different actions"""
    # For image files: open hands off to Preview, edit to an image editor, and
    # view is None so the built-in viewer takes it.
    open_cmd = get_program_for_file('image.jpg', 'open')
    view_cmd = get_program_for_file('image.jpg', 'view')
    edit_cmd = get_program_for_file('image.jpg', 'edit')

    assert open_cmd is not None, "Should have open command for JPG"
    assert edit_cmd is not None, "Should have edit command for JPG"
    assert view_cmd is None, "JPG view is None so XeFM's own image viewer handles it"

    # Edit should be different (image editor)
    assert edit_cmd != open_cmd, "Edit should use different program than open/view"

    print(f"✓ JPG open: {open_cmd}")
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
