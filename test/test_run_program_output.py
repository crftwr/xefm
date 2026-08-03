"""
External programs launched from the picker (``_run_program``) must set the
XEFM_* environment variables and stream the child's stdout/stderr into the
log-pane queue instead of letting it write to the terminal — a direct write
corrupts the curses screen in TUI mode and is lost in desktop mode.

Run with: python -m pytest test/test_run_program_output.py -v
"""

import os
import queue
import shutil
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.external_programs import build_xefm_env  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from puikit.backends import create_backend  # noqa: E402


class TestBuildXefmEnv(unittest.TestCase):
    """Unit tests for the shared XEFM_* environment builder"""

    def test_build_xefm_env(self):
        left = {'path': Path('/L'), 'selected_files': ['/L/a.txt', '/L/b c.txt'],
                'files': [], 'focused_index': 0}
        right = {'path': Path('/R'), 'selected_files': [],
                 'files': [Path('/R/x.txt')], 'focused_index': 0}

        env = build_xefm_env(left, right, left, right)

        self.assertEqual(env['XEFM_LEFT_DIR'], '/L')
        self.assertEqual(env['XEFM_RIGHT_DIR'], '/R')
        self.assertEqual(env['XEFM_THIS_DIR'], '/L')
        self.assertEqual(env['XEFM_OTHER_DIR'], '/R')
        self.assertEqual(env['XEFM_LEFT_SELECTED'], '"a.txt" "b c.txt"')
        self.assertEqual(env['XEFM_THIS_SELECTED'], '"a.txt" "b c.txt"')
        # No selection on the right: the focused file is substituted.
        self.assertEqual(env['XEFM_RIGHT_SELECTED'], '"x.txt"')
        self.assertEqual(env['XEFM_ACTIVE'], '1')


class RunProgramBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfgdir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def collect_log_lines(self, until, timeout=15.0):
        """Drain the app's log queue until ``until(lines)`` is satisfied."""
        lines = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                lines.append(self.app._log_queue.get(timeout=0.1))
            except queue.Empty:
                pass
            if until(lines):
                return lines
        self.fail(f"Timed out waiting for program output; got: {lines}")


class TestRunProgramOutput(RunProgramBase):
    def test_env_vars_and_stdout_reach_log_queue(self):
        """The child sees XEFM_* variables; its stdout lands in the log queue"""
        program = {
            'name': 'Env Echo',
            'command': [sys.executable, '-c',
                        "import os\n"
                        "print('THIS=' + os.environ.get('XEFM_THIS_DIR', ''))\n"
                        "print('ACTIVE=' + os.environ.get('XEFM_ACTIVE', ''))"],
        }
        self.app._run_program(program)

        lines = self.collect_log_lines(
            lambda ls: any(l[1].startswith('ACTIVE=') for l in ls))
        stdout_lines = [l[1] for l in lines if l[0] == 'STDOUT']
        # realpath both sides: on macOS the pane resolves /var → /private/var.
        this_dirs = [os.path.realpath(l[len('THIS='):]) for l in stdout_lines
                     if l.startswith('THIS=')]
        self.assertIn(os.path.realpath(self.tmp), this_dirs)
        self.assertIn('ACTIVE=1', stdout_lines)

    def test_stderr_and_exit_code_reach_log_queue(self):
        """stderr is routed with its own tag; a nonzero exit is reported"""
        program = {
            'name': 'Failing Tool',
            'command': [sys.executable, '-c',
                        "import sys\n"
                        "print('boom', file=sys.stderr)\n"
                        "sys.exit(3)"],
        }
        self.app._run_program(program)

        lines = self.collect_log_lines(
            lambda ls: any('exited with code 3' in l[1] for l in ls))
        stderr_lines = [l[1] for l in lines if l[0] == 'STDERR']
        self.assertIn('boom', stderr_lines)
        self.assertIn("'Failing Tool' exited with code 3", stderr_lines)


if __name__ == '__main__':
    unittest.main()
