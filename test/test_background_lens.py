"""The lens the picture scenes are filmed through (xefm.background_lens).

The scenes' own tests (test_background_earth.py, test_background_blocks_crystal.py)
check what each scene asks of it; these check the lens on simple scenes —
tone mapping, bloom, the masks, the brightness ceiling, depth of field, and the
look cycle the shader runs from time and the seeds. Metal renders them
headless; the Direct3D twin compiles and draws the same chain where it can.

Run with: python -m pytest test/test_background_lens.py -v
"""

import unittest

import pytest

from puikit.background import Shader
from puikit.backends._metal import HAVE_METAL, MetalBackground

from xefm import background_lens as bl
from xefm.background_lens import Look, lens_shader, look_at, slot_hash

metal_only = pytest.mark.skipif(not HAVE_METAL, reason="Metal unavailable")

_BACKDROP = (10, 20, 30)

#: Linear HDR: a tiny, very bright disc on a dim field — what a lens is for.
SUN_MSL = """
fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float2 c = pos.xy - u.resolution * 0.5;
    return float4(float3(length(c) < 2.0 ? 400.0 : 0.05), 1.0);
}
"""

SUN_HLSL = """
float4 puikit_bg_fragment(float4 pos : SV_Position) : SV_Target {
    float2 c = pos.xy - resolution * 0.5;
    float v = length(c) < 2.0 ? 400.0 : 0.05;
    return float4(v, v, v, 1.0);
}
"""

#: Two flat halves at different depths (inverse depth in alpha): left near, right far.
DEPTH_MSL = """
fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    float stripe = fmod(floor(pos.y / 2.0), 2.0);
    float near = pos.x < u.resolution.x * 0.5 ? 1.0 : 0.0;
    return float4(float3(stripe * 0.6), mix(1.0 / 20.0, 1.0, near));
}
"""

#: Writes xefm_slot_hash(slot = pixel column, seed) into the colour channels.
#: Not lensed: it reaches the screen as the single pass, with the hash prepended.
HASH_MSL = bl.SLOT_HASH_MSL + """
fragment float4 puikit_bg_fragment(float4 pos [[position]],
                                   constant BackgroundUniforms &u [[buffer(0)]]) {
    uint h = xefm_slot_hash(int(pos.x), u.seed);
    return float4(float(h & 255u), float((h >> 8) & 255u), float((h >> 24) & 255u), 255.0)
         / 255.0;
}
"""


def _rgb(px, width, x, y):
    i = (y * width + x) * 4
    return (px[i + 2], px[i + 1], px[i])


def _render(looks, source=SUN_MSL, w=200, h=120, t=1.0, fade=1.0, seed=0.0, seed_prev=None,
            seed_mix=1.0, backdrop=_BACKDROP, **cycle):
    r = MetalBackground()
    fields = lens_shader(source, "", looks, **cycle)
    assert r.set_shader(Shader(backdrop=backdrop, **fields)), r.error
    return MetalBackground.texture_pixels(
        r.render_to_texture(w, h, t, fade, seed=seed, seed_prev=seed_prev, seed_mix=seed_mix))


