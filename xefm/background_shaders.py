"""XeFM's background scenes — the animated fields drawn behind the file panes.

Every scene XeFM offers is a fragment shader, evaluated per pixel on the GPU. That
is a deliberate consolidation: scenes used to come in two kinds, and the CPU kind
(line segments stroked by the backend) lost on every axis that mattered. Density
cost CPU time per segment, the whole scene was stroked in a single color, and —
the one that decided it — a segment scene was drawn *inside* the UI's render pass,
so animating it repainted the entire UI every frame no matter how little it drew.
A shader owns a layer behind the UI, which the backend advances without touching a
UI pixel, so an idle XeFM with a background costs a fraction of what it used to.

**Writing one.** A scene is a single fragment function named ``puikit_bg_fragment``.
PuiKit prepends its prelude — the uniform struct and a fullscreen vertex stage — so
the source here is just that function::

    fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                       constant BackgroundUniforms &u [[buffer(0)]])

``u`` carries ``resolution`` (pixels), ``time`` (seconds, already scaled by the
theme's speed), ``opacity``, and the theme's ``ink``/``backdrop`` as RGBA — so a
shader stays on-palette without knowing anything about XeFM's theme system. The
source is compiled when the theme is applied; one that fails to compile draws
nothing and logs the compiler error, so a typo costs a blank background.

**Every scene ships three dialects.** Shader source is the one genuinely
backend-specific part of a background: macOS compiles Metal Shading Language,
Windows compiles HLSL, and the web (WebGL) backend compiles GLSL ES — different
languages. So each scene names its dialect — ``<SCENE>_MSL``, ``<SCENE>_HLSL``,
``<SCENE>_GLSL`` — and the registry at the bottom pairs them. The MSL is the
source of truth: the HLSL is hand-written and no compiler checks it against the
MSL, so tuning one and forgetting the twin is the standing hazard, which
``test_background_shaders.py`` catches by comparing their constants. The
**GLSL is generated** from the MSL by ``tools/generate_shader_glsl.py`` (a fixed
transpile — the scenes are written to allow it), so it cannot drift; re-run that
tool after tuning the MSL, and the test asserts the committed GLSL matches.

**The per-pixel inversion.** A CPU scene walks its objects and draws them. A shader
is asked, for one pixel at a time, "what covers you?" — so every scene here needs a
way to answer that without visiting everything. The recurring device is a *grid*: an
object's identity comes from hashing its cell index, so a pixel can compute which
cells could possibly reach it and consult only those. The rain visits its own column
and two neighbours, the starfield cells along a depth ray, the constellation a 5x5
block of nodes. The wave takes the idea furthest: it *texture-maps* its cells rather
than walking them, sampling a procedural dot field in the sheet's own plane, which
decouples its particle count from its per-pixel cost entirely. Where a scene needs
per-object randomness it hashes the cell index rather than calling anything
time-varying, so an object keeps a fixed identity across frames and all motion comes
from ``time``.
"""

from __future__ import annotations

#: A flowing sheet of particles — a wave surface rendered as a point cloud.
#:
#: Structure: the surface is a sum of travelling sine trains, sampled at a stack of
#: depth layers. Rather than *placing* particles, each layer **texture-maps** them:
#: a procedural dot field is sampled in the sheet's own (x, z) plane, and the layer
#: keeps whatever dots sit at the height that projects onto this pixel. That
#: inversion is what makes the particle count free — density is the texture's
#: frequency, not a loop bound — and it is why this scene draws several times the
#: particles of the cell-walking version it replaces at slightly *less* cost.
#:
#: There is no texture *asset*: puikit's background shaders take uniforms and bind
#: no images (see puikit ``SHADER_PRELUDE``), so the dot field is generated in
#: place. That is the better trade anyway — a procedural field is infinite, tiles
#: without a seam, and can be sampled at any frequency, so nothing has to be
#: uploaded or kept resident to make the sheet denser.
#:
#: Three octaves of that field are sampled per layer, each **rotating** in the
#: plane at its own slow rate. Rotation is what turns a fixed lattice into drifting
#: particles, and because the rates are mutually incommensurate the octaves never
#: re-align — the sheet churns instead of sliding, and never visibly repeats.
#:
#: The colour is the part the CPU renderer could never do: hue shifts along the
#: sheet and toward the crests, so the wave runs cool in its troughs and pales to
#: near-white where it peaks, in the spirit of the reference. It is anchored on the
#: theme's ``ink`` so it still belongs to the palette rather than ignoring it.
WAVE_MSL = """
// --- tunables ---------------------------------------------------------------
// LAYERS x 3 octaves is the per-pixel iteration count and the dominant cost. Each
// octave is a single texture lookup -- the neighbouring-cell visits the previous
// version needed are gone (see `splat`), which is what buys the extra octaves and
// the doubled layer count. Everything in the loop is transcendental-free except
// the surface and the per-octave rotation.
constant int   LAYERS      = 24;     // depth slabs sampled per pixel
constant float Z_NEAR      = 1.5;    // nearest / furthest sheet depth
constant float Z_FAR       = 5.2;
constant float CAM_H       = 0.62;   // camera height above the sheet
constant float HORIZON     = 0.36;   // sheet's vanishing line, fraction of height
constant float FOCAL       = 0.85;   // focal length in view-height units
constant float FREQ        = 24.0;   // texture cells per world unit
constant float DOT_FRAC    = 0.18;   // dot radius as a fraction of a cell
constant float SPRAY       = 0.34;   // how far a lofted particle rises
constant float GAIN        = 10.0;   // overall brightness of the accumulation
constant float THICK       = 1.0;    // band half-thickness, in dot radii

// Particle jitter, loft and brightness must be fixed per particle, so they come
// from its cell index rather than anything time-varying -- otherwise every particle
// would reshuffle each frame. This is the arithmetic-only variety on purpose: the
// usual fract(sin(n)*43758.0) idiom costs a transcendental, and at 72 lookups per
// pixel that alone would be a third of the frame.
static inline float3 hash33(float2 p) {
    float3 v = fract(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xxy + v.yzz) * v.zyx);
}

// The surface: three travelling sine trains at unrelated angles and wavelengths,
// which fold into each other instead of reading as corrugation.
static inline float surface(float x, float z, float t) {
    return 0.32 * sin(1.30 * x + 0.55 * z + 0.55 * t)
         + 0.18 * sin(-0.85 * x + 1.30 * z + 0.41 * t)
         + 0.10 * sin(2.40 * x - 0.90 * z + 0.72 * t);
}

// One octave of the particle texture. Rotates the plane by `ang`, lands in a cell,
// and measures the distance to that cell's jittered dot; `dy` is how far this pixel
// sits above the sheet, so the dot only registers if its height projects here.
// Returns the density contribution in .x and coverage in .y (for crest colouring).
static inline float2 splat(float2 p, float freq, float ang, float lodPix, float dy) {
    float s = sin(ang), c = cos(ang);
    float2 q = float2(c * p.x - s * p.y, s * p.x + c * p.y) * freq;
    float2 cell = floor(q);
    float2 f = q - cell;
    float3 rnd = hash33(cell);
    // Jitter is bounded so the dot cannot cross a cell edge. That is the whole
    // trick: one lookup is then *exact*, with none of the neighbouring-cell visits
    // the placed-particle version needed to avoid seams -- and it only holds while
    // the dots stay small, so finer dots make this scene cheaper, not dearer.
    float2 center = float2(0.5) + (rnd.xy - 0.5) * 0.62;
    float d = length(f - center);
    // Widen the dot to the pixel footprint once the cell goes subpixel, so distant
    // layers dissolve toward their average instead of aliasing into crawling noise.
    float r = max(DOT_FRAC, lodPix * freq);
    float cov = max(0.0, 1.0 - d / r);
    cov = cov * cov * (DOT_FRAC / r);      // conserve energy as it widens
    // Half-thickness comes from *this* octave's radius, so a dot is as tall as it
    // is wide at every frequency. Deriving it from one shared frequency instead
    // stretches the finer octaves into vertical dashes.
    float rw = r / freq * THICK;
    float loft = rnd.z * rnd.z * rnd.z;    // most on the sheet, a few lofted high
    float band = max(0.0, 1.0 - abs(dy - loft * SPRAY) / rw);
    // A second, independent value out of the same hash. Without it every dot peaks
    // at one brightness and the sheet reads as uniform grain rather than particles.
    float bright = (0.55 + 0.45 * fract(rnd.z * 13.7)) * (1.0 - 0.7 * loft);
    return float2(cov * band * band * bright, cov * band);
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float2 uv = pos.xy / u.resolution;
    float aspect = u.resolution.x / u.resolution.y;
    // Work in view-height units so the sheet keeps its proportions in any window.
    float px = (uv.x - 0.5) * aspect;
    float t = u.time;

    float density = 0.0;   // accumulated particle coverage
    float crest = 0.0;     // height of whatever contributed most, for colouring

    for (int i = 0; i < LAYERS; ++i) {
        float fi = (float(i) + 0.5) / float(LAYERS);
        // Even steps in 1/z are even steps on screen; stepping z directly would
        // pile the far half of the sheet onto a single line.
        float z = 1.0 / mix(1.0 / Z_NEAR, 1.0 / Z_FAR, fi);
        float layerFade = 1.0 - 0.55 * fi;

        // The projection, run backwards. Instead of placing a particle and asking
        // where it lands, ask what this pixel is looking at: at this depth the ray
        // crosses the sheet at wx, and only a particle at height py projects here.
        float wx = px * z / FOCAL;
        float py = CAM_H - (uv.y - HORIZON) * z / FOCAL;
        float h = surface(wx, z, t);

        // One pixel's width in world units at this depth, for the LOD widening.
        float lodPix = (z / FOCAL) / u.resolution.y;

        // Three octaves at unrelated frequencies, each rotating at its own rate.
        float2 p = float2(wx, z);
        float dy = py - h;
        float2 a = splat(p, FREQ,         0.050 * t,         lodPix, dy);
        float2 b = splat(p, FREQ * 1.70, -0.037 * t + 2.1,   lodPix, dy);
        float2 c = splat(p, FREQ * 2.60,  0.021 * t + 4.7,   lodPix, dy);

        density += (a.x * 1.00 + b.x * 0.80 + c.x * 0.60) * layerFade;
        crest = max(crest, (a.y + b.y) * (0.5 + 0.5 * h / 0.6));
    }

    density = 1.0 - exp(-density * GAIN);   // saturating, so dense areas read solid

    // Colour: sweep the hue along the sheet and lift it toward white at the
    // crests. The two ends are the theme ink pushed apart in opposite directions
    // rather than fixed colours, so the gradient tracks whatever palette is
    // active while still spanning the violet-to-cyan range of the reference.
    float3 violet = u.ink.rgb * float3(1.00, 0.42, 1.30);
    float3 cyan   = u.ink.rgb * float3(0.34, 1.10, 1.18);
    float sweep = 0.5 + 0.5 * sin(uv.x * 3.1 + t * 0.25);
    float3 tint = mix(violet, cyan, sweep);
    // Crests catch the light and pale out, which is what separates the leading
    // edge of the sheet from the mass behind it.
    float3 rgb = mix(tint, float3(1.0), clamp(crest * 1.9, 0.0, 1.0) * 0.7);

    rgb = mix(u.backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * u.opacity);
    return float4(rgb, 1.0);
}
"""

#: The HLSL translation of :data:`WAVE_MSL` for puikit's Direct3D 11 (Windows) backend.
#:
#: A shader is the one genuinely backend-specific part of a background: Metal Shading
#: Language and HLSL are different languages, so a cross-platform scene ships the
#: same math in both and each backend compiles the dialect it speaks (macOS reads
#: ``source``, Windows reads ``source_hlsl`` — see puikit ``Shader``). This is a
#: line-for-line port of the wave above; only the dialect differs (``fract``→``frac``,
#: ``mix``→``lerp``, the ``constant`` qualifiers become ``static const``, and the
#: uniforms are read from the ``BackgroundUniforms`` cbuffer as globals rather than a
#: ``[[buffer(0)]]`` parameter). Keep the two in sync when tuning the scene.
WAVE_HLSL = """
// --- tunables (see WAVE_MSL for the rationale of each) -------------------
static const int   LAYERS   = 24;
static const float Z_NEAR   = 1.5;
static const float Z_FAR    = 5.2;
static const float CAM_H    = 0.62;
static const float HORIZON  = 0.36;
static const float FOCAL    = 0.85;
static const float FREQ     = 24.0;
static const float DOT_FRAC = 0.18;
static const float SPRAY    = 0.34;
static const float GAIN     = 10.0;
static const float THICK    = 1.0;

float3 hash33(float2 p) {
    float3 v = frac(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return frac((v.xxy + v.yzz) * v.zyx);
}
float surface(float x, float z, float t) {
    return 0.32 * sin(1.30 * x + 0.55 * z + 0.55 * t)
         + 0.18 * sin(-0.85 * x + 1.30 * z + 0.41 * t)
         + 0.10 * sin(2.40 * x - 0.90 * z + 0.72 * t);
}

// One octave of the particle texture -- see the MSL twin for what each step is for.
float2 splat(float2 p, float freq, float ang, float lodPix, float dy) {
    float s = sin(ang), c = cos(ang);
    float2 q = float2(c * p.x - s * p.y, s * p.x + c * p.y) * freq;
    float2 cell = floor(q);
    float2 f = q - cell;
    float3 rnd = hash33(cell);
    float2 center = float2(0.5, 0.5) + (rnd.xy - 0.5) * 0.62;
    float d = length(f - center);
    float r = max(DOT_FRAC, lodPix * freq);
    float cov = max(0.0, 1.0 - d / r);
    cov = cov * cov * (DOT_FRAC / r);
    float rw = r / freq * THICK;
    float loft = rnd.z * rnd.z * rnd.z;
    float band = max(0.0, 1.0 - abs(dy - loft * SPRAY) / rw);
    float bright = (0.55 + 0.45 * frac(rnd.z * 13.7)) * (1.0 - 0.7 * loft);
    return float2(cov * band * band * bright, cov * band);
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float2 uv = pos.xy / resolution;
    float aspect = resolution.x / resolution.y;
    float px = (uv.x - 0.5) * aspect;
    float t = time;

    float density = 0.0;
    float crest = 0.0;

    for (int i = 0; i < LAYERS; ++i) {
        float fi = (float(i) + 0.5) / float(LAYERS);
        float z = 1.0 / lerp(1.0 / Z_NEAR, 1.0 / Z_FAR, fi);
        float layerFade = 1.0 - 0.55 * fi;

        float wx = px * z / FOCAL;
        float py = CAM_H - (uv.y - HORIZON) * z / FOCAL;
        float h = surface(wx, z, t);

        float lodPix = (z / FOCAL) / resolution.y;

        float2 p = float2(wx, z);
        float dy = py - h;
        float2 a = splat(p, FREQ,         0.050 * t,         lodPix, dy);
        float2 b = splat(p, FREQ * 1.70, -0.037 * t + 2.1,   lodPix, dy);
        float2 c = splat(p, FREQ * 2.60,  0.021 * t + 4.7,   lodPix, dy);

        density += (a.x * 1.00 + b.x * 0.80 + c.x * 0.60) * layerFade;
        crest = max(crest, (a.y + b.y) * (0.5 + 0.5 * h / 0.6));
    }

    density = 1.0 - exp(-density * GAIN);

    float3 violet = ink.rgb * float3(1.00, 0.42, 1.30);
    float3 cyan   = ink.rgb * float3(0.34, 1.10, 1.18);
    float sweep = 0.5 + 0.5 * sin(uv.x * 3.1 + t * 0.25);
    float3 tint = lerp(violet, cyan, sweep);
    float3 rgb = lerp(tint, float3(1.0, 1.0, 1.0), clamp(crest * 1.9, 0.0, 1.0) * 0.7);

    rgb = lerp(backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * opacity);
    return float4(rgb, 1.0);
}
"""

WAVE_GLSL = """
// --- tunables ---------------------------------------------------------------
// LAYERS x 3 octaves is the per-pixel iteration count and the dominant cost. Each
// octave is a single texture lookup -- the neighbouring-cell visits the previous
// version needed are gone (see `splat`), which is what buys the extra octaves and
// the doubled layer count. Everything in the loop is transcendental-free except
// the surface and the per-octave rotation.
const int   LAYERS      = 24;     // depth slabs sampled per pixel
const float Z_NEAR      = 1.5;    // nearest / furthest sheet depth
const float Z_FAR       = 5.2;
const float CAM_H       = 0.62;   // camera height above the sheet
const float HORIZON     = 0.36;   // sheet's vanishing line, fraction of height
const float FOCAL       = 0.85;   // focal length in view-height units
const float FREQ        = 24.0;   // texture cells per world unit
const float DOT_FRAC    = 0.18;   // dot radius as a fraction of a cell
const float SPRAY       = 0.34;   // how far a lofted particle rises
const float GAIN        = 10.0;   // overall brightness of the accumulation
const float THICK       = 1.0;    // band half-thickness, in dot radii

// Particle jitter, loft and brightness must be fixed per particle, so they come
// from its cell index rather than anything time-varying -- otherwise every particle
// would reshuffle each frame. This is the arithmetic-only variety on purpose: the
// usual fract(sin(n)*43758.0) idiom costs a transcendental, and at 72 lookups per
// pixel that alone would be a third of the frame.
vec3 hash33(vec2 p) {
    vec3 v = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xxy + v.yzz) * v.zyx);
}

// The surface: three travelling sine trains at unrelated angles and wavelengths,
// which fold into each other instead of reading as corrugation.
float surface(float x, float z, float t) {
    return 0.32 * sin(1.30 * x + 0.55 * z + 0.55 * t)
         + 0.18 * sin(-0.85 * x + 1.30 * z + 0.41 * t)
         + 0.10 * sin(2.40 * x - 0.90 * z + 0.72 * t);
}

// One octave of the particle texture. Rotates the plane by `ang`, lands in a cell,
// and measures the distance to that cell's jittered dot; `dy` is how far this pixel
// sits above the sheet, so the dot only registers if its height projects here.
// Returns the density contribution in .x and coverage in .y (for crest colouring).
vec2 splat(vec2 p, float freq, float ang, float lodPix, float dy) {
    float s = sin(ang), c = cos(ang);
    vec2 q = vec2(c * p.x - s * p.y, s * p.x + c * p.y) * freq;
    vec2 cell = floor(q);
    vec2 f = q - cell;
    vec3 rnd = hash33(cell);
    // Jitter is bounded so the dot cannot cross a cell edge. That is the whole
    // trick: one lookup is then *exact*, with none of the neighbouring-cell visits
    // the placed-particle version needed to avoid seams -- and it only holds while
    // the dots stay small, so finer dots make this scene cheaper, not dearer.
    vec2 center = vec2(0.5) + (rnd.xy - 0.5) * 0.62;
    float d = length(f - center);
    // Widen the dot to the pixel footprint once the cell goes subpixel, so distant
    // layers dissolve toward their average instead of aliasing into crawling noise.
    float r = max(DOT_FRAC, lodPix * freq);
    float cov = max(0.0, 1.0 - d / r);
    cov = cov * cov * (DOT_FRAC / r);      // conserve energy as it widens
    // Half-thickness comes from *this* octave's radius, so a dot is as tall as it
    // is wide at every frequency. Deriving it from one shared frequency instead
    // stretches the finer octaves into vertical dashes.
    float rw = r / freq * THICK;
    float loft = rnd.z * rnd.z * rnd.z;    // most on the sheet, a few lofted high
    float band = max(0.0, 1.0 - abs(dy - loft * SPRAY) / rw);
    // A second, independent value out of the same hash. Without it every dot peaks
    // at one brightness and the sheet reads as uniform grain rather than particles.
    float bright = (0.55 + 0.45 * fract(rnd.z * 13.7)) * (1.0 - 0.7 * loft);
    return vec2(cov * band * band * bright, cov * band);
}

vec4 puikit_bg_fragment(vec2 pos) {
    vec2 uv = pos.xy / resolution;
    float aspect = resolution.x / resolution.y;
    // Work in view-height units so the sheet keeps its proportions in any window.
    float px = (uv.x - 0.5) * aspect;
    float t = time;

    float density = 0.0;   // accumulated particle coverage
    float crest = 0.0;     // height of whatever contributed most, for colouring

    for (int i = 0; i < LAYERS; ++i) {
        float fi = (float(i) + 0.5) / float(LAYERS);
        // Even steps in 1/z are even steps on screen; stepping z directly would
        // pile the far half of the sheet onto a single line.
        float z = 1.0 / mix(1.0 / Z_NEAR, 1.0 / Z_FAR, fi);
        float layerFade = 1.0 - 0.55 * fi;

        // The projection, run backwards. Instead of placing a particle and asking
        // where it lands, ask what this pixel is looking at: at this depth the ray
        // crosses the sheet at wx, and only a particle at height py projects here.
        float wx = px * z / FOCAL;
        float py = CAM_H - (uv.y - HORIZON) * z / FOCAL;
        float h = surface(wx, z, t);

        // One pixel's width in world units at this depth, for the LOD widening.
        float lodPix = (z / FOCAL) / resolution.y;

        // Three octaves at unrelated frequencies, each rotating at its own rate.
        vec2 p = vec2(wx, z);
        float dy = py - h;
        vec2 a = splat(p, FREQ,         0.050 * t,         lodPix, dy);
        vec2 b = splat(p, FREQ * 1.70, -0.037 * t + 2.1,   lodPix, dy);
        vec2 c = splat(p, FREQ * 2.60,  0.021 * t + 4.7,   lodPix, dy);

        density += (a.x * 1.00 + b.x * 0.80 + c.x * 0.60) * layerFade;
        crest = max(crest, (a.y + b.y) * (0.5 + 0.5 * h / 0.6));
    }

    density = 1.0 - exp(-density * GAIN);   // saturating, so dense areas read solid

    // Colour: sweep the hue along the sheet and lift it toward white at the
    // crests. The two ends are the theme ink pushed apart in opposite directions
    // rather than fixed colours, so the gradient tracks whatever palette is
    // active while still spanning the violet-to-cyan range of the reference.
    vec3 violet = ink.rgb * vec3(1.00, 0.42, 1.30);
    vec3 cyan   = ink.rgb * vec3(0.34, 1.10, 1.18);
    float sweep = 0.5 + 0.5 * sin(uv.x * 3.1 + t * 0.25);
    vec3 tint = mix(violet, cyan, sweep);
    // Crests catch the light and pale out, which is what separates the leading
    // edge of the sheet from the mass behind it.
    vec3 rgb = mix(tint, vec3(1.0), clamp(crest * 1.9, 0.0, 1.0) * 0.7);

    rgb = mix(backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * opacity);
    return vec4(rgb, 1.0);
}
"""

