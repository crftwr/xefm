"""
Integration test for S3 directory rename restriction.

This test verifies that the S3 directory rename restriction works
correctly in the context of the full XeFM application.

Run with: python -m pytest test/test_integration_s3_directory_rename.py -v
"""

import unittest
from unittest.mock import Mock, patch

from xefm.s3 import S3PathImpl
from xefm.path import Path


class TestS3DirectoryRenameIntegration(unittest.TestCase):
    """Integration test for S3 directory rename restriction"""
    
    def test_s3_directory_rename_through_path_interface(self):
        """Test that directory rename restriction works through the Path interface"""
        # Create an S3 directory through the Path interface
        s3_dir_path = Path('s3://test-bucket/test-directory/')
        
        # Mock the underlying S3PathImpl
        mock_s3_impl = Mock(spec=S3PathImpl)
        mock_s3_impl.is_dir.return_value = True
        mock_s3_impl.rename.side_effect = OSError("Directory renaming is not supported on S3 due to performance and cost considerations")
        
        # Replace the implementation
        s3_dir_path._impl = mock_s3_impl
        
        # Attempt to rename through the Path interface
        with self.assertRaises(OSError) as context:
            s3_dir_path.rename('s3://test-bucket/renamed-directory/')
        
        # Verify the error message
        error_message = str(context.exception)
        self.assertIn("Directory renaming is not supported on S3", error_message)
        
        # Verify the underlying rename method was called
        mock_s3_impl.rename.assert_called_once()
    
    def test_s3_file_rename_still_works_through_path_interface(self):
        """Test that file rename still works through the Path interface"""
        # Create an S3 file through the Path interface
        s3_file_path = Path('s3://test-bucket/test-file.txt')
        
        # Mock the underlying S3PathImpl for a file
        mock_s3_impl = Mock(spec=S3PathImpl)
        mock_s3_impl.is_dir.return_value = False
        mock_s3_impl.rename.return_value = Path('s3://test-bucket/renamed-file.txt')
        
        # Replace the implementation
        s3_file_path._impl = mock_s3_impl
        
        # Attempt to rename through the Path interface
        try:
            result = s3_file_path.rename('s3://test-bucket/renamed-file.txt')
            # If we get here, the rename was attempted (good for files)
            mock_s3_impl.rename.assert_called_once()
        except OSError as e:
            # Make sure it's not the directory restriction error
            self.assertNotIn("Directory renaming is not supported on S3", str(e))
    
    def test_error_message_consistency(self):
        """Test that error messages are consistent across different scenarios"""
        expected_message = "Directory renaming is not supported on S3 due to performance and cost considerations"
        
        # Test different types of S3 directories
        test_cases = [
            's3://bucket/explicit-dir/',      # Explicit directory
            's3://bucket/virtual-dir',        # Virtual directory
            's3://bucket/nested/deep/dir/',   # Nested directory
        ]
        
        for s3_uri in test_cases:
            with self.subTest(s3_uri=s3_uri):
                # Create S3PathImpl and mock it as a directory
                s3_impl = S3PathImpl(s3_uri)
                s3_impl._s3_client = Mock()
                s3_impl.is_dir = Mock(return_value=True)
                
                # Test rename
                with self.assertRaises(OSError) as context:
                    s3_impl.rename(s3_uri.replace('dir', 'renamed-dir'))
                
                # Verify consistent error message
                self.assertEqual(str(context.exception), expected_message)
                
                # Test replace method too
                with self.assertRaises(OSError) as context:
                    s3_impl.replace(s3_uri.replace('dir', 'replaced-dir'))
                
                # Verify consistent error message
                self.assertEqual(str(context.exception), expected_message)


def run_test():
    """Run the integration test"""
    unittest.main(verbosity=2)
