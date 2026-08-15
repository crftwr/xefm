"""One-pass directory scanning (xefm.dir_scan) and the listing built on it.

A pane listing needs four facts per entry — is_dir, is_link, size, mtime. Asking
per file costs a round trip per file, which is the whole cost of listing a large
directory on a network mount (issue #183). ``dir_scan`` answers for the whole
directory at once, using the platform's bulk enumeration where one exists.

What matters is that the bulk answer is *indistinguishable* from the per-file
one — symlinks and all — so these tests pin every backend to the same reference.

Run with: python -m pytest test/test_dir_scan.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import dir_scan  # noqa: E402
from xefm.path import Path, attrs_via_path  # noqa: E402


def _reference(directory, name):
    """What the per-file route (stat/is_dir/is_symlink) reports — the contract
    every backend has to reproduce."""
    p = os.path.join(directory, name)
    is_link = os.path.islink(p)
    hidden = dir_scan.hidden_of(p)
    try:
        st = os.stat(p)
    except OSError:
        return {'is_dir': False, 'is_link': is_link, 'size': 0, 'mtime': 0.0,
                'hidden': hidden, 'ok': False}
    is_dir = os.path.isdir(p)
    return {'is_dir': is_dir, 'is_link': is_link,
            'size': 0 if is_dir else st.st_size,
            'mtime': st.st_mtime, 'hidden': hidden, 'ok': True}


class _TreeBase(unittest.TestCase):
    """A directory holding every shape the scan has to get right."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.tmp, "subdir"))
        with open(os.path.join(self.tmp, "regular.txt"), "w") as f:
            f.write("x" * 1234)
        with open(os.path.join(self.tmp, ".hidden"), "w") as f:
            f.write("h")
        os.symlink(os.path.join(self.tmp, "regular.txt"),
                   os.path.join(self.tmp, "link_to_file"))
        os.symlink(os.path.join(self.tmp, "subdir"),
                   os.path.join(self.tmp, "link_to_dir"))
        os.symlink(os.path.join(self.tmp, "nowhere"),
                   os.path.join(self.tmp, "link_broken"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def assertMatchesReference(self, scanned):
        got = dict(scanned)
        self.assertEqual(set(got), set(os.listdir(self.tmp)))
        for name, attrs in got.items():
            expected = _reference(self.tmp, name)
            mtime = attrs.pop('mtime')
            self.assertAlmostEqual(mtime, expected.pop('mtime'), places=2,
                                   msg=f"mtime for {name}")
            self.assertEqual(attrs, expected, f"attributes for {name}")


class ScanMatchesPerFileStat(_TreeBase):
    def test_the_platform_default_matches(self):
        self.assertMatchesReference(dir_scan.scan_dir(self.tmp))

    def test_the_portable_scandir_backend_matches(self):
        self.assertMatchesReference(dir_scan._scan_scandir(self.tmp))

    @unittest.skipUnless(dir_scan._BULK_READY, "getattrlistbulk is macOS-only")
    def test_the_bulk_backend_matches(self):
        self.assertMatchesReference(dir_scan._scan_bulk(self.tmp))

    def test_a_symlink_reports_its_target_but_stays_flagged_as_a_link(self):
        got = dict(dir_scan.scan_dir(self.tmp))
        # is_dir/size describe the target; is_link describes the link itself.
        self.assertEqual(got["link_to_dir"]["is_dir"], True)
        self.assertEqual(got["link_to_dir"]["is_link"], True)
        self.assertEqual(got["link_to_file"]["is_dir"], False)
        self.assertEqual(got["link_to_file"]["size"], 1234)
        self.assertEqual(got["link_to_file"]["is_link"], True)

    def test_a_broken_symlink_is_reported_not_raised(self):
        got = dict(dir_scan.scan_dir(self.tmp))
        broken = got["link_broken"]
        self.assertFalse(broken["ok"])
        # Still a link, even though its target is gone — that is what lets the
        # pane render it as a link with unknown size rather than dropping it.
        self.assertTrue(broken["is_link"])
        self.assertIn("regular.txt", got)  # the rest of the listing survived


class ScanReportsDirectoryErrors(_TreeBase):
    """Directory-level failures must still raise, so callers keep the error
    handling they had when this was iterdir()."""

    def test_missing_directory_raises(self):
        with self.assertRaises(FileNotFoundError):
            dir_scan.scan_dir(os.path.join(self.tmp, "nonexistent"))

    def test_a_file_is_not_a_directory(self):
        with self.assertRaises(NotADirectoryError):
            dir_scan.scan_dir(os.path.join(self.tmp, "regular.txt"))


class PathListdirAttrs(_TreeBase):
    def test_local_paths_scan_in_bulk_and_agree_with_the_per_file_route(self):
        for entry, attrs in Path(self.tmp).listdir_attrs():
            self.assertIsInstance(entry, Path)
            per_file = attrs_via_path(entry)
            self.assertEqual(attrs['is_dir'], per_file['is_dir'], entry.name)
            self.assertEqual(attrs['is_link'], per_file['is_link'], entry.name)
            self.assertEqual(attrs['size'], per_file['size'], entry.name)
            self.assertEqual(attrs['hidden'], per_file['hidden'], entry.name)
            self.assertEqual(attrs['ok'], per_file['ok'], entry.name)

    def test_it_covers_the_same_names_as_iterdir(self):
        self.assertEqual(
            sorted(p.name for p, _ in Path(self.tmp).listdir_attrs()),
            sorted(p.name for p in Path(self.tmp).iterdir()))


class ListingCostsNoPerFileCalls(_TreeBase):
    """The point of the exercise: building a listing must not stat per entry."""

    def test_compute_listing_issues_no_stat_calls(self):
        from unittest import mock
        from xefm.config import get_config
        from xefm.file_list_manager import FileListManager

        flm = FileListManager(get_config())
        real_stat, real_lstat = os.stat, os.lstat
        calls = []

        def counted(fn, label):
            def wrapper(*a, **kw):
                calls.append(label)
                return fn(*a, **kw)
            return wrapper

        # Symlinks are the one thing bulk enumeration cannot answer: its record
        # describes the link, so the target is followed per link. Everything
        # else must come out of the single scan, whatever the sort mode.
        links = sum(1 for n in os.listdir(self.tmp)
                    if os.path.islink(os.path.join(self.tmp, n)))
        entries = len(os.listdir(self.tmp))
        self.assertLess(links, entries, "fixture must have non-link entries too")

        for mode in ("name", "size", "date", "ext", "type"):
            calls.clear()
            with mock.patch("os.stat", counted(real_stat, "stat")), \
                 mock.patch("os.lstat", counted(real_lstat, "lstat")):
                result = flm.compute_listing(Path(self.tmp), sort_mode=mode)
            self.assertTrue(result["ok"])
            self.assertLessEqual(
                len(calls), links,
                f"sort={mode} cost {len(calls)} per-file calls for {entries} "
                f"entries; only the {links} symlinks may need one")


if __name__ == "__main__":
    unittest.main()
