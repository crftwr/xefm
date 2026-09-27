"""Desktop mode's external terminal (discussion #472).

The terminal application itself is never started here. What is tested is what
XeFM owns: which terminal, and the wrapper that carries the directory and the
environment across the hop. The wrappers are real scripts, so they are run for
real — ``sh`` for the POSIX one, this interpreter for the Windows one — with a
command that reports what it saw.
"""

import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from xefm import external_terminal as et


def _config(**kw):
    return types.SimpleNamespace(**kw)


#: A command that prints its cwd and one variable, then exits with a code.
def _probe(var, code=0):
    return [sys.executable, '-c',
            'import os, sys; print(os.getcwd()); '
            f'print(os.environ.get({var!r}, "<unset>")); sys.exit({code})']


class TestTerminalCommand(unittest.TestCase):

    def test_configured_string_is_split(self):
        self.assertEqual(et.terminal_command(_config(TERMINAL='wezterm start --')),
                         ['wezterm', 'start', '--'])

    def test_configured_list_is_taken_as_written(self):
        cmd = [r'C:\Program Files\Term\term.exe', '-e']
        self.assertEqual(et.terminal_command(_config(TERMINAL=cmd)), cmd)

    def test_unset_falls_back_to_the_platform_default(self):
        with patch.object(et, 'default_terminal', return_value=['t']):
            self.assertEqual(et.terminal_command(_config()), ['t'])
            self.assertEqual(et.terminal_command(_config(TERMINAL=None)), ['t'])

    def test_macos_default_is_terminal_app(self):
        with patch.object(et.sys, 'platform', 'darwin'):
            self.assertEqual(et.default_terminal(), ['open', '-a', 'Terminal'])

    def test_windows_prefers_windows_terminal(self):
        with patch.object(et.sys, 'platform', 'win32'), \
                patch.object(et.shutil, 'which', return_value=r'C:\wt.exe'):
            self.assertEqual(et.default_terminal(), ['wt.exe'])

    def test_windows_without_windows_terminal_uses_a_new_console(self):
        with patch.object(et.sys, 'platform', 'win32'), \
                patch.object(et.shutil, 'which', return_value=None):
            self.assertEqual(et.default_terminal(), [])

    def test_elsewhere_there_is_no_default(self):
        with patch.object(et.sys, 'platform', 'linux'):
            self.assertIsNone(et.default_terminal())


class TestDeliveredEnv(unittest.TestCase):

    def test_only_what_xefm_added_or_changed(self):
        env = dict(os.environ, XEFM_ACTIVE='1', PS1='[XeFM] $ ')
        delivered = et.delivered_env(env)
        self.assertEqual(delivered['XEFM_ACTIVE'], '1')
        self.assertEqual(delivered['PS1'], '[XeFM] $ ')
        self.assertNotIn('HOME', delivered)

    def test_path_is_left_to_the_terminals_shell(self):
        env = dict(os.environ, PATH='/opt/homebrew/bin:' + os.environ.get('PATH', ''))
        self.assertNotIn('PATH', et.delivered_env(env))


class WrapperCase(unittest.TestCase):

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(os.rmdir, self.dir)

    def write(self, text, suffix):
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path


