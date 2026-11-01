"""The Crystal background scene: a macro study of a xenolith — craggy black basalt
with a cluster of small cyan crystals grown out of it.

XeFM takes its name from *xenolith*, a fragment of foreign rock caught in magma,
and this is the brand's signature scene. The camera drifts a few centimetres off
the rock, never showing the whole object: twelve hexagonal crystals lean out of
the basalt, glass and rock blended where they meet, a mossy chlorite coat
creeping up from each base, glassy grains in the rock and green inclusions in
the glass. The lighting is a studio's: a warm key softbox that slowly swings, a
cyan rim strip, a dark reflective floor. The glass refracts (IOR 1.55), absorbs
toward cyan with path length, clouds slightly, disperses on the way out, and
casts cyan-tinted shadows.

**A baked volume makes it affordable.** The full-detail rock (ridged crests,
cellular cracks, vesicle pits) and the crystal distances are baked into a
176 x 64 x 144 half-float 3D texture when the background is set (PuiKit's
``ShaderVolume``; the bake is ``puikit_bg_bake`` in this source), together with
the crystal interior's inclusion and milkiness fields. Marching then costs one
texel fetch per step instead of several noise octaves; normals are still taken
from the exact field, so no voxel ever shows.

**Stateless.** Camera, target and key light are closed forms of time (slow,
incommensurate sines — the orbit never visibly repeats); the crystal layout is
a set of constant arrays computed here, in Python, from the prototype's own
formulas. The prototype's autofocus read the centre ray back to the CPU every
frame and smoothed it; here the lens pulls focus to the depth at the middle of
the frame instead (PuiKit's ``Lens.dof``), which needs no state.

**Colour.** The rim light, the glass's absorption, its internal glow and
milkiness and the tint of its shadows all follow the theme's ``ink``; with the
brand cyan (88, 199, 222) they are exactly the prototype's. The basalt, the
chlorite and the studio are fixed.

MSL is the source of truth; the HLSL is a mechanical port of it, the volume
reached through the ``VOL_*`` macros so the same functions serve both.
"""

from __future__ import annotations

import math
from dataclasses import replace

try:
    from puikit.background import Lens, ShaderVolume
    AVAILABLE = True
except ImportError:
    # PuiKit 1.17.0 and older have no volumes or lens; see background_earth.
    AVAILABLE = False

#: Options a theme's ``animation`` dict may carry for this scene.
OPTIONS = ("exposure", "brightness", "focus")

DEFAULT_BRIGHTNESS = 0.5

#: Fraction of native resolution: the depth of field blurs most of the frame
#: anyway, and the scene is the dearest XeFM draws (about 14 ms a frame for a
#: 1440 x 900 render on an M5; see doc/dev/BLOCKS_CRYSTAL_IMPLEMENTATION.md).
RESOLUTION_SCALE = 0.45

#: It is the dearest scene XeFM draws, and its camera drifts slowly enough that
#: 30 frames a second look the same as 60 (PuiKit's ``Shader.frame_rate``).
FRAME_RATE = 30.0

#: The baked volume's size in texels, over the box RB_MIN .. RB_MIN + RB_SIZE.
VOLUME_SIZE = (176, 64, 144)


def _fract(x: float) -> float:
    return x - math.floor(x)


def _js_hash33(v):
    """The prototype's JavaScript hash33 — not the same function as its GLSL one."""
    x, y, z = _fract(v[0] * 0.1031), _fract(v[1] * 0.1030), _fract(v[2] * 0.0973)
    d = x * (y + 33.33) + y * (x + 33.33) + z * (z + 33.33)
    x, y, z = x + d, y + d, z + d
    return (_fract((x + y) * z), _fract((x + x) * y), _fract((y + x) * x))


def crystal_layout():
    """The twelve crystals: (base point + bounding radius, world-to-local rows,
    (prism radius, prism height, termination height)) — the prototype's
    ``crystalLayout()``: a golden-angle spiral over the rock top, each crystal
    leaning outward and spun."""
    def rot2(ang, a, b):
        c, s = math.cos(ang), math.sin(ang)
        return c * a + s * b, -s * a + c * b

    out = []
    for i in range(12):
        h = _js_hash33((i * 3.1, i * 7.7, 1.3))
        a = i * 2.39996 + h[0] * 0.6
        f = 0.12 + 0.62 * math.sqrt((i + 0.5) / 12)
        sc = (0.45 + 0.55 * h[1]) * (1 - 0.45 * f)
        r, hh, tip = 0.055 * sc, 0.17 * sc, 0.07 * sc
        lean = -(0.25 + 0.6 * f + (h[2] - 0.5) * 0.4)
        spin = h[0] * 6.2831
        pos = (0.9 * f * math.cos(a), 0.2 + 0.36 * math.sqrt(max(1 - f * f, 0)) - 0.03,
               0.7 * f * math.sin(a), hh + tip + r + 0.06)

        def T(v):
            x, y, z = v
            x, z = rot2(a, x, z)
            x, y = rot2(lean, x, y)
            x, z = rot2(spin, x, z)
            return (x, y, z)

        cols = [T((1, 0, 0)), T((0, 1, 0)), T((0, 0, 1))]
        rows = [tuple(cols[c][r_] for c in range(3)) for r_ in range(3)]
        out.append((pos, rows, (r, hh, tip)))
    return out


def _vec(values) -> str:
    return ", ".join(f"{v:.6f}" for v in values)


def _layout_constants(dialect: str) -> str:
    kw = "constant" if dialect == "msl" else "static const"
    layout = crystal_layout()
    pos = ",\n    ".join(f"float4({_vec(p)})" for p, _, _ in layout)
    rows = [",\n    ".join(f"float3({_vec(rws[k])})" for _, rws, _ in layout) for k in range(3)]
    size = ",\n    ".join(f"float3({_vec(s)})" for _, _, s in layout)
    return (f"{kw} float4 CRY_POS[12] = {{\n    {pos}}};\n"
            f"{kw} float3 CRY_R0[12] = {{\n    {rows[0]}}};\n"
            f"{kw} float3 CRY_R1[12] = {{\n    {rows[1]}}};\n"
            f"{kw} float3 CRY_R2[12] = {{\n    {rows[2]}}};\n"
            f"{kw} float3 CRY_SIZE[12] = {{\n    {size}}};\n")


_MSL_OPTIONS = """
// --- per-theme options (baked by xefm.background_crystal.crystal_shader) -----
constant float EXPOSURE = {exposure};
#define VOL_PARAMS texture3d<float> vol, sampler vsmp
#define VOL_ARGS vol, vsmp
#define VOL_SAMPLE(uvw) vol.sample(vsmp, (uvw), level(0))
"""

_HLSL_OPTIONS = """
// --- per-theme options (baked by xefm.background_crystal.crystal_shader) -----
static const float EXPOSURE = {exposure};
Texture3D vol : register(t0);
SamplerState vsmp : register(s0);
#define VOL_PARAMS float vol_unused
#define VOL_ARGS 0.0
#define VOL_SAMPLE(uvw) vol.SampleLevel(vsmp, (uvw), 0)
"""

