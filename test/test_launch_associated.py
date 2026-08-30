"""How an associated external program is launched.

The one decision this makes is display handover, and it is answered by the
*backend*, not by the configuration:

* terminal mode — suspend, run, wait, restore (``less`` and ``vim`` need this)
* desktop mode  — detach, never block the event loop (no tty exists to release)

Exercised against the real ``XeFMApp._launch_associated`` bound to a stand-in
self, so the method under test is production code rather than a restatement of
it. A per-entry ``'terminal'`` flag used to make this decision; see
test_open_tiers.py for why it was removed.

Run with: python -m pytest test/test_launch_associated.py -v
"""

import shutil

import pytest

from xefm import app as xefm_app


class FakeEntry:
    def __init__(self, path="/home/me/a.log"):
        self._path = path
        self.name = path.rsplit("/", 1)[-1]

    def __str__(self):
        return self._path


class FakeApp:
    """Minimal stand-in exposing only what _launch_associated touches."""

    def __init__(self, local=True):
        self._local = local
        self.logged = []
        self.ran_in_terminal = None

    _is_local = staticmethod(lambda entry: FakeApp._current_local)
    _current_local = True

    def log_info(self, message):
        self.logged.append(message)

    def _run_in_terminal(self, argv, cwd=None):
        self.ran_in_terminal = argv

    launch = xefm_app.XeFMApp._launch_associated
    _files_label = staticmethod(xefm_app.XeFMApp._files_label)


@pytest.fixture
def app(monkeypatch):
    def make(desktop, local=True, popen=None):
        monkeypatch.setattr(xefm_app, "is_desktop_mode", lambda: desktop)
        FakeApp._current_local = local
        a = FakeApp()
        a.popen_calls = []

        def fake_popen(argv, *args, **kwargs):
            a.popen_calls.append(argv)
            if popen is not None:
                raise popen
            return object()

        monkeypatch.setattr(xefm_app.subprocess, "Popen", fake_popen)
        # Resolving the program against PATH (#345) is orthogonal to the
        # handover decision under test; pin it away so the argv assertions
        # read as the argv that was written, whatever this machine has
        # installed. TestPathResolution below covers the resolution itself.
        monkeypatch.setattr(shutil, "which", lambda cmd, path=None: None)
        return a
    return make


class TestTerminalMode:
    def test_hands_over_the_display_and_waits(self, app):
        a = app(desktop=False)
        assert a.launch([FakeEntry()], ["less"]) is True
        assert a.ran_in_terminal == ["less", "/home/me/a.log"]
        assert a.popen_calls == [], "must not detach in terminal mode"

    def test_gui_launcher_also_goes_through_the_handover(self, app):
        """`open -a` returns immediately, so waiting for it is cheap — and it
        is what lets one entry mix terminal and GUI programs freely."""
        a = app(desktop=False)
        a.launch([FakeEntry("/x/photo.png")], ["open", "-a", "Preview"])
        assert a.ran_in_terminal == ["open", "-a", "Preview", "/x/photo.png"]


class TestDesktopMode:
    def test_detaches_and_never_blocks(self, app):
        a = app(desktop=True)
        assert a.launch([FakeEntry()], ["code"]) is True
        assert a.popen_calls == [["code", "/home/me/a.log"]]
        assert a.ran_in_terminal is None, "no tty to hand over in desktop mode"

    def test_missing_program_reports_and_fails(self, app):
        a = app(desktop=True, popen=FileNotFoundError())
        assert a.launch([FakeEntry()], ["nope"]) is False
        assert "Command not found: nope" in a.logged[0]

    def test_other_launch_errors_are_logged_not_raised(self, app):
        a = app(desktop=True, popen=PermissionError("denied"))
        assert a.launch([FakeEntry()], ["blocked"]) is False
        assert "Failed to open a.log" in a.logged[0]


class TestPathResolution:
    def test_desktop_launch_runs_the_program_by_full_path(self, app, monkeypatch):
        """Windows' CreateProcess searches PATH but only ever appends ``.exe``,
        so a bare ``code`` never finds the ``code.cmd`` a scoop shim leaves
        there. Hand the launch the path PATHEXT-aware lookup found (#345)."""
        a = app(desktop=True)
        monkeypatch.setattr(shutil, "which",
                            lambda cmd, path=None: r"C:\shims\code.cmd")
        assert a.launch([FakeEntry()], ["code"]) is True
        assert a.popen_calls == [[r"C:\shims\code.cmd", "/home/me/a.log"]]


class TestNonLocalPaths:
    @pytest.mark.parametrize("desktop", [True, False])
    def test_remote_entries_refuse_in_either_mode(self, app, desktop):
        """An external program needs a real path on disk; returning False lets
        the caller fall back to the built-in viewer, which *can* read them."""
        a = app(desktop=desktop, local=False)
        entry = FakeEntry("s3://bucket/notes.txt")
        assert a.launch([entry], ["less"]) is False
        assert a.ran_in_terminal is None
        assert a.popen_calls == []
        assert "need a local file" in a.logged[0]


class TestArgv:
    def test_the_path_is_appended_to_the_command(self, app):
        a = app(desktop=True)
        a.launch([FakeEntry("/x/y.pdf")], ["open", "-a", "Preview"])
        assert a.popen_calls[0] == ["open", "-a", "Preview", "/x/y.pdf"]

    def test_a_batch_is_one_launch_with_every_path(self, app):
        """Several entries (a multi-file E, #273) become one argv, in order."""
        a = app(desktop=True)
        a.launch([FakeEntry("/x/a.md"), FakeEntry("/x/b.md")], ["mdedit"])
        assert a.popen_calls == [["mdedit", "/x/a.md", "/x/b.md"]]

    def test_the_configured_command_is_not_mutated(self, app):
        """The command comes straight from the user's config dict; appending
        in place would corrupt it for every later launch."""
        a = app(desktop=True)
        command = ["open", "-a", "Preview"]
        a.launch([FakeEntry()], command)
        assert command == ["open", "-a", "Preview"]
