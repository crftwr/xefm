"""The generic pick-one list dialog (xefm.choice_dialog): row seeding, result
reporting, and the type-ahead jump — prefix beats substring, the buffer
accumulates, times out after a second of quiet, and Backspace trims it.
Headless: the dialog is constructed directly and driven with plain key events.

Run with: python -m pytest test/test_choice_dialog.py -v
"""

import pytest

from puikit.event import Event, EventType

from xefm.choice_dialog import ChoiceDialog

ROWS = [
    ("auto", "Auto  (Shift-JIS)"),
    ("utf-8", "UTF-8"),
    ("cp932", "Shift-JIS"),
    ("euc-jp", "EUC-JP"),
    ("iso-2022-jp", "ISO-2022-JP"),
    ("latin-1", "Latin-1"),
]


def _key(key, char=None, mods=frozenset()):
    return Event(EventType.KEY, key=key, char=char, modifiers=frozenset(mods))


def _type(dialog, text):
    for ch in text:
        dialog.handle_event(_key(ch.lower(), char=ch))


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def dialog():
    d = ChoiceDialog("Encoding", ROWS)
    d._clock = FakeClock()
    return d


class TestSelection:
    def test_seeds_on_current_value(self):
        d = ChoiceDialog("Encoding", ROWS, current="cp932")
        assert d._rows[d._index][0] == "cp932"

    def test_seeds_on_first_row_without_current(self):
        assert ChoiceDialog("Encoding", ROWS)._index == 0

    def test_unknown_current_falls_back_to_first_row(self):
        assert ChoiceDialog("Encoding", ROWS, current="nope")._index == 0

    def test_up_down_wrap(self, dialog):
        dialog.handle_event(_key("up"))
        assert dialog._index == len(ROWS) - 1
        dialog.handle_event(_key("down"))
        assert dialog._index == 0

    def test_enter_reports_the_selected_value(self):
        results = []
        d = ChoiceDialog("Encoding", ROWS, current="euc-jp",
                         on_result=results.append)
        d.handle_event(_key("enter"))
        assert results == ["euc-jp"]

    def test_escape_reports_none(self):
        results = []
        d = ChoiceDialog("Encoding", ROWS, on_result=results.append)
        d.handle_event(_key("escape"))
        assert results == [None]


class TestTypeAhead:
    def test_single_letter_jumps_by_prefix(self, dialog):
        _type(dialog, "e")
        assert dialog._rows[dialog._index][0] == "euc-jp"

    def test_buffer_accumulates(self, dialog):
        """"u" alone hits UTF-8; "ut" must stay there, not restart matching."""
        _type(dialog, "ut")
        assert dialog._rows[dialog._index][0] == "utf-8"
        assert dialog._typeahead_buffer() == "ut"

    def test_prefix_beats_substring(self, dialog):
        # "S" is a substring of "ISO-2022-JP" (earlier row) but the prefix of
        # "Shift-JIS" — the prefix match must win.
        _type(dialog, "s")
        assert dialog._rows[dialog._index][0] == "cp932"

    def test_substring_matches_as_a_fallback(self, dialog):
        _type(dialog, "tin")  # no label starts with it; "Latin-1" contains it
        assert dialog._rows[dialog._index][0] == "latin-1"

    def test_case_insensitive(self, dialog):
        _type(dialog, "LAT")
        assert dialog._rows[dialog._index][0] == "latin-1"

    def test_no_match_keeps_selection_and_shows_the_miss(self, dialog):
        _type(dialog, "e")
        before = dialog._index
        _type(dialog, "zz")
        assert dialog._index == before
        assert dialog._typeahead_buffer() == "ezz"

    def test_quiet_timeout_resets_the_buffer(self, dialog):
        _type(dialog, "e")
        dialog._clock.now += 1.5
        assert dialog._typeahead_buffer() == ""
        _type(dialog, "u")  # a fresh jump, not "eu"
        assert dialog._rows[dialog._index][0] == "utf-8"

    def test_quick_keystrokes_keep_the_buffer(self, dialog):
        _type(dialog, "e")
        dialog._clock.now += 0.5
        _type(dialog, "u")
        assert dialog._typeahead_buffer() == "eu"
        assert dialog._rows[dialog._index][0] == "euc-jp"

    def test_backspace_trims_and_rejumps(self, dialog):
        _type(dialog, "eu")
        dialog.handle_event(_key("backspace"))
        assert dialog._typeahead_buffer() == "e"
        assert dialog._rows[dialog._index][0] == "euc-jp"

    def test_backspace_on_an_empty_buffer_is_inert(self, dialog):
        dialog.handle_event(_key("backspace"))
        assert dialog._typeahead_buffer() == ""

    def test_modified_keys_do_not_type(self, dialog):
        dialog.handle_event(_key("e", char="e", mods={"ctrl"}))
        assert dialog._typeahead_buffer() == ""
        assert dialog._index == 0

    def test_shifted_letters_do_type(self, dialog):
        dialog.handle_event(_key("e", char="E", mods={"shift"}))
        assert dialog._rows[dialog._index][0] == "euc-jp"

    def test_arrow_keys_do_not_feed_the_buffer(self, dialog):
        dialog.handle_event(_key("down"))
        assert dialog._typeahead_buffer() == ""
