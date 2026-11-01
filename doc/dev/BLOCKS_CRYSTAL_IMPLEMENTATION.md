# Blocks and Crystal themes — implementation

Two picture themes beside [Earth](EARTH_THEME_IMPLEMENTATION.md), built from
approved prototypes (a three.js mesh scene for Blocks, a WebGL2 ray-marcher for
Crystal). User-facing behaviour is in
[`doc/COLOR_SCHEMES_FEATURE.md`](../COLOR_SCHEMES_FEATURE.md#picture-themes).
They share Earth's PuiKit infrastructure and add two pieces to it.

| Where | What |
|---|---|
| `xefm/background_blocks.py` | The Blocks scene (MSL, HLSL port), `blocks_shader()` |
| `xefm/background_crystal.py` | The Crystal scene, its bake, the crystal layout (`crystal_layout()`), `crystal_shader()` |
| `xefm/background_shaders.py` | `SHADER_KINDS` / `SCENE_OPTIONS` entries |
| `xefm/app.py` | The `Blocks` and `Crystal` theme specs |
| PuiKit `puikit/background.py` | `ShaderVolume`, `Shader.volumes`, `Shader.frame_rate`, `Lens.dof` / `focus_range` |
| PuiKit `backends/_bg_lens.py` | The depth-of-field gather in the lens composite |
| PuiKit `backends/_metal.py`, `_d3d_shader.py` | Volume bake, frame-rate cap, Windows frame reuse |

## What PuiKit gained

- **`ShaderVolume`** — a 3D texture the scene bakes for itself. The source
  defines a second entry, `puikit_bg_bake`, run once per slice with
  `BakeUniforms` (size, slice, volume index); the result is half-float. The
  scene samples volume *i* in the slot after its textures. Baking is spread
  over the first frames (8 slices a frame) with the backdrop shown until done,
  and re-applying the same shader keeps the volumes. On D3D11 each slice is a
  `Texture3D` render-target view with `FirstWSlice`.
- **`Lens.dof` / `focus_range`** — depth of field in the lens composite. The
  scene writes **inverse** depth into alpha. The blur size `|1 − focus/depth| ·
  range` is linear in it, so a bilinear tap blends blur sizes across a
  silhouette as the prototype's stored circle of confusion did; writing depth
  instead invented in-focus depths along edges. Focus is the centre tap and
  four at 1.2% of the height, averaged in 1/depth: a macro's depth of field is
  shallow enough that wider taps on the rock behind pulled focus off the
  subject. The 40-tap gather averages in `(x/(1+x))^(1/2.2)` and expands
  after: the prototype blurred the tone-mapped picture, where a hairline glint
  is at most white and the dark around it is not near zero; in linear HDR one
  glint landing in some pixels' taps broke edges into teeth.
- **`Shader.frame_rate`** — the most frames a second the GPU renders the scene;
  the clock still advances every frame, the last frame stands in between, and
  a fading scene is never skipped.
- **Windows frame reuse** — the D3D renderer returns its last texture when the
  inputs (shader, size, clock, fade, seeds) are unchanged, and inside the
  frame-rate interval. Windows renders the background inside every UI frame,
  so before this every key press and scroll repainted a full scene. macOS
  already isolates the background on its own layer.

## Blocks

**One fragment, no meshes.** A 2D DDA walks the cells the ray crosses (centres
on integers, field infinite) and intersects each cell's column; the first hit
wins, the floor (−3.75) catches rays that go down a gap, and the walk stops at
72 cells or 42 units, where the fog is total. Rounded edges are shading only:
within `EDGE_R` of an edge the normal turns round a quarter circle, which is
what draws the bright edge highlight.

**Stateless motion.** The prototype integrated each column's phase from a
speed `0.08 + 2.2 (s1 s2)^1.5`. The port uses `SLOW + SURGE · s^6`, `s = 0.5 +
0.5 sin(vA t + vB)`: `s^6 = cos^12(ψ)` with `ψ` half the angle, and power
reduction makes its integral a short sum of sines (`surge_integral`). It is near
its floor most of the time and surges briefly — under a quarter of the time
above half its peak (`test_columns_are_mostly_slow_with_occasional_surges`).
The global swell's rate is a squared sine, integrated the same way.

**Leaks** are hashed events. Each gap junction has one slot per 10 s; it fires
with probability `rate · 10`, the rate weighted toward the camera's look target
(itself a closed form of time) at the slot's start, so an event never pops as
the target moves. Junctions are split into three families whose slots are
offset by a third, so slot boundaries don't pulse the whole field. A column's
side face sums the 16 junctions around its cell (point-light falloff, GGX
specular in the leak colour); the floor sums 25.

**Colour.** The prototype ran on three.js r147 in legacy colour mode, where a
hex colour is taken as *linear*; decoding them as sRGB made the metal near
black. The port takes them as the prototype did, and the theme background as
the fog the same way (`#0a1626` is exactly the prototype's fog). three's ACES
divides exposure by 0.6, so the prototype's 0.95 is 1.58 here. The leak light
is `ink`; the metal is the approved blue-black. The analytic environment (a
gradient with three panels) stands in for `RoomEnvironment`, tuned against a
headless capture of the prototype.

**Cost** (Apple M5, normal power): 4–11 ms/frame at 2160×1350 (a 1440×900-pt
window at `resolution_scale` 0.75), depending on the shot.

## Crystal

A port of the prototype's crystal specimen only. Camera, target and key light
are its closed forms (the page starts at `s = 24`, kept as `START`). The
crystal layout is computed in Python with the prototype's *JavaScript* hash
(not the GLSL one) and emitted as constant arrays in both dialects. Mutable
globals became a `Look` struct passed through the shading functions, and the
volume is reached through `VOL_*` macros so the same bodies serve MSL (texture
parameters) and HLSL (globals). The three contour-stripe fixes are kept: the
6-step settle after a hit, the faded-in relief, and AO's first taps reading the
same (baked) detail as the surface.

**Volume:** 176×64×144 RGBA16F, about 13 MB on the GPU: rock and crystal
distance, inclusion field, milkiness. Baking takes about 18 frames.

**Autofocus.** The prototype probed the centre ray on the CPU every frame and
smoothed it. The handoff's options were analytic focus, a stateless probe pass
over past times, or a state texture. The lens reads the depth at the middle of
the frame from the scene target instead: no state, no extra pass, the same
subject in focus. What it gives up is the probe's lag; the five-tap spread
softens the change as an edge crosses the middle.

**`ink`** drives the rim light, the glass's absorption, its internal glow,
milkiness and shadow tint, each scaled so the brand cyan (88, 199, 222)
reproduces the prototype exactly.

**Cost** (Apple M5, normal power): about 14 ms per frame at 1440×900 after
fixing AO to read the volume, about 11.5 ms at the 1296×810 a 1440×900-point
Retina window renders at `resolution_scale` 0.45. At `frame_rate` 30 that is
roughly a third of the GPU while the scene moves, and nothing once it parks.

**fxc.** HLSL has no real function calls: fxc inlines everything, and the
prototype's shape — a shadow march and AO inside each shading call, a secondary
march and simple shading inside both the crystal and the floor — expanded past
what fxc survives (it crashed compiling it). The port computes the shadow and AO
once per pixel at whatever was hit and passes them in, and defers the two
secondary rays (the view through a crystal, the floor's reflection) to a single
march after shading, with a weight: both enter the final colour linearly, so
the picture is unchanged (mean difference 0.3 of a level).

Validated against headless captures of the prototype at fixed times (a patched
copy that bakes in one frame and freezes the clock): framing, materials, focus
and bloom match; the remaining difference is the prototype's slight focus lag.

## Shared choices

- **Brightness ceiling 0.5** (`Lens.level`, the `brightness` option), as Earth.
- **`idle: "freeze"`** — both are composed stills. The lens chain, grain and
  bake all stop with the frame.
- **No GLSL** — the web backend binds neither a lens nor volumes.
- **Built in**, like Earth: neither needs package data, but both need PuiKit
  descriptors that the `user_api` firewall keeps out of an extension's reach.
- **HLSL** is a mechanical port of the MSL (dialect spellings, globals for
  textures, uniforms read from the cbuffer, `[loop]` on long loops so fxc does
  not unroll them).

## Open items

- Hand check in the desktop app on macOS and Windows: both themes, the Crystal
  bake's half-second, focus pulls, legibility of real file lists.
- Windows GPU cost on an integrated GPU, and fxc compile time for Crystal on
  theme switch.
- Web backend: lens, volumes and a GLSL dialect.
