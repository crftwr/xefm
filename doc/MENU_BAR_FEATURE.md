# Menu Bar Feature

English \| [日本語](MENU_BAR_FEATURE.ja.md)

## Overview

In desktop (GUI) mode, XeFM shows a native menu bar so you can drive the file
manager with the mouse in addition to the keyboard. The menus mirror XeFM's
keyboard actions: every menu item runs the same action as its key binding, and
each item's shortcut hint is generated **from the live keymap** — so if you
rebind a key in `~/.xefm/config.py`, the menu updates to match.

## Platform Support

- **macOS desktop mode**: a native `NSMenu` menu bar.
- **Windows desktop mode**: the window's native Win32 menu bar.
- **Terminal mode**: an in-window menu strip along the top row.

The menu structure and shortcuts are the same in all of them.

## Accessing the Menu Bar

### Launching Desktop Mode

Open the installed **XeFM** app from Launchpad or Spotlight on macOS, or the
Start menu on Windows — see the
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
name the **action** instead — press `F1` for the keys, or just read them off the
menu. Which actions have a key, and which key, depends on your keymap preset —
see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

### File Menu

| Item | Action |
|------|--------|
| Open | `open_item` |
| Open With ▸ Viewer | `view_file` |
| Open With ▸ Text Editor | `edit_file` |
| Open With ▸ Default App | `open_with_os` |
| Open With ▸ Choose App… | `open_with` — see [Open With](OPEN_WITH_FEATURE.md) |
| Details… | `file_details` |
| Reveal in File Manager | `reveal_in_os` |
| New Folder… | `create_directory` *(when nothing is selected)* |
| New File… | `create_file` |
| Rename ▸ Rename… | `rename` |
| Rename ▸ Rename in Editor… | `rename_in_editor` |
| Duplicate | `duplicate_files` |
| Copy to Other Pane | `copy_files` |
| Move to Other Pane | `move_files` *(when files are selected)* |
| Copy to… | `copy_files_to` |
| Move to… | `move_files_to` |
| Move to Trash… / Move to Recycle Bin… | `delete_files` — see [Trash](TRASH_FEATURE.md) |
| Delete Permanently… | `delete_permanently` |
| Archive ▸ Create… | `create_archive` |
| Archive ▸ Extract… | `extract_archive` |
| *(your `MENU_ITEMS` with `'file'`)* | up to three listed here; more go under **Custom ▸** |
| Quit | `quit` |

### Edit Menu

Everything that ends up on the clipboard.

| Item | Action |
|------|--------|
| Copy | `clipboard_copy` — see [File Clipboard](FILE_CLIPBOARD_FEATURE.md) |
| Cut | `clipboard_cut` |
| Paste | `clipboard_paste` |
| Show Clipboard… | `clipboard_show` *(ships unbound)* |
| Clear Clipboard | `clipboard_clear` *(ships unbound)* |
| Copy Name(s) | `copy_names` |
| Copy Full Path(s) | `copy_paths` |
| Copy Log Selection | `copy_log_selection` *(ships unbound; the Copy key does it when the log has a selection)* |
| Copy All Logs | `copy_log_all` *(ships unbound)* |

