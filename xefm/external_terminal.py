"""
Running a terminal-bound command from desktop mode, in the OS's terminal app.

The TUI hands its own tty to a subshell or a ``{'terminal': True}`` program. The
desktop window has no tty to hand over, so it opens a terminal application
instead (discussion #472): ``TERMINAL`` picks the application, the platform
default when unset, and the command to run is appended to it as trailing
arguments.

What that command is, is always a small generated wrapper, never the program
itself. A terminal application does not reliably pass its caller's environment
on to what it runs: Terminal.app starts a fresh login shell, and Windows
Terminal may hand the request to an already-running instance whose environment
is its own. The ``XEFM_*`` variables and the ``[XeFM]`` prompt marker are what
make the subshell more than "a shell in this directory", so the wrapper sets
them itself, changes into the directory, and then runs the command. Delivery
therefore does not depend on how any one terminal treats its parent.

- POSIX: an executable ``sh`` script. It needs nothing but ``/bin/sh``, and
  ``open -a Terminal script`` runs it (the ``.command`` suffix is what Finder
  itself uses for "run this in Terminal").
- Windows: a Python script run by XeFM's own interpreter. cmd.exe batch quoting
  cannot carry ``XEFM_*_SELECTED`` — double-quoted names that may hold ``&`` or
  ``%`` — safely; ``repr()`` can.

Both delete themselves as soon as they start, and both hold the window open on
a nonzero exit when asked, as the TUI's ``pause_on_error`` does.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from xefm.external_programs import command_argv, resolve_command, xefm_python


class NoTerminalError(Exception):
    """No terminal application is configured, and the platform has no default."""


def default_terminal() -> list | None:
    """The platform's terminal application as an argv prefix, ``[]`` for "a
    new console window" (Windows without Windows Terminal), or ``None`` when
    there is no default and ``TERMINAL`` has to be set."""
    if sys.platform == 'darwin':
        return ['open', '-a', 'Terminal']
    if sys.platform == 'win32':
        return ['wt.exe'] if shutil.which('wt') else []
    return None


def terminal_command(config) -> list | None:
    """``TERMINAL`` from the config as an argv prefix — string or list, like
    ``TEXT_EDITOR`` — or :func:`default_terminal` when it is unset."""
    configured = command_argv(getattr(config, 'TERMINAL', None))
    return configured or default_terminal()


def delivered_env(env: dict) -> dict:
    """What of ``env`` the wrapper has to set: the variables XeFM added or
    changed on top of its own environment (``XEFM_*``, the prompt marker, a
    ``ctx.run_program`` caller's extras). Everything else the terminal's own
    shell sets up better — ``PATH`` above all, which XeFM only patched because
    an app started from Finder does not get the user's."""
    return {k: v for k, v in env.items()
            if k != 'PATH' and os.environ.get(k) != v}


_POSIX_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def posix_wrapper(argv: list, cwd: str | None, env: dict,
                  pause_on_error: bool) -> str:
    """The ``sh`` script that sets ``env``, enters ``cwd`` and runs ``argv``.
    Without ``pause_on_error`` the command replaces the script (``exec``), so
    the shell's exit closes the window the way a terminal's own shell does."""
    q = shlex.quote
    lines = ['#!/bin/sh', 'rm -f -- "$0"']
    lines += [f'export {k}={q(v)}' for k, v in env.items() if _POSIX_NAME.match(k)]
    if cwd:
        lines.append(f'cd -- {q(cwd)} || {{ printf "Press Enter to close"; read _; exit 1; }}')
    command = ' '.join(q(a) for a in argv)
    if not pause_on_error:
        lines.append(f'exec {command}')
    else:
        lines += [
            command,
            'status=$?',
            'if [ "$status" -ne 0 ]; then',
            f'  printf "\\n%s exited with code %s - press Enter to close\\n" {q(argv[0])} "$status"',
            '  read _',
            'fi',
            'exit "$status"',
        ]
    return '\n'.join(lines) + '\n'


def python_wrapper(argv: list, cwd: str | None, env: dict,
                   pause_on_error: bool) -> str:
    """The Python script that sets ``env``, enters ``cwd`` and runs ``argv``,
    for Windows. There is no ``exec`` there, so it waits for the command and
    exits with its code; Ctrl+C belongs to the command, not to the wrapper."""
    return f'''import os, signal, subprocess, sys
try:
    os.remove(__file__)
except OSError:
    pass
signal.signal(signal.SIGINT, signal.SIG_IGN)
os.environ.update({env!r})
argv = {list(argv)!r}
cwd = {cwd!r}
pause = {bool(pause_on_error)!r}
try:
    if cwd:
        os.chdir(cwd)
    code = subprocess.call(argv)
except OSError as exc:
    # Not started at all: say so and hold the window, or it closes unread.
    print(f"{{argv[0]}}: {{exc}}")
    code, pause = 1, True
if pause and code != 0:
    input(f"\\n{{argv[0]}} exited with code {{code}} - press Enter to close")
sys.exit(code)
'''


def write_wrapper(argv: list, cwd: str | None, env: dict,
                  pause_on_error: bool) -> tuple[str, list]:
    """Write the platform's wrapper to a temp file; return its path and the
    command that runs it — what gets appended to the terminal's argv."""
    delivered = delivered_env(env)
    if sys.platform == 'win32':
        # The wrapper's own PATH lookup is CreateProcess's, which ignores
        # PATHEXT; resolve here, against the environment the command gets.
        text = python_wrapper(resolve_command(argv, env), cwd, delivered,
                              pause_on_error)
        suffix = '.py'
    else:
        text = posix_wrapper(argv, cwd, delivered, pause_on_error)
        suffix = '.command' if sys.platform == 'darwin' else '.sh'
    fd, path = tempfile.mkstemp(prefix='xefm-terminal-', suffix=suffix)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    if sys.platform == 'win32':
        return path, [xefm_python, path]
    os.chmod(path, 0o700)
    return path, [path]


def launch_in_terminal(terminal: list | None, argv: list, *,
                       cwd: str | None, env: dict,
                       pause_on_error: bool = False) -> None:
    """Open ``terminal`` (an argv prefix from :func:`terminal_command`) running
    ``argv`` in ``cwd`` with ``env``, and return at once — the terminal is its
    own application from here on.

    Raises :class:`NoTerminalError` when ``terminal`` is ``None``, and whatever
    :class:`subprocess.Popen` raises when it cannot be started (the wrapper is
    removed again then)."""
    if terminal is None:
        raise NoTerminalError()
    path, run_wrapper = write_wrapper(argv, cwd, env, pause_on_error)
    try:
        if terminal:
            # The terminal draws its own window; nothing of ours to lend it.
            subprocess.Popen(resolve_command(terminal + run_wrapper, env),
                             cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Windows without Windows Terminal: a console window of its own,
            # whose stdio the command must keep.
            subprocess.Popen(run_wrapper, cwd=cwd, env=env,
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
