# XeFM Dialog System

## Overview

XeFM's dialogs are the modal (and near-modal) overlays the app raises for input,
selection, search, and information display: creating a file, renaming, picking a
favorite, searching a tree, viewing help, batch-renaming, and so on.

Since the PuiKit port, every dialog is an ordinary **PuiKit widget pushed onto the
`Panel` as a layer**. There is no bespoke dialog engine, no curses drawing, and no
per-frame redraw bookkeeping. A dialog is a `Widget` (usually also a
`FocusContainer`) that is composed from PuiKit primitives — `TextEdit`,
`ListView`, `MarkdownView`, `Checkbox` — and relies on the Panel's layer stack for
modality, focus, event routing, and drawing.

## The dialog classes

| Class | Module | Factory | Role |
|-------|--------|---------|------|
| `InputDialog` | `xefm/input_dialog.py` | `show_input` | Single-line text prompt (create, rename, jump-to-path, archive name, password) |
| `FilterListDialog` | `xefm/filter_list_dialog.py` | `show_filter_list` | Filterable list picker (favorites, drives, history, external programs) |
| `ProgressiveSearchDialog` | `xefm/progressive_search_dialog.py` | `show_progressive_search` | Live search-as-you-type over the filesystem (filename / content) |
| `TextDialog` | `xefm/text_dialog.py` | `show_text` | Read-only scrollable plain-text viewer |
| `MarkdownDialog` | `xefm/text_dialog.py` | `show_markdown` | Read-only scrollable rich-text viewer (help, file details) |
| `BatchRenameDialog` | `xefm/batch_rename_dialog.py` | `show_batch_rename` | Regex batch rename with a live preview |
| `CompareSelectDialog` | `xefm/compare_dialog.py` | `show_compare_select` | Keyboard-first criteria picker for compare-and-select |
| `ISearchBar` / `ViewerISearch` | `xefm/isearch_bar.py` | (constructed directly) | Incremental search input pinned in a pane / viewer footer |
| `CandidateListOverlay` | `xefm/candidate_list.py` | (driven by `InputDialog`) | TAB-completion popup |

Two supporting pieces are not dialogs themselves:

- **`xefm/dialog_geometry.py`** — the shared sizing/chrome helpers every modal uses
  (`draw_title_bar`, `draw_hint_row`, `pane_anchored_box`, `animate_open`).
- **`show_message_box`** — a PuiKit widget primitive (from `puikit.widgets`) XeFM
  uses for confirmations, info, and error boxes (Quit, "No favorites configured",
  operation-error summaries). It follows the same layer model but ships with
  PuiKit rather than living in `src/`.

The `JumpDialog` and the drives/favorites pickers survive as features but are
implemented on this framework (jump has its own module; drives/favorites are
`FilterListDialog` call sites). See the cross-links at the bottom.

## The shared pattern

Every dialog class follows the same shape, so once you have read one you can read
them all.

### 1. It is a Panel layer

`show_xxx(panel, ...)` constructs the widget, computes a size from the backend's
`size_units`, and pushes it:

```python
panel.push_layer(dialog, z=z, hints={"shadow": True, "w": w, "h": h})
animate_open(panel, dialog)
```

The default layer `z` is `70`. The `shadow` hint gives the modal its drop shadow;
`animate_open` plays the shared entrance transition (below). Sizing is a fraction
of the window clamped to sensible min/max (e.g. `InputDialog` is
`max(36, min(sw*0.6, 64))` wide), so dialogs stay consistent regardless of item
count.

### 2. The top interactive layer owns everything (modality)

`Panel.dispatch_event` delivers events **exclusively** to the top-most
*interactive* layer (`_top_interactive_slot`). While a dialog is that layer it
receives every key and mouse event, and its `handle_event` returns `True` for
everything it doesn't otherwise use — that trailing `return True` is what makes it
modal (nothing leaks to the panes beneath). Being the top layer also makes the
dialog the **focus root**, which is what engages the backend's text-input / IME
system for its `TextEdit` field and blinks a caret.

