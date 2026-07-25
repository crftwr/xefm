"""
Test S3 caching functionality

Run with: python -m pytest test/test_s3_caching.py -v
"""

import unittest
import time
from unittest.mock import Mock, patch, MagicMock

try:
    from xefm.s3 import S3Cache, S3PathImpl, get_s3_cache, configure_s3_cache, clear_s3_cache, get_s3_cache_stats
    from xefm.path import Path
except ImportError as e:
    print(f"Import error: {e}")
    print("Skipping S3 caching tests - dependencies not available")
    sys.exit(0)


class TestS3Cache(unittest.TestCase):
    """Test the S3Cache class functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.cache = S3Cache(default_ttl=2, max_entries=5)  # Short TTL for testing
    
    def test_cache_basic_operations(self):
        """Test basic cache put/get operations"""
        # Test cache miss
        result = self.cache.get('head_object', 'test-bucket', 'test-key')
        self.assertIsNone(result)
        
        # Test cache put and hit
        test_data = {'ContentLength': 1024, 'LastModified': 'test-time'}
        self.cache.put('head_object', 'test-bucket', 'test-key', test_data)
        
        cached_result = self.cache.get('head_object', 'test-bucket', 'test-key')
        self.assertEqual(cached_result, test_data)
    
    def test_cache_expiration(self):
        """Test cache entry expiration"""
        test_data = {'test': 'data'}
        self.cache.put('head_object', 'test-bucket', 'test-key', test_data, ttl=1)
        
        # Should be available immediately
        result = self.cache.get('head_object', 'test-bucket', 'test-key')
        self.assertEqual(result, test_data)
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Should be expired now
        result = self.cache.get('head_object', 'test-bucket', 'test-key')
        self.assertIsNone(result)
    
    def test_cache_invalidation(self):
        """Test cache invalidation methods"""
        # Add some test data
        self.cache.put('head_object', 'bucket1', 'key1', {'data': '1'})
        self.cache.put('head_object', 'bucket1', 'key2', {'data': '2'})
        self.cache.put('head_object', 'bucket2', 'key1', {'data': '3'})
        self.cache.put('list_objects_v2', 'bucket1', '', {'data': 'list'})
        
        # Test key-specific invalidation
        self.cache.invalidate_key('bucket1', 'key1')
        self.assertIsNone(self.cache.get('head_object', 'bucket1', 'key1'))
        self.assertIsNotNone(self.cache.get('head_object', 'bucket1', 'key2'))
        self.assertIsNotNone(self.cache.get('head_object', 'bucket2', 'key1'))
        
        # Test bucket-wide invalidation
        self.cache.invalidate_bucket('bucket1')
        self.assertIsNone(self.cache.get('head_object', 'bucket1', 'key2'))
        self.assertIsNone(self.cache.get('list_objects_v2', 'bucket1', ''))
        self.assertIsNotNone(self.cache.get('head_object', 'bucket2', 'key1'))
    
    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full"""
        # Fill cache to capacity
        for i in range(5):
            self.cache.put('head_object', 'bucket', f'key{i}', {'data': i})
        
        # Access key0 to make it recently used
        self.cache.get('head_object', 'bucket', 'key0')
        
        # Add one more entry to trigger eviction
        self.cache.put('head_object', 'bucket', 'key5', {'data': 5})
        
        # key0 should still be there (recently accessed)
        self.assertIsNotNone(self.cache.get('head_object', 'bucket', 'key0'))
        
        # One of the other keys should have been evicted
        available_keys = []
        for i in range(1, 6):
            if self.cache.get('head_object', 'bucket', f'key{i}') is not None:
                available_keys.append(i)
        
        # Should have 4 keys available (key0 + 4 others)
        self.assertEqual(len(available_keys), 4)
    
    def test_cache_stats(self):
        """Test cache statistics"""
        stats = self.cache.get_stats()
        self.assertIn('total_entries', stats)
        self.assertIn('expired_entries', stats)
        self.assertIn('max_entries', stats)
        self.assertIn('default_ttl', stats)
        
        # Add some entries
        self.cache.put('head_object', 'bucket', 'key1', {'data': '1'})
        self.cache.put('head_object', 'bucket', 'key2', {'data': '2'}, ttl=1)
        
        stats = self.cache.get_stats()
        self.assertEqual(stats['total_entries'], 2)
        
        # Wait for one to expire
        time.sleep(1.1)
        stats = self.cache.get_stats()
        self.assertEqual(stats['expired_entries'], 1)


