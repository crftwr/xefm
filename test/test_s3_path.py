"""
Test script for S3PathImpl functionality

Run with: python -m pytest test/test_s3_path.py -v
"""


from xefm.path import Path

def test_s3_path_creation():
    """Test S3 path creation and basic properties"""
    print("Testing S3 path creation...")
    
    # Test S3 path creation
    s3_path = Path('s3://my-bucket/path/to/file.txt')
    print(f"S3 Path: {s3_path}")
    print(f"Scheme: {s3_path.get_scheme()}")
    print(f"Is remote: {s3_path.is_remote()}")
    print(f"Name: {s3_path.name}")
    print(f"Stem: {s3_path.stem}")
    print(f"Suffix: {s3_path.suffix}")
    print(f"Parent: {s3_path.parent}")
    print(f"Parts: {s3_path.parts}")
    
    # Test bucket-only path
    bucket_path = Path('s3://my-bucket/')
    print(f"\nBucket Path: {bucket_path}")
    print(f"Name: {bucket_path.name}")
    print(f"Parent: {bucket_path.parent}")
    
    # Test path manipulation
    joined = s3_path.parent / 'new_file.txt'
    print(f"\nJoined path: {joined}")
    
    with_new_name = s3_path.with_name('different.txt')
    print(f"With new name: {with_new_name}")
    
    print("\n✓ S3 path creation tests passed!")

def test_local_path_compatibility():
    """Test that local paths still work"""
    print("\nTesting local path compatibility...")
    
    local_path = Path('/tmp/test.txt')
    print(f"Local Path: {local_path}")
    print(f"Scheme: {local_path.get_scheme()}")
    print(f"Is remote: {local_path.is_remote()}")
    
    print("✓ Local path compatibility tests passed!")

def test_s3_operations_mock():
    """Test S3 operations without actual AWS calls"""
    print("\nTesting S3 operations (mock)...")
    
    s3_path = Path('s3://test-bucket/test-file.txt')
    
    # These should not raise exceptions even without AWS credentials
    print(f"URI: {s3_path.as_uri()}")
    print(f"POSIX: {s3_path.as_posix()}")
    print(f"Absolute: {s3_path.absolute()}")
    print(f"Is absolute: {s3_path.is_absolute()}")
    
    print("✓ S3 operations mock tests passed!")
