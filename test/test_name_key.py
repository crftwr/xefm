"""
The one string a pane compares an entry by (``xefm.name_key``).

Two things were wrong before this existed, and both are covered here.

**Normalization.** A name stored NFD is a base character plus a combining mark,
so a plain codepoint comparison sorted ``が.txt`` after every ``か``-something
instead of between ``か`` and ``き``, and an i-search typed at an IME — which
emits NFC — never matched it at all. (The two forms of one name cannot sit in
the same directory: APFS lookup is normalization-insensitive, so they are the
same file. Decomposed names arrive from elsewhere — HFS+ volumes, network
mounts, archives — and from anything that wrote them that way.)

**Scope (#383).** A search-results pane shows ``sub/dir/a.txt`` but ordered,
filtered and searched by the bare ``a.txt``, so the name column looked unsorted
and the directory part of what was on screen could not be matched.
"""

import os
import shutil
import sys
import tempfile
import unicodedata
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import name_key  # noqa: E402
from xefm import _config  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.path import Path  # noqa: E402


def nfd(text):
    return unicodedata.normalize("NFD", text)


def nfc(text):
    return unicodedata.normalize("NFC", text)


class NameKeyUnit(unittest.TestCase):
    """The pure functions."""

    def test_nfc_composes_decomposed_text(self):
        self.assertEqual(name_key.nfc(nfd("が.txt")), nfc("が.txt"))

    def test_nfc_leaves_composed_text_alone(self):
        composed = nfc("が.txt")
        self.assertEqual(name_key.nfc(composed), composed)

    def test_rel_name_without_root_is_the_basename(self):
        self.assertEqual(name_key.rel_name(Path("/a/b/c.txt")), "c.txt")

    def test_rel_name_under_root_keeps_the_directories(self):
        self.assertEqual(
            name_key.rel_name(Path("/a/b/sub/c.txt"), Path("/a/b")), "sub/c.txt")

    def test_rel_name_outside_root_falls_back_to_the_basename(self):
        self.assertEqual(
            name_key.rel_name(Path("/other/c.txt"), Path("/a/b")), "c.txt")

    def test_rel_name_of_the_root_itself_falls_back_to_the_basename(self):
        # Nothing is left after stripping the root, so there is no relative name
        # to show and the basename is the only sensible answer.
        self.assertEqual(name_key.rel_name(Path("/a/b"), Path("/a/b")), "b")

    def test_compare_name_is_the_relative_name_in_nfc(self):
        self.assertEqual(
            name_key.compare_name(Path("/r/" + nfd("が")), Path("/r")),
            nfc("が"))


