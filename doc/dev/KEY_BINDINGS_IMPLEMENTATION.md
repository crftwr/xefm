# Key Bindings System Implementation

## Overview

XeFM maps **config key tokens** (`"q"`, `"Shift-Down"`, `"Command-ENTER"`) to
**actions**, matching them against PuiKit key events. It supports named keys,
modifier chords, punctuation and shifted-symbol identities, and per-action
selection requirements.

The **normative cross-backend keyboard contract** — the `Event(KEY, key, char,
modifiers)` shape and how each backend (curses / macOS / Windows) normalizes a
keypress into it — lives in PuiKit: `puikit/docs/keyboard_contract.md`. This
document covers **XeFM's side**: how a config token is parsed and matched against
that contract.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     XeFM Application (xefm/app.py)                 │
└────────────────────────┬────────────────────────────────────┘
                         │ Uses
                         ↓
┌─────────────────────────────────────────────────────────────┐
│              Public API (xefm/config.py)                      │
│  - find_action_for_event(event, has_selection)              │
│  - get_keys_for_action(action)                              │
│  - format_key_for_display(key_expr)                         │
└────────────────────────┬────────────────────────────────────┘
                         │ Delegates to
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                  KeyBindings class                           │
│  - Parses tokens to (identity, modifiers, mode)             │
│  - Reduces an event to (key, char, modifiers)               │
│  - Matches the two against each other                        │
└────────────────────────┬────────────────────────────────────┘
                         │ Consumes
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                PuiKit key event (puikit.event)               │
│  - key:       canonical identity string ("a", "enter")      │
│  - char:      produced glyph, or None                        │
│  - modifiers: set ⊆ {"shift","ctrl","alt","cmd"}            │
└─────────────────────────────────────────────────────────────┘
```

## The keyboard contract (XeFM's view)

A key event reduces to a triple: `key` (canonical identity), `char` (produced
glyph or `None`), and `modifiers` (a set of `shift` / `ctrl` / `alt` / `cmd`). A
parsed config token carries `(identity, modifiers, mode)` and matches in one of
two **modes**:

- **`key` mode** — letters and named keys. Match iff `event.key == identity`
  **and** `event.modifiers == modifiers` (exact set equality, so `Shift-A` differs
  from `a`).
- **`char` mode** — digits and punctuation. Match iff `event.char == identity`
  (case-sensitive), **ignoring** `shift`/`alt` (the produced glyph already encodes
  them); `ctrl`/`cmd` are still significant iff the binding named them.

> **Shifted symbols are their own identity.** A shifted digit/punctuation binds to
> the glyph it produces — `Shift-EQUAL` → `"+"`, `Shift-1` → `"!"` — matched in
> `char` mode with `shift` dropped, so it reports the same on every backend.
>
> **Bare uppercase letters do not imply shift.** A bare `"J"` parses to key `j`
> with no modifier (identical to `"j"`); only `"Shift-J"` keeps the modifier.
> Alphabetical bindings are case-insensitive **by design** (the parser lowercases
> the letter).

## Config token → identity map

| Config token(s) | Resolves to | Match mode |
|---|---|---|
| `a`…`z` / `A`…`Z` | lowercase letter | `key` + exact mods (`Shift-` adds `shift`) |
| `ENTER`/`RETURN`, `ESCAPE`/`ESC`, `TAB`, `BACKSPACE`, `DELETE`/`DEL`, `INSERT`, `SPACE` | named identity (`enter`, `escape`, `space`, …) | `key` + exact mods |
| `UP` / `DOWN` / `LEFT` / `RIGHT` / `HOME` / `END` | same, lowercased | `key` + exact mods |
| `PAGE_UP`/`PAGEUP`, `PAGE_DOWN`/`PAGEDOWN` | `pageup` / `pagedown` | `key` + exact mods |
| `F1`…`F12` | `f1`…`f12` | `key` + exact mods |
| `ALT` (alone, not as a prefix) | `alt` — a *bare Alt tap*, delivered only by the Windows terminal (PuiKit keyboard contract §1); bound to `menu` alongside `F10` | `key` + exact mods |
| named punctuation (`MINUS`, `EQUAL`, `LEFT_BRACKET`, `SEMICOLON`, `SLASH`, …) | base glyph (`-`, `=`, `[`, `;`, `/`, …) | `char` (ignore shift/alt) |
| digit / punctuation literal (`?`, `.`, `:`, `1`, …) | the produced glyph | `char` |
| `Shift-<named punct / digit>` | the **shifted** glyph (`Shift-EQUAL` → `+`, `Shift-1` → `!`) | `char` |
| `Shift-X` (letter) | `x` + `shift` | `key` + exact mods |
| `Command-X` / `Alt-X` | `x` + `cmd` / `alt` | `key` + exact mods (curses can't deliver `cmd`; such chords are GUI-only) |

The maps that back this table live at the top of `xefm/config.py`:
`_MODIFIER_ALIASES`, `_NAMED_KEYS`, `_PUNCT_NAMES`, `_SHIFT_SYMBOL`, `_KEY_ALIASES`.

## KeyBindings class

### Location
`xefm/config.py`

### Key methods

#### `_parse_key_expression(key_expr) -> (identity, modifiers, mode)`
Parses a config token to its parsed triple.

- `identity` — PuiKit key name (`"a"`, `"enter"`, `"pageup"`) for `mode == "key"`,
  or the produced glyph (`"?"`, `"="`, `"+"`) for `mode == "char"`.
- `modifiers` — `frozenset` of contract modifier names.
- `mode` — `"key"` or `"char"`.

**Algorithm:**
1. Single-character token: a **letter** → `(lower, frozenset(), "key")`; anything
   else (digit / punctuation) → `(char, frozenset(), "char")`.
2. Otherwise split on `-`: the last part is the key, earlier parts are modifiers
   (resolved case-insensitively via `_MODIFIER_ALIASES`; unknown ones warn and are
   skipped). Then, on the key part:
   - a **named key** (`_NAMED_KEYS`) → `(identity, mods, "key")`;
   - **named punctuation** (`_PUNCT_NAMES`) → `_punct_binding` (`char` mode);
   - a single **letter** → `(lower, mods, "key")`;
   - a single **digit / punctuation literal** → `_punct_binding`.

#### `_punct_binding(glyph, mods) -> (glyph, modifiers, "char")`
Builds a `char`-mode binding, folding a `Shift` modifier into the produced
(shifted) glyph via `_SHIFT_SYMBOL` and dropping `shift`, so the identity is the
character the key actually emits.

#### `_event_identity(event) -> (key, char, modifiers)`
Reduces a PuiKit `Event` (`event.key` / `event.char` / `event.modifiers`) to
the contract triple. Aliases `page_up` / `page_down` → `pageup` / `pagedown`.

#### `_matches(parsed, key, char, mods) -> bool`
Applies the two match modes described in *The keyboard contract* above.

#### `find_action_for_event(event, has_selection=False) -> str | None`
Reduces the event, scans the reverse-lookup table for a matching parsed binding,
and returns the first action whose selection requirement is satisfied.

#### `get_keys_for_action(action) -> (key_expressions, selection_requirement)`
Returns the raw config tokens and selection requirement for an action (used by the
help dialog).

#### `format_key_for_display(key_expr) -> str`
Formats a token for UI display: single literals pass through; named tokens map to
conventional labels via `_KEY_DISPLAY` (`ENTER` → `Enter`, `UP` → `↑`,
`PAGE_UP` → `PgUp`); modifiers abbreviate via `_MOD_DISPLAY` (`Command` → `Cmd`,
`Option` → `Opt`). E.g. `"Command-Shift-X"` → `"Cmd-Shift-X"`.

## Public API functions

Module-level wrappers in `xefm/config.py` delegate to the `ConfigManager`'s cached
`KeyBindings` instance:

```python
from xefm.config import find_action_for_event, get_keys_for_action, format_key_for_display

action = find_action_for_event(event, has_selection)   # -> 'quit' | None
keys, sel_req = get_keys_for_action('delete_files')     # -> (['DELETE', 'Command-Backspace'], 'required')
label = format_key_for_display('Command-Shift-X')       # -> 'Cmd-Shift-X'
```

## Configuration formats

**Simple** (keys only, selection defaults to `'any'`):
```python
'action_name': ['key1', 'key2']
```

**Extended** (with selection requirement):
```python
'action_name': {'keys': ['key1', 'key2'], 'selection': 'required'}  # or 'none' | 'any'
```

## Selection requirements

- `'required'` — action available only when files are selected.
- `'none'` — action available only when **no** files are selected.
- `'any'` — always available (default).

Enforced in `find_action_for_event` via `_check_selection_requirement`, so a token
can map to different actions depending on selection state.

## Data structures

`KeyBindings` builds a reverse lookup once at init (`_build_key_lookup`), keyed by
the **parsed triple**:

```python
_key_to_actions = {
    ("q",      frozenset(), "key"):  [("quit", "any")],
    ("pageup", frozenset(), "key"):  [("page_up", "any")],       # from token "PAGE_UP"
    ("delete", frozenset(), "key"):  [("delete_files", "required")],
    ("?",      frozenset(), "char"): [("help", "any")],
    ("=",      frozenset(), "char"): [("diff_files", "any")],    # from token "EQUAL"
    ("+",      frozenset(), "char"): [("diff_directories", "any")],  # from token "Shift-EQUAL"
}
```

Lookup is a linear scan over this table applying `_matches` (the table is small);
the `ConfigManager` caches the `KeyBindings` instance and rebuilds it only on
`reload_config()`.

## Error handling

Parsing is defensive — an unknown modifier or key token logs a warning and is
skipped rather than crashing; a missing `KEY_BINDINGS` config falls back to
`DefaultConfig.KEY_BINDINGS`.

## Testing

- `test/test_keybindings_puikit_contract.py` — XeFM's matcher (`_parse_key_expression`
  / `_matches`) against the real keymap.
- `test/test_puikit_keyboard_contract.py` — the per-backend translation XeFM relies
  on (the contract's guarantees hold on each backend).

## See Also

- [Key Bindings Feature](../KEY_BINDINGS_FEATURE.md) — user documentation
- [Configuration System](CONFIGURATION_SYSTEM.md) — configuration architecture
- PuiKit keyboard contract — `puikit/docs/keyboard_contract.md` (event shape,
  per-backend normalization, IME focus-gating)
