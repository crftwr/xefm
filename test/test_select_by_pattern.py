"""
Select / unselect by pattern, and select the same extension (#544).

``select_by_pattern`` and ``unselect_by_pattern`` prompt for a pattern written
as the ';' filter takes it — several globs separated by spaces, or the name of
a filter a config defines — and add the matching files to the selection or take
them out of it. Matching is the filter's own (composed, case-insensitive,
against the pane-relative name a search-results pane shows), so a pattern
selects exactly the files it would have filtered the pane down to. Directories
are never touched.

``select_same_extension`` adds every file sharing the cursor file's extension,
with no prompt.

Run with: python -m pytest test/test_select_by_pattern.py -v
"""

import os
import shutil
import sys
import tempfile
import unicodedata
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import keymap_presets  # noqa: E402
from xefm import app as xefm_app  # noqa: E402
from xefm import filters  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class SelectByPattern(unittest.TestCase):
    NAMES = ["a.jpg", "b.JPG", "c.png", "d.txt", "README", ".bashrc"]
    DIRS = ["photos.jpg"]

    def setUp(self):
        # realpath: macOS TMPDIR is behind a /var -> /private/var symlink.
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.state_dir = tempfile.mkdtemp()
        for name in self.NAMES:
            open(os.path.join(self.tmp, name), "w").close()
        for name in self.DIRS:
            os.mkdir(os.path.join(self.tmp, name))
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app.flm.show_hidden = True
        self.app._relist(self.app.active_pane())
        self.app._settle_listings()
        self.pane = self.app.active_pane()

    def tearDown(self):
        filters.clear()
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _selected(self):
        return sorted(os.path.basename(p) for p in self.pane["selected_files"])

    def _select(self, *names):
        self.pane["selected_files"] = {str(f) for f in self.pane["files"]
                                       if f.name in names}

    def _prompt(self, action, text):
        """Run ``action``, type ``text`` into its prompt and press Enter;
        returns the arguments the prompt was opened with."""
        seen = {}
        with mock.patch("xefm.app.show_history_input",
                        lambda panel, items, **kw: seen.update(items=items, **kw)):
            self.app.dispatch(action)
        seen["on_accept"](text)
        return seen

    def _focus(self, name):
        self.pane["focused_index"] = next(
            i for i, f in enumerate(self.pane["files"]) if f.name == name)

    # --- select / unselect by pattern ---------------------------------------

    def test_pattern_selects_matching_files_case_insensitively(self):
        self._prompt("select_by_pattern", "*.jpg")
        self.assertEqual(self._selected(), ["a.jpg", "b.JPG"])

    def test_several_patterns_separated_by_spaces(self):
        self._prompt("select_by_pattern", "*.jpg *.png")
        self.assertEqual(self._selected(), ["a.jpg", "b.JPG", "c.png"])

    def test_directories_are_never_selected(self):
        self._prompt("select_by_pattern", "*")
        self.assertNotIn("photos.jpg", self._selected())
        self.assertEqual(len(self._selected()), len(self.NAMES))

    def test_select_adds_to_the_existing_selection(self):
        self._select("d.txt")
        self._prompt("select_by_pattern", "*.png")
        self.assertEqual(self._selected(), ["c.png", "d.txt"])

    def test_unselect_removes_only_the_matches(self):
        self._select("a.jpg", "b.JPG", "c.png", "photos.jpg")
        self._prompt("unselect_by_pattern", "*.jpg")
        self.assertEqual(self._selected(), ["c.png", "photos.jpg"])

    def test_pattern_is_recorded_in_the_filter_history(self):
        self._prompt("select_by_pattern", "*.png")
        self.assertEqual(self.app._filter_history()[0], "*.png")
        # ...and the next prompt offers it, as the Filter picker does.
        seen = self._prompt("unselect_by_pattern", "*.png")
        self.assertIn("*.png", seen["items"])

    def test_defined_filter_by_name(self):
        filters.register("pictures", globs=("*.jpg", "*.png"))
        seen = self._prompt("select_by_pattern", "pictures")
        self.assertEqual(self._selected(), ["a.jpg", "b.JPG", "c.png"])
        self.assertEqual(seen["to_text"](filters.rows()[0]), "pictures")
        # A defined filter has its own row; it is not recorded as a pattern.
        self.assertNotIn("pictures", self.app._filter_history())

    def test_defined_predicate_filter_sees_real_sizes(self):
        with open(os.path.join(self.tmp, "d.txt"), "w") as f:
            f.write("x" * 100)
        self.app._relist(self.pane)
        self.app._settle_listings()
        filters.register("big", match=lambda e: e.size > 10)
        self._prompt("select_by_pattern", "big")
        self.assertEqual(self._selected(), ["d.txt"])

    def test_predicate_that_raises_selects_nothing(self):
        filters.register("broken", match=lambda e: 1 / 0)
        ok, _msg = self.app.flm.select_by_pattern(self.pane, "broken")
        self.assertFalse(ok)
        self.assertEqual(self._selected(), [])

    def test_no_match_is_reported(self):
        ok, msg = self.app.flm.select_by_pattern(self.pane, "*.zip")
        self.assertFalse(ok)
        self.assertIn("No files", msg)

    def test_decomposed_name_matches_composed_pattern(self):
        nfd = unicodedata.normalize("NFD", "café.txt")
        open(os.path.join(self.tmp, nfd), "w").close()
        self.app._relist(self.pane)
        self.app._settle_listings()
        self.app.flm.select_by_pattern(self.pane, "café*")
        self.assertEqual(len(self.pane["selected_files"]), 1)

    # --- select same extension ----------------------------------------------

    def test_same_extension_ignores_case(self):
        self._focus("b.JPG")
        self.app.dispatch("select_same_extension")
        self.assertEqual(self._selected(), ["a.jpg", "b.JPG"])

    def test_same_extension_without_one_selects_the_others_without(self):
        self._focus("README")
        self.app.dispatch("select_same_extension")
        self.assertEqual(self._selected(), [".bashrc", "README"])

    def test_same_extension_on_a_directory_does_nothing(self):
        self._focus("photos.jpg")
        ok, _msg = self.app.flm.select_same_extension(self.pane)
        self.assertFalse(ok)
        self.assertEqual(self._selected(), [])


