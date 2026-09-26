# Screen Redraw Implementation

> **Historical.** This records the fix as it was made against XeFM's own
> renderer. Both halves have since moved into the external
> **[PuiKit](https://github.com/crftwr/puikit)** framework — the repaint
> plumbing (`puikit/backends/*`, `puikit/backend.py`) and the layer
> invalidation, which is `Panel`'s now — so the class and function names below
> no longer exist in XeFM. What survives is the reasoning, and one trigger: the
> **`redraw` action**, whose key lives in `KEY_BINDINGS`. There is no longer a
> key hardcoded outside the keymap.
>
> **And it stays a function key on purpose.** The goal is a UI that never needs
> asking: a repaint is the escape hatch for a screen something *else* wrote over
> (a multiplexer switch, a program that drew outside its lines), not a part of
> using XeFM. An action reached that rarely does not get to spend one of the
> scarce `Ctrl`+letter chords — see "Three cases" in `xefm/_config.py` for what
> that budget looks like.

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
   carrying `ModifierKey.CONTROL`. A `Ctrl`+letter key binding therefore could
   never match in terminal mode.

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

The trigger was routed ahead of the layer stack, so it worked in any context
(file list, dialogs, text/diff viewers). Two triggers existed: the `redraw`
action, and one key wired outside the keymap as a fallback for configs written
before the action existed.

**What is true now:** only the `redraw` action remains, resolved through
`KEY_BINDINGS` like everything else, and the repaint it asks for is PuiKit's. A
key wired outside the keymap could not survive the three-case split, and it does
not need to: the action takes as many keys as a config wants to give it, for
anyone whose terminal makes them reach for one.

## Tests

`test/test_keybindings_puikit_contract.py` covers the `redraw` action resolving
from the default keymap. The layer-invalidation and `force_repaint()` tests
listed here originally went to PuiKit with the code.
