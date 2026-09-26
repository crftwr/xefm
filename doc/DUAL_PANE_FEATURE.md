# Dual-Pane File Management

XeFM shows two directories side by side, which makes copying, moving, and
comparing between them far quicker than in a single-pane manager. One pane is
**active** (highlighted, with the cursor); the other is inactive. Press **Tab**
to switch which is active.

Each pane keeps its own current directory, cursor position, selection, sort
mode, filter, and history — they are fully independent.

## Actions

Press `?` in XeFM for the keys these are on — the help is built from your own
`KEY_BINDINGS`, so it is always the truth for your config.

| Action | What it does |
|--------|--------------|
| `switch_pane` | Switch active pane |
| `sync_current_to_other` | Sync current pane's directory to the other pane |
| `sync_other_to_current` | Sync other pane's directory to the current pane |
| `copy_files` | Copy selected files to the other pane's directory |
| `move_files` | Move selected files to the other pane's directory |
| `compare_selection` | Compare files/directories between panes |
| `adjust_pane_left` | Move the pane boundary left (left pane smaller) |
| `adjust_pane_right` | Move the pane boundary right (left pane larger) |

Copy/move always target the *other* pane, so the usual workflow is: point each
pane at a directory, select in one, and act.

## Workflow tips

These patterns are what the two panes are really for:

- **Copy/move between directories** — point one pane at the source and the other
  at the destination, select the files, then copy or move them across.
- **Compare two directories** — put both panes on related directories and run
  `compare_selection` to list files unique to each pane (or in both), then
  copy/move to reconcile them.
- **Backup** — source on the left, backup location on the right; select every
  file with `toggle_select_files`, then copy them across.
- **Work in one directory from both sides** — `sync_current_to_other` mirrors the
  current directory into the other pane, handy for selecting from one view while
  scrolling another part of a large directory in the second.
- **Browse an archive** — navigate one pane into an archive (`archive://...`) and
  copy files out to the regular filesystem in the other pane.
- **S3 transfers** — local filesystem in one pane, an S3 bucket (`s3://...`) in
  the other, to copy between local and cloud storage.

## Pane size

Adjust the vertical boundary with **[** (left pane smaller) and **]** (left pane
larger). The ratio is saved and restored on restart. Set the startup default in
`~/.xefm/config.py`:

```python
DEFAULT_LEFT_PANE_RATIO = 0.5  # 50/50 (default); 0.6 = wider left, 0.4 = wider right
```

## State persistence

XeFM remembers each pane's current directory, cursor position, the pane ratio,
and which pane was active between sessions, stored in `~/.xefm/state.json`.

## Command-line arguments

Set the starting directory for each pane when launching XeFM:

```bash
# Left pane only
python3 -m xefm --left /path/to/directory

# Right pane only
python3 -m xefm --right /path/to/directory

# Both panes
python3 -m xefm --left ~/documents --right ~/downloads
```
