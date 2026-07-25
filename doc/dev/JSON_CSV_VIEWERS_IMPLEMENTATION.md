# JSON and CSV Viewers — Implementation

End-user behavior: `doc/JSON_CSV_VIEWERS_FEATURE.md`. Shared viewer mechanics
(the `M` toggle, per-type memory, rich-mode search wiring): `doc/dev/
MARKDOWN_VIEWER_IMPLEMENTATION.md`.

Like Markdown, these are **not** new modals. Each is a *body renderer* the
existing full-window `TextViewer` toggles to in place, plugged in through the
`xefm.viewer_registry` seam. The two new renderers are PuiKit widgets (renderer /
widget code lives in PuiKit, not XeFM); XeFM only wires them into the registry and
maps a parse function onto each.

## PuiKit widgets

Both widgets implement the same contract `TextViewer` drives its embedded rich
widget with — `draw(ctx)`, `handle_event(event)`, and the search protocol
`search_begin` / `search_set(pattern) -> int` / `search_navigate(delta)` /
`search_status() -> (pos, total)` / `search_accept` / `search_cancel` — so the
viewer's search bar and event forwarding work unchanged (the same contract
`MarkdownView` already satisfies). Both draw in a fixed-advance (monospace) face
so a column maps to one base unit, which keeps search highlights and the depth
indent aligned on the terminal and the GUI alike.

### `puikit/widgets/json_view.py` — `JsonView`

A scrollable, collapsible tree over **already-parsed** Python data (the registry
does the `json.loads`). Construction wraps the value into a `_Node` tree
(object / array / scalar); a top-level container shows its entries at depth 0
(no synthetic root row), a bare scalar shows one leaf. Navigation, flattening
(`_visible()`), scroll, **and the disclosure marker** mirror `TreeView`: on a
vector backend a branch's mark is a stroked `ctx.draw_chevron` in a reserved slot,
on a character grid it's the inline `▸`/`▾` glyph. The slot is a whole
`_MARK_SLOT = 2` columns — the same width as the inline glyph — so the key/value
text starts at the same integer column on both backends. The two things a plain
tree lacks:

