"""
Test S3 file editing capability indicator

Run with: python -m pytest test/test_s3_file_editing_restriction.py -v
"""

import unittest
from unittest.mock import Mock, patch

from xefm.s3 import S3PathImpl


class TestS3FileEditingCapability(unittest.TestCase):
    """Test that S3 file editing capability is properly indicated"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Mock boto3 to avoid AWS dependencies
        self.mock_boto3 = Mock()
        self.mock_client = Mock()
        self.mock_boto3.client.return_value = self.mock_client
        
        # Create S3PathImpl instance
        with patch('xefm.s3.boto3', self.mock_boto3):
            with patch('xefm.s3.HAS_BOTO3', True):
                self.s3_path = S3PathImpl('s3://test-bucket/test-file.txt')
    
    def test_supports_file_editing_returns_false(self):
        """Test that supports_file_editing returns False for S3"""
        self.assertFalse(self.s3_path.supports_file_editing())
    
    def test_open_write_mode_works(self):
        """Test that opening S3 file in write mode works (returns S3WriteFile)"""
        # This should not raise an error - it should return S3WriteFile
        try:
            file_obj = self.s3_path.open('w')
            self.assertIsNotNone(file_obj)
            # Should be S3WriteFile instance
            from xefm.s3 import S3WriteFile
            self.assertIsInstance(file_obj, S3WriteFile)
        except Exception as e:
            self.fail(f"Write mode should work: {e}")
    
    def test_open_append_mode_works(self):
        """Test that opening S3 file in append mode works (returns S3WriteFile)"""
        # This should not raise an error - it should return S3WriteFile
        try:
            file_obj = self.s3_path.open('a')
            self.assertIsNotNone(file_obj)
            # Should be S3WriteFile instance
            from xefm.s3 import S3WriteFile
            self.assertIsInstance(file_obj, S3WriteFile)
        except Exception as e:
            self.fail(f"Append mode should work: {e}")
    
    def test_open_read_mode_works(self):
        """Test that opening S3 file in read mode works"""
        # Mock successful read response
        mock_response = {
            'Body': Mock()
        }
        mock_response['Body'].read.return_value = b'test content'
        self.mock_client.get_object.return_value = mock_response
        
        # Set the mocked client on the S3 path
        self.s3_path._s3_client = self.mock_client
        
        # This should not raise an error
        try:
            file_obj = self.s3_path.open('r')
            self.assertIsNotNone(file_obj)
        except Exception as e:
            self.fail(f"Read mode should work: {e}")
    
    def test_write_text_works(self):
        """Test that write_text works for S3"""
        # Mock successful put_object
        self.mock_client.put_object.return_value = {}
        
        # Set the mocked client on the S3 path
        self.s3_path._s3_client = self.mock_client
        
        try:
            result = self.s3_path.write_text("test content")
            self.assertEqual(result, 12)  # Length of "test content"
            # Verify put_object was called
            self.mock_client.put_object.assert_called_once()
        except Exception as e:
            self.fail(f"write_text should work: {e}")
    
    def test_write_bytes_works(self):
        """Test that write_bytes works for S3"""
        # Mock successful put_object
        self.mock_client.put_object.return_value = {}
        
        # Set the mocked client on the S3 path
        self.s3_path._s3_client = self.mock_client
        
        try:
            result = self.s3_path.write_bytes(b"test content")
            self.assertEqual(result, 12)  # Length of b"test content"
            # Verify put_object was called
            self.mock_client.put_object.assert_called_once()
        except Exception as e:
            self.fail(f"write_bytes should work: {e}")
