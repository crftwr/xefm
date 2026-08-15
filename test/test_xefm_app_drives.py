"""
Drives picker data for the PuiKit XeFMApp.

Covers the pane-independent row builders behind ``show_drives`` — local
locations/volumes, SSH hosts from ~/.ssh/config, and the S3 bucket generator
that streams rows in on the dialog's background loader (issue #274) — plus the
wiring that hands the picker its eager rows and that loader. The dialog itself
(a ``show_filter_list`` modal) and the actual pane navigation are exercised
elsewhere; here we pin down the ``{name, path}`` rows the picker is fed.
"""

import os
import platform
import re
import sys
import threading
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
    """The S3 scan behind the drives picker: ``_s3_scan_available`` decides
    whether a background loader is attached at all; ``_s3_drives_iter`` is the
    row generator that runs on the picker's loader thread (issue #274)."""

    def _client_returning(self, buckets):
        client = MagicMock()
        client.can_paginate.return_value = False  # pre-paginator botocore path
        client.list_buckets.return_value = {"Buckets": [{"Name": n} for n in buckets]}
        return client

    def test_maps_buckets_to_s3_urls(self):
        client = self._client_returning(["alpha", "beta"])
        with patch("boto3.client", return_value=client):
            rows = list(_bare_app()._s3_drives_iter(threading.Event()))

        self.assertEqual(rows, [
            {"name": "alpha", "path": "s3://alpha/"},
            {"name": "beta", "path": "s3://beta/"},
        ])

    def test_pages_stream_in_order(self):
        # A paginating SDK yields rows page by page (the progressive part of
        # the scan); the rows arrive in listing order across pages.
        client = MagicMock()
        client.can_paginate.return_value = True
        client.get_paginator.return_value.paginate.return_value = iter([
            {"Buckets": [{"Name": "a"}]},
            {"Buckets": [{"Name": "b"}, {"Name": "c"}]},
        ])
        with patch("boto3.client", return_value=client):
            rows = list(_bare_app()._s3_drives_iter(threading.Event()))

        self.assertEqual([r["name"] for r in rows], ["a", "b", "c"])
        client.get_paginator.assert_called_once_with("list_buckets")
        client.list_buckets.assert_not_called()

    def test_cancel_stops_between_pages(self):
        # The picker sets ``cancel`` when the dialog closes; the scan must stop
        # at the next page boundary instead of finishing the listing.
        cancel = threading.Event()

        def pages():
            yield {"Buckets": [{"Name": "kept"}]}
            cancel.set()  # dialog closed while the next page was in flight
            yield {"Buckets": [{"Name": "dropped"}]}

        client = MagicMock()
        client.can_paginate.return_value = True
        client.get_paginator.return_value.paginate.return_value = pages()
        with patch("boto3.client", return_value=client):
            rows = list(_bare_app()._s3_drives_iter(cancel))

        self.assertEqual([r["name"] for r in rows], ["kept"])

    def test_empty_on_aws_error(self):
        client = MagicMock()
        client.can_paginate.return_value = False
        client.list_buckets.side_effect = RuntimeError("no creds")
        with patch("boto3.client", return_value=client):
            self.assertEqual(list(_bare_app()._s3_drives_iter(threading.Event())), [])

    def test_scan_unavailable_without_credentials(self):
        with patch("xefm.s3.HAS_BOTO3", True), \
             patch.object(xefm_app.XeFMApp, "_aws_configured", return_value=False):
            self.assertFalse(_bare_app()._s3_scan_available())

    def test_scan_unavailable_without_boto3(self):
        with patch("xefm.s3.HAS_BOTO3", False), \
             patch.object(xefm_app.XeFMApp, "_aws_configured", return_value=True):
            self.assertFalse(_bare_app()._s3_scan_available())

    def test_scan_available_with_boto3_and_credentials(self):
        with patch("xefm.s3.HAS_BOTO3", True), \
             patch.object(xefm_app.XeFMApp, "_aws_configured", return_value=True):
            self.assertTrue(_bare_app()._s3_scan_available())

    def test_aws_configured_reads_env(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "x"}, clear=False):
            self.assertTrue(xefm_app.XeFMApp._aws_configured())


class DrivesPickerWiring(unittest.TestCase):
    """``show_drives`` opens with only the instant (local + SSH) rows; the S3
    scan rides the dialog's background loader — or is absent entirely when AWS
    isn't configured, so no thread starts and no spinner shows."""

    def _show(self, s3_available):
        app = _bare_app()
        app.panel = MagicMock()
        with patch.object(app, "_local_drives",
                          return_value=[{"name": "Home", "path": "/h"}]), \
             patch.object(app, "_ssh_drives", return_value=[]), \
             patch.object(app, "_s3_scan_available", return_value=s3_available), \
             patch.object(app, "_active_pane_region", return_value=None), \
             patch("xefm.app.show_filter_list") as show:
            app.show_drives()
        show.assert_called_once()
        return app, show.call_args

    def test_eager_rows_never_include_s3(self):
        _app, call = self._show(True)
        self.assertEqual([r["path"] for r in call.args[1]], ["/h"])

    def test_s3_scan_attached_as_background_loader(self):
        app, call = self._show(True)
        self.assertEqual(call.kwargs.get("load_more"), app._s3_drives_iter)

    def test_no_loader_without_aws(self):
        _app, call = self._show(False)
        self.assertIsNone(call.kwargs.get("load_more"))


if __name__ == "__main__":
    unittest.main()
