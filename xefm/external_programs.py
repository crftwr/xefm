#!/usr/bin/env python3
"""
XeFM External Programs Module - Handles external program execution and subshell features
"""

import os
import subprocess
import sys
import shlex
import shutil
import time
from xefm.path import Path
from xefm.backend_detector import is_desktop_mode
from xefm.log_manager import getLogger


def _resolve_xefm_python():
    r"""The interpreter external programs should be launched with.

    ``sys.executable`` is the obvious answer and the right one whenever XeFM
    runs under a real ``python``. In an application bundle it is not: the
    bundle's own launcher executable is reported there, and running *it* with a
    script argument does not run the script.

    - macOS: ``XeFM.app/Contents/MacOS/XeFM`` -> the interpreter bundled at
      ``Contents/Frameworks/Python.framework/bin/python3``.
    - Windows: ``<root>\XeFM.exe`` -> ``<root>\runtime\python.exe`` from the
      embedded CPython. The C launcher (windows_app/src/launcher.c) hardcodes
      ``sys.argv`` and sets ``parse_argv = 0``, so handing XeFM.exe a script
      would discard it and just open a second file manager window.

      The console interpreter, not ``pythonw.exe``: a tool that shells out to
      another console program (``code.cmd``, ``git``) passes on its own pipes
      only if it has a console itself. Under ``pythonw`` the grandchild gets a
      fresh console instead, so its output never reaches the log pane and its
      window flashes on screen. What keeps the console hidden is
      :data:`SUBPROCESS_NO_WINDOW`, applied at the launch sites.
    """
    if sys.platform == 'darwin' and '.app/Contents/MacOS' in sys.executable:
        # The bundled Python is at: XeFM.app/Contents/Frameworks/Python.framework/bin/python3
        bundle_path = sys.executable.rsplit('.app/Contents/MacOS', 1)[0] + '.app'
        return os.path.join(bundle_path, 'Contents', 'Frameworks', 'Python.framework', 'bin', 'python3')

    if sys.platform == 'win32':
        # Any real interpreter is named python*.exe (python.exe, pythonw.exe,
        # python3.14.exe); anything else is a launcher wrapping one - the
        # bundle's XeFM.exe. The embeddable package ships python.exe next to
        # the DLL under runtime\, which the build keeps (it only strips the
        # ._pth files).
        exe_name = os.path.basename(sys.executable).lower()
        if not (exe_name.startswith('python') and exe_name.endswith('.exe')):
            bundled = os.path.join(os.path.dirname(sys.executable), 'runtime', 'python.exe')
            if os.path.exists(bundled):
                return bundled
        return sys.executable

    # Normal execution - use current Python interpreter
    return sys.executable


#: Python interpreter path for external programs, resolved once at import.
xefm_python = _resolve_xefm_python()


