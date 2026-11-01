"""The Earth background scene: the planet from orbit, lit by a physically based
atmosphere and filmed through a choice of lenses.

Every other scene in ``xefm.background_shaders`` is procedural motion anchored on
the theme's ``ink``. This one is a picture: real surface, cloud and relief maps
(``xefm/assets/earth``, from NASA — see ``SOURCES.md`` there), single-scattering
Rayleigh and Mie air, three parallax cloud shells, a sun that reddens and shrinks
as it slides behind the limb, a star field, and a slow camera moving between
composed shots. It is physically coloured, so it **ignores** ``ink``; the theme's
``backdrop`` is still what it is mixed over (by the lens pass) and what it fades
to. The night side carries no city lights, by design.

**Textures and a lens.** It samples three textures (``Shader.textures``: day,
clouds, relief) and it returns *linear HDR* — the sun is thousands of times
brighter than the ground — which the lens passes of ``xefm.background_lens``
tone-map, grade and mix over the backdrop. The lens is part of the scene, not an
option: without it the HDR would clip. Which look is a theme choice
(:data:`LENSES`).

**Hundreds of scenes, chosen at random.** A scene is a shot (:data:`SHOTS`), one
of ``VARIANTS`` compositions of it (variant 0 is the shot as composed; the others
move the longitude, latitude, altitude, tilt, sun, lens length, framing and roll
by fixed amounts drawn from a hash, the low orbits turning the horizon any way
round), and a lens look — 10 x 12 x 10 = 1,200. Each ``SHOT_SECONDS`` slot of the
clock hashes, with PuiKit's ``seed`` uniform, to one of them:
``xefm_slot_hash(slot, seed)`` modulo the number of looks is the look (the lens
passes take it the same way), and the rest picks the shot and variant. PuiKit draws a new seed when the background is set and once each time
the user comes back to it after it parked, so XeFM opens on a random scene and
eases into a fresh one on a return (``seed_prev``/``seed_mix``).

**Everything moves as a function of ``time``** (and the seeds). The backend
advances a shader without XeFM's involvement, so there is no per-frame CPU state:
the camera follows one smooth path through all the scenes (``path_at``) — each
scene drifts steadily while it holds, and the move to the next one flows out of
that drift and into the next scene's, a monotone cubic through the scenes'
entry and exit poses — while the lens blends the looks over the move.
The sun's dip behind the limb in the ``rise`` shot and the earth's spin are
closed-form in ``time`` too. Per-theme options (which shot, which looks, cloud
height, exposure) are constants baked into the source when the theme is applied
(:func:`earth_shader`).

The camera is computed per pixel — the same few dozen operations everywhere,
small beside the atmosphere — rather than handed in as uniforms, which keeps "a
scene is a shader" true.

**Dialects.** MSL is the source of truth and the HLSL is a hand port, as for every
scene; the parity test compares their constants. There is no GLSL: the web
backend binds neither textures nor passes, and PuiKit draws the plain backdrop
there for a scene that needs them.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .background_lens import AVAILABLE, Look, lens_shader

if AVAILABLE:
    # PuiKit 1.17.0 and older have neither textures nor passes: the scene cannot
    # be built, so xefm.background_shaders leaves it out and a theme naming it
    # gets the plain background — the same as any unknown scene.
    from puikit.background import ShaderTexture

#: The textures, in the scene pass's slot order — day (sRGB colour), clouds
#: (grey coverage in red), relief (slope east/north in red/green, ocean mask in
#: blue). See ``tools/make_earth_textures.py``.
ASSET_DIR = Path(__file__).resolve().parent / "assets" / "earth"
TEXTURES = (
    ShaderTexture(str(ASSET_DIR / "day.jpg"), srgb=True, name="day"),
    ShaderTexture(str(ASSET_DIR / "clouds.jpg"), name="clouds"),
    ShaderTexture(str(ASSET_DIR / "relief.jpg"), name="relief"),
) if AVAILABLE else ()

#: Shot names, in the order of the shader's shot arrays. ``auto`` (or ``None``)
#: picks one at random per scene; a name holds that one shot.
SHOTS = ("day", "dawn", "crescent", "leo", "terminator", "glint", "rise", "polar",
         "horizon", "ocean")

#: Lens looks, by the name a theme's ``lens`` option uses. Pure data
#: (``background_lens.Look``); the thresholds are tuned to this scene's radiance
#: (exposure 1).
LENSES: "dict[str, Look]" = {
    "clean": Look(),
    "aberration": Look(aberration=0.018, distortion=0.06, vignette=0.35, bloom=0.45),
    "mono": Look(saturation=0.0, contrast=1.3, grain=0.45, vignette=0.5, bloom=0.35,
                 mono_tint=(1.0, 0.98, 0.94)),
    "film": Look(halation=0.9, grain=0.32, vignette=0.4, saturation=0.88, contrast=1.08,
                 bloom=0.45, aberration=0.002, shadow_tint=(0.86, 0.97, 1.08),
                 highlight_tint=(1.08, 1.0, 0.88)),
    "anamorphic": Look(streak=1.0, letterbox=1.0, bloom=0.5, aberration=0.003, ghosts=0.3,
                       vignette=0.25, threshold=1.2),
    "flare": Look(ghosts=1.0, bloom=0.65, aberration=0.004, vignette=0.2, threshold=1.2),
    "fisheye": Look(distortion=1.4, aberration=0.006, vignette=0.5, bloom=0.4),
    "crt": Look(scanlines=1.0, curvature=1.0, distortion=0.18, aberration=0.004, bloom=0.7,
                saturation=1.1, grain=0.2, vignette=0.6, contrast=1.1, threshold=1.0),
    "infrared": Look(color_matrix=(0.1, 1.3, -0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
                     saturation=1.15, contrast=1.1, bloom=0.4, grain=0.15, vignette=0.3),
    "night-vision": Look(saturation=0.0, mono_tint=(0.35, 1.0, 0.45), gain=2.4, grain=0.9,
                         scope=1.0, bloom=0.8, contrast=1.15, scanlines=0.25, threshold=1.0),
}

#: The defaults a theme gets for the options it does not name. ``"auto"`` lets
#: every look come up, one per scene.
DEFAULT_LENS = "auto"
DEFAULT_CLOUDS = 3.0
DEFAULT_EXPOSURE = 1.0
#: The ceiling of the picture, as a fraction of white: file names sit on it, so
#: by default no pixel of it is brighter than half white, whatever the shot and
#: the look (``Look.level``).
DEFAULT_BRIGHTNESS = 0.5

#: How long each scene holds on the scene clock (speed applied), and how much of
#: that is the move into the next. Baked into the shader and handed to the
#: lens, so the camera and the look change together.
SHOT_SECONDS = 49.0
TRANSITION = 18.0

#: The header :func:`earth_shader` prepends — the per-theme options as constants.
_MSL_OPTIONS = """
// --- per-theme options (baked by xefm.background_earth.earth_shader) ---------
constant int   SHOT     = {shot};     // -1 picks at random; else one shot
constant float CLOUD_H  = {clouds};   // cloud height exaggeration (1 = real ~14 km)
constant float EXPOSURE = {exposure};
constant int   LENS_COUNT = {lens_count};   // looks in the lens cycle (1 = fixed)
constant float SHOT_SECONDS = {period};     // how long each scene holds
constant float TRANSITION   = {transition}; // the move to the next, within those
"""

_HLSL_OPTIONS = """
// --- per-theme options (baked by xefm.background_earth.earth_shader) ---------
static const int   SHOT     = {shot};
static const float CLOUD_H  = {clouds};
static const float EXPOSURE = {exposure};
static const int   LENS_COUNT = {lens_count};
static const float SHOT_SECONDS = {period};
static const float TRANSITION   = {transition};
"""

EARTH_MSL_BODY = """
// --- tunables ---------------------------------------------------------------
constant float PI          = 3.14159265;
constant float RE          = 6360.0;     // ground radius, km
constant float RA          = 6420.0;     // top of the atmosphere, km
constant float HR          = 7.994;      // Rayleigh scale height, km
constant float HM          = 1.2;        // Mie scale height, km
constant float BM          = 0.021;      // Mie scattering, 1/km
constant float MIE_G       = 0.76;       // Mie anisotropy
constant float AUREOLE_G   = 0.985;      // the very forward lobe that hugs the sun
constant float SUN_I       = 22.0;       // sun irradiance, scene units
constant float SUN_R       = 0.0065;     // drawn sun radius, rad (~1.5x true)
constant float TILT        = 0.4091;     // axial tilt, rad
constant float SPIN        = 0.0025;     // earth rotation, rad/s
constant float CLOUD_DRIFT = 0.0009;     // cloud map drift, u per second
constant float RELIEF      = 0.35;       // strength of the relief map
constant int   VIEW_STEPS  = 14;         // atmosphere samples along the view ray
constant int   SHOT_COUNT  = 10;
constant int   VARIANTS    = 12;         // compositions per shot; 0 is the shot as composed
// How far a variant may move from its shot: degrees, radians, a fraction. The
// altitude, tilt and roll ranges are per shot (the SHOT_*J arrays below): a low
// orbit can turn the horizon any way round, a full disc only leans a little.
constant float JIT_LON     = 25.0;
constant float JIT_LAT     = 8.0;
constant float JIT_YAW     = 0.15;
constant float JIT_SPITCH  = 0.06;
constant float JIT_FOCAL   = 0.1;
constant float JIT_OFF     = 0.04;
constant float JIT_PHI     = 0.5;
// The move every scene makes while it holds, per second of the scene clock --
// each scene takes a speed between half and all of these. Its direction follows
// the way the camera is travelling, from the scene before toward the scene after,
// so that the move into a scene, the move within it and the move out of it run
// the same way wherever they can; where they cannot, the path turns smoothly
// (see path_at). Several at once, so the motion shows whatever the shot holds --
// a lit disc turns, a dark one drifts across the frame, grows and rolls.
constant float MOVE_LON    = 0.6;        // degrees round the planet
constant float MOVE_LAT    = 0.2;        // degrees
constant float MOVE_ALT    = 0.012;      // log of the altitude: in and out
constant float MOVE_PAN    = 0.0044;     // the planet across the frame, view heights
constant float MOVE_ZOOM   = 0.006;      // log of the lens length
constant float MOVE_YAW    = 0.003;      // the sun round the view, radians
constant float MOVE_ROLL   = 0.006;      // the camera turning about its axis, radians
constant float LIMB_PHI    = 0.55;       // where on the limb the sun meets it, rad
constant float LIMB_AMP    = 0.026;      // how far it swings across the limb, rad
constant float LIMB_PERIOD = 48.0;       // one dip and emergence, s
constant float LIMB_AT_X   = 0.1;        // where that point sits on screen
constant float LIMB_AT_Y   = 0.05;

