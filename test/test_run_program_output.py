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
from unittest.mock import Mock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.external_programs import (build_xefm_env, get_focused_file,  # noqa: E402
                                    get_selected_or_cursor_files, shell_family)
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
        # No selection on the right: *_SELECTED is empty, and the focused file
        # is reported by *_FOCUSED alone (#348).
        self.assertEqual(env['XEFM_RIGHT_SELECTED'], '')
        self.assertEqual(env['XEFM_RIGHT_FOCUSED'], '"x.txt"')
        self.assertEqual(env['XEFM_ACTIVE'], '1')

    def test_focused_is_independent_of_the_selection(self):
        """*_FOCUSED names the item under the cursor whether or not anything is
        selected, which is what lets a program tell the two apart (#348)."""
        left = {'path': Path('/L'), 'selected_files': ['/L/a.txt', '/L/b c.txt'],
                'files': [Path('/L/a.txt'), Path('/L/b c.txt'), Path('/L/c.txt')],
                'focused_index': 2}
        right = {'path': Path('/R'), 'selected_files': [],
                 'files': [Path('/R/x.txt')], 'focused_index': 0}

        env = build_xefm_env(left, right, left, right)

        # A selection is live on the left, and the cursor sits off it.
        self.assertEqual(env['XEFM_LEFT_SELECTED'], '"a.txt" "b c.txt"')
        self.assertEqual(env['XEFM_LEFT_FOCUSED'], '"c.txt"')
        self.assertEqual(env['XEFM_THIS_FOCUSED'], '"c.txt"')
        # Nothing selected on the right: the cursor is *not* promoted into
        # *_SELECTED, which is the whole point of the pair.
        self.assertEqual(env['XEFM_RIGHT_SELECTED'], '')
        self.assertEqual(env['XEFM_RIGHT_FOCUSED'], '"x.txt"')
        self.assertEqual(env['XEFM_OTHER_FOCUSED'], '"x.txt"')

    def test_focused_is_empty_for_an_empty_pane(self):
        empty = {'path': Path('/E'), 'selected_files': [], 'files': [],
                 'focused_index': 0}

        env = build_xefm_env(empty, empty, empty, empty)

        self.assertEqual(env['XEFM_THIS_FOCUSED'], '')
        self.assertEqual(env['XEFM_THIS_SELECTED'], '')

    def test_get_focused_file_tolerates_an_out_of_range_cursor(self):
        pane = {'path': Path('/L'), 'selected_files': [],
                'files': [Path('/L/a.txt')], 'focused_index': 7}
        self.assertEqual(get_focused_file(pane), [])

    def test_argv_still_falls_back_to_the_cursor(self):
        """The command line keeps the single-answer rule: one argument list
        cannot express both, so it stays 'selection, else cursor'."""
        pane = {'path': Path('/L'), 'selected_files': [],
                'files': [Path('/L/a.txt'), Path('/L/b.txt')], 'focused_index': 1}
        self.assertEqual(get_selected_or_cursor_files(pane), ['b.txt'])
        pane['selected_files'] = ['/L/a.txt']
        self.assertEqual(get_selected_or_cursor_files(pane), ['a.txt'])


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


