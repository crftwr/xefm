"""
Test file associations integration with XeFM

Run with: python -m pytest test/test_file_associations_integration.py -v
"""


from xefm.config import get_program_for_file, has_action_for_file


def test_open_action():
    """Test that open action works for various file types"""
    print("Testing 'open' action:")
    
    test_files = [
        'document.pdf',
        'photo.jpg',
        'video.mp4',
        'song.mp3',
        'script.py'
    ]
    
    for filename in test_files:
        command = get_program_for_file(filename, 'open')
        if command:
            print(f"  ✓ {filename:20s} -> {' '.join(command)}")
        else:
            print(f"  ✗ {filename:20s} -> No program configured")


def test_view_action():
    """Test that view action works for various file types"""
    print("\nTesting 'view' action:")
    
    test_files = [
        'document.pdf',
        'photo.jpg',
        'video.mp4',
        'readme.txt'
    ]
    
    for filename in test_files:
        command = get_program_for_file(filename, 'view')
        if command:
            print(f"  ✓ {filename:20s} -> {' '.join(command)}")
        else:
            print(f"  ✗ {filename:20s} -> No program configured")


def test_edit_action():
    """Test that edit action works for various file types"""
    print("\nTesting 'edit' action:")
    
    test_files = [
        'document.pdf',
        'photo.jpg',
        'script.py',
        'readme.txt'
    ]
    
    for filename in test_files:
        command = get_program_for_file(filename, 'edit')
        if command:
            print(f"  ✓ {filename:20s} -> {' '.join(command)}")
        else:
            print(f"  ✗ {filename:20s} -> No program configured")


def test_action_availability():
    """Test checking if actions are available"""
    print("\nTesting action availability:")
    
    test_cases = [
        ('photo.jpg', 'open', True),
        ('photo.jpg', 'view', True),
        ('photo.jpg', 'edit', True),
        ('video.avi', 'edit', False),  # AVI has edit set to None
        ('unknown.xyz', 'open', False),
    ]
    
    for filename, action, expected in test_cases:
        available = has_action_for_file(filename, action)
        status = "✓" if available == expected else "✗"
        print(f"  {status} {filename:20s} {action:6s} -> {available} (expected {expected})")


def test_combined_actions():
    """Test that combined actions (open|view) work correctly"""
    print("\nTesting combined actions (open|view):")
    
    # For images, open and view should use the same program
    filename = 'photo.png'
    open_cmd = get_program_for_file(filename, 'open')
    view_cmd = get_program_for_file(filename, 'view')
    
    if open_cmd == view_cmd:
        print(f"  ✓ {filename}: open and view use same program")
        print(f"    Command: {' '.join(open_cmd)}")
    else:
        print(f"  ✗ {filename}: open and view use different programs")
        print(f"    Open: {' '.join(open_cmd) if open_cmd else 'None'}")
        print(f"    View: {' '.join(view_cmd) if view_cmd else 'None'}")


def main():
    """Run all integration tests"""
    print("=" * 60)
    print("File Associations Integration Tests")
    print("=" * 60)
    
    try:
        test_open_action()
        test_view_action()
        test_edit_action()
        test_action_availability()
        test_combined_actions()
        
        print("\n" + "=" * 60)
        print("✅ All integration tests completed!")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
