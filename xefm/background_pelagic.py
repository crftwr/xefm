"""The Pelagic background scene: open water about ten metres down, looking up.

Moon jellyfish swim slow closed paths through the frame, pulsing as they go;
overhead the surface ripples, with Snell's window and the sun glinting through
it; sun shafts slant down through the water and sway with the swell; marine
snow drifts past; a hazy reef lies far below; and once every few minutes a sea
turtle passes, low and far off. The camera never reacts to any of it.

It is a port of an approved WebGL2 prototype, and the look and motion are kept
as tuned. The parts most easily "simplified" by accident:

- each jellyfish's bell faces where it is going, and its tentacles and oral
  arms trail along the path it has just swum, so they stream through turns;
- on each beat the bell narrows, grows taller and draws its margin in, the
  thrust landing just after the squeeze;
- the light pattern at a point is looked up where its sun ray entered the
  surface, tilted by the swell's slope there (exaggerated by ``BEND``) and
  focused by its curvature, so the shafts lean and sway as waves pass; the
  same pattern lights the floor, the turtle and the jellyfish;
- the surface shows the sky and the sun refracted through each facet, with no
  caustic net on it, and total internal reflection is the same limit as
  Fresnel going to one, so the window's edge has no seam;
- the turtle passes once every :data:`TURTLE_PERIOD` seconds, which is the
  camera's tilt period, centred on the moment the camera looks most level.

**Stateless.** Everything is a closed form of ``time``: the beat surge is
``floor`` plus a ``smoothstep`` of the beat phase, not an integral, and the
turtle's passes are slots of ``floor``. The scene opens at :data:`START`, the
moment the prototype opened on.

**Physically coloured.** The water's colour is its extinction (red dies
first), so the scene ignores ``ink``; the theme's palette is chosen to sit on
it. The water drifts slowly between blue-green and a clearer blue, and the
floor between white sand and black coral, on two slow cycles of scene time.

**Idle.** A frozen jellyfish reads as a hang, so the scene declares ``idle:
"fade"`` and answers the fade itself: the jellyfish and the surface fade with
the ``opacity`` uniform while the scene keeps moving, and it parks on the still
water, shafts and floor (``XEFM_LENS_OPACITY`` keeps the lens from dissolving
the rest).

**One body, two dialects.** The scene is written once, in the common subset of
MSL and HLSL, and :func:`_dialect` spells it for each: ``CONST`` (``constant`` /
``static const``), ``F2``/``F3`` scalar splats, ``LOOP``/``UNROLL`` (fxc's
``[loop]``/``[unroll]``; nothing in MSL), ``INL`` (``static inline`` in MSL),
and ``fract``/``mix`` → ``frac``/``lerp``. The two cannot drift apart, and the
dialect-parity test still reads both.

Design and measurements: ``doc/dev/PELAGIC_DESIGN.md``; implementation notes:
``doc/dev/PELAGIC_IMPLEMENTATION.md``.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace

from .background_lens import AVAILABLE, Look, lens_shader

#: Options a theme's ``animation`` dict may carry for this scene.
OPTIONS = ("jellyfish", "exposure", "brightness")

DEFAULT_JELLYFISH = 6
DEFAULT_EXPOSURE = 1.0
#: The picture's ceiling. Lower than 1 so text stays legible, but not the other
#: picture themes' 0.5: the ceiling multiplies the whole picture, and this one
#: is mid-bright everywhere, not black space with a hot sun.
DEFAULT_BRIGHTNESS = 0.7

#: The scene clock at the backend's ``time`` 0: the prototype opened here.
START = 40.0

#: Under half resolution, 0.9 render pixels per point on any display (as
#: Crystal's scale): the scene is soft and hazy, and 1440 x 900 points render
#: 810 lines, more than the 720 of the reference frames the look was judged on.
RESOLUTION_SCALE = 0.45
PIXEL_DENSITY = 2 * RESOLUTION_SCALE

#: The camera and the jellyfish move slowly; 30 frames a second look the same
#: as 60 and halve the cost (PuiKit's ``Shader.frame_rate``).
FRAME_RATE = 30.0

#: The turtle: one pass of :data:`TURTLE_DURATION` seconds every
#: :data:`TURTLE_PERIOD` (the camera's tilt period, 2*pi/0.029), the first
#: starting at :data:`TURTLE_FIRST`.
TURTLE_PERIOD = 216.66
TURTLE_DURATION = 60.0
TURTLE_FIRST = 132.5

#: The long swell: (direction x, direction z, wavenumber, amplitude) per wave.
#: Directions are normalized here, once, instead of per call.
SWELL_WAVES = (
    (0.8, 0.6, 0.35, 0.10),
    (-0.45, 0.9, 0.52, 0.07),
    (0.95, -0.3, 0.80, 0.045),
    (-0.6, -0.8, 1.15, 0.030),
)

#: The sun in air, about 30 degrees above the horizon.
SUN_AIR = (0.62, 0.50, 0.60)
WATER_IOR = 1.333


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _refract(i, n, eta):
    """GLSL ``refract``: zero vector on total internal reflection."""
    d = sum(a * b for a, b in zip(n, i))
    k = 1.0 - eta * eta * (1.0 - d * d)
    if k < 0.0:
        return (0.0, 0.0, 0.0)
    return tuple(eta * a - (eta * d + math.sqrt(k)) * b for a, b in zip(i, n))


def swell_table():
    """:data:`SWELL_WAVES` with unit directions — the rows both dialects carry."""
    rows = []
    for dx, dz, k, a in SWELL_WAVES:
        n = math.hypot(dx, dz)
        rows.append((dx / n, dz / n, k, a))
    return tuple(rows)


def swell_omegas():
    """Each swell wave's angular frequency, deep-water dispersion slowed by half
    (as tuned): 0.5 * sqrt(9.8 k)."""
    return tuple(0.5 * math.sqrt(9.8 * k) for _, _, k, _ in SWELL_WAVES)


def sun_vectors():
    """The sun direction in air and, refracted, under water (toward the sun)."""
    air = _normalize(SUN_AIR)
    water = tuple(-c for c in _refract(tuple(-c for c in air), (0.0, 1.0, 0.0),
                                       1.0 / WATER_IOR))
    return air, water


def turtle_on(t: float) -> bool:
    """Whether the turtle is passing at scene time ``t`` (``time + START``)."""
    k = math.floor((t - TURTLE_FIRST) / TURTLE_PERIOD)
    u = (t - TURTLE_FIRST - k * TURTLE_PERIOD) / TURTLE_DURATION
    return 0.0 <= u <= 1.0


def _f4(row) -> str:
    return "float4(" + ", ".join(repr(float(v)) for v in row) + ")"


def _f3(row) -> str:
    return "float3(" + ", ".join(repr(float(v)) for v in row) + ")"


_TABLES = """
CONST float4 SWELL[4] = {{ {swell} }};
CONST float SWELL_W[4] = {{ {swell_w} }};
CONST float3 SUN_AIR = {sun_air};
CONST float3 SUN_W = {sun_water};
"""

_OPTIONS = """
// --- per-theme options (baked by xefm.background_pelagic.pelagic_shader) ----
// The idle fade is answered inside the picture (the jellyfish and the surface
// fade out), so the lens keeps the picture whole over the backdrop.
#define XEFM_LENS_OPACITY(o) 1.0
CONST int   JELLYFISH = {jellyfish};
CONST float EXPOSURE = {exposure};
"""

#: The scene, in the subset common to MSL and HLSL (see the module docstring).
BODY = r"""
CONST float START = 40.0;
CONST float PI = 3.14159265;
// Water extinction per unit (about a metre): red dies first.
CONST float SIG_R = 0.30;
CONST float SIG_G = 0.072;
CONST float SIG_B = 0.058;
CONST float SURF = 0.0;
CONST float BEND = 3.5;          // exaggeration of the refraction tilt (artistic)
CONST float TURTLE_P = 216.66;   // = the camera's tilt period, 2 pi / 0.029
CONST float TURTLE_D = 60.0;
CONST float TURTLE_T0 = 132.5;
// The floor: a flat plane, drawn as a soft gradient of sand and coral rather
// than as terrain (below the camera's lowest point, -10.9, and the jellyfish's).
CONST float FLOOR_Y = -16.0;
// How brightly the floor is lit: by the sun through the water (FLOOR_EVEN
// everywhere, plus FLOOR_WAVE in slow waves where the shafts land), and by the
// diffuse light from above.
CONST float FLOOR_SUN = 0.9;
CONST float FLOOR_EVEN = 0.45;
CONST float FLOOR_WAVE = 0.9;
CONST float FLOOR_FILL = 1.5;
// The floor shows its colour out to FLOOR_NEAR and has melted into the water
// by FLOOR_FAR (metres along the ray).
CONST float FLOOR_NEAR = 15.0;
CONST float FLOOR_FAR = 45.0;
// The camera's look target height above the centre: its middle and its swing.
// It sets the tilt, slightly upward: the surface at the top of the frame, the
// floor along the bottom.
CONST float TILT_MID = 1.8;
CONST float TILT_AMP = 0.8;
// The lens: 1.4 is about 71 degrees of vertical field, wide enough for Snell's
// window at the top and the floor along the bottom at once.
CONST float FOCAL = 1.4;
CONST int   GOD_STEPS = 32;
CONST float GOD_RANGE = 44.0;     // metres the shafts are marched (1.375 m a step)
// A jellyfish closer than JELLY_HIDE bell radii is not drawn; it is whole again
// by JELLY_SHOW.
CONST float JELLY_HIDE = 3.5;
CONST float JELLY_SHOW = 6.0;
CONST int   BELL_STEPS = 30;
CONST int   TURTLE_STEPS = 64;
CONST int   SNOW_CELLS = 18;
// The water drifts slowly between two colours: blue-green (the approved look)
// and a clearer open-ocean blue, where green is absorbed faster than blue.
// Per colour: extinction per unit, in-scatter looking up / down, the tint of the
// sun shafts and the jellyfish's ambient glow.
CONST float3 SIG_TEAL = float3(0.24, 0.045, 0.038);
CONST float3 HI_TEAL = float3(0.010, 0.105, 0.120);
CONST float3 LO_TEAL = float3(0.0005, 0.008, 0.016);
CONST float3 RAY_TEAL = float3(0.45, 1.0, 0.92);
CONST float3 GLOW_TEAL = float3(0.06, 0.14, 0.15);
CONST float3 SIG_BLUE = float3(0.28, 0.055, 0.024);
CONST float3 HI_BLUE = float3(0.010, 0.078, 0.165);
CONST float3 LO_BLUE = float3(0.0004, 0.005, 0.019);
CONST float3 RAY_BLUE = float3(0.40, 0.82, 1.0);
CONST float3 GLOW_BLUE = float3(0.05, 0.10, 0.17);
// Rates of the slow cycles (rad/s at speed 1): the water's colour (about 8.5
// minutes a cycle) and how much of the floor is coral (about 11.5 minutes).
// The scene opens blue-green, half sand and half coral, as approved.
CONST float HUE_RATE = 0.0123;
CONST float CORAL_RATE = 0.0091;
// The floor's colour: white sand to black coral, a soft mask over broad noise
// whose edge moves with the coral cover, so dark patches grow out of the sand
// and spread until they cover it.
CONST float3 SAND = float3(0.70, 0.68, 0.60);
CONST float3 CORAL = float3(0.030, 0.034, 0.032);
CONST float CORAL_EDGE_SAND = 0.78;    // the mask's edge with no coral cover
CONST float CORAL_EDGE_REEF = 0.18;    // ... with full cover
CONST float CORAL_SOFT = 0.14;

