# Pelagic theme — implementation

A picture theme beside [Earth](EARTH_THEME_IMPLEMENTATION.md),
[Blocks and Crystal](BLOCKS_CRYSTAL_IMPLEMENTATION.md): open water about ten
metres down, looking up, with jellyfish, sun shafts, Snell's window, marine
snow, a reef and an occasional turtle. User-facing behaviour is in
[`doc/COLOR_SCHEMES_FEATURE.md`](../COLOR_SCHEMES_FEATURE.md#the-pelagic-scene).
The investigation behind it (the lens mapping, the cost breakdown and the
decisions) is in [PELAGIC_DESIGN.md](PELAGIC_DESIGN.md).

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
difference the lens alone accounts for (`PELAGIC_DESIGN.md` §2), so the scene
itself reproduces the prototype's HDR. The remaining difference is the haze
right around the sun when the camera faces it, which the lens's bloom pyramid
shapes differently from the prototype's single Gaussian.

The behaviours most easily lost in a port are listed in the module docstring:
trailing tentacles, the bell's contraction, shafts tilted by the swell's slope,
no caustic net on the surface, a seamless edge to the window, and a turtle
locked to the camera's tilt cycle.

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

Each was checked on the prototype: the HDR is identical to within 3e-6
(`PELAGIC_DESIGN.md` §5–6).

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

## Theme and options

- **`ink` is ignored**, as in Earth. The water's colour is its extinction.
  Pelagic is in `INKLESS`, `PICTURES` and `PARTIAL_FADE` in
  `test_background_shaders.py`.
- **`brightness` defaults to 0.7**, not the 0.5 of the other picture themes.
  `level` multiplies the whole picture, and this one is mid-bright everywhere
  (median brightest channel about 0.4), so 0.5 halved the approved look.
  Settle it in the legibility review.
- **`jellyfish`** (0–6, baked as `JELLYFISH`) is also the user's lever on a
  slow GPU: jellyfish are 35–50% of the frame. **`exposure`** scales the HDR
  before the lens.
- **`resolution_scale` 0.45, `pixel_density` 0.9**: 1440×900 points render
  1296×810 on any display, more lines than the 720 of the reference frames. **`frame_rate` 30**. **`idle` `"fade"`**,
  answered inside the picture (above).
- **`speed` 1.0.** The turtle's period equals the camera's tilt period in scene
  time, so any speed keeps them locked.

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