#: Falling phosphor streaks — the terminal rain.
#:
#: Structure: the screen is divided into columns whose count follows the window
#: width, so the fall keeps its density at any size. Each column draws its streaks
#: at a fixed x, so a pixel only has to consider its own column and its two
#: neighbours (a streak near a column edge bleeds across one) — three cells,
#: regardless of how many columns the window holds. Within a column, a streak is a
#: span of length ``streakLen`` hanging *above* its head, and a pixel's place along
#: that span is one subtraction; there is no per-drop geometry to walk.
#:
#: ``rnd`` is the exact uint32 avalanche of ``_rand`` in the segment module this
#: scene replaces, so column placement, speed, length and brightness come out
#: identical — the rain falls in the same places, it is only painted differently.
#:
#: Two things the CPU renderer could not do. The tail is a continuous curve rather
#: than the 7 discrete alpha steps a stack of sub-segments had to quantise it into;
#: and the head pales toward white while the tail keeps the theme ink, which is the
#: hot-phosphor tip a single-colour stroke has no way to express.
RAIN_MSL = """
// --- tunables ---------------------------------------------------------------
constant float COLUMN_PX  = 26.0;   // nominal column width; the count follows width
constant float RATE       = 0.16;   // fraction of a full fall per second
constant int   DROPS      = 2;      // streaks per column, offset in phase
constant float LEN_MIN    = 0.10;   // streak length as a fraction of view height
constant float LEN_RANGE  = 0.22;
constant float WIDTH_PX   = 1.3;    // streak width in pixels
constant float TAIL_GAMMA = 1.7;    // >1 keeps the head crisp and the tail long
constant float HEAD_GLOW  = 0.55;   // how far the head pales toward white

// The integer avalanche hash from the segment scene, verbatim: the salt picks an
// independent draw for the same column, so placement and speed are uncorrelated.
// Integer ops are exact in both dialects, which is what makes the two renderers
// agree on where the rain falls.
static inline float rnd(uint index, uint salt) {
    uint x = index * 0x9E3779B1u + salt * 0x85EBCA77u;
    x ^= x >> 15;
    x *= 0x2C1B3C6Du;
    x ^= x >> 12;
    x *= 0x297A2D39u;
    x ^= x >> 15;
    return float(x) * (1.0 / 4294967296.0);
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float H = u.resolution.y;
    float columns = max(6.0, floor(u.resolution.x / COLUMN_PX));
    float colW = u.resolution.x / columns;

    float density = 0.0;   // accumulated streak coverage at this pixel
    float hot = 0.0;       // proximity to the brightest head, for the glow

    float c0 = floor(pos.x / colW);
    for (int n = -1; n <= 1; ++n) {
        float cf = c0 + float(n);
        uint ci = uint(int(cf));

        // Jitter x within the column so the fall is not a perfect comb.
        float x = (cf + 0.15 + rnd(ci, 1) * 0.7) * colW;
        float dx = abs(pos.x - x);
        // Nothing in this column can reach this pixel: skip its drops entirely.
        // Most pixels take this exit for all three columns, which is what keeps
        // the scene cheap at native resolution.
        if (dx > WIDTH_PX * 1.6) { continue; }

        float fall      = 0.55 + rnd(ci, 2);              // per-column speed
        float streakLen = (LEN_MIN + LEN_RANGE * rnd(ci, 3)) * H;
        float bright    = 0.45 + rnd(ci, 6) * 0.55;       // some columns stay faint
        // Antialiased across the streak's width — a hard test would shimmer as the
        // column's sub-pixel x drifts with the window size.
        float prof = 1.0 - smoothstep(WIDTH_PX * 0.5, WIDTH_PX * 1.6, dx);

        for (int d = 0; d < DROPS; ++d) {
            float phase = rnd(ci, 4u + uint(d));
            // Travel 0->1 walks the head from a streak's length above the view to
            // a streak's length below it, so the streak both enters already fully
            // formed and stays until its tail has cleared the bottom edge. Stopping
            // the head at H would wrap the drop while the tail still covered the
            // last streakLen of the screen, and the drop would blink out early.
            float travel = fract(u.time * RATE * fall + phase);
            float hy = travel * (H + 2.0 * streakLen) - streakLen;
            // Place this pixel along the streak: 0 at the head, 1 at the tail end.
            float k = (hy - pos.y) / streakLen;
            if (k < 0.0 || k > 1.0) { continue; }
            float a = pow(1.0 - k, TAIL_GAMMA) * bright * prof;
            density += a;
            hot = max(hot, a * (1.0 - k));
        }
    }

    float3 rgb = mix(u.ink.rgb, float3(1.0), clamp(hot, 0.0, 1.0) * HEAD_GLOW);
    rgb = mix(u.backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * u.opacity);
    return float4(rgb, 1.0);
}
"""

#: The HLSL translation of :data:`RAIN_MSL` (see :data:`WAVE_HLSL` for why a scene ships
#: both). Line-for-line; only the dialect differs — ``fract``/``mix`` become
#: ``frac``/``lerp``, ``constant`` becomes ``static const``, the uniforms are cbuffer
#: globals, and the hash constants are typed ``uint`` so the literals do not land in
#: a signed int. Keep the two in sync when tuning the scene.
RAIN_HLSL = """
// --- tunables (see RAIN_MSL for the rationale of each) -------------------
static const float COLUMN_PX  = 26.0;
static const float RATE       = 0.16;
static const int   DROPS      = 2;
static const float LEN_MIN    = 0.10;
static const float LEN_RANGE  = 0.22;
static const float WIDTH_PX   = 1.3;
static const float TAIL_GAMMA = 1.7;
static const float HEAD_GLOW  = 0.55;

static const uint HASH_K1 = 0x9E3779B1;
static const uint HASH_K2 = 0x85EBCA77;
static const uint HASH_K3 = 0x2C1B3C6D;
static const uint HASH_K4 = 0x297A2D39;

float rnd(uint index, uint salt) {
    uint x = index * HASH_K1 + salt * HASH_K2;
    x ^= x >> 15;
    x *= HASH_K3;
    x ^= x >> 12;
    x *= HASH_K4;
    x ^= x >> 15;
    return float(x) * (1.0 / 4294967296.0);
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float H = resolution.y;
    float columns = max(6.0, floor(resolution.x / COLUMN_PX));
    float colW = resolution.x / columns;

    float density = 0.0;
    float hot = 0.0;

    float c0 = floor(pos.x / colW);
    for (int n = -1; n <= 1; ++n) {
        float cf = c0 + float(n);
        uint ci = uint(int(cf));

        float x = (cf + 0.15 + rnd(ci, 1) * 0.7) * colW;
        float dx = abs(pos.x - x);
        if (dx > WIDTH_PX * 1.6) { continue; }

        float fall      = 0.55 + rnd(ci, 2);
        float streakLen = (LEN_MIN + LEN_RANGE * rnd(ci, 3)) * H;
        float bright    = 0.45 + rnd(ci, 6) * 0.55;
        float prof = 1.0 - smoothstep(WIDTH_PX * 0.5, WIDTH_PX * 1.6, dx);

        for (int d = 0; d < DROPS; ++d) {
            float phase = rnd(ci, 4 + (uint)d);
            float travel = frac(time * RATE * fall + phase);
            float hy = travel * (H + 2.0 * streakLen) - streakLen;
            float k = (hy - pos.y) / streakLen;
            if (k < 0.0 || k > 1.0) { continue; }
            float a = pow(1.0 - k, TAIL_GAMMA) * bright * prof;
            density += a;
            hot = max(hot, a * (1.0 - k));
        }
    }

    float3 rgb = lerp(ink.rgb, float3(1.0, 1.0, 1.0), clamp(hot, 0.0, 1.0) * HEAD_GLOW);
    rgb = lerp(backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * opacity);
    return float4(rgb, 1.0);
}
"""

RAIN_GLSL = """
// --- tunables ---------------------------------------------------------------
const float COLUMN_PX  = 26.0;   // nominal column width; the count follows width
const float RATE       = 0.16;   // fraction of a full fall per second
const int   DROPS      = 2;      // streaks per column, offset in phase
const float LEN_MIN    = 0.10;   // streak length as a fraction of view height
const float LEN_RANGE  = 0.22;
const float WIDTH_PX   = 1.3;    // streak width in pixels
const float TAIL_GAMMA = 1.7;    // >1 keeps the head crisp and the tail long
const float HEAD_GLOW  = 0.55;   // how far the head pales toward white

// The integer avalanche hash from the segment scene, verbatim: the salt picks an
// independent draw for the same column, so placement and speed are uncorrelated.
// Integer ops are exact in both dialects, which is what makes the two renderers
// agree on where the rain falls.
float rnd(uint index, uint salt) {
    uint x = index * 0x9E3779B1u + salt * 0x85EBCA77u;
    x ^= x >> 15;
    x *= 0x2C1B3C6Du;
    x ^= x >> 12;
    x *= 0x297A2D39u;
    x ^= x >> 15;
    return float(x) * (1.0 / 4294967296.0);
}

vec4 puikit_bg_fragment(vec2 pos) {
    float H = resolution.y;
    float columns = max(6.0, floor(resolution.x / COLUMN_PX));
    float colW = resolution.x / columns;

    float density = 0.0;   // accumulated streak coverage at this pixel
    float hot = 0.0;       // proximity to the brightest head, for the glow

    float c0 = floor(pos.x / colW);
    for (int n = -1; n <= 1; ++n) {
        float cf = c0 + float(n);
        uint ci = uint(int(cf));

        // Jitter x within the column so the fall is not a perfect comb.
        float x = (cf + 0.15 + rnd(ci, 1u) * 0.7) * colW;
        float dx = abs(pos.x - x);
        // Nothing in this column can reach this pixel: skip its drops entirely.
        // Most pixels take this exit for all three columns, which is what keeps
        // the scene cheap at native resolution.
        if (dx > WIDTH_PX * 1.6) { continue; }

        float fall      = 0.55 + rnd(ci, 2u);              // per-column speed
        float streakLen = (LEN_MIN + LEN_RANGE * rnd(ci, 3u)) * H;
        float bright    = 0.45 + rnd(ci, 6u) * 0.55;       // some columns stay faint
        // Antialiased across the streak's width — a hard test would shimmer as the
        // column's sub-pixel x drifts with the window size.
        float prof = 1.0 - smoothstep(WIDTH_PX * 0.5, WIDTH_PX * 1.6, dx);

        for (int d = 0; d < DROPS; ++d) {
            float phase = rnd(ci, 4u + uint(d));
            // Travel 0->1 walks the head from a streak's length above the view to
            // a streak's length below it, so the streak both enters already fully
            // formed and stays until its tail has cleared the bottom edge. Stopping
            // the head at H would wrap the drop while the tail still covered the
            // last streakLen of the screen, and the drop would blink out early.
            float travel = fract(time * RATE * fall + phase);
            float hy = travel * (H + 2.0 * streakLen) - streakLen;
            // Place this pixel along the streak: 0 at the head, 1 at the tail end.
            float k = (hy - pos.y) / streakLen;
            if (k < 0.0 || k > 1.0) { continue; }
            float a = pow(1.0 - k, TAIL_GAMMA) * bright * prof;
            density += a;
            hot = max(hot, a * (1.0 - k));
        }
    }

    vec3 rgb = mix(ink.rgb, vec3(1.0), clamp(hot, 0.0, 1.0) * HEAD_GLOW);
    rgb = mix(backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * opacity);
    return vec4(rgb, 1.0);
}
"""

#: Stars streaming toward the viewer, drawn as radial motion streaks.
#:
#: Structure: stars sit on a bounded plane in front of the camera and travel only in
#: depth; the perspective divide sweeps them outward from the centre and accelerates
#: them as they near. The plane is *bounded* — that is what gives the field a
#: vanishing point, since a far layer covers only the middle of the view and opens
#: outward as it approaches.
#:
#: The per-pixel inversion is the interesting part. A star at plane position ``s`` and
#: depth ``z`` lands at ``s/z`` in normalised coordinates, so a pixel can run that
#: backwards: at an assumed depth, ``s = n * z`` names the exact cell that could
#: cover it. Depth is sampled in layers — each layer a full grid of stars sharing one
#: depth, the layers evenly offset in phase so some are always near and some far. A
#: layer recycles when its depth wraps, which is invisible because the fade-in has it
#: at zero alpha exactly there.
#:
#: A streak spans a range of depths, so the covering star lies somewhere along the
#: pixel's ray between the plane radius of its head and that of its tail. For any
#: *on-screen* pixel that span works out to well under one cell, so sampling the two
#: ends brackets it — which is why this costs two lookups per layer and not a search.
STARFIELD_MSL = """
// --- tunables ---------------------------------------------------------------
constant int   LAYERS   = 10;     // depth samples; each is a full grid of stars
constant float Z_FAR    = 2.6;    // spawn depth. Above 1 so the far plane lands
                                  // inside the view rather than already filling it
constant float Z_NEAR   = 0.16;   // closest approach; the divide blows up at 0
constant float RATE     = 0.12;   // fraction of the depth range crossed per second
constant float TAIL     = 0.055;  // streak length, in depth -- constant in depth is
                                  // what makes the drawn streak lengthen as it nears
constant float FADE_IN  = 0.55;   // fraction of the travel spent fading in
constant float DENSITY  = 3.0;    // star cells per unit of plane
constant float DOT_PX   = 1.15;   // streak half-width, in pixels
constant float NEAR_GLOW = 0.6;   // how far the nearest stars pale toward white

static inline float hash11(float n) {
    n = fract(n * 0.1031);
    n *= n + 33.33;
    n *= n + n;
    return fract(n);
}
static inline float2 hash21(float2 p) {
    float3 v = fract(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xx + v.yz) * v.zy);
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float2 halfRes = u.resolution * 0.5;
    float2 P = pos.xy - halfRes;      // pixels from the centre
    float2 n = P / halfRes;           // normalised: +-1 at the view edges
    float span = Z_FAR - Z_NEAR;

    float density = 0.0;
    float near = 0.0;                 // depth of the closest contributor, for glow

    for (int i = 0; i < LAYERS; ++i) {
        // Layers evenly offset in phase, so the field always holds stars at every
        // stage of the journey rather than pulsing in unison.
        float travel = fract(u.time * RATE + float(i) / float(LAYERS));
        float alpha = min(1.0, travel / FADE_IN);
        if (alpha <= 0.0) { continue; }
        float z = Z_FAR - travel * span;
        float zt = min(Z_FAR, z + TAIL);

        // Bracket the ray: the covering star's plane radius lies between what its
        // head would need and what its tail would.
        for (int e = 0; e < 2; ++e) {
            float2 s = n * (e == 0 ? z : zt);
            float2 cell = floor(s * DENSITY);
            float2 j = hash21(cell + float2(float(i) * 17.0, float(i) * 31.0));
            float2 star = (cell + j) / DENSITY;
            if (abs(star.x) > 1.0 || abs(star.y) > 1.0) { continue; }

            float2 A = star * halfRes;    // the star's ray, in pixels
            float L = length(A);
            if (L < 1e-4) { continue; }
            float2 dir = A / L;
            // Point-to-segment: the streak runs from the tail (further, so nearer
            // the centre) out to the head.
            float along = clamp(dot(P, dir), L / zt, L / z);
            float d = length(P - dir * along);
            float q = max(0.0, 1.0 - d / DOT_PX);
            float splat = q * q;
            float bright = 0.55 + 0.45 * hash11(cell.x * 73.0 + cell.y * 149.0 + float(i));
            // max, not sum: the two bracket samples usually find the same star, and
            // adding them would double it.
            density = max(density, splat * alpha * bright);
            near = max(near, splat * (1.0 - z / Z_FAR));
        }
    }

    float3 rgb = mix(u.ink.rgb, float3(1.0), clamp(near, 0.0, 1.0) * NEAR_GLOW);
    rgb = mix(u.backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * u.opacity);
    return float4(rgb, 1.0);
}
"""

#: The HLSL translation of :data:`STARFIELD_MSL`. Line-for-line; only the dialect
#: differs. Keep the two in sync when tuning the scene.
STARFIELD_HLSL = """
// --- tunables (see STARFIELD_MSL for the rationale of each) ------------------
static const int   LAYERS    = 10;
static const float Z_FAR     = 2.6;
static const float Z_NEAR    = 0.16;
static const float RATE      = 0.12;
static const float TAIL      = 0.055;
static const float FADE_IN   = 0.55;
static const float DENSITY   = 3.0;
static const float DOT_PX    = 1.15;
static const float NEAR_GLOW = 0.6;

float hash11(float n) {
    n = frac(n * 0.1031);
    n *= n + 33.33;
    n *= n + n;
    return frac(n);
}
float2 hash21(float2 p) {
    float3 v = frac(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return frac((v.xx + v.yz) * v.zy);
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float2 halfRes = resolution * 0.5;
    float2 P = pos.xy - halfRes;
    float2 n = P / halfRes;
    float span = Z_FAR - Z_NEAR;

    float density = 0.0;
    float near = 0.0;

    for (int i = 0; i < LAYERS; ++i) {
        float travel = frac(time * RATE + float(i) / float(LAYERS));
        float alpha = min(1.0, travel / FADE_IN);
        if (alpha <= 0.0) { continue; }
        float z = Z_FAR - travel * span;
        float zt = min(Z_FAR, z + TAIL);

        for (int e = 0; e < 2; ++e) {
            float2 s = n * (e == 0 ? z : zt);
            float2 cell = floor(s * DENSITY);
            float2 j = hash21(cell + float2(float(i) * 17.0, float(i) * 31.0));
            float2 star = (cell + j) / DENSITY;
            if (abs(star.x) > 1.0 || abs(star.y) > 1.0) { continue; }

            float2 A = star * halfRes;
            float L = length(A);
            if (L < 1e-4) { continue; }
            float2 dir = A / L;
            float along = clamp(dot(P, dir), L / zt, L / z);
            float d = length(P - dir * along);
            float q = max(0.0, 1.0 - d / DOT_PX);
            float splat = q * q;
            float bright = 0.55 + 0.45 * hash11(cell.x * 73.0 + cell.y * 149.0 + float(i));
            density = max(density, splat * alpha * bright);
            near = max(near, splat * (1.0 - z / Z_FAR));
        }
    }

    float3 rgb = lerp(ink.rgb, float3(1.0, 1.0, 1.0), clamp(near, 0.0, 1.0) * NEAR_GLOW);
    rgb = lerp(backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * opacity);
    return float4(rgb, 1.0);
}
"""

STARFIELD_GLSL = """
// --- tunables ---------------------------------------------------------------
const int   LAYERS   = 10;     // depth samples; each is a full grid of stars
const float Z_FAR    = 2.6;    // spawn depth. Above 1 so the far plane lands
                                  // inside the view rather than already filling it
const float Z_NEAR   = 0.16;   // closest approach; the divide blows up at 0
const float RATE     = 0.12;   // fraction of the depth range crossed per second
const float TAIL     = 0.055;  // streak length, in depth -- const in depth is
                                  // what makes the drawn streak lengthen as it nears
const float FADE_IN  = 0.55;   // fraction of the travel spent fading in
const float DENSITY  = 3.0;    // star cells per unit of plane
const float DOT_PX   = 1.15;   // streak half-width, in pixels
const float NEAR_GLOW = 0.6;   // how far the nearest stars pale toward white

float hash11(float n) {
    n = fract(n * 0.1031);
    n *= n + 33.33;
    n *= n + n;
    return fract(n);
}
vec2 hash21(vec2 p) {
    vec3 v = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xx + v.yz) * v.zy);
}

vec4 puikit_bg_fragment(vec2 pos) {
    vec2 halfRes = resolution * 0.5;
    vec2 P = pos.xy - halfRes;      // pixels from the centre
    vec2 n = P / halfRes;           // normalised: +-1 at the view edges
    float span = Z_FAR - Z_NEAR;

    float density = 0.0;
    float near = 0.0;                 // depth of the closest contributor, for glow

    for (int i = 0; i < LAYERS; ++i) {
        // Layers evenly offset in phase, so the field always holds stars at every
        // stage of the journey rather than pulsing in unison.
        float travel = fract(time * RATE + float(i) / float(LAYERS));
        float alpha = min(1.0, travel / FADE_IN);
        if (alpha <= 0.0) { continue; }
        float z = Z_FAR - travel * span;
        float zt = min(Z_FAR, z + TAIL);

        // Bracket the ray: the covering star's plane radius lies between what its
        // head would need and what its tail would.
        for (int e = 0; e < 2; ++e) {
            vec2 s = n * (e == 0 ? z : zt);
            vec2 cell = floor(s * DENSITY);
            vec2 j = hash21(cell + vec2(float(i) * 17.0, float(i) * 31.0));
            vec2 star = (cell + j) / DENSITY;
            if (abs(star.x) > 1.0 || abs(star.y) > 1.0) { continue; }

            vec2 A = star * halfRes;    // the star's ray, in pixels
            float L = length(A);
            if (L < 1e-4) { continue; }
            vec2 dir = A / L;
            // Point-to-segment: the streak runs from the tail (further, so nearer
            // the centre) out to the head.
            float along = clamp(dot(P, dir), L / zt, L / z);
            float d = length(P - dir * along);
            float q = max(0.0, 1.0 - d / DOT_PX);
            float splat = q * q;
            float bright = 0.55 + 0.45 * hash11(cell.x * 73.0 + cell.y * 149.0 + float(i));
            // max, not sum: the two bracket samples usually find the same star, and
            // adding them would double it.
            density = max(density, splat * alpha * bright);
            near = max(near, splat * (1.0 - z / Z_FAR));
        }
    }

    vec3 rgb = mix(ink.rgb, vec3(1.0), clamp(near, 0.0, 1.0) * NEAR_GLOW);
    rgb = mix(backdrop.rgb, rgb, clamp(density, 0.0, 1.0) * opacity);
    return vec4(rgb, 1.0);
}
"""

#: A rectangular grid corridor with the camera flying through it.
#:
#: This scene is genuinely 3D, and it is the one the per-pixel form suits *better*
#: than segments did. The CPU version placed world points on the four walls, pushed
#: them through a moving camera and stroked the resulting polyline; here the same
#: transform is simply run backwards. Each pixel recovers its own view ray, meets
#: the corridor analytically — the corridor is a box around the camera, so exactly
#: one of the four walls is hit — and asks the grid at that point how close the
#: nearest line is. No geometry is generated at all.
#:
#: What that buys, beyond cost: line width is filtered by the screen-space
#: derivative, so a rail stays a crisp constant width all the way to the vanishing
#: point instead of aliasing into a dotted crawl, and where the grid finally packs
#: tighter than a pixel it fades out rather than boiling into a wash. The camera
#: sway, ring spacing and depth fade are the segment scene's, unchanged.
GRID_MSL = """
// --- tunables ---------------------------------------------------------------
constant float RING_SPACING = 0.5;   // world distance between rings
constant float Z_NEAR       = 0.28;  // depth window actually drawn. NEAR is close
constant float Z_FAR        = 9.0;   // on purpose; FAR is where the fade reaches 0
constant float HALF_H       = 1.0;   // corridor half-height; half-width follows aspect
constant float FORWARD      = 0.35;  // world units travelled per second
constant float FADE_GAMMA   = 1.2;   // >1 holds the near/middle bright
constant float RAILS_V      = 5.0;   // rails up the side walls
constant float RAILS_H_MAX  = 12.0;  // cap on floor/ceiling rails in a wide window
constant float CAM_DRIFT_X  = 0.30;  // sway amplitudes, world units and radians
constant float CAM_DRIFT_Y  = 0.18;
constant float CAM_YAW      = 0.10;
constant float CAM_PITCH    = 0.07;
constant float RATE_X       = 0.037; // sway rates, cycles/sec. Mutually
constant float RATE_Y       = 0.029; // incommensurate -- periods of ~27, 34, 43
constant float RATE_YAW     = 0.023; // and 53s -- so the motion never reads as
constant float RATE_PITCH   = 0.019; // a loop
constant float LINE_PX      = 1.1;   // grid line width, in pixels
constant float NEAR_GLOW    = 0.35;  // how far near geometry pales toward white
constant float BRIGHTNESS   = 0.5;   // how far a lit line gets toward full ink
constant float TAU          = 6.283185307;

// A grid line as coverage rather than a hit test. `p` is a coordinate that reaches
// an integer on every line, so the distance to the nearest one is |p - round(p)|.
// fwidth gives how far p moves per pixel, which is what converts a width in pixels
// into the right threshold *and* antialiases the edge -- the whole reason a line
// stays crisp into the distance here. Past the point where one pixel spans a whole
// period the grid can no longer be resolved, so it fades out instead of turning
// into a solid wash.
static inline float grid_line(float p) {
    float w = max(fwidth(p), 1e-5);
    float halfWidth = LINE_PX * 0.5 * w;
    float d = abs(p - round(p));
    float m = 1.0 - smoothstep(halfWidth, halfWidth + w, d);
    return m * (1.0 - smoothstep(0.25, 0.6, w));
}

static inline float depth_fade(float depth) {
    float f = (Z_FAR - depth) / (Z_FAR - Z_NEAR);
    return pow(clamp(f, 0.0, 1.0), FADE_GAMMA);
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float2 halfRes = u.resolution * 0.5;
    float focal = halfRes.y;
    float halfH = HALF_H;
    float halfW = HALF_H * (u.resolution.x / u.resolution.y);
    float t = u.time;

    float camX  = CAM_DRIFT_X * sin(t * RATE_X * TAU);
    float camY  = CAM_DRIFT_Y * sin(t * RATE_Y * TAU + 1.7);
    float yaw   = CAM_YAW * sin(t * RATE_YAW * TAU + 0.6);
    float pitch = CAM_PITCH * sin(t * RATE_PITCH * TAU + 2.4);
    float camZ  = t * FORWARD;

    // This pixel's view ray, rotated back onto the world axes: the inverse of the
    // yaw-then-pitch the scene is viewed through.
    float2 P = pos.xy - halfRes;
    float cy = cos(yaw), sy = sin(yaw);
    float cp = cos(pitch), sp = sin(pitch);
    float rx = P.x / focal, ry = P.y / focal;
    float z1 = -ry * sp + cp;
    float dy =  ry * cp + sp;
    float dx =  rx * cy + z1 * sy;
    float dz = -rx * sy + z1 * cy;

    // Meet the nearest wall. Everything below stays branch-free of the derivative
    // calls: fwidth is undefined under non-uniform control flow, and the corridor
    // corners are exactly where neighbouring pixels would disagree.
    float tx = 1e9, ty = 1e9;
    if (abs(dx) > 1e-6) { tx = ((dx > 0.0 ? halfW : -halfW) - camX) / dx; }
    if (abs(dy) > 1e-6) { ty = ((dy > 0.0 ? halfH : -halfH) - camY) / dy; }
    bool sideWall = tx < ty;
    float s = clamp(min(tx, ty), 0.0, 1e6);
    float depth = s * dz;

    float visible = (dz > 1e-4 && depth >= Z_NEAR && depth <= Z_FAR) ? 1.0 : 0.0;

    // Rings sit at fixed world z, so relative to the moving camera their parameter
    // is depth/spacing offset by how far through a cell the camera has travelled --
    // which makes the recycling seamless by construction.
    float ring = depth / RING_SPACING + fract(camZ / RING_SPACING);

    // Rails: floor/ceiling carry lanes across the width, the side walls up the
    // height. The count follows the corridor's aspect so cells stay roughly square.
    float railsH = max(2.0, min(RAILS_H_MAX, round(RAILS_V * halfW / halfH)));
    float wx = camX + s * dx;
    float wy = camY + s * dy;
    // Both walls' rails are evaluated for every pixel and only *then* selected.
    // Putting the grid_line calls inside the branch instead makes their fwidth
    // conditional, and the corridor corners -- the one place neighbouring pixels
    // disagree about which wall they hit -- come out as dashed lines.
    float mSide = grid_line((wy + halfH) / (2.0 * halfH / RAILS_V));
    float mFloor = grid_line((wx + halfW) / (2.0 * halfW / railsH));
    float mRail = sideWall ? mSide : mFloor;

    float lit = max(grid_line(ring), mRail) * depth_fade(depth) * visible;

    float3 rgb = mix(u.ink.rgb, float3(1.0),
                     clamp(1.0 - depth / Z_FAR, 0.0, 1.0) * NEAR_GLOW);
    rgb = mix(u.backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * BRIGHTNESS * u.opacity);
    return float4(rgb, 1.0);
}
"""