struct Water { float3 sig; float3 hi; float3 lo; float3 ray; float3 glow; float coral; };
// The water and the floor's coral cover at scene time t.
INL Water water(float t) {
    float u = t - START;
    float w = 0.5 + 0.5 * cos(HUE_RATE * u);                      // 1 = blue-green, 0 = blue
    Water W;
    W.sig = mix(SIG_BLUE, SIG_TEAL, w);
    W.hi = mix(HI_BLUE, HI_TEAL, w);
    W.lo = mix(LO_BLUE, LO_TEAL, w);
    W.ray = mix(RAY_BLUE, RAY_TEAL, w);
    W.glow = mix(GLOW_BLUE, GLOW_TEAL, w);
    W.coral = 0.5 + 0.5 * sin(CORAL_RATE * u);                    // 0 = all sand, 1 = all coral
    return W;
}
CONST float3 CEN = float3(0.0, -9.0, 0.0);

INL float sq(float x) { return x * x; }
INL float h11(float p) { p = fract(p * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }
INL float h21(float2 p) {
    float3 q = fract(p.xyx * 0.1031); q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}
INL float2 h22(float2 p) {
    float3 q = fract(p.xyx * float3(0.1031, 0.1030, 0.0973)); q += dot(q, q.yzx + 33.33);
    return fract((q.xx + q.yz) * q.zy);
}
INL float3 h33(float3 p) {
    p = fract(p * float3(0.1031, 0.1030, 0.0973)); p += dot(p, p.yxz + 33.33);
    return fract((p.xxy + p.yxx) * p.zyx);
}
INL float vn(float2 p) {
    float2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(h21(i), h21(i + float2(1.0, 0.0)), f.x),
               mix(h21(i + float2(0.0, 1.0)), h21(i + float2(1.0, 1.0)), f.x), f.y);
}
INL float fbm(float2 p) {
    float s = 0.0, a = 0.5;
    UNROLL for (int i = 0; i < 4; i++) {
        s += a * vn(p);
        p = float2(1.6 * p.x - 1.2 * p.y, 1.2 * p.x + 1.6 * p.y);   // GLSL mat2(1.6,1.2,-1.2,1.6)*p
        a *= 0.5;
    }
    return s;
}
// GLSL rot(a)*v with rot = mat2(c,-s,s,c): column-major, so a turn by -a.
INL float2 rot2(float2 v, float a) {
    float c = cos(a), s = sin(a);
    return float2(c * v.x + s * v.y, -s * v.x + c * v.y);
}

