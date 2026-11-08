"""Key sequences — bindings of more than one key, such as ``'z z'`` (#587).

The pure half drives :class:`xefm.key_sequence.KeySequencer` over a real
``KeyBindings``; the app half presses keys on the memory backend. ``z`` is
used because no action binds it by default.
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from test_customization_api import app_with, key  # noqa: E402,F401
from xefm import key_sequence  # noqa: E402
from xefm.config import KeyBindings  # noqa: E402
from xefm.key_sequence import ACT, PASS, WAIT, KeySequencer  # noqa: E402


def z():
    return key("z", "z")


def esc():
    return key("escape")


class Harness:
    """A sequencer whose timer and timeout are in the test's hands."""

    def __init__(self, bindings, timeout=1.0):
        self.kb = KeyBindings(bindings)
        self.timers = []
        self.timed_out = []
        self.changes = 0
        self.timeout = timeout
        self.seq = KeySequencer(lambda: self.kb, "filer",
                                timeout=lambda: self.timeout,
                                call_later=lambda secs, fn: self.timers.append((secs, fn)),
                                on_timeout=self.timed_out.append,
                                on_change=self._changed)

    def _changed(self):
        self.changes += 1

    def fire(self):
        for _secs, fn in self.timers:
            fn()


# --------------------------------------------------------------------------- #
# Parsing and display
# --------------------------------------------------------------------------- #

def test_a_token_with_spaces_is_a_sequence_and_never_matches_one_key():
    kb = KeyBindings({"cursor_top": ["z z"]})
    parsed = kb._parse_key_expression("z z")
    assert parsed[2] == "seq" and len(parsed[0]) == 2
    assert kb.find_action_for_event(z(), context="filer") is None


def test_a_sequence_shows_as_its_keys():
    kb = KeyBindings({})
    assert kb.format_key_for_display("z Shift-H") == "z Shift-H"
    assert kb.format_key_for_display("g ENTER") == "g Enter"


# --------------------------------------------------------------------------- #
# The sequencer
# --------------------------------------------------------------------------- #

def test_a_sequence_completes_on_its_last_key():
    h = Harness({"cursor_top": ["z z"]})
    assert h.seq.feed(z()) == (WAIT, None)
    assert h.seq.pending and h.seq.pending_text() == "z"
    assert h.seq.feed(z()) == (ACT, "cursor_top")
    assert not h.seq.pending


def test_a_key_that_begins_no_sequence_is_left_to_the_caller():
    h = Harness({"cursor_top": ["z z"]})
    assert h.seq.feed(key("j", "j")) == (PASS, None)
    assert not h.timers


def test_a_key_that_continues_nothing_ends_the_sequence_and_is_handled():
    h = Harness({"cursor_top": ["z z"]})
    h.seq.feed(z())
    assert h.seq.feed(key("j", "j")) == (PASS, None)
    assert not h.seq.pending


def test_esc_drops_the_pending_keys():
    h = Harness({"cursor_top": ["z z"], "cursor_bottom": ["z"]})
    h.seq.feed(z())
    assert h.seq.feed(esc()) == (WAIT, None)
    assert not h.seq.pending
    h.fire()
    assert h.timed_out == []          # the dropped keys' timer does nothing


def test_with_a_timeout_the_shorter_binding_runs_when_it_passes():
    h = Harness({"cursor_top": ["z z"], "cursor_bottom": ["z"]}, timeout=0.5)
    assert h.seq.feed(z()) == (WAIT, None)
    assert [secs for secs, _fn in h.timers] == [0.5]
    h.fire()
    assert h.timed_out == ["cursor_bottom"]
    assert not h.seq.pending


def test_the_longer_binding_wins_when_its_key_comes_in_time():
    h = Harness({"cursor_top": ["z z"], "cursor_bottom": ["z"]})
    h.seq.feed(z())
    assert h.seq.feed(z()) == (ACT, "cursor_top")
    h.fire()
    assert h.timed_out == []          # the first key's timer is stale now


def test_with_no_timeout_the_shorter_binding_runs_on_the_next_key():
    h = Harness({"cursor_top": ["z z"], "cursor_bottom": ["z"]}, timeout=None)
    h.seq.feed(z())
    assert h.timers == []             # nothing armed: it waits
    assert h.seq.feed(key("j", "j")) == (PASS, "cursor_bottom")


def test_a_prefix_that_is_no_binding_never_runs_anything_on_timeout():
    h = Harness({"cursor_top": ["z z"]})
    h.seq.feed(z())
    h.fire()
    assert h.timed_out == [] and not h.seq.pending


def test_three_keys():
    h = Harness({"go_root": ["z x c"]})
    assert h.seq.feed(z())[0] == WAIT
    assert h.seq.feed(key("x", "x"))[0] == WAIT
    assert h.seq.pending_text() == "z x"
    assert h.seq.feed(key("c", "c")) == (ACT, "go_root")


def test_the_status_line_hears_about_every_change():
    h = Harness({"cursor_top": ["z z"]})
    h.seq.feed(z())
    h.seq.feed(z())
    assert h.changes == 2             # pending, then cleared


def test_the_default_timeout_is_vims():
    assert key_sequence.DEFAULT_TIMEOUT == 1.0


# --------------------------------------------------------------------------- #
# In the file list
# --------------------------------------------------------------------------- #

@pytest.fixture
def seq_app(app_with):
    from xefm import keymap_presets
    bindings = dict(keymap_presets.table(keymap_presets.AFX), cursor_bottom=["z z"], cursor_top=["z t"])
    app, _tmp = app_with(KEY_BINDINGS=bindings)
    app._keymap_preset = "afx"
    app.keys = KeyBindings(bindings)
    return app


def test_a_sequence_moves_the_cursor_and_the_status_bar_shows_it(seq_app):
    app = seq_app
    app.active_pane()["focused_index"] = 0
    app.on_event(z())
    assert app.status._text() == "z …   Esc cancel"
    app.on_event(z())
    assert app.active_pane()["focused_index"] == len(app.active_pane()["files"]) - 1
    assert "Esc cancel" not in app.status._text()
    app.on_event(z())
    app.on_event(key("t", "t"))
    assert app.active_pane()["focused_index"] == 0


def test_a_modal_layer_drops_the_pending_keys(seq_app):
    app = seq_app
    app.on_event(z())
    app.dispatch("help")
    assert app.panel.has_layers
    app.on_event(esc())
    assert not app.key_sequence.pending
