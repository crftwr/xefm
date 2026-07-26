"""
SSH Connection Management for XeFM

This module provides SSH/SFTP connection management for remote file operations.
It uses the standard sftp command-line tool via subprocess for all operations.
"""

import subprocess
import threading
import time
import os
import shlex
import shutil
import traceback
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from xefm.log_manager import getLogger
from xefm.ssh_cache import get_ssh_cache


# SSH-specific exception types
class SSHError(Exception):
    """Base exception for SSH-related errors"""
    pass


class SSHAuthenticationError(SSHError):
    """Exception raised when SSH authentication fails"""
    pass


class SSHConnectionTimeoutError(SSHError):
    """Exception raised when SSH connection times out"""
    pass


class SSHPathNotFoundError(SSHError):
    """Exception raised when a remote path does not exist"""
    pass


class SSHPermissionDeniedError(SSHError):
    """Exception raised when permission is denied for an operation"""
    pass


class SSHConnectionLostError(SSHError):
    """Exception raised when an active connection is lost"""
    pass


class _TransferMonitor:
    """Drives byte-level progress for a running ``sftp`` transfer, and stops the
    transfer when the progress callback raises.

    ``sftp`` writes its progress meter only to a terminal, so nothing usable
    reaches us on a pipe — enabling it explicitly changes nothing. The byte
    count comes instead from watching the file being written, which the caller
    supplies as ``probe``: the local temp file for a download, the remote file
    for an upload.

    The progress callback doubles as the cancel checkpoint. Whatever it raises
    is recorded in :attr:`error`, the ``sftp`` process is killed so the transfer
    stops immediately rather than running to completion, and the caller
    re-raises it unchanged.
    """

    def __init__(self, probe, total_bytes: int, callback: callable,
                 interval: float, logger):
        self._probe = probe
        self._total = total_bytes
        self._callback = callback
        self._interval = interval
        self.logger = logger
        self._stop = threading.Event()
        self._thread = None
        self._process = None
        #: Exception raised by the progress callback, if any
        self.error = None

    def start(self, process):
        """Report an empty bar and begin sampling alongside ``process``."""
        self._process = process
        if self._report(0):
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _report(self, transferred: int) -> bool:
        """Push one update; return False if the callback asked us to stop."""
        try:
            self._callback(min(transferred, self._total), self._total)
            return True
        except BaseException as e:  # noqa: BLE001 - forwarded to the caller
            self.error = e
            self._kill()
            return False

    def _run(self):
        while not self._stop.wait(self._interval):
            if self._process.poll() is not None:
                return
            try:
                transferred = self._probe()
            except Exception as e:  # noqa: BLE001
                # A probe that fails (file not created yet, remote hiccup) must
                # never take down a transfer that is otherwise healthy
                self.logger.debug(f"Transfer progress probe failed: {e}")
                continue
            if not self._report(transferred):
                return

    def _kill(self):
        try:
            self._process.kill()
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Failed to stop cancelled transfer: {e}")

    def stop(self):
        """Stop sampling and wait for the sampling thread to finish."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def finish(self):
        """Report the transfer as complete (no-op once cancelled)."""
        if self.error is None:
            self._report(self._total)


class SSHConnection:
    """
    Manages an SSH/SFTP connection to a remote host.

    Provides methods for file operations over SFTP using subprocess
    to invoke the sftp command-line tool.
    """

    #: How often a download samples its growing temp file. A local ``stat``
    #: costs nothing, so this is set by how smooth the bar should look.
    _DOWNLOAD_POLL = 0.25

    #: How often an upload samples the remote file. Each sample is a command
    #: over the multiplexed connection, so it is deliberately less frequent.
    _UPLOAD_POLL = 0.5
    
    def __init__(self, hostname: str, config: Dict[str, str]):
        """
        Initialize SSH connection.
        
        Args:
            hostname: Remote hostname (Host entry from SSH config)
            config: SSH configuration dictionary with keys like:
                    'HostName', 'User', 'Port', 'IdentityFile', etc.
        """
        self.hostname = hostname
        self.config = config
        self._connected = False
        self._lock = threading.Lock()
        self.logger = getLogger("SSHCon")
        
        # Extract connection parameters
        self.actual_host = config.get('HostName', hostname)
        self.user = config.get('User', None)
        self.port = config.get('Port', '22')
        self.identity_file = config.get('IdentityFile', None)
        
        # Default remote directory (set during connection)
        self.default_directory = None
        
        # Progress tracking. Transfers of any size are watched: the caller
        # decides what is worth a progress bar, and a cancel has to work on a
        # small file over a slow link too.
        self._progress_callback = None

        # SSH multiplexing (ControlMaster) for persistent connections
        # Use user's home directory instead of /tmp to avoid sandboxing issues
        # when running from DMG-packaged apps
        import os
        import hashlib
        from pathlib import Path
        
        # Create a short hash of the hostname to keep path length manageable
        hostname_hash = hashlib.md5(hostname.encode()).hexdigest()[:8]
        
        # Use ~/.xefm/ssh_sockets directory for control sockets
        # This avoids issues with /tmp in sandboxed environments (DMG apps)
        ssh_socket_dir = Path.home() / '.xefm' / 'ssh_sockets'
        ssh_socket_dir.mkdir(parents=True, exist_ok=True)
        
        # Include process ID to ensure unique socket per process
        # This prevents race conditions when multiple XeFM processes connect to the same host
        pid = os.getpid()
        self._control_path = str(ssh_socket_dir / f'xefm-ssh-{hostname_hash}-{pid}')
        
        # Get cache instance
        self._cache = get_ssh_cache()
        
        # Control master check caching (optimization)
        self._last_control_master_check = 0  # Timestamp of last check
        self._control_master_check_interval = 5.0  # Seconds between checks
        self._cached_control_master_status = False  # Cached status
        
    def connect(self) -> bool:
        """
        Establish SSH connection.
        
        Creates a master SSH connection using ControlMaster for efficient reuse.
        
        Returns:
            True if connection successful
            
        Raises:
            SSHAuthenticationError: If SSH key authentication fails
            SSHConnectionTimeoutError: If connection times out
            SSHError: For other connection errors
        """
        with self._lock:
            if self._connected and self._check_control_master():
                return True
            
            try:
                # Establish master SSH connection
                self._establish_control_master()
                
                # Test connection with a simple pwd command
                stdout, stderr, returncode = self._execute_sftp_command(['pwd'], timeout=10)
                
                if returncode == 0:
                    self._connected = True
                    
                    # Parse pwd output to get default directory
                    # SFTP pwd output format: "Remote working directory: /path/to/dir"
                    for line in stdout.strip().split('\n'):
                        if line.startswith('Remote working directory:'):
                            self.default_directory = line.split(':', 1)[1].strip()
                            break
                    
                    # Fallback to root if we couldn't parse the directory
                    if not self.default_directory:
                        self.default_directory = '/'
                    
                    self.logger.info(f"Connected to {self.hostname}, default directory: {self.default_directory}")
                    return True
                else:
                    # Parse error message to determine specific error type
                    stderr_lower = stderr.lower()
                    
                    if 'permission denied' in stderr_lower or 'authentication failed' in stderr_lower:
                        error_msg = f"SSH authentication failed for {self.hostname}. Please check your SSH keys and permissions."
                        self.logger.error(error_msg)
                        self.logger.error(f"Detailed error: {stderr}")
                        raise SSHAuthenticationError(error_msg)
                    elif 'connection timed out' in stderr_lower or 'connection refused' in stderr_lower:
                        error_msg = f"Connection timeout to {self.hostname}. Host may be unreachable or not responding."
                        self.logger.error(error_msg)
                        self.logger.error(f"Detailed error: {stderr}")
                        raise SSHConnectionTimeoutError(error_msg)
                    else:
                        error_msg = f"Failed to connect to {self.hostname}: {stderr}"
                        self.logger.error(error_msg)
                        raise SSHError(error_msg)
                    
            except TimeoutError as e:
                error_msg = f"Connection timeout to {self.hostname}: {e}"
                self.logger.error(error_msg)
                raise SSHConnectionTimeoutError(error_msg)
            except (SSHAuthenticationError, SSHConnectionTimeoutError, SSHError):
                # Re-raise SSH-specific errors
                raise
            except Exception as e:
                error_msg = f"Unexpected connection error to {self.hostname}: {e}"
                self.logger.error(error_msg)
                raise SSHError(error_msg)
    
    def disconnect(self):
        """Close the SSH connection and terminate control master."""
        with self._lock:
            if self._connected:
                try:
                    # Close the control master connection
                    self._close_control_master()
                except Exception as e:
                    self.logger.error(f"Error closing control master: {e}")
                finally:
                    self._connected = False
                    self.logger.info(f"Disconnected from {self.hostname}")
    
    def is_connected(self) -> bool:
        """
        Check if connection is active (with caching).
        
        Uses cached control master status to avoid redundant subprocess calls.
        Only performs actual check if the cache interval has elapsed.
        
        Returns:
            True if connected, False otherwise
        """
        with self._lock:
            if not self._connected:
                return False
            
            # Check if we need to verify control master
            import time
            current_time = time.time()
            if current_time - self._last_control_master_check < self._control_master_check_interval:
                # Use cached status (no subprocess call)
                return self._cached_control_master_status
            
            # Perform actual check (subprocess call)
            status = self._check_control_master()
            self._cached_control_master_status = status
            self._last_control_master_check = current_time
            
            if not status:
                self._connected = False
            
            return status
    
    def set_progress_callback(self, callback: Optional[callable]):
        """
        Set progress callback for file transfers.

        The callback is called with (bytes_transferred, total_bytes) as a
        transfer proceeds: once with 0 as it starts, repeatedly while it runs,
        and once with the full size when it completes.

        It doubles as the cancel checkpoint. Anything it raises stops the
        transfer — the ``sftp`` process is killed — and is re-raised unchanged
        to whoever called ``read_file``/``write_file``.

        Args:
            callback: Callable that takes (bytes_transferred: int, total_bytes: int)
                     or None to disable progress tracking
        """
        self._progress_callback = callback
    
    def _establish_control_master(self):
        """
        Establish SSH control master connection for multiplexing.
        
        This creates a persistent SSH connection that can be reused by multiple
        SFTP sessions, dramatically improving performance.
        
        Raises:
            SSHError: If control master cannot be established
        """
        # Build SSH command to establish control master
        # Note: Removed -f flag to allow proper timeout handling and error capture
        # The control master will still persist due to ControlPersist option
        ssh_cmd = ['ssh', '-N']  # -N: no command
        
        # Add control master options
        ssh_cmd.extend([
            '-o', 'ControlMaster=yes',
            '-o', f'ControlPath={self._control_path}',
            '-o', 'ControlPersist=10m',  # Keep connection alive for 10 minutes after last use
        ])
        
        # Add port if specified
        if self.port and self.port != '22':
            ssh_cmd.extend(['-p', str(self.port)])
        
        # Add identity file if specified
        if self.identity_file:
            ssh_cmd.extend(['-i', self.identity_file])
        
        # Add other options
        ssh_cmd.extend(['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new'])
        
        # Add hostname (SSH config alias)
        ssh_cmd.append(self.hostname)
        
        try:
            # Establish control master
            # Use Popen to capture output and control the process
            process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for connection to establish (with timeout)
            # SSH with -N will block, but we just need to verify it starts successfully
            # The ControlPersist option will keep the socket alive after we terminate
            try:
                # Give it a few seconds to establish connection
                stdout, stderr = process.communicate(timeout=10)
                returncode = process.returncode
                
                # Check if socket was created
                socket_created = os.path.exists(self._control_path)
                
                if returncode == 0 and socket_created:
                    # SSH exited successfully and socket exists - connection established
                    self.logger.info(f"Connected to {self.hostname}")
                else:
                    # Process exited with error or socket not created
                    self.logger.error(f"SSH process exited with code {returncode}")
                    
                    if stderr:
                        stderr_lines = stderr.split('\n')
                        self.logger.error(f"SSH stderr ({len(stderr_lines)} lines):")
                        for i, line in enumerate(stderr_lines[:50]):
                            self.logger.error(f"  stderr[{i}]: {line}")
                    
                    error_msg = f"Failed to establish control master: {stderr}"
                    self.logger.error(error_msg)
                    raise SSHError(error_msg)
                    
            except subprocess.TimeoutExpired:
                # Timeout is expected - SSH is blocking with -N
                # This means connection is likely established
                # Capture any output so far
                try:
                    stdout, stderr = process.communicate(timeout=0.1)
                except subprocess.TimeoutExpired:
                    # Still running, which is good
                    pass
                
                # Check if socket was created
                socket_created = os.path.exists(self._control_path)
                
                if socket_created:
                    self.logger.info(f"Connected to {self.hostname}")
                    # Terminate the master process - ControlPersist will keep socket alive
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                else:
                    # Socket not created after timeout - connection failed
                    self.logger.error("Control socket not created after 10 seconds")
                    
                    # Kill process and get output
                    process.kill()
                    stdout, stderr = process.communicate()
                    
                    if stderr:
                        stderr_lines = stderr.split('\n')
                        self.logger.error(f"SSH stderr ({len(stderr_lines)} lines):")
                        for i, line in enumerate(stderr_lines[:50]):
                            self.logger.error(f"  stderr[{i}]: {line}")
                    
                    error_msg = f"Timeout establishing control master for {self.hostname}"
                    self.logger.error(error_msg)
                    raise SSHConnectionTimeoutError(error_msg)
                    
        except subprocess.TimeoutExpired:
            error_msg = f"Timeout establishing control master for {self.hostname}"
            self.logger.error(error_msg)
            raise SSHConnectionTimeoutError(error_msg)
        except Exception as e:
            error_msg = f"Failed to establish control master: {e}"
            self.logger.error(error_msg)
            raise SSHError(error_msg)
    
    def _check_control_master(self) -> bool:
        """
        Check if control master is still active.
        
        Returns:
            True if control master is active, False otherwise
        """
        try:
            # Use ssh -O check to verify control master status
            result = subprocess.run(
                ['ssh', '-O', 'check', '-o', f'ControlPath={self._control_path}', self.hostname],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _close_control_master(self):
        """
        Close the control master connection.
        
        Raises:
            SSHError: If control master cannot be closed
        """
        try:
            # Use ssh -O exit to close control master
            subprocess.run(
                ['ssh', '-O', 'exit', '-o', f'ControlPath={self._control_path}', self.hostname],
                capture_output=True,
                text=True,
                timeout=5
            )
        except Exception as e:
            error_msg = f"Failed to close control master: {e}"
            self.logger.error(error_msg)
            raise SSHError(error_msg)

    def _quote_path(self, path: str) -> str:
        """
        Quote a path for use in SFTP commands.
        
        SFTP batch mode requires paths with spaces or special characters to be quoted.
        This method adds double quotes around the path and escapes any internal quotes.
        
        Args:
            path: Path to quote
            
        Returns:
            Quoted path safe for SFTP commands
        """
        # Escape any double quotes in the path
        escaped_path = path.replace('"', '\\"')
        # Wrap in double quotes
        return f'"{escaped_path}"'
    
    #: Size of a remote file without reading it. GNU coreutils and BSD spell
    #: ``stat`` differently, so try both; a file that does not exist yet (the
    #: upload has not created it) reports 0 rather than failing.
    _REMOTE_SIZE_COMMAND = (
        'stat -c %s -- {p} 2>/dev/null || stat -f %z -- {p} 2>/dev/null || echo 0')

    def _remote_size(self, remote_path: str) -> int:
        """Current size of a remote file, in bytes.

        Runs over the existing ControlMaster, so this is a channel on the
        connection already open — not a new SSH session, and no re-auth.
        """
        command = self._REMOTE_SIZE_COMMAND.format(p=shlex.quote(remote_path))

        ssh_cmd = ['ssh',
                   '-o', f'ControlPath={self._control_path}',
                   '-o', 'ControlMaster=no',
                   '-o', 'BatchMode=yes']
        if self.port and self.port != '22':
            ssh_cmd.extend(['-p', str(self.port)])
        if self.identity_file:
            ssh_cmd.extend(['-i', self.identity_file])
        ssh_cmd.extend([self.hostname, command])

        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=15)
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return int(lines[-1]) if lines else 0

    def _make_transfer_monitor(self, probe, total_bytes: int,
                               interval: float) -> Optional['_TransferMonitor']:
        """Build a monitor for a transfer, or None if nobody is watching."""
        if not self._progress_callback:
            return None
        return _TransferMonitor(probe, total_bytes, self._progress_callback,
                                interval, self.logger)

    def _parse_ls_line(self, line: str) -> Optional[Dict[str, any]]:
        """
        Parse a single line from ls -la output.
        
        Args:
            line: Single line from ls -la output
            
        Returns:
            Dictionary with parsed metadata, or None if parsing fails
            
        Example line:
            -rw-r--r--  1 user group  1234 Jan 15 10:30 filename.txt
            drwxr-xr-x  5 user group  4096 Jan 15 10:30 dirname
        """
        import re
        from datetime import datetime
        
        # Split line into parts
        parts = line.split(None, 8)  # Split on whitespace, max 9 parts
        
        if len(parts) < 9:
            return None
        
        permissions = parts[0]
        # parts[1] is link count (not used)
        # parts[2] is owner (not used)
        # parts[3] is group (not used)
        size_str = parts[4]
        month = parts[5]
        day = parts[6]
        time_or_year = parts[7]
        name = parts[8]
        
        # SFTP's ls output includes full paths in the name field
        # Extract just the basename
        import posixpath
        name = posixpath.basename(name)
        
        # Parse file type and permissions
        is_dir = permissions[0] == 'd'
        is_file = permissions[0] == '-'
        is_symlink = permissions[0] == 'l'
        
        # Convert permissions to octal mode
        mode = 0
        perm_str = permissions[1:]  # Remove first character (file type)
        for i, char in enumerate(perm_str):
            if char in 'rwx':
                # Calculate bit position (rwxrwxrwx = 9 bits)
                bit_pos = 8 - i
                mode |= (1 << bit_pos)
        
        # Parse size
        try:
            size = int(size_str)
        except ValueError:
            size = 0
        
        # Parse modification time
        # Format can be "Jan 15 10:30" or "Jan 15  2023"
        try:
            current_year = datetime.now().year
            if ':' in time_or_year:
                # Time format: assume current year
                time_str = f"{month} {day} {current_year} {time_or_year}"
                dt = datetime.strptime(time_str, "%b %d %Y %H:%M")
            else:
                # Year format
                time_str = f"{month} {day} {time_or_year}"
                dt = datetime.strptime(time_str, "%b %d %Y")
            
            mtime = dt.timestamp()
        except Exception:
            # If parsing fails, use current time
            mtime = time.time()
        
        return {
            'name': name,
            'size': size,
            'mtime': mtime,
            'mode': mode,
            'is_dir': is_dir,
            'is_file': is_file,
            'is_symlink': is_symlink,
        }

    
    def _execute_sftp_command(self, commands: List[str], timeout: int = 30,
                              monitor: Optional['_TransferMonitor'] = None) -> Tuple[str, str, int]:
        """
        Execute SFTP commands using SSH multiplexing.

        Uses the control master connection for efficient command execution.

        Args:
            commands: List of SFTP commands to execute
            timeout: Command timeout in seconds (default: 30), or None for no timeout
            monitor: Optional :class:`_TransferMonitor` to report progress and
                     cancel the transfer. It may kill the process, in which case
                     the non-zero return code here is expected and the caller
                     should raise ``monitor.error`` in preference to it.

        Returns:
            (stdout, stderr, returncode) tuple
            
        Raises:
            SSHConnectionTimeoutError: If command execution exceeds timeout
            SSHConnectionLostError: If connection is lost during execution
            SSHError: For other execution errors
        """
        # Build sftp command
        sftp_cmd = ['sftp', '-b', '-']  # Read commands from stdin
        
        # Add control master options to reuse existing connection
        sftp_cmd.extend([
            '-o', f'ControlPath={self._control_path}',
            '-o', 'ControlMaster=no',  # Don't create new master, use existing
        ])
        
        # Add port if specified
        if self.port and self.port != '22':
            sftp_cmd.extend(['-P', str(self.port)])
        
        # Add identity file if specified
        if self.identity_file:
            sftp_cmd.extend(['-i', self.identity_file])
        
        # Add other options
        sftp_cmd.extend(['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new'])
        
        # Add hostname (SSH config alias)
        sftp_cmd.append(self.hostname)
        
        try:
            # Execute SFTP with commands from stdin
            command_input = '\n'.join(commands) + '\n'
            
            # Use Popen for more control
            process = subprocess.Popen(
                sftp_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if monitor is not None:
                monitor.start(process)

            # Standard timeout or no timeout
            try:
                stdout, stderr = process.communicate(input=command_input, timeout=timeout)
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                error_msg = f"SFTP command timeout after {timeout}s for {self.hostname}"
                self.logger.error(error_msg)
                raise SSHConnectionTimeoutError(error_msg)
            finally:
                if monitor is not None:
                    monitor.stop()

            return stdout, stderr, returncode
            
        except SSHConnectionTimeoutError:
            raise
        except Exception as e:
            error_msg = f"SFTP command execution error for {self.hostname}: {e}"
            self.logger.error(error_msg)
            raise SSHError(error_msg)
    
    def list_directory(self, remote_path: str) -> List[Dict[str, any]]:
        """
        List directory contents.
        
        Args:
            remote_path: Remote directory path
            
        Returns:
            List of file/directory entries with metadata. Each entry is a dict with:
                - name: filename
                - size: file size in bytes
                - mtime: modification time as Unix timestamp
                - mode: file permissions as integer
                - is_dir: True if directory
                - is_file: True if regular file
                - is_symlink: True if symbolic link
            
        Raises:
            SSHPathNotFoundError: If directory does not exist
            SSHPermissionDeniedError: If permission is denied
            SSHConnectionLostError: If connection is lost
            SSHError: For other errors
        """
        if not self._connected:
            raise SSHConnectionLostError(f"Not connected to {self.hostname}")
        
        # Normalize path to remove excessive ./ sequences
        import posixpath
        remote_path = posixpath.normpath(remote_path)
        
        # Try to get from cache first
        cached_result = self._cache.get(
            operation='list_directory',
            hostname=self.hostname,
            path=remote_path
        )
        
        if cached_result is not None:
            return cached_result
        
        # Cache miss - fetch from remote
        commands = [f'ls -la {self._quote_path(remote_path)}']
        stdout, stderr, returncode = self._execute_sftp_command(commands)
        
        if returncode != 0:
            # Parse error to determine specific type
            stderr_lower = stderr.lower()
            
            if 'no such file' in stderr_lower or 'not found' in stderr_lower:
                error_msg = f"Remote path not found: {remote_path}"
                # Use debug level since this is often used to check if path exists
                self.logger.debug(error_msg)
                self.logger.debug(f"Detailed error: {stderr}")
                error = SSHPathNotFoundError(error_msg)
                # Cache the error to avoid repeated SFTP calls
                self._cache.put(
                    operation='list_directory',
                    hostname=self.hostname,
                    path=remote_path,
                    error=error
                )
                raise error
            elif 'permission denied' in stderr_lower:
                error_msg = f"Permission denied accessing: {remote_path}"
                self.logger.error(error_msg)
                self.logger.error(f"Detailed error: {stderr}")
                error = SSHPermissionDeniedError(error_msg)
                # Cache the error to avoid repeated SFTP calls
                self._cache.put(
                    operation='list_directory',
                    hostname=self.hostname,
                    path=remote_path,
                    error=error
                )
                raise error
            else:
                error_msg = f"Failed to list directory {remote_path}: {stderr}"
                self.logger.error(error_msg)
                raise SSHError(error_msg)
        
        # Parse ls -la output
        entries = []
        for line in stdout.strip().split('\n'):
            if not line or line.startswith('sftp>') or line.startswith('total'):
                continue
            
            entry = self._parse_ls_line(line)
            if entry:
                # Skip . and .. entries (check after parsing)
                if entry['name'] in ('.', '..'):
                    continue
                
                entries.append(entry)
                
                # Cache individual stat for this file
                import posixpath
                file_path = posixpath.join(remote_path, entry['name'])
                self._cache.put(
                    operation='stat',
                    hostname=self.hostname,
                    path=file_path,
                    data=entry
                )
        
        # Store in cache
        self._cache.put(
            operation='list_directory',
            hostname=self.hostname,
            path=remote_path,
            data=entries
        )
        
        return entries
    
    def stat(self, remote_path: str) -> Dict[str, any]:
        """
        Get file/directory metadata.
        
        Args:
            remote_path: Remote file/directory path
            
        Returns:
            Dictionary with stat information:
                - name: filename
                - size: file size in bytes
                - mtime: modification time as Unix timestamp
                - mode: file permissions as integer
                - is_dir: True if directory
                - is_file: True if regular file
                - is_symlink: True if symbolic link
            
        Raises:
            SSHPathNotFoundError: If path does not exist
            SSHPermissionDeniedError: If permission is denied
            SSHConnectionLostError: If connection is lost
            SSHError: For other errors
        """
        if not self._connected:
            raise SSHConnectionLostError(f"Not connected to {self.hostname}")
        
        # Normalize path to remove excessive ./ sequences
        import posixpath
        remote_path = posixpath.normpath(remote_path)
        
        # Try to get from cache first
        cached_result = self._cache.get(
            operation='stat',
            hostname=self.hostname,
            path=remote_path
        )
        
        if cached_result is not None:
            self.logger.debug(f"stat() cache HIT for {remote_path}")
            return cached_result
        
        # Cache miss - fetch from remote
        self.logger.debug(f"stat() cache MISS for {remote_path}, fetching from remote")
        # SFTP's ls command doesn't support -d flag
        # Try ls -l first (works for files and will list directory contents for dirs)
        commands = [f'ls -l {self._quote_path(remote_path)}']
        stdout, stderr, returncode = self._execute_sftp_command(commands)
        
        if returncode != 0:
            # Parse error to determine specific type
            stderr_lower = stderr.lower()
            
            if 'no such file' in stderr_lower or 'not found' in stderr_lower:
                error_msg = f"Remote path not found: {remote_path}"
                # Use debug level since this is often used to check if path exists
                self.logger.debug(error_msg)
                self.logger.debug(f"Detailed error: {stderr}")
                error = SSHPathNotFoundError(error_msg)
                # Cache the error to avoid repeated SFTP calls
                self._cache.put(
                    operation='stat',
                    hostname=self.hostname,
                    path=remote_path,
                    error=error
                )
                raise error
            elif 'permission denied' in stderr_lower:
                error_msg = f"Permission denied accessing: {remote_path}"
                self.logger.error(error_msg)
                self.logger.error(f"Detailed error: {stderr}")
                error = SSHPermissionDeniedError(error_msg)
                # Cache the error to avoid repeated SFTP calls
                self._cache.put(
                    operation='stat',
                    hostname=self.hostname,
                    path=remote_path,
                    error=error
                )
                raise error
            else:
                error_msg = f"Failed to stat path {remote_path}: {stderr}"
                self.logger.error(error_msg)
                raise SSHError(error_msg)
        
        # Parse ls -l output
        lines = [line for line in stdout.strip().split('\n') if line and not line.startswith('sftp>')]
        
        # If we got exactly one line, it's a file
        if len(lines) == 1:
            entry = self._parse_ls_line(lines[0])
            if entry:
                # Store in cache
                self._cache.put(
                    operation='stat',
                    hostname=self.hostname,
                    path=remote_path,
                    data=entry
                )
                return entry
        
        # If we got multiple lines OR zero lines (empty directory), it's a directory
        # We need to get the parent directory and find this entry
        if len(lines) != 1:
            # Extract parent directory and basename
            import posixpath
            
            # Normalize path to handle double slashes
            normalized_path = posixpath.normpath(remote_path)
            
            # Special case for root directory
            if normalized_path == '/':
                # Root directory - create a synthetic entry
                root_entry = {
                    'name': '/',
                    'size': 4096,
                    'mtime': 0,
                    'mode': 0o755,
                    'is_dir': True,
                    'is_file': False,
                    'is_symlink': False,
                }
                # Store in cache
                self._cache.put(
                    operation='stat',
                    hostname=self.hostname,
                    path=remote_path,
                    data=root_entry
                )
                return root_entry
            
            parent_dir = posixpath.dirname(normalized_path)
            basename = posixpath.basename(normalized_path)
            
            # If parent is empty, it means we're at root level
            if not parent_dir:
                parent_dir = '/'
            
            # List parent directory
            commands = [f'ls -l {self._quote_path(parent_dir)}']
            stdout, stderr, returncode = self._execute_sftp_command(commands)
            
            if returncode == 0:
                for line in stdout.strip().split('\n'):
                    if line and not line.startswith('sftp>'):
                        entry = self._parse_ls_line(line)
                        if entry and entry['name'] == basename:
                            # Store in cache
                            self._cache.put(
                                operation='stat',
                                hostname=self.hostname,
                                path=remote_path,
                                data=entry
                            )
                            return entry
        
        error_msg = f"Failed to parse stat output for {remote_path}"
        self.logger.error(error_msg)
        raise SSHError(error_msg)
    
    def read_file(self, remote_path: str) -> bytes:
        """
        Read file contents.
        
        Args:
            remote_path: Remote file path
            
        Returns:
            File contents as bytes
            
        Raises:
            SSHPathNotFoundError: If file does not exist
            SSHPermissionDeniedError: If permission is denied
            SSHConnectionLostError: If connection is lost
            SSHError: For other errors
        """
        if not self._connected:
            raise SSHConnectionLostError(f"Not connected to {self.hostname}")
        
        import tempfile
        import os
        
        # Create a temporary file to download to
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            # Get file size first for progress tracking
            file_size = 0
            try:
                stat_info = self.stat(remote_path)
                file_size = stat_info.get('size', 0)
            except (SSHPathNotFoundError, SSHPermissionDeniedError):
                # Re-raise these specific errors
                raise
            except Exception:
                # If stat fails for other reasons, continue without progress tracking
                pass
            
            # Download file using get command
            commands = [f'get {self._quote_path(remote_path)} {self._quote_path(tmp_path)}']
            
            # No timeout for file transfers - let SFTP handle it
            # SFTP has its own timeout mechanisms and will handle stalled transfers
            timeout = None
            
            self.logger.info(f"Downloading {file_size} bytes (no timeout - SFTP handles it)")

            # A download's byte count is free: sftp is filling tmp_path, so its
            # size on disk is exactly how far the transfer has got
            monitor = self._make_transfer_monitor(
                lambda: os.path.getsize(tmp_path), file_size, self._DOWNLOAD_POLL)

            # Execute download without timeout - SFTP handles timeouts internally
            try:
                stdout, stderr, returncode = self._execute_sftp_command(
                    commands,
                    timeout=timeout,
                    monitor=monitor
                )
            except (SSHPathNotFoundError, SSHPermissionDeniedError, SSHConnectionLostError):
                # Re-raise SSH-specific errors
                raise
            except SSHConnectionTimeoutError:
                raise
            except Exception as e:
                error_msg = f"Unexpected error reading file {remote_path}: {e}"
                self.logger.error(error_msg)
                raise SSHError(error_msg)

            # A cancel arrives as an exception from the caller's progress
            # callback. It is not a transfer failure, so it is re-raised as-is
            # and ahead of the killed process's return code.
            if monitor is not None and monitor.error is not None:
                raise monitor.error

            if returncode != 0:
                # Parse error to determine specific type
                stderr_lower = stderr.lower()

                if 'no such file' in stderr_lower or 'not found' in stderr_lower:
                    error_msg = f"Remote file not found: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPathNotFoundError(error_msg)
                elif 'permission denied' in stderr_lower:
                    error_msg = f"Permission denied reading: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPermissionDeniedError(error_msg)
                else:
                    error_msg = f"Failed to read file {remote_path}: {stderr}"
                    self.logger.error(error_msg)
                    raise SSHError(error_msg)

            if monitor is not None:
                monitor.finish()


            # Read the downloaded file
            with open(tmp_path, 'rb') as f:
                data = f.read()
            
            return data
            
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    def write_file(self, remote_path: str, data: bytes):
        """
        Write file contents.
        
        Args:
            remote_path: Remote file path
            data: File contents as bytes
            
        Raises:
            SSHPermissionDeniedError: If permission is denied
            SSHConnectionLostError: If connection is lost
            SSHError: For other errors (e.g., disk full)
        """
        if not self._connected:
            raise SSHConnectionLostError(f"Not connected to {self.hostname}")
        
        import tempfile
        import os
        
        # Create a temporary file with the data
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        
        try:
            file_size = len(data)
            
            # Upload file using put command
            commands = [f'put {self._quote_path(tmp_path)} {self._quote_path(remote_path)}']
            
            # No timeout for file transfers - let SFTP handle it
            # SFTP has its own timeout mechanisms and will handle stalled transfers
            timeout = None
            
            self.logger.info(f"Uploading {file_size} bytes (no timeout - SFTP handles it)")

            # An upload has no growing local file to watch — the source is
            # already complete — so the byte count comes from the remote file
            # sftp is filling, sampled over the connection already open
            monitor = self._make_transfer_monitor(
                lambda: self._remote_size(remote_path), file_size, self._UPLOAD_POLL)

            # Execute upload without timeout - SFTP handles timeouts internally
            try:
                stdout, stderr, returncode = self._execute_sftp_command(
                    commands,
                    timeout=timeout,
                    monitor=monitor
                )
            except (SSHPermissionDeniedError, SSHConnectionLostError):
                # Re-raise SSH-specific errors
                raise
            except SSHConnectionTimeoutError:
                raise
            except Exception as e:
                error_msg = f"Unexpected error writing file {remote_path}: {e}"
                self.logger.error(error_msg)
                raise SSHError(error_msg)

            # A cancel arrives as an exception from the caller's progress
            # callback. It is not a transfer failure, so it is re-raised as-is
            # and ahead of the killed process's return code.
            if monitor is not None and monitor.error is not None:
                # The remote file holds however much arrived before the kill
                self._cache.invalidate_path(self.hostname, remote_path)
                raise monitor.error

            if returncode != 0:
                # Parse error to determine specific type
                stderr_lower = stderr.lower()

                if 'permission denied' in stderr_lower:
                    error_msg = f"Permission denied writing to: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPermissionDeniedError(error_msg)
                elif 'no space' in stderr_lower or 'disk full' in stderr_lower:
                    error_msg = f"Disk full on remote system: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHError(error_msg)
                else:
                    error_msg = f"Failed to write file {remote_path}: {stderr}"
                    self.logger.error(error_msg)
                    raise SSHError(error_msg)

            if monitor is not None:
                monitor.finish()

            # Invalidate cache after successful write
            self._cache.invalidate_path(self.hostname, remote_path)
                
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    def delete_file(self, remote_path: str):
        """
        Delete a file.
        
        Args:
            remote_path: Remote file path
            
        Raises:
            SSHPathNotFoundError: If file does not exist
            SSHPermissionDeniedError: If permission is denied
            SSHConnectionLostError: If connection is lost
            SSHError: For other errors
        """
        if not self._connected:
            raise SSHConnectionLostError(f"Not connected to {self.hostname}")
        
        try:
            commands = [f'rm {self._quote_path(remote_path)}']
            stdout, stderr, returncode = self._execute_sftp_command(commands)
            
            if returncode != 0:
                # Parse error to determine specific type
                stderr_lower = stderr.lower()
                
                if 'no such file' in stderr_lower or 'not found' in stderr_lower:
                    error_msg = f"Remote file not found: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPathNotFoundError(error_msg)
                elif 'permission denied' in stderr_lower:
                    error_msg = f"Permission denied deleting: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPermissionDeniedError(error_msg)
                else:
                    error_msg = f"Failed to delete file {remote_path}: {stderr}"
                    self.logger.error(error_msg)
                    raise SSHError(error_msg)
                    
        except (SSHPathNotFoundError, SSHPermissionDeniedError, SSHConnectionLostError):
            # Re-raise SSH-specific errors
            raise
        except Exception as e:
            error_msg = f"Unexpected error deleting file {remote_path}: {e}"
            self.logger.error(error_msg)
            raise SSHError(error_msg)
        
        # Invalidate cache after successful delete
        self._cache.invalidate_path(self.hostname, remote_path)
    
    def delete_directory(self, remote_path: str):
        """
        Delete a directory (must be empty).
        
        Args:
            remote_path: Remote directory path
            
        Raises:
            SSHPathNotFoundError: If directory does not exist
            SSHPermissionDeniedError: If permission is denied
            SSHConnectionLostError: If connection is lost
            SSHError: For other errors (e.g., directory not empty)
        """
        if not self._connected:
            raise SSHConnectionLostError(f"Not connected to {self.hostname}")
        
        try:
            commands = [f'rmdir {self._quote_path(remote_path)}']
            stdout, stderr, returncode = self._execute_sftp_command(commands)
            
            if returncode != 0:
                # Parse error to determine specific type
                stderr_lower = stderr.lower()
                
                if 'no such file' in stderr_lower or 'not found' in stderr_lower:
                    error_msg = f"Remote directory not found: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPathNotFoundError(error_msg)
                elif 'permission denied' in stderr_lower:
                    error_msg = f"Permission denied deleting directory: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPermissionDeniedError(error_msg)
                elif 'not empty' in stderr_lower or 'directory not empty' in stderr_lower:
                    error_msg = f"Directory not empty: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHError(error_msg)
                else:
                    error_msg = f"Failed to delete directory {remote_path}: {stderr}"
                    self.logger.error(error_msg)
                    raise SSHError(error_msg)
                    
        except (SSHPathNotFoundError, SSHPermissionDeniedError, SSHConnectionLostError):
            # Re-raise SSH-specific errors
            raise
        except Exception as e:
            error_msg = f"Unexpected error deleting directory {remote_path}: {e}"
            self.logger.error(error_msg)
            raise SSHError(error_msg)
        
        # Invalidate cache after successful delete
        self._cache.invalidate_directory(self.hostname, remote_path)
    
    def create_directory(self, remote_path: str):
        """
        Create a directory.
        
        Args:
            remote_path: Remote directory path
            
        Raises:
            SSHPermissionDeniedError: If permission is denied
            SSHConnectionLostError: If connection is lost
            SSHError: For other errors (e.g., parent directory doesn't exist)
        """
        if not self._connected:
            raise SSHConnectionLostError(f"Not connected to {self.hostname}")
        
        try:
            commands = [f'mkdir {self._quote_path(remote_path)}']
            stdout, stderr, returncode = self._execute_sftp_command(commands)
            
            if returncode != 0:
                # Parse error to determine specific type
                stderr_lower = stderr.lower()
                
                if 'permission denied' in stderr_lower:
                    error_msg = f"Permission denied creating directory: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPermissionDeniedError(error_msg)
                elif 'no such file' in stderr_lower or 'not found' in stderr_lower:
                    error_msg = f"Parent directory not found for: {remote_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPathNotFoundError(error_msg)
                else:
                    error_msg = f"Failed to create directory {remote_path}: {stderr}"
                    self.logger.error(error_msg)
                    raise SSHError(error_msg)
                    
        except (SSHPathNotFoundError, SSHPermissionDeniedError, SSHConnectionLostError):
            # Re-raise SSH-specific errors
            raise
        except Exception as e:
            error_msg = f"Unexpected error creating directory {remote_path}: {e}"
            self.logger.error(error_msg)
            raise SSHError(error_msg)
        
        # Invalidate cache after successful create
        self._cache.invalidate_path(self.hostname, remote_path)
    
    def rename(self, old_path: str, new_path: str):
        """
        Rename/move a file or directory.
        
        Args:
            old_path: Current path
            new_path: New path
            
        Raises:
            SSHPathNotFoundError: If source path does not exist
            SSHPermissionDeniedError: If permission is denied
            SSHConnectionLostError: If connection is lost
            SSHError: For other errors
        """
        if not self._connected:
            raise SSHConnectionLostError(f"Not connected to {self.hostname}")
        
        try:
            commands = [f'rename {self._quote_path(old_path)} {self._quote_path(new_path)}']
            stdout, stderr, returncode = self._execute_sftp_command(commands)
            
            if returncode != 0:
                # Parse error to determine specific type
                stderr_lower = stderr.lower()
                
                if 'no such file' in stderr_lower or 'not found' in stderr_lower:
                    error_msg = f"Remote path not found: {old_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPathNotFoundError(error_msg)
                elif 'permission denied' in stderr_lower:
                    error_msg = f"Permission denied renaming {old_path} to {new_path}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Detailed error: {stderr}")
                    raise SSHPermissionDeniedError(error_msg)
                else:
                    error_msg = f"Failed to rename {old_path} to {new_path}: {stderr}"
                    self.logger.error(error_msg)
                    raise SSHError(error_msg)
                    
        except (SSHPathNotFoundError, SSHPermissionDeniedError, SSHConnectionLostError):
            # Re-raise SSH-specific errors
            raise
        except Exception as e:
            error_msg = f"Unexpected error renaming {old_path} to {new_path}: {e}"
            self.logger.error(error_msg)
            raise SSHError(error_msg)
        
        # Invalidate cache for both old and new paths after successful rename
        self._cache.invalidate_path(self.hostname, old_path)
        self._cache.invalidate_path(self.hostname, new_path)


class SSHConnectionManager:
    """
    Manages SSH connections with connection pooling and lifecycle management.
    
    Singleton pattern ensures only one manager exists per application instance.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(cls) -> 'SSHConnectionManager':
        """
        Get the singleton instance.
        
        Returns:
            SSHConnectionManager singleton instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize connection manager."""
        if SSHConnectionManager._instance is not None:
            raise RuntimeError("Use get_instance() to get SSHConnectionManager")
        
        self._connections: Dict[str, SSHConnection] = {}
        self._connection_lock = threading.Lock()
        self._last_used: Dict[str, float] = {}
        self._timeout = 300  # 5 minutes idle timeout
        self._health_check_interval = 60  # Check connection health every 60 seconds
        self._last_health_check: Dict[str, float] = {}
        self.logger = getLogger("SSHCon")
    
    def _check_connection_health(self, hostname: str, conn: SSHConnection) -> bool:
        """
        Check if a connection is still healthy (optimized).
        
        Performs a lightweight health check by verifying control master status.
        Health checks are rate-limited to avoid excessive overhead.
        Uses cached connection status within the health check interval.
        
        Args:
            hostname: Remote hostname
            conn: SSHConnection to check
            
        Returns:
            True if connection is healthy, False otherwise
        """
        current_time = time.time()
        
        # Check if we've done a health check recently
        last_check = self._last_health_check.get(hostname, 0)
        if current_time - last_check < self._health_check_interval:
            # Trust the connection's internal status without forcing a check
            # This avoids subprocess calls within the health check interval
            with conn._lock:
                return conn._connected
        
        # Health check interval elapsed, perform actual check
        try:
            if conn.is_connected():
                self._last_health_check[hostname] = current_time
                return True
            else:
                self.logger.warning(f"Health check failed for {hostname}: control master not active")
                return False
                
        except Exception as e:
            self.logger.warning(f"Health check failed for {hostname}: {e}")
            return False
    
    def get_connection(self, hostname: str, config: Dict[str, str]) -> SSHConnection:
        """
        Get or create connection for hostname.
        
        Implements automatic reconnection on connection loss and health checks.
        
        Args:
            hostname: Remote hostname
            config: SSH configuration
            
        Returns:
            SSHConnection instance
            
        Raises:
            SSHAuthenticationError: If authentication fails
            SSHConnectionTimeoutError: If connection times out
            SSHError: For other connection errors
        """
        with self._connection_lock:
            # Check if connection exists
            if hostname in self._connections:
                conn = self._connections[hostname]
                
                # Perform health check
                if self._check_connection_health(hostname, conn):
                    self._last_used[hostname] = time.time()
                    self.logger.debug(f"Reusing connection to {hostname}")
                    return conn
                else:
                    # Connection unhealthy, attempt reconnection
                    self.logger.warning(f"Connection to {hostname} unhealthy, attempting reconnection")
                    del self._connections[hostname]
                    del self._last_used[hostname]
                    if hostname in self._last_health_check:
                        del self._last_health_check[hostname]
                    
                    # Try to reconnect once
                    try:
                        conn = SSHConnection(hostname, config)
                        conn.connect()  # This will raise specific exceptions on failure
                        
                        self._connections[hostname] = conn
                        self._last_used[hostname] = time.time()
                        self._last_health_check[hostname] = time.time()
                        self.logger.info(f"Reconnected to {hostname}")
                        
                        return conn
                    except (SSHAuthenticationError, SSHConnectionTimeoutError, SSHError) as e:
                        # Log the reconnection failure and re-raise
                        self.logger.error(f"Reconnection to {hostname} failed: {e}")
                        raise
            
            # Create new connection
            conn = SSHConnection(hostname, config)
            conn.connect()  # This will raise specific exceptions on failure
            
            self._connections[hostname] = conn
            self._last_used[hostname] = time.time()
            self._last_health_check[hostname] = time.time()
            self.logger.info(f"Created new connection to {hostname}")
            
            return conn
    
    def close_connection(self, hostname: str):
        """
        Close connection for hostname.
        
        Args:
            hostname: Remote hostname
        """
        with self._connection_lock:
            if hostname in self._connections:
                self._connections[hostname].disconnect()
                del self._connections[hostname]
                del self._last_used[hostname]
                if hostname in self._last_health_check:
                    del self._last_health_check[hostname]
                self.logger.info(f"Closed connection to {hostname}")
    
    def close_all(self):
        """Close all connections gracefully."""
        with self._connection_lock:
            for hostname in list(self._connections.keys()):
                try:
                    self._connections[hostname].disconnect()
                except Exception as e:
                    self.logger.error(f"Error disconnecting from {hostname}: {e}")
            self._connections.clear()
            self._last_used.clear()
            self._last_health_check.clear()
            self.logger.info("Closed all connections")
    
    def cleanup_idle_connections(self):
        """Close connections that have been idle beyond timeout."""
        current_time = time.time()
        
        with self._connection_lock:
            idle_hosts = []
            for hostname, last_used in self._last_used.items():
                if current_time - last_used > self._timeout:
                    idle_hosts.append(hostname)
            
            for hostname in idle_hosts:
                self.logger.info(f"Closing idle connection to {hostname}")
                try:
                    self._connections[hostname].disconnect()
                except Exception as e:
                    self.logger.error(f"Error disconnecting from {hostname}: {e}")
                del self._connections[hostname]
                del self._last_used[hostname]
                if hostname in self._last_health_check:
                    del self._last_health_check[hostname]
    
    def check_connection_health(self, hostname: str) -> bool:
        """
        Check if a connection is healthy by verifying control master status.
        
        Args:
            hostname: Remote hostname to check
            
        Returns:
            True if connection is healthy, False otherwise
        """
        with self._connection_lock:
            if hostname not in self._connections:
                return False
            
            conn = self._connections[hostname]
            try:
                return conn.is_connected()
            except Exception as e:
                self.logger.warning(f"Health check failed for {hostname}: {e}")
                return False
    
    def get_active_connections(self) -> list:
        """
        Get list of currently active connection hostnames.
        
        Returns:
            List of hostnames with active connections
        """
        with self._connection_lock:
            return list(self._connections.keys())


def cleanup_ssh_connections():
    """
    Clean up all SSH connections on application exit.
    
    This function should be called during application shutdown to ensure
    all SSH connections are properly closed.
    """
    try:
        manager = SSHConnectionManager.get_instance()
        manager.close_all()
    except Exception as e:
        # Use module-level logger for cleanup
        logger = getLogger("SSHCon")
        logger.error(f"Error during SSH connection cleanup: {e}")