#: The HLSL translation of :data:`GRID_MSL`. Line-for-line; only the dialect differs.
#: Keep the two in sync when tuning the scene.
GRID_HLSL = """
// --- tunables (see GRID_MSL for the rationale of each) -----------------------
static const float RING_SPACING = 0.5;
static const float Z_NEAR       = 0.28;
static const float Z_FAR        = 9.0;
static const float HALF_H       = 1.0;
static const float FORWARD      = 0.35;
static const float FADE_GAMMA   = 1.2;
static const float RAILS_V      = 5.0;
static const float RAILS_H_MAX  = 12.0;
static const float CAM_DRIFT_X  = 0.30;
static const float CAM_DRIFT_Y  = 0.18;
static const float CAM_YAW      = 0.10;
static const float CAM_PITCH    = 0.07;
static const float RATE_X       = 0.037;
static const float RATE_Y       = 0.029;
static const float RATE_YAW     = 0.023;
static const float RATE_PITCH   = 0.019;
static const float LINE_PX      = 1.1;
static const float NEAR_GLOW    = 0.35;
static const float BRIGHTNESS   = 0.5;
static const float TAU          = 6.283185307;

float grid_line(float p) {
    float w = max(fwidth(p), 1e-5);
    float halfWidth = LINE_PX * 0.5 * w;
    float d = abs(p - round(p));
    float m = 1.0 - smoothstep(halfWidth, halfWidth + w, d);
    return m * (1.0 - smoothstep(0.25, 0.6, w));
}

float depth_fade(float depth) {
    float f = (Z_FAR - depth) / (Z_FAR - Z_NEAR);
    return pow(saturate(f), FADE_GAMMA);
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float2 halfRes = resolution * 0.5;
    float focal = halfRes.y;
    float halfH = HALF_H;
    float halfW = HALF_H * (resolution.x / resolution.y);
    float t = time;

    float camX  = CAM_DRIFT_X * sin(t * RATE_X * TAU);
    float camY  = CAM_DRIFT_Y * sin(t * RATE_Y * TAU + 1.7);
    float yaw   = CAM_YAW * sin(t * RATE_YAW * TAU + 0.6);
    float pitch = CAM_PITCH * sin(t * RATE_PITCH * TAU + 2.4);
    float camZ  = t * FORWARD;

    float2 P = pos.xy - halfRes;
    float cy = cos(yaw), sy = sin(yaw);
    float cp = cos(pitch), sp = sin(pitch);
    float rx = P.x / focal, ry = P.y / focal;
    float z1 = -ry * sp + cp;
    float dy =  ry * cp + sp;
    float dx =  rx * cy + z1 * sy;
    float dz = -rx * sy + z1 * cy;

    float tx = 1e9, ty = 1e9;
    if (abs(dx) > 1e-6) { tx = ((dx > 0.0 ? halfW : -halfW) - camX) / dx; }
    if (abs(dy) > 1e-6) { ty = ((dy > 0.0 ? halfH : -halfH) - camY) / dy; }
    bool sideWall = tx < ty;
    float s = clamp(min(tx, ty), 0.0, 1e6);
    float depth = s * dz;

    float visible = (dz > 1e-4 && depth >= Z_NEAR && depth <= Z_FAR) ? 1.0 : 0.0;

    float ring = depth / RING_SPACING + frac(camZ / RING_SPACING);

    float railsH = max(2.0, min(RAILS_H_MAX, round(RAILS_V * halfW / halfH)));
    float wx = camX + s * dx;
    float wy = camY + s * dy;
    // See the MSL twin: evaluating both before the select keeps fwidth uniform.
    float mSide = grid_line((wy + halfH) / (2.0 * halfH / RAILS_V));
    float mFloor = grid_line((wx + halfW) / (2.0 * halfW / railsH));
    float mRail = sideWall ? mSide : mFloor;

    float lit = max(grid_line(ring), mRail) * depth_fade(depth) * visible;

    float3 rgb = lerp(ink.rgb, float3(1.0, 1.0, 1.0),
                      saturate(1.0 - depth / Z_FAR) * NEAR_GLOW);
    rgb = lerp(backdrop.rgb, rgb, saturate(lit) * BRIGHTNESS * opacity);
    return float4(rgb, 1.0);
}
"""

GRID_GLSL = """
// --- tunables ---------------------------------------------------------------
const float RING_SPACING = 0.5;   // world distance between rings
const float Z_NEAR       = 0.28;  // depth window actually drawn. NEAR is close
const float Z_FAR        = 9.0;   // on purpose; FAR is where the fade reaches 0
const float HALF_H       = 1.0;   // corridor half-height; half-width follows aspect
const float FORWARD      = 0.35;  // world units travelled per second
const float FADE_GAMMA   = 1.2;   // >1 holds the near/middle bright
const float RAILS_V      = 5.0;   // rails up the side walls
const float RAILS_H_MAX  = 12.0;  // cap on floor/ceiling rails in a wide window
const float CAM_DRIFT_X  = 0.30;  // sway amplitudes, world units and radians
const float CAM_DRIFT_Y  = 0.18;
const float CAM_YAW      = 0.10;
const float CAM_PITCH    = 0.07;
const float RATE_X       = 0.037; // sway rates, cycles/sec. Mutually
const float RATE_Y       = 0.029; // incommensurate -- periods of ~27, 34, 43
const float RATE_YAW     = 0.023; // and 53s -- so the motion never reads as
const float RATE_PITCH   = 0.019; // a loop
const float LINE_PX      = 1.1;   // grid line width, in pixels
const float NEAR_GLOW    = 0.35;  // how far near geometry pales toward white
const float BRIGHTNESS   = 0.5;   // how far a lit line gets toward full ink
const float TAU          = 6.283185307;

// A grid line as coverage rather than a hit test. `p` is a coordinate that reaches
// an integer on every line, so the distance to the nearest one is |p - round(p)|.
// fwidth gives how far p moves per pixel, which is what converts a width in pixels
// into the right threshold *and* antialiases the edge -- the whole reason a line
// stays crisp into the distance here. Past the point where one pixel spans a whole
// period the grid can no longer be resolved, so it fades out instead of turning
// into a solid wash.
float grid_line(float p) {
    float w = max(fwidth(p), 1e-5);
    float halfWidth = LINE_PX * 0.5 * w;
    float d = abs(p - round(p));
    float m = 1.0 - smoothstep(halfWidth, halfWidth + w, d);
    return m * (1.0 - smoothstep(0.25, 0.6, w));
}

float depth_fade(float depth) {
    float f = (Z_FAR - depth) / (Z_FAR - Z_NEAR);
    return pow(clamp(f, 0.0, 1.0), FADE_GAMMA);
}

vec4 puikit_bg_fragment(vec2 pos) {
    vec2 halfRes = resolution * 0.5;
    float focal = halfRes.y;
    float halfH = HALF_H;
    float halfW = HALF_H * (resolution.x / resolution.y);
    float t = time;

    float camX  = CAM_DRIFT_X * sin(t * RATE_X * TAU);
    float camY  = CAM_DRIFT_Y * sin(t * RATE_Y * TAU + 1.7);
    float yaw   = CAM_YAW * sin(t * RATE_YAW * TAU + 0.6);
    float pitch = CAM_PITCH * sin(t * RATE_PITCH * TAU + 2.4);
    float camZ  = t * FORWARD;

    // This pixel's view ray, rotated back onto the world axes: the inverse of the
    // yaw-then-pitch the scene is viewed through.
    vec2 P = pos.xy - halfRes;
    float cy = cos(yaw), sy = sin(yaw);
    float cp = cos(pitch), sp = sin(pitch);
    float rx = P.x / focal, ry = P.y / focal;
    float z1 = -ry * sp + cp;
    float dy =  ry * cp + sp;
    float dx =  rx * cy + z1 * sy;
    float dz = -rx * sy + z1 * cy;

    // Meet the nearest wall. Everything below stays branch-free of the derivative
    // calls: fwidth is undefined under non-uniform control flow, and the corridor
    // corners are exactly where neighbouring pixels would disagree.
    float tx = 1e9, ty = 1e9;
    if (abs(dx) > 1e-6) { tx = ((dx > 0.0 ? halfW : -halfW) - camX) / dx; }
    if (abs(dy) > 1e-6) { ty = ((dy > 0.0 ? halfH : -halfH) - camY) / dy; }
    bool sideWall = tx < ty;
    float s = clamp(min(tx, ty), 0.0, 1e6);
    float depth = s * dz;

    float visible = (dz > 1e-4 && depth >= Z_NEAR && depth <= Z_FAR) ? 1.0 : 0.0;

    // Rings sit at fixed world z, so relative to the moving camera their parameter
    // is depth/spacing offset by how far through a cell the camera has travelled --
    // which makes the recycling seamless by construction.
    float ring = depth / RING_SPACING + fract(camZ / RING_SPACING);

    // Rails: floor/ceiling carry lanes across the width, the side walls up the
    // height. The count follows the corridor's aspect so cells stay roughly square.
    float railsH = max(2.0, min(RAILS_H_MAX, round(RAILS_V * halfW / halfH)));
    float wx = camX + s * dx;
    float wy = camY + s * dy;
    // Both walls' rails are evaluated for every pixel and only *then* selected.
    // Putting the grid_line calls inside the branch instead makes their fwidth
    // conditional, and the corridor corners -- the one place neighbouring pixels
    // disagree about which wall they hit -- come out as dashed lines.
    float mSide = grid_line((wy + halfH) / (2.0 * halfH / RAILS_V));
    float mFloor = grid_line((wx + halfW) / (2.0 * halfW / railsH));
    float mRail = sideWall ? mSide : mFloor;

    float lit = max(grid_line(ring), mRail) * depth_fade(depth) * visible;

    vec3 rgb = mix(ink.rgb, vec3(1.0),
                     clamp(1.0 - depth / Z_FAR, 0.0, 1.0) * NEAR_GLOW);
    rgb = mix(backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * BRIGHTNESS * opacity);
    return vec4(rgb, 1.0);
}
"""

#: Drifting nodes linked to their near neighbours, edges fading with distance.
#:
#: This is the scene that fought the per-pixel form hardest, and the one place the
#: port is a *reinterpretation* rather than a translation. Its identity is global
#: nearest-neighbour topology — which pairs are linked depends on where every node
#: is — and that is exactly what a shader, asked about one pixel at a time, cannot
#: survey. So the field is rebuilt on a grid: one node per cell, its position and
#: motion hashed from the cell index.
#:
#: The cell is sized so the link radius spans a little over one cell
#: (:data:`LINK_CELLS`). That ratio is load-bearing in both directions. Too large and
#: every node links to everything nearby; too small — a cell *equal* to the link
#: radius, the obvious first choice — and a regular grid puts every neighbour at
#: almost exactly the link distance, where the distance falloff sends the edge to
#: zero alpha and the net renders as bare dots. At 1.4 cells a typical neighbour sits
#: at ~0.7 of the radius, so edges are actually visible and the orbits below spread
#: the rest across the falloff.
#:
#: That ratio also bounds the search: an edge reaches at most 1.4 cells, so for any
#: pixel an edge crosses, both endpoints lie within a link of it and therefore inside
#: the 5x5 block around it. Cells whose nearest corner is already out of range are
#: rejected before their node is even evaluated, so the usual cost is far below the
#: 25 that bound allows.
#:
#: What changed, deliberately. The CPU scene drifted nodes in straight lines that
#: wrapped at the view border; a wrapping node cannot stay in the cell that owns it,
#: and the cell is how a pixel finds it. So a node orbits inside its own cell
#: instead — a circle at constant angular speed, with its own radius, rate and
#: handedness. That directly answers the objection the original raised against
#: sinusoidal paths: a sine dwells at its turning points and piles nodes up, while a
#: circle traversed at constant speed has no turning points and is uniform in time.
#: The character survives (a calm net, drifting, edges dissolving as nodes part);
#: what is gone is a node crossing the entire window over half a minute.
CONSTELLATION_MSL = """
// --- tunables ---------------------------------------------------------------
constant float CELL_FRACTION = 0.16;  // cell size as a fraction of the short side;
                                      // this is what sets how many nodes there are
constant float LINK_CELLS    = 1.4;   // link radius, in cells -- see the note above
constant float DRIFT_RATE    = 0.035; // orbit rate, cycles/sec
constant float EDGE_FADE     = 0.10;  // border fade width, fraction of the view
constant float ORBIT_MIN     = 0.15;  // orbit radius range, in cells. Varying it is
constant float ORBIT_RANGE   = 0.30;  // what stops the cells reading as a lattice
constant float NODE_PX       = 1.7;   // node dot radius, pixels
constant float LINE_PX       = 1.0;   // edge half-width, pixels
constant float EDGE_ALPHA    = 0.5;   // edges stay clearly secondary to the nodes
constant float NODE_ALPHA    = 0.85;
constant float NODE_GLOW     = 0.45;  // how far a node core pales toward white
constant float NEAR_SPAN     = 0.5;   // distance, in cells, at which an edge is at
                                      // full strength -- see the falloff note below
constant float TAU           = 6.283185307;

static inline float2 hash21(float2 p) {
    float3 v = fract(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xx + v.yz) * v.zy);
}

// Fade to nothing at the view border, so the net dissolves into the edges of the
// window instead of being cut off by them.
static inline float border_fade(float a) {
    return clamp(min(a, 1.0 - a) / EDGE_FADE, 0.0, 1.0);
}

// A node stays inside the cell that owns it -- that is what lets a pixel find it by
// index at all. A circle at constant angular speed, so the motion is uniform in
// time and never dwells; radius, rate and handedness all come from the cell.
static inline float2 node_at(float2 cell, float cellPx, float t) {
    float2 h = hash21(cell);
    float2 g = hash21(cell + 37.0);
    float radius = ORBIT_MIN + ORBIT_RANGE * h.x;
    float rate = DRIFT_RATE * (0.6 + 0.8 * h.y);
    float spin = (g.x < 0.5) ? -1.0 : 1.0;
    float ang = spin * t * TAU * rate + g.y * TAU;
    return (cell + 0.5 + float2(cos(ang), sin(ang)) * radius) * cellPx;
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float cellPx = CELL_FRACTION * min(u.resolution.x, u.resolution.y);
    float link = LINK_CELLS * cellPx;
    float2 base = floor(pos.xy / cellPx);

    float2 nodes[25];
    float  fades[25];
    int k = 0;
    for (int oy = -2; oy <= 2; ++oy) {
        for (int ox = -2; ox <= 2; ++ox) {
            float2 cell = base + float2(float(ox), float(oy));
            // Reject on the cell's bounds before evaluating its node: the corners of
            // the 5x5 are always out of range, and this skips their trig entirely.
            float2 lo = cell * cellPx;
            float2 far = max(max(lo - pos.xy, pos.xy - (lo + cellPx)), float2(0.0));
            if (dot(far, far) > link * link) {
                nodes[k] = float2(0.0);
                fades[k] = 0.0;
                k++;
                continue;
            }
            float2 p = node_at(cell, cellPx, u.time);
            nodes[k] = p;
            float2 nrm = p / u.resolution;
            fades[k] = border_fade(nrm.x) * border_fade(nrm.y);
            k++;
        }
    }

    float lit = 0.0;   // coverage at this pixel
    float hot = 0.0;   // node cores only, for the glow

    for (int a = 0; a < 25; ++a) {
        float fa = fades[a];
        if (fa <= 0.0) { continue; }
        float2 pa = nodes[a];
        float da = length(pos.xy - pa);
        // Only a node within one link of this pixel can put an edge across it: a
        // pixel on an edge lies between its ends, so it is within `len` of both.
        // The inner loop runs over every other node (not just b > a), which is what
        // keeps this prune from dropping an edge whose far end is out of range.
        if (da >= link) { continue; }

        float q = max(0.0, 1.0 - da / NODE_PX);
        float dot_ = q * q * fa;
        hot = max(hot, dot_);
        lit = max(lit, dot_ * NODE_ALPHA);

        for (int b = 0; b < 25; ++b) {
            if (b == a) { continue; }
            float fb = fades[b];
            if (fb <= 0.0) { continue; }
            float2 e = nodes[b] - pa;
            float len = length(e);
            if (len >= link || len < 1e-4) { continue; }
            float2 dir = e / len;
            float along = clamp(dot(pos.xy - pa, dir), 0.0, len);
            float d = length(pos.xy - pa - dir * along);
            float m = max(0.0, 1.0 - d / LINE_PX);
            if (m <= 0.0) { continue; }
            // Falloff measured against the *cell spacing*, not the link radius. The
            // CPU scene scattered its nodes at random, so plenty of pairs sat well
            // inside the radius and a falloff over the full radius gave a usable
            // spread. On a grid every neighbour is about one cell away, so that same
            // falloff drops them all to the same near-zero alpha and the net renders
            // as bare dots. Anchoring full strength at half a cell restores the range.
            float f = clamp((link - len) / (link - cellPx * NEAR_SPAN), 0.0, 1.0);
            lit = max(lit, m * m * f * EDGE_ALPHA * fa * fb);
        }
    }

    float3 rgb = mix(u.ink.rgb, float3(1.0), clamp(hot, 0.0, 1.0) * NODE_GLOW);
    rgb = mix(u.backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * u.opacity);
    return float4(rgb, 1.0);
}
"""

#: The HLSL translation of :data:`CONSTELLATION_MSL`. Line-for-line; only the dialect
#: differs. Keep the two in sync when tuning the scene.
CONSTELLATION_HLSL = """
// --- tunables (see CONSTELLATION_MSL for the rationale of each) --------------
static const float CELL_FRACTION = 0.16;
static const float LINK_CELLS    = 1.4;
static const float DRIFT_RATE    = 0.035;
static const float EDGE_FADE     = 0.10;
static const float ORBIT_MIN     = 0.15;
static const float ORBIT_RANGE   = 0.30;
static const float NODE_PX       = 1.7;
static const float LINE_PX       = 1.0;
static const float EDGE_ALPHA    = 0.5;
static const float NODE_ALPHA    = 0.85;
static const float NODE_GLOW     = 0.45;
static const float NEAR_SPAN     = 0.5;
static const float TAU           = 6.283185307;

float2 hash21(float2 p) {
    float3 v = frac(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return frac((v.xx + v.yz) * v.zy);
}

float border_fade(float a) {
    return saturate(min(a, 1.0 - a) / EDGE_FADE);
}

float2 node_at(float2 cell, float cellPx, float t) {
    float2 h = hash21(cell);
    float2 g = hash21(cell + 37.0);
    float radius = ORBIT_MIN + ORBIT_RANGE * h.x;
    float rate = DRIFT_RATE * (0.6 + 0.8 * h.y);
    float spin = (g.x < 0.5) ? -1.0 : 1.0;
    float ang = spin * t * TAU * rate + g.y * TAU;
    return (cell + 0.5 + float2(cos(ang), sin(ang)) * radius) * cellPx;
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float cellPx = CELL_FRACTION * min(resolution.x, resolution.y);
    float link = LINK_CELLS * cellPx;
    float2 base = floor(pos.xy / cellPx);

    float2 nodes[25];
    float  fades[25];
    int k = 0;
    for (int oy = -2; oy <= 2; ++oy) {
        for (int ox = -2; ox <= 2; ++ox) {
            float2 cell = base + float2(float(ox), float(oy));
            float2 lo = cell * cellPx;
            float2 far = max(max(lo - pos.xy, pos.xy - (lo + cellPx)), float2(0.0, 0.0));
            if (dot(far, far) > link * link) {
                nodes[k] = float2(0.0, 0.0);
                fades[k] = 0.0;
                k++;
                continue;
            }
            float2 p = node_at(cell, cellPx, time);
            nodes[k] = p;
            float2 nrm = p / resolution;
            fades[k] = border_fade(nrm.x) * border_fade(nrm.y);
            k++;
        }
    }

    float lit = 0.0;
    float hot = 0.0;

    for (int a = 0; a < 25; ++a) {
        float fa = fades[a];
        if (fa <= 0.0) { continue; }
        float2 pa = nodes[a];
        float da = length(pos.xy - pa);
        if (da >= link) { continue; }

        float q = max(0.0, 1.0 - da / NODE_PX);
        float dotv = q * q * fa;
        hot = max(hot, dotv);
        lit = max(lit, dotv * NODE_ALPHA);

        for (int b = 0; b < 25; ++b) {
            if (b == a) { continue; }
            float fb = fades[b];
            if (fb <= 0.0) { continue; }
            float2 e = nodes[b] - pa;
            float len = length(e);
            if (len >= link || len < 1e-4) { continue; }
            float2 dir = e / len;
            float along = clamp(dot(pos.xy - pa, dir), 0.0, len);
            float d = length(pos.xy - pa - dir * along);
            float m = max(0.0, 1.0 - d / LINE_PX);
            if (m <= 0.0) { continue; }
            float f = saturate((link - len) / (link - cellPx * NEAR_SPAN));
            lit = max(lit, m * m * f * EDGE_ALPHA * fa * fb);
        }
    }

    float3 rgb = lerp(ink.rgb, float3(1.0, 1.0, 1.0), saturate(hot) * NODE_GLOW);
    rgb = lerp(backdrop.rgb, rgb, saturate(lit) * opacity);
    return float4(rgb, 1.0);
}
"""