CRYSTAL_MSL_BODY = """
// --- tunables ---------------------------------------------------------------
constant float PI       = 3.14159265;
constant float3 KEY_COL = float3(2.4, 2.28, 2.112);           // (1, 0.95, 0.88) * 2.4
constant float3 RIM_DIR = float3(0.809846, 0.314940, -0.494906);
constant float3 BOUND_C = float3(0.0, 0.82, 0.0);
constant float BOUND_R  = 1.25;
constant float3 RB_MIN  = float3(-1.15, -0.05, -0.95);       // the baked volume's box
constant float3 RB_SIZE = float3(2.3, 0.85, 1.9);
constant float IOR      = 1.55;
constant int   MARCH_STEPS = 240;
constant float START    = 24.0;                             // the prototype's opening second
// The tint the colours below were tuned for, and how each follows it: with the
// brand cyan they reproduce the prototype exactly.
constant float3 INK_REF = float3(0.345098, 0.780392, 0.870588);
constant float3 ABSORB_K  = float3(6.580, 6.450, 7.912);     // per unit -ln(tint)
constant float3 SCATTER_K = float3(0.2318, 0.4357, 0.4595);
constant float3 SHADOW_K  = float3(0.9273, 1.1533, 1.1486);
constant float3 MILK_K    = float3(1.5938, 0.9995, 0.9649);

// Termination face normals: every crystal shares the same tip-to-radius ratio.
constant float3 PYR[6] = {
    float3(0.78633, 0.61782, 0.0), float3(0.39316, 0.61782, 0.68098),
    float3(-0.39316, 0.61782, 0.68098), float3(-0.78633, 0.61782, 0.0),
    float3(-0.39316, 0.61782, -0.68098), float3(0.39316, 0.61782, -0.68098)};

// @LAYOUT@

// What shading needs that is not geometry: the key light (it swings with time)
// and the colours that follow the theme's ink.
struct Look {
    float3 key; float3 rim; float3 absorb; float3 scatter; float3 shadow; float3 milk;
    float3 cam; float px; float time; float2 frag;
};

static inline float hash13(float3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return fract((p.x + p.y) * p.z);
}

static inline float3 hash33(float3 p) {
    p = fract(p * float3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return fract((p.xxy + p.yxx) * p.zyx);
}

static inline float vnoise(float3 p) {
    float3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash13(i), hash13(i + float3(1, 0, 0)), f.x),
                   mix(hash13(i + float3(0, 1, 0)), hash13(i + float3(1, 1, 0)), f.x), f.y),
               mix(mix(hash13(i + float3(0, 0, 1)), hash13(i + float3(1, 0, 1)), f.x),
                   mix(hash13(i + float3(0, 1, 1)), hash13(i + float3(1, 1, 1)), f.x), f.y), f.z);
}

static inline float fbmN(float3 p, int oct) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 5; i++) {
        if (i >= oct) break;
        s += a * vnoise(p);
        p = p * 2.03 + float3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return s;
}

// Cellular noise: x = distance to the nearest cell point, y = the gap to the
// second (0 on a grain boundary), z = the cell's id.
static inline float3 voronoi(float3 x) {
    float3 i = floor(x), f = fract(x);
    float d1 = 8.0, d2 = 8.0, id = 0.0;
    for (int k = -1; k <= 1; k++) {
        for (int j = -1; j <= 1; j++) {
            for (int m = -1; m <= 1; m++) {
                float3 g = float3(float(m), float(j), float(k));
                float3 r = g + hash33(i + g) - f;
                float d = dot(r, r);
                if (d < d1) { d2 = d1; d1 = d; id = hash13(i + g + 7.0); }
                else if (d < d2) { d2 = d; }
            }
        }
    }
    return float3(sqrt(d1), sqrt(d2) - sqrt(d1), id);
}

static inline float smin(float a, float b, float k) {
    float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
    return mix(b, a, h) - k * h * (1.0 - h);
}

static inline float sdEllipsoid(float3 p, float3 r) {
    float k0 = length(p / r);
    float k1 = length(p / (r * r));
    return k0 * (k0 - 1.0) / k1;
}

// --- the crystals: hexagonal prisms with six-faced terminations --------------

static inline float sdCrystal(float3 p, float3 sz) {
    float d = max(-p.y - 0.35, abs(p.x) - sz.x);
    d = max(d, abs(0.5 * p.x + 0.8660254 * p.z) - sz.x);
    d = max(d, abs(-0.5 * p.x + 0.8660254 * p.z) - sz.x);
    float3 q = p - float3(0.0, sz.y + sz.z, 0.0);
    for (int i = 0; i < 6; i++) d = max(d, dot(q, PYR[i]));
    return d;
}

static inline float crystals(float3 p) {
    // The cluster sits in a shell over the rock top; well clear of it, skip the loop.
    float shell = sdEllipsoid(p - float3(0.0, 0.2, 0.0), float3(1.15, 0.62, 0.95));
    if (shell > 0.05) return shell * 0.8;
    float d = 1e3;
    for (int i = 0; i < 12; i++) {
        float4 b = CRY_POS[i];
        float3 rel = p - b.xyz;
        float bd = length(rel) - b.w;
        if (bd > 0.05) { d = min(d, bd); continue; }
        float3 lp = float3(dot(CRY_R0[i], rel), dot(CRY_R1[i], rel), dot(CRY_R2[i], rel));
        d = min(d, sdCrystal(lp, CRY_SIZE[i]));
    }
    return d;
}

// --- the basalt ----------------------------------------------------------------

static inline float ridged(float3 p, int oct) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 4; i++) {
        if (i >= oct) break;
        float n = 1.0 - abs(2.0 * vnoise(p) - 1.0);
        s += a * n * n;
        p = p * 2.07 + float3(3.1, 1.7, 5.3);
        a *= 0.5;
    }
    return s;
}

// Crests and gullies, cracks between angular blocks, blocks at slightly
// different heights (zero at the cracks, so no step), fine grain, vesicle pits.
static inline float rockRelief(float3 p) {
    float off = -(ridged(p * 8.0, 3) - 0.45) * 0.07;
    float3 v = voronoi(p * 14.0);
    off += (1.0 - smoothstep(0.0, 0.12, v.y)) * 0.013;
    off -= (v.z - 0.5) * 0.012 * smoothstep(0.0, 0.15, v.y);
    off -= (ridged(p * 40.0, 2) - 0.45) * 0.014;
    off += smoothstep(0.6, 0.9, vnoise(p * 26.0)) * 0.02;
    return off;
}

static inline float rockBase(float3 p, int oct) {
    float d = sdEllipsoid(p - float3(0.0, 0.20, 0.0), float3(0.9, 0.36, 0.7));
    if (d < 0.3) {
        d += (fbmN(p * 2.6, oct) - 0.5) * 0.22;
        // Faded in rather than switched on, so the field has no seam to trip on.
        if (oct >= 5 && d < 0.14) d += rockRelief(p) * (1.0 - smoothstep(0.06, 0.14, d));
    }
    return max(d, -p.y);
}

// --- the baked volume -----------------------------------------------------------

static inline float rockTex(float3 p, VOL_PARAMS) {
    float coarse = sdEllipsoid(p - float3(0.0, 0.20, 0.0), float3(0.9, 0.36, 0.7));
    if (coarse > 0.2) return (coarse - 0.17) * 0.9;
    return VOL_SAMPLE(clamp((p - RB_MIN) / RB_SIZE, 0.0, 1.0)).r * 0.42;
}

// The crystal distance is baked too, as an accelerator: while it says the nearest
// crystal is more than a few millimetres away, step by it; close in, switch to
// the exact faceted distance so the facets stay sharp.
static inline float cryField(float3 p, int oct, VOL_PARAMS) {
    if (oct < 6) {
        float3 uvw = (p - RB_MIN) / RB_SIZE;
        if (all(uvw > 0.0) && all(uvw < 1.0)) {
            float v = VOL_SAMPLE(uvw).g;
            if (v > 0.04) return v - 0.02;
        }
    }
    return crystals(p);
}

// Rock distance, scaled to a safe step. oct 6 evaluates the full noise: normals
// come from the true surface, never from the voxel grid.
static inline float rockField(float3 p, int oct, VOL_PARAMS) {
    if (oct < 6) return rockTex(p, VOL_ARGS);
    return rockBase(p, 5) * 0.42;
}

static inline float scene_map(float3 p, int oct, VOL_PARAMS) {
    return smin(rockField(p, oct, VOL_ARGS), cryField(p, oct, VOL_ARGS), 0.03);
}

static inline float3 calcNormal(float3 p, VOL_PARAMS) {
    const float2 e = float2(1.0, -1.0) * 0.0008;
    return normalize(e.xyy * scene_map(p + e.xyy, 6, VOL_ARGS) + e.yyx * scene_map(p + e.yyx, 6, VOL_ARGS)
                   + e.yxy * scene_map(p + e.yxy, 6, VOL_ARGS) + e.xxx * scene_map(p + e.xxx, 6, VOL_ARGS));
}

// A cheaper normal for secondary hits, seen in the floor or through glass.
static inline float3 calcNormalFast(float3 p, VOL_PARAMS) {
    const float2 e = float2(1.0, -1.0) * 0.004;
    return normalize(e.xyy * scene_map(p + e.xyy, 4, VOL_ARGS) + e.yyx * scene_map(p + e.yyx, 4, VOL_ARGS)
                   + e.yxy * scene_map(p + e.yxy, 4, VOL_ARGS) + e.xxx * scene_map(p + e.xxx, 4, VOL_ARGS));
}

static inline float3 cryNormal(float3 p) {
    const float2 e = float2(1.0, -1.0) * 0.0008;
    return normalize(e.xyy * crystals(p + e.xyy) + e.yyx * crystals(p + e.yyx)
                   + e.yxy * crystals(p + e.yxy) + e.xxx * crystals(p + e.xxx));
}

static inline float2 boundHit(float3 ro, float3 rd) {
    float3 oc = ro - BOUND_C;
    float b = dot(oc, rd);
    float c = dot(oc, oc) - BOUND_R * BOUND_R;
    float h = b * b - c;
    if (h < 0.0) return float2(-1.0, -1.0);
    float s = sqrt(h);
    return float2(max(-b - s, 0.0), -b + s);
}

static inline float march(float3 ro, float3 rd, int steps, int oct, VOL_PARAMS) {
    float2 bh = boundHit(ro, rd);
    if (bh.y < 0.0) return -1.0;
    float t = bh.x;
    for (int i = 0; i < MARCH_STEPS; i++) {
        if (i >= steps) break;
        float h = scene_map(ro + rd * t, oct, VOL_ARGS);
        if (h < 0.00025 + 0.0003 * t) return t;
        t += h * 0.9;
        if (t > bh.y) break;
    }
    return -1.0;
}

// --- the studio: key softbox (it swings), cyan rim strip, overhead fill -------

static inline float softbox(float3 d, float3 axis, float2 size, float soft) {
    float c = dot(d, axis);
    if (c <= 0.0) return 0.0;
    float3 t = normalize(cross(axis, float3(0.0, 1.0, 0.0)));
    float3 b = cross(t, axis);
    float2 uv = abs(float2(dot(d, t), dot(d, b)) / c);
    float2 m = 1.0 - smoothstep(size - soft, size + soft, uv);
    return m.x * m.y;
}

static inline float3 env(float3 d, float rough, Look L) {
    float s = 0.01 + rough * 0.6;
    float spread = 1.0 / (1.0 + rough * 2.5);
    float3 c = mix(float3(0.004, 0.005, 0.006), float3(0.028, 0.033, 0.037), smoothstep(-0.1, 0.9, d.y));
    if (d.y < -0.02) c = float3(0.006, 0.007, 0.008);
    c += KEY_COL * 2.4 * spread * softbox(d, L.key, float2(0.32, 0.22), s);
    c += L.rim * 3.0 * spread * softbox(d, RIM_DIR, float2(0.05, 0.6), s);
    c += float3(0.45, 0.5, 0.55) * 0.12 * spread
       * softbox(d, normalize(float3(0.02, 1.0, -0.2)), float2(0.35, 0.35), s);
    return c;
}

// --- materials -----------------------------------------------------------------

static inline float3 basaltRough(float3 q) {
    float g = fbmN(q * 7.0, 3);
    float3 a = float3(0.026, 0.028, 0.03) * (0.7 + 0.6 * g);
    a *= 1.0 - 0.6 * smoothstep(0.76, 0.82, vnoise(q * 34.0));                          // vesicles
    a = mix(a, float3(0.22, 0.23, 0.23), smoothstep(0.92, 0.96, vnoise(q * 90.0)) * 0.4); // phenocrysts
    a = mix(a, a * float3(1.35, 1.05, 0.8), smoothstep(0.5, 0.8, vnoise(q * 3.0)) * 0.5); // weathering
    return a;
}

// x = how glassy (1 crystal, 0 basalt), y = how much of the glass is coated.
static inline float2 glassMix(float3 q, VOL_PARAMS) {
    float r = rockTex(q, VOL_ARGS) / 0.42 * 0.75, c = crystals(q);
    float m = smoothstep(-0.06, 0.06, r - c);
    float grains = smoothstep(0.78, 0.86, vnoise(q * 13.0)) * smoothstep(0.25, 0.0, c);
    m = max(m, grains);
    float coat = smoothstep(0.35, 0.8, fbmN(q * 16.0, 3) + (0.05 - max(r, 0.0)) * 7.0);
    return float2(clamp(m, 0.0, 1.0), coat);
}

static inline float3 chlorite(float3 q) {
    return mix(float3(0.018, 0.034, 0.02), float3(0.05, 0.075, 0.035), fbmN(q * 30.0, 3))
         * (0.7 + 0.6 * vnoise(q * 120.0));
}

// Light toward the key: soft shadows, tinted (not blocked) where it passes
// through a crystal. The start is jittered per pixel to break up banding.
static inline float3 lightTransmit(float3 ro, float3 rd, Look L, VOL_PARAMS) {
    if (boundHit(ro, rd).y < 0.0) return float3(1.0);
    float sr = 1.0, sc = 1.0;
    float t = 0.03 + 0.03 * hash13(float3(L.frag, L.time));
    for (int i = 0; i < 40; i++) {
        float3 p = ro + rd * t;
        float hr = rockTex(p, VOL_ARGS);
        float hc = cryField(p, 4, VOL_ARGS);
        sr = min(sr, 9.0 * hr / t);
        sc = min(sc, 9.0 * hc / t);
        t += clamp(min(hr, hc), 0.015, 0.2);
        if (sr < 0.002 || t > 4.0) break;
    }
    sr = clamp(sr, 0.0, 1.0);
    sc = clamp(sc, 0.0, 1.0);
    return float3(sr) * mix(L.shadow, float3(1.0), sc);
}

static inline float calcAO(float3 p, float3 n, VOL_PARAMS) {
    float o = 0.0, s = 1.0;
    for (int i = 0; i < 5; i++) {
        float h = 0.01 + 0.06 * float(i);
        // The first taps see the baked full detail, the surface's own, or AO
        // reads as stripes; the outer ones only need the shape.
        float d = scene_map(p + n * h, i < 2 ? 5 : 2, VOL_ARGS);
        o += (h - d) * s;
        s *= 0.7;
    }
    return clamp(1.0 - 2.2 * o, 0.0, 1.0);
}

// Surface shading. The shadow toward the key (tr) and the occlusion (ao) are
// computed once per pixel, at whatever the primary ray hit, and handed in: they
// are the dear loops, and the rock, the coat and the floor all share them.
static inline float3 shadeSurf(float3 p, float3 n, float3 rd, float3 alb, float rough, float F0,
                               float3 tr, float ao, Look L) {
    float dif = max(dot(n, L.key), 0.0);
    float rim = max(dot(n, RIM_DIR), 0.0);
    float nv = max(dot(n, -rd), 0.0);
    float fr = F0 + (max(1.0 - rough, F0) - F0) * pow(1.0 - nv, 5.0);
    float3 col = alb * (KEY_COL * dif * tr + L.rim * rim * 0.45 + env(n, 1.0, L) * 0.25 * ao);
    float3 h = normalize(L.key - rd);
    float nh = max(dot(n, h), 0.0);
    float a = max(rough * rough, 0.002), a2 = a * a;
    float dd = nh * nh * (a2 - 1.0) + 1.0;
    col += KEY_COL * tr * (a2 / (PI * dd * dd)) * fr * dif * 0.25 * smoothstep(0.1, 0.3, rough);
    col += env(reflect(rd, n), rough, L) * fr * ao * mix(float3(1.0), tr, 0.5) * mix(1.0, 0.2, rough);
    return col;
}

static inline float3 glassGrain(float3 n, float3 rd, Look L) {
    float F = 0.05 + 0.95 * pow(1.0 - max(dot(n, -rd), 0.0), 5.0);
    float lit = 0.3 + 0.7 * max(dot(n, L.key), 0.0);
    float3 body = float3(0.02, 0.09, 0.11) * lit + L.scatter * 0.6 * 0.22 * lit;
    return mix(body, env(reflect(rd, n), 0.03, L), F);
}

// Secondary hits (the floor's reflection, the view through a crystal): no
// shadows, no occlusion, no recursion.
static inline float3 surfaceSimple(float3 p, float3 n, float3 rd, Look L, VOL_PARAMS) {
    float2 g = glassMix(p, VOL_ARGS);
    float3 glass = mix(glassGrain(n, rd, L),
                       shadeSurf(p, n, rd, chlorite(p), 0.4, 0.04, float3(1.0), 1.0, L), g.y);
    return mix(shadeSurf(p, n, rd, basaltRough(p), 0.62, 0.04, float3(1.0), 1.0, L), glass, g.x);
}

// The floor's own light, without its reflection (which is fetched with the
// other secondary rays, see the fragment).
static inline float3 floorBase(float3 P, float3 tr, float ao, Look L) {
    float3 alb = float3(0.022, 0.025, 0.028) * (0.85 + 0.3 * vnoise(P * 60.0));
    return alb * (KEY_COL * L.key.y * tr + env(float3(0.0, 1.0, 0.0), 1.0, L) * 0.8 * ao);
}

// A crystal's light, split in two: what the glass gives itself (reflection,
// inclusions, glow, milkiness) and how much of whatever lies behind it reaches
// the eye, with the ray that goes to fetch it. The fetch is done by the caller,
// once per pixel, together with the floor's reflection.
struct Glass {
    float3 col; float3 w;          // own light; the weight of what lies behind
    float3 o; float3 d;            // the ray out of the crystal
    float3 rdi; float3 ne;         // for dispersion where it leaves into the studio
    float fetch;                   // 1 when there is something behind to fetch
};

static inline Glass shadeCrystal(float3 p, float3 n, float3 rd, Look L, VOL_PARAMS) {
    float nv = max(dot(n, -rd), 0.0);
    float F = 0.05 + 0.95 * pow(1.0 - nv, 5.0);
    float3 refl = env(reflect(rd, n), 0.015, L);
    float3 rdi = refract(rd, n, 1.0 / IOR);
    float t = 0.004, milk = 0.0;
    float3 q = p;
    // Green chlorite inclusions suspended in the glass, front to back.
    float3 incCol = float3(0.0);
    float incA = 0.0;
    float lit0 = 0.35 + 0.65 * max(dot(n, L.key), 0.0);
    for (int i = 0; i < 36; i++) {
        q = p + rdi * t;
        float d = -crystals(q);
        float dt = clamp(d, 0.003, 0.012);
        float2 ci = VOL_SAMPLE(clamp((q - RB_MIN) / RB_SIZE, 0.0, 1.0)).ba;
        float dens = smoothstep(0.6, 0.74, ci.x);
        if (dens > 0.0) {
            float3 c = mix(float3(0.05, 0.10, 0.05), float3(0.12, 0.16, 0.08), ci.y) * KEY_COL * lit0;
            float a = 1.0 - exp(-dens * dt * 80.0);
            float3 absorbed = exp(-t * L.absorb);
            incCol += (1.0 - incA) * a * c * absorbed;
            incA += (1.0 - incA) * a;
        }
        milk += dt * 4.0 * (0.4 + 0.6 * ci.y);
        if (d < 0.0015 || incA > 0.97) break;
        t += dt;
    }
    Glass g;
    g.fetch = 0.0;
    g.o = q;
    g.d = float3(0.0, 1.0, 0.0);
    g.rdi = rdi;
    g.ne = n;
    float3 behind = float3(0.0);
    if (incA <= 0.97) {
        float3 ne = cryNormal(q);
        float3 dG = refract(rdi, -ne, IOR);
        if (dot(dG, dG) < 1e-4) {
            behind = env(reflect(rdi, -ne), 0.04, L) * 0.9;           // total internal reflection
        } else {
            g.fetch = 1.0;
            g.o = q + dG * 0.01;
            g.d = dG;
            g.ne = ne;
        }
    }
    float3 trans = (1.0 - incA) * exp(-t * L.absorb);
    float lit = 0.25 + 0.75 * max(dot(n, L.key), 0.0);
    float3 own = incCol + trans * behind + L.scatter * 0.32 * lit * (1.0 - exp(-t * 6.5));
    float3 milkCol = L.milk * (0.10 + 0.45 * lit);
    float mk = 1.0 - exp(-milk);
    g.col = mix(mix(own, milkCol, mk), refl, F);
    g.w = trans * (1.0 - mk) * (1.0 - F);
    return g;
}

// Fine grit as a normal map, each scale fading out once its grains are smaller
// than about a pixel at this distance, so it never shimmers. w = the height.
static inline float grit(float3 q, float f1, float f2) {
    return 0.55 * f1 * vnoise(q * 160.0) + 0.3 * f2 * vnoise(q * 420.0)
         + 0.15 * f1 * (1.0 - abs(2.0 * vnoise(q * 90.0) - 1.0));
}

static inline float4 gritNormal(float3 p, float3 n, Look L) {
    float px = length(p - L.cam) * L.px;                      // world size of one pixel here
    float f1 = 1.0 - smoothstep(0.25, 0.6, px * 160.0);
    float f2 = 1.0 - smoothstep(0.25, 0.6, px * 420.0);
    float h = grit(p, f1, f2);
    if (f1 <= 0.0) return float4(n, h);
    const float e = 0.0006;
    const float2 k = float2(1.0, -1.0) * e;
    float3 g = (k.xyy * grit(p + k.xyy, f1, f2) + k.yyx * grit(p + k.yyx, f1, f2)
              + k.yxy * grit(p + k.yxy, f1, f2) + k.xxx * grit(p + k.xxx, f1, f2)) / (4.0 * e * e);
    return float4(normalize(n - 0.0036 * (g - n * dot(g, n))), h);
}

static inline float3 shadeBasalt(float3 p, float3 n, float3 rd, float3 tr, float ao, Look L) {
    float4 gn = gritNormal(p, n, L);
    float3 alb = basaltRough(p) * (0.6 + 0.8 * gn.w);
    return shadeSurf(p, gn.xyz, rd, alb, 0.58, 0.04, tr, ao, L);
}

// The volume: x rock distance, y crystal distance (both clamped to +-0.4),
// z the inclusion field, w the milkiness noise.
fragment float4 puikit_bg_bake(float4 pos [[position]], constant BakeUniforms &b [[buffer(0)]]) {
    float3 uvw = float3(pos.xy / b.size.xy, (b.size.w + 0.5) / b.size.z);
    float3 bp = RB_MIN + uvw * RB_SIZE;
    float2 d = clamp(float2(rockBase(bp, 5), crystals(bp)), -0.4, 0.4);
    return float4(d, clamp(fbmN(bp * 20.0 + 2.0, 3) + 0.04, 0.0, 1.0), vnoise(bp * 40.0));
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]],
                                   texture3d<float> vol [[texture(0)]],
                                   sampler vsmp [[sampler(0)]]) {
    float s = u.time + START;
    // The camera hovers low over the rock top and aims just above it, so a few
    // crystals stand in frame against the rock rather than filling it.
    float th = 0.9 + s * 0.045, R = 1.0 + 0.12 * sin(s * 0.07);
    float3 ro = float3(R * cos(th), 0.55 + 0.16 * sin(s * 0.043), R * 0.8 * sin(th));
    float pt = th + 0.45 * sin(s * 0.05), f = 0.38 + 0.2 * sin(s * 0.041);
    float3 tgt = float3(0.9 * f * cos(pt), 0.2 + 0.36 * sqrt(1.0 - f * f) + 0.05, 0.7 * f * sin(pt));
    float focal = 2.2;
    float A = 2.25 + 0.55 * sin(s * 0.1);

    float3 tint = u.ink.rgb;
    Look L;
    L.key = normalize(float3(cos(A) * 0.85, 0.85, sin(A) * 0.85));
    L.rim = tint * 1.5;
    L.absorb = -log(max(tint, float3(0.02))) * ABSORB_K;
    L.scatter = tint * SCATTER_K;
    L.shadow = min(tint * SHADOW_K, float3(1.0));
    L.milk = tint * MILK_K;
    L.cam = ro;
    L.px = 1.0 / (focal * u.resolution.y);
    L.time = s;
    L.frag = pos.xy;

    float2 uv = float2(pos.x - 0.5 * u.resolution.x, 0.5 * u.resolution.y - pos.y) / u.resolution.y;
    float3 ww = normalize(tgt - ro), uu = normalize(cross(ww, float3(0.0, 1.0, 0.0))), vv = cross(uu, ww);
    float3 rd = normalize(uv.x * uu + uv.y * vv + focal * ww);

    float3 bg = float3(0.006, 0.007, 0.008) + float3(0.024, 0.029, 0.033) * smoothstep(-0.2, 0.6, rd.y);
    float3 col = bg;
    float depth = 30.0;
    // What the primary ray found: 1 the specimen, 2 the floor, 0 the studio.
    int kind = 0;
    float3 P = ro, N = float3(0.0, 1.0, 0.0);
    float hit = march(ro, rd, MARCH_STEPS, 5, VOL_ARGS);
    if (hit > 0.0) {
        // Settle onto the surface: an overshoot into steep relief would leave the
        // point inside the rock, where its own shadow reads as contour stripes.
        for (int k = 0; k < 6; k++) hit += scene_map(ro + rd * hit, 5, VOL_ARGS) * 0.6;
        P = ro + rd * hit;
        N = calcNormal(P, VOL_ARGS);
        kind = 1;
        depth = hit;
    } else if (rd.y < 0.0) {
        depth = -ro.y / rd.y;
        P = ro + rd * depth;
        kind = 2;
    }

    // Shadow and occlusion, once, at whatever was hit.
    float3 tr = float3(1.0);
    float ao = 1.0;
    if (kind != 0) {
        tr = lightTransmit(P + N * (kind == 1 ? 0.02 : 0.002), L.key, L, VOL_ARGS);
        if (kind == 1 || length(P.xz) < 1.8) ao = calcAO(P, N, VOL_ARGS);
    }

    // At most one secondary ray per pixel -- through a crystal, or the floor's
    // reflection -- fetched below, with its weight in the final colour.
    float3 sw = float3(0.0), so = P, sd = N, srdi = rd, sne = N;
    int smode = 0;
    if (kind == 1) {
        float2 g = glassMix(P, VOL_ARGS);
        float3 rockC = float3(0.0), clearC = float3(0.0), coatC = float3(0.0);
        if (g.x < 0.99) rockC = shadeBasalt(P, N, rd, tr, ao, L);
        if (g.x > 0.01) {
            if (g.y < 0.99) {
                if (crystals(P) < 0.03) {
                    Glass gl = shadeCrystal(P, N, rd, L, VOL_ARGS);
                    clearC = gl.col;
                    if (gl.fetch > 0.5) {
                        sw = gl.w * (1.0 - g.y) * g.x;
                        so = gl.o;
                        sd = gl.d;
                        srdi = gl.rdi;
                        sne = gl.ne;
                        smode = 1;
                    }
                } else {
                    clearC = glassGrain(N, rd, L);
                }
            }
            if (g.y > 0.01) coatC = shadeSurf(P, N, rd, chlorite(P), 0.4, 0.04, tr, ao, L);
        }
        col = mix(rockC, mix(clearC, coatC, g.y), g.x);
    } else if (kind == 2) {
        float fade = exp(-dot(P.xz, P.xz) * 0.10);
        float fr = 0.03 + 0.97 * pow(1.0 - max(dot(N, -rd), 0.0), 5.0);
        col = mix(bg, floorBase(P, tr, ao, L), fade);
        sw = float3(1.0) * (fade * fr * 0.85);
        so = P + N * 0.003;
        sd = reflect(rd, N);
        smode = 2;
    }
    if (smode != 0) {
        float h = march(so, sd, smode == 2 ? 70 : 40, smode == 2 ? 3 : 2, VOL_ARGS);
        float3 behind;
        if (h > 0.0) {
            float3 s2 = so + sd * h;
            behind = surfaceSimple(s2, calcNormalFast(s2, VOL_ARGS), sd, L, VOL_ARGS)
                   * (smode == 2 ? exp(-h * 1.8) : 1.0);
        } else if (smode == 2) {
            behind = env(sd, 0.35, L) * 0.4;
        } else if (sd.y < 0.0) {
            float3 q = so - sd * 0.01;
            behind = floorBase(q + sd * (-q.y / sd.y), float3(1.0), 1.0, L);
        } else {
            // Dispersion as the light leaves the glass into the studio.
            float3 dR = refract(srdi, -sne, 1.53), dB = refract(srdi, -sne, 1.575);
            behind = float3(env(dR, 0.02, L).r, env(sd, 0.02, L).g, env(dB, 0.02, L).b);
        }
        col += sw * behind;
    }
    // Linear HDR; inverse depth in alpha for the lens's depth of field.
    return float4(max(col * EXPOSURE, 0.0), 1.0 / depth);
}
"""

