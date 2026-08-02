# Sort Dialog — Implementation

Issue #237: the `sort_menu` action (the `S` key) used the generic popup menu;
it now opens a specialized modal, `xefm/sort_dialog.py`.

## Shape

`SortDialog` follows the `CompareSelectDialog` pattern (`xefm/compare_dialog.py`):
a plain PuiKit `Widget` pushed as a modal layer, sized up front through
`backend.measure_text` with the proportional UI font, anchored over the active
pane via `dialog_geometry.pane_anchored_box`, opened with the shared
`animate_open` entrance, titled by the shared `draw_title_bar`. It draws
everything itself — four key rows, an Ascending/Descending segment pair, the
explanation line, the key hint — rather than composing child widgets; there is
no focus tree, no Tab, no buttons.

Key rows are one *pitch* tall: 1.0 base unit on a character grid (whole rows),
`_GUI_ROW_PITCH` (1.3) on a vector backend, where a 1.0-unit pitch packs the
proportional lines edge to edge. The pitch threads through the geometry
helpers, so sizing (`show`) and drawing agree on both backends.

State is two fields seeded from the pane: `_index` (row into the `_KEYS` table:
`name` / `ext` / `size` / `date`) and `_reverse`. The legacy `'type'` mode (the
pre-dialog menu's suffix sort, which `get_sort_description` never knew) seeds as
Extension.

The outcome is reported through `on_result` as a `(sort_mode, sort_reverse)`
tuple, or `None` on cancel — nothing is applied until then, so Escape needs no
undo. `XeFMApp.show_sort_menu` writes the pair into the pane and calls
`_resort`, the same snapshot-based in-memory path every sort change takes.

## Key model

- Up/Down move `_index` with wrap; Left/Right *assign* the order (Left =
  ascending, Right = descending) rather than toggling, so each key is
  idempotent.
- The letter hotkeys (F/E/S/T, the `_KEYS` table's third column) set `_index`
  and accept in one stroke — the issue's "closes immediately". They are
  ignored when a non-shift modifier is held, so a stray Ctrl-chord does
  nothing. The letters are not displayed on the rows — each row's initial is
  its key; the in-app help lists them.
- A click on a key row accepts it (matching both the hotkeys and the menu this
  replaces); a click on an order segment only switches the order; a click
  outside the box cancels. Hit rects are captured during `draw`, dialog-local,
  like the other pickers.

## The explanation line

`_EXPLANATIONS` maps every `(mode, reverse)` pair to a fixed string drawn
right under the order segments — three sample values in list order plus the
plain-words reading ("smallest first") — so Ascending/Descending is always
read in the selected key's own terms. Sizing measures the widest of **all
eight** so the box never resizes as the selection moves. The strings are
static rather than derived from the pane on purpose: tiny, curated values
(`1 KB → 1 MB → 1 GB`) explain the *rule*; real filenames from the pane would
explain one directory.

## Menu-bar and footer alignment

The dialog's key names are the app-wide vocabulary. The menu-bar's **View →
Sort By** submenu (`_sort_menu`) stays a menu, but its entries were re-aligned
to the same four keys: `("Filename", "name")`, `("Extension", "ext")`,
`("Size", "size")`, `("Timestamp", "date")`. The old entry `("Type", "type")`
sorted by suffix without the display-matched length cap and had no
`get_sort_description` label, so the info bar mislabeled it "Name".

`FileListManager.get_sort_description` — the pane footer's sort text and the
"Sort: …" log line — uses the same names too (it previously abbreviated to
`Name`/`Ext`/`Date`), and now labels the legacy `'type'` mode "Extension"
instead of falling back to the name label. The footer already elides its left
summary as a pane narrows, so the longer names never collide with the
right-aligned disk-space text.

## Tests

`test/test_sort_dialog.py` drives the real dialog through a MemoryBackend +
`XeFMApp` (the `test_compare_dialog.py` pattern): rendering, seeding, the
keyboard model, hotkeys (including the modifier guard), the mouse model, and
the applied listing order — the fixture's three files order differently under
every key and direction, so each mode's effect is distinguishable.
