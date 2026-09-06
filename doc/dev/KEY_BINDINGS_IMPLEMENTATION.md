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

## The isearch context

`xefm.actions.ISEARCH` names one more key-consuming surface: the incremental-
search bar (`xefm/isearch_bar.py`), which is the focus root while it is open and
so receives every key. Its keys — `isearch.next_match`, `isearch.prev_match`,
`isearch.toggle_select_down`, `isearch.toggle_select_up`,
`isearch.select_matches`, `isearch.accept`, `isearch.cancel` — are ordinary
named actions, resolved and rebound exactly like a viewer's.

Routing is not a viewer's, though, because this is the one surface whose keys
compete with **typing**. `ISearchBar.handle_event` runs three steps in order:

1. **Text first.** `typed_char(event) is not None` (minus Ctrl/Cmd chords, taken
   out first — the order `TextEdit` itself uses so `Cmd+A` is not read as typing
   "a") goes straight to the pattern field, and the keymap never sees it. This
   is what keeps `Q`, `?` and SPACE typeable into a pattern while `quit`, `help`
   and `toggle_select_down` own them in the file list a row above.
2. **Only what the bar owns.** Every context inherits the `common` actions, so
   `quit` does resolve here — but the bar tests its own action names alone
   (`ISearchBar._handlers`, built from the callbacks its owner supplied) rather
   than taking whatever `find_action_for_event` returns. A viewer's search bar
   passes no `on_select`, which is how Shift+Up/Down stay the field's there.
3. **Everything else is the field's.** Left/Right/Home/End, Backspace, Delete
   and the clipboard chords fall through untouched.

The consequence for a config: an isearch action bound to a **printable** key can
never fire, because step 1 consumes it — and the character would quietly stop
being typeable if it could. `config.printable_isearch_bindings` finds those and
the app logs one line about them at startup, the same nudge `deprecated_names_notice`
gives a config using an old action name. Defaults therefore avoid printable keys,
and also avoid the two keys a terminal cannot deliver: modified Enter (no kitty
keyboard protocol on the VT input path) and Insert (absent on macOS). Shift+arrow
satisfies both constraints on every backend, and so does the `Ctrl-A` of
`isearch.select_matches` — the one default that shadows something the field
wanted (its select-all-text), taken deliberately and only in the Ctrl form, so
`Cmd-A` still selects the text on macOS.

## The filter_list context

`xefm.actions.FILTER_LIST` names the second typing-competing surface: the modal
searchable-list picker (`xefm/filter_list_dialog.py`) behind Favorites, Drives,
History, External Programs and the `;` Filter prompt. It has one action —
`remove_list_item`, Shift-Delete by default — which drops the highlighted row.

The routing constraint is the isearch bar's: the query field holds focus and a
printable key belongs to the query, so a remove key must be modified or
non-printable. `FilterListDialog.handle_event` claims the key by **action**
(`is_action_for_event(..., context=FILTER_LIST)`) rather than by key literal,
ahead of the field — which is what keeps a rebind working, and what keeps a
plain Delete editing the query while Shift-Delete removes a row.

Two things about the name are deliberate:

- **No context prefix.** Unlike `isearch.next_match`, this is `remove_list_item`
  flat. Dropping the highlighted row is an operation other list surfaces may
  grow later, and `ActionRegistry` keeps a separate table per context, so the
  same name can be registered again elsewhere with its own default key. An
  unqualified `KEY_BINDINGS` entry then rebinds every one of them at once;
  `filter_list.remove_list_item` moves just this one.
- **Not `delete_*`.** In the file list that word means erasing files from disk
  (`delete_files`). Nothing here touches the filesystem — only the remembered
  list — and a name in `KEY_BINDINGS` must not leave a reader guessing which of
  the two they are binding.

The action is only *offered* where the rows accumulate: `show_filter_list` takes
an `on_remove(value) -> bool` hook, and a picker that passes none has no remove
key at all. The hook doing the forgetting is also what decides removability —
returning False keeps the row, which is how the Filter picker's "clear filter"
sentinel survives the key with no special case inside the dialog.

## Key labels in the UI

Every key a surface names on screen is read back from the same keymap that
matched it — a hint is never a literal. A rebind that changes what a key does
has to change what the UI calls it, or the two drift apart, which is exactly
what issue #382 reported: `text_viewer.scroll_up`/`scroll_down` rebound to
`K`/`J` showed `K / J` in the help dialog and `↑↓ scroll` in the footer.

Two label shapes, for two audiences:

- **Help dialogs list every binding**, `" / "`-joined — `_label()` / `_pair()`
  in each viewer, `_keys_label()` / `_keys_pair()` in the directory-diff viewer
  (which resolves against an injected `KeyBindings` when it has one).
- **Footers name one key per action** — `footer_key()` and `footer_pair()` in
  `xefm/text_viewer.py`, shared by all four viewers. The bar elides from the
  right, so a second binding would spend width restating what the help dialog
  already covers; `image_viewer.zoom_in` alone is bound to both `+` and `=`.
  `footer_pair` collapses two plain arrows into a cluster (`↑↓`, `←→`) and
  slash-joins anything else (`n/Shift-N`), which keeps a default keymap's bar
  looking as it always has.

An action left unbound yields an empty label, and the caller drops the whole
segment rather than printing a word no key triggers — the same rule the main
window's `StatusBar._isearch_hints()` follows.

