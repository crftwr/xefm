"""The Earth background scene: its options, its assets, and what it draws.

The scene-wide promises every background makes (compiles, animates, freezes at
speed 0, vanishes at zero fade) are in test_background_shaders.py, which covers
``earth`` with the rest. These are the ones only this scene makes — it is a
picture, built from textures and a lens, driven by time alone.

Run with: python -m pytest test/test_background_earth.py -v
"""

import re
import unittest
from dataclasses import replace

import pytest

from puikit import _platform_image
from puikit.background import Lens, LensCycle, Shader, slot_hash
from puikit.backends._metal import HAVE_METAL, MetalBackground

from xefm import app as xefm_app
from xefm import background_earth as earth
from xefm.background_shaders import SCENE_OPTIONS, SHADER_KINDS

metal_only = pytest.mark.skipif(not HAVE_METAL, reason="Metal unavailable")

_BACKDROP = (6, 10, 20)


def _capped(lens, level=earth.DEFAULT_BRIGHTNESS):
    """A preset as the scene uses it: under its brightness ceiling."""
    return replace(lens, level=level)


def _consts(source):
    return dict(re.findall(r"(?:constant|static const)\s+(?:int|float)\s+(\w+)\s*=\s*([^;]+);",
                           source))


class Options(unittest.TestCase):

    def test_defaults_pick_shots_and_lenses_at_random(self):
        fields = earth.earth_shader()
        consts = _consts(fields["source"])
        self.assertEqual(consts["SHOT"].strip(), "-1")
        self.assertIsInstance(fields["lens"], LensCycle)
        self.assertEqual(fields["lens"].looks, tuple(map(_capped, earth.LENSES.values())))
        self.assertEqual(int(consts["LENS_COUNT"]), len(earth.LENSES))
        # The camera and the look change together.
        self.assertEqual(float(consts["SHOT_SECONDS"]), fields["lens"].period)
        self.assertEqual(float(consts["TRANSITION"]), fields["lens"].transition)
        self.assertEqual(fields["idle"], "freeze")
        self.assertEqual(fields["textures"], earth.TEXTURES)

    def test_there_are_hundreds_of_scenes(self):
        variants = int(_consts(earth.EARTH_MSL_BODY)["VARIANTS"])
        self.assertGreaterEqual(len(earth.SHOTS) * variants * len(earth.LENSES), 300)

    def test_a_named_shot_is_held(self):
        for i, name in enumerate(earth.SHOTS):
            for dialect in ("source", "source_hlsl"):
                consts = _consts(earth.earth_shader(shot=name)[dialect])
                self.assertEqual(consts["SHOT"].strip(), str(i), (name, dialect))

    def test_an_unknown_shot_cycles(self):
        self.assertEqual(_consts(earth.earth_shader(shot="moon")["source"])["SHOT"].strip(), "-1")

    def test_lens_by_name_by_dict_by_list_and_fallback(self):
        fixed = earth.earth_shader(lens="Film")
        self.assertEqual(fixed["lens"], _capped(earth.LENSES["film"]))
        self.assertEqual(_consts(fixed["source"])["LENS_COUNT"].strip(), "1")
        tuned = earth.earth_shader(lens={"preset": "film", "grain": 0.0})["lens"]
        self.assertEqual(tuned.grain, 0.0)
        self.assertEqual(tuned.halation, earth.LENSES["film"].halation)
        some = earth.earth_shader(lens=["film", "nope", "crt"])
        self.assertEqual(some["lens"].looks,
                         (_capped(earth.LENSES["film"]), _capped(earth.LENSES["crt"])))
        self.assertEqual(_consts(some["source"])["LENS_COUNT"].strip(), "2")
        # The scene cannot be shown without a lens, so nothing bad leaves it lensless.
        for bad in ("no-such-lens", {"no_such_field": 1}, 42, []):
            self.assertIsInstance(earth.earth_shader(lens=bad)["lens"], (Lens, LensCycle), bad)

    def test_numbers_are_clamped_and_bad_ones_default(self):
        consts = _consts(earth.earth_shader(clouds=99, exposure="bright")["source"])
        self.assertEqual(float(consts["CLOUD_H"]), 8.0)
        self.assertEqual(float(consts["EXPOSURE"]), earth.DEFAULT_EXPOSURE)

    def test_brightness_is_the_ceiling_of_every_look(self):
        self.assertEqual({l.level for l in earth.earth_shader()["lens"].looks}, {0.5})
        self.assertEqual(earth.earth_shader(lens="film", brightness=0.8)["lens"].level, 0.8)
        self.assertEqual(earth.earth_shader(lens="film", brightness=7)["lens"].level, 1.0)

    def test_dialects_bake_the_same_options(self):
        fields = earth.earth_shader(shot="rise", clouds=1.5, exposure=0.7)
        msl, hlsl = _consts(fields["source"]), _consts(fields["source_hlsl"])
        for name in ("SHOT", "CLOUD_H", "EXPOSURE", "LENS_COUNT", "SHOT_SECONDS",
                     "TRANSITION"):
            self.assertEqual(float(msl[name]), float(hlsl[name]), name)

    def test_shot_tables_match_between_dialects(self):
        # The parity test in test_background_shaders compares scalars; the shot
        # table is arrays, and drifting one of those is the same hazard.
        pattern = r"(?:constant|static const)\s+(?:int|float)\s+(\w+)\[\d+\]\s*=\s*\{([^}]*)\}"
        msl = dict(re.findall(pattern, earth.EARTH_MSL_BODY))
        hlsl = dict(re.findall(pattern, earth.EARTH_HLSL_BODY))
        self.assertTrue(msl)
        self.assertEqual(set(msl), set(hlsl))
        for name in msl:
            self.assertEqual([float(v) for v in msl[name].split(",")],
                             [float(v) for v in hlsl[name].split(",")], name)

    def test_every_shot_name_has_a_table_column(self):
        lon = re.search(r"SHOT_LON\[(\d+)\]", earth.EARTH_MSL_BODY)
        self.assertEqual(int(lon.group(1)), len(earth.SHOTS))


