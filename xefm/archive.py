#!/usr/bin/env python3
"""
XeFM Archive Operations - Handles archive creation and extraction with cross-storage support
"""

import os
import calendar
import datetime
import tempfile
import tarfile
import zipfile
import gzip
import bz2
import lzma
import shutil
import stat
import io
import time
import threading
import fnmatch
from dataclasses import dataclass
from pathlib import Path as PathlibPath
from xefm.path import Path, PathImpl
from xefm.str_format import format_size
from typing import List, Optional, Union, Tuple, Dict, Any, Iterator


def zip_date_time_to_timestamp(date_time) -> float:
    """Convert a ``ZipInfo.date_time`` tuple to a POSIX timestamp, tolerating junk.

    A zip entry stores its timestamp as a packed MS-DOS date/time, and writers
    that have no timestamp to record simply leave the field zero — streamed
    zips, and several Java/Go/Android writers, do exactly that. ``zipfile``
    unpacks a zero field to ``(1980, 0, 0, 0, 0, 0)``: month and day zero, which
    ``datetime`` rejects. The other components can be out of range too, since
    each is only masked off the packed word — the DOS hour field holds 0..31,
    minutes 0..63, and seconds count 2-second units up to 62.

    So every component is clamped into range rather than trusted. One entry with
    a nonsense date used to raise out of ``ArchiveEntry.from_zip_info`` and fail
    the *entire* archive listing (xefm#277); a clamped date at worst shows the
    DOS epoch, 1980-01-01, for that one entry."""
    if not date_time:
        return 0.0

    year, month, day, hour, minute, second = (tuple(date_time) + (0,) * 6)[:6]
    year = min(max(year, datetime.MINYEAR), datetime.MAXYEAR)
    month = min(max(month, 1), 12)
    # Clamp the day to the month's real length: the 5-bit DOS day field can hold
    # 31 for a month that never has that many days.
    day = min(max(day, 1), calendar.monthrange(year, month)[1])
    hour = min(max(hour, 0), 23)
    minute = min(max(minute, 0), 59)
    second = min(max(second, 0), 59)

    try:
        return datetime.datetime(year, month, day, hour, minute, second).timestamp()
    except (ValueError, OverflowError, OSError):
        # Platforms disagree on which naive datetimes have a POSIX timestamp at
        # all (Windows rejects anything before 1970).
        return 0.0


@dataclass
class ArchiveEntry:
    """
    Represents an entry (file or directory) within an archive.
    
    This dataclass provides a unified representation of archive entries
    across different archive formats (zip, tar, etc.).
    """
    name: str                    # Entry name (filename or dirname)
    internal_path: str           # Full path within archive
    is_dir: bool                 # Whether this is a directory
    size: int                    # Uncompressed size in bytes
    compressed_size: int         # Compressed size in bytes
    mtime: float                 # Modification time as timestamp
    mode: int                    # File permissions (Unix-style)
    archive_type: str            # Archive format ('zip', 'tar', 'tar.gz', etc.)
    
    def to_stat_result(self):
        """
        Convert ArchiveEntry to a stat_result-like object.
        
        This allows archive entries to be used with code that expects
        os.stat_result objects.
        
        Returns:
            os.stat_result: A stat_result object representing this entry
        """
        # Create a stat_result with the entry's metadata
        # Use os.stat_result constructor with a sequence of 10 values:
        # (mode, ino, dev, nlink, uid, gid, size, atime, mtime, ctime)
        
        # Determine the file type bits for mode
        if self.is_dir:
            # Directory mode
            file_mode = stat.S_IFDIR | self.mode
        else:
            # Regular file mode
            file_mode = stat.S_IFREG | self.mode
        
        # Create stat_result with appropriate values
        # We use dummy values for fields that don't apply to archive entries
        stat_values = (
            file_mode,      # st_mode: file type and permissions
            0,              # st_ino: inode number (not applicable)
            0,              # st_dev: device (not applicable)
            1,              # st_nlink: number of hard links
            0,              # st_uid: user ID (not applicable)
            0,              # st_gid: group ID (not applicable)
            self.size,      # st_size: size in bytes
            self.mtime,     # st_atime: access time
            self.mtime,     # st_mtime: modification time
            self.mtime      # st_ctime: creation time
        )
        
        return os.stat_result(stat_values)
    
    @classmethod
    def from_zip_info(cls, zip_info: zipfile.ZipInfo, archive_type: str = 'zip') -> 'ArchiveEntry':
        """
        Create an ArchiveEntry from a ZipInfo object.
        
        Args:
            zip_info: ZipInfo object from zipfile module
            archive_type: Type of archive (default: 'zip')
            
        Returns:
            ArchiveEntry: New entry created from zip info
        """
        # Extract name and determine if it's a directory
        internal_path = zip_info.filename
        is_dir = zip_info.is_dir()
        
        # Get the entry name (last component of path)
        name = internal_path.rstrip('/').split('/')[-1] if internal_path else ''
        
        # Get sizes
        size = zip_info.file_size
        compressed_size = zip_info.compress_size
        
        # Convert date_time tuple to timestamp
        # ZipInfo.date_time is a tuple: (year, month, day, hour, minute, second)
        mtime = zip_date_time_to_timestamp(zip_info.date_time)
        
        # Extract Unix permissions from external_attr
        # For Unix systems, permissions are in the high 16 bits
        # Default to 0o644 for files, 0o755 for directories
        if zip_info.external_attr:
            mode = (zip_info.external_attr >> 16) & 0o777
        else:
            mode = 0o755 if is_dir else 0o644
        
        return cls(
            name=name,
            internal_path=internal_path,
            is_dir=is_dir,
            size=size,
            compressed_size=compressed_size,
            mtime=mtime,
            mode=mode,
            archive_type=archive_type
        )
    
    @classmethod
    def from_tar_info(cls, tar_info: tarfile.TarInfo, archive_type: str = 'tar') -> 'ArchiveEntry':
        """
        Create an ArchiveEntry from a TarInfo object.
        
        Args:
            tar_info: TarInfo object from tarfile module
            archive_type: Type of archive (e.g., 'tar', 'tar.gz', 'tar.bz2')
            
        Returns:
            ArchiveEntry: New entry created from tar info
        """
        # Extract name and path
        internal_path = tar_info.name
        is_dir = tar_info.isdir()
        
        # Get the entry name (last component of path)
        name = internal_path.rstrip('/').split('/')[-1] if internal_path else ''
        
        # Get sizes
        size = tar_info.size
        # For tar files, compressed size is not directly available
        # We'll use the same as uncompressed size as an approximation
        compressed_size = tar_info.size
        
        # Get modification time
        mtime = float(tar_info.mtime) if tar_info.mtime else 0.0
        
        # Get Unix permissions
        mode = tar_info.mode if tar_info.mode else (0o755 if is_dir else 0o644)
        
        return cls(
            name=name,
            internal_path=internal_path,
            is_dir=is_dir,
            size=size,
            compressed_size=compressed_size,
            mtime=mtime,
            mode=mode,
            archive_type=archive_type
        )


class ArchiveError(Exception):
    """Base exception for archive operations"""
    def __init__(self, message: str, user_message: Optional[str] = None):
        """
        Initialize archive error with technical and user-friendly messages.
        
        Args:
            message: Technical error message for logging
            user_message: User-friendly error message (defaults to message if not provided)
        """
        super().__init__(message)
        self.user_message = user_message or message


class ArchiveFormatError(ArchiveError):
    """Unsupported or invalid archive format"""
    pass


class ArchiveCorruptedError(ArchiveError):
    """Archive file is corrupted"""
    pass


class ArchiveExtractionError(ArchiveError):
    """Error during file extraction"""
    pass


class ArchiveNavigationError(ArchiveError):
    """Error navigating within archive"""
    pass


class ArchivePermissionError(ArchiveError):
    """Permission denied for archive operation"""
    pass


class ArchiveDiskSpaceError(ArchiveError):
    """Insufficient disk space for archive operation"""
    pass


class ArchivePasswordRequired(ArchiveError):
    """A password is required to read the archive, or the one supplied is wrong."""
    pass


class ArchiveEncryptionUnsupported(ArchiveError):
    """The archive uses an encryption scheme XeFM cannot decrypt (e.g. WinZip AES).

    Python's ``zipfile`` only decrypts legacy ZipCrypto (traditional PKWARE
    encryption); AES-encrypted entries (WinZip, compression method 99) cannot be
    opened at all."""
    pass


