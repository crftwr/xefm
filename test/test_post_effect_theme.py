"""A theme's recommended post effect is pushed to the backend on theme switch.

Themes may carry a ``post_effect`` recommendation (a CRT/phosphor look); XeFM
applies it to the backend when the theme becomes active and clears it when you
switch to a theme without one. A terminal backend inherits a no-op, so this
never branches on the backend. Runs headless on the ``memory`` backend, mirroring
``test_xefm_app_theme_persistence``.
"""

import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit import PostEffect  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


# --- pure resolver / theme-builder (no app) -----------------------------------

class ResolvePostEffect(unittest.TestCase):
    def test_named_preset(self):
        self.assertEqual(xefm_app._resolve_post_effect("crt").name, "crt")
        self.assertTrue(xefm_app._resolve_post_effect("crt").roll > 0)

    def test_name_is_case_and_space_insensitive(self):
        self.assertIsNotNone(xefm_app._resolve_post_effect("  CRT "))

    def test_unknown_preset_is_none(self):
        self.assertIsNone(xefm_app._resolve_post_effect("crt-tinted"))

    def test_params_dict(self):
        e = xefm_app._resolve_post_effect({"bloom": 0.5, "tint": (1, 2, 3)})
        self.assertEqual((e.bloom, e.tint), (0.5, (1, 2, 3)))

    def test_passthrough_and_empty(self):
        made = PostEffect(bloom=0.2)
        self.assertIs(xefm_app._resolve_post_effect(made), made)
        self.assertIsNone(xefm_app._resolve_post_effect(None))
        self.assertIsNone(xefm_app._resolve_post_effect(""))

    def test_bad_input_degrades_to_none(self):
        self.assertIsNone(xefm_app._resolve_post_effect("no-such-preset"))
        self.assertIsNone(xefm_app._resolve_post_effect({"totally": "wrong"}))

    def test_theme_carries_effect_in_extras(self):
        t = xefm_app._theme(bg=(0, 0, 0), fg=(0, 255, 0), muted=(0, 128, 0),
                       accent=(0, 200, 0), surface=(0, 30, 0), selection=(0, 80, 0),
                       post_effect="crt")
        self.assertIsInstance(t.extras.get("post_effect"), PostEffect)

    def test_theme_without_effect_has_none(self):
        t = xefm_app._theme(bg=(0, 0, 0), fg=(255, 255, 255), muted=(128, 128, 128),
                       accent=(0, 122, 204), surface=(48, 48, 52), selection=(10, 105, 178))
        self.assertIsNone(t.extras.get("post_effect"))

    def test_config_theme_override_flows_through(self):
        import types
        cfg = types.SimpleNamespace(THEMES={"Phosphor": {
            "post_effect": "crt", "background": (4, 15, 7), "foreground": (51, 245, 121),
            "muted": (33, 138, 74), "accent": (60, 235, 122), "surface": (11, 38, 20),
            "selection": (24, 105, 54)}})
        themes = dict(xefm_app._build_theme_list(cfg))
        self.assertEqual(themes["Phosphor"].extras["post_effect"].name, "crt")


class RetroBuiltinThemes(unittest.TestCase):
    """The built-in retro hardware themes are registered and each carries a
    screen-effect recommendation, so selecting one from View ▸ Theme applies its
    look on a pixel backend (and is ignored by a terminal)."""

    RETRO = ("Sci-Fi", "Segment LCD")

    def _by_name(self):
        return dict(xefm_app.THEMES)

    def test_all_registered_with_a_real_effect(self):
        themes = self._by_name()
        for name in self.RETRO:
            self.assertIn(name, themes, f"{name} missing from built-in THEMES")
            effect = themes[name].extras.get("post_effect")
            self.assertIsInstance(effect, PostEffect, name)
            self.assertFalse(effect.is_noop, f"{name} effect should do something")

    def test_sci_fi_glows_more_than_segment_lcd(self):
        # Sci-Fi is the emissive-HUD look; Segment LCD is a subtler backlit glow.
        by = self._by_name()
        self.assertGreater(by["Sci-Fi"].extras["post_effect"].glow,
                           by["Segment LCD"].extras["post_effect"].glow)

    def test_retro_themes_survive_a_config_rebuild(self):
        # They are built-ins, so they appear in the runtime list even with an empty
        # user config, and keep their effects.
        import types
        themes = dict(xefm_app._build_theme_list(types.SimpleNamespace()))
        for name in self.RETRO:
            self.assertIsInstance(themes[name].extras.get("post_effect"), PostEffect, name)


# --- integration: switching themes drives backend.set_post_effect --------------

class _FakeMonitor:
    def __init__(self, config, file_manager):
        self.reload_queue = file_manager.reload_queue

    def is_monitoring_enabled(self):
        return False

    def update_monitored_directory(self, *args):
        pass

    def stop_monitoring(self):
        pass


class ThemeSwitchAppliesEffect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.left = os.path.join(self.tmp, "l")
        self.right = os.path.join(self.tmp, "r")
        os.makedirs(self.left)
        os.makedirs(self.right)
        self._patcher = patch.object(xefm_app, "FileMonitorManager", _FakeMonitor)
        self._patcher.start()
        self.backend = create_backend("memory")
        self.backend.open()
        sm = XeFMStateManager(db_path=os.path.join(self.tmp, "state.db"))
        self.app = xefm_app.XeFMApp(self.backend, self.left, self.right, state_manager=sm)
        sys.stdout, sys.stderr = self.app._orig_stdout, self.app._orig_stderr
        # Record every effect handed to the backend on theme switch.
        self.pushed = []
        self.backend.set_post_effect = self.pushed.append

    def tearDown(self):
        self._patcher.stop()
        try:
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_theme(self, name, **kw):
        self.app.themes.append((name, xefm_app._theme(
            bg=(0, 0, 0), fg=(0, 255, 0), muted=(0, 128, 0), accent=(0, 200, 0),
            surface=(0, 30, 0), selection=(0, 80, 0), **kw)))
        return len(self.app.themes) - 1

    def test_switching_to_effect_theme_pushes_it_then_clearing_theme_clears(self):
        crt_i = self._add_theme("CRTTest", post_effect="crt")
        plain_i = self._add_theme("PlainTest")

        self.app._select_theme(crt_i)
        self.assertTrue(self.pushed, "expected an effect to be pushed")
        self.assertIsInstance(self.pushed[-1], PostEffect)
        self.assertEqual(self.pushed[-1].name, "crt")

        # Switching to a theme without an effect clears it (None).
        self.app._select_theme(plain_i)
        self.assertIsNone(self.pushed[-1])


if __name__ == "__main__":
    unittest.main()
