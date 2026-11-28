# Mouse Operation — Implementation

Issue #589, from discussion #588. Most of the plumbing already existed. The
gaps were marking, opening, move-on-drop and the chrome bars. The PuiKit side
is puikit `mouse-modifiers`.

## PuiKit prerequisites (puikit PR)

- **Modifiers on every GUI mouse event.**
  - macOS `_PuiKitView` reads `ns_event.modifierFlags()` on down, up, drag,
    right-click and wheel.
  - Windows `_key_modifiers()` (GetKeyState) on the same set.
  - Panel builds `MOUSE_CLICK` by `replace()` on the `MOUSE_UP`, so the up
    event must carry them too.
  - On macOS a bare Control-left-press becomes a right `MOUSE_CLICK`, with
    the release swallowed. That is the platform's secondary click.
- **Side buttons.** These are atomic `MOUSE_CLICK` events with
  `button="back"`/`"forward"`, from:
  - `NSEvent.buttonNumber` 3/4 (`otherMouseDown_`);
  - `WM_XBUTTONDOWN` (`HIWORD(wParam)` 1/2, return TRUE);
  - SGR buttons 8/9 (`b & 0x80`) in the terminal.

  The macOS middle button now reports down/up, as Windows already did.
- **Drop operation.** `FILE_DROP` carries `modifiers` and
  `hints["operation"]`, which is "copy", "move", "link" or `None`. The rules
  are in `puikit/backends/_drop_policy.py`:
  - Finder: ⌘ move, ⌥ copy, ⌘⌥ link.
  - Explorer: Shift move, Ctrl copy, Ctrl+Shift or Alt link.

  `None` means no modifier was held. An operation the drag source doesn't
  allow is reported as `None` too, so a copy-only source is never moved. The
  hover badge follows the same rules.
- `MultiClickTracker` is exported from `puikit.widgets`.

## XeFM

### FilePane (`xefm/file_pane.py`)

- `on_click(index, modifiers, clicks)`. `clicks` comes from a
  `MultiClickTracker` fed on `MOUSE_DOWN` with the row index. A drag-out
  calls `note_drag()`, so the next press starts a new run.
- `on_middle(index)` for a middle `MOUSE_CLICK`, and `on_nav("back"|"forward")`
  for the side buttons.
- `on_drop(index, paths, operation)`.
- **Scrollbar.**
  - `draw` records `_bar = (x, top, height, rows)`.
  - A `MOUSE_DOWN` inside it sets `_press_in_bar`. On the thumb
    (`_thumb()`, the same geometry `draw_scrollbar` gets) it grabs; on the
    track it pages by one viewport.
  - `MOUSE_DRAG` maps the pointer to `offset`.
  - The synthesized click is swallowed, so a press on the bar never moves the
    cursor or starts a drag-out.
  - `draw` re-centers on the cursor only when the cursor moved, so a dragged
    offset sticks.

### XeFMApp (`xefm/app.py`)

- **`_on_click(pane, index, modifiers, clicks)`**:
  - `shift` marks the range from `pane["_click_anchor"]` (else the cursor)
    through the clicked row, adding to the marks.
  - `cmd`/`ctrl` toggles the mark and sets the anchor.
  - A plain click moves the cursor, sets the anchor, and leaves the marks
    alone.
  - `clicks == 2` with no modifier calls `_open(pane)`, the same call as
    Enter.
- **`_on_middle_click`**: a directory row opens in the other pane through
  `_go_to_dir`, and the other pane becomes active.
- **Back / forward**:
  - `pane["_back"]` / `pane["_forward"]` are recorded in
    `_fire_directory_changed`. Every listing passes through it, and it
    already compared against the last reported path.
  - A normal change pushes the old path (capped at `_BACK_MAX`) and clears
    forward.
  - `go_back` / `go_forward` set `pane["_history_step"]`, so the change they
    cause moves the entry between the stacks instead. Stepping back to the
    parent focuses the folder you came from.
  - Keys: `Alt-LEFT` / `Alt-RIGHT`. The macOS desktop app adds
    `Command-[` / `]`.
- **`_on_drop(..., operation)`**:
  - `None` becomes "move" when `_same_volume` holds (every source is local and
    has the same `st_dev` as the target directory), otherwise "copy". This is
    Finder's and Explorer's default.
  - "link" is refused.
  - Both panes relist afterwards.
  - Drag-out now offers `("copy", "move")`. On a reported "move" both panes
    relist, because Finder performs that move itself.
