#!/usr/bin/env python3
"""
Test for external programs PATH fix for macOS app bundle
"""

import unittest
import sys
from xefm.external_programs import ensure_common_paths_in_env


#: ``ensure_common_paths_in_env`` exists for one situation — XeFM.app launched
#: from Finder or the Dock, which inherits no shell PATH — and its body is
#: entirely inside ``if sys.platform == 'darwin'``. The assertions below describe
#: that behaviour, so off macOS they were asserting a no-op had done something.
_MACOS_ONLY = unittest.skipUnless(
    sys.platform == 'darwin', "ensure_common_paths_in_env only acts on macOS")


class TestExternalProgramsPathFix(unittest.TestCase):
    """Test PATH environment variable fix for macOS app bundle"""

    @unittest.skipIf(sys.platform == 'darwin', "the macOS behaviour is below")
    def test_ensure_common_paths_leaves_other_platforms_alone(self):
        """Off macOS the environment must come back untouched — including the
        missing-PATH case, where inventing one would be worse than leaving it."""
        env = {'PATH': '/usr/bin'}
        ensure_common_paths_in_env(env)
        self.assertEqual(env, {'PATH': '/usr/bin'})
        empty = {}
        ensure_common_paths_in_env(empty)
        self.assertEqual(empty, {})

    @_MACOS_ONLY
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
    
    @_MACOS_ONLY
    def test_ensure_common_paths_empty_path(self):
        """Test handling of empty PATH"""
        env = {'PATH': ''}
        ensure_common_paths_in_env(env)
        
        # Check that common paths were added
        path_components = env['PATH'].split(':')
        self.assertIn('/usr/local/bin', path_components)
        self.assertIn('/opt/homebrew/bin', path_components)
    
    @_MACOS_ONLY
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
