"""
Test S3 Cache Fix

This test verifies that the S3 caching fix properly caches stat information
from directory listings and avoids 404 errors.

Run with: python -m pytest test/test_s3_cache_operations.py -v
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
    print("Skipping S3 cache fix tests")
    sys.exit(0)


class TestS3CacheFix(unittest.TestCase):
    """Test S3 cache fix"""
    
    def setUp(self):
        """Set up test environment"""
        # Clear cache before each test
        cache = get_s3_cache()
        cache.clear()
        
        # Mock S3 client
        self.mock_client = Mock()
        
        # Sample S3 objects for testing
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
        
        # Mock list_objects_v2 response
        self.mock_list_response = {
            'Contents': self.sample_objects,
            'CommonPrefixes': [],
            'KeyCount': len(self.sample_objects),
            'IsTruncated': False
        }
        
        # Configure mock client
        self.mock_client.list_objects_v2.return_value = self.mock_list_response
        
        # Mock paginator
        self.mock_paginator = Mock()
        self.mock_paginator.paginate.return_value = [self.mock_list_response]
        self.mock_client.get_paginator.return_value = self.mock_paginator
    
    @patch('xefm.s3.boto3.client')
    def test_cache_key_consistency(self, mock_boto3_client):
        """Test that cache keys are consistent between iterdir and stat calls"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path for directory
        s3_path = Path('s3://test-bucket/test-folder/')
        
        # List directory contents to populate cache
        files = list(s3_path.iterdir())
        
        # Verify we got the expected files
        self.assertEqual(len(files), 2)
        
        # Get cache instance
        cache = get_s3_cache()
        
        # Check that head_object entries were cached for each file
        for file_path in files:
            if file_path.is_file():
                # Check if cache contains entry for this file
                cached_head = cache.get('head_object', file_path._impl._bucket, file_path._impl._key)
                self.assertIsNotNone(cached_head, f"No cached head_object for {file_path._impl._key}")
                
                # Verify cached data has expected structure
                self.assertIn('ContentLength', cached_head)
                self.assertIn('LastModified', cached_head)
                self.assertGreater(cached_head['ContentLength'], 0)
    
    @patch('xefm.s3.boto3.client')
    def test_stat_uses_cached_data(self, mock_boto3_client):
        """Test that stat() calls use cached data and don't make API calls"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path for directory
        s3_path = Path('s3://test-bucket/test-folder/')
        
        # List directory contents to populate cache
        files = list(s3_path.iterdir())
        
        # Reset mock to track subsequent calls
        self.mock_client.reset_mock()
        
        # Call stat() on files - should use cached data
        for file_path in files:
            if file_path.is_file():
                stat_result = file_path.stat()
                
                # Verify we got valid stat data
                self.assertGreater(stat_result.st_size, 0)
                self.assertGreater(stat_result.st_mtime, 0)
        
        # Verify no head_object calls were made (should use cached data)
        self.mock_client.head_object.assert_not_called()
    
    @patch('xefm.s3.boto3.client')
    def test_no_404_errors_with_cache(self, mock_boto3_client):
        """Test that cached data prevents 404 errors from head_object calls"""
        mock_boto3_client.return_value = self.mock_client
        
        # Configure head_object to raise 404 (simulating missing objects)
        from botocore.exceptions import ClientError
        error_response = {'Error': {'Code': 'NoSuchKey', 'Message': 'Not Found'}}
        self.mock_client.head_object.side_effect = ClientError(error_response, 'HeadObject')
        
        # Create S3 path for directory
        s3_path = Path('s3://test-bucket/test-folder/')
        
        # List directory contents to populate cache
        files = list(s3_path.iterdir())
        
        # Call stat() on files - should use cached data and not get 404 errors
        for file_path in files:
            if file_path.is_file():
                try:
                    stat_result = file_path.stat()
                    # Should succeed using cached data
                    self.assertGreater(stat_result.st_size, 0)
                except FileNotFoundError:
                    self.fail(f"stat() failed with 404 for {file_path.name} - cache not working")
    
    def test_cache_key_generation(self):
        """Test that cache keys are generated correctly for different files"""
        cache = get_s3_cache()
        
        # Test cache key generation for different files in same bucket
        key1 = cache._generate_cache_key('head_object', 'bucket', 'folder/file1.txt')
        key2 = cache._generate_cache_key('head_object', 'bucket', 'folder/file2.txt')
        key3 = cache._generate_cache_key('head_object', 'bucket', 'folder/file1.txt')  # Same as key1
        
        # Different files should have different keys
        self.assertNotEqual(key1, key2)
        
        # Same file should have same key
        self.assertEqual(key1, key3)
    
    @patch('xefm.s3.boto3.client')
    def test_cache_invalidation_on_write(self, mock_boto3_client):
        """Test that cache is properly invalidated on write operations"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path for a file
        s3_path = Path('s3://test-bucket/test-folder/file1.txt')
        
        # Simulate cached head_object data
        cache = get_s3_cache()
        cache.put('head_object', 'test-bucket', 'test-folder/file1.txt', {'ContentLength': 1024})
        
        # Verify data is cached
        cached_data = cache.get('head_object', 'test-bucket', 'test-folder/file1.txt')
        self.assertIsNotNone(cached_data)
        
        # Write to the file (should invalidate cache)
        s3_path.write_text("new content")
        
        # Verify cache was invalidated
        cached_data_after = cache.get('head_object', 'test-bucket', 'test-folder/file1.txt')
        self.assertIsNone(cached_data_after)


def main():
    """Run the tests"""
    unittest.main(verbosity=2)