class _PaneCase(unittest.TestCase):
    """A real directory on disk, listed through FileListManager."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.flm = FileListManager(_config.Config())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, rel):
        p = os.path.join(self.tmp, rel)
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(p, "w") as f:
            f.write("x")
        return Path(p)

    def _pane(self, **kw):
        pane = {
            "path": Path(self.tmp), "focused_index": 0, "scroll_offset": 0,
            "files": [], "selected_files": set(), "sort_mode": "name",
            "sort_reverse": False, "filter_pattern": "",
        }
        pane.update(kw)
        return pane

    def _names(self, pane):
        return [nfc(p.name) for p in pane["files"]]


class NormalizedListing(_PaneCase):
    """A directory pane holding a decomposed name."""

    def test_a_decomposed_name_sorts_where_it_looks_like_it_belongs(self):
        # Decomposed, が is か + a combining mark, which by codepoint lands it
        # between か.txt and かア.txt — ahead of a name it plainly sorts after.
        self._touch(nfd("が.txt"))
        self._touch(nfc("かア.txt"))
        self._touch(nfc("か.txt"))
        pane = self._pane()
        self.flm.refresh_files(pane)
        self.assertEqual(
            self._names(pane),
            [nfc("か.txt"), nfc("かア.txt"), nfc("が.txt")])

    def test_isearch_typed_in_nfc_finds_a_decomposed_name(self):
        self._touch(nfd("が.txt"))
        pane = self._pane()
        self.flm.refresh_files(pane)
        hits = self.flm.find_matches(pane, nfc("が"), match_all=True,
                                     return_indices_only=True)
        self.assertEqual(len(hits), 1)

    def test_isearch_typed_in_nfd_finds_a_composed_name(self):
        # The other direction: a pasted decomposed query still finds the file.
        self._touch(nfc("が.txt"))
        pane = self._pane()
        self.flm.refresh_files(pane)
        hits = self.flm.find_matches(pane, nfd("が"), match_all=True,
                                     return_indices_only=True)
        self.assertEqual(len(hits), 1)

    def test_filter_typed_in_nfc_keeps_a_decomposed_name(self):
        self._touch(nfd("が.txt"))
        self._touch("other.txt")
        pane = self._pane(filter_pattern="*" + nfc("が") + "*")
        self.flm.refresh_files(pane)
        self.assertEqual(self._names(pane), [nfc("が.txt")])

    def test_extension_sort_normalizes_too(self):
        # Same shape one level down: .が written NFD sorts ahead of .かア by
        # codepoint and behind it once composed.
        self._touch("a." + nfd("が"))
        self._touch("b." + nfc("かア"))
        pane = self._pane(sort_mode="ext")
        self.flm.refresh_files(pane)
        self.assertEqual([p.name for p in pane["files"]],
                         ["b." + nfc("かア"), "a." + nfd("が")])


class VirtualPaneScope(_PaneCase):
    """#383 — a search-results pane compares the path it shows."""

    def _virtual_pane(self, paths, **kw):
        pane = self._pane(**kw)
        pane["virtual"] = {"kind": "search", "root": Path(self.tmp),
                           "mode": "filename", "query": "q",
                           "results": list(paths), "meta": {}}
        return pane

    def _rel(self, pane):
        root = str(self.tmp)
        return [str(p)[len(root):].lstrip("/\\") for p in pane["files"]]

    def test_sort_orders_by_the_relative_path_shown(self):
        paths = [self._touch("bbb/a.txt"), self._touch("aaa/z.txt")]
        pane = self._virtual_pane(paths)
        self.flm.refresh_files(pane)
        # By basename this would be a.txt then z.txt; by what the pane displays
        # it is aaa/ before bbb/.
        self.assertEqual(self._rel(pane), ["aaa/z.txt", "bbb/a.txt"])

    def test_isearch_matches_a_directory_component(self):
        paths = [self._touch("alpha/one.txt"), self._touch("beta/two.txt")]
        pane = self._virtual_pane(paths)
        self.flm.refresh_files(pane)
        hits = self.flm.find_matches(pane, "alpha", match_all=True,
                                     return_indices_only=True)
        self.assertEqual([self._rel(pane)[i] for i in hits], ["alpha/one.txt"])

    def test_filter_matches_a_directory_component(self):
        paths = [self._touch("alpha/one.txt"), self._touch("beta/two.txt")]
        pane = self._virtual_pane(paths, filter_pattern="*alpha*")
        self.flm.refresh_files(pane)
        self.assertEqual(self._rel(pane), ["alpha/one.txt"])

    def test_a_directory_pane_is_unaffected(self):
        # The relative name of a direct child is its basename, so an ordinary
        # pane sorts exactly as it did.
        for n in ("c.txt", "a.txt", "b.txt"):
            self._touch(n)
        pane = self._pane()
        self.flm.refresh_files(pane)
        self.assertEqual(self._names(pane), ["a.txt", "b.txt", "c.txt"])


