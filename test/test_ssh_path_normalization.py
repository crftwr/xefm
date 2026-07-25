#!/usr/bin/env python3
"""
Test for SSH path normalization fix.

This test verifies that paths with excessive ./ sequences are properly normalized
before being passed to SFTP commands.

Run with: python -m pytest test/test_ssh_path_normalization.py -v
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add the repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xefm.ssh_connection import SSHConnection


class TestSSHPathNormalization(unittest.TestCase):
    """Test SSH path normalization."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.hostname = "test-host"
        self.config = {
            'HostName': 'test.example.com',
            'User': 'testuser',
            'Port': '22'
        }
    
    def test_list_directory_normalizes_path(self):
        """Test that list_directory normalizes paths with excessive ./ sequences."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Mock _execute_sftp_command to capture the command
        executed_commands = []
        
        def mock_execute(commands, timeout=30):
            executed_commands.extend(commands)
            return ('', '', 0)
        
        conn._execute_sftp_command = mock_execute
        
        # Test path with excessive ./ sequences
        problematic_path = '/home/ubuntu/projects/././././././././././././././././././././.'
        
        try:
            conn.list_directory(problematic_path)
        except Exception:
            pass  # We don't care about the result, just the command
        
        # Verify the command uses normalized path
        self.assertEqual(len(executed_commands), 1)
        command = executed_commands[0]
        
        # The normalized path should be /home/ubuntu/projects
        self.assertIn('/home/ubuntu/projects', command)
        # Should NOT contain excessive ./ sequences
        self.assertNotIn('././././.', command)
        
        print(f"✓ Path normalized: {problematic_path} → /home/ubuntu/projects")
    
    def test_stat_normalizes_path(self):
        """Test that stat normalizes paths with excessive ./ sequences."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Mock _execute_sftp_command to capture the command
        executed_commands = []
        
        def mock_execute(commands, timeout=30):
            executed_commands.extend(commands)
            # Return a valid ls -l output
            return ('-rw-r--r--  1 user group  1024 Jan 01 12:00 file.txt\n', '', 0)
        
        conn._execute_sftp_command = mock_execute
        
        # Test path with excessive ./ sequences
        problematic_path = '/home/ubuntu/projects/././././././././file.txt'
        
        try:
            conn.stat(problematic_path)
        except Exception:
            pass  # We don't care about the result, just the command
        
        # Verify the command uses normalized path
        self.assertTrue(len(executed_commands) > 0)
        command = executed_commands[0]
        
        # The normalized path should be /home/ubuntu/projects/file.txt
        self.assertIn('/home/ubuntu/projects/file.txt', command)
        # Should NOT contain excessive ./ sequences
        self.assertNotIn('././././.', command)
        
        print(f"✓ Path normalized: {problematic_path} → /home/ubuntu/projects/file.txt")
    
    def test_normalization_preserves_valid_paths(self):
        """Test that normalization doesn't break valid paths."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Clear cache to ensure commands are executed
        conn._cache._cache.clear()
        
        # Mock _execute_sftp_command
        executed_commands = []
        
        def mock_execute(commands, timeout=30):
            executed_commands.extend(commands)
            return ('', '', 0)
        
        conn._execute_sftp_command = mock_execute
        
        # Test various valid paths
        valid_paths = [
            '/home/ubuntu/projects',
            '/home/ubuntu/projects/file.txt',
            '/home/ubuntu/projects/subdir/file.txt',
            '/',
            '/tmp',
        ]
        
        for path in valid_paths:
            executed_commands.clear()
            try:
                conn.list_directory(path)
            except Exception:
                pass
            
            # Verify the path is preserved
            self.assertEqual(len(executed_commands), 1)
            command = executed_commands[0]
            self.assertIn(path, command)
        
        print(f"✓ Valid paths preserved: {len(valid_paths)} paths tested")
    
    def test_normalization_handles_relative_paths(self):
        """Test that normalization handles relative path components."""
        conn = SSHConnection(self.hostname, self.config)
        conn._connected = True
        
        # Mock _execute_sftp_command
        executed_commands = []
        
        def mock_execute(commands, timeout=30):
            executed_commands.extend(commands)
            return ('', '', 0)
        
        conn._execute_sftp_command = mock_execute
        
        # Test paths with .. and .
        test_cases = [
            ('/home/ubuntu/projects/.', '/home/ubuntu/projects'),
            ('/home/ubuntu/projects/./file.txt', '/home/ubuntu/projects/file.txt'),
            ('/home/ubuntu/projects/../projects', '/home/ubuntu/projects'),
            ('/home/ubuntu/./projects', '/home/ubuntu/projects'),
        ]
        
        for input_path, expected_normalized in test_cases:
            # Clear cache before each test case
            conn._cache._cache.clear()
            executed_commands.clear()
            try:
                conn.list_directory(input_path)
            except Exception:
                pass
            
            # Verify the path is normalized
            self.assertEqual(len(executed_commands), 1)
            command = executed_commands[0]
            self.assertIn(expected_normalized, command)
            print(f"  ✓ {input_path} → {expected_normalized}")
        
        print(f"✓ Relative path components normalized: {len(test_cases)} cases tested")


def run_tests():
    """Run all tests."""
    print("=" * 70)
    print("SSH Path Normalization - Fix Verification")
    print("=" * 70)
    print()
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSSHPathNormalization)
    
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
        print("✓ All tests passed!")
        print()
        print("Fix Summary:")
        print("  • Paths with excessive ./ sequences are normalized")
        print("  • Valid paths are preserved")
        print("  • Relative path components (. and ..) are handled correctly")
        print("  • Both list_directory() and stat() methods are fixed")
        return 0
    else:
        print("✗ Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
