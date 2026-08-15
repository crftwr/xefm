"""Which shell the subshell action launches (issue #288).

The command comes from ``SUBSHELL`` in the config; unset, it falls back to
``$SHELL``, and then to the platform default — ``%COMSPEC%`` (cmd.exe) on
Windows, ``/bin/sh`` elsewhere. The old code used ``$SHELL`` with a hardwired
``/bin/sh`` fallback, which does not exist on Windows and could not be
changed.

Strings are taken as one argv entry, never shlex-split: a Windows path like
``C:\\Windows\\system32\\cmd.exe`` must survive intact.

Run with: python -m pytest test/test_subshell_command.py -v
"""

import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm.app import _subshell_command  # noqa: E402


class _Config:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class ConfigWins(unittest.TestCase):
    def test_a_string_is_one_argv_entry(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            self.assertEqual(_subshell_command(_Config(SUBSHELL="fish")), ["fish"])

    def test_a_list_carries_arguments(self):
        cmd = ["powershell", "-NoLogo"]
        self.assertEqual(_subshell_command(_Config(SUBSHELL=cmd)), cmd)
        # The caller gets a copy, not the config's own list.
        self.assertIsNot(_subshell_command(_Config(SUBSHELL=cmd)), cmd)

    def test_a_windows_path_is_never_shlex_split(self):
        path = "C:\\Windows\\system32\\cmd.exe"
        self.assertEqual(_subshell_command(_Config(SUBSHELL=path)), [path])

    def test_none_defers_to_the_environment(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            self.assertEqual(_subshell_command(_Config(SUBSHELL=None)), ["/bin/zsh"])

    def test_a_config_without_the_attribute_defers_too(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            self.assertEqual(_subshell_command(_Config()), ["/bin/zsh"])


class PlatformFallback(unittest.TestCase):
    def _without(self, *names):
        env = {k: v for k, v in os.environ.items() if k not in names}
        return mock.patch.dict(os.environ, env, clear=True)

    def test_posix_falls_back_to_bin_sh(self):
        with self._without("SHELL"), mock.patch.object(os, "name", "posix"):
            self.assertEqual(_subshell_command(_Config(SUBSHELL=None)), ["/bin/sh"])

    def test_windows_falls_back_to_comspec(self):
        path = "C:\\Windows\\system32\\cmd.exe"
        with self._without("SHELL"), mock.patch.object(os, "name", "nt"), \
                mock.patch.dict(os.environ, {"COMSPEC": path}):
            self.assertEqual(_subshell_command(_Config(SUBSHELL=None)), [path])

    def test_windows_without_comspec_still_finds_cmd(self):
        with self._without("SHELL", "COMSPEC"), mock.patch.object(os, "name", "nt"):
            self.assertEqual(_subshell_command(_Config(SUBSHELL=None)), ["cmd.exe"])

    def test_shell_env_wins_over_the_platform_default_even_on_windows(self):
        # A git-bash / MSYS user with $SHELL exported keeps their shell.
        with mock.patch.object(os, "name", "nt"), \
                mock.patch.dict(os.environ, {"SHELL": "/usr/bin/bash"}):
            self.assertEqual(_subshell_command(_Config(SUBSHELL=None)),
                             ["/usr/bin/bash"])


if __name__ == "__main__":
    unittest.main()