// --- surface waves ------------------------------------------------------------
// Swell: (height, d/dx, d/dz, laplacian). Also bends the rays.
INL float4 swell(float2 x, float t) {
    float4 r = F4(0.0);
    UNROLL for (int i = 0; i < 4; i++) {
        float4 K = SWELL[i];
        float2 d = K.xy; float k = K.z, a = K.w, w = SWELL_W[i];
        float ph = k * dot(d, x) - w * t + float(i) * 1.7;
        float s = sin(ph), c = cos(ph);
        r.x += a * s;
        r.yzw += float3(a * k * c * d, -a * k * k * s);
    }
    return r;
}
// Chop: nine octaves of short waves (gradient only), each fading once its
// wavelength is small on screen.
INL float2 chop(float2 x, float t, float dist) {
    float2 g = F2(0.0); float k = 2.0, a = 0.024;
    LOOP for (int i = 0; i < 9; i++) {
        float an = float(i) * 2.399 + 0.4; float2 d = float2(cos(an), sin(an));
        float w = sqrt(9.8 * k) * 0.5, ph = k * dot(d, x) - w * t + float(i) * 4.1;
        g += a * k * cos(ph) * d * clamp(1.0 - k * dist * 0.0065, 0.0, 1.0);
        k *= 1.38; a *= 0.74;
    }
    return g;
}

// --- light coming down from the surface -------------------------------------
INL float shaftPat(float2 q, float t) {
    float n = vn(q * 0.22 + float2(0.03, 0.02) * t) * 0.62 + vn(q * 0.55 - float2(0.02, 0.05) * t) * 0.38;
    float s = smoothstep(0.50, 0.92, n);
    return s * s;
}
INL float caustic(float2 p, float t) {
    float c = 0.0;
    UNROLL for (int l = 0; l < 2; l++) {
        float fl = float(l);
        float2 q = p * (0.55 + 0.45 * fl) + fl * 7.31;
        q += 0.22 * float2(sin(q.y * 1.7 + t * 0.6), sin(q.x * 1.9 - t * 0.5));
        float2 ip = floor(q), fp = fract(q); float f1 = 8.0, f2 = 8.0;
        UNROLL for (int j = -1; j <= 1; j++) {
            UNROLL for (int i = -1; i <= 1; i++) {
                float2 g = float2(float(i), float(j)), h = h22(ip + g);
                float2 o = 0.5 + 0.42 * sin(t * (0.55 + 0.25 * fl) + 6.2831 * h);
                float d = length(g + o - fp);
                if (d < f1) { f2 = f1; f1 = d; } else if (d < f2) { f2 = d; }
            }
        }
        c += exp(-(f2 - f1) * (10.0 + 4.0 * fl));
    }
    return c * 0.5;
}
INL float2 surfacePoint(float3 p) { return p.xz + SUN_W.xz * ((SURF - p.y) / SUN_W.y); }
INL float3 sunCol(float3 p, Water W) {
    float d = max(SURF - p.y, 0.0) / SUN_W.y;
    return float3(1.0, 0.97, 0.9) * 5.0 * exp(-W.sig * d);
}
// Light pattern at p: the sun ray is bent by the swell where it entered, so the
// shafts lean and sway as waves pass, and crests focus light into them.
INL float lightPat(float3 p, float t) {
    float dep = max(SURF - p.y, 0.0);
    float2 q0 = surfacePoint(p);
    float4 sw = swell(q0, t);
    float2 qs = q0 - sw.yz * dep * BEND;
    float focus = clamp(1.0 - sw.w * dep * 3.5, 0.25, 2.8);
    return shaftPat(qs, t) * focus;
}

// --- sea floor ------------------------------------------------------------------

// --- camera: closed form in time (incommensurate rates, never repeats) -------
struct Cam { float3 ro; float3 ta; };
INL Cam camera(float t) {
    Cam c;
    float th = 0.6 + 0.021 * t;
    float R = 10.0 + 2.2 * sin(0.031 * t);
    c.ro = CEN + float3(R * cos(th), 0.9 * sin(0.047 * t) - 1.0, R * sin(th));
    c.ta = CEN + float3(3.0 * sin(0.037 * t + 1.0), TILT_MID + TILT_AMP * sin(0.029 * t), 3.0 * cos(0.041 * t));
    return c;
}

