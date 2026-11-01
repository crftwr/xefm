"""The camera look the picture scenes are filmed through: bloom, flare, film, a
CRT tube — over the scene alone, under the UI.

A scene that uses it renders **linear HDR** radiance into a half-float target
(values far above 1 are the point: a sun is thousands of times brighter than
the ground), and the passes here tone-map it, apply gamma, grade it and mix it
over the ``backdrop`` by ``opacity``. They are ordinary PuiKit passes
(``Shader.targets`` / ``Shader.passes``) over this module's shader source,
appended to the scene's: PuiKit allocates the targets and runs the passes on
Metal and Direct3D, and knows nothing of what they compute.

The chain, per frame::

    scene ─▶ down0 ─▶ down1 ─▶ … ─▶ down5            13-tap downsample
                                      │              (soft threshold on the
           up0 ◀─ up1 ◀─ … ◀──── up4 ◀┘               first level)
            │      tent upsample, added onto the matching down level
            │
           streak (down1, 4 ping-pong passes; left out when no look has one)
            │
    scene + bloom(up0) + streak ─▶ composite ─▶ screen

The composite does everything that is not a blur — depth of field, distortion,
aberration, ghosts, colour matrix, tone map, gamma, grade, vignette, masks,
scanlines, grain, letterbox, dither, the brightness ceiling, and the final mix
over the backdrop — so every look a :class:`Look` describes costs the same.

**Looks are data in the shader.** The looks a theme cycles through are baked
into the source as a table, and each pass picks the look from ``time`` and the
``seed`` uniforms: one look per ``period`` seconds, chosen by
``xefm_slot_hash(slot, seed) % count``, blended into the next over its last
``transition`` seconds, and from the old seed's look into the new one's while
``seed_mix`` rises. A scene that moves between compositions hashes the same
slot (:data:`SLOT_HASH_MSL`) with the bits the look did not use, so its camera
and its look change together — and the whole picture stays a function of its
uniforms, which a backend that advances it on its own requires.

Both dialects sample with explicit level 0 (``level(0)`` / ``SampleLevel``):
the targets have no mips, and an implicit-derivative sample inside the ghost
loop is an error in HLSL.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

try:
    from puikit.background import Pass, Target
    AVAILABLE = True
except ImportError:
    # PuiKit 1.17.0 and older run a shader as a single pass, so the lens cannot
    # be built; the scenes that need it are left out (see background_earth).
    AVAILABLE = False

#: Pyramid depth. Six halvings take a 1080-line target to a 17-line top level —
#: wide enough that the sun's bloom reaches across the frame.
LEVELS = 6

#: Steps of the streak's ping-pong passes, in texels of its quarter-size source.
STREAK_STEPS = (1.0, 3.0, 9.0, 27.0)

#: A streak weaker than this is not drawn; a cycle whose looks all stay below
#: it leaves the streak passes out.
STREAK_EPSILON = 0.003

#: float4 rows a look takes in the shader's table (see ``_look_rows``).
LOOK_ROWS = 12

#: The scene pass's entry and the target it renders its HDR into.
SCENE_ENTRY = "puikit_bg_fragment"
SCENE_TARGET = "scene"


def _floats(value, n: int, default: float) -> "tuple[float, ...]":
    """``value`` as exactly ``n`` floats, padding with ``default``."""
    out = [float(v) for v in tuple(value)[:n]]
    return tuple(out + [default] * (n - len(out)))


@dataclass(frozen=True)
class Look:
    """One camera look. Every field is a parameter of the composite (or the
    threshold of the first downsample), so a look is pure data.

    Fields (``0`` = off unless noted):
      bloom            Glow from everything above ``threshold``.
      threshold        Scene radiance above which light blooms (default 1.6).
      halation         Red-orange fringe around highlights, as film shows.
      streak           Anamorphic horizontal streak through bright points.
      streak_tint      RGB of the streak.
      ghosts           Lens-flare ghosts and halo mirrored through the centre.
      aberration       Radial chromatic aberration.
      distortion       Barrel distortion (``1.4`` is a fisheye).
      color_matrix     Nine floats, row-major: ``out.r = m[0]*r + m[1]*g +
                       m[2]*b`` and so on, applied before tone mapping. ``None``
                       is the identity.
      gain             Linear multiplier before tone mapping (default 1).
      saturation       ``1`` is unchanged, ``0`` is monochrome in ``mono_tint``.
      mono_tint        RGB a desaturated image is tinted toward.
      shadow_tint / highlight_tint
                       RGB split-tone multipliers for the darks and lights.
      contrast         ``1`` is unchanged.
      vignette         Edge darkening (default 0.15).
      curvature        Rounded CRT corners.
      scope            A single round eyepiece mask.
      scanlines        CRT scanlines and an aperture grille.
      grain            Film grain, strongest in the mid-tones.
      letterbox        Bars that crop the frame to 2.39:1.
      level            The brightest the look may be, 0..1, as a multiplier on
                       its final display colour: ``0.5`` keeps every pixel at or
                       below half white, whatever the scene, exposure and grade
                       did. For a background that text sits on.
      dof              Depth of field: the largest blur radius, as a fraction
                       of the frame's height. The scene then writes its
                       **inverse** depth, ``1 / distance`` along the view ray
                       (``0`` for nothing hit), into alpha — inverse because the
                       blur size is linear in it, so filtering blends blur sizes
                       across a silhouette instead of inventing a depth there.
                       Focus is pulled to what the middle of the frame is
                       looking at, from a few taps there.
      focus_range      How quickly the blur grows away from the focus distance:
                       the circle of confusion is ``|depth - focus| / depth *
                       focus_range``, clamped to 1.
    """

    bloom: float = 0.3
    threshold: float = 1.6
    halation: float = 0.0
    streak: float = 0.0
    streak_tint: "tuple[float, float, float]" = (0.45, 0.7, 1.3)
    ghosts: float = 0.0
    aberration: float = 0.0
    distortion: float = 0.0
    color_matrix: "tuple[float, ...] | None" = None
    gain: float = 1.0
    saturation: float = 1.0
    mono_tint: "tuple[float, float, float]" = (1.0, 1.0, 1.0)
    shadow_tint: "tuple[float, float, float]" = (1.0, 1.0, 1.0)
    highlight_tint: "tuple[float, float, float]" = (1.0, 1.0, 1.0)
    contrast: float = 1.0
    vignette: float = 0.15
    curvature: float = 0.0
    scope: float = 0.0
    scanlines: float = 0.0
    grain: float = 0.0
    letterbox: float = 0.0
    level: float = 1.0
    dof: float = 0.0
    focus_range: float = 2.6

    def __post_init__(self) -> None:
        for name in ("streak_tint", "mono_tint", "shadow_tint", "highlight_tint"):
            object.__setattr__(self, name, _floats(getattr(self, name), 3, 1.0))
        if self.color_matrix is not None:
            object.__setattr__(self, "color_matrix", _floats(self.color_matrix, 9, 0.0))
        # A threshold at or below zero would bloom the whole frame, black included.
        object.__setattr__(self, "threshold", max(0.05, float(self.threshold)))
        object.__setattr__(self, "level", min(1.0, max(0.0, float(self.level))))
        object.__setattr__(self, "dof", min(0.1, max(0.0, float(self.dof))))

    @property
    def matrix_rows(self) -> "tuple[tuple[float, float, float], ...]":
        """The colour matrix as three rows, the identity when unset."""
        m = self.color_matrix or (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        return (m[0:3], m[3:6], m[6:9])


LOOK_FIELDS = tuple(f.name for f in fields(Look))


def _look_rows(look: Look) -> "list[tuple[float, float, float, float]]":
    """A look as the shader's :data:`LOOK_ROWS` float4 rows — the layout the
    ``LensLook`` struct below reads."""
    m = look.matrix_rows
    return [
        (look.aberration, look.distortion, look.bloom, look.streak),
        (look.ghosts, look.saturation, look.contrast, look.grain),
        (look.vignette, look.scanlines, look.curvature, look.letterbox),
        (look.halation, look.gain, look.scope, look.level),
        (*look.mono_tint, 0.0),
        (*look.shadow_tint, 0.0),
        (*look.highlight_tint, 0.0),
        (*look.streak_tint, 0.0),
        (*m[0], 0.0), (*m[1], 0.0), (*m[2], 0.0),
        (look.dof, look.focus_range, look.threshold, 0.0),
    ]


def slot_hash(slot: int, seed: float) -> int:
    """``xefm_slot_hash`` in Python: the same 32-bit result for the same slot
    and seed, so a test can say which look the shader picks."""
    m = 0xFFFFFFFF
    x = (int(slot) * 0x9E3779B9 + int(seed)) & m
    x ^= x >> 16
    x = (x * 0x7FEB352D) & m
    x ^= x >> 15
    x = (x * 0x846CA68B) & m
    x ^= x >> 16
    return x


def look_at(looks: "tuple[Look, ...]", period: float, transition: float, time: float,
            seed: float) -> "tuple[float, ...]":
    """What the shader's ``lens_at`` returns, flattened: the rows of the look at
    ``time`` (for tests and documentation — the GPU is what draws)."""
    rows = [sum(map(tuple, _look_rows(l)), ()) for l in looks]
    if len(looks) == 1:
        return rows[0]
    import math
    k = math.floor(time / period)
    a = rows[slot_hash(k, seed) % len(looks)]
    b = rows[slot_hash(k + 1, seed) % len(looks)]
    into, start = time - k * period, period - transition
    if into <= start or transition <= 0.0:
        return a
    x = min(1.0, (into - start) / transition)
    w = x * x * (3.0 - 2.0 * x)
    return tuple(p + (q - p) * w for p, q in zip(a, b))


#: The slot hash, for a scene that picks its composition per slot as the look
#: is picked (see the module docstring). Prepended by :func:`lens_shader` ahead of the
#: scene's source, so the scene can call it.
SLOT_HASH_MSL = """
// A well-mixed 32-bit hash of a time slot and a seed (xefm.background_lens).
static inline uint xefm_slot_hash(int slot, float seed) {
    uint x = uint(slot) * 0x9E3779B9u + uint(seed);
    x ^= x >> 16; x *= 0x7FEB352Du; x ^= x >> 15; x *= 0x846CA68Bu; x ^= x >> 16;
    return x;
}
"""

SLOT_HASH_HLSL = """
uint xefm_slot_hash(int slot, float seed) {
    uint x = uint(slot) * 0x9E3779B9u + uint(seed);
    x ^= x >> 16; x *= 0x7FEB352Du; x ^= x >> 15; x *= 0x846CA68Bu; x ^= x >> 16;
    return x;
}
"""


def _table(looks: "tuple[Look, ...]", dialect: str) -> str:
    rows = [r for look in looks for r in _look_rows(look)]
    body = ",\n    ".join("float4(" + ", ".join(repr(float(v)) for v in r) + ")" for r in rows)
    kw = "constant" if dialect == "msl" else "static const"
    head = f"{kw} float4 LENS_LOOKS[{len(rows)}] = {{"
    return f"{head}\n    {body}\n}};\n"


def _constants(looks, period, transition, dialect: str) -> str:
    kw = "constant" if dialect == "msl" else "static const"
    return (f"{kw} int   LENS_LOOK_COUNT = {len(looks)};\n"
            f"{kw} float LENS_PERIOD = {float(period)!r};\n"
            f"{kw} float LENS_TRANSITION = {float(transition)!r};\n"
            + _table(looks, dialect))


# The passes, written once per dialect. MSL is the reference; the HLSL is the
# same maths with the dialect's spellings, and the two are kept line-for-line
# parallel so a change to one is easy to carry over.

LENS_MSL = r"""
// --- the lens (xefm.background_lens) -----------------------------------------
struct LensLook { float4 r[12]; };
// r[0] aberration, distortion, bloom, streak   r[1] ghosts, saturation, contrast, grain
// r[2] vignette, scanlines, curvature, letterbox   r[3] halation, gain, scope, level
// r[4] mono  r[5] shadow  r[6] high  r[7] streak tint  r[8..10] colour matrix
// r[11] dof, focus_range, threshold, -