class TestS3PathImplCaching(unittest.TestCase):
    """Test S3PathImpl caching integration"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Configure a short TTL for testing
        configure_s3_cache(ttl=2, max_entries=100)
        clear_s3_cache()
    
    @patch('xefm.s3.boto3')
    def test_cached_head_object_calls(self, mock_boto3):
        """Test that head_object calls are cached"""
        # Mock S3 client
        mock_client = Mock()
        mock_boto3.client.return_value = mock_client
        
        # Mock head_object response
        from datetime import datetime
        mock_response = {
            'ContentLength': 1024,
            'LastModified': datetime.now()
        }
        mock_client.head_object.return_value = mock_response
        mock_client.list_objects_v2.return_value = {'KeyCount': 0}
        
        # Create S3 path
        s3_path = S3PathImpl('s3://test-bucket/test-key')
        
        # First call should hit the API
        result1 = s3_path.exists()
        self.assertTrue(result1)
        self.assertEqual(mock_client.head_object.call_count, 1)
        
        # Second call should use cache
        result2 = s3_path.exists()
        self.assertTrue(result2)
        self.assertEqual(mock_client.head_object.call_count, 1)  # No additional calls
        
        # Third call should also use cache
        stat_result = s3_path.stat()
        self.assertEqual(stat_result.st_size, 1024)
        self.assertEqual(mock_client.head_object.call_count, 1)  # Still no additional calls
    
    @patch('xefm.s3.boto3')
    def test_cache_invalidation_on_write(self, mock_boto3):
        """Test that cache is invalidated after write operations"""
        # Mock S3 client
        mock_client = Mock()
        mock_boto3.client.return_value = mock_client
        
        # Mock responses
        from datetime import datetime
        mock_client.head_object.return_value = {'ContentLength': 1024, 'LastModified': datetime.now()}
        mock_client.put_object.return_value = {}
        mock_client.list_objects_v2.return_value = {'KeyCount': 0}
        
        # Create S3 path
        s3_path = S3PathImpl('s3://test-bucket/test-key')
        
        # First exists() call should cache the result
        s3_path.exists()
        self.assertEqual(mock_client.head_object.call_count, 1)
        
        # Second exists() call should use cache
        s3_path.exists()
        self.assertEqual(mock_client.head_object.call_count, 1)
        
        # Write operation should invalidate cache
        s3_path.write_text("test content")
        self.assertEqual(mock_client.put_object.call_count, 1)
        
        # Next exists() call should hit the API again (cache invalidated)
        s3_path.exists()
        self.assertEqual(mock_client.head_object.call_count, 2)
    
    @patch('xefm.s3.boto3')
    def test_cache_expiration(self, mock_boto3):
        """Test that cached entries expire after TTL"""
        # Mock S3 client
        mock_client = Mock()
        mock_boto3.client.return_value = mock_client
        from datetime import datetime
        mock_client.head_object.return_value = {'ContentLength': 1024, 'LastModified': datetime.now()}
        mock_client.list_objects_v2.return_value = {'KeyCount': 0}
        
        # Create S3 path
        s3_path = S3PathImpl('s3://test-bucket/test-key')
        
        # First call should cache
        s3_path.exists()
        self.assertEqual(mock_client.head_object.call_count, 1)
        
        # Second call should use cache
        s3_path.exists()
        self.assertEqual(mock_client.head_object.call_count, 1)
        
        # Wait for cache to expire
        time.sleep(2.1)
        
        # Next call should hit API again
        s3_path.exists()
        self.assertEqual(mock_client.head_object.call_count, 2)
    
    def test_global_cache_functions(self):
        """Test global cache management functions"""
        # Test initial stats
        stats = get_s3_cache_stats()
        self.assertIsInstance(stats, dict)
        self.assertIn('total_entries', stats)
        
        # Test cache configuration
        configure_s3_cache(ttl=30, max_entries=500)
        stats = get_s3_cache_stats()
        self.assertEqual(stats['default_ttl'], 30)
        self.assertEqual(stats['max_entries'], 500)
        
        # Test cache clearing
        cache = get_s3_cache()
        cache.put('test', 'bucket', 'key', {'data': 'test'})
        stats = get_s3_cache_stats()
        self.assertGreater(stats['total_entries'], 0)
        
        clear_s3_cache()
        stats = get_s3_cache_stats()
        self.assertEqual(stats['total_entries'], 0)