class SelectByPatternKeys(unittest.TestCase):
    """' selects and " unselects — beside the filter's ; and :, and matched by
    the glyph, so the terminal's bare character and the desktop's Shift on the
    quote key reach the same action."""

    def setUp(self):
        from puikit import Event, EventType
        from xefm import actions as xa
        from xefm._config import Config
        from xefm.config import KeyBindings
        self.kb = KeyBindings(keymap_presets.table(keymap_presets.AFX))
        self.filer = xa.FILER
        self.key = lambda name, char, mods=(): Event(
            type=EventType.KEY, key=name, char=char, modifiers=frozenset(mods))

    def _action(self, event):
        return self.kb.find_action_for_event(event, False, self.filer)

    def test_quote_selects(self):
        self.assertEqual(self._action(self.key("'", "'")), "select_by_pattern")

    def test_double_quote_unselects(self):
        self.assertEqual(self._action(self.key('"', '"')), "unselect_by_pattern")
        self.assertEqual(self._action(self.key("'", '"', {"shift"})),
                         "unselect_by_pattern")


class SelectByPatternVirtual(unittest.TestCase):
    """On a search-results pane the compared name is the path below the search
    root, as the filter compares it."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.state_dir = tempfile.mkdtemp()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app._settle_listings()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _write(self, rel):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
        return Path(p)

    def test_pattern_matches_the_pane_relative_name(self):
        a = self._write("sub/a.txt")
        b = self._write("other/b.txt")
        self.app._feed_search_results("filename", [a, b], Path(self.tmp), "txt")
        self.app._settle_listings()
        pane = self.app.active_pane()
        self.assertIsNotNone(pane["virtual"])
        self.app.flm.select_by_pattern(pane, "sub/*")
        self.assertEqual(pane["selected_files"], {str(a)})


if __name__ == "__main__":
    unittest.main()
