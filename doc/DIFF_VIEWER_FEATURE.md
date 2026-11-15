# Diff Viewer

English \| [日本語](DIFF_VIEWER_FEATURE.ja.md)

XeFM has two built-in diff viewers: a **file diff** that compares two text files
side by side, and a **directory diff** that compares two directory trees
recursively. Both open full-window, without leaving XeFM.

## File diff

### Selecting & launching

Select exactly **two** files, then use **Select → Compare Selected Files…**
(`diff_files`). The two files may live in the same pane or one in each pane —
XeFM gathers the selection from both panes:

1. Put the cursor on a file and select it (**Select → Toggle Selection**).
2. Select the second file the same way (in either pane).
3. Choose **Select → Compare Selected Files…** to open the side-by-side diff.

Keys depend on your keymap preset — see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

Directories in the selection are ignored; if you don't end up with exactly two
files, XeFM tells you (`Select exactly 2 files to compare`).

### Binary files

When either file is binary (an image, an executable, an archive…), there is no
text to diff. Instead of the diff viewer, `diff_files` compares the two files byte for
byte and tells you the answer in a message box: both sizes, then **Identical**,
**Different (sizes differ)**, or the offset of the first byte that differs.

```
photo.jpg   2,481,152 bytes
photo2.jpg  2,481,152 bytes

Identical
```

Large files, and files on a remote server or inside an archive, are compared
with a progress dialog you can cancel.

### Reading the diff

Each side keeps its own syntax highlighting (when
[Pygments](https://pygments.org/) is installed), and lines carry their original
line numbers. Coloured bands mark what changed, and each band adapts to the
active theme (a darker band on a dark theme, a pastel one on a light theme):

- **Red** — a line present only on the **left** (deleted).
- **Green** — a line present only on the **right** (inserted / added).
- **Amber** — a line **changed on both sides** (replaced). Within such a line,
  the exact characters that differ get a stronger tint of the same hue.
- **Neutral / gray** — filler on the blank side of an insert or delete row, so
  the two sides stay aligned.
- Unchanged lines use the normal text colour.

### Controls

| Key | Action |
|-----|--------|
| `↑` `↓` | Scroll one line |
| `PgUp` / `PgDn` | Scroll one page |
| `Home` / `End` | Jump to the top / bottom |
| `←` `→` | Scroll horizontally |
| `n` / `N` | Jump to the next / previous change block |
| `isearch` | Incremental search — then `↑` / `↓` step between matches |
| Drag the centre gutter | Move the divider between the two panes |
| `F1` | Key help |
| `Esc`, or `quit` | Close the viewer |

`isearch` and `quit` are on the same keys as in the file list, which depend on
your keymap preset; the other keys here are the same in every preset.

The footer shows the total row and change counts and the key hints. Tabs are
expanded to 8-column stops, matching the text viewer.

## Directory diff

Use **Select → Compare Directories…** (`diff_directories`) to compare the
**left pane's current directory** against the **right pane's current
directory**, recursively. No file selection is needed — just navigate each pane
to the directory you want and run it.

Useful for comparing a backup against the live directory, verifying two trees
are in sync, or reviewing what changed after an update or migration.

### Progressive scanning

The viewer scans progressively so it is responsive on large trees:

- The top level of both directories appears at once.
- Deeper directories are scanned by background workers, and **visible or
  expanded** directories are prioritised — what you are looking at fills in
  first.
- Expanding an unscanned directory scans it immediately.
- You can navigate and explore the already-scanned parts while scanning
  continues; the footer shows progress and a completion count.

### Reading the tree

The union of both trees is shown side by side. Directories expand and collapse;
a centre separator glyph between the two columns carries each node's verdict:

- **Only in left** — the item exists only on the left.
- **Only in right** — the item exists only on the right.
- **Content different** — a file present on both sides whose contents differ.
- **Contains difference** — a directory with differing descendants.
- **Identical** — the same on both sides (shown muted).
- **Pending** — not yet scanned or compared.

The row above the footer details the focused item: its size and modification
time on each side, with **newer** after the side that is newer. Times less than
two seconds apart count as the same (FAT/exFAT store times in 2-second steps),
the same rule the copy conflict dialog's **Overwrite older** uses.

### Controls

| Key | Action |
|-----|--------|
| `↑` `↓` · `PgUp`/`PgDn` · `Home`/`End` | Move the cursor |
| `→` / `←` | Expand / collapse a directory |
| `Enter` | Open a directory, or open the per-file diff on a differing file (a binary file reports its byte comparison instead) |
| `n` / `N` | Jump to the next / previous difference |
| `Tab` | Switch the active side |
| `[` / `]` | Move the centre split (or drag the gutter) |
| Click / double-click | Focus a side · open a directory / file diff |
| `copy_files` | Copy the focused item to the other side |
| `move_files` | Move the focused item to the other side |
| `delete_files` | Delete the focused item (on the active side) |
| `edit_files` | Merge the two sides in your configured `TEXT_DIFF` tool |
| `s` | Sync: plan copying from the active side, then press again to run — see [Directory Sync](DIRECTORY_SYNC_FEATURE.md) |
| `d` | Show only the differences, or everything |
| `r` | Rescan |
| `Esc`, or `quit` | Close the viewer |

The rows that name an action (`copy_files`, `move_files`, `delete_files`,
`edit_files`, `quit`) use that action's keys from the file list, so they depend
on your keymap preset — see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).
The other keys are the same in every preset.

The copy / move / delete keys mirror the main file manager's and run through the
same file-operation engine, so you can reconcile the two trees in place.
`edit_files` launches the external tool set in `TEXT_DIFF` (for example `vimdiff` in a
terminal, or `code --diff` in the desktop app).

## Notes

- Diffs use Python's `difflib.SequenceMatcher` for a line-by-line comparison.
- Files are read as UTF-8, falling back to Latin-1 then CP1252. A file is
  treated as binary when its first bytes contain a NUL; XeFM keeps no list of
  binary extensions.
- `edit_files` still launches your `TEXT_DIFF` tool on any pair, so a binary-capable tool
  can be used explicitly.
- The keys of `diff_files` and `diff_directories`, and the file-operation keys
  inside the directory diff, are all rebindable in your config's `KEY_BINDINGS`.

## See also

- [Text Viewer](TEXT_VIEWER_FEATURE.md) — the single-file viewer the diff reuses
- [Directory Sync](DIRECTORY_SYNC_FEATURE.md) — applying a directory diff in bulk
- [File Associations](FILE_ASSOCIATIONS_FEATURE.md) — configuring `TEXT_DIFF` and viewers
- Developer notes: `doc/dev/TEXT_VIEWER_SYSTEM.md`