- **Per-type coloring.** `_value_segs` builds `(text, color)` segments — the key
  (object key vs. array index), the `: ` separator, and either the scalar
  (colored by Python type: string / number / `true`-`false`-`null`) or a `{n}` /
  `[n]` size summary for a container. The palette defaults to the VS Code colors
  and is overridable via `theme.extras['syntax']` (the same seam the text viewer
  and `MarkdownView`'s code blocks use). A selected row flattens to one legible
  color over the selection fill via `draw_list_row`; other rows draw their
  colored segments directly.
- **Search.** `_recompute` walks the whole tree, and for every node whose
  key/value text contains the pattern it **auto-expands the node's ancestors** so
  the match is reachable, then records the matches in display order with their
  post-expansion row indices. `_draw_matches` repaints each occurrence over an
  amber highlight (firmer for the current match), like the raw text viewer.

`Cmd/Ctrl+C` copies the selected node's value as compact JSON (`json.dumps`).
There is no horizontal scroll — a long row elides with the pane clip, like a file
tree.

### `puikit/widgets/table_view.py` — `TableView`

A table grid over a `header: list[str]` and `rows: list[list[str]]`.
Construction computes per-column widths (capped at `_COL_MAX = 40`) and numeric
alignment, then lays out full-width header / body **line strings** plus each
column's start column, so drawing, hit-testing, selection and highlights all
share one column geometry. Rendering:

- **Frozen header.** The header band is drawn on the theme's `header` surface at
  the top, scrolled horizontally in lockstep with the body (same `int(left)`
  window) but never vertically.
- **Virtualized body + two-axis scroll.** Only visible body rows are drawn
  (`offset` in base units), so a large CSV stays cheap; `left` pans horizontally
  by whole columns. Vertical and horizontal scroll bars appear when the content
  overflows, reserved in a stable order (vertical first, then horizontal against
  the remaining width).
- **Cell selection + search.** A press seeds a `(row, col)` anchor and a drag
  extends a rectangular block (`_selection_range`); keyboard arrows move a current
  cell (Shift extends). `Cmd/Ctrl+C` copies the block as TSV, `Cmd/Ctrl+A`
  selects the whole body. Search matches body rows containing the pattern
  (`_recompute`), with in-place highlighting; the selection also moves to the
  matching cell (`_select_match` → `_match_col`), panning both axes.  `_span_x`
  maps an absolute-column span to the visible horizontal window for both the
  selection and match paint.
- **Grid lines ("keisen").** Column geometry reserves a one-column border edge
  (`_edges`) with one pad column on each side of the cell text (`_content_x`),
  matching MarkdownView's table metrics; the line strings carry only the cell
  text on a blank field so the rules are overlaid at draw time (`_draw_grid`). A
  vector backend strokes `ctx.draw_hairline` for a full grid — every column edge
  full height, every row boundary, top/bottom frame. A character grid draws `│`
  bars down each column edge (one glyph per cell) and a box-drawing `├─┼─┤`
  header separator (`_draw_hsep`, using `_box_glyph` junctions), and zebra-stripes
  the body rows (a per-row rule would cost a whole text row there) — so on the TUI
  the table matches MarkdownView's. The header zone is one row taller on the grid
  (it reserves the separator row); the rules stop at the content bottom, not the
  empty body track below a short table.

Both widgets are exported from `puikit/widgets/__init__.py`.

## XeFM wiring — `xefm/viewer_registry.py`

Three `register(...)` calls join the existing Markdown one:

```python
register(RichRenderer("JSON",  _build_json),               ".json", ".jsonl", ".ndjson")
register(RichRenderer("Table", _make_table_builder(",")),  ".csv")
register(RichRenderer("Table", _make_table_builder("\t")), ".tsv")
```

- `_build_json` → `JsonView(_parse_json(source), style=style)`. `_parse_json`
  parses the whole file as one JSON document and, if that fails, falls back to
  **JSON Lines** (one value per non-blank line, wrapped in a list) — so `.json`
  and `.jsonl` / `.ndjson` share one builder without `build` needing the path.
  It raises `json.JSONDecodeError` when neither form parses.
- `_make_table_builder(delimiter)` returns a `build` closure that reads the
  source with `csv.reader(..., delimiter=...)` (first row = header). Because the
  registry's `build(source, *, style)` isn't handed the path, the CSV/TSV split
  is done by registering two builders — one per delimiter — rather than sniffing.

The PuiKit widget imports are lazy (inside `build`), matching `_build_markdown`,
so the registry stays cheap to import.

## Robust toggle — `xefm/text_viewer.py`

`TextViewer._ensure_rich_widget` now wraps the `self._rich.build(...)` call in
`try/except Exception`: a malformed `.json` / `.csv` (a builder that raises) logs
a warning and returns `False`, so the viewer **stays in raw text mode** instead
of crashing on the toggle. Raw still renders the file (pygments-highlighted).
This is the only change to `TextViewer` — everything else (the `M` toggle,
per-type memory, rich-mode search delegation, event forwarding) already works for
any registered renderer.

## Tests

- PuiKit `tests/test_json_view.py`, `tests/test_table_view.py` (parametrized TUI +
  GUI): render/markers, expand/collapse, scalar-document rendering, numeric
  alignment, frozen header while the body scrolls, horizontal scroll revealing
  later columns, keyboard cell movement, TSV copy / select-all, and each
  `search_*` method (expand-ancestors, status, navigate/wrap, no-match restore).
- XeFM `test/test_json_viewer.py`, `test/test_table_viewer.py` (parametrized TUI +
  GUI): the registry mapping; toggle building a `JsonView` / `TableView`; JSONL
  wrapping records in a list; the CSV vs TSV delimiter split; both modes drawing
  without crashing; an empty CSV rendering an empty grid; and a **malformed
  `.json` staying raw** (build fails → `_ensure_rich_widget` returns `False`,
  toggle refused, no crash).
