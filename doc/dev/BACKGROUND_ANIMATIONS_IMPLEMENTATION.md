# Background Animations Implementation

How XeFM's animated backgrounds are defined, registered and drawn, and what to do
to add one. End-user documentation is in
[COLOR_SCHEMES_FEATURE.md](../COLOR_SCHEMES_FEATURE.md) (Background animations section).

## One renderer

Every scene XeFM offers is a fragment shader, evaluated per pixel on the GPU. There
used to be two kinds — a CPU path in `xefm/background_animations.py` that returned
line segments for the backend to stroke, and this one — and the CPU path was retired
because it lost on every axis that mattered:

| | Segment scenes (removed) | Shader scenes |
|---|---|---|
| Written as | Python returning line segments | MSL + HLSL fragment source |
| Cost | ~1.4µs per segment | independent of what it draws |
| Repaints the UI to animate | yes, every frame | no |
| Colour | one per scene | full RGBA per pixel |

The third row is the one that decided it. A segment scene was drawn *inside* the
UI's render pass, so advancing it repainted the whole file manager 60 times a second
regardless of how little the scene itself drew — measured at 0.5ms of scene against
8.1ms of triggered repaint. A shader owns a layer behind the UI, which the backend
advances without marking the view dirty. Idle, that took the wave from ~52% of a core
to ~4%.

The removed code is in git history if you ever need it (`xefm/background_animations.py`,
`test/test_background_animations.py`). Don't reintroduce it.

## Where the pieces live

| Concern | Location |
|---------|----------|
| Every scene | `xefm/background_shaders.py` (XeFM) |
| Registry | `SHADER_KINDS` in that module |
| Descriptor | `Shader` in `puikit.background` (PuiKit) |
| Theme → descriptor resolution | `_resolve_background` in `xefm/app.py` |
| Push to the backend on theme switch | `XeFMApp._apply_background` in `xefm/app.py` |
| Compiling and drawing (macOS) | `puikit/backends/_metal.py` (PuiKit) |
| Compiling and drawing (Windows) | `puikit/backends/_d3d_shader.py` (PuiKit) |
| Compositing the GPU layer | `MacOSBackend._sync_shader_layer` (PuiKit) |

The split is deliberate: **PuiKit owns how a scene is drawn, XeFM owns what the scenes
are.** PuiKit ships only reference scenes that exercise its own paths; every
production scene is XeFM's, so adding one touches `xefm/background_shaders.py` and
nothing else.

## The shader contract

A scene is a single fragment function named `puikit_bg_fragment`. PuiKit prepends its
prelude — the uniform struct and a fullscreen-triangle vertex stage — so app source is
only that function and cannot break the pipeline:

```metal
fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]])
```

`u` carries `resolution` (pixels), `time` (seconds, **already scaled by the theme's
speed**), `opacity`, and the theme's `ink`/`backdrop` as RGBA. Two obligations:

- **Derive all motion from `time`.** Never read a clock of your own — `speed=0` must
  freeze the scene, and idle parking (below) depends on time being the app's to
  control. There is a test for it.
- **Anchor colour on `ink`** so the scene stays in the palette's family. A scene is
  free to push it around — the wave sweeps a gradient between two versions of it,
  most scenes pale toward white at their brightest points — but not to ignore it.

A source that fails to compile draws nothing and logs the compiler error, so a typo
costs a blank background rather than a crash.

## Every scene ships twice

Shader source is the one genuinely backend-specific part of a background: macOS
compiles Metal Shading Language, Windows compiles HLSL. So each scene is a pair named
for its dialect — `<SCENE>_MSL` and `<SCENE>_HLSL` — holding the same maths, paired up
in `SHADER_KINDS`.

Nothing compiles one against the other, so **tuning one dialect and forgetting the
twin is the standing hazard in this module**, and it surfaces only as "Windows looks
different" long after the change. `DialectParity` in `test/test_background_shaders.py`
parses the tunables out of both and asserts every MSL constant has an HLSL twin with
the same value. That catches drift in the numbers; it cannot catch a mistranslated
expression, so a change to scene *logic* still needs checking on Windows.

Only the MSL side can be exercised on a Mac — the D3D tests skip there, and the render
tool is Metal-only.

## The per-pixel inversion

A CPU scene walks its objects and draws them. A shader is asked, for one pixel at a
time, "what covers you?" — so every scene needs a way to answer that without visiting
everything. The recurring device is a **grid**: an object's identity (position,
phase, brightness) is hashed from its cell index, so a pixel can compute which cells
could possibly reach it and consult only those. Hashing the index rather than calling
anything time-varying is also what keeps an object's identity fixed across frames.

Each scene applies it differently, and the interesting part is always "which cells
could reach this pixel":

- **rain** — columns. A streak is vertical and confined to its column, so a pixel
  checks its own and two neighbours, whatever the window size.
