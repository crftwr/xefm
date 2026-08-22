# Image Viewer — Implementation

The built-in image viewer (`xefm/image_viewer.py`) is the fourth full-window
modal viewer, after text / file diff / directory diff. This note covers the
parts that are not obvious from the source: where zoom and pan actually happen,
how a terminal ends up drawing pixels at all, and which pieces landed in PuiKit
rather than here.

User-facing behavior is in `doc/IMAGE_VIEWER_FEATURE.md`.

## Split across the two repos

Rendering is PuiKit's job (per `CLAUDE.md`), so the work divides:

| Layer | Piece |
|-------|-------|
| PuiKit | `image.zoom_window()` — zoom + pan center → normalized source window |
| PuiKit | `src` hint on `draw_image` — the crop the backend samples |
| PuiKit | `backends/_terminal_graphics.py` — kitty / iTerm2 / sixel |
| PuiKit | `CursesBackend` phase-3 image emission; `images` capability |
| PuiKit | `DrawContext.images` — lets a widget pick a richer fallback |
| XeFM | `xefm/image_viewer.py` — the modal, state, keys, chrome, navigation |
| XeFM | dispatch in `xefm/app.py`, bindings + associations in `_config.py` |

## Zoom and pan are geometry, not pixels

The viewer never re-encodes an image to zoom. It holds three numbers — `zoom`,
and a pan center `cx`/`cy` in normalized image coordinates — and turns them into
a destination rect + source crop each frame (`_draw_image` / `_fill_geometry`),
the *scaled-image-clipped-to-the-client-area* model that real viewers (Preview,
browsers) use. The image is scaled by *fit-scale × zoom*; the visible intersection
with the body is the destination and the matching image region is the `src` crop,
drawn `fit="fill"`. One code path covers every zoom level:

- **Fit (`zoom == 1`)** — the destination is the whole image's contain box,
  **centered** in the body (`src = (0, 0, 1, 1)`), so the letterbox splits evenly.
- **Zoomed (`zoom > 1`)** — the box grows to cover the body, so the image fills
  the client area instead of floating in a letterbox.

```python
(dx, dy, dw, dh), src = self._fill_geometry(body_w, body_h, base_w, base_h)
ctx.draw_image(x + dx, y + dy, self._local,
               hints={"w": dw, "h": dh, "fit": "fill", "src": src, "alt": "🖼"})
```

Centering matters on TUI specifically: a terminal places a letterboxed image at
the **top-left** of its cell box, so a plain `fit="contain"` would leave all the
empty space at the bottom. Driving the fit level through `_fill_geometry` too puts
the picture in a centered destination box, so the blank cells split top and bottom.

Centering the box is only half of it, though: the image also has to *fill* that
box, or the terminal's own scale-to-fit re-introduces a within-box letterbox at
the bottom (the box is centered, but the picture floats to the top of it). So
`_terminal_graphics.render()` resizes a cropped image to the box's pixel size
**exactly** (the `src` crop already matches the box aspect, so this is not a
distortion), and the protocol is told to *stretch* rather than re-fit — iTerm2 via
`preserveAspectRatio=0`. The image then fills the centered box, and the only
residual is the ≤1-cell rounding of the box onto the grid (a character cell cannot
be split). GUI is unaffected — it never routes through `render()`.

### Why the clipped-to-viewport model (and not a fixed contain box)

The obvious first cut — always `fit="contain"` with a `zoom_window` source crop —
looks right but **wastes the client area when zoomed**: `contain`'s destination
box is aspect-locked to the *whole image*, so a wide image in a near-square window
stays letterboxed top-and-bottom no matter how far you zoom; zooming only crops
the source inside that fixed box. Real viewers (Preview, browsers) instead grow
the image as you zoom until it overflows the window and *fills* it, and that is
what `_fill_geometry` reproduces: at `zoom 1` the destination is the contain box
(letterbox), and as zoom rises the destination expands to cover the body — the
letterbox shrinks continuously and disappears once the image overflows that axis.

`_fill_geometry` works in **device pixels** — base units × `ctx.base_pixel_size`
— because a base unit is not square, so the aspect ratio is only correct in pixel
space. Destination and source stay proportional (the image is uniformly scaled),
so `fit="fill"` draws them undistorted.

It reads `ctx.base_pixel_size`, **not** `ctx.base_size`. On GUI the two agree (a
cell's point dimensions). On TUI `base_size` is `(1, 1)` — the grid's layout unit
— but a terminal cell is ~1:2 (tall), so a square-cell assumption computes a
wrong-aspect crop; the terminal-graphics `render()` then preserves that aspect
inside the cell box and letterboxes it, leaving a blank band (a real bug: the
image filled only the top of the client area). `base_pixel_size` reports the
cell's true pixel size (from `TIOCGWINSZ`, nominal `8×16` when the terminal is
silent), so the crop matches the cell box and the terminal fills it. Now exact on
both GUI and TUI.

