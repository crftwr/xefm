"""Resolving a launched program's name against PATH.

Every XeFM launch — TEXT_EDITOR, a file association, an external program, the
sub-shell, the diff tool — goes through ``resolve_command`` first, because
Windows' ``CreateProcess`` (what ``subprocess`` calls) searches PATH but only
ever appends ``.exe``: it never reads PATHEXT. A bare ``code`` therefore misses
the ``code.cmd`` that a scoop shim, or VS Code's own installer, leaves on PATH,
and the launch failed with "Command not found" even though the same name ran
from XeFM's sub-shell, where cmd.exe *does* read PATHEXT (#345).

``shutil.which`` reads PATHEXT, so the stub these tests put on PATH is named
the way each platform would name it: ``prog.cmd`` on Windows — the case that
regressed — and a plain executable ``prog`` elsewhere.

Run with: python -m pytest test/test_command_resolution.py -v
"""

import os
import stat
import sys

import pytest

from xefm.external_programs import resolve_command


@pytest.fixture
def on_path(tmp_path):
    """A runnable ``prog`` in a directory of its own; returns (env, path)."""
    stub = tmp_path / ("prog.cmd" if sys.platform == "win32" else "prog")
    stub.write_text("@echo off\n" if sys.platform == "win32" else "#!/bin/sh\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"PATH": str(tmp_path)}, str(stub)


def test_a_bare_name_becomes_the_full_path_path_answers_with(on_path):
    env, stub = on_path
    assert resolve_command(["prog"], env) == [stub]


def test_the_arguments_ride_along_untouched(on_path):
    env, stub = on_path
    assert resolve_command(["prog", "-n", "a b.txt"], env) == [stub, "-n", "a b.txt"]


def test_the_launch_environment_is_the_one_searched(on_path, monkeypatch):
    """``ensure_common_paths_in_env`` adds to the *child's* PATH — a lookup
    against ours would not see what it added (and POSIX subprocess searches the
    child's PATH too)."""
    env, stub = on_path
    monkeypatch.setenv("PATH", os.path.dirname(os.__file__))
    assert resolve_command(["prog"], env) == [stub]


def test_without_an_environment_our_own_path_is_searched(on_path, monkeypatch):
    env, stub = on_path
    monkeypatch.setenv("PATH", env["PATH"])
    assert resolve_command(["prog"]) == [stub]


def test_a_name_path_cannot_answer_is_left_alone(on_path):
    """Not an error to raise here: the launch goes ahead and fails the way it
    always has, so callers still report *what the user wrote* from the
    resulting FileNotFoundError rather than a path we invented."""
    env, _ = on_path
    assert resolve_command(["nosuchprog", "x"], env) == ["nosuchprog", "x"]


def test_the_configured_command_is_never_mutated(on_path):
    """FILE_ASSOCIATIONS and EXTERNAL_PROGRAMS hand us the list held in the
    user's config; it has to survive being launched more than once."""
    env, stub = on_path
    configured = ["prog", "--flag"]
    assert resolve_command(configured, env)[0] == stub
    assert configured == ["prog", "--flag"]


def test_an_empty_command_is_handed_back_empty(on_path):
    env, _ = on_path
    assert resolve_command([], env) == []