# --- encrypted-zip password registry ----------------------------------------
#
# Passwords the user has supplied for encrypted archives, keyed by the archive
# file's absolute path. Populated by the UI once a correct password is entered
# and consulted by ZipHandler when reading encrypted entries, so viewing files
# inside a browsed password-protected zip keeps working for the session without
# re-prompting. Cleared implicitly when the process exits (nothing is persisted).
_archive_passwords: Dict[str, bytes] = {}
_archive_passwords_lock = threading.RLock()

#: ZIP general-purpose bit-flag 0 marks an entry as encrypted.
_ZIP_ENCRYPTED_FLAG = 0x1
#: WinZip AES entries advertise compression method 99 (the real method lives in
#: an extra field). Python's zipfile cannot decrypt these — only ZipCrypto.
_ZIP_AES_METHOD = 99


def _archive_password_key(archive_path: Path) -> str:
    """The registry key for an archive file — its absolute path as a string."""
    return str(archive_path.absolute())


def set_archive_password(archive_path: Path, password: bytes) -> None:
    """Remember ``password`` (bytes) for ``archive_path`` for the rest of the
    session, so subsequent reads of its encrypted entries don't re-prompt."""
    with _archive_passwords_lock:
        _archive_passwords[_archive_password_key(archive_path)] = password


def get_archive_password(archive_path: Path) -> Optional[bytes]:
    """The remembered password for ``archive_path``, or None if none is known."""
    with _archive_passwords_lock:
        return _archive_passwords.get(_archive_password_key(archive_path))


def clear_archive_password(archive_path: Path) -> None:
    """Forget any remembered password for ``archive_path`` (e.g. after it proves
    wrong)."""
    with _archive_passwords_lock:
        _archive_passwords.pop(_archive_password_key(archive_path), None)


def zip_encryption_status(zf: zipfile.ZipFile) -> str:
    """Classify an open ``ZipFile``'s encryption:

    - ``'none'``      — no encrypted entries.
    - ``'zipcrypto'`` — legacy PKWARE encryption, decryptable with a password.
    - ``'aes'``       — WinZip AES, which Python's zipfile cannot decrypt.

    ``'aes'`` wins if any entry uses it (the archive can't be fully extracted)."""
    status = 'none'
    for info in zf.infolist():
        if info.flag_bits & _ZIP_ENCRYPTED_FLAG:
            if info.compress_type == _ZIP_AES_METHOD:
                return 'aes'
            status = 'zipcrypto'
    return status


def verify_zip_password(zf: zipfile.ZipFile, password: Optional[bytes]) -> None:
    """Probe that ``password`` opens ``zf``'s encrypted entries, raising if not.

    A no-op when nothing is encrypted. Opening the smallest encrypted entry
    validates the ZipCrypto password header (a 12-byte check) cheaply, without
    reading whole files. Raises ``RuntimeError`` for a missing/wrong ZipCrypto
    password and ``NotImplementedError`` for AES (unsupported)."""
    encrypted = [
        info for info in zf.infolist()
        if not info.is_dir() and (info.flag_bits & _ZIP_ENCRYPTED_FLAG)
    ]
    if not encrypted:
        return
    probe = min(encrypted, key=lambda info: info.file_size)
    with zf.open(probe, pwd=password) as fh:
        fh.read(1)


class ArchiveHandler:
    """
    Base class for handling archive file access and caching of archive contents.
    
    This class provides a unified interface for reading archive files and
    extracting their contents, with support for different archive formats
    through format-specific subclasses.
    """
    
    def __init__(self, archive_path: Path):
        """
        Initialize handler for specific archive file.
        
        Args:
            archive_path: Path to the archive file
        """
        self._archive_path = archive_path
        self._archive_obj = None
        self._entry_cache: Dict[str, ArchiveEntry] = {}
        self._directory_cache: Dict[str, List[str]] = {}
        self._is_open = False
        self._last_access = 0.0
    
    def open(self):
        """
        Open the archive file and cache its structure.
        
        Raises:
            ArchiveCorruptedError: If archive is corrupted
            ArchiveFormatError: If archive format is invalid
            FileNotFoundError: If archive file doesn't exist
        """
        raise NotImplementedError("Subclasses must implement open()")
    
    def close(self):
        """Close the archive file"""
        if self._archive_obj:
            try:
                self._archive_obj.close()
            except Exception:
                pass
            self._archive_obj = None
        self._is_open = False
    
    def list_entries(self, internal_path: str = "") -> List[ArchiveEntry]:
        """
        List entries at the given internal path.
        
        Args:
            internal_path: Path within archive (empty string for root)
            
        Returns:
            List of ArchiveEntry objects for direct children
            
        Raises:
            ArchiveNavigationError: If path doesn't exist in archive
        """
        raise NotImplementedError("Subclasses must implement list_entries()")
    
    def get_entry_info(self, internal_path: str) -> Optional[ArchiveEntry]:
        """
        Get information about a specific entry.
        
        Args:
            internal_path: Path to entry within archive
            
        Returns:
            ArchiveEntry object or None if not found
        """
        raise NotImplementedError("Subclasses must implement get_entry_info()")
    
    def extract_to_bytes(self, internal_path: str) -> bytes:
        """
        Extract a file's contents to memory.
        
        Args:
            internal_path: Path to file within archive
            
        Returns:
            File contents as bytes
            
        Raises:
            ArchiveExtractionError: If extraction fails
            FileNotFoundError: If file doesn't exist in archive
        """
        raise NotImplementedError("Subclasses must implement extract_to_bytes()")
    
    def extract_to_file(self, internal_path: str, target_path: Path):
        """
        Extract a file to the filesystem.
        
        Args:
            internal_path: Path to file within archive
            target_path: Destination path on filesystem
            
        Raises:
            ArchiveExtractionError: If extraction fails
            FileNotFoundError: If file doesn't exist in archive
        """
        raise NotImplementedError("Subclasses must implement extract_to_file()")
    
    def _normalize_path(self, path: str) -> str:
        """
        Normalize internal archive path.
        
        Args:
            path: Path to normalize
            
        Returns:
            Normalized path (no leading slash, consistent separators)
        """
        # Remove leading/trailing slashes
        path = path.strip('/')
        # Normalize path separators
        path = path.replace('\\', '/')
        return path
    
    def __enter__(self):
        """Context manager entry"""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
        return False


