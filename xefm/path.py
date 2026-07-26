#!/usr/bin/env python3
"""
XeFM Path - A pathlib-compatible Path class that can be extended for remote storage support
"""

import os
import stat
import fnmatch
import io
import errno
from abc import ABC, abstractmethod
from pathlib import Path as PathlibPath, PurePath
from datetime import datetime
from typing import Union, Iterator, List, Optional, Any
from xefm import dir_scan
from xefm.str_format import format_size




def attrs_via_path(entry) -> dict:
    """Build one :mod:`xefm.dir_scan` attribute record by asking a ``Path``
    itself — the per-file route, for backends with no bulk listing form.

    ``is_symlink`` is captured first because it stays meaningful for a broken
    symlink, whose ``stat`` below fails.
    """
    try:
        is_link = entry.is_symlink()
    except Exception:
        is_link = False
    try:
        stat_info = entry.stat()
        is_dir = entry.is_dir()
    except Exception:
        return dict(dir_scan.BROKEN_ATTRS, is_link=is_link)
    return {'is_dir': is_dir, 'is_link': is_link,
            'size': 0 if is_dir else stat_info.st_size,
            'mtime': stat_info.st_mtime, 'ok': True}


class PathImpl(ABC):
    """
    Abstract base class for path implementations.

    This defines the interface that all storage implementations must provide.
    Subclasses implement specific storage backends (local, S3, SCP, etc.).
    """
    
    @abstractmethod
    def __str__(self) -> str:
        """String representation of the path"""
        pass
    
    @abstractmethod
    def __eq__(self, other) -> bool:
        """Equality comparison"""
        pass
    
    @abstractmethod
    def __hash__(self) -> int:
        """Hash support for use in sets and dicts"""
        pass
    
    @abstractmethod
    def __lt__(self, other) -> bool:
        """Less than comparison for sorting"""
        pass
    
    # Properties
    @property
    @abstractmethod
    def name(self) -> str:
        """The final component of the path"""
        pass
    
    @property
    @abstractmethod
    def stem(self) -> str:
        """The final component without its suffix"""
        pass
    
    @property
    @abstractmethod
    def suffix(self) -> str:
        """The file extension of the final component"""
        pass
    
    @property
    @abstractmethod
    def suffixes(self) -> List[str]:
        """A list of the path's suffixes"""
        pass
    
    @property
    @abstractmethod
    def parent(self) -> 'Path':
        """The logical parent of the path"""
        pass
    
    @property
    @abstractmethod
    def parents(self):
        """A sequence providing access to the logical ancestors of the path"""
        pass
    
    @property
    @abstractmethod
    def parts(self) -> tuple:
        """A tuple giving access to the path's components"""
        pass
    
    @property
    @abstractmethod
    def anchor(self) -> str:
        """The concatenation of the drive and root"""
        pass
    
    # Path manipulation methods
    @abstractmethod
    def absolute(self) -> 'Path':
        """Return an absolute version of this path"""
        pass
    
    @abstractmethod
    def resolve(self, strict: bool = False) -> 'Path':
        """Make the path absolute, resolving any symlinks"""
        pass
    
    @abstractmethod
    def expanduser(self) -> 'Path':
        """Return a new path with expanded ~ and ~user constructs"""
        pass
    
    @abstractmethod
    def joinpath(self, *args) -> 'Path':
        """Combine this path with one or several arguments"""
        pass
    
    @abstractmethod
    def with_name(self, name: str) -> 'Path':
        """Return a new path with the name changed"""
        pass
    
    @abstractmethod
    def with_stem(self, stem: str) -> 'Path':
        """Return a new path with the stem changed"""
        pass
    
    @abstractmethod
    def with_suffix(self, suffix: str) -> 'Path':
        """Return a new path with the suffix changed"""
        pass
    
    @abstractmethod
    def relative_to(self, other) -> 'Path':
        """Return a version of this path relative to the other path"""
        pass
    
    # File system query methods
    @abstractmethod
    def exists(self) -> bool:
        """Whether this path exists"""
        pass
    
    @abstractmethod
    def is_dir(self) -> bool:
        """Whether this path is a directory"""
        pass
    
    @abstractmethod
    def is_file(self) -> bool:
        """Whether this path is a regular file"""
        pass
    
    @abstractmethod
    def is_symlink(self) -> bool:
        """Whether this path is a symbolic link"""
        pass
    
    @abstractmethod
    def is_absolute(self) -> bool:
        """Whether this path is absolute"""
        pass
    
    @abstractmethod
    def stat(self):
        """Return the result of os.stat() on this path"""
        pass
    
    @abstractmethod
    def lstat(self):
        """Return the result of os.lstat() on this path"""
        pass
    
    # Directory operations
    @abstractmethod
    def iterdir(self) -> Iterator['Path']:
        """Iterate over the files in this directory"""
        pass

    def listdir_attrs(self) -> List[tuple]:
        """Return ``[(Path, attrs), …]`` for this directory's entries, where
        ``attrs`` is the record described in :mod:`xefm.dir_scan`
        (``is_dir``/``is_link``/``size``/``mtime``/``ok``).

        This is ``iterdir`` plus everything a listing needs to know about each
        entry, in one call — so a backend that can answer for the whole
        directory at once (a bulk syscall, a single list request) does, instead
        of being interrogated per file. A pane listing goes through here rather
        than through ``iterdir`` + per-entry ``stat``.

        The default implementation *is* ``iterdir`` + per-entry ``stat``, so a
        backend that has no bulk form keeps working unchanged; override it where
        the underlying protocol already returns metadata alongside names.
        """
        return [(child, attrs_via_path(child)) for child in self.iterdir()]


    @abstractmethod
    def glob(self, pattern: str) -> Iterator['Path']:
        """Iterate over this subtree and yield all existing files matching pattern"""
        pass
    
    @abstractmethod
    def rglob(self, pattern: str) -> Iterator['Path']:
        """Recursively iterate over this subtree and yield all existing files matching pattern"""
        pass
    
    @abstractmethod
    def match(self, pattern: str) -> bool:
        """Return True if this path matches the given pattern"""
        pass
    
    # File I/O operations
    @abstractmethod
    def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        """Open the file pointed to by this path"""
        pass
    
    @abstractmethod
    def read_text(self, encoding=None, errors=None) -> str:
        """Open the file in text mode, read it, and close the file"""
        pass
    
    @abstractmethod
    def read_bytes(self) -> bytes:
        """Open the file in bytes mode, read it, and close the file"""
        pass
    
    @abstractmethod
    def write_text(self, data: str, encoding=None, errors=None, newline=None) -> int:
        """Open the file in text mode, write to it, and close the file"""
        pass
    
    @abstractmethod
    def write_bytes(self, data: bytes) -> int:
        """Open the file in bytes mode, write to it, and close the file"""
        pass
    
    # File system modification operations
    @abstractmethod
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """Create a new directory at this given path"""
        pass
    
    @abstractmethod
    def rmdir(self):
        """Remove this directory"""
        pass
    
    @abstractmethod
    def unlink(self, missing_ok=False):
        """Remove this file or symbolic link"""
        pass
    
    @abstractmethod
    def rename(self, target) -> 'Path':
        """Rename this file or directory to the given target"""
        pass
    
    @abstractmethod
    def replace(self, target) -> 'Path':
        """Replace this file or directory with the given target"""
        pass
    
    @abstractmethod
    def symlink_to(self, target, target_is_directory=False):
        """Make this path a symlink pointing to the target path"""
        pass
    
    @abstractmethod
    def hardlink_to(self, target):
        """Make this path a hard link pointing to the same file as target"""
        pass
    
    @abstractmethod
    def touch(self, mode=0o666, exist_ok=True):
        """Create this file with the given access mode, if it doesn't exist"""
        pass
    
    @abstractmethod
    def chmod(self, mode):
        """Change the permissions of the path"""
        pass
    
    # Storage-specific methods
    @abstractmethod
    def is_remote(self) -> bool:
        """Return True if this path represents a remote resource"""
        pass
    
    @abstractmethod
    def get_scheme(self) -> str:
        """Return the scheme of the path (e.g., 'file', 's3', 'scp')"""
        pass
    
    @abstractmethod
    def as_uri(self) -> str:
        """Return the path as a URI"""
        pass
    
    @abstractmethod
    def supports_directory_rename(self) -> bool:
        """Return True if this storage implementation supports directory renaming"""
        pass
    
    @abstractmethod
    def supports_file_editing(self) -> bool:
        """Return True if this storage implementation supports external editor editing (vim, nano, etc.)"""
        pass
    
    @abstractmethod
    def supports_write_operations(self) -> bool:
        """Return True if this storage implementation supports write operations (copy, move, create, delete)"""
        pass
    
    # Display methods for UI presentation
    @abstractmethod
    def get_display_prefix(self) -> str:
        """Return a prefix for display purposes in UI components.
        
        This method provides a storage-type indicator that UI components can
        prepend to path displays to help users identify the storage type.
        
        Returns:
            str: Display prefix with trailing space for special storage types,
                 or empty string for local files.
                 
        Examples:
            - Local files: '' (empty string)
            - Archive entries: 'ARCHIVE: '
            - S3 objects: 'S3: '
            - Remote paths: 'REMOTE: '
        
        Note:
            If non-empty, the prefix should include a trailing space for
            proper formatting when concatenated with the title.
        """
        pass
    
    @abstractmethod
    def get_display_title(self) -> str:
        """Return a formatted title for display in viewers and dialogs.
        
        This method provides a human-readable representation of the path
        appropriate for display in UI components like text viewers, info
        dialogs, and title bars.
        
        Returns:
            str: Formatted path string appropriate for display.
            
        Examples:
            - Local files: '/home/user/document.txt'
            - Archive entries: 'archive:///path/to/file.zip#internal/path.txt'
            - S3 objects: 's3://bucket-name/key/path'
        
        Note:
            The title should be complete and unambiguous, allowing users
            to identify the exact resource being displayed.
        """
        pass
    
    # Content reading strategy methods
    @abstractmethod
    def requires_extraction_for_reading(self) -> bool:
        """Return True if content must be extracted before reading.
        
        This method indicates whether the storage implementation requires
        content to be extracted or downloaded to memory/disk before it can
        be read. This affects how operations like search and viewing are
        implemented.
        
        Returns:
            bool: True if extraction/download required (archives, S3, remote),
                  False if direct access possible (local files).
                  
        Examples:
            - Local files: False (can open() and read directly)
            - Archive entries: True (must extract from archive first)
            - S3 objects: True (must download from S3 first)
        
        Note:
            This is used to determine the appropriate reading strategy and
            whether caching might be beneficial.
        """
        pass
    
    @abstractmethod
    def supports_streaming_read(self) -> bool:
        """Return True if file can be read line-by-line without full extraction.
        
        This method indicates whether the storage implementation supports
        efficient streaming reads (line-by-line iteration) or requires
        reading the entire content into memory first.
        
        Returns:
            bool: True if can use open() and iterate line-by-line (local files),
                  False if must read_text() entire content (archives, S3).
                  
        Examples:
            - Local files: True (can iterate with for line in file)
            - Archive entries: False (must extract full content)
            - S3 objects: False (must download full object)
        
        Note:
            This affects memory usage during operations like search. Streaming
            reads are more memory-efficient for large files.
        """
        pass
    
    @abstractmethod
    def get_search_strategy(self) -> str:
        """Return recommended search strategy for this storage type.
        
        This method provides a hint about the most efficient way to search
        content in this storage type. UI components use this to optimize
        search operations.
        
        Returns:
            str: One of the following strategy identifiers:
                 - 'streaming': Read and search line-by-line (local files)
                 - 'extracted': Extract entire content then search (archives)
                 - 'buffered': Download to buffer then search (S3, remote)
                 
        Examples:
            - Local files: 'streaming' (memory-efficient line-by-line)
            - Archive entries: 'extracted' (must extract full content)
            - S3 objects: 'buffered' (download then search)
        
        Note:
            The strategy hint helps UI code choose between different search
            implementations without knowing the specific storage type.
        """
        pass
    
    @abstractmethod
    def should_cache_for_search(self) -> bool:
        """Return True if content should be cached during search operations.
        
        This method indicates whether caching extracted/downloaded content
        is recommended for this storage type. Caching improves performance
        for repeated searches but uses more memory.
        
        Returns:
            bool: True if caching recommended (archives, S3, remote),
                  False if direct access is efficient (local files).
                  
        Examples:
            - Local files: False (direct access is fast)
            - Archive entries: True (extraction is expensive)
            - S3 objects: True (download is expensive)
        
        Note:
            This is a recommendation; the actual caching decision may depend
            on available memory and other factors.
        """
        pass
    
    # Metadata method for info dialogs
    @abstractmethod
    def get_extended_metadata(self) -> dict:
        """Return storage-specific metadata for display in info dialogs.
        
        This method provides detailed metadata appropriate for the storage
        type. The metadata is returned in a structured format that info
        dialogs can display without knowing the specific storage type.
        
        Returns:
            dict: Metadata dictionary with the following structure:
                {
                    'type': str,              # Storage type identifier
                    'details': List[Tuple[str, str]],  # List of (label, value) pairs
                    'format_hint': str        # Display format hint
                }
                
        Storage type identifiers:
            - 'local': Local file system
            - 'archive': Archive entry
            - 's3': S3 object
            - 'remote': Other remote storage
            
        Format hints:
            - 'standard': Standard file metadata display
            - 'archive': Archive-specific display format
            - 'remote': Remote storage display format
            
        Examples:
            Local file:
                {
                    'type': 'local',
                    'details': [
                        ('Type', 'File'),
                        ('Size', '1.2 MB'),
                        ('Permissions', 'rw-r--r--'),
                        ('Modified', '2024-01-15 10:30:00')
                    ],
                    'format_hint': 'standard'
                }
                
            Archive entry:
                {
                    'type': 'archive',
                    'details': [
                        ('Archive', 'data.zip'),
                        ('Internal Path', 'folder/file.txt'),
                        ('Type', 'File'),
                        ('Compressed Size', '512 KB'),
                        ('Uncompressed Size', '1.2 MB'),
                        ('Compression', 'Deflated'),
                        ('Modified', '2024-01-15 10:30:00')
                    ],
                    'format_hint': 'archive'
                }
                
            S3 object:
                {
                    'type': 's3',
                    'details': [
                        ('Bucket', 'my-bucket'),
                        ('Key', 'path/to/object.txt'),
                        ('Type', 'Object'),
                        ('Size', '1.2 MB'),
                        ('Storage Class', 'STANDARD'),
                        ('Last Modified', '2024-01-15 10:30:00')
                    ],
                    'format_hint': 'remote'
                }
        
        Note:
            The 'details' list should contain all relevant metadata for the
            storage type. Common fields like 'Type' and 'Size' should be
            included when applicable. The order of fields in the list
            determines the display order in info dialogs.
        """
        pass
    
    # Compatibility methods
    @abstractmethod
    def samefile(self, other_path) -> bool:
        """Return whether other_path is the same or not as this file"""
        pass
    
    @abstractmethod
    def as_posix(self) -> str:
        """Return the string representation with forward slashes"""
        pass


