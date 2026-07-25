"""
Test S3 Virtual Directory Stats Simplified

This test verifies that the simplified _get_virtual_directory_stats() method
works correctly with the new metadata caching system.

Run with: python -m pytest test/test_s3_virtual_directory_stats_simplified.py -v
"""

import time
import unittest
from unittest.mock import Mock, patch
from datetime import datetime

try:
    from xefm.path import Path
    from xefm.s3 import S3PathImpl, get_s3_cache
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Skipping S3 virtual directory stats simplified tests")
    sys.exit(0)


class TestS3VirtualDirectoryStatsSimplified(unittest.TestCase):
    """Test simplified S3 virtual directory stats"""
    
    def setUp(self):
        """Set up test environment"""
        # Clear cache before each test
        cache = get_s3_cache()
        cache.clear()
    
    def test_virtual_directory_stats_with_cached_metadata(self):
        """Test that virtual directories with cached metadata use cached mtime"""
        # Create virtual directory with cached metadata
        test_time = datetime(2024, 1, 15, 12, 0, 0)
        metadata = {
            'is_dir': True,
            'is_file': False,
            'size': 0,
            'last_modified': test_time,
            'etag': '',
            'storage_class': ''
        }
        
        virtual_dir = S3PathImpl('s3://test-bucket/virtual-dir/', metadata=metadata)
        
        # Get virtual directory stats
        size, mtime = virtual_dir._get_virtual_directory_stats()
        
        # Should use cached metadata
        self.assertEqual(size, 0)
        self.assertEqual(mtime, test_time.timestamp())
    
    def test_virtual_directory_stats_without_cached_metadata(self):
        """Test that virtual directories without cached metadata use current time"""
        # Create virtual directory without metadata
        virtual_dir = S3PathImpl('s3://test-bucket/virtual-dir/')
        
        # Record time before call
        before_time = time.time()
        
        # Get virtual directory stats
        size, mtime = virtual_dir._get_virtual_directory_stats()
        
        # Record time after call
        after_time = time.time()
        
        # Should use current time
        self.assertEqual(size, 0)
        self.assertGreaterEqual(mtime, before_time)
        self.assertLessEqual(mtime, after_time)
        
        # Should cache the result
        self.assertEqual(virtual_dir._size_cached, 0)
        self.assertIsNotNone(virtual_dir._mtime_cached)
    
    def test_virtual_directory_stats_caches_result(self):
        """Test that _get_virtual_directory_stats caches its result"""
        # Create virtual directory without metadata
        virtual_dir = S3PathImpl('s3://test-bucket/virtual-dir/')
        
        # First call should cache the result
        size1, mtime1 = virtual_dir._get_virtual_directory_stats()
        
        # Verify cached values are set
        self.assertIsNotNone(virtual_dir._size_cached)
        self.assertIsNotNone(virtual_dir._mtime_cached)
        
        # Second call should use cached values
        size2, mtime2 = virtual_dir._get_virtual_directory_stats()
        
        # Results should be identical
        self.assertEqual(size1, size2)
        self.assertEqual(mtime1, mtime2)
    
    @patch('xefm.s3.boto3.client')
    def test_stat_uses_cached_metadata_for_virtual_directory(self, mock_boto3_client):
        """Test that stat() uses cached metadata for virtual directories"""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client
        
        # Create virtual directory with cached metadata
        test_time = datetime(2024, 1, 15, 12, 0, 0)
        metadata = {
            'is_dir': True,
            'is_file': False,
            'size': 0,
            'last_modified': test_time,
            'etag': '',
            'storage_class': ''
        }
        
        virtual_dir_path = S3PathImpl.create_path_with_metadata('s3://test-bucket/virtual-dir/', metadata)
        
        # Call stat() - should use cached metadata without API calls
        stat_result = virtual_dir_path.stat()
        
        # Verify results
        self.assertEqual(stat_result.st_size, 0)
        self.assertEqual(stat_result.st_mtime, test_time.timestamp())
        self.assertTrue(stat_result.st_mode & 0o040000)  # Directory mode
        
        # Verify no API calls were made
        mock_client.list_objects_v2.assert_not_called()
        mock_client.head_object.assert_not_called()
    
    @patch('xefm.s3.boto3.client')
    def test_iterdir_creates_virtual_directories_with_metadata(self, mock_boto3_client):
        """Test that iterdir() creates virtual directories with proper metadata"""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client
        
        # Mock list_objects_v2 response with virtual directory
        mock_list_response = {
            'Contents': [],
            'CommonPrefixes': [{'Prefix': 'project/subdir/'}],
            'KeyCount': 0,
            'IsTruncated': False
        }
        
        mock_client.list_objects_v2.return_value = mock_list_response
        
        # Mock paginator
        mock_paginator = Mock()
        mock_paginator.paginate.return_value = [mock_list_response]
        mock_client.get_paginator.return_value = mock_paginator
        
        # List directory contents
        s3_path = Path('s3://test-bucket/project/')
        files = list(s3_path.iterdir())
        
        # Should find the virtual directory
        self.assertEqual(len(files), 1)
        virtual_dir = files[0]
        
        # Verify it has cached metadata
        self.assertTrue(virtual_dir._impl._is_dir_cached)
        self.assertFalse(virtual_dir._impl._is_file_cached)
        self.assertEqual(virtual_dir._impl._size_cached, 0)
        self.assertIsNotNone(virtual_dir._impl._mtime_cached)
        
        # Verify operations use cached metadata (no API calls)
        mock_client.reset_mock()
        
        is_dir = virtual_dir.is_dir()
        is_file = virtual_dir.is_file()
        stat_result = virtual_dir.stat()
        
        # Verify results
        self.assertTrue(is_dir)
        self.assertFalse(is_file)
        self.assertEqual(stat_result.st_size, 0)
        
        # Verify no additional API calls
        mock_client.list_objects_v2.assert_not_called()
        mock_client.head_object.assert_not_called()
    
    def test_simplified_method_performance(self):
        """Test that the simplified method is fast"""
        # Create virtual directory with cached metadata
        test_time = datetime(2024, 1, 15, 12, 0, 0)
        metadata = {
            'is_dir': True,
            'is_file': False,
            'size': 0,
            'last_modified': test_time,
            'etag': '',
            'storage_class': ''
        }
        
        virtual_dir = S3PathImpl('s3://test-bucket/virtual-dir/', metadata=metadata)
        
        # Time multiple calls
        start_time = time.time()
        for _ in range(1000):
            virtual_dir._get_virtual_directory_stats()
        elapsed_time = time.time() - start_time
        
        # Should be very fast (< 1ms total for 1000 calls)
        self.assertLess(elapsed_time, 0.001)
        
        # Average per call should be sub-microsecond
        avg_per_call = elapsed_time / 1000
        self.assertLess(avg_per_call, 0.000001)  # < 1 microsecond


def main():
    """Run the tests"""
    unittest.main(verbosity=2)