static inline LensLook lens_entry(int i) {
    LensLook l;
    for (int j = 0; j < 12; j++) l.r[j] = LENS_LOOKS[i * 12 + j];
    return l;
}

static inline LensLook lens_mix(LensLook a, LensLook b, float w) {
    LensLook l;
    for (int j = 0; j < 12; j++) l.r[j] = mix(a.r[j], b.r[j], w);
    return l;
}

// The look at time t for one seed: one per period, blended into the next over
// the period's last LENS_TRANSITION seconds.
static inline LensLook lens_at(float t, float seed) {
    if (LENS_LOOK_COUNT == 1) return lens_entry(0);
    int k = int(floor(t / LENS_PERIOD));
    LensLook a = lens_entry(int(xefm_slot_hash(k, seed) % uint(LENS_LOOK_COUNT)));
    float into = t - float(k) * LENS_PERIOD;
    float start = LENS_PERIOD - LENS_TRANSITION;
    if (into <= start || LENS_TRANSITION <= 0.0) return a;
    LensLook b = lens_entry(int(xefm_slot_hash(k + 1, seed) % uint(LENS_LOOK_COUNT)));
    float x = min(1.0, (into - start) / LENS_TRANSITION);
    return lens_mix(a, b, x * x * (3.0 - 2.0 * x));
}

