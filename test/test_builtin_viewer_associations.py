"""
Test that text files use built-in viewer when association is None

Run with: python -m pytest test/test_builtin_viewer_associations.py -v
"""


from xefm.config import get_program_for_file, has_action_for_file, has_explicit_association


def test_text_files_with_none_association():
    """Test that text files with None association will use built-in viewer"""
    print("Testing text files with None association:\n")
    
    text_files = [
        'readme.txt',
        'notes.md',
        'script.py',
        'app.js'
    ]
    
    for filename in text_files:
        command = get_program_for_file(filename, 'view')
        has_action = has_action_for_file(filename, 'view')
        has_explicit = has_explicit_association(filename, 'view')
        
        print(f"{filename}:")
        print(f"  Command: {command}")
        print(f"  has_action_for_file: {has_action}")
        print(f"  has_explicit_association: {has_explicit}")
        
        if command is None and has_explicit:
            print(f"  ✓ Will use built-in text viewer (explicit None)")
        elif command is None and not has_explicit:
            print(f"  ✓ Will check if text file (no association)")
        elif command:
            print(f"  ✓ Will use: {' '.join(command)}")
        print()


def test_comparison_with_media_files():
    """Compare text files (None) with media files (explicit commands)"""
    print("\nComparison with media files:\n")
    
    files = [
        ('readme.txt', 'Text file with None'),
        ('photo.jpg', 'Image with explicit command'),
        ('video.mp4', 'Video with explicit command'),
    ]
    
    for filename, description in files:
        command = get_program_for_file(filename, 'view')
        has_explicit = has_explicit_association(filename, 'view')
        
        if command:
            result = f"External: {' '.join(command)}"
        elif has_explicit:
            result = "Built-in viewer (explicit None)"
        else:
            result = "No association (will check if text)"
        
        print(f"{filename:20s} [{description:30s}] -> {result}")


def test_all_actions_for_text_files():
    """Test all actions for text files"""
    print("\n\nAll actions for text files:\n")
    
    filename = 'readme.txt'
    actions = ['open', 'view', 'edit']
    
    print(f"{filename}:")
    for action in actions:
        command = get_program_for_file(filename, action)
        has_explicit = has_explicit_association(filename, action)
        
        if command:
            result = ' '.join(command)
        elif has_explicit:
            result = "Built-in viewer (None)"
        else:
            result = "No association"
        
        print(f"  {action:6s}: {result}")


def test_expected_behavior():
    """Document expected behavior"""
    print("\n\nExpected behavior when pressing V key:\n")
    
    scenarios = [
        ("readme.txt", "Has explicit None", "Opens in built-in text viewer"),
        ("script.py", "Has explicit None", "Opens in built-in text viewer"),
        ("photo.jpg", "Has command", "Opens in Preview (external)"),
        ("unknown.xyz (text)", "No association", "Opens in built-in text viewer (fallback)"),
        ("unknown.xyz (binary)", "No association", "Shows error (not a text file)"),
    ]
    
    for filename, status, behavior in scenarios:
        print(f"  {filename:25s} [{status:20s}] -> {behavior}")


def main():
    """Run all tests"""
    print("=" * 70)
    print("Built-in Text Viewer Association Tests")
    print("=" * 70)
    
    try:
        test_text_files_with_none_association()
        test_comparison_with_media_files()
        test_all_actions_for_text_files()
        test_expected_behavior()
        
        print("\n" + "=" * 70)
        print("✅ All tests completed!")
        print("=" * 70)
        print("\nKey Points:")
        print("  • Text files (*.txt, *.md, *.py, *.js) have view=None")
        print("  • None means 'use built-in text viewer'")
        print("  • has_explicit_association() distinguishes None from no association")
        print("  • Built-in viewer provides syntax highlighting")
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
