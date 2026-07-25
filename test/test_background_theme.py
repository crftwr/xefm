"""A theme's background (animation / wallpaper) resolves and rides in extras.

Themes may carry a background behind the UI of two content kinds — an ``animation``
(a shader scene) or a ``wallpaper`` image — else the plain theme color (solid). XeFM
resolves the theme's choice into a puikit ``Shader`` / ``Wallpaper`` descriptor
and pushes it on theme switch. The content keys are ``animation`` / ``wallpaper``
because the ``background`` key is the base *color*; guarding that collision is the
key regression here. Pure resolver + a theme-builder check — no app, no window.
"""

import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from puikit.background import Shader, Wallpaper  # noqa: E402
from xefm.background_shaders import SHADER_KINDS  # noqa: E402


_COLOR = (10, 20, 30)
_BACKDROP = (1, 2, 3)


def _resolve(animation=None, wallpaper=None):
    return xefm_app._resolve_background(animation, wallpaper, color=_COLOR, backdrop=_BACKDROP)


class ResolveBackground(unittest.TestCase):
    def test_solid_is_none(self):
        self.assertIsNone(_resolve())

    def test_animation_type_string(self):
        bg = _resolve(animation="rain")
        self.assertIsInstance(bg, Shader)
        self.assertEqual(bg.speed, 0.6)           # tuned default
        self.assertEqual(bg.ink, _COLOR)          # theme fg fills the ink uniform
        self.assertEqual(bg.backdrop, _BACKDROP)  # theme bg filled in

    def test_animation_true_is_the_tuned_default(self):
        # An unnamed animation gets XeFM's default scene.
        self.assertIn(xefm_app._ANIM_DEFAULT_KIND, SHADER_KINDS)
        self.assertIsInstance(_resolve(animation=True), Shader)

    def test_animation_params_dict(self):
        bg = _resolve(animation={"type": "rain", "speed": 1.5})
        self.assertIsInstance(bg, Shader)
        self.assertEqual(bg.speed, 1.5)

    def test_wallpaper_string_and_dict(self):
        self.assertEqual(_resolve(wallpaper="~/p.png").image, "~/p.png")
        bg = _resolve(wallpaper={"image": "~/p.png", "fit": "center"})
        self.assertIsInstance(bg, Wallpaper)
        self.assertEqual((bg.image, bg.fit, bg.backdrop), ("~/p.png", "center", _BACKDROP))

    def test_passthrough_descriptors(self):
        made = Shader(source="fragment float4 puikit_bg_fragment() { return 0; }")
        self.assertIs(_resolve(animation=made), made)
        wp = Wallpaper(image="x")
        self.assertIs(_resolve(wallpaper=wp), wp)

    def test_bad_input_degrades_gracefully(self):
        # A wallpaper dict with no image resolves to solid (None), not a crash.
        self.assertIsNone(_resolve(wallpaper={"fit": "fill"}))
        # A truthy animation with no type yields the default scene.
        self.assertIsInstance(_resolve(animation=True), Shader)
        # A name that is not one of XeFM's scenes degrades to solid: a scene *is* a
        # shader now, so there is nothing else for it to resolve to.
        self.assertIsNone(_resolve(animation="snow"))


class ThemeCarriesBackground(unittest.TestCase):
    def _base(self, **extra):
        return dict(bg=(4, 15, 7), fg=(51, 245, 121), muted=(33, 138, 74),
                    accent=(60, 235, 122), surface=(11, 38, 20), selection=(24, 105, 54),
                    **extra)

    def test_animation_in_extras(self):
        t = xefm_app._theme(**self._base(animation="rain"))
        self.assertIsInstance(t.extras.get("background"), Shader)

    def test_no_background_has_none(self):
        self.assertIsNone(xefm_app._theme(**self._base()).extras.get("background"))

    def test_config_color_and_content_do_not_collide(self):
        # The regression: config 'background' is the base color; 'animation' picks
        # the content. Both must survive — the color must not be eaten by the
        # content key, nor the content dropped.
        cfg = types.SimpleNamespace(THEMES={"Phosphor": {
            "background": (4, 15, 7), "animation": "rain", "opacity": 1.0,
            "foreground": (51, 245, 121), "muted": (33, 138, 74),
            "accent": (60, 235, 122), "surface": (11, 38, 20), "selection": (24, 105, 54)}})
        themes = dict(xefm_app._build_theme_list(cfg))
        t = themes["Phosphor"]
        self.assertEqual(t.surfaces.get("content"), (4, 15, 7))          # color kept
        self.assertIsInstance(t.extras.get("background"), Shader)          # content kept

    def test_config_wallpaper_key(self):
        cfg = types.SimpleNamespace(THEMES={"Pic": {
            "base": "Dark+", "wallpaper": "~/bg.png"}})
        t = dict(xefm_app._build_theme_list(cfg))["Pic"]
        self.assertIsInstance(t.extras.get("background"), Wallpaper)


if __name__ == "__main__":
    unittest.main()
