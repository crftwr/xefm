# Context Menus

English \| [日本語](CONTEXT_MENU_FEATURE.ja.md)

The file list has two context menus: one for the **item under the cursor**,
and one for the **directory** the pane is showing. Each opens with the mouse or
from the keyboard.

| Menu | Action | Keyboard | Mouse |
|---|---|---|---|
| Item | `context_menu` | the Menu key, plus a preset key | Right-click a row |
| Directory | `context_menu_dir` | `?`, or Shift + the Menu key | Right-click the empty space below the last row |

The item menu's other key depends on your keymap preset — see
[Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

From the keyboard, the item menu opens just under the cursor row and the
directory menu hangs from the path bar at the top of the pane — the line that
names the directory. In the desktop app they are the system's own menus; in the
terminal they are drawn by XeFM. Either way, ↑/↓ and Enter choose, and Esc
closes.

The **Menu key** is the one between the right Alt and Ctrl on a PC keyboard.
It works in the Windows desktop app and the Windows terminal, and on macOS with
a PC keyboard. A terminal on macOS or Linux never passes it on, which is why
both actions also have a key that works everywhere.

## What is in them

**Item menu** — Open, View File, Open With… ([Open With](OPEN_WITH_FEATURE.md)), Select / Deselect, Rename…, Duplicate, Copy /
Move to Other Pane, Copy to… / Move to…, Delete, Copy Name(s), Copy Full Path(s), Open as List, Add
to Favorites… (that item), Show Hidden Files. Copy, Move and Delete act on the
marked files when there are any, as their keys do. Select / Deselect leaves the
cursor on the item, unlike `toggle_select_down`, which moves on to the next row.

An empty directory has no item, so `context_menu` opens the directory menu there
instead.

**Directory menu** — New Directory…, New File…, Add to Favorites… (this
directory), Copy Full Path, Open in Finder / Explorer, Subshell Here, Sort…,
Show Hidden Files.

In a search-results or imported list there is no directory of its own, so the
items about one are greyed out. Open in Finder / Explorer and Subshell Here need
a local directory, so they are greyed out on `ssh://`, `s3://` and inside
archives.

## Help moved to F1

`?` opens the directory menu, and the help is on **F1** (also
**Help ▸ Keyboard Shortcuts…**).

A config written when `?` opened the help may still say `'help': ['?']`, and keeps
working that way: your own line wins over the new default. To move to the new
keys, change it to `'help': ['F1']`.

## Changing the keys

```python
KEY_BINDINGS = {
    'context_menu': ['/', 'APPS'],
    'context_menu_dir': ['?', 'Shift-APPS'],
    'help': ['F1'],
}
```

`APPS` is the Menu key's name. See [Key Bindings](KEY_BINDINGS_FEATURE.md).
