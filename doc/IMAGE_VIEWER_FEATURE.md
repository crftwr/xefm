# Image Viewer

XeFM has a built-in image viewer. Put the cursor on an image and press **V** (or
**Enter**) to open it full-window, with zoom, pan, and navigation to the other
images in the same directory — without leaving XeFM.

## Opening

| Key | What it does |
|-----|--------------|
| `V` | View the focused file — an image opens in the image viewer |
| `Enter` | Same, for a file with no other `enter` rule |

Recognized formats: PNG, JPEG, GIF, BMP, WebP, TIFF, ICO, TGA, and the netpbm
family (PPM/PGM/PBM/PNM).

## Keys

| Key | Action |
|-----|--------|
| `+` / `=` | Zoom in |
| `-` | Zoom out |
| `0` | Fit the whole image to the window |
| `↑` `↓` `←` `→` | Pan (while zoomed in) |
| mouse drag | Pan |
| mouse scroll | Zoom in / out |
| `n` | Next image |
| `p` | Previous image |
| `Home` / `End` | First / last image |
| `?` | Key help |
| `q` / `Esc` | Close |

Zoom starts at *fit* — the whole image in the window — and each step magnifies
by 25%, up to 40×. Panning past an edge stops at the border rather than
dropping your zoom level, and zoom and pan reset when you move to another image.

The header shows the file name, its position in the list (`2/7`), pixel
dimensions, file size, and the current zoom while you are zoomed in.

## Prev / next navigation

`n` and `p` walk the **images in the pane you opened the viewer from**, in the
order shown there — so your sort order and filters carry into the viewer, and
non-image files are skipped. The list wraps at both ends.

The list is fixed when the viewer opens, so a background directory refresh
cannot shift it under you. Close and reopen to pick up new files.

## CRT / Pip-Boy themes

On a theme with a screen post-effect (glow, scanlines, bloom), the effect is
suspended while an image is open so you see the real pixels rather than a
filtered version of them. It returns automatically when you close the viewer.

## Terminal support

Terminals do not all display images. XeFM uses whichever inline-image protocol
your terminal speaks:

| Terminal | Protocol |
|----------|----------|
| kitty, Ghostty, WezTerm, Konsole | kitty graphics |
| iTerm2, mintty | iTerm2 inline images |
| foot, contour, mlterm, xterm (`-ti vt340`) | sixel |

In the **desktop app** images always render, whatever your terminal.

In a terminal without any of these protocols — Terminal.app and the VS Code
terminal, notably — the viewer shows a card with the format, dimensions and
file size instead of the picture. Navigation still works; zoom and pan are
hidden, since there is nothing to zoom. To view the picture itself, use a
terminal from the table above, run the desktop app, or press `Cmd-Enter` /
`open_with_os` to hand the file to your OS image viewer.

You can force or disable the protocol with the `PUIKIT_TERM_GRAPHICS`
environment variable (`kitty`, `iterm2`, `sixel`, or `none`) — useful when XeFM
guesses wrong, or inside `tmux`/`screen`, which intercept these sequences:

```bash
PUIKIT_TERM_GRAPHICS=none xefm     # never try to draw images inline
PUIKIT_TERM_GRAPHICS=sixel xefm    # force sixel
```

## Requirements

Decoding is done by [Pillow](https://python-pillow.org/), which ships with XeFM.
If it is somehow missing, the viewer still opens and still navigates, but shows
the metadata card instead of the picture.

## Remote and archived images

Images on S3 or over SSH, and images inside an archive, open like any other —
their bytes are fetched to a temporary file for the life of the viewer and
removed when it closes.

## Opening in an external viewer instead

By default `V` uses the built-in viewer and `Cmd-Enter` (`open_with_os`) hands
the file to your OS app. To send `V` to an external program too, point the
`view` entry at it in your config's `FILE_ASSOCIATIONS`:

```python
FILE_ASSOCIATIONS = [
    {
        'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif'],
        'open|view': ['open', '-a', 'Preview'],   # V leaves XeFM again
        'edit': ['open', '-a', 'GIMP'],
    },
]
```

Setting `'view': None` (the default) selects the built-in viewer.

> **Upgrading:** XeFM's shipped default used to send `view` to Preview. Your
> existing config keeps whatever it has — change that entry as above if `V`
> still opens Preview and you would rather stay in XeFM.

## Customizing keys

The zoom and navigation keys are rebindable in your config's `KEY_BINDINGS`:

```python
KEY_BINDINGS = {
    'image_zoom_in':    ['+', '='],
    'image_zoom_out':   ['-', '_'],
    'image_zoom_reset': ['0'],
    'image_next':       ['n'],
    'image_prev':       ['p'],
}
```

Arrow-key panning and `Home`/`End` are viewer-local and not rebindable, matching
the text viewer's scroll keys.

## See also

- `doc/dev/IMAGE_VIEWER_IMPLEMENTATION.md` — how it works internally
- `doc/TEXT_VIEWER_FEATURE.md` — the viewer for everything that is not an image
