"""
Test S3 Copy Fix - Verify that copying from local filesystem to S3 works correctly

Run with: python -m pytest test/test_s3_copy_operations.py -v
"""

import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock

from xefm.path import Path


class TestS3CopyFix(unittest.TestCase):
    """Test cases for S3 copy functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.temp_dir) / "test_file.txt"
        self.test_content = "This is a test file for S3 copy operations."
        
        # Create test file
        self.test_file.write_text(self.test_content)
    
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @patch('xefm.s3.boto3')
    def test_local_to_s3_copy(self, mock_boto3):
        """Test copying a local file to S3"""
        # Mock S3 client - the upload drains the caller's file object, so the
        # bytes have to be captured while the call is in flight
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {'KeyCount': 0}
        uploaded = {}

        def fake_upload(Fileobj, Bucket, Key, Callback=None, **kwargs):
            uploaded['content'] = Fileobj.read()

        mock_client.upload_fileobj.side_effect = fake_upload
        mock_boto3.client.return_value = mock_client

        # Create S3 destination path
        s3_dest = Path("s3://test-bucket/test-file.txt")

        # Perform copy operation
        try:
            result = self.test_file.copy_to(s3_dest, overwrite=True)
            self.assertTrue(result, "Copy operation should return True on success")

            # Verify the streaming upload was used (not a single put_object)
            mock_client.upload_fileobj.assert_called_once()
            mock_client.put_object.assert_not_called()
            call_args = mock_client.upload_fileobj.call_args

            # Check that the correct bucket and key were used
            self.assertEqual(call_args[1]['Bucket'], 'test-bucket')
            self.assertEqual(call_args[1]['Key'], 'test-file.txt')

            # Check that the content was uploaded correctly
            self.assertEqual(uploaded['content'], self.test_content.encode('utf-8'))

        except ImportError:
            self.skipTest("boto3 not available for S3 testing")

    @patch('xefm.s3.boto3')
    def test_s3_to_local_copy(self, mock_boto3):
        """Test copying an S3 file to local filesystem"""
        # Mock S3 client - the download streams into the caller's file object
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {'KeyCount': 0}
        mock_client.head_object.return_value = {
            'ContentLength': len(self.test_content),
        }

        def fake_download(Bucket, Key, Fileobj, Callback=None, **kwargs):
            Fileobj.write(self.test_content.encode('utf-8'))

        mock_client.download_fileobj.side_effect = fake_download
        mock_boto3.client.return_value = mock_client

        # Create S3 source path
        s3_source = Path("s3://test-bucket/source-file.txt")
        local_dest = Path(self.temp_dir) / "copied_file.txt"

        try:
            # Perform copy operation
            result = s3_source.copy_to(local_dest, overwrite=True)
            self.assertTrue(result, "Copy operation should return True on success")

            # Verify file was created locally
            self.assertTrue(local_dest.exists(), "Destination file should exist")

            # Verify content is correct
            copied_content = local_dest.read_text()
            self.assertEqual(copied_content, self.test_content)

            # Verify the streaming download was used (not a single get_object)
            mock_client.get_object.assert_not_called()
            call_args = mock_client.download_fileobj.call_args
            self.assertEqual(call_args[1]['Bucket'], 'test-bucket')
            self.assertEqual(call_args[1]['Key'], 'source-file.txt')

        except ImportError:
            self.skipTest("boto3 not available for S3 testing")

    def test_local_to_local_copy(self):
        """Test copying between local paths (should still work)"""
        local_dest = Path(self.temp_dir) / "local_copy.txt"
        
        # Perform copy operation
        result = self.test_file.copy_to(local_dest, overwrite=True)
        self.assertTrue(result, "Copy operation should return True on success")
        
        # Verify file was created
        self.assertTrue(local_dest.exists(), "Destination file should exist")
        
        # Verify content is correct
        copied_content = local_dest.read_text()
        self.assertEqual(copied_content, self.test_content)
    
    def test_copy_nonexistent_file(self):
        """Test copying a file that doesn't exist"""
        nonexistent = Path(self.temp_dir) / "nonexistent.txt"
        dest = Path(self.temp_dir) / "dest.txt"
        
        with self.assertRaises(FileNotFoundError):
            nonexistent.copy_to(dest)
    
    def test_copy_to_existing_file_no_overwrite(self):
        """Test copying to an existing file without overwrite flag"""
        dest = Path(self.temp_dir) / "existing.txt"
        dest.write_text("existing content")
        
        with self.assertRaises(FileExistsError):
            self.test_file.copy_to(dest, overwrite=False)
    
    def test_copy_to_existing_file_with_overwrite(self):
        """Test copying to an existing file with overwrite flag"""
        dest = Path(self.temp_dir) / "existing.txt"
        dest.write_text("existing content")
        
        # Should succeed with overwrite=True
        result = self.test_file.copy_to(dest, overwrite=True)
        self.assertTrue(result)
        
        # Verify content was overwritten
        copied_content = dest.read_text()
        self.assertEqual(copied_content, self.test_content)


class TestS3CopyIntegration(unittest.TestCase):
    """Integration tests for S3 copy functionality"""
    
    @patch('xefm.s3.boto3')
    def test_copy_method_exists(self, mock_boto3):
        """Test that the copy_to method exists and is callable"""
        # Mock boto3 to avoid import errors
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {'KeyCount': 0}
        mock_boto3.client.return_value = mock_client
        
        try:
            local_path = Path("/tmp/test.txt")
            s3_path = Path("s3://bucket/key.txt")
            
            # Verify methods exist
            self.assertTrue(hasattr(local_path, 'copy_to'))
            self.assertTrue(callable(local_path.copy_to))
            self.assertTrue(hasattr(s3_path, 'copy_to'))
            self.assertTrue(callable(s3_path.copy_to))
            
        except ImportError:
            self.skipTest("boto3 not available for S3 testing")