- **`PaneHeader`**: `_breadcrumbs(text, path, pad_x, measure)` matches the
  components of the drawn, possibly abbreviated text (split on `/` and `\`)
  to the directories up `Path.parent`, starting from the right.
  - A component containing `…` is skipped.
  - A leading separator is the root.
  - Clicking goes there with the cursor on the child.
- **`PaneFooter`** records the x ranges of the sort description and the filter
  in the drawn text (when they survived eliding), and runs `sort` / `filter`
  when they are clicked.
- **`StatusBar`** builds each file-list hint with its action as the run
  and keeps the targets of the last draw. A click runs the action, but not
  while a modal is up (the bar is then empty). The search's line presses its
  keys. On a session's screen it shows the session's parts
  (`XeFMApp._session_status_parts`: a terminal's keys run through its view's
  actions; a drawn conversation's `ChatView.status_parts` run what each key
  does - send, stop, cycle the mode, type `/` or `@`); a part that only says
  something is a note and is not a target.
- **Every key line is one model** (`xefm/hint_bar.py`): the file manager's
  status bar, a session's screen, a viewer's status bar
  (`text_viewer.draw_status_bar`) and a dialog's hint band
  (`dialog_geometry.draw_hint_row`) all build their line as `Hint` parts -
  `key(display, label, run=None)` for keys, `note(text)` for counts and
  states - and draw it with `draw_hints`. The key is drawn in the full text
  colour (bold on a vector backend), the words muted, parts `GAP` (two
  cells) apart; a part that does not fit is cut with an ellipsis and ends the
  line. `draw_hints` returns `HintHit` targets: a part of one key over its
  whole text, each key of a pair (`q/Esc`) or arrow cluster (`Shift-↑↓←→`) on
  its own, a note never. A target runs its key's `run` (a file-list action,
  a session's callable) or, with none, presses the key: the key event is
  handed to the widget (`click_hint`, called first in each viewer's and
  dialog's `handle_event`) or, from the window's status bar, to
  `panel.dispatch_event` - so a click does what the key does under any
  keymap. `hints_text` is the plain form (parts two spaces apart) for sizing
  (`hints_width`) and tests.
- Under the pointer each of these - a hint, the footer's sort and filter, the
  file clipboard's part of the status bar, a name in a pane's path (measured
  in the bold it is drawn in, as its click is) - shows it can be clicked
  (`hint_bar.hover_part`, #1019 hand check): a backing behind it (rounded on a vector
  backend, its cells on a grid), its text in the full text colour inked for
  the backing, and the pointing-hand cursor. The backing is
  `tab_strip.hover_backing`: the bar's colour moved toward the text until its
  lightness is `HOVER_SEPARATION` from the bar as seen (translucent over a
  scene) - a fixed mix was lost on some themes. `ctx.pointer_in` makes the bar redraw as the pointer
  comes and goes.

## Deferred (discussion §§3, 6)

- Right-drag menu (needs right-button drag in PuiKit).
- Rubber-band selection.
- Mouse gestures as bindings — whether they would join `KEY_BINDINGS` or get
  a separate setting of their own (no such setting exists yet).
- A click on the StatusBar's clipboard area (#578 is not merged).

## Tests

- `test/test_mouse_operation.py`:
  - the FilePane gestures: modifiers and click count, a drag breaking a
    double-click, middle and side buttons, scrollbar paging and thumb drag;
  - breadcrumbs;
  - app behavior: toggle, range, plain click keeping marks, double-click,
    modified double-click, middle-click, back/forward, forward cleared, drop
    defaults, copy modifier, link refused;
  - the clickable status hints, footer sort and header crumbs.
- `test/test_drag_and_drop.py` was updated for the operations now offered and
  the new callback arguments.
- puikit `tests/test_mouse_modifiers.py` covers the drop rules, SGR side
  buttons, and the macOS view's modifiers, Control-click and other buttons.

## Hand checks owed

- **Windows:** modifiers on clicks, the X buttons, and Explorer drop modifiers
  — none of this was run here.
- **macOS:** Cmd/Option drops from Finder, and a pane-to-pane move.
- **Terminals:** which ones pass Shift-click and the side buttons.