constant float3 BR = float3(5.8e-3, 13.5e-3, 33.1e-3);   // Rayleigh, 1/km

// The shots: what the camera looks down on (lon, lat, degrees), its distance in
// earth radii, its tilt from nadir toward the horizon, where the earth sits in
// frame, the lens, and the sun relative to the view (yaw 0 = behind the earth,
// PI = behind the camera). The order is SHOTS in background_earth.py.
// horizon and ocean are low orbits too: sunrise along the horizon, and the
// daylit ocean seen obliquely. The *J columns are the variants' ranges.
//                              day    dawn   cresc  leo    term   glint   rise   polar  horizon ocean
constant float SHOT_LON[10]   = {20.0, 150.0, -40.0, 82.0, -68.0, -155.0, 120.0, 10.0, 100.0, -140.0};
constant float SHOT_LAT[10]   = {5.0, 10.0, 0.0, 22.0, -18.0, 8.0, 5.0, 72.0, 10.0, -10.0};
constant float SHOT_DIST[10]  = {3.1, 1.55, 3.3, 1.04, 1.9, 2.4, 3.0, 2.5, 1.03, 1.05};
constant float SHOT_PITCH[10] = {0.0, 0.55, 0.0, 1.18, 0.2, 0.1, 0.0, 0.15, 1.3, 0.95};
constant float SHOT_OFFX[10]  = {0.0, 0.05, 0.0, 0.0, -0.08, 0.12, 0.0, 0.0, 0.0, 0.0};
constant float SHOT_OFFY[10]  = {0.0, -0.05, 0.02, 0.0, 0.0, -0.04, 0.0, 0.05, 0.05, 0.0};
constant float SHOT_FOCAL[10] = {1.25, 1.0, 1.15, 0.85, 1.1, 1.15, 1.6, 1.15, 0.9, 0.9};
constant float SHOT_YAW[10]   = {2.55, 0.45, 0.38, 0.7, 1.55, 2.75, 0.3, 1.9, 0.12, 2.9};
constant float SHOT_SPITCH[10]= {0.22, 0.06, 0.14, 0.3, 0.12, 0.28, 0.1, 0.35, 0.03, 0.5};
constant float SHOT_LIMB[10]  = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0};
constant float SHOT_ALTJ[10]  = {0.15, 0.2, 0.15, 0.45, 0.2, 0.15, 0.1, 0.15, 0.4, 0.4};
constant float SHOT_PITCHJ[10]= {0.06, 0.12, 0.06, 0.18, 0.1, 0.08, 0.0, 0.1, 0.12, 0.2};
constant float SHOT_ROLLJ[10] = {0.5, 0.6, 0.5, 3.1416, 0.6, 0.5, 0.4, 0.8, 3.1416, 3.1416};

// A camera pose as numbers that interpolate: a = (longitude, latitude, log of
// the altitude in earth radii, tilt from nadir), b = (frame offset x, y, log of
// the lens length, sun yaw), c = (sun pitch, limb weight, limb angle, roll).
struct Pose { float4 a; float4 b; float4 c; };

struct Cam {
    float3 ro; float3 fw; float3 rt; float3 up; float3 L; float2 off; float focal; float roll;
};

static inline float3 rot_y(float a, float3 v) {
    float c = cos(a), s = sin(a);
    return float3(c * v.x + s * v.z, v.y, -s * v.x + c * v.z);
}

static inline float3 rot_x(float a, float3 v) {
    float c = cos(a), s = sin(a);
    return float3(v.x, c * v.y - s * v.z, s * v.y + c * v.z);
}

// World space to the earth's own frame (the one the maps are in).
static inline float3 to_earth(float3 v, float spin) {
    return rot_y(spin, rot_x(-TILT, v));
}

// The earth-fixed direction of a longitude/latitude, in the maps' convention.
static inline float3 earth_fixed(float lon, float lat) {
    float th = (lon + 180.0) / 360.0 * 2.0 * PI, ph = lat * PI / 180.0;
    return float3(-cos(th) * cos(ph), sin(ph), sin(th) * cos(ph));
}

static inline float2 earth_uv(float3 n) {
    return float2(fract(atan2(n.z, -n.x) / (2.0 * PI)), acos(clamp(n.y, -1.0, 1.0)) / PI);
}

// A fixed number in [0, 1) for a scene and a purpose: the same every frame and
// every launch, so a scene is a composition, not a dice roll per frame.
static inline float scene_rand(int id, int n) {
    return float(xefm_slot_hash(id * 16 + n, 0.0) & 0xFFFFu) / 65536.0;
}

static inline float scene_signed(int id, int n) {
    return scene_rand(id, n) * 2.0 - 1.0;
}

static inline Pose pose_add(Pose p, Pose q, float k) {
    Pose r;
    r.a = p.a + q.a * k;
    r.b = p.b + q.b * k;
    r.c = p.c + q.c * k;
    return r;
}

static inline Pose pose_lerp(Pose p, Pose q, float w) {
    Pose r;
    r.a = mix(p.a, q.a, w);
    r.b = mix(p.b, q.b, w);
    r.c = mix(p.c, q.c, w);
    return r;
}

static inline float wrap_near(float v, float ref, float period) {
    return v + period * floor((ref - v) / period + 0.5);
}

// p with its angles (longitude, sun yaw, roll) taken the short way from ref.
static inline Pose unwrap_to(Pose p, Pose ref) {
    p.a.x = wrap_near(p.a.x, ref.a.x, 360.0);
    p.b.w = wrap_near(p.b.w, ref.b.w, 2.0 * PI);
    p.c.w = wrap_near(p.c.w, ref.c.w, 2.0 * PI);
    return p;
}

// The shot and variant a slot shows.
static inline int2 scene_of(int slot, float seed) {
    if (SHOT >= 0) return int2(SHOT, 0);
    uint h = xefm_slot_hash(slot, seed) / uint(LENS_COUNT);
    return int2(int(h % uint(SHOT_COUNT)), int((h / uint(SHOT_COUNT)) % uint(VARIANTS)));
}

// Shot i in variant v, as composed: where the scene is at the middle of its hold.
static inline Pose composition(int2 sv) {
    int i = sv.x, id = sv.x * VARIANTS + sv.y;
    Pose p;
    p.a = float4(SHOT_LON[i], SHOT_LAT[i], log(SHOT_DIST[i] - 1.0), SHOT_PITCH[i]);
    p.b = float4(SHOT_OFFX[i], SHOT_OFFY[i], log(SHOT_FOCAL[i]), SHOT_YAW[i]);
    p.c = float4(SHOT_SPITCH[i], SHOT_LIMB[i], LIMB_PHI, 0.0);
    if (sv.y > 0) {
        p.a += float4(JIT_LON * scene_signed(id, 0), JIT_LAT * scene_signed(id, 1),
                      SHOT_ALTJ[i] * scene_signed(id, 2), SHOT_PITCHJ[i] * scene_signed(id, 3));
        p.b += float4(JIT_OFF * scene_signed(id, 4), JIT_OFF * scene_signed(id, 5),
                      JIT_FOCAL * scene_signed(id, 6), JIT_YAW * scene_signed(id, 7));
        p.c += float4(JIT_SPITCH * scene_signed(id, 8), 0.0, JIT_PHI * scene_signed(id, 9),
                      SHOT_ROLLJ[i] * scene_signed(id, 10));
    }
    return p;
}

// +1 or -1 per component: the way from `before` to `after`, or the scene's own
// coin where they agree (a held shot, or a component the shots share).
static inline float4 heading(float4 before, float4 after, int id, int n) {
    float4 d = after - before;
    float4 coin = float4(scene_signed(id, n), scene_signed(id, n + 1),
                         scene_signed(id, n + 2), scene_signed(id, n + 3));
    float4 dir = sign(d) + (1.0 - abs(sign(d))) * sign(coin + 1e-6);
    return dir;
}

// How fast a scene moves while it holds, per second: its speeds, pointed the way
// the camera travels through it (from the scene before to the scene after).
static inline Pose drift(int2 sv, Pose before, Pose after) {
    int id = sv.x * VARIANTS + sv.y;
    float4 ka = 0.5 + 0.5 * float4(scene_rand(id, 11), scene_rand(id, 12), scene_rand(id, 13), 0.0);
    float4 kb = 0.5 + 0.5 * float4(scene_rand(id, 14), scene_rand(id, 15), scene_rand(id, 16),
                                   scene_rand(id, 17));
    float kc = 0.5 + 0.5 * scene_rand(id, 18);
    Pose d;
    d.a = float4(MOVE_LON, MOVE_LAT, MOVE_ALT, 0.0) * ka * heading(before.a, after.a, id, 20);
    d.b = float4(MOVE_PAN, MOVE_PAN * 0.6, MOVE_ZOOM, MOVE_YAW) * kb
        * heading(before.b, after.b, id, 24);
    d.c = float4(0.0, 0.0, 0.0, MOVE_ROLL * kc) * heading(before.c, after.c, id, 28);
    return d;
}

// The tangent at a knot between a segment of slope s0 over dt0 and one of slope
// s1 over dt1: Fritsch-Butland's weighted harmonic mean, zero where the two
// slopes disagree. It keeps the path monotone between knots (no overshoot, so no
// back-and-forth), lets a slow hold meet a fast move at little more than the
// hold's own speed, and where a component has to turn back it slows to a stop
// and turns rather than flicking round.
static inline float4 knot_tangent(float4 s0, float dt0, float4 s1, float dt1) {
    float4 a = s0 + (step(0.0, s0) * 2.0 - 1.0) * 1e-9;
    float4 b = s1 + (step(0.0, s1) * 2.0 - 1.0) * 1e-9;
    float4 m = 3.0 * (dt0 + dt1) / ((2.0 * dt1 + dt0) / a + (dt1 + 2.0 * dt0) / b);
    return m * step(1e-18, s0 * s1);
}

static inline Pose pose_tangent(Pose s0, float dt0, Pose s1, float dt1) {
    Pose m;
    m.a = knot_tangent(s0.a, dt0, s1.a, dt1);
    m.b = knot_tangent(s0.b, dt0, s1.b, dt1);
    m.c = knot_tangent(s0.c, dt0, s1.c, dt1);
    return m;
}