### 3. Focus resolves to a real text widget

Each dialog subclasses `FocusContainer` and implements `focus_children()`
(and sometimes `get_focused()`), returning the field(s) so the Panel's focus leaf
lands on a `TextEdit`/`Checkbox`. Without this the focus would stop at the dialog
(not a text widget) and the IME would never turn on. Class attributes
`focusable = True` and `focus_stop_when_empty = True` keep the dialog a focus stop
even when its list is momentarily empty.

### 4. Drawing uses a `DrawContext`, not curses

```python
def draw(self, ctx) -> None:
    theme = ctx.theme
    surface_bg = theme.popup_bg if theme else None
    ctx.draw_box(0, 0, *ctx.size_units, box_style, hints={"fill": True})
    y = draw_title_bar(ctx, self.title, surface_bg=surface_bg, border=border, y=1.0)
    ctx.draw_child(self.edit, field_x, y, field_w, 1.0, hints={"focused": True})
```

Drawing is done through `ctx` (a PuiKit `DrawContext`): `draw_box`, `draw_text`,
`draw_child`, `round_rect`, `fill_rect`, `draw_scrollbar`, `measure_text`,
`line_height`, plus `ctx.theme`, `ctx.size_units`, and `ctx.vector_shapes` (True on
GUI/vector backends, False on a character grid). Colors come from the theme
(`popup_bg`, `popup_border`, `text`, `muted_text`, `selection_active_bg`, …) via
`Style`, never from curses color pairs. Sub-widgets (the field, the list) are
drawn with `ctx.draw_child(...)`, and their rects are captured for mouse
hit-testing. The same widget code runs unchanged on the curses, macOS, and Windows
backends.

### 5. Events: keys, IME, mouse

`handle_event(event)` handles three event families and swallows the rest:

- **`EventType.KEY`** — `escape` cancels, `enter` accepts, `tab` switches
  field/mode where applicable, navigation keys (`up`/`down`/`pageup`/`pagedown`,
  and `home`/`end` for viewers) are forwarded to the embedded `ListView` /
  `MarkdownView`, and anything else goes to the focused `TextEdit` (typing).
- **`EventType.IME_COMPOSITION`** — forwarded to the field so CJK preedit renders
  inline (the modal layer must relay composition because the field never receives
  events directly).
- **Mouse events** — routed by hit-testing the captured child rects; a
  `MOUSE_CLICK` outside the dialog's own bounds cancels it (outside-click dismiss).

### 6. Outcome via callbacks, dismissal via `pop_layer`

Dialogs report results through callbacks passed to the factory — `on_accept`,
`on_cancel`, `on_change`, `on_done`, `on_result`, `on_close` — not return values.
A dialog closes itself with a guarded `panel.pop_layer()`:

```python
def _close(self) -> None:
    panel = self._panel
    if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
        panel.pop_layer()
```

### Rendering model (what replaced the old optimization)

There is **no** `content_changed` flag, `needs_redraw()` method, or "77.8%
rendering optimization" any more — that machinery belonged to the removed curses
render loop. Under PuiKit, redraws are on demand: a handler mutates state and calls
`self._panel.render()` (or the app calls `panel.render()` after an action). A
dialog with live, asynchronous content drives its own repaints through
`panel.request_animation_ticks(callback)` — see `ProgressiveSearchDialog` below —
falling back to a synchronous settle on a still backend (chiefly tests). The
entrance animation is handled once by `animate_open`.

## Geometry and shared chrome (`xefm/dialog_geometry.py`)

This module is the single home for a modal's size and chrome, so every dialog
looks and opens the same way.

- **`draw_title_bar(ctx, title, *, surface_bg, border, y=1.0) -> float`** — draws
  the bold title with a frame-connecting rule beneath it and returns the first
  content row. It reconciles the two backends: on a character grid the title, rule,
  and content each take a whole row (`y`, `y+1`, `y+2`); on a vector backend the
  bar is sized to the *measured* title line (`gui_title_bar_height`) so it reads
  thin and balanced. Every modal calls this rather than drawing its own header.