class TestTerminalOption(RunProgramBase):
    def test_terminal_option_hands_off_in_terminal_mode(self):
        """options {'terminal': True} diverts to _run_in_terminal with the env"""
        program = {'name': 'Less', 'command': ['less'],
                   'options': {'terminal': True}}
        with patch.object(self.app, '_run_in_terminal') as handoff, \
                patch('xefm.app.is_desktop_mode', return_value=False):
            self.app._run_program(program)

        handoff.assert_called_once()
        _, kwargs = handoff.call_args
        argv = handoff.call_args[0][0]
        self.assertEqual(argv[0], 'less')
        self.assertEqual(os.path.realpath(kwargs['cwd']),
                         os.path.realpath(self.tmp))
        self.assertEqual(kwargs['env']['XEFM_ACTIVE'], '1')
        self.assertIn('XEFM_THIS_DIR', kwargs['env'])
        self.assertTrue(kwargs['pause_on_error'])

    def test_terminal_option_opens_a_terminal_in_desktop_mode(self):
        """Desktop mode has no tty to hand over: the program gets a terminal
        window of its own (#472), with the same env, cwd and pause"""
        program = {'name': 'Echoer',
                   'command': [sys.executable, '-c', "print('piped output')"],
                   'options': {'terminal': True}}
        with patch.object(self.app, '_run_in_terminal') as handoff, \
                patch.object(self.app, 'log_info') as log, \
                patch('xefm.app.subprocess.Popen') as popen, \
                patch('xefm.external_terminal.launch_in_terminal') as launch, \
                patch('xefm.app.is_desktop_mode', return_value=True):
            self.app._run_program(program)

        handoff.assert_not_called()
        popen.assert_not_called()
        launch.assert_called_once()
        argv, kwargs = launch.call_args[0][1], launch.call_args[1]
        self.assertEqual(argv[:3], program['command'])
        self.assertEqual(os.path.realpath(kwargs['cwd']),
                         os.path.realpath(self.tmp))
        self.assertEqual(kwargs['env']['XEFM_ACTIVE'], '1')
        self.assertTrue(kwargs['pause_on_error'])
        self.assertIn('Echoer', log.call_args[0][0])

    def test_desktop_terminal_launch_failure_is_logged(self):
        """No terminal configured and no platform default: say which setting"""
        program = {'name': 'Less', 'command': ['less'],
                   'options': {'terminal': True}}
        with patch.object(self.app, 'log_info') as log, \
                patch('xefm.external_terminal.default_terminal',
                      return_value=None), \
                patch.object(self.app.config, 'TERMINAL', None, create=True), \
                patch('xefm.app.is_desktop_mode', return_value=True):
            self.app._run_program(program)
        self.assertIn('TERMINAL', log.call_args[0][0])

    def test_terminal_nonzero_exit_waits_for_enter(self):
        """pause_on_error holds the terminal until Enter on a nonzero exit"""
        with patch('builtins.input', return_value='') as enter:
            self.app._run_in_terminal(
                [sys.executable, '-c', 'import sys; sys.exit(2)'],
                pause_on_error=True)
        enter.assert_called_once()

    def test_terminal_zero_exit_returns_immediately(self):
        """A clean exit returns to XeFM without prompting"""
        with patch('builtins.input', return_value='') as enter:
            self.app._run_in_terminal(
                [sys.executable, '-c', 'pass'], pause_on_error=True)
        enter.assert_not_called()



class TestActionContextRunProgram(RunProgramBase):
    """``ctx.run_program()`` — the picker's launcher, reachable from an action
    so a program can have a key of its own (#454)."""

    def ctx(self):
        from xefm.user_api import ActionContext
        return ActionContext(self.app)

    def test_background_launch_gets_env_and_streams_output(self):
        """No file names appended; XEFM_* and the caller's env reach the child"""
        self.ctx().run_program(
            [sys.executable, '-c',
             "import os, sys\n"
             "print('ARGS=%d' % (len(sys.argv) - 1))\n"
             "print('EXTRA=' + os.environ.get('MY_VAR', ''))\n"
             "print('ACTIVE=' + os.environ.get('XEFM_ACTIVE', ''))"],
            env={'MY_VAR': 'hello'})

        lines = self.collect_log_lines(
            lambda ls: any(l[1].startswith('ACTIVE=') for l in ls))
        stdout_lines = [l[1] for l in lines if l[0] == 'STDOUT']
        self.assertIn('ARGS=0', stdout_lines)
        self.assertIn('EXTRA=hello', stdout_lines)
        self.assertIn('ACTIVE=1', stdout_lines)

    def test_terminal_hands_off_and_returns_the_exit_code(self):
        """terminal=True suspends via _run_in_terminal, in the pane's dir"""
        with patch.object(self.app, '_run_in_terminal',
                          return_value=7) as handoff, \
                patch('xefm.app.is_desktop_mode', return_value=False):
            code = self.ctx().run_program('massren --flag', terminal=True)

        self.assertEqual(code, 7)
        handoff.assert_called_once()
        argv = handoff.call_args[0][0]
        kwargs = handoff.call_args[1]
        self.assertEqual(argv, ['massren', '--flag'])
        self.assertEqual(os.path.realpath(kwargs['cwd']),
                         os.path.realpath(self.tmp))
        self.assertEqual(kwargs['env']['XEFM_ACTIVE'], '1')
        self.assertTrue(kwargs['pause_on_error'])

    def test_terminal_run_really_waits_for_the_child(self):
        """End to end through the memory backend's suspend: the code comes back"""
        with patch('xefm.app.is_desktop_mode', return_value=False), \
                patch('builtins.input', return_value=''):
            code = self.ctx().run_program(
                [sys.executable, '-c', 'import sys; sys.exit(4)'],
                terminal=True)
        self.assertEqual(code, 4)

    def test_terminal_opens_a_terminal_in_desktop_mode(self):
        with patch.object(self.app, '_run_in_terminal') as handoff, \
                patch('xefm.external_terminal.launch_in_terminal') as launch, \
                patch('xefm.app.is_desktop_mode', return_value=True):
            code = self.ctx().run_program(['vim'], terminal=True,
                                          env={'MY_VAR': 'hello'})

        self.assertIsNone(code)
        handoff.assert_not_called()
        self.assertEqual(launch.call_args[0][1], ['vim'])
        self.assertEqual(launch.call_args[1]['env']['MY_VAR'], 'hello')

    def test_an_explicit_cwd_wins(self):
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with patch.object(self.app, '_run_in_terminal') as handoff, \
                patch('xefm.app.is_desktop_mode', return_value=False):
            self.ctx().run_program(['ls'], terminal=True, cwd=other)
        self.assertEqual(handoff.call_args[1]['cwd'], other)

    def test_an_empty_command_is_an_error(self):
        with self.assertRaises(ValueError):
            self.ctx().run_program([])

