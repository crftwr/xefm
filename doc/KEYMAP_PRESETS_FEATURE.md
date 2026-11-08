# Keymap Presets

English \| [日本語](KEYMAP_PRESETS_FEATURE.ja.md)

XeFM has four complete keymaps, called **presets**. None is the default:
the first time XeFM starts, it asks which one you want.

| Preset | Bare letters | Commands are on |
|--------|--------------|-----------------|
| **AFX style** | run commands | letters (`C`, `M`, `K`, `V`, …) |
| **Orthodox** | search for a file | function keys (`F3`, `F5`, `F8`, …) |
| **OS native** | search for a file | Finder's or Explorer's keys (`Cmd`/`Ctrl`-`C`, `F2`, `Delete`, …) |
| **Vim style** | run commands | Vim-style keys (`hjkl`, `gg`, `yy`, `dd`, `/`, …) |

**Tools → Advanced → Keymap…** switches at any time. It opens the same dialog
as the first launch, with the current preset marked and a Cancel. The change
applies at once: the help
dialog (`F1`), the menus and the status bar show the new keys, and XeFM
remembers your choice for later sessions.

## The first launch

When no preset has been chosen yet, XeFM starts with a **Keymap** dialog
with one button per preset. That includes the first start after updating from
a version without presets. The dialog has no Cancel, and `Esc` does not close
it: choose one to go on. You can switch later from Tools → Advanced → Keymap….

