"""How an associated external program is launched.

Unmarked, the one decision this makes is display handover, and it is
answered by the *backend*:

* terminal mode - suspend, run, wait, restore (``less`` and ``vim`` need this)
* desktop mode  - start it in the background, never block the event loop (no
  tty exists to release)

A command marked ``{'command': ..., 'terminal': True/False}`` overrides that
(#900; see test_configured_commands.py). Exercised against a real ``XeFMApp``
over the memory backend, so the method under test is production code rather
than a restatement of it.
"""

import shutil
from unittest.mock import patch

import pytest

from test_customization_api import app_with, config_with  # noqa: F401
from xefm import app as xefm_app


class FakeEntry:
    def __init__(self, path="/home/me/a.log"):
        self._path = path
        self.name = path.rsplit("/", 1)[-1]

    def __str__(self):
        return self._path


@pytest.fixture
def app(app_with, monkeypatch):
    def make(desktop, local=True, popen=None):
        real, _ = app_with()
        monkeypatch.setattr(xefm_app, "is_desktop_mode", lambda: desktop)
        monkeypatch.setattr(real, "_is_local", lambda entry: local)
        real.logged = []
        monkeypatch.setattr(real, "log_info", real.logged.append)
        real.ran_in_terminal = None

        def hand_over(argv, cwd=None, env=None, pause_on_error=False):
            real.ran_in_terminal = argv
            return 0
        monkeypatch.setattr(real, "_run_in_terminal", hand_over)
        real.popen_calls = []

        import io

        class _Proc:
            def __init__(self):
                self.stdout, self.stderr = io.StringIO(), io.StringIO()

            def wait(self):
                return 0

        def fake_popen(argv, *args, **kwargs):
            real.popen_calls.append(argv)
            if popen is not None:
                raise popen
            return _Proc()

        monkeypatch.setattr(xefm_app.subprocess, "Popen", fake_popen)
        # Resolving the program against PATH (#345) is orthogonal to the
        # handover decision under test; pin it away so the argv assertions
        # read as the argv that was written, whatever this machine has
        # installed. TestPathResolution below covers the resolution itself.
        monkeypatch.setattr(shutil, "which", lambda cmd, path=None: None)
        real.launch = real._launch_associated
        return real
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

    def test_marked_false_runs_in_the_background_here_too(self, app):
        a = app(desktop=False)
        assert a.launch([FakeEntry()], ["code"], False) is True
        assert a.popen_calls == [["code", "/home/me/a.log"]]
        assert a.ran_in_terminal is None


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
        assert "Failed to launch a.log" in a.logged[0]

    def test_marked_true_runs_in_a_terminal_session(self, app):
        a = app(desktop=True)
        with patch.object(a, "_terminal_unavailable", return_value=None), \
                patch.object(a, "_start_session") as start:
            assert a.launch([FakeEntry()], ["less"], True) is True
        assert start.call_args.args[0] == ["less", "/home/me/a.log"]
        assert a.popen_calls == []


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
