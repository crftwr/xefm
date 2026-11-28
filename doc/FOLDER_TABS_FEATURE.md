# Folder Tabs

English \| [日本語](FOLDER_TABS_FEATURE.ja.md)

Each pane can hold several **tabs**, and each tab keeps its own place open.
Use them for the handful of directories a task moves between, or to keep a
search result or an imported list while you browse somewhere else.

| Action | Menu |
|--------|------|
| `new_tab` | Go → New Folder Tab |
| `open_in_new_tab` | Go → Open in New Folder Tab |
| `close_tab` | Go → Close Folder Tab |
| `next_tab` | Go → Next Folder Tab |
| `prev_tab` | Go → Previous Folder Tab |

Keys depend on your keymap preset — see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

All of them act on the **active pane**. The left and right panes have separate
tabs. These are not the window's tabs above the panes - **Files** and each
terminal or AI agent session - which have actions of their own
(`next_screen`, `prev_screen`; see [Terminal](TERMINAL_FEATURE.md)).

## Opening and closing

- **New Folder Tab** opens a tab showing the same place as the current one, with the
  cursor on the same item, and switches to it. On a search result or a list,
  the new tab shows that list's directory, and the results stay in their own
  tab.
- **Open in New Folder Tab** opens the directory under the cursor in a new tab, so
  the current tab stays where it is.
- **Close Folder Tab** closes the current tab and shows the next one. A pane's last
  tab can't be closed.
- **Next / Previous Folder Tab** wrap around at either end.

## The tab strip

Once a pane has more than one tab, a strip appears above its path:

```
 ▸ src ×   ▸ doc ×   ⌕ TODO ×   +
 ~/projects/xefm/doc
```

The current tab is highlighted. Click a tab to switch to it, its `×` (shown
while the pointer is over the tab) to close it, and the `+` after the tabs to open another. Drag a tab along the
strip to move it: a line shows where it will go, and it moves there when you
let go (or use `move_tab_left` and `move_tab_right`). A pane with one tab
shows no strip, so it takes no extra space in a terminal. The strip looks
like the tabs of [terminal and AI agent sessions](TERMINAL_FEATURE.md); in
the desktop app its tabs are a little taller than a line.

Each tab starts with what it shows: `▸` a directory, `▣` an archive, `⌕` a
search (labelled with its query) and `≡` an imported list (`[title]`).
The label is the directory's name. Labels are shortened when they don't all
fit.

## What a tab keeps

Everything the pane shows: the directory, cursor, selection, sort and filter.
Search results, imported lists and branch views are kept as they are, so you
can leave one and come back to it later.

A directory tab is re-read when you switch back to it. Anything that changed
while it was hidden (including changes made from the other pane) shows up
without a flicker.

**History is shared.** **Go → History…** lists the directories you have visited in any tab.

## Between sessions

When you quit, XeFM saves each pane's tabs (directory, sort and filter) and
which tab was current. On the next launch, only the current tab is read. The
others are read the first time you switch to them, so a tab on a remote server
doesn't connect at startup.

A search-result or list tab comes back as its directory. A pane you open on a
directory from the command line starts with that one tab.

## Changing the keys

```python
KEY_BINDINGS['next_tab'] = ['Ctrl-PAGE_DOWN', 'Ctrl-TAB']
KEY_BINDINGS['prev_tab'] = ['Ctrl-PAGE_UP', 'Ctrl-Shift-TAB']
```

Terminals don't send `Ctrl-Tab`, so a binding on it works only in the desktop
app. See [Key Bindings](KEY_BINDINGS_FEATURE.md).
