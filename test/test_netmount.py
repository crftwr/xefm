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

    def test_smb_without_a_share_is_a_server_to_browse(self):
        """It parses, because it names something real — a server — and the
        picker asks it for its shares. What it is not is mountable."""
        target = netmount.parse_address("smb://nas")
        self.assertEqual((target.host, target.share), ("nas", ""))

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

    def test_the_address_keeps_the_case_it_was_typed_in(self):
        """What is shown and what is saved is what the user wrote. Folding the
        host for display put ``smb://synologynas/Videos`` on screen for someone
        who had typed ``SynologyNAS`` — bookkeeping leaking onto their screen."""
        target = netmount.parse_address("smb://SynologyNAS/Videos")
        self.assertEqual(target.host, "SynologyNAS")
        self.assertEqual(target.url, "smb://SynologyNAS/Videos")

    def test_the_identity_folds_the_host_but_not_the_share(self):
        """DNS, mDNS and NetBIOS are all case-insensitive, so two spellings of
        a host are one machine and must not become two saved rows or two stored
        passwords. SMB share names do preserve case, and the mount path is
        built from them."""
        a = netmount.parse_address("smb://SynologyNAS/Videos")
        b = netmount.parse_address("smb://synologynas/Videos")
        self.assertEqual(a.key, b.key)
        self.assertEqual(a.key, "smb://synologynas/Videos")
        self.assertNotEqual(netmount.parse_address("smb://nas/Photo").key,
                            netmount.parse_address("smb://nas/photo").key)

    def test_local_comes_off_the_identity(self):
        """Bonjour answers `SynologyNas.local`, a hand-typed address says
        `synologynas`, and the mount table reports `//me@synologynas/Videos`.
        One machine. Left unfolded it was two rows, two keychain entries, and a
        mounted share the list did not recognise as mounted."""
        bonjour = netmount.parse_address("smb://SynologyNas.local/Videos")
        typed = netmount.parse_address("smb://synologynas/Videos")
        self.assertEqual(bonjour.key, typed.key)
        self.assertEqual(bonjour.canonical_host, "synologynas")
        # ...and the address still shows and connects as Bonjour gave it, since
        # the mDNS name is the one guaranteed to resolve.
        self.assertEqual(bonjour.url, "smb://SynologyNas.local/Videos")

    def test_canonical_host_on_a_bare_string(self):
        for raw, expected in (("SynologyNas.local", "synologynas"),
                              ("SynologyNas.local.", "synologynas"),
                              ("NAS", "nas"),
                              ("host.localdomain", "host.localdomain"),
                              ("", "")):
            with self.subTest(raw=raw):
                self.assertEqual(netmount.canonical_host(raw), expected)

    def test_the_identity_keeps_the_port(self):
        target = netmount.parse_address("https://DAV.example.com:8443/files")
        self.assertEqual(target.key, "https://dav.example.com:8443/files")

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