If you are updating and want the keys you have been using, choose **AFX
style**. Your `config.py` may hold a full copy of the old keymap. See
[A config.py from an earlier XeFM](#a-configpy-from-an-earlier-xefm) before
choosing another preset.

## AFX style

One letter runs one command, which is the style of the Japanese single-key
filers: the X68000 file managers, then AFX (あふ) on Windows, then cfiler.
XeFM follows that style rather than copying any one of them key for key, so
details differ from AFX. Deleting, for example, is `K`.

Copying and moving to the other pane, deleting and creating an archive act
only on marked items; with nothing marked, the same `M` makes a new folder
instead. Every key is in the [table below](#every-key-side-by-side).

## Orthodox

The layout shared by the classic two-pane file managers. No letter runs a
command. Typing a letter or digit opens [incremental search](XEFM_USER_GUIDE.md)
with that character, so `r` `e` `p` jumps to `report.txt`. It closes the way
those file managers' quick search does:

- `↑` / `↓` jump to the previous / next match, and `Backspace` removes a
  letter.
- `Esc` closes the search and leaves the cursor on the match.
- **Any other key closes the search and does its usual job.** `Enter` opens
  the match, `F5` copies it, `F3` views it, and so on, with no extra key press
  to leave the search first.
- There is no timeout. The search stays open until you press a key that
  closes it.

Matching is the same as for any incremental search. What you type can appear
anywhere in the name, and romaji finds Japanese names. When you open the
search with the I-Search key, it keeps its own keys under every preset: it
lets you mark matches as you go, and stays open until Enter or Esc.

The keys follow Total Commander's defaults, wherever XeFM has the same
command.

`F5`, `F6` and `F8` act on the marked items, or on the item under the cursor
when nothing is marked.

Every key is in the [table below](#every-key-side-by-side). A command Total
Commander has no key for has none here either (a — in the Orthodox column). It is still in the
command palette (`Ctrl-Shift-P`), and most are in the menus too. To put one on
a key, bind it in `KEY_BINDINGS`.

Function keys and modified function keys have terminal sequences, so the
layout works in a terminal as well as in the desktop app. A terminal may still
keep some of them. On macOS, Terminal.app sends `Alt-<key>` only with **Use
Option as Meta key** turned on, and a laptop keyboard may need `fn` for the
function keys. If one does nothing, rebind it.

`Ctrl-M` for `rename` works in the desktop app, and on Windows also in Windows
Terminal and the classic console window. Other terminals send `Ctrl-M` as
`Enter`, so there use `Shift-F6`.

## OS native

The keys Finder uses on macOS and Explorer uses on Windows. Use it if you
come to XeFM from those rather than from another file manager. As in
Orthodox, no letter runs a command: typing a letter searches, which is how
both Finder and Explorer select a file by name.

Finder and Explorer have nothing for the two-pane operations, so they use
the function keys every two-pane file manager uses: `F3` view, `F4` edit,
`F5` copy and `F6` move to the other pane, `F8` delete. On macOS, `Enter`
opens, as in every other preset, rather than renaming as in Finder.

**In a terminal.** The preset you choose applies to both the desktop app and
the terminal. A terminal cannot send `Command`, and cannot tell
`Ctrl-Shift-N` from `Ctrl-N`, so there the preset uses stand-ins for those
keys. In the [table below](#every-key-side-by-side), the first line of an OS
native cell is the terminal's keys, and a line headed *macOS app* or *Windows app* gives that
desktop app's keys where they differ. Everything else is the same.

## Vim style

Vim-style keys, as Vim-like file managers use them: `hjkl` to move, two-key
commands such as `gg`, `yy` and `dd`, and `/` to search. Letters
run commands, as in AFX style, and typing a letter never searches.

Every key is in the [table below](#every-key-side-by-side).

`F3`–`F8` follow the two-pane file managers' function keys. The text viewer moves the same way: `j` / `k` / `h` / `l`,
`gg` / `G`, `Ctrl-F` / `Ctrl-B` (and `Ctrl-D` / `Ctrl-U`, `Space`) by the page,
`/` to search, and `q` or `ZZ` to close it.

The two-key commands are [key sequences](KEY_BINDINGS_FEATURE.md#key-sequences).
While one is half typed, the status bar shows the first key (`g …`); `Esc`
drops it. None of the first keys runs anything on its own, so nothing waits
for `KEY_SEQUENCE_TIMEOUT`.

Where it differs from Vim and Vim-like file managers:

- `v` does not start a visual mode. It marks the range from the nearest
  marked item to the cursor, so mark the start with `t`, move, and press `v`.
- `dd` moves to the system Trash, and `p` pastes what `yy` copied or `x`
  cut. There is no `P` that moves what was yanked: cut with `x`, then `p`.
- `q` alone does nothing in the file list; `ZZ` quits. In the text viewer it
  closes the viewer.
- `/` is XeFM's incremental search, not a regular expression, and it does not
  mark its matches.

## Every key, side by side

Every key each preset binds, read from XeFM's own keymap tables. The first
column is the action's name, as `KEY_BINDINGS` and the command palette use it.
An action with no key in any preset — choosing the next theme, for one — is
not listed: find it in the menus or the command palette, or give it a key in
`KEY_BINDINGS`. In XeFM, `F1` shows the keys you actually have, with your own
`KEY_BINDINGS` applied.

- **—** means that preset has no key for the action.
- A line headed *macOS app* or *Windows app* gives the keys in that desktop app
  where they differ from a terminal's.
- In the AFX style, Orthodox and OS native columns a letter is written as the
  help dialog writes it: `C` is the C key and `Shift-C` the shifted one. The
  Vim style column writes keys as Vim does: `c` is the C key, `G` is
  `Shift-G`, and `gg` is two presses.
- *(only with items marked)* and *(only with nothing marked)* are AFX style's
  selection conditions: `M` moves marked items, or makes a new folder when
  nothing is marked.

### The file list

| Action name | What it does | AFX style | Orthodox | OS native | Vim style |
|---|---|---|---|---|---|
| **Moving the cursor** | | | | | |
| `cursor_up` | Move the cursor up one item | `↑` | `↑` | `↑` | `k`, `↑` |
| `cursor_down` | Move the cursor down one item | `↓` | `↓` | `↓` | `j`, `↓` |
| `page_up` | Move the cursor up one page | `PgUp` | `PgUp` | `PgUp` | `Ctrl-B`, `PgUp` |
| `page_down` | Move the cursor down one page | `PgDn` | `PgDn` | `PgDn` | `Ctrl-F`, `PgDn` |
| `half_page_up` | Move the cursor up half a screen | — | — | — | `Ctrl-U` |
| `half_page_down` | Move the cursor down half a screen | — | — | — | `Ctrl-D` |
| `cursor_top` | Move the cursor to the first item | `Ctrl-Home` | `Home`, `Ctrl-Home` | `Home`, `Ctrl-Home` | `gg`, `Home`, `Ctrl-Home` |
| `cursor_bottom` | Move the cursor to the last item | `Ctrl-End` | `End`, `Ctrl-End` | `End`, `Ctrl-End` | `G`, `End`, `Ctrl-End` |
| `switch_pane` | Switch between the left and right panes | `Tab` | `Tab` | `Tab` | `Tab`, `Space` |
| `nav_left` | Focus the left pane, or go to the parent | `←` | `←` | `←` | `←` |
| `nav_right` | Focus the right pane, or go to the parent | `→` | `→` | `→` | `→` |
| **Folders and places** | | | | | |
| `open_item` | Open the file, or enter the directory | `Enter` | `Enter`, `Ctrl-PgDn` | `Enter`<br>macOS app: `Enter`, `Cmd-↓` | `l`, `gl`, `Enter` |
| `go_parent` | Go to the parent directory | `Backspace` | `Backspace`, `Ctrl-PgUp` | `Backspace`, `Alt-↑`<br>macOS app: `Cmd-↑`, `Backspace`, `Opt-↑` | `h`, `gh`, `Backspace` |
| `go_root` | Go to the root of the current drive or location | `\` | `Ctrl-\` | `\` | `\` |
| `go_back` | Go back to the directory shown before | `Alt-←`<br>macOS app: `Cmd-[`, `Opt-←` | `Alt-←` | `Alt-←`<br>macOS app: `Cmd-[`, `Opt-←` | `Ctrl-O`, `Alt-←` |
| `go_forward` | Go forward again after going back | `Alt-→`<br>macOS app: `Cmd-]`, `Opt-→` | `Alt-→` | `Alt-→`<br>macOS app: `Cmd-]`, `Opt-→` | `Alt-→` |
| `history` | Go to a recently visited directory | `H` | `Alt-↓` | `Alt-↓` | — |
| `jump_to_path` | Jump to a typed path | `Shift-J` | — | `Ctrl-L`, `Alt-D`<br>macOS app: `Cmd-Shift-G`, `Ctrl-L` | `gp` |
| `favorites` | Go to a favorite directory or file | `J` | `Ctrl-D` | — | `'` |
| `add_favorite` | Add a favorite, or tag the selection | `B` | — | — | — |
| `drives` | Show drives and volumes | `D` | `Alt-F1`, `Alt-F2` | — | — |
| `connect_server` | Connect to a network server | `Shift-D` | `Ctrl-F`, `Ctrl-N` | — | — |
| `open_with_os` | Open with the OS default application | `Ctrl-O`<br>macOS app: `Cmd-Enter`, `Ctrl-O`<br>Windows app: `Ctrl-Enter`, `Ctrl-O` | `Ctrl-O`<br>macOS app: `Cmd-Enter`, `Ctrl-O`<br>Windows app: `Ctrl-Enter`, `Ctrl-O` | `Ctrl-O`<br>macOS app: `Cmd-Enter`, `Ctrl-O`<br>Windows app: `Ctrl-Enter`, `Ctrl-O` | `gx` |
| `reveal_in_os` | Reveal in the OS file manager | `Ctrl-R` | — | — | `Ctrl-R` |
| `sync_current_to_other` | Go to the other pane's directory | `O` | — | — | — |
| `sync_other_to_current` | Send this directory to the other pane | `Shift-O` | — | — | — |
| **Selecting** | | | | | |
| `toggle_select_down` | Toggle selection and move down | `Space` | `Insert`, `Space` | `Space`, `Insert`<br>macOS app: `Ctrl-Space`, `Insert` | `Insert` |
| `toggle_select_in_place` | Toggle selection without moving the cursor | — | — | — | `t` |
| `select_range` | Select from the nearest selected item to the cursor | `Shift-Space` | `Shift-Space` | `Shift-Space` | `v`, `Shift-Space` |
| `select_all` | Select every item | `Home` | `Ctrl-A` | `Ctrl-A`<br>macOS app: `Cmd-A`, `Ctrl-A` | — |
| `unselect_all` | Clear the selection | `End` | `Ctrl--` | — | `Esc` |
| `toggle_select_files` | Toggle selection of every file | `A` | `*` | — | — |
| `toggle_select_items` | Toggle selection of every item | `Shift-A` | — | — | — |
| `select_by_pattern` | Select the files matching a pattern | `'` | `+` | `'` | — |
| `unselect_by_pattern` | Unselect the files matching a pattern | `"` | `-` | `"` | `"` |
| `select_same_extension` | Select every file with the cursor file's extension | — | `Alt-+` | — | — |
| `compare_selection` | Select by comparison with the other pane | `W` | `Shift-F2` | — | — |
| `cursor_next_selected` | Jump to the next selected item | `Ctrl-↓` | — | `Ctrl-↓` | `Ctrl-↓` |
| `cursor_prev_selected` | Jump to the previous selected item | `Ctrl-↑` | — | `Ctrl-↑` | `Ctrl-↑` |
| **File operations** | | | | | |
| `copy_files` | Copy the selection to the other pane | `C` (only with items marked) | `F5` | `F5` | `F5` |
| `move_files` | Move the selection to the other pane | `M` (only with items marked) | `F6` | `F6` | `F6` |
| `copy_files_to` | Copy the selection to a directory typed in a prompt | `Shift-C` (only with items marked) | — | — | — |
| `move_files_to` | Move the selection to a directory typed in a prompt | `Shift-M` (only with items marked) | — | — | — |
| `duplicate_files` | Duplicate the selection in place | — | `Shift-F5` | — | — |
| `delete_files` | Move the selection to the Trash (or delete it where there is none) | `K`, `Del` (only with items marked) | `F8`, `Del` | `Del`, `F8`<br>macOS app: `Cmd-Backspace`, `Del`, `F8` | `dd`, `Del`, `F8` |
| `delete_permanently` | Delete the selection for good, skipping the Trash | `Shift-K`, `Shift-Del` (only with items marked) | `Shift-F8`, `Shift-Del` | `Shift-Del`, `Shift-F8`<br>macOS app: `Cmd-Opt-Backspace`, `Shift-Del`, `Shift-F8` | `DD`, `Shift-Del`, `Shift-F8` |
| `rename` | Rename the focused item, or batch-rename the selection | `R` | `Shift-F6`, `Ctrl-M` | `F2` | `cw` |
| `rename_in_editor` | Rename the selection by editing its names in TEXT_EDITOR | `Shift-R` | — | — | — |
| `create_file` | Create a new file | `Shift-E` | `Shift-F4` | — | — |
| `create_directory` | Create a new directory | `M` (only with nothing marked) | `F7` | `F7`<br>macOS app: `Cmd-Shift-N`, `F7`<br>Windows app: `Ctrl-Shift-N`, `F7` | `F7` |
| `create_archive` | Create an archive from the selection | `P` (only with items marked) | `Alt-F5` | — | — |
| `extract_archive` | Extract the selected archive(s) | `U` | `Alt-F9`, `Alt-F6` | — | — |
| **File clipboard and copying names** | | | | | |
| `clipboard_copy` | Copy files to the clipboard | `Ctrl-C`, `Y`<br>macOS app: `Cmd-C`, `Ctrl-C`, `Y` | `Ctrl-C` | `Ctrl-C`<br>macOS app: `Cmd-C`, `Ctrl-C` | `yy`, `Ctrl-C` |
| `clipboard_cut` | Cut files to the clipboard | `Ctrl-X`, `Shift-Y`<br>macOS app: `Cmd-X`, `Ctrl-X`, `Shift-Y` | `Ctrl-X` | `Ctrl-X`<br>macOS app: `Cmd-X`, `Ctrl-X` | `x`, `Ctrl-X` |
| `clipboard_paste` | Paste the clipboard into this folder | `Ctrl-V`, `G`<br>macOS app: `Cmd-V`, `Ctrl-V`, `G` | `Ctrl-V` | `Ctrl-V`<br>macOS app: `Cmd-V`, `Ctrl-V` | `p`, `Ctrl-V` |
| `copy_names` | Copy the file name(s) to the clipboard | `Ctrl-N` | — | `Ctrl-N` | `Ctrl-N` |
| `copy_paths` | Copy the full path(s) to the clipboard | `Ctrl-P` | `Ctrl-P` | `Ctrl-P`<br>macOS app: `Cmd-Opt-C`, `Ctrl-P`<br>Windows app: `Ctrl-Shift-C`, `Ctrl-P` | `Ctrl-P` |
| **Viewing, editing and comparing** | | | | | |
| `view_file` | View the focused file in the built-in viewer | `V` | `F3` | `F3` | `e`, `F3` |
| `quick_view` | Preview the item under the cursor in the other pane | `Shift-V` | `Ctrl-Q` | `Alt-P`<br>macOS app: `Space`, `Opt-P` | `w` |
| `edit_file` | Edit in the configured text editor | `E` | `F4` | `F4` | `F4` |
| `file_details` | Show details for the focused item | `I` | `Alt-Enter` | `Alt-I`<br>macOS app: `Cmd-I`, `Opt-I`<br>Windows app: `Alt-Enter`, `Alt-I` | `Ctrl-G` |
| `diff_files` | Compare two files side by side | `=` | `=` | `=` | — |
| `diff_directories` | Compare two directories recursively | `Shift-=` | — | `Shift-=` | `Shift-=` |
| **Search, filter and sort** | | | | | |
| `isearch` | Incremental search | `F` | — | — | `/` |
| `search_next` | Go to the next match of the last incremental search | — | — | — | `n` |
| `search_prev` | Go to the previous match of the last incremental search | — | — | — | `N` |
| `find_files` | Search for files by name | `Shift-F` | `Alt-F7` | `Ctrl-F`<br>macOS app: `Cmd-F`, `Ctrl-F` | — |
| `find_in_files` | Search inside files | `Shift-G` | — | — | — |
| `index_search` | Search the OS index under this folder | `Ctrl-F` | — | — | — |
| `filter` | Filter the listing by a filename pattern | `;` | `Ctrl-S` | `;` | `=` |
| `clear_filter` | Clear the filename filter | `:` | `Ctrl-F10` | `:` | `zr` |
| `flat_view` | Show every file below this directory as one list | `Shift-B` | `Ctrl-B` | — | — |
| `toggle_hidden` | Show or hide hidden files | `.` | `.` | `.`<br>macOS app: `Cmd-Shift-.`, `.` | `za` |
| `increase_font_size` | Make the text larger until XeFM quits | macOS app: `Cmd-+`, `Cmd-=`<br>Windows app: `Ctrl-+`, `Ctrl-=` | macOS app: `Cmd-+`, `Cmd-=` | macOS app: `Cmd-+`, `Cmd-=`<br>Windows app: `Ctrl-+`, `Ctrl-=` | macOS app: `Cmd-+`, `Cmd-=`<br>Windows app: `Ctrl-+`, `Ctrl-=` |
| `decrease_font_size` | Make the text smaller until XeFM quits | macOS app: `Cmd--`<br>Windows app: `Ctrl--` | macOS app: `Cmd--` | macOS app: `Cmd--`<br>Windows app: `Ctrl--` | macOS app: `Cmd--`<br>Windows app: `Ctrl--` |
| `reset_font_size` | Put the text back to `FONT_SIZE` | macOS app: `Cmd-0`<br>Windows app: `Ctrl-0` | macOS app: `Cmd-0`<br>Windows app: `Ctrl-0` | macOS app: `Cmd-0`<br>Windows app: `Ctrl-0` | macOS app: `Cmd-0`<br>Windows app: `Ctrl-0` |
| `sort` | Open the sort dialog | `S` | — | — | `S` |
| `quick_sort_name` | Sort by name | `1` | `Ctrl-F3` | — | — |
| `quick_sort_ext` | Sort by extension | `2` | `Ctrl-F4` | — | — |
| `quick_sort_size` | Sort by size | `3` | `Ctrl-F6` | — | — |
| `quick_sort_date` | Sort by modification date | `4` | `Ctrl-F5` | — | — |
| **Tabs, panes and the log** | | | | | |
| `new_tab` | Open a new tab in this pane, at the same place | `T` | `Ctrl-T` | `Ctrl-T`<br>macOS app: `Cmd-T`, `Ctrl-T` | — |
| `open_in_new_tab` | Open the directory under the cursor in a new tab | `Shift-T` | `Ctrl-↑` | — | — |
| `close_tab` | Close this pane's current tab | `Ctrl-W` | `Ctrl-W` | `Ctrl-W`<br>macOS app: `Cmd-W`, `Ctrl-W` | `Ctrl-W` |
| `next_tab` | Show this pane's next tab | `Ctrl-PgDn` | `Ctrl-Tab` | `Ctrl-PgDn` | `Ctrl-PgDn` |
| `prev_tab` | Show this pane's previous tab | `Ctrl-PgUp` | `Ctrl-Shift-Tab` | `Ctrl-PgUp` | `Ctrl-PgUp` |
| `adjust_pane_left` | Make the left pane smaller | `[` | `[` | `[` | `[` |
| `adjust_pane_right` | Make the left pane larger | `]` | `]` | `]` | `]` |
| `reset_pane_boundary` | Reset the pane split to 50 / 50 | `-` | — | `-` | `-` |
| `adjust_log_up` | Make the log pane larger | `{` | `{` | `{` | `{` |
| `adjust_log_down` | Make the log pane smaller | `}` | `}` | `}` | `}` |
| `reset_log_height` | Reset the log pane height | `_` | — | `_` | `_` |
| `scroll_log_up` | Scroll the log up one line | `Shift-↑` | `Shift-↑` | `Shift-↑` | `Shift-↑` |
| `scroll_log_down` | Scroll the log down one line | `Shift-↓` | `Shift-↓` | `Shift-↓` | `Shift-↓` |
| `scroll_log_page_up` | Scroll the log up one page | `Shift-←` | `Shift-←` | `Shift-←` | `Shift-←` |
| `scroll_log_page_down` | Scroll the log down one page | `Shift-→` | `Shift-→` | `Shift-→` | `Shift-→` |
| **Menus, tools and quitting** | | | | | |
| `help` | Show the key bindings for what is on screen | `F1` | `F1` | `F1` | `F1` |
| `command_palette` | Search every action by name and run it | `Ctrl-T` | `Ctrl-Shift-P` | `Ctrl-K`<br>macOS app: `Cmd-Shift-P`, `Ctrl-K`<br>Windows app: `Ctrl-Shift-P`, `Ctrl-K` | `:`, `Ctrl-T` |
| `menu` | Open the menu bar | `F10`, `Alt` | `F9`, `F10`, `Alt` | `F10`, `Alt` | `F10`, `Alt` |
| `context_menu` | Open the context menu for the item under the cursor | `/`, `Apps` | `Shift-F10`, `Apps` | `Shift-F10`, `Apps` | `Apps`, `Shift-F10` |
| `context_menu_dir` | Open the context menu for the current directory | `?`, `Shift-Apps` | `?`, `Shift-Apps` | `?`, `Shift-Apps` | `?`, `Shift-Apps` |
| `programs` | Run an external program | `X` | — | — | — |
| `subshell` | Open a subshell in this directory | `Shift-X` | — | — | `s` |
| `jobs` | List background jobs | `Ctrl-G` | `Ctrl-G` | `Ctrl-G` | — |
| `reread` | Re-read both panes' directories | — | `F2`, `Ctrl-R` | `Ctrl-R` | `Ctrl-L` |
| `redraw` | Redraw the screen | `F5` | — | — | — |
| `quit` | Quit XeFM — or close the open viewer | `Q` | `Alt-F4` | `Ctrl-Q` | `ZZ`, `ZQ` |
| `quit_app` | Quit XeFM from anywhere, asking first only while a task is running | macOS app: `Cmd-Q`<br>Windows app: `Alt-F4` | macOS app: `Cmd-Q`<br>Windows app: `Alt-F4` | macOS app: `Cmd-Q`<br>Windows app: `Alt-F4` | macOS app: `Cmd-Q`<br>Windows app: `Alt-F4` |

### Viewers and dialogs

These keys are the same under every preset unless a cell says otherwise. In
every viewer `Esc` closes it, and `quit`, `help`, `isearch` and `edit_file`
work there on their keys from the file list table. Vim style also closes the
text viewer with `q`.

Orthodox and OS native give `isearch` no key in the file list, since typing
a letter searches there. In the text viewer and the file diff viewer they use
the search keys of the viewers they model instead: Total Commander's Lister
for Orthodox, and the platform's own find keys for OS native. Find next and
find previous also work while the search bar is open; after it has closed,
they open it again on the last search and move to the next or previous match.

**Text viewer**

| Action name | What it does | Keys |
|---|---|---|
| `text_viewer.scroll_up` | Scroll up one line | AFX style, Orthodox, OS native: `↑`<br>Vim style: `k`, `↑` |
| `text_viewer.scroll_down` | Scroll down one line | AFX style, Orthodox, OS native: `↓`<br>Vim style: `j`, `↓` |
| `text_viewer.page_up` | Scroll up one page | AFX style, Orthodox, OS native: `PgUp`<br>Vim style: `Ctrl-B`, `Ctrl-U`, `PgUp` |
| `text_viewer.page_down` | Scroll down one page | AFX style, Orthodox, OS native: `PgDn`<br>Vim style: `Ctrl-F`, `Ctrl-D`, `PgDn`, `Space` |
| `text_viewer.scroll_top` | Go to the top | AFX style, Orthodox, OS native: `Home`<br>Vim style: `gg`, `Home` |
| `text_viewer.scroll_bottom` | Go to the bottom | AFX style, Orthodox, OS native: `End`<br>Vim style: `G`, `End` |
| `text_viewer.scroll_left` | Scroll left (unwrapped only) | AFX style, Orthodox, OS native: `←`<br>Vim style: `h`, `←` |
| `text_viewer.scroll_right` | Scroll right (unwrapped only) | AFX style, Orthodox, OS native: `→`<br>Vim style: `l`, `→` |
| `toggle_wrap` | Toggle line wrapping | `W` |
| `toggle_view_mode` | Toggle the rendered / raw view | `M` |
| `change_encoding` | Choose the text encoding | `Shift-E` |
| `isearch` | Incremental search | AFX style: `F`<br>Orthodox: `F7`<br>OS native: `Ctrl-F` (macOS app: `Cmd-F`, `Ctrl-F`)<br>Vim style: `/` |
| `text_viewer.search_next` | Find the next match of the last search | AFX style, Vim style: —<br>Orthodox: `F3`<br>OS native: `F3` (macOS app: `Cmd-G`, `F3`) |
| `text_viewer.search_prev` | Find the previous match of the last search | AFX style, Vim style: —<br>Orthodox: `Shift-F3`<br>OS native: `Shift-F3` (macOS app: `Cmd-Shift-G`, `Shift-F3`) |

**Image viewer**

| Action name | What it does | Keys |
|---|---|---|
| `image_viewer.next` | Next image in the file list | `↓` |
| `image_viewer.prev` | Previous image in the file list | `↑` |
| `image_viewer.first` | First image in the file list | `Home` |
| `image_viewer.last` | Last image in the file list | `End` |
| `image_viewer.zoom_in` | Zoom in | `+`, `=` |
| `image_viewer.zoom_out` | Zoom out | `-`, `_` |
| `image_viewer.zoom_reset` | Fit the whole image to the window | `0` |
| `image_viewer.pan_up` | Pan up (while zoomed in) | `Shift-↑` |
| `image_viewer.pan_down` | Pan down (while zoomed in) | `Shift-↓` |
| `image_viewer.pan_left` | Pan left (while zoomed in) | `Shift-←` |
| `image_viewer.pan_right` | Pan right (while zoomed in) | `Shift-→` |

**File diff viewer**

| Action name | What it does | Keys |
|---|---|---|
| `file_diff.next_block` | Next diff block | `n` |
| `file_diff.prev_block` | Previous diff block | `Shift-N` |
| `file_diff.scroll_up` | Scroll up one line | `↑` |
| `file_diff.scroll_down` | Scroll down one line | `↓` |
| `file_diff.page_up` | Scroll up one page | `PgUp` |
| `file_diff.page_down` | Scroll down one page | `PgDn` |
| `file_diff.scroll_top` | Go to the top | `Home` |
| `file_diff.scroll_bottom` | Go to the bottom | `End` |
| `file_diff.scroll_left` | Scroll left | `←` |
| `file_diff.scroll_right` | Scroll right | `→` |
| `isearch` | Incremental search | AFX style: `F`<br>Orthodox: `F7`<br>OS native: `Ctrl-F` (macOS app: `Cmd-F`, `Ctrl-F`)<br>Vim style: `/` |
| `file_diff.search_next` | Find the next match of the last search | AFX style, Vim style: —<br>Orthodox: `F3`<br>OS native: `F3` (macOS app: `Cmd-G`, `F3`) |
| `file_diff.search_prev` | Find the previous match of the last search | AFX style, Vim style: —<br>Orthodox: `Shift-F3`<br>OS native: `Shift-F3` (macOS app: `Cmd-Shift-G`, `Shift-F3`) |

**Directory diff viewer**

| Action name | What it does | Keys |
|---|---|---|
| `dir_diff.cursor_up` | Move the cursor up | `↑` |
| `dir_diff.cursor_down` | Move the cursor down | `↓` |
| `dir_diff.page_up` | Move the cursor up one page | `PgUp` |
| `dir_diff.page_down` | Move the cursor down one page | `PgDn` |
| `dir_diff.cursor_top` | Go to the first row | `Home` |
| `dir_diff.cursor_bottom` | Go to the last row | `End` |
| `dir_diff.expand` | Expand the focused directory | `→` |
| `dir_diff.collapse` | Collapse it, or go to its parent | `←` |
| `dir_diff.activate` | Expand a directory, or diff a file | `Enter` |
| `dir_diff.switch_side` | Switch the active side | `Tab` |
| `dir_diff.next_change` | Next difference | `n` |
| `dir_diff.prev_change` | Previous difference | `Shift-N` |
| `dir_diff.rescan` | Rescan both trees | `r` |
| `dir_diff.split_left` | Move the centre split left | `[` |
| `dir_diff.split_right` | Move the centre split right | `]` |
| `dir_diff.toggle_identical` | Show or hide the items that are the same on both sides | `d` |
| `dir_diff.sync` | Sync: plan from the active side, or run it | `s` |
| `dir_diff.cycle_sync_action` | Change the focused node's sync action | `Space` |
| `copy_files` | Copy the selection to the other pane | AFX style: `C` (only with items marked)<br>Orthodox, OS native, Vim style: `F5` |
| `move_files` | Move the selection to the other pane | AFX style: `M` (only with items marked)<br>Orthodox, OS native, Vim style: `F6` |
| `delete_files` | Move the selection to the Trash (or delete it where there is none) | AFX style: `K`, `Del` (only with items marked)<br>Orthodox: `F8`, `Del`<br>OS native: `Del`, `F8` (macOS app: `Cmd-Backspace`, `Del`, `F8`)<br>Vim style: `dd`, `Del`, `F8` |
| `view_file` | View the focused file in the built-in viewer | AFX style: `V`<br>Orthodox, OS native: `F3`<br>Vim style: `e`, `F3` |

**Incremental search bar**

| Action name | What it does | Keys |
|---|---|---|
| `isearch.next_match` | Move to the next match | `↓` |
| `isearch.prev_match` | Move to the previous match | `↑` |
| `isearch.toggle_select_down` | Toggle selection and move to the next match | `Ctrl-Space` |
| `isearch.select_matches` | Select every match (again: clear them) | `Ctrl-A` |
| `isearch.accept` | Stop at the current match | `Enter` |
| `isearch.cancel` | Cancel and restore the cursor | `Esc` |

**List dialogs** (Favorites, Drives, History, External Programs, the filter prompt)

| Action name | What it does | Keys |
|---|---|---|
| `remove_list_item` | Remove the highlighted entry from the list | `Shift-Del` |
| `describe_list_item` | Show help for the highlighted entry | `F1` |

**Search dialog** (Search Files, Search Content)

| Action name | What it does | Keys |
|---|---|---|
| `options` | Open the search options | `Ctrl-O`, `F9` |

## Your own key bindings come on top

`KEY_BINDINGS` in `config.py` holds **your changes** to the preset. Every
entry replaces that action's keys, whichever preset is in force. An action
you don't list keeps the preset's keys. That is why the `KEY_BINDINGS` XeFM
writes into a new `config.py` holds only commented-out examples.

A key you bind is also taken off the action the preset had given it, so you
don't have to find that action and empty it as well. `'toggle_color_scheme':
['Shift-T']` is enough on its own; AFX's `Shift-T` (open in a new tab) stops
answering, and the help and the menus stop listing it there.

A key you bind for the file list only stays on a shared action elsewhere.
`'view_file': ['Q']` opens the file with `Q` in the file list, and `Q`
still closes a viewer. A key you bind with a selection requirement leaves
the opposite one alone: `{'keys': ['C'], 'selection': 'none'}` keeps `C`
copying marked files.

```python
KEY_BINDINGS = {
    'reload_config': ['F12'],   # F12 reloads the config, under every preset
    'quit': [],                 # nothing quits by key
}
```

### A config.py from an earlier XeFM

Before the presets, `config.py` held a copy of the whole AFX-style table.
Under AFX style that copy changes nothing. Under another preset, every entry
in it replaces the preset's keys, so `C` still copies instead of searching.
When you switch presets, the log says how many actions your `config.py`
replaces, and names the first few.

To use another preset, delete the entries you did not mean to change. If you
never changed a key, delete them all and leave `KEY_BINDINGS = {}`.

## Choosing it in config.py

```python
KEY_PRESET = 'orthodox'   # or 'afx', 'native', or 'vim'
```

`'default'`, the name this preset had first, still works and means `'afx'`.

A `KEY_PRESET` in `config.py` overrides the menu, and the menu says so if you
try to change it there. It also skips the first-launch question. Leave it as
`None` to let the dialog and the menu decide.

## See also

- [Key Bindings](KEY_BINDINGS_FEATURE.md): changing individual keys
- [Command Palette](COMMAND_PALETTE_FEATURE.md): finding any command and its key
