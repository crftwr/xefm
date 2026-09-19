"""Network mounts — the parts that can be tested without a server.

What is covered here is the decision-making: which text is an address and which
is not, how the mount table is classified, and what happens around a mount
rather than during one. The mounts themselves need a NAS and a USB stick and are
hand-checked; nothing in this file touches the network.
"""

import platform
import sys
import threading
import unittest
from unittest.mock import patch

from xefm import netmount


class ParseAddress(unittest.TestCase):
    """``parse_address`` is also the "is this an address at all?" test the
    picker's filter line asks, so the rejections matter as much as the parses."""

    def test_a_plain_smb_url(self):
        target = netmount.parse_address("smb://nas/photo")
        self.assertEqual((target.scheme, target.host, target.share),
                         ("smb", "nas", "photo"))
        self.assertEqual(target.url, "smb://nas/photo")

    def test_the_user_comes_out_of_the_address(self):
        target = netmount.parse_address("smb://me@nas/photo")
        self.assertEqual(target.user, "me")
        # ...and is not part of the canonical URL, which is what saved servers
        # and stored passwords are keyed on.
        self.assertEqual(target.url, "smb://nas/photo")

    def test_a_password_in_the_address_is_dropped(self):
        target = netmount.parse_address("smb://me:hunter2@nas/photo")
        self.assertEqual(target.user, "me")
        self.assertNotIn("hunter2", target.url)
        self.assertNotIn("hunter2", repr(target))

    def test_a_subdirectory_below_the_share(self):
        target = netmount.parse_address("smb://nas/photo/2026/spring")
        self.assertEqual(target.share, "photo/2026/spring")

    def test_a_port(self):
        target = netmount.parse_address("https://dav.example.com:8443/files")
        self.assertEqual(target.port, 8443)
        self.assertEqual(target.url, "https://dav.example.com:8443/files")

    def test_cifs_is_smb(self):
        self.assertEqual(netmount.parse_address("cifs://nas/photo").scheme, "smb")

    def test_webdav_needs_no_share(self):
        target = netmount.parse_address("https://dav.example.com")
        self.assertIsNotNone(target)
        self.assertEqual(target.share, "")

    def test_smb_without_a_share_is_not_enough(self):
        self.assertIsNone(netmount.parse_address("smb://nas"))

    def test_a_unc_path(self):
        target = netmount.parse_address(r"\\nas\photo")
        self.assertEqual((target.scheme, target.host, target.share),
                         ("smb", "nas", "photo"))

    def test_a_unc_path_with_a_subdirectory(self):
        target = netmount.parse_address(r"\\nas\photo\2026")
        self.assertEqual(target.share, "photo/2026")

    def test_the_posix_spelling_of_a_unc_path(self):
        target = netmount.parse_address("//me@nas/photo")
        self.assertEqual((target.host, target.share, target.user),
                         ("nas", "photo", "me"))

    def test_the_unc_property_round_trips(self):
        self.assertEqual(netmount.parse_address("smb://nas/photo/2026").unc,
                         r"\\nas\photo\2026")

    def test_the_host_is_folded_to_lower_case(self):
        self.assertEqual(netmount.parse_address("SMB://NAS/Photo").host, "nas")
        # ...but the share is not: SMB share names are case-preserving, and the
        # mount path is built from what the user typed.
        self.assertEqual(netmount.parse_address("SMB://NAS/Photo").share, "Photo")

    def test_things_that_are_not_addresses(self):
        for text in ("", "   ", "nas", "photo", "/Volumes/photo", "C:\\Users",
                     "smb:/nas/photo", "smb//nas/photo", "http:/x",
                     "~/Documents", "ssh://host/path", "s3://bucket",
                     "smb://", "*.py", "kensaku"):
            with self.subTest(text=text):
                self.assertIsNone(netmount.parse_address(text))
                self.assertFalse(netmount.looks_like_address(text))

    def test_ssh_and_s3_stay_with_their_own_backends(self):
        """They are addresses, but not *mountable* ones — XeFM already browses
        them through their own PathImpl, and mounting them would be a second,
        worse way to reach the same place."""
        self.assertIsNone(netmount.parse_address("ssh://devbox/var/www"))
        self.assertIsNone(netmount.parse_address("s3://bucket/key"))