// Cubic Hermite from p0 (tangent m0) to p1 (tangent m1) over dt, at u.
static inline Pose hermite(Pose p0, Pose m0, Pose p1, Pose m1, float dt, float u) {
    float s = clamp(u / dt, 0.0, 1.0), s2 = s * s, s3 = s2 * s;
    float h00 = 2.0 * s3 - 3.0 * s2 + 1.0, h10 = s3 - 2.0 * s2 + s;
    float h01 = 3.0 * s2 - 2.0 * s3, h11 = s3 - s2;
    Pose r;
    r.a = p0.a * h00 + m0.a * (h10 * dt) + p1.a * h01 + m1.a * (h11 * dt);
    r.b = p0.b * h00 + m0.b * (h10 * dt) + p1.b * h01 + m1.b * (h11 * dt);
    r.c = p0.c * h00 + m0.c * (h10 * dt) + p1.c * h01 + m1.c * (h11 * dt);
    return r;
}

static inline Pose pose_scale(Pose p, float k) {
    Pose r;
    r.a = p.a * k;
    r.b = p.b * k;
    r.c = p.c * k;
    return r;
}

static inline Pose pose_slope(Pose from, Pose to, float dt) {
    return pose_scale(pose_add(to, from, -1.0), 1.0 / dt);
}

// The camera's path for one seed. Each slot k holds its scene for HOLD seconds
// and then moves to the next over TRANSITION. A scene contributes two knots: it
// enters at its composition minus half its drift over the hold and leaves at
// the composition plus half. The path runs through every knot as one smooth
// curve -- a monotone cubic, so the speed changes gradually everywhere and the
// direction never flicks: the hold drifts steadily, the move out of it starts
// from that drift and ends in the next scene's, which (headed the same way where
// it can be) carries straight on.
static inline Pose path_at(float t, float seed) {
    float hold = SHOT_SECONDS - TRANSITION;
    int k = int(floor(t / SHOT_SECONDS));
    float u = t - float(k) * SHOT_SECONDS;
    int2 s_2 = scene_of(k - 2, seed), s_1 = scene_of(k - 1, seed), s0 = scene_of(k, seed);
    int2 s1 = scene_of(k + 1, seed), s2 = scene_of(k + 2, seed);
    Pose c0 = composition(s0);
    Pose c_1 = unwrap_to(composition(s_1), c0);
    Pose c_2 = unwrap_to(composition(s_2), c_1);
    Pose c1 = unwrap_to(composition(s1), c0);
    Pose c2 = unwrap_to(composition(s2), c1);
    Pose d_1 = drift(s_1, c_2, c0), d0 = drift(s0, c_1, c1), d1 = drift(s1, c0, c2);
    Pose x_1 = pose_add(c_1, d_1, 0.5 * hold);           // the scene before leaves here
    Pose e0 = pose_add(c0, d0, -0.5 * hold);             // this one enters
    Pose x0 = pose_add(c0, d0, 0.5 * hold);              // and leaves
    Pose e1 = pose_add(c1, d1, -0.5 * hold);             // the next one enters
    Pose s_in = pose_slope(x_1, e0, TRANSITION);
    Pose s_out = pose_slope(x0, e1, TRANSITION);
    Pose m_x0 = pose_tangent(d0, hold, s_out, TRANSITION);
    if (u < hold) {
        return hermite(e0, pose_tangent(s_in, TRANSITION, d0, hold), x0, m_x0, hold, u);
    }
    return hermite(x0, m_x0, e1, pose_tangent(s_out, TRANSITION, d1, hold), TRANSITION,
                   u - hold);
}

// The whole camera and sun, from time and the seeds alone. Each SHOT_SECONDS slot
// hashes to a scene; the low part of the hash is the lens look the lens passes
// pick for the same slot (they take it modulo LENS_COUNT), and the rest picks
// the shot and its variant -- so every combination can come up. A new seed
// (each launch, each return from idle) means new scenes; while seed_mix is
// below 1 the path for the old seed blends into the new one, as the lens blends
// the looks.
static inline Cam camera(float t, float aspect, float seed, float seed_prev, float seed_mix) {
    float fov = aspect < 0.8 ? 0.75 : 1.0;      // portrait: widen the lens
    float spin = SPIN * t;
    Pose P = path_at(t, seed);
    if (seed_mix < 1.0) P = pose_lerp(unwrap_to(path_at(t, seed_prev), P), P, seed_mix);
    float dist = 1.0 + exp(P.a.z);
    // A gentle hand-held breathing on the tilt and the sun.
    float pitch = P.a.w + sin(t * 0.053) * 0.008;
    float yaw = P.b.w + sin(t * 0.07) * 0.01;
    float spitch = P.c.x;
    float limb = clamp(P.c.y, 0.0, 1.0);
    float phi = P.c.z;
    float roll = P.c.w;
    // The camera follows its spot round as the earth turns, so a shot holds its
    // framing; the spin shows in the stars and the drifting cloud instead.
    float3 d = normalize(rot_x(TILT, rot_y(-spin, earth_fixed(P.a.x, clamp(P.a.y, -80.0, 80.0)))));

    Cam c;
    c.focal = exp(P.b.z) * fov;
    c.off = P.b.xy;
    if (limb > 0.0) {
        // Frame so the point of the limb the sun meets sits at LIMB_AT on screen.
        float r = tan(asin(1.0 / dist)) * c.focal;
        c.off += limb * float2(cos(phi) * r - LIMB_AT_X, sin(phi) * r - LIMB_AT_Y);
    }
    c.ro = d * dist * RE;
    float3 upT = float3(0.0, 1.0, 0.0) - d * d.y;
    upT = dot(upT, upT) < 1e-8 ? float3(0.0, 0.0, 1.0) : normalize(upT);
    c.fw = normalize(-d * cos(pitch) + upT * sin(pitch));
    c.rt = normalize(cross(c.fw, upT));
    c.up = cross(c.rt, c.fw);
    // The roll turns the finished picture on the screen (see the fragment), so the
    // sun keeps its place against the planet and the limb framing still holds.
    c.roll = roll;
    float3 L = normalize(c.fw * (cos(spitch) * cos(yaw)) + c.rt * (cos(spitch) * sin(yaw))
                         + c.up * sin(spitch));
    if (limb > 0.001) {
        // The sun sliding behind the limb and back out: its centre swings
        // +-LIMB_AMP about the edge, once per LIMB_PERIOD.
        float aE = asin(1.0 / dist);
        float th = aE + LIMB_AMP * sin(2.0 * PI * t / LIMB_PERIOD);
        float3 side = c.rt * cos(phi) + c.up * sin(phi);
        float3 L2 = normalize(c.fw * cos(th) + side * sin(th));
        L = normalize(mix(L, L2, limb));
    }
    c.L = L;
    return c;
}

static inline float2 ray_sphere(float3 ro, float3 rd, float r) {
    float b = dot(ro, rd), c = dot(ro, ro) - r * r, h = b * b - c;
    if (h < 0.0) return float2(1e9, -1e9);
    h = sqrt(h);
    return float2(-b - h, -b + h);
}

// Optical depth of one exponential layer (scale height H) from altitude h along a
// ray at cos(zenith) mu, out to infinity: Schueler's approximation of the Chapman
// function (GPU Pro 3). Closed form, so the sun's light reaches each view sample
// without a march of its own -- that inner march was most of the scene's cost.
static inline float chapman(float h, float mu, float H) {
    float X = RE / H, hn = max(h, 0.0) / H;
    float c = sqrt(X + hn);
    if (mu >= 0.0) return H * c / (c * mu + 1.0) * exp(-hn);
    float x0 = sqrt(max(1.0 - mu * mu, 0.0)) * (X + hn);
    float c0 = sqrt(x0);
    return H * (2.0 * c0 * exp(X - x0) - c / (1.0 - c * mu) * exp(-hn));
}

// Optical depth (Rayleigh, Mie) from p toward the sun; x < 0 when the ground
// is in the way.
static inline float2 light_depth(float3 p, float3 L) {
    float r = length(p);
    float mu = dot(p, L) / r;
    // Below the horizon the ray meets the ground: no direct sun at all.
    if (mu < -sqrt(max(1.0 - (RE / r) * (RE / r), 0.0))) return float2(-1.0, -1.0);
    float h = r - RE;
    return float2(chapman(h, mu, HR), chapman(h, mu, HM));
}

static inline float3 sun_att(float3 p, float3 L) {
    float2 d = light_depth(p, L);
    return d.x < 0.0 ? float3(0.0) : exp(-(BR * d.x + BM * 1.1 * d.y));
}

// Single scattering along the view ray between t0 and t1.
static inline float3 scatter(float3 ro, float3 rd, float t0, float t1, float3 L,
                             thread float3 &trans) {
    float st = (t1 - t0) / float(VIEW_STEPS);
    float3 sR = float3(0.0), sM = float3(0.0);
    float oR = 0.0, oM = 0.0;
    for (int i = 0; i < VIEW_STEPS; i++) {
        float3 p = ro + rd * (t0 + (float(i) + 0.5) * st);
        float h = length(p) - RE;
        float dR = exp(-h / HR) * st, dM = exp(-h / HM) * st;
        oR += dR;
        oM += dM;
        float2 l = light_depth(p, L);
        if (l.x < 0.0) continue;
        float3 att = exp(-(BR * (oR + l.x) + BM * 1.1 * (oM + l.y)));
        sR += att * dR;
        sM += att * dM;
    }
    trans = exp(-(BR * oR + BM * 1.1 * oM));
    float mu = dot(rd, L);
    float pR = 3.0 / (16.0 * PI) * (1.0 + mu * mu);
    float g2 = MIE_G * MIE_G;
    float pM = 3.0 / (8.0 * PI) * ((1.0 - g2) * (1.0 + mu * mu))
             / ((2.0 + g2) * pow(1.0 + g2 - 2.0 * MIE_G * mu, 1.5));
    float ga2 = AUREOLE_G * AUREOLE_G;
    float pA = (1.0 - ga2) / (4.0 * PI * pow(1.0 + ga2 - 2.0 * AUREOLE_G * mu, 1.5));
    return SUN_I * 0.55 * (sR * BR * pR + sM * BM * (pM + 0.02 * pA));
}

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

static inline float vnoise(float3 x) {
    float3 i = floor(x), f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash13(i), hash13(i + float3(1, 0, 0)), f.x),
                   mix(hash13(i + float3(0, 1, 0)), hash13(i + float3(1, 1, 0)), f.x), f.y),
               mix(mix(hash13(i + float3(0, 0, 1)), hash13(i + float3(1, 0, 1)), f.x),
                   mix(hash13(i + float3(0, 1, 1)), hash13(i + float3(1, 1, 1)), f.x), f.y),
               f.z);
}