class ZipHandler(ArchiveHandler):
    """Handler for ZIP archive files"""
    
    def open(self):
        """Open the ZIP archive and cache its structure"""
        try:
            if not self._archive_path.exists():
                raise FileNotFoundError(
                    f"Archive not found: {self._archive_path}",
                    f"Archive file '{self._archive_path.name}' does not exist"
                )
            
            # For remote files, download to temp location
            if self._archive_path.is_remote():
                try:
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
                    temp_file.write(self._archive_path.read_bytes())
                    temp_file.close()
                    archive_to_open = temp_file.name
                    self._temp_file = temp_file.name
                except PermissionError as e:
                    raise ArchivePermissionError(
                        f"Permission denied downloading archive: {e}",
                        f"Cannot download archive '{self._archive_path.name}': Permission denied"
                    )
                except OSError as e:
                    if "No space left on device" in str(e) or "Disk quota exceeded" in str(e):
                        raise ArchiveDiskSpaceError(
                            f"Insufficient disk space: {e}",
                            "Insufficient disk space to download archive"
                        )
                    raise ArchiveError(
                        f"Error downloading archive: {e}",
                        f"Cannot download archive '{self._archive_path.name}': {e}"
                    )
            else:
                archive_to_open = str(self._archive_path)
                self._temp_file = None
            
            # Open the ZIP file
            try:
                self._archive_obj = zipfile.ZipFile(archive_to_open, 'r')
            except PermissionError as e:
                raise ArchivePermissionError(
                    f"Permission denied opening archive: {e}",
                    f"Cannot open archive '{self._archive_path.name}': Permission denied"
                )
            
            self._is_open = True
            
            # Cache all entries
            self._cache_entries()
            
        except FileNotFoundError:
            # Re-raise FileNotFoundError with user-friendly message
            raise FileNotFoundError(
                f"Archive not found: {self._archive_path}",
                f"Archive file '{self._archive_path.name}' does not exist"
            )
        except zipfile.BadZipFile as e:
            raise ArchiveCorruptedError(
                f"Corrupted ZIP archive: {e}",
                f"Archive '{self._archive_path.name}' is corrupted or invalid"
            )
        except (ArchivePermissionError, ArchiveDiskSpaceError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            raise ArchiveFormatError(
                f"Error opening ZIP archive: {e}",
                f"Cannot open archive '{self._archive_path.name}': {e}"
            )
    
    def close(self):
        """Close the ZIP archive and clean up temp files"""
        super().close()
        if hasattr(self, '_temp_file') and self._temp_file:
            try:
                os.unlink(self._temp_file)
            except Exception:
                pass
            self._temp_file = None
    
    def _cache_entries(self):
        """Cache all entries from the ZIP file with lazy loading optimization"""
        if not self._archive_obj:
            return
        
        # Clear caches
        self._entry_cache.clear()
        self._directory_cache.clear()
        
        # Track all directories we've seen (including virtual ones)
        all_directories = set()
        
        # For large archives, use lazy loading - only cache structure, not all entries
        infolist = self._archive_obj.infolist()
        is_large_archive = len(infolist) > 1000
        
        # Process all entries
        for zip_info in infolist:
            entry = ArchiveEntry.from_zip_info(zip_info, 'zip')
            normalized_path = self._normalize_path(entry.internal_path)
            
            # For large archives, only cache directory structure initially
            # Individual entries will be loaded on demand
            if not is_large_archive or entry.is_dir or normalized_path.count('/') < 2:
                # Cache the entry (all entries for small archives, only shallow for large)
                self._entry_cache[normalized_path] = entry
            
            # Build directory cache and track parent directories
            if normalized_path:
                # Get all parent directories
                parts = normalized_path.split('/')
                for i in range(len(parts)):
                    if i == 0:
                        parent = ''
                    else:
                        parent = '/'.join(parts[:i])
                    
                    # Track this directory
                    if i < len(parts) - 1 or entry.is_dir:
                        dir_path = '/'.join(parts[:i+1]) if i < len(parts) - 1 else normalized_path
                        if dir_path:
                            all_directories.add(dir_path)
                    
                    # Add to parent's children list
                    if i < len(parts):
                        child = '/'.join(parts[:i+1])
                        if parent not in self._directory_cache:
                            self._directory_cache[parent] = []
                        if child not in self._directory_cache[parent]:
                            self._directory_cache[parent].append(child)
        
        # Create virtual directory entries for directories that don't have explicit entries
        for dir_path in all_directories:
            if dir_path and dir_path not in self._entry_cache:
                # Create a virtual directory entry
                virtual_entry = ArchiveEntry(
                    name=dir_path.split('/')[-1],
                    internal_path=dir_path,
                    is_dir=True,
                    size=0,
                    compressed_size=0,
                    mtime=0.0,
                    mode=0o755,
                    archive_type='zip'
                )
                self._entry_cache[dir_path] = virtual_entry
    
    def list_entries(self, internal_path: str = "") -> List[ArchiveEntry]:
        """List entries at the given internal path"""
        if not self._is_open:
            self.open()
        
        normalized_path = self._normalize_path(internal_path)
        
        # Get direct children from directory cache
        if normalized_path not in self._directory_cache:
            # Path doesn't exist or has no children
            if normalized_path and normalized_path not in self._entry_cache:
                raise ArchiveNavigationError(f"Path not found in archive: {internal_path}")
            return []
        
        # Return entries for direct children only
        entries = []
        for child_path in self._directory_cache[normalized_path]:
            if child_path in self._entry_cache:
                entries.append(self._entry_cache[child_path])
        
        return entries
    
    def get_entry_info(self, internal_path: str) -> Optional[ArchiveEntry]:
        """Get information about a specific entry with lazy loading"""
        if not self._is_open:
            self.open()
        
        normalized_path = self._normalize_path(internal_path)
        
        # Check cache first
        if normalized_path in self._entry_cache:
            return self._entry_cache[normalized_path]
        
        # For large archives with lazy loading, load entry on demand
        if self._archive_obj:
            try:
                zip_info = self._archive_obj.getinfo(normalized_path)
                entry = ArchiveEntry.from_zip_info(zip_info, 'zip')
                self._entry_cache[normalized_path] = entry
                return entry
            except KeyError:
                # Entry doesn't exist
                return None
        
        return None
    
    def extract_to_bytes(self, internal_path: str) -> bytes:
        """Extract a file's contents to memory"""
        if not self._is_open:
            self.open()
        
        normalized_path = self._normalize_path(internal_path)
        
        # Check if entry exists (with lazy loading)
        entry = self.get_entry_info(normalized_path)
        if not entry:
            raise FileNotFoundError(
                f"File not found in archive: {internal_path}",
                f"File '{internal_path}' does not exist in archive"
            )
        
        if entry.is_dir:
            raise ArchiveExtractionError(
                f"Cannot extract directory as bytes: {internal_path}",
                f"'{internal_path}' is a directory, not a file"
            )
        
        try:
            # Extract file contents. The registered password (if any) is only
            # consulted for encrypted entries; it is ignored otherwise.
            return self._archive_obj.read(
                entry.internal_path, pwd=get_archive_password(self._archive_path)
            )
        except NotImplementedError as e:
            raise ArchiveEncryptionUnsupported(
                f"Unsupported encryption reading {internal_path}: {e}",
                f"Cannot read '{internal_path}': its encryption (e.g. AES) is not supported"
            )
        except RuntimeError as e:
            raise self._read_runtime_error(e, internal_path)
        except PermissionError as e:
            raise ArchivePermissionError(
                f"Permission denied extracting file: {e}",
                f"Cannot extract '{internal_path}': Permission denied"
            )
        except OSError as e:
            if "No space left on device" in str(e) or "Disk quota exceeded" in str(e):
                raise ArchiveDiskSpaceError(
                    f"Insufficient disk space: {e}",
                    "Insufficient disk space to extract file"
                )
            raise ArchiveExtractionError(
                f"Error extracting file: {e}",
                f"Cannot extract '{internal_path}': {e}"
            )
        except Exception as e:
            raise ArchiveExtractionError(
                f"Error extracting file: {e}",
                f"Cannot extract '{internal_path}': {e}"
            )

    def _read_runtime_error(self, exc: RuntimeError, internal_path: str) -> ArchiveError:
        """Map a ``RuntimeError`` raised by a decryption read to a typed archive
        error. Python's zipfile signals a missing or wrong password with a
        ``RuntimeError`` whose message mentions the password/encryption; anything
        else is treated as a generic extraction failure."""
        msg = str(exc).lower()
        if "password" in msg or "encrypted" in msg:
            return ArchivePasswordRequired(
                f"Password required for {internal_path}: {exc}",
                f"'{self._archive_path.name}' is password-protected — a valid password is required"
            )
        return ArchiveExtractionError(
            f"Error extracting {internal_path}: {exc}",
            f"Cannot extract '{internal_path}': {exc}"
        )

    def encryption_status(self) -> str:
        """Classify this zip's encryption — ``'none'``, ``'zipcrypto'``, or
        ``'aes'`` (see :func:`zip_encryption_status`). Opens the archive first."""
        if not self._is_open:
            self.open()
        if not self._archive_obj:
            return 'none'
        return zip_encryption_status(self._archive_obj)

    def verify_password(self, password: bytes) -> bool:
        """Return True if ``password`` correctly opens this zip's encrypted
        entries. A wrong ZipCrypto password returns False; ``NotImplementedError``
        (AES) propagates, since that isn't a wrong-password condition."""
        if not self._is_open:
            self.open()
        if not self._archive_obj:
            return False
        try:
            verify_zip_password(self._archive_obj, password)
            return True
        except RuntimeError:
            return False

    def extract_to_file(self, internal_path: str, target_path: Path):
        """Extract a file to the filesystem"""
        if not self._is_open:
            self.open()

        normalized_path = self._normalize_path(internal_path)

        # Check if entry exists
        entry = self._entry_cache.get(normalized_path)
        if not entry:
            raise FileNotFoundError(
                f"File not found in archive: {internal_path}",
                f"File '{internal_path}' does not exist in archive"
            )

        if entry.is_dir:
            raise ArchiveExtractionError(
                f"Cannot extract directory as file: {internal_path}",
                f"'{internal_path}' is a directory, not a file"
            )

        try:
            # Extract file contents (registered password used only if encrypted).
            try:
                data = self._archive_obj.read(
                    entry.internal_path, pwd=get_archive_password(self._archive_path)
                )
            except NotImplementedError as e:
                raise ArchiveEncryptionUnsupported(
                    f"Unsupported encryption reading {internal_path}: {e}",
                    f"Cannot read '{internal_path}': its encryption (e.g. AES) is not supported"
                )
            except RuntimeError as e:
                raise self._read_runtime_error(e, internal_path)

            # Write to target
            try:
                target_path.write_bytes(data)
            except PermissionError as e:
                raise ArchivePermissionError(
                    f"Permission denied writing to target: {e}",
                    f"Cannot write to '{target_path}': Permission denied"
                )
            except OSError as e:
                if "No space left on device" in str(e) or "Disk quota exceeded" in str(e):
                    raise ArchiveDiskSpaceError(
                        f"Insufficient disk space: {e}",
                        "Insufficient disk space to extract file"
                    )
                raise ArchiveExtractionError(
                    f"Error writing to target: {e}",
                    f"Cannot write to '{target_path}': {e}"
                )
            
            # Try to preserve modification time
            try:
                os.utime(str(target_path), (entry.mtime, entry.mtime))
            except Exception:
                pass  # Ignore errors setting mtime
            
        except (ArchivePermissionError, ArchiveDiskSpaceError,
                ArchivePasswordRequired, ArchiveEncryptionUnsupported):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            raise ArchiveExtractionError(
                f"Error extracting file: {e}",
                f"Cannot extract '{internal_path}': {e}"
            )


class TarHandler(ArchiveHandler):
    """Handler for TAR archive files (including compressed variants)"""
    
    def __init__(self, archive_path: Path, compression: Optional[str] = None):
        """
        Initialize TAR handler.
        
        Args:
            archive_path: Path to the archive file
            compression: Compression type ('gz', 'bz2', 'xz', or None)
        """
        super().__init__(archive_path)
        self._compression = compression
    
    def open(self):
        """Open the TAR archive and cache its structure"""
        try:
            if not self._archive_path.exists():
                raise FileNotFoundError(
                    f"Archive not found: {self._archive_path}",
                    f"Archive file '{self._archive_path.name}' does not exist"
                )
            
            # Determine open mode
            if self._compression == 'gz':
                mode = 'r:gz'
            elif self._compression == 'bz2':
                mode = 'r:bz2'
            elif self._compression == 'xz':
                mode = 'r:xz'
            else:
                mode = 'r'
            
            # For remote files, download to temp location
            if self._archive_path.is_remote():
                try:
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tar')
                    temp_file.write(self._archive_path.read_bytes())
                    temp_file.close()
                    archive_to_open = temp_file.name
                    self._temp_file = temp_file.name
                except PermissionError as e:
                    raise ArchivePermissionError(
                        f"Permission denied downloading archive: {e}",
                        f"Cannot download archive '{self._archive_path.name}': Permission denied"
                    )
                except OSError as e:
                    if "No space left on device" in str(e) or "Disk quota exceeded" in str(e):
                        raise ArchiveDiskSpaceError(
                            f"Insufficient disk space: {e}",
                            "Insufficient disk space to download archive"
                        )
                    raise ArchiveError(
                        f"Error downloading archive: {e}",
                        f"Cannot download archive '{self._archive_path.name}': {e}"
                    )
            else:
                archive_to_open = str(self._archive_path)
                self._temp_file = None
            
            # Open the TAR file
            try:
                self._archive_obj = tarfile.open(archive_to_open, mode)
            except PermissionError as e:
                raise ArchivePermissionError(
                    f"Permission denied opening archive: {e}",
                    f"Cannot open archive '{self._archive_path.name}': Permission denied"
                )
            
            self._is_open = True
            
            # Cache all entries
            self._cache_entries()
            
        except FileNotFoundError:
            # Re-raise FileNotFoundError with user-friendly message
            raise FileNotFoundError(
                f"Archive not found: {self._archive_path}",
                f"Archive file '{self._archive_path.name}' does not exist"
            )
        except tarfile.TarError as e:
            raise ArchiveCorruptedError(
                f"Corrupted TAR archive: {e}",
                f"Archive '{self._archive_path.name}' is corrupted or invalid"
            )
        except (ArchivePermissionError, ArchiveDiskSpaceError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            raise ArchiveFormatError(
                f"Error opening TAR archive: {e}",
                f"Cannot open archive '{self._archive_path.name}': {e}"
            )
    
    def close(self):
        """Close the TAR archive and clean up temp files"""
        super().close()
        if hasattr(self, '_temp_file') and self._temp_file:
            try:
                os.unlink(self._temp_file)
            except Exception:
                pass
            self._temp_file = None
    
    def _cache_entries(self):
        """Cache all entries from the TAR file"""
        if not self._archive_obj:
            return
        
        # Clear caches
        self._entry_cache.clear()
        self._directory_cache.clear()
        
        # Determine archive type string
        if self._compression == 'gz':
            archive_type = 'tar.gz'
        elif self._compression == 'bz2':
            archive_type = 'tar.bz2'
        elif self._compression == 'xz':
            archive_type = 'tar.xz'
        else:
            archive_type = 'tar'
        
        # Track all directories we've seen (including virtual ones)
        all_directories = set()
        
        # Process all entries
        for tar_info in self._archive_obj.getmembers():
            entry = ArchiveEntry.from_tar_info(tar_info, archive_type)
            normalized_path = self._normalize_path(entry.internal_path)
            
            # Cache the entry
            self._entry_cache[normalized_path] = entry
            
            # Build directory cache and track parent directories
            if normalized_path:
                # Get all parent directories
                parts = normalized_path.split('/')
                for i in range(len(parts)):
                    if i == 0:
                        parent = ''
                    else:
                        parent = '/'.join(parts[:i])
                    
                    # Track this directory
                    if i < len(parts) - 1 or entry.is_dir:
                        dir_path = '/'.join(parts[:i+1]) if i < len(parts) - 1 else normalized_path
                        if dir_path:
                            all_directories.add(dir_path)
                    
                    # Add to parent's children list
                    if i < len(parts):
                        child = '/'.join(parts[:i+1])
                        if parent not in self._directory_cache:
                            self._directory_cache[parent] = []
                        if child not in self._directory_cache[parent]:
                            self._directory_cache[parent].append(child)
        
        # Create virtual directory entries for directories that don't have explicit entries
        for dir_path in all_directories:
            if dir_path and dir_path not in self._entry_cache:
                # Create a virtual directory entry
                virtual_entry = ArchiveEntry(
                    name=dir_path.split('/')[-1],
                    internal_path=dir_path,
                    is_dir=True,
                    size=0,
                    compressed_size=0,
                    mtime=0.0,
                    mode=0o755,
                    archive_type=archive_type
                )
                self._entry_cache[dir_path] = virtual_entry
    
    def list_entries(self, internal_path: str = "") -> List[ArchiveEntry]:
        """List entries at the given internal path"""
        if not self._is_open:
            self.open()
        
        normalized_path = self._normalize_path(internal_path)
        
        # Get direct children from directory cache
        if normalized_path not in self._directory_cache:
            # Path doesn't exist or has no children
            if normalized_path and normalized_path not in self._entry_cache:
                raise ArchiveNavigationError(f"Path not found in archive: {internal_path}")
            return []
        
        # Return entries for direct children only
        entries = []
        for child_path in self._directory_cache[normalized_path]:
            if child_path in self._entry_cache:
                entries.append(self._entry_cache[child_path])
        
        return entries
    
    def get_entry_info(self, internal_path: str) -> Optional[ArchiveEntry]:
        """Get information about a specific entry"""
        if not self._is_open:
            self.open()
        
        normalized_path = self._normalize_path(internal_path)
        return self._entry_cache.get(normalized_path)
    
    def extract_to_bytes(self, internal_path: str) -> bytes:
        """Extract a file's contents to memory"""
        if not self._is_open:
            self.open()
        
        normalized_path = self._normalize_path(internal_path)
        
        # Check if entry exists
        entry = self._entry_cache.get(normalized_path)
        if not entry:
            raise FileNotFoundError(
                f"File not found in archive: {internal_path}",
                f"File '{internal_path}' does not exist in archive"
            )
        
        if entry.is_dir:
            raise ArchiveExtractionError(
                f"Cannot extract directory as bytes: {internal_path}",
                f"'{internal_path}' is a directory, not a file"
            )
        
        try:
            # Extract file contents
            file_obj = self._archive_obj.extractfile(entry.internal_path)
            if file_obj is None:
                raise ArchiveExtractionError(
                    f"Cannot extract file: {internal_path}",
                    f"Cannot extract '{internal_path}' from archive"
                )
            
            return file_obj.read()
        except ArchiveExtractionError:
            # Re-raise our custom exception
            raise
        except PermissionError as e:
            raise ArchivePermissionError(
                f"Permission denied extracting file: {e}",
                f"Cannot extract '{internal_path}': Permission denied"
            )
        except OSError as e:
            if "No space left on device" in str(e) or "Disk quota exceeded" in str(e):
                raise ArchiveDiskSpaceError(
                    f"Insufficient disk space: {e}",
                    "Insufficient disk space to extract file"
                )
            raise ArchiveExtractionError(
                f"Error extracting file: {e}",
                f"Cannot extract '{internal_path}': {e}"
            )
        except Exception as e:
            raise ArchiveExtractionError(
                f"Error extracting file: {e}",
                f"Cannot extract '{internal_path}': {e}"
            )
    
    def extract_to_file(self, internal_path: str, target_path: Path):
        """Extract a file to the filesystem"""
        if not self._is_open:
            self.open()
        
        normalized_path = self._normalize_path(internal_path)
        
        # Check if entry exists
        entry = self._entry_cache.get(normalized_path)
        if not entry:
            raise FileNotFoundError(
                f"File not found in archive: {internal_path}",
                f"File '{internal_path}' does not exist in archive"
            )
        
        if entry.is_dir:
            raise ArchiveExtractionError(
                f"Cannot extract directory as file: {internal_path}",
                f"'{internal_path}' is a directory, not a file"
            )
        
        try:
            # Extract file contents
            file_obj = self._archive_obj.extractfile(entry.internal_path)
            if file_obj is None:
                raise ArchiveExtractionError(
                    f"Cannot extract file: {internal_path}",
                    f"Cannot extract '{internal_path}' from archive"
                )
            
            data = file_obj.read()
            
            # Write to target
            try:
                target_path.write_bytes(data)
            except PermissionError as e:
                raise ArchivePermissionError(
                    f"Permission denied writing to target: {e}",
                    f"Cannot write to '{target_path}': Permission denied"
                )
            except OSError as e:
                if "No space left on device" in str(e) or "Disk quota exceeded" in str(e):
                    raise ArchiveDiskSpaceError(
                        f"Insufficient disk space: {e}",
                        "Insufficient disk space to extract file"
                    )
                raise ArchiveExtractionError(
                    f"Error writing to target: {e}",
                    f"Cannot write to '{target_path}': {e}"
                )
            
            # Try to preserve modification time and permissions
            try:
                os.utime(str(target_path), (entry.mtime, entry.mtime))
                os.chmod(str(target_path), entry.mode)
            except Exception:
                pass  # Ignore errors setting metadata
            
        except (ArchivePermissionError, ArchiveDiskSpaceError, ArchiveExtractionError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            raise ArchiveExtractionError(
                f"Error extracting file: {e}",
                f"Cannot extract '{internal_path}': {e}"
            )


class ArchiveCache:
    """
    Cache for opened archives and their structures.
    
    Features:
    - LRU eviction policy to limit memory usage
    - Configurable TTL (time-to-live) for cached structures
    - Thread-safe operations with locks
    - Lazy initialization of archive handlers
    - Cache statistics and monitoring
    - Performance metrics tracking
    """
    
    def __init__(self, max_open: int = 5, ttl: int = 300):
        """
        Initialize cache.
        
        Args:
            max_open: Maximum number of archives to keep open (default: 5)
            ttl: Time-to-live for cached structures in seconds (default: 300)
        """
        self._max_open = max_open
        self._ttl = ttl
        self._handlers: Dict[str, ArchiveHandler] = {}
        self._access_times: Dict[str, float] = {}
        self._lock = threading.RLock()
        
        # Performance metrics
        self._cache_hits = 0
        self._cache_misses = 0
        self._evictions = 0
        self._total_open_time = 0.0
    
    def get_handler(self, archive_path: Path) -> ArchiveHandler:
        """
        Get or create handler for archive with lazy initialization.
        
        Args:
            archive_path: Path to the archive file
            
        Returns:
            ArchiveHandler: Handler for the archive
            
        Raises:
            ArchiveError: If archive cannot be opened
        """
        # Convert path to string for cache key
        cache_key = str(archive_path.absolute())
        current_time = time.time()
        
        with self._lock:
            # Check if handler exists and is still valid
            if cache_key in self._handlers:
                handler = self._handlers[cache_key]
                access_time = self._access_times.get(cache_key, 0)
                
                # Check if handler has expired
                if current_time - access_time > self._ttl:
                    # Handler expired, close and remove it
                    try:
                        handler.close()
                    except Exception:
                        pass
                    del self._handlers[cache_key]
                    del self._access_times[cache_key]
                    self._cache_misses += 1
                else:
                    # Handler is valid, update access time and return
                    self._access_times[cache_key] = current_time
                    self._cache_hits += 1
                    return handler
            else:
                self._cache_misses += 1
            
            # Need to create new handler
            # First, enforce max_open limit using LRU eviction
            if len(self._handlers) >= self._max_open:
                self._evict_lru()
            
            # Create appropriate handler based on archive format
            handler = self._create_handler(archive_path)
            
            # Open the handler (lazy initialization) and track time
            open_start = time.time()
            handler.open()
            open_duration = time.time() - open_start
            self._total_open_time += open_duration
            
            # Cache the handler
            self._handlers[cache_key] = handler
            self._access_times[cache_key] = current_time
            
            return handler
    
    def _create_handler(self, archive_path: Path) -> ArchiveHandler:
        """
        Create appropriate handler for archive format.
        
        Args:
            archive_path: Path to the archive file
            
        Returns:
            ArchiveHandler: Appropriate handler for the archive format
            
        Raises:
            ArchiveFormatError: If archive format is not supported
        """
        filename = archive_path.name.lower()
        
        # Check for ZIP format
        if filename.endswith('.zip'):
            return ZipHandler(archive_path)
        
        # Check for TAR formats
        if filename.endswith('.tar'):
            return TarHandler(archive_path, compression=None)
        elif filename.endswith('.tar.gz') or filename.endswith('.tgz'):
            return TarHandler(archive_path, compression='gz')
        elif filename.endswith('.tar.bz2') or filename.endswith('.tbz2'):
            return TarHandler(archive_path, compression='bz2')
        elif filename.endswith('.tar.xz') or filename.endswith('.txz'):
            return TarHandler(archive_path, compression='xz')
        
        # Unsupported format
        raise ArchiveFormatError(f"Unsupported archive format: {filename}")
    
    def invalidate(self, archive_path: Path):
        """
        Invalidate cache for specific archive.
        
        Args:
            archive_path: Path to the archive file to invalidate
        """
        cache_key = str(archive_path.absolute())
        
        with self._lock:
            if cache_key in self._handlers:
                handler = self._handlers[cache_key]
                try:
                    handler.close()
                except Exception:
                    pass
                del self._handlers[cache_key]
                del self._access_times[cache_key]
    
    def clear(self):
        """Clear all cached archives."""
        with self._lock:
            # Close all handlers
            for handler in self._handlers.values():
                try:
                    handler.close()
                except Exception:
                    pass
            
            # Clear caches
            self._handlers.clear()
            self._access_times.clear()
    
    def _evict_lru(self):
        """Evict the least recently used cache entry."""
        if not self._handlers:
            return
        
        # Find the entry with the oldest access time
        oldest_key = min(self._access_times.keys(), 
                        key=lambda k: self._access_times[k])
        
        # Close and remove the handler
        handler = self._handlers[oldest_key]
        try:
            handler.close()
        except Exception:
            pass
        
        del self._handlers[oldest_key]
        del self._access_times[oldest_key]
        self._evictions += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.
        
        Returns:
            Dictionary containing cache statistics:
            - open_archives: Number of currently open archives
            - max_open: Maximum number of archives that can be open
            - ttl: Time-to-live in seconds
            - expired_count: Number of expired entries (not yet evicted)
            - cache_hits: Number of cache hits
            - cache_misses: Number of cache misses
            - hit_rate: Cache hit rate (0.0 to 1.0)
            - evictions: Number of LRU evictions performed
            - avg_open_time: Average time to open an archive (seconds)
        """
        with self._lock:
            current_time = time.time()
            expired_count = sum(
                1 for cache_key in self._access_times.keys()
                if current_time - self._access_times[cache_key] > self._ttl
            )
            
            total_requests = self._cache_hits + self._cache_misses
            hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0.0
            avg_open_time = self._total_open_time / self._cache_misses if self._cache_misses > 0 else 0.0
            
            return {
                'open_archives': len(self._handlers),
                'max_open': self._max_open,
                'ttl': self._ttl,
                'expired_count': expired_count,
                'cache_hits': self._cache_hits,
                'cache_misses': self._cache_misses,
                'hit_rate': hit_rate,
                'evictions': self._evictions,
                'avg_open_time': avg_open_time
            }


# Global archive cache instance
_archive_cache = None


def get_archive_cache() -> ArchiveCache:
    """Get or create the global archive cache instance."""
    global _archive_cache
    if _archive_cache is None:
        # Get configuration from config if available
        try:
            from xefm.config import get_config
            config = get_config()
            max_open = config.ARCHIVE_CACHE_MAX_OPEN
            ttl = config.ARCHIVE_CACHE_TTL
        except (ImportError, Exception):
            # Fallback to defaults if config not available
            max_open = 5
            ttl = 300
        
        _archive_cache = ArchiveCache(max_open=max_open, ttl=ttl)
    
    return _archive_cache


class ArchivePathImpl(PathImpl):
    """
    Archive file implementation of PathImpl.
    
    This class provides access to files and directories within archive files
    as if they were a virtual filesystem. Archive paths use the format:
    archive:///absolute/path/to/archive.zip#internal/path
    
    The '#' separator distinguishes the archive file path from the internal path.
    """
    
    def __init__(self, archive_uri: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize with archive URI and optional metadata.
        
        Args:
            archive_uri: URI in format archive://path/to/file.zip#internal/path
            metadata: Optional cached metadata to avoid archive reads
        """
        self._uri = archive_uri
        self._metadata = metadata or {}
        
        # Parse the URI to extract archive path and internal path
        self._parse_uri()
        
        # Get the global archive cache
        self._cache = get_archive_cache()
        
        # Cache for frequently accessed properties to avoid repeated computation
        self._property_cache = {}
    
    def _parse_uri(self):
        """Parse archive URI into archive path and internal path components."""
        if not self._uri.startswith('archive://'):
            raise ValueError(f"Invalid archive URI: {self._uri}")
        
        # Remove the 'archive://' prefix
        path_part = self._uri[10:]  # len('archive://') = 10
        
        # Split on '#' to separate archive path from internal path
        if '#' in path_part:
            archive_path_str, internal_path = path_part.split('#', 1)
        else:
            # No internal path specified, use root
            archive_path_str = path_part
            internal_path = ''
        
        # Create Path object for the archive file
        self._archive_path = Path(archive_path_str)
        
        # Normalize internal path
        self._internal_path = self._normalize_internal_path(internal_path)
    
    def _normalize_internal_path(self, path: str) -> str:
        """
        Normalize internal archive paths.
        
        Args:
            path: Path to normalize
            
        Returns:
            Normalized path (no leading slash, consistent separators)
        """
        # Remove leading/trailing slashes
        path = path.strip('/')
        # Normalize path separators
        path = path.replace('\\', '/')
        return path
    
    def _get_archive_handler(self) -> ArchiveHandler:
        """Get or create cached archive handler for this archive file."""
        return self._cache.get_handler(self._archive_path)
    
    def _get_entry(self) -> Optional[ArchiveEntry]:
        """Get the ArchiveEntry for this path."""
        # Check metadata cache first
        if 'entry' in self._metadata:
            return self._metadata['entry']
        
        # Get from archive handler
        handler = self._get_archive_handler()
        entry = handler.get_entry_info(self._internal_path)
        
        # Cache the entry
        if entry:
            self._metadata['entry'] = entry
        
        return entry
    
    def __str__(self) -> str:
        """String representation of the path."""
        return self._uri
    
    def __eq__(self, other) -> bool:
        """Equality comparison."""
        if isinstance(other, ArchivePathImpl):
            return self._uri == other._uri
        elif isinstance(other, str):
            return self._uri == other
        return False
    
    def __hash__(self) -> int:
        """Hash support for use in sets and dicts."""
        return hash(self._uri)
    
    def __lt__(self, other) -> bool:
        """Less than comparison for sorting."""
        if isinstance(other, ArchivePathImpl):
            return self._uri < other._uri
        return self._uri < str(other)
    
    # Properties
    @property
    def name(self) -> str:
        """The final component of the path."""
        # Check property cache first
        if 'name' in self._property_cache:
            return self._property_cache['name']
        
        if not self._internal_path:
            # Root of archive - return archive filename
            result = self._archive_path.name
        else:
            # Return last component of internal path
            parts = self._internal_path.rstrip('/').split('/')
            result = parts[-1] if parts else ''
        
        self._property_cache['name'] = result
        return result
    
    @property
    def stem(self) -> str:
        """The final component without its suffix."""
        name = self.name
        if '.' in name:
            return name.rsplit('.', 1)[0]
        return name
    
    @property
    def suffix(self) -> str:
        """The file extension of the final component."""
        name = self.name
        if '.' in name:
            return '.' + name.rsplit('.', 1)[1]
        return ''
    
    @property
    def suffixes(self) -> List[str]:
        """A list of the path's suffixes."""
        name = self.name
        if '.' not in name:
            return []
        
        parts = name.split('.')
        return ['.' + part for part in parts[1:]]
    
    @property
    def parent(self) -> 'Path':
        """The logical parent of the path."""
        if not self._internal_path:
            # At root of archive - parent is the directory containing the archive
            return self._archive_path.parent
        
        # Get parent of internal path
        parts = self._internal_path.rstrip('/').split('/')
        if len(parts) > 1:
            parent_internal = '/'.join(parts[:-1])
        else:
            parent_internal = ''
        
        # Create new archive path for parent
        parent_uri = f"archive://{self._archive_path.absolute()}#{parent_internal}"
        return Path(parent_uri)
    
    @property
    def parents(self):
        """A sequence providing access to the logical ancestors of the path."""
        parents_list = []
        current = self.parent
        
        while True:
            parents_list.append(current)
            
            # Check if we've reached the archive root
            if isinstance(current._impl, ArchivePathImpl):
                if not current._impl._internal_path:
                    # At archive root, add the archive's parent directory
                    parents_list.append(current._impl._archive_path.parent)
                    break
                current = current.parent
            else:
                # Reached filesystem path
                break
        
        return parents_list
    
    @property
    def parts(self) -> tuple:
        """A tuple giving access to the path's components."""
        # Check property cache first
        if 'parts' in self._property_cache:
            return self._property_cache['parts']
        
        # Include archive path parts and internal path parts
        archive_parts = self._archive_path.parts
        
        if self._internal_path:
            internal_parts = tuple(self._internal_path.split('/'))
            result = archive_parts + ('#',) + internal_parts
        else:
            result = archive_parts + ('#',)
        
        self._property_cache['parts'] = result
        return result
    
    @property
    def anchor(self) -> str:
        """The concatenation of the drive and root."""
        return self._archive_path.anchor
    
    # Path manipulation methods
    def absolute(self) -> 'Path':
        """Return an absolute version of this path."""
        # Archive paths are always absolute
        abs_archive = self._archive_path.absolute()
        abs_uri = f"archive://{abs_archive}#{self._internal_path}"
        return Path(abs_uri)
    
    def resolve(self, strict: bool = False) -> 'Path':
        """Make the path absolute, resolving any symlinks."""
        # Archive paths don't have symlinks, just return absolute
        return self.absolute()
    
    def expanduser(self) -> 'Path':
        """Return a new path with expanded ~ and ~user constructs."""
        # Expand user in archive path
        expanded_archive = self._archive_path.expanduser()
        expanded_uri = f"archive://{expanded_archive}#{self._internal_path}"
        return Path(expanded_uri)
    
    def joinpath(self, *args) -> 'Path':
        """Combine this path with one or several arguments."""
        # Join to internal path
        if not args:
            return Path(self._uri)
        
        # Combine all arguments
        joined_parts = [self._internal_path] if self._internal_path else []
        for arg in args:
            arg_str = str(arg).strip('/')
            if arg_str:
                joined_parts.append(arg_str)
        
        new_internal = '/'.join(joined_parts)
        new_uri = f"archive://{self._archive_path.absolute()}#{new_internal}"
        return Path(new_uri)
    
    def with_name(self, name: str) -> 'Path':
        """Return a new path with the name changed."""
        if not self._internal_path:
            raise ValueError("Cannot change name of archive root")
        
        # Replace last component
        parts = self._internal_path.rstrip('/').split('/')
        parts[-1] = name
        new_internal = '/'.join(parts)
        new_uri = f"archive://{self._archive_path.absolute()}#{new_internal}"
        return Path(new_uri)
    
    def with_stem(self, stem: str) -> 'Path':
        """Return a new path with the stem changed."""
        suffix = self.suffix
        new_name = stem + suffix
        return self.with_name(new_name)
    
    def with_suffix(self, suffix: str) -> 'Path':
        """Return a new path with the suffix changed."""
        stem = self.stem
        new_name = stem + suffix
        return self.with_name(new_name)
    
    def relative_to(self, other) -> 'Path':
        """Return a version of this path relative to the other path."""
        # For archive paths, this is complex - simplified implementation
        if isinstance(other, Path) and isinstance(other._impl, ArchivePathImpl):
            other_impl = other._impl
            
            # Must be in same archive
            if self._archive_path != other_impl._archive_path:
                raise ValueError(f"{self} is not relative to {other}")
            
            # Get relative internal path
            if not other_impl._internal_path:
                # Other is archive root
                return Path(self._internal_path)
            
            # Check if self is under other
            if self._internal_path.startswith(other_impl._internal_path + '/'):
                rel_path = self._internal_path[len(other_impl._internal_path) + 1:]
                return Path(rel_path)
            
            raise ValueError(f"{self} is not relative to {other}")
        
        raise ValueError(f"{self} is not relative to {other}")
    
    # File system query methods
    def exists(self) -> bool:
        """Whether this path exists."""
        try:
            # Check if archive file exists
            if not self._archive_path.exists():
                return False
            
            # Root of archive always exists if archive exists
            if not self._internal_path:
                return True
            
            # Check if entry exists in archive
            entry = self._get_entry()
            return entry is not None
        except Exception:
            return False
    
    def is_dir(self) -> bool:
        """Whether this path is a directory."""
        try:
            # Root of archive is always a directory
            if not self._internal_path:
                return True
            
            entry = self._get_entry()
            return entry.is_dir if entry else False
        except Exception:
            return False
    
    def is_file(self) -> bool:
        """Whether this path is a regular file."""
        try:
            # Root of archive is not a file
            if not self._internal_path:
                return False
            
            entry = self._get_entry()
            return not entry.is_dir if entry else False
        except Exception:
            return False
    
    def is_symlink(self) -> bool:
        """Whether this path is a symbolic link."""
        # Archives don't support symlinks in our implementation
        return False
    
    def is_absolute(self) -> bool:
        """Whether this path is absolute."""
        # Archive paths are always absolute
        return True
    
    def stat(self):
        """Return the result of os.stat() on this path."""
        entry = self._get_entry()
        if not entry:
            raise FileNotFoundError(f"No such file or directory: {self}")
        
        return entry.to_stat_result()
    
    def lstat(self):
        """Return the result of os.lstat() on this path."""
        # No symlinks in archives, same as stat
        return self.stat()
    
    # Directory operations
    def iterdir(self) -> Iterator['Path']:
        """Iterate over the files in this directory."""
        if not self.is_dir():
            raise NotADirectoryError(f"Not a directory: {self}")
        
        try:
            handler = self._get_archive_handler()
            entries = handler.list_entries(self._internal_path)
            
            for entry in entries:
                entry_uri = f"archive://{self._archive_path.absolute()}#{entry.internal_path}"
                # Create Path with cached metadata
                path = Path(entry_uri)
                path._impl._metadata['entry'] = entry
                yield path
        except Exception as e:
            raise OSError(f"Error iterating directory: {e}")
    
    def glob(self, pattern: str) -> Iterator['Path']:
        """Iterate over this subtree and yield all existing files matching pattern."""
        if not self.is_dir():
            return
        
        # Handle ** pattern for recursive search
        if pattern.startswith('**/'):
            # Recursive pattern - search all subdirectories
            sub_pattern = pattern[3:]  # Remove **/ prefix
            
            # Yield matching items in current directory
            for item in self.iterdir():
                if fnmatch.fnmatch(item.name, sub_pattern):
                    yield item
                
                # Recursively search subdirectories
                if item.is_dir():
                    try:
                        for sub_item in item.glob(pattern):
                            yield sub_item
                    except Exception:
                        pass
        else:
            # Non-recursive pattern - only search current directory
            for item in self.iterdir():
                if fnmatch.fnmatch(item.name, pattern):
                    yield item
    
    def rglob(self, pattern: str) -> Iterator['Path']:
        """Recursively iterate over this subtree and yield all existing files matching pattern."""
        # rglob is like glob with ** prefix
        return self.glob(f"**/{pattern}")
    
    def match(self, pattern: str) -> bool:
        """Return True if this path matches the given pattern."""
        return fnmatch.fnmatch(str(self), pattern)
    
    # File I/O operations
    def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        """Open the file pointed to by this path."""
        if 'w' in mode or 'a' in mode or '+' in mode:
            raise OSError("Archive files are read-only")
        
        if not self.is_file():
            raise IsADirectoryError(f"Is a directory: {self}")
        
        try:
            handler = self._get_archive_handler()
            data = handler.extract_to_bytes(self._internal_path)
            
            if 'b' in mode:
                # Binary mode
                return io.BytesIO(data)
            else:
                # Text mode
                text = data.decode(encoding or 'utf-8', errors or 'strict')
                return io.StringIO(text)
        except Exception as e:
            raise OSError(f"Error opening file: {e}")
    
    def read_text(self, encoding=None, errors=None) -> str:
        """Open the file in text mode, read it, and close the file."""
        try:
            handler = self._get_archive_handler()
            data = handler.extract_to_bytes(self._internal_path)
            return data.decode(encoding or 'utf-8', errors or 'strict')
        except Exception as e:
            raise OSError(f"Error reading text: {e}")
    
    def read_bytes(self) -> bytes:
        """Open the file in bytes mode, read it, and close the file."""
        try:
            handler = self._get_archive_handler()
            return handler.extract_to_bytes(self._internal_path)
        except Exception as e:
            raise OSError(f"Error reading bytes: {e}")
    
    def write_text(self, data: str, encoding=None, errors=None, newline=None) -> int:
        """Open the file in text mode, write to it, and close the file."""
        raise OSError("Archive files are read-only")
    
    def write_bytes(self, data: bytes) -> int:
        """Open the file in bytes mode, write to it, and close the file."""
        raise OSError("Archive files are read-only")
    
    # File system modification operations
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """Create a new directory at this given path."""
        raise OSError("Archive files are read-only")
    
    def rmdir(self):
        """Remove this directory."""
        raise OSError("Archive files are read-only")
    
    def unlink(self, missing_ok=False):
        """Remove this file or symbolic link."""
        raise OSError("Archive files are read-only")
    
    def rename(self, target) -> 'Path':
        """Rename this file or directory to the given target."""
        raise OSError("Archive files are read-only")
    
    def replace(self, target) -> 'Path':
        """Replace this file or directory with the given target."""
        raise OSError("Archive files are read-only")
    
    def symlink_to(self, target, target_is_directory=False):
        """Make this path a symlink pointing to the target path."""
        raise OSError("Archive files are read-only")
    
    def hardlink_to(self, target):
        """Make this path a hard link pointing to the same file as target."""
        raise OSError("Archive files are read-only")
    
    def touch(self, mode=0o666, exist_ok=True):
        """Create this file with the given access mode, if it doesn't exist."""
        raise OSError("Archive files are read-only")
    
    def chmod(self, mode):
        """Change the permissions of the path."""
        raise OSError("Archive files are read-only")
    
    # Storage-specific methods
    def is_remote(self) -> bool:
        """Return True if this path represents a remote resource."""
        # Archive paths are virtual, but the underlying archive might be remote
        return self._archive_path.is_remote()
    
    def get_scheme(self) -> str:
        """Return the scheme of the path (e.g., 'file', 's3', 'scp')."""
        return 'archive'
    
    def as_uri(self) -> str:
        """Return the path as a URI."""
        return self._uri
    
    def supports_directory_rename(self) -> bool:
        """Return True if this storage implementation supports directory renaming."""
        return False  # Archives are read-only
    
    def supports_file_editing(self) -> bool:
        """Return True if this storage implementation supports external editor editing (vim, nano, etc.)"""
        return False  # Archives are read-only
    
    def supports_write_operations(self) -> bool:
        """Return True if this storage implementation supports write operations (copy, move, create, delete)"""
        return False  # Archives are read-only
    
    # Display methods for UI presentation
    def get_display_prefix(self) -> str:
        """Return a prefix for display purposes.
        
        For archive entries, returns 'ARCHIVE: ' to indicate the storage type
        in UI components like text viewers and info dialogs.
        
        Returns:
            str: 'ARCHIVE: ' (with trailing space)
        """
        return 'ARCHIVE: '
    
    def get_display_title(self) -> str:
        """Return a formatted title for display in viewers and dialogs.
        
        For archive entries, returns the full archive URI which includes both
        the archive file path and the internal path within the archive.
        
        Returns:
            str: Full archive URI in format 'archive://path/to/file.zip#internal/path'
        """
        return self._uri
    
    # Content reading strategy methods
    def requires_extraction_for_reading(self) -> bool:
        """Return True if content must be extracted before reading.
        
        Archive files must be extracted from the archive container before their
        content can be read. This affects how content is accessed - it cannot be
        read directly and must be extracted to memory or disk first.
        
        Returns:
            bool: True - archive content always requires extraction
        """
        return True
    
    def supports_streaming_read(self) -> bool:
        """Return True if file can be read line-by-line without full extraction.
        
        Archive files do not support streaming reads. The entire file must be
        extracted from the archive before it can be accessed. This affects memory
        usage during operations like search, as the full content must be loaded.
        
        Returns:
            bool: False - archive content cannot be streamed
        """
        return False
    
    def get_search_strategy(self) -> str:
        """Return recommended search strategy for this storage type.
        
        Archive files require the 'extracted' strategy, meaning the entire file
        content must be extracted from the archive before searching can begin.
        This is necessary because archive formats don't support random access
        or streaming reads of individual files.
        
        Returns:
            str: 'extracted' - must extract entire content before searching
        """
        return 'extracted'
    
    def should_cache_for_search(self) -> bool:
        """Return True if content should be cached during search operations.
        
        Archive content should be cached during search operations because
        extraction is expensive. Caching the extracted content allows multiple
        search operations or result viewing without repeated extraction overhead.
        
        Returns:
            bool: True - caching is recommended for archive content
        """
        return True
    
    # Metadata method for info dialogs
    def get_extended_metadata(self) -> dict:
        """Return storage-specific metadata for display in info dialogs.
        
        For archive entries, provides detailed information including the archive
        file name, internal path within the archive, compressed and uncompressed
        sizes, compression type, and modification time.
        
        Returns:
            dict: Metadata dictionary with keys:
                - 'type': 'archive'
                - 'details': List of (label, value) tuples with archive-specific fields
                - 'format_hint': 'archive'
        """
        entry = self._get_entry()
        if not entry:
            # If entry doesn't exist, return minimal metadata
            details = [
                ('Archive', self._archive_path.name),
                ('Internal Path', self._internal_path or '/'),
                ('Type', 'Unknown'),
            ]
        else:
            details = [
                ('Archive', self._archive_path.name),
                ('Internal Path', self._internal_path or '/'),
                ('Type', 'Directory' if entry.is_dir else 'File'),
                ('Compressed Size', format_size(entry.compressed_size)),
                ('Uncompressed Size', format_size(entry.size)),
                ('Compression', self._get_compression_name(entry.archive_type)),
                ('Modified', self._format_archive_time(entry.mtime))
            ]
        
        return {
            'type': 'archive',
            'details': details,
            'format_hint': 'archive'
        }
    
    def _get_compression_name(self, archive_type: str) -> str:
        """Convert archive type to compression name.
        
        Args:
            archive_type: Archive format string (e.g., 'zip', 'tar.gz', 'tar')
            
        Returns:
            str: Human-readable compression name
        """
        compression_map = {
            'zip': 'ZIP (Deflated)',
            'tar': 'None (Uncompressed)',
            'tar.gz': 'GZIP',
            'tar.bz2': 'BZIP2',
            'tar.xz': 'LZMA/XZ',
        }
        return compression_map.get(archive_type, archive_type.upper())
    
    def _format_archive_time(self, timestamp: float) -> str:
        """Format archive entry modification time.
        
        Args:
            timestamp: Unix timestamp (seconds since epoch)
            
        Returns:
            str: Formatted date/time string (e.g., '2024-01-15 10:30:00')
        """
        import datetime
        try:
            dt = datetime.datetime.fromtimestamp(timestamp)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError):
            # Handle invalid timestamps
            return 'Unknown'
    
    # Compatibility methods
    def samefile(self, other_path) -> bool:
        """Return whether other_path is the same or not as this file."""
        if isinstance(other_path, Path) and isinstance(other_path._impl, ArchivePathImpl):
            return self._uri == other_path._impl._uri
        return False
    
    def as_posix(self) -> str:
        """Return the string representation with forward slashes."""
        return self._uri


# --- UI-facing encrypted-archive helpers -------------------------------------
#
# Thin wrappers the app layer uses to gate reads of files inside a browsed,
# password-protected zip. They keep the app from reaching into ``_impl`` and the
# cache internals directly.


def get_member_archive_path(path) -> Optional[Path]:
    """The archive *file* Path backing ``path`` when ``path`` is an entry inside a
    browsed archive (an ``archive://`` URI), else None (an ordinary file)."""
    impl = getattr(path, '_impl', None)
    if isinstance(impl, ArchivePathImpl):
        return impl._archive_path
    return None


def archive_password_state(path) -> str:
    """Password gate state for a Path that may be a member of a browsed archive:

    - ``'ok'``   — not an archive entry, not a zip, unencrypted, or a password is
                   already known: reading can proceed.
    - ``'need'`` — an encrypted ZipCrypto entry with no password yet: prompt.
    - ``'aes'``  — encryption XeFM cannot decrypt (WinZip AES).

    Ordinary filesystem paths always return ``'ok'`` cheaply (no archive is
    opened), so callers can route every read through this gate."""
    archive_path = get_member_archive_path(path)
    if archive_path is None:
        return 'ok'
    try:
        handler = get_archive_cache().get_handler(archive_path)
    except Exception:
        # Can't classify (e.g. corrupt archive) — let the normal read path report.
        return 'ok'
    if not isinstance(handler, ZipHandler):
        return 'ok'  # only zip supports password-protected extraction here
    try:
        status = handler.encryption_status()
    except Exception:
        return 'ok'
    if status == 'aes':
        return 'aes'
    if status == 'zipcrypto' and get_archive_password(archive_path) is None:
        return 'need'
    return 'ok'


def try_archive_password(path, password: str) -> bool:
    """Verify ``password`` against the archive backing ``path`` and, on success,
    remember it for the session. Returns True when the password is correct.

    ``password`` is encoded UTF-8 (zip passwords are bytes); most passwords are
    ASCII, for which this is exact."""
    archive_path = get_member_archive_path(path)
    if archive_path is None:
        return False
    try:
        handler = get_archive_cache().get_handler(archive_path)
    except Exception:
        return False
    if not isinstance(handler, ZipHandler):
        return False
    pwd = password.encode('utf-8')
    try:
        if handler.verify_password(pwd):
            set_archive_password(archive_path, pwd)
            return True
    except Exception:
        return False
    return False


def zip_encryption_status_path(path: str) -> str:
    """Classify a local ``.zip`` file by filesystem path — ``'none'``,
    ``'zipcrypto'``, or ``'aes'`` (see :func:`zip_encryption_status`). Returns
    ``'none'`` if the file can't be opened or classified."""
    try:
        with zipfile.ZipFile(path) as zf:
            return zip_encryption_status(zf)
    except Exception:
        return 'none'

