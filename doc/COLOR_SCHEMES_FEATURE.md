# Color Schemes Feature

## Overview

XeFM ships a range of **themes** — palettes that look good in different terminal
environments, plus a few richer "screen" themes that pair a palette with a screen
effect and a moving background on the GUI backend. You switch between them at run
time; XeFM remembers the last one you chose.

This page covers the themes themselves, the animated backgrounds a theme can draw
behind the panes, and the motion (dialogs, text effects, pane-focus cues) that a
theme can turn on — including the single `REDUCED_MOTION` switch that quiets all
of it.

## Available themes

XeFM starts on **Dark+** and includes a set of standard palettes:

- **Dark+** (default) — dark backgrounds with bright colored text; yellow
  directories, green executables. Easy on the eyes in low light.
- **Light+** — white backgrounds with black text; high contrast, clean and
  professional. Good for light terminal backgrounds.
- **Monokai**, **Dracula**, **Nord**, **Solarized** (light and dark),
  **Gruvbox Dark** — popular editor palettes.

### Retro themes with screen effects

Beyond the standard palettes, XeFM ships four **screen** themes, each pairing a
palette with a recommended *screen effect*:

- **Sci-Fi** — a tactical-HUD look: soft cyan-white text on a deep navy, cool cyan
  chrome and a warm amber selection accent, behind a strong emissive bloom halo and
  glow with a vignette — no scanlines, no rolling glitch.
