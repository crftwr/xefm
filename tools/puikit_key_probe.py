#!/usr/bin/env python3
"""Interactive keyboard probe for the PuiKit keyboard contract.

The interactive half of the harness in ``doc/dev/PUIKIT_KEYBOARD_CONTRACT.md``.
It opens a PuiKit backend and, for every real keypress, shows three things:

  raw        - the Event exactly as the backend produced it
  normalized - that Event after applying the proposed contract (Rule 2: an
               uppercase letter becomes key=<lower> + {"shift"}), which is what
               XeFM's matcher will see once the PuiKit-side changes (§3) land or
               are emulated here
  action     - the XeFM action a small sample keymap binds to it, via the
               reference matcher

Use it to confirm what a *real terminal* delivers for Shift / Ctrl / Alt / Cmd
and punctuation (modifier reporting varies by emulator), and later to re-check
the macOS GUI backend.

    python tools/puikit_key_probe.py                 # curses (TUI)
    python tools/puikit_key_probe.py --backend gui   # macOS GUI

Quit with Ctrl+Q.
"""

import argparse

from puikit import EventType, Style
from puikit.backends import create_backend


# A representative slice of XeFM's keymap (doc/dev/PUIKIT_KEYBOARD_CONTRACT.md §3),
# exercising letters, Shift-letters, named keys, punctuation, and GUI-only chords.
SAMPLE_KEYMAP = {
    "q": "quit",
    "Shift-A": "select_all_items",
    "a": "select_all_files",
    "enter": "open_item",
    "Command-enter": "open_with_os",   # GUI-only (terminals can't send Cmd)
    "Alt-enter": "reveal_in_os",       # GUI-only
    "tab": "switch_pane",
    "Shift-tab": "switch_pane_back",
    "space": "select_file",
    "Shift-space": "select_file_up",
    "?": "help",
    ".": "toggle_hidden",
    "=": "diff_files",
    "[": "adjust_pane_left",
    "]": "adjust_pane_right",
    "f5": "redraw",
}

_MOD_TOKENS = {"shift": "shift", "control": "ctrl", "ctrl": "ctrl",
               "alt": "alt", "option": "alt", "command": "cmd", "cmd": "cmd"}

# Multi-char token -> PuiKit identity (lowercased names; punctuation stays literal).
_NAME_TOKENS = {
    "enter": "enter", "escape": "escape", "tab": "tab", "space": "space",
    "backspace": "backspace", "delete": "delete", "insert": "insert",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end", "pageup": "pageup", "pagedown": "pagedown",
    **{f"f{n}": f"f{n}" for n in range(1, 13)},
}


def parse_token(token):
    """``"Shift-A"`` -> ``("a", frozenset({"shift"}))``; ``"?"`` -> ``("?", set())``."""
    parts = token.split("-")
    mods, key_part = set(), parts[-1]
    for p in parts[:-1]:
        mods.add(_MOD_TOKENS[p.lower()])
    low = key_part.lower()
    if low in _NAME_TOKENS:
        identity = _NAME_TOKENS[low]
    elif len(key_part) == 1 and key_part.isalpha():
        identity = key_part.lower()
    else:
        identity = key_part  # punctuation literal
    return identity, frozenset(mods)


def normalize(event):
    """Apply contract Rule 2 to whatever the backend produced, so the probe
    shows the intended identity even before PuiKit's backends are patched."""
    key, char, mods = event.key, event.char, set(event.modifiers)
    if key and len(key) == 1 and key.isalpha() and key.isupper():
        mods.add("shift")
        key = key.lower()
    return key, char, frozenset(mods)


def matches(binding, key, char, mods):
    identity, required = binding
    is_punct = len(identity) == 1 and not identity.isalnum() and identity != " "
    if is_punct:
        sig = {m for m in mods if m in ("ctrl", "cmd")}
        want = {m for m in required if m in ("ctrl", "cmd")}
        return char == identity and sig == want
    return key == identity and frozenset(mods) == required


_COMPILED = [(parse_token(t), a) for t, a in SAMPLE_KEYMAP.items()]


def lookup_action(key, char, mods):
    for binding, action in _COMPILED:
        if matches(binding, key, char, mods):
            return action
    return "-"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="tui",
                        help="backend name (tui, gui, memory)")
    args = parser.parse_args()

    backend = create_backend(args.backend)
    history = []  # most-recent-last list of formatted lines

    with backend:
        def render():
            backend.clear()
            w, h = backend.size
            header = "PuiKit key probe - press keys; Ctrl+Q to quit"
            backend.draw_text(1, 0, header[: w - 2], Style())
            cols = " raw key/char/mods        ->  normalized key/mods        action"
            backend.draw_text(1, 2, cols[: w - 2], Style())
            rows = max(1, h - 4)
            for i, line in enumerate(history[-rows:]):
                backend.draw_text(1, 3 + i, line[: w - 2], Style())
            backend.present()

        def on_event(event):
            if event.type is EventType.KEY and event.key == "q" \
                    and "ctrl" in event.modifiers:
                backend.quit()
                return
            if event.type is EventType.KEY:
                raw = f"{event.key!r}/{event.char!r}/{sorted(event.modifiers)}"
                nkey, nchar, nmods = normalize(event)
                norm = f"{nkey!r}/{sorted(nmods)}"
                action = lookup_action(nkey, nchar, nmods)
                history.append(f"{raw:26}->  {norm:26} {action}")
            elif event.type is EventType.RESIZE:
                pass
            else:
                history.append(f"[{event.type.value}] "
                               f"x={event.x} y={event.y} mods={sorted(event.modifiers)}")
            render()

        render()
        backend.run_event_loop(on_event)


if __name__ == "__main__":
    main()