static inline float fbm(float3 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 5; i++) {
        s += a * vnoise(p);
        p = p * 2.07 + 11.3;
        a *= 0.5;
    }
    return s;
}

static inline float3 star_layer(float3 rd, float R, float pxAng, float density, float seed,
                                float t) {
    float3 c = floor(rd * R);
    float3 h = hash33(c + seed);
    if (h.x > density) return float3(0.0);
    float3 s = normalize(c + 0.25 + 0.5 * hash33(c + seed + 7.1));
    float ang = length(cross(rd, s));
    float mag = pow(hash13(c + seed + 3.3), 6.0);
    float r = pxAng * 0.65;
    float core = exp(-ang * ang / (r * r));
    float3 tint = mix(float3(1.0, 0.78, 0.58), float3(0.66, 0.78, 1.0), h.y);
    float tw = 0.85 + 0.15 * sin(t * (1.0 + 3.0 * h.z) + h.y * 40.0);
    return tint * core * (0.03 + 1.6 * mag) * tw;
}

static inline float3 stars(float3 rd, float pxAng, float t) {
    float3 col = star_layer(rd, 60.0, pxAng, 0.2, 0.0, t)
               + star_layer(rd, 130.0, pxAng, 0.3, 19.7, t) * 0.5;
    // A faint Milky Way: a band of dust with darker lanes through it. The two
    // fbm calls are the dearest thing in the sky, so they run only inside the
    // band -- outside it they would be multiplied by next to nothing.
    float3 gN = normalize(float3(0.3, 0.85, -0.42));
    float b = dot(rd, gN), band = exp(-b * b * 28.0);
    if (band > 0.02) {
        float dust = fbm(rd * 6.0), lanes = fbm(rd * 13.0 + 4.0);
        col += float3(0.55, 0.6, 0.75) * band * smoothstep(0.35, 0.8, dust) * 0.05
             * (1.0 - 0.7 * smoothstep(0.5, 0.75, lanes));
        col += star_layer(rd, 230.0, pxAng, 0.5 * band, 41.0, t) * 0.4;
    }
    return col;
}

// The mip level that matches a pixel's footprint on the sphere. Explicit rather
// than from screen derivatives: those jump at the map's date-line seam (u wraps
// from 1 to 0), which picks the smallest mip along a visible line.
static inline float lod_for(float dist, float mu, float pxAng, float width) {
    float foot = dist * pxAng / sqrt(max(mu, 0.04));
    return max(log2(foot * width / (2.0 * PI * RE)), 0.0);
}

static inline float cloud_cover(texture2d<float> clouds, sampler s, float3 ne, float lod,
                                float t) {
    return clouds.sample(s, earth_uv(ne) + float2(t * CLOUD_DRIFT, 0.0), level(lod)).r;
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]],
                                   texture2d<float> day [[texture(0)]],
                                   texture2d<float> clouds [[texture(1)]],
                                   texture2d<float> relief [[texture(2)]],
                                   sampler sDay [[sampler(0)]],
                                   sampler sClouds [[sampler(1)]],
                                   sampler sRelief [[sampler(2)]]) {
    float t = u.time;
    Cam cam = camera(t, u.resolution.x / u.resolution.y, u.seed, u.seed_prev, u.seed_mix);
    // y up, as the shot table was composed; then turned by the roll, about the
    // middle of the screen, before the framing offset places the composition.
    float2 uv0 = float2(pos.x - 0.5 * u.resolution.x, 0.5 * u.resolution.y - pos.y)
               / u.resolution.y;
    float cr = cos(cam.roll), sr = sin(cam.roll);
    float2 uv = float2(cr * uv0.x - sr * uv0.y, sr * uv0.x + cr * uv0.y) + cam.off;
    float3 ro = cam.ro, L = cam.L;
    float3 rd = normalize(cam.fw * cam.focal + uv.x * cam.rt + uv.y * cam.up);
    float pxAng = 1.0 / (u.resolution.y * cam.focal);
    float spin = SPIN * t;
    float3 Le = to_earth(L, spin);
    float dayW = float(day.get_width());
    float cloudW = float(clouds.get_width());
    float reliefW = float(relief.get_width());

    float2 tE = ray_sphere(ro, rd, RE), tA = ray_sphere(ro, rd, RA);
    bool hitE = tE.x > 0.0 && tE.x < 1e8;
    float3 trans = float3(1.0), ins = float3(0.0);
    if (tA.x < 1e8) ins = scatter(ro, rd, max(tA.x, 0.0), hitE ? tE.x : tA.y, L, trans);

    // Clouds: three stacked shells, thicker cover reaching the higher ones. Each
    // is intersected on its own, so it shifts against the ground as the camera
    // moves -- that is the parallax.
    float3 cC = float3(0.0);
    float cA = 0.0;
    float hTop = 4.0 + 10.0 * CLOUD_H;
    for (int i = 2; i >= 0; i--) {
        float fi = float(i);
        float rc = RE + hTop * (0.55 + 0.225 * fi);
        float tc = ray_sphere(ro, rd, rc).x;
        if (tc <= 0.0 || tc > 1e8 || (hitE && tc > tE.x)) continue;
        float3 pc = ro + rd * tc, nc = normalize(pc), ne = to_earth(nc, spin);
        float lod = lod_for(tc, abs(dot(nc, rd)), pxAng, cloudW);
        float c = cloud_cover(clouds, sClouds, ne, lod, t);
        float th = 0.08 + 0.2 * fi;
        float d = smoothstep(th, th + 0.35, c);
        if (d <= 0.001) continue;
        // Self-shadow: how much cover sits toward the sun from here.
        float occ = cloud_cover(clouds, sClouds, normalize(ne + Le * (0.003 + 0.002 * fi)),
                                lod, t);
        float ndl = dot(nc, L);
        float3 sunlit = SUN_I * 0.085 * sun_att(pc * 1.0002, L) * smoothstep(-0.15, 0.55, ndl);
        float3 col = sunlit * (0.62 + 0.19 * fi)
                   * (1.0 - 0.45 * smoothstep(0.3, 0.9, occ) * (1.0 - fi * 0.4));
        col += float3(0.4, 0.55, 0.8) * 0.012;   // faint skylight keeps the shadowed side's form
        float a = d * 0.9;
        cC += (1.0 - cA) * a * col;
        cA += (1.0 - cA) * a;
    }

    float3 base;
    if (hitE) {
        float3 p = ro + rd * tE.x, n = normalize(p);
        float3 ne = to_earth(n, spin);
        float2 tuv = earth_uv(ne);
        float mu = max(dot(n, -rd), 0.0);
        float3 alb = day.sample(sDay, tuv, level(lod_for(tE.x, mu, pxAng, dayW))).rgb;
        float4 rel = relief.sample(sRelief, tuv, level(lod_for(tE.x, mu, pxAng, reliefW)));
        float ocean = rel.b;
        float3 E0 = cross(float3(0.0, 1.0, 0.0), ne);
        float3 E = dot(E0, E0) > 1e-8 ? normalize(E0) : float3(1.0, 0.0, 0.0);
        float3 Nn = cross(ne, E);
        float2 nm = rel.rg * 2.0 - 1.0;
        float3 ns = normalize(ne + RELIEF * (nm.x * E + nm.y * Nn));

        // Cloud shadow, cast along the true sun direction onto the ground.
        float tS = ray_sphere(p, L, RE + hTop * 0.775).y;
        float cs = smoothstep(0.1, 0.6, cloud_cover(clouds, sClouds,
                              to_earth(normalize(p + L * tS), spin),
                              lod_for(tE.x, mu, pxAng, cloudW), t));

        float ndl = dot(ne, Le);
        float3 sun = SUN_I * 0.15 * sun_att(p * 1.0004, L);
        float3 surf = alb * sun * max(dot(ns, Le), 0.0) * (1.0 - 0.6 * cs);
        float3 ve = to_earth(-rd, spin), hv = normalize(Le + ve);
        float fres = 0.02 + 0.98 * pow(1.0 - max(dot(ne, ve), 0.0), 5.0);
        float nh = max(dot(ne, hv), 0.0);
        float spec = pow(nh, 260.0) * 2.2 + pow(nh, 24.0) * 0.05;
        surf += sun * ocean * (spec + fres * 0.08) * (1.0 - cs) * step(0.0, ndl);
        // The night side: no city lights, only the faintest moonlit trace of land.
        surf += alb * float3(0.5, 0.62, 0.85) * 0.006 * (1.0 - smoothstep(-0.2, 0.05, ndl));
        base = surf;
    } else {
        float disk = smoothstep(cos(SUN_R * 1.12), cos(SUN_R * 0.88), dot(rd, L));
        base = stars(rd, pxAng, t) * 0.9 + float3(1.0, 0.96, 0.9) * disk * 60.0;
    }
    float3 col = (base * (1.0 - cA) + cC) * trans + ins;

    // Airglow: a thin green line ~95 km up, seen along the night-side limb.
    float tm = -dot(ro, rd);
    if (tm > 0.0 && (!hitE || tm < tE.x + 400.0)) {
        float3 pm = ro + rd * tm;
        float hm = length(pm) - RE;
        float night = 1.0 - smoothstep(-0.25, 0.1, dot(normalize(pm), L));
        float g = (hm - 95.0) / 4.5;
        col += float3(0.32, 1.0, 0.5) * exp(-g * g) * night * 0.035;
    }

    // --- the sun against the limb ---
    float3 eC = -normalize(ro);
    float aE = asin(RE / length(ro));                  // the earth's angular radius
    float thS = acos(clamp(dot(L, eC), -1.0, 1.0));
    float dS = thS - aE;                               // sun centre above (+) / below (-) the limb
    // The visible share of the disk: a circular segment cut by a straight limb.
    float hh = clamp((dS + SUN_R) / (2.0 * SUN_R), 0.0, 1.0), xx = 1.0 - 2.0 * hh;
    float vis = (acos(xx) - xx * sqrt(max(1.0 - xx * xx, 0.0))) / PI;
    // What still shows comes in grazing, through the most air, so it reddens.
    float3 perp = L - eC * dot(L, eC);
    perp = dot(perp, perp) > 1e-10 ? normalize(perp) : float3(0.0, 1.0, 0.0);
    float aV = max(thS, aE + 0.0009);
    float3 sunTv = sun_att(ro, eC * cos(aV) + perp * sin(aV));

    // Glare: brightness follows the visible share, and its radius shrinks with it.
    float muS = max(dot(rd, L), 0.0);
    float kC = 2200.0 / max(vis, 0.02), kW = 60.0 / max(sqrt(vis), 0.12);
    col += sunTv * vis * (float3(1.0, 0.9, 0.78) * pow(muS, kC) * 3.0
                        + float3(0.9, 0.85, 0.8) * pow(muS, kW) * 0.05);

    // Limb flare: as the sun touches the edge the air beside it lights up and
    // swells, fusing with the disk -- strongest along the limb, falling off away
    // from the sun.
    float q = dS / (5.0 * SUN_R);
    float prox = exp(-q * q);
    float angE = acos(clamp(dot(rd, eC), -1.0, 1.0));
    float dl = angE - aE;                              // pixel above (+) / inside (-) the limb
    float angS = acos(clamp(dot(rd, L), -1.0, 1.0));
    float band = exp(-abs(dl - 0.0012) / mix(0.0015, 0.004, prox));
    float swell = exp(-angS / (0.035 + 0.06 * prox)) * band * 2.4
                + exp(-angS / (SUN_R * (2.0 + 4.0 * prox))) * 0.6;
    float3 flareCol = mix(float3(1.0, 0.55, 0.25), float3(1.0, 0.92, 0.8), vis);
    col += sunTv * flareCol * swell * prox * (0.25 + 0.75 * vis) * 1.6;

    // Linear HDR out: the lens tone-maps, grades and mixes over the backdrop.
    return float4(max(col * EXPOSURE, 0.0), 1.0);
}
"""

#: The HLSL translation of :data:`EARTH_MSL_BODY` for the Direct3D 11 (Windows)
#: backend: the same maths line for line, with the dialect's spellings —
#: ``frac``/``lerp``, ``static const``, an ``out`` parameter for the
#: transmittance, the textures and samplers as globals in the registers the slot
#: order gives (t0..t2, s0..s2), and the uniforms read from the cbuffer. Keep the
#: two in sync when tuning the scene; the parity test compares their constants.
EARTH_HLSL_BODY = """
// --- tunables ---------------------------------------------------------------
static const float PI          = 3.14159265;
static const float RE          = 6360.0;     // ground radius, km
static const float RA          = 6420.0;     // top of the atmosphere, km
static const float HR          = 7.994;      // Rayleigh scale height, km
static const float HM          = 1.2;        // Mie scale height, km
static const float BM          = 0.021;      // Mie scattering, 1/km
static const float MIE_G       = 0.76;       // Mie anisotropy
static const float AUREOLE_G   = 0.985;      // the very forward lobe that hugs the sun
static const float SUN_I       = 22.0;       // sun irradiance, scene units
static const float SUN_R       = 0.0065;     // drawn sun radius, rad (~1.5x true)
static const float TILT        = 0.4091;     // axial tilt, rad
static const float SPIN        = 0.0025;     // earth rotation, rad/s
static const float CLOUD_DRIFT = 0.0009;     // cloud map drift, u per second
static const float RELIEF      = 0.35;       // strength of the relief map
static const int   VIEW_STEPS  = 14;         // atmosphere samples along the view ray
static const int   SHOT_COUNT  = 10;
static const int   VARIANTS    = 12;         // compositions per shot; 0 is the shot as composed
// How far a variant may move from its shot: degrees, radians, a fraction. The
// altitude, tilt and roll ranges are per shot (the SHOT_*J arrays below): a low
// orbit can turn the horizon any way round, a full disc only leans a little.
static const float JIT_LON     = 25.0;
static const float JIT_LAT     = 8.0;
static const float JIT_YAW     = 0.15;
static const float JIT_SPITCH  = 0.06;
static const float JIT_FOCAL   = 0.1;
static const float JIT_OFF     = 0.04;
static const float JIT_PHI     = 0.5;
// The move every scene makes while it holds, per second of the scene clock --
// each scene takes a speed between half and all of these. Its direction follows
// the way the camera is travelling, from the scene before toward the scene after,
// so that the move into a scene, the move within it and the move out of it run
// the same way wherever they can; where they cannot, the path turns smoothly
// (see path_at). Several at once, so the motion shows whatever the shot holds --
// a lit disc turns, a dark one drifts across the frame, grows and rolls.
static const float MOVE_LON    = 0.6;        // degrees round the planet
static const float MOVE_LAT    = 0.2;        // degrees
static const float MOVE_ALT    = 0.012;      // log of the altitude: in and out
static const float MOVE_PAN    = 0.0044;     // the planet across the frame, view heights
static const float MOVE_ZOOM   = 0.006;      // log of the lens length
static const float MOVE_YAW    = 0.003;      // the sun round the view, radians
static const float MOVE_ROLL   = 0.006;      // the camera turning about its axis, radians
static const float LIMB_PHI    = 0.55;       // where on the limb the sun meets it, rad
static const float LIMB_AMP    = 0.026;      // how far it swings across the limb, rad
static const float LIMB_PERIOD = 48.0;       // one dip and emergence, s
static const float LIMB_AT_X   = 0.1;        // where that point sits on screen
static const float LIMB_AT_Y   = 0.05;