- **`draw_hint_row(ctx, text, *, surface_bg, border, x=2.0, right="")`** — the
  title bar's mirror, and the one place a modal names its keys: a
  frame-connecting rule, then the muted line of keys in the band beneath it, hard
  against the bottom border. A modal is framed by two matched bands with its
  content between them. Content measures against **`hint_content_bottom(ctx,
  surface_bg)`** (the counterpart to what `draw_title_bar` returns); a dialog that
  sizes its box up front, with no stretchy body to measure, adds **`HINT_ROWS`**
  to its content height instead. `right` pins a second reading to the band's
  right end — Tip of the Day's position counter is the only one — kept whole
  while the keys elide against it. Every modal that owns the keyboard draws this;
  see *Where a hint is drawn* in `doc/dev/KEY_BINDINGS_IMPLEMENTATION.md` for
  which ones, and for the two that deliberately do not.

- **`pane_anchored_box(desired_w, screen_w, region, *, margin=2.0) -> (w, x)`** —
  positions a pane-targeting picker over the pane it acts on. `region` is the
  pane's `(x, width)` column span (base units). The dialog keeps its *own* desired
  width (a narrow pane never shrinks it) and is centered on the pane's center, so
  it visibly leans over its target pane; an on-screen clamp keeps a margin on each
  side. Callers opt in by passing `region=` to a `show_*` factory (favorites,
  drives, filter, compare, jump anchor over the active pane via
  `XeFMApp._active_pane_region()`).

- **`animate_open(panel, widget, duration_ms=OPEN_MS_DIALOG)`** — the one
  app-wide modal entrance: a scale-from-92%-plus-fade "materialize" with an
  `ease_out_expo` curve. It honors a theme opting out (`dialog_effect=False` in
  `Theme.extras`, e.g. Segment LCD) and reduced motion, returning `False` when no
  transition was scheduled (the widget is simply already in its final state). On a
  terminal the Panel renders the intent as a two-frame open. `OPEN_MS_DIALOG` is
  `180` ms; viewers use the slightly faster `OPEN_MS_VIEWER` (`140` ms).

## The dialogs in detail

### InputDialog — `show_input`

A small centered modal with a title, a prompt label, and one `TextEdit`. Typing
edits; Enter accepts (text passed to `on_accept`); Esc or an outside click cancels;
`on_change` fires live on every keystroke (used for incremental prompts).

- **`validate(text) -> str | None`** — returns an error string to keep the dialog
  open and show the message inline (empty/duplicate names), so a bad value never
  silently closes it.
- **`select_all`** — start with the whole value selected (rename: first keystroke
  replaces) versus caret-at-end (append).
- **`password`** — masks the field with a bullet glyph and disables clipboard
  copy/cut of its contents (encrypted-archive password).
- **`completer`** — enables TAB completion. A `CompletionController` (from
  `xefm.completion`) mutates the field and tracks candidate state; when several
  matches remain, a `CandidateListOverlay` is pushed as a separate,
  **non-interactive** layer just below/above the field, navigated with the arrow
  keys. Used for filepath completion in Jump-to-Path.

Call sites: New Directory, New File, Rename, Create Archive, Jump to Path, and the
archive password prompt.

### FilterListDialog — `show_filter_list`

