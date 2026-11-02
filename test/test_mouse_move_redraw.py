"""A pointer move redraws the window only when it changes what was drawn.

XeFM used to re-render on every MOUSE_MOVE so the splitters could swap in their
resize cursor. A full render is the dearest thing XeFM does per event, and on
Windows a mouse moving at 125 Hz then left no time to paint: the animated
background stood still for as long as the pointer moved. PuiKit's Panel now
says whether the move crossed anything the last frame drew from the pointer
(``dispatch_event`` for MOUSE_MOVE); XeFM renders only then.

Runs on the headless ``memory`` backend with monitoring faked, mirroring
test_xefm_app_theme_persistence.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from puikit import Event, EventType
from puikit.backends import create_backend
from puikit.panel import DrawContext

from xefm import app as xefm_app
from xefm.state_manager import XeFMStateManager


class _FakeMonitor:
    def __init__(self, config, file_manager):
        self.reload_queue = file_manager.reload_queue

    def is_monitoring_enabled(self):
        return False

    def update_monitored_directory(self, *args):
        pass

    def stop_monitoring(self):
        pass

    def check_observer_health(self):
        pass


@unittest.skipUnless(hasattr(DrawContext, "pointer_in"), "PuiKit without move answers")
class MouseMoveRedraw(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for side in ("l", "r"):
            os.makedirs(os.path.join(self.tmp, side))
            for i in range(5):
                open(os.path.join(self.tmp, side, f"file{i}.txt"), "w").close()
        self._patcher = patch.object(xefm_app, "FileMonitorManager", _FakeMonitor)
        self._patcher.start()
        self.backend = create_backend("memory")
        self.backend.open()
        sm = XeFMStateManager(db_path=os.path.join(self.tmp, "state.db"))
        self.app = xefm_app.XeFMApp(self.backend, os.path.join(self.tmp, "l"),
                                    os.path.join(self.tmp, "r"), state_manager=sm)
        sys.stdout, sys.stderr = self.app._orig_stdout, self.app._orig_stderr
        # The first listings land from worker threads whenever they finish, and
        # on_event renders for them; that is not what these tests are about.
        self.app._pump_monitoring = lambda: False
        self.app.panel.render()
        self.renders = 0
        real = self.app.panel.render

        def counting():
            self.renders += 1
            real()
        self.app.panel.render = counting

    def tearDown(self):
        self._patcher.stop()
        try:
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _move(self, x, y):
        self.app.on_event(Event(type=EventType.MOUSE_MOVE, x=float(x), y=float(y)))

    def test_moving_over_a_file_list_does_not_redraw(self):
        for x in range(3, 9):
            self._move(x, 4)
        self.assertEqual(self.renders, 0)

    def test_a_move_the_panel_says_matters_redraws(self):
        with patch.object(self.app.panel, "dispatch_event", return_value=True):
            self._move(4, 4)
        self.assertEqual(self.renders, 1)


if __name__ == "__main__":
    unittest.main()
