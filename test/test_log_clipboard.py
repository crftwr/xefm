"""The log pane's clipboard copies (issue #360).

Copying the log used to be one hardcoded chord — Cmd-C on the macOS GUI,
Ctrl-C everywhere else — resolved before the keymap and gated on the log
holding keyboard focus. Nothing named it, so it could not be rebound, did not
appear in the help, and had no menu item: the reporter concluded the feature
did not exist.

It is now two ordinary ``filer`` actions, ``copy_log_selection`` and
``copy_log_all``, which reach into the log without needing focus exactly as
``scroll_log_up`` and its siblings always have.

Run with: python -m pytest test/test_log_clipboard.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit.backends import create_backend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402
from puikit.menu import Menu, MenuItem  # noqa: E402

from xefm import _config  # noqa: E402
from xefm import app as xefm_app  # noqa: E402
from xefm.actions import FILER  # noqa: E402
from xefm.config import KeyBindings  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


def _key(name, mods=()):
    return Event(type=EventType.KEY, key=name, modifiers=frozenset(mods))


def _find_item(menu: Menu, label: str) -> MenuItem:
    for entry in menu.items:
        if isinstance(entry, MenuItem):
            if entry.label == label:
                return entry
            if entry.submenu is not None:
                found = _find_item(entry.submenu, label)
                if found is not None:
                    return found
    return None


class LogClipboardActions(unittest.TestCase):
    def setUp(self):
        self.left = tempfile.mkdtemp()
        self.right = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.left, self.right,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app.panel.set_text_effect(False)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.app.panel.render()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
        except Exception:
            pass
        self.b.close()
        shutil.rmtree(self.left, ignore_errors=True)
        shutil.rmtree(self.right, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _log(self, *messages):
        """Put lines in the pane and lay them out — the selection helpers below
        address display rows, which only exist once a draw has wrapped them."""
        for message in messages:
            self.app.log_info(message)
        self.app.panel.render()

    # --- copy_log_selection --------------------------------------------------

    def test_copies_the_selection_without_the_log_holding_focus(self):
        self._log("alpha line", "beta line")
        self.app.log._select_all()
        self.assertIsNot(self.app.panel.focused_leaf(), self.app.log,
                         "the log is not the focused widget; the copy must "
                         "work anyway")

        self.app.copy_log_selection()

        text = self.b.get_clipboard()
        self.assertIn("alpha line", text)
        self.assertIn("beta line", text)

    def test_copying_drops_the_highlight(self):
        self._log("alpha line")
        self.app.log._select_all()
        self.app.copy_log_selection()
        self.assertEqual(self.app.log.selection_text(), "")

    def test_no_selection_leaves_the_clipboard_alone(self):
        self._log("alpha line")
        self.b.set_clipboard("untouched")
        self.app.copy_log_selection()
        self.assertEqual(self.b.get_clipboard(), "untouched")

    # --- copy_log_all --------------------------------------------------------

    def test_copies_every_line_including_those_scrolled_out_of_view(self):
        self._log(*[f"line {i}" for i in range(200)])
        self.app.copy_log_all()
        copied = self.b.get_clipboard().splitlines()
        self.assertIn("line 0", copied)
        self.assertIn("line 199", copied)

    def test_reports_the_count(self):
        self._log("only line")
        self.app.copy_log_all()
        count = len(self.b.get_clipboard().splitlines())
        self.app.panel.render()
        screen = "\n".join(self.b.snapshot())
        self.assertIn(f"Copied {count} log lines to clipboard", screen)

    # --- bindings ------------------------------------------------------------

    def test_the_copy_chord_resolves_to_the_action(self):
        keys = KeyBindings(_config.Config.KEY_BINDINGS)
        self.assertEqual(
            keys.find_action_for_event(_key("c", ("ctrl",)), False, FILER),
            "copy_log_selection")
        if sys.platform != "win32":
            self.assertEqual(
                keys.find_action_for_event(_key("c", ("cmd",)), False, FILER),
                "copy_log_selection")

    def test_a_config_predating_the_action_still_gets_the_chord(self):
        """Nobody's ~/.xefm/config.py mentions these names — _copy_missing_fields
        fills whole missing fields, never a missing key inside KEY_BINDINGS — so
        the registry's own default has to carry them."""
        keys = KeyBindings({})
        self.assertEqual(
            keys.find_action_for_event(_key("c", ("ctrl",)), False, FILER),
            "copy_log_selection")

    def test_copy_log_all_ships_unbound(self):
        keys = KeyBindings(_config.Config.KEY_BINDINGS)
        self.assertEqual(keys.get_keys_for_action("copy_log_all")[0], [])

    # --- the menu ------------------------------------------------------------

    def test_the_edit_menu_carries_both_log_copies(self):
        edit = _find_item(self.app._build_menu(), "Edit")
        self.assertIsNotNone(edit, "no Edit menu")
        self.assertIsNotNone(_find_item(edit.submenu, "Copy Log Selection"))
        self.assertIsNotNone(_find_item(edit.submenu, "Copy All Logs"))

    def test_the_menu_item_puts_its_log_line_on_screen(self):
        """Same property as #253: a native menu fires on_select with nothing
        rendering afterwards, so the item itself must leave the screen current."""
        self._log("only line")
        item = _find_item(self.app._build_menu(), "Copy All Logs")
        item.on_select()
        screen = "\n".join(self.b.snapshot())
        self.assertIn("log lines to clipboard", screen)

    def test_the_menu_hint_survives_a_config_that_predates_the_action(self):
        """_menu_shortcut resolves in the filer context, so the hint comes from
        the registry default when KEY_BINDINGS never names the action — the flat
        lookup it used to do showed nothing at all."""
        edit = _find_item(self.app._build_menu(), "Edit")
        item = _find_item(edit.submenu, "Copy Log Selection")
        self.assertIsNotNone(item.shortcut)

    def test_copy_log_selection_item_is_disabled_without_a_selection(self):
        self._log("alpha line")
        item = _find_item(self.app._build_menu(), "Copy Log Selection")
        self.assertFalse(item.enabled())
        self.app.log._select_all()
        item = _find_item(self.app._build_menu(), "Copy Log Selection")
        self.assertTrue(item.enabled())


if __name__ == "__main__":
    unittest.main()
