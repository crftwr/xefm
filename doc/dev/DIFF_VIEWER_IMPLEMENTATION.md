# Text Diff Viewer Implementation

## Overview

The Text Diff Viewer is a full-window modal side-by-side comparison of two text
files, integrated into XeFM. It is a PuiKit `Widget` (`DiffViewer`, in
`xefm/diff_viewer.py`), pushed over the active panel with
`show_diff_viewer(panel, path1, path2)`.

## Architecture

### Current components (`xefm/diff_viewer.py`)

- **`DiffViewer(Widget)`** — the modal viewer. Holds the shared scroll state
  (`top` / `left` / `_view_h`), the computed diff rows, and the incremental-search
  state; draws the header band, shared vertical scrollbar, and footer chrome.
- **`_DiffPane(Widget)`** — one side (left/old, right/new): its filename header,
  line-number gutter, and scrolling content. Both panes read the parent's shared
  scroll state, so they stay row-aligned and pan together; only the split *width*
  differs. The rows render in a clipped child (`_ScrollBody`) for smooth
  fractional scroll on both axes.
- **`Splitter`** (from PuiKit) — carries the two panes with a draggable divider.
- **`compute_diff(lines1, lines2)`** — a module function (see below) that builds
  the diff model.

The viewer **reuses the text viewer's file machinery** (`xefm.text_viewer`):
`_read_lines` for encoding-detected reading + binary sniffing, and `_highlight`
for pygments syntax colors — so each side keeps its syntax colors with the diff
tint laid over them. There is no separate file-loading or binary-detection code
here.

### Integration with XeFMApp (`xefm/app.py`)

**Method: `diff_files()`** — bound to `=` (the `diff_files` action, `EQUAL` in
`xefm/_config.py`). It collects the selected files from both panes, validates that
exactly two non-directory files are selected, and launches the viewer.

## File Selection Logic

The diff viewer supports three selection patterns:

1. **Both files in the left pane**
2. **Both files in the right pane**
3. **One file per pane**

All three fall out of collecting selected files across *both* panes and requiring
exactly two:

```python
selected = []
for name in ("left", "right"):
    pane = self.pane(name)
    for entry in pane["files"]:
        if str(entry) in pane["selected_files"]:
            selected.append(entry)

files = [e for e in selected if not e.is_dir()]     # files only, not directories

if len(files) != 2:
    self.log_info(f"Select exactly 2 files to compare (selected {len(files)})")
    return

show_diff_viewer(self.panel, files[0], files[1])
```

## Diff Algorithm

### SequenceMatcher

`compute_diff` uses Python's `difflib.SequenceMatcher` for line-by-line
comparison, walking `get_opcodes()`:

```python
matcher = difflib.SequenceMatcher(None, lines1, lines2)
for tag, i1, i2, j1, j2 in matcher.get_opcodes():
    # tag is one of: 'equal', 'replace', 'delete', 'insert'
```

### Diff model — `(rows, blocks)`

`compute_diff(lines1, lines2) -> (rows, blocks)`:

- **`rows`** — a `list[dict]`, one entry per display line, with keys:
  - `tag` — `'equal'`, `'replace'`, `'delete'`, or `'insert'`
  - `l1`, `l2` — the text shown on the left / right side (`""` where a side has
    no line for this row)
  - `n1`, `n2` — the 1-based line numbers in each file, or `None` when that side
    has no line
  - `cr1`, `cr2` — per-side changed-character ranges for a `replace` row (or
    `None`), computed by `_char_ranges(a, b)` from `SequenceMatcher` opcodes so
    only the differing spans are emphasised
- **`blocks`** — the row index where each change block begins, driving the
  `n` / `N` next/prev-change navigation (independent of search).

## Rendering

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Header (filename per side)                                  │
├──────────────────────────┬──────────────────────────────────┤
│ Left File Content        │ Right File Content               │
│ (scrollable)             │ (scrollable)                     │
├──────────────────────────┴──────────────────────────────────┤
│ Status Bar                                                  │
└─────────────────────────────────────────────────────────────┘
```

### Color coding

Diff band tints are **derived from the active theme's content background**, not
fixed color constants — a dark band on a dark theme, a pastel one on a light
theme. `_diff_bgs(content)` blends the content background toward semantic hues:

- deleted / left-side change — red (`_HUE_DEL`)
- inserted / right-side change — green (`_HUE_INS`)
- replaced line, both sides — amber (`_HUE_REPLACE`)
- the empty side of an insert/delete row — a faint neutral fill

The whole-row tint uses `_ROW_TINT`; the changed-character span inside a replaced
line uses the stronger `_CHAR_TINT`. Syntax colors keep their exact palette on a
dark theme and are auto-inked to the surface on a light one.

### Scrolling

Both panes share `top` (vertical) and `left` (horizontal), so they scroll and pan
together. Vertical scroll uses one shared scrollbar; each pane draws its own
horizontal scrollbar (the panes have different widths). Offsets are floats for
smooth fractional (sub-cell) scroll on a vector backend.

## Navigation Controls

Config-driven keys resolve through the shared `KEY_BINDINGS` (honouring the user's
rebinds); the scroll and `n`/`N` keys are viewer-local.

| Key | Action |
|-----|--------|
| `↑` / `↓` | Scroll one line |
| `PgUp` / `PgDn` | Scroll one page |
| `Home` / `End` | Top / bottom |
| `←` / `→` | Scroll horizontally |
| `n` / `N` | Next / previous change block |
| `search` (default `F`) | Incremental search — the shared `ISearchBar` overlay (matches on both sides; `↑`/`↓` walk them) |
| `help` (default `?`) | Key reference |
| `quit` (default `q`) / `Esc` | Close |

Mouse events route to the `Splitter` so the divider can be dragged; the panes
themselves are display-only.

## Testing

- `test/test_diff_viewer_theme.py` — the theme-derived diff band tints.

## Integration Points

### Dependencies

- `difflib` — standard-library diff computation
- `xefm.text_viewer` — reused `_read_lines`, `_highlight`, `_ScrollBody`, the
  scrollbar / status-bar helpers, and the shared viewer layer hints
- `xefm.path` — path abstraction for local/remote files
- `puikit` — the external UI framework (`Widget`, `Splitter`, backend); the old
  in-repo `ttk` toolkit was removed in the port

### File Manager Integration

- **Selection**: reads `pane["selected_files"]` on both panes
- **Text detection**: none up front — files are read and decoded, with binary
  content detected from the bytes during the read (see
  [Text Viewer System](TEXT_VIEWER_SYSTEM.md#text-file-detection))
- **Color scheme**: uses the same theme as the file manager

## References

- `xefm/diff_viewer.py` — implementation
- `xefm/app.py` — `diff_files()` launch
- `xefm/_config.py` — the `diff_files` key binding (`=`)
- `doc/DIFF_VIEWER_FEATURE.md` — user documentation
- Python difflib: https://docs.python.org/3/library/difflib.html
