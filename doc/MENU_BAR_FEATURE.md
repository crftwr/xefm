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

In terminal mode, the `menu` action opens the first menu (on the Windows
terminal, tapping **Alt** by itself works too, just like a desktop menu bar).
On the Windows terminal, **Alt+letter** opens a menu directly by the first
letter of its title: **Alt+F** for File, **Alt+E** Edit, **Alt+G** for Go,
**Alt+S** Select, **Alt+V** View, **Alt+T** Tools, **Alt+H** Help. (Other terminals don't
deliver bare Alt or Alt+letter chords reliably — use the `menu` action and the
arrow keys there.)

While a menu is open:

- **←/→** move between the menus on the bar (wrapping at the ends), and
  **Alt+letter** jumps straight to that menu;
- **↑/↓** move within the open menu;
- **a letter by itself** picks items by first letter: a unique match runs
  immediately, several matches step the highlight through them (press Enter
  on the one you mean);
- **→** on an item with a submenu opens the submenu, **←** backs out of it;
- **Enter** runs the highlighted item;
- **Esc** (or the `menu` key again, or a click elsewhere) closes the menu.

The activation key is the `menu` action in `~/.xefm/config.py`, so it can be
rebound like any other; if you bind
`Alt-<letter>` chords of your own, they win over the menu accelerator. In
desktop mode the OS menu bar handles keyboard access natively (Alt on
Windows).

## Available Menus

XeFM has seven menus: **File**, **Edit**, **Go**, **Select**, **View**,
**Tools**, and **Help** — in the terminal, each opens directly with Alt + its first letter
on the Windows terminal.

Each item draws the key its action is actually bound to, so the tables below
name the **action** instead — press `?` for the keys, or just read them off the
menu.

### File Menu

| Item | Action |
|------|--------|
| Open | `open_item` |
| View File | `view_file` |
| Edit File | `edit_file` |
| Details… | `file_details` |
| Open with Default App | `open_with_os` |
| Reveal in File Manager | `reveal_in_os` |
| New Folder… | `create_directory` *(when nothing is selected)* |
| New File… | `create_file` |
| Rename… | `rename` |
| Duplicate | *(menu only)* |
| Copy to Other Pane | `copy_files` |
| Move to Other Pane | `move_files` *(when files are selected)* |
| Delete… | `delete_files` |
| Create Archive… | `create_archive` |
| Extract Archive… | `extract_archive` |
| Quit | `quit` |

### Edit Menu

Everything that ends up on the clipboard.

| Item | Action |
|------|--------|
| Copy Name(s) | `copy_names` |
| Copy Full Path(s) | `copy_paths` |
| Copy Log Selection | `copy_log_selection` |
| Copy All Logs | `copy_log_all` *(ships unbound)* |

The log items act on the log pane under the file panes: select log text with
the mouse for the first, take the whole buffer with the second. See
[Logging](LOGGING_FEATURE.md#copy-log-to-clipboard).

### Go Menu

| Item | Action |
|------|--------|
| Parent Directory | `go_parent` |
| Go to Favorite… | `favorites` |
| Jump to Path… | `jump_to_path` |
| Drives… | `drives` |
| History… | `history` |

### Select Menu

| Item | Action |
|------|--------|
| Toggle Selection | `toggle_select_down` |
| Select to Cursor | `select_range` |
| Select All Items | `select_all` |
| Clear Selection | `unselect_all` |
| Compare and Select… | `compare_selection` |
| Compare Selected Files… | `diff_files` |
| Compare Directories… | `diff_directories` |

### View Menu

| Item | Action |
|------|--------|
| Find… | `isearch` |
| Filter… | `filter` |
| Search Files… | `find_files` |
| Search Content… | `find_in_files` |
| Show Hidden Files | `toggle_hidden` |
| Reverse Sort | *(menu only)* |
| Sort By ▸ | (submenu: Name / Extension / Size / Date — also the `quick_sort_*` actions) |
| Theme ▸ | (submenu of installed themes) |
| Next Theme | `toggle_color_scheme` *(ships unbound)* |
| Switch Pane | `switch_pane` |

### Tools Menu

| Item | Action |
|------|--------|
| External Programs… | `programs` |
| Subshell Here | `subshell` *(terminal mode only)* |
| Edit Configuration… | `edit_config` *(ships unbound)* |
| Reload Configuration | `reload_config` *(ships unbound)* |

### Help Menu

| Item | Action |
|------|--------|
| Keyboard Shortcuts… | `help` |
| Tip of the Day… | *(menu only)* |
| About XeFM | *(menu only)* |

> Note: `create_directory` and `move_files` ship on one key, which does whichever
> fits — a new folder when nothing is selected, a move when files are. That is a
> property of their bindings, and the menu reflects both.

## Menu Item States

Items enable and disable based on context. For example, **Copy/Move/Delete** and
**Create Archive** require a selection; **Rename**, **View**, and **Details**
require a focused item; **Parent Directory** is disabled at the filesystem root.
Disabled items appear grayed out.

## Keyboard Shortcuts

### How shortcut hints are produced

Each menu item shows the first key bound to its action, formatted for display —
single letters appear as-is, special keys are spelled out (`Enter`, `Backspace`,
`Tab`), and modifier combinations use `Cmd-`, `Shift-`, `Alt-` prefixes. Because
the hint is read live from the keymap,
rebinding an action in config automatically updates its menu shortcut — and the
hint follows the case it is drawn in, so "Open with Default App" reads
`Cmd-Enter` in the macOS app and `Ctrl-O` in a terminal.

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
