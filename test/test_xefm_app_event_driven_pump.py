"""Event-driven monitoring pump (XeFMApp._wake_pump / _on_pump_wake).

On a backend that can dispatch to the main thread, XeFM has no idle polling
timer: each producer thread (fs watcher, listing worker, stdout/stderr streams)
calls _wake_pump, which schedules a single drain on the UI thread. A burst of
signals must coalesce to one main-thread hop, and a producer that enqueues while
a drain is in flight must re-arm a fresh hop (never a lost update).

Run with: python -m pytest test/test_xefm_app_event_driven_pump.py -v
"""

import os
import sys
import threading
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402


class FakePanel:
    def __init__(self):
        self.scheduled = []

    def call_on_main_thread(self, cb):
        self.scheduled.append(cb)
        return True

    def render(self):
        pass


def _app(event_driven=True):
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app._event_driven = event_driven
    app._wake_lock = threading.Lock()
    app._wake_pending = False
    app._rendering = False              # self-feeding-render guard; see _wake_pump
    app._ui_thread_ident = threading.get_ident()
    app.panel = FakePanel()
    app._pump_monitoring = lambda: False  # nothing to drain in these unit tests
    return app


class WakeCoalescing(unittest.TestCase):
    def test_burst_of_signals_coalesces_to_one_hop(self):
        app = _app()
        app._wake_pump()
        app._wake_pump()
        app._wake_pump()
        self.assertEqual(len(app.panel.scheduled), 1)

    def test_hop_rearms_after_the_drain_runs(self):
        app = _app()
        app._wake_pump()
        self.assertEqual(len(app.panel.scheduled), 1)
        self.assertTrue(app._wake_pending)

        # The UI thread runs the scheduled drain: it clears the pending flag.
        app.panel.scheduled.pop()()
        self.assertFalse(app._wake_pending)

        # A later producer signal schedules a fresh hop rather than being dropped.
        app._wake_pump()
        self.assertEqual(len(app.panel.scheduled), 1)

    def test_drain_clears_pending_before_pumping(self):
        # A producer that enqueues mid-drain must re-arm. We prove the ordering by
        # having the pump itself fire a nested wake: because the flag is cleared
        # first, that nested signal schedules another hop.
        app = _app()
        nested = []

        def pump_with_nested_signal():
            app._wake_pump()  # simulates a producer racing the drain
            nested.append(True)
            return False

        app._pump_monitoring = pump_with_nested_signal
        app._wake_pump()
        # Run the drain; it clears pending, then pumps, which re-arms + reschedules.
        app.panel.scheduled.pop()()
        self.assertTrue(nested)
        self.assertTrue(app._wake_pending)
        self.assertEqual(len(app.panel.scheduled), 1)

    def test_noop_when_not_event_driven(self):
        app = _app(event_driven=False)
        app._wake_pump()
        self.assertEqual(app.panel.scheduled, [])


if __name__ == "__main__":
    unittest.main()
