"""
Test S3 Move Fix - Verify that S3 file move operations work correctly

This test verifies that the fix for S3 file moving operations works properly
by testing the rename method on S3 paths.

Run with: python -m pytest test/test_s3_move_operations.py -v
"""

import unittest
from unittest.mock import Mock, patch, MagicMock

from xefm.path import Path
from xefm.s3 import S3PathImpl


class TestS3MoveFix(unittest.TestCase):
    """Test S3 move operations"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Mock boto3 client. Give list_objects_v2 a real dict so the is_dir
        # probe (KeyCount > 0) compares ints rather than a Mock.
        self.mock_s3_client = Mock()
        self.mock_s3_client.list_objects_v2.return_value = {'KeyCount': 0}
        
        # Create S3 paths for testing
        self.source_path = Path('s3://test-bucket/source/file1.txt')
        self.dest_path = Path('s3://test-bucket/dest/file1.txt')
        
        # Mock the S3 client for both paths
        if hasattr(self.source_path._impl, '_s3_client'):
            self.source_path._impl._s3_client = self.mock_s3_client
        if hasattr(self.dest_path._impl, '_s3_client'):
            self.dest_path._impl._s3_client = self.mock_s3_client
    
    @patch('xefm.s3.boto3')
    def test_s3_rename_method_exists(self, mock_boto3):
        """Test that S3PathImpl has a rename method"""
        # Configure mock
        mock_boto3.client.return_value = self.mock_s3_client
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/file1.txt')
        
        # Verify that the rename method exists
        self.assertTrue(hasattr(s3_path._impl, 'rename'))
        self.assertTrue(callable(getattr(s3_path._impl, 'rename')))
    
    @patch('xefm.s3.boto3')
    def test_s3_rename_calls_copy_and_delete(self, mock_boto3):
        """Test that S3 rename performs copy and delete operations"""
        # Configure mock
        mock_boto3.client.return_value = self.mock_s3_client
        
        # Create S3 paths
        source = Path('s3://test-bucket/source/file1.txt')
        dest = Path('s3://test-bucket/dest/file1.txt')
        
        # Mock the S3 client methods
        source._impl._s3_client = self.mock_s3_client
        dest._impl._s3_client = self.mock_s3_client
        
        # Perform rename operation
        try:
            result = source.rename(dest)
            
            # Verify copy_object was called
            self.mock_s3_client.copy_object.assert_called_once()
            
            # Verify delete_object was called
            self.mock_s3_client.delete_object.assert_called_once()
            
            # Verify result is the destination path
            self.assertEqual(str(result), str(dest))
            
        except Exception as e:
            # If there's an error, it should be related to the mock setup, not the method existence
            self.fail(f"S3 rename method failed unexpectedly: {e}")
    
    @patch('xefm.s3.boto3')
    def test_s3_path_creation(self, mock_boto3):
        """Test that S3 paths can be created and have the correct implementation"""
        # Configure mock
        mock_boto3.client.return_value = self.mock_s3_client
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/file1.txt')
        
        # Verify it's using S3PathImpl
        self.assertIsInstance(s3_path._impl, S3PathImpl)
        
        # Verify URI parsing
        self.assertEqual(s3_path._impl._bucket, 'test-bucket')
        self.assertEqual(s3_path._impl._key, 'file1.txt')
    
    def test_path_rename_method_exists(self):
        """Test that Path class has rename method"""
        # Create a regular path (doesn't need to exist for this test)
        path = Path('/tmp/test.txt')
        
        # Verify that the rename method exists
        self.assertTrue(hasattr(path, 'rename'))
        self.assertTrue(callable(getattr(path, 'rename')))


def main():
    """Run the tests"""
    print("Testing S3 Move Fix...")
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestS3MoveFix)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    if result.wasSuccessful():
        print(f"\n✅ All {result.testsRun} tests passed!")
        return True
    else:
        print(f"\n❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False