CONSTELLATION_GLSL = """
// --- tunables ---------------------------------------------------------------
const float CELL_FRACTION = 0.16;  // cell size as a fraction of the short side;
                                      // this is what sets how many nodes there are
const float LINK_CELLS    = 1.4;   // link radius, in cells -- see the note above
const float DRIFT_RATE    = 0.035; // orbit rate, cycles/sec
const float EDGE_FADE     = 0.10;  // border fade width, fraction of the view
const float ORBIT_MIN     = 0.15;  // orbit radius range, in cells. Varying it is
const float ORBIT_RANGE   = 0.30;  // what stops the cells reading as a lattice
const float NODE_PX       = 1.7;   // node dot radius, pixels
const float LINE_PX       = 1.0;   // edge half-width, pixels
const float EDGE_ALPHA    = 0.5;   // edges stay clearly secondary to the nodes
const float NODE_ALPHA    = 0.85;
const float NODE_GLOW     = 0.45;  // how far a node core pales toward white
const float NEAR_SPAN     = 0.5;   // distance, in cells, at which an edge is at
                                      // full strength -- see the falloff note below
const float TAU           = 6.283185307;

vec2 hash21(vec2 p) {
    vec3 v = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xx + v.yz) * v.zy);
}

// Fade to nothing at the view border, so the net dissolves into the edges of the
// window instead of being cut off by them.
float border_fade(float a) {
    return clamp(min(a, 1.0 - a) / EDGE_FADE, 0.0, 1.0);
}

// A node stays inside the cell that owns it -- that is what lets a pixel find it by
// index at all. A circle at const angular speed, so the motion is uniform in
// time and never dwells; radius, rate and handedness all come from the cell.
vec2 node_at(vec2 cell, float cellPx, float t) {
    vec2 h = hash21(cell);
    vec2 g = hash21(cell + 37.0);
    float radius = ORBIT_MIN + ORBIT_RANGE * h.x;
    float rate = DRIFT_RATE * (0.6 + 0.8 * h.y);
    float spin = (g.x < 0.5) ? -1.0 : 1.0;
    float ang = spin * t * TAU * rate + g.y * TAU;
    return (cell + 0.5 + vec2(cos(ang), sin(ang)) * radius) * cellPx;
}

vec4 puikit_bg_fragment(vec2 pos) {
    float cellPx = CELL_FRACTION * min(resolution.x, resolution.y);
    float link = LINK_CELLS * cellPx;
    vec2 base = floor(pos.xy / cellPx);

    vec2 nodes[25];
    float  fades[25];
    int k = 0;
    for (int oy = -2; oy <= 2; ++oy) {
        for (int ox = -2; ox <= 2; ++ox) {
            vec2 cell = base + vec2(float(ox), float(oy));
            // Reject on the cell's bounds before evaluating its node: the corners of
            // the 5x5 are always out of range, and this skips their trig entirely.
            vec2 lo = cell * cellPx;
            vec2 far = max(max(lo - pos.xy, pos.xy - (lo + cellPx)), vec2(0.0));
            if (dot(far, far) > link * link) {
                nodes[k] = vec2(0.0);
                fades[k] = 0.0;
                k++;
                continue;
            }
            vec2 p = node_at(cell, cellPx, time);
            nodes[k] = p;
            vec2 nrm = p / resolution;
            fades[k] = border_fade(nrm.x) * border_fade(nrm.y);
            k++;
        }
    }

    float lit = 0.0;   // coverage at this pixel
    float hot = 0.0;   // node cores only, for the glow

    for (int a = 0; a < 25; ++a) {
        float fa = fades[a];
        if (fa <= 0.0) { continue; }
        vec2 pa = nodes[a];
        float da = length(pos.xy - pa);
        // Only a node within one link of this pixel can put an edge across it: a
        // pixel on an edge lies between its ends, so it is within `len` of both.
        // The inner loop runs over every other node (not just b > a), which is what
        // keeps this prune from dropping an edge whose far end is out of range.
        if (da >= link) { continue; }

        float q = max(0.0, 1.0 - da / NODE_PX);
        float dot_ = q * q * fa;
        hot = max(hot, dot_);
        lit = max(lit, dot_ * NODE_ALPHA);

        for (int b = 0; b < 25; ++b) {
            if (b == a) { continue; }
            float fb = fades[b];
            if (fb <= 0.0) { continue; }
            vec2 e = nodes[b] - pa;
            float len = length(e);
            if (len >= link || len < 1e-4) { continue; }
            vec2 dir = e / len;
            float along = clamp(dot(pos.xy - pa, dir), 0.0, len);
            float d = length(pos.xy - pa - dir * along);
            float m = max(0.0, 1.0 - d / LINE_PX);
            if (m <= 0.0) { continue; }
            // Falloff measured against the *cell spacing*, not the link radius. The
            // CPU scene scattered its nodes at random, so plenty of pairs sat well
            // inside the radius and a falloff over the full radius gave a usable
            // spread. On a grid every neighbour is about one cell away, so that same
            // falloff drops them all to the same near-zero alpha and the net renders
            // as bare dots. Anchoring full strength at half a cell restores the range.
            float f = clamp((link - len) / (link - cellPx * NEAR_SPAN), 0.0, 1.0);
            lit = max(lit, m * m * f * EDGE_ALPHA * fa * fb);
        }
    }

    vec3 rgb = mix(ink.rgb, vec3(1.0), clamp(hot, 0.0, 1.0) * NODE_GLOW);
    rgb = mix(backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * opacity);
    return vec4(rgb, 1.0);
}
"""

#: Horizontal data traffic — layered tracks of dashes streaming past the viewer.
#:
#: The look this chases is a telemetry wall seen side-on: rows of bright segments of
#: many lengths sliding by at different rates, faint tick marks standing between
#: them, the whole field clumping into busy and quiet regions. Where :data:`RAIN_MSL`
#: falls, this *travels* — the two are the same idea rotated, but the differences
#: that matter are the ones a rotation does not give you: parallax layers, a
#: leading-edge hot head, and the vertical connectors.
#:
#: Structure: each layer is a stack of rows, and a row is a lane of dashes. A pixel
#: finds its row by division and its dash by another, so it consults exactly one cell
#: per layer — no neighbour visits at all, because a dash is contained in its cell by
#: construction (the cell *is* the dash's slot; only its length varies). That is the
#: cheapest form the grid device takes anywhere in this module, which is what pays
#: for running several layers.
#:
#: Layers recede by a constant factor in pitch, cell length, speed and brightness, so
#: the far ones read as distance rather than as clutter. Every row flows the same
#: direction and differs only in rate: counter-flowing rows read as noise, while a
#: shared direction reads as travel.
#:
#: **Time is folded, not accumulated.** A lane's offset grows without bound, and
#: feeding ``x + t*speed`` straight into the cell hash would lose the fractional part
#: to float32 after a long uptime — the dashes would start to jitter on a machine
#: left running for days. So the offset is split into its integer cell count and its
#: fraction: the fraction positions the pixel inside a cell, the integer only
#: *identifies* which cell (wrapped at :data:`_DS_WRAP` cells, ~10^5 px of travel, so
#: the hash input stays exact). The field repeats after that, which is unobservable
#: and the whole point.
DATASTREAM_MSL = """
// --- tunables ---------------------------------------------------------------
constant int   LAYERS      = 3;     // depth stack; each is a full field of rows
constant float ROW_PX      = 13.0;  // row pitch of the nearest layer, pixels
constant float CELL_PX     = 240.0; // dash slot length of the nearest layer
constant float RATE        = 58.0;  // nearest layer's drift, pixels/second
constant float LINE_PX     = 1.5;   // dash thickness, pixels
constant float DASH_MIN    = 0.06;  // dash length as a fraction of its slot. Skewed
constant float DASH_RANGE  = 0.90;  // short (see DASH_SKEW) so the long ones are rare
constant float DASH_SKEW   = 2.0;   // and read as the exception rather than the rule
constant float HEAD_PX     = 14.0;  // hot leading edge, pixels -- a length, not a
                                    // fraction, so a long streak is not all head
constant float DENSITY     = 0.55;  // fraction of slots that carry a dash
constant float LAYER_STEP  = 0.62;  // each further layer's pitch/speed factor
constant float LAYER_DIM   = 0.60;  // ...and its brightness factor
constant float SPEED_MIN   = 0.35;  // per-row rate spread, x the layer's rate
constant float SPEED_RANGE = 1.30;
constant float TAIL_FLOOR  = 0.42;  // how far a dash dims from head to tail
constant float HEAD_GLOW   = 0.70;  // how far a leading edge pales toward white
constant float TICK_SHARE  = 0.30;  // share of dashes that also stand a tick
constant float TICK_PX     = 1.4;   // tick width, pixels
constant float TICK_FRAC   = 0.92;  // tick height, as a fraction of the row pitch
constant float TICK_ALPHA  = 0.85;
constant float WASH_X      = 2.6;   // the drifting density wash: spatial frequency
constant float WASH_Y      = 1.7;   // in each axis, and how fast it moves
constant float WASH_RATE   = 0.11;
constant float WASH_FLOOR  = 0.55;  // density multiplier at the quietest
constant float WASH_RANGE  = 0.60;
constant float AA_PX       = 0.8;   // edge softening, pixels
constant float CELL_WRAP   = 4096.0;// see the note on folding time, above

// The arithmetic-only hash used throughout this module: no transcendentals, and
// exact for the integer-valued inputs it is given here.
static inline float3 hash33(float2 p) {
    float3 v = fract(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xxy + v.yzz) * v.zyx);
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float t = u.time;
    float2 uv = pos.xy / u.resolution;

    // Busy and quiet regions drifting across the field. Modulating the *density*
    // threshold rather than the brightness is what makes it read as traffic
    // thinning out instead of the whole field dimming.
    float wash = 0.5 + 0.5 * sin(uv.x * WASH_X + t * WASH_RATE)
                           * sin(uv.y * WASH_Y - t * WASH_RATE * 0.77);
    float dens = DENSITY * (WASH_FLOOR + WASH_RANGE * wash);

    float lit = 0.0;   // coverage at this pixel
    float far = 0.0;   // the share of it owed to the receding layers, for the hue
    float hot = 0.0;   // proximity to a leading edge, for the white head

    float scale = 1.0;
    float dim = 1.0;
    for (int i = 0; i < LAYERS; ++i) {
        float rowH = ROW_PX * scale;
        float cellW = CELL_PX * scale;
        // Floors: the far layers must not thin below what a pixel can draw, or they
        // stop being distance and become a grey haze over the file list.
        float halfT = max(0.55, LINE_PX * 0.5 * scale);
        float tickHalf = rowH * TICK_FRAC * 0.5;

        float row = floor(pos.y / rowH);
        float dy = abs(pos.y - (row + 0.5) * rowH);
        // Most pixels sit in a row's gap. Rejecting on the tallest thing the row can
        // hold skips the rest of the layer for them.
        if (dy <= tickHalf + AA_PX) {
            float3 r = hash33(float2(row, float(i) * 91.0));
            float speed = RATE * scale * (SPEED_MIN + SPEED_RANGE * r.x);

            // Fold time: the fraction places this pixel in its slot, the integer
            // only names the slot (see the module note).
            float shift = t * speed / cellW;
            float shiftI = floor(shift);
            float uX = pos.x / cellW + (shift - shiftI);
            float cell = floor(uX);
            float f = uX - cell;
            float cid = fmod(cell + shiftI, CELL_WRAP);

            float3 c = hash33(float2(cid, row + float(i) * 313.0));
            if (c.x <= dens) {
                // Skewed short: most slots carry a stub, a few carry a streak most
                // of the slot long. A flat distribution gives every dash roughly the
                // same length, which reads as a dashed rule rather than as traffic.
                float dash = DASH_MIN + DASH_RANGE * pow(c.y, DASH_SKEW);
                float aa = AA_PX / cellW;          // the AA width, in slot units
                float bright = (0.45 + 0.55 * c.z) * dim;

                // The lane slides left, so f = 0 is the dash's leading edge.
                float covY = 1.0 - smoothstep(halfT, halfT + AA_PX, dy);
                float covX = smoothstep(0.0, aa, f)
                           * (1.0 - smoothstep(dash - aa, dash, f));
                float k = f / dash;                // 0 at the head, 1 at the tail
                float a = covX * covY * bright * mix(1.0, TAIL_FLOOR, k * k);
                lit = max(lit, a);
                far = max(far, a * (1.0 - dim));
                // The head is a fixed number of pixels, not a fraction of the dash:
                // a motion streak's hot tip is the same size however long the streak
                // is, and scaling it with the length makes the long ones glow end to
                // end instead of leading with a bright point.
                hot = max(hot, a * (1.0 - smoothstep(0.0, HEAD_PX, f * cellW)));

                // A vertical connector standing at the *trailing* end of some dashes
                // -- the circuit-trace tick. At the trailing end rather than the
                // leading one so it reads as a terminator: it carries the dash's
                // untapered brightness, so against the faded tail it stands out,
                // whereas at the head it would merge into the hot leading edge.
                // Confined to its own row on purpose: a tick spanning several rows
                // would have to be found by pixels in rows that do not own it, and
                // the one-cell lookup is what makes this scene cheap.
                if (c.x < TICK_SHARE * dens) {
                    float m = 1.0 - smoothstep(TICK_PX * 0.5, TICK_PX * 0.5 + AA_PX,
                                               abs(f - dash) * cellW);
                    float covT = 1.0 - smoothstep(tickHalf, tickHalf + AA_PX, dy);
                    lit = max(lit, m * covT * bright * TICK_ALPHA);
                }
            }
        }
        scale *= LAYER_STEP;
        dim *= LAYER_DIM;
    }

    // Colour: the near tracks carry the theme ink; the far ones recede toward a
    // cooler, bluer cast of it, and a leading edge pales toward white. Both ends are
    // the ink pushed rather than fixed colours, so the field stays on-palette.
    float3 nearInk = u.ink.rgb;
    float3 farInk = u.ink.rgb * float3(0.42, 0.80, 1.15);
    float3 rgb = mix(nearInk, farInk, clamp(far / max(lit, 1e-4), 0.0, 1.0));
    rgb = mix(rgb, float3(1.0), clamp(hot, 0.0, 1.0) * HEAD_GLOW);

    rgb = mix(u.backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * u.opacity);
    return float4(rgb, 1.0);
}
"""

#: The HLSL translation of :data:`DATASTREAM_MSL` (see :data:`WAVE_HLSL` for why a
#: scene ships both). Line-for-line; only the dialect differs — ``fract``/``mix``
#: become ``frac``/``lerp``, ``constant`` becomes ``static const``, and the uniforms
#: are cbuffer globals. Keep the two in sync when tuning the scene.
DATASTREAM_HLSL = """
// --- tunables (see DATASTREAM_MSL for the rationale of each) -----------------
static const int   LAYERS      = 3;
static const float ROW_PX      = 13.0;
static const float CELL_PX     = 240.0;
static const float RATE        = 58.0;
static const float LINE_PX     = 1.5;
static const float DASH_MIN    = 0.06;
static const float DASH_RANGE  = 0.90;
static const float DASH_SKEW   = 2.0;
static const float HEAD_PX     = 14.0;
static const float DENSITY     = 0.55;
static const float LAYER_STEP  = 0.62;
static const float LAYER_DIM   = 0.60;
static const float SPEED_MIN   = 0.35;
static const float SPEED_RANGE = 1.30;
static const float TAIL_FLOOR  = 0.42;
static const float HEAD_GLOW   = 0.70;
static const float TICK_SHARE  = 0.30;
static const float TICK_PX     = 1.4;
static const float TICK_FRAC   = 0.92;
static const float TICK_ALPHA  = 0.85;
static const float WASH_X      = 2.6;
static const float WASH_Y      = 1.7;
static const float WASH_RATE   = 0.11;
static const float WASH_FLOOR  = 0.55;
static const float WASH_RANGE  = 0.60;
static const float AA_PX       = 0.8;
static const float CELL_WRAP   = 4096.0;

float3 hash33(float2 p) {
    float3 v = frac(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return frac((v.xxy + v.yzz) * v.zyx);
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float t = time;
    float2 uv = pos.xy / resolution;

    float wash = 0.5 + 0.5 * sin(uv.x * WASH_X + t * WASH_RATE)
                           * sin(uv.y * WASH_Y - t * WASH_RATE * 0.77);
    float dens = DENSITY * (WASH_FLOOR + WASH_RANGE * wash);

    float lit = 0.0;
    float far = 0.0;
    float hot = 0.0;

    float scale = 1.0;
    float dim = 1.0;
    for (int i = 0; i < LAYERS; ++i) {
        float rowH = ROW_PX * scale;
        float cellW = CELL_PX * scale;
        float halfT = max(0.55, LINE_PX * 0.5 * scale);
        float tickHalf = rowH * TICK_FRAC * 0.5;

        float row = floor(pos.y / rowH);
        float dy = abs(pos.y - (row + 0.5) * rowH);
        if (dy <= tickHalf + AA_PX) {
            float3 r = hash33(float2(row, float(i) * 91.0));
            float speed = RATE * scale * (SPEED_MIN + SPEED_RANGE * r.x);

            float shift = t * speed / cellW;
            float shiftI = floor(shift);
            float uX = pos.x / cellW + (shift - shiftI);
            float cell = floor(uX);
            float f = uX - cell;
            float cid = fmod(cell + shiftI, CELL_WRAP);

            float3 c = hash33(float2(cid, row + float(i) * 313.0));
            if (c.x <= dens) {
                float dash = DASH_MIN + DASH_RANGE * pow(c.y, DASH_SKEW);
                float aa = AA_PX / cellW;
                float bright = (0.45 + 0.55 * c.z) * dim;

                float covY = 1.0 - smoothstep(halfT, halfT + AA_PX, dy);
                float covX = smoothstep(0.0, aa, f)
                           * (1.0 - smoothstep(dash - aa, dash, f));
                float k = f / dash;
                float a = covX * covY * bright * lerp(1.0, TAIL_FLOOR, k * k);
                lit = max(lit, a);
                far = max(far, a * (1.0 - dim));
                hot = max(hot, a * (1.0 - smoothstep(0.0, HEAD_PX, f * cellW)));

                // See the MSL twin: the tick stands at the dash's trailing end.
                if (c.x < TICK_SHARE * dens) {
                    float m = 1.0 - smoothstep(TICK_PX * 0.5, TICK_PX * 0.5 + AA_PX,
                                               abs(f - dash) * cellW);
                    float covT = 1.0 - smoothstep(tickHalf, tickHalf + AA_PX, dy);
                    lit = max(lit, m * covT * bright * TICK_ALPHA);
                }
            }
        }
        scale *= LAYER_STEP;
        dim *= LAYER_DIM;
    }

    float3 nearInk = ink.rgb;
    float3 farInk = ink.rgb * float3(0.42, 0.80, 1.15);
    float3 rgb = lerp(nearInk, farInk, saturate(far / max(lit, 1e-4)));
    rgb = lerp(rgb, float3(1.0, 1.0, 1.0), saturate(hot) * HEAD_GLOW);

    rgb = lerp(backdrop.rgb, rgb, saturate(lit) * opacity);
    return float4(rgb, 1.0);
}
"""

DATASTREAM_GLSL = """
float pk_fmod(float a, float b) { return a - b * trunc(a / b); }

// --- tunables ---------------------------------------------------------------
const int   LAYERS      = 3;     // depth stack; each is a full field of rows
const float ROW_PX      = 13.0;  // row pitch of the nearest layer, pixels
const float CELL_PX     = 240.0; // dash slot length of the nearest layer
const float RATE        = 58.0;  // nearest layer's drift, pixels/second
const float LINE_PX     = 1.5;   // dash thickness, pixels
const float DASH_MIN    = 0.06;  // dash length as a fraction of its slot. Skewed
const float DASH_RANGE  = 0.90;  // short (see DASH_SKEW) so the long ones are rare
const float DASH_SKEW   = 2.0;   // and read as the exception rather than the rule
const float HEAD_PX     = 14.0;  // hot leading edge, pixels -- a length, not a
                                    // fraction, so a long streak is not all head
const float DENSITY     = 0.55;  // fraction of slots that carry a dash
const float LAYER_STEP  = 0.62;  // each further layer's pitch/speed factor
const float LAYER_DIM   = 0.60;  // ...and its brightness factor
const float SPEED_MIN   = 0.35;  // per-row rate spread, x the layer's rate
const float SPEED_RANGE = 1.30;
const float TAIL_FLOOR  = 0.42;  // how far a dash dims from head to tail
const float HEAD_GLOW   = 0.70;  // how far a leading edge pales toward white
const float TICK_SHARE  = 0.30;  // share of dashes that also stand a tick
const float TICK_PX     = 1.4;   // tick width, pixels
const float TICK_FRAC   = 0.92;  // tick height, as a fraction of the row pitch
const float TICK_ALPHA  = 0.85;
const float WASH_X      = 2.6;   // the drifting density wash: spatial frequency
const float WASH_Y      = 1.7;   // in each axis, and how fast it moves
const float WASH_RATE   = 0.11;
const float WASH_FLOOR  = 0.55;  // density multiplier at the quietest
const float WASH_RANGE  = 0.60;
const float AA_PX       = 0.8;   // edge softening, pixels
const float CELL_WRAP   = 4096.0;// see the note on folding time, above

// The arithmetic-only hash used throughout this module: no transcendentals, and
// exact for the integer-valued inputs it is given here.
vec3 hash33(vec2 p) {
    vec3 v = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xxy + v.yzz) * v.zyx);
}

vec4 puikit_bg_fragment(vec2 pos) {
    float t = time;
    vec2 uv = pos.xy / resolution;

    // Busy and quiet regions drifting across the field. Modulating the *density*
    // threshold rather than the brightness is what makes it read as traffic
    // thinning out instead of the whole field dimming.
    float wash = 0.5 + 0.5 * sin(uv.x * WASH_X + t * WASH_RATE)
                           * sin(uv.y * WASH_Y - t * WASH_RATE * 0.77);
    float dens = DENSITY * (WASH_FLOOR + WASH_RANGE * wash);

    float lit = 0.0;   // coverage at this pixel
    float far = 0.0;   // the share of it owed to the receding layers, for the hue
    float hot = 0.0;   // proximity to a leading edge, for the white head

    float scale = 1.0;
    float dim = 1.0;
    for (int i = 0; i < LAYERS; ++i) {
        float rowH = ROW_PX * scale;
        float cellW = CELL_PX * scale;
        // Floors: the far layers must not thin below what a pixel can draw, or they
        // stop being distance and become a grey haze over the file list.
        float halfT = max(0.55, LINE_PX * 0.5 * scale);
        float tickHalf = rowH * TICK_FRAC * 0.5;

        float row = floor(pos.y / rowH);
        float dy = abs(pos.y - (row + 0.5) * rowH);
        // Most pixels sit in a row's gap. Rejecting on the tallest thing the row can
        // hold skips the rest of the layer for them.
        if (dy <= tickHalf + AA_PX) {
            vec3 r = hash33(vec2(row, float(i) * 91.0));
            float speed = RATE * scale * (SPEED_MIN + SPEED_RANGE * r.x);

            // Fold time: the fraction places this pixel in its slot, the integer
            // only names the slot (see the module note).
            float shift = t * speed / cellW;
            float shiftI = floor(shift);
            float uX = pos.x / cellW + (shift - shiftI);
            float cell = floor(uX);
            float f = uX - cell;
            float cid = pk_fmod(cell + shiftI, CELL_WRAP);

            vec3 c = hash33(vec2(cid, row + float(i) * 313.0));
            if (c.x <= dens) {
                // Skewed short: most slots carry a stub, a few carry a streak most
                // of the slot long. A flat distribution gives every dash roughly the
                // same length, which reads as a dashed rule rather than as traffic.
                float dash = DASH_MIN + DASH_RANGE * pow(c.y, DASH_SKEW);
                float aa = AA_PX / cellW;          // the AA width, in slot units
                float bright = (0.45 + 0.55 * c.z) * dim;

                // The lane slides left, so f = 0 is the dash's leading edge.
                float covY = 1.0 - smoothstep(halfT, halfT + AA_PX, dy);
                float covX = smoothstep(0.0, aa, f)
                           * (1.0 - smoothstep(dash - aa, dash, f));
                float k = f / dash;                // 0 at the head, 1 at the tail
                float a = covX * covY * bright * mix(1.0, TAIL_FLOOR, k * k);
                lit = max(lit, a);
                far = max(far, a * (1.0 - dim));
                // The head is a fixed number of pixels, not a fraction of the dash:
                // a motion streak's hot tip is the same size however long the streak
                // is, and scaling it with the length makes the long ones glow end to
                // end instead of leading with a bright point.
                hot = max(hot, a * (1.0 - smoothstep(0.0, HEAD_PX, f * cellW)));

                // A vertical connector standing at the *trailing* end of some dashes
                // -- the circuit-trace tick. At the trailing end rather than the
                // leading one so it reads as a terminator: it carries the dash's
                // untapered brightness, so against the faded tail it stands out,
                // whereas at the head it would merge into the hot leading edge.
                // Confined to its own row on purpose: a tick spanning several rows
                // would have to be found by pixels in rows that do not own it, and
                // the one-cell lookup is what makes this scene cheap.
                if (c.x < TICK_SHARE * dens) {
                    float m = 1.0 - smoothstep(TICK_PX * 0.5, TICK_PX * 0.5 + AA_PX,
                                               abs(f - dash) * cellW);
                    float covT = 1.0 - smoothstep(tickHalf, tickHalf + AA_PX, dy);
                    lit = max(lit, m * covT * bright * TICK_ALPHA);
                }
            }
        }
        scale *= LAYER_STEP;
        dim *= LAYER_DIM;
    }

    // Colour: the near tracks carry the theme ink; the far ones recede toward a
    // cooler, bluer cast of it, and a leading edge pales toward white. Both ends are
    // the ink pushed rather than fixed colours, so the field stays on-palette.
    vec3 nearInk = ink.rgb;
    vec3 farInk = ink.rgb * vec3(0.42, 0.80, 1.15);
    vec3 rgb = mix(nearInk, farInk, clamp(far / max(lit, 1e-4), 0.0, 1.0));
    rgb = mix(rgb, vec3(1.0), clamp(hot, 0.0, 1.0) * HEAD_GLOW);

    rgb = mix(backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * opacity);
    return vec4(rgb, 1.0);
}
"""

