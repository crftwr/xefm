# Background lens — system

The picture themes (Earth, Blocks, Crystal) render linear HDR and are filmed
through a camera look: bloom, a streak, flare ghosts, distortion, a colour
grade, film grain, CRT and scope masks, depth of field, a brightness ceiling.
That look is XeFM's (`xefm/background_lens.py`). PuiKit runs it but does not
know what it is: to PuiKit it is a list of passes through offscreen targets.

| Where | What |
|---|---|
| `xefm/background_lens.py` | `Look` (one look's parameters), `lens_shader()` (a scene plus the lens, as `Shader` fields), the pass shaders in MSL and HLSL, `xefm_slot_hash` |
| `xefm/background_earth.py`, `_blocks.py`, `_crystal.py` | The scenes; each calls `lens_shader()` with its looks |
| PuiKit `puikit/background.py` | `Target`, `Pass`, `ShaderTexture.name`, `Shader.targets` / `passes` |
| PuiKit `backends/_bg_graph.py` | Checks a graph, resolves names to slots, lays out bakes, packs `PassUniforms` |
| PuiKit `backends/_metal.py`, `_d3d_shader.py` | Allocate targets, bind inputs, draw each pass |

## The boundary

The first version of these themes put the lens in PuiKit: a `Lens` descriptor
with two dozen fields, a `LensCycle` evaluated on the CPU each frame, and a
`ShaderVolume` with a bake entry point of its own. That made PuiKit the owner
of one application's look. Each new idea for a background (a new lens effect, a
second bake, a feedback blur, a different tone map) would have been a PuiKit
change and a PuiKit release.

The boundary now sits at the GPU primitives Metal and Direct3D 11 share:

- **What PuiKit owns:** offscreen render targets (2D or 3D, half-float or
  8-bit, sized from the drawable or absolutely), fullscreen draws of a named
  fragment function, sampled inputs bound in order, bakes run once and kept,
  textures decoded off the UI thread, the frame-rate cap, Windows frame reuse,
  the seed uniforms. Their platform differences are its job too: Metal's
  `depthPlane` against a D3D11 `Texture3D` slice view, the pixel formats, how
  registers are bound, D3D11's refusal to write a texture still bound for
  reading.
- **What XeFM owns:** what each pass computes, how many there are, the look
  data, and how the look changes over time.

The test of the boundary is a new background. If it needs offscreen targets
and passes, it needs no PuiKit change. Earth, Blocks and Crystal were moved onto
it without changing a pixel: re-rendering 29 reference frames across every
look, the look cycle, a reseed blend, the bake and depth of field, the worst
pixel differs by 1 of 255 (float32 against the Python doubles that blended
looks before).

## The chain

`lens_shader(source, source_hlsl, looks, period, transition, scene_inputs,
scene_targets, scene_once)` returns `source`, `source_hlsl`, `targets` and
`passes`:

```
[once passes]  ─▶  bake targets            (Crystal: the rock volume)
puikit_bg_fragment  ─▶  scene              (RGBA16F, the drawable's size)
lens_down × 6       ─▶  down0 … down5      (halving; soft threshold on down0)
lens_up × 5         ─▶  up4 … up0          (tent upsample onto down i)
lens_streak × 4     ─▶  streak0/1          (only if a look has a streak)
lens_composite      ─▶  the screen         (scene, up0, streak or down1)
```

The scene's source comes first, after the slot hash and the look table, and
the lens passes after it. Their names are all prefixed `lens_` / `LENS_` so
that a scene's own names cannot clash with them. In HLSL the lens declares
`lens_t0..2` on `t0..t2`, which overlap the scene's own textures. fxc binds
registers per entry point, so the overlap is harmless (checked in the Windows
VM, a `Texture3D` and a `Texture2D` on the same register included). When no
look has a streak, the composite still samples slot 2, at zero weight, so it is
given `down1`, which has always been written by then: an unwritten half-float
target can hold NaN, and multiplying NaN by zero is still NaN.

## Looks in the shader, not the CPU

`LensCycle` used to run on the CPU every frame: pick the look for this period,
blend it into the next one, blend from the old seed's look to the new one's,
then upload the result as uniforms. Now the looks are a constant table in the
source (`LENS_LOOKS`, `LOOK_ROWS` float4s a look), and `lens_look()` does the
same steps from `time`, `seed`, `seed_prev` and `seed_mix`. It runs per pixel
in the composite and the first downsample, which costs a few hashes and a dozen
`mix` calls. What it buys:

- PuiKit needs no per-frame callback into the app. A backend advances a
  background on its own, and every frame stays a pure function of the
  uniforms.
- Earth's camera and its look are chosen from the same hash in the same
  language: the low part of `xefm_slot_hash(slot, seed)` modulo the look count
  is the look, and the rest picks the shot. They cannot drift apart.

`look_at()` is the same selection in Python, for tests. The GPU test compares
a cycle's frames with single-look frames of the look `look_at` names.

## Depth of field and the brightness ceiling

Both are look fields. Depth of field reads inverse depth from the scene's
alpha and focuses on the middle of the frame
([BLOCKS_CRYSTAL_IMPLEMENTATION.md](BLOCKS_CRYSTAL_IMPLEMENTATION.md#the-bake-depth-of-field-and-what-puikit-gained)
has the reasoning). `level` multiplies the final display colour before the mix
over the backdrop: at 0.5, no pixel is brighter than half white.

## Open items

- The web backend runs no passes, so the picture themes show their backdrop
  there. That needs passes in the WebGL client and a GLSL lens.
