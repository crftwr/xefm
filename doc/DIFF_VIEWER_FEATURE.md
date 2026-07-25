# Diff Viewer

XeFM has two built-in diff viewers: a **file diff** that compares two text files
side by side, and a **directory diff** that compares two directory trees
recursively. Both open full-window, without leaving XeFM.

## File diff

### Selecting & launching

Select exactly **two** files, then press `=`. The two files may live in the
same pane or one in each pane — XeFM gathers the selection from both panes:

1. Put the cursor on a file and press `Space` to select it.
2. Select the second file the same way (in either pane).
3. Press `=` to open the side-by-side diff.

Directories in the selection are ignored; if you don't end up with exactly two
files, XeFM tells you (`Select exactly 2 files to compare`). A binary file opens
but shows a `[Binary file — cannot display as text]` placeholder instead of
content.

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
| `F` | Incremental search — then `↑` / `↓` step between matches |
| Drag the centre gutter | Move the divider between the two panes |
| `?` | Key help |
| `Q` / `Esc` | Close the viewer |

The footer shows the total row and change counts and the key hints. Tabs are
expanded to 8-column stops, matching the text viewer.

## Directory diff

Press `Shift+=` to compare the **left pane's current directory** against the
**right pane's current directory**, recursively. No file selection is needed —
just navigate each pane to the directory you want and press the key.

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

### Controls

| Key | Action |
|-----|--------|
| `↑` `↓` · `PgUp`/`PgDn` · `Home`/`End` | Move the cursor |
| `→` / `←` | Expand / collapse a directory |
| `Enter` | Open a directory, or open the per-file diff on a differing file |
| `n` / `N` | Jump to the next / previous difference |
| `Tab` | Switch the active side |
| `[` / `]` | Move the centre split (or drag the gutter) |
| Click / double-click | Focus a side · open a directory / file diff |
| `C` | Copy the focused item to the other side |
| `M` | Move the focused item to the other side |
| `K` / `Del` | Delete the focused item (on the active side) |
| `E` | Merge the two sides in your configured `TEXT_DIFF` tool |
| `r` | Rescan |
| `Q` / `Esc` | Close the viewer |

The copy / move / delete keys mirror the main file manager's and run through the
same file-operation engine, so you can reconcile the two trees in place. `E`
launches the external tool set in `TEXT_DIFF` (for example `vimdiff` in a
terminal, or `code --diff` in the desktop app).

## Notes

- Diffs use Python's `difflib.SequenceMatcher` for a line-by-line comparison.
- Files are read as UTF-8, falling back to Latin-1 then CP1252; binary content
  is detected and shown as a placeholder rather than decoded.
- The `=` and `Shift+=` keys, and the file-operation keys inside the directory
  diff, are all rebindable in your config's `KEY_BINDINGS`.

## See also

- [Text Viewer](TEXT_VIEWER_FEATURE.md) — the single-file viewer the diff reuses
- [File Associations](FILE_ASSOCIATIONS_FEATURE.md) — configuring `TEXT_DIFF` and viewers
- Developer notes: `doc/dev/TEXT_VIEWER_SYSTEM.md`
