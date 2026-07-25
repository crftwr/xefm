#!/usr/bin/env python3
"""
Tests for SSH Control Socket Path

Verifies that SSH control sockets are created in the user's home directory
instead of /tmp, which fixes issues with DMG-packaged apps.
"""

import unittest
import sys
import os
from pathlib import Path
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xefm.ssh_connection import SSHConnection


class TestSSHSocketPath(unittest.TestCase):
    """Test SSH control socket path configuration"""
    
    def test_socket_path_uses_home_directory(self):
        """Test that control socket path uses home directory, not /tmp"""
        # Create SSH connection instance with minimal config
        config = {'HostName': 'test-host'}
        conn = SSHConnection('test-host', config)
        
        # Verify control path is set
        self.assertIsNotNone(conn._control_path)
        
        # Verify it's not in /tmp
        self.assertNotIn('/tmp', conn._control_path)
        self.assertNotIn(tempfile.gettempdir(), conn._control_path)
        
        # Verify it's in home directory
        home_dir = str(Path.home())
        self.assertIn(home_dir, conn._control_path)
        
        # Verify it's in .xefm/ssh_sockets
        self.assertIn('.xefm', conn._control_path)
        self.assertIn('ssh_sockets', conn._control_path)
    
    def test_socket_directory_created(self):
        """Test that socket directory is created on initialization"""
        # Create SSH connection instance with minimal config
        config = {'HostName': 'test-host'}
        conn = SSHConnection('test-host', config)
        
        # Extract directory from control path
        socket_dir = Path(conn._control_path).parent
        
        # Verify directory exists
        self.assertTrue(socket_dir.exists())
        self.assertTrue(socket_dir.is_dir())
        
        # Verify it's the expected directory
        expected_dir = Path.home() / '.xefm' / 'ssh_sockets'
        self.assertEqual(socket_dir, expected_dir)
    
    def test_socket_path_format(self):
        """Test that socket path has correct format"""
        # Create SSH connection instance with minimal config
        config = {'HostName': 'test-host'}
        conn = SSHConnection('test-host', config)
        
        # Verify path format: ~/.xefm/ssh_sockets/xefm-ssh-{hash}-{pid}
        socket_path = Path(conn._control_path)
        
        # Check filename starts with xefm-ssh-
        self.assertTrue(socket_path.name.startswith('xefm-ssh-'))
        
        # Check format: xefm-ssh-{hash}-{pid}
        parts = socket_path.name.split('-')
        self.assertEqual(len(parts), 4)  # ['xefm', 'ssh', '{hash}', '{pid}']
        self.assertEqual(parts[0], 'xefm')
        self.assertEqual(parts[1], 'ssh')
        
        # Check hash is 8 characters (MD5 truncated)
        hash_part = parts[2]
        self.assertEqual(len(hash_part), 8)
        
        # Check hash is hexadecimal
        try:
            int(hash_part, 16)
        except ValueError:
            self.fail(f"Hash part '{hash_part}' is not hexadecimal")
        
        # Check PID is numeric
        pid_part = parts[3]
        try:
            int(pid_part)
        except ValueError:
            self.fail(f"PID part '{pid_part}' is not numeric")
    
    def test_different_hosts_different_paths(self):
        """Test that different hostnames get different socket paths"""
        config1 = {'HostName': 'host1'}
        config2 = {'HostName': 'host2'}
        conn1 = SSHConnection('host1', config1)
        conn2 = SSHConnection('host2', config2)
        
        # Verify paths are different
        self.assertNotEqual(conn1._control_path, conn2._control_path)
        
        # But both in same directory
        self.assertEqual(
            Path(conn1._control_path).parent,
            Path(conn2._control_path).parent
        )
    
    def test_same_host_different_path_per_process(self):
        """Test that same hostname gets different socket path per process (due to PID)"""
        config = {'HostName': 'test-host'}
        conn1 = SSHConnection('test-host', config)
        conn2 = SSHConnection('test-host', config)
        
        # Since both are created in the same process, they should have the same path
        self.assertEqual(conn1._control_path, conn2._control_path)
        
        # Verify PID is in the path
        self.assertIn(str(os.getpid()), conn1._control_path)
    
    def test_socket_path_length_reasonable(self):
        """Test that socket path length is reasonable"""
        # Create connection with long hostname
        long_hostname = 'very-long-hostname-that-could-cause-path-issues.example.com'
        config = {'HostName': long_hostname}
        conn = SSHConnection(long_hostname, config)
        
        # Verify path length is reasonable (< 104 chars is safe for Unix sockets)
        self.assertLess(len(conn._control_path), 104)
        
        # Verify hash keeps it short
        # Format: xefm-ssh-{8-char-hash}-{pid}
        socket_name = Path(conn._control_path).name
        # PID can be up to 7 digits, so max length is: 8 + 8 + 7 + 2 = 25
        self.assertLess(len(socket_name), 30)


if __name__ == '__main__':
    unittest.main()