The log items act on the log pane under the file panes: select log text with
the mouse for the first, take the whole buffer with the second. See
[Logging](LOGGING_FEATURE.md#copy-log-to-clipboard).

### Go Menu

| Item | Action |
|------|--------|
| Parent Directory | `go_parent` |
| Root Directory | `go_root` |
| Go to Favorite… | `favorites` |
| Add to Favorites… | `add_favorite` |
| Jump to Path… | `jump_to_path` |
| Drives… | `drives` |
| Connect to Server… | `connect_server` |
| History… | `history` |
| Back | `go_back` |
| Forward | `go_forward` |
| Switch Pane | `switch_pane` |
| New Tab | `new_tab` — see [Folder Tabs](FOLDER_TABS_FEATURE.md) |
| Open in New Tab | `open_in_new_tab` |
| Close Tab | `close_tab` |
| Next Tab | `next_tab` |
| Previous Tab | `prev_tab` |
| Open List → From Clipboard | `open_list_from_clipboard` *(ships unbound)* — see [File lists](FILE_LIST_IMPORT_FEATURE.md) |
| Open List → From Command… | `open_list_from_command` *(ships unbound)* |
| Open List → From File | `open_list_from_file` *(ships unbound)* — also **Open as List** on a file's right-click menu |

### Select Menu

| Item | Action |
|------|--------|
| Toggle Selection | `toggle_select_down` |
| Select to Cursor | `select_range` |
| Select All Items | `select_all` |
| Clear Selection | `unselect_all` |
| Select by Pattern… | `select_by_pattern` — see [Select by Pattern](SELECT_BY_PATTERN_FEATURE.md) |
| Unselect by Pattern… | `unselect_by_pattern` |
| Select Same Extension | `select_same_extension` |
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
| Search Spotlight… / Search Windows Search… | `index_search` — see [Searching the OS Index](OS_INDEX_SEARCH_FEATURE.md) |
| Search Tags… | `find_by_tag` *(ships unbound)* — see [File Tags](FILE_TAGS_FEATURE.md) |
| Reread | `reread` |
| Show Hidden Files | `toggle_hidden` |
| Layout ▸ | (submenu: every layout — also `choose_layout`) — see [File List Layouts](FILE_LIST_LAYOUTS_FEATURE.md) |
| Show ▸ | (submenu: each extra — Tags, and those `LAYOUT_EXTRAS` or an extension add — with Auto / On / Off, also `choose_extras`) |
| Resolve Attribute… | `resolve_attribute` *(ships unbound)* — a folder's total size and other attributes worked out on request; see [File List Layouts](FILE_LIST_LAYOUTS_FEATURE.md) |
| Sort By ▸ | (submenu: Name / Extension / Size / Date — also the `quick_sort_*` actions — then Reverse Sort, menu only) |
| Theme ▸ | (submenu: Next Theme, `toggle_color_scheme` *(ships unbound)*, then the installed themes) |
| Quick View | `quick_view` — see [Quick View](QUICK_VIEW_FEATURE.md) |
| Flat View | `flat_view` — see [Flat View](FLAT_VIEW_FEATURE.md) |

### Tools Menu

| Item | Action |
|------|--------|
| Command Palette… | `command_palette` |
| Background Jobs… | `jobs` — see [Background Jobs](BACKGROUND_JOBS_FEATURE.md) |
| Find Similar Files… | `find_similar` *(ships unbound)* — see [Find Similar Files](FIND_SIMILAR_FILES_FEATURE.md) |
| External Programs… | `programs` |
| Subshell Here | `subshell` *(desktop mode: in a terminal window)* |
| Edit Configuration… | `edit_config` *(ships unbound)* |
| Reload Configuration | `reload_config` *(ships unbound)* |
| Advanced ▸ Keymap… | Choose AFX style, Orthodox, OS native or Vim style, each described — see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md) |
| Advanced ▸ Extensions… | `extensions` *(ships unbound)* — see [Extension Packages](EXTENSIONS_FEATURE.md) |
| Advanced ▸ Check for Extension Updates… | `check_extension_updates` *(ships unbound)* |
| Advanced ▸ Install Extension… | `install_extension` *(ships unbound)* — a folder, `.zip`, URL or `github:owner/repo` |
| Advanced ▸ Sync Python Packages | `sync_python_packages` *(ships unbound)* — see [Extra Python Libraries](PYTHON_PACKAGES_FEATURE.md) |

Advanced holds what is set up once or now and then. Everything in it is also
in the command palette.

### Help Menu

| Item | Action |
|------|--------|
| Keyboard Shortcuts… | `help` |
| Tip of the Day… | *(menu only)* |
| About XeFM | *(menu only)* |

> Note: in AFX style, `create_directory` and `move_files` share one key, which
> does whichever fits — a new folder when nothing is selected, a move when files
> are. That is a property of their bindings, and the menu reflects both.

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
hint follows the case it is drawn in, so "Open with Default App" can show one
key in the macOS app and another in a terminal (see
[Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side)).

### Using shortcuts

You do not need to open a menu — pressing the shortcut runs the action directly.
The menu is there for discovery and mouse-driven use.

## Usage Examples

### Create a new folder
Open **File → New Folder…** (`create_directory`), type the name, and confirm.

### Copy files to the other pane
Select files (**Select → Toggle Selection**), then choose **File → Copy to Other
Pane** (`copy_files`).

### Change the theme
Open **View → Theme ▸** and pick one, or choose **View → Theme ▸ Next Theme** to cycle
to the next theme.

## Troubleshooting

### Menu bar not visible
Make sure you are running XeFM in desktop mode. In terminal mode the menu is the
strip along the top row.

### A menu item is grayed out
The action isn't available in the current context (e.g. Copy with no selection,
or Parent Directory at the root). Adjust the selection or location and it enables.

### A shortcut doesn't work
The shortcut shown is whatever the action is currently bound to in
`~/.xefm/config.py`. A bare letter is the unshifted key whichever case it is
written in (`q` and `Q` are the same binding); a shortcut shown as `Shift-Q`
needs Shift. Check your key bindings if you've customized them — see
[Key Bindings](KEY_BINDINGS_FEATURE.md).

## Related Features

- [Key Bindings](KEY_BINDINGS_FEATURE.md) — the keymap the menu mirrors
- [Configuration](CONFIGURATION_FEATURE.md) — customizing key bindings
- [Menu System](dev/MENU_SYSTEM.md) — developer documentation for the menu system