static const float3 BR = float3(5.8e-3, 13.5e-3, 33.1e-3);   // Rayleigh, 1/km

Texture2D day : register(t0);
Texture2D clouds : register(t1);
Texture2D relief : register(t2);
SamplerState sDay : register(s0);
SamplerState sClouds : register(s1);
SamplerState sRelief : register(s2);

// The shots: what the camera looks down on (lon, lat, degrees), its distance in
// earth radii, its tilt from nadir toward the horizon, where the earth sits in
// frame, the lens, and the sun relative to the view (yaw 0 = behind the earth,
// PI = behind the camera). The order is SHOTS in background_earth.py.
// horizon and ocean are low orbits too: sunrise along the horizon, and the
// daylit ocean seen obliquely. The *J columns are the variants' ranges.
//                              day    dawn   cresc  leo    term   glint   rise   polar  horizon ocean
static const float SHOT_LON[10]   = {20.0, 150.0, -40.0, 82.0, -68.0, -155.0, 120.0, 10.0, 100.0, -140.0};
static const float SHOT_LAT[10]   = {5.0, 10.0, 0.0, 22.0, -18.0, 8.0, 5.0, 72.0, 10.0, -10.0};
static const float SHOT_DIST[10]  = {3.1, 1.55, 3.3, 1.04, 1.9, 2.4, 3.0, 2.5, 1.03, 1.05};
static const float SHOT_PITCH[10] = {0.0, 0.55, 0.0, 1.18, 0.2, 0.1, 0.0, 0.15, 1.3, 0.95};
static const float SHOT_OFFX[10]  = {0.0, 0.05, 0.0, 0.0, -0.08, 0.12, 0.0, 0.0, 0.0, 0.0};
static const float SHOT_OFFY[10]  = {0.0, -0.05, 0.02, 0.0, 0.0, -0.04, 0.0, 0.05, 0.05, 0.0};
static const float SHOT_FOCAL[10] = {1.25, 1.0, 1.15, 0.85, 1.1, 1.15, 1.6, 1.15, 0.9, 0.9};
static const float SHOT_YAW[10]   = {2.55, 0.45, 0.38, 0.7, 1.55, 2.75, 0.3, 1.9, 0.12, 2.9};
static const float SHOT_SPITCH[10]= {0.22, 0.06, 0.14, 0.3, 0.12, 0.28, 0.1, 0.35, 0.03, 0.5};
static const float SHOT_LIMB[10]  = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0};
static const float SHOT_ALTJ[10]  = {0.15, 0.2, 0.15, 0.45, 0.2, 0.15, 0.1, 0.15, 0.4, 0.4};
static const float SHOT_PITCHJ[10]= {0.06, 0.12, 0.06, 0.18, 0.1, 0.08, 0.0, 0.1, 0.12, 0.2};
static const float SHOT_ROLLJ[10] = {0.5, 0.6, 0.5, 3.1416, 0.6, 0.5, 0.4, 0.8, 3.1416, 3.1416};

// A camera pose as numbers that interpolate: a = (longitude, latitude, log of
// the altitude in earth radii, tilt from nadir), b = (frame offset x, y, log of
// the lens length, sun yaw), c = (sun pitch, limb weight, limb angle, roll).
struct Pose { float4 a; float4 b; float4 c; };

struct Cam {
    float3 ro; float3 fw; float3 rt; float3 up; float3 L; float2 off; float focal; float roll;
};

float3 rot_y(float a, float3 v) {
    float c = cos(a), s = sin(a);
    return float3(c * v.x + s * v.z, v.y, -s * v.x + c * v.z);
}

float3 rot_x(float a, float3 v) {
    float c = cos(a), s = sin(a);
    return float3(v.x, c * v.y - s * v.z, s * v.y + c * v.z);
}

// World space to the earth's own frame (the one the maps are in).
float3 to_earth(float3 v, float spin) {
    return rot_y(spin, rot_x(-TILT, v));
}

// The earth-fixed direction of a longitude/latitude, in the maps' convention.
float3 earth_fixed(float lon, float lat) {
    float th = (lon + 180.0) / 360.0 * 2.0 * PI, ph = lat * PI / 180.0;
    return float3(-cos(th) * cos(ph), sin(ph), sin(th) * cos(ph));
}

float2 earth_uv(float3 n) {
    return float2(frac(atan2(n.z, -n.x) / (2.0 * PI)), acos(clamp(n.y, -1.0, 1.0)) / PI);
}

// A fixed number in [0, 1) for a scene and a purpose: the same every frame and
// every launch, so a scene is a composition, not a dice roll per frame.
float scene_rand(int id, int n) {
    return float(xefm_slot_hash(id * 16 + n, 0.0) & 0xFFFFu) / 65536.0;
}

float scene_signed(int id, int n) {
    return scene_rand(id, n) * 2.0 - 1.0;
}

Pose pose_add(Pose p, Pose q, float k) {
    Pose r;
    r.a = p.a + q.a * k;
    r.b = p.b + q.b * k;
    r.c = p.c + q.c * k;
    return r;
}

Pose pose_lerp(Pose p, Pose q, float w) {
    Pose r;
    r.a = lerp(p.a, q.a, w);
    r.b = lerp(p.b, q.b, w);
    r.c = lerp(p.c, q.c, w);
    return r;
}

float wrap_near(float v, float ref, float period) {
    return v + period * floor((ref - v) / period + 0.5);
}

