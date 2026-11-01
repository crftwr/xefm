"""``xefm keys`` (#801): what each key does, read without starting XeFM.

Pinned here: a key name or action name XeFM would not understand is an error
(and the exit status says so), a good binding is listed in the context it is
reached in, the preset is the one XeFM would use, and nothing is written to
the home it reads.

Run with: python -m pytest test/test_keys_cli.py -v
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm import keys_cli  # noqa: E402
from xefm import log_manager  # noqa: E402
from xefm.actions import registry  # noqa: E402
from xefm.config import key_problem  # noqa: E402

_TEMPLATE = Path(keys_cli.__file__).parent / "_config.py"


def _config_with(bindings: str) -> str:
    """XeFM's template with ``bindings`` (lines of a dict body) at the top of
    its KEY_BINDINGS."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    anchor = "    KEY_BINDINGS = {\n"
    assert anchor in text
    return text.replace(anchor, anchor + bindings, 1)


class KeyProblemTest(unittest.TestCase):
    def test_known_keys(self):
        for expr in ("F12", "Ctrl-T", "Shift-EQUAL", "?", "g g", "Cmd-ENTER", "MINUS"):
            self.assertIsNone(key_problem(expr), expr)

    def test_unknown_keys(self):
        self.assertIn("unknown key 'F13'", key_problem("F13"))
        self.assertIn("unknown modifier 'Hyper'", key_problem("Hyper-T"))
        self.assertIn("key sequence", key_problem("F 12"))
        self.assertIn("MINUS", key_problem("Ctrl--"))
        self.assertIn("is not a key", key_problem(""))
        self.assertIn("is not a key", key_problem(12))


class KeysCliTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(os.path.realpath(tempfile.mkdtemp(prefix="xefm-keys-")))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.home / ".xefm").mkdir()
        env = unittest.mock.patch.dict(os.environ, {"HOME": str(self.home),
                                                    "USERPROFILE": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(registry.unregister_source, "user")
        self.addCleanup(log_manager.clear_log_sink)
        self.addCleanup(setattr, sys, "dont_write_bytecode", sys.dont_write_bytecode)

    def write_config(self, bindings: str) -> None:
        (self.home / ".xefm" / "config.py").write_text(_config_with(bindings),
                                                      encoding="utf-8")

    def run_keys(self, *argv) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = keys_cli.main(list(argv))
        return status, out.getvalue() + err.getvalue()

    def test_a_good_binding_is_listed_where_it_is_reached(self):
        self.write_config("        'reload_config': ['F12'],\n")
        status, out = self.run_keys("F12")
        self.assertEqual(status, 0, out)
        self.assertIn("[filer]", out)
        self.assertRegex(out, r"F12\s+reload_config")
        self.assertNotIn("error:", out)

    def test_an_unknown_key_name_is_an_error(self):
        self.write_config("        'reload_config': ['F 12'],\n")
        status, out = self.run_keys()
        self.assertEqual(status, 1)
        self.assertIn("error: KEY_BINDINGS['reload_config']: 'F 12': unknown key '12'", out)
        self.assertIn("never fires", out)

    def test_an_unknown_action_is_an_error_with_a_suggestion(self):
        self.write_config("        'relod_config': ['F12'],\n")
        status, out = self.run_keys("F12")
        self.assertEqual(status, 1)
        self.assertIn("no action is called 'relod_config' — did you mean "
                      "'reload_config'?", out)

    def test_a_malformed_entry_is_an_error(self):
        self.write_config("        'reload_config': 'F12',\n"
                          "        'quit': {'keys': ['Q'], 'selection': 'some'},\n")
        status, out = self.run_keys()
        self.assertEqual(status, 1)
        self.assertIn("KEY_BINDINGS['reload_config']: the keys are a list", out)
        self.assertIn("KEY_BINDINGS['quit']: selection is", out)

    def test_a_config_that_does_not_load_is_an_error(self):
        (self.home / ".xefm" / "config.py").write_text("raise RuntimeError('boom')\n",
                                                       encoding="utf-8")
        status, out = self.run_keys()
        self.assertEqual(status, 1)
        self.assertIn("does not load", out)
        self.assertIn("boom", out)

    def test_an_unbound_name_given_exits_1(self):
        self.write_config("")
        status, out = self.run_keys("reload_config", "--keymap", "afx")
        self.assertEqual(status, 1)
        self.assertIn("not bound in any context", out)

    def test_a_name_that_is_neither_is_a_usage_error(self):
        self.write_config("")
        status, out = self.run_keys("F13")
        self.assertEqual(status, 2)
        self.assertIn("unknown key 'F13'", out)
        status, out = self.run_keys("relod_config")
        self.assertEqual(status, 2)
        self.assertIn("did you mean 'reload_config'", out)

    def test_the_preset_chosen_in_xefm_is_used(self):
        from xefm.state_manager import StateManager
        self.write_config("")
        StateManager(self.home / ".xefm" / "state.db").set_state("keymap.preset",
                                                                 "orthodox")
        status, out = self.run_keys("copy_files", "--context", "filer")
        self.assertIn("keymap:  orthodox (chosen in XeFM)", out)
        self.assertRegex(out, r"F5\s+copy_files")
        status, out = self.run_keys("copy_files", "--keymap", "afx")
        self.assertIn("keymap:  afx (--keymap)", out)
        self.assertNotRegex(out, r"F5\s+copy_files")

    def test_no_preset_chosen_says_so(self):
        self.write_config("")
        status, out = self.run_keys("quit")
        self.assertIn("none chosen yet", out)

    def test_nothing_is_written(self):
        self.write_config("        'reload_config': ['F12'],\n")
        before = sorted(p.relative_to(self.home) for p in self.home.rglob("*"))
        self.run_keys()
        after = sorted(p.relative_to(self.home) for p in self.home.rglob("*"))
        self.assertEqual(before, after)

    def test_a_missing_home_config_shows_the_template(self):
        status, out = self.run_keys("quit")
        self.assertIn("XeFM's template is shown", out)
        self.assertFalse((self.home / ".xefm" / "config.py").exists())

    def test_usage_errors(self):
        self.assertEqual(self.run_keys("--keymap", "emacs")[0], 2)
        self.assertEqual(self.run_keys("--context", "nowhere")[0], 2)
        self.assertEqual(self.run_keys("--config", str(self.home / "nope.py"))[0], 2)


if __name__ == "__main__":
    unittest.main()
