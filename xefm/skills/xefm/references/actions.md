# XeFM actions and their default keys

Generated from XeFM {XEFM_VERSION}'s action registry and keymap presets
by `tools/gen_skill_references.py` — do not edit by hand.

Use these names exactly in `KEY_BINDINGS` (and with `ctx.invoke`). The
key columns are each preset's defaults *before* the user's
`KEY_BINDINGS` is laid over them: to know whether a key is free, look
for it in the column of the preset in force (`KEY_PRESET`, or the one
the user picked in **Tools ▸ Advanced ▸ Keymap…**; ask which if `KEY_PRESET` is
`None` and you cannot tell) *and* in the user's own `KEY_BINDINGS`.
— means the action has no key by default.

## File list

| Action | What it does | AFX style | Orthodox | OS native | Vim style |
|---|---|---|---|---|---|
| `cursor_up` | Move the cursor up one item | `UP` | `UP` | `UP` | `k`, `UP` |
| `cursor_down` | Move the cursor down one item | `DOWN` | `DOWN` | `DOWN` | `j`, `DOWN` |
| `page_up` | Move the cursor up one page | `PAGE_UP` | `PAGE_UP` | `PAGE_UP` | `Ctrl-B`, `PAGE_UP` |
| `page_down` | Move the cursor down one page | `PAGE_DOWN` | `PAGE_DOWN` | `PAGE_DOWN` | `Ctrl-F`, `PAGE_DOWN` |
| `half_page_up` | Move the cursor up half a screen | — | — | — | `Ctrl-U` |
| `half_page_down` | Move the cursor down half a screen | — | — | — | `Ctrl-D` |
| `cursor_top` | Move the cursor to the first item | `Ctrl-HOME` | `HOME`, `Ctrl-HOME` | `HOME`, `Ctrl-HOME` | `g g`, `HOME`, `Ctrl-HOME` |
| `cursor_bottom` | Move the cursor to the last item | `Ctrl-END` | `END`, `Ctrl-END` | `END`, `Ctrl-END` | `Shift-G`, `END`, `Ctrl-END` |
| `open_item` | Open the file, or enter the directory | `ENTER` | `ENTER`, `Ctrl-PAGE_DOWN` | `ENTER` | `l`, `g l`, `ENTER` |
| `open_with_os` | Open with the OS default application | `Ctrl-O` | `Ctrl-O` | `Ctrl-O` | `g x` |
| `reveal_in_os` | Reveal in the OS file manager | `Ctrl-R` | — | — | `Ctrl-R` |
| `go_parent` | Go to the parent directory | `BACKSPACE` | `BACKSPACE`, `Ctrl-PAGE_UP` | `BACKSPACE`, `Alt-UP` | `h`, `g h`, `BACKSPACE` |
| `go_root` | Go to the root of the current drive or location | `\` | `Ctrl-BACKSLASH` | `\` | `\` |
| `switch_pane` | Switch between the left and right panes | `TAB` | `TAB` | `TAB` | `TAB`, `SPACE` |
| `nav_left` | Focus the left pane, or go to the parent | `LEFT` | `LEFT` | `LEFT` | `LEFT` |
| `nav_right` | Focus the right pane, or go to the parent | `RIGHT` | `RIGHT` | `RIGHT` | `RIGHT` |
| `focus_left` | Focus the left pane | — | — | — | — |
| `focus_right` | Focus the right pane | — | — | — | — |
| `toggle_select_down` | Toggle selection and move down | `SPACE` | `INSERT`, `SPACE` | `SPACE`, `INSERT` | `INSERT` |
| `toggle_select_up` | Toggle selection and move up | — | — | — | — |
| `toggle_select_in_place` | Toggle selection without moving the cursor | — | — | — | `t` |
| `select_all` | Select every item | `HOME` | `Ctrl-A` | `Ctrl-A` | — |
| `unselect_all` | Clear the selection | `END` | `Ctrl-MINUS` | — | `ESCAPE` |
| `toggle_select_files` | Toggle selection of every file | `A` | `*` | — | — |
| `toggle_select_items` | Toggle selection of every item | `Shift-A` | — | — | — |
| `select_range` | Select from the nearest selected item to the cursor | `Shift-SPACE` | `Shift-SPACE` | `Shift-SPACE` | `v`, `Shift-SPACE` |
| `search_next` | Go to the next match of the last incremental search | — | — | — | `n` |
| `search_prev` | Go to the previous match of the last incremental search | — | — | — | `Shift-N` |
| `select_by_pattern` | Select the files matching a pattern | `'` | `+` | `'` | — |
| `unselect_by_pattern` | Unselect the files matching a pattern | `"` | `-` | `"` | `"` |
| `select_same_extension` | Select every file with the cursor file's extension | — | `Alt-+` | — | — |
| `cursor_next_selected` | Jump to the next selected item | `Ctrl-DOWN` | — | `Ctrl-DOWN` | `Ctrl-DOWN` |
| `cursor_prev_selected` | Jump to the previous selected item | `Ctrl-UP` | — | `Ctrl-UP` | `Ctrl-UP` |
| `copy_names` | Copy the file name(s) to the clipboard | `Ctrl-N` | — | `Ctrl-N` | `Ctrl-N` |
| `copy_paths` | Copy the full path(s) to the clipboard | `Ctrl-P` | `Ctrl-P` | `Ctrl-P` | `Ctrl-P` |
| `copy_files` | Copy the selection to the other pane | `C` (selection: required) | `F5` | `F5` | `F5` |
| `move_files` | Move the selection to the other pane | `M` (selection: required) | `F6` | `F6` | `F6` |
| `copy_files_to` | Copy the selection to a directory typed in a prompt | `Shift-C` (selection: required) | — | — (selection: required) | — (selection: required) |
| `move_files_to` | Move the selection to a directory typed in a prompt | `Shift-M` (selection: required) | — | — (selection: required) | — (selection: required) |
| `duplicate_files` | Duplicate the selection in place | — | `Shift-F5` | — | — |
| `delete_files` | Move the selection to the Trash (or delete it where there is none) | `K`, `DELETE` (selection: required) | `F8`, `DELETE` | `DELETE`, `F8` | `d d`, `DELETE`, `F8` |
| `delete_permanently` | Delete the selection for good, skipping the Trash | `Shift-K`, `Shift-DELETE` (selection: required) | `Shift-F8`, `Shift-DELETE` | `Shift-DELETE`, `Shift-F8` | `Shift-D Shift-D`, `Shift-DELETE`, `Shift-F8` |
| `rename` | Rename the focused item, or batch-rename the selection | `R` | `Shift-F6`, `Ctrl-M` | `F2` | `c w` |
| `rename_in_editor` | Rename the selection by editing its names in TEXT_EDITOR | `Shift-R` | — | — | — |
| `create_file` | Create a new file | `Shift-E` | `Shift-F4` | — | — |
| `create_directory` | Create a new directory | `M` (selection: none) | `F7` | `F7` | `F7` |
| `view_file` | View the focused file in the built-in viewer | `V` | `F3` | `F3` | `e`, `F3` |
| `file_details` | Show details for the focused item | `I` | `Alt-ENTER` | `Alt-I` | `Ctrl-G` |
| `diff_files` | Compare two files side by side | `EQUAL` | `EQUAL` | `EQUAL` | — |
| `diff_directories` | Compare two directories recursively | `Shift-EQUAL` | — | `Shift-EQUAL` | `Shift-EQUAL` |
| `create_archive` | Create an archive from the selection | `P` (selection: required) | `Alt-F5` | — (selection: required) | — (selection: required) |
| `extract_archive` | Extract the selected archive(s) | `U` | `Alt-F9`, `Alt-F6` | — | — |
| `find_files` | Search for files by name | `Shift-F` | `Alt-F7` | `Ctrl-F` | — |
| `find_in_files` | Search inside files | `Shift-G` | — | — | — |
| `filter` | Filter the listing by a filename pattern | `;` | `Ctrl-S` | `;` | `=` |
| `clear_filter` | Clear the filename filter | `:` | `Ctrl-F10` | `:` | `z r` |
| `sort` | Open the sort dialog | `S` | — | — | `Shift-S` |
| `quick_sort_name` | Sort by name | `1` | `Ctrl-F3` | — | — |
| `quick_sort_ext` | Sort by extension | `2` | `Ctrl-F4` | — | — |
| `quick_sort_size` | Sort by size | `3` | `Ctrl-F6` | — | — |
| `quick_sort_date` | Sort by modification date | `4` | `Ctrl-F5` | — | — |
| `favorites` | Go to a favorite directory or file | `J` | `Ctrl-D` | — | `'` |
| `add_favorite` | Add a favorite, or tag the selection | `B` | — | — | — |
| `context_menu` | Open the context menu for the item under the cursor | `/`, `APPS` | `Shift-F10`, `APPS` | `Shift-F10`, `APPS` | `APPS`, `Shift-F10` |
| `context_menu_dir` | Open the context menu for the current directory | `?`, `Shift-APPS` | `?`, `Shift-APPS` | `?`, `Shift-APPS` | `?`, `Shift-APPS` |
| `jump_to_path` | Jump to a typed path | `Shift-J` | — | `Ctrl-L`, `Alt-D` | `g p` |
| `history` | Go to a recently visited directory | `H` | `Alt-DOWN` | `Alt-DOWN` | — |
| `go_back` | Go back to the directory shown before | `Alt-LEFT` | `Alt-LEFT` | `Alt-LEFT` | `Ctrl-O`, `Alt-LEFT` |
| `go_forward` | Go forward again after going back | `Alt-RIGHT` | `Alt-RIGHT` | `Alt-RIGHT` | `Alt-RIGHT` |
| `drives` | Show drives and volumes | `D` | `Alt-F1`, `Alt-F2` | — | — |
| `connect_server` | Connect to a network server | `Shift-D` | `Ctrl-F`, `Ctrl-N` | — | — |
| `flat_view` | Show every file below this directory as one list | `Shift-B` | `Ctrl-B` | — | — |
| `open_list_from_clipboard` | Open the paths on the clipboard as the pane's list | — | — | — | — |
| `open_list_from_command` | Open the paths a command prints as the pane's list | — | — | — | — |
| `open_list_from_file` | Open the list file under the cursor as the pane's list | — | — | — | — |
| `index_search` | Search the OS index under this folder | `Ctrl-F` | — | — | — |
| `find_by_tag` | Find the files with a tag under this folder | — | — | — | — |
| `clipboard_copy` | Copy files to the clipboard | `Ctrl-C`, `Y` | `Ctrl-C` | `Ctrl-C` | `y y`, `Ctrl-C` |
| `clipboard_cut` | Cut files to the clipboard | `Ctrl-X`, `Shift-Y` | `Ctrl-X` | `Ctrl-X` | `x`, `Ctrl-X` |
| `clipboard_paste` | Paste the clipboard into this folder | `Ctrl-V`, `G` | `Ctrl-V` | `Ctrl-V` | `p`, `Ctrl-V` |
| `clipboard_clear` | Empty the file clipboard | — | — | — | — |
| `clipboard_show` | Show what the file clipboard holds | — | — | — | — |
| `quick_view` | Preview the item under the cursor in the other pane | `Shift-V` | `Ctrl-Q` | `Alt-P` | `w` |
| `jobs` | List background jobs | `Ctrl-G` | `Ctrl-G` | `Ctrl-G` | — |
| `find_similar` | Find identical files, or similar images, videos or audio | — | — | — | — |
| `new_tab` | Open a new tab in this pane, at the same place | `T` | `Ctrl-T` | `Ctrl-T` | — |
| `open_in_new_tab` | Open the directory under the cursor in a new tab | `Shift-T` | `Ctrl-UP` | — | — |
| `close_tab` | Close this pane's current tab | `Ctrl-W` | `Ctrl-W` | `Ctrl-W` | `Ctrl-W` |
| `next_tab` | Show this pane's next tab | `Ctrl-PAGE_DOWN` | `Ctrl-TAB` | `Ctrl-PAGE_DOWN` | `Ctrl-PAGE_DOWN` |
| `prev_tab` | Show this pane's previous tab | `Ctrl-PAGE_UP` | `Ctrl-Shift-TAB` | `Ctrl-PAGE_UP` | `Ctrl-PAGE_UP` |
| `sync_current_to_other` | Go to the other pane's directory | `O` | — | — | — |
| `sync_other_to_current` | Send this directory to the other pane | `Shift-O` | — | — | — |
| `compare_selection` | Select by comparison with the other pane | `W` | `Shift-F2` | — | — |
| `adjust_pane_left` | Make the left pane smaller | `[` | `[` | `[` | `[` |
| `adjust_pane_right` | Make the left pane larger | `]` | `]` | `]` | `]` |
| `reset_pane_boundary` | Reset the pane split to 50 / 50 | `-` | — | `-` | `-` |
| `adjust_log_up` | Make the log pane larger | `{` | `{` | `{` | `{` |
| `adjust_log_down` | Make the log pane smaller | `}` | `}` | `}` | `}` |
| `reset_log_height` | Reset the log pane height | `_` | — | `_` | `_` |
| `scroll_log_up` | Scroll the log up one line | `Shift-UP` | `Shift-UP` | `Shift-UP` | `Shift-UP` |
| `scroll_log_down` | Scroll the log down one line | `Shift-DOWN` | `Shift-DOWN` | `Shift-DOWN` | `Shift-DOWN` |
| `scroll_log_page_up` | Scroll the log up one page | `Shift-LEFT` | `Shift-LEFT` | `Shift-LEFT` | `Shift-LEFT` |
| `scroll_log_page_down` | Scroll the log down one page | `Shift-RIGHT` | `Shift-RIGHT` | `Shift-RIGHT` | `Shift-RIGHT` |
| `copy_log_selection` | Copy the log pane's selected text to the clipboard | — | — | — | — |
| `copy_log_all` | Copy the whole log to the clipboard | — | — | — | — |
| `toggle_hidden` | Show or hide hidden files | `.` | `.` | `.` | `z a` |
| `toggle_color_scheme` | Cycle to the next color theme | — | — | — | — |
| `choose_layout` | Choose how the pane presents its rows | — | — | — | — |
| `choose_extras` | Turn an extra such as Git status on or off in this tab | — | — | — | — |
| `resolve_attribute` | Work out an attribute that takes time, such as a folder's total size | — | — | — | — |
| `redraw` | Redraw the screen | `F5` | — | — | — |
| `reread` | Re-read both panes' directories | — | `F2`, `Ctrl-R` | `Ctrl-R` | `Ctrl-L` |
| `menu` | Open the menu bar | `F10`, `ALT` | `F9`, `F10`, `ALT` | `F10`, `ALT` | `F10`, `ALT` |
| `command_palette` | Search every action by name and run it | `Ctrl-T` | `Ctrl-Shift-P` | `Ctrl-K` | `:`, `Ctrl-T` |
| `choose_keymap` | Choose the keymap preset | — | — | — | — |
| `programs` | Run an external program | `X` | — | — | — |
| `subshell` | Open a subshell in this directory | `Shift-X` | — | — | `s` |
| `edit_config` | Edit config.py, then reload it | — | — | — | — |
| `reload_config` | Re-read config.py and apply it live | — | — | — | — |
| `install_extension` | Install an extension package from a folder, a .zip, a URL or GitHub | — | — | — | — |
| `extensions` | List the extension packages and whether they loaded | — | — | — | — |
| `check_extension_updates` | Look for newer versions of the installed extension packages | — | — | — | — |
| `sync_python_packages` | Install the Python packages ~/.xefm/requirements.txt lists | — | — | — | — |
| `quit` | Quit XeFM — or close the open viewer | `Q` | `Alt-F4` | `Ctrl-Q` | `Shift-Z Shift-Z`, `Shift-Z Shift-Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — | — | — | — |
| `help` | Show the key bindings for what is on screen | `F1` | `F1` | `F1` | `F1` |
| `isearch` | Incremental search | `F` | — | — | `/` |
| `edit_file` | Edit in the configured text editor | `E` | `F4` | `F4` | `F4` |

### Desktop app additions

The desktop app adds platform keys to a few actions (a terminal cannot
send them). These replace the row above in that app:

**macOS desktop app:**

- `clipboard_copy` (AFX style): `Command-C`, `Ctrl-C`, `Y`
- `clipboard_copy` (OS native): `Command-C`, `Ctrl-C`
- `clipboard_cut` (AFX style): `Command-X`, `Ctrl-X`, `Shift-Y`
- `clipboard_cut` (OS native): `Command-X`, `Ctrl-X`
- `clipboard_paste` (AFX style): `Command-V`, `Ctrl-V`, `G`
- `clipboard_paste` (OS native): `Command-V`, `Ctrl-V`
- `close_tab` (OS native): `Command-W`, `Ctrl-W`
- `command_palette` (OS native): `Command-Shift-P`, `Ctrl-K`
- `copy_paths` (OS native): `Command-Alt-C`, `Ctrl-P`
- `create_directory` (OS native): `Command-Shift-N`, `F7`
- `delete_files` (OS native): `Command-BACKSPACE`, `DELETE`, `F8`
- `delete_permanently` (OS native): `Command-Alt-BACKSPACE`, `Shift-DELETE`, `Shift-F8`
- `file_details` (OS native): `Command-I`, `Alt-I`
- `find_files` (OS native): `Command-F`, `Ctrl-F`
- `go_back` (AFX style): `Command-LEFT_BRACKET`, `Alt-LEFT`
- `go_back` (OS native): `Command-LEFT_BRACKET`, `Alt-LEFT`
- `go_forward` (AFX style): `Command-RIGHT_BRACKET`, `Alt-RIGHT`
- `go_forward` (OS native): `Command-RIGHT_BRACKET`, `Alt-RIGHT`
- `go_parent` (OS native): `Command-UP`, `BACKSPACE`, `Alt-UP`
- `jump_to_path` (OS native): `Command-Shift-G`, `Ctrl-L`
- `new_tab` (OS native): `Command-T`, `Ctrl-T`
- `open_item` (OS native): `ENTER`, `Command-DOWN`
- `open_with_os` (AFX style): `Command-ENTER`, `Ctrl-O`
- `open_with_os` (OS native): `Command-ENTER`, `Ctrl-O`
- `open_with_os` (Orthodox): `Command-ENTER`, `Ctrl-O`
- `quick_view` (OS native): `SPACE`, `Alt-P`
- `quit_app` (AFX style): `Command-Q`
- `quit_app` (OS native): `Command-Q`
- `quit_app` (Orthodox): `Command-Q`
- `quit_app` (Vim style): `Command-Q`
- `select_all` (OS native): `Command-A`, `Ctrl-A`
- `toggle_hidden` (OS native): `Command-Shift-.`, `.`
- `toggle_select_down` (OS native): `Ctrl-SPACE`, `INSERT`

**Windows desktop app:**

- `command_palette` (OS native): `Ctrl-Shift-P`, `Ctrl-K`
- `copy_paths` (OS native): `Ctrl-Shift-C`, `Ctrl-P`
- `create_directory` (OS native): `Ctrl-Shift-N`, `F7`
- `file_details` (OS native): `Alt-ENTER`, `Alt-I`
- `open_with_os` (AFX style): `Ctrl-ENTER`, `Ctrl-O`
- `open_with_os` (OS native): `Ctrl-ENTER`, `Ctrl-O`
- `open_with_os` (Orthodox): `Ctrl-ENTER`, `Ctrl-O`
- `quit_app` (AFX style): `Alt-F4`
- `quit_app` (OS native): `Alt-F4`
- `quit_app` (Orthodox): `Alt-F4`
- `quit_app` (Vim style): `Alt-F4`

## Inside viewers and dialogs

These keys are the same under every preset. Bind one with its full
dotted name (`'text_viewer.page_down': ['SPACE']`). A file-list action
name with a viewer prefix (`'file_diff.quit'`) rebinds it inside that
viewer only.

### `text_viewer`

| Action | What it does | Keys |
|---|---|---|
| `toggle_wrap` | Toggle line wrapping | `W` |
| `toggle_view_mode` | Toggle the rendered / raw view | `M` |
| `change_encoding` | Choose the text encoding | `Shift-E` |
| `text_viewer.scroll_up` | Scroll up one line | `UP` |
| `text_viewer.scroll_down` | Scroll down one line | `DOWN` |
| `text_viewer.page_up` | Scroll up one page | `PAGE_UP` |
| `text_viewer.page_down` | Scroll down one page | `PAGE_DOWN` |
| `text_viewer.scroll_top` | Go to the top | `HOME` |
| `text_viewer.scroll_bottom` | Go to the bottom | `END` |
| `text_viewer.scroll_left` | Scroll left (unwrapped only) | `LEFT` |
| `text_viewer.scroll_right` | Scroll right (unwrapped only) | `RIGHT` |
| `text_viewer.search_next` | Find the next match of the last search | — |
| `text_viewer.search_prev` | Find the previous match of the last search | — |
| `quit` | Quit XeFM — or close the open viewer | `Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — |
| `help` | Show the key bindings for what is on screen | `F1` |
| `isearch` | Incremental search | `F` |
| `edit_file` | Edit in the configured text editor | `E` |

