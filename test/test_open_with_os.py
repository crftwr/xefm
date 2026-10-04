"""Ctrl-O's OS-default launch, when no FILE_ASSOCIATIONS rule claims the file.

On Windows this used to be cmd.exe's ``start`` under ``shell=True``. The
command line that builds quotes an argument only for ASCII blanks, so a name
with a full-width space (U+3000) reached cmd.exe bare and was split there —
"あいう　お.xlsx" tried to open "あいう" (#508). ShellExecute via
``os.startfile`` takes the path as one argument and no shell parses it.

Exercised against the real ``XeFMApp.open_with_os`` bound to a stand-in self.

Run with: python -m pytest test/test_open_with_os.py -v
"""

import os

import pytest

from xefm import app as xefm_app


class FakeEntry:
    def __init__(self, path):
        self._path = path
        self.name = path.rsplit("\\", 1)[-1]

    def __str__(self):
        return self._path


class FakeApp:
    def __init__(self, entry):
        self._entry = entry
        self.logged = []

    def _focused_entry(self):
        return self._entry

    def log_info(self, message):
        self.logged.append(message)

    open_with_os = xefm_app.XeFMApp.open_with_os


@pytest.fixture
def windows(monkeypatch):
    """Pretend to be Windows with no association, recording what is launched."""
    started, ran = [], []
    monkeypatch.setattr(xefm_app.platform, "system", lambda: "Windows")
    monkeypatch.setattr(xefm_app, "get_program_for_file", lambda name, tier: None)
    monkeypatch.setattr(xefm_app, "has_explicit_association", lambda name, tier: False)
    monkeypatch.setattr(os, "startfile", started.append, raising=False)
    monkeypatch.setattr(xefm_app.subprocess, "run",
                        lambda *a, **k: ran.append((a, k)))
    return started, ran


@pytest.mark.parametrize("name", [
    "あいう\u3000お.xlsx",   # full-width space: the #508 report
    "a b.xlsx",              # ASCII space
    "R&D ^1.xlsx",           # cmd.exe metacharacters
])
def test_windows_hands_the_whole_path_to_shellexecute(windows, name):
    started, ran = windows
    path = "C:\\Users\\me\\" + name
    app = FakeApp(FakeEntry(path))
    app.open_with_os()
    assert started == [path]
    assert ran == []          # no cmd.exe in between
    assert app.logged == [f"Opened {name} with the default app"]


def test_windows_failure_is_logged_not_raised(windows, monkeypatch):
    def fail(path):
        raise OSError("no application is associated")
    monkeypatch.setattr(os, "startfile", fail, raising=False)
    app = FakeApp(FakeEntry("C:\\Users\\me\\a.zzz"))
    app.open_with_os()
    assert app.logged == ["Failed to open a.zzz: no application is associated"]
