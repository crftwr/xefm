"""XeFM's GPU background shaders: the registry, how a theme resolves one, and that
each shader actually compiles and draws.

The compile/draw tests use puikit's offscreen Metal path, so the real fragment
shader is built by the real Metal compiler with no window involved. They skip
where Metal is unavailable.

Run with: python -m pytest test/test_background_shaders.py -v
"""

import re
import unittest

import pytest

from puikit.background import SHADER_ENTRY, Shader
from puikit.backends._metal import HAVE_METAL, MetalBackground

try:
    from puikit.backends._d3d_shader import (
        HAVE_D3D_SHADER, SHADER_ENTRY as HLSL_ENTRY, D3DShaderBackground,
    )
except (ImportError, AttributeError):
    # puikit's D3D module pulls in Windows-only ctypes bindings (``WinDLL``,
    # ``WINFUNCTYPE``) at module scope, so off Windows it is not importable at all
    # rather than merely reporting itself unsupported. Same outcome either way —
    # no D3D here, the @d3d_only tests skip — but without this the whole file fails
    # to collect and the Metal half stops running too. The HLSL entry-point name is
    # shared with Metal, so the dialect checks that do not need a GPU still work.
    HAVE_D3D_SHADER = False
    HLSL_ENTRY = SHADER_ENTRY
    D3DShaderBackground = None

from xefm import app as xefm_app
from xefm.background_shaders import SHADER_KINDS

metal_only = pytest.mark.skipif(not HAVE_METAL, reason="Metal unavailable")
d3d_only = pytest.mark.skipif(not HAVE_D3D_SHADER, reason="D3D shader support unavailable")

_INK, _BACKDROP = (200, 224, 245), (16, 30, 50)


def _shader(kind):
    return Shader(ink=_INK, backdrop=_BACKDROP, **SHADER_KINDS[kind])


class Registry(unittest.TestCase):

    def test_expected_shaders_are_offered(self):
        self.assertEqual(set(SHADER_KINDS),
                         {"wave", "rain", "starfield", "grid", "constellation",
                          "datastream", "hologram"})

    def test_each_entry_is_valid_shader_kwargs(self):
        # The dict is splatted straight into Shader(...), so a stray key would
        # only show up as a TypeError at theme-apply time.
        for kind, params in SHADER_KINDS.items():
            self.assertIn("source", params, kind)
            Shader(**params)

    def test_sources_define_the_entry_point(self):
        for kind, params in SHADER_KINDS.items():
            self.assertIn(SHADER_ENTRY, params["source"], kind)

    def test_every_scene_dissolves_when_idle(self):
        # The backend parks an animated background after ~a minute of no input.
        # What it comes to rest *as* is the scene's call, and every scene XeFM ships
        # is nothing but motion — rain falling, stars streaming, a corridor being
        # flown through — so the frame a freeze would leave behind is not a picture
        # of anything, just wherever the objects happened to be. They fade out
        # instead. A scene composed to be looked at still may say "freeze"; it would
        # be the first, so this asserts the current answer rather than a rule.
        for kind, params in SHADER_KINDS.items():
            self.assertEqual(params.get("idle"), "fade", kind)
            self.assertTrue(Shader(**params).fades_when_idle, kind)

    def test_every_scene_ships_an_hlsl_translation(self):
        # A shader is the one backend-specific part of a background: macOS compiles
        # ``source`` (MSL), Windows compiles ``source_hlsl`` (HLSL). A scene missing
        # the HLSL twin would silently draw nothing on Windows.
        for kind, params in SHADER_KINDS.items():
            self.assertIn("source_hlsl", params, kind)
            self.assertIn(HLSL_ENTRY, params["source_hlsl"], kind)

    def test_every_scene_ships_a_glsl_translation(self):
        # The web (WebGL) backend compiles ``source_glsl``; a scene missing it draws
        # nothing on web.
        for kind, params in SHADER_KINDS.items():
            self.assertIn("source_glsl", params, kind)
            self.assertIn(SHADER_ENTRY, params["source_glsl"], kind)

    def test_glsl_is_regenerated_from_msl(self):
        # ``source_glsl`` is a mechanical transpile of the MSL (tools/
        # generate_shader_glsl.py), not hand-maintained. Re-transpiling must match
        # the committed GLSL, so tuning the MSL without regenerating is caught here.
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        from generate_shader_glsl import transpile  # noqa: E402
        from xefm import background_shaders as mod
        for name in ("WAVE", "RAIN", "STARFIELD", "GRID", "CONSTELLATION",
                     "DATASTREAM", "HOLOGRAM"):
            expected = transpile(getattr(mod, name + "_MSL"))
            self.assertEqual(getattr(mod, name + "_GLSL"), expected,
                             f"{name}_GLSL is stale — run tools/generate_shader_glsl.py")


