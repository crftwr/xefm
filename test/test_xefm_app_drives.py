"""
Drives picker data for the PuiKit XeFMApp.

Covers the pane-independent row builders behind ``show_drives`` — local
locations/volumes and SSH hosts from ~/.ssh/config. The dialog itself (a
``show_filter_list`` modal) and the actual pane navigation are exercised
elsewhere; here we pin down the ``{name, path}`` rows the picker is fed.
"""

import os
import platform
import re
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
    def _rows(self, system, drive_roots=()):
        with patch.object(xefm_app.platform, "system", return_value=system), \
             patch.object(xefm_app.XeFMApp, "_windows_drive_roots",
                          return_value=list(drive_roots)):
            return _bare_app()._local_drives()

    def test_includes_home(self):
        by_name = {r["name"]: r["path"] for r in _bare_app()._local_drives()}
        self.assertEqual(by_name.get("Home"), str(xefm_app.Path.home()))

    def test_posix_includes_root(self):
        by_name = {r["name"]: r["path"] for r in self._rows("Linux")}
        self.assertEqual(by_name.get("Root"), "/")

    def test_windows_lists_drive_letters_not_root(self):
        rows = self._rows("Windows", ["C:\\", "D:\\"])
        by_name = {r["name"]: r["path"] for r in rows}
        self.assertEqual(by_name.get("C:"), "C:\\")
        self.assertEqual(by_name.get("D:"), "D:\\")
        self.assertNotIn("Root", by_name)  # "/" is drive-relative on Windows

    def test_windows_survives_empty_drive_scan(self):
        by_name = {r["name"]: r["path"] for r in self._rows("Windows")}
        self.assertEqual(by_name.get("Home"), str(xefm_app.Path.home()))

    def test_paths_are_unique(self):
        paths = [r["path"] for r in _bare_app()._local_drives()]
        self.assertEqual(len(paths), len(set(paths)))


class WindowsDriveRoots(unittest.TestCase):
    @unittest.skipUnless(platform.system() == "Windows", "queries real Windows drives")
    def test_real_roots_shape(self):
        roots = xefm_app.XeFMApp._windows_drive_roots()
        self.assertTrue(roots)  # at least the system drive
        for root in roots:
            self.assertRegex(root, re.compile(r"^[A-Z]:\\$"))

    def test_bitmask_fallback(self):
        # Pre-3.12 path: os.listdrives is absent, GetLogicalDrives supplies bits
        # 2 and 3 (C: and D:).
        ctypes_mod = MagicMock()
        ctypes_mod.windll.kernel32.GetLogicalDrives.return_value = 0b1100
        with patch.object(xefm_app.os, "listdrives", create=True,
                          side_effect=AttributeError), \
             patch.dict(sys.modules, {"ctypes": ctypes_mod}):
            roots = xefm_app.XeFMApp._windows_drive_roots()
        self.assertEqual(roots, ["C:\\", "D:\\"])


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