// ... and eased from the old seed's look into the new one's after a reseed.
static inline LensLook lens_look(constant BackgroundUniforms &u) {
    LensLook now = lens_at(u.time, u.seed);
    if (u.seed_mix >= 1.0) return now;
    return lens_mix(lens_at(u.time, u.seed_prev), now, u.seed_mix);
}

constant float LENS_FOCUS_SPREAD = 0.012;   // the autofocus taps' distance from the middle

static inline float3 lens_tap(texture2d<float> t, sampler s, float2 uv) {
    return t.sample(s, uv, level(0)).rgb;
}

// 13-tap downsample (Jimenez 2014). The first level (params.x) also clamps and
// soft-thresholds, so only what is genuinely bright feeds the bloom.
fragment float4 lens_down(float4 pos [[position]],
                          constant BackgroundUniforms &u [[buffer(0)]],
                          constant PassUniforms &p [[buffer(1)]],
                          texture2d<float> src [[texture(0)]], sampler s [[sampler(0)]]) {
    float2 tx = 1.0 / p.inputs[0].xy;
    float2 uv = pos.xy / p.target.xy;
    float3 r = lens_tap(src, s, uv) * 0.125
        + (lens_tap(src, s, uv + float2(-2, 2) * tx) + lens_tap(src, s, uv + float2(2, 2) * tx)
         + lens_tap(src, s, uv + float2(-2, -2) * tx) + lens_tap(src, s, uv + float2(2, -2) * tx)) * 0.03125
        + (lens_tap(src, s, uv + float2(0, 2) * tx) + lens_tap(src, s, uv + float2(-2, 0) * tx)
         + lens_tap(src, s, uv + float2(2, 0) * tx) + lens_tap(src, s, uv + float2(0, -2) * tx)) * 0.0625
        + (lens_tap(src, s, uv + float2(-1, 1) * tx) + lens_tap(src, s, uv + float2(1, 1) * tx)
         + lens_tap(src, s, uv + float2(-1, -1) * tx) + lens_tap(src, s, uv + float2(1, -1) * tx)) * 0.125;
    if (p.params.x > 0.5) {
        float threshold = lens_look(u).r[11].z;
        r = min(r, float3(24.0));
        float br = max(r.r, max(r.g, r.b));
        float knee = threshold * 0.6;
        float soft = clamp(br - threshold + knee, 0.0, 2.0 * knee);
        soft = soft * soft / (4.0 * knee + 1e-4);
        r *= max(soft, br - threshold) / max(br, 1e-4);
    }
    return float4(r, 1.0);
}

