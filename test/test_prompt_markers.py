"""The ``[XeFM]`` prompt marker follows the shell that is actually launched.

``PROMPT`` is claimed by two unrelated shells: zsh reads it with ``%``-codes,
cmd.exe with ``$``-codes. Writing zsh's default unconditionally made a cmd.exe
subshell (``SUBSHELL = ["cmd.exe"]``) display the format string literally as
``[XeFM] %n@%m:%~%#``. PowerShell reads neither variable — its prompt is a
function — so it gets no marker rather than a misleading one.

Run with: python -m pytest test/test_prompt_markers.py -v
"""

import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm.external_programs import prefix_prompt_markers, shell_family  # noqa: E402


class ShellFamily(unittest.TestCase):
    def test_cmd_by_name_path_and_case(self):
        for command in (["cmd.exe"], ["cmd"], ["CMD.EXE"],
                        ["C:\\Windows\\system32\\cmd.exe"]):
            self.assertEqual(shell_family(command), "cmd", command)

    def test_powershell(self):
        self.assertEqual(shell_family(["powershell.exe", "-NoLogo"]), "powershell")
        self.assertEqual(shell_family(["pwsh"]), "powershell")

    def test_posix_shells(self):
        for command in (["/bin/sh"], ["/bin/bash"], ["/usr/bin/zsh"], ["fish"],
                        ["C:\\Program Files\\Git\\bin\\bash.exe"]):
            self.assertEqual(shell_family(command), "posix", command)

    def test_unknown_shell_follows_the_platform(self):
        with mock.patch.object(os, "name", "nt"):
            self.assertEqual(shell_family(["mystery"]), "cmd")
        with mock.patch.object(os, "name", "posix"):
            self.assertEqual(shell_family(["mystery"]), "posix")

    def test_no_command_follows_the_platform(self):
        with mock.patch.object(os, "name", "posix"):
            self.assertEqual(shell_family(None), "posix")
            self.assertEqual(shell_family([]), "posix")


class CmdExe(unittest.TestCase):
    def test_unset_prompt_gets_cmds_own_default(self):
        env = {}
        prefix_prompt_markers(env, ["cmd.exe"])
        self.assertEqual(env["PROMPT"], "[XeFM] $P$G")

    def test_an_existing_prompt_is_prefixed_not_replaced(self):
        env = {"PROMPT": "$P$_$G"}
        prefix_prompt_markers(env, ["cmd.exe"])
        self.assertEqual(env["PROMPT"], "[XeFM] $P$_$G")

    def test_no_zsh_format_string_reaches_cmd(self):
        env = {}
        prefix_prompt_markers(env, ["cmd.exe"])
        self.assertNotIn("%", env["PROMPT"])

    def test_ps1_is_left_alone(self):
        env = {"PS1": "\\u@\\h\\$ "}
        prefix_prompt_markers(env, ["cmd.exe"])
        self.assertEqual(env["PS1"], "\\u@\\h\\$ ")


class PowerShell(unittest.TestCase):
    def test_neither_variable_is_touched(self):
        env = {"PROMPT": "$P$G", "PS1": "x"}
        prefix_prompt_markers(env, ["pwsh"])
        self.assertEqual(env, {"PROMPT": "$P$G", "PS1": "x"})


class PosixShells(unittest.TestCase):
    def test_unset_variables_get_the_per_shell_defaults(self):
        env = {}
        prefix_prompt_markers(env, ["/bin/zsh"])
        self.assertEqual(env["PS1"], "[XeFM] \\u@\\h:\\w\\$ ")
        self.assertEqual(env["PROMPT"], "[XeFM] %n@%m:%~%# ")

    def test_existing_variables_are_prefixed(self):
        env = {"PS1": "$ ", "PROMPT": "%# "}
        prefix_prompt_markers(env, ["/bin/bash"])
        self.assertEqual(env["PS1"], "[XeFM] $ ")
        self.assertEqual(env["PROMPT"], "[XeFM] %# ")

    def test_the_old_no_command_call_still_works_on_posix(self):
        with mock.patch.object(os, "name", "posix"):
            env = {}
            prefix_prompt_markers(env)
        self.assertTrue(env["PS1"].startswith("[XeFM] "))
        self.assertTrue(env["PROMPT"].startswith("[XeFM] "))


if __name__ == "__main__":
    unittest.main()
