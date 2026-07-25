#!/usr/bin/env python3
"""
Performance validation for SFTP bulk stat optimization.

This script measures the actual performance improvements from caching
individual file stats during list_directory() operations.

Run with: PYTHONPATH=. python temp/test_ssh_bulk_stat_performance.py
"""

import sys
import time
import unittest
from unittest.mock import Mock, patch, MagicMock
from xefm.ssh_connection import SSHConnection
from xefm.ssh_cache import SSHCache


class TestBulkStatPerformance(unittest.TestCase):
    """Performance validation tests for bulk stat caching"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.hostname = "test-host"
        self.config = {
            'HostName': 'test.example.com',
            'User': 'testuser',
            'Port': '22'
        }
        
        # Create connection with mocked subprocess
        with patch('xefm.ssh_connection.subprocess'):
            self.conn = SSHConnection(self.hostname, self.config)
            self.conn._connected = True
            
        # Clear cache before each test
        self.conn._cache.clear()
    
    def tearDown(self):
        """Clean up after tests"""
        self.conn._cache.clear()
    
    def _mock_ls_output(self, num_files: int) -> str:
        """
        Generate mock ls -la output for testing.
        
        Args:
            num_files: Number of files to generate
            
        Returns:
            Mock ls -la output string
        """
        lines = []
        for i in range(num_files):
            # Generate realistic ls -la line
            line = f"-rw-r--r--  1 user group  {1000 + i} Jan 15 10:30 /test/file{i}.txt"
            lines.append(line)
        
        return '\n'.join(lines)
    
    def test_network_call_reduction_100_files(self):
        """
        Test that network calls are reduced from 101 to 1 for 100 files.
        
        Validates: Requirements 4.1
        """
        print("\n" + "="*60)
        print("Test: Network Call Reduction (100 files)")
        print("="*60)
        
        num_files = 100
        remote_path = "/test/directory"
        
        # Mock ls -la output
        ls_output = self._mock_ls_output(num_files)
        
        # Track network calls
        network_calls = []
        
        def mock_execute(commands, timeout=30):
            """Mock SFTP command execution"""
            network_calls.append(commands[0])
            
            if commands[0].startswith('ls -la'):
                return ls_output, '', 0
            elif commands[0].startswith('ls -l'):
                # Individual stat call - should not happen if cache works
                # Return single file info
                return "-rw-r--r--  1 user group  1000 Jan 15 10:30 /test/file0.txt", '', 0
            else:
                return '', '', 0
        
        with patch.object(self.conn, '_execute_sftp_command', side_effect=mock_execute):
            # Phase 1: Call list_directory() - should make 1 network call
            print(f"\nPhase 1: Calling list_directory() on {remote_path}")
            entries = self.conn.list_directory(remote_path)
            
            list_calls = len(network_calls)
            print(f"  Network calls after list_directory(): {list_calls}")
            self.assertEqual(list_calls, 1, "list_directory() should make exactly 1 network call")
            self.assertEqual(len(entries), num_files, f"Should return {num_files} entries")
            
            # Phase 2: Call stat() on each file - should make 0 additional network calls
            print(f"\nPhase 2: Calling stat() on {num_files} files")
            network_calls.clear()  # Reset counter
            
            for i in range(num_files):
                file_path = f"/test/directory/file{i}.txt"
                stat_info = self.conn.stat(file_path)
                self.assertIsNotNone(stat_info, f"stat() should return data for {file_path}")
            
            stat_calls = len(network_calls)
            print(f"  Network calls for {num_files} stat() operations: {stat_calls}")
            
            # Verify 0 network calls (all cache hits)
            self.assertEqual(stat_calls, 0, 
                           f"stat() should make 0 network calls (all cache hits), but made {stat_calls}")
            
            # Calculate improvement
            old_total = 101  # 1 list + 100 stats
            new_total = 1    # 1 list + 0 stats (cached)
            reduction_pct = ((old_total - new_total) / old_total) * 100
            
            print(f"\n✓ Network call reduction:")
            print(f"  Before optimization: {old_total} calls (1 list + 100 stats)")
            print(f"  After optimization:  {new_total} call (1 list + 0 stats)")
            print(f"  Reduction: {reduction_pct:.1f}%")
    
    def test_time_reduction_simulation(self):
        """
        Test that time is reduced by ~99% for directory loading.
        
        Simulates network latency to measure time improvement.
        
        Validates: Requirements 4.3
        """
        print("\n" + "="*60)
        print("Test: Time Reduction Simulation")
        print("="*60)
        
        num_files = 100
        remote_path = "/test/directory"
        network_latency_ms = 20  # Simulate 20ms per network call
        
        # Mock ls -la output
        ls_output = self._mock_ls_output(num_files)
        
        def mock_execute_with_latency(commands, timeout=30):
            """Mock SFTP command execution with simulated latency"""
            # Simulate network latency
            time.sleep(network_latency_ms / 1000.0)
            
            if commands[0].startswith('ls -la'):
                return ls_output, '', 0
            elif commands[0].startswith('ls -l'):
                return "-rw-r--r--  1 user group  1000 Jan 15 10:30 /test/file0.txt", '', 0
            else:
                return '', '', 0
        
        with patch.object(self.conn, '_execute_sftp_command', side_effect=mock_execute_with_latency):
            # Measure time for optimized path (with caching)
            print(f"\nMeasuring optimized path (with bulk stat caching):")
            start_time = time.time()
            
            # Call list_directory() - 1 network call
            entries = self.conn.list_directory(remote_path)
            
            # Call stat() on each file - 0 network calls (cached)
            for i in range(num_files):
                file_path = f"/test/directory/file{i}.txt"
                self.conn.stat(file_path)
            
            optimized_time = time.time() - start_time
            print(f"  Time: {optimized_time*1000:.1f}ms")
            
            # Clear cache to simulate unoptimized path
            self.conn._cache.clear()
            
            # Measure time for unoptimized path (without caching)
            print(f"\nSimulating unoptimized path (without bulk stat caching):")
            print(f"  (Simulating {num_files} individual stat() network calls)")
            
            # Calculate expected time: 1 list + 100 stats = 101 calls × 20ms
            unoptimized_time = (num_files + 1) * (network_latency_ms / 1000.0)
            print(f"  Expected time: {unoptimized_time*1000:.1f}ms")
            
            # Calculate improvement
            time_reduction_pct = ((unoptimized_time - optimized_time) / unoptimized_time) * 100
            
            print(f"\n✓ Time reduction:")
            print(f"  Before optimization: {unoptimized_time*1000:.1f}ms")
            print(f"  After optimization:  {optimized_time*1000:.1f}ms")
            print(f"  Reduction: {time_reduction_pct:.1f}%")
            
            # Verify at least 90% reduction (requirement 4.3)
            self.assertGreaterEqual(time_reduction_pct, 90.0,
                                  f"Time reduction should be at least 90%, got {time_reduction_pct:.1f}%")
    
    def test_cache_hit_rate(self):
        """
        Test that cache hit rate is > 99% after list_directory().
        
        Validates: Non-functional requirement (cache hit rate)
        """
        print("\n" + "="*60)
        print("Test: Cache Hit Rate")
        print("="*60)
        
        num_files = 100
        remote_path = "/test/directory"
        
        # Mock ls -la output
        ls_output = self._mock_ls_output(num_files)
        
        # Track cache hits and misses
        cache_hits = 0
        cache_misses = 0
        
        original_get = self.conn._cache.get
        
        def mock_cache_get(operation, hostname, path):
            """Track cache hits and misses"""
            nonlocal cache_hits, cache_misses
            result = original_get(operation, hostname, path)
            if result is not None:
                cache_hits += 1
            else:
                cache_misses += 1
            return result
        
        with patch.object(self.conn._cache, 'get', side_effect=mock_cache_get):
            with patch.object(self.conn, '_execute_sftp_command', 
                            return_value=(ls_output, '', 0)):
                # Call list_directory()
                print(f"\nCalling list_directory() on {remote_path}")
                entries = self.conn.list_directory(remote_path)
                
                # Reset counters (list_directory had a cache miss)
                cache_hits = 0
                cache_misses = 0
                
                # Call stat() on each file
                print(f"Calling stat() on {num_files} files")
                for i in range(num_files):
                    file_path = f"/test/directory/file{i}.txt"
                    self.conn.stat(file_path)
                
                # Calculate hit rate
                total_accesses = cache_hits + cache_misses
                hit_rate = (cache_hits / total_accesses) * 100 if total_accesses > 0 else 0
                
                print(f"\n✓ Cache statistics:")
                print(f"  Cache hits:   {cache_hits}")
                print(f"  Cache misses: {cache_misses}")
                print(f"  Hit rate:     {hit_rate:.1f}%")
                
                # Verify > 99% hit rate
                self.assertGreater(hit_rate, 99.0,
                                 f"Cache hit rate should be > 99%, got {hit_rate:.1f}%")
    
    def test_zero_network_calls_when_cached(self):
        """
        Test that 0 network calls are made when directory is already cached.
        
        Validates: Requirements 4.2
        """
        print("\n" + "="*60)
        print("Test: Zero Network Calls When Cached")
        print("="*60)
        
        num_files = 100
        remote_path = "/test/directory"
        
        # Mock ls -la output
        ls_output = self._mock_ls_output(num_files)
        
        # Track network calls
        network_calls = []
        
        def mock_execute(commands, timeout=30):
            """Mock SFTP command execution"""
            network_calls.append(commands[0])
            
            if commands[0].startswith('ls -la'):
                return ls_output, '', 0
            else:
                return '', '', 0
        
        with patch.object(self.conn, '_execute_sftp_command', side_effect=mock_execute):
            # First access - populate cache
            print(f"\nFirst access: Populating cache")
            self.conn.list_directory(remote_path)
            first_calls = len(network_calls)
            print(f"  Network calls: {first_calls}")
            
            # Second access - should use cache
            print(f"\nSecond access: Using cache")
            network_calls.clear()
            self.conn.list_directory(remote_path)
            second_calls = len(network_calls)
            print(f"  Network calls: {second_calls}")
            
            # Verify 0 network calls on second access
            self.assertEqual(second_calls, 0,
                           "Second list_directory() should make 0 network calls (cached)")
            
            # Call stat() on files - should also be cached
            print(f"\nCalling stat() on {num_files} files (should all be cached)")
            network_calls.clear()
            for i in range(num_files):
                file_path = f"/test/directory/file{i}.txt"
                self.conn.stat(file_path)
            
            stat_calls = len(network_calls)
            print(f"  Network calls: {stat_calls}")
            
            self.assertEqual(stat_calls, 0,
                           "stat() calls should make 0 network calls (all cached)")
            
            print(f"\n✓ Total network calls when cached: 0")


def run_performance_validation():
    """Run all performance validation tests"""
    print("\n" + "="*70)
    print("SFTP BULK STAT OPTIMIZATION - PERFORMANCE VALIDATION")
    print("="*70)
    print("\nThis test suite validates the performance improvements from")
    print("caching individual file stats during list_directory() operations.")
    print("\nExpected improvements:")
    print("  - Network calls: 101 → 1 (99% reduction)")
    print("  - Load time: ~2000ms → ~20ms (99% reduction)")
    print("  - Cache hit rate: > 99%")
    
    # Run tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBulkStatPerformance)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("PERFORMANCE VALIDATION SUMMARY")
    print("="*70)
    
    if result.wasSuccessful():
        print("\n✓ All performance validation tests PASSED")
        print("\nKey findings:")
        print("  ✓ Network calls reduced from 101 to 1 (99% reduction)")
        print("  ✓ Time reduced by at least 90% (requirement met)")
        print("  ✓ Cache hit rate > 99% (requirement met)")
        print("  ✓ Zero network calls when directory is cached")
        print("\nConclusion:")
        print("  The bulk stat optimization successfully achieves the")
        print("  performance goals specified in the requirements.")
        return 0
    else:
        print("\n✗ Some performance validation tests FAILED")
        print(f"\nFailures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
        return 1


if __name__ == '__main__':
    sys.exit(run_performance_validation())
