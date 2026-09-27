"""A text field over its history (:mod:`xefm.history_input_dialog`).

The dialog behind Import List from Command and the ';' Filter prompt. What is
under test is the contract that makes it different from the picker it
replaced there:

- Enter uses the *field*, always — so typing a prefix of an old command runs
  the prefix, not the old command the typing matched.
- Focus is on one side at a time: typing highlights nothing; ↓ highlights a
  row and copies its text into the field.
- Copying a row in does not re-filter (the list would collapse to that row);
  editing the copied text does, and the edit becomes the query.
- ↑ past the first row, or Esc, returns to typing with the typed text back.

Run with: python -m pytest test/test_history_input_dialog.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit.event import Event, EventType  # noqa: E402

from xefm import filters  # noqa: E402
from xefm.history_input_dialog import HistoryInputDialog  # noqa: E402


def _key(name, mods=(), char=None):
    return Event(type=EventType.KEY, key=name, modifiers=frozenset(mods), char=char)


def _type(dialog, text):
    for ch in text:
        dialog.handle_event(_key(ch, char=ch))


HISTORY = ["rg -l TODO", "git ls-files -m", "rg -l FIXME"]


class Typing(unittest.TestCase):
    def setUp(self):
        self.used = []
        self.d = HistoryInputDialog(HISTORY, on_accept=self.used.append)

    def test_nothing_is_highlighted_while_typing(self):
        _type(self.d, "rg")
        self.assertFalse(self.d.browsing)
        self.assertEqual(self.d.list.selected, -1)

    def test_typing_narrows_the_history(self):
        _type(self.d, "FIX")
        self.assertEqual(self.d.filtered, ["rg -l FIXME"])

    def test_enter_uses_the_typed_text_even_where_it_matches_a_row(self):
        _type(self.d, "rg -l")
        self.assertEqual(len(self.d.filtered), 2)       # two old commands match
        self.d.handle_event(_key("enter"))
        self.assertEqual(self.used, ["rg -l"])

    def test_esc_while_typing_cancels(self):
        cancelled = []
        self.d.on_cancel = lambda: cancelled.append(True)
        self.d.handle_event(_key("escape"))
        self.assertEqual(cancelled, [True])
        self.assertEqual(self.used, [])

    def test_up_while_typing_does_nothing(self):
        self.d.handle_event(_key("up"))
        self.assertFalse(self.d.browsing)


class Browsing(unittest.TestCase):
    def setUp(self):
        self.used = []
        self.d = HistoryInputDialog(HISTORY, on_accept=self.used.append)

    def test_down_highlights_the_first_row_and_copies_it_in(self):
        self.d.handle_event(_key("down"))
        self.assertTrue(self.d.browsing)
        self.assertEqual(self.d.list.selected, 0)
        self.assertEqual(self.d.field.text, "rg -l TODO")

    def test_moving_copies_each_row_and_does_not_refilter(self):
        _type(self.d, "rg")
        self.d.handle_event(_key("down"))
        self.d.handle_event(_key("down"))
        self.assertEqual(self.d.field.text, "rg -l FIXME")
        # Still both rg rows — the copied text did not become the query.
        self.assertEqual(self.d.filtered, ["rg -l TODO", "rg -l FIXME"])
        self.assertEqual(self.d.query, "rg")

    def test_down_stops_at_the_last_row(self):
        for _ in range(10):
            self.d.handle_event(_key("down"))
        self.assertEqual(self.d.list.selected, len(HISTORY) - 1)

    def test_enter_in_the_history_chooses_and_a_second_enter_uses(self):
        self.d.handle_event(_key("down"))
        self.d.handle_event(_key("down"))
        self.d.handle_event(_key("enter"))
        # Chosen: back in the field with the row's text, nothing used yet.
        self.assertFalse(self.d.browsing)
        self.assertEqual(self.d.field.text, "git ls-files -m")
        self.assertEqual(self.used, [])
        # The list did not collapse to the chosen row.
        self.assertEqual(self.d.filtered, HISTORY)
        self.d.handle_event(_key("enter"))
        self.assertEqual(self.used, ["git ls-files -m"])

    def test_a_chosen_row_can_be_edited_before_it_is_used(self):
        self.d.handle_event(_key("down"))          # "rg -l TODO"
        self.d.handle_event(_key("enter"))         # choose
        _type(self.d, " src")
        self.d.handle_event(_key("enter"))
        self.assertEqual(self.used, ["rg -l TODO src"])

    def test_up_past_the_first_row_puts_the_typed_text_back(self):
        _type(self.d, "rg")
        self.d.handle_event(_key("down"))
        self.d.handle_event(_key("up"))
        self.assertFalse(self.d.browsing)
        self.assertEqual(self.d.field.text, "rg")

    def test_esc_while_browsing_goes_back_to_typing_not_away(self):
        cancelled = []
        self.d.on_cancel = lambda: cancelled.append(True)
        _type(self.d, "git")
        self.d.handle_event(_key("down"))
        self.d.handle_event(_key("escape"))
        self.assertEqual(cancelled, [])
        self.assertFalse(self.d.browsing)
        self.assertEqual(self.d.field.text, "git")
        self.d.handle_event(_key("escape"))
        self.assertEqual(cancelled, [True])

    def test_editing_a_copied_row_makes_it_the_query(self):
        self.d.handle_event(_key("down"))          # "rg -l TODO"
        self.d.handle_event(_key("backspace"))     # "rg -l TOD"
        self.assertFalse(self.d.browsing)
        self.assertEqual(self.d.query, "rg -l TOD")
        self.assertEqual(self.d.filtered, ["rg -l TODO"])
        self.d.handle_event(_key("enter"))
        self.assertEqual(self.used, ["rg -l TOD"])


class Remove(unittest.TestCase):
    def test_the_remove_key_forgets_the_highlighted_row(self):
        forgotten = []
        d = HistoryInputDialog(
            list(HISTORY), on_remove=lambda v: forgotten.append(v) or True)
        d.handle_event(_key("down"))
        d.handle_event(_key("delete", mods=("shift",)))
        self.assertEqual(forgotten, ["rg -l TODO"])
        self.assertNotIn("rg -l TODO", d.all_items)
        # The next row slid up and is the one copied in now.
        self.assertEqual(d.field.text, "git ls-files -m")

    def test_while_typing_the_remove_key_is_the_fields_own(self):
        forgotten = []
        d = HistoryInputDialog(
            list(HISTORY), on_remove=lambda v: forgotten.append(v) or True)
        d.handle_event(_key("delete", mods=("shift",)))
        self.assertEqual(forgotten, [])

    def test_a_refused_removal_keeps_the_row(self):
        d = HistoryInputDialog(list(HISTORY), on_remove=lambda v: False)
        d.handle_event(_key("down"))
        self.assertFalse(d.remove_selected())
        self.assertEqual(d.all_items, HISTORY)

    def test_removing_the_last_row_goes_back_to_typing(self):
        d = HistoryInputDialog(["only"], on_remove=lambda v: True)
        d.handle_event(_key("down"))
        d.remove_selected()
        self.assertFalse(d.browsing)
        self.assertEqual(d.field.text, "")


class Clicks(unittest.TestCase):
    def test_a_click_copies_and_a_second_uses(self):
        used = []
        d = HistoryInputDialog(HISTORY, on_accept=used.append)
        with mock.patch("xefm.history_input_dialog.time.monotonic",
                        side_effect=[10.0, 10.2]):
            d._clicked(1, None)
            self.assertEqual(d.field.text, "git ls-files -m")
            self.assertEqual(used, [])
            d._clicked(1, None)
        self.assertEqual(used, ["git ls-files -m"])

    def test_two_slow_clicks_only_copy(self):
        used = []
        d = HistoryInputDialog(HISTORY, on_accept=used.append)
        with mock.patch("xefm.history_input_dialog.time.monotonic",
                        side_effect=[10.0, 11.0]):
            d._clicked(1, None)
            d._clicked(1, None)
        self.assertEqual(used, [])


class LabelsAndText(unittest.TestCase):
    def test_a_row_can_draw_one_thing_and_stand_for_another(self):
        rows = [("big", "Big files")]
        d = HistoryInputDialog(rows, to_label=lambda v: v[1],
                               to_text=lambda v: v[0])
        self.assertEqual(d.list.items, ["Big files"])
        _type(d, "Big")                     # filtering reads the label
        self.assertEqual(d.filtered, rows)
        d.handle_event(_key("down"))
        self.assertEqual(d.field.text, "big")   # the field gets the text

    def test_the_hint_follows_the_focus(self):
        d = HistoryInputDialog(HISTORY, on_remove=lambda v: True,
                               accept_label="run")
        self.assertIn("↓ history", d.hint())
        self.assertIn("Enter run", d.hint())
        self.assertNotIn("remove", d.hint())
        d.handle_event(_key("down"))
        self.assertIn("remove", d.hint())
        self.assertIn("Enter choose", d.hint())
        self.assertIn("Esc back", d.hint())


class FilterPrompt(unittest.TestCase):
    """The ';' prompt: a defined filter goes into the field as its name, the
    clear row as nothing, and Enter applies the field."""

    def setUp(self):
        from puikit.backends import create_backend
        from xefm import app as xefm_app
        from xefm.state_manager import XeFMStateManager
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(
            self.b, self.tmp, self.tmp, left_provided=True, right_provided=True,
            state_manager=XeFMStateManager(
                db_path=os.path.join(self.state_dir, "state.db")))
        self.app.file_monitor.stop_monitoring()
        self.app._settle_listings()
        filters.clear()
        filters.register("big", label="Big files", match=lambda e: True)
        self.app._record_filter_pattern("*.py")

    def tearDown(self):
        filters.clear()
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _open(self):
        self.app.enter_filter()
        dialog = self.app.panel._layers[-1].widget
        self.assertIsInstance(dialog, HistoryInputDialog)
        return dialog

    def _copy(self, label):
        dialog = self._open()
        labels = [dialog.to_label(v) for v in dialog.filtered]
        dialog._browse(labels.index(label))
        return dialog.field.text

    def test_a_remembered_pattern(self):
        self.assertEqual(self._copy("*.py"), "*.py")

    def test_a_defined_filter_copies_in_as_its_name(self):
        self.assertEqual(self._copy("Big files"), "big")

    def test_the_clear_row_copies_in_as_nothing(self):
        self.assertEqual(self._copy(self.app._FILTER_CLEAR), "")

    def test_a_new_pattern_is_applied_as_typed(self):
        dialog = self._open()
        _type(dialog, "py")                  # matches the remembered *.py
        dialog.handle_event(_key("enter"))
        self.app._settle_listings()
        self.assertEqual(self.app.active_pane()["filter_pattern"], "py")


if __name__ == "__main__":
    unittest.main()