class ThemeResolution(unittest.TestCase):

    def _resolve(self, animation):
        return xefm_app._resolve_background(animation, None, color=(200, 200, 200),
                                            backdrop=_BACKDROP)

    def test_scene_options_reach_the_shader(self):
        bg = self._resolve({"type": "earth", "shot": "leo", "lens": "crt", "speed": 0.5})
        self.assertIsInstance(bg, Shader)
        self.assertEqual(bg.lens, _capped(earth.LENSES["crt"]))
        self.assertEqual(_consts(bg.source)["SHOT"].strip(), str(earth.SHOTS.index("leo")))
        self.assertEqual(bg.speed, 0.5)

    def test_the_bare_name_uses_the_registry_defaults(self):
        bg = self._resolve("earth")
        self.assertEqual(bg.source, SHADER_KINDS["earth"]["source"])
        self.assertEqual(bg.lens, SHADER_KINDS["earth"]["lens"])

    def test_options_of_one_scene_do_not_leak_into_another(self):
        # ``lens`` means nothing to the wave; it is ignored, not an error.
        bg = self._resolve({"type": "wave", "lens": "crt"})
        self.assertIsNone(bg.lens)
        self.assertEqual(SCENE_OPTIONS["earth"][0], earth.OPTIONS)

    def test_the_earth_theme_is_built_in(self):
        names = [name for name, _theme in xefm_app.THEMES]
        self.assertIn("Earth", names)
        theme = dict(xefm_app.THEMES)["Earth"]
        bg = theme.extras["background"]
        self.assertIsInstance(bg, Shader)
        self.assertIsNotNone(bg.lens)
        self.assertEqual(bg.backdrop, (6, 10, 20))     # mixed over the theme navy


class Assets(unittest.TestCase):

    def test_every_texture_ships_and_decodes(self):
        for tex in earth.TEXTURES:
            path = tex.path
            self.assertTrue(earth.Path(path).is_file(), path)
            if _platform_image.extensions():           # an OS decoder to ask
                raster = _platform_image.decode(path)
                self.assertIsNotNone(raster, path)
                self.assertEqual(raster.width, raster.height * 2, path)   # equirectangular

    def test_the_sources_are_credited(self):
        notes = (earth.ASSET_DIR / "SOURCES.md").read_text(encoding="utf-8")
        self.assertIn("NASA", notes)


