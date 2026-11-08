"""Keymap presets (#565, #597): whole keymaps, chosen as one.

The pure half builds a preset's table, lays a ``config.py``'s
``KEY_BINDINGS`` over it, and checks what moved, what stayed the user's, and
what was freed. The app half switches presets, answers the first launch's
question, and presses keys on the memory backend.

Run with: python -m pytest test/test_keymap_presets.py -v
"""

import copy
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit import Event, EventType  # noqa: E402

from xefm import keymaps  # noqa: E402
from xefm import keymap_presets  # noqa: E402
from xefm import app as xefm_app  # noqa: E402
from xefm import config as xefm_config  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402

def _afx():
    """The AFX table as the presets will build it now — built at the call,
    since its desktop overrides read the backend another test may have set."""
    return keymap_presets.table(keymap_presets.AFX)


def _config_with(**overrides):
    """A config whose ``config.py`` binds ``overrides`` and nothing else."""
    return types.SimpleNamespace(KEY_BINDINGS=dict(overrides), KEY_PRESET=None)


def _keys(config, action):
    value = config.KEY_BINDINGS.get(action)
    return value["keys"] if isinstance(value, dict) else value


class Apply(unittest.TestCase):

    def test_afx_is_its_whole_table(self):
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertEqual(config.KEY_BINDINGS, _afx())
        self.assertFalse(keymap_presets.type_ahead(config))

    def test_orthodox_is_its_whole_table(self):
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        self.assertEqual(_keys(config, "copy_files"), ["F5"])
        self.assertEqual(_keys(config, "delete_files"), ["F8", "DELETE"])
        self.assertEqual(_keys(config, "redraw"), [])
        self.assertTrue(keymap_presets.type_ahead(config))

    def test_a_preset_key_has_no_selection_gate(self):
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        # AFX's copy_files is {'keys': ['C'], 'selection': 'required'}.
        self.assertEqual(config.KEY_BINDINGS["copy_files"], ["F5"])

    def test_bare_letters_leave_the_file_list(self):
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        for action, value in config.KEY_BINDINGS.items():
            if action in keymap_presets._typing_contexts():
                keys = value["keys"] if isinstance(value, dict) else value
                self.assertFalse([k for k in keys if keymap_presets.is_typing_key(k)],
                                 action)
        # A key that is not a letter stays where the preset says nothing:
        # '.' still shows hidden files.
        self.assertEqual(_keys(config, "toggle_hidden"), _afx()["toggle_hidden"])

    def test_orthodox_follows_total_commander(self):
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        expected = {
            "help": ["F1"], "reread": ["F2", "Ctrl-R"], "view_file": ["F3"],
            "edit_file": ["F4"], "copy_files": ["F5"], "move_files": ["F6"],
            "create_directory": ["F7"], "delete_files": ["F8", "DELETE"],
            "quit": ["Alt-F4"], "rename": ["Shift-F6", "Ctrl-M"],
            "duplicate_files": ["Shift-F5"], "compare_selection": ["Shift-F2"],
            "find_files": ["Alt-F7"], "create_archive": ["Alt-F5"],
            "history": ["Alt-DOWN"], "favorites": ["Ctrl-D"],
            "filter": ["Ctrl-S"], "go_parent": ["BACKSPACE", "Ctrl-PAGE_UP"],
            "select_all": ["Ctrl-A"], "quick_sort_date": ["Ctrl-F5"],
        }
        for action, keys in expected.items():
            self.assertEqual(_keys(config, action), keys, action)

    def test_actions_this_xefm_lacks_are_skipped(self):
        """The table may name actions of features not merged yet; where the
        running XeFM lacks one, its keys stay free."""
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        for action in keymaps.orthodox.own_bindings():
            # Known in any context: the viewers' scoped search keys are (#737).
            if not keymap_presets._known(action):
                self.assertNotIn(action, config.KEY_BINDINGS, action)
        self.assertIn("text_viewer.search_next", config.KEY_BINDINGS)

    def test_a_viewer_keeps_its_letters(self):
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        self.assertEqual(_keys(config, "toggle_wrap"), _afx()["toggle_wrap"])

    def test_config_py_overrides_every_preset(self):
        for name in keymap_presets.PRESETS:
            config = _config_with(copy_files=["Ctrl-K"], view_file=["V", "Q"])
            keymap_presets.apply(config, name)
            self.assertEqual(config.KEY_BINDINGS["copy_files"], ["Ctrl-K"], name)
            # Not freed either: the user's letters are the user's.
            self.assertEqual(config.KEY_BINDINGS["view_file"], ["V", "Q"], name)

    def test_an_entry_equal_to_afx_still_overrides(self):
        """No "untouched" test any more: an entry is an entry, whatever it
        happens to equal."""
        config = _config_with(copy_files=_afx()["copy_files"])
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        self.assertEqual(config.KEY_BINDINGS["copy_files"], _afx()["copy_files"])

    def test_an_old_name_overrides_the_action_it_names(self):
        config = _config_with(rename_file=["Ctrl-K"])
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        self.assertNotIn("rename", config.KEY_BINDINGS)
        self.assertEqual(config.KEY_BINDINGS["rename_file"], ["Ctrl-K"])

    def test_a_rebound_key_leaves_the_action_that_had_it(self):
        """#662: binding Shift-T is enough; the preset's own Shift-T action
        does not have to be emptied by hand."""
        self.assertIn("Shift-T", _keys(types.SimpleNamespace(
            KEY_BINDINGS=_afx()), "open_in_new_tab"))
        config = _config_with(toggle_color_scheme=["Shift-T"])
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertNotIn("Shift-T", _keys(config, "open_in_new_tab"))
        self.assertEqual(_keys(config, "toggle_color_scheme"), ["Shift-T"])
        keys = xefm_config.KeyBindings(config.KEY_BINDINGS)
        event = Event(EventType.KEY, key="t", char="T", modifiers={"shift"})
        self.assertEqual(keys.find_action_for_event(event, context="filer"),
                         "toggle_color_scheme")

    def test_a_rebound_key_is_matched_however_it_is_spelled(self):
        config = _config_with(toggle_color_scheme=["shift-t"])
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertNotIn("Shift-T", _keys(config, "open_in_new_tab"))

    def test_the_actions_other_keys_stay(self):
        config = _config_with(toggle_color_scheme=["Shift-T"])
        keymap_presets.apply(config, keymap_presets.AFX)
        expected = [k for k in _keys(types.SimpleNamespace(KEY_BINDINGS=_afx()),
                                     "open_in_new_tab") if k != "Shift-T"]
        self.assertEqual(_keys(config, "open_in_new_tab"), expected)

    def test_a_shared_key_rebound_in_one_context_stays_elsewhere(self):
        """quit is a common action: a file-list action taking Q takes it in the
        file list only, and the viewers still quit on it."""
        self.assertIn("Q", _keys(types.SimpleNamespace(KEY_BINDINGS=_afx()), "quit"))
        config = _config_with(view_file=["Q"])
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertIn("Q", _keys(config, "quit"))
        keys = xefm_config.KeyBindings(config.KEY_BINDINGS)
        event = Event(EventType.KEY, key="q", char="q", modifiers=set())
        self.assertEqual(keys.find_action_for_event(event, context="filer"),
                         "view_file")
        self.assertEqual(keys.find_action_for_event(event, context="text_viewer"),
                         "quit")

    def test_a_key_split_by_selection_is_not_taken(self):
        """AFX's C copies only when files are marked; binding C for when none
        are leaves that alone, and binding it outright takes it."""
        self.assertEqual(_afx()["copy_files"]["selection"], "required")
        self.assertIn("C", _afx()["copy_files"]["keys"])
        # view_file is reached wherever copy_files is (the file list and the
        # directory diff), so its C may take copy_files' C.
        config = _config_with(view_file={"keys": ["C"], "selection": "none"})
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertIn("C", _keys(config, "copy_files"))
        keys = xefm_config.KeyBindings(config.KEY_BINDINGS)
        event = Event(EventType.KEY, key="c", char="c", modifiers=set())
        self.assertEqual(keys.find_action_for_event(event, True, "filer"), "copy_files")
        self.assertEqual(keys.find_action_for_event(event, False, "filer"), "view_file")

        config = _config_with(view_file=["C"])
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertNotIn("C", _keys(config, "copy_files"))
        # The gate survives on what is left.
        self.assertEqual(config.KEY_BINDINGS["copy_files"]["selection"], "required")

    def test_a_key_taken_where_the_action_is_not_stays_where_it_is(self):
        """copy_files also copies in the directory diff; file_details, a file
        list action, taking C leaves the diff's C copying."""
        config = _config_with(file_details=["C"])
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertIn("C", _keys(config, "copy_files"))
        keys = xefm_config.KeyBindings(config.KEY_BINDINGS)
        event = Event(EventType.KEY, key="c", char="c", modifiers=set())
        self.assertEqual(keys.find_action_for_event(event, True, "filer"), "file_details")
        self.assertEqual(keys.find_action_for_event(event, True, "dir_diff"), "copy_files")

    def test_a_scoped_rebind_takes_its_context_only(self):
        """'text_viewer.quit' is not an action: rebinding Q there leaves the
        file list's Q where the preset put it."""
        afx = _afx()
        holder = next(a for a, v in afx.items()
                      if "Q" in (v["keys"] if isinstance(v, dict) else v))
        config = _config_with(**{"text_viewer.quit": ["X"],
                                 "text_viewer.toggle_wrap": ["Q"]})
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertIn("Q", _keys(config, holder))

    def test_config_py_entries_are_matched_first(self):
        config = _config_with(toggle_color_scheme=["Shift-T"])
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        self.assertEqual(next(iter(config.KEY_BINDINGS)), "toggle_color_scheme")

    def test_replaced_names_what_config_py_changes(self):
        config = _config_with(copy_files=_afx()["copy_files"],
                              help=["F1"])
        self.assertEqual(keymap_presets.replaced(config, keymap_presets.AFX), [])
        self.assertEqual(keymap_presets.replaced(config, keymap_presets.ORTHODOX),
                         ["copy_files"])

    def test_switching_back_and_forth_does_not_compound(self):
        config = _config_with(quit=[])
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        self.assertEqual(_keys(config, "copy_files"), ["F5"])
        keymap_presets.apply(config, keymap_presets.AFX)
        self.assertEqual(config.KEY_BINDINGS, dict(_afx(), quit=[]))
        self.assertFalse(keymap_presets.type_ahead(config))

    def test_no_two_actions_share_a_key_in_the_file_list(self):
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.ORTHODOX)
        filer = keymap_presets._typing_contexts()
        seen = {}
        for action, value in config.KEY_BINDINGS.items():
            if action not in filer:
                continue
            keys = value["keys"] if isinstance(value, dict) else value
            sel = value.get("selection", "any") if isinstance(value, dict) else "any"
            for k in keys:
                seen.setdefault((k, sel), []).append(action)
        clashes = {k: v for k, v in seen.items() if len(v) > 1}
        self.assertEqual(clashes, {})

    def test_the_common_table_binds_no_letter_in_the_file_list(self):
        # Every preset is laid over it; a letter there would reach Orthodox
        # and OS native, whose letters type ahead.
        from xefm.keymaps import common as keymap_common
        typing = keymap_presets._typing_contexts()
        for action, value in keymap_common.bindings().items():
            if action in typing:
                keys = value["keys"] if isinstance(value, dict) else value
                self.assertFalse([k for k in keys if keymap_presets.is_typing_key(k)],
                                 action)

    def test_a_preset_is_the_common_table_with_its_own_keys(self):
        from xefm.keymaps import afx, common
        own = afx.own_bindings()
        table = keymap_presets.table(keymap_presets.AFX)
        self.assertEqual(list(table), list(common.bindings()))
        for action, value in own.items():
            self.assertEqual(table[action], value, action)

    def test_typing_keys(self):
        for k in ("K", "k", "7", "Shift-K"):
            self.assertTrue(keymap_presets.is_typing_key(k), k)
        for k in ("F5", "Ctrl-K", ";", "Shift-F6", "DELETE", "+"):
            self.assertFalse(keymap_presets.is_typing_key(k), k)

    def test_resolve(self):
        config = types.SimpleNamespace(KEY_PRESET=None)
        self.assertIsNone(keymap_presets.resolve(config, None), "nothing chosen")
        self.assertEqual(keymap_presets.resolve(config, "orthodox"), "orthodox")
        config.KEY_PRESET = "afx"
        self.assertEqual(keymap_presets.resolve(config, "orthodox"), "afx")
        config.KEY_PRESET = "nonsense"
        self.assertEqual(keymap_presets.resolve(config, "orthodox"), "orthodox")
        self.assertIsNone(keymap_presets.resolve(config, None))

    def test_default_is_the_old_name_of_afx(self):
        config = types.SimpleNamespace(KEY_PRESET="default")
        self.assertEqual(keymap_presets.resolve(config, "orthodox"), "afx")
        config.KEY_PRESET = None
        self.assertEqual(keymap_presets.resolve(config, "default"), "afx",
                         "a menu choice saved under the old name")
        self.assertEqual(keymap_presets.get("default").name, "afx")
        self.assertEqual(keymap_presets.LABELS["afx"], "AFX style")

    def test_the_shipped_key_bindings_holds_examples_only(self):
        from xefm import _config
        self.assertEqual(_config.Config.KEY_BINDINGS, {})