#: A depth of holographic panels drifting toward the viewer — the data-wall look.
#:
#: Structure: a stack of planes at increasing depth, each tiled into cells, each cell
#: hosting one **panel** — a small flat HUD of rules, blocks and pseudo-text. A plane
#: sweeps from far to near and recycles, so panels grow and slide outward as they
#: approach and pass. This is :data:`STARFIELD_MSL`'s depth machinery carrying a
#: *drawing* instead of a dot, and it inherits that scene's key property: a panel's
#: identity comes from its position on the plane, which never moves, so approaching
#: it magnifies it rather than morphing it.
#:
#: A panel draws one of six things — typed pseudo-text, a bar chart, a line chart,
#: progress bars, a ring gauge, or a wireframe mesh — picked by a hash and read off a
#: threshold chain, so only the winning branch costs anything. Text is much the
#: commonest; the charts are punctuation.
#:
#: **Why the content is procedural blocks and not text.** A background shader is
#: handed uniforms and binds no textures — there is no font to sample, and glyph
#: rasterisation in a fragment function would cost more than the whole rest of the
#: scene. So a row of "text" is a run of blocks with text's *rhythm*: varied widths,
#: short gaps, a common baseline. At the size panels actually occupy that is what the
#: reference reads as anyway; the legibility was never there to lose.
#:
#: What it does need is text's **order**. A row types out left to right, holds, then
#: retypes with fresh content, with the mark under the head burning brighter — the
#: caret. Re-rolling every slot at once (what this did first) costs nothing less and
#: reads as noise: writing order is most of what identifies a row as writing.
#:
#: **Three nested grids, one lookup each.** Cell → panel, panel → row, row → block:
#: a pixel divides its way down to exactly one block and hashes it. Nothing is
#: iterated but the depth planes, which is what lets the field be this dense.
#:
#: **Speed.** Panels creep toward the viewer and the ambient field drifts at a few
#: pixels a second, which between them make a scene that barely appears to move. The
#: *fast layer* — barcode bursts, dashes and dots running along horizontal lanes — is
#: the one element with real pace, and it is what keeps the whole thing from reading
#: as a still image under a slow zoom.
#:
#: **The concentration lines** raking outward from the vanishing point are the
#: datastream's dash-in-a-slot wrapped around the centre — a pixel finds its angular
#: sector and its slot along the ray and consults one cell, so the whole field costs
#: about what one more depth plane would. They earn their place by selling the motion
#: the panels only imply: panels *grow*, but nothing about them streaks.
#:
#: **Resolution-aware fade.** Depth means far panels pack their rows tighter than a
#: pixel can resolve, and drawing them anyway turns the far field into crawling
#: noise. Each panel measures a pixel against its own row pitch — computed
#: analytically from the depth, since ``fwidth`` is undefined under the non-uniform
#: branching this scene is built from — and fades out where it can no longer be read.
#: That is also what bounds the cost of the far planes rather than the plane count.
#:
#: **The warm accent.** The reference punctuates its cyan with amber, and a shader
#: gets exactly one theme colour (``ink``). The accent is therefore the ink with red
#: and blue swapped: on the cyan this scene is written for that lands on amber
#: exactly, and on any other palette it stays a hue derived from the theme rather
#: than a colour imported from outside it.
HOLOGRAM_MSL = """
// --- tunables ---------------------------------------------------------------
constant int   LAYERS      = 12;    // depth planes; each a full grid of panels
constant float Z_FAR       = 3.0;   // spawn depth / closest approach. The divide
constant float Z_NEAR      = 0.45;  // blows up as Z_NEAR reaches 0
constant float RATE        = 0.015;  // fraction of the depth range crossed per second
constant float FADE_IN     = 0.30;  // fraction of the travel spent fading in
constant float FADE_OUT    = 0.18;  // ...and fading out as it sweeps past. Long,
                                    // because a plane at Z_NEAR is wider than the
                                    // window: a panel has to be gone before it
                                    // becomes the whole screen and pops out
constant float GRID        = 3.20;  // panel cells per unit of plane
constant float PANEL_KEEP  = 0.38;  // share of cells that host a panel at all
constant float PANEL_W_MIN = 0.40;  // panel size as a fraction of its cell
constant float PANEL_W_RNG = 0.50;
constant float PANEL_H_MIN = 0.22;
constant float PANEL_H_RNG = 0.42;

// What a panel *is*. Cumulative thresholds on one hash, read off in a comparison
// chain, so a panel draws one kind and only the winning branch costs anything.
constant float K_TEXT      = 0.660;  // typed pseudo-text (the commonest)
constant float K_BARS      = 0.725;  // bar chart
constant float K_LINE      = 0.765;  // line chart
constant float K_PROG      = 0.875;  // progress bars
constant float K_PIE       = 0.915;  // ring gauge -- the rest are wireframe

// Text panels
constant float ROWS        = 9.0;   // content rows per panel
constant float SEG_MIN     = 8.0;   // character slots per row
constant float SEG_RNG     = 16.0;
constant float ROW_FILL    = 0.60;  // share of slots carrying a mark
constant float BLOCK_H     = 0.32;  // mark height, as a fraction of the row
constant float BLOCK_MIN   = 0.15;  // mark width, as a fraction of its slot
constant float BLOCK_RNG   = 0.55;
constant float RULE_SHARE  = 0.20;  // share of rows drawn as a full-width hairline
constant float RULE_H      = 0.09;
constant float TYPE_RATE   = 0.16;  // type-hold-retype cycles per second
constant float TYPE_FRAC   = 0.34;  // fraction of that cycle spent typing
constant float CURSOR_LIFT = 0.60;  // extra brightness on the mark at the head

// Bar charts
constant float BAR_N_MIN   = 5.0;   // bars per panel
constant float BAR_N_RNG   = 9.0;
constant float BAR_W       = 0.42;  // bar width, as a fraction of its slot
constant float BAR_MIN     = 0.12;  // bar height range, as a fraction of the panel
constant float BAR_RNG     = 0.80;
constant float BAR_RATE    = 0.22;  // re-rolls per second

// Line charts
constant float LINE_PTS    = 8.0;   // vertices across the panel
constant float LINE_W      = 0.022;  // trace thickness, in panel-local units
constant float LINE_RATE   = 0.18;
constant float LINE_LO     = 0.12;  // the band the trace stays inside
constant float LINE_SPAN   = 0.76;
constant float LINE_FILL   = 0.10;  // brightness of the wash under the trace

// Progress bars
constant float PROG_ROWS   = 4.0;
constant float PROG_H      = 0.34;  // bar height, as a fraction of its row
constant float PROG_RATE   = 0.12;
constant float PROG_TRACK  = 0.32;  // brightness of the unfilled track
constant float PROG_LO     = 0.08;  // fill range, so a bar is never quite empty/full
constant float PROG_SPAN   = 0.86;

// Ring gauges
constant float PIE_R       = 0.24;  // radius, as a fraction of the panel's short side
constant float PIE_W       = 0.06;  // ring thickness, as a fraction of the radius
constant float PIE_RATE    = 0.09;
constant float PIE_TRACK   = 0.50;  // brightness of the unswept ring

// Wireframes
constant float WIRE_NX     = 6.0;   // mesh divisions
constant float WIRE_NY     = 4.0;
constant float WIRE_DIAG   = 0.50;  // share that also carry diagonals
constant float WIRE_ALPHA  = 0.50;

// Panel chrome and shading
constant float FRAME_SHARE = 0.45;  // share of panels carrying an outline
constant float FRAME_ALPHA = 0.55;
constant float WARM_SHARE  = 0.14;  // share of marks struck in the warm accent
constant float NEAR_GLOW   = 0.55;  // how far the nearest panels pale toward white
constant float DEPTH_DIM   = 0.52;  // brightness of the furthest plane vs the nearest.
                                    // Without this the field reads flat: every plane
                                    // draws at the same strength, so the eye gets the
                                    // *scale* cue and no aerial one, and a big near
                                    // panel looks like a big panel rather than a
                                    // close one
constant float RESOLVE     = 0.85;  // fade a panel out past this many pixels per row

// Concentration lines -- the radial speed streaks
constant float CONC_SECTORS = 220.0; // angular slots around the vanishing point
constant float CONC_COUNT   = 4.0;   // how many of them carry a streak. A pixel only
                                     // ever sees its own sector, so this cannot be a
                                     // hard cap -- it is the *expected* number, set by
                                     // keeping a COUNT/SECTORS share of the draws
constant float CONC_CELL    = 0.34;  // streak slot length, as a fraction of the radius
constant float CONC_DASH    = 0.55;  // dash length within its slot
constant float CONC_RATE    = 0.20;  // outward drift, fraction of the radius/second
constant float CONC_PX      = 2.6;   // streak width, pixels
constant float CONC_ALPHA   = 0.95;
constant float CONC_IN      = 0.16;  // radius (fraction) the streaks start at
constant float CONC_RAMP    = 0.26;  // ...and how far they take to reach full strength
constant float CONC_HEAD    = 0.60;  // how far a leading edge pales toward white

constant float LIFE_RATE   = 0.167; // panel appear-hold-vanish cycles per second.
                                    // Deliberately independent of RATE: see the note
                                    // in the loop on why the two had to come apart
constant float LIFE_IN     = 0.12;  // fraction of a life spent fading up
constant float LIFE_OUT    = 0.18;  // ...and fading out

// The ambient field: soft out-of-focus dots, rings and strokes drifting in *screen*
// space, with no part in the depth sweep. Everything else here flies at the viewer,
// which gives the scene one motion and one only; this layer drifts across it instead,
// so there is something in frame that is simply there rather than arriving.
constant float AMB_CELL_PX  = 170.0; // ambient cell size, pixels
constant float AMB_KEEP     = 0.55;  // share of cells carrying an object
constant float AMB_MAX_R    = 70.0;  // bound on an object's reach: the jitter below is
                                     // clamped so nothing leaves its own cell, which
                                     // is what keeps this to one lookup per pixel
constant float AMB_DRIFT_X  = 5.0;   // field drift, pixels/second
constant float AMB_DRIFT_Y  = -3.0;
constant float AMB_ORBIT    = 0.05;  // per-object orbit, turns/second
constant float AMB_ORBIT_R  = 9.0;   // ...and its radius, pixels
constant float AMB_K_DOT    = 0.60;  // kind mix: dot / stroke
constant float AMB_DOT_R    = 40.0;
constant float AMB_DOT_A    = 0.45;
constant float AMB_LINE_L   = 80.0;
constant float AMB_LINE_W   = 1.4;
constant float AMB_LINE_A   = 0.30;
constant float AMB_SOFT     = 7.0;   // edge softness, pixels -- these read as
                                     // out-of-focus, so the falloff is wide

// The fast layer: bright dashes and dots running along horizontal lanes, far quicker
// than anything else here. The ambient field drifts at a few pixels a second and the
// panels creep toward the viewer; this is the only element with real speed, and it is
// what stops the scene reading as a still image with a slow zoom.
constant float FAST_LANE_PX = 38.0;  // lane pitch, pixels
constant float FAST_KEEP    = 0.42;  // share of lanes carrying traffic
constant float FAST_CELL_PX = 150.0; // slot length along a lane, pixels
constant float FAST_FILL    = 0.55;  // share of slots carrying an object
constant float FAST_RATE    = 260.0; // lane speed, pixels/second
constant float FAST_DASH    = 0.16;  // dash length, as a fraction of its slot
constant float FAST_LINE_W  = 1.3;   // dash thickness, pixels
constant float FAST_DOT_R   = 2.6;   // dot radius, pixels
constant float FAST_TICK_H  = 15.0;  // upright tick height, pixels (before variance)
constant float FAST_TICK_W  = 1.6;   // ...and its width
constant float FAST_BURST   = 0.30;  // a tick object is a *burst* of bars, spanning
constant float FAST_TICK_N  = 8.0;   // this fraction of its slot, this many bars
constant float FAST_TICK_FILL = 0.70;// ...of which this share are actually drawn
constant float FAST_DOT_MIX = 0.30;  // kind mix, cumulative: dot / upright tick /
constant float FAST_TICK_MIX = 0.66; // horizontal dash
constant float FAST_REACH   = 17.0;  // the tallest a lane's contents can reach, for
                                     // the early-out. A tick varies up to 2x its
                                     // nominal height, so this is not FAST_TICK_H
constant float FAST_ALPHA   = 0.85;
constant float FAST_HEAD    = 0.70;  // how far a dash's leading edge pales to white
constant float FAST_WRAP    = 4096.0;

constant float CYCLE_WRAP   = 512.0; // keeps the hash inputs exact -- see the note on
constant float CONC_WRAP    = 4096.0;// folding time in DATASTREAM_MSL
constant float TAU          = 6.283185307;

static inline float3 hash33(float2 p) {
    float3 v = fract(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xxy + v.yzz) * v.zyx);
}

// A value that re-rolls on a fixed beat and eases between draws, so charts move
// rather than jump. Returns the eased value; `gen` is the draw it is heading to.
static inline float stepped(float2 seed, float beat, float phase) {
    float ct = beat + phase;
    float gen = floor(ct);
    float a = hash33(seed + float2(gen * 53.0, 0.0)).x;
    float b = hash33(seed + float2((gen + 1.0) * 53.0, 0.0)).x;
    return mix(a, b, smoothstep(0.0, 1.0, fract(ct)));
}

// The ambient field: one soft object per screen-space cell, drifting as a whole and
// orbiting within its cell. The jitter is clamped so an object cannot leave the cell
// that owns it, which is what lets a pixel consult exactly one cell -- the same
// bounded-jitter trick the wave uses, and the reason this layer is nearly free.
//
// Nothing here takes part in the depth sweep. That is the point: every other element
// flies at the viewer, so the scene had exactly one kind of motion, and a layer that
// merely drifts across it reads as depth of field rather than as more traffic.
static inline float ambient_field(float2 p, float t) {
    float2 q = p + float2(t * AMB_DRIFT_X, t * AMB_DRIFT_Y);
    float2 cell = floor(q / AMB_CELL_PX);
    float2 f = q - cell * AMB_CELL_PX;
    float3 h = hash33(cell + 91.0);
    if (h.x > AMB_KEEP) { return 0.0; }

    float3 g = hash33(cell * 1.7 + 13.0);
    float span = AMB_CELL_PX - 2.0 * AMB_MAX_R;
    float2 c = float2(AMB_CELL_PX * 0.5) + (g.xy - 0.5) * span;
    float ang = t * AMB_ORBIT * TAU * (0.6 + 0.8 * g.z) + h.z * TAU;
    c += float2(cos(ang), sin(ang)) * AMB_ORBIT_R;

    float2 d2 = f - c;
    float d = length(d2);
    if (h.y < AMB_K_DOT) {
        // A squared falloff, not a smoothstep-bounded disc: an out-of-focus
        // highlight has no edge. (Cubed, the first try, collapses the visible core
        // to a point -- the dots read as dust rather than as lights.)
        float r = AMB_DOT_R * (0.5 + 0.9 * g.x);
        float k = max(0.0, 1.0 - d / r);
        return k * k * AMB_DOT_A;
    }
    float a2 = g.z * TAU;
    float2 dir = float2(cos(a2), sin(a2));
    float half_len = AMB_LINE_L * 0.5 * (0.5 + 0.9 * g.x);
    float along = clamp(dot(d2, dir), -half_len, half_len);
    return (1.0 - smoothstep(AMB_LINE_W, AMB_LINE_W + AMB_SOFT,
                             length(d2 - dir * along))) * AMB_LINE_A;
}

// Bright traffic running along horizontal lanes: short dashes with a hot leading
// edge, and dots riding the same slots. Folded like the datastream's lanes -- the
// fraction places the pixel in its slot, the integer only names it -- so a pixel
// consults exactly one cell however long the app has been running.
//
// Returns coverage in .x and how much of it is leading edge in .y.
static inline float2 fast_field(float2 pos, float t) {
    float lane = floor(pos.y / FAST_LANE_PX);
    float dy = abs(pos.y - (lane + 0.5) * FAST_LANE_PX);
    // Everything in a lane hugs its centre line, so most pixels leave immediately.
    if (dy > FAST_REACH) { return float2(0.0); }

    float3 lh = hash33(float2(lane, 71.0));
    if (lh.x > FAST_KEEP) { return float2(0.0); }

    float speed = FAST_RATE * (0.6 + 0.8 * lh.y);
    float shift = t * speed / FAST_CELL_PX;
    float shiftI = floor(shift);
    float uu = pos.x / FAST_CELL_PX + (shift - shiftI);
    float slot = floor(uu);
    float fx = uu - slot;
    float3 sh = hash33(float2(fmod(slot - shiftI, FAST_WRAP), lane));
    if (sh.x > FAST_FILL) { return float2(0.0); }

    if (sh.y < FAST_DOT_MIX) {
        float d = length(float2(fx * FAST_CELL_PX, dy));
        return float2((1.0 - smoothstep(FAST_DOT_R, FAST_DOT_R + 1.2, d))
                      * FAST_ALPHA, 0.0);
    }
    if (sh.y < FAST_TICK_MIX) {
        // A burst of upright bars -- the barcode the reference runs along its bands.
        // A single bar per slot (the first try) scatters into isolated tally marks;
        // it is the *cluster* that reads as a packet of data going past. Heights vary
        // widely on purpose too: a run of equal bars reads as a ruler.
        if (fx > FAST_BURST) { return float2(0.0); }
        float gx = fx / FAST_BURST * FAST_TICK_N;
        float bar = floor(gx);
        float gf = gx - bar;
        float3 th = hash33(float2(bar + slot * 17.0, lane + 5.0));
        if (th.x > FAST_TICK_FILL) { return float2(0.0); }
        float half_h = FAST_TICK_H * (0.35 + 1.1 * th.y);
        float pitch = FAST_BURST * FAST_CELL_PX / FAST_TICK_N;   // bar spacing, px
        float covX = 1.0 - smoothstep(FAST_TICK_W * 0.5, FAST_TICK_W * 0.5 + 1.0,
                                      gf * pitch);
        float covY = 1.0 - smoothstep(half_h, half_h + 1.0, dy);
        return float2(covX * covY * FAST_ALPHA, 0.0);
    }
    float dash = FAST_DASH * (0.4 + 1.2 * sh.z);
    float aa = 1.0 / FAST_CELL_PX;
    float covX = smoothstep(0.0, aa, fx) * (1.0 - smoothstep(dash - aa, dash, fx));
    float covY = 1.0 - smoothstep(FAST_LINE_W * 0.5, FAST_LINE_W * 0.5 + 1.0, dy);
    float a = covX * covY * FAST_ALPHA;
    return float2(a, a * (1.0 - smoothstep(0.0, dash * 0.35, fx)));
}

// One panel's contents, in panel-local coordinates (0..1 on each axis). Returns
// coverage in .x and how much of it is struck in the warm accent in .y.
//
// `pixCell` is one screen pixel expressed in *cell* units -- the panel's own axes
// are anisotropic (it is pw x panelH of a cell), so each branch converts as it needs
// to. Everything is antialiased against that rather than against fwidth: the caller
// reaches this under heavily non-uniform branching, where a derivative is undefined.
static inline float2 panel_content(float lx, float ly, float pixCell,
                                   float pw, float panelH, float2 salt,
                                   float kind, float kvar, float t) {
    float pixX = pixCell / pw;          // one pixel, in panel-local x
    float pixY = pixCell / panelH;      // ...and y
    float a = 0.0;
    float acc = 0.0;

    if (kind < K_TEXT) {
        // --- typed pseudo-text ------------------------------------------------
        float ry = ly * ROWS;
        float row = floor(ry);
        float fy = ry - row;
        float aaY = pixY * ROWS;
        float3 rh = hash33(salt + float2(row * 7.0, 3.0));
        if (rh.x < RULE_SHARE) {
            a = 1.0 - smoothstep(RULE_H * 0.5, RULE_H * 0.5 + aaY, abs(fy - 0.5));
        } else {
            float segs = floor(SEG_MIN + SEG_RNG * rh.y);
            float sx = lx * segs;
            float seg = floor(sx);
            float fx = sx - seg;
            // A row types out left to right, holds, then retypes with fresh content.
            // Re-rolling every slot at once (what this did before) is what made the
            // marks read as noise rather than as characters: text has a writing
            // *order*, and the order is most of what identifies it as text.
            float ct = t * TYPE_RATE + rh.z * 7.0;
            float gen = floor(ct);
            float head = clamp(fract(ct) / TYPE_FRAC, 0.0, 1.0) * segs;
            if (seg < head) {
                float3 sh = hash33(float2(seg + gen * 131.0, salt.y + row));
                if (sh.x < ROW_FILL) {
                    float bw = BLOCK_MIN + BLOCK_RNG * sh.y;
                    float covX = 1.0 - smoothstep(bw - pixX * segs, bw, fx);
                    float covY = 1.0 - smoothstep(BLOCK_H * 0.5,
                                                  BLOCK_H * 0.5 + aaY, abs(fy - 0.5));
                    a = covX * covY;
                    // The mark under the head burns brighter for a slot or so -- the
                    // caret, and the cue that reads as "this is being written now".
                    a *= 1.0 + CURSOR_LIFT * (1.0 - smoothstep(0.0, 1.5, head - seg));
                    acc = (sh.z > 1.0 - WARM_SHARE) ? a : 0.0;
                }
            }
        }
    } else if (kind < K_BARS) {
        // --- bar chart --------------------------------------------------------
        float bars = floor(BAR_N_MIN + BAR_N_RNG * kvar);
        float bx = lx * bars;
        float bar = floor(bx);
        float fx = bx - bar;
        float h = BAR_MIN + BAR_RNG * stepped(salt + float2(bar, 0.0),
                                              t * BAR_RATE, kvar * 5.0);
        float covX = 1.0 - smoothstep(BAR_W - pixX * bars, BAR_W, fx);
        // ly runs downward, so a bar standing on the floor is (1 - ly) < h.
        float covY = 1.0 - smoothstep(h - pixY, h, 1.0 - ly);
        a = covX * covY;
        a = max(a, 1.0 - smoothstep(pixY * 0.5, pixY * 1.5, 1.0 - ly));   // baseline
    } else if (kind < K_LINE) {
        // --- line chart -------------------------------------------------------
        float px = lx * LINE_PTS;
        float ip = floor(px);
        float fp = px - ip;
        float y0 = LINE_LO + LINE_SPAN * stepped(salt + float2(ip, 0.0),
                                                 t * LINE_RATE, kvar * 3.0);
        float y1 = LINE_LO + LINE_SPAN * stepped(salt + float2(ip + 1.0, 0.0),
                                                 t * LINE_RATE, kvar * 3.0);
        float yl = mix(y0, y1, fp);
        // Perpendicular distance, not vertical: without the slope correction a steep
        // leg of the trace draws several times thicker than a flat one.
        float slope = (y1 - y0) * LINE_PTS;
        float d = abs(ly - yl) / sqrt(1.0 + slope * slope);
        a = 1.0 - smoothstep(LINE_W * 0.5, LINE_W * 0.5 + pixY, d);
        a = max(a, (ly > yl) ? LINE_FILL : 0.0);      // the wash under the trace
    } else if (kind < K_PROG) {
        // --- progress bars ----------------------------------------------------
        float ry = ly * PROG_ROWS;
        float row = floor(ry);
        float fy = ry - row;
        float aaY = pixY * PROG_ROWS;
        float3 rh = hash33(salt + float2(row * 11.0, 17.0));
        float band = 1.0 - smoothstep(PROG_H * 0.5, PROG_H * 0.5 + aaY, abs(fy - 0.5));
        float p = PROG_LO + PROG_SPAN * stepped(salt + float2(row * 3.0, 9.0),
                                                t * PROG_RATE, rh.z * 4.0);
        float fill = band * (1.0 - smoothstep(p - pixX, p, lx));
        a = max(band * PROG_TRACK, fill);
        acc = (rh.y > 1.0 - WARM_SHARE) ? fill : 0.0;
    } else if (kind < K_PIE) {
        // --- ring gauge -------------------------------------------------------
        // Back into cell units, where the axes are isotropic again -- drawn in
        // panel-local units a circle would come out as an ellipse.
        float2 q = float2((lx - 0.5) * pw, (ly - 0.5) * panelH);
        float R = PIE_R * min(pw, panelH);
        float r = length(q);
        float ring = 1.0 - smoothstep(R * PIE_W, R * PIE_W + pixCell, abs(r - R));
        float band = 1.0 - smoothstep(R * PIE_W * 2.4, R * PIE_W * 2.4 + pixCell,
                                      abs(r - R));
        float sweep = stepped(salt + float2(31.0, 0.0), t * PIE_RATE, kvar * 6.0);
        float ang = atan2(q.y, q.x) / TAU + 0.5;
        float arc = (ang < sweep) ? band : 0.0;
        a = max(ring * PIE_TRACK, arc);
        acc = arc;
    } else {
        // --- wireframe --------------------------------------------------------
        float u = lx * WIRE_NX;
        float v = ly * WIRE_NY;
        float wu = pixX * WIRE_NX;
        float wv = pixY * WIRE_NY;
        a = max(1.0 - smoothstep(0.5 * wu, 1.5 * wu, abs(u - round(u))),
                1.0 - smoothstep(0.5 * wv, 1.5 * wv, abs(v - round(v))));
        if (kvar < WIRE_DIAG) {
            float d = u + v;
            float wd = wu + wv;
            a = max(a, 1.0 - smoothstep(0.5 * wd, 1.5 * wd, abs(d - round(d))));
        }
        a *= WIRE_ALPHA;
    }
    return float2(a, acc);
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float2 halfRes = u.resolution * 0.5;
    // View-height units in both axes, so a panel stays square whatever the window
    // aspect. (The starfield normalises per-axis instead and lets its field stretch;
    // a stretching *drawing* would read as a mistake where a stretching dot does not.)
    float2 P = pos.xy - halfRes;
    float2 n = P / halfRes.y;
    float t = u.time;

    float lit = 0.0;    // coverage at this pixel
    float warm = 0.0;   // the share of it struck in the accent, for the hue
    float hot = 0.0;    // nearness of whatever covered it, for the white lift

    for (int i = 0; i < LAYERS; ++i) {
        // Planes evenly offset in phase, so the field always holds panels at every
        // stage of the approach rather than pulsing in unison.
        float raw = t * RATE + float(i) / float(LAYERS);
        float travel = fract(raw);
        float cycle = fmod(floor(raw), CYCLE_WRAP);   // re-rolls a plane's content
        // Even steps in 1/z are even steps *on screen* (the same reason the wave
        // stacks its slabs this way). Stepping z linearly instead spends almost every
        // plane in the far half, where 1/z barely moves -- which is why the field
        // came out as one size of panel repeated rather than a depth of them. This
        // spreads the planes evenly across apparent scale, so a big near panel, a
        // mid one and the far haze are all on screen at once.
        float z = 1.0 / mix(1.0 / Z_FAR, 1.0 / Z_NEAR, travel);
        float alpha = min(1.0, travel / FADE_IN)
                    * (1.0 - smoothstep(1.0 - FADE_OUT, 1.0, travel));
        if (alpha <= 0.002) { continue; }

        // Run the projection backwards: at this depth the ray crosses the plane
        // here, so this is the only cell that can cover this pixel.
        float2 s = n * z;
        float2 cell = floor(s * GRID);
        float2 f = s * GRID - cell;

        // Each panel lives and dies on its own clock, much shorter than its plane's
        // traversal: it fades up, holds, fades out, and the cell is redrawn with a
        // fresh one. Decoupling the two is the whole point -- the plane's sweep used
        // to serve as the panel lifetime as well, so slowing the flight would have
        // made every panel linger proportionally longer. Now the flight can be slow
        // and the field still turns over quickly.
        float3 lh = hash33(cell * 0.61 + float2(float(i) * 3.0, 7.0));
        float lifeT = t * LIFE_RATE + lh.x * 11.0;
        float lifeGen = fmod(floor(lifeT), CYCLE_WRAP);
        float lifePh = fract(lifeT);
        float life = smoothstep(0.0, LIFE_IN, lifePh)
                   * (1.0 - smoothstep(1.0 - LIFE_OUT, 1.0, lifePh));
        if (life <= 0.002) { continue; }

        // ``lifeGen`` rides in every panel hash below, so a cell that comes back
        // comes back as a different panel rather than as the same one blinking.
        float3 ph = hash33(cell + float2(cycle * 13.0 + float(i) * 57.0 + lifeGen * 29.0,
                                         cycle * 7.0 - float(i) * 23.0 + lifeGen * 41.0));
        if (ph.x > PANEL_KEEP) { continue; }     // this cell is empty space

        float3 qh = hash33(cell * 1.37 + float2(float(i) * 11.0,
                                                cycle * 3.0 + lifeGen * 17.0));
        float pw = PANEL_W_MIN + PANEL_W_RNG * ph.y;
        float panelH = PANEL_H_MIN + PANEL_H_RNG * ph.z;
        float lx = (f.x - (1.0 - pw) * qh.x) / pw;   // panel-local, 0..1
        float ly = (f.y - (1.0 - panelH) * qh.y) / panelH;
        if (lx < 0.0 || lx > 1.0 || ly < 0.0 || ly > 1.0) { continue; }

        // One pixel, in cell units. Derived from the depth rather than from fwidth:
        // the branching above is non-uniform, which makes a derivative undefined,
        // and every antialiasing width downstream depends on this.
        float pixCell = z * GRID / halfRes.y;
        // Past the point where a pixel spans a good part of a row, the panel cannot
        // be read at all; fading it out is what keeps the far field from boiling.
        float resolve = 1.0 - smoothstep(RESOLVE * 0.5, RESOLVE,
                                         (pixCell / panelH) * ROWS);
        if (resolve <= 0.0) { continue; }

        // ``travel``, not z: with the 1/z stepping above it is travel that is linear
        // in apparent scale, so it is the measure that makes the aerial cue agree
        // with the size cue.
        float depth = 1.0 - travel;                         // 0 near, 1 far
        float bright = (0.3 + 0.7 * ph.y) * alpha * life * resolve
                     * mix(1.0, DEPTH_DIM, depth);

        float2 r = panel_content(lx, ly, pixCell, pw, panelH,
                                 float2(cell.x * 13.0 + float(i),
                                        cell.y * 29.0 + cycle + lifeGen * 7.0),
                                 qh.z, fract(qh.y * 11.7), t);
        float a = r.x;

        // A hairline outline on some panels, which is most of what makes a cluster
        // of marks read as a *panel* rather than as loose debris.
        if (fract(qh.x * 7.3) < FRAME_SHARE) {
            float edge = min(min(lx, 1.0 - lx) * pw,
                             min(ly, 1.0 - ly) * panelH) / pixCell;
            a = max(a, (1.0 - smoothstep(0.6, 1.6, edge)) * FRAME_ALPHA);
        }

        a *= bright;
        lit = max(lit, a);
        warm = max(warm, r.y * bright);
        hot = max(hot, a * (1.0 - z / Z_FAR));
    }

    // --- concentration lines --------------------------------------------------
    // Radial speed streaks raking outward from the vanishing point. This is the
    // datastream's dash-in-a-slot wrapped around the centre: a pixel finds its
    // angular sector and its slot along the ray and consults exactly one cell, so a
    // whole field of them costs about what one more panel plane would. They sell the
    // forward motion the panels only imply -- the panels grow, but nothing *streaks*.
    float rad = length(P);
    float rn = rad / length(halfRes);          // 0 at the centre, 1 at the corner
    if (rn > CONC_IN && rad > 1.0) {
        float ang = atan2(P.y, P.x) / TAU + 0.5;
        // Wrapped, or the slot at ang = 1 would be a different draw from the one at
        // ang = 0 and the field would carry a seam straight out along -x.
        float sector = fmod(floor(ang * CONC_SECTORS), CONC_SECTORS);
        float3 ch = hash33(float2(sector, 4.0));
        if (ch.x * CONC_SECTORS < CONC_COUNT) {
            // Folded like the datastream's lanes: the fraction places the pixel in
            // its slot, the integer only names it.
            float shift = t * CONC_RATE * (0.5 + 1.2 * ch.y) / CONC_CELL;
            float shiftI = floor(shift);
            float uu = rn / CONC_CELL - (shift - shiftI);
            float slot = floor(uu);
            float fu = uu - slot;
            float3 dh = hash33(float2(fmod(slot - shiftI, CONC_WRAP), sector));
            if (dh.x < 0.75) {
                float dash = CONC_DASH * (0.35 + 0.9 * dh.y);
                // Constant width in pixels, so the angular half-width has to shrink
                // as the radius grows -- otherwise a streak fans out into a wedge.
                float dPx = abs(fract(ang * CONC_SECTORS) - 0.5) / CONC_SECTORS * TAU * rad;
                float covA = 1.0 - smoothstep(CONC_PX * 0.5, CONC_PX * 0.5 + 1.0, dPx);
                float covR = smoothstep(0.0, 0.02, fu)
                           * (1.0 - smoothstep(dash - 0.02, dash, fu));
                float fade = smoothstep(CONC_IN, CONC_IN + CONC_RAMP, rn);
                float a = covA * covR * fade * CONC_ALPHA * (0.5 + 0.5 * dh.z);
                lit = max(lit, a);
                hot = max(hot, a * (1.0 - smoothstep(0.0, 0.3, fu)) * CONC_HEAD);
            }
        }
    }

    // The ambient layer sits under the rest: dim, soft and cool, never warm or hot.
    lit = max(lit, ambient_field(pos.xy, t));

    // The fast layer, on top: this is the element that actually moves.
    float2 fastR = fast_field(pos.xy, t);
    lit = max(lit, fastR.x);
    hot = max(hot, fastR.y * FAST_HEAD);

    // The accent is the ink with red and blue swapped -- amber out of this scene's
    // cyan, and a theme-derived hue out of anything else (see the module note).
    float3 rgb = mix(u.ink.rgb, u.ink.zyx, clamp(warm / max(lit, 1e-4), 0.0, 1.0));
    rgb = mix(rgb, float3(1.0), clamp(hot, 0.0, 1.0) * NEAR_GLOW);

    rgb = mix(u.backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * u.opacity);
    return float4(rgb, 1.0);
}
"""