// --- sea turtle: one pass every TURTLE_P seconds, low over the floor ----------
struct Turtle { float3 c; float2 d; float2 nm; float on; float u; float flap; };
INL Turtle turtle(float t) {
    Turtle T;
    float k = floor((t - TURTLE_T0) / TURTLE_P);
    T.u = (t - TURTLE_T0 - k * TURTLE_P) / TURTLE_D;
    T.on = step(0.0, T.u) * step(T.u, 1.0);
    T.c = F3(0.0); T.d = float2(1.0, 0.0); T.nm = float2(0.0, 1.0); T.flap = 0.0;
    if (T.on < 0.5) return T;
    // Placed from where the camera will be looking halfway through the pass: a
    // crossing about 20 m out, low in the frame. The camera never reacts.
    Cam cm = camera(TURTLE_T0 + k * TURTLE_P + 0.5 * TURTLE_D);
    float2 fw = normalize(cm.ta.xz - cm.ro.xz);
    float side = h11(k * 7.13 + 1.7) < 0.5 ? -1.0 : 1.0;
    T.d = side * float2(-fw.y, fw.x); T.nm = float2(-T.d.y, T.d.x);
    float dist = 23.0 + 5.0 * h11(k * 3.91 + 0.3);
    float2 xz = cm.ro.xz + fw * dist + T.d * mix(-20.0, 20.0, clamp(T.u, 0.0, 1.0));
    float fy = FLOOR_Y;
    // about 16 degrees below the eye line, never closer than 2.5 m to the floor
    T.c = float3(xz.x, max(fy + 2.5, cm.ro.y - 0.29 * dist) + 0.25 * sin(t * 0.45), xz.y);
    T.flap = t * 1.25;
    return T;
}
INL float sdEll(float3 p, float3 r) { float k0 = length(p / r), k1 = length(p / (r * r)); return k0 * (k0 - 1.0) / k1; }
INL float smin(float a, float b, float k) { float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0); return mix(b, a, h) - k * h * (1.0 - h); }
INL float sdCap(float3 p, float3 a, float3 b, float r) {
    float3 pa = p - a, ba = b - a; float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - r;
}
// Local frame: x forward, y up, z to the side. (distance, material: 0 shell / 1 skin)
INL float2 turtleSDF(float3 q, float flap) {
    float S = 1.5; q /= S;
    float shell = sdEll(q - float3(-0.05, 0.06, 0.0), float3(0.92, 0.30, 0.74));
    shell = max(shell, -(q.y + 0.10));                                         // flat plastron
    float skin = sdCap(q, float3(0.62, -0.01, 0.0), float3(0.98, 0.02, 0.0), 0.13);  // neck
    skin = smin(skin, sdEll(q - float3(1.08, 0.03, 0.0), float3(0.24, 0.16, 0.17)), 0.06);  // head
    UNROLL for (int i = 0; i < 2; i++) {
        float s = i == 0 ? 1.0 : -1.0;
        // front flipper: long, swept back, flapping like a wing
        float3 f = q - float3(0.42, -0.03, 0.50 * s); f.z *= s;
        f.xz = rot2(f.xz, -0.55 - 0.25 * sin(flap + 0.9));
        f.yz = rot2(f.yz, 0.55 * sin(flap));
        f.xy = rot2(f.xy, 0.25 * cos(flap));
        float fl = sdEll(f - float3(-0.06, 0.0, 0.62), float3(0.22, 0.040, 0.70));
        // rear flipper: small paddle
        float3 r = q - float3(-0.78, -0.06, 0.32 * s); r.z *= s;
        r.xz = rot2(r.xz, 0.75);
        r.yz = rot2(r.yz, 0.20 * sin(flap * 1.0 + 1.5));
        float rf = sdEll(r - float3(-0.10, 0.0, 0.14), float3(0.20, 0.035, 0.17));
        skin = smin(skin, min(fl, rf), 0.07);
    }
    float d = smin(shell, skin, 0.05);
    return float2(d * S, step(skin, shell));
}
INL float2 turtleMap(float3 p, Turtle T) {
    float3 lp = p - T.c;
    float3 q = float3(dot(lp.xz, T.d), lp.y, dot(lp.xz, T.nm));
    return turtleSDF(q, T.flap);
}
INL float3 turtleShade(float3 p, float3 rd, Turtle T, float t, Water W) {
    float3 L = SUN_W;
    float2 e = float2(0.004, -0.004);
    float3 n = normalize(e.xyy * turtleMap(p + e.xyy, T).x + e.yyx * turtleMap(p + e.yyx, T).x
                       + e.yxy * turtleMap(p + e.yxy, T).x + e.xxx * turtleMap(p + e.xxx, T).x);
    float2 m = turtleMap(p, T);
    float3 lp = p - T.c; float3 q = float3(dot(lp.xz, T.d), lp.y, dot(lp.xz, T.nm)) / 1.5;
    float3 alb;
    if (m.y < 0.5) {
        // carapace: scutes (cellular) with darker seams
        float2 g = q.xz * float2(2.6, 3.0); float2 ip = floor(g), fp = fract(g); float f1 = 8.0, f2 = 8.0;
        UNROLL for (int j = -1; j <= 1; j++) {
            UNROLL for (int i = -1; i <= 1; i++) {
                float2 o = float2(float(i), float(j)) + 0.5 + 0.35 * (h22(ip + float2(float(i), float(j))) - 0.5);
                float d = length(o - fp);
                if (d < f1) { f2 = f1; f1 = d; } else if (d < f2) { f2 = d; }
            }
        }
        float seam = smoothstep(0.0, 0.08, f2 - f1);
        alb = mix(float3(0.10, 0.07, 0.035), float3(0.30, 0.20, 0.09) * (0.75 + 0.5 * vn(q.xz * 14.0)), seam);
        alb = mix(alb, float3(0.42, 0.36, 0.22), 1.0 - smoothstep(-0.10, 0.0, q.y));   // pale plastron
    } else {
        float sc = vn(q.xz * 22.0 + q.y * 9.0);
        alb = mix(float3(0.10, 0.09, 0.06), float3(0.36, 0.32, 0.22), smoothstep(0.35, 0.65, sc));
    }
    float2 s0 = surfacePoint(p);
    float2 sp = s0 - swell(s0, t).yz * (-p.y) * BEND;
    float ca = 0.82 + 0.36 * caustic(sp * 0.35, t * 0.6);   // faint, soft ripple only
    float3 li = sunCol(p, W) * max(dot(n, L), 0.0) * ca * (0.12 + 1.5 * lightPat(p, t));
    float3 c = alb * (li * 0.5 + W.hi * (0.55 + 0.45 * n.y) * 2.2);
    float sp2 = pow(max(dot(reflect(rd, n), L), 0.0), 24.0);
    c += sunCol(p, W) * sp2 * 0.02 * ca;
    return c;
}

