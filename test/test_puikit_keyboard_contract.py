"""Characterization / spec test for the PuiKit keyboard contract.

This is the headless half of the keyboard-contract harness described in
``doc/dev/PUIKIT_KEYBOARD_CONTRACT.md``. It drives the two implemented PuiKit
backends' key-translation paths directly (no window, no terminal) and asserts
the proposed contract.

Cases PuiKit does **not** yet satisfy are marked ``xfail(strict=True)`` with a
reference to the §3 change that fixes them: each flips to a real pass exactly
when that backend change lands, and fails loudly if a future change regresses
the contract. So this file doubles as a checklist for the PuiKit-side work.

It also includes a small *reference matcher* (the logic XeFM's binding parser
will use) driven by already-normalized events, proving the contract is
sufficient to express XeFM's tricky bindings (``a`` vs ``Shift-A``, ``?``,
``Shift-SPACE``) regardless of the current backend gaps.
"""

import curses

import pytest

from puikit.event import EventType, char_key_event


# --------------------------------------------------------------------------- #
# Backend access helpers
# --------------------------------------------------------------------------- #

def _curses_event(ch):
    """Translate a single curses input (str from get_wch, or int key code)
    through the real backend logic, without initialising curses."""
    from puikit.backends.curses_backend import CursesBackend

    backend = CursesBackend.__new__(CursesBackend)  # skip __init__ / curses
    return backend._translate(ch)


# AppKit modifier-flag bits (NSEventModifierFlag*).
_NS_SHIFT = 1 << 17
_NS_CTRL = 1 << 18
_NS_ALT = 1 << 19
_NS_CMD = 1 << 20


def _as_tuple(ev):
    if ev is None:
        return None
    return (ev.type, ev.key, ev.char, frozenset(ev.modifiers))


# --------------------------------------------------------------------------- #
# Curses backend contract
# --------------------------------------------------------------------------- #

class TestCursesContract:
    def test_lowercase_letter(self):
        ev = _curses_event("a")
        assert (ev.type, ev.key, ev.char) == (EventType.KEY, "a", "a")
        assert ev.modifiers == frozenset()

    def test_ctrl_letter(self):
        # Ctrl+A arrives as byte 0x01.
        ev = _curses_event("\x01")
        assert ev.key == "a"
        assert ev.modifiers == frozenset({"ctrl"})

    def test_named_key_enter_escape_tab(self):
        assert _curses_event("\n").key == "enter"
        assert _curses_event("\x1b").key == "escape"
        assert _curses_event("\t").key == "tab"

    def test_punctuation_identity(self):
        # Rule 3: identity is the literal glyph; shift is not part of it.
        for ch in ("?", "@", "=", "-", "[", "]", ";"):
            ev = _curses_event(ch)
            assert (ev.key, ev.char) == (ch, ch), ch

    def test_shift_letter_normalized(self):
        # Rule 2: Shift-A must be key='a' + {'shift'} on every backend.
        ev = _curses_event("A")
        assert ev.key == "a"
        assert ev.char == "A"
        assert ev.modifiers == frozenset({"shift"})

    def test_function_key_f5(self):
        ev = _curses_event(curses.KEY_F5)
        assert _as_tuple(ev)[:2] == (EventType.KEY, "f5")

    def test_space_is_named(self):
        # SPACE is a named key (so Shift-SPACE is expressible) but keeps the
        # typed glyph on char so text fields still insert a space.
        ev = _curses_event(" ")
        assert ev.key == "space"
        assert ev.char == " "


# --------------------------------------------------------------------------- #
# macOS backend contract (skipped where the GUI backend can't import)
# --------------------------------------------------------------------------- #

class TestMacOSContract:
    def _translate(self, characters, flags=0):
        m = pytest.importorskip("puikit.backends.macos_backend")
        return m.translate_key(characters, flags)

    def test_lowercase_letter(self):
        ev = self._translate("a", 0)
        assert (ev.key, ev.char) == ("a", "a")
        assert ev.modifiers == frozenset()

    def test_ctrl_letter(self):
        ev = self._translate("a", _NS_CTRL)
        assert ev.key == "a"
        assert "ctrl" in ev.modifiers

    def test_cmd_enter_is_gui_chord(self):
        ev = self._translate("\r", _NS_CMD)
        assert ev.key == "enter"
        assert "cmd" in ev.modifiers

    def test_punctuation_identity_drops_shift(self):
        # Shift+/ produces '?'; the shifted glyph is the identity and Shift is
        # already baked into it, so it must NOT appear in modifiers — matching
        # the curses backend, which has no shift to report (Rule 3).
        ev = self._translate("?", _NS_SHIFT)
        assert (ev.key, ev.char) == ("?", "?")
        assert "shift" not in ev.modifiers

    def test_punctuation_keeps_cmd_drops_shift(self):
        # Shift+Cmd+1 -> '!': drop Shift (in the glyph), keep Cmd (significant).
        ev = self._translate("!", _NS_SHIFT | _NS_CMD)
        assert ev.key == "!"
        assert ev.modifiers == frozenset({"cmd"})

    def test_shift_letter_normalized(self):
        ev = self._translate("A", _NS_SHIFT)
        assert ev.key == "a"
        assert ev.char == "A"
        assert "shift" in ev.modifiers

    def test_function_key_f5(self):
        ev = self._translate(chr(0xF708), 0)  # NSF5FunctionKey
        assert ev is not None and ev.key == "f5"


