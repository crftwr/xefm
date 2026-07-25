#!/usr/bin/env python3
"""
Test for external programs PATH fix for macOS app bundle
"""

import unittest
import sys
from xefm.external_programs import ensure_common_paths_in_env


class TestExternalProgramsPathFix(unittest.TestCase):
    """Test PATH environment variable fix for macOS app bundle"""
    
    def test_ensure_common_paths_adds_missing_paths(self):
        """Test that common paths are added when missing"""
        env = {'PATH': '/usr/bin'}
        ensure_common_paths_in_env(env)
        
        # Check that common paths were added
        path_components = env['PATH'].split(':')
        self.assertIn('/usr/local/bin', path_components)
        self.assertIn('/opt/homebrew/bin', path_components)
        self.assertIn('/usr/bin', path_components)
        self.assertIn('/bin', path_components)
    
    def test_ensure_common_paths_preserves_existing_paths(self):
        """Test that existing paths are preserved"""
        env = {'PATH': '/custom/path:/usr/bin'}
        ensure_common_paths_in_env(env)
        
        # Check that custom path is still present
        path_components = env['PATH'].split(':')
        self.assertIn('/custom/path', path_components)
        self.assertIn('/usr/bin', path_components)
    
    def test_ensure_common_paths_no_duplicates(self):
        """Test that paths are not duplicated"""
        env = {'PATH': '/usr/local/bin:/usr/bin'}
        ensure_common_paths_in_env(env)
        
        # Count occurrences of /usr/local/bin
        path_components = env['PATH'].split(':')
        count = path_components.count('/usr/local/bin')
        self.assertEqual(count, 1, "Path should not be duplicated")
    
    def test_ensure_common_paths_empty_path(self):
        """Test handling of empty PATH"""
        env = {'PATH': ''}
        ensure_common_paths_in_env(env)
        
        # Check that common paths were added
        path_components = env['PATH'].split(':')
        self.assertIn('/usr/local/bin', path_components)
        self.assertIn('/opt/homebrew/bin', path_components)
    
    def test_ensure_common_paths_missing_path_key(self):
        """Test handling of missing PATH key"""
        env = {}
        ensure_common_paths_in_env(env)
        
        # Check that PATH was created with common paths
        self.assertIn('PATH', env)
        path_components = env['PATH'].split(':')
        self.assertIn('/usr/local/bin', path_components)
    
    def test_ensure_common_paths_only_on_darwin(self):
        """Test that function only modifies PATH on macOS"""
        if sys.platform != 'darwin':
            env = {'PATH': '/usr/bin'}
            original_path = env['PATH']
            ensure_common_paths_in_env(env)
            
            # On non-macOS platforms, PATH should not be modified
            self.assertEqual(env['PATH'], original_path)


if __name__ == '__main__':
    unittest.main()