// --- jellyfish ------------------------------------------------------------------
// Each swims a closed path; the bell faces the direction of travel and surges on
// every beat. Tentacles trail along the path it just swam.
struct Jelly {
    float3 c; float3 u; float3 xv; float3 zv; float3 h;
    float R; float pc; float tl; float al; float sp; float seed; float s; float dS;
};
INL float3 jPath(float3 h, float s, float fi) {
    float3 f = float3(0.055, 0.071, 0.047) * (0.8 + 0.4 * h.zxy);
    float3 ph = 6.2831 * h + float3(fi, 0.0, 2.0 * fi);
    return CEN + float3(7.0, 3.2, 7.0) * sin(f * s + ph) + float3(0.0, -0.5, 0.0);
}
INL float3 jVel(float3 h, float s, float fi) {
    float3 f = float3(0.055, 0.071, 0.047) * (0.8 + 0.4 * h.zxy);
    float3 ph = 6.2831 * h + float3(fi, 0.0, 2.0 * fi);
    return float3(7.0, 3.2, 7.0) * f * cos(f * s + ph);
}
INL Jelly jelly(int i, float t) {
    float fi = float(i);
    float3 h = h33(float3(fi * 3.7 + 1.0, fi * 1.3 + 2.0, fi * 5.1 + 3.0));
    Jelly j; j.h = h;
    j.R = 1.1 + 0.8 * h.y;
    float w = 0.60 + 0.35 * h.z;
    float ph = t * w + 6.2831 * h.x;
    float f = fract(ph / 6.2831);
    j.pc = f < 0.25 ? smoothstep(0.0, 0.25, f) : 1.0 - smoothstep(0.25, 1.0, f);  // fast squeeze, slow relax
    float beats = floor(ph / 6.2831) + smoothstep(0.08, 0.55, f);                // thrust just after the squeeze
    j.s = 0.30 * t + 2.4 * beats + 120.0 * h.x;
    j.c = jPath(h, j.s, fi);
    float3 v = jVel(h, j.s, fi);
    j.u = normalize(v + float3(0.0, 0.25, 0.0) * length(v));                       // slight bias to swim upward
    float3 rf = abs(j.u.y) < 0.9 ? float3(0.0, 1.0, 0.0) : float3(1.0, 0.0, 0.0);
    float3 xv = normalize(cross(rf, j.u)), zv = cross(j.u, xv);
    float sa = 0.05 * t + 6.2831 * h.z, cs = cos(sa), sn = sin(sa);
    j.xv = cs * xv + sn * zv; j.zv = -sn * xv + cs * zv;
    j.tl = mix(0.8, 3.4, step(0.62, h.z));   // two species: short fringe / long trailing
    j.al = 1.3 + 0.5 * h.x;                  // oral arms
    j.dS = j.R / max(length(v), 0.08);       // path parameter per R of distance swum
    j.sp = fi * 1.7;
    j.seed = h.x;
    return j;
}
// Centre of the bell's past position, "back" bell radii behind.
INL float3 trail(Jelly j, float back, float fi) { return jPath(j.h, j.s - back * j.dS, fi); }

// Ray against a sphere: (t0, t1), t1 < 0 for a miss.
INL float2 sph(float3 ro, float3 rd, float3 c, float r) {
    float3 oc = ro - c; float b = dot(oc, rd), q = dot(oc, oc) - r * r, d = b * b - q;
    if (d < 0.0) return float2(0.0, -1.0);
    d = sqrt(d);
    return float2(max(-b - d, 0.0), -b + d);
}
// Closest approach of a ray to a segment: (distance, t along the ray, s along the segment).
INL float3 raySeg(float3 ro, float3 rd, float3 a, float3 b) {
    float3 ba = b - a, w = ro - a;
    float e = dot(rd, ba), g = dot(ba, ba), p = dot(rd, w), q = dot(ba, w);
    float s = clamp((p * e - q) / min(e * e - g, -1e-5), 0.0, 1.0);
    float t = max(s * e - p, 0.0);
    return float3(length(w + rd * t - ba * s), t, s);
}

// Bell profile at contraction pc: (horizontal radius, height, margin y, margin radius).
INL float4 bellShape(float pc) {
    float a = 1.0 - 0.30 * pc, b = 0.44 + 0.26 * pc;
    float cut = -(0.04 + 0.34 * pc);             // the margin pulls down and in as it squeezes
    float rimR = a * sqrt(max(1.0 - (cut * cut) / (b * b), 0.0));
    return float4(a, b, cut, rimR);
}
INL float2 bellDens(float3 q, float4 S) {
    float a = S.x, b = S.y, cut = S.z, rimR = S.w;
    float e = length(float3(q.x / a, q.y / b, q.z / a));
    float e2 = length(float3(q.x / (a * 0.92), (q.y + 0.14) / (b * 0.80), q.z / (a * 0.92)));
    float up = smoothstep(cut - 0.05, cut + 0.03, q.y);
    float shell = exp(-sq((e - 1.0) / 0.075));
    float body = (1.0 - smoothstep(0.97, 1.02, e)) * smoothstep(0.96, 1.04, e2) * 0.35;
    float ang = atan2(q.z, q.x);
    float canal = pow(abs(cos(ang * 8.0)), 36.0) * body * 1.4;
    float rim = exp(-sq((q.y - cut) / 0.05)) * exp(-sq((length(q.xz) - rimR) / 0.06)) * 2.4;
    float g = 0.0;
    UNROLL for (int k = 0; k < 4; k++) {
        float ak = float(k) * 1.5708 + 0.785;
        float2 cc = 0.34 * a * float2(cos(ak), sin(ak));
        float d = abs(length(q.xz - cc) - 0.16 * a);
        g += exp(-sq(d / 0.04));
    }
    g *= exp(-sq((q.y - b * 0.42) / 0.10)) * step(e, 1.0) * 1.6;
    return float2((shell * 0.9 + body + canal) * up + rim, g);
}

INL float3 waterLight(float3 p, float t, Water W) { return sunCol(p, W) * (0.25 + 1.6 * lightPat(p, t)); }

