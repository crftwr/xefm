"""The hidden-files toggle covers the platform's own mark, not just dotfiles.

A leading dot hides an entry on POSIX. Windows says the same thing with a file
attribute instead, and XeFM ignored it: ``AppData``, ``$Recycle.Bin``,
``System Volume Information`` and every ``desktop.ini`` sat in the listing with
hidden files off (issue #284). These tests pin both halves — the attribute is
read as part of the one-pass scan, and every consumer of the toggle honours it.

The Windows classes need no privilege (``SetFileAttributesW`` is not
``symlink``), so they run on any Windows checkout; elsewhere they skip and the
platform-independent classes carry the filter logic.

Run with: python -m pytest test/test_hidden_files.py -v
"""

import ctypes
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import dir_scan  # noqa: E402
from xefm.completion import FilepathCompleter  # noqa: E402
from xefm.config import get_config  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.path import Path, attrs_via_path  # noqa: E402

_WINDOWS = sys.platform == "win32"

FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_SYSTEM = 0x04


def _mark(path, attributes):
    """Set Windows file attributes on ``path``, the way ``attrib +h`` does."""
    if not ctypes.windll.kernel32.SetFileAttributesW(str(path), attributes):
        raise ctypes.WinError(ctypes.get_last_error())


def _attrs(entries, name):
    return dict(entries)[name]


# ---------------------------------------------------------------------------
# The record: what the scan reports for a marked entry
# ---------------------------------------------------------------------------


@unittest.skipUnless(_WINDOWS, "the hidden attribute is Windows-only")
class ScanReadsTheHiddenAttribute(unittest.TestCase):
    """``scan_dir`` collects ``hidden`` alongside is_dir/size/mtime, so the
    listing costs no extra call to learn it."""

    def setUp(self):
        import tempfile
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

        def touch(name, attributes=None):
            p = os.path.join(self.tmp, name)
            with open(p, "w") as f:
                f.write("x")
            if attributes:
                _mark(p, attributes)
            return p

        touch("visible.txt")
        touch("marked.txt", FILE_ATTRIBUTE_HIDDEN)
        touch("system.txt", FILE_ATTRIBUTE_SYSTEM)
        touch("protected.sys", FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)
        touch(".dotfile")
        os.mkdir(os.path.join(self.tmp, "marked_dir"))
        _mark(os.path.join(self.tmp, "marked_dir"), FILE_ATTRIBUTE_HIDDEN)
        os.mkdir(os.path.join(self.tmp, "plain_dir"))

    def test_a_marked_file_reports_hidden(self):
        got = dict(dir_scan.scan_dir(self.tmp))
        self.assertTrue(got["marked.txt"]["hidden"])
        self.assertTrue(got["marked_dir"]["hidden"])

    def test_an_unmarked_entry_does_not(self):
        got = dict(dir_scan.scan_dir(self.tmp))
        self.assertFalse(got["visible.txt"]["hidden"])
        self.assertFalse(got["plain_dir"]["hidden"])
        # A dot-name is hidden by *name*, which the attribute does not claim;
        # is_hidden puts the two together.
        self.assertFalse(got[".dotfile"]["hidden"])
        self.assertTrue(dir_scan.is_hidden(".dotfile", got[".dotfile"]))

    def test_the_system_attribute_alone_does_not_hide(self):
        """Explorer keeps SYSTEM-but-not-hidden entries visible — C:\\Windows\\Fonts
        and a customized Documents folder carry it, and losing those from the
        listing would be worse than the bug being fixed. A protected operating
        system file carries HIDDEN too, so it still goes."""
        got = dict(dir_scan.scan_dir(self.tmp))
        self.assertFalse(got["system.txt"]["hidden"])
        self.assertTrue(got["protected.sys"]["hidden"])

    def test_the_per_file_route_agrees_with_the_scan(self):
        for entry, attrs in Path(self.tmp).listdir_attrs():
            self.assertEqual(attrs["hidden"], attrs_via_path(entry)["hidden"],
                             entry.name)
            self.assertEqual(attrs["hidden"], dir_scan.hidden_of(entry),
                             entry.name)


