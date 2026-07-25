"""
Test S3 Caching Optimization

This test verifies that the S3 caching optimization reduces API calls
during directory listing and file stat operations.

Run with: python -m pytest test/test_s3_caching_optimization.py -v
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
    print("Skipping S3 caching optimization tests")
    sys.exit(0)


class TestS3CachingOptimization(unittest.TestCase):
    """Test S3 caching optimization"""
    
    def setUp(self):
        """Set up test environment"""
        # Clear cache before each test
        cache = get_s3_cache()
        cache.clear()
        
        # Mock S3 client
        self.mock_client = Mock()
        self.mock_paginator = Mock()
        self.mock_client.get_paginator.return_value = self.mock_paginator
        
        # Sample S3 objects for testing
        self.sample_objects = [
            {
                'Key': 'folder/file1.txt',
                'Size': 1024,
                'LastModified': datetime(2024, 1, 1, 12, 0, 0),
                'ETag': '"abc123"',
                'StorageClass': 'STANDARD'
            },
            {
                'Key': 'folder/file2.txt', 
                'Size': 2048,
                'LastModified': datetime(2024, 1, 2, 12, 0, 0),
                'ETag': '"def456"',
                'StorageClass': 'STANDARD'
            },
            {
                'Key': 'folder/subdir/',
                'Size': 0,
                'LastModified': datetime(2024, 1, 3, 12, 0, 0),
                'ETag': '"ghi789"',
                'StorageClass': 'STANDARD'
            }
        ]
        
        # Mock paginator response
        self.mock_page = {
            'Contents': self.sample_objects,
            'CommonPrefixes': [{'Prefix': 'folder/subdir/'}],
            'KeyCount': len(self.sample_objects),
            'IsTruncated': False
        }
        
        self.mock_paginator.paginate.return_value = [self.mock_page]
    
    @patch('xefm.s3.boto3.client')
    def test_iterdir_caches_stat_info(self, mock_boto3_client):
        """Test that iterdir caches stat information from directory listing"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/folder/')
        
        # List directory contents
        files = list(s3_path.iterdir())
        
        # Verify we got the expected files
        self.assertEqual(len(files), 3)  # 2 files + 1 directory
        
        # Verify paginator was called once
        self.mock_client.get_paginator.assert_called_once_with('list_objects_v2')
        self.mock_paginator.paginate.assert_called_once()
        
        # Now test that stat() calls don't make additional API calls
        cache = get_s3_cache()
        
        # Check cache contains head_object entries for files
        file_paths = [f for f in files if f.is_file()]
        
        for file_path in file_paths:
            # This should use cached data, not make API calls
            stat_result = file_path.stat()
            
            # Verify stat result has correct data
            self.assertGreater(stat_result.st_size, 0)
            self.assertGreater(stat_result.st_mtime, 0)
        
        # Verify no additional API calls were made for head_object
        # (The mock client should only have been called for list_objects_v2)
        self.mock_client.head_object.assert_not_called()
    
    @patch('xefm.s3.boto3.client')
    def test_virtual_directory_stats_uses_cached_data(self, mock_boto3_client):
        """Test that virtual directory stats use cached directory listing data"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path for directory
        s3_path = Path('s3://test-bucket/folder/')
        
        # First, list directory to populate cache
        files = list(s3_path.iterdir())
        
        # Reset mock to track subsequent calls
        self.mock_client.reset_mock()
        self.mock_paginator.reset_mock()
        
        # Now get directory stats - should use cached data
        stat_result = s3_path.stat()
        
        # Verify we got valid stats
        self.assertEqual(stat_result.st_size, 0)  # Directories have 0 size
        self.assertGreater(stat_result.st_mtime, 0)
        
        # Verify no additional API calls were made
        # (Should use cached directory listing data)
        self.mock_client.list_objects_v2.assert_not_called()
        self.mock_client.get_paginator.assert_not_called()
    
    @patch('xefm.s3.boto3.client')
    def test_cache_hit_ratio_improvement(self, mock_boto3_client):
        """Test that cache hit ratio improves with optimization"""
        mock_boto3_client.return_value = self.mock_client
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/folder/')
        
        # Get cache instance
        cache = get_s3_cache()
        
        # First iteration - should populate cache
        files = list(s3_path.iterdir())
        
        # Get stats for all files (should use cached data)
        for file_path in files:
            if file_path.is_file():
                file_path.stat()
        
        # Second iteration - should be fully cached
        files2 = list(s3_path.iterdir())
        
        # Get stats again (should be fully cached)
        for file_path in files2:
            if file_path.is_file():
                file_path.stat()
        
        # Verify cache has entries
        cache_stats = cache.get_stats()
        self.assertGreater(cache_stats['total_entries'], 0)
        
        # Verify minimal API calls were made
        # Should only be called once for the initial directory listing
        self.assertEqual(self.mock_paginator.paginate.call_count, 1)
        self.mock_client.head_object.assert_not_called()
    
    def test_cache_key_generation(self):
        """Test that cache keys are generated correctly"""
        cache = get_s3_cache()
        
        # Test cache key generation for different operations
        key1 = cache._generate_cache_key('head_object', 'bucket', 'key1')
        key2 = cache._generate_cache_key('head_object', 'bucket', 'key2')
        key3 = cache._generate_cache_key('list_objects_v2', 'bucket', 'key1')
        
        # Keys should be different for different parameters
        self.assertNotEqual(key1, key2)
        self.assertNotEqual(key1, key3)
        
        # Same parameters should generate same key
        key1_duplicate = cache._generate_cache_key('head_object', 'bucket', 'key1')
        self.assertEqual(key1, key1_duplicate)
    
    def test_cache_invalidation(self):
        """Test that cache invalidation works correctly"""
        cache = get_s3_cache()
        
        # Add some test data to cache
        cache.put('head_object', 'bucket', 'key1', {'test': 'data1'})
        cache.put('head_object', 'bucket', 'key2', {'test': 'data2'})
        cache.put('list_objects_v2', 'bucket', '', {'test': 'list_data'})
        
        # Verify data is in cache
        self.assertIsNotNone(cache.get('head_object', 'bucket', 'key1'))
        self.assertIsNotNone(cache.get('head_object', 'bucket', 'key2'))
        self.assertIsNotNone(cache.get('list_objects_v2', 'bucket', ''))
        
        # Invalidate specific key
        cache.invalidate_key('bucket', 'key1')
        
        # key1's own entry is gone, and so is the parent directory listing that
        # would have included it (invalidate_key also drops list_objects_v2
        # entries whose prefix contains the key — here the root listing). A
        # sibling key's head_object entry is untouched.
        self.assertIsNone(cache.get('head_object', 'bucket', 'key1'))
        self.assertIsNotNone(cache.get('head_object', 'bucket', 'key2'))
        self.assertIsNone(cache.get('list_objects_v2', 'bucket', ''))
        
        # Invalidate entire bucket
        cache.invalidate_bucket('bucket')
        
        # Verify all entries for bucket were invalidated
        self.assertIsNone(cache.get('head_object', 'bucket', 'key2'))
        self.assertIsNone(cache.get('list_objects_v2', 'bucket', ''))


def main():
    """Run the tests"""
    unittest.main(verbosity=2)
