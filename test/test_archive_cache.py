"""
Test ArchiveCache class functionality

Run with: python -m pytest test/test_archive_cache.py -v
"""

import os
import unittest
import tempfile
import zipfile
import tarfile
import time
from pathlib import Path as PathlibPath

from xefm.archive import ArchiveCache, ArchiveHandler, ZipHandler, TarHandler
from xefm.path import Path


class TestArchiveCache(unittest.TestCase):
    """Test the ArchiveCache class functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create temporary directory for test archives
        self.temp_dir = tempfile.mkdtemp(prefix='test_archive_cache_')
        self.temp_path = PathlibPath(self.temp_dir)
        
        # Create test ZIP archive
        self.zip_path = self.temp_path / 'test.zip'
        with zipfile.ZipFile(str(self.zip_path), 'w') as zf:
            zf.writestr('file1.txt', 'content1')
            zf.writestr('file2.txt', 'content2')
        
        # Create test TAR archive
        self.tar_path = self.temp_path / 'test.tar.gz'
        with tarfile.open(str(self.tar_path), 'w:gz') as tf:
            # Create temporary files to add to tar
            temp_file1 = self.temp_path / 'temp1.txt'
            temp_file1.write_text('content1')
            tf.add(str(temp_file1), arcname='file1.txt')
            temp_file1.unlink()
    
    def tearDown(self):
        """Clean up test fixtures"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_cache_initialization(self):
        """Test cache initialization with custom parameters"""
        cache = ArchiveCache(max_open=3, ttl=60)
        
        self.assertEqual(cache._max_open, 3)
        self.assertEqual(cache._ttl, 60)
        self.assertEqual(len(cache._handlers), 0)
        self.assertEqual(len(cache._access_times), 0)
    
    def test_get_handler_creates_handler(self):
        """Test that get_handler creates and caches a handler"""
        cache = ArchiveCache(max_open=5, ttl=300)
        archive_path = Path(self.zip_path)
        
        # Get handler for the first time
        handler = cache.get_handler(archive_path)
        
        # Verify handler was created and cached
        self.assertIsInstance(handler, ZipHandler)
        self.assertEqual(len(cache._handlers), 1)
        self.assertTrue(handler._is_open)
    
    def test_get_handler_returns_cached_handler(self):
        """Test that get_handler returns cached handler on subsequent calls"""
        cache = ArchiveCache(max_open=5, ttl=300)
        archive_path = Path(self.zip_path)
        
        # Get handler twice
        handler1 = cache.get_handler(archive_path)
        handler2 = cache.get_handler(archive_path)
        
        # Verify same handler is returned
        self.assertIs(handler1, handler2)
        self.assertEqual(len(cache._handlers), 1)
    
    def test_get_handler_updates_access_time(self):
        """Test that get_handler updates access time"""
        cache = ArchiveCache(max_open=5, ttl=300)
        archive_path = Path(self.zip_path)
        
        # Get handler and record access time
        handler1 = cache.get_handler(archive_path)
        cache_key = str(archive_path.absolute())
        access_time1 = cache._access_times[cache_key]
        
        # Wait a bit and get handler again
        time.sleep(0.1)
        handler2 = cache.get_handler(archive_path)
        access_time2 = cache._access_times[cache_key]
        
        # Verify access time was updated
        self.assertGreater(access_time2, access_time1)
    
    def test_lru_eviction(self):
        """Test LRU eviction when max_open is reached"""
        cache = ArchiveCache(max_open=2, ttl=300)
        
        # Create three archives
        zip_path1 = self.temp_path / 'test1.zip'
        zip_path2 = self.temp_path / 'test2.zip'
        zip_path3 = self.temp_path / 'test3.zip'
        
        for path in [zip_path1, zip_path2, zip_path3]:
            with zipfile.ZipFile(str(path), 'w') as zf:
                zf.writestr('file.txt', 'content')
        
        # Get handlers for first two archives
        handler1 = cache.get_handler(Path(zip_path1))
        handler2 = cache.get_handler(Path(zip_path2))
        
        # Verify both are cached
        self.assertEqual(len(cache._handlers), 2)
        
        # Get handler for third archive (should evict first)
        handler3 = cache.get_handler(Path(zip_path3))
        
        # Verify only two handlers are cached
        self.assertEqual(len(cache._handlers), 2)
        
        # Verify first handler was evicted
        cache_key1 = str(Path(zip_path1).absolute())
        self.assertNotIn(cache_key1, cache._handlers)
    
    def test_ttl_expiration(self):
        """Test that expired handlers are removed"""
        cache = ArchiveCache(max_open=5, ttl=1)  # 1 second TTL
        archive_path = Path(self.zip_path)
        
        # Get handler
        handler1 = cache.get_handler(archive_path)
        self.assertEqual(len(cache._handlers), 1)
        
        # Wait for TTL to expire
        time.sleep(1.5)
        
        # Get handler again (should create new one)
        handler2 = cache.get_handler(archive_path)
        
        # Verify new handler was created
        self.assertIsNot(handler1, handler2)
        self.assertEqual(len(cache._handlers), 1)
    
    def test_invalidate_specific_archive(self):
        """Test invalidating cache for specific archive"""
        cache = ArchiveCache(max_open=5, ttl=300)
        archive_path = Path(self.zip_path)
        
        # Get handler
        handler = cache.get_handler(archive_path)
        self.assertEqual(len(cache._handlers), 1)
        
        # Invalidate the archive
        cache.invalidate(archive_path)
        
        # Verify handler was removed
        self.assertEqual(len(cache._handlers), 0)
        self.assertEqual(len(cache._access_times), 0)
    
    def test_clear_all_caches(self):
        """Test clearing all cached archives"""
        cache = ArchiveCache(max_open=5, ttl=300)
        
        # Create and cache multiple archives
        zip_path1 = self.temp_path / 'test1.zip'
        zip_path2 = self.temp_path / 'test2.zip'
        
        for path in [zip_path1, zip_path2]:
            with zipfile.ZipFile(str(path), 'w') as zf:
                zf.writestr('file.txt', 'content')
        
        handler1 = cache.get_handler(Path(zip_path1))
        handler2 = cache.get_handler(Path(zip_path2))
        
        self.assertEqual(len(cache._handlers), 2)
        
        # Clear all caches
        cache.clear()
        
        # Verify all handlers were removed
        self.assertEqual(len(cache._handlers), 0)
        self.assertEqual(len(cache._access_times), 0)
    
    def test_get_stats(self):
        """Test cache statistics"""
        cache = ArchiveCache(max_open=5, ttl=300)
        
        # Get initial stats
        stats = cache.get_stats()
        self.assertEqual(stats['open_archives'], 0)
        self.assertEqual(stats['max_open'], 5)
        self.assertEqual(stats['ttl'], 300)
        self.assertEqual(stats['expired_count'], 0)
        
        # Add some archives
        archive_path = Path(self.zip_path)
        handler = cache.get_handler(archive_path)
        
        # Get stats again
        stats = cache.get_stats()
        self.assertEqual(stats['open_archives'], 1)
    
    def test_handler_format_detection(self):
        """Test that correct handler type is created for different formats"""
        cache = ArchiveCache(max_open=5, ttl=300)
        
        # Test ZIP handler
        zip_handler = cache.get_handler(Path(self.zip_path))
        self.assertIsInstance(zip_handler, ZipHandler)
        
        # Test TAR handler
        tar_handler = cache.get_handler(Path(self.tar_path))
        self.assertIsInstance(tar_handler, TarHandler)
    
    def test_thread_safety(self):
        """Test that cache operations are thread-safe"""
        import threading
        
        cache = ArchiveCache(max_open=5, ttl=300)
        archive_path = Path(self.zip_path)
        results = []
        
        def get_handler_thread():
            try:
                handler = cache.get_handler(archive_path)
                results.append(handler)
            except Exception as e:
                results.append(e)
        
        # Create multiple threads
        threads = [threading.Thread(target=get_handler_thread) for _ in range(10)]
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all threads got a handler (same instance)
        self.assertEqual(len(results), 10)
        for result in results:
            self.assertIsInstance(result, ArchiveHandler)
        
        # Verify only one handler was created
        self.assertEqual(len(cache._handlers), 1)
