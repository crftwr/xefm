"""
Range selection: from the nearest marked item to the cursor (#266).

``select_range`` (Shift-Space) fills the span between the cursor and the nearest
already-selected item — a Shift-click done with the keyboard. The anchor is
looked for above the cursor first and only then below, so marking an item and
then moving either way reaches the same run with the same key. Nothing moves and
nothing outside the span is touched, which is what lets the open search bar run
the same operation over its own cursor (``isearch.select_range``).

Run with: python -m pytest test/test_select_range.py -v
"""

import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class SelectRange(unittest.TestCase):
    NAMES = ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        for name in self.NAMES:
            open(os.path.join(self.tmp, name), "w").close()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app._settle_listings()
        self.pane = self.app.active_pane()
        self.assertEqual([f.name for f in self.pane["files"]], self.NAMES)

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _select(self, *names):
        self.pane["selected_files"] = {str(f) for f in self.pane["files"]
                                       if f.name in names}

    def _selected(self):
        return sorted(os.path.basename(p) for p in self.pane["selected_files"])

    def _focused_name(self):
        return self.pane["files"][self.pane["focused_index"]].name

    # --- the span ----------------------------------------------------------

    def test_fills_from_the_mark_above_down_to_the_cursor(self):
        self._select("b.txt")
        self.pane["focused_index"] = 3               # d.txt
        self.app.dispatch("select_range")
        self.assertEqual(self._selected(), ["b.txt", "c.txt", "d.txt"])

    def test_fills_upwards_when_the_only_mark_is_below(self):
        # The fallback that keeps one key enough: mark an item, move *up*, and
        # the run still ends at the cursor.
        self._select("d.txt")
        self.pane["focused_index"] = 1               # b.txt
        self.app.dispatch("select_range")
        self.assertEqual(self._selected(), ["b.txt", "c.txt", "d.txt"])

    def test_the_nearest_mark_above_wins_over_one_further_up(self):
        self._select("a.txt", "c.txt")
        self.pane["focused_index"] = 4               # e.txt
        self.app.dispatch("select_range")
        self.assertEqual(self._selected(),
                         ["a.txt", "c.txt", "d.txt", "e.txt"])  # b.txt untouched

    def test_a_mark_above_wins_over_a_nearer_one_below(self):
        self._select("a.txt", "e.txt")
        self.pane["focused_index"] = 3               # d.txt
        self.app.dispatch("select_range")
        self.assertEqual(self._selected(),
                         ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"])

    def test_the_cursor_does_not_move(self):
        self._select("a.txt")
        self.pane["focused_index"] = 2
        self.app.dispatch("select_range")
        self.assertEqual(self._focused_name(), "c.txt")

    def test_runs_accumulate_and_nothing_is_ever_deselected(self):
        self._select("a.txt")
        self.pane["focused_index"] = 1
        self.app.dispatch("select_range")            # a..b
        self._select("a.txt", "b.txt", "d.txt")      # mark a third, further down
        self.pane["focused_index"] = 4
        self.app.dispatch("select_range")            # d..e
        self.assertEqual(self._selected(),
                         ["a.txt", "b.txt", "d.txt", "e.txt"])  # c.txt still out

    def test_pressing_it_again_changes_nothing(self):
        self._select("b.txt")
        self.pane["focused_index"] = 3
        self.app.dispatch("select_range")
        before = self._selected()
        self.app.dispatch("select_range")
        self.assertEqual(self._selected(), before)

    # --- nothing to reach --------------------------------------------------

    def test_no_selection_at_all_is_a_no_op(self):
        self.pane["focused_index"] = 2
        self.app.dispatch("select_range")
        self.assertEqual(self._selected(), [])

    def test_only_the_cursor_marked_is_a_no_op(self):
        self._select("c.txt")
        self.pane["focused_index"] = 2               # c.txt itself
        self.app.dispatch("select_range")
        self.assertEqual(self._selected(), ["c.txt"])

    # --- the messages the log pane shows -----------------------------------

    def test_messages(self):
        flm = self.app.flm
        self.assertEqual(flm.select_range(self.pane), (False, "No selection"))
        self._select("c.txt")
        self.pane["focused_index"] = 2
        self.assertEqual(flm.select_range(self.pane),
                         (False, "No other selected item"))
        self.pane["focused_index"] = 3
        self.assertEqual(flm.select_range(self.pane), (True, "Selected 1 item"))
        self.pane["focused_index"] = 4
        self.assertEqual(flm.select_range(self.pane), (True, "Selected 1 item"))
        self._select("a.txt", "b.txt")
        self.pane["focused_index"] = 1
        ok, message = flm.select_range(self.pane)
        self.assertTrue(ok)
        self.assertIn("already selected", message)

    # --- the keymap --------------------------------------------------------

    def test_default_bindings(self):
        from xefm._config import Config
        self.assertEqual(Config.KEY_BINDINGS["select_range"], ["Shift-SPACE"])
        # The key it took over, left unbound rather than moved: nothing else
        # says "range", and SPACE already marks and moves.
        self.assertEqual(Config.KEY_BINDINGS["toggle_select_up"], [])

    def test_the_search_bar_has_its_own_key_for_it(self):
        # Shift on a printable cannot reach an action inside the pattern field
        # (nor a POSIX terminal at all), so the same operation is a Ctrl chord
        # there — and the two contexts keep their own defaults.
        from xefm.actions import FILER, ISEARCH
        keys = self.app.keys
        self.assertEqual(keys.get_keys_for_action("select_range", FILER)[0],
                         ["Shift-SPACE"])
        self.assertEqual(
            keys.get_keys_for_action("isearch.select_range", ISEARCH)[0],
            ["Ctrl-Shift-SPACE"])
        # The unqualified name is the file list's alone; binding it in a config
        # must not reach into the search bar.
        self.assertEqual(keys.get_keys_for_action("select_range", ISEARCH)[0], [])

    def test_a_config_that_predates_this_keeps_its_own_shift_space(self):
        """XeFM never rewrites a config's KEY_BINDINGS, so an existing one still
        binds Shift-SPACE to 'toggle_select_up' — and that entry wins, because a
        config's own bindings are resolved before an action's built-in defaults
        (``KeyBindings._context_entries``). Such a config reaches the new action
        through Select → Select to Cursor until its owner edits the line, which is
        what the "Defaults that moved" table in doc/KEY_BINDINGS_FEATURE.md is
        for. The one outcome that would be wrong is the key doing *both*."""
        from puikit.event import Event, EventType
        from xefm._config import Config
        from xefm.actions import FILER
        from xefm.config import KeyBindings, printable_text_notice

        old = dict(Config.KEY_BINDINGS)
        old["toggle_select_up"] = ["Shift-SPACE"]
        del old["select_range"]
        keys = KeyBindings(old)
        event = Event(type=EventType.KEY, key="space", char=" ",
                      modifiers=frozenset({"shift"}))
        self.assertEqual(keys.find_action_for_event(event, context=FILER),
                         "toggle_select_up")
        # And nothing about either config is reported as a printable-key mistake.
        self.assertIsNone(printable_text_notice(old))
        self.assertIsNone(printable_text_notice(Config.KEY_BINDINGS))

    def test_the_select_menu_offers_it(self):
        # The one route for a key a POSIX terminal cannot deliver.
        select = next(item for item in self.app.menu_bar.menu.items
                      if getattr(item, "label", None) == "Select")
        labels = [getattr(i, "label", None) for i in select.submenu.items]
        self.assertIn("Select to Cursor", labels)


if __name__ == "__main__":
    unittest.main()
