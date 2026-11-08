"""Key-binding matching against the PuiKit keyboard contract.

Drives XeFM's real AFX keymap (`keymap_presets.table(AFX)`) through
``find_action_for_event`` using **PuiKit** ``Event`` objects shaped exactly as
the curses/macOS backends now produce them (see
``doc/dev/PUIKIT_KEYBOARD_CONTRACT.md``).
"""

import contextlib
import os
import sys
import unittest

from xefm import keymap_presets  # noqa: E402
from puikit import Event, EventType
from xefm.config import KeyBindings


def key(name, char=None, mods=()):
    return Event(type=EventType.KEY, key=name, char=char, modifiers=frozenset(mods))


@contextlib.contextmanager
def case(platform_name, backend):
    """Read the AFX keymap as one of its three cases sees it — macOS desktop,
    Windows desktop, or any terminal — with the platform and backend it
    branches on. The table is built on each call, so nothing is reloaded."""
    from xefm import backend_detector
    saved_platform = sys.platform
    saved_backend = os.environ.get("XEFM_BACKEND")
    sys.platform = platform_name
    os.environ["XEFM_BACKEND"] = backend
    backend_detector._cached_backend = None
    try:
        yield KeyBindings(keymap_presets.table(keymap_presets.AFX))
    finally:
        sys.platform = saved_platform
        if saved_backend is None:
            os.environ.pop("XEFM_BACKEND", None)
        else:
            os.environ["XEFM_BACKEND"] = saved_backend
        backend_detector._cached_backend = None


