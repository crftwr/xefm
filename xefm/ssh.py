"""
SSH Path Implementation for XeFM

This module provides SSH/SFTP path implementation that integrates with XeFM's
Path polymorphism architecture. It allows browsing and manipulating files on
remote systems through SSH connections.
"""

import io
import stat as stat_module
from typing import Iterator, List, Optional
from datetime import datetime
from xefm.log_manager import getLogger
from xefm.str_format import format_size


class SSHPathImpl:
    """
    SSH/SFTP implementation of PathImpl.
    
    Represents paths on remote systems accessible via SSH/SFTP.
    URI format: ssh://hostname/path/to/file
    """
    
    def __init__(self, uri: str):
        """
        Initialize SSH path from URI.
        
        Args:
            uri: SSH URI in format ssh://hostname/path/to/file
        
        Raises:
            ValueError: If URI format is invalid
        """
        self.logger = getLogger("SSHPath")
        self._uri = uri
        self.hostname, self.remote_path = self._parse_uri(uri)
        
        # Import here to avoid circular dependency
        from xefm.ssh_config import SSHConfigParser
        from xefm.ssh_connection import SSHConnectionManager
        
        # Get SSH config for this hostname
        parser = SSHConfigParser()
        hosts = parser.parse()
        self.config = hosts.get(self.hostname, {'HostName': self.hostname})
        
        # Get connection manager
        self._conn_manager = SSHConnectionManager.get_instance()
    
    def _parse_uri(self, uri: str) -> tuple:
        """
        Parse SSH URI into components.
        
        Args:
            uri: SSH URI in format ssh://hostname/path/to/file
        
        Returns:
            (hostname, remote_path) tuple
            
        Raises:
            ValueError: If URI format is invalid
        """
        if not uri.startswith('ssh://'):
            raise ValueError(f"Invalid SSH URI: {uri}")
        
        # Remove ssh:// prefix
        remainder = uri[6:]
        
        # Split into hostname and path
        if '/' in remainder:
            hostname, path = remainder.split('/', 1)
            remote_path = '/' + path
        else:
            hostname = remainder
            remote_path = '/'
        
        if not hostname:
            raise ValueError(f"Invalid SSH URI: missing hostname in {uri}")
        
        return hostname, remote_path
    
    def _get_connection(self):
        """
        Get or create SSH connection for this host.
        
        Returns:
            SSHConnection instance for the hostname
        """
        return self._conn_manager.get_connection(self.hostname, self.config)
    
    def __str__(self) -> str:
        """String representation of the path"""
        return self._uri
    
    def __eq__(self, other) -> bool:
        """Equality comparison"""
        if isinstance(other, SSHPathImpl):
            return self._uri == other._uri
        elif isinstance(other, str):
            return self._uri == other
        return False
    
    def __hash__(self) -> int:
        """Hash support for use in sets and dicts"""
        return hash(self._uri)
    
    def __lt__(self, other) -> bool:
        """Less than comparison for sorting"""
        if isinstance(other, SSHPathImpl):
            return self._uri < other._uri
        return self._uri < str(other)
    
    # Properties
    @property
    def name(self) -> str:
        """The final component of the path"""
        if self.remote_path == '/':
            return ''
        return self.remote_path.rstrip('/').split('/')[-1]
    
    @property
    def stem(self) -> str:
        """The final component without its suffix"""
        name = self.name
        if '.' in name:
            return name.rsplit('.', 1)[0]
        return name
    
    @property
    def suffix(self) -> str:
        """The file extension of the final component"""
        name = self.name
        if '.' in name:
            return '.' + name.rsplit('.', 1)[1]
        return ''
    
    @property
    def suffixes(self) -> List[str]:
        """A list of the path's suffixes"""
        name = self.name
        if '.' not in name:
            return []
        parts = name.split('.')
        return ['.' + part for part in parts[1:]]
    
    @property
    def parent(self):
        """The logical parent of the path"""
        if self.remote_path == '/':
            return self  # Root has no parent
        
        parent_path = self.remote_path.rstrip('/').rsplit('/', 1)[0]
        if not parent_path:
            parent_path = '/'
        
        # Ensure parent_path starts with /
        if not parent_path.startswith('/'):
            parent_path = '/' + parent_path
        
        parent_uri = f"ssh://{self.hostname}{parent_path}"
        
        # Import Path here to avoid circular dependency
        from xefm.path import Path
        return Path(parent_uri)
    
    @property
    def parents(self):
        """A sequence providing access to the logical ancestors of the path"""
        parents_list = []
        current = self.parent
        while str(current) != str(self):
            parents_list.append(current)
            current = current.parent
        return parents_list
    
    @property
    def parts(self) -> tuple:
        """A tuple giving access to the path's components"""
        if self.remote_path == '/':
            return (f'ssh://{self.hostname}', '/')
        
        path_parts = self.remote_path.strip('/').split('/')
        return (f'ssh://{self.hostname}', '/') + tuple(path_parts)
    
    @property
    def anchor(self) -> str:
        """The concatenation of the drive and root"""
        return f'ssh://{self.hostname}/'
    
    # Path manipulation methods
    def absolute(self):
        """Return an absolute version of this path"""
        # SSH paths are always absolute
        return self._make_path(self._uri)
    
    def resolve(self, strict: bool = False):
        """Make the path absolute, resolving any symlinks"""
        # For now, just return absolute path
        # TODO: Could resolve symlinks via SSH if needed
        return self.absolute()
    
    def expanduser(self):
        """Return a new path with expanded ~ and ~user constructs"""
        # SSH paths don't support ~ expansion in URI
        return self._make_path(self._uri)
    
    def joinpath(self, *args):
        """Combine this path with one or several arguments"""
        # Build new path by joining components
        new_path = self.remote_path.rstrip('/')
        for arg in args:
            arg_str = str(arg).lstrip('/')
            new_path = new_path + '/' + arg_str
        
        new_uri = f"ssh://{self.hostname}{new_path}"
        return self._make_path(new_uri)
    
    def with_name(self, name: str):
        """Return a new path with the name changed"""
        parent_path = self.remote_path.rstrip('/').rsplit('/', 1)[0]
        if not parent_path:
            parent_path = '/'
        
        new_path = parent_path.rstrip('/') + '/' + name
        new_uri = f"ssh://{self.hostname}{new_path}"
        return self._make_path(new_uri)
    
    def with_stem(self, stem: str):
        """Return a new path with the stem changed"""
        new_name = stem + self.suffix
        return self.with_name(new_name)
    
    def with_suffix(self, suffix: str):
        """Return a new path with the suffix changed"""
        new_name = self.stem + suffix
        return self.with_name(new_name)
    
    def relative_to(self, other):
        """Return a version of this path relative to the other path"""
        # Import Path here to avoid circular dependency
        from xefm.path import Path
        
        other_str = str(other)
        self_str = str(self)
        
        if not self_str.startswith(other_str):
            raise ValueError(f"{self_str} is not relative to {other_str}")
        
        relative = self_str[len(other_str):].lstrip('/')
        return Path(relative) if relative else Path('.')
    
    def _make_path(self, uri: str):
        """Helper to create a Path object from URI"""
        from xefm.path import Path
        return Path(uri)
    
    # File system query methods
    def exists(self) -> bool:
        """Whether this path exists"""
        try:
            conn = self._get_connection()
            conn.stat(self.remote_path)
            return True
        except Exception:
            return False
    
    def is_dir(self) -> bool:
        """Whether this path is a directory"""
        try:
            conn = self._get_connection()
            stat_info = conn.stat(self.remote_path)
            return stat_info.get('is_dir', False)
        except Exception:
            return False
    
    def is_file(self) -> bool:
        """Whether this path is a regular file"""
        try:
            conn = self._get_connection()
            stat_info = conn.stat(self.remote_path)
            return stat_info.get('is_file', False)
        except Exception:
            return False
    
    def is_symlink(self) -> bool:
        """Whether this path is a symbolic link"""
        try:
            conn = self._get_connection()
            stat_info = conn.stat(self.remote_path)
            return stat_info.get('is_symlink', False)
        except Exception:
            return False
    
    def is_absolute(self) -> bool:
        """Whether this path is absolute"""
        # SSH paths are always absolute
        return True
    
    def stat(self):
        """Return the result of os.stat() on this path"""
        conn = self._get_connection()
        stat_info = conn.stat(self.remote_path)
        
        # Convert to os.stat_result-like object
        # Create a simple namespace object with the required attributes
        class StatResult:
            def __init__(self, info):
                self.st_size = info.get('size', 0)
                self.st_mtime = info.get('mtime', 0)
                self.st_mode = info.get('mode', 0)
                # Add other stat fields with defaults
                self.st_atime = self.st_mtime
                self.st_ctime = self.st_mtime
                self.st_uid = 0
                self.st_gid = 0
                self.st_ino = 0
                self.st_dev = 0
                self.st_nlink = 1
        
        return StatResult(stat_info)
    
    def lstat(self):
        """Return the result of os.lstat() on this path"""
        # For SSH, lstat is the same as stat
        return self.stat()
    
    # Directory operations
    def iterdir(self) -> Iterator:
        """Iterate over the files in this directory"""
        conn = self._get_connection()
        entries = conn.list_directory(self.remote_path)
        
        for entry in entries:
            entry_name = entry['name']
            entry_path = self.remote_path.rstrip('/') + '/' + entry_name
            entry_uri = f"ssh://{self.hostname}{entry_path}"
            yield self._make_path(entry_uri)
    
    def glob(self, pattern: str) -> Iterator:
        """Iterate over this subtree and yield all existing files matching pattern"""
        import fnmatch
        
        # Simple implementation: list directory and filter
        if self.is_dir():
            for item in self.iterdir():
                if fnmatch.fnmatch(item.name, pattern):
                    yield item
    
    def rglob(self, pattern: str) -> Iterator:
        """Recursively iterate over this subtree and yield all existing files matching pattern"""
        import fnmatch
        
        # Recursive implementation
        def _rglob_recursive(path):
            if path.is_dir():
                for item in path.iterdir():
                    if fnmatch.fnmatch(item.name, pattern):
                        yield item
                    if item.is_dir():
                        yield from _rglob_recursive(item)
        
        yield from _rglob_recursive(self)
    
    def match(self, pattern: str) -> bool:
        """Return True if this path matches the given pattern"""
        import fnmatch
        return fnmatch.fnmatch(self.remote_path, pattern)
    
    # File I/O operations
    def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        """Open the file pointed to by this path"""
        # For SSH, we need to read the entire file into memory
        # and return a file-like object
        conn = self._get_connection()
        
        if 'r' in mode:
            # Read mode
            data = conn.read_file(self.remote_path)
            if 'b' in mode:
                return io.BytesIO(data)
            else:
                text = data.decode(encoding or 'utf-8', errors or 'strict')
                return io.StringIO(text)
        elif 'w' in mode or 'a' in mode:
            # Write/append mode - return a writable buffer
            # that will be uploaded on close
            class SSHFileWriter:
                def __init__(self, path_impl, mode, encoding):
                    self.path_impl = path_impl
                    self.mode = mode
                    self.encoding = encoding
                    self.buffer = io.BytesIO() if 'b' in mode else io.StringIO()
                    self.closed = False
                
                def write(self, data):
                    return self.buffer.write(data)
                
                def close(self):
                    if not self.closed:
                        self.closed = True
                        # Upload the buffer content
                        self.buffer.seek(0)
                        if isinstance(self.buffer, io.BytesIO):
                            data = self.buffer.read()
                        else:
                            data = self.buffer.read().encode(self.encoding or 'utf-8')
                        
                        conn = self.path_impl._get_connection()
                        conn.write_file(self.path_impl.remote_path, data)
                
                def __enter__(self):
                    return self
                
                def __exit__(self, exc_type, exc_val, exc_tb):
                    self.close()
            
            return SSHFileWriter(self, mode, encoding)
        else:
            raise ValueError(f"Unsupported mode: {mode}")
    
    def read_text(self, encoding=None, errors=None) -> str:
        """Open the file in text mode, read it, and close the file"""
        conn = self._get_connection()
        data = conn.read_file(self.remote_path)
        return data.decode(encoding or 'utf-8', errors or 'strict')
    
    def read_bytes(self) -> bytes:
        """Open the file in bytes mode, read it, and close the file"""
        conn = self._get_connection()
        return conn.read_file(self.remote_path)
    
    def read_bytes_with_progress(self, progress_callback: callable) -> bytes:
        """
        Open the file in bytes mode, read it, and close the file with progress tracking.
        
        Args:
            progress_callback: Callable that takes (bytes_transferred: int, total_bytes: int)
        
        Returns:
            File contents as bytes
        """
        conn = self._get_connection()
        conn.set_progress_callback(progress_callback)
        try:
            return conn.read_file(self.remote_path)
        finally:
            conn.set_progress_callback(None)
    
    def write_text(self, data: str, encoding=None, errors=None, newline=None) -> int:
        """Open the file in text mode, write to it, and close the file"""
        conn = self._get_connection()
        bytes_data = data.encode(encoding or 'utf-8', errors or 'strict')
        conn.write_file(self.remote_path, bytes_data)
        return len(bytes_data)
    
    def write_bytes(self, data: bytes) -> int:
        """Open the file in bytes mode, write to it, and close the file"""
        conn = self._get_connection()
        conn.write_file(self.remote_path, data)
        return len(data)
    
    def write_bytes_with_progress(self, data: bytes, progress_callback: callable) -> int:
        """
        Open the file in bytes mode, write to it, and close the file with progress tracking.
        
        Args:
            data: File contents as bytes
            progress_callback: Callable that takes (bytes_transferred: int, total_bytes: int)
        
        Returns:
            Number of bytes written
        """
        conn = self._get_connection()
        conn.set_progress_callback(progress_callback)
        try:
            conn.write_file(self.remote_path, data)
            return len(data)
        finally:
            conn.set_progress_callback(None)
    
    # File system modification operations
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """Create a new directory at this given path"""
        conn = self._get_connection()
        
        if parents:
            # Create parent directories as needed
            parent = self.parent
            if not parent.exists():
                parent.mkdir(mode=mode, parents=True, exist_ok=True)
        
        try:
            conn.create_directory(self.remote_path)
        except Exception as e:
            if exist_ok and self.exists():
                return
            raise
    
    def rmdir(self):
        """Remove this directory"""
        conn = self._get_connection()
        conn.delete_directory(self.remote_path)
    
    def unlink(self, missing_ok=False):
        """Remove this file or symbolic link"""
        conn = self._get_connection()
        try:
            conn.delete_file(self.remote_path)
        except Exception as e:
            if missing_ok and not self.exists():
                return
            raise
    
    def rename(self, target):
        """Rename this file or directory to the given target"""
        target_str = str(target)
        
        # Check if target is also SSH path on same host
        if target_str.startswith(f'ssh://{self.hostname}/'):
            # Same host - use native rename
            target_path = target_str[len(f'ssh://{self.hostname}'):]
            conn = self._get_connection()
            conn.rename(self.remote_path, target_path)
            return self._make_path(target_str)
        else:
            # Cross-storage rename not supported via this method
            raise ValueError("Cross-storage rename not supported via rename()")
    
    def replace(self, target):
        """Replace this file or directory with the given target"""
        # For SSH, replace is the same as rename
        return self.rename(target)
    
    def symlink_to(self, target, target_is_directory=False):
        """Make this path a symlink pointing to the target path"""
        raise NotImplementedError("Symlink creation not supported for SSH paths")
    
    def hardlink_to(self, target):
        """Make this path a hard link pointing to the same file as target"""
        raise NotImplementedError("Hard link creation not supported for SSH paths")
    
    def touch(self, mode=0o666, exist_ok=True):
        """Create this file with the given access mode, if it doesn't exist"""
        if self.exists():
            if not exist_ok:
                raise FileExistsError(f"File exists: {self}")
            return
        
        # Create empty file
        self.write_bytes(b'')
    
    def chmod(self, mode):
        """Change the permissions of the path"""
        # SFTP doesn't provide a direct chmod command
        # Would need to use SSH command execution
        raise NotImplementedError("chmod not supported for SSH paths via SFTP")
    
    # Storage-specific methods
    def is_remote(self) -> bool:
        """Return True if this path represents a remote resource"""
        return True
    
    def get_scheme(self) -> str:
        """Return the scheme of the path (e.g., 'file', 's3', 'ssh')"""
        return 'ssh'
    
    def as_uri(self) -> str:
        """Return the path as a URI"""
        return self._uri
    
    def supports_directory_rename(self) -> bool:
        """Return True if this storage implementation supports directory renaming"""
        return True
    
    def supports_file_editing(self) -> bool:
        """Return True if this storage implementation supports external editor editing"""
        return False  # No external editor support for remote files
    
    def supports_write_operations(self) -> bool:
        """Return True if this storage implementation supports write operations"""
        return True
    
    # Display methods for UI presentation
    def get_display_prefix(self) -> str:
        """Return a prefix for display purposes in UI components"""
        return "SSH: "
    
    def get_display_title(self) -> str:
        """Return a formatted title for display in viewers and dialogs"""
        return self._uri
    
    # Content reading strategy methods
    def requires_extraction_for_reading(self) -> bool:
        """Return True if content must be extracted before reading"""
        return True  # SSH files must be downloaded before reading
    
    def supports_streaming_read(self) -> bool:
        """Return True if file can be read line-by-line without full extraction"""
        return False  # Must download entire file first
    
    def get_search_strategy(self) -> str:
        """Return recommended search strategy for this storage type"""
        return 'buffered'  # Download to buffer then search
    
    def should_cache_for_search(self) -> bool:
        """Return True if content should be cached during search operations"""
        return True  # Download is expensive, caching recommended
    
    # Metadata method for info dialogs
    def get_extended_metadata(self) -> dict:
        """Return storage-specific metadata for display in info dialogs"""
        try:
            stat_info = self.stat()
            
            # Determine file type
            if self.is_dir():
                file_type = 'Directory'
            elif self.is_symlink():
                file_type = 'Symbolic Link'
            else:
                file_type = 'File'
            
            # Get user@host display
            user = self.config.get('User', '')
            actual_host = self.config.get('HostName', self.hostname)
            if user:
                host_display = f"{user}@{actual_host}"
            else:
                host_display = actual_host
            
            # Build details list
            details = [
                ('Host', host_display),
                ('Remote Path', self.remote_path),
                ('Type', file_type),
                ('Size', format_size(stat_info.st_size)),
                ('Modified', self._format_time(stat_info.st_mtime))
            ]
            
            return {
                'type': 'ssh',
                'details': details,
                'format_hint': 'remote'
            }
        except Exception as e:
            # If we can't get metadata, return minimal info
            return {
                'type': 'ssh',
                'details': [
                    ('URI', self._uri),
                    ('Error', f'Unable to retrieve metadata: {e}')
                ],
                'format_hint': 'remote'
            }
    
    
    def _format_time(self, timestamp: float) -> str:
        """Format timestamp as readable date/time"""
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Compatibility methods
    def samefile(self, other_path) -> bool:
        """Return whether other_path is the same or not as this file"""
        return str(self) == str(other_path)
    
    def as_posix(self) -> str:
        """Return the string representation with forward slashes"""
        return self._uri