#: Extra :mod:`subprocess` keyword arguments for launching a console program
#: without showing a console window. Windows gives a console-subsystem child a
#: window of its own whenever the parent has no console - which is every launch
#: from the GUI backend - and that window appears even though the child's output
#: is already redirected to pipes. ``CREATE_NO_WINDOW`` gives the child a console
#: it can still lend to *its* own children, just an invisible one. Empty off
#: Windows, and deliberately not applied where a program is meant to take over
#: the terminal (``options {'terminal': True}``, the sub-shell).
SUBPROCESS_NO_WINDOW = (
    {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {})


def xefm_tool(tool_name):
    """
    Find and return the path to a XeFM tool.
    
    This function searches for tools in the XeFM tool directories:
    1. ~/.xefm/tools/ (user-specific tools, highest priority)
    2. xefm/tools/ (system tools - works for both development and installed package)
    
    Args:
        tool_name: Name of the tool to search for
        
    Returns:
        Path to the tool if found, otherwise the original tool_name
        
    Example:
        {'name': 'My Tool', 'command': [sys.executable, xefm_tool('my_script.py')]}
    """
    
    # Candidate directories in priority order
    candidates = []
    
    # 1. User-specific tools directory: ~/.xefm/tools/
    home_dir = Path.home()
    user_tools_dir = home_dir / '.xefm' / 'tools'
    candidates.append(user_tools_dir / tool_name)
    
    # 2. System tools directory
    # This works for both development and installed package:
    # - Development: project_root/xefm/external_programs.py -> project_root/xefm/tools/
    # - Installed: site-packages/xefm/external_programs.py -> site-packages/xefm/tools/
    current_file = Path(__file__)  # This is xefm/external_programs.py
    tools_dir = current_file.parent / 'tools'  # tools/ is in the same directory as this file
    candidates.append(tools_dir / tool_name)
    
    # Check each candidate
    for candidate_path in candidates:
        if candidate_path.exists():
            return str(candidate_path)
    
    # Tool not found, return original name (will likely fail later with clear error)
    return tool_name


def quote_filenames_with_double_quotes(filenames):
    """
    Quote filenames for safe shell usage using double quotes.
    
    This function replaces the previous use of shlex.quote() which used single quotes.
    Double quotes are preferred for XEFM_*_SELECTED environment variables to provide
    consistent quoting behavior across different shell environments.
    
    Args:
        filenames: List of filename strings to quote
        
    Returns:
        List of quoted filename strings using double quotes
    """
    quoted = []
    for filename in filenames:
        # Use double quotes and escape any double quotes or backslashes in the filename
        escaped = filename.replace('\\', '\\\\').replace('"', '\\"')
        quoted.append(f'"{escaped}"')
    return quoted


def get_focused_file(pane_data):
    """The name of the item under the cursor, as a one-element list — or an
    empty list when the pane has no rows. Independent of the selection, which
    is what separates ``XEFM_*_FOCUSED`` from ``XEFM_*_SELECTED`` (#348)."""
    files = pane_data['files']
    if not files:
        return []
    index = pane_data['focused_index']
    return [files[index].name] if 0 <= index < len(files) else []


def get_selected_files(pane_data):
    """The names explicitly selected with Space in ``pane_data`` — empty when
    nothing is selected. The ``XEFM_*_SELECTED`` contract (#348)."""
    return [Path(f).name for f in pane_data['selected_files']]


def get_selected_or_cursor_files(pane_data):
    """Get selected files, or current cursor position if no files selected.

    This is the **argv** rule, not the environment's: a program launched from
    the picker is handed the selection when there is one and the focused entry
    otherwise, because one argument list cannot express both. Programs that
    need the distinction read ``XEFM_*_SELECTED`` and ``XEFM_*_FOCUSED``, which
    report the two separately.
    """
    selected = get_selected_files(pane_data)
    if not selected:
        # No files selected, use focused file
        selected = get_focused_file(pane_data)
    return selected


def build_xefm_env(left_pane, right_pane, current_pane, other_pane):
    """The XEFM_* variables describing the pane state, ready to merge into a
    subprocess environment. Both families hold space-separated, double-quoted
    filenames.

    ``XEFM_*_SELECTED`` is exactly what Space selected, and is **empty when
    nothing is selected** — it does not substitute the file under the cursor
    (it used to, through XeFM 1.1.0). ``XEFM_*_FOCUSED`` names that file
    instead, and is empty only when the pane itself is. Keeping them apart is
    what lets a program require a real selection — one that compares the two
    selected files, say — rather than silently acting on whatever the cursor
    happened to be on."""
    def selected(pane):
        return ' '.join(quote_filenames_with_double_quotes(
            get_selected_files(pane)))

    def focused(pane):
        return ' '.join(quote_filenames_with_double_quotes(
            get_focused_file(pane)))

    return {
        'XEFM_LEFT_DIR': str(left_pane['path']),
        'XEFM_RIGHT_DIR': str(right_pane['path']),
        'XEFM_THIS_DIR': str(current_pane['path']),
        'XEFM_OTHER_DIR': str(other_pane['path']),
        'XEFM_LEFT_SELECTED': selected(left_pane),
        'XEFM_RIGHT_SELECTED': selected(right_pane),
        'XEFM_THIS_SELECTED': selected(current_pane),
        'XEFM_OTHER_SELECTED': selected(other_pane),
        'XEFM_LEFT_FOCUSED': focused(left_pane),
        'XEFM_RIGHT_FOCUSED': focused(right_pane),
        'XEFM_THIS_FOCUSED': focused(current_pane),
        'XEFM_OTHER_FOCUSED': focused(other_pane),
        'XEFM_ACTIVE': '1',
    }


#: Shell basenames whose prompt convention we know, mapped to a family. Anything
#: unrecognized falls back to the platform's own family (see :func:`shell_family`).
_SHELL_FAMILIES = {
    'cmd': 'cmd', 'command': 'cmd',
    'powershell': 'powershell', 'pwsh': 'powershell',
    'sh': 'posix', 'bash': 'posix', 'zsh': 'posix', 'ksh': 'posix',
    'dash': 'posix', 'ash': 'posix', 'fish': 'posix', 'csh': 'posix',
    'tcsh': 'posix', 'busybox': 'posix',
}


def shell_family(command):
    """Which prompt convention the shell in ``command`` (a list, as passed to
    ``subprocess``) follows: ``'cmd'``, ``'powershell'`` or ``'posix'``. An
    unrecognized shell is assumed to follow the platform's own convention."""
    # Split on both separators regardless of the host: the config that names
    # C:\Windows\system32\cmd.exe is read on Windows, but the tests for it run
    # everywhere. A POSIX filename containing a backslash is not worth the
    # ambiguity here — the only thing riding on this is which prompt variable
    # gets the marker.
    name = command[0].replace('\\', '/').rsplit('/', 1)[-1] if command else ''
    name = os.path.splitext(name)[0].lower()
    return _SHELL_FAMILIES.get(name,
                               'cmd' if os.name == 'nt' else 'posix')


def prefix_prompt_markers(env, command=None):
    """Prefix a ``[XeFM]`` marker onto the prompt variable of the shell in
    ``command`` so a sub-shell visibly reads as nested inside XeFM.

    ``PROMPT`` is claimed by two unrelated shells with incompatible syntaxes —
    zsh's ``%``-codes and cmd.exe's ``$``-codes — so which default we write has
    to follow the shell actually being launched, not the variable name: cmd.exe
    given zsh's default rendered it literally as ``[XeFM] %n@%m:%~%#``.
    PowerShell builds its prompt from a ``prompt`` function and reads neither
    variable, so it gets no marker at all.

    Best effort in every case: an rc file (or a ``PROMPT`` set by a cmd
    ``AutoRun``) that sets its own prompt overwrites this — the docs suggest
    keying off ``XEFM_ACTIVE`` for that case."""
    family = shell_family(command)
    if family == 'powershell':
        return
    if family == 'cmd':
        # cmd.exe's built-in default when PROMPT is unset is "$P$G".
        env['PROMPT'] = f"[XeFM] {env.get('PROMPT', '') or '$P$G'}"
        return
    current_ps1 = env.get('PS1', '')
    if current_ps1:
        env['PS1'] = f'[XeFM] {current_ps1}'
    else:
        env['PS1'] = '[XeFM] \\u@\\h:\\w\\$ '
    current_prompt = env.get('PROMPT', '')
    if current_prompt:
        env['PROMPT'] = f'[XeFM] {current_prompt}'
    else:
        env['PROMPT'] = '[XeFM] %n@%m:%~%# '


def ensure_common_paths_in_env(env):
    """
    Ensure common binary paths are in PATH environment variable.
    
    When XeFM.app is launched from Finder/Dock on macOS, it doesn't inherit
    the user's shell PATH. This function adds common binary paths like
    /usr/local/bin where tools like 'code' (VS Code) are typically installed.
    
    Args:
        env: Environment dictionary to modify
    """
    if sys.platform == 'darwin':
        current_path = env.get('PATH', '')
        common_paths = ['/usr/local/bin', '/opt/homebrew/bin', '/usr/bin', '/bin']
        path_components = current_path.split(':') if current_path else []
        
        # Add missing common paths to the beginning of PATH
        for path in reversed(common_paths):
            if path not in path_components:
                path_components.insert(0, path)
        
        env['PATH'] = ':'.join(path_components)


def resolve_command(command, env=None):
    r"""``command`` with its program resolved to a full path, when PATH holds one.

    Windows' ``CreateProcess`` - what :mod:`subprocess` calls - searches PATH
    but only ever appends ``.exe``; it never reads PATHEXT. So a bare ``code``
    misses the ``code.cmd`` that scoop's shims (and VS Code's own installer) put
    on PATH, and the launch fails with "Command not found" even though the very
    same name runs from XeFM's sub-shell, where cmd.exe does read PATHEXT
    (#345). :func:`shutil.which` applies PATHEXT, and CreateProcess happily runs
    a ``.cmd`` it is handed by full path.

    ``env`` is the environment the program will be launched with when that is
    not ours: its PATH is the one to search - what POSIX :mod:`subprocess` does
    anyway, and what makes :func:`ensure_common_paths_in_env` count.

    A name PATH cannot resolve comes back untouched rather than raising, so the
    launch still happens and still fails exactly as it always has: callers
    report the missing command from the resulting :class:`FileNotFoundError`,
    naming what the user wrote rather than a path we invented.
    """
    if not command:
        return list(command)
    found = shutil.which(command[0], path=env.get('PATH') if env else None)
    return [found] + list(command[1:]) if found else list(command)


class ExternalProgramManager:
    """Manages external program execution and subshell functionality"""
    
    def __init__(self, config, log_manager, renderer=None):
        self.config = config
        self.log_manager = log_manager
        self.renderer = renderer
        self.logger = getLogger("ExtProg")

    def execute_external_program(self, pane_manager, program):
        """Execute an external program with environment variables set"""
        # Detect if running in desktop mode
        desktop_mode = is_desktop_mode()
        
        # In terminal mode, restore stdout/stderr to allow subprocess to use terminal
        # In desktop mode, keep LogCapture active so subprocess output goes to log pane
        if not desktop_mode:
            self.log_manager.restore_stdio()
        
        # Clear the screen and reset cursor
        self.renderer.clear()
        self.renderer.refresh()
        
        # Suspend the renderer to allow external program to run
        self.renderer.suspend()
        
        try:
            # Get current pane information
            left_pane = pane_manager.left_pane
            right_pane = pane_manager.right_pane
            current_pane = pane_manager.get_current_pane()
            other_pane = pane_manager.get_inactive_pane()
            
            # Set environment variables with XEFM_ prefix
            env = os.environ.copy()
            ensure_common_paths_in_env(env)
            env.update(build_xefm_env(left_pane, right_pane, current_pane, other_pane))

            # Use the command as-is (users should use xefm_tool() for XeFM tools),
            # bar the PATH lookup Windows won't do for us (see resolve_command).
            command = resolve_command(program['command'], env)
            
            # Determine working directory for external program
            # If current pane is browsing a remote directory (like S3), 
            # fallback to XeFM's working directory
            working_dir = None
            if current_pane['path'].is_remote():
                working_dir = os.getcwd()
            else:
                working_dir = str(current_pane['path'])
            
            # Print information about the program execution
            self.logger.info(f"XeFM External Program: {program['name']}")
            self.logger.info("=" * 50)
            self.logger.info(f"Command: {' '.join(command)}")
            self.logger.info(f"Working Directory: {working_dir}")
            if current_pane['path'].is_remote():
                self.logger.info(f"Note: Current pane is browsing remote directory: {current_pane['path']}")
                self.logger.info(f"Working directory set to XeFM's directory: {working_dir}")
            self.logger.info(f"XEFM_THIS_DIR: {env['XEFM_THIS_DIR']}")
            self.logger.info(f"XEFM_THIS_SELECTED: {env['XEFM_THIS_SELECTED']}")
            self.logger.info(f"XEFM_THIS_FOCUSED: {env['XEFM_THIS_FOCUSED']}")
            self.logger.info("=" * 50)
            self.logger.info("")
            
            # Change to the working directory
            os.chdir(working_dir)
            
            # Execute the program with the modified environment
            # In desktop mode, capture output to redirect to log pane
            if desktop_mode:
                result = subprocess.run(command, env=env, capture_output=True, text=True,
                                        **SUBPROCESS_NO_WINDOW)
                
                # Redirect stdout to log pane (LogCapture is still active)
                if result.stdout:
                    for line in result.stdout.splitlines():
                        self.logger.info(line)
                
                # Redirect stderr to log pane (LogCapture is still active)
                if result.stderr:
                    for line in result.stderr.splitlines():
                        self.logger.error(line)
            else:
                # Terminal mode - let subprocess use terminal directly
                result = subprocess.run(command, env=env)
            
            # Check if auto_return option is enabled
            auto_return = program.get('options', {}).get('auto_return', False)
            
            # Show exit status
            self.logger.info("")
            self.logger.info("=" * 50)
            if result.returncode == 0:
                self.logger.info(f"Program '{program['name']}' completed successfully")
                
                if auto_return or desktop_mode:
                    # In desktop mode, no sleep needed - just return immediately
                    if not desktop_mode:
                        time.sleep(1)  # Brief pause in terminal mode only
                else:
                    self.logger.info("Press Enter to return to XeFM...")
                    input()
            else:
                self.logger.error(f"Program '{program['name']}' exited with code {result.returncode}")
                # In desktop mode, auto-return even on error (user can check log pane)
                # In terminal mode, wait for user input when there's an error
                if desktop_mode:
                    self.logger.info("Check log pane for error details.")
                    # No sleep in desktop mode - return immediately
                else:
                    self.logger.info("Press Enter to return to XeFM...")
                    input()
            
        except FileNotFoundError:
            self.logger.error(f"Error: Command not found: {program['command'][0]}")
            self.logger.info("Tip: Use xefm_tool() function for XeFM tools in your configuration")
            
            # In desktop mode, auto-return (user can check log pane)
            # In terminal mode, wait for user input
            if desktop_mode:
                self.logger.info("Check log pane for error details.")
                # No sleep in desktop mode - return immediately
            else:
                self.logger.info("Press Enter to continue...")
                input()
        except Exception as e:
            self.logger.error(f"Error executing program '{program['name']}': {e}")
            
            # In desktop mode, auto-return (user can check log pane)
            # In terminal mode, wait for user input
            if desktop_mode:
                self.logger.info("Check log pane for error details.")
                # No sleep in desktop mode - return immediately
            else:
                self.logger.info("Press Enter to continue...")
                input()
        
        finally:
            # Resume the renderer
            self.renderer.resume()
            
            # Reinitialize colors after the subprocess
            from xefm.colors import init_colors
            init_colors(self.renderer)
            
            # Restore stdout/stderr capture (only needed in terminal mode)
            # In desktop mode, LogCapture was never disconnected
            if not desktop_mode:
                from xefm.log_manager import LogCapture
                sys.stdout = LogCapture("STDOUT", self.log_manager.original_stdout, 
                                       is_desktop_mode=False, logger=self.log_manager._stream_logger)
                sys.stderr = LogCapture("STDERR", self.log_manager.original_stderr,
                                       is_desktop_mode=False, logger=self.log_manager._stream_logger)
            
            # Log return from program execution
            self.logger.info(f"Returned from external program: {program['name']}")
    
    def enter_subshell_mode(self, pane_manager):
        """Enter sub-shell mode with environment variables set"""
        # Restore stdout/stderr temporarily
        self.log_manager.restore_stdio()
        
        # Clear the screen and reset cursor
        self.renderer.clear()
        self.renderer.refresh()
        
        # Suspend the renderer to allow subshell to run
        self.renderer.suspend()
        
        try:
            # Get current pane information
            left_pane = pane_manager.left_pane
            right_pane = pane_manager.right_pane
            current_pane = pane_manager.get_current_pane()
            other_pane = pane_manager.get_inactive_pane()
            
            # Set environment variables with XEFM_ prefix
            env = os.environ.copy()
            ensure_common_paths_in_env(env)
            env.update(build_xefm_env(left_pane, right_pane, current_pane, other_pane))

            # Modify shell prompt to include [XeFM] label
            shell = env.get('SHELL', '/bin/bash')
            prefix_prompt_markers(env, [shell])
            
            # Determine working directory for subshell
            # If current pane is browsing a remote directory (like S3), 
            # fallback to XeFM's working directory
            working_dir = None
            if current_pane['path'].is_remote():
                working_dir = os.getcwd()
                self.logger.info("XeFM Sub-shell Mode")
                self.logger.info("=" * 50)
                self.logger.info(f"XEFM_LEFT_DIR:      {env['XEFM_LEFT_DIR']}")
                self.logger.info(f"XEFM_RIGHT_DIR:     {env['XEFM_RIGHT_DIR']}")
                self.logger.info(f"XEFM_THIS_DIR:      {env['XEFM_THIS_DIR']}")
                self.logger.info(f"XEFM_OTHER_DIR:     {env['XEFM_OTHER_DIR']}")
                self.logger.info(f"XEFM_LEFT_SELECTED: {env['XEFM_LEFT_SELECTED']}")
                self.logger.info(f"XEFM_RIGHT_SELECTED: {env['XEFM_RIGHT_SELECTED']}")
                self.logger.info(f"XEFM_THIS_SELECTED: {env['XEFM_THIS_SELECTED']}")
                self.logger.info(f"XEFM_OTHER_SELECTED: {env['XEFM_OTHER_SELECTED']}")
                self.logger.info(f"XEFM_LEFT_FOCUSED: {env['XEFM_LEFT_FOCUSED']}")
                self.logger.info(f"XEFM_RIGHT_FOCUSED: {env['XEFM_RIGHT_FOCUSED']}")
                self.logger.info(f"XEFM_THIS_FOCUSED: {env['XEFM_THIS_FOCUSED']}")
                self.logger.info(f"XEFM_OTHER_FOCUSED: {env['XEFM_OTHER_FOCUSED']}")
                self.logger.info("=" * 50)
                self.logger.info(f"Note: Current pane is browsing remote directory: {current_pane['path']}")
                self.logger.info(f"Subshell working directory set to XeFM's directory: {working_dir}")
            else:
                working_dir = str(current_pane['path'])
                self.logger.info("XeFM Sub-shell Mode")
                self.logger.info("=" * 50)
                self.logger.info(f"XEFM_LEFT_DIR:      {env['XEFM_LEFT_DIR']}")
                self.logger.info(f"XEFM_RIGHT_DIR:     {env['XEFM_RIGHT_DIR']}")
                self.logger.info(f"XEFM_THIS_DIR:      {env['XEFM_THIS_DIR']}")
                self.logger.info(f"XEFM_OTHER_DIR:     {env['XEFM_OTHER_DIR']}")
                self.logger.info(f"XEFM_LEFT_SELECTED: {env['XEFM_LEFT_SELECTED']}")
                self.logger.info(f"XEFM_RIGHT_SELECTED: {env['XEFM_RIGHT_SELECTED']}")
                self.logger.info(f"XEFM_THIS_SELECTED: {env['XEFM_THIS_SELECTED']}")
                self.logger.info(f"XEFM_OTHER_SELECTED: {env['XEFM_OTHER_SELECTED']}")
                self.logger.info(f"XEFM_LEFT_FOCUSED: {env['XEFM_LEFT_FOCUSED']}")
                self.logger.info(f"XEFM_RIGHT_FOCUSED: {env['XEFM_RIGHT_FOCUSED']}")
                self.logger.info(f"XEFM_THIS_FOCUSED: {env['XEFM_THIS_FOCUSED']}")
                self.logger.info(f"XEFM_OTHER_FOCUSED: {env['XEFM_OTHER_FOCUSED']}")
                self.logger.info("=" * 50)
            
            self.logger.info("XEFM_ACTIVE environment variable is set for shell customization")
            self.logger.info("To show [XeFM] in your prompt, add this to your shell config:")
            self.logger.info("  Zsh (~/.zshrc): if [[ -n \"$XEFM_ACTIVE\" ]]; then PROMPT=\"[XeFM] $PROMPT\"; fi")
            self.logger.info("  Bash (~/.bashrc): if [[ -n \"$XEFM_ACTIVE\" ]]; then PS1=\"[XeFM] $PS1\"; fi")
            self.logger.info("Type 'exit' to return to XeFM")
            self.logger.info("")
            
            # Change to the working directory
            os.chdir(working_dir)
            
            # Start the shell with the modified environment
            subprocess.run(resolve_command([shell], env), env=env)
            
        except Exception as e:
            self.logger.error(f"Error starting sub-shell: {e}")
            input("Press Enter to continue...")
        
        finally:
            # Resume the renderer
            self.renderer.resume()
            
            # Reinitialize colors after the subprocess
            from xefm.colors import init_colors
            init_colors(self.renderer)
            
            # Restore stdout/stderr capture  
            from xefm.log_manager import LogCapture
            sys.stdout = LogCapture("STDOUT", self.log_manager.original_stdout,
                                   is_desktop_mode=False, logger=self.log_manager._stream_logger)
            sys.stderr = LogCapture("STDERR", self.log_manager.original_stderr,
                                   is_desktop_mode=False, logger=self.log_manager._stream_logger)
            
            # Log return from sub-shell
            self.logger.info("Returned from sub-shell mode")