The `TIOCGWINSZ` division is **fractional** (`_terminal_graphics.cell_pixels`).
`ws_ypixel` is rarely an exact multiple of the row count, and integer-dividing
(e.g. `1290 / 80 = 16.125 → 16`) drops a pixel per row: a couple of blank rows at
the bottom of a tall image, and a cell aspect that no longer matches the
emulator's own, so it re-letterboxes what should fill. Keeping the fraction makes
the scaled image line up with the real cell grid — the fix for "1–2 rows of white
space when zoomed in".

### `src` is normalized, not pixels — and why

`src` is **normalized fractions** (`0..1`, top-left origin), not pixels. That is
not cosmetic: a backend does not measure an image in the units the caller thinks
in. A macOS `NSImage.size()` returns *points* derived from the file's DPI, so a
Retina 2422×1610 image reports **1211×805** — half. Direct2D and Pillow use true
pixels. A pixel-space crop computed against 2422×1610 is therefore off by 2× on
macOS: the source rect lands twice the size of the image and offset off its
bottom edge, and Cocoa draws only the top-left overlap — the picture renders
tiny in the top-left corner. (This was a real bug during development; the
symptom is that exact.)

Normalizing sidesteps it entirely: each backend multiplies the fractions by *its
own* measured size — points on macOS, pixels on Direct2D and Pillow — so the DPI
gap never leaves the backend. Two per-backend details remain: **Cocoa's source
rect is bottom-left origin**, so a top band `(y, h)` maps to `(1 - y - h)` from
the bottom; Direct2D and Pillow are top-left, unflipped.

The fit level still sends `src=None` (plain whole-image path, no source rect to
get wrong); the `src` crops in the zoomed path are computed by `_fill_geometry`.

### The pan center must be clamped to its *reachable* range

The pan step is divided by the zoom (`_pan_by`), so one keypress covers roughly
the same share of the *visible* extent at every zoom. `_clamp_center` then keeps
`cx`/`cy` within the range the client area can actually **reach**, using the
client-area geometry cached at the last draw (`self._view`):

- An axis the displayed image does **not** overflow (`dw <= bw`) cannot pan, so
  the center pins to `0.5` (centred).
- An axis it does overflow pans within `[k, 1 - k]`, where `k` is half the
  visible fraction of the image on that axis.

Clamping to the full `0..1` was a bug: panning past a border kept incrementing an
unreachable center (e.g. `cx` climbing to `1.0` while the view stopped moving at
`cx = 0.75`), so reversing direction moved *nothing* until the value wound back
into range — several dead keypresses. `_clamp_center` also runs after a zoom
(zooming out shrinks the reachable range and can strand a center that was valid
higher in), and at the fit level it re-centers unconditionally (nothing to pan).
Because the clamp reflects the true reachable range, the displayed image always
*slides* to an edge rather than shrinking — the zoom level survives a pan into a
corner (`test_pan_at_an_edge_keeps_filling_the_client_area`).

## The post-effect is suspended while a picture is up

On a CRT / Pip-Boy theme the post-effect is a full-view Core Image content
filter (see `MacOSBackend._apply_post_effect`), so it would tint the image and
lay scanlines over it — the picture would not be shown faithfully. Per-region
exemption is not feasible with a whole-layer filter, so `XeFMApp._open_viewer`
**suspends** the effect (`set_post_effect(None)`) when it opens a picture and
restores it on close through the viewer's `on_close` hook
(`_restore_post_effect`). It is a no-op for themes without an effect and on
terminals (where `set_post_effect` no-ops), so it never branches on the backend.
The modal swallows the theme-toggle key, so the effect can't change while the
viewer is up and a plain save/restore is safe.

## Images in a terminal

A character grid has no pixels, and XeFM's curses backend has a hard **256
color-pair ceiling** (`CursesBackend._color_pair`), so the half-block-mosaic
approach is a non-starter: a 60×30 image region wants ~1800 distinct (fg, bg)
pairs and would degrade to nearest-pair mush while starving the rest of the UI.

Instead the backend uses the emulator's **inline-image protocol**, which puts
real pixels on screen out-of-band, entirely outside the grid.

### Where it hooks in

`CursesBackend.present()` already had a two-phase shape for color emoji: commit
the text grid, `refresh()`, then overlay the deferred glyphs as isolated writes.
Images ride the same seam as **phase 3**:

