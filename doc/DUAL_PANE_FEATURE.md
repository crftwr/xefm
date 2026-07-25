# Dual-Pane File Management

XeFM shows two directories side by side, which makes copying, moving, and
comparing between them far quicker than in a single-pane manager. One pane is
**active** (highlighted, with the cursor); the other is inactive. Press **Tab**
to switch which is active.

Each pane keeps its own current directory, cursor position, selection, sort
mode, filter, and history — they are fully independent.

## Key bindings

| Key | Action |
|-----|--------|
| **Tab** | Switch active pane |
| **O** | Sync current pane's directory to the other pane |
| **Shift-O** | Sync other pane's directory to the current pane |
| **C** | Copy selected files to the other pane's directory |
| **M** | Move selected files to the other pane's directory |
| **W** | Compare files/directories between panes |
| **[** | Move the pane boundary left (left pane smaller) |
| **]** | Move the pane boundary right (left pane larger) |

Copy/move always target the *other* pane, so the usual workflow is: point each
pane at a directory, select in one, and act.

## Workflow tips

These patterns are what the two panes are really for:

- **Copy/move between directories** — point one pane at the source and the other
  at the destination, select files with Space, then press **C** (copy) or **M**
  (move).
- **Compare two directories** — put both panes on related directories and press
  **W** to list files unique to each pane (or in both), then copy/move to
  reconcile them.
- **Backup** — source on the left, backup location on the right; press **A** to
  select all files, then **C** to copy them across.
- **Work in one directory from both sides** — press **O** to mirror the current
  directory into the other pane, handy for selecting from one view while
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
