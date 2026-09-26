"""A command's output as a file list (#453 ③, ``import_list_from_command``).

:mod:`xefm.command_list` runs a real subprocess through the shell here — the
current Python, so the tests need nothing installed — and the app half is
driven headless on the ``memory`` backend, as ``test_path_list.py`` does.

Run with: python -m pytest test/test_command_list.py -v
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import command_list, path_list  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


def py(code: str) -> str:
    """A shell command line running ``code`` in this Python. ``code`` must not
    contain double quotes: the same line goes through ``sh`` and ``cmd.exe``."""
    return f'"{sys.executable}" -c "{code}"'


class Decode(unittest.TestCase):
    def test_utf8(self):
        self.assertEqual(path_list.decode("a/日本.txt\n".encode()),
                         "a/日本.txt\n")

    def test_a_byte_order_mark_is_dropped(self):
        self.assertEqual(path_list.decode(b"\xef\xbb\xbfa.txt\n"), "a.txt\n")

    @unittest.skipUnless(sys.platform == "win32", "Windows code pages")
    def test_windows_falls_back_to_the_ansi_code_page(self):
        data = "café.txt\n".encode("cp1252")      # not valid UTF-8
        self.assertEqual(path_list.decode(data),
                         data.decode("mbcs", errors="replace"))

    @unittest.skipIf(sys.platform == "win32", "POSIX filesystem encoding")
    def test_posix_keeps_undecodable_names_addressable(self):
        raw = b"caf\xe9.txt"            # Latin-1, not UTF-8
        text = path_list.decode(raw + b"\n")
        self.assertEqual(os.fsencode(text.rstrip("\n")), raw)


class Run(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.cwd, ignore_errors=True)

    def _run(self, command, **kwargs):
        return command_list.run(command, cwd=self.cwd, env=dict(os.environ), **kwargs)

    def test_stdout_is_kept_and_lines_are_counted(self):
        counts = []
        out = self._run(py(r"import sys; sys.stdout.write('a\nb\nc\n')"),
                        on_count=counts.append)
        self.assertEqual(out.stdout.splitlines(), ["a", "b", "c"])
        self.assertEqual(out.code, 0)
        self.assertFalse(out.cancelled)
        self.assertEqual(counts[-1], 3)

    def test_it_runs_in_the_directory_it_is_given(self):
        out = self._run(py("import os; print(os.getcwd())"))
        self.assertEqual(os.path.normcase(os.path.realpath(out.stdout.strip())),
                         os.path.normcase(os.path.realpath(self.cwd)))

    def test_the_exit_code_and_the_end_of_stderr_come_back(self):
        out = self._run(py(r"import sys; sys.stderr.write('\n'.join("
                           r"str(i) for i in range(20))); sys.exit(3)"))
        self.assertEqual(out.code, 3)
        self.assertEqual(out.stderr_tail, [str(i) for i in range(15, 20)])

    def test_the_shell_is_in_the_middle(self):
        # A pipe is the shell's, not the program's.
        out = self._run(py(r"print('x')") + " | " + py(
            "import sys; print(sys.stdin.read().strip() + 'y')"))
        self.assertEqual(out.stdout.strip(), "xy")

    @unittest.skipUnless(sys.platform == "win32", "console code pages")
    def test_a_console_program_is_asked_for_utf8(self):
        # es.exe and dir /b write in the console's code page; on an English
        # system that is cp437, where a Japanese name is gone before it is read.
        out = self._run(py("import ctypes; "
                           "print(ctypes.windll.kernel32.GetConsoleOutputCP())"))
        self.assertEqual(out.stdout.strip(), "65001")

    @unittest.skipUnless(sys.platform == "win32", "cmd.exe")
    def test_cmd_dir_keeps_a_japanese_name(self):
        name = "設計メモ.md"
        open(os.path.join(self.cwd, name), "w").close()
        out = self._run("dir /b")
        self.assertEqual(out.stdout.splitlines(), [name])

    @unittest.skipUnless(sys.platform == "win32", "cmd.exe")
    def test_the_command_is_parsed_once_as_at_a_prompt(self):
        # %VAR% expands, ! stays (Everything's NOT), a quoted | is not a pipe,
        # ^& is a literal ampersand, && chains.
        env = dict(os.environ, XEFM_X="expanded")
        out = command_list.run('echo !NOT! %XEFM_X% "a|b" ^& done && echo next',
                               cwd=self.cwd, env=env)
        self.assertEqual([line.strip() for line in out.stdout.splitlines()],
                         ['!NOT! expanded "a|b" & done', "next"])

    @unittest.skipUnless(sys.platform == "win32", "cmd.exe")
    def test_the_exit_code_is_the_commands_not_chcps(self):
        out = self._run(py("raise SystemExit(4)") + " && echo never")
        self.assertEqual(out.code, 4)
        self.assertEqual(out.stdout.strip(), "")

    def test_stdin_reads_eof_rather_than_waiting(self):
        start = time.monotonic()
        out = self._run(py("import sys; print(len(sys.stdin.read()))"))
        self.assertEqual(out.stdout.strip(), "0")
        self.assertLess(time.monotonic() - start, 10)

    def test_cancel_stops_the_whole_tree(self):
        # The shell's child holds stdout open; if it survived the cancel, the
        # reader would wait on it and this would take the join timeout, or 30s.
        start = time.monotonic()
        deadline = start + 0.5
        out = self._run(py("import time; time.sleep(30)"),
                        cancelled=lambda: time.monotonic() > deadline)
        self.assertTrue(out.cancelled)
        self.assertLess(time.monotonic() - start, 4.5)

    def test_a_command_that_cannot_start(self):
        out = command_list.run("anything", cwd=os.path.join(self.cwd, "nowhere"),
                               env=dict(os.environ))
        self.assertIsNone(out.code)
        self.assertTrue(out.error)


class AppCommand(unittest.TestCase):
    def setUp(self):
        from puikit.backends import create_backend
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.pane = self.app.active_pane()

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _write(self, rel):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")
        return p

    def _run(self, command):
        self.app._run_list_command(self.app.pm.active_pane, command)
        # The task runs on a worker where the backend drives frame ticks;
        # wait for it to hand over, then for the listing it starts.
        deadline = time.monotonic() + 10
        while self.app.tasks.has_active() and time.monotonic() < deadline:
            self.b.run_animation_ticks()
            time.sleep(0.01)
        self.b.run_animation_ticks()
        self.app._settle_listings()

    def _logs(self):
        self.app._drain_captured_output()
        return [text for text, _style in self.app.log.lines]

    def test_the_lines_a_command_prints_become_the_pane(self):
        self._write(os.path.join("src", "a.py"))
        self._write(os.path.join("src", "b.py"))
        command = py(r"print('src/a.py'); print('src/b.py'); print('src/gone.py')")
        self._run(command)
        virtual = self.pane["virtual"]
        self.assertEqual(virtual["kind"], "list")
        self.assertEqual(virtual["title"], command)
        self.assertEqual(sorted(f.name for f in self.pane["files"]), ["a.py", "b.py"])
        self.assertEqual(str(virtual["root"]), str(Path(os.path.join(self.tmp, "src"))))
        self.assertTrue(any("1 not found" in line for line in self._logs()))

    def test_the_last_command_is_remembered(self):
        command = py("print()")
        self._run(command)
        self.assertEqual(self.sm.get_state(self.app._LIST_COMMAND_STATE), command)

    def test_nothing_printed_leaves_the_pane_and_says_why(self):
        before = list(self.pane["files"])
        self._run(py("import sys; sys.stderr.write('no match'); sys.exit(1)"))
        self.assertIsNone(self.pane["virtual"])
        self.assertEqual(self.pane["files"], before)
        logs = self._logs()
        self.assertTrue(any("printed no paths (exit code 1)" in line for line in logs))
        self.assertIn("no match", logs)

    def test_a_nonzero_exit_with_output_still_shows_it(self):
        a = self._write("a.txt")
        self._run(py(f"print(r'{a}'); raise SystemExit(1)"))
        self.assertEqual([str(f) for f in self.pane["files"]], [a])

    def test_a_remote_pane_refuses(self):
        self.pane["path"] = Path("s3://bucket/dir")
        self.app.import_list_from_command()
        self.assertIn("run in a local directory", self._logs()[-1])


if __name__ == "__main__":
    unittest.main()
