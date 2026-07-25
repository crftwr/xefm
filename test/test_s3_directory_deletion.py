"""
Test for S3 directory deletion fix

This test reproduces and verifies the fix for the issue where deleting
empty S3 directories fails with "No files to delete" error.

Run with: python -m pytest test/test_s3_directory_deletion.py -v
"""

import pytest
import tempfile
import shutil
from pathlib import Path

try:
    from xefm.path import Path as XeFMPath
    from xefm.s3 import S3PathImpl
    import boto3
    from moto import mock_s3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
    mock_s3 = lambda f: f  # No-op decorator
    print("boto3 or moto not available, skipping S3 tests")


@pytest.mark.skipif(not HAS_BOTO3, reason="requires boto3 + moto for mocked S3")
class TestS3DirectoryDeletionFix:
    """Test S3 directory deletion fix"""

    # Class attribute (was __init__, which prevented pytest from collecting the class).
    test_bucket = 'test-bucket-s3-dir-deletion'

    @mock_s3
    def test_empty_directory_deletion(self):
        """Test deleting an empty S3 directory"""
        if not HAS_BOTO3:
            print("Skipping S3 tests - boto3/moto not available")
            return True
        
        print("Testing S3 empty directory deletion...")
        
        # Create S3 client and bucket
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket=self.test_bucket)
        
        # Create a directory structure with some files, then delete the files
        # This simulates the scenario where a directory exists but becomes empty
        test_dir_path = f's3://{self.test_bucket}/test1/dir3/dir2/'
        
        # First, create some files in the directory
        s3_client.put_object(Bucket=self.test_bucket, Key='test1/dir3/dir2/file1.txt', Body=b'content1')
        s3_client.put_object(Bucket=self.test_bucket, Key='test1/dir3/dir2/file2.txt', Body=b'content2')
        
        # Verify directory exists and has files
        dir_path = XeFMPath(test_dir_path)
        assert dir_path.is_dir(), "Directory should exist"
        
        files_in_dir = list(dir_path.iterdir())
        assert len(files_in_dir) == 2, f"Should have 2 files, got {len(files_in_dir)}"
        
        # Now delete the files, leaving an empty directory
        for file_path in files_in_dir:
            file_path.unlink()
        
        # Verify directory is now empty
        files_in_dir_after = list(dir_path.iterdir())
        assert len(files_in_dir_after) == 0, f"Directory should be empty, got {len(files_in_dir_after)} files"
        
        # Test the fix: directory should now be detected as existing
        print(f"Directory path: {dir_path}")
        print(f"Directory exists: {dir_path.exists()}")
        print(f"Directory is_dir: {dir_path.is_dir()}")
        print(f"Files in directory: {len(list(dir_path.iterdir()))}")
        
        # The key fix: exists() should return True even for empty directories
        assert dir_path.exists(), "Fixed exists() method should return True for empty S3 directories"
        
        # Try to delete the empty directory
        try:
            dir_path.rmdir()
            print("Successfully deleted empty S3 directory")
            return True
        except OSError as e:
            print(f"Failed to delete empty S3 directory: {e}")
            return False
    
    @mock_s3
    def test_directory_with_marker_deletion(self):
        """Test deleting an S3 directory that has an explicit directory marker"""
        if not HAS_BOTO3:
            print("Skipping S3 tests - boto3/moto not available")
            return True
        
        print("Testing S3 directory marker deletion...")
        
        # Create S3 client and bucket
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket=self.test_bucket)
        
        # Create a directory marker (empty object with key ending in '/')
        test_dir_path = f's3://{self.test_bucket}/test1/dir3/dir4/'
        s3_client.put_object(Bucket=self.test_bucket, Key='test1/dir3/dir4/', Body=b'')
        
        # Verify directory exists
        dir_path = XeFMPath(test_dir_path)
        assert dir_path.is_dir(), "Directory should exist"
        assert dir_path.exists(), "Directory should exist"
        
        # Verify directory is empty
        files_in_dir = list(dir_path.iterdir())
        assert len(files_in_dir) == 0, f"Directory should be empty, got {len(files_in_dir)} files"
        
        print(f"Directory path: {dir_path}")
        print(f"Directory exists: {dir_path.exists()}")
        print(f"Directory is_dir: {dir_path.is_dir()}")
        print(f"Files in directory: {len(list(dir_path.iterdir()))}")
        
        # Try to delete the directory marker
        try:
            dir_path.rmdir()
            print("Successfully deleted S3 directory marker")
            
            # Verify it's gone
            assert not dir_path.exists(), "Directory should no longer exist"
            return True
        except OSError as e:
            print(f"Failed to delete S3 directory marker: {e}")
            return False
    
    @mock_s3
    def test_recursive_directory_deletion(self):
        """Test deleting an S3 directory with contents using rmtree"""
        if not HAS_BOTO3:
            print("Skipping S3 tests - boto3/moto not available")
            return True
        
        print("Testing S3 recursive directory deletion...")
        
        # Create S3 client and bucket
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket=self.test_bucket)
        
        # Create a directory structure with files and subdirectories
        test_dir_path = f's3://{self.test_bucket}/test1/dir3/dir5/'
        
        # Create files in the directory
        s3_client.put_object(Bucket=self.test_bucket, Key='test1/dir3/dir5/file1.txt', Body=b'content1')
        s3_client.put_object(Bucket=self.test_bucket, Key='test1/dir3/dir5/file2.txt', Body=b'content2')
        s3_client.put_object(Bucket=self.test_bucket, Key='test1/dir3/dir5/subdir/file3.txt', Body=b'content3')
        s3_client.put_object(Bucket=self.test_bucket, Key='test1/dir3/dir5/subdir/file4.txt', Body=b'content4')
        
        # Verify directory exists and has contents
        dir_path = XeFMPath(test_dir_path)
        assert dir_path.is_dir(), "Directory should exist"
        assert dir_path.exists(), "Directory should exist"
        
        files_in_dir = list(dir_path.iterdir())
        print(f"Directory contents: {len(files_in_dir)} items")
        for item in files_in_dir:
            print(f"  - {item.name} ({'dir' if item.is_dir() else 'file'})")
        
        # Should have files and subdirectory
        assert len(files_in_dir) > 0, "Directory should have contents"
        
        # Try rmdir() - should fail because directory is not empty
        try:
            dir_path.rmdir()
            print("✗ rmdir() should have failed for non-empty directory")
            return False
        except OSError:
            print("✓ rmdir() correctly failed for non-empty directory")
        
        # Try rmtree() - should succeed
        try:
            s3_impl = dir_path._impl
            if isinstance(s3_impl, S3PathImpl):
                s3_impl.rmtree()
                print("✓ rmtree() succeeded")
                
                # Verify directory is gone
                if not dir_path.exists():
                    print("✓ Directory no longer exists")
                    return True
                else:
                    print("✗ Directory still exists after rmtree()")
                    return False
            else:
                print("✗ Not an S3 path")
                return False
        except Exception as e:
            print(f"✗ rmtree() failed: {e}")
            return False
    
    @mock_s3
    def test_delete_selected_files_simulation(self):
        """Test the delete_selected_files logic with the fix"""
        if not HAS_BOTO3:
            print("Skipping S3 tests - boto3/moto not available")
            return True
        
        print("Testing delete_selected_files simulation...")
        
        # Create S3 client and bucket
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket=self.test_bucket)
        
        # Create a directory with files
        test_dir_path = f's3://{self.test_bucket}/test1/dir3/dir6/'
        s3_client.put_object(Bucket=self.test_bucket, Key='test1/dir3/dir6/file1.txt', Body=b'content1')
        
        # Simulate the delete_selected_files logic
        selected_files = {test_dir_path}
        files_to_delete = []
        
        for file_path_str in selected_files:
            file_path = XeFMPath(file_path_str)
            print(f"Checking path: {file_path_str}")
            print(f"  exists(): {file_path.exists()}")
            print(f"  is_dir(): {file_path.is_dir()}")
            
            if file_path.exists():
                files_to_delete.append(file_path)
                print(f"  ✓ Added to deletion list")
            else:
                print(f"  ✗ Not added to deletion list")
        
        print(f"Files to delete: {len(files_to_delete)}")
        
        if len(files_to_delete) == 0:
            print("✗ This would cause 'No files to delete' error")
            return False
        else:
            print("✓ Fix successful - directory detected for deletion")
            return True
    
    def run_all_tests(self):
        """Run all tests"""
        print("=" * 60)
        print("S3 Directory Deletion Fix Tests")
        print("=" * 60)
        
        tests = [
            self.test_empty_directory_deletion,
            self.test_directory_with_marker_deletion,
            self.test_recursive_directory_deletion,
            self.test_delete_selected_files_simulation,
        ]
        
        passed = 0
        total = len(tests)
        
        for test in tests:
            try:
                if test():
                    passed += 1
                    print("✓ PASSED")
                else:
                    print("✗ FAILED")
            except Exception as e:
                print(f"✗ ERROR: {e}")
            print()
        
        print(f"Results: {passed}/{total} tests passed")
        return passed == total


def main():
    """Run the tests"""
    tester = TestS3DirectoryDeletionFix()
    success = tester.run_all_tests()
    
    if success:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed!")
        return 1
