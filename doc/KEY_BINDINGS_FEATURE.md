# Key Bindings Feature

## Overview

XeFM's key bindings system allows you to customize keyboard shortcuts for all actions in the application. The system supports:

- **Single-character keys**: Simple keys like 'q', 'a', '?'
- **Key names**: Keys with no glyph, like 'ENTER', 'UP', 'PAGE_DOWN', 'F10'
- **Punctuation by name**: 'SEMICOLON', 'BACKQUOTE', 'LEFT_BRACKET'
- **Modifier combinations**: Keys with modifiers like 'Shift-Down', 'Command-Q'
- **Multiple keys per action**: Assign several keys to the same action
- **Selection requirements**: Control when actions are available based on file selection

## Key Expression Format

### Single Character Keys

The simplest form - just a single character:

```python
'quit': ['Q']
'help': ['?']
'toggle_hidden': ['.']
```

**Important behavior:**

- **A letter is the same binding whichever case you write it in.** `'a'` and
  `'A'` both mean the A key with no modifier.
- **Writing a capital is not the same as pressing Shift.** A binding written
  `'Q'` does *not* fire when you press Shift+Q — it is still the unshifted key.
  Write `'Shift-Q'` when you mean the shifted one, which is why the defaults
  spell out `'Shift-F'` next to `'F'`.
- **Punctuation and digits are the glyph they produce**, so `?` and `/` are
  different keys even though they share one physical key.

Examples:
```python
'quit': ['Q']              # the Q key; writing 'q' would mean the same
'help': ['?']              # the '?' glyph, not the '/' key it shares
'isearch': ['F']           # F on its own
'find_files': ['Shift-F']  # Shift+F — a different binding from 'F'
```

### Key Names

A key with no glyph of its own is written by name:

```python
'move_up': ['UP']
'page_up': ['PAGE_UP']
'confirm': ['ENTER']
'cancel': ['ESCAPE']
'menu': ['F10']
```

**This is the complete list.** A name that is not here is not accepted: XeFM
logs `Unknown key in expression: ...` and the binding never fires.

| Group | Names |
|---|---|
| Navigation | `UP`, `DOWN`, `LEFT`, `RIGHT`, `HOME`, `END`, `PAGE_UP` (or `PAGEUP`), `PAGE_DOWN` (or `PAGEDOWN`) |
| Editing | `ENTER` (or `RETURN`), `ESCAPE` (or `ESC`), `TAB`, `BACKSPACE`, `DELETE` (or `DEL`), `INSERT`, `SPACE` |
| Function keys | `F1` through `F12` |
| Bare Alt tap | `ALT` on its own — Alt pressed and released with nothing in between. Delivered only by the Windows terminal, where it opens the menu bar. As a *prefix* (`Alt-X`) it is the modifier instead. |

Names are **case-insensitive**: `'ENTER'`, `'enter'` and `'Enter'` all work.

### Punctuation by Name

Punctuation can be written as its glyph (`'-'`, `'['`, `';'`) or by name, which
is easier to read in a config file:

