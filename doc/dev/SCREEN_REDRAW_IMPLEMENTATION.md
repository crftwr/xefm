# Screen Redraw (Ctrl-L) Implementation

> **⚠️ Partly historical (pre-PuiKit port).** The `force_repaint()` / backend
> plumbing referenced below (`ttk/backends/curses_backend.py`, `ttk/renderer.py`)
> moved to the external **[PuiKit](https://github.com/crftwr/puikit)** framework
> (`puikit/backends/curses_backend.py`, `puikit/backend.py`), where the API may
> differ. XeFM's redraw-trigger design still applies. See
> [PROJECT_HISTORY.md](PROJECT_HISTORY.md).

## Problem

When XeFM runs inside a terminal multiplexer (tmux/screen), switching away from
and back to the XeFM window leaves the screen blank or garbled. XeFM does not
repaint until some other event forces a redraw.

### Root cause

Two independent gaps combined to cause this:

1. **No force-repaint path.** The curses backend relies on curses' internal
   model of the physical screen and only transmits changed cells on
   `refresh()`. A multiplexer context switch alters the terminal contents
   behind curses' back, so curses still believes the screen is correct and
   sends nothing. XeFM's own UI layer stack adds a second layer of
   dirty-tracking on top, so even a full re-render would not re-send unchanged
   cells.

2. **Ctrl+letter never produced a CONTROL modifier (terminal mode).** In the
   curses backend, control bytes (1-26) were not translated into `KeyEvent`s
   carrying `ModifierKey.CONTROL`. A `Ctrl-L` key binding therefore could never
   match in terminal mode.

## Solution

### 1. Translate Ctrl+letter in the curses backend

`CursesBackend._translate_curses_key()` now maps control bytes 1-26 to
`KeyEvent(key_code=KeyCode.<letter>, modifiers=ModifierKey.CONTROL)`.

Bytes with established special-key semantics are intentionally excluded so
existing behavior is preserved:

| Byte | Key       | Reason for exclusion |
|------|-----------|----------------------|
| 8    | Ctrl-H    | Historically Backspace |
| 9    | Ctrl-I    | Tab |
| 10   | Ctrl-J    | Enter (line feed) |
| 13   | Ctrl-M    | Enter (carriage return) |

The CoreGraphics (desktop) backend already extracted the Control modifier from
`NSEvent` flags, so no change was needed there.

### 2. Renderer `force_repaint()`

A new concrete method `Renderer.force_repaint()` was added to the renderer ABC
with a default no-op implementation. Keeping it concrete (not abstract) avoids
breaking the many existing backends and test mocks.

- **CursesBackend** overrides it to call `stdscr.redrawwin()` followed by
  `refresh()`, which invalidates the curses screen model and re-sends every
  cell.
- **CoreGraphicsBackend** uses the default no-op: it always redraws from its
  character grid, so it has no stale physical-screen model to recover.

### 3. `UILayerStack.mark_all_dirty()`

Marks every layer in the stack dirty so the next `render()` re-renders the full
interface (header, panes, log, status bar, and any open dialogs/viewers).

### 4. `FileManager.force_redraw()`

Ties it together: invalidates the renderer's physical-screen model
(`force_repaint()`) and marks all UI layers dirty (`mark_all_dirty()`). The
next iteration of the main loop redraws everything.

### 5. Global key routing

`XeFMEventCallback.on_key_event()` intercepts the redraw shortcut before routing
to the layer stack, so it works in any context (file list, dialogs, text/diff
viewers). It honors two triggers:

- A **hardcoded `Ctrl-L`** trigger. This is intentional and permanent: Ctrl-L is
  the universal terminal convention for "redraw the screen", so it always works
  regardless of configuration (including for users whose `~/.xefm/config.py`
  predates this action — missing sub-keys of `KEY_BINDINGS` are not auto-merged
  into existing user configs). It cannot be disabled via config by design.
- The configurable `redraw` action (default `F5` in `_config.py`). Users can
  bind additional keys to the action without affecting the hardcoded Ctrl-L.

## Files changed

| File | Change |
|------|--------|
| `ttk/backends/curses_backend.py` | Translate Ctrl+letter (1-26) to CONTROL KeyEvents; add `force_repaint()` |
| `ttk/renderer.py` | Add concrete no-op `force_repaint()` to the ABC |
| `xefm/app.py` | Add `UILayerStack.mark_all_dirty()` |
| `xefm/app.py` | Add `FileManager.force_redraw()`; route Ctrl-L / `redraw` globally |
| `xefm/_config.py` | Add `redraw: ['F5']` default key binding (Ctrl-L is hardcoded separately) |
| `xefm/text_dialog.py` | Document Ctrl-L in the help dialog |

## Tests

- `ttk/test/test_curses_input_handling.py` — Ctrl+letter translation, reserved
  bytes preserved, `force_repaint()` behavior.
- `test/test_ui_layer_basic.py` — `mark_all_dirty()` marks all layers and
  triggers a full re-render.
- `test/test_redraw_action.py` — `Ctrl-L` resolves to `redraw`; default config
  binding present; `force_redraw()` invalidates the renderer and marks layers
  dirty (including the renderer-error path).
- `test/test_xefm_main_input_handling.py` — global handler routes both the
  hardcoded Ctrl-L fallback and a rebound `redraw` action to `force_redraw()`.