class LocalPathImpl(PathImpl):
    """
    Local file system implementation of PathImpl.
    
    This class wraps pathlib.Path to provide local file system operations
    while implementing the PathImpl interface.
    """
    
    def __init__(self, path_obj: PathlibPath):
        """Initialize with a pathlib.Path object"""
        self._path = path_obj
    
    def __str__(self) -> str:
        """String representation of the path"""
        return str(self._path)
    
    def __eq__(self, other) -> bool:
        """Equality comparison"""
        if isinstance(other, LocalPathImpl):
            return self._path == other._path
        elif isinstance(other, PathlibPath):
            return self._path == other
        elif isinstance(other, str):
            return str(self._path) == other
        return False
    
    def __hash__(self) -> int:
        """Hash support for use in sets and dicts"""
        return hash(self._path)
    
    def __lt__(self, other) -> bool:
        """Less than comparison for sorting"""
        if isinstance(other, LocalPathImpl):
            return str(self._path) < str(other._path)
        return str(self._path) < str(other)
    
    # Properties
    @property
    def name(self) -> str:
        """The final component of the path"""
        return self._path.name
    
    @property
    def stem(self) -> str:
        """The final component without its suffix"""
        return self._path.stem
    
    @property
    def suffix(self) -> str:
        """The file extension of the final component"""
        return self._path.suffix
    
    @property
    def suffixes(self) -> List[str]:
        """A list of the path's suffixes"""
        return self._path.suffixes
    
    @property
    def parent(self) -> 'Path':
        """The logical parent of the path"""
        return Path(self._path.parent)
    
    @property
    def parents(self):
        """A sequence providing access to the logical ancestors of the path"""
        return [Path(p) for p in self._path.parents]
    
    @property
    def parts(self) -> tuple:
        """A tuple giving access to the path's components"""
        return self._path.parts
    
    @property
    def anchor(self) -> str:
        """The concatenation of the drive and root"""
        return self._path.anchor
    
    # Path manipulation methods
    def absolute(self) -> 'Path':
        """Return an absolute version of this path"""
        return Path(self._path.absolute())
    
    def resolve(self, strict: bool = False) -> 'Path':
        """Make the path absolute, resolving any symlinks"""
        return Path(self._path.resolve(strict=strict))
    
    def expanduser(self) -> 'Path':
        """Return a new path with expanded ~ and ~user constructs"""
        return Path(self._path.expanduser())
    
    def joinpath(self, *args) -> 'Path':
        """Combine this path with one or several arguments"""
        return Path(self._path.joinpath(*args))
    
    def with_name(self, name: str) -> 'Path':
        """Return a new path with the name changed"""
        return Path(self._path.with_name(name))
    
    def with_stem(self, stem: str) -> 'Path':
        """Return a new path with the stem changed"""
        return Path(self._path.with_stem(stem))
    
    def with_suffix(self, suffix: str) -> 'Path':
        """Return a new path with the suffix changed"""
        return Path(self._path.with_suffix(suffix))
    
    def relative_to(self, other) -> 'Path':
        """Return a version of this path relative to the other path"""
        if isinstance(other, Path):
            other = other._impl._path
        elif isinstance(other, LocalPathImpl):
            other = other._path
        return Path(self._path.relative_to(other))
    
    # File system query methods
    def exists(self) -> bool:
        """Whether this path exists"""
        return self._path.exists()
    
    def is_dir(self) -> bool:
        """Whether this path is a directory"""
        return self._path.is_dir()
    
    def is_file(self) -> bool:
        """Whether this path is a regular file"""
        return self._path.is_file()
    
    def is_symlink(self) -> bool:
        """Whether this path is a symbolic link"""
        return self._path.is_symlink()
    
    def is_absolute(self) -> bool:
        """Whether this path is absolute"""
        return self._path.is_absolute()
    
    def stat(self):
        """Return the result of os.stat() on this path"""
        return self._path.stat()
    
    def lstat(self):
        """Return the result of os.lstat() on this path"""
        return self._path.lstat()
    
    # Directory operations
    def iterdir(self) -> Iterator['Path']:
        """Iterate over the files in this directory"""
        for item in self._path.iterdir():
            yield Path(item)

    def listdir_attrs(self) -> List[tuple]:
        """Read the directory and every entry's attributes in one pass — see
        :func:`xefm.dir_scan.scan_dir`, which uses the platform's bulk
        enumeration where one exists. This is what keeps a large directory on a
        network mount from costing one round trip per file."""
        base = self._path
        return [(Path(base / name), attrs)
                for name, attrs in dir_scan.scan_dir(str(base))]


    def glob(self, pattern: str) -> Iterator['Path']:
        """Iterate over this subtree and yield all existing files matching pattern"""
        for item in self._path.glob(pattern):
            yield Path(item)
    
    def rglob(self, pattern: str) -> Iterator['Path']:
        """Recursively iterate over this subtree and yield all existing files matching pattern"""
        for item in self._path.rglob(pattern):
            yield Path(item)
    
    def match(self, pattern: str) -> bool:
        """Return True if this path matches the given pattern"""
        return self._path.match(pattern)
    
    # File I/O operations
    def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        """Open the file pointed to by this path"""
        return self._path.open(mode, buffering, encoding, errors, newline)
    
    def read_text(self, encoding=None, errors=None) -> str:
        """Open the file in text mode, read it, and close the file"""
        return self._path.read_text(encoding, errors)
    
    def read_bytes(self) -> bytes:
        """Open the file in bytes mode, read it, and close the file"""
        return self._path.read_bytes()
    
    def write_text(self, data: str, encoding=None, errors=None, newline=None) -> int:
        """Open the file in text mode, write to it, and close the file"""
        return self._path.write_text(data, encoding, errors)
    
    def write_bytes(self, data: bytes) -> int:
        """Open the file in bytes mode, write to it, and close the file"""
        return self._path.write_bytes(data)
    
    # File system modification operations
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """Create a new directory at this given path"""
        return self._path.mkdir(mode, parents, exist_ok)
    
    def rmdir(self):
        """Remove this directory"""
        return self._path.rmdir()
    
    def unlink(self, missing_ok=False):
        """Remove this file or symbolic link"""
        return self._path.unlink(missing_ok)
    
    def rename(self, target) -> 'Path':
        """Rename this file or directory to the given target"""
        if isinstance(target, Path):
            target = target._impl._path
        elif isinstance(target, LocalPathImpl):
            target = target._path
        return Path(self._path.rename(target))
    
    def replace(self, target) -> 'Path':
        """Replace this file or directory with the given target"""
        if isinstance(target, Path):
            target = target._impl._path
        elif isinstance(target, LocalPathImpl):
            target = target._path
        return Path(self._path.replace(target))
    
    def symlink_to(self, target, target_is_directory=False):
        """Make this path a symlink pointing to the target path"""
        if isinstance(target, Path):
            target = target._impl._path
        elif isinstance(target, LocalPathImpl):
            target = target._path
        return self._path.symlink_to(target, target_is_directory)
    
    def hardlink_to(self, target):
        """Make this path a hard link pointing to the same file as target"""
        if isinstance(target, Path):
            target = target._impl._path
        elif isinstance(target, LocalPathImpl):
            target = target._path
        return self._path.hardlink_to(target)
    
    def touch(self, mode=0o666, exist_ok=True):
        """Create this file with the given access mode, if it doesn't exist"""
        return self._path.touch(mode, exist_ok)
    
    def chmod(self, mode):
        """Change the permissions of the path"""
        return self._path.chmod(mode)
    
    # Storage-specific methods
    def is_remote(self) -> bool:
        """Return True if this path represents a remote resource"""
        return False
    
    def get_scheme(self) -> str:
        """Return the scheme of the path (e.g., 'file', 's3', 'scp')"""
        return 'file'
    
    def as_uri(self) -> str:
        """Return the path as a URI"""
        return self._path.as_uri()
    
    # Compatibility methods
    def samefile(self, other_path) -> bool:
        """Return whether other_path is the same or not as this file"""
        if isinstance(other_path, Path):
            other_path = other_path._impl._path
        elif isinstance(other_path, LocalPathImpl):
            other_path = other_path._path
        return self._path.samefile(other_path)
    
    def as_posix(self) -> str:
        """Return the string representation with forward slashes"""
        return self._path.as_posix()
    
    def supports_directory_rename(self) -> bool:
        """Return True if this storage implementation supports directory renaming"""
        return True  # Local file system supports directory renaming
    
    def supports_file_editing(self) -> bool:
        """Return True if this storage implementation supports external editor editing (vim, nano, etc.)"""
        return True  # Local file system supports file editing
    
    def supports_write_operations(self) -> bool:
        """Return True if this storage implementation supports write operations (copy, move, create, delete)"""
        return True  # Local file system supports all write operations
    
    # Display methods for UI presentation
    def get_display_prefix(self) -> str:
        """Return a prefix for display purposes.
        
        For local files, no prefix is needed as they are the default/standard
        storage type.
        
        Returns:
            str: Empty string (no prefix for local files)
        """
        return ''
    
    def get_display_title(self) -> str:
        """Return a formatted title for display in viewers and dialogs.
        
        For local files, the standard path string representation is appropriate.
        
        Returns:
            str: String representation of the path
        """
        return str(self._path)
    
    # Content reading strategy methods
    def requires_extraction_for_reading(self) -> bool:
        """Return True if content must be extracted before reading.
        
        Local files can be read directly without extraction.
        
        Returns:
            bool: False (local files support direct access)
        """
        return False
    
    def supports_streaming_read(self) -> bool:
        """Return True if file can be read line-by-line without full extraction.
        
        Local files support efficient streaming reads using open() and iteration.
        
        Returns:
            bool: True (local files support streaming)
        """
        return True
    
    def get_search_strategy(self) -> str:
        """Return recommended search strategy for this storage type.
        
        Local files are best searched using streaming (line-by-line) approach
        for memory efficiency.
        
        Returns:
            str: 'streaming' (memory-efficient line-by-line search)
        """
        return 'streaming'
    
    def should_cache_for_search(self) -> bool:
        """Return True if content should be cached during search operations.
        
        Local files don't need caching as direct access is already efficient.
        
        Returns:
            bool: False (direct access is efficient, no caching needed)
        """
        return False
    
    # Metadata method for info dialogs
    def get_extended_metadata(self) -> dict:
        """Return storage-specific metadata for display in info dialogs.
        
        For local files, provides standard file system metadata including
        type, size, permissions, and modification time.
        
        Returns:
            dict: Metadata dictionary with structure:
                {
                    'type': 'local',
                    'details': [(label, value), ...],
                    'format_hint': 'standard'
                }
        """
        try:
            stat_info = self._path.stat()
            
            # Determine file type
            if self.is_dir():
                file_type = 'Directory'
            elif self.is_symlink():
                file_type = 'Symbolic Link'
            else:
                file_type = 'File'
            
            # Build details list
            details = [
                ('Type', file_type),
                ('Size', format_size(stat_info.st_size)),
                ('Permissions', self._format_permissions(stat_info.st_mode)),
                ('Modified', self._format_time(stat_info.st_mtime))
            ]
            
            return {
                'type': 'local',
                'details': details,
                'format_hint': 'standard'
            }
        except Exception as e:
            # If we can't get metadata, return minimal info
            return {
                'type': 'local',
                'details': [
                    ('Path', str(self._path)),
                    ('Error', f'Unable to retrieve metadata: {e}')
                ],
                'format_hint': 'standard'
            }
    
    
    def _format_permissions(self, mode: int) -> str:
        """Format permissions as rwxrwxrwx string.
        
        Args:
            mode: File mode from stat
            
        Returns:
            str: Permission string (e.g., 'rwxr-xr-x')
        """
        perms = []
        # Owner permissions
        perms.append('r' if mode & stat.S_IRUSR else '-')
        perms.append('w' if mode & stat.S_IWUSR else '-')
        perms.append('x' if mode & stat.S_IXUSR else '-')
        # Group permissions
        perms.append('r' if mode & stat.S_IRGRP else '-')
        perms.append('w' if mode & stat.S_IWGRP else '-')
        perms.append('x' if mode & stat.S_IXGRP else '-')
        # Other permissions
        perms.append('r' if mode & stat.S_IROTH else '-')
        perms.append('w' if mode & stat.S_IWOTH else '-')
        perms.append('x' if mode & stat.S_IXOTH else '-')
        return ''.join(perms)
    
    def _format_time(self, timestamp: float) -> str:
        """Format timestamp as readable date/time.
        
        Args:
            timestamp: Unix timestamp
            
        Returns:
            str: Formatted date/time string (e.g., '2024-01-15 10:30:00')
        """
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')