INL float4 renderJelly(float3 ro, float3 rd, Jelly j, float fi, float tEnd, float t, float jit, Water W) {
    float3 L = SUN_W;
    float3 col = F3(0.0); float T = 1.0;
    float R = j.R;
    float4 S = bellShape(j.pc);
    // bell: a short volume march in the bell's own frame
    float2 bb = sph(ro, rd, j.c + j.u * 0.12 * R, 0.95 * R);
    if (bb.y > 0.0 && bb.x < tEnd) {
        float t0 = bb.x, t1 = min(bb.y, tEnd);
        float dt = (t1 - t0) / float(BELL_STEPS);
        float3 liB = waterLight(ro + rd * (0.5 * (t0 + t1)), t, W);   // one light lookup per pixel
        float fw = 0.6 + 1.4 * pow(max(dot(rd, L), 0.0), 3.0);
        LOOP for (int i = 0; i < BELL_STEPS; i++) {
            float tt = t0 + (float(i) + jit) * dt;
            float3 p = ro + rd * tt;
            float3 d = (p - j.c) / R, q = float3(dot(d, j.xv), dot(d, j.u), dot(d, j.zv));
            float2 dd = bellDens(q, S);
            float den = dd.x + dd.y * 1.6;
            if (den < 0.003) continue;
            float3 tint = mix(float3(0.92, 0.97, 1.0), float3(0.92, 0.70, 1.0), dd.y / (den + 1e-3));
            tint *= 0.92 + 0.16 * sin(float3(0.0, 2.1, 4.2) + q.y * 7.0 + length(q.xz) * 5.0);
            float3 em = tint * (liB * 0.16 * fw + W.glow * 1.2)
                      + float3(0.5, 0.9, 1.0) * liB * 0.05 * smoothstep(0.2, 0.5, q.y);
            float a = 1.0 - exp(-den * dt / R * 2.2);
            col += T * a * em * exp(-W.sig * tt);
            T *= 1.0 - a * 0.55;
        }
    }
    // tentacles + oral arms: polylines that follow the swum path
    float reach = max(j.tl, j.al);
    float3 rimC = j.u * S.z * R;                 // margin plane offset from the bell centre
    float3 tipC = trail(j, reach, fi) + rimC;
    float3 mid = 0.5 * (j.c + rimC + tipC);
    float2 sb = sph(ro, rd, mid, 0.5 * length(tipC - j.c - rimC) + 1.3 * R);
    if (sb.y > 0.0 && sb.x < tEnd) {
        bool longs = j.tl > 2.0;
        int NS = longs ? 8 : 4;                  // long strands get more joints so their ripple survives
        float3 tc[9]; tc[0] = j.c + rimC;
        LOOP for (int s = 1; s <= 8; s++) { if (s > NS) break; tc[s] = trail(j, j.tl * float(s) / float(NS), fi) + rimC; }
        float3 ac[7]; ac[0] = j.c + j.u * (S.z * 0.5) * R;
        LOOP for (int s = 1; s <= 6; s++) ac[s] = trail(j, j.al * float(s) / 6.0, fi) + j.u * (S.z * 0.5) * R;
        int NT = longs ? 10 : 22;
        float wS = (longs ? 0.020 : 0.011) * R;
        float freq = longs ? 7.5 : 5.5, amp = (longs ? 0.16 : 0.10) * j.tl, gain = longs ? 0.9 : 0.45;
        float glow = 0.0, tAcc = 0.0;
        // Joints outside, strands inside: every strand's segment s lies within
        // rmax of the axis segment tc[s-1]..tc[s], so a ray that passes that axis
        // further off cannot see any of them (the picture is unchanged).
        LOOP for (int s = 1; s <= 8; s++) {
            if (s > NS) break;
            float fs = float(s) / float(NS), fq = float(s - 1) / float(NS);
            float rmax = (S.w * 1.05 + 0.8 * amp * fs) * R;
            float3 ax = raySeg(ro, rd, tc[s - 1], tc[s]);
            if (ax.x > rmax + 4.0 * (wS + (ax.y + rmax) * 0.0010)) continue;
            float spread = S.w * (1.0 - 0.30 * fs + 0.35 * (1.0 - j.pc) * fs);   // open on the relax
            float spq = S.w * (1.0 - 0.30 * fq + 0.35 * (1.0 - j.pc) * fq);
            LOOP for (int k = 0; k < 22; k++) {
                if (k >= NT) break;
                float th = 6.2831 * (float(k) + 0.37 * j.seed) / float(NT);
                float3 rad = j.xv * cos(th) + j.zv * sin(th), tan_ = -j.xv * sin(th) + j.zv * cos(th);
                float3 prev;
                if (s == 1) {
                    prev = tc[0] + rad * S.w * R;
                } else {
                    float wq = sin(fq * freq - t * 1.7 + j.sp + th * 2.0) * amp * fq;   // travelling ripple
                    prev = tc[s - 1] + (rad * spq + tan_ * wq * 0.5 + rad * wq * 0.3) * R;
                }
                float wv = sin(fs * freq - t * 1.7 + j.sp + th * 2.0) * amp * fs;
                float3 cur = tc[s] + (rad * spread + tan_ * wv * 0.5 + rad * wv * 0.3) * R;
                float3 r = raySeg(ro, rd, prev, cur);
                float w = wS + r.y * 0.0010;
                float g = exp(-sq(r.x / w)) * (1.0 - 0.75 * fs) * step(r.y, tEnd) * gain;
                glow += g; tAcc += g * r.y;
            }
        }
        float arms = 0.0, aAcc = 0.0;
        LOOP for (int k = 0; k < 4; k++) {
            float th = float(k) * 1.5708 + 0.3;
            float3 rad = j.xv * cos(th) + j.zv * sin(th), tan_ = -j.xv * sin(th) + j.zv * cos(th);
            float3 prev = ac[0] + rad * 0.08 * R;
            LOOP for (int s = 1; s <= 6; s++) {
                float fs = float(s) / 6.0;
                float wv = sin(fs * 6.0 - t * 1.3 + j.sp + float(k) * 1.9) * 0.30 * fs;
                float3 cur = ac[s] + (rad * (0.10 + 0.14 * fs) + tan_ * wv) * R;
                float3 r = raySeg(ro, rd, prev, cur);
                float frill = 0.75 + 0.25 * sin(r.z * 18.0 + t * 1.2 + float(k));
                float w = (0.048 * frill * (1.0 - 0.6 * fs)) * R + r.y * 0.001;
                float g = exp(-sq(r.x / w)) * step(r.y, tEnd);
                arms += g; aAcc += g * r.y;
                prev = cur;
            }
        }
        if (glow > 0.001) {
            float tt = tAcc / glow; float3 p = ro + rd * tt;
            float3 li = waterLight(p, t, W);
            col += T * min(glow, 1.5) * float3(0.62, 0.86, 0.96) * (li * 0.035 + W.hi * 0.7) * exp(-W.sig * tt);
        }
        if (arms > 0.001) {
            float tt = aAcc / arms; float3 p = ro + rd * tt;
            float3 li = waterLight(p, t, W);
            float a = min(arms, 1.0) * 0.38;
            col += T * a * float3(0.80, 0.78, 0.98) * (li * 0.06 + W.hi * 1.1) * exp(-W.sig * tt);
            T *= 1.0 - a * 0.4;
        }
    }
    return float4(col, T);
}