@metal_only
class Rendering(unittest.TestCase):

    def _frame(self, fields, elapsed=5.0, ink=(200, 224, 245), w=160, h=100, seed=0.0):
        r = MetalBackground()
        self.assertTrue(r.set_shader(Shader(ink=ink, backdrop=_BACKDROP, **fields)), r.error)
        return MetalBackground.texture_pixels(r.render_to_texture(w, h, elapsed, seed=seed))

    def test_every_shot_draws_a_picture(self):
        for name in earth.SHOTS:
            px = self._frame(earth.earth_shader(shot=name))
            distinct = {bytes(px[i:i + 3]) for i in range(0, len(px), 4)}
            self.assertGreater(len(distinct), 200, f"{name} drew a flat frame")

    def test_every_lens_draws(self):
        for name in earth.LENSES:
            px = self._frame(earth.earth_shader(shot="rise", lens=name))
            self.assertGreater(max(px[i] for i in range(0, len(px), 4)), 40, name)

    def test_the_scene_ignores_ink(self):
        # Physically coloured, by decision: the planet does not take the palette's hue.
        fields = earth.earth_shader(shot="day")
        self.assertEqual(bytes(self._frame(fields, ink=(200, 224, 245))),
                         bytes(self._frame(fields, ink=(51, 245, 121))))

    @staticmethod
    def _disc(px, w=160):
        """Centroid and area of the lit planet — the pixels well above the sky."""
        xs, ys = [], []
        for i in range(0, len(px), 4):
            if px[i] + px[i + 1] + px[i + 2] > 240:
                xs.append((i // 4) % w)
                ys.append((i // 4) // w)
        n = max(len(xs), 1)
        return sum(xs) / n, sum(ys) / n, len(xs)

    @staticmethod
    def _shot(slot, seed, lenses=len(earth.LENSES)):
        """The shot the scene picks for ``slot`` — see ``camera`` in the shader."""
        return (slot_hash(slot, seed) // lenses) % len(earth.SHOTS)

    def test_auto_moves_to_the_next_scene(self):
        # Pure function of time: one scene in a slot, another a period on.
        fields = earth.earth_shader(lens="clean")
        seed = next(s for s in range(200)
                    if {self._shot(0, s, 1), self._shot(1, s, 1)} == {0, 2})   # day, crescent
        a = self._disc(self._frame(fields, 5.0, seed=seed))
        b = self._disc(self._frame(fields, 5.0 + earth.SHOT_SECONDS, seed=seed))
        self.assertGreater(abs(a[2] - b[2]), a[2] // 3 + b[2] // 3, "the scene did not change")

    def test_a_new_seed_is_a_new_scene(self):
        # What the backend's reseed on launch and on wake turns into: the same
        # moment of the clock shows a different scene.
        fields = earth.earth_shader(lens="clean")
        seed = next(s for s in range(1, 200) if self._shot(0, s, 1) != self._shot(0, 0, 1))
        self.assertNotEqual(self._disc(self._frame(fields, 5.0, seed=0.0)),
                            self._disc(self._frame(fields, 5.0, seed=seed)))

    def test_a_held_shot_drifts_slowly(self):
        # Every scene moves: a held shot keeps its subject, but over half a minute
        # the camera has visibly moved — slowly, nothing like a cut.
        fields = earth.earth_shader(shot="day", lens="clean")
        a = self._disc(self._frame(fields, 5.0))
        b = self._disc(self._frame(fields, 35.0))
        moved = abs(a[2] - b[2]) / a[2] + (abs(a[0] - b[0]) + abs(a[1] - b[1])) / 160
        self.assertGreater(moved, 0.05)
        self.assertLess(moved, 0.5)

    def test_no_pixel_passes_half_white(self):
        # Whatever the shot and the look — the sunlit disc, the glint, the
        # night-vision gain — file names never sit on more than half white.
        for shot in ("day", "glint", "rise"):
            for lens in ("clean", "night-vision", "flare"):
                px = self._frame(earth.earth_shader(shot=shot, lens=lens))
                brightest = max(max(px[i], px[i + 1], px[i + 2]) for i in range(0, len(px), 4))
                self.assertLessEqual(brightest, 128, (shot, lens))

    def test_exposure_scales_the_picture(self):
        dim = self._frame(earth.earth_shader(shot="day", exposure=0.3))
        bright = self._frame(earth.earth_shader(shot="day", exposure=2.0))
        self.assertGreater(sum(bright[0::4]), sum(dim[0::4]) * 1.3)


if __name__ == "__main__":
    unittest.main()
