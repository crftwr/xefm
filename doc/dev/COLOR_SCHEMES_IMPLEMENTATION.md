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

## The cursor cue

`extras['cursor']` (`active` / `inactive`) is the color of the *cursor row*
marker, kept orthogonal to the selection fill so the two never read as the same
channel. `xefm/file_pane.py` draws it two ways, because the two surfaces have
different room:

- **GUI** (`vector_shapes`): a rounded outline rectangle framing the row, drawn
  over the row fill (`_draw_cursor`).
- **TUI** (character grid): the `[` … `]` brackets in the reserved gutter
  columns **and a rule under the whole row**, both in the cursor color.

The rule was added for [#350](https://github.com/crftwr/xefm/issues/350): two
bracket characters at the far ends of a wide row are easy to lose, and their
color was the only thing separating the active pane's cursor from the resting
one's. Three details make it work on a grid:

1. **A blank run goes down first.** Each grid cell carries exactly one style, so
   an underline cannot be added to a row after its text is drawn, and the gaps
   *between* columns have no text of their own to carry it. `_draw_row` lays a
   run of underlined blanks across the content region, then draws the name / size
   / date runs underlined over it — one unbroken line.
2. **The brackets carry their own two cells.** The gutter is exactly one column
   on each side (`GUTTER_W` / `BRACKET_W`), so the bracket cue joins the rule up
   end to end rather than sitting outside it.
3. **The color rides on `Style.underline_color`** (PuiKit ≥ 1.5), which the VT
   backend emits as SGR 58 in the sub-parameter form `58:2::r:g:b`. A terminal
   without colored underlines discards that one parameter and still draws the
   rule in the text color, so the cue degrades to "underlined row" rather than
   disappearing. The blanks take the cursor color as their *foreground* for the
   same reason: on such a terminal the gaps still rule in it.

`--backend curses` draws the underline (curses `A_UNDERLINE`) but never its
color; the GUI backends are unaffected, since they keep the outline rectangle.

Choosing between the two shapes is a **known deviation** from PuiKit's rule that
a widget reads a capability only to drop a pixel-only ornament, never to switch
drawing models (its `docs/rendering_system.md` §5). `FilePane.draw` carries the
note at the `grid = not ctx.vector_shapes` line, the framework half — a missing
row-marker primitive — is §9.4 there, and every capability read in XeFM is
audited in [CAPABILITY_BRANCHING_AUDIT.md](CAPABILITY_BRANCHING_AUDIT.md). The color itself is *not* part of
the deviation: it travels as `Style.underline_color`, an intent each backend
resolves its own way.

### The resting pane's cue is colorless

`active` defaults to `CURSOR_ACTIVE` (a red). `inactive` has **no constant**: when
a theme names none, `_cursor_fg` derives a gray — `_neutral(theme.muted_text)`,
chroma removed in OKLab so the gray keeps the muted ink's *perceived* lightness,
then floored against the pane background at `LC_MIN_NONTEXT` (a rule and two
brackets are decoration, not text; `LC_LARGE` lands around 180 gray, bright enough
to compete with the focused pane).

It replaced a per-theme "muted version of the active color" — a dark red beside a
bright red, a dark amber beside a bright amber. That is one cue at two strengths,
and on a one-pixel rule the eye reads hue long before it reads strength, so the
two panes looked alike. Colorless makes them categorically different: color means
"you are working here". Deriving it from the theme (rather than one fixed gray)
keeps it at each palette's own quiet level, and the floor keeps a theme with very
dim muted ink (Nord) from hiding its resting cursor entirely.

Only **Segment LCD** still names an `inactive`, because a two-colour LCD panel has
no gray — and needs none, its near-black active cue being as far from mid-green as
that palette goes. A user's `config.py` names one the same way.

## Related Files

- `xefm/colors.py` — color-pair constants, `dark`/`light` palettes, `init_colors`, accessors
- `xefm/log_manager.py`, `xefm/logging_handlers.py` — live consumers of the log/status colors
- `xefm/external_programs.py` — re-initializes color pairs after a subprocess
- `xefm/app.py` — `_THEME_SPECS` and the PuiKit `Theme` wiring (modern theme system)
- PuiKit `docs/color_system.md` — the modern theme / auto-ink color system