// --- marine snow: 3D DDA through a sparse grid of points -----------------------
INL float3 snow(float3 ro, float3 rd, float tEnd, float t, Water W) {
    float CS = 1.6;
    float3 p = ro / CS, ip = floor(p), st = sign(rd), dd = 1.0 / max(abs(rd), F3(1e-6));
    float3 sd = (st * (ip - p) + st * 0.5 + 0.5) * dd;
    float3 acc = F3(0.0);
    LOOP for (int i = 0; i < SNOW_CELLS; i++) {
        float3 h = h33(ip + 17.0);
        if (h.x > 0.55) {
            float3 c = (ip + 0.15 + 0.7 * h + 0.12 * sin(t * float3(0.31, 0.23, 0.27) + h * 40.0)
                        - float3(0.0, fract(t * 0.004 * (1.0 + h.y)), 0.0)) * CS;
            float3 v = c - ro; float tt = dot(v, rd);
            if (tt > 0.05 && tt < tEnd) {
                float d = length(v - rd * tt);
                float sz = 0.010 + 0.020 * h.z + tt * 0.0035 + abs(tt - 7.0) * 0.0025;  // grows with distance and defocus
                float g = exp(-sq(d / sz)) * (0.010 + 0.02 * h.y) / (sz * 30.0);
                acc += g * float3(0.7, 0.95, 1.0) * (W.hi * 6.0 + 0.15) * exp(-W.sig * tt);
            }
        }
        float3 m = step(sd, sd.yzx) * step(sd, sd.zxy);
        sd += m * dd; ip += m * st;
    }
    return acc;
}

// --- the frame ---------------------------------------------------------------------
// ``presence`` is the idle fade (1 in use, easing to 0 when the app parks): the
// jellyfish and the surface fade out with it, so what is left standing still
// is the water, the shafts and the floor -- nothing caught in mid-motion.
INL float4 pelagic(float2 pos, float2 res, float t, float presence) {
    Water W = water(t);
    float2 uv = float2(2.0 * pos.x - res.x, res.y - 2.0 * pos.y) / res.y;   // y up, view-height units
    Cam cm = camera(t);
    float3 ro = cm.ro;
    float3 fw = normalize(cm.ta - ro), rt = normalize(cross(fw, float3(0.0, 1.0, 0.0))), up = cross(rt, fw);
    float3 rd = normalize(uv.x * rt + uv.y * up + FOCAL * fw);
    float3 L = SUN_W;
    float jit = h21(pos);

    // what the ray ends on
    float tEnd = 90.0; float3 bg; bool hit = true;
    float tS = rd.y > 0.0 ? (SURF - ro.y) / rd.y : 1e9;
    float tF = 1e9;
    if (rd.y < 0.0) tF = (FLOOR_Y - ro.y) / rd.y;   // the floor is a plane below the camera
    Turtle TU = turtle(t); float tT = 1e9;
    if (TU.on > 0.5) {
        float3 oc = ro - TU.c; float b = dot(oc, rd), q = dot(oc, oc) - 10.0, dsc = b * b - q;
        if (dsc > 0.0) {
            dsc = sqrt(dsc); float t1 = -b + dsc; float tt = max(-b - dsc, 0.0);
            LOOP for (int i = 0; i < TURTLE_STEPS; i++) {
                if (tt > t1) break;
                float d = turtleMap(ro + rd * tt, TU).x;
                if (d < 0.002 * tt + 0.002) { tT = tt; break; }
                tt += d * 0.8;
            }
        }
    }
    float3 amb = mix(W.lo, W.hi, smoothstep(-0.7, 0.9, rd.y));
    if (tT < tS && tT < tF) {
        tEnd = tT; bg = turtleShade(ro + rd * tT, rd, TU, t, W);
    } else if (tS < tF && tS < 90.0) {
        tEnd = tS;
        float3 p = ro + rd * tS; float4 w = swell(p.xz, t);
        float2 rg = chop(p.xz, t, tS);
        float3 n = normalize(float3(-w.y - rg.x, 1.0, -w.z - rg.y));
        float3 tr = refract(rd, -n, 1.333);
        float3 refl = mix(W.lo, W.hi, smoothstep(-0.7, 0.9, reflect(rd, n).y)) * 1.1;
        if (dot(tr, tr) > 0.0) {
            float F = 0.02 + 0.98 * pow(max(1.0 - abs(dot(tr, n)), 0.0), 5.0);
            float3 sky = mix(float3(0.50, 0.72, 0.82), float3(0.16, 0.36, 0.62), smoothstep(0.0, 0.9, tr.y));
            float sd = max(dot(tr, SUN_AIR), 0.0);
            // the sun seen through each facet: glints near the sun, soft mottling elsewhere
            sky += float3(1.0, 0.96, 0.88) * (pow(sd, 1500.0) * 120.0 + pow(sd, 160.0) * 28.0
                                              + pow(sd, 24.0) * 4.0 + pow(sd, 4.0) * 0.7);
            sky *= 0.85 + 0.3 * vn(p.xz * 0.35 + float2(0.05, 0.03) * t);
            bg = sky * (1.0 - F) * 0.45 + refl * F;
        } else {
            bg = refl;   // total internal reflection: the same limit as F -> 1, so no seam
        }
        bg = mix(amb, bg, presence);   // fading out: open water where the surface was
    } else if (tF < 90.0) {
        tEnd = tF;
        float3 p = ro + rd * tF;
        // Colour: a soft, broad blend of sand and coral -- no terrain drawn.
        float edge = mix(CORAL_EDGE_SAND, CORAL_EDGE_REEF, W.coral);
        float reef = smoothstep(edge - CORAL_SOFT, edge + CORAL_SOFT, fbm(p.xz * 0.045 + 3.1));
        float3 alb = mix(SAND, CORAL, reef);
        // Light: the same shafts (looked up where the sun ray entered, bent by the
        // swell), smoothed into slow waves of brightness instead of lines.
        float2 s0 = surfacePoint(p);
        float2 qs = s0 - swell(s0, t).yz * (-p.y) * BEND;
        float wave = vn(qs * 0.22 + float2(0.03, 0.02) * t) * 0.62 + vn(qs * 0.55 - float2(0.02, 0.05) * t) * 0.38;
        float3 li = sunCol(p, W) * SUN_W.y * (FLOOR_EVEN + FLOOR_WAVE * wave);
        bg = alb * (li * FLOOR_SUN + W.hi * FLOOR_FILL);
        // Near, the floor's own colour; further off it melts into the water, so
        // there is no horizon line, only sea colour toward the middle of the frame.
        bg = mix(amb, bg, 1.0 - smoothstep(FLOOR_NEAR, FLOOR_FAR, tF));
    } else {
        bg = amb; hit = false;
    }
    float3 Tw = exp(-W.sig * tEnd);
    float3 col = bg * Tw + amb * (1.0 - Tw);

    // god rays: single-scatter march along the view ray
    {
        float tm = min(tEnd, GOD_RANGE);
        float dt = tm / float(GOD_STEPS);
        float mu = dot(rd, L);
        float g = 0.72; float hg = (1.0 - g * g) / pow(1.0 + g * g - 2.0 * g * mu, 1.5) / (4.0 * PI);
        float g2 = 0.94; hg = 0.65 * hg + 0.35 * (1.0 - g2 * g2) / pow(1.0 + g2 * g2 - 2.0 * g2 * mu, 1.5) / (4.0 * PI);
        float3 acc = F3(0.0);
        // The ray stays under the surface, so the sunlight reaching a point times
        // the attenuation back to the eye, sunCol(p) * exp(-sig * tt), is an
        // exponential in tt: start it at the first sample, multiply per step.
        float slope = 1.0 - rd.y / SUN_W.y;
        float3 light = float3(1.0, 0.97, 0.9) * 5.0
                     * exp(-W.sig * ((SURF - ro.y) / SUN_W.y + jit * dt * slope));
        float3 stepMul = exp(-W.sig * (dt * slope));
        LOOP for (int i = 0; i < GOD_STEPS; i++) {
            float tt = (float(i) + jit) * dt;
            acc += light * lightPat(ro + rd * tt, t) * dt;
            light *= stepMul;
        }
        col += acc * (0.0025 + 0.10 * hg) * W.ray;
        // the diffuse glow of the sun through the water column
        float mp = max(mu, 0.0);
        float halo = pow(mp, 6.0) * 0.35 + pow(mp, 40.0) * 1.2 + pow(mp, 300.0) * 3.0;
        col += sunCol(ro, W) * halo * 0.06 * (1.0 - exp(-0.08 * tm)) * mix(F3(1.0), W.ray, 0.9);
    }

    col += snow(ro, rd, tEnd, t, W);

    float3 jc = F3(0.0); float jT = 1.0;
    int count = presence > 0.003 ? JELLYFISH : 0;
    LOOP for (int i = 0; i < 6; i++) {
        if (i >= count) break;
        Jelly j = jelly(i, t);
        // A jellyfish that drifts close to the lens fades out instead of filling the
        // frame: a large one on screen is also the dearest thing to draw.
        float fd = smoothstep(JELLY_HIDE * j.R, JELLY_SHOW * j.R, length(j.c - ro));
        if (fd < 0.01) continue;
        float4 r = renderJelly(ro, rd, j, float(i), tEnd, t, jit, W);
        fd *= presence;
        jc += r.rgb * fd * jT; jT *= mix(1.0, r.a, fd);
    }
    col = col * jT + jc;
    // Linear HDR; inverse depth in alpha for the lens (0 for open water).
    return float4(max(col * EXPOSURE, F3(0.0)), hit ? 1.0 / tEnd : 0.0);
}
"""

_ENTRY_MSL = """
fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    return pelagic(pos.xy, u.resolution, u.time + START, u.opacity);
}
"""

_ENTRY_HLSL = """
float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    return pelagic(pos.xy, resolution, time + START, opacity);
}
"""


def _dialect(text: str, dialect: str) -> str:
    """Spell the common body in ``dialect`` ("msl" or "hlsl")."""
    if dialect == "msl":
        subs = (("CONST ", "constant "), ("INL ", "static inline "), ("LOOP ", ""),
                ("UNROLL ", ""), ("F2(", "float2("), ("F3(", "float3("), ("F4(", "float4("))
        for a, b in subs:
            text = text.replace(a, b)
        return text
    subs = (("CONST ", "static const "), ("INL ", ""), ("LOOP ", "[loop] "),
            ("UNROLL ", "[unroll] "), ("F2(", "(float2)("), ("F3(", "(float3)("),
            ("F4(", "(float4)("))
    for a, b in subs:
        text = text.replace(a, b)
    text = re.sub(r"\bfract\(", "frac(", text)
    return re.sub(r"\bmix\(", "lerp(", text)


def _tables() -> str:
    air, water = sun_vectors()
    return _TABLES.format(swell=", ".join(_f4(r) for r in swell_table()),
                          swell_w=", ".join(repr(w) for w in swell_omegas()),
                          sun_air=_f3(air), sun_water=_f3(water))


def source(dialect: str, jellyfish=DEFAULT_JELLYFISH, exposure=DEFAULT_EXPOSURE) -> str:
    """The scene's source in ``dialect`` with the options baked in."""
    text = (_OPTIONS.format(jellyfish=int(jellyfish), exposure=repr(float(exposure)))
            + _tables() + BODY)
    return _dialect(text, dialect) + (_ENTRY_MSL if dialect == "msl" else _ENTRY_HLSL)