// 3x3 tent upsample of the coarser level, added onto this level's downsample.
fragment float4 lens_up(float4 pos [[position]],
                        constant BackgroundUniforms &u [[buffer(0)]],
                        constant PassUniforms &p [[buffer(1)]],
                        texture2d<float> src [[texture(0)]],
                        texture2d<float> base [[texture(1)]],
                        sampler s [[sampler(0)]], sampler sb [[sampler(1)]]) {
    float2 tx = 1.0 / p.inputs[0].xy;
    float2 uv = pos.xy / p.target.xy;
    float3 t = lens_tap(src, s, uv + float2(-1, -1) * tx) + lens_tap(src, s, uv + float2(1, -1) * tx)
             + lens_tap(src, s, uv + float2(-1, 1) * tx) + lens_tap(src, s, uv + float2(1, 1) * tx)
             + 2.0 * (lens_tap(src, s, uv + float2(0, -1) * tx) + lens_tap(src, s, uv + float2(0, 1) * tx)
                    + lens_tap(src, s, uv + float2(-1, 0) * tx) + lens_tap(src, s, uv + float2(1, 0) * tx))
             + 4.0 * lens_tap(src, s, uv);
    return float4(lens_tap(base, sb, uv) + t / 16.0, 1.0);
}

// One horizontal pass of the anamorphic streak; run with growing steps (params.x).
fragment float4 lens_streak(float4 pos [[position]],
                            constant BackgroundUniforms &u [[buffer(0)]],
                            constant PassUniforms &p [[buffer(1)]],
                            texture2d<float> src [[texture(0)]], sampler s [[sampler(0)]]) {
    float2 uv = pos.xy / p.target.xy;
    float2 dir = float2(p.params.x / p.target.x, 0.0);
    float3 c = lens_tap(src, s, uv) * 0.30;
    c += (lens_tap(src, s, uv + dir) + lens_tap(src, s, uv - dir)) * 0.22;
    c += (lens_tap(src, s, uv + dir * 2.0) + lens_tap(src, s, uv - dir * 2.0)) * 0.09;
    c += (lens_tap(src, s, uv + dir * 3.0) + lens_tap(src, s, uv - dir * 3.0)) * 0.025;
    return float4(c, 1.0);
}