// p with its angles (longitude, sun yaw, roll) taken the short way from ref.
Pose unwrap_to(Pose p, Pose ref) {
    p.a.x = wrap_near(p.a.x, ref.a.x, 360.0);
    p.b.w = wrap_near(p.b.w, ref.b.w, 2.0 * PI);
    p.c.w = wrap_near(p.c.w, ref.c.w, 2.0 * PI);
    return p;
}

// The shot and variant a slot shows.
int2 scene_of(int slot, float seed) {
    if (SHOT >= 0) return int2(SHOT, 0);
    uint h = xefm_slot_hash(slot, seed) / uint(LENS_COUNT);
    return int2(int(h % uint(SHOT_COUNT)), int((h / uint(SHOT_COUNT)) % uint(VARIANTS)));
}

// Shot i in variant v, as composed: where the scene is at the middle of its hold.
Pose composition(int2 sv) {
    int i = sv.x, id = sv.x * VARIANTS + sv.y;
    Pose p;
    p.a = float4(SHOT_LON[i], SHOT_LAT[i], log(SHOT_DIST[i] - 1.0), SHOT_PITCH[i]);
    p.b = float4(SHOT_OFFX[i], SHOT_OFFY[i], log(SHOT_FOCAL[i]), SHOT_YAW[i]);
    p.c = float4(SHOT_SPITCH[i], SHOT_LIMB[i], LIMB_PHI, 0.0);
    if (sv.y > 0) {
        p.a += float4(JIT_LON * scene_signed(id, 0), JIT_LAT * scene_signed(id, 1),
                      SHOT_ALTJ[i] * scene_signed(id, 2), SHOT_PITCHJ[i] * scene_signed(id, 3));
        p.b += float4(JIT_OFF * scene_signed(id, 4), JIT_OFF * scene_signed(id, 5),
                      JIT_FOCAL * scene_signed(id, 6), JIT_YAW * scene_signed(id, 7));
        p.c += float4(JIT_SPITCH * scene_signed(id, 8), 0.0, JIT_PHI * scene_signed(id, 9),
                      SHOT_ROLLJ[i] * scene_signed(id, 10));
    }
    return p;
}

// +1 or -1 per component: the way from `before` to `after`, or the scene's own
// coin where they agree (a held shot, or a component the shots share).
float4 heading(float4 before, float4 after, int id, int n) {
    float4 d = after - before;
    float4 coin = float4(scene_signed(id, n), scene_signed(id, n + 1),
                         scene_signed(id, n + 2), scene_signed(id, n + 3));
    float4 dir = sign(d) + (1.0 - abs(sign(d))) * sign(coin + 1e-6);
    return dir;
}

// How fast a scene moves while it holds, per second: its speeds, pointed the way
// the camera travels through it (from the scene before to the scene after).
Pose drift(int2 sv, Pose before, Pose after) {
    int id = sv.x * VARIANTS + sv.y;
    float4 ka = 0.5 + 0.5 * float4(scene_rand(id, 11), scene_rand(id, 12), scene_rand(id, 13), 0.0);
    float4 kb = 0.5 + 0.5 * float4(scene_rand(id, 14), scene_rand(id, 15), scene_rand(id, 16),
                                   scene_rand(id, 17));
    float kc = 0.5 + 0.5 * scene_rand(id, 18);
    Pose d;
    d.a = float4(MOVE_LON, MOVE_LAT, MOVE_ALT, 0.0) * ka * heading(before.a, after.a, id, 20);
    d.b = float4(MOVE_PAN, MOVE_PAN * 0.6, MOVE_ZOOM, MOVE_YAW) * kb
        * heading(before.b, after.b, id, 24);
    d.c = float4(0.0, 0.0, 0.0, MOVE_ROLL * kc) * heading(before.c, after.c, id, 28);
    return d;
}

// The tangent at a knot between a segment of slope s0 over dt0 and one of slope
// s1 over dt1: Fritsch-Butland's weighted harmonic mean, zero where the two
// slopes disagree. It keeps the path monotone between knots (no overshoot, so no
// back-and-forth), lets a slow hold meet a fast move at little more than the
// hold's own speed, and where a component has to turn back it slows to a stop
// and turns rather than flicking round.
float4 knot_tangent(float4 s0, float dt0, float4 s1, float dt1) {
    float4 a = s0 + (step(0.0, s0) * 2.0 - 1.0) * 1e-9;
    float4 b = s1 + (step(0.0, s1) * 2.0 - 1.0) * 1e-9;
    float4 m = 3.0 * (dt0 + dt1) / ((2.0 * dt1 + dt0) / a + (dt1 + 2.0 * dt0) / b);
    return m * step(1e-18, s0 * s1);
}

Pose pose_tangent(Pose s0, float dt0, Pose s1, float dt1) {
    Pose m;
    m.a = knot_tangent(s0.a, dt0, s1.a, dt1);
    m.b = knot_tangent(s0.b, dt0, s1.b, dt1);
    m.c = knot_tangent(s0.c, dt0, s1.c, dt1);
    return m;
}

// Cubic Hermite from p0 (tangent m0) to p1 (tangent m1) over dt, at u.
Pose hermite(Pose p0, Pose m0, Pose p1, Pose m1, float dt, float u) {
    float s = clamp(u / dt, 0.0, 1.0), s2 = s * s, s3 = s2 * s;
    float h00 = 2.0 * s3 - 3.0 * s2 + 1.0, h10 = s3 - 2.0 * s2 + s;
    float h01 = 3.0 * s2 - 2.0 * s3, h11 = s3 - s2;
    Pose r;
    r.a = p0.a * h00 + m0.a * (h10 * dt) + p1.a * h01 + m1.a * (h11 * dt);
    r.b = p0.b * h00 + m0.b * (h10 * dt) + p1.b * h01 + m1.b * (h11 * dt);
    r.c = p0.c * h00 + m0.c * (h10 * dt) + p1.c * h01 + m1.c * (h11 * dt);
    return r;
}

Pose pose_scale(Pose p, float k) {
    Pose r;
    r.a = p.a * k;
    r.b = p.b * k;
    r.c = p.c * k;
    return r;
}

Pose pose_slope(Pose from, Pose to, float dt) {
    return pose_scale(pose_add(to, from, -1.0), 1.0 / dt);
}

// The camera's path for one seed. Each slot k holds its scene for HOLD seconds
// and then moves to the next over TRANSITION. A scene contributes two knots: it
// enters at its composition minus half its drift over the hold and leaves at
// the composition plus half. The path runs through every knot as one smooth
// curve -- a monotone cubic, so the speed changes gradually everywhere and the
// direction never flicks: the hold drifts steadily, the move out of it starts
// from that drift and ends in the next scene's, which (headed the same way where
// it can be) carries straight on.
Pose path_at(float t, float seed) {
    float hold = SHOT_SECONDS - TRANSITION;
    int k = int(floor(t / SHOT_SECONDS));
    float u = t - float(k) * SHOT_SECONDS;
    int2 s_2 = scene_of(k - 2, seed), s_1 = scene_of(k - 1, seed), s0 = scene_of(k, seed);
    int2 s1 = scene_of(k + 1, seed), s2 = scene_of(k + 2, seed);
    Pose c0 = composition(s0);
    Pose c_1 = unwrap_to(composition(s_1), c0);
    Pose c_2 = unwrap_to(composition(s_2), c_1);
    Pose c1 = unwrap_to(composition(s1), c0);
    Pose c2 = unwrap_to(composition(s2), c1);
    Pose d_1 = drift(s_1, c_2, c0), d0 = drift(s0, c_1, c1), d1 = drift(s1, c0, c2);
    Pose x_1 = pose_add(c_1, d_1, 0.5 * hold);           // the scene before leaves here
    Pose e0 = pose_add(c0, d0, -0.5 * hold);             // this one enters
    Pose x0 = pose_add(c0, d0, 0.5 * hold);              // and leaves
    Pose e1 = pose_add(c1, d1, -0.5 * hold);             // the next one enters
    Pose s_in = pose_slope(x_1, e0, TRANSITION);
    Pose s_out = pose_slope(x0, e1, TRANSITION);
    Pose m_x0 = pose_tangent(d0, hold, s_out, TRANSITION);
    if (u < hold) {
        return hermite(e0, pose_tangent(s_in, TRANSITION, d0, hold), x0, m_x0, hold, u);
    }
    return hermite(x0, m_x0, e1, pose_tangent(s_out, TRANSITION, d1, hold), TRANSITION,
                   u - hold);
}

// The whole camera and sun, from time and the seeds alone. Each SHOT_SECONDS slot
// hashes to a scene; the low part of the hash is the lens look the lens passes
// pick for the same slot (they take it modulo LENS_COUNT), and the rest picks
// the shot and its variant -- so every combination can come up. A new seed
// (each launch, each return from idle) means new scenes; while seed_mix is
// below 1 the path for the old seed blends into the new one, as the lens blends
// the looks.
Cam camera(float t, float aspect, float seed, float seed_prev, float seed_mix) {
    float fov = aspect < 0.8 ? 0.75 : 1.0;      // portrait: widen the lens
    float spin = SPIN * t;
    Pose P = path_at(t, seed);
    if (seed_mix < 1.0) P = pose_lerp(unwrap_to(path_at(t, seed_prev), P), P, seed_mix);
    float dist = 1.0 + exp(P.a.z);
    // A gentle hand-held breathing on the tilt and the sun.
    float pitch = P.a.w + sin(t * 0.053) * 0.008;
    float yaw = P.b.w + sin(t * 0.07) * 0.01;
    float spitch = P.c.x;
    float limb = clamp(P.c.y, 0.0, 1.0);
    float phi = P.c.z;
    float roll = P.c.w;
    // The camera follows its spot round as the earth turns, so a shot holds its
    // framing; the spin shows in the stars and the drifting cloud instead.
    float3 d = normalize(rot_x(TILT, rot_y(-spin, earth_fixed(P.a.x, clamp(P.a.y, -80.0, 80.0)))));

    Cam c;
    c.focal = exp(P.b.z) * fov;
    c.off = P.b.xy;
    if (limb > 0.0) {
        // Frame so the point of the limb the sun meets sits at LIMB_AT on screen.
        float r = tan(asin(1.0 / dist)) * c.focal;
        c.off += limb * float2(cos(phi) * r - LIMB_AT_X, sin(phi) * r - LIMB_AT_Y);
    }
    c.ro = d * dist * RE;
    float3 upT = float3(0.0, 1.0, 0.0) - d * d.y;
    upT = dot(upT, upT) < 1e-8 ? float3(0.0, 0.0, 1.0) : normalize(upT);
    c.fw = normalize(-d * cos(pitch) + upT * sin(pitch));
    c.rt = normalize(cross(c.fw, upT));
    c.up = cross(c.rt, c.fw);
    // The roll turns the finished picture on the screen (see the fragment), so the
    // sun keeps its place against the planet and the limb framing still holds.
    c.roll = roll;
    float3 L = normalize(c.fw * (cos(spitch) * cos(yaw)) + c.rt * (cos(spitch) * sin(yaw))
                         + c.up * sin(spitch));
    if (limb > 0.001) {
        // The sun sliding behind the limb and back out: its centre swings
        // +-LIMB_AMP about the edge, once per LIMB_PERIOD.
        float aE = asin(1.0 / dist);
        float th = aE + LIMB_AMP * sin(2.0 * PI * t / LIMB_PERIOD);
        float3 side = c.rt * cos(phi) + c.up * sin(phi);
        float3 L2 = normalize(c.fw * cos(th) + side * sin(th));
        L = normalize(lerp(L, L2, limb));
    }
    c.L = L;
    return c;
}

