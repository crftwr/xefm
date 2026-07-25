"""
Verification script for SSH error handling in bulk stat optimization.

This script verifies that:
1. list_directory() errors don't create stat cache entries
2. Partial parse failures cache successful entries
3. Cached errors are re-raised correctly

Requirements: 6.1, 6.2, 6.3, 6.4
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import Mock, patch, MagicMock
from xefm.ssh_connection import SSHConnection, SSHPathNotFoundError, SSHPermissionDeniedError
from xefm.ssh_cache import SSHCache


def test_list_directory_error_no_stat_cache():
    """
    Verify that list_directory() errors don't create stat cache entries.
    
    Requirements: 6.2
    """
    print("\n=== Test 1: list_directory() error doesn't create stat cache entries ===")
    
    # Create connection with mock cache
    cache = SSHCache()
    conn = SSHConnection('testhost', {'HostName': 'test.example.com'})
    conn._cache = cache
    conn._connected = True
    
    # Mock _execute_sftp_command to return an error
    with patch.object(conn, '_execute_sftp_command') as mock_exec:
        mock_exec.return_value = ('', 'No such file or directory', 1)
        
        # Try to list a non-existent directory
        try:
            conn.list_directory('/nonexistent')
            print("❌ FAIL: Expected SSHPathNotFoundError to be raised")
            return
        except SSHPathNotFoundError as e:
            print(f"✓ SSHPathNotFoundError raised as expected: {e}")
        
        # Verify that no stat cache entries were created
        # Check cache for any stat operations
        cache_stats = cache.get_stats()
        stat_count = cache_stats['operation_counts'].get('stat', 0)
        
        if stat_count > 0:
            print(f"❌ FAIL: Found {stat_count} stat cache entries, expected 0")
            return
        
        print("✓ No stat cache entries created")
        
        # Verify that the error was cached for list_directory
        try:
            cached_result = cache.get(
                operation='list_directory',
                hostname='testhost',
                path='/nonexistent'
            )
            print("❌ FAIL: Expected cached error to be re-raised")
            return
        except SSHPathNotFoundError:
            print("✓ Error was cached for list_directory operation")
    
    print("✓ Test 1 PASSED")
    return


def test_partial_parse_failures_cache_successful():
    """
    Verify that partial parse failures cache successful entries.
    
    Requirements: 6.1
    """
    print("\n=== Test 2: Partial parse failures cache successful entries ===")
    
    # Create connection with mock cache
    cache = SSHCache()
    conn = SSHConnection('testhost', {'HostName': 'test.example.com'})
    conn._cache = cache
    conn._connected = True
    
    # Mock _execute_sftp_command to return mixed output (some valid, some invalid)
    # Note: . and .. entries are filtered by checking if line ends with ' .' or ' ..'
    ls_output = """sftp> ls -la /test
