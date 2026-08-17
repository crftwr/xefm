"""
Recursive content (grep) search for the PuiKit XeFMApp.

Covers the pane-independent search core behind ``show_content_search`` — the
streaming tree walk (``_iter_content_matches``), the BOM-aware binary/encoding
sniff (``_sniff_text_encoding``), the pane-filter narrowing, and result
navigation (``_go_to_content_hit``). The
results now stream into the progressive ``ProgressiveSearchDialog`` (see
``test_progressive_search_dialog.py``); the walk itself is a cancellable
generator, exercised here directly.
"""

import codecs
import os
import re
import sys
import tempfile
import shutil
import threading
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


def _bare_app(show_hidden=False):
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app.flm = type("_FLM", (), {"show_hidden": show_hidden})()
    return app


class WalkGrep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, relpath, content, mode="w"):
        p = os.path.join(self.tmp, relpath)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode) as f:
            f.write(content)
        return p

    def _grep(self, pattern, name_filter="", **kw):
        app = _bare_app(**kw)
        return list(app._iter_content_matches(
            Path(self.tmp), re.compile(pattern, re.IGNORECASE), threading.Event(),
            name_filter=name_filter))

    def test_finds_matching_line_with_number(self):
        self._write("a.txt", "alpha\nneedle here\ngamma\n")
        hits = self._grep("needle")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line"], 2)
        self.assertEqual(hits[0]["text"], "needle here")
        self.assertEqual(hits[0]["path"].name, "a.txt")

    def test_recurses_into_subdirectories(self):
        self._write("sub/deep/b.txt", "TODO: fix this\n")
        hits = self._grep("todo")  # case-insensitive
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"].name, "b.txt")

    def test_skips_binary_files(self):
        self._write("bin.dat", "match\x00more match\n", mode="w")
        hits = self._grep("match")
        self.assertEqual(hits, [])

    def test_skips_hidden_unless_shown(self):
        self._write(".secret.txt", "password\n")
        self.assertEqual(self._grep("password"), [])
        self.assertEqual(len(self._grep("password", show_hidden=True)), 1)

    def test_walk_is_uncapped(self):
        # The walk yields every match; the result cap now lives in the dialog.
        self._write("big.txt", "hit\n" * 50)
        self.assertEqual(len(self._grep("hit")), 50)

    def test_cancel_stops_the_walk(self):
        self._write("big.txt", "hit\n" * 50)
        app = _bare_app()
        cancel = threading.Event()
        cancel.set()  # already cancelled -> generator yields nothing
        hits = list(app._iter_content_matches(
            Path(self.tmp), re.compile("hit"), cancel))
        self.assertEqual(hits, [])

    def test_no_matches_returns_empty(self):
        self._write("a.txt", "nothing interesting\n")
        self.assertEqual(self._grep("zzz"), [])

    def test_name_filter_narrows_to_matching_files(self):
        # The pane filter reaches the grep (issue #305): only files it matches
        # are read, with the same case-insensitive whole-name glob semantics.
        self._write("a.txt", "needle\n")
        self._write("b.nim", "needle\n")
        self._write("c.TXT", "needle\n")
        hits = self._grep("needle", name_filter="*.txt")
        self.assertEqual(sorted(h["path"].name for h in hits), ["a.txt", "c.TXT"])

    def test_name_filter_still_descends_directories(self):
        # The filter applies to files only, as in the pane listing — a directory
        # not matching *.txt is still walked for the .txt files inside it.
        self._write("sub/deep/a.txt", "needle\n")
        self._write("sub/deep/b.nim", "needle\n")
        hits = self._grep("needle", name_filter="*.txt")
        self.assertEqual([h["path"].name for h in hits], ["a.txt"])

    def test_empty_name_filter_searches_everything(self):
        self._write("a.txt", "needle\n")
        self._write("b.nim", "needle\n")
        self.assertEqual(len(self._grep("needle", name_filter="")), 2)

    def test_utf8_bom_file_matches_anchored_pattern_on_line_1(self):
        # The BOM is consumed by the codec (utf-8-sig), so a ^-anchored pattern
        # matches the true first characters of the file (issue #305).
        self._write("bom.txt", b"\xef\xbb\xbf#import winim\n", mode="wb")
        hits = self._grep("^#import")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["text"], "#import winim")

    def test_utf16_bom_files_are_searched_not_skipped_as_binary(self):
        # UTF-16 text is full of NULs; the BOM must win over the NUL sniff
        # (issue #305 — Windows Notepad's "Unicode" and PowerShell output).
        self._write("le.txt", "let clip = 1\n日本語\n".encode("utf-16"), mode="wb")
        self._write("be.txt",
                    codecs.BOM_UTF16_BE + "let clip = 2\n".encode("utf-16-be"),
                    mode="wb")
        hits = self._grep("let clip")
        self.assertEqual(sorted(h["path"].name for h in hits), ["be.txt", "le.txt"])
        self.assertEqual(len(self._grep("日本語")), 1)


class SniffTextEncoding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, data):
        p = os.path.join(self.tmp, "f")
        with open(p, "wb") as fh:
            fh.write(data)
        return Path(p)

    def _sniff(self, data):
        return xefm_app.XeFMApp._sniff_text_encoding(self._file(data))

    def test_plain_text_reads_as_utf8(self):
        self.assertEqual(self._sniff(b"hello world"), "utf-8")

    def test_nul_byte_is_binary(self):
        self.assertIsNone(self._sniff(b"hello\x00world"))

    def test_empty_is_not_textual(self):
        self.assertIsNone(self._sniff(b""))

    def test_utf8_bom_reads_as_utf8_sig(self):
        self.assertEqual(self._sniff(codecs.BOM_UTF8 + b"hello"), "utf-8-sig")

    def test_utf16_boms_read_as_utf16(self):
        for bom in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
            self.assertEqual(self._sniff(bom + b"h\x00i\x00"), "utf-16")

    def test_utf32_boms_read_as_utf32(self):
        for bom in (codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE):
            self.assertEqual(self._sniff(bom + b"h\x00\x00\x00"), "utf-32")


class Navigation(unittest.TestCase):
    def test_go_to_hit_moves_pane_and_cursor(self):
        tmp = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()   # outside the pane dir: not a listed row
        try:
            os.makedirs(os.path.join(tmp, "sub"))
            target = os.path.join(tmp, "sub", "hit.txt")
            open(target, "w").close()
            open(os.path.join(tmp, "sub", "other.txt"), "w").close()

            from puikit.backends import create_backend
            b = create_backend("memory"); b.open()
            # Temp state DB, never the real ~/.xefm/state.db: the app restores
            # each pane's sort mode, sort direction and filter from it, so the
            # developer's own last-used settings would otherwise decide where
            # the cursor lands in this listing.
            sm = XeFMStateManager(db_path=os.path.join(state_dir, "state.db"))
            app = xefm_app.XeFMApp(b, tmp, tmp, left_provided=True,
                                   right_provided=True, state_manager=sm)
            try:
                app._go_to_content_hit({"path": Path(target), "line": 1, "text": "x"})
                app._settle_listings()  # navigation lists on a worker; wait for it
                pane = app.active_pane()
                self.assertEqual(str(pane["path"]), os.path.join(tmp, "sub"))
                self.assertEqual(pane["files"][pane["focused_index"]].name, "hit.txt")
            finally:
                app.file_monitor.stop_monitoring()
                b.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
