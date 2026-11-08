# Pelagic theme — implementation

A picture theme beside [Earth](EARTH_THEME_IMPLEMENTATION.md),
[Blocks and Crystal](BLOCKS_CRYSTAL_IMPLEMENTATION.md): open water about ten
metres down, looking up, with jellyfish, sun shafts, Snell's window, marine
snow, a reef and an occasional turtle. User-facing behaviour is in
[`doc/COLOR_SCHEMES_FEATURE.md`](../COLOR_SCHEMES_FEATURE.md#the-pelagic-scene).
The design investigation that came before the port (the lens mapping, the fxc
risk, the decisions and why) is folded in below; the full report is in git
history as `doc/dev/PELAGIC_DESIGN.md`.

| Where | What |
|---|---|
| `xefm/background_pelagic.py` | The scene (one body, spelled for MSL and HLSL), its tables, `LENS`, `pelagic_shader()` |
| `xefm/background_shaders.py` | `SHADER_KINDS["pelagic"]`, `SCENE_OPTIONS["pelagic"]` |
| `xefm/app.py` | The `Pelagic` theme spec |
| `test/test_background_pelagic.py` | Options, tables, dialect spelling, the turtle's slots, rendering |

**No PuiKit change.** The scene renders linear HDR into the lens's scene
target (`lens_shader()`, [BACKGROUND_LENS_SYSTEM.md](BACKGROUND_LENS_SYSTEM.md)),
with one `Look`. It reads only `time` and `resolution`, and uses no textures,
bakes or 3D targets.

## A port, not a redesign

It ports an approved WebGL2 prototype, and the look and motion are kept as
tuned. Rendered on Metal at the prototype's reference times
(t40/95/162/300/459), the result matches the prototype's own frames to within
1.3–1.9 levels of 255 on average (on 8×8 averages). That is the same
difference the lens alone accounts for ([Matching the lens](#matching-the-lens)),
so the scene itself reproduces the prototype's HDR. The remaining difference is the haze
right around the sun when the camera faces it, which the lens's bloom pyramid
shapes differently from the prototype's single Gaussian.

The behaviours most easily lost in a port are listed in the module docstring:
trailing tentacles, the bell's contraction, shafts tilted by the swell's slope,
no caustic net on the surface, a seamless edge to the window, and a turtle
locked to the camera's tilt cycle.

## Matching the lens

`LENS` was set against the real lens, not an imitation of it, before the scene
was ported:

1. A headless Chrome (ANGLE on Metal, the real GPU) rendered the prototype's
   scene pass at fixed times and read back its **linear HDR** as float32, and
   rendered the prototype's own post pass from the same buffer.
2. That HDR went through `lens_shader()` on Metal (a two-texture MSL scene
   decoding it, via `MetalBackground.render_to_texture`, as the tests render),
   exact to half a level.
3. The two were compared cropped by 4 px (the lens antialiases the outermost
   pixel, as for every picture theme) and averaged 4×4, grain at 0.

| Field | Prototype | `LENS` | Why |
|---|---|---|---|
| `gain` | `aces(c × 1.15)` | 1.15 | The lens's tone map is the prototype's Narkowicz ACES and gamma 2.2, so this is exact. |
| `vignette` | `1 − 0.30·|0.85q|²` | 0.47 | Matches at the corners (0.57) and the edge midpoints (0.78). The lens is flat over the middle third, so the centre is up to ~2 levels brighter: the main residual everywhere. |
| `bloom`, `threshold` | soft knee 0.45–1.6, one Gaussian at ¼ resolution, ×0.55 | 1.5, 1.6 | Bloom shows only around the sun when the camera faces it (t459); elsewhere the HDR peaks at 0.3–1.0. The lens's six-level pyramid spreads the glow wider than the single Gaussian; more `bloom` brightens the periphery before it fills the core (tried up to 8, all worse), so 1.2–2.0 is the useful range. |
| `grain` | ±0.006 uniform | 0.06 | At this scene's typical luminance (≈0.36) the lens's grain is ±0.006 at 0.06, Crystal's value. |
| `dof` | none | 0 | The scene still writes `1/tEnd` to alpha, for a future look. |

Mean / p99 difference in levels of 255, on 4×4 averages:

| t40 | t95 | t162 | t300 | t459 | t459, sun region |
|---|---|---|---|---|---|
| 1.5 / 5.4 | 1.7 / 6.2 | 1.4 / 5.6 | 1.4 / 5.2 | 1.9 / 11.9 | 4.8 / 48, max 74 |

Within about 2 levels everywhere except the haze close around the sun, which
the lens draws a little crisper near the core and wider further out.

## Stateless, and its limits

The scene reads `time` and `resolution` and nothing else: no feedback target,
no clock of its own. The camera and the jellyfish paths are closed forms in
time; a beat's surge is `floor(phase) + smoothstep(0.08, 0.55, f)`, a smooth
step of the path parameter with no integration; the turtle's slot is
`floor((t − T0)/P)`, its path placed from `camera(T0 + kP + D/2)`. The page's
own state (its integrated `simT`, speed slider and "Next turtle") is replaced
by the backend clock.

There is **no seed**. Like Crystal, Pelagic is one continuous take: a
seed-based start would give a different opening each launch, but the reseed
after idle would then need a dip (as Earth has) to avoid a cut, which is not
worth it for a scene that does not repeat within minutes.

Kept as approved:

- Each snow particle sinks through `fract(t·0.004·(1+h.y))` and jumps back up a
  1.6 m cell every 125–250 s, and one that has sunk out of its home cell can be
  clipped by the DDA, which tests only the home cells along the ray. Snow is
  faint, and neither has been seen in review.
- Float32 `time`: the finest chop octave moves at ω ≈ 8 rad/s, so after about a
  day of *animated* time its phase loses ~0.06 rad and the last octave
  shimmers. The idle clock advances only while the app is in use, so this takes
  weeks. Earth and Crystal share the same class of limit.

## fxc

Crystal crashed fxc because its loops were **nested** (a shadow march and AO
inside every shading call). Pelagic's long loops are **siblings** at the top
level (shafts, snow, the jellyfish loop), and the deepest nesting is jellyfish
× joints × strands around a small body, with no march inside shading and no
texture derivatives. The risk was judged moderate, and the body is written to
keep it so:

- `[loop]` on every loop of 6 or more iterations (jellyfish, bell march,
  joints, strands, arms, shafts, turtle, snow); `[unroll]` only on the 2–4
  iteration inner loops (`swell`, `fbm`, the gonad rings, the flipper pair).
- `renderJelly` has a single call site inside a real `[loop]`, so fxc inlines
  it once, not six times.
- If fxc ever struggles, hoist `waterLight` and the `trail()` joint positions
  out of the strand loop: they depend on the jellyfish, not the pixel.

D3D compiles a new scene on worker threads and caches the bytecode on disk
(PuiKit `_d3d_shader.py`), so a slow compile is a backdrop shown longer on the
first switch, not a UI freeze.

## Departures from the prototype (crftwr's tuning, 2026-11-07)

After the faithful port, crftwr asked for these changes. The numbers above
describe the port before them.

| What | Prototype | Now | Why |
|---|---|---|---|
| Floor | ray-marched terrain with reef patches, about 21 m down, Voronoi caustic web | a plane at −16 m, a soft sand–coral gradient (`fbm` mask), lit by the shafts smoothed into slow waves of brightness; it melts into the water between 15 and 45 m along the ray | "an ambiguous gradient, not sand shapes; the shafts as gentle waves, not lines" |
| Water clarity | `SIG` (0.30, 0.072, 0.058) | (0.24, 0.045, 0.038) blue-green, (0.28, 0.055, 0.024) blue | clear water: the near floor shows its colour, the far water its own |
| Camera | look target 3.0 ± 2.6 above the centre, focal 1.65 (62° vertical) | 1.8 ± 0.8, focal 1.4 (71°); pitch 4–36°, median 15° | slightly up: Snell's window in frame 98% of the time, the floor along the bottom (about 20%) 89% |
| Colour | fixed blue-green | slow cycles of water colour and coral cover | variety over time |
| Idle | freeze | jellyfish and surface fade, then park | a frozen jellyfish reads as a hang |
| Near jellyfish | faded out inside 1.4–3.0 bell radii | inside 3.5–6.0 | GPU: a large one on screen was the dearest case |
| Shafts | 40 steps over 55 m | 32 steps over 44 m (the same 1.375 m a step, so no more noise) | GPU |
| Snow | 28 DDA cells | 18 | GPU: only distant flakes go |

`test_the_camera_looks_slightly_up` holds the framing to the camera's closed
form with the shader's own constants.

## One body, two dialects

Every other scene keeps its MSL and its HLSL as two texts, held together by the
dialect-parity test. Pelagic is written once, in the subset of the language the
two share, and `_dialect()` spells it for each:

| Token | MSL | HLSL |
|---|---|---|
| `CONST` | `constant` | `static const` |
| `INL` | `static inline` | (nothing) |
| `LOOP` / `UNROLL` | (nothing) | `[loop]` / `[unroll]` |
| `F2(x)` `F3(x)` `F4(x)` | `float3(x)` | `(float3)(x)` (fxc rejects a one-argument constructor) |
| `fract(` `mix(` | as written | `frac(` `lerp(` |

The body avoids what the two dialects spell differently: no `out` or `thread&`
parameters (`camera()` and `sph()` return values), no matrices (rotations are
spelled out, keeping the prototype's column-major sign), no derivatives, and
`atan2` in both. The entry points are a few lines per dialect around
`pelagic(pos, resolution, time + START)`. `test_the_hlsl_is_spelled_for_hlsl`
checks that no token of the wrong dialect survives.

The `SWELL` table and the sun's direction (in air, and refracted under water)
are computed in Python (`swell_table()`, `sun_vectors()`) and emitted to both
dialects.

## Port notes

- **`pow(x, 2.0)` of a signed value** (four places in the bell's density) is
  `sq(x)`. A negative base is NaN in HLSL and under Metal's fast math; the
  browser had folded it to `x*x`. A test keeps any `pow(…, 2.0)` out of the
  body.
- **Reversed `smoothstep`** (the bell body, the turtle plastron) is written
  `1 - smoothstep(lo, hi, x)`.
- **`gl_FragCoord`** has its origin at the bottom; `pos` has it at the top, so
  `uv.y` is flipped. The per-pixel jitter hash reads `pos`, so its pattern
  differs, which cannot be seen.
- **Fast-math guards**: the snow DDA's `1/|rd|` is taken against
  `max(|rd|, 1e-6)`, and the Fresnel base `1 - |cos|` is clamped at 0.
- **`START` = 40**: the backend clock starts at 0 on every apply, and the
  prototype opened at t = 40.
- **Alpha** carries `1/tEnd` for a hit and 0 for open water, for a future look
  with depth of field (`Look.dof` is 0).

## Speed-ups that leave the picture unchanged

Each was checked on the prototype, rendered on the real GPU: the HDR is
identical to within 3e-6.

- **Strand culling.** Joints are the outer loop and strands the inner. For
  each joint, the distance from the ray to the axis segment bounds the
  distance to every strand's segment there, so a ray that passes further off
  than the widest strand offset plus four glow widths skips them all. This
  saves 5–28% of the frame.
- **Shaft attenuation.** Under the surface, the sunlight reaching a point times
  its attenuation back to the eye is an exponential in the distance along the
  ray, so the god-ray loop starts it at the first sample and multiplies once
  per step instead of evaluating six exponentials (identical to within 1 level).
  The swell's angular frequencies are a Python table (`swell_omegas()`).
- **Turtle placement** (its `camera()` call) runs only during a pass.

(The port first gated the terrain march to downward rays; the floor is now a
plane, met with one division.)

**Not taken:** fewer fringe strands, and capping how many jellyfish run the
full strand loop per pixel. Both change the look, and culling already removes
most of what they would save.

## Idle: a fade inside the picture

A frozen jellyfish, or a surface caught mid-ripple, reads as a hang, but the
shafts, the floor and the water make a calm still. So Pelagic declares
`idle: "fade"`, which makes PuiKit keep the scene at full speed while it eases
the `opacity` uniform to 0 over 40 s, and then park. The scene reads that
uniform as `presence`. The jellyfish's contribution and transmittance are scaled
by it (none are drawn at all below 0.003), and the surface's colour is mixed
toward the open-water in-scatter `amb`, which is what the ray would see with no
surface there. The lens normally dissolves the whole picture into the backdrop by
the same uniform. Pelagic defines `XEFM_LENS_OPACITY(o)` as `1.0` (a hook in
`background_lens.py`, [BACKGROUND_LENS_SYSTEM.md](BACKGROUND_LENS_SYSTEM.md)),
so the water stays and only the two elements go. Parked, the frame is the scene
with no jellyfish and no surface: `test_idle_fades_the_jellyfish_and_surface_but_keeps_the_water`
checks that it equals a `jellyfish=0` frame at zero fade.

A side effect: the theme's `opacity` for the scene now scales only the
jellyfish and the surface, not the whole picture. The Pelagic theme uses 1.
Under reduced motion PuiKit never fades, so the jellyfish stay, held still.

## Slow colour cycles

Two closed-form cycles in scene time, set at the top of the body:

- **The water** (`HUE_RATE`, about 8.5 minutes a cycle) mixes two sets of
  extinction, in-scatter (up and down), shaft tint and jellyfish glow:
  blue-green (the approved look, `*_TEAL`) and a clearer open-ocean blue
  (`*_BLUE`, green absorbed faster than blue). They pass through every
  function as a `Water` struct, because MSL has no mutable globals.
- **The floor** (`CORAL_RATE`, about 11.5 minutes) moves the edge of a soft
  colour mask over broad noise, from `CORAL_EDGE_SAND` (no coral) to
  `CORAL_EDGE_REEF` (all coral), between white `SAND` and black `CORAL`, so dark
  patches grow out of the sand and spread until they cover it.

The scene opens blue-green with the floor half sand and half coral. All sand
reads as a pale, shaft-lit band along the bottom of the frame; all coral, as a
dark one.

## Palette: a white shell over dark water

The first palette was all water colours, and the selected row, the bars and the
headers vanished into the scene behind them. The chrome is now a white shell
(`surface`, `status`, `footer` near `#EEE8E0`): the bars and pane headers
translucent at the theme's opacity over the sea, dialogs and menus opaque. A
selected file is a white row (`selection_fill`), the cursor coral, and text
selected with the mouse a deep coral that reads on the dark panes and on the
white shell alike. The panes stay the dark water, so the file names keep their
light colours.

`_theme(theme_fields=...)` pins the derived Theme fields that would otherwise
come out of the dark background and land dark inside the white dialogs: inputs
(`control_*`), secondary buttons, the popup frame, hover rows and unfocused
selections. Text over the white is inked dark by auto-ink. PuiKit 1.23.0 is
what makes that hold on translucent surfaces (it judges a fill as seen, so the
bars' text goes black rather than a gray that read faint over the water), and
what keeps inline code, viewer headers, selections and search hits consistent
with the surfaces they sit on. The text viewer marks its search hits and
selection the same way over a scene (`_MATCH_*_SCENE`, a mark opacity).

## Theme and options

- **`ink` is ignored**, as in Earth. The water's colour is its extinction.
  Pelagic is in `INKLESS`, `PICTURES` and `PARTIAL_FADE` in
  `test_background_shaders.py`.
- **`brightness` defaults to 0.7**, not the 0.5 of the other picture themes.
  `level` multiplies the whole picture, and this one is mid-bright everywhere:
  across the five reference frames the median brightest channel is 0.34–0.45
  and the brightest pixel 0.70–0.86. Earth is mostly black space, so its 0.5
  only cut highlights; here 0.5 halves the whole picture and the water reads
  as dusk. At 0.7 a pixel reaches at most 0.60. Settle it in the legibility
  review.
- **`jellyfish`** (0–6, baked as `JELLYFISH`) is also the user's lever on a
  slow GPU: jellyfish are 35–50% of the frame. **`exposure`** scales the HDR
  before the lens.
- **`resolution_scale` 0.45, `pixel_density` 0.9**: 1440×900 points render
  1296×810 on any display, more lines than the 720 of the reference frames;
  the scene is soft and hazy, and at half resolution the strands soften but
  stay intact. **`frame_rate` 30**: the bell's squeeze takes 1.6–2.6 s and the
  fastest chop octave cycles at about 1.3 Hz (23 frames a cycle), so neither
  judders. **`idle` `"fade"`**, answered inside the picture (above).
- **No `turtle` option.** The turtle is part of the approved picture and costs
  nothing outside its 60 s pass.
- **`speed` 1.0.** The turtle's period (216.66 s) equals the camera's tilt
  period (2π/0.029) in scene time, so any speed keeps them locked.
- **Built in**, because the scene needs `Target`/`Pass` descriptors, which the
  `user_api` firewall keeps out of extensions (the reason for every picture
  theme). Its whole cost is one source file.
- **The name.** *Pelagic* is the open-water zone, away from shore and floor,
  which is what the frame mostly shows; one word like Earth, Blocks and
  Crystal, and unlikely to clash with a user's theme. *Ocean* is the likeliest
  name for a future plain-colour theme, and *Deep Sea* is wrong (the camera is
  about 10 m down in sunlit water).

## Cost

Apple M5, **on battery in Low Power Mode**, frames back to back with
`MetalBackground._encode`, at the render size of a 1440×900-point window:

| | t40 | t95 | t162 (turtle pass) | t300 | t459 |
|---|---|---|---|---|---|
| The faithful port (1440×900) | 27.6 ms | 31.3 ms | 41.6 ms | 26.0 ms | 31.5 ms |
| Now (1296×810) | 16.6 ms | 15.5 ms | 16.0 ms | 13.5 ms | 14.7 ms |

About half on average, and the worst case under 40%. Over 11 minutes sampled
every 20 s: mean 15.4 ms, worst 21.5 ms. Crystal at 1296×810 in the same state
takes 25.7 ms, and its doc gives 11.5 ms on normal power, a Low Power factor of
about 2.1: Pelagic is then about 7–10 ms on normal power.

What went into the halving, as measured (mean over the sweep, Low Power):
the floor plane (no 72-step march, about −20%), the shafts' exact attenuation
(−3 ms), near jellyfish hidden earlier (−3 ms), 32 shaft steps over 44 m and 18
snow cells (−4 ms), and `resolution_scale` 0.45 (−3 ms). The shafts are still
the largest cost (about half before these changes), then the jellyfish.

## Open items

- Fine-tuning with crftwr continues: the bloom around the sun, `brightness`,
  `opacity` and `selection` over real file lists.
- Windows: D3DCompile time on the first switch and the frame time on an
  integrated GPU.
- Hand check in the desktop app on macOS and Windows: the swaying shafts, the
  bell's contraction, trailing tentacles, no net on the surface, a seamless
  window edge, the glow toward the sun, the turtle low and far off, the idle
  fade of the jellyfish and surface, reduced motion.
- Web backend: passes and a GLSL dialect, as for the other picture themes.