CRYSTAL_HLSL_BODY = """
// --- tunables ---------------------------------------------------------------
static const float PI       = 3.14159265;
static const float3 KEY_COL = float3(2.4, 2.28, 2.112);           // (1, 0.95, 0.88) * 2.4
static const float3 RIM_DIR = float3(0.809846, 0.314940, -0.494906);
static const float3 BOUND_C = float3(0.0, 0.82, 0.0);
static const float BOUND_R  = 1.25;
static const float3 RB_MIN  = float3(-1.15, -0.05, -0.95);       // the baked volume's box
static const float3 RB_SIZE = float3(2.3, 0.85, 1.9);
static const float IOR      = 1.55;
static const int   MARCH_STEPS = 240;
static const float START    = 24.0;                             // the prototype's opening second
// The tint the colours below were tuned for, and how each follows it: with the
// brand cyan they reproduce the prototype exactly.
static const float3 INK_REF = float3(0.345098, 0.780392, 0.870588);
static const float3 ABSORB_K  = float3(6.580, 6.450, 7.912);     // per unit -ln(tint)
static const float3 SCATTER_K = float3(0.2318, 0.4357, 0.4595);
static const float3 SHADOW_K  = float3(0.9273, 1.1533, 1.1486);
static const float3 MILK_K    = float3(1.5938, 0.9995, 0.9649);

// Termination face normals: every crystal shares the same tip-to-radius ratio.
static const float3 PYR[6] = {
    float3(0.78633, 0.61782, 0.0), float3(0.39316, 0.61782, 0.68098),
    float3(-0.39316, 0.61782, 0.68098), float3(-0.78633, 0.61782, 0.0),
    float3(-0.39316, 0.61782, -0.68098), float3(0.39316, 0.61782, -0.68098)};

// @LAYOUT@

// What shading needs that is not geometry: the key light (it swings with time)
// and the colours that follow the theme's ink.
struct Look {
    float3 key; float3 rim; float3 absorb; float3 scatter; float3 shadow; float3 milk;
    float3 cam; float px; float time; float2 frag;
};

float hash13(float3 p) {
    p = frac(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return frac((p.x + p.y) * p.z);
}

float3 hash33(float3 p) {
    p = frac(p * float3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return frac((p.xxy + p.yxx) * p.zyx);
}

float vnoise(float3 p) {
    float3 i = floor(p), f = frac(p);
    f = f * f * (3.0 - 2.0 * f);
    return lerp(lerp(lerp(hash13(i), hash13(i + float3(1, 0, 0)), f.x),
                   lerp(hash13(i + float3(0, 1, 0)), hash13(i + float3(1, 1, 0)), f.x), f.y),
               lerp(lerp(hash13(i + float3(0, 0, 1)), hash13(i + float3(1, 0, 1)), f.x),
                   lerp(hash13(i + float3(0, 1, 1)), hash13(i + float3(1, 1, 1)), f.x), f.y), f.z);
}

float fbmN(float3 p, int oct) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 5; i++) {
        if (i >= oct) break;
        s += a * vnoise(p);
        p = p * 2.03 + float3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return s;
}

// Cellular noise: x = distance to the nearest cell point, y = the gap to the
// second (0 on a grain boundary), z = the cell's id.
float3 voronoi(float3 x) {
    float3 i = floor(x), f = frac(x);
    float d1 = 8.0, d2 = 8.0, id = 0.0;
    for (int k = -1; k <= 1; k++) {
        for (int j = -1; j <= 1; j++) {
            for (int m = -1; m <= 1; m++) {
                float3 g = float3(float(m), float(j), float(k));
                float3 r = g + hash33(i + g) - f;
                float d = dot(r, r);
                if (d < d1) { d2 = d1; d1 = d; id = hash13(i + g + 7.0); }
                else if (d < d2) { d2 = d; }
            }
        }
    }
    return float3(sqrt(d1), sqrt(d2) - sqrt(d1), id);
}

float smin(float a, float b, float k) {
    float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
    return lerp(b, a, h) - k * h * (1.0 - h);
}

float sdEllipsoid(float3 p, float3 r) {
    float k0 = length(p / r);
    float k1 = length(p / (r * r));
    return k0 * (k0 - 1.0) / k1;
}

// --- the crystals: hexagonal prisms with six-faced terminations --------------

float sdCrystal(float3 p, float3 sz) {
    float d = max(-p.y - 0.35, abs(p.x) - sz.x);
    d = max(d, abs(0.5 * p.x + 0.8660254 * p.z) - sz.x);
    d = max(d, abs(-0.5 * p.x + 0.8660254 * p.z) - sz.x);
    float3 q = p - float3(0.0, sz.y + sz.z, 0.0);
    for (int i = 0; i < 6; i++) d = max(d, dot(q, PYR[i]));
    return d;
}

float crystals(float3 p) {
    // The cluster sits in a shell over the rock top; well clear of it, skip the loop.
    float shell = sdEllipsoid(p - float3(0.0, 0.2, 0.0), float3(1.15, 0.62, 0.95));
    if (shell > 0.05) return shell * 0.8;
    float d = 1e3;
    for (int i = 0; i < 12; i++) {
        float4 b = CRY_POS[i];
        float3 rel = p - b.xyz;
        float bd = length(rel) - b.w;
        if (bd > 0.05) { d = min(d, bd); continue; }
        float3 lp = float3(dot(CRY_R0[i], rel), dot(CRY_R1[i], rel), dot(CRY_R2[i], rel));
        d = min(d, sdCrystal(lp, CRY_SIZE[i]));
    }
    return d;
}

// --- the basalt ----------------------------------------------------------------

float ridged(float3 p, int oct) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 4; i++) {
        if (i >= oct) break;
        float n = 1.0 - abs(2.0 * vnoise(p) - 1.0);
        s += a * n * n;
        p = p * 2.07 + float3(3.1, 1.7, 5.3);
        a *= 0.5;
    }
    return s;
}

// Crests and gullies, cracks between angular blocks, blocks at slightly
// different heights (zero at the cracks, so no step), fine grain, vesicle pits.
float rockRelief(float3 p) {
    float off = -(ridged(p * 8.0, 3) - 0.45) * 0.07;
    float3 v = voronoi(p * 14.0);
    off += (1.0 - smoothstep(0.0, 0.12, v.y)) * 0.013;
    off -= (v.z - 0.5) * 0.012 * smoothstep(0.0, 0.15, v.y);
    off -= (ridged(p * 40.0, 2) - 0.45) * 0.014;
    off += smoothstep(0.6, 0.9, vnoise(p * 26.0)) * 0.02;
    return off;
}

float rockBase(float3 p, int oct) {
    float d = sdEllipsoid(p - float3(0.0, 0.20, 0.0), float3(0.9, 0.36, 0.7));
    if (d < 0.3) {
        d += (fbmN(p * 2.6, oct) - 0.5) * 0.22;
        // Faded in rather than switched on, so the field has no seam to trip on.
        if (oct >= 5 && d < 0.14) d += rockRelief(p) * (1.0 - smoothstep(0.06, 0.14, d));
    }
    return max(d, -p.y);
}

// --- the baked volume -----------------------------------------------------------

float rockTex(float3 p, VOL_PARAMS) {
    float coarse = sdEllipsoid(p - float3(0.0, 0.20, 0.0), float3(0.9, 0.36, 0.7));
    if (coarse > 0.2) return (coarse - 0.17) * 0.9;
    return VOL_SAMPLE(clamp((p - RB_MIN) / RB_SIZE, 0.0, 1.0)).r * 0.42;
}

// The crystal distance is baked too, as an accelerator: while it says the nearest
// crystal is more than a few millimetres away, step by it; close in, switch to
// the exact faceted distance so the facets stay sharp.
float cryField(float3 p, int oct, VOL_PARAMS) {
    if (oct < 6) {
        float3 uvw = (p - RB_MIN) / RB_SIZE;
        if (all(uvw > 0.0) && all(uvw < 1.0)) {
            float v = VOL_SAMPLE(uvw).g;
            if (v > 0.04) return v - 0.02;
        }
    }
    return crystals(p);
}

// Rock distance, scaled to a safe step. oct 6 evaluates the full noise: normals
// come from the true surface, never from the voxel grid.
float rockField(float3 p, int oct, VOL_PARAMS) {
    if (oct < 6) return rockTex(p, VOL_ARGS);
    return rockBase(p, 5) * 0.42;
}

float scene_map(float3 p, int oct, VOL_PARAMS) {
    return smin(rockField(p, oct, VOL_ARGS), cryField(p, oct, VOL_ARGS), 0.03);
}

float3 calcNormal(float3 p, VOL_PARAMS) {
    const float2 e = float2(1.0, -1.0) * 0.0008;
    return normalize(e.xyy * scene_map(p + e.xyy, 6, VOL_ARGS) + e.yyx * scene_map(p + e.yyx, 6, VOL_ARGS)
                   + e.yxy * scene_map(p + e.yxy, 6, VOL_ARGS) + e.xxx * scene_map(p + e.xxx, 6, VOL_ARGS));
}

// A cheaper normal for secondary hits, seen in the floor or through glass.
float3 calcNormalFast(float3 p, VOL_PARAMS) {
    const float2 e = float2(1.0, -1.0) * 0.004;
    return normalize(e.xyy * scene_map(p + e.xyy, 4, VOL_ARGS) + e.yyx * scene_map(p + e.yyx, 4, VOL_ARGS)
                   + e.yxy * scene_map(p + e.yxy, 4, VOL_ARGS) + e.xxx * scene_map(p + e.xxx, 4, VOL_ARGS));
}

float3 cryNormal(float3 p) {
    const float2 e = float2(1.0, -1.0) * 0.0008;
    return normalize(e.xyy * crystals(p + e.xyy) + e.yyx * crystals(p + e.yyx)
                   + e.yxy * crystals(p + e.yxy) + e.xxx * crystals(p + e.xxx));
}

float2 boundHit(float3 ro, float3 rd) {
    float3 oc = ro - BOUND_C;
    float b = dot(oc, rd);
    float c = dot(oc, oc) - BOUND_R * BOUND_R;
    float h = b * b - c;
    if (h < 0.0) return float2(-1.0, -1.0);
    float s = sqrt(h);
    return float2(max(-b - s, 0.0), -b + s);
}

float march(float3 ro, float3 rd, int steps, int oct, VOL_PARAMS) {
    float2 bh = boundHit(ro, rd);
    if (bh.y < 0.0) return -1.0;
    float t = bh.x;
    [loop] for (int i = 0; i < MARCH_STEPS; i++) {
        if (i >= steps) break;
        float h = scene_map(ro + rd * t, oct, VOL_ARGS);
        if (h < 0.00025 + 0.0003 * t) return t;
        t += h * 0.9;
        if (t > bh.y) break;
    }
    return -1.0;
}

// --- the studio: key softbox (it swings), cyan rim strip, overhead fill -------

float softbox(float3 d, float3 axis, float2 size, float soft) {
    float c = dot(d, axis);
    if (c <= 0.0) return 0.0;
    float3 t = normalize(cross(axis, float3(0.0, 1.0, 0.0)));
    float3 b = cross(t, axis);
    float2 uv = abs(float2(dot(d, t), dot(d, b)) / c);
    float2 m = 1.0 - smoothstep(size - soft, size + soft, uv);
    return m.x * m.y;
}

float3 env(float3 d, float rough, Look L) {
    float s = 0.01 + rough * 0.6;
    float spread = 1.0 / (1.0 + rough * 2.5);
    float3 c = lerp(float3(0.004, 0.005, 0.006), float3(0.028, 0.033, 0.037), smoothstep(-0.1, 0.9, d.y));
    if (d.y < -0.02) c = float3(0.006, 0.007, 0.008);
    c += KEY_COL * 2.4 * spread * softbox(d, L.key, float2(0.32, 0.22), s);
    c += L.rim * 3.0 * spread * softbox(d, RIM_DIR, float2(0.05, 0.6), s);
    c += float3(0.45, 0.5, 0.55) * 0.12 * spread
       * softbox(d, normalize(float3(0.02, 1.0, -0.2)), float2(0.35, 0.35), s);
    return c;
}

// --- materials -----------------------------------------------------------------

float3 basaltRough(float3 q) {
    float g = fbmN(q * 7.0, 3);
    float3 a = float3(0.026, 0.028, 0.03) * (0.7 + 0.6 * g);
    a *= 1.0 - 0.6 * smoothstep(0.76, 0.82, vnoise(q * 34.0));                          // vesicles
    a = lerp(a, float3(0.22, 0.23, 0.23), smoothstep(0.92, 0.96, vnoise(q * 90.0)) * 0.4); // phenocrysts
    a = lerp(a, a * float3(1.35, 1.05, 0.8), smoothstep(0.5, 0.8, vnoise(q * 3.0)) * 0.5); // weathering
    return a;
}

// x = how glassy (1 crystal, 0 basalt), y = how much of the glass is coated.
float2 glassMix(float3 q, VOL_PARAMS) {
    float r = rockTex(q, VOL_ARGS) / 0.42 * 0.75, c = crystals(q);
    float m = smoothstep(-0.06, 0.06, r - c);
    float grains = smoothstep(0.78, 0.86, vnoise(q * 13.0)) * smoothstep(0.25, 0.0, c);
    m = max(m, grains);
    float coat = smoothstep(0.35, 0.8, fbmN(q * 16.0, 3) + (0.05 - max(r, 0.0)) * 7.0);
    return float2(clamp(m, 0.0, 1.0), coat);
}

float3 chlorite(float3 q) {
    return lerp(float3(0.018, 0.034, 0.02), float3(0.05, 0.075, 0.035), fbmN(q * 30.0, 3))
         * (0.7 + 0.6 * vnoise(q * 120.0));
}

// Light toward the key: soft shadows, tinted (not blocked) where it passes
// through a crystal. The start is jittered per pixel to break up banding.
float3 lightTransmit(float3 ro, float3 rd, Look L, VOL_PARAMS) {
    if (boundHit(ro, rd).y < 0.0) return float3(1.0, 1.0, 1.0);
    float sr = 1.0, sc = 1.0;
    float t = 0.03 + 0.03 * hash13(float3(L.frag, L.time));
    [loop] for (int i = 0; i < 40; i++) {
        float3 p = ro + rd * t;
        float hr = rockTex(p, VOL_ARGS);
        float hc = cryField(p, 4, VOL_ARGS);
        sr = min(sr, 9.0 * hr / t);
        sc = min(sc, 9.0 * hc / t);
        t += clamp(min(hr, hc), 0.015, 0.2);
        if (sr < 0.002 || t > 4.0) break;
    }
    sr = clamp(sr, 0.0, 1.0);
    sc = clamp(sc, 0.0, 1.0);
    return float3(sr, sr, sr) * lerp(L.shadow, float3(1.0, 1.0, 1.0), sc);
}

float calcAO(float3 p, float3 n, VOL_PARAMS) {
    float o = 0.0, s = 1.0;
    for (int i = 0; i < 5; i++) {
        float h = 0.01 + 0.06 * float(i);
        // The first taps see the baked full detail, the surface's own, or AO
        // reads as stripes; the outer ones only need the shape.
        float d = scene_map(p + n * h, i < 2 ? 5 : 2, VOL_ARGS);
        o += (h - d) * s;
        s *= 0.7;
    }
    return clamp(1.0 - 2.2 * o, 0.0, 1.0);
}

// Surface shading. The shadow toward the key (tr) and the occlusion (ao) are
// computed once per pixel, at whatever the primary ray hit, and handed in: they
// are the dear loops, and the rock, the coat and the floor all share them.
float3 shadeSurf(float3 p, float3 n, float3 rd, float3 alb, float rough, float F0,
                               float3 tr, float ao, Look L) {
    float dif = max(dot(n, L.key), 0.0);
    float rim = max(dot(n, RIM_DIR), 0.0);
    float nv = max(dot(n, -rd), 0.0);
    float fr = F0 + (max(1.0 - rough, F0) - F0) * pow(1.0 - nv, 5.0);
    float3 col = alb * (KEY_COL * dif * tr + L.rim * rim * 0.45 + env(n, 1.0, L) * 0.25 * ao);
    float3 h = normalize(L.key - rd);
    float nh = max(dot(n, h), 0.0);
    float a = max(rough * rough, 0.002), a2 = a * a;
    float dd = nh * nh * (a2 - 1.0) + 1.0;
    col += KEY_COL * tr * (a2 / (PI * dd * dd)) * fr * dif * 0.25 * smoothstep(0.1, 0.3, rough);
    col += env(reflect(rd, n), rough, L) * fr * ao * lerp(float3(1.0, 1.0, 1.0), tr, 0.5) * lerp(1.0, 0.2, rough);
    return col;
}

float3 glassGrain(float3 n, float3 rd, Look L) {
    float F = 0.05 + 0.95 * pow(1.0 - max(dot(n, -rd), 0.0), 5.0);
    float lit = 0.3 + 0.7 * max(dot(n, L.key), 0.0);
    float3 body = float3(0.02, 0.09, 0.11) * lit + L.scatter * 0.6 * 0.22 * lit;
    return lerp(body, env(reflect(rd, n), 0.03, L), F);
}

// Secondary hits (the floor's reflection, the view through a crystal): no
// shadows, no occlusion, no recursion.
float3 surfaceSimple(float3 p, float3 n, float3 rd, Look L, VOL_PARAMS) {
    float2 g = glassMix(p, VOL_ARGS);
    float3 glass = lerp(glassGrain(n, rd, L),
                       shadeSurf(p, n, rd, chlorite(p), 0.4, 0.04, float3(1.0, 1.0, 1.0), 1.0, L), g.y);
    return lerp(shadeSurf(p, n, rd, basaltRough(p), 0.62, 0.04, float3(1.0, 1.0, 1.0), 1.0, L), glass, g.x);
}

// The floor's own light, without its reflection (which is fetched with the
// other secondary rays, see the fragment).
float3 floorBase(float3 P, float3 tr, float ao, Look L) {
    float3 alb = float3(0.022, 0.025, 0.028) * (0.85 + 0.3 * vnoise(P * 60.0));
    return alb * (KEY_COL * L.key.y * tr + env(float3(0.0, 1.0, 0.0), 1.0, L) * 0.8 * ao);
}

// A crystal's light, split in two: what the glass gives itself (reflection,
// inclusions, glow, milkiness) and how much of whatever lies behind it reaches
// the eye, with the ray that goes to fetch it. The fetch is done by the caller,
// once per pixel, together with the floor's reflection.
struct Glass {
    float3 col; float3 w;          // own light; the weight of what lies behind
    float3 o; float3 d;            // the ray out of the crystal
    float3 rdi; float3 ne;         // for dispersion where it leaves into the studio
    float fetch;                   // 1 when there is something behind to fetch
};

Glass shadeCrystal(float3 p, float3 n, float3 rd, Look L, VOL_PARAMS) {
    float nv = max(dot(n, -rd), 0.0);
    float F = 0.05 + 0.95 * pow(1.0 - nv, 5.0);
    float3 refl = env(reflect(rd, n), 0.015, L);
    float3 rdi = refract(rd, n, 1.0 / IOR);
    float t = 0.004, milk = 0.0;
    float3 q = p;
    // Green chlorite inclusions suspended in the glass, front to back.
    float3 incCol = float3(0.0, 0.0, 0.0);
    float incA = 0.0;
    float lit0 = 0.35 + 0.65 * max(dot(n, L.key), 0.0);
    [loop] for (int i = 0; i < 36; i++) {
        q = p + rdi * t;
        float d = -crystals(q);
        float dt = clamp(d, 0.003, 0.012);
        float2 ci = VOL_SAMPLE(clamp((q - RB_MIN) / RB_SIZE, 0.0, 1.0)).ba;
        float dens = smoothstep(0.6, 0.74, ci.x);
        if (dens > 0.0) {
            float3 c = lerp(float3(0.05, 0.10, 0.05), float3(0.12, 0.16, 0.08), ci.y) * KEY_COL * lit0;
            float a = 1.0 - exp(-dens * dt * 80.0);
            float3 absorbed = exp(-t * L.absorb);
            incCol += (1.0 - incA) * a * c * absorbed;
            incA += (1.0 - incA) * a;
        }
        milk += dt * 4.0 * (0.4 + 0.6 * ci.y);
        if (d < 0.0015 || incA > 0.97) break;
        t += dt;
    }
    Glass g;
    g.fetch = 0.0;
    g.o = q;
    g.d = float3(0.0, 1.0, 0.0);
    g.rdi = rdi;
    g.ne = n;
    float3 behind = float3(0.0, 0.0, 0.0);
    if (incA <= 0.97) {
        float3 ne = cryNormal(q);
        float3 dG = refract(rdi, -ne, IOR);
        if (dot(dG, dG) < 1e-4) {
            behind = env(reflect(rdi, -ne), 0.04, L) * 0.9;           // total internal reflection
        } else {
            g.fetch = 1.0;
            g.o = q + dG * 0.01;
            g.d = dG;
            g.ne = ne;
        }
    }
    float3 trans = (1.0 - incA) * exp(-t * L.absorb);
    float lit = 0.25 + 0.75 * max(dot(n, L.key), 0.0);
    float3 own = incCol + trans * behind + L.scatter * 0.32 * lit * (1.0 - exp(-t * 6.5));
    float3 milkCol = L.milk * (0.10 + 0.45 * lit);
    float mk = 1.0 - exp(-milk);
    g.col = lerp(lerp(own, milkCol, mk), refl, F);
    g.w = trans * (1.0 - mk) * (1.0 - F);
    return g;
}

// Fine grit as a normal map, each scale fading out once its grains are smaller
// than about a pixel at this distance, so it never shimmers. w = the height.
float grit(float3 q, float f1, float f2) {
    return 0.55 * f1 * vnoise(q * 160.0) + 0.3 * f2 * vnoise(q * 420.0)
         + 0.15 * f1 * (1.0 - abs(2.0 * vnoise(q * 90.0) - 1.0));
}

float4 gritNormal(float3 p, float3 n, Look L) {
    float px = length(p - L.cam) * L.px;                      // world size of one pixel here
    float f1 = 1.0 - smoothstep(0.25, 0.6, px * 160.0);
    float f2 = 1.0 - smoothstep(0.25, 0.6, px * 420.0);
    float h = grit(p, f1, f2);
    if (f1 <= 0.0) return float4(n, h);
    const float e = 0.0006;
    const float2 k = float2(1.0, -1.0) * e;
    float3 g = (k.xyy * grit(p + k.xyy, f1, f2) + k.yyx * grit(p + k.yyx, f1, f2)
              + k.yxy * grit(p + k.yxy, f1, f2) + k.xxx * grit(p + k.xxx, f1, f2)) / (4.0 * e * e);
    return float4(normalize(n - 0.0036 * (g - n * dot(g, n))), h);
}

float3 shadeBasalt(float3 p, float3 n, float3 rd, float3 tr, float ao, Look L) {
    float4 gn = gritNormal(p, n, L);
    float3 alb = basaltRough(p) * (0.6 + 0.8 * gn.w);
    return shadeSurf(p, gn.xyz, rd, alb, 0.58, 0.04, tr, ao, L);
}

// The volume: x rock distance, y crystal distance (both clamped to +-0.4),
// z the inclusion field, w the milkiness noise.
float4 puikit_bg_bake(float4 pos : SV_Position) : SV_Target {
    float3 uvw = float3(pos.xy / bake_size.xy, (bake_size.w + 0.5) / bake_size.z);
    float3 bp = RB_MIN + uvw * RB_SIZE;
    float2 d = clamp(float2(rockBase(bp, 5), crystals(bp)), -0.4, 0.4);
    return float4(d, clamp(fbmN(bp * 20.0 + 2.0, 3) + 0.04, 0.0, 1.0), vnoise(bp * 40.0));
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float s = time + START;
    // The camera hovers low over the rock top and aims just above it, so a few
    // crystals stand in frame against the rock rather than filling it.
    float th = 0.9 + s * 0.045, R = 1.0 + 0.12 * sin(s * 0.07);
    float3 ro = float3(R * cos(th), 0.55 + 0.16 * sin(s * 0.043), R * 0.8 * sin(th));
    float pt = th + 0.45 * sin(s * 0.05), f = 0.38 + 0.2 * sin(s * 0.041);
    float3 tgt = float3(0.9 * f * cos(pt), 0.2 + 0.36 * sqrt(1.0 - f * f) + 0.05, 0.7 * f * sin(pt));
    float focal = 2.2;
    float A = 2.25 + 0.55 * sin(s * 0.1);

    float3 tint = ink.rgb;
    Look L;
    L.key = normalize(float3(cos(A) * 0.85, 0.85, sin(A) * 0.85));
    L.rim = tint * 1.5;
    L.absorb = -log(max(tint, float3(0.02, 0.02, 0.02))) * ABSORB_K;
    L.scatter = tint * SCATTER_K;
    L.shadow = min(tint * SHADOW_K, float3(1.0, 1.0, 1.0));
    L.milk = tint * MILK_K;
    L.cam = ro;
    L.px = 1.0 / (focal * resolution.y);
    L.time = s;
    L.frag = pos.xy;

    float2 uv = float2(pos.x - 0.5 * resolution.x, 0.5 * resolution.y - pos.y) / resolution.y;
    float3 ww = normalize(tgt - ro), uu = normalize(cross(ww, float3(0.0, 1.0, 0.0))), vv = cross(uu, ww);
    float3 rd = normalize(uv.x * uu + uv.y * vv + focal * ww);

    float3 bg = float3(0.006, 0.007, 0.008) + float3(0.024, 0.029, 0.033) * smoothstep(-0.2, 0.6, rd.y);
    float3 col = bg;
    float depth = 30.0;
    // What the primary ray found: 1 the specimen, 2 the floor, 0 the studio.
    int kind = 0;
    float3 P = ro, N = float3(0.0, 1.0, 0.0);
    float hit = march(ro, rd, MARCH_STEPS, 5, VOL_ARGS);
    if (hit > 0.0) {
        // Settle onto the surface: an overshoot into steep relief would leave the
        // point inside the rock, where its own shadow reads as contour stripes.
        for (int k = 0; k < 6; k++) hit += scene_map(ro + rd * hit, 5, VOL_ARGS) * 0.6;
        P = ro + rd * hit;
        N = calcNormal(P, VOL_ARGS);
        kind = 1;
        depth = hit;
    } else if (rd.y < 0.0) {
        depth = -ro.y / rd.y;
        P = ro + rd * depth;
        kind = 2;
    }

    // Shadow and occlusion, once, at whatever was hit.
    float3 tr = float3(1.0, 1.0, 1.0);
    float ao = 1.0;
    if (kind != 0) {
        tr = lightTransmit(P + N * (kind == 1 ? 0.02 : 0.002), L.key, L, VOL_ARGS);
        if (kind == 1 || length(P.xz) < 1.8) ao = calcAO(P, N, VOL_ARGS);
    }

    // At most one secondary ray per pixel -- through a crystal, or the floor's
    // reflection -- fetched below, with its weight in the final colour.
    float3 sw = float3(0.0, 0.0, 0.0), so = P, sd = N, srdi = rd, sne = N;
    int smode = 0;
    if (kind == 1) {
        float2 g = glassMix(P, VOL_ARGS);
        float3 rockC = float3(0.0, 0.0, 0.0), clearC = float3(0.0, 0.0, 0.0), coatC = float3(0.0, 0.0, 0.0);
        if (g.x < 0.99) rockC = shadeBasalt(P, N, rd, tr, ao, L);
        if (g.x > 0.01) {
            if (g.y < 0.99) {
                if (crystals(P) < 0.03) {
                    Glass gl = shadeCrystal(P, N, rd, L, VOL_ARGS);
                    clearC = gl.col;
                    if (gl.fetch > 0.5) {
                        sw = gl.w * (1.0 - g.y) * g.x;
                        so = gl.o;
                        sd = gl.d;
                        srdi = gl.rdi;
                        sne = gl.ne;
                        smode = 1;
                    }
                } else {
                    clearC = glassGrain(N, rd, L);
                }
            }
            if (g.y > 0.01) coatC = shadeSurf(P, N, rd, chlorite(P), 0.4, 0.04, tr, ao, L);
        }
        col = lerp(rockC, lerp(clearC, coatC, g.y), g.x);
    } else if (kind == 2) {
        float fade = exp(-dot(P.xz, P.xz) * 0.10);
        float fr = 0.03 + 0.97 * pow(1.0 - max(dot(N, -rd), 0.0), 5.0);
        col = lerp(bg, floorBase(P, tr, ao, L), fade);
        sw = float3(1.0, 1.0, 1.0) * (fade * fr * 0.85);
        so = P + N * 0.003;
        sd = reflect(rd, N);
        smode = 2;
    }
    if (smode != 0) {
        float h = march(so, sd, smode == 2 ? 70 : 40, smode == 2 ? 3 : 2, VOL_ARGS);
        float3 behind;
        if (h > 0.0) {
            float3 s2 = so + sd * h;
            behind = surfaceSimple(s2, calcNormalFast(s2, VOL_ARGS), sd, L, VOL_ARGS)
                   * (smode == 2 ? exp(-h * 1.8) : 1.0);
        } else if (smode == 2) {
            behind = env(sd, 0.35, L) * 0.4;
        } else if (sd.y < 0.0) {
            float3 q = so - sd * 0.01;
            behind = floorBase(q + sd * (-q.y / sd.y), float3(1.0, 1.0, 1.0), 1.0, L);
        } else {
            // Dispersion as the light leaves the glass into the studio.
            float3 dR = refract(srdi, -sne, 1.53), dB = refract(srdi, -sne, 1.575);
            behind = float3(env(dR, 0.02, L).r, env(sd, 0.02, L).g, env(dB, 0.02, L).b);
        }
        col += sw * behind;
    }
    // Linear HDR; inverse depth in alpha for the lens's depth of field.
    return float4(max(col * EXPOSURE, 0.0), 1.0 / depth);
}
"""