#: The HLSL translation of :data:`HOLOGRAM_MSL` (see :data:`WAVE_HLSL` for why a scene
#: ships both). Line-for-line; only the dialect differs. Keep the two in sync.
HOLOGRAM_HLSL = """
// --- tunables (see HOLOGRAM_MSL for the rationale of each) -------------------
static const int   LAYERS      = 12;    // depth planes; each a full grid of panels
static const float Z_FAR       = 3.0;   // spawn depth / closest approach. The divide
static const float Z_NEAR      = 0.45;  // blows up as Z_NEAR reaches 0
static const float RATE        = 0.015;  // fraction of the depth range crossed per second
static const float FADE_IN     = 0.30;  // fraction of the travel spent fading in
static const float FADE_OUT    = 0.18;  // ...and fading out as it sweeps past. Long,
                                    // because a plane at Z_NEAR is wider than the
                                    // window: a panel has to be gone before it
                                    // becomes the whole screen and pops out
static const float GRID        = 3.20;  // panel cells per unit of plane
static const float PANEL_KEEP  = 0.38;  // share of cells that host a panel at all
static const float PANEL_W_MIN = 0.40;  // panel size as a fraction of its cell
static const float PANEL_W_RNG = 0.50;
static const float PANEL_H_MIN = 0.22;
static const float PANEL_H_RNG = 0.42;

// What a panel *is*. Cumulative thresholds on one hash, read off in a comparison
// chain, so a panel draws one kind and only the winning branch costs anything.
static const float K_TEXT      = 0.660;  // typed pseudo-text (the commonest)
static const float K_BARS      = 0.725;  // bar chart
static const float K_LINE      = 0.765;  // line chart
static const float K_PROG      = 0.875;  // progress bars
static const float K_PIE       = 0.915;  // ring gauge -- the rest are wireframe

// Text panels
static const float ROWS        = 9.0;   // content rows per panel
static const float SEG_MIN     = 8.0;   // character slots per row
static const float SEG_RNG     = 16.0;
static const float ROW_FILL    = 0.60;  // share of slots carrying a mark
static const float BLOCK_H     = 0.32;  // mark height, as a fraction of the row
static const float BLOCK_MIN   = 0.15;  // mark width, as a fraction of its slot
static const float BLOCK_RNG   = 0.55;
static const float RULE_SHARE  = 0.20;  // share of rows drawn as a full-width hairline
static const float RULE_H      = 0.09;
static const float TYPE_RATE   = 0.16;  // type-hold-retype cycles per second
static const float TYPE_FRAC   = 0.34;  // fraction of that cycle spent typing
static const float CURSOR_LIFT = 0.60;  // extra brightness on the mark at the head

// Bar charts
static const float BAR_N_MIN   = 5.0;   // bars per panel
static const float BAR_N_RNG   = 9.0;
static const float BAR_W       = 0.42;  // bar width, as a fraction of its slot
static const float BAR_MIN     = 0.12;  // bar height range, as a fraction of the panel
static const float BAR_RNG     = 0.80;
static const float BAR_RATE    = 0.22;  // re-rolls per second

// Line charts
static const float LINE_PTS    = 8.0;   // vertices across the panel
static const float LINE_W      = 0.022;  // trace thickness, in panel-local units
static const float LINE_RATE   = 0.18;
static const float LINE_LO     = 0.12;  // the band the trace stays inside
static const float LINE_SPAN   = 0.76;
static const float LINE_FILL   = 0.10;  // brightness of the wash under the trace

// Progress bars
static const float PROG_ROWS   = 4.0;
static const float PROG_H      = 0.34;  // bar height, as a fraction of its row
static const float PROG_RATE   = 0.12;
static const float PROG_TRACK  = 0.32;  // brightness of the unfilled track
static const float PROG_LO     = 0.08;  // fill range, so a bar is never quite empty/full
static const float PROG_SPAN   = 0.86;

// Ring gauges
static const float PIE_R       = 0.24;  // radius, as a fraction of the panel's short side
static const float PIE_W       = 0.06;  // ring thickness, as a fraction of the radius
static const float PIE_RATE    = 0.09;
static const float PIE_TRACK   = 0.50;  // brightness of the unswept ring

// Wireframes
static const float WIRE_NX     = 6.0;   // mesh divisions
static const float WIRE_NY     = 4.0;
static const float WIRE_DIAG   = 0.50;  // share that also carry diagonals
static const float WIRE_ALPHA  = 0.50;

// Panel chrome and shading
static const float FRAME_SHARE = 0.45;  // share of panels carrying an outline
static const float FRAME_ALPHA = 0.55;
static const float WARM_SHARE  = 0.14;  // share of marks struck in the warm accent
static const float NEAR_GLOW   = 0.55;  // how far the nearest panels pale toward white
static const float DEPTH_DIM   = 0.52;  // brightness of the furthest plane vs the nearest.
                                    // Without this the field reads flat: every plane
                                    // draws at the same strength, so the eye gets the
                                    // *scale* cue and no aerial one, and a big near
                                    // panel looks like a big panel rather than a
                                    // close one
static const float RESOLVE     = 0.85;  // fade a panel out past this many pixels per row

// Concentration lines -- the radial speed streaks
static const float CONC_SECTORS = 220.0; // angular slots around the vanishing point
static const float CONC_COUNT   = 4.0;   // how many of them carry a streak. A pixel only
                                     // ever sees its own sector, so this cannot be a
                                     // hard cap -- it is the *expected* number, set by
                                     // keeping a COUNT/SECTORS share of the draws
static const float CONC_CELL    = 0.34;  // streak slot length, as a fraction of the radius
static const float CONC_DASH    = 0.55;  // dash length within its slot
static const float CONC_RATE    = 0.20;  // outward drift, fraction of the radius/second
static const float CONC_PX      = 2.6;   // streak width, pixels
static const float CONC_ALPHA   = 0.95;
static const float CONC_IN      = 0.16;  // radius (fraction) the streaks start at
static const float CONC_RAMP    = 0.26;  // ...and how far they take to reach full strength
static const float CONC_HEAD    = 0.60;  // how far a leading edge pales toward white

static const float LIFE_RATE   = 0.167; // panel appear-hold-vanish cycles per second.
                                    // (see HOLOGRAM_MSL for the rationale)
static const float LIFE_IN     = 0.12;  // fraction of a life spent fading up
static const float LIFE_OUT    = 0.18;  // ...and fading out

// The ambient field -- see the MSL twin.
static const float AMB_CELL_PX  = 170.0; // ambient cell size, pixels
static const float AMB_KEEP     = 0.55;  // share of cells carrying an object
static const float AMB_MAX_R    = 70.0;  // bound on an object's reach: the jitter below is
static const float AMB_DRIFT_X  = 5.0;   // field drift, pixels/second
static const float AMB_DRIFT_Y  = -3.0;
static const float AMB_ORBIT    = 0.05;  // per-object orbit, turns/second
static const float AMB_ORBIT_R  = 9.0;   // ...and its radius, pixels
static const float AMB_K_DOT    = 0.60;  // kind mix: dot / stroke
static const float AMB_DOT_R    = 40.0;
static const float AMB_DOT_A    = 0.45;
static const float AMB_LINE_L   = 80.0;
static const float AMB_LINE_W   = 1.4;
static const float AMB_LINE_A   = 0.30;
static const float AMB_SOFT     = 7.0;   // edge softness, pixels -- these read as

// The fast layer -- see the MSL twin.
static const float FAST_LANE_PX = 38.0;  // lane pitch, pixels
static const float FAST_KEEP    = 0.42;  // share of lanes carrying traffic
static const float FAST_CELL_PX = 150.0; // slot length along a lane, pixels
static const float FAST_FILL    = 0.55;  // share of slots carrying an object
static const float FAST_RATE    = 260.0; // lane speed, pixels/second
static const float FAST_DASH    = 0.16;  // dash length, as a fraction of its slot
static const float FAST_LINE_W  = 1.3;   // dash thickness, pixels
static const float FAST_DOT_R   = 2.6;   // dot radius, pixels
static const float FAST_TICK_H  = 15.0;  // upright tick height, pixels (before variance)
static const float FAST_TICK_W  = 1.6;   // ...and its width
static const float FAST_BURST   = 0.30;  // a tick object is a *burst* of bars, spanning
static const float FAST_TICK_N  = 8.0;   // this fraction of its slot, this many bars
static const float FAST_TICK_FILL = 0.70;// ...of which this share are actually drawn
static const float FAST_DOT_MIX = 0.30;  // kind mix, cumulative: dot / upright tick /
static const float FAST_TICK_MIX = 0.66; // horizontal dash
static const float FAST_REACH   = 17.0;  // the tallest a lane's contents can reach, for
                                     // the early-out. A tick varies up to 2x its
                                     // nominal height, so this is not FAST_TICK_H
static const float FAST_ALPHA   = 0.85;
static const float FAST_HEAD    = 0.70;  // how far a dash's leading edge pales to white
static const float FAST_WRAP    = 4096.0;

static const float CYCLE_WRAP   = 512.0; // keeps the hash inputs exact -- see the note on
static const float CONC_WRAP    = 4096.0;// folding time in DATASTREAM_MSL
static const float TAU          = 6.283185307;

float3 hash33(float2 p) {
    float3 v = frac(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return frac((v.xxy + v.yzz) * v.zyx);
}

// A value that re-rolls on a fixed beat and eases between draws, so charts move
// rather than jump. Returns the eased value; `gen` is the draw it is heading to.
float stepped(float2 seed, float beat, float phase) {
    float ct = beat + phase;
    float gen = floor(ct);
    float a = hash33(seed + float2(gen * 53.0, 0.0)).x;
    float b = hash33(seed + float2((gen + 1.0) * 53.0, 0.0)).x;
    return lerp(a, b, smoothstep(0.0, 1.0, frac(ct)));
}

// The ambient field: one soft object per screen-space cell, drifting as a whole and
// orbiting within its cell. The jitter is clamped so an object cannot leave the cell
// that owns it, which is what lets a pixel consult exactly one cell -- the same
// bounded-jitter trick the wave uses, and the reason this layer is nearly free.
//
// Nothing here takes part in the depth sweep. That is the point: every other element
// flies at the viewer, so the scene had exactly one kind of motion, and a layer that
// merely drifts across it reads as depth of field rather than as more traffic.
float ambient_field(float2 p, float t) {
    float2 q = p + float2(t * AMB_DRIFT_X, t * AMB_DRIFT_Y);
    float2 cell = floor(q / AMB_CELL_PX);
    float2 f = q - cell * AMB_CELL_PX;
    float3 h = hash33(cell + 91.0);
    if (h.x > AMB_KEEP) { return 0.0; }

    float3 g = hash33(cell * 1.7 + 13.0);
    float span = AMB_CELL_PX - 2.0 * AMB_MAX_R;
    // HLSL vector constructors take one argument per component -- there is no scalar
    // broadcast, which is what the MSL twin's ``float2(AMB_CELL_PX * 0.5)`` relies on.
    float2 c = float2(AMB_CELL_PX * 0.5, AMB_CELL_PX * 0.5) + (g.xy - 0.5) * span;
    float ang = t * AMB_ORBIT * TAU * (0.6 + 0.8 * g.z) + h.z * TAU;
    c += float2(cos(ang), sin(ang)) * AMB_ORBIT_R;

    float2 d2 = f - c;
    float d = length(d2);
    if (h.y < AMB_K_DOT) {
        // A squared falloff, not a smoothstep-bounded disc: an out-of-focus
        // highlight has no edge. (Cubed, the first try, collapses the visible core
        // to a point -- the dots read as dust rather than as lights.)
        float r = AMB_DOT_R * (0.5 + 0.9 * g.x);
        float k = max(0.0, 1.0 - d / r);
        return k * k * AMB_DOT_A;
    }
    float a2 = g.z * TAU;
    float2 dir = float2(cos(a2), sin(a2));
    float half_len = AMB_LINE_L * 0.5 * (0.5 + 0.9 * g.x);
    float along = clamp(dot(d2, dir), -half_len, half_len);
    return (1.0 - smoothstep(AMB_LINE_W, AMB_LINE_W + AMB_SOFT,
                             length(d2 - dir * along))) * AMB_LINE_A;
}

// Bright traffic running along horizontal lanes: short dashes with a hot leading
// edge, and dots riding the same slots. Folded like the datastream's lanes -- the
// fraction places the pixel in its slot, the integer only names it -- so a pixel
// consults exactly one cell however long the app has been running.
//
// Returns coverage in .x and how much of it is leading edge in .y.
static inline float2 fast_field(float2 pos, float t) {
    float lane = floor(pos.y / FAST_LANE_PX);
    float dy = abs(pos.y - (lane + 0.5) * FAST_LANE_PX);
    // Everything in a lane hugs its centre line, so most pixels leave immediately.
    if (dy > FAST_REACH) { return float2(0.0, 0.0); }

    float3 lh = hash33(float2(lane, 71.0));
    if (lh.x > FAST_KEEP) { return float2(0.0, 0.0); }

    float speed = FAST_RATE * (0.6 + 0.8 * lh.y);
    float shift = t * speed / FAST_CELL_PX;
    float shiftI = floor(shift);
    float uu = pos.x / FAST_CELL_PX + (shift - shiftI);
    float slot = floor(uu);
    float fx = uu - slot;
    float3 sh = hash33(float2(fmod(slot - shiftI, FAST_WRAP), lane));
    if (sh.x > FAST_FILL) { return float2(0.0, 0.0); }

    if (sh.y < FAST_DOT_MIX) {
        float d = length(float2(fx * FAST_CELL_PX, dy));
        return float2((1.0 - smoothstep(FAST_DOT_R, FAST_DOT_R + 1.2, d))
                      * FAST_ALPHA, 0.0);
    }
    if (sh.y < FAST_TICK_MIX) {
        // A burst of upright bars -- the barcode the reference runs along its bands.
        // A single bar per slot (the first try) scatters into isolated tally marks;
        // it is the *cluster* that reads as a packet of data going past. Heights vary
        // widely on purpose too: a run of equal bars reads as a ruler.
        if (fx > FAST_BURST) { return float2(0.0, 0.0); }
        float gx = fx / FAST_BURST * FAST_TICK_N;
        float bar = floor(gx);
        float gf = gx - bar;
        float3 th = hash33(float2(bar + slot * 17.0, lane + 5.0));
        if (th.x > FAST_TICK_FILL) { return float2(0.0, 0.0); }
        float half_h = FAST_TICK_H * (0.35 + 1.1 * th.y);
        float pitch = FAST_BURST * FAST_CELL_PX / FAST_TICK_N;   // bar spacing, px
        float covX = 1.0 - smoothstep(FAST_TICK_W * 0.5, FAST_TICK_W * 0.5 + 1.0,
                                      gf * pitch);
        float covY = 1.0 - smoothstep(half_h, half_h + 1.0, dy);
        return float2(covX * covY * FAST_ALPHA, 0.0);
    }
    float dash = FAST_DASH * (0.4 + 1.2 * sh.z);
    float aa = 1.0 / FAST_CELL_PX;
    float covX = smoothstep(0.0, aa, fx) * (1.0 - smoothstep(dash - aa, dash, fx));
    float covY = 1.0 - smoothstep(FAST_LINE_W * 0.5, FAST_LINE_W * 0.5 + 1.0, dy);
    float a = covX * covY * FAST_ALPHA;
    return float2(a, a * (1.0 - smoothstep(0.0, dash * 0.35, fx)));
}

// One panel's contents, in panel-local coordinates (0..1 on each axis). Returns
// coverage in .x and how much of it is struck in the warm accent in .y.
//
// `pixCell` is one screen pixel expressed in *cell* units -- the panel's own axes
// are anisotropic (it is pw x panelH of a cell), so each branch converts as it needs
// to. Everything is antialiased against that rather than against fwidth: the caller
// reaches this under heavily non-uniform branching, where a derivative is undefined.
float2 panel_content(float lx, float ly, float pixCell,
                                   float pw, float panelH, float2 salt,
                                   float kind, float kvar, float t) {
    float pixX = pixCell / pw;          // one pixel, in panel-local x
    float pixY = pixCell / panelH;      // ...and y
    float a = 0.0;
    float acc = 0.0;

    if (kind < K_TEXT) {
        // --- typed pseudo-text ------------------------------------------------
        float ry = ly * ROWS;
        float row = floor(ry);
        float fy = ry - row;
        float aaY = pixY * ROWS;
        float3 rh = hash33(salt + float2(row * 7.0, 3.0));
        if (rh.x < RULE_SHARE) {
            a = 1.0 - smoothstep(RULE_H * 0.5, RULE_H * 0.5 + aaY, abs(fy - 0.5));
        } else {
            float segs = floor(SEG_MIN + SEG_RNG * rh.y);
            float sx = lx * segs;
            float seg = floor(sx);
            float fx = sx - seg;
            // A row types out left to right, holds, then retypes with fresh content.
            // Re-rolling every slot at once (what this did before) is what made the
            // marks read as noise rather than as characters: text has a writing
            // *order*, and the order is most of what identifies it as text.
            float ct = t * TYPE_RATE + rh.z * 7.0;
            float gen = floor(ct);
            float head = clamp(frac(ct) / TYPE_FRAC, 0.0, 1.0) * segs;
            if (seg < head) {
                float3 sh = hash33(float2(seg + gen * 131.0, salt.y + row));
                if (sh.x < ROW_FILL) {
                    float bw = BLOCK_MIN + BLOCK_RNG * sh.y;
                    float covX = 1.0 - smoothstep(bw - pixX * segs, bw, fx);
                    float covY = 1.0 - smoothstep(BLOCK_H * 0.5,
                                                  BLOCK_H * 0.5 + aaY, abs(fy - 0.5));
                    a = covX * covY;
                    // The mark under the head burns brighter for a slot or so -- the
                    // caret, and the cue that reads as "this is being written now".
                    a *= 1.0 + CURSOR_LIFT * (1.0 - smoothstep(0.0, 1.5, head - seg));
                    acc = (sh.z > 1.0 - WARM_SHARE) ? a : 0.0;
                }
            }
        }
    } else if (kind < K_BARS) {
        // --- bar chart --------------------------------------------------------
        float bars = floor(BAR_N_MIN + BAR_N_RNG * kvar);
        float bx = lx * bars;
        float bar = floor(bx);
        float fx = bx - bar;
        float h = BAR_MIN + BAR_RNG * stepped(salt + float2(bar, 0.0),
                                              t * BAR_RATE, kvar * 5.0);
        float covX = 1.0 - smoothstep(BAR_W - pixX * bars, BAR_W, fx);
        // ly runs downward, so a bar standing on the floor is (1 - ly) < h.
        float covY = 1.0 - smoothstep(h - pixY, h, 1.0 - ly);
        a = covX * covY;
        a = max(a, 1.0 - smoothstep(pixY * 0.5, pixY * 1.5, 1.0 - ly));   // baseline
    } else if (kind < K_LINE) {
        // --- line chart -------------------------------------------------------
        float px = lx * LINE_PTS;
        float ip = floor(px);
        float fp = px - ip;
        float y0 = LINE_LO + LINE_SPAN * stepped(salt + float2(ip, 0.0),
                                                 t * LINE_RATE, kvar * 3.0);
        float y1 = LINE_LO + LINE_SPAN * stepped(salt + float2(ip + 1.0, 0.0),
                                                 t * LINE_RATE, kvar * 3.0);
        float yl = lerp(y0, y1, fp);
        // Perpendicular distance, not vertical: without the slope correction a steep
        // leg of the trace draws several times thicker than a flat one.
        float slope = (y1 - y0) * LINE_PTS;
        float d = abs(ly - yl) / sqrt(1.0 + slope * slope);
        a = 1.0 - smoothstep(LINE_W * 0.5, LINE_W * 0.5 + pixY, d);
        a = max(a, (ly > yl) ? LINE_FILL : 0.0);      // the wash under the trace
    } else if (kind < K_PROG) {
        // --- progress bars ----------------------------------------------------
        float ry = ly * PROG_ROWS;
        float row = floor(ry);
        float fy = ry - row;
        float aaY = pixY * PROG_ROWS;
        float3 rh = hash33(salt + float2(row * 11.0, 17.0));
        float band = 1.0 - smoothstep(PROG_H * 0.5, PROG_H * 0.5 + aaY, abs(fy - 0.5));
        float p = PROG_LO + PROG_SPAN * stepped(salt + float2(row * 3.0, 9.0),
                                                t * PROG_RATE, rh.z * 4.0);
        float fill = band * (1.0 - smoothstep(p - pixX, p, lx));
        a = max(band * PROG_TRACK, fill);
        acc = (rh.y > 1.0 - WARM_SHARE) ? fill : 0.0;
    } else if (kind < K_PIE) {
        // --- ring gauge -------------------------------------------------------
        // Back into cell units, where the axes are isotropic again -- drawn in
        // panel-local units a circle would come out as an ellipse.
        float2 q = float2((lx - 0.5) * pw, (ly - 0.5) * panelH);
        float R = PIE_R * min(pw, panelH);
        float r = length(q);
        float ring = 1.0 - smoothstep(R * PIE_W, R * PIE_W + pixCell, abs(r - R));
        float band = 1.0 - smoothstep(R * PIE_W * 2.4, R * PIE_W * 2.4 + pixCell,
                                      abs(r - R));
        float sweep = stepped(salt + float2(31.0, 0.0), t * PIE_RATE, kvar * 6.0);
        float ang = atan2(q.y, q.x) / TAU + 0.5;
        float arc = (ang < sweep) ? band : 0.0;
        a = max(ring * PIE_TRACK, arc);
        acc = arc;
    } else {
        // --- wireframe --------------------------------------------------------
        float u = lx * WIRE_NX;
        float v = ly * WIRE_NY;
        float wu = pixX * WIRE_NX;
        float wv = pixY * WIRE_NY;
        a = max(1.0 - smoothstep(0.5 * wu, 1.5 * wu, abs(u - round(u))),
                1.0 - smoothstep(0.5 * wv, 1.5 * wv, abs(v - round(v))));
        if (kvar < WIRE_DIAG) {
            float d = u + v;
            float wd = wu + wv;
            a = max(a, 1.0 - smoothstep(0.5 * wd, 1.5 * wd, abs(d - round(d))));
        }
        a *= WIRE_ALPHA;
    }
    return float2(a, acc);
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float2 halfRes = resolution * 0.5;
    // View-height units in both axes, so a panel stays square whatever the window
    // aspect. (The starfield normalises per-axis instead and lets its field stretch;
    // a stretching *drawing* would read as a mistake where a stretching dot does not.)
    float2 P = pos.xy - halfRes;
    float2 n = P / halfRes.y;
    float t = time;

    float lit = 0.0;    // coverage at this pixel
    float warm = 0.0;   // the share of it struck in the accent, for the hue
    float hot = 0.0;    // nearness of whatever covered it, for the white lift

    for (int i = 0; i < LAYERS; ++i) {
        // Planes evenly offset in phase, so the field always holds panels at every
        // stage of the approach rather than pulsing in unison.
        float raw = t * RATE + float(i) / float(LAYERS);
        float travel = frac(raw);
        float cycle = fmod(floor(raw), CYCLE_WRAP);   // re-rolls a plane's content
        // Even steps in 1/z are even steps *on screen* (the same reason the wave
        // stacks its slabs this way). Stepping z linearly instead spends almost every
        // plane in the far half, where 1/z barely moves -- which is why the field
        // came out as one size of panel repeated rather than a depth of them. This
        // spreads the planes evenly across apparent scale, so a big near panel, a
        // mid one and the far haze are all on screen at once.
        float z = 1.0 / lerp(1.0 / Z_FAR, 1.0 / Z_NEAR, travel);
        float alpha = min(1.0, travel / FADE_IN)
                    * (1.0 - smoothstep(1.0 - FADE_OUT, 1.0, travel));
        if (alpha <= 0.002) { continue; }

        // Run the projection backwards: at this depth the ray crosses the plane
        // here, so this is the only cell that can cover this pixel.
        float2 s = n * z;
        float2 cell = floor(s * GRID);
        float2 f = s * GRID - cell;

        // Each panel lives and dies on its own clock, much shorter than its plane's
        // traversal: it fades up, holds, fades out, and the cell is redrawn with a
        // fresh one. Decoupling the two is the whole point -- the plane's sweep used
        // to serve as the panel lifetime as well, so slowing the flight would have
        // made every panel linger proportionally longer. Now the flight can be slow
        // and the field still turns over quickly.
        float3 lh = hash33(cell * 0.61 + float2(float(i) * 3.0, 7.0));
        float lifeT = t * LIFE_RATE + lh.x * 11.0;
        float lifeGen = fmod(floor(lifeT), CYCLE_WRAP);
        float lifePh = frac(lifeT);
        float life = smoothstep(0.0, LIFE_IN, lifePh)
                   * (1.0 - smoothstep(1.0 - LIFE_OUT, 1.0, lifePh));
        if (life <= 0.002) { continue; }

        // ``lifeGen`` rides in every panel hash below, so a cell that comes back
        // comes back as a different panel rather than as the same one blinking.
        float3 ph = hash33(cell + float2(cycle * 13.0 + float(i) * 57.0 + lifeGen * 29.0,
                                         cycle * 7.0 - float(i) * 23.0 + lifeGen * 41.0));
        if (ph.x > PANEL_KEEP) { continue; }     // this cell is empty space

        float3 qh = hash33(cell * 1.37 + float2(float(i) * 11.0,
                                                cycle * 3.0 + lifeGen * 17.0));
        float pw = PANEL_W_MIN + PANEL_W_RNG * ph.y;
        float panelH = PANEL_H_MIN + PANEL_H_RNG * ph.z;
        float lx = (f.x - (1.0 - pw) * qh.x) / pw;   // panel-local, 0..1
        float ly = (f.y - (1.0 - panelH) * qh.y) / panelH;
        if (lx < 0.0 || lx > 1.0 || ly < 0.0 || ly > 1.0) { continue; }

        // One pixel, in cell units. Derived from the depth rather than from fwidth:
        // the branching above is non-uniform, which makes a derivative undefined,
        // and every antialiasing width downstream depends on this.
        float pixCell = z * GRID / halfRes.y;
        // Past the point where a pixel spans a good part of a row, the panel cannot
        // be read at all; fading it out is what keeps the far field from boiling.
        float resolve = 1.0 - smoothstep(RESOLVE * 0.5, RESOLVE,
                                         (pixCell / panelH) * ROWS);
        if (resolve <= 0.0) { continue; }

        // ``travel``, not z: with the 1/z stepping above it is travel that is linear
        // in apparent scale, so it is the measure that makes the aerial cue agree
        // with the size cue.
        float depth = 1.0 - travel;                         // 0 near, 1 far
        float bright = (0.3 + 0.7 * ph.y) * alpha * life * resolve
                     * lerp(1.0, DEPTH_DIM, depth);

        float2 r = panel_content(lx, ly, pixCell, pw, panelH,
                                 float2(cell.x * 13.0 + float(i),
                                        cell.y * 29.0 + cycle + lifeGen * 7.0),
                                 qh.z, frac(qh.y * 11.7), t);
        float a = r.x;

        // A hairline outline on some panels, which is most of what makes a cluster
        // of marks read as a *panel* rather than as loose debris.
        if (frac(qh.x * 7.3) < FRAME_SHARE) {
            float edge = min(min(lx, 1.0 - lx) * pw,
                             min(ly, 1.0 - ly) * panelH) / pixCell;
            a = max(a, (1.0 - smoothstep(0.6, 1.6, edge)) * FRAME_ALPHA);
        }

        a *= bright;
        lit = max(lit, a);
        warm = max(warm, r.y * bright);
        hot = max(hot, a * (1.0 - z / Z_FAR));
    }

    // --- concentration lines --------------------------------------------------
    // Radial speed streaks raking outward from the vanishing point. This is the
    // datastream's dash-in-a-slot wrapped around the centre: a pixel finds its
    // angular sector and its slot along the ray and consults exactly one cell, so a
    // whole field of them costs about what one more panel plane would. They sell the
    // forward motion the panels only imply -- the panels grow, but nothing *streaks*.
    float rad = length(P);
    float rn = rad / length(halfRes);          // 0 at the centre, 1 at the corner
    if (rn > CONC_IN && rad > 1.0) {
        float ang = atan2(P.y, P.x) / TAU + 0.5;
        // Wrapped, or the slot at ang = 1 would be a different draw from the one at
        // ang = 0 and the field would carry a seam straight out along -x.
        float sector = fmod(floor(ang * CONC_SECTORS), CONC_SECTORS);
        float3 ch = hash33(float2(sector, 4.0));
        if (ch.x * CONC_SECTORS < CONC_COUNT) {
            // Folded like the datastream's lanes: the fraction places the pixel in
            // its slot, the integer only names it.
            float shift = t * CONC_RATE * (0.5 + 1.2 * ch.y) / CONC_CELL;
            float shiftI = floor(shift);
            float uu = rn / CONC_CELL - (shift - shiftI);
            float slot = floor(uu);
            float fu = uu - slot;
            float3 dh = hash33(float2(fmod(slot - shiftI, CONC_WRAP), sector));
            if (dh.x < 0.75) {
                float dash = CONC_DASH * (0.35 + 0.9 * dh.y);
                // Constant width in pixels, so the angular half-width has to shrink
                // as the radius grows -- otherwise a streak fans out into a wedge.
                float dPx = abs(frac(ang * CONC_SECTORS) - 0.5) / CONC_SECTORS * TAU * rad;
                float covA = 1.0 - smoothstep(CONC_PX * 0.5, CONC_PX * 0.5 + 1.0, dPx);
                float covR = smoothstep(0.0, 0.02, fu)
                           * (1.0 - smoothstep(dash - 0.02, dash, fu));
                float fade = smoothstep(CONC_IN, CONC_IN + CONC_RAMP, rn);
                float a = covA * covR * fade * CONC_ALPHA * (0.5 + 0.5 * dh.z);
                lit = max(lit, a);
                hot = max(hot, a * (1.0 - smoothstep(0.0, 0.3, fu)) * CONC_HEAD);
            }
        }
    }

    // The ambient layer sits under the rest: dim, soft and cool, never warm or hot.
    lit = max(lit, ambient_field(pos.xy, t));

    // The fast layer, on top: this is the element that actually moves.
    float2 fastR = fast_field(pos.xy, t);
    lit = max(lit, fastR.x);
    hot = max(hot, fastR.y * FAST_HEAD);

    // The accent is the ink with red and blue swapped -- amber out of this scene's
    // cyan, and a theme-derived hue out of anything else (see the module note).
    float3 rgb = lerp(ink.rgb, ink.zyx, clamp(warm / max(lit, 1e-4), 0.0, 1.0));
    rgb = lerp(rgb, float3(1.0, 1.0, 1.0), clamp(hot, 0.0, 1.0) * NEAR_GLOW);

    rgb = lerp(backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * opacity);
    return float4(rgb, 1.0);
}
"""

