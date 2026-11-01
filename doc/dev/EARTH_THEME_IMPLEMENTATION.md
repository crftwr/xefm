# Earth theme — implementation

The **Earth** theme puts a real-time view of the planet from orbit behind the
file panes: textured surface and clouds, single-scattering atmosphere, a sun
that shrinks and reddens behind the limb, stars, a slow camera between composed
shots, and lens looks — paired at random into hundreds of scenes. User-facing behaviour is in
[`doc/COLOR_SCHEMES_FEATURE.md`](../COLOR_SCHEMES_FEATURE.md#the-earth-scene).
It started from a WebGL2 prototype; this page records how it was brought into
the background pipeline and why.

| Where | What |
|---|---|
| `xefm/background_earth.py` | The scene (MSL source of truth, HLSL port), shot table, lens presets, `earth_shader()` |
| `xefm/background_shaders.py` | `SHADER_KINDS["earth"]` and the `SCENE_OPTIONS` registry |
| `xefm/app.py` | `_resolve_background` (scene options), the `Earth` theme spec |
| `xefm/assets/earth/` | `day.jpg`, `clouds.jpg`, `relief.jpg`, `SOURCES.md` |
| `tools/make_earth_textures.py` | Downloads the NASA sources and builds the three maps |
| PuiKit `puikit/background.py` | `ShaderTexture`, `Lens`, `Shader.textures`, `Shader.lens` |
| PuiKit `backends/_bg_lens.py`, `_bg_textures.py` | Lens chain shaders and packing; off-thread texture decode |
| PuiKit `backends/_metal.py`, `_d3d_shader.py` | Texture upload, HDR target and lens passes per backend |

## What PuiKit gained

Two additions to `Shader`, both appended with defaults that reproduce the old
behaviour (PuiKit's additive recipe). PuiKit's `docs/backgrounds.md` §3.1–3.2
is the reference; in short:

- **`textures: tuple[ShaderTexture, ...]`** — bound by position, texture *i*
  with its own sampler in slot *i* (`[[texture(i)]]`/`[[sampler(i)]]`,
  `t i`/`s i`). Per texture: `srgb`, `wrap_u`/`wrap_v`, `mipmaps`. Decoded by the
  OS decoder on a worker thread; until the upload the frame is the bare
  backdrop, and a failed load stays that way — the same outcome as a compile
  error. The web backend binds none and shows the backdrop.
- **`seed`, `seed_prev`, `seed_mix` uniforms and `puikit_slot_hash`** — a
  whole number the backend draws when the background is set, and again once
  when the user comes back to a parked background (`backends/_bg_seed.py`),
  with the old one kept and an eased 0→1 mix over six seconds; and a 32-bit hash
  in every prelude with a bit-exact Python twin (`slot_hash`). A scene hashes
  `floor(time / period)` with the seed to pick what each period shows.
- **`Lens.level`** — the ceiling of the lens's result, a multiplier on the final
  display colour. Earth uses 0.5: no pixel above half white.
- **`lens: Lens | LensCycle | None`** — a look for the **background only**. With a lens the
  scene renders linear HDR into an RGBA16F target; a 6-level bloom pyramid, an
  optional streak, and one composite pass tone-map, grade and mix it over the
  backdrop by `opacity` × idle fade.

### Why a separate lens, not `PostEffect`

`PostEffect` is confirmed whole-frame: macOS applies it as Core Image content
filters on the view that draws the UI, Windows as Direct2D effects over the
composed frame. Distortion, aberration and grain there would land on the file
names. A lens lives between the scene and the backdrop instead, so the two
compose — Earth uses a lens *and* the `drop_shadow` post effect — and the
existing `post_effect` theme key is untouched. Generalising `PostEffect` with a
target was rejected: its fields (`roll`, `drop_shadow`, the CI/D2D realization)
are about the output surface, and the lens's HDR contract with the scene has no
meaning there.

## Scenes: hundreds of them, chosen at random

A scene is a shot (10), a variant of it (12: variant 0 is the shot as
composed, the others move longitude, latitude, altitude, tilt, sun direction,
focal length, framing, the limb angle and the roll by fixed amounts hashed from
the shot and variant; the altitude, tilt and roll ranges are per shot, so the
low-orbit shots — `leo`, `horizon`, `ocean`, down to about 170 km — can turn the
horizon any way round) and a lens look (10) — 1,200 in all. The roll turns the
finished picture on the screen, after the sun and the limb framing are placed,
so a rolled scene is the same lit composition at a new angle. Each 49-second slot (31 s held, an 18 s move) hashes with the seed:
`h % LENS_COUNT` is the look, which PuiKit's `LensCycle` evaluates on the CPU
from the same hash; `h / LENS_COUNT` picks shot and variant in the shader. So
the look and the camera change together without either side telling the other
anything per frame.

The seed is what makes it random across runs. PuiKit draws one on
`set_background`, so XeFM opens on a random scene. A background that parks owes
a new one, paid on the first tick at which the app is really in use again —
focused, recent input, not reduced motion. Paying it whenever the tick re-arms
was the first version and was wrong: a mouse crossing an unfocused window
re-arms the tick on every move, the tick parks again at once, and each of those
wakes cut to another scene. The change is also not a cut: the shader computes
the path for both seeds and blends the two poses by `seed_mix` (eased in wall
time, so the blend starts and ends at rest), and `LensCycle` blends the two
looks the same way.

### The camera path

The pose is twelve numbers (longitude, latitude, log altitude, tilt, frame
offset, log lens length, sun yaw and pitch, limb weight and angle, roll — log
altitude so the low orbits cannot dive in). Each scene contributes two knots:
it **enters** at its composition minus half its drift over the hold and
**leaves** at the composition plus half. The path is one monotone cubic
through all the knots (Hermite segments, tangents by the Fritsch–Butland
weighted harmonic mean of the neighbouring slopes, zero where they disagree):

- the hold is a slow, steady drift, and the move to the next scene starts from
  that drift and arrives at the next scene's — velocity is continuous at every
  knot (checked numerically: the mismatch falls with the finite-difference
  step);
- a component never turns back inside a segment (monotone); where the scene
  before and the scene after lie on opposite sides of this one, that component
  eases to a stop at the knot and turns, instead of flicking round;
- each scene's drift is pointed from the scene before toward the scene after,
  so the hold, the move in and the move out run the same way wherever they can.

Two earlier versions explain the design. Blending two moving poses with a
smoothstep left the transition ending at full deceleration straight into a
drift that could point the other way — a visible bounce. Slow sines for the
drift stopped at their turns and read as no motion on a dark disc; the drift is
linear in each hold, and includes a pan, a zoom and a roll so it shows whatever
the shot holds.

Each slot's evaluation needs the compositions of five scenes (k−2…k+2: the
knots of k−1…k+1 and the drift headings that place them), all a few dozen
operations per pixel, small beside the atmosphere.

## Everything is a function of `time`

The backend advances a shader without XeFM, so the prototype's CPU-side
smoothing could not come along. The shot table is constant arrays in the
shader; the scene in view is the slot's hash (above), the camera follows the
path above, and the `LensCycle` blends the two looks over each slot's last
`TRANSITION` seconds, the same seconds the camera travels. The `rise` shot's limb oscillation, the in-scene
drift, the earth's spin, cloud drift and the hand-held "breath" are closed-form
in `time`.
The camera is recomputed per pixel; it is a few dozen operations, negligible
beside the atmosphere.

A per-frame uniform provider in PuiKit was the alternative. It would have
broken the "a scene is just a shader" model (and the parked/idle logic, which
only scales `time`) for no visual gain.

**Static options** (shot, cloud height, exposure, the number of looks, the
slot timing) are baked into the source as constants by `earth_shader()` when
the theme resolves; the lens is a `Lens` or `LensCycle` descriptor. A generic params uniform block was the alternative; baking keeps
PuiKit's uniform contract unchanged, lets the compiler fold a fixed shot, and
the recompile happens once per theme apply, where a compile happens anyway.
`SCENE_OPTIONS` maps a scene to its option keys and builder, so a second scene
with options is a registry entry, not a branch in `_resolve_background`.

## Port notes (GLSL prototype → MSL → HLSL)

- `out vec3 trans` → `thread float3 &trans` (MSL) / `out float3` (HLSL).
- `mat3` rotations replaced by `rot_y`/`rot_x` on vectors — sidesteps
  column- vs row-major entirely.
- Textures: `texture()` → `sample(s, uv, level(l))` / `SampleLevel`. The level is
  **computed** from the pixel's footprint on the sphere (`lod_for`), not taken
  from derivatives: derivatives jump at the date-line seam and are illegal in
  HLSL loops.
- `pow(tex, 2.2)` dropped: the day map is an sRGB texture, decoded by the
  sampler.
- Reversed `smoothstep(hi, lo, x)` rewritten as `1 - smoothstep(lo, hi, x)`.
- HLSL: scalar `float3(x)` constructors spelled out; `lit` (an intrinsic) renamed
  `sunlit`; textures/samplers are globals.
- No GLSL: the web client binds neither textures nor a lens, so there is
  nothing to transpile to.

The scalar parity test covers the constants; `test_background_earth.py` adds
the shot-table arrays and the baked options.

## Performance

Measured on an Apple M5 (10-core GPU) **on battery in Low Power Mode** — a worst
case — as sustained wall time per frame with the GPU kept busy:

| | 1440×900 | 2160×1350 |
|---|---|---|
| Earth, before tuning | 11–14 ms | 18–23 ms |
| Earth, shipped | 8–11 ms | 15–20 ms |
| lens chain alone (`clean`) | ~4 ms | ~7 ms |

Levers taken:

- **Analytic light depth.** The 6-step march toward the sun from every one of
  the 14 view samples was replaced by Schüler's Chapman-function approximation,
  with an explicit ground-shadow test. Visually indistinguishable.
- **Milky Way gated to its band.** Its two 5-octave fbm calls were a third of
  the frame on sky pixels; they now run only where the band is visible.
- **`resolution_scale` 0.5.** At 0.5 vs 0.75 upscaled to Retina, the surface is
  indistinguishable (the maps, not the render, limit detail); it halves the
  cost. A 1440×900-point window on a 2× display renders 1440×900.
- **`idle: "freeze"`.** Earth is a picture: when the app parks the animation it
  coasts to a stop and holds the shot, and nothing — scene or lens chain — is
  drawn while parked.

Not taken (yet): a transmittance LUT, fewer view samples, a reduced-rate bloom.
Windows iGPU timing is unmeasured; the D3D11 path is verified for correctness
in the Windows VM (`make test-vm GUEST=qa-win`), not for speed.

Measuring: render offscreen with `MetalBackground._encode`, commit 60 frames
back to back and divide wall time — per-buffer `GPUStartTime`/`GPUEndTime`
overlaps when pipelined, and a single frame measures the GPU waking up.

## Assets

NASA Earth Observatory imagery (no copyright restrictions; credit in
`xefm/assets/earth/SOURCES.md`), built by `tools/make_earth_textures.py`:

| File | Size | Bytes |
|---|---|---|
| `day.jpg` | 4096×2048 | ~0.9 MB |
| `clouds.jpg` | 4096×2048 | ~2.2 MB |
| `relief.jpg` | 2048×1024 | ~0.5 MB |

`relief.jpg` packs the slope (R east, G north; a tangent-space normal's x/y)
and the ocean mask (B), saved without chroma subsampling. Every map is RGB
because the OS decoders hand back 32-bit pixels only. They ship as package data
(`assets/*/*` in `pyproject.toml`); the macOS and Windows app builds copy the
whole `xefm/` tree. About 3.6 MB added to the wheel and app packages; GPU memory
with mips is about 100 MB.

## Legibility and palette

The scene ignores `ink` — it is physically coloured — and uses `backdrop` as
what the lens mixes it over. The theme keeps text readable with `opacity` 0.72
for surfaces, a `drop_shadow`, and the scene's brightness ceiling (`Lens.level`
0.5): whatever the shot and the look, no background pixel is brighter than half
white, which a test asserts over the brightest shots and looks. That replaced an
earlier `opacity` 0.85 / `exposure` 0.85 trim, which still let the glint and the
night-vision gain through.

## Built in, not an extension

An extension cannot contribute a shader with textures today without either
passing PuiKit types through the public API (which the `user_api` firewall
forbids) or a new `@preview` contribution point for scenes plus assets. Shipping
it in the core needed neither; the cost is ~3.6 MB of package data.

## Open items

- Release the PuiKit side, then raise the floor in `requirements.txt`. The
  floor is soft: on PuiKit 1.17.0 and older `background_earth.AVAILABLE` is
  false, the `earth` scene is not registered, and the Earth theme shows its
  plain navy.

- Hand check in the desktop app on macOS and Windows: theme switch latency
  (textures decode off-thread), live resize, idle freeze, each lens.
- Windows GPU cost on a typical iGPU.
- Web backend: textures and the lens chain in the WebGL client, then a GLSL
  dialect.