class TestSubshellEnv(RunProgramBase):
    def _subshell(self, shell):
        """Run the subshell action with SUBSHELL pinned to ``shell`` — the
        app's config is the *user's* here, so the shell has to be forced for
        this to test anything stable — and return (argv, kwargs)."""
        with patch.object(self.app, '_run_in_terminal') as handoff, \
                patch.object(self.app.config, 'SUBSHELL', shell, create=True), \
                patch('xefm.app.is_desktop_mode', return_value=False):
            self.app.subshell()
        handoff.assert_called_once()
        return handoff.call_args[0][0], handoff.call_args[1]

    def test_subshell_gets_xefm_env_and_prompt_marker(self):
        """Shift-X hands the shell the XEFM_* variables and a [XeFM] prompt"""
        argv, kwargs = self._subshell('/bin/zsh')
        self.assertEqual(argv, ['/bin/zsh'])
        self.assertEqual(os.path.realpath(kwargs['cwd']),
                         os.path.realpath(self.tmp))
        env = kwargs['env']
        self.assertEqual(env['XEFM_ACTIVE'], '1')
        self.assertEqual(os.path.realpath(env['XEFM_THIS_DIR']),
                         os.path.realpath(self.tmp))
        self.assertIn('XEFM_LEFT_SELECTED', env)
        self.assertEqual(shell_family(argv), 'posix')
        self.assertTrue(env['PS1'].startswith('[XeFM] '))
        self.assertTrue(env['PROMPT'].startswith('[XeFM] '))

    def test_cmd_exe_gets_a_prompt_it_can_render(self):
        """A cmd.exe subshell must not be handed zsh's %-code prompt"""
        argv, kwargs = self._subshell(['cmd.exe'])
        self.assertEqual(argv, ['cmd.exe'])
        env = kwargs['env']
        self.assertEqual(env['XEFM_ACTIVE'], '1')
        self.assertEqual(env['PROMPT'], '[XeFM] $P$G')

    def test_subshell_opens_a_terminal_in_desktop_mode(self):
        """Desktop mode has no tty to hand over: SUBSHELL opens in the
        TERMINAL application, with the env and prompt marker (#472)"""
        with patch.object(self.app, '_run_in_terminal') as handoff, \
                patch.object(self.app.config, 'SUBSHELL', '/bin/zsh', create=True), \
                patch.object(self.app.config, 'TERMINAL', ['my-term', '-e'],
                             create=True), \
                patch('xefm.external_terminal.launch_in_terminal') as launch, \
                patch('xefm.app.is_desktop_mode', return_value=True):
            self.app.subshell()

        handoff.assert_not_called()
        launch.assert_called_once()
        terminal, argv = launch.call_args[0]
        kwargs = launch.call_args[1]
        self.assertEqual(terminal, ['my-term', '-e'])
        self.assertEqual(argv, ['/bin/zsh'])
        self.assertEqual(os.path.realpath(kwargs['cwd']),
                         os.path.realpath(self.tmp))
        self.assertEqual(kwargs['env']['XEFM_ACTIVE'], '1')
        self.assertTrue(kwargs['env']['PROMPT'].startswith('[XeFM] '))
        self.assertFalse(kwargs['pause_on_error'])


class TestAutoReturnDeprecation(unittest.TestCase):
    def _validate(self, programs):
        from xefm._config import Config
        from xefm.config import ConfigManager

        class UserConfig(Config):
            PROGRAMS = programs

        return ConfigManager().validate_config(UserConfig())

    def test_auto_return_triggers_config_warning(self):
        errors = self._validate([
            {'name': 'Old Tool', 'command': ['x'],
             'options': {'auto_return': True}},
        ])
        matches = [e for e in errors if 'auto_return' in e]
        self.assertEqual(len(matches), 1)
        self.assertIn('Old Tool', matches[0])
        self.assertIn('deprecated', matches[0])

    def test_default_config_carries_no_auto_return(self):
        from xefm._config import Config
        from xefm.config import ConfigManager
        errors = ConfigManager().validate_config(Config())
        self.assertEqual([e for e in errors if 'auto_return' in e], [])


if __name__ == '__main__':
    unittest.main()
