"""File Details shows an entry's attributes (#789 B).

Beyond its own fields (path, type, size, dates, permissions), the dialog lists
every attribute that applies to the entry — tags, an ``ATTRIBUTES`` entry, an
extension's — written out in words. A value the pane already holds shows at
once; the rest is read for these entries while the dialog is open, and a value
of ``None`` shows no row.

Driven end-to-end on the headless memory backend, as
test_file_details_disk_usage.py does.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import attributes  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from xefm.user_api import load_user_entries  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


def _kind(directory, entries):
    return [{"txt": "T", "md": None}.get(e.name.rsplit(".", 1)[-1]) for e in entries]


class FileDetailsAttributes(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.cfgdir = tempfile.mkdtemp()
        for name in ("a.txt", "b.md"):
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write("x" * 10)
        self.calls = []

        def seconds(directory, entries):
            self.calls.append([e.name for e in entries])
            return [125 for _ in entries]

        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app._settle_listings()
        # After the app is built: starting it loads the (default) config,
        # which clears every registration.
        load_user_entries(types.SimpleNamespace(ATTRIBUTES={
            "kind": {"label": "Kind", "type": "enum", "read": _kind,
                     "values": {"T": {"label": "Text file"}}},
            "length": {"label": "Length", "type": "duration", "read": seconds,
                       "compute": "on_request"},
        }))

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        load_user_entries(types.SimpleNamespace())
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def _open(self, focus):
        """Open the dialog on ``focus``; returns it and every source it showed,
        the first as it opened."""
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(focus)
        pane["selected_files"] = set()
        sources = []
        real = xefm_app.show_markdown

        def opening(panel, source, **kw):
            sources.append(source)
            return real(panel, source, **kw)
        xefm_app.show_markdown = opening
        try:
            self.app.file_details()
        finally:
            xefm_app.show_markdown = real
        dialog = self.app.panel._layers[-1].widget
        orig = dialog.md.set_source

        def spy(src):
            orig(src)
            sources.append(src)
        dialog.md.set_source = spy
        return dialog, sources

    def _settle(self, sources):
        for _ in range(200):
            self.backend.run_animation_ticks()
            if len(sources) > 1 and "reading…" not in sources[-1]:
                return sources[-1]
            time.sleep(0.01)
        self.fail("attribute reads never settled")

    def test_values_are_read_and_written_in_words(self):
        dialog, sources = self._open("a.txt")
        final = self._settle(sources)
        self.assertIn("| Kind | Text file |", final)
        self.assertIn("| Length | 2:05 |", final)
        self.assertEqual(self.calls, [["a.txt"]])

    def test_an_entry_without_a_value_gets_no_row(self):
        dialog, sources = self._open("b.md")
        final = self._settle(sources)
        self.assertNotIn("| Kind |", final)
        self.assertIn("| Length | 2:05 |", final)

    def test_a_value_the_pane_holds_shows_at_once_and_is_not_read_again(self):
        pane = self.app.active_pane()
        store = attributes.store_of(pane)
        records = {str(p): a for p, a in pane["_listing_entries"]}
        a = next(p for p in pane["files"] if p.name == "a.txt")
        done = threading.Event()
        store.request("length", [a], records, on_done=lambda n, c: done.set())
        self.assertTrue(done.wait(3))
        self.calls.clear()
        dialog, sources = self._open("a.txt")
        self._settle(sources)
        self.assertEqual(self.calls, [])

    def test_closing_the_dialog_stops_the_reads(self):
        started, release = threading.Event(), threading.Event()
        seen = []

        def slow(directory, entries):
            seen.append(entries[0].name)
            started.set()
            release.wait(3)
            return [1] * len(entries)

        load_user_entries(types.SimpleNamespace(ATTRIBUTES={
            "slow": {"label": "Slow", "type": "count", "read": slow},
            "after": {"label": "After", "type": "count", "read": slow}}))
        dialog, sources = self._open("a.txt")
        self.assertIn("| Attributes | *reading…* |", sources[0])
        self.assertTrue(started.wait(3))
        dialog._close()
        release.set()
        time.sleep(0.1)
        # The second attribute is never asked for once the dialog is gone.
        self.assertEqual(seen, ["a.txt"])

if __name__ == "__main__":
    unittest.main()