static inline float lens_hash12(float2 p) {
    float3 p3 = fract(float3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

static inline float lens_in_frame(float2 uv) {
    float2 e = min(uv, 1.0 - uv);
    return step(0.0, min(e.x, e.y));
}

// Depth of field: the scene carries its *inverse* depth in alpha. The circle of
// confusion, |1 - focus / depth| * range, is linear in 1 / depth, so a bilinear
// tap blends blur sizes across a silhouette rather than inventing a depth there
// (which can land on the focus distance and draw the edge's stair steps sharp).
// Focus is what the middle of the frame is looking at -- the centre tap and four
// close round it, averaged as 1/depth so a near subject wins over the distance
// behind it. Close, because a macro's depth of field is shallow enough that a
// tap landing on the rock behind the subject would pull focus off it; spread a
// little, so focus moves across a short band rather than jumping as an edge
// crosses the middle. Each pixel gathers a golden-angle disc sized by its circle
// of confusion. A tap counts only if its own blur disc reaches this pixel, so
// sharp detail never smears over a blurred background.
static inline float3 lens_dof_encode(float3 x) {
    return pow(x / (1.0 + max(x, 0.0)), float3(1.0 / 2.2));
}

static inline float3 lens_dof_decode(float3 m) {
    float3 y = min(pow(m, float3(2.2)), float3(0.999));
    return y / (1.0 - y);
}

static inline float3 lens_depth_of_field(texture2d<float> scene, sampler lin, float2 uv,
                                         float2 px, float2 res, float dof, float range) {
    float asp = res.x / res.y;
    float inv = 0.0, wsum = 0.0;
    for (int i = 0; i < 5; i++) {
        float a = float(i) * 1.5708;
        float2 o = i == 0 ? float2(0.0) : float2(cos(a) / asp, sin(a)) * LENS_FOCUS_SPREAD;
        float w = i == 0 ? 2.0 : 1.0;
        inv += w * scene.sample(lin, float2(0.5) + o, level(0)).a;
        wsum += w;
    }
    float focus = wsum / max(inv, 1e-4);
    float maxr = dof * res.y;
    float4 c0 = scene.sample(lin, uv, level(0));
    float r0 = clamp(abs(1.0 - focus * c0.a) * range, 0.0, 1.0) * maxr;
    // The taps are averaged in a squashed, gamma-encoded space -- (x / (1 + x))
    // ^ (1/2.2) -- and the mean expanded again. This gather runs on HDR, and a
    // hairline glint many times white would otherwise land in some pixels' taps
    // and not their neighbours', breaking a clean edge into teeth. Squashed, no
    // tap weighs more than white; encoded, the dark around it is not so dark
    // that one glint doubles it -- as if the blur ran on the finished picture,
    // without losing the HDR the tone map comes after.
    float3 acc = lens_dof_encode(c0.rgb);
    float tot = 1.0;
    float rot = lens_hash12(px) * 6.2831;
    for (int i = 1; i < 40; i++) {
        float fi = float(i);
        float rr = sqrt(fi / 40.0) * r0;
        float a = fi * 2.39996 + rot;
        float4 s = scene.sample(lin, uv + float2(cos(a), sin(a)) * rr / res, level(0));
        float rs = clamp(abs(1.0 - focus * s.a) * range, 0.0, 1.0) * maxr;
        float w = clamp(rs - rr + 1.0, 0.0, 1.0);
        acc += lens_dof_encode(s.rgb) * w;
        tot += w;
    }
    return lens_dof_decode(acc / tot);
}

fragment float4 lens_composite(float4 pos [[position]],
                               constant BackgroundUniforms &u [[buffer(0)]],
                               constant PassUniforms &p [[buffer(1)]],
                               texture2d<float> scene [[texture(0)]],
                               texture2d<float> bloom [[texture(1)]],
                               texture2d<float> streak [[texture(2)]],
                               sampler lin [[sampler(0)]]) {
    const float PI = 3.14159265;
    LensLook L = lens_look(u);
    float4 la = L.r[0], lb = L.r[1], lc = L.r[2], ld = L.r[3], le = L.r[11];
    float2 uv = pos.xy / u.resolution;
    float asp = u.resolution.x / u.resolution.y;
    float ca = la.x, distort = la.y;
    float2 c = (uv - 0.5) * float2(asp, 1.0);
    float r2 = dot(c, c);
    // Barrel distortion, normalised so the middle of the top and bottom edges stays put.
    float2 d = c * (1.0 + distort * r2) / (1.0 + distort * 0.25);
    float2 uvG = d / float2(asp, 1.0) + 0.5;
    float2 uvR = (d * (1.0 + ca)) / float2(asp, 1.0) + 0.5;
    float2 uvB = (d * (1.0 - ca)) / float2(asp, 1.0) + 0.5;

    float3 col;
    if (le.x > 0.0) {
        col = lens_depth_of_field(scene, lin, uvG, pos.xy, u.resolution, le.x, le.y)
            * lens_in_frame(uvG);
    } else {
        col = float3(lens_tap(scene, lin, uvR).r * lens_in_frame(uvR),
                     lens_tap(scene, lin, uvG).g * lens_in_frame(uvG),
                     lens_tap(scene, lin, uvB).b * lens_in_frame(uvB));
    }
    float3 bl = float3(lens_tap(bloom, lin, uvR).r * lens_in_frame(uvR),
                       lens_tap(bloom, lin, uvG).g * lens_in_frame(uvG),
                       lens_tap(bloom, lin, uvB).b * lens_in_frame(uvB));
    col += bl * la.z * 0.07;
    col += bl * float3(1.0, 0.22, 0.06) * ld.x * 0.06;
    float streak_w = la.w > 0.003 ? la.w : 0.0;
    col += lens_tap(streak, lin, uvG) * lens_in_frame(uvG) * L.r[7].rgb * streak_w * 0.6;

    // Ghosts and halo: mirrored, blurred copies of the bright parts through the centre.
    float ghosts = lb.x;
    if (ghosts > 0.001) {
        float2 gv = float2(0.5) - uvG;
        float3 g = float3(0.0);
        for (int i = 1; i <= 5; i++) {
            float fi = float(i);
            float2 suv = uvG + gv * (0.32 * fi + 0.18);
            float w = pow(max(1.0 - length(float2(0.5) - suv) / 0.75, 0.0), 6.0);
            float3 tint = 0.62 + 0.38 * cos(6.2832 * (fi * 0.17 + float3(0.0, 0.33, 0.67)));
            g += lens_tap(bloom, lin, suv) * lens_in_frame(suv) * tint * w * (0.9 / fi);
        }
        float2 hv = normalize(gv * float2(asp, 1.0) + 1e-5) / float2(asp, 1.0) * 0.42;
        float hw = pow(max(1.0 - length(float2(0.5) - (uvG + hv)) / 0.75, 0.0), 4.0);
        g += float3(lens_tap(bloom, lin, uvG + hv * 1.02).r, lens_tap(bloom, lin, uvG + hv).g,
                    lens_tap(bloom, lin, uvG + hv * 0.98).b) * hw * 0.22;
        col += g * ghosts * 0.12;
    }

    col = max(float3(dot(L.r[8].xyz, col), dot(L.r[9].xyz, col), dot(L.r[10].xyz, col)), 0.0)
        * ld.y;
    // ACES-style tone map, then display gamma.
    col = clamp((col * (2.51 * col + 0.03)) / (col * (2.43 * col + 0.59) + 0.14), 0.0, 1.0);
    col = pow(col, float3(1.0 / 2.2));

    // Grade.
    float l = dot(col, float3(0.2126, 0.7152, 0.0722));
    col = mix(float3(l) * L.r[4].rgb, col, lb.y);
    col *= mix(L.r[5].rgb, L.r[6].rgb, smoothstep(0.05, 0.75, l));
    col = clamp(mix(float3(0.5), col, lb.z), 0.0, 1.0);

    // Vignette and optical masks.
    float rv = length(uv - 0.5) * 1.4142;
    col *= mix(1.0, smoothstep(1.2, 0.25, rv), lc.x);
    float cr = 0.05 * lc.z;                                  // CRT rounded corners
    float2 q = abs(uvG - 0.5) - (0.5 - cr);
    float rr = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - cr;
    col *= 1.0 - smoothstep(-0.004, 0.0, rr);
    float sc = length(c) - 0.47;                             // a single round scope
    col *= mix(1.0, 1.0 - smoothstep(-0.03, 0.0, sc), ld.z);

    // CRT scanlines and aperture grille.
    float scan = lc.y;
    if (scan > 0.001) {
        float lines = u.resolution.y / max(2.0, u.resolution.y / 260.0);
        float sl = 0.62 + 0.38 * sin(uvG.y * lines * PI * 2.0);
        float m = fmod(floor(pos.x), 3.0);
        float3 mk = m < 1.0 ? float3(1.0, 0.72, 0.72)
                  : (m < 2.0 ? float3(0.72, 1.0, 0.72) : float3(0.72, 0.72, 1.0));
        col *= mix(float3(1.0), sl * 1.3 * mk * 1.12, scan);
        col *= 1.0 - scan * 0.025 * sin(u.time * 50.0 + uvG.y * 8.0);
    }

    // Grain, strongest in the mid-tones.
    float n = lens_hash12(pos.xy + fract(u.time * 7.13) * float2(431.0, 217.0)) - 0.5;
    col += n * lb.w * 0.22 * (0.35 + 2.6 * l * (1.0 - l));

    // Letterbox to 2.39:1.
    float vis = mix(1.0, min(1.0, asp / 2.39), lc.w);
    col *= 1.0 - smoothstep(vis * 0.5 - 0.001, vis * 0.5, abs(uv.y - 0.5));

    col += (lens_hash12(pos.xy + 17.0 * fract(u.time)) - 0.5) / 255.0;
    return float4(mix(u.backdrop.rgb, clamp(col, 0.0, 1.0) * ld.w, u.opacity), 1.0);
}
"""

LENS_HLSL = r"""
// --- the lens (xefm.background_lens) -----------------------------------------
struct LensLook { float4 r[12]; };

Texture2D lens_t0 : register(t0);
Texture2D lens_t1 : register(t1);
Texture2D lens_t2 : register(t2);
SamplerState lens_s0 : register(s0);
SamplerState lens_s1 : register(s1);
static const float LENS_FOCUS_SPREAD = 0.012;

LensLook lens_entry(int i) {
    LensLook l;
    [unroll] for (int j = 0; j < 12; j++) l.r[j] = LENS_LOOKS[i * 12 + j];
    return l;
}

LensLook lens_mix(LensLook a, LensLook b, float w) {
    LensLook l;
    [unroll] for (int j = 0; j < 12; j++) l.r[j] = lerp(a.r[j], b.r[j], w);
    return l;
}

LensLook lens_at(float t, float sd) {
    if (LENS_LOOK_COUNT == 1) return lens_entry(0);
    int k = int(floor(t / LENS_PERIOD));
    LensLook a = lens_entry(int(xefm_slot_hash(k, sd) % uint(LENS_LOOK_COUNT)));
    float into = t - float(k) * LENS_PERIOD;
    float start = LENS_PERIOD - LENS_TRANSITION;
    if (into <= start || LENS_TRANSITION <= 0.0) return a;
    LensLook b = lens_entry(int(xefm_slot_hash(k + 1, sd) % uint(LENS_LOOK_COUNT)));
    float x = min(1.0, (into - start) / LENS_TRANSITION);
    return lens_mix(a, b, x * x * (3.0 - 2.0 * x));
}

LensLook lens_look() {
    LensLook now = lens_at(time, seed);
    if (seed_mix >= 1.0) return now;
    return lens_mix(lens_at(time, seed_prev), now, seed_mix);
}

float3 lens_tap0(float2 uv) { return lens_t0.SampleLevel(lens_s0, uv, 0).rgb; }
float3 lens_tap1(float2 uv) { return lens_t1.SampleLevel(lens_s0, uv, 0).rgb; }
float3 lens_tap2(float2 uv) { return lens_t2.SampleLevel(lens_s0, uv, 0).rgb; }

float4 lens_down(float4 pos : SV_Position) : SV_Target {
    float2 tx = 1.0 / pass_inputs[0].xy;
    float2 uv = pos.xy / pass_target.xy;
    float3 r = lens_tap0(uv) * 0.125
        + (lens_tap0(uv + float2(-2, 2) * tx) + lens_tap0(uv + float2(2, 2) * tx)
         + lens_tap0(uv + float2(-2, -2) * tx) + lens_tap0(uv + float2(2, -2) * tx)) * 0.03125
        + (lens_tap0(uv + float2(0, 2) * tx) + lens_tap0(uv + float2(-2, 0) * tx)
         + lens_tap0(uv + float2(2, 0) * tx) + lens_tap0(uv + float2(0, -2) * tx)) * 0.0625
        + (lens_tap0(uv + float2(-1, 1) * tx) + lens_tap0(uv + float2(1, 1) * tx)
         + lens_tap0(uv + float2(-1, -1) * tx) + lens_tap0(uv + float2(1, -1) * tx)) * 0.125;
    if (pass_params.x > 0.5) {
        float threshold = lens_look().r[11].z;
        r = min(r, float3(24.0, 24.0, 24.0));
        float br = max(r.r, max(r.g, r.b));
        float knee = threshold * 0.6;
        float soft = clamp(br - threshold + knee, 0.0, 2.0 * knee);
        soft = soft * soft / (4.0 * knee + 1e-4);
        r *= max(soft, br - threshold) / max(br, 1e-4);
    }
    return float4(r, 1.0);
}

float4 lens_up(float4 pos : SV_Position) : SV_Target {
    float2 tx = 1.0 / pass_inputs[0].xy;
    float2 uv = pos.xy / pass_target.xy;
    float3 t = lens_tap0(uv + float2(-1, -1) * tx) + lens_tap0(uv + float2(1, -1) * tx)
             + lens_tap0(uv + float2(-1, 1) * tx) + lens_tap0(uv + float2(1, 1) * tx)
             + 2.0 * (lens_tap0(uv + float2(0, -1) * tx) + lens_tap0(uv + float2(0, 1) * tx)
                    + lens_tap0(uv + float2(-1, 0) * tx) + lens_tap0(uv + float2(1, 0) * tx))
             + 4.0 * lens_tap0(uv);
    return float4(lens_t1.SampleLevel(lens_s1, uv, 0).rgb + t / 16.0, 1.0);
}

float4 lens_streak(float4 pos : SV_Position) : SV_Target {
    float2 uv = pos.xy / pass_target.xy;
    float2 dir = float2(pass_params.x / pass_target.x, 0.0);
    float3 c = lens_tap0(uv) * 0.30;
    c += (lens_tap0(uv + dir) + lens_tap0(uv - dir)) * 0.22;
    c += (lens_tap0(uv + dir * 2.0) + lens_tap0(uv - dir * 2.0)) * 0.09;
    c += (lens_tap0(uv + dir * 3.0) + lens_tap0(uv - dir * 3.0)) * 0.025;
    return float4(c, 1.0);
}

float lens_hash12(float2 p) {
    float3 p3 = frac(float3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return frac((p3.x + p3.y) * p3.z);
}

float lens_in_frame(float2 uv) {
    float2 e = min(uv, 1.0 - uv);
    return step(0.0, min(e.x, e.y));
}

float3 lens_dof_encode(float3 x) {
    return pow(x / (1.0 + max(x, 0.0)), 1.0 / 2.2);
}

float3 lens_dof_decode(float3 m) {
    float3 y = min(pow(m, 2.2), float3(0.999, 0.999, 0.999));
    return y / (1.0 - y);
}

float3 lens_depth_of_field(float2 uv, float2 px, float dof, float range) {
    float asp = resolution.x / resolution.y;
    float inv = 0.0, wsum = 0.0;
    [unroll] for (int i = 0; i < 5; i++) {
        float a = float(i) * 1.5708;
        float2 o = i == 0 ? float2(0.0, 0.0) : float2(cos(a) / asp, sin(a)) * LENS_FOCUS_SPREAD;
        float w = i == 0 ? 2.0 : 1.0;
        inv += w * lens_t0.SampleLevel(lens_s0, float2(0.5, 0.5) + o, 0).a;
        wsum += w;
    }
    float focus = wsum / max(inv, 1e-4);
    float maxr = dof * resolution.y;
    float4 c0 = lens_t0.SampleLevel(lens_s0, uv, 0);
    float r0 = clamp(abs(1.0 - focus * c0.a) * range, 0.0, 1.0) * maxr;
    float3 acc = lens_dof_encode(c0.rgb);
    float tot = 1.0;
    float rot = lens_hash12(px) * 6.2831;
    [loop] for (int j = 1; j < 40; j++) {
        float fi = float(j);
        float rr = sqrt(fi / 40.0) * r0;
        float a = fi * 2.39996 + rot;
        float4 s = lens_t0.SampleLevel(lens_s0, uv + float2(cos(a), sin(a)) * rr / resolution, 0);
        float rs = clamp(abs(1.0 - focus * s.a) * range, 0.0, 1.0) * maxr;
        float w = clamp(rs - rr + 1.0, 0.0, 1.0);
        acc += lens_dof_encode(s.rgb) * w;
        tot += w;
    }
    return lens_dof_decode(acc / tot);
}

float4 lens_composite(float4 pos : SV_Position) : SV_Target {
    const float PI = 3.14159265;
    LensLook L = lens_look();
    float4 la = L.r[0], lb = L.r[1], lc = L.r[2], ld = L.r[3], le = L.r[11];
    float2 uv = pos.xy / resolution;
    float asp = resolution.x / resolution.y;
    float ca = la.x, distort = la.y;
    float2 c = (uv - 0.5) * float2(asp, 1.0);
    float r2 = dot(c, c);
    float2 d = c * (1.0 + distort * r2) / (1.0 + distort * 0.25);
    float2 uvG = d / float2(asp, 1.0) + 0.5;
    float2 uvR = (d * (1.0 + ca)) / float2(asp, 1.0) + 0.5;
    float2 uvB = (d * (1.0 - ca)) / float2(asp, 1.0) + 0.5;

    float3 col;
    if (le.x > 0.0) {
        col = lens_depth_of_field(uvG, pos.xy, le.x, le.y) * lens_in_frame(uvG);
    } else {
        col = float3(lens_tap0(uvR).r * lens_in_frame(uvR), lens_tap0(uvG).g * lens_in_frame(uvG),
                     lens_tap0(uvB).b * lens_in_frame(uvB));
    }
    float3 bl = float3(lens_tap1(uvR).r * lens_in_frame(uvR), lens_tap1(uvG).g * lens_in_frame(uvG),
                       lens_tap1(uvB).b * lens_in_frame(uvB));
    col += bl * la.z * 0.07;
    col += bl * float3(1.0, 0.22, 0.06) * ld.x * 0.06;
    float streak_w = la.w > 0.003 ? la.w : 0.0;
    col += lens_tap2(uvG) * lens_in_frame(uvG) * L.r[7].rgb * streak_w * 0.6;

    float ghosts = lb.x;
    if (ghosts > 0.001) {
        float2 gv = float2(0.5, 0.5) - uvG;
        float3 g = float3(0.0, 0.0, 0.0);
        [unroll] for (int i = 1; i <= 5; i++) {
            float fi = float(i);
            float2 suv = uvG + gv * (0.32 * fi + 0.18);
            float w = pow(max(1.0 - length(float2(0.5, 0.5) - suv) / 0.75, 0.0), 6.0);
            float3 tint = 0.62 + 0.38 * cos(6.2832 * (fi * 0.17 + float3(0.0, 0.33, 0.67)));
            g += lens_tap1(suv) * lens_in_frame(suv) * tint * w * (0.9 / fi);
        }
        float2 hv = normalize(gv * float2(asp, 1.0) + 1e-5) / float2(asp, 1.0) * 0.42;
        float hw = pow(max(1.0 - length(float2(0.5, 0.5) - (uvG + hv)) / 0.75, 0.0), 4.0);
        g += float3(lens_tap1(uvG + hv * 1.02).r, lens_tap1(uvG + hv).g,
                    lens_tap1(uvG + hv * 0.98).b) * hw * 0.22;
        col += g * ghosts * 0.12;
    }

    col = max(float3(dot(L.r[8].xyz, col), dot(L.r[9].xyz, col), dot(L.r[10].xyz, col)), 0.0)
        * ld.y;
    col = saturate((col * (2.51 * col + 0.03)) / (col * (2.43 * col + 0.59) + 0.14));
    col = pow(col, 1.0 / 2.2);

    float l = dot(col, float3(0.2126, 0.7152, 0.0722));
    col = lerp(l * L.r[4].rgb, col, lb.y);
    col *= lerp(L.r[5].rgb, L.r[6].rgb, smoothstep(0.05, 0.75, l));
    col = saturate(lerp(float3(0.5, 0.5, 0.5), col, lb.z));

    float rv = length(uv - 0.5) * 1.4142;
    col *= lerp(1.0, smoothstep(1.2, 0.25, rv), lc.x);
    float cr = 0.05 * lc.z;
    float2 q = abs(uvG - 0.5) - (0.5 - cr);
    float rr = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - cr;
    col *= 1.0 - smoothstep(-0.004, 0.0, rr);
    float sc = length(c) - 0.47;
    col *= lerp(1.0, 1.0 - smoothstep(-0.03, 0.0, sc), ld.z);

    float scan = lc.y;
    if (scan > 0.001) {
        float lines = resolution.y / max(2.0, resolution.y / 260.0);
        float sl = 0.62 + 0.38 * sin(uvG.y * lines * PI * 2.0);
        float m = fmod(floor(pos.x), 3.0);
        float3 mk = m < 1.0 ? float3(1.0, 0.72, 0.72)
                  : (m < 2.0 ? float3(0.72, 1.0, 0.72) : float3(0.72, 0.72, 1.0));
        col *= lerp(float3(1.0, 1.0, 1.0), sl * 1.3 * mk * 1.12, scan);
        col *= 1.0 - scan * 0.025 * sin(time * 50.0 + uvG.y * 8.0);
    }

    float n = lens_hash12(pos.xy + frac(time * 7.13) * float2(431.0, 217.0)) - 0.5;
    col += n * lb.w * 0.22 * (0.35 + 2.6 * l * (1.0 - l));

    float vis = lerp(1.0, min(1.0, asp / 2.39), lc.w);
    col *= 1.0 - smoothstep(vis * 0.5 - 0.001, vis * 0.5, abs(uv.y - 0.5));

    col += (lens_hash12(pos.xy + 17.0 * frac(time)) - 0.5) / 255.0;
    return float4(lerp(backdrop.rgb, saturate(col) * ld.w, opacity), 1.0);
}
"""


def lens_shader(source: str, source_hlsl: str, looks: "tuple[Look, ...] | Look",
         period: float = 40.0, transition: float = 9.0,
         scene_inputs: "tuple[str, ...]" = (), scene_targets: tuple = (),
         scene_once: tuple = ()) -> dict:
    """The ``Shader`` fields for a scene filmed through ``looks``.

    ``source`` / ``source_hlsl`` define the scene's ``puikit_bg_fragment``,
    which returns linear HDR (and, for depth of field, inverse depth in alpha);
    they may call ``xefm_slot_hash``. One look holds; several cycle, one per
    ``period`` seconds with a ``transition`` into the next (see the module
    docstring). ``scene_inputs`` are what the scene pass reads (texture and
    target names); ``scene_targets`` and ``scene_once`` add targets and once
    passes ahead of it, for a scene that bakes something."""
    looks = (looks,) if isinstance(looks, Look) else tuple(looks)
    targets = [*scene_targets, Target(SCENE_TARGET)]
    passes = [*scene_once, Pass(SCENE_ENTRY, SCENE_TARGET, inputs=scene_inputs)]
    src = SCENE_TARGET
    for i in range(LEVELS):
        name = f"down{i}"
        targets.append(Target(name, scale=0.5 ** (i + 1)))
        passes.append(Pass("lens_down", name, inputs=(src,), params=(1.0 if i == 0 else 0.0,)))
        src = name
    low = f"down{LEVELS - 1}"
    for i in range(LEVELS - 2, -1, -1):
        name = f"up{i}"
        targets.append(Target(name, scale=0.5 ** (i + 1)))
        passes.append(Pass("lens_up", name, inputs=(low, f"down{i}")))
        low = name
    # With no streak the composite still samples slot 2, at zero weight: bind a
    # target that has been written, not one holding whatever the GPU left there.
    streak = "down1"
    if any(l.streak > STREAK_EPSILON for l in looks):
        targets += [Target("streak0", scale=0.25), Target("streak1", scale=0.25)]
        src = "down1"
        for i, step in enumerate(STREAK_STEPS):
            dst = f"streak{i % 2}"
            passes.append(Pass("lens_streak", dst, inputs=(src,), params=(step,)))
            src = dst
        streak = src
    passes.append(Pass("lens_composite", None, inputs=(SCENE_TARGET, "up0", streak)))
    return {
        "source": (SLOT_HASH_MSL + _constants(looks, period, transition, "msl")
                   + source + LENS_MSL),
        "source_hlsl": (SLOT_HASH_HLSL + _constants(looks, period, transition, "hlsl")
                        + source_hlsl + LENS_HLSL),
        "targets": tuple(targets),
        "passes": tuple(passes),
    }