### `image_viewer`

| Action | What it does | Keys |
|---|---|---|
| `image_viewer.zoom_in` | Zoom in | `+`, `=` |
| `image_viewer.zoom_out` | Zoom out | `-`, `_` |
| `image_viewer.zoom_reset` | Fit the whole image to the window | `0` |
| `image_viewer.next` | Next image in the file list | `DOWN` |
| `image_viewer.prev` | Previous image in the file list | `UP` |
| `image_viewer.pan_up` | Pan up (while zoomed in) | `Shift-UP` |
| `image_viewer.pan_down` | Pan down (while zoomed in) | `Shift-DOWN` |
| `image_viewer.pan_left` | Pan left (while zoomed in) | `Shift-LEFT` |
| `image_viewer.pan_right` | Pan right (while zoomed in) | `Shift-RIGHT` |
| `image_viewer.first` | First image in the file list | `HOME` |
| `image_viewer.last` | Last image in the file list | `END` |
| `quit` | Quit XeFM — or close the open viewer | `Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — |
| `help` | Show the key bindings for what is on screen | `F1` |
| `isearch` | Incremental search | `F` |
| `edit_file` | Edit in the configured text editor | `E` |

### `file_diff`

| Action | What it does | Keys |
|---|---|---|
| `file_diff.next_block` | Next diff block | `n` |
| `file_diff.prev_block` | Previous diff block | `Shift-N` |
| `file_diff.scroll_up` | Scroll up one line | `UP` |
| `file_diff.scroll_down` | Scroll down one line | `DOWN` |
| `file_diff.page_up` | Scroll up one page | `PAGE_UP` |
| `file_diff.page_down` | Scroll down one page | `PAGE_DOWN` |
| `file_diff.scroll_top` | Go to the top | `HOME` |
| `file_diff.scroll_bottom` | Go to the bottom | `END` |
| `file_diff.scroll_left` | Scroll left | `LEFT` |
| `file_diff.scroll_right` | Scroll right | `RIGHT` |
| `file_diff.search_next` | Find the next match of the last search | — |
| `file_diff.search_prev` | Find the previous match of the last search | — |
| `quit` | Quit XeFM — or close the open viewer | `Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — |
| `help` | Show the key bindings for what is on screen | `F1` |
| `isearch` | Incremental search | `F` |
| `edit_file` | Edit in the configured text editor | `E` |

