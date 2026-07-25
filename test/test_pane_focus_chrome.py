"""Theme-driven pane focus chrome, and the shared modal open transition.

Two things a theme can now turn on as pure data, with no app code behind them:
corner brackets framing the *focused* file pane (``extras['pane_frame']``) and an
ink wash over the *resting* one (``extras['pane_dim']``). Only the themes in
``OPTED_IN`` below use them; every other theme must render exactly as it did
before these existed, which is what most of this file checks.

Also covers ``xefm.dialog_geometry.animate_open`` — the one place XeFM's modal
entrance is defined, so the eleven dialogs that call it cannot drift apart.

Runs headless on the ``memory`` backend, mirroring ``test_post_effect_theme``.
"""

import os
import sys
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import dialog_geometry as dg  # noqa: E402
from xefm.file_pane import (  # noqa: E402
    PANE_INACTIVE_DIM, FilePane, _dim_ink,
)
from puikit import PROFILE_GUI_DESKTOP, PROFILE_TUI, Panel  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402
from puikit.capability import CapabilityProfile  # noqa: E402

THEMES = dict(xefm_app.THEMES)
SCIFI = THEMES["Sci-Fi"]
DARK = THEMES["Dark+"]

#: The built-ins that opt into the focus chrome and the arriving-text effect. The
#: guarantee these tests defend is not "exactly one theme uses them" but "a theme
#: that does not name them is untouched" — so adding a look costs one entry here.
OPTED_IN = ("Sci-Fi", "Cyber")


class _VectorBackend(MemoryBackend):
    """MemoryBackend masks vector_shapes off (it is a character grid); the pane
    frame is drawn only where sub-cell room exists, so testing it needs the
    vector path re-enabled."""

    @property
    def capabilities(self):
        return CapabilityProfile({**PROFILE_GUI_DESKTOP, "native_menus": False})

    @property
    def base_size(self):
        return (8, 16)


def _render(theme, active, backend, w=26, h=8):
    pane = {"files": [Path(f"/tmp/file{i}.txt") for i in range(5)],
            "focused_index": 1, "selected_files": set(), "path": "/tmp"}
    panel = Panel(backend)
    panel.theme = theme
    view = FilePane(pane)
    view.active = active
    panel.add(view, x=0, y=0, w=w, h=h)
    panel.render()
    # Settle any arriving-text effect the theme carries (Sci-Fi decodes its text
    # in as the pane appears — see puikit.textfx). These tests are about the pane
    # *focus chrome*, so they assert against the resting frame; the animation
    # itself is covered by puikit's test_textfx.py.
    for wid in list(panel._text_anims):
        panel._text_anims[wid] -= 99.0
    panel.render()
    return backend, panel


def _hairlines(theme, active):
    """The sub-unit strokes drawn for a pane — i.e. its frame, if any.

    Captured from a single settled frame: _render draws more than once (to let a
    theme's arriving-text effect finish), so a spy left on across all of them
    would count the frame once per render."""
    be = _VectorBackend(width=26, height=8)
    _be, panel = _render(theme, active, be)
    calls = []
    orig = be.fill_rect
    be.fill_rect = lambda *a, **k: (calls.append(a), orig(*a, **k))[1]
    panel.render()
    return [c for c in calls if min(c[2], c[3]) < 1.0]


# --- theme data ----------------------------------------------------------------

