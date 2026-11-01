"""The Blocks background scene: a field of dark metal columns, with light leaking
up through the gaps.

A dense square grid of tall blue-black columns with rounded edges, seen in
perspective through blue fog. The columns rise and fall slowly, each at its own
uneven speed — long slow stretches, a brief surge, then nearly still again —
and every so often light leaks up through a gap junction from below, swells,
glows on the sides of the neighbouring columns, and dies away. A slow camera
loops through composed shots: wide oblique views, low close ones where the
columns loom, a skim across the tops, near-overhead views, a macro shot.

**One fragment, no meshes.** The columns are found by walking the grid cells
the ray crosses (a 2D DDA, Amanatides–Woo) and intersecting each cell's column;
the field is infinite (every value hashes from the cell index), so its edge can
never show. The rounded edges are not geometry: near an edge the shading normal
bends round a quarter circle of ``EDGE_R``, which is what puts the thin bright
highlight along every edge.

**Everything is a function of ``time``.** The prototype integrated each
column's phase from a drifting speed; that is per-column state, which a
background cannot keep. Here the speed is ``SLOW + SURGE * s^6`` with ``s = 0.5
+ 0.5 sin(vA t + vB)`` — near zero most of the time, a surge when ``s`` nears 1 —
and its integral is closed form (``s^6`` is ``cos^12`` of half the angle, and
power reduction turns that into a sum of cosines), so the phase is a function
of ``t``. The global swell is integrated the same way. Leaks are hashed events:
each gap junction has one event slot per ``LEAK_PERIOD`` that fires with a
probability weighted toward where the camera looks (the look target is a
closed-form function of time too), with its start, length, peak and radius
from the hash; a point evaluates only the junctions near it.

**Colour.** The leak light is the theme's ``ink``; the fog and the sky are
built from its ``backdrop``. The metal itself is the approved blue-black and
does not follow the palette. A lens (PuiKit's background-only chain) supplies
the bloom that carries the glow, tone-maps, and caps the brightness.

MSL is the source of truth; the HLSL is a mechanical port of it.
"""

from __future__ import annotations

from dataclasses import replace

try:
    from puikit.background import Lens
    AVAILABLE = True
except ImportError:
    # PuiKit 1.17.0 and older have no background lens; see background_earth.
    AVAILABLE = False

#: Options a theme's ``animation`` dict may carry for this scene.
OPTIONS = ("leaks", "leak_strength", "motion", "camera", "exposure", "brightness")

DEFAULT_BRIGHTNESS = 0.5

#: Fraction of native resolution. The edge highlights are a few pixels wide at
#: mid distance; 0.75 keeps them from crawling while saving almost half the cost.
RESOLUTION_SCALE = 0.75

_MSL_OPTIONS = """
// --- per-theme options (baked by xefm.background_blocks.blocks_shader) -------
constant float LEAK_RATE  = {leaks};          // how often light leaks (1 = as tuned)
constant float LEAK_POWER = {leak_strength};  // how bright a leak gets
constant float BOB        = {motion};         // how far the columns rise and fall
constant float CAM_SPEED  = {camera};         // camera speed along its loop
constant float EXPOSURE   = {exposure};
"""

_HLSL_OPTIONS = """
// --- per-theme options (baked by xefm.background_blocks.blocks_shader) -------
static const float LEAK_RATE  = {leaks};
static const float LEAK_POWER = {leak_strength};
static const float BOB        = {motion};
static const float CAM_SPEED  = {camera};
static const float EXPOSURE   = {exposure};
"""

