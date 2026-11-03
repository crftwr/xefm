"""--backend curses: refused on Windows, a warning elsewhere (PuiKit 1.19.0 deprecated it)."""

import pytest

from xefm.app import _curses_backend_notice


@pytest.mark.parametrize("backend", ["tui", "gui", "web"])
def test_other_backends_say_nothing(backend):
    assert _curses_backend_notice(backend, "win32") is None
    assert _curses_backend_notice(backend, "darwin") is None


def test_windows_is_told_to_use_tui():
    notice = _curses_backend_notice("curses", "win32")
    assert "not supported on Windows" in notice and "--backend tui" in notice


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_elsewhere_it_runs_with_a_deprecation_warning(platform):
    notice = _curses_backend_notice("curses", platform)
    assert "deprecated" in notice and "PuiKit 2.0" in notice and "--backend tui" in notice