class ThemeOptIn(unittest.TestCase):

    def test_scifi_opts_into_both(self):
        self.assertEqual(SCIFI.extras["pane_frame"],
                         {"color": (130, 205, 255), "arm": 2})
        self.assertTrue(SCIFI.extras["pane_dim"])

    def test_cyber_opts_into_both(self):
        cyber = THEMES["Cyber"]
        self.assertEqual(cyber.extras["pane_frame"], {"color": (64, 214, 236), "arm": 2})
        self.assertTrue(cyber.extras["pane_dim"])

    def test_no_other_builtin_theme_opts_in(self):
        # The guarantee that makes this a safe addition: a theme that does not ask
        # for the chrome renders byte-for-byte as it did before the chrome existed.
        for name, theme in xefm_app.THEMES:
            if name in OPTED_IN:
                continue
            self.assertIsNone(theme.extras.get("pane_frame"), name)
            self.assertIsNone(theme.extras.get("pane_dim"), name)

    def test_both_keys_are_user_configurable(self):
        for key in ("pane_frame", "pane_dim", "text_effect"):
            self.assertIn(key, xefm_app._THEME_OVERRIDE_MAP)

    def test_scifi_opts_into_the_arriving_text_effect(self):
        from puikit import textfx
        effect = textfx.coerce(SCIFI.extras.get("text_effect"))
        self.assertIsNotNone(effect)
        # A plain left-to-right reveal: the pane's job is to be read, and a
        # decoding tail competes with the text that has already resolved.
        # ``decode`` stays available as the louder alternative.
        self.assertEqual(effect.kind, "typewriter")
        self.assertIn("decode", textfx.TEXT_EFFECTS)
        # Short and capped: this fires on every directory change, so a long or
        # uncapped cascade would sit between the user and their file list.
        self.assertLessEqual(effect.duration_ms, 400)
        self.assertTrue(effect.max_rows)

    def test_cyber_takes_the_louder_reveal(self):
        # The opposite side of the trade Sci-Fi makes above: Cyber's identity *is*
        # the decoding churn, and it pays for the noise by being quicker.
        from puikit import textfx
        cyber = textfx.coerce(THEMES["Cyber"].extras["text_effect"])
        scifi = textfx.coerce(SCIFI.extras["text_effect"])
        self.assertEqual(cyber.kind, "decode")
        self.assertLess(cyber.duration_ms, scifi.duration_ms)
        self.assertTrue(cyber.max_rows)

    def test_no_other_builtin_theme_animates_text(self):
        for name, theme in xefm_app.THEMES:
            if name in OPTED_IN:
                continue
            self.assertIsNone(theme.extras.get("text_effect"), name)

    def test_text_viewer_prefers_scatter_with_flash(self):
        from puikit import textfx
        from xefm.text_viewer import TextViewer
        variant = TextViewer.text_effect
        merged = textfx.merge(textfx.coerce(SCIFI.extras["text_effect"]), variant)
        self.assertEqual(merged.kind, "scatter")
        self.assertGreater(merged.params.get("flash", 0), 0)
        base = textfx.coerce(SCIFI.extras["text_effect"])
        # Duration still comes from the theme...
        self.assertEqual(merged.duration_ms, base.duration_ms)
        # ...but a screenful is not a list of rows, so the viewer drops the
        # pane's cascade and its row cap: the whole page materializes at once.
        self.assertEqual(merged.stagger_ms, 0)
        self.assertEqual(merged.max_rows, 0)
        self.assertTrue(base.max_rows, "the pane itself should still be capped")

    def test_viewer_variant_is_inert_without_a_theme_effect(self):
        # A widget preference must never animate what a theme left off.
        from puikit import textfx
        self.assertIsNone(textfx.coerce(DARK.extras.get("text_effect")))

    def test_theme_builder_passes_text_effect_through(self):
        t = xefm_app._theme(bg=(0, 0, 0), fg=(255, 255, 255), muted=(128, 128, 128),
                       accent=(0, 122, 204), surface=(20, 20, 20),
                       selection=(10, 60, 100), text_effect="typewriter")
        self.assertEqual(t.extras["text_effect"], "typewriter")

    def test_theme_builder_passes_them_through(self):
        t = xefm_app._theme(bg=(0, 0, 0), fg=(255, 255, 255), muted=(128, 128, 128),
                       accent=(0, 122, 204), surface=(20, 20, 20),
                       selection=(10, 60, 100),
                       pane_frame={"color": (1, 2, 3)}, pane_dim=0.5)
        self.assertEqual(t.extras["pane_frame"], {"color": (1, 2, 3)})
        self.assertEqual(t.extras["pane_dim"], 0.5)

    def test_a_theme_naming_neither_carries_neither(self):
        t = xefm_app._theme(bg=(0, 0, 0), fg=(255, 255, 255), muted=(128, 128, 128),
                       accent=(0, 122, 204), surface=(20, 20, 20),
                       selection=(10, 60, 100))
        self.assertNotIn("pane_frame", t.extras)
        self.assertNotIn("pane_dim", t.extras)


# --- the frame -----------------------------------------------------------------

class PaneFrame(unittest.TestCase):

    def test_focused_scifi_pane_is_framed_on_a_vector_backend(self):
        self.assertEqual(len(_hairlines(SCIFI, active=True)), 8)  # 4 corners x 2 legs

    def test_resting_pane_is_not_framed(self):
        # The louder cue marks the focused state, never the reverse.
        self.assertEqual(_hairlines(SCIFI, active=False), [])

    def test_a_theme_that_opts_out_is_never_framed(self):
        self.assertEqual(_hairlines(DARK, active=True), [])

    def test_frame_stays_inside_the_pane(self):
        for x, y, w, h, _style in _hairlines(SCIFI, active=True):
            self.assertGreaterEqual(x, -1e-9)
            self.assertGreaterEqual(y, -1e-9)
            self.assertLessEqual(x + w, 26 + 1e-9)
            self.assertLessEqual(y + h, 8 + 1e-9)

    def test_grid_pane_draws_no_frame_and_keeps_its_filenames(self):
        # A character grid has no sub-cell margin, so the frame would land on the
        # first and last rows and eat the leading characters of those filenames.
        be, _panel = _render(SCIFI, True, MemoryBackend(width=26, height=8,
                                                        capabilities=PROFILE_TUI))
        lines = be.snapshot()
        self.assertIn("file0.txt", lines[0])
        self.assertIn("file4.txt", lines[4])
        for line in lines:
            for glyph in "┏┓┗┛━┃":
                self.assertNotIn(glyph, line)


# --- the dim -------------------------------------------------------------------