float2 ray_sphere(float3 ro, float3 rd, float r) {
    float b = dot(ro, rd), c = dot(ro, ro) - r * r, h = b * b - c;
    if (h < 0.0) return float2(1e9, -1e9);
    h = sqrt(h);
    return float2(-b - h, -b + h);
}

// Optical depth of one exponential layer (scale height H) from altitude h along a
// ray at cos(zenith) mu, out to infinity: Schueler's approximation of the Chapman
// function (GPU Pro 3). Closed form, so the sun's light reaches each view sample
// without a march of its own -- that inner march was most of the scene's cost.
float chapman(float h, float mu, float H) {
    float X = RE / H, hn = max(h, 0.0) / H;
    float c = sqrt(X + hn);
    if (mu >= 0.0) return H * c / (c * mu + 1.0) * exp(-hn);
    float x0 = sqrt(max(1.0 - mu * mu, 0.0)) * (X + hn);
    float c0 = sqrt(x0);
    return H * (2.0 * c0 * exp(X - x0) - c / (1.0 - c * mu) * exp(-hn));
}

// Optical depth (Rayleigh, Mie) from p toward the sun; x < 0 when the ground
// is in the way.
float2 light_depth(float3 p, float3 L) {
    float r = length(p);
    float mu = dot(p, L) / r;
    // Below the horizon the ray meets the ground: no direct sun at all.
    if (mu < -sqrt(max(1.0 - (RE / r) * (RE / r), 0.0))) return float2(-1.0, -1.0);
    float h = r - RE;
    return float2(chapman(h, mu, HR), chapman(h, mu, HM));
}

float3 sun_att(float3 p, float3 L) {
    float2 d = light_depth(p, L);
    return d.x < 0.0 ? float3(0.0, 0.0, 0.0) : exp(-(BR * d.x + BM * 1.1 * d.y));
}

// Single scattering along the view ray between t0 and t1.
float3 scatter(float3 ro, float3 rd, float t0, float t1, float3 L,
                             out float3 trans) {
    float st = (t1 - t0) / float(VIEW_STEPS);
    float3 sR = float3(0.0, 0.0, 0.0), sM = float3(0.0, 0.0, 0.0);
    float oR = 0.0, oM = 0.0;
    for (int i = 0; i < VIEW_STEPS; i++) {
        float3 p = ro + rd * (t0 + (float(i) + 0.5) * st);
        float h = length(p) - RE;
        float dR = exp(-h / HR) * st, dM = exp(-h / HM) * st;
        oR += dR;
        oM += dM;
        float2 l = light_depth(p, L);
        if (l.x < 0.0) continue;
        float3 att = exp(-(BR * (oR + l.x) + BM * 1.1 * (oM + l.y)));
        sR += att * dR;
        sM += att * dM;
    }
    trans = exp(-(BR * oR + BM * 1.1 * oM));
    float mu = dot(rd, L);
    float pR = 3.0 / (16.0 * PI) * (1.0 + mu * mu);
    float g2 = MIE_G * MIE_G;
    float pM = 3.0 / (8.0 * PI) * ((1.0 - g2) * (1.0 + mu * mu))
             / ((2.0 + g2) * pow(1.0 + g2 - 2.0 * MIE_G * mu, 1.5));
    float ga2 = AUREOLE_G * AUREOLE_G;
    float pA = (1.0 - ga2) / (4.0 * PI * pow(1.0 + ga2 - 2.0 * AUREOLE_G * mu, 1.5));
    return SUN_I * 0.55 * (sR * BR * pR + sM * BM * (pM + 0.02 * pA));
}

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

float vnoise(float3 x) {
    float3 i = floor(x), f = frac(x);
    f = f * f * (3.0 - 2.0 * f);
    return lerp(lerp(lerp(hash13(i), hash13(i + float3(1, 0, 0)), f.x),
                   lerp(hash13(i + float3(0, 1, 0)), hash13(i + float3(1, 1, 0)), f.x), f.y),
               lerp(lerp(hash13(i + float3(0, 0, 1)), hash13(i + float3(1, 0, 1)), f.x),
                   lerp(hash13(i + float3(0, 1, 1)), hash13(i + float3(1, 1, 1)), f.x), f.y),
               f.z);
}

float fbm(float3 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 5; i++) {
        s += a * vnoise(p);
        p = p * 2.07 + 11.3;
        a *= 0.5;
    }
    return s;
}

float3 star_layer(float3 rd, float R, float pxAng, float density, float seed,
                                float t) {
    float3 c = floor(rd * R);
    float3 h = hash33(c + seed);
    if (h.x > density) return float3(0.0, 0.0, 0.0);
    float3 s = normalize(c + 0.25 + 0.5 * hash33(c + seed + 7.1));
    float ang = length(cross(rd, s));
    float mag = pow(hash13(c + seed + 3.3), 6.0);
    float r = pxAng * 0.65;
    float core = exp(-ang * ang / (r * r));
    float3 tint = lerp(float3(1.0, 0.78, 0.58), float3(0.66, 0.78, 1.0), h.y);
    float tw = 0.85 + 0.15 * sin(t * (1.0 + 3.0 * h.z) + h.y * 40.0);
    return tint * core * (0.03 + 1.6 * mag) * tw;
}

float3 stars(float3 rd, float pxAng, float t) {
    float3 col = star_layer(rd, 60.0, pxAng, 0.2, 0.0, t)
               + star_layer(rd, 130.0, pxAng, 0.3, 19.7, t) * 0.5;
    // A faint Milky Way: a band of dust with darker lanes through it. The two
    // fbm calls are the dearest thing in the sky, so they run only inside the
    // band -- outside it they would be multiplied by next to nothing.
    float3 gN = normalize(float3(0.3, 0.85, -0.42));
    float b = dot(rd, gN), band = exp(-b * b * 28.0);
    if (band > 0.02) {
        float dust = fbm(rd * 6.0), lanes = fbm(rd * 13.0 + 4.0);
        col += float3(0.55, 0.6, 0.75) * band * smoothstep(0.35, 0.8, dust) * 0.05
             * (1.0 - 0.7 * smoothstep(0.5, 0.75, lanes));
        col += star_layer(rd, 230.0, pxAng, 0.5 * band, 41.0, t) * 0.4;
    }
    return col;
}

// The mip level that matches a pixel's footprint on the sphere. Explicit rather
// than from screen derivatives: those jump at the map's date-line seam (u wraps
// from 1 to 0), which picks the smallest mip along a visible line.
float lod_for(float dist, float mu, float pxAng, float width) {
    float foot = dist * pxAng / sqrt(max(mu, 0.04));
    return max(log2(foot * width / (2.0 * PI * RE)), 0.0);
}

float cloud_cover(float3 ne, float lod, float t) {
    return clouds.SampleLevel(sClouds, earth_uv(ne) + float2(t * CLOUD_DRIFT, 0.0), lod).r;
}