BLOCKS_MSL_BODY = """
// --- tunables ---------------------------------------------------------------
constant float PI         = 3.14159265;
constant float HALF_W     = 0.455;    // half the width of a column (pitch 1, gap 0.09)
constant float EDGE_R     = 0.045;    // radius of the rounded edges
constant float FLOOR_Y    = -3.75;    // the glowing floor, well below the columns
constant float FOG_D      = 0.055;    // exponential-squared fog density
constant int   MAX_CELLS  = 72;       // cells a ray may cross before it is fog
constant float MAX_T      = 42.0;     // and the distance at which it is fog anyway
constant float SLOW       = 0.06;     // a column's resting speed ...
constant float SURGE      = 1.5;      // ... and how much faster it gets at a surge
constant float METAL      = 0.92;
constant float ROUGH      = 0.36;
constant float ENV_INT    = 0.4;
constant float LOOP_SEC   = 300.0;    // one pass through every shot
constant int   SHOT_COUNT = 8;
constant float LEAK_PERIOD = 10.0;    // each junction's event slot, seconds
constant float LEAK_BASE  = 0.00028;  // leaks per junction per second, anywhere
constant float LEAK_NEAR  = 0.0084;   // ... and extra near the camera's target
constant float LEAK_NEAR_R = 3.0;     // how near "near" is
constant float LEAK_RANGE = 4.5;      // how far a leak lights the columns' sides
constant float LEAK_LIGHT = 9.0;      // and how strongly

// The prototype's colours, taken as three.js r147 takes a hex colour: as linear
// values, not sRGB. Decoding them would make the metal a near-black it never was.
constant float3 ALBEDO   = float3(0.106, 0.149, 0.208);      // #1b2635
constant float3 KEY_COL  = float3(0.725, 0.839, 0.961) * 0.75;
constant float3 SKY_COL  = float3(0.373, 0.525, 0.722) * 0.12;

// The shots: camera position, look target and vertical field of view (degrees).
// Columns are centred on integers here and on half-integers in the prototype, so
// the positions are the prototype's shifted by half a cell to frame the same gaps.
//                               wide  low   skim   high   top   far   macro  high-wide
constant float CAM_X[8]  = {0.5, 3.5, -3.5, -1.5, 3.5, 8.5, 2.1, -5.5};
constant float CAM_Y[8]  = {5.5, 1.9, 1.4, 9.5, 5.5, 2.4, 1.5, 8.0};
constant float CAM_Z[8]  = {13.5, 6.5, 2.5, 1.7, -1.5, -5.5, -0.5, 8.5};
constant float TGT_X[8]  = {0.5, 0.5, -7.5, -1.5, 3.7, 2.5, 0.5, 0.5};
constant float TGT_Y[8]  = {-0.5, 0.6, 0.4, 0.0, 0.0, 0.0, 0.8, -1.0};
constant float TGT_Z[8]  = {0.5, -1.5, -5.5, 1.1, -1.0, -0.5, -2.1, 0.5};
constant float CAM_FOV[8] = {38.0, 32.0, 46.0, 40.0, 34.0, 34.0, 29.0, 42.0};

struct Cam { float3 ro; float3 fw; float3 rt; float3 up; float focal; float3 target; };
struct Hit { float t; float3 n; float2 cell; float top; int kind; };   // kind 0 none, 1 column, 2 floor

static inline float hash2(float2 p) {
    float3 p3 = fract(float3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

static inline float3 hash3(float3 p) {
    p = fract(p * float3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return fract((p.xxy + p.yxx) * p.zyx);
}

// --- the camera: closed Catmull-Rom loops through the shots ------------------

static inline float3 shot_pos(int i) { return float3(CAM_X[i], CAM_Y[i], CAM_Z[i]); }
static inline float3 shot_tgt(int i) { return float3(TGT_X[i], TGT_Y[i], TGT_Z[i]); }

// Non-uniform Catmull-Rom with centripetal knot spacing, as three.js builds it.
static inline float3 centripetal(float3 p0, float3 p1, float3 p2, float3 p3, float u) {
    float dt0 = pow(max(dot(p1 - p0, p1 - p0), 1e-8), 0.25);
    float dt1 = pow(max(dot(p2 - p1, p2 - p1), 1e-8), 0.25);
    float dt2 = pow(max(dot(p3 - p2, p3 - p2), 1e-8), 0.25);
    if (dt1 < 1e-4) dt1 = 1.0;
    if (dt0 < 1e-4) dt0 = dt1;
    if (dt2 < 1e-4) dt2 = dt1;
    float3 m1 = ((p1 - p0) / dt0 - (p2 - p0) / (dt0 + dt1) + (p2 - p1) / dt1) * dt1;
    float3 m2 = ((p2 - p1) / dt1 - (p3 - p1) / (dt1 + dt2) + (p3 - p2) / dt2) * dt1;
    float3 c2 = -3.0 * p1 + 3.0 * p2 - 2.0 * m1 - m2;
    float3 c3 = 2.0 * p1 - 2.0 * p2 + m1 + m2;
    return p1 + m1 * u + c2 * u * u + c3 * u * u * u;
}

static inline float catmull(float x0, float x1, float x2, float x3, float u) {
    float m1 = 0.5 * (x2 - x0), m2 = 0.5 * (x3 - x1);
    return x1 + m1 * u + (-3.0 * x1 + 3.0 * x2 - 2.0 * m1 - m2) * u * u
         + (2.0 * x1 - 2.0 * x2 + m1 + m2) * u * u * u;
}

// Where the loop is at camera time c: lingering near each shot, travelling between.
static inline float loop_param(float c) {
    float u = fract(c / LOOP_SEC) * float(SHOT_COUNT);
    float k = floor(u), f = u - k;
    float e = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    return k + 0.35 * f + 0.65 * e;               // in shots, 0..SHOT_COUNT
}

static inline int wrap_shot(int i) { return (i % SHOT_COUNT + SHOT_COUNT) % SHOT_COUNT; }

// The camera's look target at time t -- also where leaks favour.
static inline float3 target_at(float t) {
    float p = loop_param(t * CAM_SPEED);
    int k = int(floor(p));
    float w = p - float(k);
    return centripetal(shot_tgt(wrap_shot(k - 1)), shot_tgt(wrap_shot(k)),
                       shot_tgt(wrap_shot(k + 1)), shot_tgt(wrap_shot(k + 2)), w);
}

static inline Cam camera(float t, float aspect) {
    float c = t * CAM_SPEED;
    float p = loop_param(c);
    int k = int(floor(p));
    float w = p - float(k);
    int i0 = wrap_shot(k - 1), i1 = wrap_shot(k), i2 = wrap_shot(k + 1), i3 = wrap_shot(k + 2);
    Cam cam;
    cam.ro = centripetal(shot_pos(i0), shot_pos(i1), shot_pos(i2), shot_pos(i3), w);
    cam.target = centripetal(shot_tgt(i0), shot_tgt(i1), shot_tgt(i2), shot_tgt(i3), w);
    // A slow breathing drift on top of the path.
    cam.ro += float3(0.25 * sin(c * 0.11), 0.15 * sin(c * 0.083), 0.0);
    float fov = catmull(CAM_FOV[i0], CAM_FOV[i1], CAM_FOV[i2], CAM_FOV[i3], w);
    if (aspect < 0.8) fov *= 1.35;                 // portrait: widen
    cam.focal = 0.5 / tan(fov * PI / 360.0);
    cam.fw = normalize(cam.target - cam.ro);
    float3 rt = normalize(cross(cam.fw, float3(0.0, 1.0, 0.0)));
    float3 up = cross(rt, cam.fw);
    float roll = 0.04 * sin(c * 0.05);
    cam.rt = rt * cos(roll) + up * sin(roll);
    cam.up = up * cos(roll) - rt * sin(roll);
    return cam;
}

// --- the columns -------------------------------------------------------------

// The integral of s^6 over time, s = 0.5 + 0.5 sin(a t + b), up to a constant:
// s = cos^2(psi) with psi = (a t + b - PI/2) / 2, and cos^12 reduces to a sum of
// cosines whose integrals are sines.
static inline float surge_integral(float t, float a, float b) {
    float psi = 0.5 * (a * t + b - 0.5 * PI);
    float f = 924.0 * psi + 792.0 * sin(2.0 * psi) + 247.5 * sin(4.0 * psi)
            + 73.3333 * sin(6.0 * psi) + 16.5 * sin(8.0 * psi) + 2.4 * sin(10.0 * psi)
            + 0.166667 * sin(12.0 * psi);
    return f / 4096.0 * 2.0 / a;
}

// The global swell's phase: the integral of 0.3 (0.35 + 1.3 (0.5 + 0.5 sin 0.07t)^2).
static inline float swell(float t) {
    float s2 = 0.375 * t - 0.5 * cos(0.07 * t) / 0.07 - 0.125 * sin(0.14 * t) / 0.14;
    return 0.3 * (0.35 * t + 1.3 * s2);
}

static inline float column_top(float2 c, float t, float sw) {
    float base = floor(hash2(c) * 3.0 + 0.5) * 0.28 + 0.15 * sin(0.35 * c.x) + 0.15 * cos(0.27 * c.y);
    float phase = hash2(c + float2(17.0, 3.0)) * 2.0 * PI;
    float freq = 0.15 + 0.25 * hash2(c + float2(5.0, 41.0));
    float amp = 0.12 + 0.35 * hash2(c + float2(9.0, 7.0));
    float va = 0.05 + 0.12 * hash2(c + float2(23.0, 13.0));
    float vb = 2.0 * PI * hash2(c + float2(31.0, 29.0));
    float ph = phase + freq * 2.0 * (SLOW * t + SURGE * surge_integral(t, va, vb));
    return base + (0.8 * sin(ph) + 0.2 * sin(1.618 * ph + 1.3)) * amp * BOB
         + 0.12 * sin(sw + 0.25 * c.x + 0.18 * c.y) * BOB;
}

// Walk the cells the ray crosses (centres on integers) and hit the first column.
static inline Hit trace(float3 ro, float3 rd, float t0, float time, float sw) {
    Hit h;
    h.kind = 0;
    h.t = MAX_T;
    float ymax = 1.3 + 0.6 * BOB;
    float t = t0;
    if (ro.y > ymax) {
        if (rd.y >= 0.0) return h;
        t = max(t, (ymax - ro.y) / rd.y);
    }
    float2 rdxz = float2(abs(rd.x) < 1e-6 ? 1e-6 : rd.x, abs(rd.z) < 1e-6 ? 1e-6 : rd.z);
    float2 p = ro.xz + rdxz * t;
    float2 cell = floor(p + 0.5);
    float2 stp = float2(rdxz.x > 0.0 ? 1.0 : -1.0, rdxz.y > 0.0 ? 1.0 : -1.0);
    float2 tdelta = abs(1.0 / rdxz);
    float2 tmax = t + ((cell + 0.5 * stp) - p) / rdxz;
    float tfloor = rd.y < 0.0 ? (FLOOR_Y - ro.y) / rd.y : 1e9;
    for (int i = 0; i < MAX_CELLS; i++) {
        float texit = min(tmax.x, tmax.y);
        float top = column_top(cell, time, sw);
        float2 lo = (cell - HALF_W - ro.xz) / rdxz, hi = (cell + HALF_W - ro.xz) / rdxz;
        float2 tn = min(lo, hi), tf = max(lo, hi);
        float ty = (top - ro.y) / rd.y;
        float tye = rd.y < 0.0 ? ty : (ro.y <= top ? -1e9 : 1e9);
        float tyx = rd.y < 0.0 ? 1e9 : (ro.y <= top ? ty : -1e9);
        float te = max(max(tn.x, tn.y), tye);
        float tx = min(min(tf.x, tf.y), tyx);
        if (te <= tx && te > 1e-3 && te < tfloor) {
            h.kind = 1;
            h.t = te;
            h.cell = cell;
            h.top = top;
            if (te == tye) h.n = float3(0.0, 1.0, 0.0);
            else if (tn.x > tn.y) h.n = float3(-stp.x, 0.0, 0.0);
            else h.n = float3(0.0, 0.0, -stp.y);
            return h;
        }
        if (tfloor <= texit) {
            h.kind = 2;
            h.t = tfloor;
            h.n = float3(0.0, 1.0, 0.0);
            return h;
        }
        if (texit > MAX_T) return h;
        if (tmax.x < tmax.y) { cell.x += stp.x; tmax.x += tdelta.x; }
        else { cell.y += stp.y; tmax.y += tdelta.y; }
    }
    return h;
}

// The rounded edge, as shading: near an edge the normal turns round a quarter
// circle of EDGE_R toward the neighbouring face.
static inline float3 rounded_normal(float3 p, Hit h) {
    float2 l = p.xz - h.cell;
    float dy = h.top - p.y;
    float2 e = clamp((abs(l) - (HALF_W - EDGE_R)) / EDGE_R, 0.0, 1.0);
    float uy = clamp((EDGE_R - dy) / EDGE_R, 0.0, 1.0);
    float2 s = float2(l.x < 0.0 ? -1.0 : 1.0, l.y < 0.0 ? -1.0 : 1.0);
    if (h.n.y > 0.5) {
        return normalize(float3(s.x * e.x, sqrt(max(1.0 - e.x * e.x - e.y * e.y, 0.0)), s.y * e.y));
    }
    if (abs(h.n.x) > 0.5) {
        return normalize(float3(h.n.x * sqrt(max(1.0 - uy * uy - e.y * e.y, 0.0)), uy, s.y * e.y));
    }
    return normalize(float3(s.x * e.x, uy, h.n.z * sqrt(max(1.0 - uy * uy - e.x * e.x, 0.0))));
}

// --- light leaking from below ------------------------------------------------

// The leak at junction j (a cell corner) at time t: x = brightness, y = radius.
// Three families of junctions run their event slots a third of a period apart,
// so the slots' boundaries do not pulse the whole field at once; targets holds
// the camera target at the start of each family's current slot.
static inline float2 leak(float2 j, float t, float3 targets[3]) {
    float fam = floor(hash2(j + float2(41.0, 11.0)) * 3.0);
    int fi = int(fam);
    float offset = fam / 3.0;
    float k = floor(t / LEAK_PERIOD + offset);
    float start = (k - offset) * LEAK_PERIOD;
    float3 h = hash3(float3(j, k));
    float2 d = j - targets[fi].xz;
    float rate = LEAK_RATE * (LEAK_BASE + LEAK_NEAR * exp(-dot(d, d) / (2.0 * LEAK_NEAR_R * LEAK_NEAR_R)));
    if (h.x > rate * LEAK_PERIOD) return float2(0.0, 1.0);
    float3 g = hash3(float3(j + 7.3, k + 1.7));
    float dur = 3.0 + 5.0 * h.y;
    float u = (t - start - (LEAK_PERIOD - dur) * h.z) / dur;
    if (u <= 0.0 || u >= 1.0) return float2(0.0, 1.0);
    float rise = sin(u / 0.3 * 0.5 * PI);
    float env = u < 0.3 ? rise * rise : pow(1.0 - (u - 0.3) / 0.7, 1.6);
    float flick = 0.9 + 0.1 * sin(t * 7.3 + j.x * 3.1);
    return float2(env * (0.5 + 0.7 * g.x) * LEAK_POWER * flick, 0.5 + 0.9 * g.y);
}

// --- shading -----------------------------------------------------------------

// A soft studio in place of the prototype's room environment: a dark gradient
// and a few emissive panels that widen with roughness.
static inline float3 environment(float3 d, float rough) {
    float w = 0.15 + rough;
    float3 c = mix(float3(0.02, 0.025, 0.03), float3(0.45, 0.47, 0.5), smoothstep(-0.1, 1.0, d.y));
    c += float3(3.0) * smoothstep(1.0 - 0.25 * w, 1.0, d.y);                            // ceiling panel
    c += float3(2.0) * smoothstep(1.0 - 0.3 * w, 1.0, dot(d, normalize(float3(-0.7, 0.4, 0.5))));
    c += float3(1.6) * smoothstep(1.0 - 0.3 * w, 1.0, dot(d, normalize(float3(0.8, 0.3, -0.4))));
    return c;
}

static inline float ggx(float3 n, float3 v, float3 l, float rough) {
    float3 hv = normalize(v + l);
    float nh = max(dot(n, hv), 0.0), nl = max(dot(n, l), 0.0), nv = max(dot(n, v), 1e-3);
    float a = rough * rough, a2 = a * a;
    float dd = nh * nh * (a2 - 1.0) + 1.0;
    float D = a2 / (PI * dd * dd);
    float k = a * 0.5;
    float G = nl / (nl * (1.0 - k) + k) * nv / (nv * (1.0 - k) + k);
    return D * G / (4.0 * nv + 1e-4);
}

static inline float3 fresnel(float3 f0, float c) {
    return f0 + (1.0 - f0) * pow(1.0 - c, 5.0);
}

static inline float3 shade_column(float3 p, float3 n, float3 rd, Hit h, float t, float3 glow,
                                  float3 targets[3]) {
    float3 v = -rd;
    float3 f0 = mix(float3(0.04), ALBEDO, METAL);
    float3 diff = ALBEDO * (1.0 - METAL);
    float nv = max(dot(n, v), 0.0);
    float3 key = normalize(float3(-6.0, 10.0, 4.0));
    float nl = max(dot(n, key), 0.0);
    float3 col = (diff / PI + fresnel(f0, max(dot(normalize(v + key), v), 0.0)) * ggx(n, v, key, ROUGH))
               * KEY_COL * nl * PI;
    col += diff * mix(float3(0.0), SKY_COL, 0.5 + 0.5 * n.y);
    col += environment(reflect(rd, n), ROUGH) * fresnel(f0, nv) * ENV_INT;
    // The leaks below light the sides that face their gap. Only the junctions
    // of this column and the ring round it can reach, and only sides see them.
    if (n.y < 0.7) {
        for (int jz = -1; jz <= 2; jz++) {
            for (int jx = -1; jx <= 2; jx++) {
                float2 j = h.cell + float2(float(jx) - 0.5, float(jz) - 0.5);
                float2 lk = leak(j, t, targets);
                if (lk.x <= 0.0) continue;
                float3 lp = float3(j.x, h.top - 0.9, j.y);
                float3 dl = lp - p;
                float dist = length(dl);
                float att = max(1.0 - dist / LEAK_RANGE, 0.0);
                if (att <= 0.0) continue;
                float3 l = dl / dist;
                float lnl = max(dot(n, l), 0.0);
                float3 spec = fresnel(f0, max(dot(normalize(v + l), v), 0.0)) * ggx(n, v, l, ROUGH);
                col += (diff / PI + spec) * glow * lk.x * LEAK_LIGHT * att * att * lnl;
            }
        }
    }
    return col;
}

static inline float3 floor_glow(float2 x, float t, float3 glow, float3 targets[3]) {
    float g = 0.0;
    float2 c = floor(x) + 0.5;                    // the junction lattice is at half-integers
    for (int jz = -2; jz <= 2; jz++) {
        for (int jx = -2; jx <= 2; jx++) {
            float2 j = c + float2(float(jx), float(jz));
            float2 lk = leak(j, t, targets);
            if (lk.x <= 0.0) continue;
            float2 d = x - j;
            g += lk.x * exp(-dot(d, d) / (lk.y * lk.y));
        }
    }
    return glow * (g * 3.2 + 0.035);
}

// --- the distance: haze, a faint glow, dust ---------------------------------

static inline float vnoise(float3 x) {
    float3 i = floor(x), f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash2(i.xy + 37.0 * i.z), b = hash2(i.xy + float2(1, 0) + 37.0 * i.z);
    float c = hash2(i.xy + float2(0, 1) + 37.0 * i.z), d = hash2(i.xy + float2(1, 1) + 37.0 * i.z);
    float e = hash2(i.xy + 37.0 * (i.z + 1.0)), g = hash2(i.xy + float2(1, 0) + 37.0 * (i.z + 1.0));
    float k = hash2(i.xy + float2(0, 1) + 37.0 * (i.z + 1.0)), m = hash2(i.xy + float2(1, 1) + 37.0 * (i.z + 1.0));
    return mix(mix(mix(a, b, f.x), mix(c, d, f.x), f.y), mix(mix(e, g, f.x), mix(k, m, f.x), f.y), f.z);
}

static inline float fbm(float3 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 4; i++) {
        s += a * vnoise(p);
        p = p * 2.03 + float3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return s;
}

static inline float3 sky(float3 d, float t, float3 fog, float3 glow) {
    float h = d.y;
    float3 top = fog * float3(0.154, 0.14, 0.174);
    float3 col = mix(fog, top, smoothstep(0.0, 0.55, h));
    col = mix(col, fog * 0.45, smoothstep(0.0, 0.4, -h));
    float band = exp(-h * h * 9.0);
    if (band > 0.02) {
        float n = fbm(d * float3(2.2, 7.0, 2.2) + float3(t * 0.012, 0.0, t * 0.008));
        col += fog * float3(2.6, 2.0, 1.75) * smoothstep(0.42, 0.85, n) * band * 0.55;
        float aur = fbm(d * float3(1.2, 3.0, 1.2) - float3(0.0, t * 0.006, t * 0.01));
        col += glow * 0.07 * smoothstep(0.5, 0.8, aur) * band * (0.6 + 0.4 * sin(t * 0.05 + d.x * 2.0));
    }
    return col;
}

// Fine motes in the air between the camera and what it sees: a few layers of
// hashed cells along the ray, each holding at most one mote that rises and sways.
static inline float3 dust(float3 ro, float3 rd, float tmax, float t, float pxAng, float3 glow) {
    float3 sum = float3(0.0);
    for (int i = 0; i < 6; i++) {
        float d = 1.6 + 2.2 * float(i);
        if (d > tmax) break;
        float3 q = ro + rd * d;
        float3 drift = float3(0.6 * sin(t * 0.05 + float(i)), -0.05 * t, 0.6 * cos(t * 0.04 + float(i)));
        float3 g = (q + drift) * 0.9;
        float3 cell = floor(g);
        float3 h = hash3(cell + float(i) * 17.0);
        if (h.x > 0.35) continue;
        float3 mote = (cell + 0.2 + 0.6 * hash3(cell + 3.7)) / 0.9 - drift;
        if (mote.y < 1.2 || mote.y > 7.2) continue;
        float3 w = mote - ro;
        float along = dot(w, rd);
        if (along <= 0.0 || along > tmax) continue;
        float off = length(w - rd * along) / along;          // angle off the ray
        float size = pxAng * (1.2 + 1.5 * h.y) + 0.004 / along;
        float a = exp(-off * off / (size * size));
        float tw = 0.55 + 0.45 * sin(t * (0.8 + h.z * 1.8) + h.y * 40.0);
        sum += mix(float3(0.55, 0.68, 0.85), glow, 0.5) * a * 0.05 * tw * exp(-pow(FOG_D * along, 2.0));
    }
    return sum;
}

fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float t = u.time;
    Cam cam = camera(t, u.resolution.x / u.resolution.y);
    float2 uv = float2(pos.x - 0.5 * u.resolution.x, 0.5 * u.resolution.y - pos.y) / u.resolution.y;
    float3 rd = normalize(uv.x * cam.rt + uv.y * cam.up + cam.focal * cam.fw);
    float pxAng = 1.0 / (u.resolution.y * cam.focal);
    // Taken as linear, like every prototype colour (see ALBEDO): the theme's
    // backdrop #0a1626 is then exactly the prototype's fog.
    float3 glow = u.ink.rgb;
    float3 fog = u.backdrop.rgb;
    float sw = swell(t);
    // The camera target at the start of each leak family's current slot.
    float3 targets[3];
    for (int f = 0; f < 3; f++) {
        float off = float(f) / 3.0;
        targets[f] = target_at((floor(t / LEAK_PERIOD + off) - off) * LEAK_PERIOD);
    }

    Hit h = trace(cam.ro, rd, 0.0, t, sw);
    float3 col;
    if (h.kind == 1) {
        float3 p = cam.ro + rd * h.t;
        col = shade_column(p, rounded_normal(p, h), rd, h, t, glow, targets);
    } else if (h.kind == 2) {
        float3 p = cam.ro + rd * h.t;
        col = floor_glow(p.xz, t, glow, targets);
        col = mix(col, fog * 0.6, (1.0 - exp(-pow(FOG_D * h.t, 2.0))) * 0.85);
    } else {
        col = sky(rd, t, fog, glow);
    }
    if (h.kind == 1) col = mix(col, fog, 1.0 - exp(-pow(FOG_D * h.t, 2.0)));
    col += dust(cam.ro, rd, h.t, t, pxAng, glow);
    // Linear HDR out: the lens blooms, tone-maps and caps it.
    return float4(max(col * EXPOSURE, 0.0), 1.0);
}
"""

