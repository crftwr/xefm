"""
Test S3 rmdir emptiness check against directory-marker objects.

A directory created through XeFM's mkdir() (or the AWS console's "Create
folder") is backed by a zero-byte marker object whose key is the directory
prefix itself (e.g. "tmp/123/"). iterdir() hides that marker, so the pane
shows the directory as empty — but rmdir()'s emptiness check used to count
it and always fail with "Directory not empty". These tests pin the fixed
behavior: the marker alone doesn't count as content, while any real object
(including a nested empty subdirectory's marker) still does.

Run with: python -m pytest test/test_s3_rmdir_empty_check.py -v
"""

import unittest

from xefm.path import Path


class FakeS3Client:
    """Minimal stand-in for boto3's S3 client, emulating real list_objects_v2
    semantics over an in-memory key set: Prefix filters, StartAfter is
    exclusive ("starts listing after this specified key"), MaxKeys truncates,
    and KeyCount reflects the returned page. delete_object on a missing key
    succeeds silently, as on real S3."""

    def __init__(self, keys):
        self.keys = sorted(keys)
        self.deleted = []

    def list_objects_v2(self, Bucket, Prefix='', StartAfter='', MaxKeys=1000, **kwargs):
        matches = [k for k in self.keys if k.startswith(Prefix) and k > StartAfter]
        matches = matches[:MaxKeys]
        return {
            'KeyCount': len(matches),
            'Contents': [{'Key': k} for k in matches],
        }

    def delete_object(self, Bucket, Key):
        if Key in self.keys:
            self.keys.remove(Key)
        self.deleted.append(Key)
        return {}


class TestS3RmdirEmptyCheck(unittest.TestCase):
    """rmdir() emptiness semantics around directory-marker objects"""

    def _make_dir_path(self, keys):
        """Path for s3://test-bucket/tmp/123/ over a fake bucket holding keys"""
        path = Path('s3://test-bucket/tmp/123/')
        client = FakeS3Client(keys)
        path._impl._s3_client = client
        return path, client

    def test_rmdir_deletes_directory_holding_only_its_own_marker(self):
        path, client = self._make_dir_path(['tmp/123/'])

        path.rmdir()

        self.assertIn('tmp/123/', client.deleted)
        self.assertEqual(client.keys, [])

    def test_rmdir_succeeds_without_marker(self):
        # Implicit directory whose children were already deleted: no object
        # remains at all, and rmdir() is still expected to succeed.
        path, client = self._make_dir_path([])

        path.rmdir()

        self.assertEqual(client.keys, [])

    def test_rmdir_raises_when_directory_holds_a_file(self):
        path, client = self._make_dir_path(['tmp/123/', 'tmp/123/file.txt'])

        with self.assertRaises(OSError) as ctx:
            path.rmdir()

        self.assertIn('Directory not empty', str(ctx.exception))
        self.assertEqual(client.deleted, [])

    def test_rmdir_raises_when_directory_holds_an_empty_subdirectory(self):
        # A nested marker is real content: the subdirectory must be removed
        # first, exactly as with a local filesystem rmdir.
        path, client = self._make_dir_path(['tmp/123/', 'tmp/123/sub/'])

        with self.assertRaises(OSError) as ctx:
            path.rmdir()

        self.assertIn('Directory not empty', str(ctx.exception))
        self.assertEqual(client.deleted, [])

    def test_rmdir_does_not_count_sibling_with_same_prefix_string(self):
        # "tmp/123x" shares the string prefix "tmp/123" but lives outside the
        # directory; the check must scope to "tmp/123/".
        path, client = self._make_dir_path(['tmp/123/', 'tmp/123x'])

        path.rmdir()

        self.assertIn('tmp/123/', client.deleted)
        self.assertEqual(client.keys, ['tmp/123x'])


if __name__ == '__main__':
    unittest.main()
