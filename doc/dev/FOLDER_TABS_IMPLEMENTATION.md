# Folder Tabs — Implementation

[#563](https://github.com/crftwr/xefm/issues/563), from discussion
[#546](https://github.com/crftwr/xefm/discussions/546). User-facing behavior is
in [`doc/FOLDER_TABS_FEATURE.md`](../FOLDER_TABS_FEATURE.md).

## The model: a tab is a pane

`PaneManager` holds `tabs = {"left": [pane, …], "right": [pane, …]}` and
`tab_index`. Every tab is a complete pane dict, exactly what a pane was
before. `left_pane` / `right_pane` are now **properties that return the side's
current tab**, with setters that replace it.

That is why the feature touches so little. Every one of the app's many
`self.pane(name)`, `self.pm.left_pane` and `active_pane()` reads goes on
meaning "the pane on screen", and switching a tab changes which dict that is.
Everything a pane already held — cursor, selection, sort, filter, `virtual` —
is per tab automatically.

| Piece | Where |
|---|---|
| Tabs, current index, `new_pane`, `open_tab`, `close_tab`, `select_tab`, `side_of`, `is_shown` | `xefm/pane_manager.py` |
| Actions | `XeFMApp.new_tab`, `open_in_new_tab`, `close_tab`, `next_tab`, `prev_tab`, `select_tab` |
| Putting a tab on screen | `XeFMApp._show_tab` |
| Not listing a hidden tab | `XeFMApp._hold_if_hidden`, called first by `_relist`, `_resort`, `_list_virtual` |
| Strip and click | `PaneHeader._draw_tabs` (drawn by `xefm/tab_strip.py`), `PaneHeader.handle_event`, `PaneHeader.measure` |
| Label | `_tab_label` (module level in `xefm/app.py`) |
| Persistence | `XeFMApp._save_tabs`, `_restore_tabs`; state keys `tabs.left`, `tabs.right` |

## What had to change because a side's pane can change

**Listing generations are global.** A listing result is
`(side, gen, result, …)` and lands on `self.pane(side)` if `gen` matches that
dict's `_load_gen`. With per-pane counters, tab B could have reached the
number that tab A's in-flight listing carries. Switching from A to B
mid-listing would then install A's directory into B. `_LOAD_GENS` is one
`itertools.count` shared by `_list_pane`, `_list_virtual` and `_resort`, so a
generation names exactly one listing of one dict, and a result for a tab no
longer shown is dropped.

**A hidden tab is not listed.** `_list_pane` lists by side, so asking it to
re-list a hidden tab would re-list the shown one. `_relist`, `_resort` and
`_list_virtual` start with `_hold_if_hidden(pane)`. For a hidden tab, it marks
`_stale` and returns. Callers that hold a pane dict across an asynchronous
step (a file operation's completion re-listing "the" pane) are therefore
harmless.

**`_pane_name_of` searches the tabs** (`PaneManager.side_of`). It used to
answer "right" for any dict that wasn't `left_pane`, which is wrong for a
hidden left tab.

**The view is rebound.** `FilePane.pane` is the dict it draws. `_show_tab`
assigns it.

File monitoring needed no change. `_sync_monitored_dirs` already re-points
each side's watcher at `self.pane(side)["path"]` on every tick.

## `_show_tab`

- **A directory tab already listed**: `_list_pane(side, keep_visible=True)`
  with the cursor anchor. Its directory went unwatched while hidden, and an
  operation in the other pane may have changed it. `keep_visible` keeps the
  rows up during the re-read, and drops the result when nothing changed.
- **A tab never listed** (new, or restored from the last session):
  `_refresh`, like a navigation, landing on `focus` (New Tab's cursor row) or
  the remembered cursor.
- **A virtual tab**: re-listed only when `_stale` or still `_load_pending`.
  Re-probing a large or remote list on every switch would cost round trips to
  learn that nothing changed.

The outgoing tab needs nothing done to it. A listing it had in flight is
dropped when it lands (its generation no longer matches the shown dict), and
`_load_pending` stays set, so `_show_tab` re-reads it on the way back in.

## The strip

`PaneHeader.measure` adds a tab's height (`tab_strip.tab_height`: one row on
a grid, 1.6 in the desktop app, #1019) when the side has more than one tab,
so a single-tab pane (the TUI's usual case) costs nothing. Since #1019 each
chip is the screen strip's: the kind's icon (`_tab_parts`), the label, `×`
(`close_tab_at`, which closes a tab out of view without showing it), and a
`+` chip after them (`new_tab` on that side). The header is placed
with `size="content"`, and the layout measures it each frame, so opening the
second tab grows the bar with no extra plumbing. Labels get their natural
width, and an equal share each when they don't all fit. The drawing is
`xefm.tab_strip.TabStrip` (shared with the screen strip since #1019), which
records the row and each tab's span for `handle_event`'s click
(`PaneHeader._strip.hit`).

## Persistence

`_save_tabs` writes `{"active": i, "tabs": [{path, sort_mode, sort_reverse,
filter_pattern}, …]}` per side. The current tab is also still saved through
`save_pane_state` as before, and `_restore_one_pane` restores it first.
`_restore_tabs` then builds the other tabs around it **without reading
anything**: no `exists()`, no listing. They are listed by `_show_tab` the
first time they are shown. A missing directory then fails the way any listing
does. A side given a directory on the command line skips the restore.

## Keys

`T` (a bare letter nothing used), `Shift-T`, `Ctrl-W`, and
`Ctrl-PAGE_DOWN` / `Ctrl-PAGE_UP`. Next and previous are not on `Ctrl-TAB`
because a terminal never delivers it (see KEY_BINDINGS_FEATURE.md, "What a
terminal can carry"). `Ctrl-T`, the conventional new-tab chord, is already the
command palette.

## Not done (from #546)

Locked tabs, per-tab history, "open in new tab" variants of favorites /
history / Jump, a tab context menu, dragging tabs, and restoring a virtual tab
as itself.

## Tests

`test/test_folder_tabs.py`, headless on the memory backend. It covers New Tab
(same place and cursor, view rebound), each tab keeping its place, selection
per tab, Open in New Tab (and its refusal on a file), close and the last tab,
per-pane tabs, wrapping, a virtual tab kept as it was, a listing started for
one tab never landing on another, re-reading a hidden directory tab,
`_hold_if_hidden`, `side_of` for a hidden tab, the strip appearing only with
two tabs, a click selecting a tab, labels, restoring tabs unread except the
current one, and a command-line directory opening alone.

`test/test_xefm_app_async_listing.py`'s stub `PaneManager` gained `side_of`
and `is_shown`.
