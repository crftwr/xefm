"""The help dialog against the backend it is being shown on.

XeFM runs the same widget code as a desktop app and as a TUI, and a few actions
only one of them can perform. The help used to list them unconditionally, so the
macOS build offered ``F10, Alt — Open the menu bar`` (PuiKit's ``MenuBar`` opens
nothing once the OS bar owns the menu) and ``Open a shell in the current directory``
(``subshell`` needs a terminal to hand over). Both rows named a key and then did
nothing when pressed.

``_help_markdown`` is built here from a bare instance — the keymap and a stubbed
menu bar are all it reads — so both frontends can be checked in one process.
"""

import re
import types
import unittest

import xefm.app as app_module
from xefm import _config
from xefm.app import UNBOUND_KEYS, XeFMApp
from xefm.config import KeyBindings


def menu_bar(*, takes_activation_key: bool):
    """A stand-in for PuiKit's MenuBar, which reports whether an activation key
    (F10, a bare Alt tap) opens it — False once an OS bar owns the menu."""
    return types.SimpleNamespace(takes_activation_key=takes_activation_key)


class HelpMarkdownCase(unittest.TestCase):
    """Builds the help body for a chosen frontend."""

    def setUp(self):
        # is_desktop_mode() caches a process-wide answer, so the gate reads the
        # module global and each test puts back what it found.
        real = app_module.is_desktop_mode
        self.addCleanup(setattr, app_module, "is_desktop_mode", real)

    def help_for(self, *, native_menus: bool, desktop: bool) -> str:
        app_module.is_desktop_mode = lambda: desktop
        app = object.__new__(XeFMApp)  # no __init__: no config file, no panel
        app.keys = KeyBindings(_config.Config.KEY_BINDINGS)
        app.menu_bar = menu_bar(takes_activation_key=not native_menus)
        return app._help_markdown()

    def desktop_help(self) -> str:
        return self.help_for(native_menus=True, desktop=True)

    def terminal_help(self) -> str:
        return self.help_for(native_menus=False, desktop=False)


class TestBackendGatedRows(HelpMarkdownCase):

    def test_menu_bar_row_is_absent_under_an_os_menu_bar(self):
        # MenuBar.open_menu returns False on a native_menus backend, so the key
        # would be advertised and then answer nothing.
        self.assertNotIn("Open the menu bar", self.desktop_help())

    def test_menu_bar_row_is_present_in_the_terminal(self):
        self.assertIn("Open the menu bar", self.terminal_help())

    def test_subshell_row_is_absent_in_desktop_mode(self):
        # subshell() logs "it needs a terminal, and desktop mode has none".
        self.assertNotIn("Open a shell in the current directory",
                         self.desktop_help())

    def test_subshell_row_is_present_in_the_terminal(self):
        self.assertIn("Open a shell in the current directory",
                      self.terminal_help())

    def test_gating_only_removes_rows(self):
        # Every desktop row is also a terminal row: the gate subtracts, it never
        # rewrites or reorders what both frontends share.
        rows = lambda md: [line for line in md.splitlines() if line.startswith("| ")]
        desktop, terminal = rows(self.desktop_help()), rows(self.terminal_help())
        self.assertTrue(set(desktop) <= set(terminal))
        self.assertEqual(desktop, [r for r in terminal if r in set(desktop)])

    def test_a_fully_gated_section_loses_its_heading(self):
        # Nothing gates a whole section today; the dialog must not grow an empty
        # table if something ever does.
        gates = dict(XeFMApp._BACKEND_GATED)
        gates.update({name: (lambda self: False)
                      for name, _desc in dict(XeFMApp._HELP_SECTIONS)["Other"]})
        self.addCleanup(setattr, XeFMApp, "_BACKEND_GATED",
                        XeFMApp._BACKEND_GATED)
        XeFMApp._BACKEND_GATED = gates
        self.assertNotIn("## Other", self.terminal_help())


class TestUnboundRowsReadAsUnbound(HelpMarkdownCase):

    #: A key cell holding a code span — what a real binding renders as.
    _CODE_KEY = re.compile(r"^\| `.+?` \| ", re.MULTILINE)

    def test_unbound_key_is_not_typeset_as_a_key(self):
        # "—" in the same code style as Q or ? reads as a key you could press,
        # and reset_log_height's binding really is an underscore.
        md = self.terminal_help()
        self.assertIn(f"| {UNBOUND_KEYS} | Copy the whole log", md)
        self.assertNotIn(f"| `{UNBOUND_KEYS}` |", md)

    def test_bound_key_is_still_typeset_as_a_key(self):
        md = self.terminal_help()
        self.assertIn("| `Q` | Quit XeFM |", md)
        self.assertIn("| `_` | Reset the log pane height |", md)
        self.assertTrue(self._CODE_KEY.search(md))

    def test_every_unbound_row_names_the_menu_that_reaches_it(self):
        # A row with no key and no route names a feature and withholds the one
        # way to use it.
        routeless = [line for line in self.terminal_help().splitlines()
                     if line.startswith(f"| {UNBOUND_KEYS} |")
                     and "menu)" not in line]
        self.assertEqual(routeless, [],
                         f"unbound help rows with no route: {routeless}")

    def test_menu_routes_match_the_menu_bar(self):
        md = self.terminal_help()
        self.assertIn("Copy the whole log (Edit menu)", md)
        self.assertIn("(Tools menu)", md)


if __name__ == "__main__":
    unittest.main()
