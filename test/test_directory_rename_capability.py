"""
Test directory rename capability functionality.

This test verifies that the new supports_directory_rename() method
works correctly for different path implementations.

Run with: python -m pytest test/test_directory_rename_capability.py -v
"""

import unittest
from unittest.mock import Mock

from xefm.path import Path, LocalPathImpl
from xefm.s3 import S3PathImpl


class TestDirectoryRenameCapability(unittest.TestCase):
    """Test directory rename capability method"""
    
    def test_local_path_supports_directory_rename(self):
        """Test that local paths support directory renaming"""
        local_path = Path('/tmp/test-directory')
        self.assertTrue(local_path.supports_directory_rename())
        
        # Test the implementation directly too
        local_impl = LocalPathImpl('/tmp/test-directory')
        self.assertTrue(local_impl.supports_directory_rename())
    
    def test_s3_path_does_not_support_directory_rename(self):
        """Test that S3 paths do not support directory renaming"""
        s3_path = Path('s3://test-bucket/test-directory/')
        self.assertFalse(s3_path.supports_directory_rename())
        
        # Test the implementation directly too
        s3_impl = S3PathImpl('s3://test-bucket/test-directory/')
        s3_impl._s3_client = Mock()
        self.assertFalse(s3_impl.supports_directory_rename())
    
    def test_capability_method_exists_on_all_implementations(self):
        """Test that the capability method exists on all path implementations"""
        # Test local implementation
        local_impl = LocalPathImpl('/tmp/test')
        self.assertTrue(hasattr(local_impl, 'supports_directory_rename'))
        self.assertTrue(callable(getattr(local_impl, 'supports_directory_rename')))
        
        # Test S3 implementation
        s3_impl = S3PathImpl('s3://bucket/key')
        s3_impl._s3_client = Mock()
        self.assertTrue(hasattr(s3_impl, 'supports_directory_rename'))
        self.assertTrue(callable(getattr(s3_impl, 'supports_directory_rename')))
        
        # Test Path facade
        path = Path('/tmp/test')
        self.assertTrue(hasattr(path, 'supports_directory_rename'))
        self.assertTrue(callable(getattr(path, 'supports_directory_rename')))
    
    def test_capability_method_returns_boolean(self):
        """Test that the capability method returns boolean values"""
        # Local path should return True
        local_path = Path('/tmp/test')
        result = local_path.supports_directory_rename()
        self.assertIsInstance(result, bool)
        self.assertTrue(result)
        
        # S3 path should return False
        s3_path = Path('s3://bucket/key')
        result = s3_path.supports_directory_rename()
        self.assertIsInstance(result, bool)
        self.assertFalse(result)


def run_test():
    """Run the test"""
    unittest.main(verbosity=2)
