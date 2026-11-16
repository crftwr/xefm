"""Starting XeFM inside XeFM - its subshell, or a program it started, both
marked XEFM_ACTIVE - warns before the TUI takes over the terminal (#900)."""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm import app as xefm_app  # noqa: E402


class _Tty(io.StringIO):
    def isatty(self):
        return True


def _run(monkeypatch, *, marked, tty, answer=""):
    if marked:
        monkeypatch.setenv("XEFM_ACTIVE", "1")
    else:
        monkeypatch.delenv("XEFM_ACTIVE", raising=False)
    err = _Tty() if tty else io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.setattr(sys, "stdin", _Tty(answer) if tty else io.StringIO(answer))
    return xefm_app._confirm_nested_launch(), err.getvalue()


def test_outside_xefm_nothing_is_asked(monkeypatch):
    assert _run(monkeypatch, marked=False, tty=True) == (True, "")


def test_inside_it_the_default_is_not_to_start(monkeypatch):
    ok, said = _run(monkeypatch, marked=True, tty=True, answer="\n")
    assert not ok and "inside XeFM" in said and "[y/N]" in said
    assert all(ord(c) < 128 for c in said)


def test_yes_starts_it_anyway(monkeypatch):
    assert _run(monkeypatch, marked=True, tty=True, answer="y\n")[0]


def test_without_a_terminal_to_ask_on_it_warns_and_goes_on(monkeypatch):
    ok, said = _run(monkeypatch, marked=True, tty=False)
    assert ok and "inside XeFM" in said and "[y/N]" not in said
