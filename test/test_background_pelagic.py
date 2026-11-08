"""The Pelagic background scene: its options, the closed forms that keep it
stateless, its two dialects, and what it draws.

The promises every background makes (compiles, animates, freezes at speed 0,
vanishes at zero fade, freezes when idle) are in test_background_shaders.py.

Run with: python -m pytest test/test_background_pelagic.py -v
"""

import dataclasses
import math
import re
import time
import unittest

import pytest

from puikit.background import Shader
from puikit.backends._metal import HAVE_METAL, MetalBackground

try:
    from puikit.backends._d3d_shader import HAVE_D3D_SHADER, D3DShaderBackground
except (ImportError, AttributeError):   # Windows-only ctypes at module scope
    HAVE_D3D_SHADER = False
    D3DShaderBackground = None

from xefm import app as xefm_app
from xefm import background_pelagic as pelagic

metal_only = pytest.mark.skipif(not HAVE_METAL, reason="Metal unavailable")
d3d_only = pytest.mark.skipif(not HAVE_D3D_SHADER, reason="D3D shader support unavailable")


def _consts(source):
    return dict(re.findall(r"(?:constant|static const)\s+(?:int|float)\s+(\w+)\s*=\s*([^;]+);",
                           source))


class Options(unittest.TestCase):

    def test_options_are_baked_and_clamped(self):
        fields = pelagic.pelagic_shader(jellyfish=9, exposure="bright", brightness=2)
        for src in (fields["source"], fields["source_hlsl"]):
            consts = _consts(src)
            self.assertEqual(int(consts["JELLYFISH"]), 6)
            self.assertEqual(float(consts["EXPOSURE"]), pelagic.DEFAULT_EXPOSURE)
        self.assertEqual(int(_consts(pelagic.pelagic_shader(jellyfish=-2)["source"])["JELLYFISH"]), 0)
        self.assertEqual(int(_consts(pelagic.pelagic_shader(jellyfish=2.6)["source"])["JELLYFISH"]), 3)
        self.assertEqual(pelagic.pelagic_look(brightness=2).level, 1.0)
        self.assertEqual(pelagic.pelagic_look().level, pelagic.DEFAULT_BRIGHTNESS)
        self.assertEqual(pelagic.pelagic_look(brightness=float("nan")).level,
                         pelagic.DEFAULT_BRIGHTNESS)

    def test_scene_fields(self):
        fields = pelagic.pelagic_shader()
        self.assertEqual(fields["idle"], "fade")   # in part: see Rendering
        self.assertEqual(fields["frame_rate"], pelagic.FRAME_RATE)
        self.assertEqual(fields["resolution_scale"], pelagic.RESOLUTION_SCALE)
        self.assertEqual(fields["pixel_density"], pelagic.PIXEL_DENSITY)
        self.assertEqual(fields["passes"][-1].entry, "lens_composite")
        self.assertNotIn("textures", fields)   # nothing to decode, nothing to bake

    def test_python_constants_match_the_shader(self):
        consts = _consts(pelagic.pelagic_shader()["source"])
        self.assertEqual(float(consts["START"]), pelagic.START)
        self.assertEqual(float(consts["TURTLE_P"]), pelagic.TURTLE_PERIOD)
        self.assertEqual(float(consts["TURTLE_D"]), pelagic.TURTLE_DURATION)
        self.assertEqual(float(consts["TURTLE_T0"]), pelagic.TURTLE_FIRST)

    def test_dialects_share_their_tables(self):
        pattern = r"(?:constant|static const)\s+(?:float[234]?|int)\s+(\w+)(?:\[\d+\])?\s*=\s*(\{[^}]*\}|float\d\([^;]*\));"
        fields = pelagic.pelagic_shader()
        a, b = dict(re.findall(pattern, fields["source"])), dict(re.findall(pattern, fields["source_hlsl"]))
        for name in ("SWELL", "SUN_AIR", "SUN_W", "SIG_TEAL", "SIG_BLUE", "HI_TEAL", "HI_BLUE",
                     "SAND", "CORAL", "CEN"):
            self.assertIn(name, a)
            self.assertEqual(a[name], b[name], name)

    def test_the_hlsl_is_spelled_for_hlsl(self):
        body = pelagic.source("hlsl")
        for token in (r"\bconstant ", r"static inline", r"\[\[", r"\bfract\(", r"\bmix\(",
                      r"\bF3\(", r"\bCONST ", r"\bLOOP ", r"\bUNROLL "):
            self.assertNotRegex(body, token)
        self.assertIn("[loop]", body)
        msl = pelagic.source("msl")
        for token in (r"static const", r"\[loop\]", r"\bfrac\(", r"\blerp\(", r"\bF3\(",
                      r"\bCONST "):
            self.assertNotRegex(msl, token)

    def test_no_pow_of_a_signed_square(self):
        # pow() of a negative base is NaN in HLSL and in Metal's fast math; the
        # prototype squared signed values with pow(x, 2.0).
        self.assertNotRegex(pelagic.BODY, r"pow\([^;]*,\s*2\.0\)")

    def test_the_swell_table_has_unit_directions(self):
        for dx, dz, k, a in pelagic.swell_table():
            self.assertAlmostEqual(math.hypot(dx, dz), 1.0, places=12)
            self.assertGreater(k, 0.0)
            self.assertGreater(a, 0.0)

    def test_the_sun_is_refracted_under_water(self):
        air, water = pelagic.sun_vectors()
        # about 30 degrees above the horizon in air, steeper (about 50) under water
        self.assertAlmostEqual(math.degrees(math.asin(air[1])), 30.0, delta=2.0)
        self.assertAlmostEqual(math.degrees(math.asin(water[1])), 50.0, delta=3.0)
        self.assertAlmostEqual(sum(c * c for c in water), 1.0, places=9)

    def test_the_turtle_passes_in_its_slots(self):
        self.assertFalse(pelagic.turtle_on(pelagic.START))
        self.assertTrue(pelagic.turtle_on(162.0))
        self.assertFalse(pelagic.turtle_on(200.0))
        self.assertTrue(pelagic.turtle_on(162.0 + 3 * pelagic.TURTLE_PERIOD))
        # its period is the camera's tilt period, so speed never unlocks them
        self.assertAlmostEqual(pelagic.TURTLE_PERIOD, 2 * math.pi / 0.029, delta=0.01)
        share = sum(pelagic.turtle_on(t * 0.5) for t in range(0, 20000)) / 20000
        self.assertAlmostEqual(share, pelagic.TURTLE_DURATION / pelagic.TURTLE_PERIOD, delta=0.02)

    def test_the_camera_looks_slightly_up(self):
        # Snell's window (above 41.4 degrees) in the top of the frame nearly all
        # the time, and the floor along the bottom most of it: the camera's
        # closed form, with the shader's own constants.
        c = {k: float(v) for k, v in _consts(pelagic.pelagic_shader()["source"]).items()
             if k in ("TILT_MID", "TILT_AMP", "FOCAL")}
        half = math.degrees(math.atan(1.0 / c["FOCAL"]))
        pitches = []
        for i in range(2000):
            t = i * 0.5
            th, r = 0.6 + 0.021 * t, 10.0 + 2.2 * math.sin(0.031 * t)
            ro = (r * math.cos(th), -10.0 + 0.9 * math.sin(0.047 * t), r * math.sin(th))
            ta = (3.0 * math.sin(0.037 * t + 1.0), -9.0 + c["TILT_MID"] + c["TILT_AMP"] * math.sin(0.029 * t),
                  3.0 * math.cos(0.041 * t))
            d = [a - b for a, b in zip(ta, ro)]
            pitches.append(math.degrees(math.asin(d[1] / math.sqrt(sum(x * x for x in d)))))
        self.assertGreater(min(pitches), 0.0)                                   # never looks down
        self.assertGreater(sum(p + half >= 41.4 for p in pitches) / len(pitches), 0.9)
        self.assertGreater(sum(p - half <= -10.0 for p in pitches) / len(pitches), 0.8)

    def test_the_theme_is_built_in(self):
        bg = dict(xefm_app.THEMES)["Pelagic"].extras["background"]
        self.assertIsInstance(bg, Shader)
        self.assertEqual(bg.passes[-1].entry, "lens_composite")
        self.assertEqual(bg.speed, 1.0)


