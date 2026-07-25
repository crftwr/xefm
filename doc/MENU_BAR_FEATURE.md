# Menu Bar Feature

## Overview

In desktop (GUI) mode, XeFM shows a native menu bar so you can drive the file
manager with the mouse in addition to the keyboard. The menus mirror XeFM's
keyboard actions: every menu item runs the same action as its key binding, and
each item's shortcut hint is generated **from the live keymap** — so if you
rebind a key in `~/.xefm/config.py`, the menu updates to match.

## Platform Support

- **macOS desktop mode** (`python3 -m xefm --backend gui`): a native `NSMenu` menu bar.
- **Terminal mode**: an in-window menu strip along the top row.

The menu structure and shortcuts are the same in both.

## Accessing the Menu Bar

### Launching Desktop Mode

```bash
# Launch XeFM as a native macOS window
python3 -m xefm --backend gui
```

### Using the Menu Bar

- **Mouse**: click a menu title, then click an item.
- **Keyboard**: every item can be triggered directly by its shortcut (shown next
  to the item) without opening the menu.

## Available Menus

XeFM has four menus: **File**, **Select**, **View**, and **Help**.

### File Menu

| Item | Shortcut |
|------|----------|
| Open | Enter |
| View File | V |
| Edit File | E |
| Details… | I |
| Open with Default App | Cmd-Enter |
| Reveal in File Manager | Alt-Enter |
| External Programs… | X |
| Subshell Here | Shift-X |
| Parent Directory | Backspace |
| Go to Favorite… | J |
| Jump to Path… | Shift-J |
| Drives… | D |
| History… | H |
| New Folder… | M *(when nothing is selected)* |
| New File… | Shift-E |
| Rename… | R |
| Copy to Other Pane | C |
| Move to Other Pane | M *(when files are selected)* |
| Delete… | K |
| Copy Name(s) | Cmd-Shift-C |
| Copy Full Path(s) | Cmd-Shift-P |
| Create Archive… | P |
| Extract Archive… | U |
| Quit | Q |

### Select Menu

| Item | Shortcut |
|------|----------|
| Toggle Selection | Space |
| Select All Items | Shift-A |
| Clear Selection | End |
| Compare and Select… | W |
| Compare Selected Files… | = |
| Compare Directories… | Shift-= |

### View Menu

| Item | Shortcut |
|------|----------|
| Find… | F |
| Filter… | ; |
| Search Files… | Shift-F |
| Search Content… | Shift-G |
| Show Hidden Files | . |
| Reverse Sort | — |
| Sort By ▸ | (submenu: Name / Extension / Size / Date; quick keys `1`–`4`) |
| Theme ▸ | (submenu of installed themes) |
| Next Theme | T |
| Switch Pane | Tab |

### Help Menu

| Item | Shortcut |
|------|----------|
| Keyboard Shortcuts… | ? |
| About XeFM | — |

> Note: `M` is context-sensitive — it creates a new folder when nothing is
> selected, and moves the selection when files are selected. This is a property
> of the `create_directory` / `move_files` key bindings, and the menu reflects
> both.

## Menu Item States

Items enable and disable based on context. For example, **Copy/Move/Delete** and
**Create Archive** require a selection; **Rename**, **View**, and **Details**
require a focused item; **Parent Directory** is disabled at the filesystem root.
Disabled items appear grayed out.

## Keyboard Shortcuts

### How shortcut hints are produced

Each menu item shows the first key bound to its action, formatted for display —
single letters appear as-is (`C`, `R`), special keys are spelled out (`Enter`,
`Backspace`, `Tab`), and modifier combinations use `Cmd-`, `Shift-`, `Alt-`
prefixes (`Cmd-Shift-C`, `Shift-F`). Because the hint is read live from the
keymap, rebinding an action in config automatically updates its menu shortcut.

### Using shortcuts

You do not need to open a menu — pressing the shortcut runs the action directly.
The menu is there for discovery and mouse-driven use.

## Usage Examples

### Create a new folder
Open **File → New Folder…** (or press `M` when nothing is selected), type the
name, and confirm.

### Copy files to the other pane
Select files with `Space`, then **File → Copy to Other Pane** (or press `C`).

### Change the theme
Open **View → Theme ▸** and pick one, or press `T` to cycle to the next theme.

## Troubleshooting

### Menu bar not visible
Make sure you launched desktop mode (`python3 -m xefm --backend gui`). In terminal
mode the menu is the strip along the top row.

### A menu item is grayed out
The action isn't available in the current context (e.g. Copy with no selection,
or Parent Directory at the root). Adjust the selection or location and it enables.

### A shortcut doesn't work
Letter keys are case-sensitive, and the shortcut shown is whatever the action is
currently bound to in `~/.xefm/config.py`. Check your key bindings if you've
customized them.

## Related Features

- [Key Bindings](KEY_BINDINGS_FEATURE.md) — the keymap the menu mirrors
- [Configuration](CONFIGURATION_FEATURE.md) — customizing key bindings
- [Menu System](dev/MENU_SYSTEM.md) — developer documentation for the menu system
