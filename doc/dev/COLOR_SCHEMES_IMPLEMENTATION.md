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
focused-inactive variants, all vestigial: the file-type slots have had no reader
since the panes moved to the theme palette below, and `get_file_color()` — which
was the only one — is gone), `COLOR_HEADER` / `COLOR_FOOTER` / `COLOR_STATUS` /
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

## The file-type palette

`extras['file_types']` is what actually colors a filename, read by
`FilePane._type_fg()` in `xefm/file_pane.py`. Three type entries, resolved in
this order:

- `link` — a symlink wins over a directory, so a link *to* a folder still reads
  as a link (default: cyan, the `ls` convention).
- `directory` — default a soft yellow. The legacy flat `extras['directory']` is
  still honored as a shorthand, with an explicit `file_types` entry winning.
- `file` — default the theme's own `text`.

There is deliberately **no executables entry**. The pane's types are the ones
every platform has; Windows has no execute bit, so an executables color would
decay into a hardcoded extension list on one platform and a mode check on the
other (issue #354). The old `colors.py` slot named above is what the feature doc
used to promise, and neither has painted a pane in a long time.

### `hidden` is a treatment, not a fourth type

A hidden entry is still a directory or still a link — the property is orthogonal
to type, so giving it its own color would mean a second entry per type and a
2×N palette that grows every time a type is added. Instead `_type_fg()` resolves
the type color first and then, for a hidden entry, washes it toward the pane
background by `HIDDEN_DIM` (0.40). A resting pane's own wash (`extras['pane_dim']`)
applies on top of that, toward the same background, and `ctx.ink` floors the
result once at the draw site.

### The wash, and the one floor under it

A hidden name is `_mix_oklab(color, bg, HIDDEN_DIM)` — a wash toward the pane
background, 0.40 by default — and nothing else. Washing toward the background is
what makes it read as hidden rather than as a second palette: it spends lightness
*and* chroma together, which is what the eye knows as faded.

The wash is perceptual, and that is not a detail. Blending gamma-encoded sRGB
toward a dark background spends lightness fast and leaves hue and much of the
chroma standing, so a faded orange arrives as a *dark orange*: Shinagawa's
directory gold, washed 40% toward its navy, kept chroma 0.079 of 0.147 and
rotated three degrees — a different shade rather than the same name, quieter.
Interpolating in OKLab lands the same lightness with a quarter less chroma
(0.059) and the hue six degrees further toward the background's. It is also what
"40% of the way to the background" is supposed to mean, OKLab being the space
where equal steps look equal. Neither ends up *blue* at 40% of anything; the
question is only how much color survives, and the sRGB answer was "too much".

Worth knowing for comparison: this is not alpha compositing, which happens in
linear light and would arrive lighter still — Shinagawa's gold at (207, 137, 76)
rather than (152, 115, 90). A hidden entry is faded further than 40%
transparency would fade it.

Under it sits `HIDDEN_LC` (Lc 30), a backstop rather than a design level. Names
and directories land clear of it (Lc 34–41 across the built-ins); it catches the
symlink hues, mid-luminance aquas that cross the line under a full wash, and the
two palettes whose own ink starts near their background. It cannot be the floor
a *visible* name gets: `LC_BODY` sits above where the wash lands — a dark
palette's text clears Lc 75 by a hair, Dark+ being at 78.7 — so applying it would
undo the wash entirely, handing back 206 grey for 212 grey.

An earlier cut did something far more elaborate here: wash only as far as the
floor allows, bisecting on `apca_lc`, so that the lift never ran and the hue came
through intact. That was scaffolding for the lift described in the next section,
and once the pane opted out of the lift it was not merely redundant but wrong.
Preserving chroma while darkening leaves a *deeper, more vivid* color, and vivid
reads as prominent — measured against a visible name that auto-ink had lifted
toward white, the hidden row was the louder of the two. Gruvbox's hidden
directory came out at chroma 0.127 against the visible row's 0.123, a difference
of nothing; the plain wash puts it at 0.110. Fading is supposed to cost chroma.

### There are two ink passes, and only one of them is the pane's

`ctx.ink` is the pane asking for a floor. `Panel.auto_ink` — which `XeFMApp`
turns on — is the framework applying one to *every* text run whose background is
concrete, at a weight-aware target that is `LC_BODY` for ordinary text. The
second pass does not know the first happened, so it lifted every faded name
straight back to body weight: Gruvbox drew hidden entries at (213, 209, 196)
against (235, 219, 178) for visible ones. Pale, not dim — the washing-out again,
one layer further down.

It skipped one row. A run drawing over a *transparent* background is left alone,
because the glyphs land on whatever the widget painted underneath and the widget
owns that contrast — and on a GUI backend the row that fills and then draws
transparently is the cursor row. So the fade survived under the cursor and
nowhere else, which is how this was reported: a hidden file under the cursor
drawn visibly darker than the hidden files around it.

The name run of a hidden entry therefore passes `ink=False`, PuiKit's opt-out
for "this widget owns this color deliberately". `TextAttribute.DIM` would also
have lowered the target (auto-ink floors dimmed text at `LC_MIN_NONTEXT`), but
it is a real attribute: the curses backend maps it to `A_DIM` and the terminal
would dim an already-faded color a second time.

The size and date columns opt out for the same reason, and had been wanting to
for longer: `_draw_row` inks them at `LC_LARGE` to sit a tier under the
filenames, and auto-ink had been raising them to body weight — Gruvbox's muted
(146, 131, 116) reached the row as (214, 208, 201), a hair off the filename's
own color — so a pane's numbers read as loud as its names, except on a GUI
cursor row. They now land where the pane put them: (191, 182, 172), Lc 60
against the name's 82. See `test_file_pane_column_weight.py`.

One thing follows for anyone testing a pane's colors: a `Panel` under test must
set `auto_ink = True` or it is not the app's pipeline. The version of this
feature that lifted every hidden name back to body weight passed a full suite
that had left it off.

Rendered across the built-ins, a hidden name reads 23 to 55 Lc below its visible
counterpart — the drop rather than the absolute, since a light palette starts at
Lc 104 and a 40% wash still leaves it high — keeps at least 58% of its chroma,
and holds at least 70% of the separation the visible types have from each other.

`test_file_pane_hidden_color.py` renders a pane per theme for all of this,
because none of it is visible from `_type_fg`'s return value — the arithmetic was
right in both broken versions. It also renders the cursor row on a
GUI-capable backend, the one place the two ink passes disagreed. One thing it
deliberately does not defend: the configured amount is a *ceiling*, not a
target. On the dark themes the floor
binds first (Dark+ reaches Lc 45 at a wash of 0.32, under the 0.40 default), and
a theme asking for less than the floor allows is the range where the knob means
anything.

`file_types['hidden']` overrides it in either of two spellings — a number (or
`False`) for a different wash, or an `(r, g, b)` that replaces the type color
outright for every hidden entry. The color form exists for the monochrome themes
(Phosphor, Segment LCD), which have no second hue to spend and would rather say
"hidden is this dimmer green" than fade a color they only have one of. It is
floored the same way, so it moves the hue freely and the lightness only down to
the quiet tier.

Where the flag comes from costs nothing: `dir_scan`'s per-entry record already
carries `hidden` for the hidden-files toggle (issue #284), so
`FileListManager._build_file_info()` just copies it into the display cache the
pane renders from — through `is_hidden()`, the same predicate the toggle filters
on, so "hidden enough to be filtered out" and "hidden enough to be faded" can
never disagree. Rendering issues no `stat`. The one exception is
`FilePane._info()`'s fallback for an entry missing from that cache, which was
already stat'ing and now also calls `is_hidden_path()`.

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
2. **The color rides on `Style.underline_color`** (PuiKit ≥ 1.5), which the VT
   backend emits as SGR 58 in the sub-parameter form `58:2::r:g:b` — and only to
   a terminal it recognizes as parsing sub-parameters at all
   (`vt_backend._supports_underline_color`, a whitelist). That whitelist is not
   caution for its own sake: macOS Terminal.app abandons the whole escape
   sequence at the first colon, which drops the underline attribute and the row's
   fg/bg with it, so the cursor row came out in the terminal's own default ink.
3. **The two spellings are exclusive, and chosen by capability.** PuiKit
   publishes that detection as `ctx.colored_underlines`, and `FilePane.draw`
   reads it into `ruled`. Where it is true the row is ruled and **no brackets are
   drawn**; where it is false the row is **not** underlined at all and the `[`
   `]` brackets are the cue. A colorless rule was the first fallback and it is
   the wrong one — it marks a row without saying which pane owns it, which is
   most of what the cue is for, while the brackets carry the cursor color in
   their own foreground on any terminal.
4. **The gutter is reserved either way** (`GUTTER_W` / `BRACKET_W`, one column
   per side), so which spelling a terminal gets never moves a pane's columns.
   `_draw_cursor` owns those two cells in both: the brackets, or — when ruled —
   underlined blanks, which is how the rule reaches past the content region and
   out to the row's ends. Neither carries a background: the gutter sits outside
   the row's fill, and a cell written with one would widen the selection tint on
   the cursor row alone.

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
- `xefm/file_pane.py` — `_type_fg()`, `HIDDEN_DIM`: the palette that colors filenames
- `xefm/file_list_manager.py` — `_build_file_info()`, the display cache the pane reads
- PuiKit `docs/color_system.md` — the modern theme / auto-ink color system