@metal_only
class Rendering(unittest.TestCase):

    def _frame(self, fields, t, ink=(88, 199, 222), backdrop=(3, 22, 26), w=160, h=100):
        """Scene time ``t`` (the shader adds START to the backend's clock)."""
        r = MetalBackground()
        self.assertTrue(r.set_shader(Shader(ink=ink, backdrop=backdrop, **fields)), r.error)
        return MetalBackground.texture_pixels(r.render_to_texture(w, h, t - pelagic.START))

    def test_draws_a_picture_under_the_ceiling(self):
        for brightness in (0.5, pelagic.DEFAULT_BRIGHTNESS):
            px = self._frame(pelagic.pelagic_shader(brightness=brightness), 95.0)
            distinct = {bytes(px[i:i + 3]) for i in range(0, len(px), 4)}
            self.assertGreater(len(distinct), 200)
            top = max(px[i] for i in range(len(px)) if i % 4 != 3)
            self.assertLessEqual(top, math.ceil(255 * brightness))

    def test_the_scene_ignores_ink(self):
        fields = pelagic.pelagic_shader()
        self.assertEqual(bytes(self._frame(fields, 95.0, ink=(88, 199, 222))),
                         bytes(self._frame(fields, 95.0, ink=(255, 60, 60))))

    def test_the_jellyfish_option_draws_them(self):
        with_ = self._frame(pelagic.pelagic_shader(jellyfish=6), 95.0)
        without = self._frame(pelagic.pelagic_shader(jellyfish=0), 95.0)
        self.assertNotEqual(bytes(with_), bytes(without))

    def _px(self, fields, t, fade=1.0, w=160, h=100):
        r = MetalBackground()
        self.assertTrue(r.set_shader(Shader(ink=(88, 199, 222), backdrop=(3, 22, 26), **fields)), r.error)
        return MetalBackground.texture_pixels(r.render_to_texture(w, h, t - pelagic.START, fade))

    def test_idle_fades_the_jellyfish_and_surface_but_keeps_the_water(self):
        fields = pelagic.pelagic_shader()
        gone = self._px(fields, 95.0, fade=0.0)
        # still a picture over the backdrop, not the bare backdrop ...
        self.assertGreater(len({bytes(gone[i:i + 3]) for i in range(0, len(gone), 4)}), 50)
        # ... and at zero, exactly the scene with no jellyfish and no surface:
        # the same frame whether it had jellyfish or not
        none = self._px(pelagic.pelagic_shader(jellyfish=0), 95.0, fade=0.0)
        # (to within float noise: the two compile differently)
        self.assertLessEqual(max(abs(x - y) for x, y in zip(gone, none)), 2)
        # halfway is between the two
        half = self._px(fields, 95.0, fade=0.5)
        full = self._px(fields, 95.0, fade=1.0)
        self.assertNotEqual(bytes(half), bytes(full))
        self.assertNotEqual(bytes(half), bytes(gone))

    def test_the_water_and_floor_change_colour_slowly(self):
        # Half a hue cycle on, the water is bluer: less green against blue.
        def ratio(px):
            g = sum(px[i + 1] for i in range(0, len(px), 4))
            b = sum(px[i] for i in range(0, len(px), 4))
            return g / b
        fields = pelagic.pelagic_shader(jellyfish=0, brightness=1.0)
        teal = self._px(fields, pelagic.START)
        blue = self._px(fields, pelagic.START + math.pi / 0.0123)
        self.assertGreater(ratio(teal), ratio(blue) * 1.08)
        # A second later, almost nothing has changed colour.
        later = self._px(fields, pelagic.START + 1.0)
        self.assertLess(abs(ratio(teal) - ratio(later)), 0.01)

    def test_the_turtle_appears_only_inside_its_pass(self):
        # The same scene with the turtle's first pass moved far away: identical
        # outside the pass, different during it.
        def fields(moved):
            f = pelagic.pelagic_shader(jellyfish=0)
            if moved:
                for key in ("source", "source_hlsl"):
                    f[key] = re.sub(r"(float TURTLE_T0 = )132\.5", r"\g<1>100000.5", f[key])
            return f
        size = dict(w=320, h=180)
        self.assertEqual(bytes(self._frame(fields(False), 110.0, **size)),
                         bytes(self._frame(fields(True), 110.0, **size)))
        self.assertNotEqual(bytes(self._frame(fields(False), 162.0, **size)),
                            bytes(self._frame(fields(True), 162.0, **size)))