The canonical searchable-list picker, built from a `TextEdit` filter field over
a `ListView`. Typing filters the list with the shared incremental-search query
(`xefm.search_match`, issue #349): whitespace-separated tokens that must *all*
match the rendered label, each as a case-insensitive "contains" glob or through
Migemo. One matcher, so the dialogs and the pane's isearch cannot drift apart —
`_label_hit` is `search_match.hit` on `to_label(value)`, with the query compiled
once per keystroke (and once per streamed batch in `add_items`, where regex
generation would otherwise repeat per row).
`up`/`down`/`pageup`/`pagedown`
drive the selection even while the field holds focus; Enter accepts the selected
value via `on_accept`; a click selects/activates a row.

- **`on_accept_text`** — optional free-text fallback: when Enter is pressed and no
  row matches the query, the raw filter text is handed here instead, so the picker
  can double as an editor (a brand-new filter pattern that isn't in history).
- **`to_label`**, **`ellipsis`** / **`elide_where`** — control row rendering;
  path lists use `elide_where="middle"` so a long path keeps its meaningful tail.

Call sites: favorites, drives, directory history, external programs.

### ProgressiveSearchDialog — `show_progressive_search`

A single modal combining a query field with a **streaming results list**; typing
re-runs a filesystem search on every keystroke. `Tab` switches between `filename`
and `content` mode in place. Enter accepts the selected row via
`on_accept(mode, value)`.

Threading model (mirrors the port's async pane listing):

- Each keystroke bumps a generation counter, signals the previous search's
  `threading.Event` to cancel, and starts a fresh daemon thread pulling from the
  caller-supplied `search_iter(mode, query, cancel)` generator.
- The worker batches hits onto a `queue.Queue`; a per-frame drain registered via
  `panel.request_animation_ticks(self._drain)` pulls batches on the UI thread,
  extends the list, advances the braille spinner, and re-renders — so results
  appear progressively and a stale generation is dropped.
- On a still backend (no animation ticks, e.g. tests) the search settles
  synchronously: the worker is joined and the queue drained in one shot.

A `result_cap` (default `1000`) bounds growth on a huge tree.

### TextDialog / MarkdownDialog — `show_text` / `show_markdown`

The read-only counterparts (the `InfoDialog` replacement). Both share a
`_ScrollModal` base that owns the box, title bar, a hint row, and event routing;
they differ only in the body widget:

- **`TextDialog`** hosts a `ListView` of preformatted lines (log-like /
  pre-aligned content). `show_text`.
- **`MarkdownDialog`** hosts a `MarkdownView` — CommonMark-ish headings, emphasis,
  tables, `code`, and links — for content that reads better as structured prose.
  `show_markdown`.

Both forward `up`/`down`/`pageup`/`pagedown`/`home`/`end` to the body and close on
Enter / Esc / outside-click. `keys_markdown(rows, intro=...)` is a helper that
builds a two-column `| Key(s) | Action |` table source for key-help overlays.
Call sites: file Details and the Help/About overlays.

### BatchRenameDialog — `show_batch_rename`

Rename many files with a regex *search* pattern and a *replace* pattern, with a
live `original → new` preview before anything touches disk. Two `TextEdit` fields
(`Tab` switches) sit above a `ListView` preview.

- The pure function **`compute_preview(files, search, replace)`** produces the
  plan (one dict per file with `original`, `new`, `valid`, `conflict`, `file`). It
  is filesystem-free, so it is unit-test-friendly and safe to run on every
  keystroke. The replace pattern supports `\0` (whole match), `\1`..`\9` (groups),
  and `\d` (1-based batch index).
- The preview flags invalid names and collisions (against an existing file **or**
  against another row producing the same name), and Enter refuses to run while any
  conflict stands. `on_done(success_count, errors)` fires after a successful run.

### CompareSelectDialog — `show_compare_select`

A compact, keyboard-first criteria picker (no Tab, no buttons) that assembles a
`CompareCriteria` for the compare-and-select action. It has three `ConditionRow`s
(Size / Modified / Content) — each a real `Checkbox` plus a segmented relation
picker — and a "Preserve current selection" toggle.

- **Up / Down** move focus between rows; **Left / Right** choose the relation on a
  condition row; **Space** toggles the checkbox (`any` == unchecked, i.e. don't
  compare that attribute); **Enter** accepts, **Esc** cancels.
- It sizes itself to its content up front by measuring through the backend with the
  proportional UI font (so the box hugs its text on a GUI backend, and counts
  columns on a grid). The result is reported through `on_result(criteria)`
  (`None` on cancel).

### ISearchBar / ViewerISearch — `xefm/isearch_bar.py`

Incremental search is the exception to the centered-modal rule: it must sit exactly
on the active pane's (or a viewer's) **footer bar** while the list above stays
visible and its cursor keeps moving as you type. So `ISearchBar` is pushed as a
thin overlay layer positioned at the footer's captured rect (with a `"status"`
surface hint), rather than a centered box.

It is one row: a bold prompt on the left, an editable `TextEdit` pattern field
across the rest, and a `position/total` match counter pinned to the right.
`Up`/`Down` walk the match set, `Enter` stops at the current match, `Esc` (or an
outside click) cancels. The bar owns no search logic — the host supplies callbacks
(`on_change`, `on_navigate`, `on_submit`, `on_cancel`, `get_status`). See
`XeFMApp.enter_isearch` for the main-window wiring. **`ViewerISearch`** is a small
driver that gives the full-window text/diff viewers the same footer-anchored
incremental search without each re-implementing the plumbing.

### CandidateListOverlay — `xefm/candidate_list.py`

The TAB-completion popup for `InputDialog`. It is a small presentational widget
pushed as its **own non-interactive layer** directly below/above the field being
completed (above the dialog in z-order so it hugs the field, but non-interactive so
keyboard focus stays with the dialog beneath). The host syncs it with
`set_state(candidates, focused_index)` from a `CompletionController` and positions
it with `overlay_geometry(...)`, which places the popup below the field (or above
when there is no room), left-anchored so the candidate text lines up with the
token, sized to the longest candidate and capped at `MAX_ROWS` (8) rows with a
scrollbar. Because it is not the event-owning layer, the host forwards clicks that
fall inside it to `handle_event`, which reports the chosen row through
`on_activate`.

## Integration with XeFMApp

The app holds a single `self.panel` (a PuiKit `Panel`). An action handler simply
calls a factory and renders:

```python
def show_favorites(self) -> None:
    show_filter_list(
        self.panel, favorites, title="Go to Favorite",
        to_label=lambda fav: f"{fav['name']}  —  {fav['path']}",
        on_accept=self._jump_to_favorite,
        region=self._active_pane_region(),
        elide_where="middle",
    )
    self.panel.render()
```

There is no dialog dispatch table, no `handle_input(key)` fan-out, and no
`_draw_dialogs_if_needed()` in the main loop — the Panel routes events to the top
layer and draws all layers itself. Incremental search is the one case the app
manages more directly, because it constructs `ISearchBar` and pins it to a captured
footer rect rather than centering it (`XeFMApp.enter_isearch` and the
`_isearch_*` callbacks).

## Testing

Dialog behavior is covered by unit tests that drive the widgets against PuiKit's
headless backend (no live TUI). Representative files:

- `test/test_progressive_search_dialog.py` — streaming search, generations,
  synchronous settle.
- `test/test_batch_rename_conflicts.py` — `compute_preview` conflict/invalid
  detection and macros.
- `test/test_compare_dialog.py` — criteria assembly and navigation.
- `test/test_dialog_geometry.py` — `pane_anchored_box` / title-bar sizing.
- `test/test_viewer_isearch.py` — the viewer incremental-search driver.

Run them with the project's standard invocation
(`python -m pytest test/<file> -v`).

## Related Documentation

- [Jump Dialog System](JUMP_DIALOG_SYSTEM.md) — the directory-jump picker built on
  this framework.
- [Drives Dialog System](DRIVES_DIALOG_SYSTEM.md) — the storage-location picker
  (a `FilterListDialog` call site).
- [Menu System](MENU_SYSTEM.md) — the menu-bar / context-menu overlays (also
  PuiKit layers).
- [Text Viewer System](TEXT_VIEWER_SYSTEM.md) and
  [Directory Diff Viewer System](DIRECTORY_DIFF_VIEWER_SYSTEM.md) — full-window
  viewers that reuse `ViewerISearch`.
- [XeFM Application Overview](XEFM_APPLICATION_OVERVIEW.md) — overall architecture
  and the Panel/layer model.