BLOCKS_HLSL_BODY = """
// --- tunables ---------------------------------------------------------------
static const float PI         = 3.14159265;
static const float HALF_W     = 0.455;    // half the width of a column (pitch 1, gap 0.09)
static const float EDGE_R     = 0.045;    // radius of the rounded edges
static const float FLOOR_Y    = -3.75;    // the glowing floor, well below the columns
static const float FOG_D      = 0.055;    // exponential-squared fog density
static const int   MAX_CELLS  = 72;       // cells a ray may cross before it is fog
static const float MAX_T      = 42.0;     // and the distance at which it is fog anyway
static const float SLOW       = 0.06;     // a column's resting speed ...
static const float SURGE      = 1.5;      // ... and how much faster it gets at a surge
static const float METAL      = 0.92;
static const float ROUGH      = 0.36;
static const float ENV_INT    = 0.4;
static const float LOOP_SEC   = 300.0;    // one pass through every shot
static const int   SHOT_COUNT = 8;
static const float LEAK_PERIOD = 10.0;    // each junction's event slot, seconds
static const float LEAK_BASE  = 0.00028;  // leaks per junction per second, anywhere
static const float LEAK_NEAR  = 0.0084;   // ... and extra near the camera's target
static const float LEAK_NEAR_R = 3.0;     // how near "near" is
static const float LEAK_RANGE = 4.5;      // how far a leak lights the columns' sides
static const float LEAK_LIGHT = 9.0;      // and how strongly

// The prototype's colours, taken as three.js r147 takes a hex colour: as linear
// values, not sRGB. Decoding them would make the metal a near-black it never was.
static const float3 ALBEDO   = float3(0.106, 0.149, 0.208);      // #1b2635
static const float3 KEY_COL  = float3(0.725, 0.839, 0.961) * 0.75;
static const float3 SKY_COL  = float3(0.373, 0.525, 0.722) * 0.12;

// The shots: camera position, look target and vertical field of view (degrees).
// Columns are centred on integers here and on half-integers in the prototype, so
// the positions are the prototype's shifted by half a cell to frame the same gaps.
//                               wide  low   skim   high   top   far   macro  high-wide
static const float CAM_X[8]  = {0.5, 3.5, -3.5, -1.5, 3.5, 8.5, 2.1, -5.5};
static const float CAM_Y[8]  = {5.5, 1.9, 1.4, 9.5, 5.5, 2.4, 1.5, 8.0};
static const float CAM_Z[8]  = {13.5, 6.5, 2.5, 1.7, -1.5, -5.5, -0.5, 8.5};
static const float TGT_X[8]  = {0.5, 0.5, -7.5, -1.5, 3.7, 2.5, 0.5, 0.5};
static const float TGT_Y[8]  = {-0.5, 0.6, 0.4, 0.0, 0.0, 0.0, 0.8, -1.0};
static const float TGT_Z[8]  = {0.5, -1.5, -5.5, 1.1, -1.0, -0.5, -2.1, 0.5};
static const float CAM_FOV[8] = {38.0, 32.0, 46.0, 40.0, 34.0, 34.0, 29.0, 42.0};

struct Cam { float3 ro; float3 fw; float3 rt; float3 up; float focal; float3 target; };
struct Hit { float t; float3 n; float2 cell; float top; int kind; };   // kind 0 none, 1 column, 2 floor

float hash2(float2 p) {
    float3 p3 = frac(float3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return frac((p3.x + p3.y) * p3.z);
}

float3 hash3(float3 p) {
    p = frac(p * float3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return frac((p.xxy + p.yxx) * p.zyx);
}

// --- the camera: closed Catmull-Rom loops through the shots ------------------

float3 shot_pos(int i) { return float3(CAM_X[i], CAM_Y[i], CAM_Z[i]); }
float3 shot_tgt(int i) { return float3(TGT_X[i], TGT_Y[i], TGT_Z[i]); }

// Non-uniform Catmull-Rom with centripetal knot spacing, as three.js builds it.
float3 centripetal(float3 p0, float3 p1, float3 p2, float3 p3, float u) {
    float dt0 = pow(max(dot(p1 - p0, p1 - p0), 1e-8), 0.25);
    float dt1 = pow(max(dot(p2 - p1, p2 - p1), 1e-8), 0.25);
    float dt2 = pow(max(dot(p3 - p2, p3 - p2), 1e-8), 0.25);
    if (dt1 < 1e-4) dt1 = 1.0;
    if (dt0 < 1e-4) dt0 = dt1;
    if (dt2 < 1e-4) dt2 = dt1;
    float3 m1 = ((p1 - p0) / dt0 - (p2 - p0) / (dt0 + dt1) + (p2 - p1) / dt1) * dt1;
    float3 m2 = ((p2 - p1) / dt1 - (p3 - p1) / (dt1 + dt2) + (p3 - p2) / dt2) * dt1;
    float3 c2 = -3.0 * p1 + 3.0 * p2 - 2.0 * m1 - m2;
    float3 c3 = 2.0 * p1 - 2.0 * p2 + m1 + m2;
    return p1 + m1 * u + c2 * u * u + c3 * u * u * u;
}

float catmull(float x0, float x1, float x2, float x3, float u) {
    float m1 = 0.5 * (x2 - x0), m2 = 0.5 * (x3 - x1);
    return x1 + m1 * u + (-3.0 * x1 + 3.0 * x2 - 2.0 * m1 - m2) * u * u
         + (2.0 * x1 - 2.0 * x2 + m1 + m2) * u * u * u;
}

// Where the loop is at camera time c: lingering near each shot, travelling between.
float loop_param(float c) {
    float u = frac(c / LOOP_SEC) * float(SHOT_COUNT);
    float k = floor(u), f = u - k;
    float e = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    return k + 0.35 * f + 0.65 * e;               // in shots, 0..SHOT_COUNT
}

int wrap_shot(int i) { return (i % SHOT_COUNT + SHOT_COUNT) % SHOT_COUNT; }

// The camera's look target at time t -- also where leaks favour.
float3 target_at(float t) {
    float p = loop_param(t * CAM_SPEED);
    int k = int(floor(p));
    float w = p - float(k);
    return centripetal(shot_tgt(wrap_shot(k - 1)), shot_tgt(wrap_shot(k)),
                       shot_tgt(wrap_shot(k + 1)), shot_tgt(wrap_shot(k + 2)), w);
}

Cam camera(float t, float aspect) {
    float c = t * CAM_SPEED;
    float p = loop_param(c);
    int k = int(floor(p));
    float w = p - float(k);
    int i0 = wrap_shot(k - 1), i1 = wrap_shot(k), i2 = wrap_shot(k + 1), i3 = wrap_shot(k + 2);
    Cam cam;
    cam.ro = centripetal(shot_pos(i0), shot_pos(i1), shot_pos(i2), shot_pos(i3), w);
    cam.target = centripetal(shot_tgt(i0), shot_tgt(i1), shot_tgt(i2), shot_tgt(i3), w);
    // A slow breathing drift on top of the path.
    cam.ro += float3(0.25 * sin(c * 0.11), 0.15 * sin(c * 0.083), 0.0);
    float fov = catmull(CAM_FOV[i0], CAM_FOV[i1], CAM_FOV[i2], CAM_FOV[i3], w);
    if (aspect < 0.8) fov *= 1.35;                 // portrait: widen
    cam.focal = 0.5 / tan(fov * PI / 360.0);
    cam.fw = normalize(cam.target - cam.ro);
    float3 rt = normalize(cross(cam.fw, float3(0.0, 1.0, 0.0)));
    float3 up = cross(rt, cam.fw);
    float roll = 0.04 * sin(c * 0.05);
    cam.rt = rt * cos(roll) + up * sin(roll);
    cam.up = up * cos(roll) - rt * sin(roll);
    return cam;
}

// --- the columns -------------------------------------------------------------

// The integral of s^6 over time, s = 0.5 + 0.5 sin(a t + b), up to a constant:
// s = cos^2(psi) with psi = (a t + b - PI/2) / 2, and cos^12 reduces to a sum of
// cosines whose integrals are sines.
float surge_integral(float t, float a, float b) {
    float psi = 0.5 * (a * t + b - 0.5 * PI);
    float f = 924.0 * psi + 792.0 * sin(2.0 * psi) + 247.5 * sin(4.0 * psi)
            + 73.3333 * sin(6.0 * psi) + 16.5 * sin(8.0 * psi) + 2.4 * sin(10.0 * psi)
            + 0.166667 * sin(12.0 * psi);
    return f / 4096.0 * 2.0 / a;
}

// The global swell's phase: the integral of 0.3 (0.35 + 1.3 (0.5 + 0.5 sin 0.07t)^2).
float swell(float t) {
    float s2 = 0.375 * t - 0.5 * cos(0.07 * t) / 0.07 - 0.125 * sin(0.14 * t) / 0.14;
    return 0.3 * (0.35 * t + 1.3 * s2);
}

float column_top(float2 c, float t, float sw) {
    float base = floor(hash2(c) * 3.0 + 0.5) * 0.28 + 0.15 * sin(0.35 * c.x) + 0.15 * cos(0.27 * c.y);
    float phase = hash2(c + float2(17.0, 3.0)) * 2.0 * PI;
    float freq = 0.15 + 0.25 * hash2(c + float2(5.0, 41.0));
    float amp = 0.12 + 0.35 * hash2(c + float2(9.0, 7.0));
    float va = 0.05 + 0.12 * hash2(c + float2(23.0, 13.0));
    float vb = 2.0 * PI * hash2(c + float2(31.0, 29.0));
    float ph = phase + freq * 2.0 * (SLOW * t + SURGE * surge_integral(t, va, vb));
    return base + (0.8 * sin(ph) + 0.2 * sin(1.618 * ph + 1.3)) * amp * BOB
         + 0.12 * sin(sw + 0.25 * c.x + 0.18 * c.y) * BOB;
}

// Walk the cells the ray crosses (centres on integers) and hit the first column.
Hit trace(float3 ro, float3 rd, float t0, float time, float sw) {
    Hit h;
    h.kind = 0;
    h.t = MAX_T;
    float ymax = 1.3 + 0.6 * BOB;
    float t = t0;
    if (ro.y > ymax) {
        if (rd.y >= 0.0) return h;
        t = max(t, (ymax - ro.y) / rd.y);
    }
    float2 rdxz = float2(abs(rd.x) < 1e-6 ? 1e-6 : rd.x, abs(rd.z) < 1e-6 ? 1e-6 : rd.z);
    float2 p = ro.xz + rdxz * t;
    float2 cell = floor(p + 0.5);
    float2 stp = float2(rdxz.x > 0.0 ? 1.0 : -1.0, rdxz.y > 0.0 ? 1.0 : -1.0);
    float2 tdelta = abs(1.0 / rdxz);
    float2 tmax = t + ((cell + 0.5 * stp) - p) / rdxz;
    float tfloor = rd.y < 0.0 ? (FLOOR_Y - ro.y) / rd.y : 1e9;
    [loop] for (int i = 0; i < MAX_CELLS; i++) {
        float texit = min(tmax.x, tmax.y);
        float top = column_top(cell, time, sw);
        float2 lo = (cell - HALF_W - ro.xz) / rdxz, hi = (cell + HALF_W - ro.xz) / rdxz;
        float2 tn = min(lo, hi), tf = max(lo, hi);
        float ty = (top - ro.y) / rd.y;
        float tye = rd.y < 0.0 ? ty : (ro.y <= top ? -1e9 : 1e9);
        float tyx = rd.y < 0.0 ? 1e9 : (ro.y <= top ? ty : -1e9);
        float te = max(max(tn.x, tn.y), tye);
        float tx = min(min(tf.x, tf.y), tyx);
        if (te <= tx && te > 1e-3 && te < tfloor) {
            h.kind = 1;
            h.t = te;
            h.cell = cell;
            h.top = top;
            if (te == tye) h.n = float3(0.0, 1.0, 0.0);
            else if (tn.x > tn.y) h.n = float3(-stp.x, 0.0, 0.0);
            else h.n = float3(0.0, 0.0, -stp.y);
            return h;
        }
        if (tfloor <= texit) {
            h.kind = 2;
            h.t = tfloor;
            h.n = float3(0.0, 1.0, 0.0);
            return h;
        }
        if (texit > MAX_T) return h;
        if (tmax.x < tmax.y) { cell.x += stp.x; tmax.x += tdelta.x; }
        else { cell.y += stp.y; tmax.y += tdelta.y; }
    }
    return h;
}

// The rounded edge, as shading: near an edge the normal turns round a quarter
// circle of EDGE_R toward the neighbouring face.
float3 rounded_normal(float3 p, Hit h) {
    float2 l = p.xz - h.cell;
    float dy = h.top - p.y;
    float2 e = clamp((abs(l) - (HALF_W - EDGE_R)) / EDGE_R, 0.0, 1.0);
    float uy = clamp((EDGE_R - dy) / EDGE_R, 0.0, 1.0);
    float2 s = float2(l.x < 0.0 ? -1.0 : 1.0, l.y < 0.0 ? -1.0 : 1.0);
    if (h.n.y > 0.5) {
        return normalize(float3(s.x * e.x, sqrt(max(1.0 - e.x * e.x - e.y * e.y, 0.0)), s.y * e.y));
    }
    if (abs(h.n.x) > 0.5) {
        return normalize(float3(h.n.x * sqrt(max(1.0 - uy * uy - e.y * e.y, 0.0)), uy, s.y * e.y));
    }
    return normalize(float3(s.x * e.x, uy, h.n.z * sqrt(max(1.0 - uy * uy - e.x * e.x, 0.0))));
}

// --- light leaking from below ------------------------------------------------

// The leak at junction j (a cell corner) at time t: x = brightness, y = radius.
// Three families of junctions run their event slots a third of a period apart,
// so the slots' boundaries do not pulse the whole field at once; targets holds
// the camera target at the start of each family's current slot.
float2 leak(float2 j, float t, float3 targets[3]) {
    float fam = floor(hash2(j + float2(41.0, 11.0)) * 3.0);
    int fi = int(fam);
    float offset = fam / 3.0;
    float k = floor(t / LEAK_PERIOD + offset);
    float start = (k - offset) * LEAK_PERIOD;
    float3 h = hash3(float3(j, k));
    float2 d = j - targets[fi].xz;
    float rate = LEAK_RATE * (LEAK_BASE + LEAK_NEAR * exp(-dot(d, d) / (2.0 * LEAK_NEAR_R * LEAK_NEAR_R)));
    if (h.x > rate * LEAK_PERIOD) return float2(0.0, 1.0);
    float3 g = hash3(float3(j + 7.3, k + 1.7));
    float dur = 3.0 + 5.0 * h.y;
    float u = (t - start - (LEAK_PERIOD - dur) * h.z) / dur;
    if (u <= 0.0 || u >= 1.0) return float2(0.0, 1.0);
    float rise = sin(u / 0.3 * 0.5 * PI);
    float env = u < 0.3 ? rise * rise : pow(1.0 - (u - 0.3) / 0.7, 1.6);
    float flick = 0.9 + 0.1 * sin(t * 7.3 + j.x * 3.1);
    return float2(env * (0.5 + 0.7 * g.x) * LEAK_POWER * flick, 0.5 + 0.9 * g.y);
}

// --- shading -----------------------------------------------------------------

// A soft studio in place of the prototype's room environment: a dark gradient
// and a few emissive panels that widen with roughness.
float3 environment(float3 d, float rough) {
    float w = 0.15 + rough;
    float3 c = lerp(float3(0.02, 0.025, 0.03), float3(0.45, 0.47, 0.5), smoothstep(-0.1, 1.0, d.y));
    c += float3(3.0, 3.0, 3.0) * smoothstep(1.0 - 0.25 * w, 1.0, d.y);                            // ceiling panel
    c += float3(2.0, 2.0, 2.0) * smoothstep(1.0 - 0.3 * w, 1.0, dot(d, normalize(float3(-0.7, 0.4, 0.5))));
    c += float3(1.6, 1.6, 1.6) * smoothstep(1.0 - 0.3 * w, 1.0, dot(d, normalize(float3(0.8, 0.3, -0.4))));
    return c;
}

float ggx(float3 n, float3 v, float3 l, float rough) {
    float3 hv = normalize(v + l);
    float nh = max(dot(n, hv), 0.0), nl = max(dot(n, l), 0.0), nv = max(dot(n, v), 1e-3);
    float a = rough * rough, a2 = a * a;
    float dd = nh * nh * (a2 - 1.0) + 1.0;
    float D = a2 / (PI * dd * dd);
    float k = a * 0.5;
    float G = nl / (nl * (1.0 - k) + k) * nv / (nv * (1.0 - k) + k);
    return D * G / (4.0 * nv + 1e-4);
}

float3 fresnel(float3 f0, float c) {
    return f0 + (1.0 - f0) * pow(1.0 - c, 5.0);
}

float3 shade_column(float3 p, float3 n, float3 rd, Hit h, float t, float3 glow,
                                  float3 targets[3]) {
    float3 v = -rd;
    float3 f0 = lerp(float3(0.04, 0.04, 0.04), ALBEDO, METAL);
    float3 diff = ALBEDO * (1.0 - METAL);
    float nv = max(dot(n, v), 0.0);
    float3 key = normalize(float3(-6.0, 10.0, 4.0));
    float nl = max(dot(n, key), 0.0);
    float3 col = (diff / PI + fresnel(f0, max(dot(normalize(v + key), v), 0.0)) * ggx(n, v, key, ROUGH))
               * KEY_COL * nl * PI;
    col += diff * lerp(float3(0.0, 0.0, 0.0), SKY_COL, 0.5 + 0.5 * n.y);
    col += environment(reflect(rd, n), ROUGH) * fresnel(f0, nv) * ENV_INT;
    // The leaks below light the sides that face their gap. Only the junctions
    // of this column and the ring round it can reach, and only sides see them.
    if (n.y < 0.7) {
        for (int jz = -1; jz <= 2; jz++) {
            for (int jx = -1; jx <= 2; jx++) {
                float2 j = h.cell + float2(float(jx) - 0.5, float(jz) - 0.5);
                float2 lk = leak(j, t, targets);
                if (lk.x <= 0.0) continue;
                float3 lp = float3(j.x, h.top - 0.9, j.y);
                float3 dl = lp - p;
                float dist = length(dl);
                float att = max(1.0 - dist / LEAK_RANGE, 0.0);
                if (att <= 0.0) continue;
                float3 l = dl / dist;
                float lnl = max(dot(n, l), 0.0);
                float3 spec = fresnel(f0, max(dot(normalize(v + l), v), 0.0)) * ggx(n, v, l, ROUGH);
                col += (diff / PI + spec) * glow * lk.x * LEAK_LIGHT * att * att * lnl;
            }
        }
    }
    return col;
}

float3 floor_glow(float2 x, float t, float3 glow, float3 targets[3]) {
    float g = 0.0;
    float2 c = floor(x) + 0.5;                    // the junction lattice is at half-integers
    for (int jz = -2; jz <= 2; jz++) {
        for (int jx = -2; jx <= 2; jx++) {
            float2 j = c + float2(float(jx), float(jz));
            float2 lk = leak(j, t, targets);
            if (lk.x <= 0.0) continue;
            float2 d = x - j;
            g += lk.x * exp(-dot(d, d) / (lk.y * lk.y));
        }
    }
    return glow * (g * 3.2 + 0.035);
}

// --- the distance: haze, a faint glow, dust ---------------------------------

float vnoise(float3 x) {
    float3 i = floor(x), f = frac(x);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash2(i.xy + 37.0 * i.z), b = hash2(i.xy + float2(1, 0) + 37.0 * i.z);
    float c = hash2(i.xy + float2(0, 1) + 37.0 * i.z), d = hash2(i.xy + float2(1, 1) + 37.0 * i.z);
    float e = hash2(i.xy + 37.0 * (i.z + 1.0)), g = hash2(i.xy + float2(1, 0) + 37.0 * (i.z + 1.0));
    float k = hash2(i.xy + float2(0, 1) + 37.0 * (i.z + 1.0)), m = hash2(i.xy + float2(1, 1) + 37.0 * (i.z + 1.0));
    return lerp(lerp(lerp(a, b, f.x), lerp(c, d, f.x), f.y), lerp(lerp(e, g, f.x), lerp(k, m, f.x), f.y), f.z);
}

float fbm(float3 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 4; i++) {
        s += a * vnoise(p);
        p = p * 2.03 + float3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return s;
}

float3 sky(float3 d, float t, float3 fog, float3 glow) {
    float h = d.y;
    float3 top = fog * float3(0.154, 0.14, 0.174);
    float3 col = lerp(fog, top, smoothstep(0.0, 0.55, h));
    col = lerp(col, fog * 0.45, smoothstep(0.0, 0.4, -h));
    float band = exp(-h * h * 9.0);
    if (band > 0.02) {
        float n = fbm(d * float3(2.2, 7.0, 2.2) + float3(t * 0.012, 0.0, t * 0.008));
        col += fog * float3(2.6, 2.0, 1.75) * smoothstep(0.42, 0.85, n) * band * 0.55;
        float aur = fbm(d * float3(1.2, 3.0, 1.2) - float3(0.0, t * 0.006, t * 0.01));
        col += glow * 0.07 * smoothstep(0.5, 0.8, aur) * band * (0.6 + 0.4 * sin(t * 0.05 + d.x * 2.0));
    }
    return col;
}

// Fine motes in the air between the camera and what it sees: a few layers of
// hashed cells along the ray, each holding at most one mote that rises and sways.
float3 dust(float3 ro, float3 rd, float tmax, float t, float pxAng, float3 glow) {
    float3 sum = float3(0.0, 0.0, 0.0);
    for (int i = 0; i < 6; i++) {
        float d = 1.6 + 2.2 * float(i);
        if (d > tmax) break;
        float3 q = ro + rd * d;
        float3 drift = float3(0.6 * sin(t * 0.05 + float(i)), -0.05 * t, 0.6 * cos(t * 0.04 + float(i)));
        float3 g = (q + drift) * 0.9;
        float3 cell = floor(g);
        float3 h = hash3(cell + float(i) * 17.0);
        if (h.x > 0.35) continue;
        float3 mote = (cell + 0.2 + 0.6 * hash3(cell + 3.7)) / 0.9 - drift;
        if (mote.y < 1.2 || mote.y > 7.2) continue;
        float3 w = mote - ro;
        float along = dot(w, rd);
        if (along <= 0.0 || along > tmax) continue;
        float off = length(w - rd * along) / along;          // angle off the ray
        float size = pxAng * (1.2 + 1.5 * h.y) + 0.004 / along;
        float a = exp(-off * off / (size * size));
        float tw = 0.55 + 0.45 * sin(t * (0.8 + h.z * 1.8) + h.y * 40.0);
        sum += lerp(float3(0.55, 0.68, 0.85), glow, 0.5) * a * 0.05 * tw * exp(-pow(FOG_D * along, 2.0));
    }
    return sum;
}

float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float t = time;
    Cam cam = camera(t, resolution.x / resolution.y);
    float2 uv = float2(pos.x - 0.5 * resolution.x, 0.5 * resolution.y - pos.y) / resolution.y;
    float3 rd = normalize(uv.x * cam.rt + uv.y * cam.up + cam.focal * cam.fw);
    float pxAng = 1.0 / (resolution.y * cam.focal);
    // Taken as linear, like every prototype colour (see ALBEDO): the theme's
    // backdrop #0a1626 is then exactly the prototype's fog.
    float3 glow = ink.rgb;
    float3 fog = backdrop.rgb;
    float sw = swell(t);
    // The camera target at the start of each leak family's current slot.
    float3 targets[3];
    for (int f = 0; f < 3; f++) {
        float off = float(f) / 3.0;
        targets[f] = target_at((floor(t / LEAK_PERIOD + off) - off) * LEAK_PERIOD);
    }

    Hit h = trace(cam.ro, rd, 0.0, t, sw);
    float3 col;
    if (h.kind == 1) {
        float3 p = cam.ro + rd * h.t;
        col = shade_column(p, rounded_normal(p, h), rd, h, t, glow, targets);
    } else if (h.kind == 2) {
        float3 p = cam.ro + rd * h.t;
        col = floor_glow(p.xz, t, glow, targets);
        col = lerp(col, fog * 0.6, (1.0 - exp(-pow(FOG_D * h.t, 2.0))) * 0.85);
    } else {
        col = sky(rd, t, fog, glow);
    }
    if (h.kind == 1) col = lerp(col, fog, 1.0 - exp(-pow(FOG_D * h.t, 2.0)));
    col += dust(cam.ro, rd, h.t, t, pxAng, glow);
    // Linear HDR out: the lens blooms, tone-maps and caps it.
    return float4(max(col * EXPOSURE, 0.0), 1.0);
}
"""