@d3d_only
@pytest.mark.timeout(300)
class RenderingD3D(unittest.TestCase):
    """The HLSL spelling, through fxc: it compiles, and draws a moving picture.
    Its own test, so a failure in another scene cannot hide this one."""

    def test_compiles_draws_and_moves(self):
        r = D3DShaderBackground()
        fields = pelagic.pelagic_shader(brightness=1.0)
        start = time.monotonic()
        ok = r.set_shader(Shader(ink=(88, 199, 222), backdrop=(3, 22, 26), **fields))
        print(f"pelagic: D3DCompile + set_shader {time.monotonic() - start:.1f} s")
        self.assertTrue(ok, r.error)
        a = r.render_pixels(320, 180, 95.0 - pelagic.START)
        self.assertGreater(len({bytes(a[i:i + 3]) for i in range(0, len(a), 4)}), 200)
        uncapped = dataclasses.replace(Shader(ink=(88, 199, 222), backdrop=(3, 22, 26), **fields),
                                       frame_rate=0.0)
        self.assertTrue(r.set_shader(uncapped), r.error)
        b = r.render_pixels(320, 180, 98.0 - pelagic.START)
        self.assertNotEqual(bytes(a), bytes(b))
        r.close()


if __name__ == "__main__":
    unittest.main()