| Name(s) | Key | `Shift-` gives |
|---|---|---|
| `MINUS` | `-` | `_` |
| `EQUAL`, `EQUALS` | `=` | `+` |
| `LEFT_BRACKET` | `[` | `{` |
| `RIGHT_BRACKET` | `]` | `}` |
| `BACKSLASH` | `\` | `\|` |
| `SEMICOLON` | `;` | `:` |
| `QUOTE`, `APOSTROPHE` | `'` | `"` |
| `COMMA` | `,` | `<` |
| `PERIOD`, `DOT` | `.` | `>` |
| `SLASH` | `/` | `?` |
| `GRAVE`, `BACKTICK`, `BACKQUOTE` | `` ` `` | `~` |

`Shift-` on a punctuation or digit key resolves to the character that key
actually produces on a US layout — `'Shift-EQUAL'` is `+`, `'Shift-1'` is `!`,
`'Shift-BACKQUOTE'` is `~` — so the two ways of writing it are the same binding:

```python
'go_root': ['BACKSLASH']          # same as ['\\']
'adjust_log_up': ['Shift-LEFT_BRACKET']   # same as ['{']
```

On a non-US layout, write the glyph your keyboard produces rather than the
shifted name.

### Modifier Key Combinations

Add modifiers before the main key, separated by hyphens:

```python
'page_up': ['PAGE_UP', 'Shift-UP']
'page_down': ['PAGE_DOWN', 'Shift-DOWN']
'jump_to_top': ['Command-UP']
'jump_to_bottom': ['Command-DOWN']
'delete_files': ['DELETE', 'Command-Backspace']
```

**Available modifiers:**
- `Shift` - Shift key
- `Control` or `Ctrl` - Control key
- `Alt` or `Option` - Alt/Option key
- `Command` or `Cmd` - Command key (macOS)

**Modifier rules:**
- Modifiers are **case-insensitive**: `'Shift'`, `'SHIFT'`, and `'shift'` all work
- Modifier **order doesn't matter**: `'Command-Shift-X'` equals `'Shift-Command-X'`
- You can combine **multiple modifiers**: `'Command-Shift-X'`, `'Control-Alt-Delete'`

### What a terminal can carry

The same XeFM runs as a desktop app and in a terminal, and a terminal cannot
send every chord a window can. The defaults are therefore **one common table** —
every key in it reaches XeFM in the macOS app, the Windows app and any terminal —
with two per-case additions where a desktop platform owns the gesture outright:

| Case | What is added |
|---|---|
| macOS desktop | `Command-ENTER` for `open_with_os`, `Command-C` for `copy_log_selection` |
| Windows desktop | `Ctrl-ENTER` for `open_with_os` |
| Any terminal | nothing — the common table is the whole keymap |

What a terminal cannot deliver, and why those chords are not in the common table:

| Chord | Why not |
|---|---|
| `Command-<key>` | No terminal encodes the Command key at all — not Terminal.app, not iTerm2, not VS Code's. |
| `Ctrl-Shift-<letter>` | A terminal sends Ctrl+letter as a single control byte with no room for Shift, so `'Ctrl-Shift-C'` *is* `'Ctrl-C'` there. (The Windows console is the exception, but a binding that works on one console only is not a default.) |
| `Ctrl-ENTER` | Same reason — indistinguishable from plain `ENTER`. |
| `Alt-ENTER` | macOS keyboards spend Option on glyphs and IME, and the Windows terminal takes Alt+Enter for fullscreen. |
| `Ctrl-I`, `Ctrl-M`, `Ctrl-J`, `Ctrl-H`, `Ctrl-[` | Those bytes already *are* Tab, Enter, Backspace and Escape. |

Shift and Ctrl on a **named** key are fine everywhere — `Ctrl-UP`, `Shift-DOWN`,
`Ctrl-HOME`, `Shift-F3` — because a terminal has a sequence for those. That
leaves **plain `Ctrl-<letter>`** as the chord family the whole keymap can rely on,
which is what the OS-flavoured actions use.

### Keys the host takes first

On top of that, whatever runs XeFM may claim a chord before XeFM sees it. Nothing
is logged when it does — XeFM is never told the key was pressed, so the binding
simply does nothing. The ones worth knowing:

- **Windows Terminal** claims `Ctrl-Shift-P` (command palette), `Ctrl-Shift-F`
  (find), `Ctrl-Shift-T`/`N`/`D`/`W` (tabs, windows, panes), `Ctrl-Shift-A`/`V`/`M`/`K`
  (select all, paste, mark mode, clear), `Ctrl-Shift-<arrow>`/`HOME`/`END`/`PAGE_UP`/`PAGE_DOWN`
  (scrollback), `Ctrl-Shift-SPACE`, `Ctrl-Shift-TAB`, `Ctrl-Shift-<digit>`,
  `Ctrl-Alt-<digit>`, `Alt-ENTER` and `F11`. Its copy chords (`Ctrl-Shift-C`,
  `Ctrl-INSERT`, `ENTER`) only fire while text is selected *in the terminal*; with
  nothing selected they fall through.
- **VS Code's integrated terminal** keeps the commands listed in
  `terminal.integrated.commandsToSkipShell` and never sends them on. That
  includes the command palette (`Cmd-Shift-P` / `Ctrl-Shift-P`) and Quick Open
  (`Ctrl-P` and `Ctrl-E` on Windows and Linux) — so `copy_paths` on `Ctrl-P` is
  the one deliberate compromise in the defaults: it works in every terminal
  except that one, where Quick Open opens instead. Rebind it there, or use
  **Edit → Copy Full Path(s)**.
- **tmux and screen** keep their prefix key (`Ctrl-B`, `Ctrl-A`) and whatever is
  typed after it.

### Defaults that moved

These changed when the keymap became one common table, and an existing
`~/.xefm/config.py` keeps whatever it already says — XeFM fills in a setting your
config is missing, but never rewrites the `KEY_BINDINGS` you already have. Edit
the lines by hand if your config predates the change:

| Action | Was | Now |
|---|---|---|
| `open_with_os` | `Command-ENTER` / `Ctrl-ENTER` (Windows) | `Ctrl-O`, plus the old chord in the desktop app |
| `reveal_in_os` | `Alt-ENTER` / `Ctrl-Shift-E` (Windows) | `Ctrl-R` |
| `copy_names` | `Command-Shift-C` / `Ctrl-Shift-C` (Windows) | `Ctrl-N` |
| `copy_paths` | `Command-Shift-P` / `Ctrl-Shift-P` (Windows) | `Ctrl-P` |
| `copy_log_selection` | `Command-C`, `Ctrl-C` | `Ctrl-C`, plus `Command-C` in the macOS app |

## Configuration Format

### Simple Format

For actions without selection requirements, use a list of keys:

```python
KEY_BINDINGS = {
    'quit': ['Q'],              # the Q key ('q' would mean the same)
    'help': ['?'],              # the '?' glyph
    'move_up': ['UP', 'k'],     # two keys for one action
    'move_down': ['DOWN', 'j'],
}
```

### Extended Format

For actions that require or prohibit file selection, use a dictionary:

```python
KEY_BINDINGS = {
    'delete_files': {
        'keys': ['K', 'DELETE'],
        'selection': 'required'  # Only available when files are selected
    },
    'create_directory': {
        'keys': ['M'],
        'selection': 'none'  # Only available when no files are selected
    },
}
```

The plain list form is just shorthand for `'selection': 'any'`, so existing
list-style bindings keep working unchanged.

**Selection requirements:**
- `'required'` - Action only available when files are selected
- `'none'` - Action only available when no files are selected
- `'any'` - Action always available (default)

**Default selection-aware actions.** Out of the box these file operations use
`'required'` (they act on the selection, so they're hidden when nothing is
selected): `copy_files` (`C`), `move_files` (`M`), `delete_files` (`K` / `DELETE`),
and `create_archive` (`P`). `create_directory` (`M`) uses `'none'` so it shares
the `M` key with `move_files` without conflict — XeFM picks whichever action fits
the current selection state. You can add a `'selection'` requirement to any other
action the same way.

### Viewer keys

The keys used *inside* the text, image, diff and directory-diff viewers are named
actions too, prefixed with the viewer they belong to — `text_viewer.page_down`,
`file_diff.next_block`, `dir_diff.switch_side`. They are not listed in the
default `KEY_BINDINGS` because they work without an entry; add one only for a key
you want to change:

```python
KEY_BINDINGS = {
    'text_viewer.page_down': ['SPACE'],
    'file_diff.next_block': ['J'],
}
```

Because each surface only looks at its own names, a viewer key may share a key
with a file-list key with no conflict. The same prefix also scopes a *shared*
action — `quit`, `help`, `isearch`, `edit_file` — to one viewer:
`'file_diff.quit': ['X']` changes it there and nowhere else.

The full list of viewer actions and their defaults is in
[Customization (Preview)](CUSTOMIZATION_FEATURE.md), along with how to bind a key
to a Python function of your own.

### Search bar keys

The incremental search bar (`F`) is a surface of its own too, and its keys carry
its name the same way — `isearch.next_match`, `isearch.prev_match`,
`isearch.toggle_select_down`, `isearch.toggle_select_up`,
`isearch.select_matches`, `isearch.accept`, `isearch.cancel`. They are rebound
exactly like a viewer's; the defaults and what each one does are in
[Customization (Preview)](CUSTOMIZATION_FEATURE.md#the-incremental-search-bar).

One rule is specific to this surface: **the key must not be one that types a
character.** The pattern field is offered every printable key first — that is
what keeps `Q`, `?` and Space typeable into a pattern while `quit`, `help` and
`toggle_select_down` own them in the file list — so an isearch action bound to
`N` can never fire. XeFM notes it in the log pane at startup rather than leaving
the binding silently dead. `Shift-DOWN`, `Ctrl-N` and `F2` are all fine.

### Renamed actions

Some actions have been given clearer names. **Your old names keep working** — a
config binding one still resolves to the same action — and XeFM notes it once in
the log pane at startup. Rename when convenient; nothing breaks if you don't.

| Old name | Current name |
|---|---|
| `search` | `isearch` |
| `search_dialog` | `find_files` |
| `search_content` | `find_in_files` |
| `sort_menu` | `sort` |
| `drives_dialog` | `drives` |
| `rename_file` | `rename` |
| `select_file` | `toggle_select_down` |
| `select_file_up` | `toggle_select_up` |
| `select_all_files` | `toggle_select_files` |
| `select_all_items` | `toggle_select_items` |
| `image_zoom_in` | `image_viewer.zoom_in` |
| `image_zoom_out` | `image_viewer.zoom_out` |
| `image_zoom_reset` | `image_viewer.zoom_reset` |
| `image_next` | `image_viewer.next` |
| `image_prev` | `image_viewer.prev` |
| `image_scroll_up` | `image_viewer.pan_up` |
| `image_scroll_down` | `image_viewer.pan_down` |
| `image_scroll_left` | `image_viewer.pan_left` |
| `image_scroll_right` | `image_viewer.pan_right` |

Three kinds of change are in there. The image viewer's actions gained their
viewer's prefix, which leaves the plain names — `zoom_in`, `next` — free to
become shared actions if a second viewer ever grows them. The `image_scroll_*`
group became `pan_*`, which is what those keys have always done. And the three
unrelated things called "search" got names that say which is which: `isearch`
jumps to a match as you type, `find_files` searches for files by name,
`find_in_files` searches inside them.

The text viewer's `toggle_wrap`, `toggle_view_mode` and `change_encoding` were
deliberately **not** prefixed. Those name capabilities rather than one viewer's
use of them — the diff viewer could grow an encoding picker tomorrow — and an
unprefixed name is what lets a second viewer pick one up with no change to your
config at all.

If a config lists both spellings of an action, the current one wins and the old
one is ignored — so migrating a key at a time is safe.

## Complete Example

Here's a complete configuration example:

```python
# ~/.xefm/config.py

class Config:
    KEY_BINDINGS = {
        # Basic navigation
        'quit': ['q'],                    # Matches both 'q' and 'Q'
        'help': ['?'],                    # Matches only '?'
        'move_up': ['UP', 'k'],           # 'k' matches both 'k' and 'K'
        'move_down': ['DOWN', 'j'],       # 'j' matches both 'j' and 'J'
        'move_left': ['LEFT', 'h'],       # 'h' matches both 'h' and 'H'
        'move_right': ['RIGHT', 'l'],     # 'l' matches both 'l' and 'L'
        
        # Page navigation with modifiers
        'page_up': ['PAGE_UP', 'Shift-UP'],
        'page_down': ['PAGE_DOWN', 'Shift-DOWN'],
        'jump_to_top': ['HOME', 'Command-UP'],
        'jump_to_bottom': ['END', 'Command-DOWN'],
        
        # File operations with selection requirements
        'delete_files': {
            'keys': ['K', 'DELETE'],
            'selection': 'required'
        },
        'copy_files': {
            'keys': ['C'],                # 'C' and 'c' are equivalent
            'selection': 'required'
        },
        'create_directory': {
            'keys': ['M'],                # 'M' and 'm' are equivalent
            'selection': 'none'
        },
        # Use Shift modifier for uppercase-specific bindings
        'find_files': ['Shift-F'],     # Only matches Shift+F
    }
```

## Migration from Old Format

If you have an existing configuration, here's how to migrate:

### Old Format (Before)

```python
KEY_BINDINGS = {
    'quit': ['q', 'Q'],           # Redundant uppercase
    'copy_files': ['c', 'C'],     # Redundant uppercase
    'move_up': ['UP', 'k'],
    'page_up': ['PPAGE'],         # Old special key name
}
```

### New Format (After)

```python
KEY_BINDINGS = {
    'quit': ['Q'],                # one entry: 'Q' and 'q' are the same binding
    'copy_files': ['C'],          # likewise
    'move_up': ['UP', 'k'],       # a named key and a letter, both bound
    'page_up': ['PAGE_UP', 'Shift-UP'],  # the current name, plus a chord
}
```

**Key changes:**
- **Remove the duplicated letter**: `'q'` and `'Q'` are one and the same
  binding, so listing both does nothing.
- **Use the Shift modifier when you mean the shifted key**: `'Shift-F'`, not
  `'F'` — a capital in the token is not Shift.
- **Punctuation stays the glyph it produces**: `?` and `/` are different.
- `PPAGE` → `PAGE_UP`, `NPAGE` → `PAGE_DOWN`. The old curses names are **not
  accepted** — a config still using them logs `Unknown key in expression` at
  startup and that binding does nothing.
- All other key names are unchanged.

## Tips and Best Practices

1. **Use descriptive keys**: Choose keys that make sense for the action
2. **Provide alternatives**: Assign multiple keys to important actions
3. **Consider modifiers**: Use modifiers for related actions (e.g., Shift for page navigation)
4. **Test your bindings**: Make sure keys don't conflict with each other
5. **Document custom bindings**: Add comments to explain non-obvious choices

## Troubleshooting

### Key not working

1. Check the key expression format is correct
2. Verify the key name is one of those listed under "Key Names" and
   "Punctuation by Name" above — a name outside those lists logs
   `Unknown key in expression: ...` and never fires
3. Make sure modifiers are spelled correctly
4. Check for conflicts with other key bindings
5. In a terminal, check the chord is one a terminal can send at all, and that
   the emulator (or VS Code, or tmux) does not claim it first — see "What a
   terminal can carry" and "Keys the host takes first" above
6. For an `isearch.*` action, check the key is not a printable one — the search
   pattern is offered those first, so such a binding never fires (XeFM says so in
   the log pane at startup)

### Action not available

1. Check the selection requirement matches your current state
2. Verify files are selected if action requires `'selection': 'required'`
3. Verify no files are selected if action requires `'selection': 'none'`

### Modifier key not recognized

1. Verify modifier name is one of: Shift, Control/Ctrl, Alt/Option, Command/Cmd
2. Check spelling (case doesn't matter)
3. Make sure you're using hyphens to separate modifiers from the main key

## See Also

- [Configuration Feature](CONFIGURATION_FEATURE.md) - General configuration guide
- [Customization (Preview)](CUSTOMIZATION_FEATURE.md) - Viewer keys, your own actions, event hooks
- [Help Dialog Feature](HELP_DIALOG_FEATURE.md) - Viewing key bindings in XeFM