The one deliberate literal is the text viewer's **rich mode** footer
(`_draw_rich`): keys there are forwarded straight to the embedded renderer,
which scrolls on its own arrows, so `text_viewer.scroll_*` is inert and naming
it would advertise a key that does nothing. It says `↑↓ scroll` because `↑↓` is
what scrolls.

A row about *another* surface's keys passes that surface's context: the
viewers' "prev / next match (in search)" row resolves `isearch.prev_match` /
`isearch.next_match` in `ISEARCH`, not in the viewer's own context, where those
actions do not exist.

### Where a hint is drawn, and who is allowed to speak

`dialog_geometry.draw_hint_row` is the one place a modal names its keys, and it
is built as the **mirror of `draw_title_bar`**: a frame-connecting rule, then
the muted line of keys in the band beneath it, hard against the bottom border.
A modal is framed by two matched chrome bands — what it is at the top, what it
answers to at the bottom — with the content between them, rather than a hint
floating in the client area with nothing separating it from the content above.

The mirroring is literal on both backends:

| | title bar | hint bar |
|---|---|---|
| grid | border, title, rule | rule, hint, border |
| vector | `gui_title_bar_height` = line box + `2 × _GUI_TITLE_PAD`, rule at its bottom edge | `gui_hint_bar_height`, same formula, rule at its **top** edge |
| content | starts `_GUI_CONTENT_GAP` below the rule | stops `_GUI_CONTENT_GAP` above the rule |

`hint_content_bottom(ctx, surface_bg)` is what a modal's content measures
against — the counterpart to what `draw_title_bar` returns. It takes the surface
colour because the band's *height* is measured from the hint's own text style
(`hint_style`), exactly as the title bar's is measured from the title's, so the
two bands stay the same height as the font changes.

A dialog that sizes its box **up front** — Sort, Choice, Compare & Select, the
input prompt — never reaches a draw context to measure against, so it adds
`HINT_ROWS` (the grid's rule + keys + border) to its content height instead. A
vector band is shorter than that, so the grid figure is the safe reserve for
both; the band is pinned to the frame either way, and any slack falls between
the content and the rule rather than under the keys.

`draw_hint_row` also takes an optional `right`, a second reading pinned to the
band's right end and kept whole while the keys elide against it. Tip of the
Day's `3/14` position counter is the only user: the one thing a modal says down
here that is not a key.

Every modal that owns its keyboard draws the band:

| modal | what it names |
|---|---|
| filter-list picker | select / choose / remove (from the keymap) / cancel |
| search (progressive) | select / open / `Tab` **to the other mode** / cancel |
| input prompt | accept / `Tab` complete (only with a completer) / cancel |
| batch rename | switch field / scroll preview / rename / cancel |
| sort, choice, compare & select | that dialog's own axes |
| tips | prev / next / toggle / close, plus the counter |
| scroll modals (help, file details) | scroll / close |

Two things a modal says *near* the bottom are deliberately not in the band,
because they are not keys: the search dialog's status line (spinner, result
count) and batch rename's `\0 / \1-\9 / \d` macro legend, which stays with the
field it is a legend for. Both used to carry a `Tab …` fragment; that fragment
moved into the band, where the keys live.

Two modals draw no band. The overwrite-conflict dialog answers with a **button
row** along its bottom — that row already is the band, and its labels name the
choices. The task-progress dialog is not a picker: it takes one key (Esc, to ask
about cancelling) and measures its byte bar up from the foot of the box.

`TextDialog` (help, file details) used to carry its hint in the header instead,
between the title and the body the title describes; it does not any more.

Only one surface names keys at a time. `StatusBar._text()` returns the empty
string while `panel.has_layers` — a modal owns the keyboard and lists its own
keys, so the file list's would be advertising keys that cannot fire. The search
bar is the exception: it is a layer too, but it hands the bar its keys to show,
which is what a footer overlay is for.

## Error handling

Parsing is defensive — an unknown modifier or key token logs a warning and is
skipped rather than crashing; a missing `KEY_BINDINGS` config falls back to
`DefaultConfig.KEY_BINDINGS`.

## Testing

- `test/test_keybindings_puikit_contract.py` — XeFM's matcher (`_parse_key_expression`
  / `_matches`) against the real keymap.
- `test/test_puikit_keyboard_contract.py` — the per-backend translation XeFM relies
  on (the contract's guarantees hold on each backend).
- `test/test_isearch_keys.py` — the isearch context: its defaults, the
  printable-binding notice, the bar's three-step routing, and Shift+Up/Down
  marking through a live file list.
- `test/test_viewer_footer_keys.py` — the label helpers, and each viewer's
  footer text under a rebind (issue #382).
- `test/test_filter_list_remove.py` — the `filter_list` context: the default
  binding, Shift-Delete vs a plain Delete in the query field, the dialog's local
  row edit, and what each owner forgets (issue #271).
- `test/test_dialog_hint_row.py` — the two bands mirroring each other on both
  backends, every modal drawing its keys in the band below its content, and the
  status bar going quiet under a modal.

## See Also

- [Key Bindings Feature](../KEY_BINDINGS_FEATURE.md) — user documentation
- [Configuration System](CONFIGURATION_SYSTEM.md) — configuration architecture
- PuiKit keyboard contract — `puikit/docs/keyboard_contract.md` (event shape,
  per-backend normalization, IME focus-gating)