class Classify(unittest.TestCase):
    def setUp(self):
        self.mounts = [
            netmount.MountInfo("/Volumes/photo", netmount.NETWORK,
                               "//me@nas/photo", "smbfs"),
            netmount.MountInfo("/Volumes/USB", netmount.REMOVABLE, "/dev/disk4s1"),
            netmount.MountInfo("/", netmount.OTHER, "/dev/disk3s1s1"),
        ]

    def test_an_exact_mount_point_is_found(self):
        with patch.object(netmount, "list_mounts", return_value=self.mounts):
            self.assertEqual(netmount.classify("/Volumes/photo").kind,
                             netmount.NETWORK)

    def test_a_trailing_separator_does_not_matter(self):
        with patch.object(netmount, "list_mounts", return_value=self.mounts):
            self.assertEqual(netmount.classify("/Volumes/USB/").kind,
                             netmount.REMOVABLE)

    def test_a_directory_inside_a_volume_is_not_the_volume(self):
        """Disconnecting from a row that is merely *in* a share would be a very
        surprising thing for Shift-Delete to do."""
        with patch.object(netmount, "list_mounts", return_value=self.mounts):
            self.assertIsNone(netmount.classify("/Volumes/photo/2026"))

    def test_nothing_is_classified_without_a_path(self):
        self.assertIsNone(netmount.classify(""))


class _FakeBackend:
    """Stands in for a platform module, so the wrapper logic in
    :mod:`xefm.netmount` can be tested with no operating system involved."""

    SCHEMES = ("smb",)

    def __init__(self, path="/Volumes/photo"):
        self.path = path
        self.unmounted = []

    def is_available(self):
        return True

    def mount(self, target, user="", password="", drive_letter=""):
        return self.path

    def unmount(self, path):
        self.unmounted.append(path)

    def eject(self, path):
        self.unmounted.append(path)

    def list_mounts(self):
        return []