class SearchWalk(_PaneCase):
    """The directory walk that feeds a search-results pane matches the same way.

    Fixing the pane alone would not have been enough: a decomposed name the walk
    never yields cannot be found in the results either.
    """

    def _found(self, pattern):
        import threading
        from types import SimpleNamespace
        from xefm.app import XeFMApp
        app = SimpleNamespace(flm=SimpleNamespace(show_hidden=False))
        hits = XeFMApp._iter_filename_matches(
            app, Path(self.tmp), pattern, threading.Event())
        return sorted(nfc(p.name) for p in hits)

    def test_filename_search_finds_a_decomposed_name(self):
        self._touch(nfd("が.txt"))
        self._touch("other.txt")
        self.assertEqual(self._found(nfc("が") + "*"), [nfc("が.txt")])

    def test_filename_search_accepts_a_decomposed_query(self):
        self._touch(nfc("が.txt"))
        self.assertEqual(self._found(nfd("が") + "*"), [nfc("が.txt")])


class ComparedNameIsNotAPath(_PaneCase):
    """The compared name is for ordering and matching, never for opening."""

    def test_the_listing_keeps_the_on_disk_name_verbatim(self):
        decomposed = nfd("が.txt")
        self._touch(decomposed)
        pane = self._pane()
        self.flm.refresh_files(pane)
        entry = pane["files"][0]
        # The compared name composed it; the Path did not, so the entry still
        # addresses the bytes the filesystem actually holds.
        self.assertEqual(
            pane["file_info"][str(entry)]["cmp_name"], nfc("が.txt"))
        self.assertEqual(entry.name, decomposed)
        self.assertTrue(entry.exists())


class BatchRename(_PaneCase):
    """The rename preview runs on the same composed name the pane displays.

    Finder settles two of these: it normalizes before matching, and it flags a
    rename that lands on an existing file under a different spelling of one name.
    It parts company on the third — it writes NFD, as HFS+ did, where XeFM writes
    NFC on every platform.
    """

    def _preview(self, search, replace, names):
        from xefm.batch_rename_dialog import compute_preview
        files = [self._touch(n) for n in names]
        return compute_preview(files, search, replace)

    def test_an_ime_typed_pattern_matches_a_decomposed_name(self):
        rows = self._preview(nfc("が"), "X", [nfd("が.txt")])
        self.assertEqual(rows[0]["new"], "X.txt")

    def test_a_pasted_decomposed_pattern_matches_a_composed_name(self):
        rows = self._preview(nfd("が"), "X", [nfc("が.txt")])
        self.assertEqual(rows[0]["new"], "X.txt")

    def test_an_unmatched_name_is_left_exactly_as_it_was(self):
        # The apply loop skips a row whose original equals its new name, so this
        # is what keeps a rename from re-spelling files it was not asked about.
        rows = self._preview("nomatch", "X", [nfd("が.txt")])
        self.assertEqual(rows[0]["original"], rows[0]["new"])

    def test_the_untouched_part_of_a_renamed_name_comes_out_composed(self):
        rows = self._preview(r"\.txt$", ".md", [nfd("が.txt")])
        self.assertEqual(rows[0]["new"], nfc("が.md"))
        self.assertTrue(unicodedata.is_normalized("NFC", rows[0]["new"]))

    def test_a_decomposed_replacement_does_not_make_a_mixed_name(self):
        rows = self._preview("^a", nfd("が"), ["ab.txt"])
        self.assertEqual(rows[0]["new"], nfc("が") + "b.txt")
        self.assertTrue(unicodedata.is_normalized("NFC", rows[0]["new"]))

    def test_two_rows_landing_on_one_file_collide(self):
        # Before, these keyed apart and both renames ran: on APFS the second
        # silently replaced the first, since the two spellings are one file.
        rows = self._preview("^[XY]", "", ["X" + nfd("が.txt"),
                                           "Y" + nfc("が.txt")])
        self.assertEqual({r["new"] for r in rows}, {nfc("が.txt")})
        self.assertTrue(all(r["conflict"] for r in rows))


if __name__ == "__main__":
    unittest.main()
