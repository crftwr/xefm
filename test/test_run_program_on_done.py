"""``ctx.run_program(..., on_done=)`` (Preview, #900): the exit code reaches
the extension in every way a program runs - terminal mode's hand-over, a
terminal session in the desktop app, the background - and never before the
call returns."""

import os
import sys
import time
from unittest.mock import patch

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from test_customization_api import app_with, config_with  # noqa: E402,F401
from xefm import user_api  # noqa: E402


def run(app, func):
    out = {}
    user_api.load_user_entries(config_with(
        ACTIONS={"probe": lambda ctx: out.setdefault("value", func(ctx))}))
    app.dispatch("probe")
    return out.get("value")


def _pump(app, until, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        app._pump_later()
        time.sleep(0.01)


def test_terminal_mode_reports_the_code_after_returning(app_with):
    app, _ = app_with()
    got = []
    with patch("xefm.app.is_desktop_mode", return_value=False), \
            patch.object(app, "_run_in_terminal", return_value=3):
        code = run(app, lambda ctx: ctx.run_program(
            ["vim"], terminal=True, on_done=lambda ctx, c: got.append((ctx, c))))
    assert code == 3 and got == []  # not inside the call
    _pump(app, lambda: got)
    [(ctx, c)] = got
    assert c == 3 and isinstance(ctx, user_api.ActionContext)


def test_a_terminal_session_reports_when_it_ends(app_with):
    app, _ = app_with()
    got = []
    with patch("xefm.app.is_desktop_mode", return_value=True), \
            patch.object(app, "_terminal_unavailable", return_value=None), \
            patch.object(app, "_start_session") as start:
        assert run(app, lambda ctx: ctx.run_program(
            ["vim"], terminal=True, on_done=lambda ctx, c: got.append(c))) is None
    assert start.call_args.kwargs["shell"] is False
    start.call_args.kwargs["on_done"](0)  # the session ended
    assert got == []
    _pump(app, lambda: got)
    assert got == [0]


def test_no_terminal_in_the_desktop_app_reports_none(app_with):
    app, _ = app_with()
    got = []
    with patch("xefm.app.is_desktop_mode", return_value=True), \
            patch.object(app, "_terminal_unavailable", return_value="no libghostty"):
        run(app, lambda ctx: ctx.run_program(
            ["vim"], terminal=True, on_done=lambda ctx, c: got.append(c)))
    _pump(app, lambda: got)
    assert got == [None]


def test_the_background_reports_the_real_exit(app_with):
    app, _ = app_with()
    got = []
    run(app, lambda ctx: ctx.run_program(
        [sys.executable, "-c", "raise SystemExit(4)"],
        on_done=lambda ctx, c: got.append(c)))
    _pump(app, lambda: got)
    assert got == [4]


def test_a_program_that_cannot_start_reports_none(app_with):
    app, _ = app_with()
    got = []
    run(app, lambda ctx: ctx.run_program(
        ["/no/such/program-xefm"], on_done=lambda ctx, c: got.append(c)))
    _pump(app, lambda: got)
    assert got == [None]