#: The lens: bloom carries the glow of the leaks and the edge highlights.
LENS = Lens(bloom=0.9, threshold=0.55, vignette=0.12) if AVAILABLE else None


def _clamped(value, default: float, lo: float, hi: float) -> float:
    try:
        v = float(default if value is None else value)
    except (TypeError, ValueError):
        v = default
    return min(hi, max(lo, v))


def blocks_shader(leaks=None, leak_strength=None, motion=None, camera=None,
                  exposure=None, brightness=None) -> dict:
    """The ``Shader`` fields for the Blocks scene with a theme's options applied:
    ``leaks`` (how often light leaks, 0..3, 1 as tuned), ``leak_strength``
    (0..3), ``motion`` (how far the columns rise and fall, 0..2), ``camera``
    (camera speed, 0..3), ``exposure`` (0.1..4) and ``brightness`` (the
    picture's ceiling, 0..1, default 0.5). Bad values fall back to the defaults."""
    options = dict(leaks=repr(_clamped(leaks, 1.0, 0.0, 3.0)),
                   leak_strength=repr(_clamped(leak_strength, 1.0, 0.0, 3.0)),
                   motion=repr(_clamped(motion, 1.0, 0.0, 2.0)),
                   camera=repr(_clamped(camera, 1.0, 0.0, 3.0)),
                   # three.js's ACES divides the exposure by 0.6 before the curve
                   # the lens uses; 0.95 there is 1.58 here.
                   exposure=repr(_clamped(exposure, 1.58, 0.1, 4.0)))
    return {
        "source": _MSL_OPTIONS.format(**options) + BLOCKS_MSL_BODY,
        "source_hlsl": _HLSL_OPTIONS.format(**options) + BLOCKS_HLSL_BODY,
        "lens": replace(LENS, level=_clamped(brightness, DEFAULT_BRIGHTNESS, 0.0, 1.0)),
        "resolution_scale": RESOLUTION_SCALE,
        "idle": "freeze",
    }