def _key(key, char=None, mods=()):
    return Event(type=EventType.KEY, key=key, char=char, modifiers=frozenset(mods))


def _native_case(platform_name, backend, preset=keymap_presets.NATIVE):
    """A preset's table — OS native unless told otherwise — as one of the
    three cases builds it."""
    from contextlib import contextmanager
    from xefm import backend_detector

    @contextmanager
    def scope():
        saved_platform, saved_backend = sys.platform, os.environ.get("XEFM_BACKEND")
        sys.platform = platform_name
        os.environ["XEFM_BACKEND"] = backend
        backend_detector._cached_backend = None
        try:
            yield keymap_presets.table(preset)
        finally:
            sys.platform = saved_platform
            if saved_backend is None:
                os.environ.pop("XEFM_BACKEND", None)
            else:
                os.environ["XEFM_BACKEND"] = saved_backend
            backend_detector._cached_backend = None
    return scope()


CASES = (("darwin", "gui"), ("win32", "gui"), ("linux", "vt"), ("darwin", "vt"))


class Native(unittest.TestCase):
    """#587: Finder's keys on the macOS desktop, Explorer's on the Windows one,
    and in a terminal the same layout with what a terminal can send."""

    def _keys(self, table, action):
        value = table.get(action)
        return value["keys"] if isinstance(value, dict) else value

    def test_it_is_a_preset_with_type_ahead(self):
        config = _config_with()
        keymap_presets.apply(config, keymap_presets.NATIVE)
        self.assertTrue(keymap_presets.type_ahead(config))
        self.assertIn(keymap_presets.NATIVE, keymap_presets.LABELS)

    def test_each_case_follows_its_platform(self):
        with _native_case("darwin", "gui") as t:
            self.assertEqual(self._keys(t, "clipboard_copy")[0], "Command-C")
            self.assertEqual(self._keys(t, "create_directory")[0], "Command-Shift-N")
            self.assertEqual(self._keys(t, "quick_view")[0], "SPACE")
            self.assertEqual(self._keys(t, "go_parent")[0], "Command-UP")
            self.assertEqual(self._keys(t, "quit_app"), ["Command-Q"])
            self.assertEqual(self._keys(t, "quit"), ["Ctrl-Q"])
        with _native_case("win32", "gui") as t:
            self.assertEqual(self._keys(t, "create_directory")[0], "Ctrl-Shift-N")
            self.assertEqual(self._keys(t, "file_details")[0], "Alt-ENTER")
            self.assertEqual(self._keys(t, "quit_app"), ["Alt-F4"])
            self.assertEqual(self._keys(t, "quit"), ["Ctrl-Q"])
        for platform_name in ("darwin", "win32", "linux"):
            with _native_case(platform_name, "vt") as t:
                self.assertEqual(self._keys(t, "create_directory"), ["F7"])
                self.assertEqual(self._keys(t, "clipboard_copy"), ["Ctrl-C"])
                self.assertEqual(self._keys(t, "rename"), ["F2"])

    def test_the_two_pane_operations_are_on_function_keys(self):
        for platform_name, backend in CASES:
            with _native_case(platform_name, backend) as t:
                self.assertEqual(self._keys(t, "copy_files"), ["F5"])
                self.assertEqual(self._keys(t, "move_files"), ["F6"])
                self.assertEqual(self._keys(t, "redraw"), [])

    def test_no_key_runs_two_file_list_actions(self):
        from collections import defaultdict
        from xefm.actions import FILER, registry
        own = {a.name for a in registry.actions(FILER)}
        for platform_name, backend in CASES:
            with self.subTest(case=(platform_name, backend)), \
                    _native_case(platform_name, backend) as t:
                kb = xefm_config.KeyBindings(t)
                seen = defaultdict(list)
                for action, value in t.items():
                    if action in own:
                        for expr in self._keys(t, action):
                            seen[kb._parse_key_expression(expr)].append(action)
                clashes = {k: v for k, v in seen.items() if len(v) > 1}
                self.assertEqual(clashes, {})

    def test_every_key_parses(self):
        for platform_name, backend in CASES:
            with _native_case(platform_name, backend) as t:
                kb = xefm_config.KeyBindings(t)
                with patch.object(kb, "logger") as logger:
                    for action in t:
                        for expr in self._keys(t, action) or []:
                            kb._parse_key_expression(expr)
                self.assertFalse(logger.warning.called, logger.warning.call_args_list)

    def test_the_terminal_case_binds_nothing_a_terminal_cannot_send(self):
        from xefm.actions import COMMON, FILER, registry
        ours = {a.name for a in registry.actions(FILER)} | \
            {a.name for a in registry.actions(COMMON)}
        with _native_case("linux", "vt") as t:
            kb = xefm_config.KeyBindings(t)
            for action in ours & set(t):
                for expr in self._keys(t, action):
                    ident, mods, _mode = kb._parse_key_expression(expr)
                    self.assertNotIn("cmd", mods, f"{action}: {expr}")
                    letter = len(ident) == 1 and ident.isalpha()
                    self.assertFalse(letter and {"ctrl", "shift"} <= mods,
                                     f"{action}: {expr}")
                    self.assertFalse(ident == "enter" and mods & {"ctrl", "alt"},
                                     f"{action}: {expr}")