HOLOGRAM_GLSL = """
float pk_fmod(float a, float b) { return a - b * trunc(a / b); }

// --- tunables ---------------------------------------------------------------
const int   LAYERS      = 12;    // depth planes; each a full grid of panels
const float Z_FAR       = 3.0;   // spawn depth / closest approach. The divide
const float Z_NEAR      = 0.45;  // blows up as Z_NEAR reaches 0
const float RATE        = 0.015;  // fraction of the depth range crossed per second
const float FADE_IN     = 0.30;  // fraction of the travel spent fading in
const float FADE_OUT    = 0.18;  // ...and fading out as it sweeps past. Long,
                                    // because a plane at Z_NEAR is wider than the
                                    // window: a panel has to be gone before it
                                    // becomes the whole screen and pops out
const float GRID        = 3.20;  // panel cells per unit of plane
const float PANEL_KEEP  = 0.38;  // share of cells that host a panel at all
const float PANEL_W_MIN = 0.40;  // panel size as a fraction of its cell
const float PANEL_W_RNG = 0.50;
const float PANEL_H_MIN = 0.22;
const float PANEL_H_RNG = 0.42;

// What a panel *is*. Cumulative thresholds on one hash, read off in a comparison
// chain, so a panel draws one kind and only the winning branch costs anything.
const float K_TEXT      = 0.660;  // typed pseudo-text (the commonest)
const float K_BARS      = 0.725;  // bar chart
const float K_LINE      = 0.765;  // line chart
const float K_PROG      = 0.875;  // progress bars
const float K_PIE       = 0.915;  // ring gauge -- the rest are wireframe

// Text panels
const float ROWS        = 9.0;   // content rows per panel
const float SEG_MIN     = 8.0;   // character slots per row
const float SEG_RNG     = 16.0;
const float ROW_FILL    = 0.60;  // share of slots carrying a mark
const float BLOCK_H     = 0.32;  // mark height, as a fraction of the row
const float BLOCK_MIN   = 0.15;  // mark width, as a fraction of its slot
const float BLOCK_RNG   = 0.55;
const float RULE_SHARE  = 0.20;  // share of rows drawn as a full-width hairline
const float RULE_H      = 0.09;
const float TYPE_RATE   = 0.16;  // type-hold-retype cycles per second
const float TYPE_FRAC   = 0.34;  // fraction of that cycle spent typing
const float CURSOR_LIFT = 0.60;  // extra brightness on the mark at the head

// Bar charts
const float BAR_N_MIN   = 5.0;   // bars per panel
const float BAR_N_RNG   = 9.0;
const float BAR_W       = 0.42;  // bar width, as a fraction of its slot
const float BAR_MIN     = 0.12;  // bar height range, as a fraction of the panel
const float BAR_RNG     = 0.80;
const float BAR_RATE    = 0.22;  // re-rolls per second

// Line charts
const float LINE_PTS    = 8.0;   // vertices across the panel
const float LINE_W      = 0.022;  // trace thickness, in panel-local units
const float LINE_RATE   = 0.18;
const float LINE_LO     = 0.12;  // the band the trace stays inside
const float LINE_SPAN   = 0.76;
const float LINE_FILL   = 0.10;  // brightness of the wash under the trace

// Progress bars
const float PROG_ROWS   = 4.0;
const float PROG_H      = 0.34;  // bar height, as a fraction of its row
const float PROG_RATE   = 0.12;
const float PROG_TRACK  = 0.32;  // brightness of the unfilled track
const float PROG_LO     = 0.08;  // fill range, so a bar is never quite empty/full
const float PROG_SPAN   = 0.86;

// Ring gauges
const float PIE_R       = 0.24;  // radius, as a fraction of the panel's short side
const float PIE_W       = 0.06;  // ring thickness, as a fraction of the radius
const float PIE_RATE    = 0.09;
const float PIE_TRACK   = 0.50;  // brightness of the unswept ring

// Wireframes
const float WIRE_NX     = 6.0;   // mesh divisions
const float WIRE_NY     = 4.0;
const float WIRE_DIAG   = 0.50;  // share that also carry diagonals
const float WIRE_ALPHA  = 0.50;

// Panel chrome and shading
const float FRAME_SHARE = 0.45;  // share of panels carrying an outline
const float FRAME_ALPHA = 0.55;
const float WARM_SHARE  = 0.14;  // share of marks struck in the warm accent
const float NEAR_GLOW   = 0.55;  // how far the nearest panels pale toward white
const float DEPTH_DIM   = 0.52;  // brightness of the furthest plane vs the nearest.
                                    // Without this the field reads flat: every plane
                                    // draws at the same strength, so the eye gets the
                                    // *scale* cue and no aerial one, and a big near
                                    // panel looks like a big panel rather than a
                                    // close one
const float RESOLVE     = 0.85;  // fade a panel out past this many pixels per row

// Concentration lines -- the radial speed streaks
const float CONC_SECTORS = 220.0; // angular slots around the vanishing point
const float CONC_COUNT   = 4.0;   // how many of them carry a streak. A pixel only
                                     // ever sees its own sector, so this cannot be a
                                     // hard cap -- it is the *expected* number, set by
                                     // keeping a COUNT/SECTORS share of the draws
const float CONC_CELL    = 0.34;  // streak slot length, as a fraction of the radius
const float CONC_DASH    = 0.55;  // dash length within its slot
const float CONC_RATE    = 0.20;  // outward drift, fraction of the radius/second
const float CONC_PX      = 2.6;   // streak width, pixels
const float CONC_ALPHA   = 0.95;
const float CONC_IN      = 0.16;  // radius (fraction) the streaks start at
const float CONC_RAMP    = 0.26;  // ...and how far they take to reach full strength
const float CONC_HEAD    = 0.60;  // how far a leading edge pales toward white

const float LIFE_RATE   = 0.167; // panel appear-hold-vanish cycles per second.
                                    // Deliberately independent of RATE: see the note
                                    // in the loop on why the two had to come apart
const float LIFE_IN     = 0.12;  // fraction of a life spent fading up
const float LIFE_OUT    = 0.18;  // ...and fading out

// The ambient field: soft out-of-focus dots, rings and strokes drifting in *screen*
// space, with no part in the depth sweep. Everything else here flies at the viewer,
// which gives the scene one motion and one only; this layer drifts across it instead,
// so there is something in frame that is simply there rather than arriving.
const float AMB_CELL_PX  = 170.0; // ambient cell size, pixels
const float AMB_KEEP     = 0.55;  // share of cells carrying an object
const float AMB_MAX_R    = 70.0;  // bound on an object's reach: the jitter below is
                                     // clamped so nothing leaves its own cell, which
                                     // is what keeps this to one lookup per pixel
const float AMB_DRIFT_X  = 5.0;   // field drift, pixels/second
const float AMB_DRIFT_Y  = -3.0;
const float AMB_ORBIT    = 0.05;  // per-object orbit, turns/second
const float AMB_ORBIT_R  = 9.0;   // ...and its radius, pixels
const float AMB_K_DOT    = 0.60;  // kind mix: dot / stroke
const float AMB_DOT_R    = 40.0;
const float AMB_DOT_A    = 0.45;
const float AMB_LINE_L   = 80.0;
const float AMB_LINE_W   = 1.4;
const float AMB_LINE_A   = 0.30;
const float AMB_SOFT     = 7.0;   // edge softness, pixels -- these read as
                                     // out-of-focus, so the falloff is wide

// The fast layer: bright dashes and dots running along horizontal lanes, far quicker
// than anything else here. The ambient field drifts at a few pixels a second and the
// panels creep toward the viewer; this is the only element with real speed, and it is
// what stops the scene reading as a still image with a slow zoom.
const float FAST_LANE_PX = 38.0;  // lane pitch, pixels
const float FAST_KEEP    = 0.42;  // share of lanes carrying traffic
const float FAST_CELL_PX = 150.0; // slot length along a lane, pixels
const float FAST_FILL    = 0.55;  // share of slots carrying an object
const float FAST_RATE    = 260.0; // lane speed, pixels/second
const float FAST_DASH    = 0.16;  // dash length, as a fraction of its slot
const float FAST_LINE_W  = 1.3;   // dash thickness, pixels
const float FAST_DOT_R   = 2.6;   // dot radius, pixels
const float FAST_TICK_H  = 15.0;  // upright tick height, pixels (before variance)
const float FAST_TICK_W  = 1.6;   // ...and its width
const float FAST_BURST   = 0.30;  // a tick object is a *burst* of bars, spanning
const float FAST_TICK_N  = 8.0;   // this fraction of its slot, this many bars
const float FAST_TICK_FILL = 0.70;// ...of which this share are actually drawn
const float FAST_DOT_MIX = 0.30;  // kind mix, cumulative: dot / upright tick /
const float FAST_TICK_MIX = 0.66; // horizontal dash
const float FAST_REACH   = 17.0;  // the tallest a lane's contents can reach, for
                                     // the early-out. A tick varies up to 2x its
                                     // nominal height, so this is not FAST_TICK_H
const float FAST_ALPHA   = 0.85;
const float FAST_HEAD    = 0.70;  // how far a dash's leading edge pales to white
const float FAST_WRAP    = 4096.0;

const float CYCLE_WRAP   = 512.0; // keeps the hash inputs exact -- see the note on
const float CONC_WRAP    = 4096.0;// folding time in DATASTREAM_MSL
const float TAU          = 6.283185307;

vec3 hash33(vec2 p) {
    vec3 v = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    v += dot(v, v.yzx + 33.33);
    return fract((v.xxy + v.yzz) * v.zyx);
}

// A value that re-rolls on a fixed beat and eases between draws, so charts move
// rather than jump. Returns the eased value; `gen` is the draw it is heading to.
float stepped(vec2 seed, float beat, float phase) {
    float ct = beat + phase;
    float gen = floor(ct);
    float a = hash33(seed + vec2(gen * 53.0, 0.0)).x;
    float b = hash33(seed + vec2((gen + 1.0) * 53.0, 0.0)).x;
    return mix(a, b, smoothstep(0.0, 1.0, fract(ct)));
}

// The ambient field: one soft object per screen-space cell, drifting as a whole and
// orbiting within its cell. The jitter is clamped so an object cannot leave the cell
// that owns it, which is what lets a pixel consult exactly one cell -- the same
// bounded-jitter trick the wave uses, and the reason this layer is nearly free.
//
// Nothing here takes part in the depth sweep. That is the point: every other element
// flies at the viewer, so the scene had exactly one kind of motion, and a layer that
// merely drifts across it reads as depth of field rather than as more traffic.
float ambient_field(vec2 p, float t) {
    vec2 q = p + vec2(t * AMB_DRIFT_X, t * AMB_DRIFT_Y);
    vec2 cell = floor(q / AMB_CELL_PX);
    vec2 f = q - cell * AMB_CELL_PX;
    vec3 h = hash33(cell + 91.0);
    if (h.x > AMB_KEEP) { return 0.0; }

    vec3 g = hash33(cell * 1.7 + 13.0);
    float span = AMB_CELL_PX - 2.0 * AMB_MAX_R;
    vec2 c = vec2(AMB_CELL_PX * 0.5) + (g.xy - 0.5) * span;
    float ang = t * AMB_ORBIT * TAU * (0.6 + 0.8 * g.z) + h.z * TAU;
    c += vec2(cos(ang), sin(ang)) * AMB_ORBIT_R;

    vec2 d2 = f - c;
    float d = length(d2);
    if (h.y < AMB_K_DOT) {
        // A squared falloff, not a smoothstep-bounded disc: an out-of-focus
        // highlight has no edge. (Cubed, the first try, collapses the visible core
        // to a point -- the dots read as dust rather than as lights.)
        float r = AMB_DOT_R * (0.5 + 0.9 * g.x);
        float k = max(0.0, 1.0 - d / r);
        return k * k * AMB_DOT_A;
    }
    float a2 = g.z * TAU;
    vec2 dir = vec2(cos(a2), sin(a2));
    float half_len = AMB_LINE_L * 0.5 * (0.5 + 0.9 * g.x);
    float along = clamp(dot(d2, dir), -half_len, half_len);
    return (1.0 - smoothstep(AMB_LINE_W, AMB_LINE_W + AMB_SOFT,
                             length(d2 - dir * along))) * AMB_LINE_A;
}

// Bright traffic running along horizontal lanes: short dashes with a hot leading
// edge, and dots riding the same slots. Folded like the datastream's lanes -- the
// fraction places the pixel in its slot, the integer only names it -- so a pixel
// consults exactly one cell however long the app has been running.
//
// Returns coverage in .x and how much of it is leading edge in .y.
vec2 fast_field(vec2 pos, float t) {
    float lane = floor(pos.y / FAST_LANE_PX);
    float dy = abs(pos.y - (lane + 0.5) * FAST_LANE_PX);
    // Everything in a lane hugs its centre line, so most pixels leave immediately.
    if (dy > FAST_REACH) { return vec2(0.0); }

    vec3 lh = hash33(vec2(lane, 71.0));
    if (lh.x > FAST_KEEP) { return vec2(0.0); }

    float speed = FAST_RATE * (0.6 + 0.8 * lh.y);
    float shift = t * speed / FAST_CELL_PX;
    float shiftI = floor(shift);
    float uu = pos.x / FAST_CELL_PX + (shift - shiftI);
    float slot = floor(uu);
    float fx = uu - slot;
    vec3 sh = hash33(vec2(pk_fmod(slot - shiftI, FAST_WRAP), lane));
    if (sh.x > FAST_FILL) { return vec2(0.0); }

    if (sh.y < FAST_DOT_MIX) {
        float d = length(vec2(fx * FAST_CELL_PX, dy));
        return vec2((1.0 - smoothstep(FAST_DOT_R, FAST_DOT_R + 1.2, d))
                      * FAST_ALPHA, 0.0);
    }
    if (sh.y < FAST_TICK_MIX) {
        // A burst of upright bars -- the barcode the reference runs along its bands.
        // A single bar per slot (the first try) scatters into isolated tally marks;
        // it is the *cluster* that reads as a packet of data going past. Heights vary
        // widely on purpose too: a run of equal bars reads as a ruler.
        if (fx > FAST_BURST) { return vec2(0.0); }
        float gx = fx / FAST_BURST * FAST_TICK_N;
        float bar = floor(gx);
        float gf = gx - bar;
        vec3 th = hash33(vec2(bar + slot * 17.0, lane + 5.0));
        if (th.x > FAST_TICK_FILL) { return vec2(0.0); }
        float half_h = FAST_TICK_H * (0.35 + 1.1 * th.y);
        float pitch = FAST_BURST * FAST_CELL_PX / FAST_TICK_N;   // bar spacing, px
        float covX = 1.0 - smoothstep(FAST_TICK_W * 0.5, FAST_TICK_W * 0.5 + 1.0,
                                      gf * pitch);
        float covY = 1.0 - smoothstep(half_h, half_h + 1.0, dy);
        return vec2(covX * covY * FAST_ALPHA, 0.0);
    }
    float dash = FAST_DASH * (0.4 + 1.2 * sh.z);
    float aa = 1.0 / FAST_CELL_PX;
    float covX = smoothstep(0.0, aa, fx) * (1.0 - smoothstep(dash - aa, dash, fx));
    float covY = 1.0 - smoothstep(FAST_LINE_W * 0.5, FAST_LINE_W * 0.5 + 1.0, dy);
    float a = covX * covY * FAST_ALPHA;
    return vec2(a, a * (1.0 - smoothstep(0.0, dash * 0.35, fx)));
}

// One panel's contents, in panel-local coordinates (0..1 on each axis). Returns
// coverage in .x and how much of it is struck in the warm accent in .y.
//
// `pixCell` is one screen pixel expressed in *cell* units -- the panel's own axes
// are anisotropic (it is pw x panelH of a cell), so each branch converts as it needs
// to. Everything is antialiased against that rather than against fwidth: the caller
// reaches this under heavily non-uniform branching, where a derivative is undefined.
vec2 panel_content(float lx, float ly, float pixCell,
                                   float pw, float panelH, vec2 salt,
                                   float kind, float kvar, float t) {
    float pixX = pixCell / pw;          // one pixel, in panel-local x
    float pixY = pixCell / panelH;      // ...and y
    float a = 0.0;
    float acc = 0.0;

    if (kind < K_TEXT) {
        // --- typed pseudo-text ------------------------------------------------
        float ry = ly * ROWS;
        float row = floor(ry);
        float fy = ry - row;
        float aaY = pixY * ROWS;
        vec3 rh = hash33(salt + vec2(row * 7.0, 3.0));
        if (rh.x < RULE_SHARE) {
            a = 1.0 - smoothstep(RULE_H * 0.5, RULE_H * 0.5 + aaY, abs(fy - 0.5));
        } else {
            float segs = floor(SEG_MIN + SEG_RNG * rh.y);
            float sx = lx * segs;
            float seg = floor(sx);
            float fx = sx - seg;
            // A row types out left to right, holds, then retypes with fresh content.
            // Re-rolling every slot at once (what this did before) is what made the
            // marks read as noise rather than as characters: text has a writing
            // *order*, and the order is most of what identifies it as text.
            float ct = t * TYPE_RATE + rh.z * 7.0;
            float gen = floor(ct);
            float head = clamp(fract(ct) / TYPE_FRAC, 0.0, 1.0) * segs;
            if (seg < head) {
                vec3 sh = hash33(vec2(seg + gen * 131.0, salt.y + row));
                if (sh.x < ROW_FILL) {
                    float bw = BLOCK_MIN + BLOCK_RNG * sh.y;
                    float covX = 1.0 - smoothstep(bw - pixX * segs, bw, fx);
                    float covY = 1.0 - smoothstep(BLOCK_H * 0.5,
                                                  BLOCK_H * 0.5 + aaY, abs(fy - 0.5));
                    a = covX * covY;
                    // The mark under the head burns brighter for a slot or so -- the
                    // caret, and the cue that reads as "this is being written now".
                    a *= 1.0 + CURSOR_LIFT * (1.0 - smoothstep(0.0, 1.5, head - seg));
                    acc = (sh.z > 1.0 - WARM_SHARE) ? a : 0.0;
                }
            }
        }
    } else if (kind < K_BARS) {
        // --- bar chart --------------------------------------------------------
        float bars = floor(BAR_N_MIN + BAR_N_RNG * kvar);
        float bx = lx * bars;
        float bar = floor(bx);
        float fx = bx - bar;
        float h = BAR_MIN + BAR_RNG * stepped(salt + vec2(bar, 0.0),
                                              t * BAR_RATE, kvar * 5.0);
        float covX = 1.0 - smoothstep(BAR_W - pixX * bars, BAR_W, fx);
        // ly runs downward, so a bar standing on the floor is (1 - ly) < h.
        float covY = 1.0 - smoothstep(h - pixY, h, 1.0 - ly);
        a = covX * covY;
        a = max(a, 1.0 - smoothstep(pixY * 0.5, pixY * 1.5, 1.0 - ly));   // baseline
    } else if (kind < K_LINE) {
        // --- line chart -------------------------------------------------------
        float px = lx * LINE_PTS;
        float ip = floor(px);
        float fp = px - ip;
        float y0 = LINE_LO + LINE_SPAN * stepped(salt + vec2(ip, 0.0),
                                                 t * LINE_RATE, kvar * 3.0);
        float y1 = LINE_LO + LINE_SPAN * stepped(salt + vec2(ip + 1.0, 0.0),
                                                 t * LINE_RATE, kvar * 3.0);
        float yl = mix(y0, y1, fp);
        // Perpendicular distance, not vertical: without the slope correction a steep
        // leg of the trace draws several times thicker than a flat one.
        float slope = (y1 - y0) * LINE_PTS;
        float d = abs(ly - yl) / sqrt(1.0 + slope * slope);
        a = 1.0 - smoothstep(LINE_W * 0.5, LINE_W * 0.5 + pixY, d);
        a = max(a, (ly > yl) ? LINE_FILL : 0.0);      // the wash under the trace
    } else if (kind < K_PROG) {
        // --- progress bars ----------------------------------------------------
        float ry = ly * PROG_ROWS;
        float row = floor(ry);
        float fy = ry - row;
        float aaY = pixY * PROG_ROWS;
        vec3 rh = hash33(salt + vec2(row * 11.0, 17.0));
        float band = 1.0 - smoothstep(PROG_H * 0.5, PROG_H * 0.5 + aaY, abs(fy - 0.5));
        float p = PROG_LO + PROG_SPAN * stepped(salt + vec2(row * 3.0, 9.0),
                                                t * PROG_RATE, rh.z * 4.0);
        float fill = band * (1.0 - smoothstep(p - pixX, p, lx));
        a = max(band * PROG_TRACK, fill);
        acc = (rh.y > 1.0 - WARM_SHARE) ? fill : 0.0;
    } else if (kind < K_PIE) {
        // --- ring gauge -------------------------------------------------------
        // Back into cell units, where the axes are isotropic again -- drawn in
        // panel-local units a circle would come out as an ellipse.
        vec2 q = vec2((lx - 0.5) * pw, (ly - 0.5) * panelH);
        float R = PIE_R * min(pw, panelH);
        float r = length(q);
        float ring = 1.0 - smoothstep(R * PIE_W, R * PIE_W + pixCell, abs(r - R));
        float band = 1.0 - smoothstep(R * PIE_W * 2.4, R * PIE_W * 2.4 + pixCell,
                                      abs(r - R));
        float sweep = stepped(salt + vec2(31.0, 0.0), t * PIE_RATE, kvar * 6.0);
        float ang = atan(q.y, q.x) / TAU + 0.5;
        float arc = (ang < sweep) ? band : 0.0;
        a = max(ring * PIE_TRACK, arc);
        acc = arc;
    } else {
        // --- wireframe --------------------------------------------------------
        float u = lx * WIRE_NX;
        float v = ly * WIRE_NY;
        float wu = pixX * WIRE_NX;
        float wv = pixY * WIRE_NY;
        a = max(1.0 - smoothstep(0.5 * wu, 1.5 * wu, abs(u - round(u))),
                1.0 - smoothstep(0.5 * wv, 1.5 * wv, abs(v - round(v))));
        if (kvar < WIRE_DIAG) {
            float d = u + v;
            float wd = wu + wv;
            a = max(a, 1.0 - smoothstep(0.5 * wd, 1.5 * wd, abs(d - round(d))));
        }
        a *= WIRE_ALPHA;
    }
    return vec2(a, acc);
}

vec4 puikit_bg_fragment(vec2 pos) {
    vec2 halfRes = resolution * 0.5;
    // View-height units in both axes, so a panel stays square whatever the window
    // aspect. (The starfield normalises per-axis instead and lets its field stretch;
    // a stretching *drawing* would read as a mistake where a stretching dot does not.)
    vec2 P = pos.xy - halfRes;
    vec2 n = P / halfRes.y;
    float t = time;

    float lit = 0.0;    // coverage at this pixel
    float warm = 0.0;   // the share of it struck in the accent, for the hue
    float hot = 0.0;    // nearness of whatever covered it, for the white lift

    for (int i = 0; i < LAYERS; ++i) {
        // Planes evenly offset in phase, so the field always holds panels at every
        // stage of the approach rather than pulsing in unison.
        float raw = t * RATE + float(i) / float(LAYERS);
        float travel = fract(raw);
        float cycle = pk_fmod(floor(raw), CYCLE_WRAP);   // re-rolls a plane's content
        // Even steps in 1/z are even steps *on screen* (the same reason the wave
        // stacks its slabs this way). Stepping z linearly instead spends almost every
        // plane in the far half, where 1/z barely moves -- which is why the field
        // came out as one size of panel repeated rather than a depth of them. This
        // spreads the planes evenly across apparent scale, so a big near panel, a
        // mid one and the far haze are all on screen at once.
        float z = 1.0 / mix(1.0 / Z_FAR, 1.0 / Z_NEAR, travel);
        float alpha = min(1.0, travel / FADE_IN)
                    * (1.0 - smoothstep(1.0 - FADE_OUT, 1.0, travel));
        if (alpha <= 0.002) { continue; }

        // Run the projection backwards: at this depth the ray crosses the plane
        // here, so this is the only cell that can cover this pixel.
        vec2 s = n * z;
        vec2 cell = floor(s * GRID);
        vec2 f = s * GRID - cell;

        // Each panel lives and dies on its own clock, much shorter than its plane's
        // traversal: it fades up, holds, fades out, and the cell is redrawn with a
        // fresh one. Decoupling the two is the whole point -- the plane's sweep used
        // to serve as the panel lifetime as well, so slowing the flight would have
        // made every panel linger proportionally longer. Now the flight can be slow
        // and the field still turns over quickly.
        vec3 lh = hash33(cell * 0.61 + vec2(float(i) * 3.0, 7.0));
        float lifeT = t * LIFE_RATE + lh.x * 11.0;
        float lifeGen = pk_fmod(floor(lifeT), CYCLE_WRAP);
        float lifePh = fract(lifeT);
        float life = smoothstep(0.0, LIFE_IN, lifePh)
                   * (1.0 - smoothstep(1.0 - LIFE_OUT, 1.0, lifePh));
        if (life <= 0.002) { continue; }

        // ``lifeGen`` rides in every panel hash below, so a cell that comes back
        // comes back as a different panel rather than as the same one blinking.
        vec3 ph = hash33(cell + vec2(cycle * 13.0 + float(i) * 57.0 + lifeGen * 29.0,
                                         cycle * 7.0 - float(i) * 23.0 + lifeGen * 41.0));
        if (ph.x > PANEL_KEEP) { continue; }     // this cell is empty space

        vec3 qh = hash33(cell * 1.37 + vec2(float(i) * 11.0,
                                                cycle * 3.0 + lifeGen * 17.0));
        float pw = PANEL_W_MIN + PANEL_W_RNG * ph.y;
        float panelH = PANEL_H_MIN + PANEL_H_RNG * ph.z;
        float lx = (f.x - (1.0 - pw) * qh.x) / pw;   // panel-local, 0..1
        float ly = (f.y - (1.0 - panelH) * qh.y) / panelH;
        if (lx < 0.0 || lx > 1.0 || ly < 0.0 || ly > 1.0) { continue; }

        // One pixel, in cell units. Derived from the depth rather than from fwidth:
        // the branching above is non-uniform, which makes a derivative undefined,
        // and every antialiasing width downstream depends on this.
        float pixCell = z * GRID / halfRes.y;
        // Past the point where a pixel spans a good part of a row, the panel cannot
        // be read at all; fading it out is what keeps the far field from boiling.
        float resolve = 1.0 - smoothstep(RESOLVE * 0.5, RESOLVE,
                                         (pixCell / panelH) * ROWS);
        if (resolve <= 0.0) { continue; }

        // ``travel``, not z: with the 1/z stepping above it is travel that is linear
        // in apparent scale, so it is the measure that makes the aerial cue agree
        // with the size cue.
        float depth = 1.0 - travel;                         // 0 near, 1 far
        float bright = (0.3 + 0.7 * ph.y) * alpha * life * resolve
                     * mix(1.0, DEPTH_DIM, depth);

        vec2 r = panel_content(lx, ly, pixCell, pw, panelH,
                                 vec2(cell.x * 13.0 + float(i),
                                        cell.y * 29.0 + cycle + lifeGen * 7.0),
                                 qh.z, fract(qh.y * 11.7), t);
        float a = r.x;

        // A hairline outline on some panels, which is most of what makes a cluster
        // of marks read as a *panel* rather than as loose debris.
        if (fract(qh.x * 7.3) < FRAME_SHARE) {
            float edge = min(min(lx, 1.0 - lx) * pw,
                             min(ly, 1.0 - ly) * panelH) / pixCell;
            a = max(a, (1.0 - smoothstep(0.6, 1.6, edge)) * FRAME_ALPHA);
        }

        a *= bright;
        lit = max(lit, a);
        warm = max(warm, r.y * bright);
        hot = max(hot, a * (1.0 - z / Z_FAR));
    }

    // --- concentration lines --------------------------------------------------
    // Radial speed streaks raking outward from the vanishing point. This is the
    // datastream's dash-in-a-slot wrapped around the centre: a pixel finds its
    // angular sector and its slot along the ray and consults exactly one cell, so a
    // whole field of them costs about what one more panel plane would. They sell the
    // forward motion the panels only imply -- the panels grow, but nothing *streaks*.
    float rad = length(P);
    float rn = rad / length(halfRes);          // 0 at the centre, 1 at the corner
    if (rn > CONC_IN && rad > 1.0) {
        float ang = atan(P.y, P.x) / TAU + 0.5;
        // Wrapped, or the slot at ang = 1 would be a different draw from the one at
        // ang = 0 and the field would carry a seam straight out along -x.
        float sector = pk_fmod(floor(ang * CONC_SECTORS), CONC_SECTORS);
        vec3 ch = hash33(vec2(sector, 4.0));
        if (ch.x * CONC_SECTORS < CONC_COUNT) {
            // Folded like the datastream's lanes: the fraction places the pixel in
            // its slot, the integer only names it.
            float shift = t * CONC_RATE * (0.5 + 1.2 * ch.y) / CONC_CELL;
            float shiftI = floor(shift);
            float uu = rn / CONC_CELL - (shift - shiftI);
            float slot = floor(uu);
            float fu = uu - slot;
            vec3 dh = hash33(vec2(pk_fmod(slot - shiftI, CONC_WRAP), sector));
            if (dh.x < 0.75) {
                float dash = CONC_DASH * (0.35 + 0.9 * dh.y);
                // Constant width in pixels, so the angular half-width has to shrink
                // as the radius grows -- otherwise a streak fans out into a wedge.
                float dPx = abs(fract(ang * CONC_SECTORS) - 0.5) / CONC_SECTORS * TAU * rad;
                float covA = 1.0 - smoothstep(CONC_PX * 0.5, CONC_PX * 0.5 + 1.0, dPx);
                float covR = smoothstep(0.0, 0.02, fu)
                           * (1.0 - smoothstep(dash - 0.02, dash, fu));
                float fade = smoothstep(CONC_IN, CONC_IN + CONC_RAMP, rn);
                float a = covA * covR * fade * CONC_ALPHA * (0.5 + 0.5 * dh.z);
                lit = max(lit, a);
                hot = max(hot, a * (1.0 - smoothstep(0.0, 0.3, fu)) * CONC_HEAD);
            }
        }
    }

    // The ambient layer sits under the rest: dim, soft and cool, never warm or hot.
    lit = max(lit, ambient_field(pos.xy, t));

    // The fast layer, on top: this is the element that actually moves.
    vec2 fastR = fast_field(pos.xy, t);
    lit = max(lit, fastR.x);
    hot = max(hot, fastR.y * FAST_HEAD);

    // The accent is the ink with red and blue swapped -- amber out of this scene's
    // cyan, and a theme-derived hue out of anything else (see the module note).
    vec3 rgb = mix(ink.rgb, ink.zyx, clamp(warm / max(lit, 1e-4), 0.0, 1.0));
    rgb = mix(rgb, vec3(1.0), clamp(hot, 0.0, 1.0) * NEAR_GLOW);

    rgb = mix(backdrop.rgb, rgb, clamp(lit, 0.0, 1.0) * opacity);
    return vec4(rgb, 1.0);
}
"""