#: The lens, matched against the prototype's post pass on its own HDR frames
#: (doc/dev/PELAGIC_DESIGN.md §2): its ACES tone map on colour x 1.15, its
#: vignette, a sun-only bloom, fine grain.
LENS = Look(gain=1.15, bloom=1.5, threshold=1.6, vignette=0.47, grain=0.06)


def _clamped(value, default: float, lo: float, hi: float) -> float:
    try:
        v = float(default if value is None else value)
    except (TypeError, ValueError):
        v = default
    if v != v:   # NaN
        v = default
    return min(hi, max(lo, v))


def pelagic_look(brightness=None) -> Look:
    """:data:`LENS` with a theme's ``brightness`` ceiling (0..1)."""
    return replace(LENS, level=_clamped(brightness, DEFAULT_BRIGHTNESS, 0.0, 1.0))


def pelagic_shader(jellyfish=None, exposure=None, brightness=None) -> dict:
    """The ``Shader`` fields for the Pelagic scene with a theme's options applied:
    ``jellyfish`` (0..6, 6 as tuned), ``exposure`` (0.1..4, 1 as tuned) and
    ``brightness`` (the picture's ceiling, 0..1, default 0.7). Bad values fall
    back to the defaults."""
    count = int(round(_clamped(jellyfish, DEFAULT_JELLYFISH, 0, 6)))
    exp_ = _clamped(exposure, DEFAULT_EXPOSURE, 0.1, 4.0)
    return {
        **lens_shader(source("msl", count, exp_), source("hlsl", count, exp_),
                      pelagic_look(brightness)),
        "resolution_scale": RESOLUTION_SCALE,
        "pixel_density": PIXEL_DENSITY,
        "frame_rate": FRAME_RATE,
        # Fades, but only in part: PuiKit keeps the scene moving while it eases
        # the opacity uniform to 0, the scene fades its jellyfish and surface by
        # it, and parks on the still water, shafts and floor.
        "idle": "fade",
    }