- **wave** — particle cells across depth layers, three per layer.
- **starfield** — a star at plane position `s` and depth `z` lands at `s/z`, so the
  pixel runs that backwards: at an assumed depth, `s = n * z` names the cell exactly.
  Depth is sampled in layers, and the streak's span works out to under one cell for
  any on-screen pixel, so two lookups per layer bracket it.
- **constellation** — a 5x5 block of nodes, the span bounded by the cell-to-link
  ratio (see below).
- **grid** — no grid of objects at all; it inverts the *camera* instead and meets the
  corridor analytically.

## Registration and resolution

```python
SHADER_KINDS = {"starfield": {"source": STARFIELD_MSL, "source_hlsl": STARFIELD_HLSL}, ...}
```

The dict is splatted straight into `Shader(...)`, so a stray key is a `TypeError` at
theme-apply time — there is a test that constructs every entry. From there:

1. A theme names `animation='starfield'` (or a params dict).
2. `_resolve_background` finds the name in `SHADER_KINDS` and builds a `Shader`,
   filling `ink` from the theme foreground and `backdrop` from the theme background.
   `_ANIM_DEFAULTS` supplies XeFM's tuning (`speed=0.6, opacity=0.6`);
   `_ANIM_DEFAULT_KIND` is used when a theme says `animation=True` without a type.
3. The descriptor rides in `theme.extras['background']`.
4. `XeFMApp._apply_background` pushes it on every theme switch, so switching away
   clears it.

A name **not** in `SHADER_KINDS` resolves to `None` — a plain solid background. There
is nowhere else for it to go: a scene *is* a shader, and puikit no longer carries a
second background kind. So a config typo costs the scene, not startup.

A backend without the `background_shader` capability (curses, or a desktop backend
with no usable shader path) inherits a no-op, so none of this branches on the backend.

## Adding a scene

1. Write `<SCENE>_MSL` and `<SCENE>_HLSL` in `xefm/background_shaders.py`.
2. Add both to `SHADER_KINDS`, with `resolution_scale` if the scene can afford it.
3. Add a row to the table in `doc/COLOR_SCHEMES_FEATURE.md` (Background animations section) and to the theme
   comment block in `xefm/_config.py`.
4. Update the expected set in `test/test_background_shaders.py`. The generic suites
   pick the scene up from `SHADER_KINDS` automatically, so compilation, drawing,
   animating, freezing at `speed=0`, following the ink, staying a backdrop and
   dialect parity all come for free.

### Verifying the look

The tests check invariants, not aesthetics, and XeFM's TUI cannot be launched
non-interactively. To actually see a frame, rasterize it headlessly:

```bash
PYTHONPATH=. python tools/render_background_animations.py
PYTHONPATH=. python tools/render_background_animations.py --kind starfield --time 12 --size 1600x1000
```

It writes a PNG per scene (into `temp/` by default) against the theme that scene
ships with, and reports what share of the frame each one lights.

**This is worth doing, every time.** Every serious defect in this module's history was
invisible to the test suite and obvious in a render:

- The **starfield** originally spawned stars at depth 1, where the plane projects to
  exactly the view bounds — so the field began already covering the window instead of
  streaming out of a vanishing point. Fixed by spawning at `Z_FAR = 2.6`.
- The **constellation**, when first ported to a shader, sized its grid cell to exactly
  the link radius. On a regular grid that puts every neighbour at almost exactly the
  link distance, where the distance falloff sends the edge to zero alpha — it rendered
  as bare dots with no links at all, and every test passed.
- The **grid tunnel** called `grid_line()` inside both arms of a ternary, making its
  `fwidth` conditional. Derivatives are undefined under non-uniform control flow, and
  the corridor corners — the one place neighbouring pixels disagree about which wall
  they hit — came out as dashed lines.

## Scene notes

### The grid tunnel inverts the camera

The other scenes compute screen coordinates from object positions. `grid` runs the
whole projection backwards: each pixel recovers its own view ray, meets the corridor
analytically — the corridor is a box around the camera, so exactly one of the four
walls is hit — and asks the grid at that point how far the nearest line is. No
geometry is generated at all.

- The camera sways on four slow sines whose rates are mutually incommensurate
  (periods ~27s, ~34s, ~43s, ~53s), so the motion never comes back into phase and
  never reads as a loop. Amplitudes stay well inside the corridor so it cannot clip a
  wall.
- The corridor's half-width is derived from the view aspect so that **at depth 1 its
  cross-section maps exactly onto the viewport**.
- Line width is filtered by the screen-space derivative, which is the real gain over
  the segment version: a rail stays a crisp constant width all the way to the
  vanishing point instead of aliasing into a dotted crawl, and where the grid finally
  packs tighter than a pixel it fades out rather than boiling into a wash.

### The constellation is a reinterpretation, not a translation

Its identity is global nearest-neighbour topology — which pairs are linked depends on
where every node is — and that is exactly what a shader, asked about one pixel at a
time, cannot survey. So the field is rebuilt on a grid, one node per cell, and two
ratios carry the whole scene:

- **Cell size to link radius** (`LINK_CELLS`, 1.4). Too large and everything links to
  everything; equal to 1 and the net renders as bare dots, for the reason above. It
  also bounds the search: an edge reaches at most 1.4 cells, so both endpoints of any
  edge crossing a pixel lie inside the 5x5 block around it.
- **Falloff measured against the cell spacing**, not the link radius. The CPU scene
  scattered nodes at random, so plenty of pairs sat well inside the radius; on a grid
  every neighbour is about one cell away, and a falloff over the full radius collapses
  them all to the same near-zero alpha.

A node **orbits inside its own cell** — a circle at constant angular speed — because a
node that wandered out of its cell could not be found by index. That also answers the
objection the original CPU scene raised against sinusoidal paths (a sine dwells at its
turning points and piles nodes up): a circle traversed at constant speed has no
turning points and is uniform in time. What is gone is a node crossing the whole
window over half a minute.

## Idle parking

An animated background is the only thing in XeFM that keeps an idle app redrawing
indefinitely, so PuiKit stops it when nobody is watching. Lives in `MacOSBackend`, so
neither XeFM nor any scene has to opt in.

- `_bg_target` asks for full rate while the window holds focus **and** input was
  recent (`_BG_IDLE_TIMEOUT`, 15s); otherwise zero.
- `_background_tick` eases `_bg_rate` toward that target — `_BG_RAMP_DOWN` (40s)
  falling, `_BG_RAMP_UP` (15s) rising — through `_smoothstep`, so the *change in
  speed* is gradual at both ends. Measured: at most **0.17%** change in speed per
  frame, below the threshold at which the eye reads the ramp itself as motion.
  Stopping dead would be as noticeable as the animation.
- Those spans are long deliberately, and trade against the battery goal: it is ~55s
  from last input to parked. Parking is deferred, not skipped.
- At zero the tick returns `False`, unregistering itself, which lets
  `_ensure_animation_timer` drop the frame timer to the 10Hz idle rate — where the
  actual power saving comes from. The last frame stays on screen; the shader's layer
  keeps its drawable.
- `_dispatch` calls `_ensure_background_ticker` on every input.

**The clock is the subtle part.** `_bg_clock` counts *animated* time — it advances by
`dt × eased_rate`, never wall clock. So a background parked for ten minutes resumes
exactly where it stopped rather than teleporting ten minutes into the scene. `dt` is
clamped to 0.25s so a stalled main thread resumes by continuing rather than lurching.
This is why a scene must take its motion from the `time` uniform and nothing else.

`_smoothstep` and `_approach` are module-level pure functions specifically so the ramp
is exactly testable, and `tests/test_background_idle.py` drives the whole park/resume
lifecycle against a fake clock — no window, no waiting.

## Compositing

A `CALayer` draws its sublayers *above* its own contents, so the GPU layer cannot live
inside the UI view — it has to be a sibling behind it. `open()` puts the UI view inside
a container, and `_sync_shader_layer` inserts a `CAMetalLayer` at index 0 of the
container's layer.

When a shader is active the render pass clears the UI view to **transparent** (with
`NSCompositingOperationCopy` — source-over would leave the previous frame), so the
layer behind shows through. The layer is created lazily, so an app that never sets a
shader creates no Metal objects.

`_render_into_view` deliberately does *not* dispatch on `Shader`: the only thing the UI
pass owes a shader is that transparent clear. That is what keeps animating the
background off the UI's repaint path.

## Cost

Per-pixel, so the tunables that matter are the per-pixel loop and the resolution:

- Keep the inner loop **transcendental-free** where you can. The usual
  `fract(sin(n) * 43758.0)` hash and a gaussian `exp()` splat together cost more than
  the wave's surface itself; it uses an arithmetic hash and a squared clamped
  polynomial instead. Where a `pow` is unavoidable, guard it behind the test that
  decides whether the pixel is even on the feature (see the constellation's edge loop).
- Prune before you evaluate. The constellation rejects a cell on its *bounds* before
  computing the node inside it, so the corners of its 5x5 block cost nothing.
- `Shader.resolution_scale` renders below native and lets the compositor scale up.
  Only the wave uses it (`0.5`): it is diffuse grain, indistinguishable at a quarter
  of the pixels. Every other scene is thin bright lines, where halving the scale trades
  away exactly the crispness that is the point of drawing them.

Measure with `tools/render_background_animations.py` plus a timing loop over
`MetalBackground.render_to_texture`, or in the real app with `PUIKIT_BG_PROFILE=1`.

## Tuning notes

These sit behind a working file manager, so every scene is tuned to stay a backdrop: a
star crosses in roughly eight seconds, a constellation node orbits in about half a
minute, and nothing approaches full brightness. `speed=1.0` is the tuned look; themes
typically ask for `0.6`. `test_every_shader_stays_a_backdrop` enforces the floor of
this — the theme background must remain the dominant colour of the frame.

Each scene's tunables are constants at the top of its source with comments explaining
what breaks at the extremes — notably the starfield's `Z_NEAR`, which must stay well
above zero because the perspective divide would otherwise fling a star to infinity.
