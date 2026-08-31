"""The incremental-search bar's own keys (issue #347).

The bar is the one surface whose keys compete with typing, so its routing is
tested from both ends: the widget's key dispatch (text first, then the actions
it owns, then the field) and the file list's Shift+Up/Down marking through a
live app.

See xefm/isearch_bar.py, the ``isearch`` context in xefm/actions.py, and
doc/dev/KEY_BINDINGS_IMPLEMENTATION.md.

Run with: python -m pytest test/test_isearch_keys.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit.event import Event, EventType, char_key_event

from xefm import _config
from xefm import app as xefm_app
from xefm.actions import ISEARCH
from xefm.config import (KeyBindings, printable_isearch_bindings,
                         printable_isearch_notice)
from xefm.isearch_bar import ISearchBar
from xefm.state_manager import XeFMStateManager

from puikit.backends import create_backend


def _key(name, mods=()):
    return Event(type=EventType.KEY, key=name, modifiers=frozenset(mods))


class Calls:
    """Recorder standing in for the controller's callbacks."""

    def __init__(self):
        self.navigate = []
        self.select = []
        self.select_all = 0
        self.submitted = 0
        self.cancelled = 0

    def bar(self, **kw) -> ISearchBar:
        opts = dict(on_navigate=self.navigate.append,
                    on_select=self.select.append,
                    on_select_all=self._select_all,
                    on_submit=self._submit,
                    on_cancel=self._cancel)
        opts.update(kw)
        return ISearchBar(**opts)

    def _select_all(self):
        self.select_all += 1

    def _submit(self):
        self.submitted += 1

    def _cancel(self):
        self.cancelled += 1


# --- the keymap --------------------------------------------------------------


def test_defaults_resolve_in_the_isearch_context():
    kb = KeyBindings(_config.Config().KEY_BINDINGS)
    # Not in the shipped KEY_BINDINGS at all — they resolve from the action's
    # own defaults, like every other dotted (viewer) action.
    assert kb.get_keys_for_action("isearch.toggle_select_down", ISEARCH)[0] == \
        ["Shift-DOWN"]
    assert kb.get_keys_for_action("isearch.next_match", ISEARCH)[0] == ["DOWN"]
    assert kb.get_keys_for_action("isearch.cancel", ISEARCH)[0] == ["ESCAPE"]
    assert kb.get_keys_for_action("isearch.select_matches", ISEARCH)[0] == \
        ["Ctrl-A"]


def test_a_config_can_rebind_an_isearch_key():
    kb = KeyBindings(dict(_config.Config().KEY_BINDINGS,
                          **{"isearch.toggle_select_down": ["INSERT"]}))
    assert kb.get_keys_for_action("isearch.toggle_select_down", ISEARCH)[0] == \
        ["INSERT"]
    assert kb.find_action_for_event(_key("insert"), context=ISEARCH) == \
        "isearch.toggle_select_down"
    # An entry replaces the default rather than adding to it.
    assert kb.find_action_for_event(_key("down", {"shift"}), context=ISEARCH) != \
        "isearch.toggle_select_down"


def test_isearch_keys_do_not_leak_into_the_file_list():
    """The dotted names belong to one context, like every viewer action."""
    from xefm.actions import FILER
    kb = KeyBindings(_config.Config().KEY_BINDINGS)
    assert kb.get_keys_for_action("isearch.next_match", FILER)[0] == []


def test_printable_binding_is_reported():
    bindings = dict(_config.Config().KEY_BINDINGS,
                    **{"isearch.toggle_select_down": ["N"],
                       "isearch.accept": ["SPACE"]})
    found = dict(printable_isearch_bindings(bindings))
    assert found == {"isearch.toggle_select_down": "N",
                     "isearch.accept": "SPACE"}
    notice = printable_isearch_notice(bindings)
    assert notice and "never fire" in notice


def test_defaults_and_chords_are_not_reported():
    plain = _config.Config().KEY_BINDINGS
    assert printable_isearch_bindings(plain) == []
    assert printable_isearch_notice(plain) is None
    # A Ctrl chord is a command, not typing: the field passes it on, so the bar
    # can have it.
    assert printable_isearch_bindings(
        dict(plain, **{"isearch.next_match": ["Ctrl-N"]})) == []


# --- the bar's key routing ---------------------------------------------------


def test_printable_keys_are_typed_not_dispatched():
    """'Q' quits and '?' helps a row above; here they are just text. SPACE most
    of all — it separates the pattern's tokens, which is why the file list's
    SPACE cannot mark a file during a search (#347)."""
    c = Calls()
    bar = c.bar()
    for ch in "q?a b":
        bar.handle_event(char_key_event(ch))
    assert bar.pattern == "q?a b"
    assert (c.navigate, c.select, c.submitted, c.cancelled) == ([], [], 0, 0)


def test_shift_arrows_mark_and_walk():
    c = Calls()
    bar = c.bar()
    bar.handle_event(_key("down", {"shift"}))
    bar.handle_event(_key("up", {"shift"}))
    assert c.select == [1, -1]
    assert c.navigate == []
    assert bar.pattern == ""


def test_plain_arrows_walk_the_matches():
    c = Calls()
    bar = c.bar()
    bar.handle_event(_key("down"))
    bar.handle_event(_key("up"))
    assert c.navigate == [1, -1]
    assert c.select == []


def test_enter_accepts_and_escape_cancels():
    c = Calls()
    bar = c.bar()
    bar.handle_event(_key("enter"))
    bar.handle_event(_key("escape"))
    assert (c.submitted, c.cancelled) == (1, 1)


