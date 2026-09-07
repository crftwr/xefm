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

CASE = Option("case", "Case", accel="c", flag="Aa",
              values=("smart", "sensitive", "insensitive"),
              labels=("smart", "always on", "always off"))
PATTERN = Option("pattern", "Pattern", accel="p", flag=".*",
                 values=("regex", "literal"), modes=("content",))
SUBDIRS = Option("subdirs", "Search subfolders", accel="s", flag="sub",
                 values=(True, False))

ALL = (CASE, PATTERN, SUBDIRS)


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
        assert names == ["case", "subdirs"]   # pattern is content-only

    def test_a_gated_option_is_absent_not_dimmed(self, options):
        # An option that cannot do anything must not look like one that is off.
        dialog = OptionsDialog(options, mode="filename")
        assert all(o.name != "pattern" for o in dialog.rows)

    def test_row_set_is_captured_at_open(self, options, dialog):
        # The list must not resize under the cursor while the box is open.
        before = list(dialog.rows)
        options.cycle("case")
        assert dialog.rows == before


class TestChanging:
    def test_space_advances_the_selected_option(self, options, dialog):
        dialog.handle_event(_key("space", char=" "))
        assert options["case"] == "sensitive"

    def test_left_walks_back(self, options, dialog):
        dialog.handle_event(_key("left"))
        assert options["case"] == "insensitive"

    def test_right_walks_forward(self, options, dialog):
        dialog.handle_event(_key("right"))
        assert options["case"] == "sensitive"

    def test_a_plain_letter_picks_its_option_anywhere_in_the_list(self, options, dialog):
        # The point of a surface with no text field: the letter is the key.
        dialog.handle_event(_key("s", char="s"))
        assert options["subdirs"] is False
        assert dialog.rows[dialog._index].name == "subdirs"

    def test_an_unclaimed_letter_does_nothing(self, options, dialog):
        dialog.handle_event(_key("z", char="z"))
        assert options.snapshot() == OptionSet(ALL).snapshot()

    def test_a_letter_for_a_gated_option_does_nothing(self, options):
        dialog = OptionsDialog(options, mode="filename")
        dialog.handle_event(_key("p", char="p"))
        assert options["pattern"] == "regex"

    def test_arrows_move_the_selection(self, options, dialog):
        dialog.handle_event(_key("down"))
        dialog.handle_event(_key("space", char=" "))
        assert options["pattern"] == "literal"
        assert options["case"] == "smart"

    def test_selection_wraps(self, dialog):
        dialog.handle_event(_key("up"))
        assert dialog._index == len(dialog.rows) - 1

    def test_changes_reach_the_owner_as_they_are_made(self, options, dialog):
        seen = []
        options.on_change = lambda name, value: seen.append((name, value))
        dialog.handle_event(_key("c", char="c"))
        dialog.handle_event(_key("s", char="s"))
        assert seen == [("case", "sensitive"), ("subdirs", False)]


class TestClosing:
    def test_escape_closes_without_reverting(self, options, dialog):
        dialog.handle_event(_key("c", char="c"))
        dialog.handle_event(_key("escape"))
        assert options["case"] == "sensitive"   # already applied; nothing to undo

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

    def test_a_row_click_changes_it_and_stays_open(self, options, dialog):
        closed = []
        dialog.on_close = lambda: closed.append(True)
        dialog._size = (40.0, 10.0)
        dialog._row_hits = [(i, 4.0 + i, 5.0 + i) for i in range(len(dialog.rows))]
        dialog.handle_event(self._click(10.0, 4.5))
        assert options["case"] == "sensitive"
        assert closed == []

    def test_a_click_outside_dismisses(self, dialog):
        closed = []
        dialog.on_close = lambda: closed.append(True)
        dialog._size = (40.0, 10.0)
        dialog.handle_event(self._click(-1.0, 4.5))
        assert closed == [True]