### `dir_diff`

| Action | What it does | Keys |
|---|---|---|
| `copy_files` | Copy the focused node to the other side | `C` (selection: required) |
| `move_files` | Move the focused node to the other side | `M` (selection: required) |
| `delete_files` | Delete the focused node | `K`, `DELETE` (selection: required) |
| `view_file` | Open the focused node's file diff | `V` |
| `dir_diff.cursor_up` | Move the cursor up | `UP` |
| `dir_diff.cursor_down` | Move the cursor down | `DOWN` |
| `dir_diff.page_up` | Move the cursor up one page | `PAGE_UP` |
| `dir_diff.page_down` | Move the cursor down one page | `PAGE_DOWN` |
| `dir_diff.cursor_top` | Go to the first row | `HOME` |
| `dir_diff.cursor_bottom` | Go to the last row | `END` |
| `dir_diff.expand` | Expand the focused directory | `RIGHT` |
| `dir_diff.collapse` | Collapse it, or go to its parent | `LEFT` |
| `dir_diff.activate` | Expand a directory, or diff a file | `ENTER` |
| `dir_diff.switch_side` | Switch the active side | `TAB` |
| `dir_diff.next_change` | Next difference | `n` |
| `dir_diff.prev_change` | Previous difference | `Shift-N` |
| `dir_diff.rescan` | Rescan both trees | `r` |
| `dir_diff.split_left` | Move the centre split left | `[` |
| `dir_diff.split_right` | Move the centre split right | `]` |
| `dir_diff.sync` | Sync: plan from the active side, or run it | `s` |
| `dir_diff.cycle_sync_action` | Change the focused node's sync action | `SPACE` |
| `dir_diff.toggle_identical` | Show or hide the items that are the same on both sides | `d` |
| `quit` | Quit XeFM — or close the open viewer | `Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — |
| `help` | Show the key bindings for what is on screen | `F1` |
| `isearch` | Incremental search | `F` |
| `edit_file` | Edit in the configured text editor | `E` |

### `isearch`

| Action | What it does | Keys |
|---|---|---|
| `isearch.next_match` | Move to the next match | `DOWN` |
| `isearch.prev_match` | Move to the previous match | `UP` |
| `isearch.toggle_select_down` | Toggle selection and move to the next match | `Ctrl-SPACE` |
| `isearch.toggle_select_up` | Toggle selection and move to the previous match | — |
| `isearch.select_matches` | Select every match (again: clear them) | `Ctrl-A` |
| `isearch.accept` | Stop at the current match | `ENTER` |
| `isearch.cancel` | Cancel and restore the cursor | `ESCAPE` |
| `quit` | Quit XeFM — or close the open viewer | `Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — |
| `help` | Show the key bindings for what is on screen | `F1` |
| `isearch` | Incremental search | `F` |
| `edit_file` | Edit in the configured text editor | `E` |

