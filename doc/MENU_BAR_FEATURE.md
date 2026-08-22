# Menu Bar Feature

## Overview

In desktop (GUI) mode, XeFM shows a native menu bar so you can drive the file
manager with the mouse in addition to the keyboard. The menus mirror XeFM's
keyboard actions: every menu item runs the same action as its key binding, and
each item's shortcut hint is generated **from the live keymap** — so if you
rebind a key in `~/.xefm/config.py`, the menu updates to match.

## Platform Support

- **macOS desktop mode**: a native `NSMenu` menu bar.
- **Terminal mode**: an in-window menu strip along the top row.

The menu structure and shortcuts are the same in both.

## Accessing the Menu Bar

### Launching Desktop Mode

Open the installed **XeFM** app from Launchpad or Spotlight — see the
[Desktop Mode Guide](DESKTOP_MODE_GUIDE.md#installing-the-desktop-app-package).
(During XeFM development, `python3 -m xefm --backend gui` opens the same window
from a checkout.)

### Using the Menu Bar

- **Mouse**: click a menu title, then click an item.
- **Keyboard**: every item can be triggered directly by its shortcut (shown next
  to the item) without opening the menu.

### Opening the menu with the keyboard (terminal mode)

In terminal mode, press **F10** to open the first menu (on the Windows
terminal, tapping **Alt** by itself works too, just like a desktop menu bar).
On the Windows terminal, **Alt+letter** opens a menu directly by the first
letter of its title: **Alt+F** for File, **Alt+G** for Go, **Alt+S** Select,
**Alt+V** View, **Alt+T** Tools, **Alt+H** Help. (Other terminals don't
deliver bare Alt or Alt+letter chords reliably — use F10 and the arrow keys
there.)

While a menu is open:

- **←/→** move between the menus on the bar (wrapping at the ends), and
  **Alt+letter** jumps straight to that menu;
- **↑/↓** move within the open menu;
- **a letter by itself** picks items by first letter: a unique match runs
  immediately, several matches step the highlight through them (press Enter
  on the one you mean);
- **→** on an item with a submenu opens the submenu, **←** backs out of it;
- **Enter** runs the highlighted item;
- **Esc** (or F10 again, or a click elsewhere) closes the menu.

The activation key is the `menu` action in `~/.xefm/config.py`
(default `['F10', 'ALT']`), so it can be rebound like any other; if you bind
`Alt-<letter>` chords of your own, they win over the menu accelerator. In
desktop mode the OS menu bar handles keyboard access natively (Alt on
Windows).

## Available Menus

XeFM has six menus: **File**, **Go**, **Select**, **View**, **Tools**, and
**Help** — in the terminal, each opens directly with Alt + its first letter
on the Windows terminal.

### File Menu

| Item | Shortcut |
|------|----------|
| Open | Enter |
| View File | V |
| Edit File | E |
| Details… | I |
| Open with Default App | Cmd-Enter |
| Reveal in File Manager | Alt-Enter |
| New Folder… | M *(when nothing is selected)* |
| New File… | Shift-E |
| Rename… | R |
| Duplicate | — |
| Copy to Other Pane | C |
| Move to Other Pane | M *(when files are selected)* |
| Delete… | K |
| Copy Name(s) | Cmd-Shift-C |
| Copy Full Path(s) | Cmd-Shift-P |
| Create Archive… | P |
| Extract Archive… | U |
| Quit | Q |

### Go Menu

| Item | Shortcut |
|------|----------|
| Parent Directory | Backspace |
| Go to Favorite… | J |
| Jump to Path… | Shift-J |
| Drives… | D |
| History… | H |

### Select Menu

| Item | Shortcut |
|------|----------|
| Toggle Selection | Space |
| Select All Items | Home |
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
| Next Theme | — |
| Switch Pane | Tab |

### Tools Menu

| Item | Shortcut |
|------|----------|
| External Programs… | X |
| Subshell Here | Shift-X *(terminal mode only)* |
| Edit Configuration… | — |
| Reload Configuration | — |

### Help Menu

| Item | Shortcut |
|------|----------|
| Keyboard Shortcuts… | ? |
| Tip of the Day… | — |
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
Make sure you are running XeFM in desktop mode. In terminal mode the menu is the
strip along the top row.

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
