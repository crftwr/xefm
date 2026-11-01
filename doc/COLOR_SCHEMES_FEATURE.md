# Color Schemes Feature

English \| [日本語](COLOR_SCHEMES_FEATURE.ja.md)

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
  directories, cyan symlinks. Easy on the eyes in low light.
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

### Earth

- **Earth** — the planet seen from orbit, behind the panes: real surface and
  clouds, a glowing atmosphere, the sun rising over the limb, a field of stars,
  and a slowly drifting camera filmed through a changing choice of lens looks —
  hundreds of scenes, eased from one to the next at random. The palette
  is a deep-space navy with the pale blue of the lit horizon for the chrome and a
  sunrise amber for the cursor and i-search. Like the screen effects, the planet
  is drawn only by the desktop app; a terminal shows the palette alone. See [The
  Earth scene](#the-earth-scene) for choosing a shot or a lens look.

## What Gets Colored

Every theme changes:
- **File Types**: Different colors for directories, symlinks, and regular files,
  with hidden entries faded into the background (see below)
- **Selected Items**: Highlighting for selected files
- **Interface**: Headers, footers, status bar, and pane borders
- **Log Messages**: Different colors for different types of messages
- **Text Viewer**: Syntax highlighting when viewing code files
- **Search Results**: Highlighting for search matches

### Hidden Files

With hidden files shown (`toggle_hidden`, **View → Show Hidden Files**), a hidden entry is drawn in its
own type color faded toward the background, so it still reads as a folder or a
link while being visibly set apart from everything else in the pane. On Windows
this is the only thing that tells you: hidden there is a file attribute, not a
dot at the front of the name, so `desktop.ini` and an ordinary file look alike
otherwise.

To change how far they fade — or to give them a single flat color instead — name
`hidden` in a theme's `file_types` in `~/.xefm/config.py`:

```python
THEMES = {
    'Ocean': {
        'file_types': {
            'hidden': 0.6,             # fade harder (0 = not at all)
            # 'hidden': (110, 110, 110),  # ...or one flat gray for every hidden entry
        },
    },
}
```

The number is what you get, up to a point: XeFM holds a hidden name to a minimum
contrast against the pane behind it, so a high number — or a flat color close to
the background — fades as far as that floor and no further. A hidden entry ends
up quiet enough to skip over and still solid enough to read when you look at it.

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
on-palette whichever theme (or custom palette) you use. The exception is `earth`,
a picture of the planet in its natural colours: it takes only the theme background,
as the colour it is shown over.

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
| `earth` | The Earth from orbit — surface, clouds at three heights that slide against the ground as the camera moves, a glowing atmosphere with sunrise and sunset along the edge, sunlight glinting off the oceans, a dark night side with no city lights, stars and a faint Milky Way. A slow camera moves between composed shots, and a choice of lens looks (film, anamorphic, CRT and more) is applied to the picture only, never to the panes. See [The Earth scene](#the-earth-scene). |
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
with no usable GPU shader support. `earth` also needs desktop mode in the strict
sense: the browser (web) mode shows the plain background for it.

### Turning one on

Animations are chosen per theme. Among the built-in themes, **Sci-Fi** ships with
the starfield, **Cyber** with the hologram, **Shinagawa** with the wave and
**Earth** with the earth; select one from **View → Theme**.

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
- What you are left with is the plain theme background. Almost every scene XeFM
  ships is pure motion — falling rain, streaming stars, a corridor being flown
  down — and a scene like that has no frame worth stopping on: freeze one and you
  get the drops and stars stranded wherever they happened to be, which reads as
  XeFM having hung rather than settled. Dissolving away leaves something the
  palette already has.
- `earth` is the exception. Every frame of it is a picture of the planet, so
  instead of fading it slows gently to a stop and **holds the scene** it was on.
  When you come back to XeFM it does not resume that scene: over a few seconds
  it moves on to a new one, picked at random — once per return. Moving the mouse
  over XeFM while another app is in front does not count as coming back.
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

#### The Earth scene

Left to itself, `earth` makes **scenes** by pairing a shot (one of ten, each in
twelve compositions — moved round the planet, higher or lower, tilted, and turned
so the Earth can lie at the bottom, the side or the top of the frame) with a lens
look (one of ten) — 1,200 combinations. Each scene lasts about 50 seconds at
`speed` `1.0` — about half a minute held, then a slow move of about 18 seconds into
the next — with the camera moving slowly and steadily the whole time — around
the planet, closer or further, the planet drifting and turning across the frame
and the sun creeping with it — and then travels to the next, picked at random, in
one smooth move: the drift within a scene and the move between scenes flow into
each other. XeFM opens on a random scene, and returns from idle to a
fresh one.

The picture is kept dim on purpose: no pixel of it is brighter than half white
(`brightness`), so file names stay readable over a sunlit ocean.

It takes five keys of its own in the same dict:

```python
'animation': {'type': 'earth', 'shot': 'rise', 'lens': 'film',
              'clouds': 3.0, 'exposure': 0.85},
```

| Key | Meaning |
|-----|---------|
| `shot` | Hold one shot (below), or leave it out (or `'auto'`) to pick one at random for every scene. |
| `lens` | The camera look (below). Leave it out (or `'auto'`) to pick one at random for every scene; name one to keep it, or give a list to pick among those: `['clean', 'film', 'anamorphic']`. A dict tunes a look: `{'preset': 'film', 'grain': 0}`. |
| `clouds` | How far the clouds are lifted above the ground, 0–8. `1` is their real height; the default `3` lets them visibly slide against the surface from orbit. |
| `exposure` | How much light the camera takes in, 0.1–4. Default `1`. |
| `brightness` | The brightest the picture may be, as a fraction of white, 0–1. Default `0.5`. |

The shots:

| `shot` | What you see |
|--------|--------------|
| `day` | The full disc in daylight, Africa and Europe. |
| `dawn` | Sunrise along the curve of the Earth over the western Pacific. |
| `crescent` | A thin crescent, lit from behind, the atmosphere glowing on the edge. |
| `leo` | Low orbit, about 250 km up, looking across the Himalaya to the horizon. |
| `terminator` | The line between day and night across the Andes. |
| `glint` | The sun reflected off the central Pacific. |
| `rise` | The sun slipping behind the edge of the Earth and back out — it shrinks and reddens as it goes, and the air beside it flares. |
| `polar` | Over the Arctic. |
| `horizon` | Sunrise along the horizon, seen from low orbit. |
| `ocean` | The daylit Pacific seen obliquely from low orbit. |

A held shot still moves slowly, and keeps its composition as listed here; the
other eleven compositions of each shot only come up when `shot` is left to choose.

The lenses. They are applied to the picture only; the panes, text and dialogs are
never distorted, blurred or grained:

| `lens` | Look |
|--------|------|
| `clean` | A light glow around the brightest light and a soft vignette. |
| `aberration` | Colour fringing toward the edges, with slight barrel distortion. |
| `mono` | Black and white with grain. |
| `film` | Warm highlights, cool shadows, a red halo around light, grain. |
| `anamorphic` | Wide-screen bars, a blue horizontal streak through the sun, faint flare. |
| `flare` | Lens-flare ghosts mirrored through the centre of the frame. |
| `fisheye` | A strong fisheye. |
| `crt` | A curved CRT tube with scanlines. |
| `infrared` | False colour, as infrared film renders foliage and sky. |
| `night-vision` | A green intensified-image scope. |

The textures are NASA's Blue Marble imagery; their credits are in
`xefm/assets/earth/SOURCES.md`. On a laptop the scene costs noticeably more GPU
time than the other animations while it is moving — it stops (and costs nothing)
when XeFM is idle, like the rest.

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
app it is an outline around the row; in a terminal it is **a line under the whole
row**, which is what makes it findable on a wide listing.

Only the pane you are **working in** gets that color. The other pane marks its
cursor in plain gray — so the two never look alike, and a glance at the color
tells you which side Enter will act on. (Before, the resting cue was a dimmed
version of the same color, which at the width of a rule read as the same cue.)

**XeFM picks the marking your terminal can actually show, by itself.** Most
modern terminals (Windows Terminal, iTerm2, WezTerm, kitty, GNOME Terminal,
Ghostty, Alacritty, Konsole, …) can draw an underline in a color of its own, and
there you get the line. Where a terminal cannot — macOS's own Terminal.app among
them — a line would come out in the row's own text color, saying only "this row
is underlined" and nothing about which pane you are in, so the cursor row is
marked `[` … `]` instead, in the cursor color. Both spellings say the same thing,
neither needs configuring, and both cost the listing the same one column at each
edge — so a pane looks the same on every terminal but for how its cursor row is
marked.

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
- an animated theme background (Sci-Fi's starfield, Shinagawa's wave, Earth's
  planet and the rest) decelerates to a stop and holds a still frame;
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

- **In XeFM**: Press `F1` for help, which lists all key bindings
- **Log messages**: XeFM shows what type of colors your terminal supports

The theme feature makes XeFM look good in any terminal environment!

## See also

- [Configuration](CONFIGURATION_FEATURE.md) — where `~/.xefm/config.py` lives and how themes are defined
- [Desktop Mode Guide](DESKTOP_MODE_GUIDE.md) — running the GUI backend that renders effects and animated backgrounds
- [Developer notes](dev/BACKGROUND_ANIMATIONS_IMPLEMENTATION.md) — how an animated scene is defined and how to add one