class QuitAppEverywhere(unittest.TestCase):
    """Cmd-Q in the macOS app and Alt-F4 in the Windows app quit under every
    preset (quit_app). A terminal has no quit_app key at all: closing the
    terminal window is its own business."""

    def _quit_app(self, platform_name, backend, preset):
        with _native_case(platform_name, backend, preset) as t:
            value = t.get("quit_app")
            return value["keys"] if isinstance(value, dict) else value

    def test_the_desktop_app_gets_the_platform_key_under_every_preset(self):
        for preset in keymap_presets.PRESETS:
            with self.subTest(preset=preset):
                self.assertEqual(self._quit_app("darwin", "gui", preset), ["Command-Q"])
                self.assertEqual(self._quit_app("win32", "gui", preset), ["Alt-F4"])

    def test_a_terminal_gets_none(self):
        for platform_name in ("darwin", "linux", "win32"):
            for preset in keymap_presets.PRESETS:
                self.assertEqual(self._quit_app(platform_name, "vt", preset), [],
                                 (platform_name, preset))


class FontSizeKeys(unittest.TestCase):
    """The desktop app's text size keys: Cmd on macOS, Ctrl on Windows, under
    every preset, except that Orthodox's Ctrl-MINUS clears the selection, so
    its Windows app leaves Larger and Smaller to the menu and keeps Ctrl-0. A
    terminal draws in its own font and gets none."""

    ACTIONS = ("increase_font_size", "decrease_font_size", "reset_font_size")

    def _keys(self, platform_name, backend, preset):
        with _native_case(platform_name, backend, preset) as t:
            return {a: t[a]["keys"] if isinstance(t[a], dict) else t[a]
                    for a in self.ACTIONS}

    def test_the_macos_app(self):
        for preset in keymap_presets.PRESETS:
            with self.subTest(preset=preset):
                self.assertEqual(self._keys("darwin", "gui", preset), {
                    "increase_font_size": ["Command-+", "Command-="],
                    "decrease_font_size": ["Command-MINUS"],
                    "reset_font_size": ["Command-0"]})

    def test_the_windows_app(self):
        for preset in keymap_presets.PRESETS:
            with self.subTest(preset=preset):
                orthodox = preset == keymap_presets.ORTHODOX
                self.assertEqual(self._keys("win32", "gui", preset), {
                    "increase_font_size": [] if orthodox else ["Ctrl-+", "Ctrl-="],
                    "decrease_font_size": [] if orthodox else ["Ctrl-MINUS"],
                    "reset_font_size": ["Ctrl-0"]})

    def test_orthodox_keeps_ctrl_minus_for_unselect_all(self):
        with _native_case("win32", "gui", keymap_presets.ORTHODOX) as t:
            self.assertEqual(t["unselect_all"], ["Ctrl-MINUS"])

    def test_no_preset_clashes_with_them_in_the_windows_app(self):
        from collections import defaultdict
        from xefm.actions import FILER, registry
        own = {a.name for a in registry.actions(FILER)}
        for preset in keymap_presets.PRESETS:
            with self.subTest(preset=preset), \
                    _native_case("win32", "gui", preset) as t:
                kb = xefm_config.KeyBindings(t)
                seen = defaultdict(list)
                for action, value in t.items():
                    if action not in own:
                        continue
                    keys = value["keys"] if isinstance(value, dict) else value
                    sel = value.get("selection", "any") if isinstance(value, dict) else "any"
                    for expr in keys:
                        seen[(kb._parse_key_expression(expr), sel)].append(action)
                clashes = {k: v for k, v in seen.items()
                           if len(v) > 1 and set(v) & set(self.ACTIONS)}
                self.assertEqual(clashes, {})

    def test_a_terminal_gets_none(self):
        for platform_name in ("darwin", "linux", "win32"):
            for preset in keymap_presets.PRESETS:
                self.assertEqual(self._keys(platform_name, "vt", preset),
                                 {a: [] for a in self.ACTIONS},
                                 (platform_name, preset))


