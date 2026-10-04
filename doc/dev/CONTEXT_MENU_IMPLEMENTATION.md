# Context Menus — Implementation

End-user behavior: [CONTEXT_MENU_FEATURE.md](../CONTEXT_MENU_FEATURE.md).

## Two menus, three ways in

`XeFMApp` builds two menus and opens them from three places:

| Entry | Menu | Anchor |
|---|---|---|
| Right-click on a row (`FilePane.on_context`, index ≥ 0) | `_item_context_menu` | the pointer |
| Right-click below the rows (`on_context`, index -1) | `_dir_context_menu` | the pointer |
| `context_menu` (`/`, `APPS`) | item, or dir in an empty pane | `FilePane.menu_anchor(focused_index)` |
| `context_menu_dir` (`?`, `Shift-APPS`) | dir | `PaneHeader.menu_anchor()` |

The pair is cfiler's `ContextMenu` / `ContextMenuDir` (`Slash` / `S-Slash` on its
US keymap), which also opened the item menu one row under the cursor.

`FilePane` used to swallow a right-click with no row under it, on the grounds
that a context menu is for an item. It now reports -1 and lets the app decide:
the click is on the directory.

## Anchors

`FilePane.menu_anchor(index)` is the inverse of `_row_at`: screen origin + top
margin + `(index - offset)` rows, plus one row so the menu opens *under* the
cursor row rather than over it. A row scrolled out of view falls back to the top
of the listing.

The directory menu hangs from the path bar instead (`PaneHeader.menu_anchor`:
the bar's bottom edge, under the start of the path text; `XeFMApp._headers` keeps
the bars, as `_footers` does). Anchored to the listing's top it opened under the
first row and read as that file's menu — the bar is the line that names the
directory.

`popup_menu` takes base units on every backend, so neither anchor needs a
capability branch — a native backend converts it, the widget popup clamps it to
the screen. The geometry comes from the last draw (`_abs`, `_margin_y`, the
bar's rect); a keyboard action always runs after at least one frame, so it is
current.

## Keys

- `/` and `?` are glyphs: XeFM matches punctuation by the character produced,
  so Shift-/ *is* `?` and the two are reachable on any layout that has them.
- That is also why `help` had to move. A terminal delivers Shift-/ as `?`; there
  is no way to bind "Shift + the slash key" apart from the glyph. `help`
  defaults to `F1` now.
- `APPS` is a named key (`config._NAMED_KEYS` → PuiKit's `apps`). PuiKit maps
  `VK_APPS` on Windows (desktop and console), `NSMenuFunctionKey` on macOS and
  `ContextMenu` on the web; a POSIX terminal sends nothing. A named key keeps
  its Shift, so `Shift-APPS` is a separate binding. On an older PuiKit the key
  simply never arrives — nothing breaks, which is why the PuiKit floor did not
  have to move for it.
- An old config with `'help': ['?']` keeps help on `?`: config entries are
  resolved before built-in defaults (`KeyBindings._context_binding`), so
  `context_menu_dir`'s default `?` loses to it, and the directory menu stays
  reachable through `Shift-APPS` and the right-click.

## Directory menu items

New Directory / New File reuse `create_directory` / `create_file` (which refuse
inside an archive themselves). Add to Favorites calls `_name_favorite(pane path,
is_file=False)`. Copy Full Path and Open in Finder/Explorer are small helpers
(`_copy_dir_path`, `_open_dir_in_os`). A virtual pane disables everything that
needs a directory; Open in OS and Subshell Here also need a local one.

## Tests

`test/test_context_menu_keys.py` (actions, anchors, empty pane, virtual pane,
right-click below the rows), `test/test_pane_click_activation.py` (-1 is
reported), `test/test_keybindings_puikit_contract.py` (`/`, `?`, `F1`, `apps`).