### `filter_list`

| Action | What it does | Keys |
|---|---|---|
| `remove_list_item` | Remove the highlighted entry from the list | `Shift-DELETE` |
| `describe_list_item` | Show help for the highlighted entry | `F1` |
| `quit` | Quit XeFM — or close the open viewer | `Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — |
| `help` | Show the key bindings for what is on screen | `F1` |
| `isearch` | Incremental search | `F` |
| `edit_file` | Edit in the configured text editor | `E` |

### `search`

| Action | What it does | Keys |
|---|---|---|
| `options` | Open the search options | `Ctrl-O`, `F9` |
| `toggle_case` | Change: Case sensitive | — |
| `toggle_word` | Change: Whole word | — |
| `toggle_regex` | Change: Regular expression | — |
| `toggle_subdirs` | Change: Search subfolders | — |
| `toggle_kind` | Change: Kind | — |
| `toggle_modified` | Change: Modified | — |
| `toggle_size` | Change: Size | — |
| `quit` | Quit XeFM — or close the open viewer | `Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — |
| `help` | Show the key bindings for what is on screen | `F1` |
| `isearch` | Incremental search | `F` |
| `edit_file` | Edit in the configured text editor | `E` |

### `common`

| Action | What it does | Keys |
|---|---|---|
| `quit` | Quit XeFM — or close the open viewer | `Q` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | — |
| `help` | Show the key bindings for what is on screen | `F1` |
| `isearch` | Incremental search | `F` |
| `edit_file` | Edit in the configured text editor | `E` |

