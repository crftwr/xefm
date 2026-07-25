#!/usr/bin/env python3
"""
XeFM External Programs Module - Handles external program execution and subshell features
"""

import os
import subprocess
import sys
import shlex
import time
from xefm.path import Path
from xefm.backend_detector import is_desktop_mode
from xefm.log_manager import getLogger


# Python interpreter path for external programs
# This variable points to the correct Python interpreter depending on execution context:
# - When running from macOS app bundle: uses bundled python3 executable
# - When running normally: uses sys.executable (current Python interpreter)
if sys.platform == 'darwin' and '.app/Contents/MacOS' in sys.executable:
    # Running from macOS app bundle - use bundled python3
    # The bundled Python is at: XeFM.app/Contents/Frameworks/Python.framework/bin/python3
    bundle_path = sys.executable.rsplit('.app/Contents/MacOS', 1)[0] + '.app'
    xefm_python = os.path.join(bundle_path, 'Contents', 'Frameworks', 'Python.framework', 'bin', 'python3')
else:
    # Normal execution - use current Python interpreter
    xefm_python = sys.executable


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


def get_selected_or_cursor_files(pane_data):
    """Get selected files, or current cursor position if no files selected"""
    selected = [Path(f).name for f in pane_data['selected_files']]
    if not selected and pane_data['files'] and pane_data['focused_index'] < len(pane_data['files']):
        # No files selected, use focused file
        focused_file = pane_data['files'][pane_data['focused_index']]
        selected = [focused_file.name]
    return selected


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
            env['XEFM_LEFT_DIR'] = str(left_pane['path'])
            env['XEFM_RIGHT_DIR'] = str(right_pane['path'])
            env['XEFM_THIS_DIR'] = str(current_pane['path'])
            env['XEFM_OTHER_DIR'] = str(other_pane['path'])
            
            # Get selected files for each pane, or cursor position if no selection
            left_selected = quote_filenames_with_double_quotes(get_selected_or_cursor_files(left_pane))
            right_selected = quote_filenames_with_double_quotes(get_selected_or_cursor_files(right_pane))
            current_selected = quote_filenames_with_double_quotes(get_selected_or_cursor_files(current_pane))
            other_selected = quote_filenames_with_double_quotes(get_selected_or_cursor_files(other_pane))
            
            # Set selected files environment variables (space-separated) with XEFM_ prefix
            env['XEFM_LEFT_SELECTED'] = ' '.join(left_selected)
            env['XEFM_RIGHT_SELECTED'] = ' '.join(right_selected)
            env['XEFM_THIS_SELECTED'] = ' '.join(current_selected)
            env['XEFM_OTHER_SELECTED'] = ' '.join(other_selected)
            
            # Set XeFM indicator environment variable
            env['XEFM_ACTIVE'] = '1'
            
            # Use the command as-is (users should use xefm_tool() for XeFM tools)
            command = program['command']
            
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
            self.logger.info("=" * 50)
            self.logger.info("")
            
            # Change to the working directory
            os.chdir(working_dir)
            
            # Execute the program with the modified environment
            # In desktop mode, capture output to redirect to log pane
            if desktop_mode:
                result = subprocess.run(command, env=env, capture_output=True, text=True)
                
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
            
            # Reinitialize colors after the subprocess (legacy ttk renderer)
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
            env['XEFM_LEFT_DIR'] = str(left_pane['path'])
            env['XEFM_RIGHT_DIR'] = str(right_pane['path'])
            env['XEFM_THIS_DIR'] = str(current_pane['path'])
            env['XEFM_OTHER_DIR'] = str(other_pane['path'])
            
            # Get selected files for each pane, or cursor position if no selection
            left_selected = quote_filenames_with_double_quotes(get_selected_or_cursor_files(left_pane))
            right_selected = quote_filenames_with_double_quotes(get_selected_or_cursor_files(right_pane))
            current_selected = quote_filenames_with_double_quotes(get_selected_or_cursor_files(current_pane))
            other_selected = quote_filenames_with_double_quotes(get_selected_or_cursor_files(other_pane))
            
            # Set selected files environment variables (space-separated) with XEFM_ prefix
            # Filenames are properly quoted with double quotes for shell safety
            env['XEFM_LEFT_SELECTED'] = ' '.join(left_selected)
            env['XEFM_RIGHT_SELECTED'] = ' '.join(right_selected)
            env['XEFM_THIS_SELECTED'] = ' '.join(current_selected)
            env['XEFM_OTHER_SELECTED'] = ' '.join(other_selected)
            
            # Set XeFM indicator environment variable
            env['XEFM_ACTIVE'] = '1'
            
            # Modify shell prompt to include [XeFM] label
            # Handle both bash (PS1) and zsh (PROMPT) prompts
            current_ps1 = env.get('PS1', '')
            current_prompt = env.get('PROMPT', '')
            
            # Modify PS1 for bash and other shells
            if current_ps1:
                env['PS1'] = f'[XeFM] {current_ps1}'
            else:
                env['PS1'] = '[XeFM] \\u@\\h:\\w\\$ '
            
            # Modify PROMPT for zsh
            if current_prompt:
                env['PROMPT'] = f'[XeFM] {current_prompt}'
            else:
                env['PROMPT'] = '[XeFM] %n@%m:%~%# '
            
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
            shell = env.get('SHELL', '/bin/bash')
            subprocess.run([shell], env=env)
            
        except Exception as e:
            self.logger.error(f"Error starting sub-shell: {e}")
            input("Press Enter to continue...")
        
        finally:
            # Resume the renderer
            self.renderer.resume()
            
            # Reinitialize colors after the subprocess (legacy ttk renderer)
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