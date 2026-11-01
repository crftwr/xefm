"""The Blocks and Crystal background scenes: their options, the closed forms
that keep them stateless, and what they draw.

The promises every background makes (compiles, animates, freezes at speed 0,
vanishes at zero fade, follows the ink) are in test_background_shaders.py.

Run with: python -m pytest test/test_background_blocks_crystal.py -v
"""

import math
import re
import unittest

import pytest

from puikit.background import Lens, Shader, ShaderVolume
from puikit.backends._metal import HAVE_METAL, MetalBackground

from xefm import app as xefm_app
from xefm import background_blocks as blocks
from xefm import background_crystal as crystal

metal_only = pytest.mark.skipif(not HAVE_METAL, reason="Metal unavailable")


def _consts(source):
    return dict(re.findall(r"(?:constant|static const)\s+(?:int|float)\s+(\w+)\s*=\s*([^;]+);",
                           source))


class BlocksMotion(unittest.TestCase):
    """The prototype integrated each column's speed every frame. The port
    replaces that with closed forms; these check they integrate what they say."""

    @staticmethod
    def _surge_integral(t, a, b):
        # The shader's surge_integral, in Python.
        psi = 0.5 * (a * t + b - 0.5 * math.pi)
        f = (924 * psi + 792 * math.sin(2 * psi) + 247.5 * math.sin(4 * psi)
             + 73.3333 * math.sin(6 * psi) + 16.5 * math.sin(8 * psi) + 2.4 * math.sin(10 * psi)
             + 0.166667 * math.sin(12 * psi))
        return f / 4096 * 2 / a

    def test_the_surge_integral_integrates_s_to_the_sixth(self):
        for a, b in ((0.05, 0.3), (0.12, 4.0), (0.17, 2.2)):
            for t in (0.0, 13.0, 77.7, 400.0):
                h = 1e-3
                speed = (self._surge_integral(t + h, a, b) - self._surge_integral(t - h, a, b)) / (2 * h)
                s = 0.5 + 0.5 * math.sin(a * t + b)
                self.assertAlmostEqual(speed, s ** 6, places=4)

    def test_columns_are_mostly_slow_with_occasional_surges(self):
        # The motion crftwr asked for: speed = SLOW + SURGE s^6 is near its floor
        # most of the time and well above it only briefly.
        body = _consts(blocks.BLOCKS_MSL_BODY)
        slow, surge = float(body["SLOW"]), float(body["SURGE"])
        speeds = [slow + surge * (0.5 + 0.5 * math.sin(0.1 * t)) ** 6 for t in range(0, 6283)]
        quick = sum(1 for v in speeds if v > 0.5 * (slow + surge)) / len(speeds)
        self.assertLess(quick, 0.25)
        self.assertGreater(max(speeds), 10 * min(speeds))

    def test_the_swell_integrates_its_rate(self):
        def swell(t):
            s2 = 0.375 * t - 0.5 * math.cos(0.07 * t) / 0.07 - 0.125 * math.sin(0.14 * t) / 0.14
            return 0.3 * (0.35 * t + 1.3 * s2)
        for t in (0.0, 30.0, 100.0):
            h = 1e-3
            rate = (swell(t + h) - swell(t - h)) / (2 * h)
            want = 0.3 * (0.35 + 1.3 * (0.5 + 0.5 * math.sin(0.07 * t)) ** 2)
            self.assertAlmostEqual(rate, want, places=5)


