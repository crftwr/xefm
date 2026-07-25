"""
Test S3 directory rename restriction functionality.

This test verifies that XeFM properly prevents directory renaming on S3
to avoid expensive copy/delete operations.

Run with: python -m pytest test/test_s3_directory_rename_restriction.py -v
"""

import unittest
from unittest.mock import Mock, patch, MagicMock

from xefm.s3 import S3PathImpl


class TestS3DirectoryRenameRestriction(unittest.TestCase):
    """Test S3 directory rename restriction"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Mock S3 client
        self.mock_client = Mock()
        
        # Create S3 path implementations
        self.s3_file = S3PathImpl('s3://test-bucket/file.txt')
        self.s3_file._s3_client = self.mock_client  # Set the internal client directly
        
        self.s3_directory = S3PathImpl('s3://test-bucket/directory/')
        self.s3_directory._s3_client = self.mock_client  # Set the internal client directly
        
        # Mock the is_dir method for our test cases
        self.s3_file.is_dir = Mock(return_value=False)
        self.s3_directory.is_dir = Mock(return_value=True)
    
    def test_directory_rename_blocked(self):
        """Test that directory renaming is blocked on S3"""
        # This should raise an OSError before any S3 operations
        with self.assertRaises(OSError) as context:
            self.s3_directory.rename('s3://test-bucket/renamed_directory/')
        
        # Verify the error message is informative
        error_message = str(context.exception)
        self.assertIn("Directory renaming is not supported on S3", error_message)
        self.assertIn("performance and cost considerations", error_message)
        
        # Verify no S3 operations were attempted
        self.mock_client.copy_object.assert_not_called()
    
    def test_virtual_directory_rename_blocked(self):
        """Test that virtual directory renaming is blocked"""
        # Create a virtual directory (one that doesn't end with / but has children)
        virtual_dir = S3PathImpl('s3://test-bucket/virtual_dir')
        virtual_dir._s3_client = self.mock_client
        virtual_dir.is_dir = Mock(return_value=True)
        
        # This should raise an OSError
        with self.assertRaises(OSError) as context:
            virtual_dir.rename('s3://test-bucket/renamed_virtual_dir')
        
        # Verify the error message
        error_message = str(context.exception)
        self.assertIn("Directory renaming is not supported on S3", error_message)
    
    def test_replace_method_also_blocked_for_directories(self):
        """Test that replace method (which calls rename) is also blocked for directories"""
        # The replace method calls rename, so it should also be blocked
        with self.assertRaises(OSError) as context:
            self.s3_directory.replace('s3://test-bucket/replaced_directory/')
        
        # Verify the error message
        error_message = str(context.exception)
        self.assertIn("Directory renaming is not supported on S3", error_message)
    
    def test_file_rename_check_bypassed(self):
        """Test that files bypass the directory check"""
        # For files, the is_dir() check should return False and allow the rename to proceed
        # We'll test that the directory check is bypassed (no early return)
        
        try:
            # This should not raise the directory error (but may raise other errors)
            self.s3_file.rename('s3://test-bucket/renamed_file.txt')
            # If we get here, the directory check was bypassed (good)
        except OSError as e:
            # Make sure it's not the directory restriction error
            error_msg = str(e)
            self.assertNotIn("Directory renaming is not supported on S3", error_msg)
            # Other errors are fine - we just want to make sure it's not the directory error


def run_test():
    """Run the test"""
    unittest.main(verbosity=2)
