# Capability Branching Audit

Every place XeFM reads a backend capability, and whether that read is allowed.

PuiKit's rule (its `docs/rendering_system.md` §5, "The one rule for reading a
capability"):

> A widget may read exactly these booleans, and **only to decide whether a
> pixel-only ornament is worth drawing** — never to switch drawing models.
>
> The litmus test: if reading a capability makes the widget *draw something
> different in kind* (a line here, a rectangle there), the branch is in the wrong
> place — push it down into a `DrawContext` method so every widget shares it. If
> it only makes the widget *add or omit an ornament the grid can't afford*, it
> belongs in the widget.

XeFM reads capabilities in about twenty places. Most are within the rule — a
sub-cell pad that collapses to zero, an ornament a grid cannot afford. **Two are
not**, and both exist for the same reason: PuiKit has no intent primitive for the
thing being drawn, so the widget makes the choice the framework should be making.
They are listed first, with the note that lives at each site.

This file is the record. It is not a plan — nothing here is a bug the user can
see, and the fixes are PuiKit API additions.

---

## Deviations

### 1. The file-pane cursor cue — `xefm/file_pane.py`

`grid = not ctx.vector_shapes` picks between a stroked rounded rect framing the
row (GUI) and `[` `]` bracket characters plus an underline attribute (TUI). That
is different *in kind*, and it drags two more branches with it: the gutter
columns the brackets need, and the cursor band those gutters define.

The fix is a row-marker primitive in PuiKit — `ctx.draw_row_marker(x, y, w,
style, hints)` in the control-face family (`round_rect`, `draw_hairline`,
`draw_check`), resolving to the outline on a vector backend and to brackets plus
an underlined blank run on a grid. It needs a second half the other faces do not:
the grid variant spends a gutter column at each end, so a widget must be able to
ask what the marker costs *before* it lays out its columns — the same shape as
`draw_border` insetting the content clip.

Recorded at the branch in `FilePane.draw`, in
[COLOR_SCHEMES_IMPLEMENTATION.md](COLOR_SCHEMES_IMPLEMENTATION.md), and as §9.4
of PuiKit's `docs/rendering_system.md`.

### 2. The directory-diff tree column — `xefm/directory_diff_viewer.py`

`vector = ctx.vector_shapes` selects between two whole renderers,
`_draw_side_vector` and `_draw_side_grid`: thin pixel strokes with a
proportional, measured-width name, or `├ └ │` box-drawing connectors with
column-counted truncation. This is the largest instance of the pattern in the
codebase — a drawing model chosen in the app, not one ornament dropped.

Same shape of gap as #1: a **tree-connector** intent primitive is missing.
`draw_hairline` already makes exactly this vector-vs-grid choice for a single
rule and proves the model; a connector is that plus the elbow/tee/stem cases and
their indent arithmetic.

---

## Within the rule

| Site | Reads | What it decides |
|---|---|---|
| `app.py` `_bar_pad` | `vector_shapes` | Chrome-bar inset: device pixels, or one whole cell / no row on a grid |
| `app.py` hint bar draw | `vector_shapes` | One extra cell of inset under an OS-rounded window corner (a terminal's corners are the emulator's) |
| `candidate_list.py` | `vector_shapes` | Draws the popup's rounded border only where it costs no cell |
| `compare_dialog.py` segments | `vector_shapes` | Pill padding around a highlighted segment; zero on a grid |
| `compare_dialog.py` layout | `pixel_layout`, `hairline`, `native_menus` | Feeds a sub-layout resolution, mirroring the Panel's own `snap` rule — §5 names `pixel_layout` for exactly this |
| `diff_viewer.py` (×2) | `vector_shapes` | Content inset, zero on a grid |
| `file_pane.py` margins | `vector_shapes` | Content / cursor / inner margins, zero on a grid |
| `text_viewer.py` `viewer_pad` | `vector_shapes` | Viewer content inset, zero on a grid |
| `tips_dialog.py` (×3) | `vector_shapes` | Sub-row gaps on vector, whole rows on a grid |
| `choice_dialog.py`, `sort_dialog.py` `_row_pitch` | `vector_shapes` | Row pitch: taller than one unit on vector, where a 1.0 pitch packs proportional lines edge to edge |
| `sort_dialog.py` pad | `vector_shapes` | Selection-band padding; zero on a grid |
| `input_dialog.py` | `vector_shapes` | Dialog height, 5 rows or 6 — the compact GUI title bar pulls the field up one row |

### Borderline, worth revisiting

- **`dialog_geometry.py` `draw_title_bar`** — both paths draw a title and a
  `draw_frame_divider`; only the *geometry* differs (a measured bar height on
  vector, whole rows on a grid). Same primitives, so it is spacing rather than a
  drawing model — but it is the reason `input_dialog.py` has to branch on the
  dialog's height too, which is how a spacing branch spreads.
- **`filter_list_dialog.py` / `progressive_search_dialog.py`** — `icon_gap = 2.5
  if vector else 3.0`, because the magnifier emoji occupies two cells on a grid.
  That is a *measurement*, and `ctx.measure_text` already answers it on both
  backends; the branch could go away without any PuiKit change.