class Looks(unittest.TestCase):

    def test_tints_and_matrix_are_normalized(self):
        look = Look(mono_tint=(0.5, 1), color_matrix=[1, 2, 3])
        self.assertEqual(look.mono_tint, (0.5, 1.0, 1.0))
        self.assertEqual(look.matrix_rows, ((1.0, 2.0, 3.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
        self.assertEqual(Look().matrix_rows[1], (0.0, 1.0, 0.0))

    def test_a_zero_threshold_cannot_bloom_black(self):
        self.assertGreater(Look(threshold=0.0).threshold, 0.0)

    def test_level_and_dof_are_clamped(self):
        self.assertEqual((Look(level=2.0).level, Look(level=-1).level), (1.0, 0.0))
        self.assertEqual(Look(dof=1.0).dof, 0.1)

    def test_every_field_reaches_the_table(self):
        # The shader reads a look as LOOK_ROWS float4s; each field has a place.
        rows = bl._look_rows(Look())
        self.assertEqual(len(rows), bl.LOOK_ROWS)
        flat = sum(map(tuple, rows), ())
        for name in bl.LOOK_FIELDS:
            if name == "color_matrix":
                continue
            value = getattr(Look(), name)
            for v in value if isinstance(value, tuple) else (value,):
                self.assertIn(v, flat, name)

    def test_the_hash_spreads(self):
        self.assertEqual(len({slot_hash(k, 123) % 10 for k in range(60)}), 10)

    def test_a_cycle_holds_a_look_then_blends_to_the_next(self):
        looks = (Look(bloom=0.0), Look(bloom=1.0), Look(bloom=0.5))
        seed = next(s for s in range(100) if slot_hash(0, s) % 3 != slot_hash(1, s) % 3)
        a, b = looks[slot_hash(0, seed) % 3], looks[slot_hash(1, seed) % 3]
        bloom = lambda t: look_at(looks, 40.0, 10.0, t, seed)[2]
        self.assertEqual((bloom(5.0), bloom(29.9)), (a.bloom, a.bloom))
        self.assertTrue(min(a.bloom, b.bloom) < bloom(35.0) < max(a.bloom, b.bloom))
        self.assertEqual(bloom(40.0), b.bloom)


class Graph(unittest.TestCase):

    def test_the_chain_holds_together(self):
        from puikit.backends import _bg_graph
        for looks in (Look(), (Look(), Look(streak=1.0))):
            plan = _bg_graph.plan(Shader(**lens_shader("", "", looks)))
            self.assertIsNone(plan.error)
            self.assertEqual(plan.frame[0].entry, bl.SCENE_ENTRY)
            self.assertEqual(plan.frame[-1].entry, "lens_composite")

    def test_the_streak_passes_are_left_out_unless_a_look_has_one(self):
        def entries(looks):
            return [p.entry for p in lens_shader("", "", looks)["passes"]]
        self.assertNotIn("lens_streak", entries(Look()))
        self.assertEqual(entries((Look(), Look(streak=1.0))).count("lens_streak"),
                         len(bl.STREAK_STEPS))

    def test_the_pyramid_halves(self):
        targets = {t.name: t for t in lens_shader("", "", Look())["targets"]}
        self.assertEqual(targets["down0"].extent(1920, 1080), (960, 540, 1))
        self.assertEqual(targets["down5"].extent(1920, 1080), (30, 16, 1))

    def test_both_dialects_carry_the_same_table(self):
        import re
        fields = lens_shader("", "", (Look(), Look(grain=0.3)), period=12.0, transition=3.0)
        nums = lambda s: re.findall(r"LENS_\w+ = ([^;]+);", s)
        self.assertEqual(nums(fields["source"]), nums(fields["source_hlsl"]))
        table = lambda s: s[s.index("LENS_LOOKS"):s.index("};", s.index("LENS_LOOKS"))]
        self.assertEqual(table(fields["source"]).split("{", 1)[1],
                         table(fields["source_hlsl"]).split("{", 1)[1])


@metal_only
class Rendering(unittest.TestCase):

    def test_hdr_is_tone_mapped_not_clipped_flat(self):
        px = _render(Look(bloom=0.0, vignette=0.0))
        # The 400x sun saturates to white; the 0.05 field maps to a dim grey well
        # above black — HDR in, display colour out.
        self.assertEqual(_rgb(px, 200, 100, 60), (255, 255, 255))
        self.assertTrue(30 < _rgb(px, 200, 10, 10)[0] < 90)

    def test_bloom_spreads_the_sun(self):
        plain = _render(Look(bloom=0.0, vignette=0.0))
        bloomed = _render(Look(bloom=1.0, vignette=0.0))
        self.assertGreater(_rgb(bloomed, 200, 115, 60)[0], _rgb(plain, 200, 115, 60)[0] + 5)

    def test_every_feature_draws_without_nan(self):
        # NaN reaches an 8-bit target as black; a frame with every feature on must
        # still show the bright sun and a lit field near it.
        px = _render(Look(streak=1, ghosts=1, scanlines=1, grain=0.5, distortion=0.2,
                          aberration=0.01, halation=1,
                          color_matrix=(0.1, 1.3, -0.5, 1, 0, 0, 0, 0, 1)))
        self.assertGreater(sum(_rgb(px, 200, 100, 60)), 600)
        self.assertGreater(sum(_rgb(px, 200, 120, 60)), 0)

    def test_masks_reach_black_then_the_mix_over_the_backdrop(self):
        self.assertEqual(_rgb(_render(Look(scope=1.0)), 200, 2, 2), (0, 0, 0))

    def test_zero_fade_is_the_bare_backdrop(self):
        px = _render(Look(), fade=0.0)
        self.assertEqual({_rgb(px, 200, x, y) for x in range(0, 200, 7) for y in range(0, 120, 7)},
                         {_BACKDROP})

    def test_level_caps_the_brightest_pixel(self):
        px = _render(Look(bloom=1.0, level=0.5), backdrop=(0, 0, 0))
        self.assertLessEqual(max(max(px[i:i + 3]) for i in range(0, len(px), 4)), 128)

    def test_what_is_in_focus_stays_sharp_and_the_rest_blurs(self):
        # Focus is pulled to the middle of the frame, which sits on the boundary;
        # sample well inside each half: the stripes survive where the depth
        # matches the focus and wash out where it does not.
        def render(dof):
            return _render(Look(dof=dof, bloom=0.0, vignette=0.0), source=DEPTH_MSL,
                           w=120, h=80, backdrop=(0, 0, 0))
        sharp, blurred = render(0.0), render(0.05)
        def contrast(px, x):
            col = [_rgb(px, 120, x, y)[0] for y in range(20, 60)]
            return max(col) - min(col)
        self.assertGreater(contrast(sharp, 100), 60)
        self.assertTrue(contrast(blurred, 100) < contrast(sharp, 100) / 2
                        or contrast(blurred, 20) < contrast(sharp, 20) / 2)


@metal_only
class CycleOnTheGpu(unittest.TestCase):
    """The look cycle runs in the shader; Python's look_at says what it should pick."""

    LOOKS = (Look(bloom=0.0, vignette=0.0), Look(saturation=0.0, gain=3.0, vignette=0.0),
             Look(bloom=1.0, scope=1.0))

    def test_the_gpu_hash_matches_python(self):
        r = MetalBackground()
        self.assertTrue(r.set_shader(Shader(source=HASH_MSL)), r.error)
        for seed in (0.0, 1.0, 40321.0, 65535.0):
            px = MetalBackground.texture_pixels(r.render_to_texture(64, 1, 0.0, seed=seed))
            for x in range(64):
                h = slot_hash(x, seed)
                self.assertEqual(_rgb(px, 64, x, 0), (h & 255, (h >> 8) & 255, (h >> 24) & 255))

    def test_each_period_shows_the_look_its_slot_hashes_to(self):
        for seed in (1.0, 2.0, 3.0, 4.0):
            for t in (1.0, 11.0, 21.0):
                k = int(t // 10.0)
                want = self.LOOKS[slot_hash(k, seed) % len(self.LOOKS)]
                self.assertEqual(
                    _render(self.LOOKS, w=64, h=40, t=t, seed=seed, period=10.0, transition=2.0),
                    _render(want, w=64, h=40, t=t, seed=seed), (seed, t))

    def test_a_reseed_blends_from_the_old_seeds_look(self):
        a, b = next((x, y) for x in range(50) for y in range(50)
                    if slot_hash(0, x) % 3 == 0 and slot_hash(0, y) % 3 == 1)
        cycle = dict(period=40.0, transition=1.0)
        old = _render(self.LOOKS, w=64, h=40, t=5.0, seed=b, seed_prev=a, seed_mix=0.0, **cycle)
        new = _render(self.LOOKS, w=64, h=40, t=5.0, seed=b, seed_prev=a, seed_mix=1.0, **cycle)
        mid = _render(self.LOOKS, w=64, h=40, t=5.0, seed=b, seed_prev=a, seed_mix=0.5, **cycle)
        self.assertEqual(old, _render(self.LOOKS[0], w=64, h=40, t=5.0))
        self.assertEqual(new, _render(self.LOOKS[1], w=64, h=40, t=5.0))
        self.assertNotIn(mid, (old, new))


class Direct3D(unittest.TestCase):
    """The HLSL twin compiles and draws where Direct3D is (the Windows VM)."""

    def test_the_hlsl_chain_draws(self):
        try:
            from puikit.backends._d3d_shader import HAVE_D3D_SHADER, D3DShaderBackground
        except (ImportError, OSError, AttributeError):
            self.skipTest("Direct3D unavailable")
        if not HAVE_D3D_SHADER:
            self.skipTest("Direct3D unavailable")
        for look in (Look(bloom=1.0), (Look(streak=1, ghosts=1, scanlines=1), Look(dof=0.05))):
            r = D3DShaderBackground()
            self.assertTrue(r.set_shader(Shader(backdrop=_BACKDROP,
                                                **lens_shader("", SUN_HLSL, look))), r.error)
            px = r.render_pixels(200, 120, 1.0)
            r.close()
            self.assertEqual(_rgb(px, 200, 100, 60), (255, 255, 255))
            self.assertGreater(_rgb(px, 200, 10, 10)[0], 20)


if __name__ == "__main__":
    unittest.main()
