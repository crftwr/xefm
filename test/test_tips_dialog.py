"""Tests for the Tip of the Day dialog (issue #261): the content module's
placeholders resolve against the real keymap, and the dialog — driven through a
MemoryBackend + XeFMApp — navigates, persists its rotation and the "Don't show
tips at startup" opt-out, and appears at startup at most once per day."""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from xefm.tips import TIPS, referenced_actions, render_tip, tip_count  # noqa: E402
from xefm.tips_dialog import TipsDialog  # noqa: E402
from puikit.backends import create_backend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402


def _key(k, mods=frozenset()):
    return Event(EventType.KEY, key=k, modifiers=frozenset(mods))


class TipsContent(unittest.TestCase):
    """Pure content checks, no backend."""

    def test_rotation_size(self):
        self.assertGreaterEqual(tip_count(), 20)

    def test_welcome_is_first(self):
        title, body = TIPS[0]
        self.assertIn("Welcome", title)
        self.assertIn("{key:help}", body)   # points a new user at the Help dialog

    def test_render_resolves_placeholders(self):
        for i in range(tip_count()):
            source = render_tip(i, lambda action: "X")
            self.assertNotIn("{key:", source, f"unresolved placeholder in tip {i}")
            self.assertTrue(source.startswith("### "), f"tip {i} lacks its heading")

    def test_render_wraps_index(self):
        self.assertEqual(render_tip(tip_count()), render_tip(0))


class TipsDialogApp(unittest.TestCase):
    def setUp(self):
        self.left = tempfile.mkdtemp()
        self.right = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        # Temp state DB, never the real ~/.xefm/state.db — these tests read and
        # write the tips.* keys, and must not touch the developer's own.
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.left, self.right,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.panel.set_text_effect(False)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
        except Exception:
            pass
        self.b.close()
        shutil.rmtree(self.left, ignore_errors=True)
        shutil.rmtree(self.right, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _open(self):
        self.app.show_tips()
        dlg = self.app.panel._layers[-1].widget
        self.assertIsInstance(dlg, TipsDialog)
        return dlg

    def _dialog_open(self):
        layers = self.app.panel._layers
        return bool(layers) and isinstance(layers[-1].widget, TipsDialog)

    # --- content vs. the default keymap --------------------------------------

    def test_all_referenced_actions_are_bound_by_default(self):
        # A typo'd action in a tip would render as "—" (unbound). Checked
        # against the *template* keymap, not the app's live one — the live
        # keymap comes from the developer's own ~/.xefm/config.py, and an
        # action deliberately shipped unbound (edit_config) must not appear in
        # a tip as a key reference in the first place.
        from xefm._config import Config
        for action in sorted(referenced_actions()):
            binding = Config.KEY_BINDINGS.get(action)
            if isinstance(binding, dict):
                binding = binding.get("keys")
            self.assertTrue(binding,
                            f"tip references unbound/unknown action {action!r}")

    # --- draw / layout -------------------------------------------------------

    def test_dialog_draws_welcome_checkbox_and_counter(self):
        self._open()
        self.app.panel.render()
        screen = "\n".join(self.b.snapshot())
        for token in ("Tip of the Day", "Welcome to XeFM",
                      "Don't show tips at startup", f"1/{tip_count()}"):
            self.assertIn(token, screen, f"missing {token!r}")

    # --- navigation ----------------------------------------------------------

    def test_left_right_step_and_wrap(self):
        dlg = self._open()
        dlg.handle_event(_key("right"))
        self.assertEqual(dlg.index, 1)
        dlg.handle_event(_key("left"))
        self.assertEqual(dlg.index, 0)
        dlg.handle_event(_key("left"))              # wraps backward
        self.assertEqual(dlg.index, tip_count() - 1)
        dlg.handle_event(_key("right"))             # and forward again
        self.assertEqual(dlg.index, 0)

    def test_navigation_updates_screen(self):
        dlg = self._open()
        dlg.handle_event(_key("right"))
        self.app.panel.render()
        screen = "\n".join(self.b.snapshot())
        self.assertIn(TIPS[1][0], screen)           # the second tip's title
        self.assertIn(f"2/{tip_count()}", screen)

    # --- rotation persistence ------------------------------------------------

    def test_close_advances_rotation_past_last_viewed(self):
        dlg = self._open()
        dlg.handle_event(_key("right"))
        dlg.handle_event(_key("right"))             # viewing tip index 2
        dlg.handle_event(_key("escape"))
        self.assertFalse(self._dialog_open())
        self.assertEqual(self.sm.get_state("tips.index"), 3)
        self.assertTrue(self.sm.get_state("tips.enabled"))
        # Reopening resumes at the next unseen tip.
        dlg = self._open()
        self.assertEqual(dlg.index, 3)
        dlg.handle_event(_key("escape"))

    def test_rotation_wraps_to_start(self):
        dlg = self._open()
        dlg.handle_event(_key("left"))              # jump to the last tip
        self.assertEqual(dlg.index, tip_count() - 1)
        dlg.handle_event(_key("enter"))             # Enter closes too
        self.assertEqual(self.sm.get_state("tips.index"), 0)

    # --- don't show again ----------------------------------------------------

    def test_space_opts_out_and_reopening_shows_it_checked(self):
        dlg = self._open()
        dlg.handle_event(_key("space"))
        self.assertTrue(dlg.checkbox.checked)
        dlg.handle_event(_key("escape"))
        self.assertFalse(self.sm.get_state("tips.enabled"))
        # From the Help menu the dialog still opens, checkbox pre-checked;
        # unchecking it there re-enables the startup tips.
        dlg = self._open()
        self.assertTrue(dlg.checkbox.checked)
        dlg.handle_event(_key("space"))
        dlg.handle_event(_key("escape"))
        self.assertTrue(self.sm.get_state("tips.enabled"))

    def test_click_on_checkbox_toggles(self):
        dlg = self._open()
        self.app.panel.render()                     # populate the hit rect
        x0, x1, y0, y1 = dlg._cb_rect
        dlg.handle_event(Event(EventType.MOUSE_CLICK,
                               x=(x0 + x1) / 2.0, y=(y0 + y1) / 2.0))
        self.assertTrue(dlg.checkbox.checked)
        self.assertTrue(self._dialog_open())        # a toggle doesn't close
        dlg.handle_event(_key("escape"))

    def test_click_outside_closes(self):
        dlg = self._open()
        self.app.panel.render()
        dlg.handle_event(Event(EventType.MOUSE_CLICK, x=-1.0, y=-1.0))
        self.assertFalse(self._dialog_open())

    # --- startup -------------------------------------------------------------

    def test_startup_shows_once_per_day(self):
        self.app._maybe_show_startup_tip()
        self.assertTrue(self._dialog_open())
        self.app.panel._layers[-1].widget.handle_event(_key("escape"))
        self.app._maybe_show_startup_tip()          # same day: stays quiet
        self.assertFalse(self._dialog_open())

    def test_startup_respects_opt_out(self):
        self.sm.set_state("tips.enabled", False)
        self.app._maybe_show_startup_tip()
        self.assertFalse(self._dialog_open())


if __name__ == "__main__":
    unittest.main()