class InTheApp(unittest.TestCase):

    #: What keymap_presets.apply writes onto the config it is given.
    _PRESET_STATE = ("KEY_BINDINGS", "_KEY_BINDINGS_BASE", "_KEY_TYPE_AHEAD")

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        for name in ("alpha.txt", "beta.txt", "report.txt"):
            with open(os.path.join(self.tmp, name), "w") as fh:
                fh.write("x")
        self.state_dir = tempfile.mkdtemp()
        self.db = os.path.join(self.state_dir, "state.db")
        # Applying a preset rewrites the shared config's KEY_BINDINGS and stashes
        # the table it started from; keep all three as found, so the next test
        # file reads the developer's config and not the last preset tested here.
        shared = xefm_config.get_config()
        self._saved = {name: copy.deepcopy(shared.__dict__[name])
                       for name in self._PRESET_STATE if name in shared.__dict__}
        self.app = self._open()

    def _open(self, bindings=None):
        from puikit.backends import create_backend
        self.b = create_backend("memory")
        self.b.open()
        # The shared config is the developer's ~/.xefm/config.py; its own
        # KEY_BINDINGS would be laid over every preset here. Test the presets
        # as a config.py binding nothing would see them.
        shared = xefm_config.get_config()
        shared._KEY_BINDINGS_BASE = dict(bindings or {})
        app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                               left_provided=True, right_provided=True,
                               state_manager=XeFMStateManager(db_path=self.db))
        app.file_monitor.stop_monitoring()
        app.file_monitor.enabled = False
        app._settle_listings()
        app.panel.render()
        return app

    def tearDown(self):
        # Leave the shared config as it was found for the next test file. Not
        # by applying a preset again: with no stashed base, apply() would take
        # the table this test left behind for the developer's own entries.
        shared = self.app.config
        for name in self._PRESET_STATE:
            if name in self._saved:
                setattr(shared, name, self._saved[name])
            else:
                shared.__dict__.pop(name, None)
        xefm_config.config_manager._key_bindings = None
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _action(self, event):
        return self.app.keys.find_action_for_event(event, False, "filer")

    def test_a_key_bound_to_a_config_py_action_leaves_the_preset_action(self):
        """#662 with an action of config.py's own: it is registered after the
        keymap is first built, and the keymap is built again once it is, so
        the preset action gives up the key (and the help and menus stop
        listing it there)."""
        def say_hi(ctx):
            """Say hi."""
        shared = xefm_config.get_config()
        saved_actions = getattr(shared, "ACTIONS", None)
        shared.ACTIONS = {"say_hi": say_hi}
        try:
            self.app.file_monitor.stop_monitoring()
            self.b.close()
            self.app = self._open({"say_hi": ["Shift-T"]})
            self.assertEqual(self._action(_key("t", "T", {"shift"})), "say_hi")
            self.assertNotIn("Shift-T", self.app.config.KEY_BINDINGS["open_in_new_tab"])
        finally:
            shared.ACTIONS = saved_actions
            from xefm.user_api import load_user_entries
            load_user_entries(shared)

    def test_switching_relabels_the_keymap_at_once(self):
        self.assertEqual(self._action(_key("v", "v")), "view_file")
        self.app.set_keymap_preset("orthodox")
        self.assertEqual(self._action(_key("f5")), "copy_files")
        self.assertEqual(self._action(_key("f8")), "delete_files")
        self.assertEqual(self._action(_key("f3")), "view_file")
        self.assertIsNone(self._action(_key("v", "v")))
        self.assertIn("Orthodox", self.app.log.lines[-1][0])

    def test_a_typed_letter_starts_a_search_with_it(self):
        self.app.set_keymap_preset("orthodox")
        self.app.on_event(_key("r", "r"))
        self.assertTrue(self.app._isearch_active)
        self.assertEqual(self.app._isearch_bar.pattern, "r")
        pane = self.app.active_pane()
        self.assertEqual(pane["files"][pane["focused_index"]].name, "report.txt")

    # --- quick search: the classic behaviour (Total Commander's) ------------

    def _focused(self):
        pane = self.app.active_pane()
        return pane["files"][pane["focused_index"]].name

    def _quick(self, text):
        self.app.set_keymap_preset("orthodox")
        for ch in text:
            self.app.on_event(_key(ch, ch))

    def test_quick_search_is_the_i_search_with_its_matching(self):
        self._quick("a")
        self.assertEqual(self.app._isearch_bar.prompt, "I-Search:")
        names = {self.app.active_pane()["files"][i].name
                 for i in self.app._isearch_matches}
        self.assertEqual(names, {"alpha.txt", "beta.txt"}, "contains, as I-Search")

    def test_esc_closes_and_keeps_the_cursor_on_the_match(self):
        self._quick("r")
        self.app.on_event(_key("escape"))
        self.assertFalse(self.app._isearch_active)
        self.assertEqual(self._focused(), "report.txt")

    def test_another_key_closes_the_search_and_acts(self):
        self._quick("r")
        ran = []
        with patch.object(self.app, "dispatch",
                          lambda action: ran.append(action) or True):
            self.app.on_event(_key("f5"))
        self.assertFalse(self.app._isearch_active)
        self.assertEqual(ran, ["copy_files"])
        self.assertEqual(self._focused(), "report.txt")

    def test_enter_opens_the_match(self):
        os.mkdir(os.path.join(self.tmp, "reports"))
        self.app._relist(self.app.active_pane())
        self.app._settle_listings()
        self._quick("reports")
        self.app.on_event(_key("enter"))
        self.app._settle_listings()
        self.assertFalse(self.app._isearch_active)
        self.assertEqual(str(self.app.active_pane()["path"]),
                         os.path.join(self.tmp, "reports"))

    def test_backspace_still_edits(self):
        self._quick("re")
        self.app.on_event(_key("backspace"))
        self.assertTrue(self.app._isearch_active)
        self.assertEqual(self.app._isearch_bar.pattern, "r")

    def test_the_status_bar_says_other_keys_act(self):
        self._quick("r")
        self.assertIn("other keys act on the file", self.app.status._text())

    def test_the_isearch_key_keeps_its_own_closing(self):
        self.app.set_keymap_preset("orthodox")
        self.app.enter_isearch()
        self.app.on_event(_key("r", "r"))
        self.app.on_event(_key("f5"))
        self.assertTrue(self.app._isearch_active, "F5 does not end an I-Search")

    def test_the_default_keymap_has_no_type_ahead(self):
        self.app.on_event(_key("z", "z"))
        self.assertFalse(self.app._isearch_active)

    def test_the_choice_is_remembered(self):
        self.app.set_keymap_preset("orthodox")
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        self.app = self._open()
        self.assertEqual(self.app._keymap_preset, "orthodox")
        self.assertEqual(self._action(_key("f5")), "copy_files")

    def test_key_preset_in_config_wins(self):
        self.app.config.KEY_PRESET = "default"
        try:
            self.app._apply_keymap_preset()
            self.app.set_keymap_preset("orthodox")
            self.assertEqual(self.app._keymap_preset, "afx")
            self.assertIn("KEY_PRESET", self.app.log.lines[-1][0])
        finally:
            self.app.config.KEY_PRESET = None

    # --- the first launch (#597) ---------------------------------------------

    def _reopen(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        self.app = self._open()

    def _forget(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        os.remove(self.db)
        self.app = self._open()

    def test_nothing_chosen_is_asked_new_install_or_upgrade_alike(self):
        """No preset is the default: with none chosen, whether config.py is
        new or from an earlier XeFM, the launch asks."""
        self._forget()
        self.assertIsNone(self.app._keymap_preset)
        self.assertIsNone(self.app.state_manager.get_state("keymap.preset"))
        asked = []
        with patch.object(xefm_app, "show_message_box",
                          lambda *a, **k: asked.append(dict(k, text=a[1]))):
            self.app._ask_keymap_preset()
        self.assertEqual(asked[0]["buttons"],
                         ("AFX style", "Orthodox", "OS native", "Vim style"))
        # The buttons are short; each preset's full label and description is
        # in the text above them.
        for preset in keymap_presets.PRESETS.values():
            self.assertIn(preset.label, asked[0]["text"])
            self.assertIn(preset.description, asked[0]["text"])
        self.assertFalse(asked[0]["dismissable"], "there is no Cancel")
        asked[0]["on_result"]("Orthodox")
        self.assertEqual(self.app._keymap_preset, "orthodox")
        self.assertEqual(self._action(_key("f5")), "copy_files")

    def _menu_dialog(self):
        asked = []
        with patch.object(xefm_app, "show_message_box",
                          lambda *a, **k: asked.append(dict(k, text=a[1]))):
            self.app.choose_keymap()
        return asked[0]

    def test_the_menu_opens_the_same_dialog_with_a_cancel(self):
        self.app.set_keymap_preset("orthodox")
        shown = self._menu_dialog()
        self.assertEqual(shown["buttons"],
                         ("AFX style", "Orthodox", "OS native", "Vim style", "Cancel"))
        self.assertTrue(shown["dismissable"])
        self.assertEqual(shown["cancel"], 4)
        self.assertEqual(shown["default"], 1)              # the current one
        self.assertIn("**Orthodox** (current)", shown["text"])
        for preset in keymap_presets.PRESETS.values():
            self.assertIn(preset.description, shown["text"])

    def test_choosing_in_the_menu_dialog_switches_and_cancel_does_not(self):
        self.app.set_keymap_preset("afx")
        self._menu_dialog()["on_result"]("Cancel")
        self.assertEqual(self.app._keymap_preset, "afx")
        self._menu_dialog()["on_result"]("Vim style")
        self.assertEqual(self.app._keymap_preset, "vim")

    def test_the_menu_dialog_says_when_config_py_decides(self):
        self.app.config.KEY_PRESET = "orthodox"
        try:
            self.assertIn("KEY_PRESET = 'orthodox'", self._menu_dialog()["text"])
        finally:
            self.app.config.KEY_PRESET = None

    def test_the_tools_menu_has_one_keymap_item(self):
        tools = next(i for i in self.app._build_menu().items if i.label == "Tools")
        advanced = next(i for i in tools.submenu.items
                        if getattr(i, "label", "") == "Advanced")
        keymap = [i for i in advanced.submenu.items
                  if getattr(i, "label", "").startswith("Keymap")]
        self.assertEqual([i.label for i in keymap], ["Keymap…"])
        self.assertIsNone(keymap[0].submenu)

    def test_quitting_unanswered_asks_again_at_the_next_launch(self):
        self._forget()
        self._reopen()
        self.assertIsNone(self.app._keymap_preset)
        self.app.set_keymap_preset("afx")
        self._reopen()
        self.assertEqual(self.app._keymap_preset, "afx")

    def test_switching_says_what_config_py_replaces(self):
        self.app.config._KEY_BINDINGS_BASE = {"copy_files": ["C"]}
        self.app.set_keymap_preset("orthodox")
        self.assertIn("replaces this keymap's keys for 1 action(s): copy_files",
                      self.app.log.lines[-1][0])
        self.assertEqual(self._action(_key("c", "c")), "copy_files")


if __name__ == "__main__":
    unittest.main()