@unittest.skipUnless(_WINDOWS, "the hidden attribute is Windows-only")
class TheToggleHidesMarkedEntries(unittest.TestCase):
    """The bug as reported: with hidden files off, a pane still listed
    everything Windows had marked."""

    def setUp(self):
        import tempfile
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ("visible.txt", "marked.txt", "desktop.ini", ".dotfile"):
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write("x")
        _mark(os.path.join(self.tmp, "marked.txt"), FILE_ATTRIBUTE_HIDDEN)
        _mark(os.path.join(self.tmp, "desktop.ini"),
              FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)
        self.flm = FileListManager(get_config())

    def _listing(self, show_hidden):
        self.flm.show_hidden = show_hidden
        result = self.flm.compute_listing(Path(self.tmp))
        self.assertTrue(result["ok"])
        return sorted(p.name for p in result["files"])

    def test_hidden_off_drops_them(self):
        self.assertEqual(self._listing(False), ["visible.txt"])

    def test_hidden_on_shows_them(self):
        self.assertEqual(self._listing(True),
                         [".dotfile", "desktop.ini", "marked.txt",
                          "visible.txt"])

    def test_completion_drops_them_too(self):
        """Tab completion mirrors the panes' toggle (#258), so it has to mirror
        this half of it as well."""
        comp = FilepathCompleter(base_directory=self.tmp, show_hidden=False)
        self.assertEqual(comp.get_candidates("", 0), ["visible.txt"])
        comp = FilepathCompleter(base_directory=self.tmp, show_hidden=True)
        self.assertIn("marked.txt", comp.get_candidates("", 0))

    def test_a_typed_dot_does_not_resurrect_an_attribute_hidden_entry(self):
        """Typing a dot asks for dot-names — the shell convention. There is no
        such thing to type for an attribute, so it stays hidden."""
        comp = FilepathCompleter(base_directory=self.tmp, show_hidden=False)
        self.assertEqual(comp.get_candidates(".", 1), [".dotfile"])


# ---------------------------------------------------------------------------
# The predicate and the filter, on any platform
# ---------------------------------------------------------------------------


class IsHiddenCombinesNameAndAttribute(unittest.TestCase):
    def test_a_dot_name_is_hidden_anywhere(self):
        self.assertTrue(dir_scan.is_hidden(".bashrc"))
        self.assertTrue(dir_scan.is_hidden(".bashrc", {"hidden": False}))

    def test_the_attribute_hides_a_plain_name(self):
        self.assertTrue(dir_scan.is_hidden("pagefile.sys", {"hidden": True}))

    def test_a_plain_entry_is_not_hidden(self):
        self.assertFalse(dir_scan.is_hidden("readme.md"))
        self.assertFalse(dir_scan.is_hidden("readme.md", {"hidden": False}))

    def test_a_missing_record_falls_back_to_the_name(self):
        """Every backend fills ``hidden`` in, but a caller may hold a record
        built before it existed; that must read as 'not marked', not crash."""
        self.assertFalse(dir_scan.is_hidden("readme.md", {}))
        self.assertFalse(dir_scan.is_hidden("readme.md", None))
        self.assertTrue(dir_scan.is_hidden(".bashrc", {}))

    def test_hidden_from_stat_is_false_without_the_field(self):
        """Every non-Windows ``stat_result`` lacks ``st_file_attributes``."""
        class _Plain:
            pass

        self.assertFalse(dir_scan.hidden_from_stat(_Plain()))

    def test_hidden_from_stat_survives_a_synthesized_record(self):
        """A backend that builds its own ``stat_result`` from a tuple — the
        archive one does — leaves the field present but None on Windows."""
        st = os.stat_result((0o100644, 0, 0, 1, 0, 0, 10, 0, 0, 0))
        self.assertIsNone(getattr(st, "st_file_attributes", None) if _WINDOWS
                          else None)
        self.assertFalse(dir_scan.hidden_from_stat(st))


class TheListingFilterUsesTheRecord(unittest.TestCase):
    """The pane filter itself, driven by hand-built records so it is checked on
    every platform, not only where the attribute exists."""

    def setUp(self):
        self.flm = FileListManager(get_config())

    def _listing(self, show_hidden):
        base = Path(os.path.dirname(os.path.abspath(__file__)))
        entries = [
            (base / "visible.txt", _record(hidden=False)),
            (base / "marked.txt", _record(hidden=True)),
            (base / ".dotfile", _record(hidden=False)),
        ]

        class _Dir:
            def listdir_attrs(self):
                return entries

            def __str__(self):
                return str(base)

        self.flm.show_hidden = show_hidden
        result = self.flm.compute_listing(_Dir())
        self.assertTrue(result["ok"])
        return sorted(p.name for p in result["files"])

    def test_a_marked_record_is_filtered_out(self):
        self.assertEqual(self._listing(False), ["visible.txt"])

    def test_showing_hidden_keeps_everything(self):
        self.assertEqual(self._listing(True),
                         [".dotfile", "marked.txt", "visible.txt"])


def _record(*, hidden):
    return {"is_dir": False, "is_link": False, "size": 1, "mtime": 0.0,
            "hidden": hidden, "ok": True}


if __name__ == "__main__":
    unittest.main()
