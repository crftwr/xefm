# JSON and CSV Viewers

XeFM's built-in file viewer can render **JSON / JSON Lines** files as a
collapsible tree and **CSV / TSV** files as an aligned table, in addition to the
usual raw, line-numbered text view. They work exactly like the [Markdown
viewer](MARKDOWN_VIEWER_FEATURE.md): press **V** to open a file, then **M** to
toggle between the raw text and the rich view.

## JSON / JSON Lines (`*.json`, `*.jsonl`, `*.ndjson`)

The rich view is a **collapsible tree**. Objects and arrays are branches you can
expand and collapse; scalars are leaves. Each row shows its key (an object key or
an array index) and the value, colored by type — strings, numbers, and
`true` / `false` / `null` each get their own color, following the active theme.
A collapsed branch shows its size (`{3}` for a 3-key object, `[5]` for a 5-item
array), so you can see the shape of a document without expanding everything.

A `.jsonl` / `.ndjson` file (one JSON value per line) is shown as an array of its
records.

**Selecting a fragment with the mouse.** Selection in the tree is *structural*:
a click or drag always selects a meaningful piece of JSON — never half a word or
a stray text span. Click a key to select `"name"`, a value to select `"str"` /
`123` (or, on a branch row, the whole `{...}` / `[...]` sub-document), or the
`: ` between them to select the whole `"name": ...` entry. Drag to grow the
selection: across a key and its value it becomes the entry, across two rows it
becomes the container that holds them both, and across two top-level entries the
whole document. **⌘C / Ctrl+C** copies the highlighted fragment as JSON text;
with nothing highlighted it copies the current row's value, as before. Arrow
keys or a click on empty space clear the highlight. (Array indices aren't JSON
text, so clicking one selects the element's value.)

**Long values.** A string longer than the window has two ways to be read.
Unwrapped (the default), the view **pans horizontally** — swipe sideways on a
trackpad or press **Shift+←/→**, with a horizontal scrollbar along the bottom
while something overflows. Press **W** to **wrap** instead: every value folds
into the window width, continuing on extra lines aligned under where it starts,
so the whole string is on screen at once. The header shows *WRAP* while wrap is
on, and W toggles back.

| Key | Action |
|-----|--------|
| ↑ / ↓ | Move up / down a row |
| → | Expand a branch (or step into it) |
| ← | Collapse a branch (or jump to its parent) |
| Enter / Space | Toggle the selected branch |
| PgUp / PgDn, Home / End | Scroll by a page / jump to the top or bottom |
| **W** | Toggle line wrap for long values |
| Shift+← / Shift+→ | Pan a long row sideways (when wrap is off) |
| Mouse wheel / click | Scroll / select a row (click the ▸ ▾ marker to toggle) |
| Click / drag on text | Select a JSON fragment (key, value, entry, or container) |
| **⌘C / Ctrl+C** | Copy the fragment — or, with none, the row's value — as JSON |
| **F** | Incremental search |

## CSV / TSV (`*.csv`, `*.tsv`)

The rich view is an **aligned table** with ruled grid lines. The header row stays
frozen at the top while the body scrolls, columns are sized to their content
(numeric columns right-align), and the grid scrolls both vertically and
horizontally so wide tables stay readable. A `.tsv` file is split on tabs, a
`.csv` file on commas.

The grid lines follow the display: on the graphical app they're crisp
device-thin rules around every cell; on the terminal they're box-drawing
characters (`│` column separators and a `├─┼─┤` line under the header), with the
body rows zebra-striped for separation.

| Key | Action |
|-----|--------|
| ↑ / ↓ / ← / → | Move the current cell |
| PgUp / PgDn | Scroll a page |
| Home / End | First / last column |
| Mouse wheel | Scroll (vertical, and horizontal on a trackpad) |
| Click + drag | Select a rectangular block of cells |
| **⌘C / Ctrl+C** | Copy the selected cells as TSV |
| **⌘A / Ctrl+A** | Select the whole table |
| **F** | Incremental search |

## Shared behavior

- **The M toggle and per-type memory.** The rich view is reached with **M**, the
  same key the Markdown viewer uses. XeFM remembers the view you last chose *per
  file type* and reopens that type the same way next time — toggle one `.json`
  file to the tree and every `.json` opens as a tree afterward, this session and
  after a restart. The header's top-right shows the current view's name (*JSON* /
  *Table*); the footer shows the toggle key.
- **Search.** Press **F** in either rich view to search. As you type, the
  selection moves to the match — the current row in the JSON tree, the current
  cell's row in the table — just like the main file manager's search. In the JSON
  tree, matches auto-expand their branches so they're reachable. **↑** / **↓**
  step between matches, **Enter** commits the selection on the current match, and
  **Esc** cancels and restores the selection you started from. Matching is
  case-insensitive.
- **Malformed files fall back to raw.** If a `.json` doesn't parse (or a file
  otherwise can't be rendered), **M** simply leaves you in the raw text view —
  which still shows the file with syntax highlighting — rather than failing.
- Both views follow the active theme and work on the terminal and the native
  (macOS / Windows) backends.