class DialectParity(unittest.TestCase):
    """Every scene ships the same maths twice, in two languages, and no compiler
    cross-checks them. Tuning one dialect and forgetting the other is the mistake
    this arrangement invites, and it surfaces only as "Windows looks different" —
    long after the change. Comparing the tunables as text catches it here, with no
    GPU involved, so it runs on any machine."""

    #: ``constant float NAME = 1.0;`` (MSL) and its ``static const`` HLSL twin.
    _MSL = re.compile(r"constant\s+(?:int|uint|float)\s+(\w+)\s*=\s*([^;]+);")
    _HLSL = re.compile(r"static\s+const\s+(?:int|uint|float)\s+(\w+)\s*=\s*([^;]+);")

    @staticmethod
    def _consts(pattern, source):
        return {name: value.strip() for name, value in pattern.findall(source)}

    def test_every_msl_tunable_has_an_hlsl_twin(self):
        # MSL is the canonical side. HLSL may add dialect-only helpers (the hash
        # constants, which MSL inlines), so the check is one-directional.
        for kind, params in SHADER_KINDS.items():
            missing = set(self._consts(self._MSL, params["source"])) - set(
                self._consts(self._HLSL, params["source_hlsl"]))
            self.assertFalse(missing, f"{kind}: tunables absent from HLSL: {sorted(missing)}")

    def test_shared_tunables_hold_the_same_value(self):
        for kind, params in SHADER_KINDS.items():
            msl = self._consts(self._MSL, params["source"])
            hlsl = self._consts(self._HLSL, params["source_hlsl"])
            shared = sorted(set(msl) & set(hlsl))
            self.assertTrue(shared, f"{kind}: no tunables found to compare")
            for name in shared:
                self.assertEqual(float(msl[name]), float(hlsl[name]),
                                 f"{kind}: {name} drifted between MSL and HLSL")


class ThemeResolution(unittest.TestCase):
    """A theme names a scene; XeFM picks the descriptor its renderer needs."""

    def _resolve(self, animation):
        return xefm_app._resolve_background(animation, None, color=_INK, backdrop=_BACKDROP)

    def test_a_shader_name_resolves_to_a_shader(self):
        bg = self._resolve("wave")
        self.assertIsInstance(bg, Shader)
        self.assertEqual(bg.ink, _INK)         # theme fg arrives as the ink uniform
        self.assertEqual(bg.backdrop, _BACKDROP)

    def test_a_non_xefm_name_degrades_to_solid(self):
        # A scene *is* a shader, so a name absent from SHADER_KINDS has nowhere to
        # resolve to and yields no background rather than an error.
        self.assertIsNone(self._resolve("cube"))

    def test_tuned_defaults_apply_to_shaders_too(self):
        bg = self._resolve("wave")
        self.assertEqual((bg.speed, bg.opacity),
                         (xefm_app._ANIM_DEFAULTS["speed"], xefm_app._ANIM_DEFAULTS["opacity"]))

    def test_params_dict_overrides_carry_through(self):
        bg = self._resolve({"type": "wave", "speed": 1.4, "opacity": 0.9})
        self.assertIsInstance(bg, Shader)
        self.assertEqual((bg.speed, bg.opacity), (1.4, 0.9))

    def test_scene_owned_fields_are_not_theme_overridable(self):
        # resolution_scale is a property of the scene (how much sharpness it can
        # give up), not of the theme, so it comes from the registry either way.
        bg = self._resolve({"type": "wave", "speed": 2.0})
        self.assertEqual(bg.resolution_scale, SHADER_KINDS["wave"]["resolution_scale"])

    def test_an_unknown_name_does_not_crash_startup(self):
        # A config typo must cost the scene, not the app.
        self.assertIsNone(self._resolve("no-such-scene"))


