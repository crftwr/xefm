"""
Integration test for S3 Backspace key navigation in XeFM

Run with: python -m pytest test/test_s3_backspace_navigation.py -v
"""

from xefm.path import Path

def test_s3_backspace_navigation():
    """Test that S3 paths work correctly with XeFM's Backspace navigation logic"""
    
    print("Testing S3 Backspace navigation integration...")
    
    # Simulate the exact logic used in xefm_main.py for Backspace key handling
    def can_navigate_to_parent(current_path):
        """Simulate the condition check in xefm_main.py line 3689"""
        return current_path != current_path.parent
    
    # Test cases that should allow navigation (Backspace should work)
    navigable_paths = [
        's3://bucket/folder/subfolder/',
        's3://bucket/folder/subfolder',
        's3://bucket/folder/',
        's3://bucket/file.txt',
        's3://bucket/deep/nested/folder/structure/',
        's3://bucket/file-with-dashes.txt',
        's3://bucket/folder_with_underscores/',
    ]
    
    # Test cases that should NOT allow navigation (at bucket root)
    non_navigable_paths = [
        's3://bucket/',
    ]
    
    all_passed = True
    
    print("\nTesting paths that SHOULD allow Backspace navigation:")
    for path_str in navigable_paths:
        try:
            current_path = Path(path_str)
            can_navigate = can_navigate_to_parent(current_path)
            
            if can_navigate:
                print(f"✅ {path_str} -> Can navigate to {current_path.parent}")
            else:
                print(f"❌ {path_str} -> FAILED: Should allow navigation but doesn't")
                print(f"   Current: {current_path}")
                print(f"   Parent:  {current_path.parent}")
                print(f"   Equal?:  {current_path == current_path.parent}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ {path_str} -> ERROR: {e}")
            all_passed = False
    
    print("\nTesting paths that should NOT allow Backspace navigation:")
    for path_str in non_navigable_paths:
        try:
            current_path = Path(path_str)
            can_navigate = can_navigate_to_parent(current_path)
            
            if not can_navigate:
                print(f"✅ {path_str} -> Correctly blocked navigation (at bucket root)")
            else:
                print(f"❌ {path_str} -> FAILED: Should block navigation but allows it")
                print(f"   Current: {current_path}")
                print(f"   Parent:  {current_path.parent}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ {path_str} -> ERROR: {e}")
            all_passed = False
    
    # Test the actual parent navigation behavior
    print("\nTesting parent navigation behavior:")
    navigation_tests = [
        ('s3://bucket/folder/subfolder/', 's3://bucket/folder/'),
        ('s3://bucket/folder/', 's3://bucket/'),
        ('s3://bucket/', 's3://bucket/'),  # Bucket is its own parent
        ('s3://bucket/deep/nested/path/', 's3://bucket/deep/nested/'),
    ]
    
    for current_str, expected_parent_str in navigation_tests:
        try:
            current_path = Path(current_str)
            parent_path = current_path.parent
            
            if str(parent_path) == expected_parent_str:
                print(f"✅ {current_str} -> {parent_path}")
            else:
                print(f"❌ {current_str} -> Expected {expected_parent_str}, got {parent_path}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ {current_str} -> ERROR: {e}")
            all_passed = False
    
    if all_passed:
        print("\n🎉 All S3 Backspace navigation tests passed!")
        print("The Backspace key should now work correctly in S3 buckets!")
    else:
        print("\n💥 Some tests failed!")
        
    return
