"""
S3: a newly created directory must show up on the next listing (#262).

``iterdir()`` caches the aggregated directory listing under the operation name
``list_objects_v2_complete``, but ``S3Cache.invalidate_key`` used to evict
listings only for ``list_objects_v2`` / ``head_bucket`` — so a ``mkdir`` (or any
other write) left the parent pane's cached listing stale for the full cache TTL
(60s by default), and the new directory "didn't show up".

``_invalidate_cache_for_write`` had a second hole: for a directory-marker key
("dir/sub/") the parent computation kept the trailing empty segment, so the
"parent" it invalidated was the marker key itself, never the real parent.

Run with: python -m pytest test/test_s3_mkdir_visibility.py -v
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime

from botocore.exceptions import ClientError

from xefm.path import Path
from xefm.s3 import S3Cache, S3PathImpl, get_s3_cache


def _listing(contents, prefixes):
    return {
        'Contents': contents,
        'CommonPrefixes': [{'Prefix': p} for p in prefixes],
        'KeyCount': len(contents),
        'IsTruncated': False,
    }


class MkdirThenListVisibility(unittest.TestCase):
    """End-to-end through the mocked client: list, mkdir, list again."""

    def setUp(self):
        get_s3_cache().clear()
        self.client = Mock()
        self.before = _listing(
            [{'Key': 'project/readme.md', 'Size': 3,
              'LastModified': datetime(2024, 1, 1), 'ETag': '"a"',
              'StorageClass': 'STANDARD'}],
            [],
        )
        self.after = _listing(self.before['Contents'], ['project/newdir/'])
        self.paginator = Mock()
        self.paginator.paginate.return_value = [self.before]
        self.client.get_paginator.return_value = self.paginator
        # mkdir()'s existence probe: the directory doesn't exist yet.
        self.client.head_object.side_effect = ClientError(
            {'Error': {'Code': '404'}}, 'HeadObject')
        self.client.list_objects_v2.return_value = {'KeyCount': 0}

    @patch('xefm.s3.boto3.client')
    def test_new_directory_appears_without_waiting_for_ttl(self, boto3_client):
        boto3_client.return_value = self.client

        parent = Path('s3://test-bucket/project/')
        names = [p.name for p in parent.iterdir()]
        self.assertNotIn('newdir', names)

        Path('s3://test-bucket/project/newdir').mkdir()
        self.client.put_object.assert_called_once_with(
            Bucket='test-bucket', Key='project/newdir/', Body=b'')

        # The next listing must go back to S3 (stale cache evicted), not
        # replay the pre-mkdir listing from cache.
        self.paginator.paginate.return_value = [self.after]
        names = [p.name for p in Path('s3://test-bucket/project/').iterdir()]
        self.assertIn('newdir', names)


class InvalidateForWrite(unittest.TestCase):
    """Unit-level checks on the invalidation seams the bug hid in."""

    def setUp(self):
        get_s3_cache().clear()

    def _cache_listing(self, key):
        # Exactly the shape iterdir() stores.
        prefix = key.rstrip('/') + '/' if key else ''
        get_s3_cache().put(
            operation='list_objects_v2_complete', bucket='b', key=key,
            data=_listing([], []),
            prefix=prefix, delimiter='/', complete_listing=True)

    def _cached(self, key):
        prefix = key.rstrip('/') + '/' if key else ''
        return get_s3_cache().get(
            operation='list_objects_v2_complete', bucket='b', key=key,
            prefix=prefix, delimiter='/', complete_listing=True)

    def test_directory_marker_write_evicts_parent_listing_both_spellings(self):
        # A listing may be cached under 'project' or 'project/' depending on
        # how the pane's path was spelled; both must go.
        for spelling in ('project', 'project/'):
            with self.subTest(spelling=spelling):
                self._cache_listing(spelling)
                S3PathImpl('s3://b/project/newdir')._invalidate_cache_for_write(
                    'project/newdir/')
                self.assertIsNone(self._cached(spelling))

    def test_top_level_directory_write_evicts_bucket_root_listing(self):
        self._cache_listing('')
        S3PathImpl('s3://b/newdir')._invalidate_cache_for_write('newdir/')
        self.assertIsNone(self._cached(''))

    def test_file_write_evicts_parent_listing(self):
        self._cache_listing('project')
        S3PathImpl('s3://b/project/new.txt')._invalidate_cache_for_write()
        self.assertIsNone(self._cached('project'))

    def test_invalidate_key_covers_complete_listing_operation(self):
        cache = S3Cache()
        cache.put(operation='list_objects_v2_complete', bucket='b',
                  key='project', data={}, prefix='project/', delimiter='/',
                  complete_listing=True)
        cache.invalidate_key('b', 'project/newdir/')
        self.assertIsNone(cache.get(
            operation='list_objects_v2_complete', bucket='b', key='project',
            prefix='project/', delimiter='/', complete_listing=True))

    def test_unrelated_sibling_listing_survives(self):
        self._cache_listing('other')
        S3PathImpl('s3://b/project/newdir')._invalidate_cache_for_write(
            'project/newdir/')
        self.assertIsNotNone(self._cached('other'))


if __name__ == '__main__':
    unittest.main()