@metal_only
class Compilation(unittest.TestCase):
    """Every shipped shader must build with the real Metal compiler."""

    def test_every_shader_compiles(self):
        renderer = MetalBackground()
        for kind in SHADER_KINDS:
            ok = renderer.set_shader(_shader(kind))
            self.assertTrue(ok, f"{kind} failed to compile:\n{renderer.error}")

    def test_every_shader_draws_something(self):
        renderer = MetalBackground()
        for kind in SHADER_KINDS:
            self.assertTrue(renderer.set_shader(_shader(kind)), renderer.error)
            px = MetalBackground.texture_pixels(
                renderer.render_to_texture(160, 100, 3.0))
            distinct = {bytes(px[i:i + 4]) for i in range(0, len(px), 4)}
            self.assertGreater(len(distinct), 8, f"{kind} drew a flat frame")

    def test_every_shader_animates(self):
        for kind in SHADER_KINDS:
            renderer = MetalBackground()
            self.assertTrue(renderer.set_shader(_shader(kind)), renderer.error)
            a = MetalBackground.texture_pixels(renderer.render_to_texture(160, 100, 0.0))
            b = MetalBackground.texture_pixels(renderer.render_to_texture(160, 100, 3.0))
            self.assertNotEqual(bytes(a), bytes(b), f"{kind} is a still frame")

    def test_every_shader_is_frozen_at_zero_speed(self):
        # speed scales the time uniform, so 0 must stop the scene dead. A scene that
        # read a clock of its own instead would keep moving here.
        for kind in SHADER_KINDS:
            renderer = MetalBackground()
            frozen = Shader(speed=0.0, ink=_INK, backdrop=_BACKDROP, **SHADER_KINDS[kind])
            self.assertTrue(renderer.set_shader(frozen), renderer.error)
            a = MetalBackground.texture_pixels(renderer.render_to_texture(120, 80, 0.0))
            b = MetalBackground.texture_pixels(renderer.render_to_texture(120, 80, 9.0))
            self.assertEqual(bytes(a), bytes(b), f"{kind} moved at speed 0")

    def test_every_shader_follows_the_theme_ink(self):
        # Scenes are anchored on the theme foreground rather than fixed colours, so
        # a different palette must produce a visibly different frame.
        for kind in SHADER_KINDS:
            renderer = MetalBackground()
            self.assertTrue(renderer.set_shader(
                Shader(ink=(200, 224, 245), backdrop=_BACKDROP, **SHADER_KINDS[kind])))
            blue = MetalBackground.texture_pixels(renderer.render_to_texture(120, 80, 2.0))
            self.assertTrue(renderer.set_shader(
                Shader(ink=(51, 245, 121), backdrop=_BACKDROP, **SHADER_KINDS[kind])))
            green = MetalBackground.texture_pixels(renderer.render_to_texture(120, 80, 2.0))
            self.assertNotEqual(bytes(blue), bytes(green), f"{kind} ignores the ink")

    def test_every_shader_stays_a_backdrop(self):
        # These sit behind a working file manager, so the theme background has to
        # remain the *dominant* colour of the frame. A scene that covered most of the
        # window would compete with the filenames on top of it.
        #
        # Measured at a realistic window size on purpose: line widths are set in
        # pixels, so at the 160x100 the tests elsewhere use, the grid's 1.1px rails
        # are a far larger share of the frame than they ever are in use.
        for kind in SHADER_KINDS:
            renderer = MetalBackground()
            self.assertTrue(renderer.set_shader(_shader(kind)), renderer.error)
            px = MetalBackground.texture_pixels(renderer.render_to_texture(400, 260, 2.0))
            near_backdrop = sum(
                1 for i in range(0, len(px), 4)
                if all(abs(a - b) <= 3 for a, b in
                       zip((px[i + 2], px[i + 1], px[i]), _BACKDROP)))
            self.assertGreater(near_backdrop, (len(px) // 4) * 0.5,
                               f"{kind} covers more than half the window")

    def test_every_shader_vanishes_at_zero_fade(self):
        # What makes the idle fade-out work, and the one thing it needs from the
        # scenes: the backend dissolves a parked scene by scaling the opacity
        # uniform to zero, so at zero every scene must leave the *bare backdrop* —
        # not a dimmed version of itself. A scene that added its colour rather than
        # mixing over the backdrop would park on a visible ghost.
        for kind in SHADER_KINDS:
            renderer = MetalBackground()
            self.assertTrue(renderer.set_shader(_shader(kind)), renderer.error)
            px = MetalBackground.texture_pixels(
                renderer.render_to_texture(160, 100, 2.0, 0.0))
            off = [i for i in range(0, len(px), 4)
                   if any(abs(a - b) > 1 for a, b in
                          zip((px[i + 2], px[i + 1], px[i]), _BACKDROP))]
            self.assertEqual(off, [], f"{kind} still shows at zero fade")


@d3d_only
class CompilationD3D(unittest.TestCase):
    """Every shipped shader must also build with the real HLSL (Direct3D 11)
    compiler — the Windows twin of the Metal Compilation tests."""

    def test_every_shader_compiles(self):
        renderer = D3DShaderBackground()
        for kind in SHADER_KINDS:
            ok = renderer.set_shader(_shader(kind))
            self.assertTrue(ok, f"{kind} failed to compile:\n{renderer.error}")
        renderer.close()

    def test_every_shader_draws_something(self):
        renderer = D3DShaderBackground()
        for kind in SHADER_KINDS:
            self.assertTrue(renderer.set_shader(_shader(kind)), renderer.error)
            px = renderer.render_pixels(160, 100, 3.0)
            distinct = {bytes(px[i:i + 4]) for i in range(0, len(px), 4)}
            self.assertGreater(len(distinct), 8, f"{kind} drew a flat frame")
        renderer.close()

    def test_every_shader_animates(self):
        renderer = D3DShaderBackground()
        for kind in SHADER_KINDS:
            self.assertTrue(renderer.set_shader(_shader(kind)), renderer.error)
            a = renderer.render_pixels(160, 100, 0.0)
            b = renderer.render_pixels(160, 100, 3.0)
            self.assertNotEqual(bytes(a), bytes(b), f"{kind} is a still frame")
        renderer.close()

    def test_every_shader_stays_a_backdrop(self):
        renderer = D3DShaderBackground()
        for kind in SHADER_KINDS:
            self.assertTrue(renderer.set_shader(_shader(kind)), renderer.error)
            px = renderer.render_pixels(400, 260, 2.0)   # see the Metal twin
            near_backdrop = sum(
                1 for i in range(0, len(px), 4)
                if all(abs(a - b) <= 3 for a, b in
                       zip((px[i + 2], px[i + 1], px[i]), _BACKDROP)))
            self.assertGreater(near_backdrop, (len(px) // 4) * 0.5,
                               f"{kind} covers more than half the window")
        renderer.close()

    def test_every_shader_vanishes_at_zero_fade(self):
        renderer = D3DShaderBackground()
        for kind in SHADER_KINDS:
            self.assertTrue(renderer.set_shader(_shader(kind)), renderer.error)
            px = renderer.render_pixels(160, 100, 2.0, 0.0)   # see the Metal twin
            off = [i for i in range(0, len(px), 4)
                   if any(abs(a - b) > 1 for a, b in
                          zip((px[i + 2], px[i + 1], px[i]), _BACKDROP))]
            self.assertEqual(off, [], f"{kind} still shows at zero fade")
        renderer.close()


if __name__ == "__main__":
    unittest.main()