# --------------------------------------------------------------------------- #
# Shared printable-glyph contract (puikit.event.char_key_event). Every backend
# (curses, macOS, AND Windows) routes its printable-char path through this, so
# testing it here covers all three on any OS — including the Windows backend,
# whose module can't even import off-Windows.
# --------------------------------------------------------------------------- #

class TestCharKeyEventContract:
    def test_plain_letter(self):
        ev = char_key_event("a")
        assert (ev.key, ev.char, ev.modifiers) == ("a", "a", frozenset())

    def test_shift_letter_lowercases_and_keeps_shift(self):
        ev = char_key_event("A", frozenset({"shift"}))
        assert (ev.key, ev.char) == ("a", "A")
        assert ev.modifiers == frozenset({"shift"})

    def test_digit(self):
        ev = char_key_event("1")
        assert (ev.key, ev.char, ev.modifiers) == ("1", "1", frozenset())

    def test_shifted_symbol_drops_shift(self):
        # Shift+1 -> '!': identity is the glyph; shift must be dropped so every
        # backend (incl. Windows, which used to report ('!', {shift})) agrees.
        ev = char_key_event("!", frozenset({"shift"}))
        assert (ev.key, ev.char) == ("!", "!")
        assert ev.modifiers == frozenset()

    def test_shifted_symbol_keeps_cmd_drops_shift(self):
        ev = char_key_event("!", frozenset({"shift", "cmd"}))
        assert ev.key == "!"
        assert ev.modifiers == frozenset({"cmd"})

    def test_punctuation_keeps_ctrl(self):
        ev = char_key_event("1", frozenset({"ctrl"}))
        assert ev.modifiers == frozenset({"ctrl"})

    def test_space_is_named_keeps_char(self):
        ev = char_key_event(" ")
        assert (ev.key, ev.char) == ("space", " ")

    def test_shift_space_distinct(self):
        ev = char_key_event(" ", frozenset({"shift"}))
        assert ev.key == "space"
        assert ev.modifiers == frozenset({"shift"})


# --------------------------------------------------------------------------- #
# Reference matcher — the logic XeFM's binding parser will use.
# Driven by already-normalized (contract-conformant) events, so it passes today
# and demonstrates the contract is sufficient for XeFM's hard cases.
# --------------------------------------------------------------------------- #

def _matches(binding, ev):
    """Reference implementation of the §2 matcher rules.

    ``binding`` is ``(identity, required_mods)``. ``identity`` is a letter /
    named key (matched on ``ev.key`` + exact mods) or a single punctuation glyph
    (matched on ``ev.char``, ignoring shift/alt)."""
    identity, required = binding
    is_punct = len(identity) == 1 and not identity.isalnum() and identity != " "
    if is_punct:
        # ignore shift/alt; honour ctrl/cmd if the binding asked for them
        sig = {m for m in ev.modifiers if m in ("ctrl", "cmd")}
        want = {m for m in required if m in ("ctrl", "cmd")}
        return ev.char == identity and sig == want
    return ev.key == identity and frozenset(ev.modifiers) == frozenset(required)


def _key(key, char=None, mods=()):
    from puikit.event import Event
    return Event(type=EventType.KEY, key=key, char=char, modifiers=frozenset(mods))


class TestReferenceMatcher:
    def test_lower_a_vs_shift_a_are_distinct(self):
        lower = _key("a", "a")
        upper = _key("a", "A", {"shift"})
        assert _matches(("a", frozenset()), lower)
        assert not _matches(("a", frozenset()), upper)        # 'a' != Shift-A
        assert _matches(("a", frozenset({"shift"})), upper)   # 'Shift-A'

    def test_punctuation_ignores_shift(self):
        ev = _key("?", "?", {"shift"})  # '?' is Shift+/ on a US layout
        assert _matches(("?", frozenset()), ev)

    def test_shift_space_distinct_from_space(self):
        space = _key("space")
        shift_space = _key("space", mods={"shift"})
        assert _matches(("space", frozenset()), space)
        assert _matches(("space", frozenset({"shift"})), shift_space)
        assert not _matches(("space", frozenset()), shift_space)

    def test_gui_only_chord(self):
        cmd_enter = _key("enter", mods={"cmd"})
        assert _matches(("enter", frozenset({"cmd"})), cmd_enter)
        assert not _matches(("enter", frozenset()), cmd_enter)