def test_editing_keys_still_reach_the_field():
    c = Calls()
    bar = c.bar()
    for ch in "abc":
        bar.handle_event(char_key_event(ch))
    bar.handle_event(_key("backspace"))
    bar.handle_event(_key("left"))
    bar.handle_event(char_key_event("x"))
    assert bar.pattern == "axb"
    assert (c.navigate, c.select) == ([], [])


def test_ctrl_a_marks_every_match():
    """Chords are taken out before the printable test, in the order TextEdit
    itself uses — otherwise Ctrl-A would type "a" into the pattern instead."""
    c = Calls()
    bar = c.bar()
    bar.handle_event(char_key_event("a", frozenset({"ctrl"})))
    assert c.select_all == 1
    assert bar.pattern == ""
    assert (c.navigate, c.select, c.submitted, c.cancelled) == ([], [], 0, 0)


def test_cmd_a_is_left_to_the_field():
    """Only the Ctrl form is the action: Cmd-A stays macOS's select-all-text,
    and either way the letter is not typed."""
    c = Calls()
    bar = c.bar()
    for ch in "abc":
        bar.handle_event(char_key_event(ch))
    bar.handle_event(char_key_event("a", frozenset({"cmd"})))
    assert c.select_all == 0
    assert bar.pattern == "abc"


def test_common_actions_inherited_by_the_context_do_not_fire(monkeypatch):
    """``quit`` resolves in the isearch context (every context inherits the
    common actions), but the bar runs only what it owns — tearing the app down
    from under an open prompt is not one of them."""
    import xefm.isearch_bar as isearch_bar

    monkeypatch.setattr(isearch_bar, "is_action_for_event",
                        lambda event, name, **kw: name == "quit")
    c = Calls()
    bar = c.bar()
    bar.handle_event(_key("f2"))
    assert (c.navigate, c.select, c.submitted, c.cancelled) == ([], [], 0, 0)
    assert bar.pattern == ""


def test_a_viewer_bar_leaves_the_select_keys_to_the_field():
    """No selection to mark, so ``on_select`` is never passed and the actions
    are simply not claimed."""
    c = Calls()
    bar = c.bar(on_select=None, on_select_all=None)
    bar.handle_event(_key("down", {"shift"}))
    bar.handle_event(char_key_event("a", frozenset({"ctrl"})))
    assert c.select == [] and c.navigate == [] and c.select_all == 0
    assert bar.pattern == ""


# --- through a live file list ------------------------------------------------


class ISearchSelectionTest(unittest.TestCase):
    """Shift+Down marks the file the search is sitting on and moves to the next
    match — the whole point of #347."""

    NAMES = ["alpha.txt", "beta.txt", "delta.txt", "gamma_alpha.txt"]

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
        self.app.panel.render()          # the footer rect isearch anchors to

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _search(self, pattern):
        self.app.enter_isearch()
        self.assertTrue(self.app._isearch_active)
        for ch in pattern:
            self.app.panel.dispatch_event(char_key_event(ch))

    def _selected(self):
        return sorted(os.path.basename(p) for p in self.pane["selected_files"])

    def _focused(self):
        return self.pane["files"][self.pane["focused_index"]].name

    def test_shift_down_marks_each_match_in_turn(self):
        self._search("alpha")                       # alpha.txt, gamma_alpha.txt
        self.assertEqual(self.app._isearch_matches, [0, 3])
        self.assertEqual(self._focused(), "alpha.txt")

        self.app.panel.dispatch_event(_key("down", {"shift"}))
        self.assertEqual(self._selected(), ["alpha.txt"])
        self.assertEqual(self._focused(), "gamma_alpha.txt")

        self.app.panel.dispatch_event(_key("down", {"shift"}))
        self.assertEqual(self._selected(), ["alpha.txt", "gamma_alpha.txt"])
        self.assertEqual(self._focused(), "alpha.txt")   # wrapped

        # Marking again clears it, as SPACE does in the file list.
        self.app.panel.dispatch_event(_key("up", {"shift"}))
        self.assertEqual(self._selected(), ["gamma_alpha.txt"])
        self.assertEqual(self._focused(), "gamma_alpha.txt")

    def test_space_still_types_into_the_pattern(self):
        self._search("alpha")
        self.app.panel.dispatch_event(char_key_event(" "))
        self.assertEqual(self.app._isearch_bar.pattern, "alpha ")
        self.assertEqual(self._selected(), [])

    def test_marks_survive_the_search(self):
        self._search("alpha")
        self.app.panel.dispatch_event(_key("down", {"shift"}))
        self.app.panel.dispatch_event(_key("enter"))     # stop here
        self.assertFalse(self.app._isearch_active)
        self.assertEqual(self._selected(), ["alpha.txt"])

    def test_ctrl_a_marks_the_whole_match_set(self):
        self._search("alpha")
        self.app.panel.dispatch_event(char_key_event("a", frozenset({"ctrl"})))
        self.assertEqual(self._selected(), ["alpha.txt", "gamma_alpha.txt"])
        # Again clears exactly those, rather than inverting item by item.
        self.app.panel.dispatch_event(char_key_event("a", frozenset({"ctrl"})))
        self.assertEqual(self._selected(), [])

    def test_marks_outside_the_match_set_survive(self):
        """Narrowing the pattern and marking again accumulates."""
        self.pane["selected_files"] = {str(self.pane["files"][1])}   # beta.txt
        self._search("alpha")
        self.app.panel.dispatch_event(char_key_event("a", frozenset({"ctrl"})))
        self.assertEqual(self._selected(),
                         ["alpha.txt", "beta.txt", "gamma_alpha.txt"])

    def test_hint_line_names_the_select_keys(self):
        hints = self.app.status._isearch_hints()
        self.assertIn("Shift-↑/Shift-↓ select", hints)
        self.assertIn("Ctrl-A all", hints)
        self.assertIn("↑/↓ prev/next match", hints)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
