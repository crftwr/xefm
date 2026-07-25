#!/usr/bin/env python3
"""
Verification test for SSH control master check optimization.

This test validates that:
1. Control master checks are cached within the check interval
2. Subprocess calls are reduced by ~99% (100 → 1 for 100 operations)
3. Health checks use cached status within the health check interval
4. Operations still work correctly with caching enabled
5. Connection errors trigger fresh checks

Run with: PYTHONPATH=. python temp/verify_control_master_optimization.py
"""

import os
import sys
import time
import unittest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict

# Add the repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xefm.ssh_connection import SSHConnection, SSHConnectionManager


class TestControlMasterOptimization(unittest.TestCase):
    """Test control master check optimization."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.hostname = "test-host"
        self.config = {
            'HostName': 'test.example.com',
            'User': 'testuser',
            'Port': '22'
        }
    
    def test_caching_attributes_initialized(self):
        """Test that caching attributes are properly initialized."""
        conn = SSHConnection(self.hostname, self.config)
        
        # Verify caching attributes exist
        self.assertTrue(hasattr(conn, '_last_control_master_check'))
        self.assertTrue(hasattr(conn, '_control_master_check_interval'))
        self.assertTrue(hasattr(conn, '_cached_control_master_status'))
        
        # Verify initial values
        self.assertEqual(conn._last_control_master_check, 0)
        self.assertEqual(conn._control_master_check_interval, 5.0)
        self.assertEqual(conn._cached_control_master_status, False)
        
        print("✓ Caching attributes initialized correctly")
    
    def test_control_master_check_caching(self):
        """Test that control master checks are cached within interval."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Mock _check_control_master to count calls
        call_count = 0
        original_check = conn._check_control_master
        
        def mock_check():
            nonlocal call_count
            call_count += 1
            return True
        
        conn._check_control_master = mock_check
        
        # First call should trigger check
        result1 = conn.is_connected()
        self.assertTrue(result1)
        self.assertEqual(call_count, 1)
        
        # Immediate second call should use cache (no subprocess)
        result2 = conn.is_connected()
        self.assertTrue(result2)
        self.assertEqual(call_count, 1)  # Still 1, not 2!
        
        # Multiple calls within interval should all use cache
        for _ in range(10):
            result = conn.is_connected()
            self.assertTrue(result)
        self.assertEqual(call_count, 1)  # Still 1!
        
        print(f"✓ Control master check cached: 12 calls → {call_count} subprocess call")
    
    def test_control_master_check_after_interval(self):
        """Test that control master check is performed after interval elapses."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        conn._control_master_check_interval = 0.1  # 100ms for faster test
        
        # Mock _check_control_master to count calls
        call_count = 0
        
        def mock_check():
            nonlocal call_count
            call_count += 1
            return True
        
        conn._check_control_master = mock_check
        
        # First call
        conn.is_connected()
        self.assertEqual(call_count, 1)
        
        # Wait for interval to elapse
        time.sleep(0.15)
        
        # Next call should trigger fresh check
        conn.is_connected()
        self.assertEqual(call_count, 2)
        
        print("✓ Fresh check performed after interval elapsed")
    
    def test_subprocess_call_reduction(self):
        """Test that subprocess calls are reduced by ~99% for 100 operations."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Mock _check_control_master to count calls
        call_count = 0
        
        def mock_check():
            nonlocal call_count
            call_count += 1
            return True
        
        conn._check_control_master = mock_check
        
        # Perform 100 operations within 5 seconds
        for _ in range(100):
            conn.is_connected()
        
        # Should only have 1 subprocess call (99% reduction)
        self.assertEqual(call_count, 1)
        reduction_percent = ((100 - call_count) / 100) * 100
        
        print(f"✓ Subprocess call reduction: 100 operations → {call_count} call ({reduction_percent:.0f}% reduction)")
    
    def test_health_check_optimization(self):
        """Test that health checks use cached status within interval."""
        manager = SSHConnectionManager.get_instance()
        manager._health_check_interval = 60  # 60 seconds
        
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Mock _check_control_master to count calls
        call_count = 0
        
        def mock_check():
            nonlocal call_count
            call_count += 1
            return True
        
        conn._check_control_master = mock_check
        
        # First health check should call is_connected()
        result1 = manager._check_connection_health(self.hostname, conn)
        self.assertTrue(result1)
        self.assertEqual(call_count, 1)
        
        # Immediate second health check should use cached _connected status
        # without calling is_connected() at all
        result2 = manager._check_connection_health(self.hostname, conn)
        self.assertTrue(result2)
        self.assertEqual(call_count, 1)  # Still 1!
        
        # Multiple health checks within interval should all use cached status
        for _ in range(10):
            result = manager._check_connection_health(self.hostname, conn)
            self.assertTrue(result)
        self.assertEqual(call_count, 1)  # Still 1!
        
        print(f"✓ Health check optimization: 12 checks → {call_count} subprocess call")
    
    def test_connection_error_clears_cache(self):
        """Test that connection errors properly update cached status."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Mock _check_control_master to return False (connection lost)
        def mock_check_fail():
            return False
        
        conn._check_control_master = mock_check_fail
        
        # Call is_connected() - should detect failure
        result = conn.is_connected()
        self.assertFalse(result)
        
        # Verify connection marked as disconnected
        self.assertFalse(conn._connected)
        
        # Verify cached status updated
        self.assertFalse(conn._cached_control_master_status)
        
        print("✓ Connection error properly updates cached status")
    
    def test_cached_status_accuracy(self):
        """Test that cached status accurately reflects connection state."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Mock _check_control_master to return True
        conn._check_control_master = lambda: True
        
        # First call should cache True status
        result1 = conn.is_connected()
        self.assertTrue(result1)
        self.assertTrue(conn._cached_control_master_status)
        
        # Cached status should be returned
        result2 = conn.is_connected()
        self.assertTrue(result2)
        
        print("✓ Cached status accurately reflects connection state")
    
    def test_thread_safety(self):
        """Test that caching is thread-safe."""
        import threading
        
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        conn._check_control_master = lambda: True
        
        results = []
        errors = []
        
        def check_connection():
            try:
                for _ in range(10):
                    result = conn.is_connected()
                    results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = [threading.Thread(target=check_connection) for _ in range(5)]
        
        # Start all threads
        for t in threads:
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # Verify no errors
        self.assertEqual(len(errors), 0)
        
        # Verify all results are True
        self.assertTrue(all(results))
        
        print(f"✓ Thread safety verified: {len(results)} concurrent checks, 0 errors")


def run_tests():
    """Run all verification tests."""
    print("=" * 70)
    print("SSH Control Master Check Optimization - Verification Tests")
    print("=" * 70)
    print()
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestControlMasterOptimization)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print()
    
    if result.wasSuccessful():
        print("✓ All verification tests passed!")
        print()
        print("Key Results:")
        print("  • Control master checks are properly cached")
        print("  • Subprocess calls reduced by 99% (100 → 1)")
        print("  • Health checks use cached status efficiently")
        print("  • Connection errors properly handled")
        print("  • Thread-safe implementation verified")
        return 0
    else:
        print("✗ Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