@unittest.skipIf(os.name == 'nt', 'the POSIX wrapper needs /bin/sh')
class TestPosixWrapper(WrapperCase):

    def run_wrapper(self, argv, env, pause=False, stdin=''):
        path = self.write(et.posix_wrapper(argv, self.dir, env, pause), '.sh')
        result = subprocess.run(['/bin/sh', path], input=stdin, text=True,
                                capture_output=True)
        return path, result

    def test_sets_env_enters_cwd_and_runs(self):
        # The awkward value is XEFM_*_SELECTED's real shape: double-quoted
        # names, here with a quote, a dollar and a space inside them.
        value = '"it\'s $HOME.txt" "a b"'
        _, result = self.run_wrapper(_probe('XEFM_THIS_SELECTED'),
                                     {'XEFM_THIS_SELECTED': value})
        self.assertEqual(result.stdout.splitlines(), [self.dir, value])

    def test_deletes_itself(self):
        path, _ = self.run_wrapper(['true'], {})
        self.assertFalse(os.path.exists(path))

    def test_without_pause_the_command_replaces_the_script(self):
        text = et.posix_wrapper(['zsh'], self.dir, {}, False)
        self.assertEqual(text.splitlines()[-1], 'exec zsh')

    def test_pause_holds_a_failure_and_keeps_the_code(self):
        _, result = self.run_wrapper(_probe('X', code=3), {}, pause=True,
                                     stdin='\n')
        self.assertEqual(result.returncode, 3)
        self.assertIn('exited with code 3', result.stdout)

    def test_pause_lets_a_success_through(self):
        _, result = self.run_wrapper(_probe('X'), {}, pause=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('press Enter', result.stdout)

    def test_names_sh_cannot_export_are_skipped(self):
        text = et.posix_wrapper(['true'], None, {'BAD-NAME': 'x', 'OK': 'y'}, False)
        self.assertNotIn('BAD-NAME', text)
        self.assertIn("export OK=y", text)


class TestPythonWrapper(WrapperCase):
    """The Windows wrapper is plain Python, so it runs anywhere."""

    def run_wrapper(self, argv, env, pause=False, stdin=''):
        path = self.write(et.python_wrapper(argv, self.dir, env, pause), '.py')
        result = subprocess.run([sys.executable, path], input=stdin, text=True,
                                capture_output=True)
        return path, result

    def test_sets_env_enters_cwd_and_runs(self):
        value = '"a&b%PATH%.txt" "c d"'
        _, result = self.run_wrapper(_probe('XEFM_THIS_SELECTED'),
                                     {'XEFM_THIS_SELECTED': value})
        self.assertEqual(result.stdout.splitlines(), [self.dir, value])

    def test_deletes_itself(self):
        path, _ = self.run_wrapper(_probe('X'), {})
        self.assertFalse(os.path.exists(path))

    def test_exit_code_passes_through_and_pause_holds_it(self):
        _, result = self.run_wrapper(_probe('X', code=4), {}, pause=True,
                                     stdin='\n')
        self.assertEqual(result.returncode, 4)
        self.assertIn('exited with code 4', result.stdout)

    def test_no_pause_without_being_asked(self):
        _, result = self.run_wrapper(_probe('X', code=4), {})
        self.assertEqual(result.returncode, 4)
        self.assertNotIn('press Enter', result.stdout)

    def test_a_command_that_cannot_start_holds_the_window(self):
        _, result = self.run_wrapper(['no-such-program-xefm'], {}, stdin='\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('press Enter', result.stdout)


class TestLaunch(unittest.TestCase):

    def test_no_terminal_raises_before_writing_anything(self):
        with patch.object(et, 'write_wrapper') as write:
            with self.assertRaises(et.NoTerminalError):
                et.launch_in_terminal(None, ['sh'], cwd=None, env={})
        write.assert_not_called()

    def test_wrapper_is_appended_to_the_terminal(self):
        with patch.object(et.subprocess, 'Popen') as popen:
            et.launch_in_terminal(['my-term', '-e'], ['zsh'], cwd=None,
                                  env=dict(os.environ))
        argv = popen.call_args[0][0]
        wrapper = argv[-1]
        self.addCleanup(os.remove, wrapper)
        self.assertEqual(argv[1], '-e')
        self.assertTrue(argv[0].endswith('my-term') or argv[0] == 'my-term')
        self.assertTrue(os.path.basename(wrapper).startswith('xefm-terminal-'))
        if os.name != 'nt':
            self.assertTrue(os.access(wrapper, os.X_OK))

    def test_a_failed_launch_removes_the_wrapper(self):
        written = []
        real = et.write_wrapper

        def spy(*a, **kw):
            path, run = real(*a, **kw)
            written.append(path)
            return path, run

        with patch.object(et, 'write_wrapper', side_effect=spy), \
                patch.object(et.subprocess, 'Popen',
                             side_effect=FileNotFoundError('my-term')):
            with self.assertRaises(FileNotFoundError):
                et.launch_in_terminal(['my-term'], ['zsh'], cwd=None, env={})
        self.assertFalse(os.path.exists(written[0]))


if __name__ == '__main__':
    unittest.main()