class Options(unittest.TestCase):

    def test_blocks_options_are_baked_and_clamped(self):
        fields = blocks.blocks_shader(leaks=9, motion=-1, camera="fast")
        consts = _consts(fields["source"])
        self.assertEqual(float(consts["LEAK_RATE"]), 3.0)
        self.assertEqual(float(consts["BOB"]), 0.0)
        self.assertEqual(float(consts["CAM_SPEED"]), 1.0)
        self.assertEqual(fields["lens"].level, blocks.DEFAULT_BRIGHTNESS)
        self.assertEqual(fields["idle"], "freeze")

    def test_crystal_brings_its_volume_lens_and_frame_rate(self):
        fields = crystal.crystal_shader(brightness=0.8, focus=0)
        self.assertEqual(fields["volumes"], (ShaderVolume(crystal.VOLUME_SIZE),))
        self.assertEqual(fields["lens"].level, 0.8)
        self.assertEqual(fields["lens"].dof, 0.0)                 # focus 0 turns it off
        self.assertGreater(crystal.crystal_shader()["lens"].dof, 0.0)
        self.assertEqual(fields["frame_rate"], crystal.FRAME_RATE)
        self.assertIn("puikit_bg_bake", fields["source"])
        self.assertIn("puikit_bg_bake", fields["source_hlsl"])

    def test_dialects_share_their_constants_and_tables(self):
        pattern = r"(?:constant|static const)\s+(?:float[234]?|int)\s+(\w+)\[\d+\]\s*=\s*\{([^}]*)\}"
        for msl, hlsl in ((blocks.blocks_shader()["source"], blocks.blocks_shader()["source_hlsl"]),
                          (crystal.crystal_shader()["source"], crystal.crystal_shader()["source_hlsl"])):
            a, b = dict(re.findall(pattern, msl)), dict(re.findall(pattern, hlsl))
            self.assertTrue(a)
            self.assertEqual(a, b)

    def test_the_crystal_layout_is_twelve_leaning_crystals(self):
        layout = crystal.crystal_layout()
        self.assertEqual(len(layout), 12)
        for pos, rows, size in layout:
            # World-to-local is a rotation: orthonormal rows.
            for i in range(3):
                for j in range(3):
                    d = sum(rows[i][k] * rows[j][k] for k in range(3))
                    self.assertAlmostEqual(d, 1.0 if i == j else 0.0, places=6)
            self.assertGreater(pos[1], 0.0)                          # on the rock top
            self.assertLess(size[0], 0.06)                           # small: the approved size

    def test_the_themes_are_built_in(self):
        themes = dict(xefm_app.THEMES)
        for name, kind in (("Blocks", blocks), ("Crystal", crystal)):
            bg = themes[name].extras["background"]
            self.assertIsInstance(bg, Shader, name)
            self.assertIsInstance(bg.lens, Lens, name)


@metal_only
class Rendering(unittest.TestCase):

    def _frame(self, fields, t=20.0, ink=(99, 214, 255), backdrop=(10, 22, 38), w=160, h=100):
        r = MetalBackground()
        self.assertTrue(r.set_shader(Shader(ink=ink, backdrop=backdrop, **fields)), r.error)
        return MetalBackground.texture_pixels(r.render_to_texture(w, h, t))

    def test_both_scenes_draw_pictures_under_the_ceiling(self):
        for fields in (blocks.blocks_shader(), crystal.crystal_shader()):
            px = self._frame(fields)
            distinct = {bytes(px[i:i + 3]) for i in range(0, len(px), 4)}
            self.assertGreater(len(distinct), 200)
            self.assertLessEqual(max(px[i] for i in range(len(px)) if i % 4 != 3), 128)

    def test_the_crystal_glass_follows_the_ink(self):
        fields = crystal.crystal_shader(brightness=1.0)
        cyan = self._frame(fields, ink=(88, 199, 222), backdrop=(21, 24, 27))
        amber = self._frame(fields, ink=(222, 150, 60), backdrop=(21, 24, 27))
        self.assertNotEqual(bytes(cyan), bytes(amber))

    def test_the_crystal_depth_of_field_blurs(self):
        sharp = self._frame(crystal.crystal_shader(focus=0, brightness=1.0), w=200, h=125)
        soft = self._frame(crystal.crystal_shader(brightness=1.0), w=200, h=125)
        def detail(px, w=200):
            return sum(abs(px[i] - px[i + 4]) for i in range(0, len(px) - 4, 4) if (i // 4) % w != w - 1)
        self.assertGreater(detail(sharp), detail(soft) * 1.1)


if __name__ == "__main__":
    unittest.main()