1. `draw_image()` records a placement — it emits nothing.
2. `present()` commits text and emoji as before.
3. `_present_images()` writes the escape sequences last.

Ordering is the whole point: a `refresh()` after the pixels would paint grid
cells back over them. Nothing may follow phase 3.

### Erasing

Curses' diff refresh only resends cells whose `(glyph, pair#)` changed — it
cannot know pixels were painted over its grid, so it will never clear an image
on its own. `_present_images` therefore diffs this frame's placements against
last frame's and erases the stale ones:

- **kitty** has a real delete verb (`a=d,d=i,i=<id>`), keyed by a stable image
  id assigned in draw order.
- **iTerm2 / sixel** have none, so the backend forces `redrawwin()` and lets the
  repainted text cells overwrite the image. `_terminal_graphics.clear()`
  returning `""` for these is a real answer, not a stub.

Unchanged placements are left alone — retransmitting a few hundred KB per frame
would make panning crawl.

`close()` also erases: images live outside the grid, so `endwin()` does not take
them with it and they would otherwise be burned into the shell's scrollback.

### Detection

`detect_protocol()` reads **environment variables only** — `KITTY_WINDOW_ID`,
`KONSOLE_VERSION`, `TERM_PROGRAM`, then `TERM` substrings. The obvious
alternative, a Device Attributes query (`\x1b[c`), means writing to the tty and
blocking on a reply that a non-supporting emulator never sends: a startup hang
risk inside curses' raw mode, for a cosmetic capability. `PUIKIT_TERM_GRAPHICS`
overrides in both directions (a protocol name, or `none`).

When a protocol is found the backend flips `images: True` in its capability
profile, so `Panel.draw_image` stops substituting the alt glyph and the same
widget code renders pictures on curses and GUI alike.

### Escapes must reach the real terminal, not a redirected `sys.stdout`

The first reason images never appeared in iTerm2: **XeFM replaces `sys.stdout`**
with a `LogCapture` shim (`xefm.log_manager`) that routes writes to its log pane
and *never forwards them to the tty*. An image escape has no newline, so the
shim's line-buffer holds it forever — the picture simply never renders (and the
same swallowing hit kitty, sixel, OSC 52 clipboard, and OSC 22 pointer).

So `CursesBackend` writes every out-of-band escape (mouse tracking, pointer
shape, clipboard, **images**) through `self._raw_out`, captured once at
construction from `sys.__stdout__` — the interpreter's original stream, which no
host reassigns — not the live `sys.stdout`. `test_terminal_graphics.py`'s
`test_images_go_to_the_real_terminal_not_a_redirected_stdout` pins it: with a
swallowing shim installed as `sys.stdout`, the image still reaches the terminal.

This is the diagnostic hook's main use, too: `PUIKIT_TERM_GRAPHICS_DEBUG=<file>`
traces detection → each placement → each emission with byte counts, and
`tools/diagnose_terminal_graphics.py` emits the protocol directly (bypassing
curses) to separate an encoding problem from an integration one.

### Cursor drift (why iTerm2 showed nothing)

kitty keeps the cursor put (`C=1`); iTerm2 and sixel have no such option and
**advance the cursor when they draw**. Left unchecked, an image low on the
screen scrolls the alternate screen and pushes the picture out of view — which
presents as "no image appears at all." So `_present_images` brackets the whole
batch in DECSC/DECRC (`\x1b7` … `\x1b8`): save the cursor curses positioned,
draw, restore it. Each image is addressed absolutely (`\x1b[row;colH`), so one
image's drift never offsets the next and a single save/restore covers the batch.