class PaneDim(unittest.TestCase):

    def test_resting_scifi_pane_ink_recedes(self):
        active, _ = _render(SCIFI, True, MemoryBackend(width=26, height=8,
                                                       capabilities=PROFILE_TUI))
        resting, _ = _render(SCIFI, False, MemoryBackend(width=26, height=8,
                                                         capabilities=PROFILE_TUI))
        self.assertNotEqual(active.style_at(1, 0).fg, resting.style_at(1, 0).fg)

    def test_focused_pane_is_never_dimmed(self):
        # Even on a theme that opts in: the cue marks the resting pane, so the
        # focused one is never the pane that changed.
        view = FilePane({"files": [], "focused_index": 0, "selected_files": set()})
        view.active = True
        self.assertEqual(view._inactive_dim(SCIFI), 0.0)

    def test_opted_out_theme_is_identical_focused_or_not(self):
        active, _ = _render(DARK, True, MemoryBackend(width=26, height=8,
                                                      capabilities=PROFILE_TUI))
        resting, _ = _render(DARK, False, MemoryBackend(width=26, height=8,
                                                        capabilities=PROFILE_TUI))
        self.assertEqual(active.style_at(1, 0).fg, resting.style_at(1, 0).fg)

    def test_true_means_the_default_strength(self):
        view = FilePane({"files": [], "focused_index": 0, "selected_files": set()})
        view.active = False
        self.assertEqual(view._inactive_dim(SCIFI), PANE_INACTIVE_DIM)

    def test_a_float_sets_its_own_strength(self):
        view = FilePane({"files": [], "focused_index": 0, "selected_files": set()})
        view.active = False
        t = xefm_app._theme(bg=(0, 0, 0), fg=(255, 255, 255), muted=(128, 128, 128),
                       accent=(0, 122, 204), surface=(20, 20, 20),
                       selection=(10, 60, 100), pane_dim=0.75)
        self.assertEqual(view._inactive_dim(t), 0.75)

    def test_strength_is_clamped(self):
        view = FilePane({"files": [], "focused_index": 0, "selected_files": set()})
        view.active = False
        for given, want in ((5.0, 1.0), (-2.0, 0.0)):
            t = xefm_app._theme(bg=(0, 0, 0), fg=(255, 255, 255), muted=(128, 128, 128),
                           accent=(0, 122, 204), surface=(20, 20, 20),
                           selection=(10, 60, 100), pane_dim=given)
            self.assertEqual(view._inactive_dim(t), want)

    def test_dim_ink_is_a_no_op_at_zero(self):
        color = (200, 224, 245)
        self.assertIs(_dim_ink(color, (16, 30, 50), 0.0), color)

    def test_dim_ink_moves_toward_the_background(self):
        bg = (16, 30, 50)
        washed = _dim_ink((200, 224, 245), bg, 0.5)
        self.assertEqual(washed, (108, 127, 148))


# --- the shared modal entrance -------------------------------------------------

class OpenTransition(unittest.TestCase):

    class _Spy:
        def __init__(self, result=True):
            self.hints = None
            self.result = result

        def animate(self, widget, hints=None):
            self.hints = hints
            return self.result

    def test_uses_a_fading_scale_with_expo_easing(self):
        spy = self._Spy()
        dg.animate_open(spy, object())
        self.assertEqual(spy.hints["transition"], "scale")
        self.assertTrue(spy.hints["fade"])
        self.assertEqual(spy.hints["easing"], "ease_out_expo")
        self.assertEqual(spy.hints["from_scale"], 0.92)

    def test_default_duration_is_the_dialog_one(self):
        spy = self._Spy()
        dg.animate_open(spy, object())
        self.assertEqual(spy.hints["duration_ms"], dg.OPEN_MS_DIALOG)

    def test_viewers_open_faster_than_dialogs(self):
        self.assertLess(dg.OPEN_MS_VIEWER, dg.OPEN_MS_DIALOG)
        spy = self._Spy()
        dg.animate_open(spy, object(), dg.OPEN_MS_VIEWER)
        self.assertEqual(spy.hints["duration_ms"], dg.OPEN_MS_VIEWER)

    def test_reports_whether_a_transition_was_scheduled(self):
        # False under reduced motion / a still backend, so a caller needing to act
        # after the transition does it at once instead of waiting on a tick.
        self.assertFalse(dg.animate_open(self._Spy(result=False), object()))
        self.assertTrue(dg.animate_open(self._Spy(result=True), object()))

    def test_the_shared_hints_are_not_mutated_by_a_call(self):
        # animate_open spreads the module constant into a fresh dict; if it
        # mutated it, one viewer's duration would leak into every later dialog.
        before = dict(dg._OPEN_TRANSITION)
        dg.animate_open(self._Spy(), object(), 999)
        self.assertEqual(dg._OPEN_TRANSITION, before)
        self.assertNotIn("duration_ms", dg._OPEN_TRANSITION)


if __name__ == "__main__":
    unittest.main()