class Discovery(unittest.TestCase):
    def test_a_discovered_server_becomes_a_share_less_address(self):
        """The advertised name is not the host — a Mac announces "Anna's
        MacBook Pro" and answers to Annas-MacBook-Pro.local — so the address is
        built from the resolved host, and the name is only ever shown."""
        server = netmount.DiscoveredServer(name="Anna's MacBook Pro",
                                           host="Annas-MacBook-Pro.local")
        self.assertEqual(server.target.url, "smb://Annas-MacBook-Pro.local")
        self.assertEqual(server.target.share, "")

    def test_discovery_is_silent_where_it_is_unsupported(self):
        with patch.object(netmount, "_backend", return_value=None):
            self.assertFalse(netmount.can_discover())
            self.assertEqual(list(netmount.discover_servers(threading.Event())),
                             [])

    def test_a_backend_that_throws_mid_scan_keeps_what_it_found(self):
        """A browse that dies halfway is a shorter list, not an error dialog
        over a picker the user is already reading."""
        def half(cancel):
            yield netmount.DiscoveredServer("A", "a.local")
            raise OSError("network went away")

        backend = _FakeBackend()
        backend.discover_servers = half
        with patch.object(netmount, "_backend", return_value=backend):
            found = list(netmount.discover_servers(threading.Event()))
        self.assertEqual([s.name for s in found], ["A"])


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

    def test_a_server_with_no_share_cannot_be_mounted(self):
        target = netmount.parse_address("smb://nas")
        with self.assertRaises(netmount.MountError) as caught:
            netmount.mount(target)
        self.assertIn("Choose a share", str(caught.exception))

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

    def test_the_error_an_smb_server_actually_answers_with_is_an_auth_error(self):
        """EAUTH (80) is what a Synology — and most SMB servers — return for a
        refused login. Leaving it out of the auth set sent the user to a
        message box instead of back to the password field, which is a dead end
        for the one failure that has an obvious next step."""
        self.assertIn(80, self.mac._AUTH_ERRORS)
        self.assertIn(81, self.mac._AUTH_ERRORS)

    def test_a_refused_guest_connection_names_what_is_missing(self):
        target = netmount.parse_address("smb://synologynas/Videos")
        self.assertEqual(self.mac._describe(80, target, guest=True),
                         "synologynas needs a user name and password.")

    def test_a_refused_password_says_so(self):
        target = netmount.parse_address("smb://synologynas/Videos")
        self.assertIn("rejected", self.mac._describe(80, target, guest=False))

    def test_an_unreachable_server_is_named(self):
        target = netmount.parse_address("smb://synologynas/Videos")
        self.assertTrue(
            self.mac._describe(65, target).startswith("synologynas:"))

    def test_share_listing_reads_the_real_smbutil_table(self):
        """Captured from ``smbutil view -g //synologynas``. The columns are
        fixed-width, so the name is sliced at the offset the header gives
        rather than split — a share name may contain spaces, and the Comments
        column beside it certainly does."""
        output = (
            "Share                                           Type    Comments\n"
            "-------------------------------\n"
            "home                                            Disk    Home directory of crftwr\n"
            "Videos                                          Disk    \n"
            "IPC$                                            Pipe    IPC Service ()\n"
            "Documents                                       Disk    \n"
            "Time Machine                                    Disk    a name with spaces\n"
            "C$                                              Disk    admin share\n"
            "\n"
            "6 shares listed\n")
        self.assertEqual(
            self.mac._parse_shares(output),
            ["home", "Videos", "Documents", "Time Machine"])

    def test_share_listing_tries_guest_then_the_account(self):
        """A Synology refuses the guest query outright, so the account is the
        attempt that matters — and `smbutil` finds its password in the login
        Keychain, which is why no password is passed here."""
        import subprocess

        calls = []

        def fake(argv, **kwargs):
            calls.append(argv)
            failed = subprocess.CompletedProcess(
                argv, 68, stdout="",
                stderr="smbutil: server connection failed: Authentication error")
            ok = subprocess.CompletedProcess(
                argv, 0,
                stdout="Share                                           Type    Comments\n"
                       "----\nVideos                                          Disk\n",
                stderr="")
            return ok if "@" in argv[-1] else failed

        target = netmount.parse_address("smb://synologynas")
        with patch.object(self.mac, "_run_tool", fake):
            self.assertEqual(self.mac.list_shares(target, "crftwr"), ["Videos"])
        self.assertEqual([c[-1] for c in calls],
                         ["//synologynas", "//crftwr@synologynas"])
        self.assertIn("-g", calls[0])
        # The password is never an argument, and there is no password to pass.
        self.assertNotIn("crftwr@synologynas", " ".join(calls[0]))

    def test_share_listing_without_an_account_only_asks_as_a_guest(self):
        import subprocess

        calls = []

        def fake(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 68, stdout="", stderr="nope")

        target = netmount.parse_address("smb://synologynas")
        with patch.object(self.mac, "_run_tool", fake):
            with self.assertRaises(netmount.MountError) as caught:
                self.mac.list_shares(target)
        # Both spellings of the host are tried, but every attempt is a guest
        # one: with no account there is nothing to authenticate as.
        self.assertTrue(calls)
        for argv in calls:
            self.assertIn("-g", argv)
            self.assertNotIn("@", argv[-1])
        self.assertTrue(caught.exception.auth)

    def test_discovery_reports_the_bare_host_label(self):
        """macOS records a server under the spelling it was mounted with, so
        mounting "SynologyNas.local" makes Finder list the NAS twice — once as
        it advertises itself, once as XeFM connected to it."""
        for raw, expected in (("SynologyNas.local.", "SynologyNas"),
                              ("Annas-MacBook-Pro.local", "Annas-MacBook-Pro"),
                              ("nas.example.com.", "nas.example.com"),
                              ("", "")):
            with self.subTest(raw=raw):
                self.assertEqual(self.mac._host_label(raw), expected)

    def test_a_single_label_host_is_also_tried_as_mdns(self):
        """The bare name first, because it is the one that keeps the machine a
        single row in Finder — and `.local` behind it, because a Mac sharing
        its disk answers to nothing else."""
        self.assertEqual(self.mac._mdns_alternatives("SynologyNas"),
                         ["SynologyNas", "SynologyNas.local"])
        self.assertEqual(self.mac._mdns_alternatives("nas.example.com"),
                         ["nas.example.com"])
        self.assertEqual(self.mac._mdns_alternatives("SynologyNas.local"),
                         ["SynologyNas.local"])

    def test_the_fallback_swaps_only_the_host(self):
        target = netmount.parse_address("smb://nas:4450/share/sub")
        self.assertEqual(self.mac._url_for(target, "nas.local"),
                         "smb://nas.local:4450/share/sub")

    def test_a_host_that_answers_nothing_is_retried_as_mdns(self):
        tried = []

        def attempt(target, host, user, password):
            tried.append(host)
            if host == "nas.local":
                return "/Volumes/share"
            error = netmount.MountError("nas: The server cannot be reached.")
            error.unreachable = True
            raise error

        target = netmount.parse_address("smb://nas/share")
        with patch.object(self.mac, "_mount_once", attempt):
            self.assertEqual(self.mac.mount(target), "/Volumes/share")
        self.assertEqual(tried, ["nas", "nas.local"])

    def test_a_rejected_password_is_not_retried_under_another_name(self):
        """The server answered. Asking it again under a different name only
        earns a second rejection and a worse message."""
        tried = []

        def attempt(target, host, user, password):
            tried.append(host)
            raise netmount.MountError("rejected", auth=True)

        target = netmount.parse_address("smb://nas/share")
        with patch.object(self.mac, "_mount_once", attempt):
            with self.assertRaises(netmount.MountError):
                self.mac.mount(target)
        self.assertEqual(tried, ["nas"])

    def test_share_listing_tries_both_spellings(self):
        import subprocess

        calls = []

        def fake(argv, **kwargs):
            calls.append(argv[-1])
            return subprocess.CompletedProcess(argv, 68, stdout="", stderr="no")

        target = netmount.parse_address("smb://nas")
        with patch.object(self.mac, "_run_tool", fake):
            with self.assertRaises(netmount.MountError):
                self.mac.list_shares(target, "me")
        self.assertEqual(calls, ["//nas", "//me@nas",
                                 "//nas.local", "//me@nas.local"])

    def test_the_keychain_is_searched_under_finder_s_spelling_first(self):
        """Finder files a Bonjour-discovered server under its *service* name,
        so a lookup by host name finds nothing on exactly the machines the user
        has already connected to."""
        target = netmount.parse_address("smb://SynologyNas.local")
        self.assertEqual(
            self.mac._keychain_servers(target),
            ["SynologyNas._smb._tcp.local", "SynologyNas.local", "synologynas"])

    def test_the_keychain_spellings_do_not_repeat(self):
        target = netmount.parse_address("smb://nas")
        self.assertEqual(self.mac._keychain_servers(target),
                         ["nas._smb._tcp.local", "nas"])

    def test_an_account_is_read_out_of_the_keychain(self):
        import subprocess

        asked = []

        def fake(args, stdin=""):
            asked.append(args)
            if args[2] != "SynologyNas._smb._tcp.local":
                return subprocess.CompletedProcess(args, 44, stdout="",
                                                   stderr="not found")
            return subprocess.CompletedProcess(
                args, 0,
                stdout='    "acct"<blob>="crftwr"\n    "ptcl"<uint32>="smb "\n',
                stderr="")

        target = netmount.parse_address("smb://SynologyNas.local")
        with patch.object(self.mac, "_security", fake):
            self.assertEqual(self.mac.find_account(target), "crftwr")
        # Attributes only: -w would decrypt the password and can raise an
        # access prompt, for a server the user has merely highlighted.
        self.assertTrue(asked)
        for args in asked:
            self.assertNotIn("-w", args)

    def test_no_account_is_not_an_error(self):
        import subprocess

        def fake(args, stdin=""):
            return subprocess.CompletedProcess(args, 44, stdout="",
                                               stderr="not found")

        target = netmount.parse_address("smb://nas")
        with patch.object(self.mac, "_security", fake):
            self.assertEqual(self.mac.find_account(target), "")

    def test_share_listing_survives_output_it_does_not_recognise(self):
        self.assertEqual(self.mac._parse_shares(""), [])
        self.assertEqual(self.mac._parse_shares("smbutil: something went wrong"), [])

    def test_the_browse_services_are_the_two_finder_shows(self):
        self.assertEqual(set(self.mac._BONJOUR_SERVICES.values()),
                         {"smb", "afp"})

    def test_no_system_tool_is_run_with_a_terminal(self):
        """Every one of these must be detached from the controlling terminal.

        ``security -w`` reads its password from ``/dev/tty`` when it can, not
        from the stdin it was handed — so in the TUI it printed "password data
        for new item:" over the file pane, waited for keystrokes that were
        going to XeFM, and timed out twenty seconds later. Reproduced under a
        real pty before this was fixed. The guard is ``start_new_session``, and
        it belongs on every tool here, not just the one that was caught.
        """
        import subprocess

        target = netmount.parse_address("smb://nas/photo")
        calls = []

        def record(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with patch.object(self.mac.subprocess, "run", record):
            self.mac.save_password(target, "me", "secret")
            self.mac.load_password(target, "me")
            self.mac.forget_password(target, "me")
            self.mac.unmount("/Volumes/photo")
            self.mac.eject("/Volumes/USB")
            self.mac.list_shares(target)

        self.assertEqual(len(calls), 6)
        for argv, kwargs in calls:
            with self.subTest(tool=argv[0]):
                self.assertTrue(kwargs.get("start_new_session"),
                                f"{argv[0]} may reach for /dev/tty")

    def test_a_password_never_reaches_the_command_line(self):
        """The process list is readable by every user on the machine."""
        import subprocess

        target = netmount.parse_address("smb://nas/photo")
        seen = {}

        def record(argv, **kwargs):
            seen["argv"], seen["input"] = argv, kwargs.get("input", "")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with patch.object(self.mac.subprocess, "run", record):
            self.mac.save_password(target, "me", "hunter2")
        self.assertNotIn("hunter2", " ".join(seen["argv"]))
        # It goes on stdin instead — twice, because -w prompts and confirms.
        self.assertEqual(seen["input"], "hunter2\nhunter2\n")

    def test_finding_an_already_mounted_share(self):
        mounts = [netmount.MountInfo("/Volumes/photo", netmount.NETWORK,
                                     "//me@NAS/Photo", "smbfs")]
        target = netmount.parse_address("smb://nas/photo")
        with patch.object(self.mac, "list_mounts", return_value=mounts):
            self.assertEqual(self.mac._find_mount(target), "/Volumes/photo")

    def test_a_bonjour_address_matches_the_mount_table(self):
        """The mount table says `synologynas`; the address came from Bonjour
        and says `SynologyNas.local`. The share is mounted either way."""
        mounts = [netmount.MountInfo("/Volumes/Videos", netmount.NETWORK,
                                     "//crftwr@synologynas/Videos", "smbfs")]
        target = netmount.parse_address("smb://SynologyNas.local/Videos")
        with patch.object(self.mac, "list_mounts", return_value=mounts):
            self.assertEqual(self.mac._find_mount(target), "/Volumes/Videos")

    def test_the_keychain_is_keyed_on_the_canonical_host(self):
        """A password saved when the address was typed by hand has to be found
        again when the address comes from Bonjour."""
        typed = netmount.parse_address("smb://synologynas/Videos")
        bonjour = netmount.parse_address("smb://SynologyNas.local/Documents")
        self.assertEqual(self.mac._keychain_keys(typed, "me"),
                         self.mac._keychain_keys(bonjour, "me"))

    def test_a_different_share_on_the_same_server_is_not_a_match(self):
        mounts = [netmount.MountInfo("/Volumes/photo", netmount.NETWORK,
                                     "//me@nas/photo", "smbfs")]
        target = netmount.parse_address("smb://nas/backup")
        with patch.object(self.mac, "list_mounts", return_value=mounts):
            self.assertEqual(self.mac._find_mount(target), "")


class BackendParity(unittest.TestCase):
    """Both platform modules are called through the same wrapper, so a
    function they both declare has to take the same arguments.

    Read out of the source with ``ast`` rather than imported, because neither
    module can be imported on the other's platform — which is exactly how this
    went wrong: ``list_shares`` grew a ``user`` argument on macOS and on the
    wrapper, the Windows one kept its single parameter, and every attempt to
    browse a server on Windows died on a TypeError inside a worker thread. The
    picker reported that as the server refusing to list its shares.
    """

    #: Declared by one platform only, and reached through ``hasattr`` or from
    #: Windows-only code. Everything else must match.
    ONLY_ONE_PLATFORM = {"find_account", "free_drive_letters"}

    def _signatures(self, path: str) -> dict:
        import ast
        import io

        tree = ast.parse(io.open(path, encoding="utf-8").read())
        return {node.name: [a.arg for a in node.args.posonlyargs
                            + node.args.args + node.args.kwonlyargs]
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and not node.name.startswith("_")}

    def test_both_backends_take_the_same_arguments(self):
        windows = self._signatures("xefm/netmount_windows.py")
        mac = self._signatures("xefm/netmount_macos.py")
        shared = (set(windows) & set(mac)) | (
            (set(windows) ^ set(mac)) - self.ONLY_ONE_PLATFORM)
        self.assertIn("list_shares", shared)
        for name in sorted(shared):
            with self.subTest(function=name):
                self.assertEqual(windows.get(name), mac.get(name))


@unittest.skipUnless(sys.platform == "win32", "Windows backend")
class WindowsBackend(unittest.TestCase):
    def setUp(self):
        from xefm import netmount_windows
        self.win = netmount_windows

    def _row(self, remote, provider="", *, display=0, usage=0, type=1):
        return self.win._Resource(local="", remote=remote, provider=provider,
                                  usage=usage, display=display, type=type)

    def test_a_container_keeps_the_provider_it_came_from(self):
        """The top level of the network is the installed providers, and a
        provider's remote name is a display name — "Microsoft Windows Network"
        — not a path. Rebuilt from that name alone, as this once was, the
        NETRESOURCE belongs to no provider and Windows refuses it with
        ERROR_NO_NET_OR_BAD_PATH."""
        row = self._row("Microsoft Windows Network",
                        "Microsoft Windows Network",
                        display=6, usage=self.win.RESOURCEUSAGE_CONTAINER,
                        type=0)
        resource = self.win._container(row)
        self.assertEqual(resource.lpProvider, "Microsoft Windows Network")
        self.assertEqual(resource.lpRemoteName, "Microsoft Windows Network")
        self.assertEqual(resource.dwUsage, self.win.RESOURCEUSAGE_CONTAINER)
        self.assertEqual(resource.dwDisplayType, 6)
        self.assertEqual(resource.dwScope, self.win.RESOURCE_GLOBALNET)

    def test_a_server_named_by_hand_has_no_provider(self):
        """NULL, not an empty string — which would name a provider called ""."""
        self.assertIsNone(self.win._container(self._row("//nas")).lpProvider)

    def test_the_walk_asks_the_provider_for_the_level_below_it(self):
        """The regression: with the provider dropped, the second level was
        refused every time, the walk ended at the providers, and discovery
        found nothing on any machine — silently, since an empty answer is a
        legitimate one here."""
        provider = self._row("Microsoft Windows Network",
                             "Microsoft Windows Network", display=6,
                             usage=self.win.RESOURCEUSAGE_CONTAINER, type=0)
        server = self._row(r"\\nas", "Microsoft Windows Network",
                           display=self.win.RESOURCEDISPLAYTYPE_SERVER)
        asked = []

        def enum(scope, resource=None):
            asked.append(resource)
            if resource is None:
                return [provider]
            if resource.lpRemoteName == provider.remote:
                return [server]
            return []

        with patch.object(self.win, "_enum", enum):
            found = list(self.win._walk_the_providers(threading.Event(), set()))

        self.assertEqual([s.host for s in found], ["nas"])
        self.assertEqual(asked[1].lpProvider, "Microsoft Windows Network")

    def test_share_listing_takes_the_account_the_wrapper_passes(self):
        """Windows authenticates a share listing with the session's own
        credentials, so the account is unused — but it is still passed, and
        being unable to receive it is what broke browsing entirely."""
        rows = [self._row(rf"\\nas\{name}") for name in ("photo", "C$", "IPC$")]
        target = netmount.parse_address("smb://nas")
        with patch.object(self.win, "_enum", lambda scope, resource=None: rows):
            self.assertEqual(self.win.list_shares(target, "crftwr"), ["photo"])
            self.assertEqual(self.win.list_shares(target), ["photo"])

    # --- mDNS discovery --------------------------------------------------

    def test_the_label_is_taken_off_the_service_type(self):
        label = self.win._instance_label("SynologyNas._smb._tcp.local",
                                         self.win._SMB_SERVICE)
        self.assertEqual(label, "SynologyNas")
        # A trailing root dot, and a label with a space in it: both are
        # ordinary DNS-SD, and neither is a host name.
        self.assertEqual(
            self.win._instance_label("Annas MacBook Pro._smb._tcp.local.",
                                     self.win._SMB_SERVICE),
            "Annas MacBook Pro")

    def test_only_the_srv_record_names_a_server(self):
        """A batch carries PTR, SRV, TXT and addresses. The host lives in the
        SRV target and nowhere else — an instance name is a label, so a row
        built from the PTR would be a row that cannot be opened."""
        import ctypes

        srv = self.win.DNS_RECORDW()
        srv.pName = "SynologyNas._smb._tcp.local"
        srv.wType = self.win.DNS_TYPE_SRV
        srv.Data.Srv.pNameTarget = "SynologyNas.local."
        srv.Data.Srv.wPort = 445
        ptr = self.win.DNS_RECORDW()
        ptr.pName = "_smb._tcp.local"
        ptr.wType = 12
        ptr.pNext = ctypes.pointer(srv)

        browse = self.win._ServiceBrowse(self.win._SMB_SERVICE)
        self.assertEqual(list(browse._servers(ctypes.pointer(ptr))),
                         [("SynologyNas", "SynologyNas.local")])

    def test_a_discovered_local_name_falls_back_to_the_short_one(self):
        """The enumeration runs on the session's own credentials and the
        redirector keys a session on the name as written, so a NAS already
        connected as `\\\\SynologyNas` is a stranger as `\\\\SynologyNas.local`
        and answers ERROR_ACCESS_DENIED. Discovery is mDNS, so `.local` is the
        spelling every discovered row carries."""
        asked = []

        def enum(scope, resource=None):
            asked.append(resource.lpRemoteName)
            if resource.lpRemoteName.endswith(".local"):
                return []  # refused, as an anonymous session is
            return [self._row(r"\\SynologyNas\Videos")]

        target = netmount.parse_address("smb://SynologyNas.local")
        with patch.object(self.win, "_enum", enum):
            self.assertEqual(self.win.list_shares(target), ["Videos"])
        self.assertEqual(asked, [r"\\SynologyNas.local", r"\\SynologyNas"])

    def test_a_plain_host_is_asked_for_once(self):
        self.assertEqual(self.win._spellings("nas"), ["nas"])
        self.assertEqual(self.win._spellings("SynologyNas.local"),
                         ["SynologyNas.local", "SynologyNas"])

    def test_the_two_sources_are_merged_and_one_machine_is_one_row(self):
        """mDNS says `SynologyNas.local`, the provider walk says
        `SYNOLOGYNAS`, and they are the same NAS — folded by canonical_host,
        the same rule the keychain and the mount table are matched by. The
        multicast answer comes first because it arrives in a fraction of the
        time the walk takes."""
        import itertools
        import queue as queue_module

        class FakeBrowse:
            def __init__(self, service):
                self.service = service
                self.queue = queue_module.Queue()
                self.queue.put(("SynologyNas", "SynologyNas.local"))
                self.stopped = False

            def start(self):
                return True

            def stop(self):
                self.stopped = True

        browses = []
        provider = self._row("Microsoft Windows Network",
                             "Microsoft Windows Network", display=6,
                             usage=self.win.RESOURCEUSAGE_CONTAINER, type=0)

        def enum(scope, resource=None):
            if resource is None:
                return [provider]
            if resource.lpRemoteName == provider.remote:
                return [self._row(r"\\SYNOLOGYNAS", display=2),
                        self._row(r"\\OLDBOX", display=2)]
            return []

        def make(service):
            browses.append(FakeBrowse(service))
            return browses[-1]

        with patch.object(self.win, "_ServiceBrowse", make), \
             patch.object(self.win, "_MDNS_SETTLE", 0.05), \
             patch.object(self.win, "_enum", enum):
            found = self.win.discover_servers(threading.Event())
            rows = list(itertools.islice(found, 2))
            found.close()

        self.assertEqual([(s.name, s.host) for s in rows],
                         [("SynologyNas", "SynologyNas.local"),
                          ("OLDBOX", "OLDBOX")])
        self.assertEqual(browses[0].service, self.win._SMB_SERVICE)
        # Closing the picker stops the browse; a subscription left running is
        # multicast traffic nobody is reading.
        self.assertTrue(browses[0].stopped)


if __name__ == "__main__":
    unittest.main()
