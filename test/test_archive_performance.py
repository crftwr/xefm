"""
Performance tests for archive virtual directory feature.

Tests verify:
- Archive caching with LRU eviction is working efficiently
- Lazy loading for archive directory structures
- Memory usage optimization for large archives
- Hot path optimization in ArchivePathImpl

Run with: python -m pytest test/test_archive_performance.py -v
"""

import sys
import time
import tempfile
import zipfile
import tarfile
from pathlib import Path as PathlibPath

from xefm.path import Path
from xefm.archive import ArchiveCache, get_archive_cache, ArchivePathImpl


def create_test_archive(archive_path: PathlibPath, num_files: int = 100, num_dirs: int = 10):
    """Create a test archive with specified number of files and directories"""
    with zipfile.ZipFile(str(archive_path), 'w') as zf:
        # Create directory structure
        for i in range(num_dirs):
            dir_name = f"dir_{i}/"
            zf.writestr(dir_name, '')
            
            # Add files to each directory
            for j in range(num_files // num_dirs):
                file_name = f"dir_{i}/file_{j}.txt"
                content = f"Content of file {j} in directory {i}\n" * 10
                zf.writestr(file_name, content)


def test_cache_efficiency():
    """Test that archive caching with LRU eviction is working efficiently"""
    print("\n=== Testing Cache Efficiency ===")
    
    # Create temporary directory for test archives
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = PathlibPath(temp_dir)
        
        # Create multiple test archives
        archives = []
        for i in range(10):
            archive_path = temp_path / f"test_{i}.zip"
            create_test_archive(archive_path, num_files=50, num_dirs=5)
            archives.append(archive_path)
        
        # Get the global cache and clear it
        cache = get_archive_cache()
        cache.clear()
        
        # Reconfigure cache for testing
        cache._max_open = 5
        cache._ttl = 300
        
        # Access archives in sequence - should trigger LRU eviction
        print(f"Accessing {len(archives)} archives with max_open=5...")
        start_time = time.time()
        
        for archive_path in archives:
            path = Path(archive_path)
            archive_uri = f"archive://{path.absolute()}#"
            archive_path_impl = Path(archive_uri)
            
            # Access the archive (triggers handler creation)
            _ = list(archive_path_impl.iterdir())
        
        elapsed = time.time() - start_time
        print(f"First pass completed in {elapsed:.3f}s")
        
        # Get cache statistics
        stats = cache.get_stats()
        print(f"\nCache Statistics:")
        print(f"  Open archives: {stats['open_archives']}/{stats['max_open']}")
        print(f"  Cache hits: {stats['cache_hits']}")
        print(f"  Cache misses: {stats['cache_misses']}")
        print(f"  Hit rate: {stats['hit_rate']:.2%}")
        print(f"  Evictions: {stats['evictions']}")
        print(f"  Avg open time: {stats['avg_open_time']:.4f}s")
        
        # Verify LRU eviction occurred
        assert stats['evictions'] > 0, "Expected LRU evictions to occur"
        assert stats['open_archives'] <= 5, "Cache should not exceed max_open"
        
        # Access same archives again - should have better hit rate
        print("\nAccessing archives again (should use cache)...")
        start_time = time.time()
        
        for archive_path in archives[-5:]:  # Access last 5 (should be in cache)
            path = Path(archive_path)
            archive_uri = f"archive://{path.absolute()}#"
            archive_path_impl = Path(archive_uri)
            _ = list(archive_path_impl.iterdir())
        
        elapsed = time.time() - start_time
        print(f"Second pass completed in {elapsed:.3f}s")
        
        # Get updated statistics
        stats = cache.get_stats()
        print(f"\nUpdated Cache Statistics:")
        print(f"  Cache hits: {stats['cache_hits']}")
        print(f"  Cache misses: {stats['cache_misses']}")
        print(f"  Hit rate: {stats['hit_rate']:.2%}")
        
        # Verify cache is working
        assert stats['cache_hits'] > 0, "Expected cache hits on second pass"
        
        print("\n✓ Cache efficiency test passed")


def test_lazy_loading():
    """Test that lazy loading for archive directory structures works"""
    print("\n=== Testing Lazy Loading ===")
    
    # Clear cache before test
    cache = get_archive_cache()
    cache.clear()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = PathlibPath(temp_dir)
        
        # Create a large archive (>1000 files to trigger lazy loading)
        print("Creating large archive with 1500 files...")
        large_archive = temp_path / "large.zip"
        create_test_archive(large_archive, num_files=1500, num_dirs=15)
        
        # Access the archive
        path = Path(large_archive)
        archive_uri = f"archive://{path.absolute()}#"
        archive_path_impl = Path(archive_uri)
        
        # Measure time to open and list root directory
        print("Opening archive and listing root directory...")
        start_time = time.time()
        root_entries = list(archive_path_impl.iterdir())
        elapsed = time.time() - start_time
        
        print(f"Listed {len(root_entries)} root entries in {elapsed:.3f}s")
        
        # Access a specific subdirectory
        if root_entries:
            subdir = root_entries[0]
            print(f"\nAccessing subdirectory: {subdir.name}")
            start_time = time.time()
            subdir_entries = list(subdir.iterdir())
            elapsed = time.time() - start_time
            
            print(f"Listed {len(subdir_entries)} entries in subdirectory in {elapsed:.3f}s")
        
        # Verify lazy loading is working (should be fast)
        assert elapsed < 1.0, f"Lazy loading should be fast, took {elapsed:.3f}s"
        
        print("\n✓ Lazy loading test passed")


def test_memory_optimization():
    """Test memory usage optimization for large archives"""
    print("\n=== Testing Memory Optimization ===")
    
    # Get the global cache and clear it
    cache = get_archive_cache()
    cache.clear()
    
    # Reconfigure cache for testing
    cache._max_open = 2
    cache._ttl = 300
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = PathlibPath(temp_dir)
        
        # Create multiple large archives
        print("Creating 3 large archives...")
        archives = []
        for i in range(3):
            archive_path = temp_path / f"large_{i}.zip"
            create_test_archive(archive_path, num_files=1000, num_dirs=10)
            archives.append(archive_path)
        
        # Access all archives - should evict oldest
        print("Accessing archives (should trigger eviction)...")
        for archive_path in archives:
            path = Path(archive_path)
            archive_uri = f"archive://{path.absolute()}#"
            archive_path_impl = Path(archive_uri)
            _ = list(archive_path_impl.iterdir())
        
        # Verify memory is managed
        stats = cache.get_stats()
        print(f"\nCache Statistics:")
        print(f"  Open archives: {stats['open_archives']}/{stats['max_open']}")
        print(f"  Evictions: {stats['evictions']}")
        
        assert stats['open_archives'] <= 2, "Should not exceed max_open"
        assert stats['evictions'] >= 1, "Should have evicted at least one archive"
        
        print("\n✓ Memory optimization test passed")


def test_hot_path_optimization():
    """Test hot path optimization in ArchivePathImpl"""
    print("\n=== Testing Hot Path Optimization ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = PathlibPath(temp_dir)
        
        # Create test archive
        archive_path = temp_path / "test.zip"
        create_test_archive(archive_path, num_files=100, num_dirs=10)
        
        # Create archive path
        path = Path(archive_path)
        archive_uri = f"archive://{path.absolute()}#dir_0/file_0.txt"
        archive_path_impl = Path(archive_uri)
        
        # Test property access performance (should use cache)
        print("Testing property access performance...")
        iterations = 1000
        
        # Test name property
        start_time = time.time()
        for _ in range(iterations):
            _ = archive_path_impl.name
        elapsed = time.time() - start_time
        print(f"  name property: {iterations} accesses in {elapsed:.4f}s ({elapsed/iterations*1000:.4f}ms each)")
        
        # Test parts property
        start_time = time.time()
        for _ in range(iterations):
            _ = archive_path_impl.parts
        elapsed = time.time() - start_time
        print(f"  parts property: {iterations} accesses in {elapsed:.4f}s ({elapsed/iterations*1000:.4f}ms each)")
        
        # Test stem property
        start_time = time.time()
        for _ in range(iterations):
            _ = archive_path_impl.stem
        elapsed = time.time() - start_time
        print(f"  stem property: {iterations} accesses in {elapsed:.4f}s ({elapsed/iterations*1000:.4f}ms each)")
        
        # Verify property caching is working (should be very fast)
        assert elapsed < 0.1, f"Property access should be fast with caching, took {elapsed:.4f}s"
        
        print("\n✓ Hot path optimization test passed")


def test_cache_statistics():
    """Test that cache statistics are tracked correctly"""
    print("\n=== Testing Cache Statistics ===")
    
    # Get the global cache and clear it
    cache = get_archive_cache()
    cache.clear()
    
    # Reconfigure cache for testing
    cache._max_open = 3
    cache._ttl = 300
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = PathlibPath(temp_dir)
        
        # Create test archive
        archive_path = temp_path / "test.zip"
        create_test_archive(archive_path, num_files=50, num_dirs=5)
        
        # Access archive multiple times
        path = Path(archive_path)
        archive_uri = f"archive://{path.absolute()}#"
        
        for i in range(5):
            archive_path_impl = Path(archive_uri)
            _ = list(archive_path_impl.iterdir())
        
        # Get statistics
        stats = cache.get_stats()
        print(f"\nCache Statistics:")
        print(f"  Open archives: {stats['open_archives']}")
        print(f"  Max open: {stats['max_open']}")
        print(f"  TTL: {stats['ttl']}s")
        print(f"  Cache hits: {stats['cache_hits']}")
        print(f"  Cache misses: {stats['cache_misses']}")
        print(f"  Hit rate: {stats['hit_rate']:.2%}")
        print(f"  Evictions: {stats['evictions']}")
        print(f"  Avg open time: {stats['avg_open_time']:.4f}s")
        
        # Verify statistics are reasonable
        assert stats['cache_hits'] > 0, "Should have cache hits"
        assert stats['cache_misses'] > 0, "Should have cache misses"
        assert 0 <= stats['hit_rate'] <= 1.0, "Hit rate should be between 0 and 1"
        assert stats['avg_open_time'] >= 0, "Average open time should be non-negative"
        
        print("\n✓ Cache statistics test passed")


def main():
    """Run all performance tests"""
    print("=" * 60)
    print("Archive Virtual Directory Performance Tests")
    print("=" * 60)
    
    try:
        test_cache_efficiency()
        test_lazy_loading()
        test_memory_optimization()
        test_hot_path_optimization()
        test_cache_statistics()
        
        print("\n" + "=" * 60)
        print("All performance tests passed!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