Do **not** send `doNotMoveCursor=1` to iTerm2 — it is not a real `File` argument
(it was a mistaken port of kitty's `C=1`), and sending it stopped iTerm2
rendering the image entirely. Only the documented args go out: `inline`, `size`,
`width`, `height`, `preserveAspectRatio`.

### Sixel

kitty and iTerm2 both accept a PNG payload, so those encoders are mostly
base64 plus framing. Sixel has no such luxury and is encoded by hand in
`_sixel()`: six vertical pixels per band per byte, one pass per palette color
within a band (`$` returns to column 0 to overlay the next color, `-` advances
the band), run-compressed with `!<count>`.

Because a hand-written encoder can look well-formed and still render garbage,
`test_terminal_graphics.py` decodes the output back to pixels and compares them
to the source (`test_sixel_round_trips_to_the_original_pixels`).

## Pillow

Pillow is a **hard** dependency of the XeFM viewer's picture rendering and an
**optional** one for PuiKit:

- It crops (`src`), scales to the target's pixel box, and re-encodes to the wire
  format — the terminal protocols have no backend-side source rect, so the crop
  must be applied before transmission.
- Scaling happens before transmission so the payload is proportional to the
  screen box, not the file: a 24-megapixel photo ships as a few hundred KB, and
  zooming re-crops from the original rather than upscaling a downscaled copy.
- `_terminal_graphics.detect_protocol()` returns `None` when Pillow is missing,
  so the capability never turns on and the alt-glyph path stands.

The viewer degrades to its metadata card rather than failing.

## The metadata card

`ctx.images` (added to `DrawContext` for this) tells the viewer whether a
picture can be drawn. Where it cannot, `_draw_card` centers the format,
dimensions, size, and the reason. This is why the viewer reads `ctx.images`
directly, against the usual rule that widgets should not branch on capability:
the Panel's fallback is a single centered glyph, and "opening an image tells you
nothing about it" is a worse outcome than a small, deliberate branch.

`_hint()` and the header follow suit — zoom and pan hints are omitted where
there is no picture, and prev/next where there are no siblings.

## Navigation and the sibling list

`XeFMApp._open_viewer` filters the pane's `files` through `is_image_file` and
hands the result plus the index to `show_image_viewer`. Two deliberate choices:

- **`pane["files"]`, not a fresh listing.** It is already sorted and filtered by
  `xefm.file_list_manager` — the single choke point — so the viewer walks exactly
  what the user sees, in their order.
- **A snapshot, not a live reference.** The file monitor mutates `pane["files"]`
  in place on refresh, which would shift the index under an open viewer.
  `ImageViewer.__init__` copies the list; `test_sibling_list_is_snapshotted_not_referenced`
  pins it.

The constructor also re-derives the index from the path when the caller's index
disagrees, so a stale index cannot land the viewer on a different file.

Moving to another image resets zoom and pan — carrying a 20× crop across would
open the next file on an arbitrary corner of it.

## Non-local images

`draw_image` and Pillow both take a filesystem path, which an S3 / SSH /
in-archive `xefm.path.Path` does not have. `_resolve()` materializes those via
`read_bytes()` into a temp file for the life of the viewer, released on
navigation and on close. Failures are recorded in `_error` and shown on the card
rather than raised — one corrupt file should not make a directory unbrowsable.

## Dispatch and config

- `xefm/app.py` routes on `is_image_file` in `_open_viewer`, and the binary guard in
  `_enter_file` now exempts images (they *are* binary, but there is finally
  something that renders them). That guard's comment had predicted this seam.
- `_config.py` gains an `image_*` binding block. `-` and `_` intentionally share
  with `reset_pane_boundary` / `reset_log_height`: those are file-list-only, and
  each context matches its own action *by name* through `is_action_for_event`,
  the same pattern `text_viewer.toggle_wrap` uses to share `W`.
- `_pressed()` falls back to literal characters when an action is absent from
  `KEY_BINDINGS`, so a config merged from a template older than this viewer
  still works — mirroring `TextViewer._wrap_pressed`. Note the `[0]`:
  `get_keys_for_action` returns `(keys, selection_requirement)`, and testing the
  tuple's truthiness instead of the key list silently disables the fallback.
- The shipped `FILE_ASSOCIATIONS` image entry changed from `'open|view'` to
  `'open'` + `'view': None`, so `V` reaches the built-in viewer while
  `open_with_os` still hands off to Preview. **Existing user configs keep the
  old association** and will keep opening Preview until edited.

## Testing

`test/test_image_viewer.py` (41 tests) covers the file-type claim, zoom/pan
arithmetic and clamping, navigation and its snapshot semantics, the hints that
reach the backend, the TUI metadata card, modal behavior, app-level dispatch,
and remote-file materialization. Drawing is asserted against `MemoryBackend`
under both `PROFILE_TUI` and `PROFILE_GUI_DESKTOP`.

On the PuiKit side, `tests/test_terminal_graphics.py` and the additions to
`tests/test_image_widgets.py` cover detection, crop/scale, the three encoders,
and the sixel round-trip.

```bash
python -m pytest test/test_image_viewer.py -v
(cd ../puikit && pytest tests/test_terminal_graphics.py tests/test_image_widgets.py -v)
```

Note that `test/test_image_viewer.py` binds `import xefm` at module scope. Both
the repo root and `test/` are packages, so once pytest prepends the repo's
*parent* to `sys.path`, a later `import xefm` resolves to the repo directory's
`__init__.py` instead of the `xefm/app.py` app entry.
