"""``PaneApi.activate()`` — moving the cursor into a named pane (#509).

Driven headless on the ``memory`` backend: the point is that the model's active
pane and both views' ``active`` flags move together, as a Tab press moves them.
"""

import os
import shutil
import tempfile
import unittest

from xefm import _config
from xefm import app as xefm_app
from xefm.state_manager import XeFMStateManager
from xefm.user_api import ActionContext


class PaneActivate(unittest.TestCase):
    def setUp(self):
        from puikit.backends import create_backend
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.app.pm.active_pane = "left"
        self.app._sync_active()
        self.ctx = ActionContext(self.app)

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _assert_active(self, name):
        self.assertEqual(self.app.pm.active_pane, name)
        self.assertEqual(self.ctx.pane.name, name)
        self.assertEqual(self.app.left_view.active, name == "left")
        self.assertEqual(self.app.right_view.active, name == "right")

    def test_activate_moves_the_cursor_across(self):
        self.ctx.right.activate()
        self._assert_active("right")
        self.ctx.left.activate()
        self._assert_active("left")

    def test_activating_the_active_pane_stays_put(self):
        # Unlike nav_left, which from the left pane goes to the parent.
        before = self.ctx.left.path
        self.ctx.left.activate()
        self._assert_active("left")
        self.assertEqual(self.ctx.left.path, before)

    def test_other_follows(self):
        self.ctx.other.activate()
        self._assert_active("right")
        self.assertEqual(self.ctx.other.name, "left")

    def test_focus_actions(self):
        self.assertTrue(self.app.dispatch("focus_right"))
        self._assert_active("right")
        self.assertTrue(self.app.dispatch("focus_right"))
        self._assert_active("right")
        self.assertTrue(self.app.dispatch("focus_left"))
        self._assert_active("left")

    def test_focus_actions_ship_unbound(self):
        self.assertEqual(_config.Config.KEY_BINDINGS["focus_left"], [])
        self.assertEqual(_config.Config.KEY_BINDINGS["focus_right"], [])


if __name__ == "__main__":
    unittest.main()
