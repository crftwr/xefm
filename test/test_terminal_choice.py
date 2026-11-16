"""Which terminal the desktop app runs things in (#900): XeFM's own unless
config.py names a TERMINAL application."""

from types import SimpleNamespace

import pytest

from xefm import terminal


@pytest.mark.parametrize("value", [None, [], ""])
def test_no_terminal_application_leaves_it_to_xefm_s_own(value):
    config = SimpleNamespace(TERMINAL=value)
    assert not terminal.chosen_elsewhere(config)
    # Whatever stops XeFM's terminal here, it is not the configuration.
    assert terminal.unavailable(config) != "TERMINAL is set in config.py"


@pytest.mark.parametrize("value", [["wezterm", "start", "--"], "wezterm start --",
                                   ["wt.exe", "-w", "0", "nt"]])
def test_a_terminal_application_is_always_used(value):
    config = SimpleNamespace(TERMINAL=value)
    assert terminal.chosen_elsewhere(config)
    assert terminal.unavailable(config) == "TERMINAL is set in config.py"


def test_a_config_without_the_field_counts_as_none():
    assert not terminal.chosen_elsewhere(SimpleNamespace())
