"""S3 clients are shared, not built per path object (issue #418).

A boto3 client owns a connection pool. ``S3PathImpl`` used to build its own, so
a copy — which touches one path object per node in the tree — paid a TLS
handshake per node and left a pool behind for each, ending in thousands of
sockets stuck in CLOSE_WAIT. These tests pin the sharing, and the one thing
sharing is allowed to be split by: the bucket's region.

Run with: python -m pytest test/test_s3_client_sharing.py -v
"""

import unittest
from unittest.mock import MagicMock, patch

from xefm.s3 import (S3PathImpl, S3_MAX_POOL_CONNECTIONS, clear_s3_clients,
                     get_s3_client, get_s3_client_for_bucket,
                     get_s3_probe_client, note_bucket_region)


def _distinct_client_per_region(mock_boto3, session_region=None):
    """Make the stubbed boto3 hand out a distinct client per region, the way the
    real one does. ``session_region`` is what the region-less client resolves to."""
    def make(service, region_name=None, config=None, **kwargs):
        client = MagicMock(name=f"s3-client-{region_name or 'session'}")
        client.meta.region_name = region_name or session_region
        return client

    mock_boto3.client.side_effect = make


@patch('xefm.s3.boto3')
class SharedClients(unittest.TestCase):
    """One client per region for the whole process, however many paths ask."""

    def test_every_path_in_a_bucket_gets_the_same_client(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)

        impls = [S3PathImpl(f"s3://bucket/dir/file{i}.txt") for i in range(50)]
        clients = {id(impl._client) for impl in impls}

        self.assertEqual(len(clients), 1)
        self.assertEqual(mock_boto3.client.call_count, 1)

    def test_buckets_of_unknown_region_share_the_session_client(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)

        first = S3PathImpl("s3://alpha/key")._client
        second = S3PathImpl("s3://beta/key")._client

        self.assertIs(first, second)
        self.assertEqual(mock_boto3.client.call_count, 1)

    def test_pool_is_sized_for_the_copy_workers(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)

        S3PathImpl("s3://bucket/key")._client

        config = mock_boto3.client.call_args.kwargs['config']
        self.assertEqual(config.max_pool_connections, S3_MAX_POOL_CONNECTIONS)

    def test_a_client_attached_to_one_path_still_wins(self, mock_boto3):
        # The seam tests inject stubs through; nothing in the app sets it.
        _distinct_client_per_region(mock_boto3)
        stub = MagicMock()

        impl = S3PathImpl("s3://bucket/key")
        impl._s3_client = stub

        self.assertIs(impl._client, stub)
        mock_boto3.client.assert_not_called()

    def test_a_client_filed_under_two_keys_is_closed_once(self, mock_boto3):
        # The session client is also filed under the region it resolved to.
        _distinct_client_per_region(mock_boto3, session_region="us-east-1")

        client = get_s3_client()
        clear_s3_clients()

        client.close.assert_called_once()

    def test_cleared_clients_are_closed_and_rebuilt(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)

        first = get_s3_client()
        clear_s3_clients()
        second = get_s3_client()

        first.close.assert_called_once()
        self.assertIsNot(first, second)


@patch('xefm.s3.boto3')
class RegionRouting(unittest.TestCase):
    """The split by region: a request that starts at the wrong regional endpoint
    is answered with a redirect and has to be sent again, so a bucket whose
    region is known is reached through a client already bound to it."""

    def test_known_regions_get_their_own_clients(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)
        note_bucket_region("tokyo-bucket", "ap-northeast-1")
        note_bucket_region("dublin-bucket", "eu-west-1")

        tokyo = S3PathImpl("s3://tokyo-bucket/key")._client
        dublin = S3PathImpl("s3://dublin-bucket/key")._client

        self.assertIsNot(tokyo, dublin)
        self.assertEqual(tokyo.meta.region_name, "ap-northeast-1")
        self.assertEqual(dublin.meta.region_name, "eu-west-1")
        self.assertEqual(
            [c.kwargs['region_name'] for c in mock_boto3.client.call_args_list],
            ["ap-northeast-1", "eu-west-1"])

    def test_buckets_in_one_region_share_that_region_client(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)
        note_bucket_region("first", "eu-west-1")
        note_bucket_region("second", "eu-west-1")

        self.assertIs(get_s3_client_for_bucket("first"),
                      get_s3_client_for_bucket("second"))
        self.assertEqual(mock_boto3.client.call_count, 1)

    def test_session_client_serves_its_own_region_too(self, mock_boto3):
        # Learning that a bucket sits in the region the session already resolved
        # to must not open a second pool to an endpoint we are connected to.
        _distinct_client_per_region(mock_boto3, session_region="us-east-1")

        session = get_s3_client()
        note_bucket_region("home-bucket", "us-east-1")

        self.assertIs(get_s3_client_for_bucket("home-bucket"), session)
        self.assertEqual(mock_boto3.client.call_count, 1)

    def test_a_region_we_were_not_told_is_not_invented(self, mock_boto3):
        # ListBuckets omits BucketRegion on older SDKs; that leaves the bucket on
        # the session client rather than on a client bound to ``None``-something.
        _distinct_client_per_region(mock_boto3)
        note_bucket_region("bucket", None)
        note_bucket_region("bucket", "")

        self.assertIs(get_s3_client_for_bucket("bucket"), get_s3_client())
        self.assertEqual(mock_boto3.client.call_count, 1)


@patch('xefm.s3.boto3')
class ProbeClient(unittest.TestCase):
    """The drives picker's client: shared like the others, but on deadlines a
    transfer must not inherit."""

    def test_reopening_the_picker_reuses_one_client(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)

        self.assertIs(get_s3_probe_client(), get_s3_probe_client())
        self.assertEqual(mock_boto3.client.call_count, 1)

    def test_picker_fails_fast_while_transfers_do_not(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)

        probe = get_s3_probe_client()
        transfer = get_s3_client()

        self.assertIsNot(probe, transfer)
        probe_config = mock_boto3.client.call_args_list[0].kwargs['config']
        transfer_config = mock_boto3.client.call_args_list[1].kwargs['config']
        self.assertEqual(probe_config.connect_timeout, 2)
        self.assertEqual(probe_config.read_timeout, 3)
        self.assertEqual(probe_config.retries, {"max_attempts": 0})
        self.assertIsNone(transfer_config.retries)

    def test_clearing_drops_the_probe_client_as_well(self, mock_boto3):
        _distinct_client_per_region(mock_boto3)

        first = get_s3_probe_client()
        clear_s3_clients()

        first.close.assert_called_once()
        self.assertIsNot(get_s3_probe_client(), first)


if __name__ == '__main__':
    unittest.main()
