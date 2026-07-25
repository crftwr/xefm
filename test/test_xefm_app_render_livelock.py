"""Regression: a stray stdout/stderr write during render must not livelock the UI.

XeFM routes stdout/stderr into the log pane (``_StreamToLog``), and every captured
line wakes the monitoring pump, which drains the line and re-renders so it shows.
That is correct for a *worker* thread posting output. But if anything writes to
stdout/stderr from the UI thread *during* the render itself, the render schedules
another wake, which drains and renders again, which writes again — a
self-sustaining cycle. The UI keeps responding (it is a livelock, not a deadlock)
while burning 100% of a core, which is what a user sees as "XeFM hung".

The write can come from anywhere in the draw path: a ``logger.warning`` on a
handler-less logger falls through to ``logging.lastResort``, which writes to
stderr. No component has to be at fault for the loop to run away.

Run with: python -m pytest test/test_xefm_app_render_livelock.py -v
"""

import os
import queue
import sys
import threading
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402

#: How many pump→render cycles to run before declaring the loop non-terminating.
#: A healthy pump settles in a couple of frames; the livelock runs forever.
_RUNAWAY = 200


class FakeLog:
    def __init__(self):
        self.lines = []

    def append(self, line, style=None):
        self.lines.append(line)


class FakePanel:
    """Panel whose render writes to stderr, standing in for any draw-path write."""

    def __init__(self):
        self.scheduled = []
        self.renders = 0
        self.on_render = None

    def call_on_main_thread(self, cb):
        self.scheduled.append(cb)
        return True

    def render(self):
        self.renders += 1
        if self.on_render is not None:
            self.on_render()


def _app():
    """A XeFMApp with the real pump + captured-output machinery, nothing else."""
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app._event_driven = True
    app._wake_lock = threading.Lock()
    app._wake_pending = False
    app._rendering = False
    app._ui_thread_ident = threading.get_ident()
    app._log_queue = queue.Queue()
    app.log = FakeLog()
    app.panel = FakePanel()
    # Only the captured-output branch of the pump is under test; the rest report
    # "nothing changed" so any re-render is attributable to captured output.
    app._sync_monitored_dirs = lambda: None
    app._process_reload_queue = lambda: False
    app._process_result_queue = lambda: False
    app._pump_loading_indicator = lambda: False
    return app


def _run_scheduled(app, limit=_RUNAWAY):
    """Drive the UI thread's message loop: run scheduled callbacks until the
    queue drains or ``limit`` cycles pass (i.e. it is not going to settle)."""
    cycles = 0
    while app.panel.scheduled and cycles < limit:
        app.panel.scheduled.pop(0)()
        cycles += 1
    return cycles


class RenderWriteLivelock(unittest.TestCase):
    def test_write_during_render_settles(self):
        app = _app()
        stream = xefm_app._StreamToLog("STDERR", app._log_queue, on_write=app._wake_pump)
        # Every render emits a line, exactly as a warning from the draw path would.
        app.panel.on_render = lambda: stream.write("shader failed to compile\n")

        stream.write("first line\n")          # a real producer starts things off
        cycles = _run_scheduled(app)

        self.assertLess(cycles, _RUNAWAY,
                        "pump never settled: a write during render keeps "
                        "scheduling another render (100% CPU livelock)")

    def test_worker_thread_write_still_wakes_the_ui(self):
        # The guard must not break what _wake_pump exists for: a worker thread
        # posting output has to reach the log pane.
        app = _app()
        stream = xefm_app._StreamToLog("STDERR", app._log_queue, on_write=app._wake_pump)

        t = threading.Thread(target=lambda: stream.write("from a worker\n"))
        t.start()
        t.join()

        self.assertEqual(len(app.panel.scheduled), 1, "worker write did not wake the UI")
        _run_scheduled(app)
        self.assertIn("from a worker", app.log.lines)

    def test_worker_write_during_render_is_not_dropped(self):
        # A worker racing a render is NOT the livelock case and must still land.
        app = _app()
        stream = xefm_app._StreamToLog("STDERR", app._log_queue, on_write=app._wake_pump)

        def write_from_worker():
            t = threading.Thread(target=lambda: stream.write("raced the render\n"))
            t.start()
            t.join()

        app.panel.on_render = write_from_worker
        stream.write("first line\n")
        _run_scheduled(app)

        self.assertIn("raced the render", app.log.lines)


if __name__ == "__main__":
    unittest.main()