#: The lens: a macro's depth of field, bloom on the glints, vignette, fine grain.
LENS = Lens(bloom=1.4, threshold=0.75, vignette=0.32, grain=0.06, dof=0.014,
            focus_range=2.6) if AVAILABLE else None


def _clamped(value, default: float, lo: float, hi: float) -> float:
    try:
        v = float(default if value is None else value)
    except (TypeError, ValueError):
        v = default
    return min(hi, max(lo, v))


def crystal_shader(exposure=None, brightness=None, focus=None) -> dict:
    """The ``Shader`` fields for the Crystal scene with a theme's options applied:
    ``exposure`` (0.1..4, 1.25 as tuned), ``brightness`` (the picture's ceiling,
    0..1, default 0.5) and ``focus`` (how strong the depth of field is, 0..2, 1
    as tuned; 0 turns it off). Bad values fall back to the defaults."""
    options = dict(exposure=repr(_clamped(exposure, 1.25, 0.1, 4.0)))
    layout_msl, layout_hlsl = _layout_constants("msl"), _layout_constants("hlsl")
    lens = replace(LENS, level=_clamped(brightness, DEFAULT_BRIGHTNESS, 0.0, 1.0),
                   dof=LENS.dof * _clamped(focus, 1.0, 0.0, 2.0))
    return {
        "source": _MSL_OPTIONS.format(**options) + CRYSTAL_MSL_BODY.replace("// @LAYOUT@", layout_msl),
        "source_hlsl": (_HLSL_OPTIONS.format(**options)
                        + CRYSTAL_HLSL_BODY.replace("// @LAYOUT@", layout_hlsl)),
        "lens": lens,
        "volumes": (ShaderVolume(VOLUME_SIZE),),
        "resolution_scale": RESOLUTION_SCALE,
        "frame_rate": FRAME_RATE,
        "idle": "freeze",
    }
