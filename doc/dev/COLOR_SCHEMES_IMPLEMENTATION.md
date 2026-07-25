# Color Schemes Implementation

## Overview

XeFM's colors come from two layers today:

1. **`xefm/colors.py`** — a color-*pair* abstraction: a fixed catalog of
   named UI color slots, two built-in RGB palettes (`dark` / `light`), and the
   code that initializes those pairs on the active renderer. This is what this
   document describes.
2. **The modern multi-theme system** — the PuiKit `Theme` objects that the file
   panes, viewers, dialogs and chrome actually render against, and that the user
   cycles at runtime. It is summarized at the end and documented in depth by
   PuiKit; this doc does not restate its internals.

> The renderer passed to `init_colors()` is the active PuiKit backend renderer,
> which always supports full 24-bit RGB.

## What `xefm/colors.py` provides

### Named color-pair constants

The module defines integer constants for every semantic UI slot — e.g.
`COLOR_REGULAR_FILE`, `COLOR_DIRECTORIES`, `COLOR_EXECUTABLES` (with focused and
focused-inactive variants), `COLOR_HEADER` / `COLOR_FOOTER` / `COLOR_STATUS` /
`COLOR_BOUNDARY` / `COLOR_ERROR`, the log colors, the syntax-highlighting
colors, the search-highlight colors, the diff-viewer colors, the scrollbar
color, and the Matrix-animation colors used by the About dialog. Widgets refer
to slots by constant; `init_colors()` binds each constant to concrete RGB.

### Built-in palettes

`COLOR_SCHEMES` is a dict with two entries, `'dark'` and `'light'`. Each maps
role names (`HEADER_BG`, `DIRECTORY_FG`, `DEFAULT_FG`, `DEFAULT_BG`, the syntax
roles, the diff roles, …) to a definition of the form:

```python
'DIRECTORY_FG': {
    'color_num': 101,          # vestigial; not used by the renderer
    'rgb': (204, 204, 120),    # the value actually applied
}
```

Only the `rgb` tuple (0–255 per channel) is consumed — `color_num` is a leftover
from the curses era and is inert.

### `init_colors(renderer, color_scheme=None)`

Binds every color-pair constant on the renderer:

1. Optionally switch the current scheme (`color_scheme`).
2. `renderer.set_fullcolor_mode(not force_fallback_colors)` — turn full RGB on
   unless fallback mode is forced (see below).
3. `renderer.clear_color_cache()` — required so re-initialization takes effect
   when the palette changes.
4. `renderer.update_background(default_bg)` — set the terminal/canvas background
   so blank areas match the palette.
5. `renderer.init_color_pair(constant, fg_rgb, bg_rgb)` for each slot, reading
   the RGB values out of the current scheme.

In the live app `init_colors()` is called to (re)establish the color pairs after
an external program or sub-shell returns (see
`xefm/external_programs.py`), restoring them after the child process.

### Accessor helpers

Widgets fetch a slot plus attributes rather than raw numbers. Each helper
returns a `(color_pair, attributes)` tuple, where `attributes` is a
`puikit.TextAttribute` (`NORMAL`, `BOLD`, `UNDERLINE`, `REVERSE`):

- `get_file_color(is_dir, is_executable, is_focused, is_active)`
- `get_header_color(is_active)`, `get_footer_color(is_active)`,
  `get_status_color()`, `get_error_color()`, `get_boundary_color()`
- `get_log_color(source)`, `get_line_number_color()`
- `get_syntax_color(token_type)` (maps Pygments token types to a syntax slot)
- `get_search_color()`, `get_search_match_color()`, `get_search_current_color()`
- `get_scrollbar_color()`, `get_background_color_pair()`,
  `get_color_with_attrs(color_pair)`

These log/status helpers are the primary live consumers of `xefm.colors`
(`xefm/log_manager.py`, `xefm/logging_handlers.py`).

### Scheme management

- `get_available_color_schemes()` → `['dark', 'light']`
- `get_current_color_scheme()` → the active scheme name
- `set_color_scheme(name)` — switch scheme (raises on an unknown name); call
  `init_colors()` separately to apply it
- `toggle_color_scheme()` — swap `dark` ↔ `light`, returning the new name

Note the live "Next Theme" / `T` action does **not** call
`toggle_color_scheme()`; it cycles the PuiKit `Theme` system (below). These
dark/light helpers are the legacy pair-layer switch.

### Reduced-color terminals

There is no `FALLBACK_COLOR_SCHEMES` dict — RGB is always the source of truth.
`init_colors()` calls `renderer.set_fullcolor_mode(True)` and the backend
approximates the RGB values on a terminal with a reduced palette.

## The modern multi-theme system (high level)

The palettes the user actually cycles at runtime — the "Next Theme" menu item
and the `toggle_color_scheme` (`T`) key — are PuiKit `Theme` objects, **not** the
`dark`/`light` pairs above. In `xefm/app.py`:

- `_THEME_SPECS` is the list of built-in palettes (Dark+, Monokai, Dracula,
  Nord, Solarized, Gruvbox Dark, and more), each a small keyword spec.
- A helper builds each spec into a PuiKit `Theme` via `derive_theme`, merging any
  user overrides from `~/.xefm/config.py`.
- Themes carry app-specific colors and per-theme *effects* in `Theme.extras`
  (post-processing looks like CRT/phosphor, background animations/wallpaper,
  surface opacity, pane-focus chrome, text-entrance effects), which `XeFMApp`
  pushes to the backend on theme switch — a GUI backend honors them, a terminal
  ignores them.
- PuiKit applies **auto-ink** legibility on top: foreground inks are corrected
  against their background so low-contrast palettes stay readable.

Because that system is owned by PuiKit and is largely theme *data* at a
framework seam, the authoritative reference is PuiKit's `docs/color_system.md`
(in the separate PuiKit repo). For how per-theme motion/effects are wired on the
XeFM side, see [MOTION_IMPLEMENTATION.md](MOTION_IMPLEMENTATION.md); the built-in
palettes themselves live in `_THEME_SPECS` in `xefm/app.py`.

## Related Files

- `xefm/colors.py` — color-pair constants, `dark`/`light` palettes, `init_colors`, accessors
- `xefm/log_manager.py`, `xefm/logging_handlers.py` — live consumers of the log/status colors
- `xefm/external_programs.py` — re-initializes color pairs after a subprocess
- `xefm/app.py` — `_THEME_SPECS` and the PuiKit `Theme` wiring (modern theme system)
- PuiKit `docs/color_system.md` — the modern theme / auto-ink color system
