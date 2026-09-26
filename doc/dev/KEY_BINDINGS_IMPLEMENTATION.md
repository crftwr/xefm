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

### What a backend can actually deliver

A binding is worth no more than the transport under it, and the backends do not
carry the same set:

| Chord | Desktop (macOS / Windows) | Windows console (VT / curses) | POSIX terminal |
|---|---|---|---|
| `Command-…` | yes (macOS) | — | — |
| `Ctrl-<letter>` | yes | yes | yes, except I, M, J, H and `[` — those bytes already *are* tab, enter, backspace and escape |
| `Ctrl-Shift-<letter>` | yes | yes | **no** — one control byte, no room for shift |
| `Ctrl-ENTER` | yes | yes | **no** — arrives as plain `enter` |
| `Alt-<key>` | yes | yes | as ESC + key; macOS keyboards spend Option on glyphs and IME |
| modifiers on a named key (arrows, F-keys, Home/End, Tab…) | yes | yes | yes, via the xterm CSI modifier parameter |

The Windows console reports a real virtual key plus `dwControlKeyState`
(`ReadConsoleInputW`), which is why `Ctrl-Shift-<letter>` and `Ctrl-ENTER` survive
there and nowhere else in a terminal. On a VT stream a Ctrl+letter is the bare
control byte 0x01–0x1A: PuiKit's VT input path turns it back into
`key=<letter>, modifiers={ctrl}` and there is no shift to recover. PuiKit
implements kitty's *graphics* protocol, not its keyboard protocol, so no CSI-u
path changes this.

### The three cases, and where they live

`KEY_BINDINGS` in `xefm/_config.py` is therefore written as **one common table**
— only chords every backend delivers — followed by a small override block keyed
on `is_desktop_mode()` and `sys.platform`:

| Case | Override |
|---|---|
| macOS desktop | `open_with_os` gains `Command-ENTER`; `copy_log_selection` gains `Command-C` |
| Windows desktop | `open_with_os` gains `Ctrl-ENTER` |
| Any terminal | none |

Both overrides *prepend* the platform chord and keep the common one, because
`_menu_shortcut` shows `keys[0]` while the help dialog lists them all: the menu
then reads `Cmd-Enter` in the macOS app and `Ctrl-O` in a terminal, each true
where it is drawn. `is_desktop_mode()` is evaluated at config-load time (it reads
`XEFM_BACKEND` / `--backend`, so it is decided before the config is read) and
again on `reload_config`.

What the *host* takes before XeFM sees it — a terminal's own shortcuts, VS Code's
`commandsToSkipShell`, a multiplexer's prefix — is a second filter on top of this
one, and the reason the common letters are what they are. The user-facing list is
under "Keys the host takes first" in
[KEY_BINDINGS_FEATURE.md](../KEY_BINDINGS_FEATURE.md); `TestThreeCases` in
`test/test_keybindings_puikit_contract.py` holds the rule that terminal mode
binds nothing a terminal cannot send.

## Config token → identity map

