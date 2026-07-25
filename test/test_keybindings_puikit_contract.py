"""Key-binding matching against the PuiKit keyboard contract.

Drives XeFM's real default keymap (`_config.py`) through
``find_action_for_event`` using **PuiKit** ``Event`` objects shaped exactly as
the curses/macOS backends now produce them (see
``doc/dev/PUIKIT_KEYBOARD_CONTRACT.md``).
"""

import unittest

from xefm import _config
from puikit import Event, EventType
from xefm.config import KeyBindings


def key(name, char=None, mods=()):
    return Event(type=EventType.KEY, key=name, char=char, modifiers=frozenset(mods))


class TestKeybindingsPuikitContract(unittest.TestCase):
    def setUp(self):
        # Build against the canonical template defaults (_config.py), so the
        # test is deterministic and independent of any ~/.xefm/config.py.
        self.kb = KeyBindings(_config.Config.KEY_BINDINGS)

    def action(self, event, has_selection=False):
        return self.kb.find_action_for_event(event, has_selection)

    # --- letters & shift-letters (key mode) ---------------------------------
    def test_plain_letter(self):
        self.assertEqual(self.action(key("q", "q")), "quit")

    def test_letter_lowercase_vs_shift(self):
        # 'A' bound to select_all_files; 'Shift-A' bound to select_all_items.
        self.assertEqual(self.action(key("a", "a")), "select_all_files")
        self.assertEqual(
            self.action(key("a", "A", {"shift"})), "select_all_items"
        )

    def test_letter_with_selection_requirement(self):
        self.assertIsNone(self.action(key("c", "c"), has_selection=False))
        self.assertEqual(
            self.action(key("c", "c"), has_selection=True), "copy_files"
        )

    def test_shared_key_selection_dispatch(self):
        # 'M' is move_files (selection) or create_directory (no selection).
        self.assertEqual(
            self.action(key("m", "m"), has_selection=True), "move_files"
        )
        self.assertEqual(
            self.action(key("m", "m"), has_selection=False), "create_directory"
        )

    # --- named keys (key mode) ----------------------------------------------
    def test_named_keys(self):
        self.assertEqual(self.action(key("home")), "select_all")
        self.assertEqual(self.action(key("end")), "unselect_all")
        self.assertEqual(self.action(key("tab")), "switch_pane")
        self.assertEqual(self.action(key("up")), "cursor_up")
        self.assertEqual(self.action(key("backspace")), "go_parent")

    def test_shift_arrow(self):
        self.assertEqual(self.action(key("up", mods={"shift"})), "scroll_log_up")

    def test_function_key(self):
        self.assertEqual(self.action(key("f5")), "redraw")

    # --- space vs shift-space (named key, shift significant) ----------------
    def test_space_and_shift_space(self):
        self.assertEqual(self.action(key("space", " ")), "select_file")
        self.assertEqual(
            self.action(key("space", " ", {"shift"})), "select_file_up"
        )

    # --- punctuation & digits (char mode, ignore shift/alt) -----------------
    def test_punctuation(self):
        self.assertEqual(self.action(key("?", "?")), "help")
        self.assertEqual(self.action(key(".", ".")), "toggle_hidden")
        self.assertEqual(self.action(key(";", ";")), "filter")
        self.assertEqual(self.action(key("[", "[")), "adjust_pane_left")

    def test_named_punctuation_token(self):
        # 'EQUAL' -> '=', 'Shift-EQUAL' -> '+' (the produced shifted glyph).
        self.assertEqual(self.action(key("=", "=")), "diff_files")
        self.assertEqual(self.action(key("+", "+", {"shift"})), "diff_directories")

    def test_digit(self):
        self.assertEqual(self.action(key("1", "1")), "quick_sort_name")
        self.assertEqual(self.action(key("4", "4")), "quick_sort_date")

    # --- GUI-only chords (key mode with cmd/alt) ----------------------------
    def test_gui_only_chords(self):
        self.assertEqual(
            self.action(key("enter", mods={"cmd"})), "open_with_os"
        )
        self.assertEqual(
            self.action(key("enter", mods={"alt"})), "reveal_in_os"
        )
        # Plain Enter is the ordinary open.
        self.assertEqual(self.action(key("enter")), "open_item")

    # --- negative cases ------------------------------------------------------
    def test_unbound_key_returns_none(self):
        self.assertIsNone(self.action(key("y", "y")))

    def test_shift_does_not_trigger_unshifted_letter(self):
        # Shift-Q is not bound; must not fall through to 'quit' ('q' no-mods).
        self.assertIsNone(self.action(key("q", "Q", {"shift"})))


if __name__ == "__main__":
    unittest.main()
