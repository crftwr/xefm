"""
Test byte-level progress reporting for S3 copies (GitHub issue #131).

S3 transfers used to be a single get_object/put_object call, so the progress
bar sat at 0% and then jumped to 100%. Copies now go through boto3's managed
transfer, which reports bytes as they move.

Run with: python -m pytest test/test_s3_copy_progress.py -v
"""

import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from xefm.path import Path
from xefm.s3 import clear_s3_cache


class TestS3CopyProgress(unittest.TestCase):
    """Byte-level progress for local <-> S3 and S3 -> S3 copies"""

    def setUp(self):
        # The S3 cache is a process-wide singleton; a stale head_object from a
        # sibling test would otherwise decide this test's file size
        clear_s3_cache()
        self.temp_dir = tempfile.mkdtemp()
        self.content = b"x" * 4096
        self.local_file = Path(self.temp_dir) / "payload.bin"
        self.local_file.write_bytes(self.content)

        self.client = Mock()
        self.client.list_objects_v2.return_value = {'KeyCount': 0}
        self.client.head_object.return_value = {'ContentLength': len(self.content)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        clear_s3_cache()

    def _record_progress(self):
        """Return (updates list, callback) matching ProgressManager's signature"""
        updates = []

        def callback(bytes_copied, bytes_total):
            updates.append((bytes_copied, bytes_total))

        return updates, callback

    @patch('xefm.s3.boto3')
    def test_upload_reports_incremental_progress(self, mock_boto3):
        """Uploading a local file drives the bar as chunks are sent"""
        mock_boto3.client.return_value = self.client

        def fake_upload(Fileobj, Bucket, Key, Callback=None, **kwargs):
            Fileobj.read()
            for _ in range(4):
                Callback(1024)

        self.client.upload_fileobj.side_effect = fake_upload
        updates, callback = self._record_progress()

        self.local_file.copy_to(Path("s3://bucket/payload.bin"), overwrite=True,
                                progress_callback=callback)

        # boto3 hands over per-chunk deltas; the bar wants running totals
        self.assertEqual(updates, [(0, 4096), (1024, 4096), (2048, 4096),
                                   (3072, 4096), (4096, 4096)])

    @patch('xefm.s3.boto3')
    def test_download_reports_incremental_progress(self, mock_boto3):
        """Downloading to a local file drives the bar as chunks arrive"""
        mock_boto3.client.return_value = self.client

        def fake_download(Bucket, Key, Fileobj, Callback=None, **kwargs):
            for offset in range(0, len(self.content), 1024):
                Fileobj.write(self.content[offset:offset + 1024])
                Callback(1024)

        self.client.download_fileobj.side_effect = fake_download
        updates, callback = self._record_progress()

        dest = Path(self.temp_dir) / "downloaded.bin"
        Path("s3://bucket/payload.bin").copy_to(dest, overwrite=True,
                                                progress_callback=callback)

        self.assertEqual(updates, [(0, 4096), (1024, 4096), (2048, 4096),
                                   (3072, 4096), (4096, 4096)])
        self.assertEqual(dest.read_bytes(), self.content)

    @patch('xefm.s3.boto3')
    def test_download_streams_without_buffering_whole_object(self, mock_boto3):
        """The object goes straight to disk instead of through read_bytes()"""
        mock_boto3.client.return_value = self.client

        def fake_download(Bucket, Key, Fileobj, Callback=None, **kwargs):
            Fileobj.write(self.content)

        self.client.download_fileobj.side_effect = fake_download

        dest = Path(self.temp_dir) / "downloaded.bin"
        Path("s3://bucket/payload.bin").copy_to(dest, overwrite=True)

        self.client.get_object.assert_not_called()
        self.assertEqual(dest.read_bytes(), self.content)

    @patch('xefm.s3.boto3')
    def test_failed_download_leaves_no_truncated_file(self, mock_boto3):
        """A download that dies part way through does not leave a stub behind"""
        mock_boto3.client.return_value = self.client

        def fake_download(Bucket, Key, Fileobj, Callback=None, **kwargs):
            Fileobj.write(self.content[:1024])
            raise OSError("connection reset")

        self.client.download_fileobj.side_effect = fake_download

        dest = Path(self.temp_dir) / "downloaded.bin"
        with self.assertRaises(OSError):
            Path("s3://bucket/payload.bin").copy_to(dest, overwrite=True)

        self.assertFalse(dest.exists(),
                         "partial download should not be left on disk")

    @patch('xefm.s3.boto3')
    def test_s3_to_s3_copies_server_side(self, mock_boto3):
        """An S3 -> S3 copy never pulls the bytes through the client"""
        mock_boto3.client.return_value = self.client

        def fake_copy(CopySource, Bucket, Key, Callback=None, **kwargs):
            Callback(len(self.content))

        self.client.copy.side_effect = fake_copy
        updates, callback = self._record_progress()

        source = Path("s3://bucket/payload.bin")
        source.copy_to(Path("s3://other-bucket/payload.bin"), overwrite=True,
                       progress_callback=callback)

        self.client.copy.assert_called_once()
        call_args = self.client.copy.call_args
        self.assertEqual(call_args[1]['CopySource'],
                         {'Bucket': 'bucket', 'Key': 'payload.bin'})
        self.assertEqual(call_args[1]['Bucket'], 'other-bucket')
        self.assertEqual(call_args[1]['Key'], 'payload.bin')

        self.client.get_object.assert_not_called()
        self.client.put_object.assert_not_called()
        self.assertEqual(updates, [(0, 4096), (4096, 4096)])

    @patch('xefm.s3.boto3')
    def test_multipart_progress_totals_are_not_lost(self, mock_boto3):
        """Concurrent multipart callbacks still add up to the full size"""
        mock_boto3.client.return_value = self.client

        def fake_upload(Fileobj, Bucket, Key, Callback=None, **kwargs):
            Fileobj.read()
            # A multipart upload calls back from each of its transfer threads
            threads = [threading.Thread(target=lambda: [Callback(1) for _ in range(256)])
                       for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.client.upload_fileobj.side_effect = fake_upload
        updates, callback = self._record_progress()

        self.local_file.copy_to(Path("s3://bucket/payload.bin"), overwrite=True,
                                progress_callback=callback)

        self.assertEqual(updates[-1], (1024, 4096))
        self.assertEqual(len(updates), 1025)  # the initial (0, total) plus each tick


if __name__ == '__main__':
    unittest.main()