## Old names

Names actions used to have. XeFM still accepts each one in
`KEY_BINDINGS`, as the action it now names, so an older `config.py`
may use them. Edit such an entry under the name it has (or rename
it); never add the current name beside it — two entries for one
action leave it unclear which keys win.

| Old name | Now |
|---|---|
| `select_file` | `toggle_select_down` |
| `select_file_up` | `toggle_select_up` |
| `select_all_files` | `toggle_select_files` |
| `select_all_items` | `toggle_select_items` |
| `rename_file` | `rename` |
| `search_dialog` | `find_files` |
| `search_content` | `find_in_files` |
| `sort_menu` | `sort` |
| `drives_dialog` | `drives` |
| `connect_to_server` | `connect_server` |
| `search` | `isearch` |
| `image_zoom_in` | `image_viewer.zoom_in` |
| `image_zoom_out` | `image_viewer.zoom_out` |
| `image_zoom_reset` | `image_viewer.zoom_reset` |
| `image_next` | `image_viewer.next` |
| `image_prev` | `image_viewer.prev` |
| `image_scroll_up` | `image_viewer.pan_up` |
| `image_scroll_down` | `image_viewer.pan_down` |
| `image_scroll_left` | `image_viewer.pan_left` |
| `image_scroll_right` | `image_viewer.pan_right` |