- **Cyber** — a data-wall look: dense cyan telemetry on near-black navy, amber for
  the things you need to find (cursor, i-search) and magenta for links, over a depth
  of [`hologram`](#background-animations) panels drifting toward you.
  Purely emissive — a strong bloom halo and glow, with no scanlines and no roll
  glitch, so it reads as a projected hologram rather than a tube being scanned.
  Filenames decode into place as they arrive.
- **Segment LCD** — a positive/reflective digital display: near-black "segments"
  on a sage-green base (just two colours), flat — no scanlines or glow — where the
  black segments (text) cast a soft drop shadow for an embossed LCD look.
- **Shinagawa** — a bay-at-night look: white text on a deep marine blue, over a lit
  [`wave`](#background-animations) sheet rolling past below. The chrome is
  a single blue-to-white ramp, but the content is not: directories are a warm orange
  (with i-search to match) and the text viewer gets a full spread of syntax colours,
  so the file list stays sortable at a glance against the moving water. Its only
  effect is a soft drop shadow on the text, which lifts the glyphs clear of the
  background. Text appears instantly; the water is the only thing that moves.

Select any of them from **View → Theme**.

The screen effect is composited over the whole frame and is only rendered by the
**desktop app** (macOS/Windows) — a terminal shows the
palette alone. The effect turns on when
you switch to the theme and off when you switch away. You can add your own themes
(with or without an effect) via the `THEMES` dict in `~/.xefm/config.py`; see
[Configuration](CONFIGURATION_FEATURE.md).

## What Gets Colored

Every theme changes:
- **File Types**: Different colors for directories, executables, and regular files
- **Selected Items**: Highlighting for selected files
- **Interface**: Headers, footers, status bar, and pane borders
- **Log Messages**: Different colors for different types of messages
- **Text Viewer**: Syntax highlighting when viewing code files
- **Search Results**: Highlighting for search matches

## How to Use

### Switch Themes

Pick a theme directly from **View → Theme** while XeFM is running. The change
happens immediately.

### Default Theme

XeFM starts on the **Dark+** theme and remembers whichever theme you last switched
to across restarts — there is no single default-scheme setting. To add or
customize themes, use the `THEMES` dict in `~/.xefm/config.py` (see
[Configuration](CONFIGURATION_FEATURE.md)).

### Assign a Theme Key

Cycling themes has no key by default. To cycle from the keyboard, bind
`toggle_color_scheme` in `~/.xefm/config.py`:

```python
KEY_BINDINGS = {
    'toggle_color_scheme': ['Y'],  # Pick any free key
    # ... other bindings
}
```

## Terminal Compatibility

XeFM automatically detects what your terminal supports:

- **Modern Terminals**: Get full 24-bit colors (millions of colors)
- **Older Terminals**: Get basic 8 or 16 colors (still looks good)
- **All Terminals**: Themes work everywhere (the screen effects and animated
  backgrounds are GUI-backend only — a terminal shows the palette alone)

## Background animations

A theme can draw a slow animated scene *behind* the file panes. The animation is
rendered under the whole UI and shows through wherever the interface is not fully
opaque, so it reads as a living wallpaper rather than as decoration on top of your
files.

Animations are drawn in **your theme's own colours** — the line colour comes from
the theme foreground and the backdrop from the theme background — so a scene stays
on-palette whichever theme (or custom palette) you use.

> **Desktop mode only.** Animations need real pixels. They are rendered by the
> desktop backend, on macOS/Windows. In a terminal there
> are no sub-cell pixels to draw into, so the setting is silently ignored and you
> simply get the theme's plain background colour.

### Available animations

| Name | What it looks like |
|------|--------------------|
| `starfield` | Stars streaming toward you out of a vanishing point, drawn as motion streaks that lengthen and brighten as they approach. |
| `rain` | Falling streaks with fading tails, each column at its own speed — the classic phosphor-terminal rain. |
| `constellation` | Slowly drifting points that link to their near neighbours, the links fading in and out as points pass. |
| `grid` | Flying down a wireframe corridor — floor, ceiling and both walls gridded, converging on a vanishing point that wanders as the camera slowly drifts and turns. |
| `wave` | A dense field of particles flowing over a rolling wave surface, with a colour gradient sweeping along it. |
| `datastream` | Horizontal telemetry traffic: layered rows of dashes streaming past at different rates, mostly short with the occasional long streak, each leading with a bright head and some ending in a small upright tick. Busy and quiet regions drift across the field. |
| `hologram` | A depth of holographic panels drifting toward you, each a small flat readout — pseudo-text that types itself out left to right, bar and line charts, progress bars, ring gauges, wireframe meshes — struck here and there with a warm accent. Panels fade up, hold and vanish on their own clock as the field flies slowly past, with a fine haze of distant ones behind, a few thick speed streaks raking outward from the vanishing point, soft out-of-focus dots and strokes drifting slowly across it all, and bright traffic — barcode bursts, dashes and dots — running fast along horizontal lanes. |

The UI toolkit's own `cube` (a spinning wireframe) also works. It exists as a
reference scene for the rendering path rather than as a finished look.

### Where they run

Every scene is a **GPU shader**, computed for each pixel on the graphics card.
That is what lets them be dense, use real colour gradients rather than a single
flat line colour, and cost almost nothing while XeFM sits idle — the graphics card
advances the scene behind the UI without XeFM having to redraw the interface.

They need **desktop mode**, on macOS or Windows. In a
terminal there are no pixels to draw into, so the `animation` key is ignored and
you get the plain theme background. The same is true on the rare desktop setup
with no usable GPU shader support.

### Turning one on

Animations are chosen per theme. Among the built-in themes, **Sci-Fi** ships with
the starfield, **Cyber** with the hologram and **Shinagawa** with the wave; select
one from **View → Theme**.

To use one in your own theme, add an `animation` key to a theme in the `THEMES`
dict in `~/.xefm/config.py`:

```python
THEMES = {
    'Deep Space': {
        'base': 'Dark+',
        'animation': 'starfield',
        'opacity': 0.6,          # let the scene show through the panes
    },
}
```

#### `opacity` — letting the animation show through

An animation is drawn *behind* the UI, so with a fully opaque interface you would
only see it in whatever gaps the layout leaves. The theme's `opacity` value (0–1)
controls how opaque the pane and row backgrounds are; lower it and the scene
becomes visible through them.

- `1.0` — fully opaque UI (default). The animation is essentially hidden.
- `0.6` — a good starting point: the scene reads clearly, text stays crisp.
- `0.3` — very translucent; atmospheric, but check legibility with your palette.

Text, outlines and dialog boxes always stay opaque, so lowering `opacity` does not
make the interface unreadable.

#### It fades away when you're not using it

An animation that ran forever would keep your machine busy — and drain the
battery — while you were reading something else. So it doesn't:

- After about 15 seconds without input, or as soon as XeFM loses focus, the
  animation **very gradually fades out**, taking a further 40 seconds or so to
  disappear. The fade is deliberately too gentle to notice — an abrupt cut would
  catch the eye as much as the movement does.
- It keeps moving at its normal speed the whole time it fades. It does not slow
  down as well: a scene visibly winding down *and* fading reads as two things going
  wrong at once, and the point of fading is that you never see it stop.
- What you are left with is the plain theme background. Every scene XeFM ships is
  pure motion — falling rain, streaming stars, a corridor being flown down — and a
  scene like that has no frame worth stopping on: freeze one and you get the drops
  and stars stranded wherever they happened to be, which reads as XeFM having hung
  rather than settled. Dissolving away leaves something the palette already has.
- The moment you press a key or move the mouse, it **eases back in**.
- It resumes from exactly where it stopped. Leave XeFM alone for an hour and the
  wave picks up where you left it, instead of jumping to wherever it "would have"
  been.

If your system's **reduce motion** setting is on, the scene stops but *stays* —
the fade would itself be motion, and you are still at the machine.

There is nothing to configure and no interruption to what you're doing — while
parked, XeFM uses no more power than it would with a plain background.

#### Tuning speed and strength

Give `animation` a dict instead of a name to adjust it:

```python
'animation': {'type': 'rain', 'speed': 1.0, 'opacity': 0.8},
```

| Key | Meaning |
|-----|---------|
| `type` | Which animation (see the table above). |
| `speed` | Motion-rate multiplier. `1.0` is the tuned look; XeFM's default is `0.6`. `0` freezes the scene. |
| `opacity` | How strongly the scene itself is drawn, 0–1. Not to be confused with the theme-level `opacity`, which is about the UI on top of it. |
| `color` | The colour the scene is built on, if you want something other than the theme foreground. Scenes anchor their own colouring on it rather than using it flat, so a scene with a gradient shifts with it instead of losing the gradient. |

All animations are deliberately slow and understated — they sit behind a working
file manager, so they are tuned to stay in the background rather than compete with
filenames for attention. Raising `speed` much above `1.0` works, but is likely to
be distracting during real use.

### Using an image instead

The background can be a static image rather than an animation — see the
`wallpaper` key in the theme documentation. A theme has one background: naming
both `wallpaper` and `animation` uses the wallpaper.

## Motion & text effects

XeFM animates a few things on a GUI backend — dialogs arriving, the Sci-Fi theme's
starfield drifting behind the UI — and marks which file pane has focus. This
section covers what you see and how to change it.

### Dialogs

Every modal (input prompts, the filter and favorites pickers, batch rename, the
text / diff / directory-diff viewers) enters the same way: it grows from 92% to
full size while fading in, decelerating sharply and gliding to a stop.

Pickers take 180 ms, full-screen viewers 140 ms — viewers are usually opened
deliberately, and a shorter beat keeps them from feeling like they lag behind the
keystroke.

In a terminal there is no compositing, so the same intent plays as two frames —
one inset frame, then the finished box. Nothing is lost; the beat is just
coarser.

### Arriving text (Sci-Fi)

Under the **Sci-Fi** theme, text types itself into place as it arrives: a file
pane filling in left to right when you enter a directory, a dialog's labels
doing the same as it opens, and **each new line in the log pane** as it is
written. Every other theme draws text plainly.

It fires when something *arrives* — a new listing, a dialog, a fresh log line.
It deliberately does **not** fire while you scroll, or when a status value ticks
over, so it never sits between you and something you are reading. Scrolling back
over log lines you have already read leaves them alone.

#### Choosing a different one

Five styles ship. Any theme can name one in your `config.py`:

```python
THEMES = {
    'Dracula': {
        'text_effect': 'scatter',   # or 'typewriter', 'decode', 'wipe', 'flicker'
        # ...or tune it:
        # 'text_effect': {'kind': 'typewriter', 'duration_ms': 300,
        #                 'stagger_ms': 8, 'max_rows': 120},
    },
}
```

- `typewriter` — characters appear left to right, nothing in the tail (the Sci-Fi default)
- `scatter` — characters land in **random order**, each straight into its final
  spot; nothing ever shifts sideways. Reads as a message materializing rather
  than being typed
- `decode` — the un-revealed tail churns as junk glyphs until the reveal passes over it
- `wipe` — the tail is held open by a block glyph until it resolves
- `flicker` — the text is present but interferes, then settles

`duration_ms` is how long one string takes; `stagger_ms` is the delay added per
**row**, so a listing cascades down the pane; `max_rows` caps how many rows
animate before the rest simply appear, so a very tall window does not cascade for
seconds. A misspelled name turns the effect off rather than breaking anything.

#### Options

Two knobs work with `typewriter`, `scatter` and `decode`:

```python
'text_effect': {
    'kind': 'typewriter',
    'flash': 0.08,        # each character flashes as a solid block as it lands
    'hidden': 'scramble', # not-yet-revealed characters churn instead of staying blank
},
```

- **`flash`** — a character shows as a filled block for an instant at the moment
  it resolves, then settles into its glyph. On `typewriter` this reads as a
  typing cursor; on `scatter`, as characters striking into place. The value is a
  fraction of the whole duration, so roughly `1 / len(text)` flashes for about
  one character's worth of time — `0.06`–`0.12` suits most strings.
- **`hidden`** — what an un-revealed character shows. Blank by default; set it to
  `'scramble'` for churning junk (which is what makes `decode` look the way it
  does, and can be applied to `scatter` for a noisier materialize).

Text you are **editing** never animates — an input field always shows its real
value, whatever the theme asks for.

#### Not everything uses the same one

The **text viewer** uses `scatter` with `flash` regardless of which style the
theme names, because a full screen of text has no single place for the eye to
follow — a left-to-right reveal reads as a slow wipe, while landing everywhere at
once fills the page in the same time.

It still obeys the theme on everything that matters: if your theme has no text
effect the viewer opens plainly like everything else, and it takes its timing
from the theme rather than setting its own.

### The cursor row

The row your cursor is on is marked in the theme's cursor color. In the desktop
app it is an outline around the row; in a terminal it is the `[` … `]` brackets
**and a line under the whole row**, which is what makes it findable on a wide
listing.

Only the pane you are **working in** gets that color. The other pane marks its
cursor in plain gray — so the two never look alike, and a glance at the color
tells you which side Enter will act on. (Before, the resting cue was a dimmed
version of the same color, which at the width of a rule read as the same cue.)

Most modern terminals (Windows Terminal, iTerm2, WezTerm, kitty, GNOME Terminal,
Ghostty, …) draw that line in the cursor color. On one that cannot, the line is
still drawn — in the row's own text color — so the cursor stays just as easy to
find, only less colorful. Nothing needs to be configured either way.

### Pane focus

Two cues mark which pane you are working in. Both are per-theme, and only the
Sci-Fi theme turns them on by default:

- **Corner brackets** frame the focused pane (GUI only — see below).
- The **resting pane's text recedes** slightly toward the pane background.

Filenames in the resting pane stay readable: the wash is applied before XeFM's
legibility pass, which lifts any color pushed under the contrast floor back over
it. A theme cannot configure its resting pane into illegibility.

In a terminal the brackets are skipped. A character grid has no sub-cell room for
them, and reserving whole columns and rows for decoration would cost real listing
space — so terminal focus stays marked by the cursor cue, which is colored on the
focused pane and gray on the resting one. The ink wash still applies, since a
color change costs no space.

#### Turning them on for another theme

Both are plain theme data in your `config.py`:

```python
THEMES = {
    'Dracula': {
        # Brackets in the theme accent, default arm length:
        'pane_frame': True,
        # ...or spell it out:
        # 'pane_frame': {'color': (130, 205, 255), 'arm': 2, 'thickness': 1.0},

        # Default wash strength:
        'pane_dim': True,
        # ...or set your own, 0.0 (untouched) to 1.0 (invisible):
        # 'pane_dim': 0.15,
    },
}
```

## Reduced motion

To suppress decorative motion everywhere — the dialog scale-in, the text effects,
and the animated theme backgrounds above — set this in `config.py`:

```python
REDUCED_MOTION = True
```

With it on:

- dialogs appear at once instead of scaling in;
- text appears immediately instead of decoding in;
- an animated theme background (Sci-Fi's starfield, Shinagawa's wave, and the
  rest) decelerates to a stop and holds a still frame;
- a CRT-style theme keeps its glow, scanlines and vignette — the screen still
  looks like a CRT — but the rolling band and flicker stop.

Everything lands in its **final** state, never frozen part-way, so nothing is
hidden by turning it on.

Worth knowing: this only affects decoration. Progress bars, file-list reloads,
search results and every other functional update keep running exactly as before.

It is also worth setting over a slow SSH link, where each animated frame is a
full screen repaint.

## Troubleshooting

### Colors Don't Change When Switching Themes
- Make sure your terminal supports colors
- Check that colors are enabled in your configuration
- Try restarting XeFM

### Colors Look Wrong
- Your terminal might not support full RGB colors (this is normal)
- XeFM automatically uses simpler colors that work in your terminal
- Try a different terminal if you want more colors

### Colors Are Too Bright/Dark
- Switch to a different theme (**View → Theme**)
- Dark themes (Dark+) work better with dark terminal backgrounds
- Light themes (Light+) work better with light terminal backgrounds

## Tips

- **Dark terminals**: Use a dark theme such as Dark+ (the default)
- **Light terminals**: Switch to a light theme such as Light+
- **SSH connections**: Colors work over SSH too
- **Screen/tmux**: Colors work in terminal multiplexers
- **Different terminals**: Try several themes to see which looks best

## Getting More Information

- **In XeFM**: Press `?` for help, which lists all key bindings
- **Log messages**: XeFM shows what type of colors your terminal supports

The theme feature makes XeFM look good in any terminal environment!

## See also

- [Configuration](CONFIGURATION_FEATURE.md) — where `~/.xefm/config.py` lives and how themes are defined
- [Desktop Mode Guide](DESKTOP_MODE_GUIDE.md) — running the GUI backend that renders effects and animated backgrounds
- [Developer notes](dev/BACKGROUND_ANIMATIONS_IMPLEMENTATION.md) — how an animated scene is defined and how to add one
