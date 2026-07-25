#!/usr/bin/env python3
"""
Test S3 Multiple Reads

Tests that S3 files can be read multiple times without losing content.
This verifies the fix for the stream consumption issue in S3PathImpl.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

# Import Path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xefm.path import Path


class MockS3Response:
    """Mock S3 response with a streaming body"""
    def __init__(self, content: bytes):
        self._content = content
    
    def read(self):
        """Simulate reading from the Body stream"""
        return self._content


class TestS3MultipleReads(unittest.TestCase):
    """Test S3 files can be read multiple times"""
    
    def setUp(self):
        """Clear S3 cache before each test"""
        from xefm.s3 import get_s3_cache
        cache = get_s3_cache()
        cache.clear()
    
    @patch('xefm.s3.boto3')
    def test_read_bytes_multiple_times(self, mock_boto3):
        """Test that read_bytes() can be called multiple times"""
        # Create mock S3 client
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # Test content
        test_content = b"Line 1\nLine 2\nLine 3\n"
        
        # Mock get_object to return a dict with Body stream
        # This will be called only once due to caching
        mock_body = MockS3Response(test_content)
        mock_client.get_object.return_value = {
            'Body': mock_body,
            'ContentLength': len(test_content),
            'LastModified': datetime.now()
        }
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/file.txt')
        
        # Read the file multiple times
        content1 = s3_path.read_bytes()
        content2 = s3_path.read_bytes()
        content3 = s3_path.read_bytes()
        
        # Verify all reads return the same content
        self.assertEqual(content1, test_content)
        self.assertEqual(content2, test_content)
        self.assertEqual(content3, test_content)
        
        # Verify get_object was called only once (due to caching)
        self.assertEqual(mock_client.get_object.call_count, 1)
    
    @patch('xefm.s3.boto3')
    def test_read_text_multiple_times(self, mock_boto3):
        """Test that read_text() can be called multiple times"""
        # Create mock S3 client
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # Test content
        test_content = b"Hello World\nLine 2\n"
        
        # Mock get_object
        mock_body = MockS3Response(test_content)
        mock_client.get_object.return_value = {
            'Body': mock_body,
            'ContentLength': len(test_content),
            'LastModified': datetime.now()
        }
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/file.txt')
        
        # Read the file multiple times
        content1 = s3_path.read_text()
        content2 = s3_path.read_text()
        content3 = s3_path.read_text()
        
        # Verify all reads return the same content
        expected = test_content.decode('utf-8')
        self.assertEqual(content1, expected)
        self.assertEqual(content2, expected)
        self.assertEqual(content3, expected)
        
        # Verify get_object was called only once (due to caching)
        self.assertEqual(mock_client.get_object.call_count, 1)
    
    @patch('xefm.s3.boto3')
    def test_open_multiple_times(self, mock_boto3):
        """Test that open() can be called multiple times"""
        # Create mock S3 client
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # Test content
        test_content = b"Line 1\nLine 2\n"
        
        # Mock get_object
        mock_body = MockS3Response(test_content)
        mock_client.get_object.return_value = {
            'Body': mock_body,
            'ContentLength': len(test_content),
            'LastModified': datetime.now()
        }
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/file.txt')
        
        # Open and read the file multiple times
        with s3_path.open('r') as f:
            content1 = f.read()
        
        with s3_path.open('r') as f:
            content2 = f.read()
        
        with s3_path.open('rb') as f:
            content3 = f.read()
        
        # Verify all reads return the same content
        expected_text = test_content.decode('utf-8')
        self.assertEqual(content1, expected_text)
        self.assertEqual(content2, expected_text)
        self.assertEqual(content3, test_content)
        
        # Verify get_object was called only once (due to caching)
        self.assertEqual(mock_client.get_object.call_count, 1)
    
    @patch('xefm.s3.boto3')
    def test_mixed_read_methods(self, mock_boto3):
        """Test mixing read_bytes(), read_text(), and open()"""
        # Create mock S3 client
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # Test content
        test_content = b"Mixed read test\n"
        
        # Mock get_object
        mock_body = MockS3Response(test_content)
        mock_client.get_object.return_value = {
            'Body': mock_body,
            'ContentLength': len(test_content),
            'LastModified': datetime.now()
        }
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/file.txt')
        
        # Use different read methods
        bytes_content = s3_path.read_bytes()
        text_content = s3_path.read_text()
        
        with s3_path.open('r') as f:
            open_content = f.read()
        
        # Verify all methods return correct content
        self.assertEqual(bytes_content, test_content)
        self.assertEqual(text_content, test_content.decode('utf-8'))
        self.assertEqual(open_content, test_content.decode('utf-8'))
        
        # Verify get_object was called only once (due to caching)
        self.assertEqual(mock_client.get_object.call_count, 1)
    
    @patch('xefm.s3.boto3')
    def test_read_after_cache_invalidation(self, mock_boto3):
        """Test that reads work correctly after cache invalidation"""
        # Create mock S3 client
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # Test content
        test_content1 = b"Original content\n"
        test_content2 = b"Updated content\n"
        
        # Mock get_object to return different content on each call
        mock_client.get_object.side_effect = [
            {
                'Body': MockS3Response(test_content1),
                'ContentLength': len(test_content1),
                'LastModified': datetime.now()
            },
            {
                'Body': MockS3Response(test_content2),
                'ContentLength': len(test_content2),
                'LastModified': datetime.now()
            }
        ]
        
        # Create S3 path
        s3_path = Path('s3://test-bucket/file.txt')
        
        # Read original content
        content1 = s3_path.read_bytes()
        self.assertEqual(content1, test_content1)
        
        # Write new content (this should invalidate cache)
        s3_path.write_bytes(test_content2)
        
        # Read again - should get new content
        content2 = s3_path.read_bytes()
        self.assertEqual(content2, test_content2)
        
        # Verify get_object was called twice (once before write, once after)
        self.assertEqual(mock_client.get_object.call_count, 2)


if __name__ == '__main__':
    unittest.main()