class Path:
    """
    A pathlib-compatible Path class designed to support both local and remote storage.
    
    This class acts as a facade that delegates operations to specific storage
    implementations (LocalPathImpl, S3PathImpl, etc.) based on the path scheme.
    """
    
    def __init__(self, *args):
        """Initialize Path with the same interface as pathlib.Path"""
        # Determine the appropriate implementation based on the path
        if len(args) == 1 and isinstance(args[0], Path):
            # Copy constructor
            self._impl = args[0]._impl
        elif len(args) == 1 and isinstance(args[0], PathlibPath):
            # Wrap existing pathlib.Path
            self._impl = LocalPathImpl(args[0])
        else:
            # Create new path from string arguments
            # Check for remote schemes first before using PathlibPath
            if len(args) == 1 and isinstance(args[0], str) and args[0].startswith(('archive://', 's3://', 'ssh://', 'scp://', 'ftp://')):
                path_str = args[0]
            else:
                path_str = str(PathlibPath(*args))
            self._impl = self._create_implementation(path_str)
    
    def _create_implementation(self, path_str: str) -> PathImpl:
        """Create the appropriate implementation based on the path string"""
        # Detect archive URIs
        if path_str.startswith('archive://'):
            try:
                # Try relative import first, then absolute
                try:
                    from .xefm.archive import ArchivePathImpl
                except ImportError:
                    from xefm.archive import ArchivePathImpl
                return ArchivePathImpl(path_str)
            except ImportError as e:
                raise ImportError(f"Archive support not available: {e}")
        
        # Detect S3 URIs
        if path_str.startswith('s3://'):
            try:
                # Try relative import first, then absolute
                try:
                    from .xefm.s3 import S3PathImpl
                except ImportError:
                    from xefm.s3 import S3PathImpl
                return S3PathImpl(path_str)
            except ImportError as e:
                raise ImportError(f"S3 support not available: {e}")
        
        # Detect SSH URIs
        if path_str.startswith('ssh://'):
            try:
                # Try relative import first, then absolute
                try:
                    from .xefm.ssh import SSHPathImpl
                except ImportError:
                    from xefm.ssh import SSHPathImpl
                return SSHPathImpl(path_str)
            except ImportError as e:
                raise ImportError(f"SSH support not available: {e}")
        
        # Default to local file system
        return LocalPathImpl(PathlibPath(path_str))
    
    def __str__(self):
        """String representation of the path"""
        return str(self._impl)
    
    def __repr__(self):
        """Representation of the path"""
        return f"Path({str(self._impl)!r})"
    
    def __fspath__(self):
        """Support for os.fspath()"""
        return str(self._impl)
    
    def __truediv__(self, other):
        """Support for / operator"""
        return self._impl.joinpath(other)
    
    def __rtruediv__(self, other):
        """Support for reverse / operator"""
        return Path(other) / self
    
    def __eq__(self, other):
        """Equality comparison"""
        if isinstance(other, Path):
            return self._impl == other._impl
        else:
            return self._impl == other
    
    def __hash__(self):
        """Hash support for use in sets and dicts"""
        return hash(self._impl)
    
    def __lt__(self, other):
        """Less than comparison for sorting"""
        if isinstance(other, Path):
            return self._impl < other._impl
        return self._impl < other
    
    # Properties that delegate to implementation
    @property
    def name(self) -> str:
        """The final component of the path"""
        return self._impl.name
    
    @property
    def stem(self) -> str:
        """The final component without its suffix"""
        return self._impl.stem
    
    @property
    def suffix(self) -> str:
        """The file extension of the final component"""
        return self._impl.suffix
    
    @property
    def suffixes(self) -> List[str]:
        """A list of the path's suffixes"""
        return self._impl.suffixes
    
    @property
    def parent(self) -> 'Path':
        """The logical parent of the path"""
        return self._impl.parent
    
    @property
    def parents(self):
        """A sequence providing access to the logical ancestors of the path"""
        return self._impl.parents
    
    @property
    def parts(self) -> tuple:
        """A tuple giving access to the path's components"""
        return self._impl.parts
    
    @property
    def anchor(self) -> str:
        """The concatenation of the drive and root"""
        return self._impl.anchor
    
    # Methods that delegate to implementation
    def absolute(self) -> 'Path':
        """Return an absolute version of this path"""
        return self._impl.absolute()
    
    def resolve(self, strict: bool = False) -> 'Path':
        """Make the path absolute, resolving any symlinks"""
        return self._impl.resolve(strict=strict)
    
    def expanduser(self) -> 'Path':
        """Return a new path with expanded ~ and ~user constructs"""
        return self._impl.expanduser()
    
    def exists(self) -> bool:
        """Whether this path exists"""
        return self._impl.exists()
    
    def is_dir(self) -> bool:
        """Whether this path is a directory"""
        return self._impl.is_dir()
    
    def is_file(self) -> bool:
        """Whether this path is a regular file"""
        return self._impl.is_file()
    
    def is_symlink(self) -> bool:
        """Whether this path is a symbolic link"""
        return self._impl.is_symlink()
    
    def is_absolute(self) -> bool:
        """Whether this path is absolute"""
        return self._impl.is_absolute()
    
    def stat(self):
        """Return the result of os.stat() on this path"""
        return self._impl.stat()
    
    def lstat(self):
        """Return the result of os.lstat() on this path"""
        return self._impl.lstat()
    
    def iterdir(self) -> Iterator['Path']:
        """Iterate over the files in this directory"""
        return self._impl.iterdir()

    def listdir_attrs(self) -> List[tuple]:
        """Return ``[(Path, attrs), …]`` for this directory — ``iterdir`` plus
        each entry's ``is_dir``/``is_link``/``size``/``mtime`` in one call. See
        :meth:`PathImpl.listdir_attrs`."""
        return self._impl.listdir_attrs()


    def glob(self, pattern: str) -> Iterator['Path']:
        """Iterate over this subtree and yield all existing files matching pattern"""
        return self._impl.glob(pattern)
    
    def rglob(self, pattern: str) -> Iterator['Path']:
        """Recursively iterate over this subtree and yield all existing files matching pattern"""
        return self._impl.rglob(pattern)
    
    def match(self, pattern: str) -> bool:
        """Return True if this path matches the given pattern"""
        return self._impl.match(pattern)
    
    def relative_to(self, other) -> 'Path':
        """Return a version of this path relative to the other path"""
        return self._impl.relative_to(other)
    
    def with_name(self, name: str) -> 'Path':
        """Return a new path with the name changed"""
        return self._impl.with_name(name)
    
    def with_stem(self, stem: str) -> 'Path':
        """Return a new path with the stem changed"""
        return self._impl.with_stem(stem)
    
    def with_suffix(self, suffix: str) -> 'Path':
        """Return a new path with the suffix changed"""
        return self._impl.with_suffix(suffix)
    
    def joinpath(self, *args) -> 'Path':
        """Combine this path with one or several arguments"""
        return self._impl.joinpath(*args)
    
    # File operations
    def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        """Open the file pointed to by this path"""
        return self._impl.open(mode, buffering, encoding, errors, newline)
    
    def read_text(self, encoding=None, errors=None) -> str:
        """Open the file in text mode, read it, and close the file"""
        return self._impl.read_text(encoding, errors)
    
    def read_bytes(self) -> bytes:
        """Open the file in bytes mode, read it, and close the file"""
        return self._impl.read_bytes()
    
    def write_text(self, data: str, encoding=None, errors=None, newline=None) -> int:
        """Open the file in text mode, write to it, and close the file"""
        return self._impl.write_text(data, encoding, errors, newline)
    
    def write_bytes(self, data: bytes) -> int:
        """Open the file in bytes mode, write to it, and close the file"""
        return self._impl.write_bytes(data)
    
    # Directory operations
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """Create a new directory at this given path"""
        return self._impl.mkdir(mode, parents, exist_ok)
    
    def rmdir(self):
        """Remove this directory"""
        return self._impl.rmdir()
    
    def unlink(self, missing_ok=False):
        """Remove this file or symbolic link"""
        return self._impl.unlink(missing_ok)
    
    def rename(self, target) -> 'Path':
        """Rename this file or directory to the given target"""
        return self._impl.rename(target)
    
    def replace(self, target) -> 'Path':
        """Replace this file or directory with the given target"""
        return self._impl.replace(target)
    
    def symlink_to(self, target, target_is_directory=False):
        """Make this path a symlink pointing to the target path"""
        return self._impl.symlink_to(target, target_is_directory)
    
    def hardlink_to(self, target):
        """Make this path a hard link pointing to the same file as target"""
        return self._impl.hardlink_to(target)
    
    def touch(self, mode=0o666, exist_ok=True):
        """Create this file with the given access mode, if it doesn't exist"""
        return self._impl.touch(mode, exist_ok)
    
    def chmod(self, mode):
        """Change the permissions of the path"""
        return self._impl.chmod(mode)
    
    # Class methods
    @classmethod
    def cwd(cls) -> 'Path':
        """Return a new path representing the current working directory"""
        return cls(PathlibPath.cwd())
    
    @classmethod
    def home(cls) -> 'Path':
        """Return a new path representing the user's home directory"""
        return cls(PathlibPath.home())
    
    # Storage-specific methods
    def is_remote(self) -> bool:
        """Return True if this path represents a remote resource"""
        return self._impl.is_remote()
    
    def get_scheme(self) -> str:
        """Return the scheme of the path (e.g., 'file', 's3', 'scp')"""
        return self._impl.get_scheme()
    
    def as_uri(self) -> str:
        """Return the path as a URI"""
        return self._impl.as_uri()
    
    # Compatibility methods for os.path operations
    def samefile(self, other_path) -> bool:
        """Return whether other_path is the same or not as this file"""
        return self._impl.samefile(other_path)
    
    def as_posix(self) -> str:
        """Return the string representation with forward slashes"""
        return self._impl.as_posix()
    
    def supports_directory_rename(self) -> bool:
        """Return True if this storage implementation supports directory renaming"""
        return self._impl.supports_directory_rename()
    
    def supports_file_editing(self) -> bool:
        """Return True if this storage implementation supports external editor editing (vim, nano, etc.)"""
        return self._impl.supports_file_editing()
    
    def supports_write_operations(self) -> bool:
        """Return True if this storage implementation supports write operations (copy, move, create, delete)"""
        return self._impl.supports_write_operations()
    
    # Display methods delegation
    def get_display_prefix(self) -> str:
        """Return a prefix for display purposes"""
        return self._impl.get_display_prefix()
    
    def get_display_title(self) -> str:
        """Return a formatted title for display in viewers and dialogs"""
        return self._impl.get_display_title()
    
    # Content reading strategy methods delegation
    def requires_extraction_for_reading(self) -> bool:
        """Return True if content must be extracted before reading"""
        return self._impl.requires_extraction_for_reading()
    
    def supports_streaming_read(self) -> bool:
        """Return True if file can be read line-by-line without full extraction"""
        return self._impl.supports_streaming_read()
    
    def get_search_strategy(self) -> str:
        """Return recommended search strategy for this storage type"""
        return self._impl.get_search_strategy()
    
    def should_cache_for_search(self) -> bool:
        """Return True if content should be cached during search operations"""
        return self._impl.should_cache_for_search()
    
    # Metadata method delegation
    def get_extended_metadata(self) -> dict:
        """Return storage-specific metadata for display in info dialogs"""
        return self._impl.get_extended_metadata()
    
    def move_to(self, destination: 'Path', overwrite: bool = False) -> bool:
        """
        Move this file or directory to the destination path.
        
        This method handles cross-storage moving (e.g., local to S3, S3 to local).
        For same-storage moves, it uses the native rename operation.
        For cross-storage moves, it copies then deletes the source.
        
        Args:
            destination: Target path where the file/directory should be moved
            overwrite: Whether to overwrite existing files
            
        Returns:
            True if move was successful, False otherwise
            
        Raises:
            FileNotFoundError: If source doesn't exist
            FileExistsError: If destination exists and overwrite=False
            PermissionError: If insufficient permissions
            OSError: For other I/O errors
        """
        if not self.exists():
            raise FileNotFoundError(f"Source path does not exist: {self}")
        
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Destination already exists: {destination}")
        
        # Handle same-storage moving first
        source_scheme = self.get_scheme()
        dest_scheme = destination.get_scheme()
        
        if source_scheme == dest_scheme:
            # Same storage type - use native rename/move
            try:
                self.rename(destination)
                return True
            except OSError as e:
                # errno 18 is EXDEV (Cross-device link) - different mount points
                # Fall through to copy+delete approach
                if e.errno != 18:
                    raise OSError(f"Failed to move {self} to {destination}: {e}")
        
        # Cross-storage moving: copy then delete
        try:
            # First copy to destination
            success = self.copy_to(destination, overwrite=overwrite)
            if not success:
                return False
            
            # Then delete source
            if self.is_dir():
                # For directories, use recursive delete
                if hasattr(self._impl, 'rmtree'):
                    # S3 has optimized recursive delete
                    self._impl.rmtree()
                else:
                    # Use standard recursive delete
                    import shutil
                    if source_scheme == 'file':
                        shutil.rmtree(str(self))
                    else:
                        # For other remote schemes, delete recursively
                        self._delete_recursive()
            else:
                # Single file
                self.unlink()
            
            return True
            
        except Exception as e:
            raise OSError(f"Failed to move {self} to {destination}: {e}")
    
    def _delete_recursive(self):
        """Delete directory recursively for remote storage"""
        if self.is_dir():
            # Delete all contents first
            for item in self.iterdir():
                if item.is_dir():
                    item._delete_recursive()
                else:
                    item.unlink()
            # Then delete the directory itself
            self.rmdir()
        else:
            self.unlink()
    
    def copy_to(self, destination: 'Path', overwrite: bool = False, 
                progress_callback: Optional[callable] = None) -> bool:
        """
        Copy this file or directory to the destination path.
        
        This method handles cross-storage copying (e.g., local to S3, S3 to local).
        
        Args:
            destination: Target path where the file/directory should be copied
            overwrite: Whether to overwrite existing files
            progress_callback: Optional callback for progress tracking (bytes_transferred, total_bytes)
            
        Returns:
            True if copy was successful, False otherwise
            
        Raises:
            FileNotFoundError: If source doesn't exist
            FileExistsError: If destination exists and overwrite=False
            PermissionError: If insufficient permissions
            OSError: For other I/O errors
        """
        if not self.exists():
            raise FileNotFoundError(f"Source path does not exist: {self}")
        
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Destination already exists: {destination}")
        
        # Handle same-storage copying first
        source_scheme = self.get_scheme()
        dest_scheme = destination.get_scheme()
        
        if source_scheme == dest_scheme:
            # Same storage type - use native copy if available
            if hasattr(self._impl, 'copy_to') and hasattr(destination._impl, 'copy_from'):
                return self._impl.copy_to(destination._impl)
            elif source_scheme == 'file':
                # Local to local - use shutil
                import shutil
                if self.is_dir():
                    shutil.copytree(str(self), str(destination), dirs_exist_ok=overwrite)
                else:
                    # Create parent directories for local destination
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(self), str(destination))
                return True
        
        # Cross-storage copying with progress tracking
        if self.is_dir():
            return self._copy_directory_cross_storage(destination, overwrite, progress_callback)
        else:
            return self._copy_file_cross_storage(destination, overwrite, progress_callback)
    
    def _copy_file_cross_storage(self, destination: 'Path', overwrite: bool = False, 
                                 progress_callback: Optional[callable] = None) -> bool:
        """Copy a single file across different storage systems.
        
        Handles transfers between different storage types:
        - Local → Remote (SSH, S3)
        - Remote → Local (SSH, S3)
        - Remote → Remote (SSH, S3)
        
        Args:
            destination: Target path for the copy
            overwrite: Whether to overwrite existing files
            progress_callback: Optional callback for progress tracking (bytes_transferred, total_bytes)
            
        Returns:
            True if copy was successful
            
        Raises:
            OSError: If copy operation fails
        """
        try:
            # Create destination directory if needed (only for local destinations)
            if destination.get_scheme() == 'file':
                destination.parent.mkdir(parents=True, exist_ok=True)
            
            # Get source and destination schemes
            source_scheme = self.get_scheme()
            dest_scheme = destination.get_scheme()
            
            # Handle all cross-storage combinations with progress tracking
            if source_scheme == 'file' and dest_scheme in ('s3', 'ssh'):
                # Local → Remote (S3 or SSH)
                # Read from local file and write to remote
                with self.open('rb') as src:
                    data = src.read()
                
                # Use progress-aware write if available and callback provided
                if dest_scheme == 'ssh' and progress_callback:
                    destination._impl.write_bytes_with_progress(data, progress_callback)
                else:
                    destination.write_bytes(data)
                    
            elif source_scheme in ('s3', 'ssh') and dest_scheme == 'file':
                # Remote → Local (S3 or SSH)
                # Read from remote and write to local file
                if source_scheme == 'ssh' and progress_callback:
                    data = self._impl.read_bytes_with_progress(progress_callback)
                else:
                    data = self.read_bytes()
                destination.write_bytes(data)
                
            elif source_scheme in ('s3', 'ssh') and dest_scheme in ('s3', 'ssh'):
                # Remote → Remote (S3 or SSH)
                # Read from source remote and write to destination remote
                if source_scheme == 'ssh' and progress_callback:
                    data = self._impl.read_bytes_with_progress(progress_callback)
                else:
                    data = self.read_bytes()
                
                if dest_scheme == 'ssh' and progress_callback:
                    destination._impl.write_bytes_with_progress(data, progress_callback)
                else:
                    destination.write_bytes(data)
            else:
                # Generic cross-storage copy for any other combinations
                data = self.read_bytes()
                destination.write_bytes(data)
            
            return True
        except Exception as e:
            raise OSError(f"Failed to copy file from {self} to {destination}: {e}")
    
    def _copy_directory_cross_storage(self, destination: 'Path', overwrite: bool = False,
                                      progress_callback: Optional[callable] = None) -> bool:
        """Copy a directory recursively across different storage systems.
        
        Handles recursive copying of directories and their contents across
        different storage types (local, SSH, S3).
        
        Args:
            destination: Target directory path
            overwrite: Whether to overwrite existing files
            progress_callback: Optional callback for progress tracking (bytes_transferred, total_bytes)
            
        Returns:
            True if copy was successful
            
        Raises:
            OSError: If copy operation fails
        """
        try:
            # Create destination directory
            # For local destinations, use parents=True to create intermediate directories
            # For remote destinations, mkdir should handle directory creation
            if destination.get_scheme() == 'file':
                destination.mkdir(parents=True, exist_ok=overwrite)
            else:
                # For remote destinations (SSH, S3), create directory if it doesn't exist
                if not destination.exists():
                    destination.mkdir(exist_ok=True)
            
            # Copy all contents recursively
            for item in self.iterdir():
                dest_item = destination / item.name
                if item.is_dir():
                    # Recursively copy subdirectories
                    item._copy_directory_cross_storage(dest_item, overwrite, progress_callback)
                else:
                    # Copy individual files with progress tracking
                    item._copy_file_cross_storage(dest_item, overwrite, progress_callback)
            
            return True
        except Exception as e:
            raise OSError(f"Failed to copy directory from {self} to {destination}: {e}")


# Convenience functions that mirror pathlib module-level functions
def PurePath(*args):
    """Create a PurePath - for now, just return our Path class"""
    return Path(*args)


# For backward compatibility, provide access to the underlying pathlib Path
def as_pathlib_path(path: Path) -> PathlibPath:
    """Convert our Path back to a pathlib.Path if needed"""
    if isinstance(path, Path) and isinstance(path._impl, LocalPathImpl):
        return path._impl._path
    return path