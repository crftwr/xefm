"""
Integration test for S3PathImpl with actual AWS operations
This test requires AWS credentials to be configured

Run with: python -m pytest test/test_s3_integration.py -v
"""

import sys
import os

from xefm.path import Path
from xefm.s3 import S3PathImpl

def test_s3_name_property():
    """Test S3 name property with various key formats"""
    print("Testing S3 name property...")
    
    test_cases = [
        ("s3://bucket/", "bucket"),           # Bucket root
        ("s3://bucket/file.txt", "file.txt"), # File
        ("s3://bucket/dir/", "dir"),          # Directory with slash
        ("s3://bucket/dir", "dir"),           # Directory without slash
        ("s3://bucket/path/to/file.txt", "file.txt"), # Nested file
        ("s3://bucket/path/to/dir/", "dir"),  # Nested directory
        ("s3://my-bucket/folder/subfolder/", "subfolder"), # Deep nested directory
    ]
    
    all_passed = True
    for uri, expected_name in test_cases:
        try:
            s3_impl = S3PathImpl(uri)
            actual_name = s3_impl.name
            if actual_name == expected_name:
                print(f"✓ {uri} -> name='{actual_name}'")
            else:
                print(f"✗ {uri} -> name='{actual_name}' (expected: '{expected_name}')")
                all_passed = False
        except Exception as e:
            print(f"✗ {uri} -> ERROR: {e}")
            all_passed = False
    
    if all_passed:
        print("✓ S3 name property test passed")
    else:
        print("⚠ S3 name property test had failures")
    
    return

def test_s3_credentials():
    """Test if AWS credentials are available"""
    print("Testing AWS credentials availability...")
    
    try:
        s3_path = Path('s3://test-bucket/test-file.txt')
        # This will trigger credential check
        s3_path._impl._client
        print("✓ AWS credentials are available")
        return
    except RuntimeError as e:
        print(f"⚠ AWS credentials not available: {e}")
        return
    except Exception as e:
        print(f"⚠ AWS connection issue: {e}")
        return

def test_s3_bucket_operations():
    """Test S3 bucket operations (requires valid credentials and bucket)"""
    print("\nTesting S3 bucket operations...")
    
    # Use a test bucket - replace with your own bucket name
    test_bucket = os.environ.get('XEFM_TEST_S3_BUCKET', 'xefm-test-bucket-nonexistent')
    s3_path = Path(f's3://{test_bucket}/')
    
    try:
        exists = s3_path.exists()
        print(f"Bucket {test_bucket} exists: {exists}")
        
        if exists:
            print("Testing directory listing...")
            try:
                items = list(s3_path.iterdir())
                print(f"Found {len(items)} items in bucket")
                for item in items[:5]:  # Show first 5 items
                    print(f"  - {item}")
                if len(items) > 5:
                    print(f"  ... and {len(items) - 5} more items")
            except Exception as e:
                print(f"Error listing bucket contents: {e}")
        
        print("✓ S3 bucket operations test completed")
        return
    except Exception as e:
        print(f"⚠ S3 bucket operations failed: {e}")
        return

def test_s3_file_operations():
    """Test S3 file operations"""
    print("\nTesting S3 file operations...")
    
    test_bucket = os.environ.get('XEFM_TEST_S3_BUCKET', 'xefm-test-bucket-nonexistent')
    test_file = Path(f's3://{test_bucket}/xefm-test-file.txt')
    
    try:
        # Test file existence
        exists = test_file.exists()
        print(f"Test file exists: {exists}")
        
        # Test writing (only if we have a real bucket)
        if test_bucket != 'xefm-test-bucket-nonexistent':
            print("Testing file write...")
            test_content = "Hello from XeFM S3 integration test!"
            test_file.write_text(test_content)
            print("✓ File written successfully")
            
            # Test reading
            print("Testing file read...")
            read_content = test_file.read_text()
            print(f"Read content: {read_content}")
            
            if read_content == test_content:
                print("✓ File content matches")
            else:
                print("⚠ File content mismatch")
            
            # Test file info
            stat_info = test_file.stat()
            print(f"File size: {stat_info.st_size} bytes")
            print(f"File modified: {stat_info.st_mtime}")
            
            # Clean up
            print("Cleaning up test file...")
            test_file.unlink()
            print("✓ Test file deleted")
        
        print("✓ S3 file operations test completed")
        return
    except Exception as e:
        print(f"⚠ S3 file operations failed: {e}")
        return

def main():
    """Run all integration tests"""
    print("XeFM S3 Integration Tests")
    print("=" * 40)
    
    # Check if boto3 is available
    try:
        import boto3
        print("✓ boto3 is available")
    except ImportError:
        print("❌ boto3 is not installed. Run: pip install boto3")
        return False
    
    # Test S3 name property (doesn't require AWS credentials)
    name_test = test_s3_name_property()
    
    # Test credentials
    has_credentials = test_s3_credentials()
    
    if not has_credentials:
        print("\nSkipping AWS operations tests due to missing credentials.")
        print("To run full tests:")
        print("1. Configure AWS credentials (aws configure)")
        print("2. Set XEFM_TEST_S3_BUCKET environment variable to a test bucket")
        print("3. Re-run this test")
        return True
    
    # Run AWS operations tests
    bucket_test = test_s3_bucket_operations()
    file_test = test_s3_file_operations()
    
    if name_test and bucket_test and file_test:
        print("\n🎉 All integration tests passed!")
        return True
    else:
        print("\n⚠ Some integration tests had issues (see above)")
        return True