| Config token(s) | Resolves to | Match mode |
|---|---|---|
| `a`…`z` / `A`…`Z` | lowercase letter | `key` + exact mods (`Shift-` adds `shift`) |
| `ENTER`/`RETURN`, `ESCAPE`/`ESC`, `TAB`, `BACKSPACE`, `DELETE`/`DEL`, `INSERT`, `SPACE` | named identity (`enter`, `escape`, `space`, …) | `key` + exact mods |
| `UP` / `DOWN` / `LEFT` / `RIGHT` / `HOME` / `END` | same, lowercased | `key` + exact mods |
| `PAGE_UP`/`PAGEUP`, `PAGE_DOWN`/`PAGEDOWN` | `pageup` / `pagedown` | `key` + exact mods |
| `F1`…`F12` | `f1`…`f12` | `key` + exact mods |
| `ALT` (alone, not as a prefix) | `alt` — a *bare Alt tap*, delivered only by the Windows terminal (PuiKit keyboard contract §1); bound to `menu` alongside `F10` | `key` + exact mods |
| named punctuation — `MINUS`, `EQUAL`/`EQUALS`, `LEFT_BRACKET`, `RIGHT_BRACKET`, `BACKSLASH`, `SEMICOLON`, `QUOTE`/`APOSTROPHE`, `COMMA`, `PERIOD`/`DOT`, `SLASH`, `GRAVE`/`BACKTICK`/`BACKQUOTE` (the whole set) | base glyph (`-`, `=`, `[`, `]`, `\`, `;`, `'`, `,`, `.`, `/`, `` ` ``) | `char` (ignore shift/alt) |
| digit / punctuation literal (`?`, `.`, `:`, `1`, …) | the produced glyph | `char` |
| `Shift-<named punct / digit>` | the **shifted** glyph (`Shift-EQUAL` → `+`, `Shift-1` → `!`) | `char` |
| `Shift-X` (letter) | `x` + `shift` | `key` + exact mods |
| `Command-X` / `Alt-X` | `x` + `cmd` / `alt` | `key` + exact mods (curses can't deliver `cmd`; such chords are GUI-only) |

The maps that back this table live at the top of `xefm/config.py`:
`_MODIFIER_ALIASES`, `_NAMED_KEYS`, `_PUNCT_NAMES`, `_SHIFT_SYMBOL`, `_KEY_ALIASES`.
The table is exhaustive on purpose — a token outside it falls through
`_parse_key_expression`'s tail, which logs `Unknown key in expression: …` and
returns an identity nothing can ever match. Curses-era names (`PPAGE`, `NPAGE`)
and `KEY_`-prefixed ones (`KEY_A`, `KEY_MINUS`) are exactly that: they were
documented once and never parsed. The user-facing list is
`doc/KEY_BINDINGS_FEATURE.md`, "Key Names" / "Punctuation by Name"; when this
table changes, that one has to change with it.

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
`isearch.toggle_select_down`, `isearch.toggle_select_up`, `isearch.select_range`,
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
   passes no `on_select` / `on_select_range`, which is how the marking chords stay
   the field's there.
3. **Everything else is the field's.** Left/Right/Home/End, Backspace, Delete
   and the clipboard chords fall through untouched.

The consequence for a config: an isearch action bound to a **printable** key can
never fire, because step 1 consumes it — and the character would quietly stop
being typeable if it could. `config.printable_isearch_bindings` finds those and
the app logs one line about them at startup, the same nudge `deprecated_names_notice`
gives a config using an old action name. Defaults therefore avoid printable keys,
and also avoid the two keys a terminal cannot deliver: modified Enter (no kitty
keyboard protocol on the VT input path) and Insert (absent on macOS).

`Ctrl-SPACE` satisfies every one of those and says what it does — Space is
"select" in the file list, Ctrl is what makes a command of a key that would
otherwise type — so it carries `isearch.toggle_select_down`, and
`Ctrl-Shift-SPACE` carries `isearch.select_range` because Shift is the range
gesture in the file list too (`select_range`, Shift-Space) and everywhere else:

| | mark one | mark a range |
|---|---|---|
| file list | `SPACE` | `Shift-SPACE` |
| search bar | `Ctrl-SPACE` | `Ctrl-Shift-SPACE` |

Two mechanics make that table possible, and both are worth knowing before moving
any of it:

- **Shift does not make a printable a command.** Step 1 exempts Ctrl and Cmd
  only, so `Shift-SPACE` types a space here however it arrives — and on a POSIX
  terminal it *is* a plain space, since a terminal reports the character and has
  no room for a modifier on it. The file list's key therefore cannot serve this
  surface, which is why `isearch.select_range` is a separate dotted action rather
  than the unqualified `select_range` registered in both contexts: the shipped
  `KEY_BINDINGS` names `select_range`, and an unqualified entry reaches every
  context that understands the name (`KeyBindings._context_entries`, source 2),
  which would hand this surface Shift-Space and have
  `printable_text_bindings` report XeFM's own default as a mistake.
- **`Ctrl-SPACE` reaches every backend.** Both GUI backends and the Windows
  console report it natively; a POSIX terminal sends the NUL byte, which PuiKit
  decodes as space+ctrl (1.7.2 — the byte one below the `0x01..0x1A` run it
  already turned into Ctrl+letter). `Ctrl-Shift-SPACE` reaches the desktop app
  alone: a terminal cannot encode it and the Windows terminal claims that chord
  for scrollback.

`isearch.toggle_select_up` and the file list's `toggle_select_up` are registered
with **no default key**: a search walks forwards, `Shift-SPACE` was worth more as
a range, and both were the keys least missed. They stay in the registry so a
config can bind either, and out of the help dialog, whose unbound rows are
required to name a menu route (`test/test_help_backend.py`).

`Ctrl-A` (`isearch.select_matches`) is the one default that shadows something the
field wanted (its select-all-text), taken deliberately and only in the Ctrl form,
so `Cmd-A` still selects the text on macOS.

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

### Labels built once, and the reload that has to redo them

Two surfaces cannot afford a lookup per draw and hold a resolved string instead:

- `StatusBar._hints()` and `_isearch_hints()` (`xefm/app.py`) cache their line.
  The bar redraws every frame, and a dozen keymap lookups a frame buy nothing.
- The menu resolves every `shortcut=` once, when `_build_menu()` runs — and on
  a `native_menus` backend `MenuBar` then hands that menu to the OS, which owns
  it from there.

Both were written when the keymap really was fixed for the process lifetime.
`reload_config` is what made that untrue: it rebuilds `self.keys`, and the help
dialog — which looks up every time — went on to say `D` while the bar and the
menu still said `K`. That is the second half of issue #382, reported against
`delete_files`. The reload therefore also calls `StatusBar.invalidate()` and
`MenuBar.set_menu(self._build_menu())`; the latter is a PuiKit method for
exactly this case, redrawing the in-window bar from the new menu and
re-registering an OS bar, since installing is the only way to replace one.

The rule for anything added later: **a key label resolved outside a draw is
`reload_config`'s to refresh.**

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
| search (progressive) | select / **what the owner does with Enter** / `Tab` **to the other mode** / cancel |
| input prompt | accept / `Tab` complete (only with a completer) / cancel |
| batch rename | switch field / scroll preview / rename / cancel |
| sort, choice, compare & select | that dialog's own axes |
| tips | prev / next / toggle / close, plus the counter |
| scroll modals (help, file details) | scroll / close |

A band names the key, but not always what the key *means*: a reusable picker
knows Enter is Enter and nothing more. `ProgressiveSearchDialog` takes an
`accept_hint` for that half, injected the way its `titles` are, because XeFM's
search does not open the highlighted hit — it **feeds the whole result set into
the pane** (`XeFMApp._open_search` passes `"results to pane"`; see
[Search Results Pane](SEARCH_RESULTS_PANE_IMPLEMENTATION.md)). The band said
"Enter open" until someone read it and expected a file to open.

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
  printable-binding notice, the bar's three-step routing, and Ctrl+Space /
  Ctrl+Shift+Space marking through a live file list.
- `test/test_select_range.py` — `select_range` itself (#266): the span it fills,
  the anchor rule, the log lines, both contexts' defaults, and what a config
  written before the action existed resolves to.
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