class TestKeybindingsPuikitContract(unittest.TestCase):
    def setUp(self):
        # Build against the AFX keymap (keymap_presets.table(AFX)), so the
        # test is deterministic and independent of any ~/.xefm/config.py.
        self.kb = KeyBindings(keymap_presets.table(keymap_presets.AFX))

    def action(self, event, has_selection=False):
        return self.kb.find_action_for_event(event, has_selection)

    # --- letters & shift-letters (key mode) ---------------------------------
    def test_plain_letter(self):
        self.assertEqual(self.action(key("q", "q")), "quit")

    def test_letter_lowercase_vs_shift(self):
        # 'A' bound to toggle_select_files; 'Shift-A' to toggle_select_items.
        self.assertEqual(self.action(key("a", "a")), "toggle_select_files")
        self.assertEqual(
            self.action(key("a", "A", {"shift"})), "toggle_select_items"
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

    def test_ctrl_arrow(self):
        self.assertEqual(self.action(key("down", mods={"ctrl"})),
                         "cursor_next_selected")
        self.assertEqual(self.action(key("up", mods={"ctrl"})),
                         "cursor_prev_selected")

    def test_function_key(self):
        self.assertEqual(self.action(key("f5")), "redraw")

    # --- space vs shift-space (named key, shift significant) ----------------
    def test_space_and_shift_space(self):
        self.assertEqual(self.action(key("space", " ")), "toggle_select_down")
        # Shift on SPACE is a different action, which is the whole reason the
        # binding is on the named key rather than the character: a char-mode
        # match would ignore shift and both would mark one item. Only a console
        # that reports modifiers on a printable can deliver it — a POSIX
        # terminal sends a bare space (see the Three cases note in xefm/keymaps/common.py).
        self.assertEqual(
            self.action(key("space", " ", {"shift"})), "select_range"
        )

    def test_ctrl_space_is_the_search_bar_s_alone(self):
        # The file list does not answer it: marking with Ctrl-SPACE belongs to
        # the search bar, where a bare SPACE types into the pattern.
        self.assertIsNone(self.action(key("space", " ", {"ctrl"})))

    # --- punctuation & digits (char mode, ignore shift/alt) -----------------
    def test_punctuation(self):
        self.assertEqual(self.action(key("?", "?")), "context_menu_dir")
        self.assertEqual(self.action(key("/", "/")), "context_menu")
        self.assertEqual(self.action(key(".", ".")), "toggle_hidden")
        self.assertEqual(self.action(key(";", ";")), "filter")
        self.assertEqual(self.action(key("[", "[")), "adjust_pane_left")

    def test_help_is_f1(self):
        self.assertEqual(self.action(key("f1")), "help")

    def test_the_menu_key_opens_the_context_menus(self):
        # Shift is kept on a named key, so the Menu key is two bindings.
        self.assertEqual(self.action(key("apps")), "context_menu")
        self.assertEqual(self.action(key("apps", None, {"shift"})), "context_menu_dir")

    def test_named_punctuation_token(self):
        # 'EQUAL' -> '=', 'Shift-EQUAL' -> '+' (the produced shifted glyph).
        self.assertEqual(self.action(key("=", "=")), "diff_files")
        self.assertEqual(self.action(key("+", "+", {"shift"})), "diff_directories")

    def test_digit(self):
        self.assertEqual(self.action(key("1", "1")), "quick_sort_name")
        self.assertEqual(self.action(key("4", "4")), "quick_sort_date")

    # --- the common Ctrl chords (one key for all three cases) ---------------
    def test_common_ctrl_chords(self):
        # The OS-flavoured actions ride plain Ctrl+letter, which is the only
        # chord family a terminal, a Mac window and a Windows window all deliver.
        self.assertEqual(self.action(key("o", mods={"ctrl"})), "open_with_os")
        self.assertEqual(self.action(key("r", mods={"ctrl"})), "reveal_in_os")
        self.assertEqual(self.action(key("n", mods={"ctrl"})), "copy_names")
        self.assertEqual(self.action(key("p", mods={"ctrl"})), "copy_paths")
        # Copy / cut / paste: the file clipboard (#577). The copy chord also
        # copies the log's selected text when there is one (in the handler).
        self.assertEqual(self.action(key("c", mods={"ctrl"})), "clipboard_copy")
        self.assertEqual(self.action(key("x", mods={"ctrl"})), "clipboard_cut")
        self.assertEqual(self.action(key("v", mods={"ctrl"})), "clipboard_paste")
        # Plain Enter is still the ordinary open.
        self.assertEqual(self.action(key("enter")), "open_item")

    # --- negative cases ------------------------------------------------------
    def test_unbound_key_returns_none(self):
        self.assertIsNone(self.action(key("z", "z")))

    def test_shift_does_not_trigger_unshifted_letter(self):
        # Shift-Q is not bound; must not fall through to 'quit' ('q' no-mods).
        self.assertIsNone(self.action(key("q", "Q", {"shift"})))


class TestThreeCases(unittest.TestCase):
    """The per-case overrides at the foot of ``xefm/keymaps/common.py``: two platform
    idioms on the desktop, and nothing a terminal cannot send anywhere."""

    def test_macos_desktop_adds_command_chords(self):
        with case("darwin", "gui") as kb:
            keys, _ = kb.get_keys_for_action("open_with_os", "filer")
            self.assertEqual(keys, ["Command-ENTER", "Ctrl-O"])
            keys, _ = kb.get_keys_for_action("clipboard_copy", "filer")
            self.assertEqual(keys, ["Command-C", "Ctrl-C", "Y"])
            keys, _ = kb.get_keys_for_action("clipboard_paste", "filer")
            self.assertEqual(keys, ["Command-V", "Ctrl-V", "G"])

    def test_windows_desktop_adds_ctrl_enter(self):
        with case("win32", "gui") as kb:
            keys, _ = kb.get_keys_for_action("open_with_os", "filer")
            self.assertEqual(keys, ["Ctrl-ENTER", "Ctrl-O"])
            # No Command on Windows, so copy keeps the common chord.
            keys, _ = kb.get_keys_for_action("clipboard_copy", "filer")
            self.assertEqual(keys, ["Ctrl-C", "Y"])

    def test_terminal_case_is_the_common_table(self):
        for platform_name in ("darwin", "win32", "linux"):
            with self.subTest(platform=platform_name), \
                    case(platform_name, "vt") as kb:
                for action, expected in (("open_with_os", ["Ctrl-O"]),
                                         ("reveal_in_os", ["Ctrl-R"]),
                                         ("copy_names", ["Ctrl-N"]),
                                         ("copy_paths", ["Ctrl-P"]),
                                         ("clipboard_copy", ["Ctrl-C", "Y"]),
                                         ("clipboard_cut", ["Ctrl-X", "Shift-Y"]),
                                         ("clipboard_paste", ["Ctrl-V", "G"])):
                    keys, _ = kb.get_keys_for_action(action, "filer")
                    self.assertEqual(keys, expected, action)

    def test_terminal_case_binds_nothing_a_terminal_cannot_send(self):
        # The rule the three-case split exists to keep: in terminal mode every
        # default must be a chord a terminal can actually encode. Command never
        # arrives; Ctrl-Shift-<letter> is the same control byte as Ctrl-<letter>;
        # Ctrl-ENTER and Alt-ENTER are plain Enter (or hijacked).
        with case("linux", "vt") as kb:
            for name, binding in keymap_presets.table(keymap_presets.AFX).items():
                keys, _ = KeyBindings._binding_parts(binding)
                for expr in keys:
                    ident, mods, _mode = kb._parse_key_expression(expr)
                    self.assertNotIn("cmd", mods, f"{name}: {expr}")
                    letter = len(ident) == 1 and ident.isalpha()
                    self.assertFalse(
                        letter and {"ctrl", "shift"} <= mods,
                        f"{name}: {expr} is the same byte as Ctrl-{ident} "
                        f"in a terminal",
                    )
                    self.assertFalse(
                        ident == "enter" and mods & {"ctrl", "alt"},
                        f"{name}: {expr} arrives as plain Enter in a terminal",
                    )


if __name__ == "__main__":
    unittest.main()
