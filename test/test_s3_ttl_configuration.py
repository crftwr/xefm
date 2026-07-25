"""
Test S3 TTL Configuration

Tests that S3 cache TTL can be configured through the Config class.

Run with: python -m pytest test/test_s3_ttl_configuration.py -v
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
import pytest

try:
    from xefm._config import Config
    from xefm.s3 import get_s3_cache, S3Cache
    S3_AVAILABLE = True
except ImportError as e:
    S3_AVAILABLE = False
    S3_ERROR = str(e)

# Skip all tests in this module if S3 modules are not available
pytestmark = pytest.mark.skipif(
    not S3_AVAILABLE,
    reason="S3 modules not available"
)


class TestS3TTLConfiguration(unittest.TestCase):
    """Test S3 TTL configuration functionality"""
    
    def setUp(self):
        """Set up test environment"""
        # Clear any existing global cache
        import xefm.s3
        xefm.s3._s3_cache = None
    
    def test_default_s3_cache_ttl(self):
        """Test that Config has S3_CACHE_TTL set to 60"""
        self.assertTrue(hasattr(Config, 'S3_CACHE_TTL'))
        self.assertEqual(Config.S3_CACHE_TTL, 60)
    
    def test_s3_cache_uses_default_ttl(self):
        """Test that S3Cache uses the default TTL from configuration"""
        # Mock the config to return a specific TTL
        mock_config = MagicMock()
        mock_config.S3_CACHE_TTL = 120
        
        with patch('xefm.config.get_config', return_value=mock_config):
            # Clear the global cache to force recreation
            import xefm.s3
            xefm.s3._s3_cache = None
            
            cache = get_s3_cache()
            self.assertEqual(cache.default_ttl, 120)
    
    def test_s3_cache_fallback_ttl(self):
        """Test that S3Cache falls back to 60 seconds if config is unavailable"""
        # Mock import error for config
        with patch('xefm.config.get_config', side_effect=ImportError("Config not available")):
            # Clear the global cache to force recreation
            import xefm.s3
            xefm.s3._s3_cache = None
            
            cache = get_s3_cache()
            self.assertEqual(cache.default_ttl, 60)
    
    def test_s3_cache_custom_ttl_in_config(self):
        """Test that custom TTL values in config are respected"""
        # Test different TTL values
        test_ttls = [30, 60, 120, 300, 600]
        
        for ttl in test_ttls:
            with self.subTest(ttl=ttl):
                mock_config = MagicMock()
                mock_config.S3_CACHE_TTL = ttl
                
                with patch('xefm.config.get_config', return_value=mock_config):
                    # Clear the global cache to force recreation
                    import xefm.s3
                    xefm.s3._s3_cache = None
                    
                    cache = get_s3_cache()
                    self.assertEqual(cache.default_ttl, ttl)
    
    def test_s3_cache_missing_config_attribute(self):
        """Test that missing S3_CACHE_TTL attribute falls back to default"""
        # Mock config without S3_CACHE_TTL attribute
        mock_config = MagicMock()
        del mock_config.S3_CACHE_TTL  # Remove the attribute
        
        with patch('xefm.config.get_config', return_value=mock_config):
            # Clear the global cache to force recreation
            import xefm.s3
            xefm.s3._s3_cache = None
            
            cache = get_s3_cache()
            self.assertEqual(cache.default_ttl, 60)
    
    def test_s3_cache_singleton_behavior(self):
        """Test that get_s3_cache returns the same instance"""
        # Clear the global cache
        import xefm.s3
        xefm.s3._s3_cache = None
        
        cache1 = get_s3_cache()
        cache2 = get_s3_cache()
        
        self.assertIs(cache1, cache2)
        self.assertIsInstance(cache1, S3Cache)
