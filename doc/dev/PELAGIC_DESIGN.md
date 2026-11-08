# Pelagic theme — design report (Phase 1)

> **Status:** implemented on the decisions recommended here; see
> [PELAGIC_IMPLEMENTATION.md](PELAGIC_IMPLEMENTATION.md) for what was built.

A picture theme that films open water from about 10 m down, looking up:
jellyfish, Snell's window, swaying sun shafts, marine snow, a hazy reef and,
now and then, a distant turtle. It starts from the approved WebGL2 prototype
(`temp/pelagic-handoff/pelagic-prototype/index.html`). This report checks how
the prototype fits XeFM's background pipeline and plans the port. It is written
against XeFM `a6bdfe75` (after #858), with PuiKit 1.22.0 installed (floor 1.20.1).

Nothing here is implemented. The measurements come from the prototype itself,
run on this Mac's GPU, and from XeFM's real lens. The harness is kept in
`temp/pelagic-design/harness/` (gitignored), with the contact sheets
`temp/pelagic-design/lens_levels.png` and `resolution_crops.png`.

Contents: [1 Findings](#1-findings) · [2 Lens mapping](#2-the-lens-mapping) ·
[3 Stateless](#3-stateless-and-speed) · [4 Options](#4-options) ·
[5 Port plan](#5-port-plan) · [6 Performance](#6-performance) ·
[7 Palette and legibility](#7-palette-ink-theme-spec-legibility) ·
[8 Built in, names](#8-built-in-and-names) ·
[9 Decisions for crftwr](#9-decisions-for-crftwr) ·
[10 Phase 2 tasks](#10-phase-2-tasks)

---

## 1. Findings

**Open Issues and Discussions.** None is about themes, the lens or picture
scenes. The nearest is #857 (match the title bar to a theme's light/dark
polarity). It would treat Pelagic as a dark theme like the others and needs
nothing from this design. #732 (image viewer stall) is unrelated.

The handoff's §2.1, checked:

| Claim | Verdict |
|---|---|
| Pelagic needs no PuiKit change | **Confirmed.** It needs a scene pass into linear HDR, then bloom, the tone map, a vignette and grain. `lens_shader()` (`xefm/background_lens.py`) provides all of them. Pelagic uses no textures, bakes, 3D targets or derivatives. The only uniform it reads is `time` (and `resolution`). |
| `Look` covers the post pass, with different numbers | **Confirmed, and closer than expected.** The lens's tone map is the prototype's exact Narkowicz ACES followed by gamma 2.2 (`lens_composite`), so `gain` 1.15 reproduces the prototype's `×1.15` exactly. §2 has the numbers. |
| `lens_shader(source, source_hlsl, look)` with one `Look` | **Confirmed.** The signature is now `lens_shader(source, source_hlsl, looks, period, transition, scene_inputs, scene_targets, scene_once)`. A bare `Look` is accepted as a cycle of one, and `period`/`transition` then do nothing. |
| `frame_rate`, `resolution_scale`, `pixel_density`, `idle` are per-scene `Shader` fields | **Confirmed.** `crystal_shader()` sets `resolution_scale`, `frame_rate` and `idle`. Earth also sets `pixel_density` (`background_earth.py`, `PIXEL_DENSITY = 2 * RESOLUTION_SCALE`). |
| Windows reuses the last frame when nothing changed | **Confirmed** (`BLOCKS_CRYSTAL_IMPLEMENTATION.md`, "Windows frame reuse"). Also: D3D compiles a new scene on **worker threads** and caches the bytecode on disk (PuiKit `_d3d_shader.py`, `set_shader`). A slow fxc compile is a backdrop shown for longer on the first switch, not a UI freeze. A crash is still a crash. |
| Web runs no passes, no GLSL needed | **Confirmed** (`BACKGROUND_LENS_SYSTEM.md`, Open items). |
| Built in, because of `Target`/`Pass` | **Confirmed.** `lens_shader` returns `Target`/`Pass` descriptors, which the `user_api` firewall keeps out of extensions. |
| `DialectParity` holds constants equal | **Confirmed** (`test/test_background_shaders.py`, which parses `constant`/`static const` int/uint/float). Table arrays need their own test, as `test_dialects_share_their_constants_and_tables` does for Crystal. Picture scenes are listed in `PICTURES` in that file, and `test_every_scene_dissolves_when_idle` expects `"freeze"` for them. |
| Reduced motion: a still frame, no fade | **Confirmed, with a nuance.** `MacOSBackend._bg_target` returns 0 under reduced motion, so the scene **coasts down the normal ramp** to a stop and holds that frame. `_bg_fade_target` never fades under reduced motion. Nothing Pelagic-specific is needed. |

Corrections to the handoff's description of the prototype:

- **Strand cost.** The handoff gives "up to about 200 `raySeg` per jellyfish".
  The maximum is **112**: the fringe species has 22 strands × 4 joints plus
  4 arms × 6 joints. The long species has 10 × 8 + 24 = 104.
- **Reversed `smoothstep`.** Two calls are reversed: the bell body
  `smoothstep(1.02, 0.97, e)` and the turtle plastron
  `smoothstep(0.0, -0.10, q.y)`. The near-camera fade
  `smoothstep(1.4R, 3.0R, d)` and the margin cut are the normal way round.
- **A bigger HLSL/MSL hazard than reversed `smoothstep`.** The prototype
  squares signed values through `pow`: `pow((e-1.0)/0.075, 2.0)`,
  `pow((q.y-cut)/0.05, 2.0)`, `pow((length(q.xz)-rimR)/0.06, 2.0)` and
  `pow((q.y-b*0.42)/0.10, 2.0)`. `pow` of a negative base is undefined. HLSL
  computes it as `exp2(y·log2 x)`, which gives NaN, and Metal under fast math
  does the same. The browser evidently folds `pow(x, 2.0)` to `x*x`, or the
  bell would not render. Every `pow(·, 2.0)` becomes an explicit square. §5
  lists all of them.
- **The opening frame.** The page starts at `simT = 40`, not 0. That is the
  first frame crftwr saw on every load (§3).
- **Network dependencies.** The page loads Google Fonts, for the overlay only.
  The shaders need nothing.

---

## 2. The lens mapping

**Method.** This compares the real lens, not an imitation of it.

1. A headless Chrome harness (ANGLE on Metal, the real M5 GPU, not
   SwiftShader) renders the prototype's scene pass at a fixed `t` and reads
   back its **linear HDR** as float32. It also renders the prototype's own
   post pass from that same buffer. These GPU frames match the handoff's
   SwiftShader references to within 0.6–1.7 levels on average.
2. The HDR goes into two 8-bit PNG planes as a 16-bit log code. A
   two-texture MSL scene decodes them, and that scene runs through
   `lens_shader()` on Metal via `MetalBackground.render_to_texture`, as the
   tests render. The round trip is exact to half a level.
3. The result is compared with the prototype's post pass. Both are cropped by
   4 px (the lens antialiases the outermost pixel, as it does for every
   picture theme) and averaged 4×4 so grain and dither drop out. Grain is set
   to 0 for the comparison.

**Proposed look:**

```python
LENS = Look(gain=1.15, bloom=1.5, threshold=1.6, vignette=0.47, grain=0.06,
            dof=0.0, level=brightness)
```

| Field | Prototype | Lens | Why |
|---|---|---|---|
| `gain` | `aces(c × 1.15)` | 1.15 | The same tone map and gamma, so this is exact. |
| `vignette` | `1 − 0.30·|0.85q|²` | 0.47 | The lens uses `smoothstep(1.2, 0.25, r)`. 0.47 matches at the corners (0.57) and the edge midpoints (0.78). The lens is flat over the middle third, so the centre is up to ~2 levels brighter. That is the main residual everywhere. |
| `bloom`, `threshold` | luminance soft knee 0.45–1.6, 2× separable blur at ¼ resolution, ×0.55 | 1.5, 1.6 | Bloom matters in one place only: around the sun when the camera faces it (t459). The HDR of the other four frames peaks at 0.3–1.0, so neither post pass blooms them visibly. The prototype's single Gaussian (σ ≈ 4% of the height) concentrates more glow at the sun's core than the lens's six-level pyramid, which spreads it wider. More `bloom` brightens the periphery before it fills the core (tried up to 8, every combination worse), so 1.2–2.0 is the useful range. |
| `grain` | ±0.006 uniform | 0.06 | The lens's grain is `±0.5 · grain · 0.22 · (0.35 + 2.6 l(1−l))`. At this scene's typical display luminance (≈0.36) that is ±0.006 at `grain` 0.06, Crystal's value. The lens also adds its ±½/255 dither. |
| `dof` | none | 0 | The scene still writes `1/tEnd` to alpha (§5), for a future look. |
| `level` | none | the `brightness` option | §7. This is the one real departure from the approved look. |

**Side by side** (mean / p99 absolute difference, in levels of 255, on 4×4
averages):

| Frame | t40 | t95 | t162 | t300 | t459 | t459, sun region |
|---|---|---|---|---|---|---|
| Proposed look | 1.5 / 5.4 | 1.7 / 6.2 | 1.4 / 5.6 | 1.4 / 5.2 | 1.9 / 11.9 | 4.8 / 48, max 74 |
| Same, `bloom` 0 | 1.5 / 5.4 | 1.7 / 6.2 | 1.4 / 5.6 | 1.4 / 5.2 | 1.8 / 11.2 | 4.7 / 50, max 75 |

So the lens reproduces the prototype within about 2 levels everywhere except
the haze close around the sun at t459, which the lens's bloom kernel cannot
shape the same way. The sun disk and facets match. The lens draws the haze
around them a little crisper near the core and a little wider further out.
`temp/pelagic-design/lens_levels.png` shows t95, t300 and t459 side by side:
at level 1.0 the two can hardly be told apart.

The bloom values are a starting point. The sun haze is a judgement on a
moving picture, so set them in the Phase 2 side by side in the app.

---

## 3. Stateless, and speed

**Confirmed.** The scene reads `uTime`, `uRes`, `uJelly` and `uHdrScale`, and
nothing else. It uses no feedback target and no clock of its own.

- The camera and the jellyfish paths are closed forms in time.
- The beat surge is `floor(phase) + smoothstep(0.08, 0.55, f)`. The path
  parameter jumps by 2.4 per beat in a smooth step, with no integration.
- The turtle slot is `floor((t − T0)/P)`. Its path is placed from
  `camera(T0 + kP + D/2)`, also a closed form.

The only prototype-side state is the page's: `simT` integrated from
`requestAnimationFrame`, the speed slider, "Next turtle", and grain that
freezes when paused (`uTime = playing ? simT : 0`). The backend clock replaces
all of it.

**Speed 1.0**, as Blocks and Crystal use. The turtle's period (216.66 s)
equals the camera's tilt period (2π/0.029) in shader time, so the two stay
locked at any speed. Other speeds are only untuned.

**Start at 40 s.** The backend clock starts at 0 on every apply. The
prototype opened at `t = 40` on every load, so that is the opening crftwr
approved. Add `START = 40.0` as Crystal does (`START` there is the page's
`s = 24`): `t = time + START`. The first turtle pass then comes 92 s after
launch, not 132 s.

**No seed.** Like Crystal, Pelagic is one continuous take, not slots, so
`seed` is not used. A seed-based start offset would give a different opening
each launch, but the reseed after idle would then need a dip (as Earth has)
to avoid a cut. That is not worth it for a scene that never repeats within
five minutes anyway.

**Quirks kept as approved** (decide in §9 whether to change them):

- Each snow particle sinks through `fract(t·0.004·(1+h.y))` and jumps back up
  a 1.6 m cell every 125–250 s. Snow is faint and the jump has not been seen
  in review.
- A particle that has sunk out of its home cell can be clipped by the DDA,
  which only tests the home cells along the ray.
- Float32 `time`: the finest chop octave moves at ω ≈ 8 rad/s. After about a
  day of *animated* time its phase loses about 0.06 rad of precision, and the
  last octave shimmers. The idle clock only advances while the app is in use,
  so this takes weeks of normal use. Earth and Crystal share the same class
  of limit.

---

## 4. Options

Follow Crystal: `OPTIONS`, `_clamped()`, constants baked into `_MSL_OPTIONS` /
`_HLSL_OPTIONS`, `pelagic_look()` and `pelagic_shader(**options)`.

| Option | Range, default | Baked as | Expose? |
|---|---|---|---|
| `jellyfish` | 0–6, **6** | `constant int JELLYFISH` (the loop's `break`) | **Yes.** It is also the user's lever on a slow GPU: jellyfish are 35–50% of the frame (§6). |
| `brightness` | 0–1, default per §7 | `Look.level` | **Yes**, as on every picture theme. |
| `exposure` | 0.1–4, 1.0 | `EXPOSURE` multiplying the scene's HDR | **Yes**, for consistency with Earth and Crystal. It moves the picture along the ACES curve, which `brightness` does not. |
| `turtle` | on/off | — | **No.** It is part of the approved picture, costs nothing outside its 60 s pass, and an option for it would only invite a question. Add it later if someone asks. |

Bad values fall back to the defaults, and numbers are clamped, as in the
existing scenes.

---

## 5. Port plan

**MSL is the source of truth, and HLSL is a mechanical port** with
`[loop]`/`[unroll]` attributes. There is no GLSL. The structure follows
`background_crystal.py`. Pelagic needs no textures, so the `VOL_*` macro
trick is not needed, and the bodies differ only in dialect spellings.

### Rewrites

| Prototype | Port |
|---|---|
| `uniform int uJelly` | `JELLYFISH` baked (§4) |
| `uniform float uHdrScale` | dropped |
| `gl_FragCoord` (origin bottom-left) | `pos` (origin top-left): `uv = float2(2·pos.x − res.x, res.y − 2·pos.y) / res.y`. The jitter hash `h21(pos)` stays per pixel; its pattern differs, which no one can see. |
| `void camera(t, out ro, out ta)` | return a struct `Cam { float3 ro, ta; }` |
| `bool sph(..., out t0, out t1)` | return `float2(t0, t1)` with `t1 < 0` for a miss |
| `Turtle`, `Jelly` structs | keep (both dialects support structs) |
| `mat2(1.6,1.2,−1.2,1.6)*p` in `fbm` (column-major) | `float2(1.6·x − 1.2·y, 1.2·x + 1.6·y)` |
| `rot(a)*v` with `rot = mat2(c,−s,s,c)` | `rot2(v, a) = float2(c·x + s·y, −s·x + c·y)`. Column-major, this is a rotation by **−a**. Keep that sign. |
| `atan(y, x)` | `atan2(y, x)` in both dialects (same argument order) |
| `pow(signed, 2.0)`: the bell shell, rim height, rim radius, gonad height | `sq(x) = x*x`. Also rewrite the non-negative cases (`pow(d/0.04,2)`, `pow(r.x/w,2)`, `pow(d/sz,2)`) so that no `pow(·, 2.0)` remains: cheaper, and safe under fast math. |
| reversed `smoothstep(1.02, 0.97, e)`, `smoothstep(0.0, −0.10, q.y)` | `1 − smoothstep(0.97, 1.02, e)`, `1 − smoothstep(−0.10, 0.0, q.y)` |
| `vec4 K[4]` built inside `swell()`, `normalize(K[i].xy)` per call | a constant table `SWELL[4]` of `(dir.x, dir.z, k, amp)` with directions **normalized in Python** and `ω` precomputed, emitted to both dialects from one Python tuple (`SWELL_WAVES`), plus a table test |
| `vec3 tc[9]`, `vec3 ac[7]` with loop-variable indices | keep. Metal handles them, and fxc places them in an indexable temp register array, which is legal inside `[loop]`. |
| `refract()`, zero at total internal reflection | Both MSL and HLSL `refract` return a zero vector at total internal reflection, so the `dot(tr,tr) > 0` test ports unchanged. Keep the TIR branch exactly: it is what makes the window's edge seamless. |
| `abs(1.0/rd)` in the snow DDA (infinite for an axis-aligned ray) | `1.0 / max(abs(rd), 1e-6)`. Metal's fast math does not promise IEEE infinity. |
| `fract`, `mix`, `vecN`, `mod` | `frac`, `lerp`, `floatN` in HLSL; scalar `float3(x)` spelled out |
| Output `vec4(col, 1)` | `float4(max(col·EXPOSURE, 0), hit ? 1/tEnd : 0)`. "No hit" means the open-water fog (`tEnd` = 90). |

Constants (`SIG`, `AMB_HI`, `AMB_LO`, `SUN_AIR`, `BEND`, `CEN`, `TURTLE_P/D/T0`
and the like) become `constant float` / `static const float` scalars, so that
`DialectParity` covers them. The `float3` ones become scalar triples where the
parity test needs them (Earth did the same).

### Free speed-ups that leave the picture unchanged (measured, §6)

- **Strand culling.** Per joint *s*, take the distance from the ray to the
  axis segment `tc[s−1]..tc[s]`. Skip all strands' segment *s* when that
  distance exceeds the largest strand offset there,
  `(S.w·1.05 + 0.8·amp·fs)·R`, plus four glow widths. The loops swap order
  (joints outside, strands inside); the sum does not change. Measured: HDR
  identical to 2.6e-6, 5–28% faster.
- **Floor gate `rd.y < 0`** instead of `< 0.12`. The floor never rises above
  −12.15 and the camera never drops below −10.9, so a level or upward ray
  cannot reach it. Exact.
- **Compute `turtle(t)` only inside a pass.** Its three `floorY` calls and its
  `camera()` call run on every pixel today. Exact.

Starting the floor march at the y = −12.15 plane is **not** exact. It moves
where the march steps land (HDR difference up to 1.4e-2) and saved under 1 ms,
so leave it out.

### fxc risk

Crystal crashed fxc because the shape was **nested**: a shadow march and AO
inside every shading call, and a secondary march inside the crystal and floor
shading. Pelagic's long loops are **siblings** at the top level:

```
main ─ floor march (72) ─ turtle march (64, during a pass) ─ surface/floor shading
     ─ god-ray march (40 × lightPat → swell[4] + 2 noises)
     ─ snow DDA (28)
     ─ jellyfish loop (6) ─ bell march (30 × bellDens[4])
                           ─ strands (8 joints × 22) + arms (4 × 6) ─ raySeg
                           ─ waterLight × 3 (→ lightPat → swell[4])
```

The deepest nesting is jellyfish × joints × strands, a triple loop around a
small body. It has no march inside shading and needs no texture derivatives
(Pelagic samples nothing). The risk is **moderate, not Crystal-level**.
Mitigations, in order:

1. `[loop]` on every loop of 6 or more iterations: the jellyfish loop, the
   bell march, joints, strands, arms, god rays, floor, turtle, snow. Use
   `[unroll]` only on the 2–4-iteration inner loops (`swell`, `fbm`, the
   gonad rings, the turtle's flipper pair, the caustic's 3×3).
2. Keep `renderJelly` a single call site inside a real `[loop]` over `i`, so
   fxc inlines it once, not six times.
3. If fxc still struggles, hoist `waterLight` (three `lightPat` calls) and the
   `trail()` joint positions out of the strand loop. They depend on the
   jellyfish, not the pixel, but the bodies are small.

Measure `D3DCompile` time on the Windows guest (`make test-vm GUEST=qa-win`)
as the first Windows step, before any visual work. Compiles run off the UI
thread, so the threshold is "it finishes, and in seconds", not a frame
budget.

---

## 6. Performance

### Measurements

There is no native port yet, so this measures the **prototype's scene pass on
the real GPU** through Chrome (ANGLE translating to Metal). Each run is 30
frames back to back with a flush per frame, best of 2–3 runs. Without the
flush, ANGLE drops overwritten draws and reports nonsense. Time scales
linearly with pixel count (320×180: 1.7 ms, 1280×720: 33 ms, 1920×1080:
66 ms), which confirms the draws are real.

The Mac was **on battery in Low Power Mode**, the same worst case as the Earth
doc's table. Crystal, rendered natively the same way in the same state, took
24.0 ms at 1296×810. Its doc gives 11.5 ms on normal power, a factor of about
2.1.

**Per-feature cost**, 1280×720, Low Power Mode, ms. Each feature row is "full
minus the frame with that feature removed". Noise is about ±2–3 ms (the
turtle row reads 2–3 ms even at times it is off).

| | t40 | t95 | t162 | t300 | t459 |
|---|---|---|---|---|---|
| **Full frame** | 20.9 | 26.2 | 37.9 | 19.7 | 24.1 |
| Jellyfish, all | 8.1 | 15.1 | 19.4 | 7.5 | 10.0 |
|  · of which strands + arms | 6.4 | 13.0 | 17.7 | 6.0 | 8.2 |
|  · of which bell march | ~1 | ~1.5 | ~1 | ~1 | ~1.7 |
| God rays (40 × `lightPat`) | 7.5 | 7.8 | 8.0 | 8.1 | 8.3 |
| Floor march + shading | 3.5 | 3.0 | **14.6** | 6.1 | 5.9 |
| Marine snow | 1.5 | 1.9 | 4.7 | 5.4 | 3.5 |
| Turtle (on only at t162) | — | — | 4.6 | — | — |
| **With strand culling** | 15.8 | 20.7 | 27.4 | 22.0 | 21.4 |

Per pixel, Pelagic with culling costs 17–30 ms per megapixel in Low Power
Mode, against Crystal's 23. The lens chain alone measured 0.55 ms natively at
1440×900, which is negligible.

**Estimate for the port.** Assume the target is Earth's: `resolution_scale`
0.5 with `pixel_density` 1.0, so a 1440×900-pt window renders 1440×900
(1.30 Mpx) on Retina and on a standard display. Assume culling is in and
native Metal performs like ANGLE (unverified; expect ±30%). On normal power
that gives **10.5–18.5 ms a frame**: about 11–15 ms in typical framings, and
about 18 ms at the turtle pass with the floor in frame (t162).

### Budget

**Target 11–14 ms on an M5 at normal power** at the render size above, with
`frame_rate` 30, in line with Crystal. Typical framings land about on budget.
The turtle-and-floor framing does not, until the levers below are applied.
At 30 fps the scene takes 33–55% of the GPU while it moves (Crystal takes
about a third), and nothing once it parks.

### Levers, best first

1. **Strand culling.** Exact, measured −5 to −28%. Take it.
2. **`resolution_scale` 0.5, `pixel_density` 1.0** (Earth). The scene is soft
   and hazy, and the strands are what suffer first.
   `temp/pelagic-design/resolution_crops.png` compares 100%, 70% and 50% on
   tentacle-heavy crops: at 50% the strands soften slightly but stay intact.
   Count lines, not percentages: the approved 70% view was about 1,100 lines
   in a typical browser window, and 1440×900 at this setting is 900 lines.
   That is close to the approved density, and **more** than the 720-line
   reference frames. Going down to Crystal's 0.45 would save another 19%.
3. **The floor at t162**, the worst frame. Take the exact gate (§5), then
   measure: (a) leave the 0.25 m fine relief (`0.25·vn(x·1.3)`) out of the
   march and add it only at the hit, (b) fewer or larger steps. Both change
   the picture slightly, so check them side by side.
4. **God rays 40 → 28 steps.** The per-pixel jitter hides banding. This
   should save about 2–3 ms in Low Power Mode. Check for banding in the
   shafts toward the sun (t459). Drop the Laplacian focus from the god-ray
   `lightPat` only if a side by side shows no difference. It is what makes
   crests focus light (decision 3), so I expect it to show.
5. **`frame_rate` 30.** The bell squeeze takes 1.6–2.6 s, and the fastest
   chop octave cycles at about 1.3 Hz (23 frames a cycle at 30 fps). Neither
   should judder. Check by eye on the bell pulse and the window's ripple.
6. **The `jellyfish` option** as the user's own lever on a slow machine
   (Windows integrated GPUs are unmeasured for every picture theme).

Fewer fringe strands, and capping how many jellyfish run the full strand loop
per pixel, change the look. Culling already removes most of what they would
save, so I would not take them.

**Measuring in Phase 2:** 60 frames back to back with
`MetalBackground._encode` (`temp/pelagic-design/harness/native_time.py`
already does this for any `SHADER_KINDS` entry), at t40/95/162/300/459, on
normal power. In the app, `PUIKIT_BG_PROFILE=1`. On Windows, the D3DCompile
time on the first switch, then the frame time in the guest.

### `idle` and reduced motion

`idle: "freeze"`, as the other picture themes use. A held frame (jellyfish
mid-drift under the shafts) is a composed still. Under reduced motion PuiKit
coasts the scene to a stop and holds the frame, with no fade (§1). That is
right for Pelagic as it stands.

---

## 7. Palette, `ink`, theme spec, legibility

**`ink`: ignore it**, as Earth does. The water's colour *is* the scene: red
dies first through `SIG = (0.30, 0.072, 0.058)`, and the in-scatter, sun shafts
and jellyfish glow all inherit that cyan. Tinting `AMB_*` or the jellyfish by
`ink` would fight the extinction and look like a filter over the water, so I
would not offer it. Add Pelagic to `INKLESS` in `test_background_shaders.py`
(the existing `test_the_scene_ignores_ink` pattern).

**Brightness: the one real departure from the approved look.** `level` is a
multiplier on the final display colour, not a clip. The approved frames are
mid-bright:

| Frame | median brightest channel | brightest pixel | pixels with a channel above 0.5 |
|---|---|---|---|
| t40 | 0.39 | 0.73 | 16% |
| t95 | 0.45 | 0.78 | 38% |
| t162 | 0.38 | 0.73 | 17% |
| t300 | 0.34 | 0.70 | 12% |
| t459 | 0.40 | 0.86 | 23% |

Earth is mostly black space, so its 0.5 ceiling only cut highlights. On
Pelagic, 0.5 **halves the whole picture**: the median drops from about 0.4 to
0.2, and the water reads as dusk. `temp/pelagic-design/lens_levels.png`
shows 1.0, 0.7 and 0.5. Pelagic's peaks are only 0.86, where Earth's sun is
thousands of times brighter, so the ceiling exists for a different reason
here. crftwr approved legibility in the prototype's overlay with panes at 58%
opacity over the *uncapped* picture.

**Recommendation:** default `brightness` **0.7** (a pixel then reaches at most
0.60), and decide in the Phase 2 legibility review with real file lists at
t95 (the brightest window) and t459 (the sun). Fall back to 0.5 if text near
the window or the sun loses contrast. Keep the `brightness` option either
way. The decision is crftwr's (§9).

**Starting theme spec** (from the prototype's overlay; crftwr has not
finalised it):

```python
("Pelagic", dict(bg=(3, 22, 26), fg=(207, 230, 234), muted=(127, 166, 173),
                 accent=(88, 199, 222), surface=(5, 20, 24), selection=(24, 72, 84),
                 accent2=(255, 154, 82),
                 status=lambda p: mix(p["bg"], p["accent"], 0.14),
                 footer=lambda p: mix(p["bg"], p["accent"], 0.14),
                 file_types={"directory": (159, 216, 227), "link": (236, 132, 200)},
                 cursor={"active": (255, 154, 82)},
                 syntax={...},              # Crystal's, re-checked on this background
                 post_effect={"drop_shadow": 0.5},
                 animation={"type": "pelagic", "speed": 1.0, "opacity": 1.0},
                 opacity=0.6)),
```

- `bg` `#03161a` is the scene's own deep-water colour looking down, so the
  backdrop shown while compiling and on the web
  sits with the picture.
- Pink links, as Earth and Crystal use, because a frame the colour of the
  amber cursor disappears (#846).
- `selection` is a guess at the overlay's `rgba(88,199,222,0.16)` cursor row
  over the surface. Tune it in the review.
- The accent is the brand cyan, the same as Crystal's. The two themes differ
  in their bases (graphite against deep teal), which is enough.

Legibility checks for Phase 2: t95 and t300 (the window behind the upper
rows), t459 (the sun behind the top-left pane), and a bell rim in the sun
behind a selected row.

---

## 8. Built in, and names

**Built in** (crftwr's decision). Pelagic needs `Target`/`Pass`, which the
`user_api` firewall keeps out of extensions, the same reason as for the
other picture themes. It ships no package data: the whole cost is one source file,
`xefm/background_pelagic.py`.

**Names** (crftwr's decision). Scene key `pelagic`, theme **Pelagic**.

- *Pelagic* is accurate: the open-water zone, away from shore and floor,
  which is what the frame mostly shows. It is one word, like Earth, Blocks
  and Crystal, and unlikely to clash with a user's own theme name.
- *Ocean* is generic and the likeliest name for a future plain-colour theme
  (or a user's).
- *Deep Sea* is inaccurate: the camera is about 10 m down in sunlit water.
  It is also two words.

---

## 9. Decisions for crftwr

1. **Default `brightness`**: 0.7 (recommended, settled in the legibility
   review) or 0.5 like the other picture themes, which halves the approved
   picture (§7).
2. **Name**: Pelagic (recommended), Ocean or Deep Sea (§8).
3. **Built in** (recommended) or an extension (§8). An extension is not
   possible today without a new public contribution point for passes.
4. **`ink`**: ignored (recommended), or tint the water or jellyfish (§7).
5. **`idle`**: `"freeze"` (recommended) or `"fade"` (§6).
6. **Options exposed**: `jellyfish`, `brightness`, `exposure` (recommended).
   Add `turtle` only if wanted (§4).
7. **Opening frame**: start at the prototype's t = 40 (recommended), or a
   seed-based random start with a dip on reseed (§3).
8. **Approved quirks**: the snow's wrap and clip, and the frame-edge pixel the
   lens darkens on every picture theme. Keep them (recommended) or fix them
   (§3).
9. **Look changes for speed**, beyond the exact ones: floor relief at the
   hit, 28 god-ray steps. Accept them only if the side by side shows nothing
   (§6).

---

## 10. Phase 2 tasks

Sizes: S ≈ under 2 h, M ≈ half a day, L ≈ a day or more.

| # | Task | Size |
|---|---|---|
| 1 | `xefm/background_pelagic.py`: docstring, `OPTIONS`, `START`, `RESOLUTION_SCALE` 0.5, `PIXEL_DENSITY` 1.0, `FRAME_RATE` 30, the `SWELL_WAVES` table emitted to both dialects, the **MSL body** with every §5 rewrite and the three exact speed-ups, `LENS`, `pelagic_look()`, `pelagic_shader()` | L |
| 2 | Metal side by side against the prototype at t40/95/162/300/459. Reuse `harness/capture.py` for the prototype's HDR and compare HDR to HDR (before the lens) first, so scene errors and lens errors stay apart. Then tune `bloom` around the sun | M |
| 3 | Performance on normal power at those five times. Apply levers 3–5 only if they hold up side by side. Record the numbers in the implementation doc | M |
| 4 | **HLSL port**, `[loop]` attributes, parity, then D3DCompile time and frame time in `qa-win` before any visual work there. Restructure per §5 if fxc struggles | M (L if fxc fights) |
| 5 | Registration: `SHADER_KINDS`, `SCENE_OPTIONS` gated on `AVAILABLE`; `PICTURES` and `INKLESS` in `test_background_shaders.py` | S |
| 6 | Theme: the `_THEME_SPECS` entry, its comment, and the `xefm/_config.py` theme comments | S |
| 7 | `test/test_background_pelagic.py`: options baked and clamped; dialect constants and the swell table equal; built in; a picture under the ceiling; frozen at `speed=0`; ignores `ink`; turtle pixels only inside its slots (render with the jellyfish off at a mid-pass time and an off-pass time); `jellyfish=0` draws no bells; the opening is t = 40 | M |
| 8 | Legibility review with real file lists at t95, t300, t459; settle `brightness`, `opacity`, `selection` with crftwr | S (with crftwr) |
| 9 | Docs: `doc/dev/PELAGIC_IMPLEMENTATION.md`; "Picture themes" and a "The Pelagic scene" section in `doc/COLOR_SCHEMES_FEATURE.md` **and its `.ja.md`**; `make check-docs`. Keep or delete this design report once the implementation doc supersedes it | M |
| 10 | Hand checks in the app on macOS, and on Windows through the VM: swaying shafts, bell contraction, trailing tentacles, no net on the surface, a seamless window edge, the glow toward the sun, the turtle low and far off, the idle freeze, reduced motion | M |

PuiKit: no change, and no floor bump. `background_lens.AVAILABLE` already
gates the scene on PuiKit 1.18.0 and later, and the floor is 1.20.1.
