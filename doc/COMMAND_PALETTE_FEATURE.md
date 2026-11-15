# Command Palette

English \| [日本語](COMMAND_PALETTE_FEATURE.ja.md)

Press **Ctrl-T** (or **Tools → Command Palette…**) to search every action the
file list understands and run the one you pick.

```
┌ Command Palette ───────────────────────────────────────┐
│ 🔍  [copy                                            ] │
│                                                        │
│ copy_names                                     Ctrl-N  │
│ copy_paths                                     Ctrl-P  │
│ copy_files                                          C  │
│ copy_files_to                                 Shift-C  │
│ copy_log_all                                           │
│                                                        │
│ Copy the file name(s) to the clipboard                 │
├────────────────────────────────────────────────────────┤
│ ↑/↓ select · Enter choose · F1 help · Esc cancel       │
└────────────────────────────────────────────────────────┘
```

## What is in it

- Every action of the file list — including the ones with no key and no menu
  item, such as `duplicate_files`, `focus_left` or `copy_log_all`.
- The actions every screen shares (`quit`, `help`, `isearch`, `edit_files`).
- Your own actions from `ACTIONS` in `config.py`.

Actions that only mean something inside a viewer (scrolling the text viewer,
zooming an image) are not listed; open that viewer and press **F1** for its keys.

## Using it

- **Type** part of a name to narrow the list. Words separated by spaces must all
  match, in any order: `sel all` finds `select_all` and `toggle_select_items`.
  Romaji finds Japanese names through Migemo, as in every other picker, and the
  best matches come first, also as there: `copy` lists `copy_files` above
  `clipboard_copy`.
- **↑/↓**, **Page Up/Page Down** move through the list.
- **Enter** runs the highlighted action on the active pane.
- **F1** opens a help page for the highlighted action: what it does, its keys,
  whether it needs a selection, and — for your own actions — the function's
  docstring. **Esc** closes the page and returns to the palette with your query
  and position intact.
- **Esc** closes the palette.

Each row shows the key the action is bound to on the right, so the palette is
also the quickest way to find out which key does something. The line under the
list describes the highlighted action.

An action that needs a selection still runs from the palette and works on the
item under the cursor, or says why it cannot — the same as choosing it from a
menu.

## The palette, the menu bar and F1 help

| | |
|---|---|
| **Menu bar** | the main operations, grouped, to browse |
| **F1 help** | every key on the current screen, to read and learn |
| **Command palette** | any action, found by a fragment of its name, and run |

## Keys you can change

```python
KEY_BINDINGS = {
    'command_palette': ['Ctrl-T'],      # open the palette (file list)
    'describe_list_item': ['F1'],       # help for the highlighted row (inside the palette)
}
```

`describe_list_item` belongs to the searchable-list pickers, so like
`remove_list_item` it must be a modified or non-printable key — the query field
takes every character you type.

## Describing your own actions

Write a docstring. Its first line is shown under the list, and the paragraphs
after the blank line are the page **F1** opens:

```python
def open_in_vscode(ctx):
    """Open the focused item in VS Code.

    Works on directories too — VS Code opens them as a workspace.
    """
    ctx.run_program(['code', str(ctx.pane.focused.path)])


class Config:
    ACTIONS = {
        'open_in_vscode': open_in_vscode,
    }
```

See [Customization](CUSTOMIZATION_FEATURE.md) for writing actions.