#: Every scene XeFM offers, by the name a theme's ``animation`` key uses, paired with
#: the puikit ``Shader`` fields that belong to the scene rather than to the theme.
#: ``_resolve_background`` in ``xefm/app.py`` resolves a theme's ``animation`` name here
#: and nowhere else: a name absent from this dict yields no background at all, so a
#: typo in a theme costs the scene rather than startup.
#:
#: ``resolution_scale`` is per scene because only the scene knows how much sharpness
#: it can give up. The wave is diffuse grain, and at half resolution it is four times
#: cheaper — which is what keeps it affordable on a Retina display, and it needs to
#: be: the texture-mapped sheet samples three octaves across 24 depth slabs. The
#: upscale does soften its dots, and that is a deliberate trade rather than a free
#: one; 0.75 renders them visibly crisper for a little over twice the cost. Every
#: other scene here is thin bright lines, where halving the scale and upscaling would
#: trade away the crispness that is the point of drawing them.
SHADER_KINDS: dict[str, dict] = {
    "wave": {"source": WAVE_MSL, "source_hlsl": WAVE_HLSL, "source_glsl": WAVE_GLSL, "resolution_scale": 0.5},
    # Rain renders at full resolution: it is thin bright lines, and at half scale the
    # upscale makes them crawl and shimmer. It can afford to — a pixel tests three
    # columns and most exit before touching a drop.
    "rain": {"source": RAIN_MSL, "source_hlsl": RAIN_HLSL, "source_glsl": RAIN_GLSL},
    # Also full resolution: streaks are thin and near-white at the head, and halving
    # the scale turns them into crawling smudges.
    "starfield": {"source": STARFIELD_MSL, "source_hlsl": STARFIELD_HLSL, "source_glsl": STARFIELD_GLSL},
    # The corridor is all thin straight lines, and its whole gain over the segment
    # version is derivative-filtered width. Rendering at half scale and upscaling
    # would throw exactly that away.
    "grid": {"source": GRID_MSL, "source_hlsl": GRID_HLSL, "source_glsl": GRID_GLSL},
    # Dots and hairline edges, so again full resolution.
    "constellation": {"source": CONSTELLATION_MSL, "source_hlsl": CONSTELLATION_HLSL, "source_glsl": CONSTELLATION_GLSL},
    # Thin dashes with crisp leading edges, and the far layers' rows are only a few
    # pixels apart — halving the scale would merge them into a band.
    "datastream": {"source": DATASTREAM_MSL, "source_hlsl": DATASTREAM_HLSL, "source_glsl": DATASTREAM_GLSL},
    # Hairline rules, 1px panel outlines and blocks a couple of pixels tall, all of
    # which the upscale from a half-scale render would smear into mush. It is also
    # the scene that most wants the resolution: its far planes fade out exactly where
    # a pixel stops resolving a row, so rendering at half scale would throw away
    # depth, not just sharpness.
    "hologram": {"source": HOLOGRAM_MSL, "source_hlsl": HOLOGRAM_HLSL, "source_glsl": HOLOGRAM_GLSL},
}