total 12
-rw-r--r--  1 user group  1234 Jan 15 10:30 file1.txt
INVALID LINE THAT CANNOT BE PARSED
-rw-r--r--  1 user group  5678 Jan 15 10:30 file2.txt
ANOTHER INVALID LINE
drwxr-xr-x  2 user group  4096 Jan 15 10:30 subdir
"""
    
    with patch.object(conn, '_execute_sftp_command') as mock_exec:
        mock_exec.return_value = (ls_output, '', 0)
        
        # List directory
        entries = conn.list_directory('/test')
        
        # Should have 3 valid entries (file1.txt, file2.txt, subdir)
        # Invalid lines should be skipped
        if len(entries) != 3:
            print(f"❌ FAIL: Expected 3 entries, got {len(entries)}")
            print(f"Entries: {[e['name'] for e in entries]}")
            return
        
        print(f"✓ Parsed {len(entries)} valid entries from mixed output")
        
        # Verify that stat cache entries were created for valid files
        valid_files = ['file1.txt', 'file2.txt', 'subdir']
        for filename in valid_files:
            try:
                cached_stat = cache.get(
                    operation='stat',
                    hostname='testhost',
                    path=f'/test/{filename}'
                )
                if cached_stat is None:
                    print(f"❌ FAIL: No cache entry for {filename}")
                    return
                print(f"✓ Stat cached for {filename}: size={cached_stat['size']}")
            except Exception as e:
                print(f"❌ FAIL: Error getting cached stat for {filename}: {e}")
                return
        
        # Verify cache stats
        cache_stats = cache.get_stats()
        stat_count = cache_stats['operation_counts'].get('stat', 0)
        
        if stat_count != 3:
            print(f"❌ FAIL: Expected 3 stat cache entries, got {stat_count}")
            return
        
        print(f"✓ Created {stat_count} stat cache entries for valid files")
    
    print("✓ Test 2 PASSED")
    return


def test_cached_errors_are_reraised():
    """
    Verify that cached errors are re-raised correctly.
    
    Requirements: 6.4
    """
    print("\n=== Test 3: Cached errors are re-raised correctly ===")
    
    # Create connection with mock cache
    cache = SSHCache()
    conn = SSHConnection('testhost', {'HostName': 'test.example.com'})
    conn._cache = cache
    conn._connected = True
    
    # First call: stat() fails with permission denied
    with patch.object(conn, '_execute_sftp_command') as mock_exec:
        mock_exec.return_value = ('', 'Permission denied', 1)
        
        try:
            conn.stat('/forbidden/file.txt')
            print("❌ FAIL: Expected SSHPermissionDeniedError to be raised")
            return
        except SSHPermissionDeniedError as e:
            print(f"✓ First call raised SSHPermissionDeniedError: {e}")
    
    # Second call: should get cached error without network call
    with patch.object(conn, '_execute_sftp_command') as mock_exec:
        # This should NOT be called because error is cached
        mock_exec.side_effect = Exception("Should not be called - error is cached")
        
        try:
            conn.stat('/forbidden/file.txt')
            print("❌ FAIL: Expected cached SSHPermissionDeniedError to be raised")
            return
        except SSHPermissionDeniedError as e:
            print(f"✓ Second call raised cached SSHPermissionDeniedError: {e}")
        
        # Verify that _execute_sftp_command was NOT called
        if mock_exec.called:
            print("❌ FAIL: Network call was made despite cached error")
            return
        
        print("✓ No network call made (error was cached)")
    
    print("✓ Test 3 PASSED")
    return


def test_list_directory_success_caches_stats():
    """
    Verify that successful list_directory() caches individual stats.
    
    This is a positive test to ensure the optimization is working.
    """
    print("\n=== Test 4: Successful list_directory() caches individual stats ===")
    
    # Create connection with mock cache
    cache = SSHCache()
    conn = SSHConnection('testhost', {'HostName': 'test.example.com'})
    conn._cache = cache
    conn._connected = True
    
    # Mock _execute_sftp_command to return valid directory listing
    # Note: . and .. entries are filtered by checking if line ends with ' .' or ' ..'
    ls_output = """sftp> ls -la /home/user
total 12
-rw-r--r--  1 user group  1234 Jan 15 10:30 file1.txt
-rw-r--r--  1 user group  5678 Jan 15 10:30 file2.txt
drwxr-xr-x  2 user group  4096 Jan 15 10:30 subdir
"""
    
    with patch.object(conn, '_execute_sftp_command') as mock_exec:
        mock_exec.return_value = (ls_output, '', 0)
        
        # List directory
        entries = conn.list_directory('/home/user')
        
        print(f"✓ list_directory() returned {len(entries)} entries")
        
        # Verify that stat cache entries were created
        for entry in entries:
            filename = entry['name']
            try:
                cached_stat = cache.get(
                    operation='stat',
                    hostname='testhost',
                    path=f'/home/user/{filename}'
                )
                if cached_stat is None:
                    print(f"❌ FAIL: No cache entry for {filename}")
                    return
                print(f"✓ Stat cached for {filename}")
            except Exception as e:
                print(f"❌ FAIL: Error getting cached stat for {filename}: {e}")
                return
    
    print("✓ Test 4 PASSED")
    return


def main():
    """Run all verification tests."""
    print("=" * 70)
    print("SSH Error Handling Verification")
    print("=" * 70)
    
    tests = [
        test_list_directory_error_no_stat_cache,
        test_partial_parse_failures_cache_successful,
        test_cached_errors_are_reraised,
        test_list_directory_success_caches_stats,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("\n✓ All error handling tests PASSED")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
