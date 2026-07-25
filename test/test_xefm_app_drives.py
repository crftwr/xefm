"""
Drives picker data for the PuiKit XeFMApp.

Covers the pane-independent row builders behind ``show_drives`` — local
locations/volumes and SSH hosts from ~/.ssh/config. The dialog itself (a
``show_filter_list`` modal) and the actual pane navigation are exercised
elsewhere; here we pin down the ``{name, path}`` rows the picker is fed.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402


def _bare_app():
    """A XeFMApp shell for the stateless row builders (no backend/UI needed)."""
    return xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)


class LocalDrives(unittest.TestCase):
    def test_includes_home_and_root(self):
        rows = _bare_app()._local_drives()
        by_name = {r["name"]: r["path"] for r in rows}
        self.assertEqual(by_name.get("Home"), str(xefm_app.Path.home()))
        self.assertEqual(by_name.get("Root"), "/")

    def test_paths_are_unique(self):
        paths = [r["path"] for r in _bare_app()._local_drives()]
        self.assertEqual(len(paths), len(set(paths)))


class SshDrives(unittest.TestCase):
    def _with_hosts(self, hosts):
        parser = MagicMock()
        parser.parse.return_value = hosts
        return patch("xefm.ssh_config.SSHConfigParser", return_value=parser)

    def test_maps_hosts_to_ssh_urls(self):
        hosts = {
            "myhost": {"HostName": "h.example.com", "User": "bob"},
            "plain": {"HostName": "plain.example.com"},
        }
        with self._with_hosts(hosts):
            rows = _bare_app()._ssh_drives()

        by_path = {r["path"]: r["name"] for r in rows}
        self.assertEqual(by_path["ssh://myhost/"], "bob@h.example.com")
        self.assertEqual(by_path["ssh://plain/"], "plain.example.com")

    def test_uses_alias_when_no_hostname(self):
        with self._with_hosts({"box": {}}):
            rows = _bare_app()._ssh_drives()
        self.assertEqual(rows, [{"name": "box", "path": "ssh://box/"}])

    def test_empty_when_parser_unavailable(self):
        with patch("xefm.ssh_config.SSHConfigParser", side_effect=RuntimeError):
            self.assertEqual(_bare_app()._ssh_drives(), [])

    def test_empty_when_no_config(self):
        with self._with_hosts({}):
            self.assertEqual(_bare_app()._ssh_drives(), [])


class S3Drives(unittest.TestCase):
    def _client_returning(self, buckets):
        client = MagicMock()
        client.list_buckets.return_value = {"Buckets": [{"Name": n} for n in buckets]}
        return client

    def test_maps_buckets_to_s3_urls(self):
        client = self._client_returning(["alpha", "beta"])
        with patch.object(xefm_app.XeFMApp, "_aws_configured", return_value=True), \
             patch("boto3.client", return_value=client):
            rows = _bare_app()._s3_drives()

        self.assertEqual(rows, [
            {"name": "alpha", "path": "s3://alpha/"},
            {"name": "beta", "path": "s3://beta/"},
        ])

    def test_skips_scan_when_aws_not_configured(self):
        with patch.object(xefm_app.XeFMApp, "_aws_configured", return_value=False), \
             patch("boto3.client") as mock_client:
            rows = _bare_app()._s3_drives()

        self.assertEqual(rows, [])
        mock_client.assert_not_called()  # no network call at all

    def test_empty_on_aws_error(self):
        client = MagicMock()
        client.list_buckets.side_effect = RuntimeError("no creds")
        with patch.object(xefm_app.XeFMApp, "_aws_configured", return_value=True), \
             patch("boto3.client", return_value=client):
            self.assertEqual(_bare_app()._s3_drives(), [])

    def test_aws_configured_reads_env(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "x"}, clear=False):
            self.assertTrue(xefm_app.XeFMApp._aws_configured())


if __name__ == "__main__":
    unittest.main()
