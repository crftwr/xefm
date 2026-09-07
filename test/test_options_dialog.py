"""The shared options box (xefm.options_dialog) — the one surface behind the
``options`` key.

What matters here is that it is a surface with no text field, which is the whole
argument for one entry key instead of one chord per option: every plain letter
is free to be an accelerator. The rest is the live-apply contract — changes go
out through the OptionSet as they are made, so Enter and Esc both just close and
neither is an undo.

Headless: the dialog is constructed directly and driven with plain key events.

Run with: python -m pytest test/test_options_dialog.py -v
"""

import pytest

from puikit.event import Event, EventType

from xefm.options import Option, OptionSet
from xefm.options_dialog import OptionsDialog

CASE = Option("case", "Case sensitive", flag="Aa")
REGEX = Option("regex", "Regular expression", flag=".*", default=True,
               modes=("content",))
SUBDIRS = Option("subdirs", "Search subfolders", flag="Sub", default=True)

ALL = (CASE, REGEX, SUBDIRS)


def _key(key, char=None, mods=frozenset()):
    return Event(EventType.KEY, key=key, char=char, modifiers=frozenset(mods))


@pytest.fixture
def options():
    return OptionSet(ALL)


@pytest.fixture
def dialog(options):
    return OptionsDialog(options, title="Search Options", mode="content")


class TestRows:
    def test_lists_the_options_that_apply_to_the_mode(self, options):
        names = [o.name for o in OptionsDialog(options, mode="filename").rows]
        assert names == ["case", "subdirs"]   # regex is content-only

    def test_a_gated_option_is_absent_not_dimmed(self, options):
        # An option that cannot do anything must not look like one that is off.
        dialog = OptionsDialog(options, mode="filename")
        assert all(o.name != "regex" for o in dialog.rows)

    def test_row_set_is_captured_at_open(self, options, dialog):
        # The list must not resize under the cursor while the box is open.
        before = list(dialog.rows)
        options.toggle("case")
        assert dialog.rows == before


class TestChanging:
    def test_space_toggles_the_selected_option(self, options, dialog):
        dialog.handle_event(_key("space", char=" "))
        assert options["case"] is True

    def test_left_and_right_toggle_too(self, options, dialog):
        dialog.handle_event(_key("left"))
        assert options["case"] is True
        dialog.handle_event(_key("right"))
        assert options["case"] is False

    def test_a_plain_letter_picks_its_option_anywhere_in_the_list(self, options, dialog):
        # The point of a surface with no text field: the letter is the key, and
        # it is the label's initial rather than a column of its own.
        dialog.handle_event(_key("s", char="s"))
        assert options["subdirs"] is False
        assert dialog.rows[dialog._index].name == "subdirs"

    def test_an_unclaimed_letter_does_nothing(self, options, dialog):
        dialog.handle_event(_key("z", char="z"))
        assert options.snapshot() == OptionSet(ALL).snapshot()

    def test_a_letter_for_a_gated_option_does_nothing(self, options):
        dialog = OptionsDialog(options, mode="filename")
        dialog.handle_event(_key("r", char="r"))
        assert options["regex"] is True

    def test_arrows_move_the_selection(self, options, dialog):
        dialog.handle_event(_key("down"))
        dialog.handle_event(_key("space", char=" "))
        assert options["regex"] is False
        assert options["case"] is False

    def test_selection_wraps(self, dialog):
        dialog.handle_event(_key("up"))
        assert dialog._index == len(dialog.rows) - 1

    def test_changes_reach_the_owner_as_they_are_made(self, options, dialog):
        seen = []
        options.on_change = lambda name, value: seen.append((name, value))
        dialog.handle_event(_key("c", char="c"))
        dialog.handle_event(_key("s", char="s"))
        assert seen == [("case", True), ("subdirs", False)]


class TestClosing:
    def test_escape_closes_without_reverting(self, options, dialog):
        dialog.handle_event(_key("c", char="c"))
        dialog.handle_event(_key("escape"))
        assert options["case"] is True   # already applied; nothing to undo

    def test_enter_closes_too(self, options, dialog):
        closed = []
        dialog.on_close = lambda: closed.append(True)
        dialog.handle_event(_key("enter"))
        assert closed == [True]

    def test_close_notifies_the_owner_once(self, dialog):
        closed = []
        dialog.on_close = lambda: closed.append(True)
        dialog.handle_event(_key("escape"))
        assert closed == [True]


class TestMouse:
    def _click(self, x, y):
        return Event(EventType.MOUSE_CLICK, x=x, y=y)

    def test_a_row_click_toggles_it_and_stays_open(self, options, dialog):
        closed = []
        dialog.on_close = lambda: closed.append(True)
        dialog._size = (40.0, 10.0)
        dialog._row_hits = [(i, 4.0 + i, 5.0 + i) for i in range(len(dialog.rows))]
        dialog.handle_event(self._click(10.0, 4.5))
        assert options["case"] is True
        assert closed == []

    def test_a_click_outside_dismisses(self, dialog):
        closed = []
        dialog.on_close = lambda: closed.append(True)
        dialog._size = (40.0, 10.0)
        dialog.handle_event(self._click(-1.0, 4.5))
        assert closed == [True]