float tex_width(Texture2D map) {
    uint w, h;
    map.GetDimensions(w, h);
    return float(w);
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float t = time;
    Cam cam = camera(t, resolution.x / resolution.y, seed, seed_prev, seed_mix);
    // y up, as the shot table was composed; then turned by the roll, about the
    // middle of the screen, before the framing offset places the composition.
    float2 uv0 = float2(pos.x - 0.5 * resolution.x, 0.5 * resolution.y - pos.y)
               / resolution.y;
    float cr = cos(cam.roll), sr = sin(cam.roll);
    float2 uv = float2(cr * uv0.x - sr * uv0.y, sr * uv0.x + cr * uv0.y) + cam.off;
    float3 ro = cam.ro, L = cam.L;
    float3 rd = normalize(cam.fw * cam.focal + uv.x * cam.rt + uv.y * cam.up);
    float pxAng = 1.0 / (resolution.y * cam.focal);
    float spin = SPIN * t;
    float3 Le = to_earth(L, spin);
    float dayW = tex_width(day);
    float cloudW = tex_width(clouds);
    float reliefW = tex_width(relief);

    float2 tE = ray_sphere(ro, rd, RE), tA = ray_sphere(ro, rd, RA);
    bool hitE = tE.x > 0.0 && tE.x < 1e8;
    float3 trans = float3(1.0, 1.0, 1.0), ins = float3(0.0, 0.0, 0.0);
    if (tA.x < 1e8) ins = scatter(ro, rd, max(tA.x, 0.0), hitE ? tE.x : tA.y, L, trans);

    // Clouds: three stacked shells, thicker cover reaching the higher ones. Each
    // is intersected on its own, so it shifts against the ground as the camera
    // moves -- that is the parallax.
    float3 cC = float3(0.0, 0.0, 0.0);
    float cA = 0.0;
    float hTop = 4.0 + 10.0 * CLOUD_H;
    for (int i = 2; i >= 0; i--) {
        float fi = float(i);
        float rc = RE + hTop * (0.55 + 0.225 * fi);
        float tc = ray_sphere(ro, rd, rc).x;
        if (tc <= 0.0 || tc > 1e8 || (hitE && tc > tE.x)) continue;
        float3 pc = ro + rd * tc, nc = normalize(pc), ne = to_earth(nc, spin);
        float lod = lod_for(tc, abs(dot(nc, rd)), pxAng, cloudW);
        float c = cloud_cover(ne, lod, t);
        float th = 0.08 + 0.2 * fi;
        float d = smoothstep(th, th + 0.35, c);
        if (d <= 0.001) continue;
        // Self-shadow: how much cover sits toward the sun from here.
        float occ = cloud_cover(normalize(ne + Le * (0.003 + 0.002 * fi)),
                                lod, t);
        float ndl = dot(nc, L);
        float3 sunlit = SUN_I * 0.085 * sun_att(pc * 1.0002, L) * smoothstep(-0.15, 0.55, ndl);
        float3 col = sunlit * (0.62 + 0.19 * fi)
                   * (1.0 - 0.45 * smoothstep(0.3, 0.9, occ) * (1.0 - fi * 0.4));
        col += float3(0.4, 0.55, 0.8) * 0.012;   // faint skylight keeps the shadowed side's form
        float a = d * 0.9;
        cC += (1.0 - cA) * a * col;
        cA += (1.0 - cA) * a;
    }

    float3 base;
    if (hitE) {
        float3 p = ro + rd * tE.x, n = normalize(p);
        float3 ne = to_earth(n, spin);
        float2 tuv = earth_uv(ne);
        float mu = max(dot(n, -rd), 0.0);
        float3 alb = day.SampleLevel(sDay, tuv, lod_for(tE.x, mu, pxAng, dayW)).rgb;
        float4 rel = relief.SampleLevel(sRelief, tuv, lod_for(tE.x, mu, pxAng, reliefW));
        float ocean = rel.b;
        float3 E0 = cross(float3(0.0, 1.0, 0.0), ne);
        float3 E = dot(E0, E0) > 1e-8 ? normalize(E0) : float3(1.0, 0.0, 0.0);
        float3 Nn = cross(ne, E);
        float2 nm = rel.rg * 2.0 - 1.0;
        float3 ns = normalize(ne + RELIEF * (nm.x * E + nm.y * Nn));

        // Cloud shadow, cast along the true sun direction onto the ground.
        float tS = ray_sphere(p, L, RE + hTop * 0.775).y;
        float cs = smoothstep(0.1, 0.6, cloud_cover(to_earth(normalize(p + L * tS), spin),
                              lod_for(tE.x, mu, pxAng, cloudW), t));

        float ndl = dot(ne, Le);
        float3 sun = SUN_I * 0.15 * sun_att(p * 1.0004, L);
        float3 surf = alb * sun * max(dot(ns, Le), 0.0) * (1.0 - 0.6 * cs);
        float3 ve = to_earth(-rd, spin), hv = normalize(Le + ve);
        float fres = 0.02 + 0.98 * pow(1.0 - max(dot(ne, ve), 0.0), 5.0);
        float nh = max(dot(ne, hv), 0.0);
        float spec = pow(nh, 260.0) * 2.2 + pow(nh, 24.0) * 0.05;
        surf += sun * ocean * (spec + fres * 0.08) * (1.0 - cs) * step(0.0, ndl);
        // The night side: no city lights, only the faintest moonlit trace of land.
        surf += alb * float3(0.5, 0.62, 0.85) * 0.006 * (1.0 - smoothstep(-0.2, 0.05, ndl));
        base = surf;
    } else {
        float disk = smoothstep(cos(SUN_R * 1.12), cos(SUN_R * 0.88), dot(rd, L));
        base = stars(rd, pxAng, t) * 0.9 + float3(1.0, 0.96, 0.9) * disk * 60.0;
    }
    float3 col = (base * (1.0 - cA) + cC) * trans + ins;

    // Airglow: a thin green line ~95 km up, seen along the night-side limb.
    float tm = -dot(ro, rd);
    if (tm > 0.0 && (!hitE || tm < tE.x + 400.0)) {
        float3 pm = ro + rd * tm;
        float hm = length(pm) - RE;
        float night = 1.0 - smoothstep(-0.25, 0.1, dot(normalize(pm), L));
        float g = (hm - 95.0) / 4.5;
        col += float3(0.32, 1.0, 0.5) * exp(-g * g) * night * 0.035;
    }

    // --- the sun against the limb ---
    float3 eC = -normalize(ro);
    float aE = asin(RE / length(ro));                  // the earth's angular radius
    float thS = acos(clamp(dot(L, eC), -1.0, 1.0));
    float dS = thS - aE;                               // sun centre above (+) / below (-) the limb
    // The visible share of the disk: a circular segment cut by a straight limb.
    float hh = clamp((dS + SUN_R) / (2.0 * SUN_R), 0.0, 1.0), xx = 1.0 - 2.0 * hh;
    float vis = (acos(xx) - xx * sqrt(max(1.0 - xx * xx, 0.0))) / PI;
    // What still shows comes in grazing, through the most air, so it reddens.
    float3 perp = L - eC * dot(L, eC);
    perp = dot(perp, perp) > 1e-10 ? normalize(perp) : float3(0.0, 1.0, 0.0);
    float aV = max(thS, aE + 0.0009);
    float3 sunTv = sun_att(ro, eC * cos(aV) + perp * sin(aV));

    // Glare: brightness follows the visible share, and its radius shrinks with it.
    float muS = max(dot(rd, L), 0.0);
    float kC = 2200.0 / max(vis, 0.02), kW = 60.0 / max(sqrt(vis), 0.12);
    col += sunTv * vis * (float3(1.0, 0.9, 0.78) * pow(muS, kC) * 3.0
                        + float3(0.9, 0.85, 0.8) * pow(muS, kW) * 0.05);

    // Limb flare: as the sun touches the edge the air beside it lights up and
    // swells, fusing with the disk -- strongest along the limb, falling off away
    // from the sun.
    float q = dS / (5.0 * SUN_R);
    float prox = exp(-q * q);
    float angE = acos(clamp(dot(rd, eC), -1.0, 1.0));
    float dl = angE - aE;                              // pixel above (+) / inside (-) the limb
    float angS = acos(clamp(dot(rd, L), -1.0, 1.0));
    float band = exp(-abs(dl - 0.0012) / lerp(0.0015, 0.004, prox));
    float swell = exp(-angS / (0.035 + 0.06 * prox)) * band * 2.4
                + exp(-angS / (SUN_R * (2.0 + 4.0 * prox))) * 0.6;
    float3 flareCol = lerp(float3(1.0, 0.55, 0.25), float3(1.0, 0.92, 0.8), vis);
    col += sunTv * flareCol * swell * prox * (0.25 + 0.75 * vis) * 1.6;

    // Linear HDR out: the lens tone-maps, grades and mixes over the backdrop.
    return float4(max(col * EXPOSURE, 0.0), 1.0);
}
"""

#: Fraction of native resolution the scene renders at. The atmosphere march is
#: the cost, and the scene is soft everywhere but the limb and the stars, which
#: 0.75 keeps crisp enough; see doc/dev/EARTH_THEME_IMPLEMENTATION.md for the
#: measurements behind it.
RESOLUTION_SCALE = 0.5

#: The option keys a theme's ``animation`` dict may carry for this scene.
OPTIONS = ("shot", "lens", "clouds", "exposure", "brightness")


def _one_lens(value) -> "Look | None":
    """One look: a preset name, a params dict (``preset`` names the base, the rest
    override it) or a ``Look``; ``None`` for anything else."""
    if isinstance(value, Look):
        return value
    if isinstance(value, str):
        return LENSES.get(value.strip().lower())
    if isinstance(value, dict):
        params = dict(value)
        base = LENSES.get(str(params.pop("preset", "clean")).lower(), LENSES["clean"])
        try:
            return replace(base, **params)
        except TypeError:
            return base
    return None


def _resolve_lens(value) -> "tuple[Look, ...]":
    """A lens option as the looks the scene is filmed through: ``"auto"`` (or
    ``None``) cycles through every look, one per scene; a list cycles through
    those; a single look (see :func:`_one_lens`) holds it. Unknown names are
    dropped, and nothing usable left means the default — the scene cannot be
    shown without *some* lens."""
    if value is None or (isinstance(value, str) and value.strip().lower() == "auto"):
        looks = tuple(LENSES.values())
    elif isinstance(value, (list, tuple)):
        looks = tuple(l for l in map(_one_lens, value) if l is not None)
    else:
        one = _one_lens(value)
        looks = (one,) if one is not None else ()
    return looks or _resolve_lens(DEFAULT_LENS)


def _clamped(value, default: float, lo: float, hi: float) -> float:
    try:
        v = float(default if value is None else value)
    except (TypeError, ValueError):
        v = default
    return min(hi, max(lo, v))


def earth_looks(lens=None, brightness=None) -> "tuple[Look, ...]":
    """The looks a theme's ``lens`` and ``brightness`` options film the scene
    through (see :func:`_resolve_lens`), each under the brightness ceiling."""
    level = _clamped(brightness, DEFAULT_BRIGHTNESS, 0.0, 1.0)
    return tuple(replace(l, level=level) for l in _resolve_lens(lens))


def earth_shader(shot=None, lens=None, clouds=None, exposure=None,
                 brightness=None) -> dict:
    """The ``Shader`` fields for the Earth scene with a theme's options applied.

    ``shot``: a name from :data:`SHOTS` to hold one shot (as composed, still
    slowly moving), or ``None``/``"auto"`` to pick a shot and variant at random for
    every scene. ``lens``: see :func:`_resolve_lens`. ``clouds``: cloud-height
    exaggeration, 0..8 (1 is real height; 3, the default, lets the parallax read
    from orbit). ``exposure``: 0.1..4, scales the light before the lens.
    ``brightness``: 0..1, the ceiling of the result after it (default 0.5). Bad
    values fall back to the defaults."""
    name = shot.strip().lower() if isinstance(shot, str) else None
    index = SHOTS.index(name) if name in SHOTS else -1
    looks = earth_looks(lens, brightness)
    options = dict(shot=index,
                   clouds=repr(_clamped(clouds, DEFAULT_CLOUDS, 0.0, 8.0)),
                   exposure=repr(_clamped(exposure, DEFAULT_EXPOSURE, 0.1, 4.0)),
                   lens_count=len(looks),
                   period=repr(SHOT_SECONDS), transition=repr(TRANSITION))
    return {
        **lens_shader(_MSL_OPTIONS.format(**options) + EARTH_MSL_BODY,
                      _HLSL_OPTIONS.format(**options) + EARTH_HLSL_BODY,
                      looks, period=SHOT_SECONDS, transition=TRANSITION,
                      scene_inputs=tuple(t.name for t in TEXTURES)),
        "textures": TEXTURES,
        "resolution_scale": RESOLUTION_SCALE,
        "idle": "freeze",
    }
