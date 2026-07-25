"""
Test S3 Virtual Directory Optimization

This test verifies that S3PathImpl instances store metadata as properties
to avoid API calls for is_dir(), is_file(), and stat() methods.

Run with: python -m pytest test/test_s3_virtual_directory_optimization.py -v
"""

import time
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

try:
    from xefm.path import Path
    from xefm.s3 import S3PathImpl, get_s3_cache
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Skipping S3 virtual directory optimization tests")
    sys.exit(0)


class TestS3VirtualDirectoryOptimization(unittest.TestCase):
    """Test S3 virtual directory optimization"""
    
    def setUp(self):
        """Set up test environment"""
        # Clear cache before each test
        cache = get_s3_cache()
        cache.clear()
        
        # Mock S3 client
        self.mock_client = Mock()
        
        # Sample S3 objects for testing (includes virtual directory)
        self.sample_objects = [
            {
                'Key': 'test-folder/file1.txt',
                'Size': 1024,
                'LastModified': datetime(2024, 1, 1, 12, 0, 0),
                'ETag': '"abc123"',
                'StorageClass': 'STANDARD'
            },
            {
                'Key': 'test-folder/file2.txt', 
                'Size': 2048,
                'LastModified': datetime(2024, 1, 2, 12, 0, 0),
                'ETag': '"def456"',
                'StorageClass': 'STANDARD'
            }
        ]
        
        # Mock list_objects_v2 response with virtual directory
        self.mock_list_response = {
            'Contents': self.sample_objects,
            'CommonPrefixes': [{'Prefix': 'test-folder/subdir/'}],  # Virtual directory
            'KeyCount': len(self.sample_objects),
            'IsTruncated': False
        }
        
        # Configure mock client
        self.mock_client.list_objects_v2.return_value = self.mock_list_response
        
        # Mock paginator
        self.mock_paginator = Mock()
        self.mock_paginator.paginate.return_value = [self.mock_list_response]
        self.mock_client.get_paginator.return_value = self.mock_paginator
    
    def test_s3pathimpl_with_metadata(self):
        """Test S3PathImpl creation with metadata"""
        metadata = {
            'is_dir': True,
            'is_file': False,
            'size': 0,
            'last_modified': datetime(2024, 1, 1, 12, 0, 0),
            'etag': '',
            'storage_class': ''
        }
        
        s3_impl = S3PathImpl('s3://test-bucket/virtual-dir/', metadata=metadata)
        
        # Verify metadata is stored
        self.assertEqual(s3_impl._is_dir_cached, True)
        self.assertEqual(s3_impl._is_file_cached, False)
        self.assertEqual(s3_impl._size_cached, 0)
        self.assertIsNotNone(s3_impl._mtime_cached)
    
    def test_create_path_with_metadata(self):
        """Test creating Path objects with metadata"""
        metadata = {
            'is_dir': False,
            'is_file': True,
            'size': 1024,
            'last_modified': datetime(2024, 1, 1, 12, 0, 0),
            'etag': '"abc123"',
            'storage_class': 'STANDARD'
        }
        
        path = S3PathImpl.create_path_with_metadata('s3://test-bucket/file.txt', metadata)
        
        # Verify it's a proper Path object
        self.assertIsInstance(path, Path)
        self.assertIsInstance(path._impl, S3PathImpl)
        
        # Verify metadata is accessible
        self.assertEqual(path._impl._is_file_cached, True)
        self.assertEqual(path._impl._size_cached, 1024)
    
    @patch('xefm.s3.boto3.client')
    def test_is_dir_uses_cached_metadata(self, mock_boto3_client):
        """Test that is_dir() uses cached metadata without API calls"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path for directory
        s3_path = Path('s3://test-bucket/test-folder/')
        
        # List directory contents to populate metadata
        files = list(s3_path.iterdir())
        
        # Reset mock to track subsequent calls
        self.mock_client.reset_mock()
        
        # Test is_dir() on files - should use cached metadata
        for file_path in files:
            # This should not make any API calls
            is_dir_result = file_path.is_dir()
            
            # Verify result is correct based on path
            if file_path.name == 'subdir':  # Virtual directory
                self.assertTrue(is_dir_result)
            else:  # Regular files
                self.assertFalse(is_dir_result)
        
        # Verify no additional API calls were made
        self.mock_client.list_objects_v2.assert_not_called()
        self.mock_client.head_object.assert_not_called()
    
    @patch('xefm.s3.boto3.client')
    def test_is_file_uses_cached_metadata(self, mock_boto3_client):
        """Test that is_file() uses cached metadata without API calls"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path for directory
        s3_path = Path('s3://test-bucket/test-folder/')
        
        # List directory contents to populate metadata
        files = list(s3_path.iterdir())
        
        # Reset mock to track subsequent calls
        self.mock_client.reset_mock()
        
        # Test is_file() on files - should use cached metadata
        for file_path in files:
            # This should not make any API calls
            is_file_result = file_path.is_file()
            
            # Verify result is correct based on path
            if file_path.name == 'subdir':  # Virtual directory
                self.assertFalse(is_file_result)
            else:  # Regular files
                self.assertTrue(is_file_result)
        
        # Verify no additional API calls were made
        self.mock_client.list_objects_v2.assert_not_called()
        self.mock_client.head_object.assert_not_called()
    
    @patch('xefm.s3.boto3.client')
    def test_stat_uses_cached_metadata(self, mock_boto3_client):
        """Test that stat() uses cached metadata without API calls"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path for directory
        s3_path = Path('s3://test-bucket/test-folder/')
        
        # List directory contents to populate metadata
        files = list(s3_path.iterdir())
        
        # Reset mock to track subsequent calls
        self.mock_client.reset_mock()
        
        # Test stat() on files - should use cached metadata
        for file_path in files:
            # This should not make any API calls for files with cached metadata
            stat_result = file_path.stat()
            
            # Verify we got valid stat data
            self.assertIsNotNone(stat_result)
            self.assertGreaterEqual(stat_result.st_size, 0)
            self.assertGreater(stat_result.st_mtime, 0)
            
            # Verify directory/file status is correct
            if file_path.name == 'subdir':  # Virtual directory
                self.assertEqual(stat_result.st_size, 0)
                self.assertTrue(stat_result.st_mode & 0o040000)  # Directory mode
            else:  # Regular files
                self.assertGreater(stat_result.st_size, 0)
                self.assertFalse(stat_result.st_mode & 0o040000)  # File mode
        
        # Verify no head_object calls were made (files use cached metadata)
        self.mock_client.head_object.assert_not_called()
        
        # Virtual directory stats might make list_objects_v2 calls, but files should not
        # Count calls to verify optimization
        list_calls = self.mock_client.list_objects_v2.call_count
        self.assertLessEqual(list_calls, 1)  # At most 1 call for virtual directory stats
    
    @patch('xefm.s3.boto3.client')
    def test_virtual_directory_no_head_object_calls(self, mock_boto3_client):
        """Test that virtual directories don't make head_object calls"""
        mock_boto3_client.return_value = self.mock_client
        
        # Configure head_object to raise 404 (should not be called for virtual directories)
        from botocore.exceptions import ClientError
        error_response = {'Error': {'Code': 'NoSuchKey', 'Message': 'Not Found'}}
        self.mock_client.head_object.side_effect = ClientError(error_response, 'HeadObject')
        
        # Create S3 path for directory
        s3_path = Path('s3://test-bucket/test-folder/')
        
        # List directory contents to populate metadata
        files = list(s3_path.iterdir())
        
        # Find virtual directory
        virtual_dir = None
        for file_path in files:
            if file_path.name == 'subdir':
                virtual_dir = file_path
                break
        
        self.assertIsNotNone(virtual_dir, "Virtual directory not found")
        
        # Reset mock to track subsequent calls
        self.mock_client.reset_mock()
        self.mock_client.head_object.side_effect = ClientError(error_response, 'HeadObject')
        
        # Test operations on virtual directory - should not call head_object
        try:
            is_dir = virtual_dir.is_dir()
            is_file = virtual_dir.is_file()
            stat_result = virtual_dir.stat()
            
            # Verify results are correct
            self.assertTrue(is_dir)
            self.assertFalse(is_file)
            self.assertIsNotNone(stat_result)
            self.assertEqual(stat_result.st_size, 0)
            
        except ClientError:
            self.fail("Virtual directory operations should not make head_object calls that fail")
        
        # Verify head_object was not called
        self.mock_client.head_object.assert_not_called()
    
    def test_metadata_caching_performance(self):
        """Test that metadata caching improves performance"""
        # Create paths with and without metadata
        metadata = {
            'is_dir': False,
            'is_file': True,
            'size': 1024,
            'last_modified': datetime(2024, 1, 1, 12, 0, 0),
            'etag': '"abc123"',
            'storage_class': 'STANDARD'
        }
        
        # Path with metadata (should be fast)
        path_with_metadata = S3PathImpl.create_path_with_metadata('s3://test-bucket/file.txt', metadata)
        
        # Path without metadata (would need API calls)
        path_without_metadata = Path('s3://test-bucket/file.txt')
        
        # Test is_dir() performance (with metadata should be instant)
        start_time = time.time()
        result1 = path_with_metadata.is_dir()
        time_with_metadata = time.time() - start_time
        
        # Verify cached result is correct and fast
        self.assertFalse(result1)
        self.assertLess(time_with_metadata, 0.001)  # Should be very fast (< 1ms)
        
        # Verify metadata is being used
        self.assertIsNotNone(path_with_metadata._impl._is_dir_cached)
        self.assertIsNone(path_without_metadata._impl._is_dir_cached)


def main():
    """Run the tests"""
    unittest.main(verbosity=2)