class MountWrapper(unittest.TestCase):
    def setUp(self):
        self.backend = _FakeBackend()
        patcher = patch.object(netmount, "_backend", return_value=self.backend)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.target = netmount.parse_address("smb://nas/photo")

    def test_the_path_the_backend_reports_is_what_comes_back(self):
        """Not the path the caller could have guessed: macOS renames a mount
        point whose name is taken, and the pane has to go to the real one."""
        self.backend.path = "/Volumes/photo-1"
        self.assertEqual(netmount.mount(self.target), "/Volumes/photo-1")

    def test_an_unsupported_scheme_is_refused_before_any_call(self):
        target = netmount.parse_address("https://dav.example.com/files")
        with self.assertRaises(netmount.MountError):
            netmount.mount(target)

    def test_a_mount_that_lands_after_being_cancelled_is_undone(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(netmount.MountError):
            netmount.mount(self.target, cancel=cancel)
        self.assertEqual(self.backend.unmounted, ["/Volumes/photo"])

    def test_a_mount_that_was_not_cancelled_is_left_alone(self):
        netmount.mount(self.target, cancel=threading.Event())
        self.assertEqual(self.backend.unmounted, [])


class NoBackend(unittest.TestCase):
    """On Linux — and on a Mac where the framework will not load — the feature
    reports itself unavailable rather than raising at the point of use."""

    def setUp(self):
        patcher = patch.object(netmount, "_backend", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unsupported(self):
        self.assertFalse(netmount.is_supported())
        self.assertEqual(netmount.supported_schemes(), ())
        self.assertEqual(netmount.list_mounts(), [])

    def test_mounting_says_so(self):
        with self.assertRaises(netmount.MountError):
            netmount.mount(netmount.parse_address("smb://nas/photo"))

    def test_passwords_are_a_no_op(self):
        target = netmount.parse_address("smb://nas/photo")
        self.assertFalse(netmount.save_password(target, "me", "x"))
        self.assertEqual(netmount.load_password(target, "me"), "")
        netmount.forget_password(target, "me")  # must not raise


class BackendSelection(unittest.TestCase):
    def tearDown(self):
        netmount.reset_backend_cache()

    def test_linux_has_no_backend(self):
        netmount.reset_backend_cache()
        with patch.object(platform, "system", return_value="Linux"):
            self.assertFalse(netmount.is_supported())

    def test_a_backend_that_reports_itself_unavailable_is_dropped(self):
        """A Mac whose NetFS will not load must end up with no backend at all,
        rather than one that raises the moment it is used."""
        from xefm import netmount_macos

        netmount.reset_backend_cache()
        with patch.object(platform, "system", return_value="Darwin"), \
             patch.object(netmount_macos, "is_available", return_value=False):
            self.assertFalse(netmount.is_supported())


@unittest.skipUnless(sys.platform == "darwin", "macOS backend")
class MacBackend(unittest.TestCase):
    def setUp(self):
        from xefm import netmount_macos
        self.mac = netmount_macos

    def test_the_statfs_layout_is_the_one_the_sdk_declares(self):
        """``getmntinfo`` returns an array, and ctypes walks it by this size.
        Get it wrong and the mount paths come back as garbage rather than as an
        error — so the number is asserted, not trusted."""
        import ctypes
        self.assertEqual(ctypes.sizeof(self.mac._statfs), 2168)

    def test_the_real_mount_table_reads_back(self):
        mounts = self.mac.list_mounts()
        self.assertTrue(mounts)
        paths = [m.path for m in mounts]
        self.assertIn("/", paths)
        for info in mounts:
            self.assertIn(info.kind, (netmount.NETWORK, netmount.REMOVABLE,
                                      netmount.OTHER))

    def test_classification(self):
        local, dontbrowse = 0x1000, 0x00100000
        cases = [
            ("smbfs", "/Volumes/photo", 0, netmount.NETWORK),
            ("webdav", "/Volumes/dav", 0, netmount.NETWORK),
            ("nfs", "/Volumes/export", 0, netmount.NETWORK),
            ("apfs", "/Volumes/USB", local, netmount.REMOVABLE),
            ("msdos", "/Volumes/CARD", local, netmount.REMOVABLE),
            # The Recovery volume is local and under /Volumes, and ejecting it
            # is not something to offer.
            ("apfs", "/Volumes/Recovery", local | dontbrowse, netmount.OTHER),
            ("apfs", "/", local, netmount.OTHER),
            ("apfs", "/System/Volumes/Data", local, netmount.OTHER),
            # Not local, but not a share either — and `umount /dev` is not a
            # thing to put on a keystroke.
            ("autofs", "/System/Volumes/Data/home", 0, netmount.OTHER),
            ("devfs", "/dev", 0, netmount.OTHER),
            # A directory below a volume is not the volume.
            ("apfs", "/Volumes/USB/sub", local, netmount.OTHER),
        ]
        for fstype, path, flags, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(self.mac._kind(fstype, path, flags), expected)

    def test_a_password_that_came_back_as_hex_is_decoded(self):
        self.assertEqual(self.mac._decode_password("e697a5e69cac"), "日本")

    def test_a_password_that_merely_looks_like_hex_is_not(self):
        """``security -w`` prints non-ASCII passwords as hex, and ``123456`` is
        valid hex. Decoding it would hand back three control characters."""
        for raw in ("123456", "ABCDEF", "", "abc", "hunter2"):
            with self.subTest(raw=raw):
                self.assertEqual(self.mac._decode_password(raw), raw)

    def test_finding_an_already_mounted_share(self):
        mounts = [netmount.MountInfo("/Volumes/photo", netmount.NETWORK,
                                     "//me@NAS/Photo", "smbfs")]
        target = netmount.parse_address("smb://nas/photo")
        with patch.object(self.mac, "list_mounts", return_value=mounts):
            self.assertEqual(self.mac._find_mount(target), "/Volumes/photo")

    def test_a_different_share_on_the_same_server_is_not_a_match(self):
        mounts = [netmount.MountInfo("/Volumes/photo", netmount.NETWORK,
                                     "//me@nas/photo", "smbfs")]
        target = netmount.parse_address("smb://nas/backup")
        with patch.object(self.mac, "list_mounts", return_value=mounts):
            self.assertEqual(self.mac._find_mount(target), "")


if __name__ == "__main__":
    unittest.main()
