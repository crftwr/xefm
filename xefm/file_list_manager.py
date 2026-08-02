#!/usr/bin/env python3
"""
XeFM File List Manager - Manages file lists, sorting, filtering, and selection
"""

import os
import stat
import fnmatch
from xefm.path import Path, attrs_via_path
from datetime import datetime
from xefm.str_format import format_size


class FileListManager:
    """Manages file lists, sorting, filtering, and selection.
    
    This class handles all file list management operations for file panes,
    including refreshing directory contents, sorting entries, applying filters,
    and managing file selection state.
    """
    
    def __init__(self, config):
        self.config = config
        self.show_hidden = config.SHOW_HIDDEN_FILES
        self.log_manager = None  # Will be set by FileManager if available
        # Use module-level getLogger - no need to check if log_manager exists
        from xefm.log_manager import getLogger
        self.logger = getLogger("FileList")
    
    def refresh_files(self, pane_data):
        """Refresh a pane's file list synchronously: read the directory, apply
        the filter, sort, and reconcile the cursor/selection.

        This is ``compute_listing`` (the blocking I/O) followed by
        ``apply_listing`` (the pane mutation). The two are split so a caller can
        run the I/O on a worker thread and apply the result on the UI thread
        without freezing on a slow remote directory; ``refresh_files`` keeps the
        simple synchronous contract for local paths and existing callers.

        For a **virtual pane** (a search-results feed, ``pane_data['virtual']``
        set) there is no directory to read: the listing is rebuilt from the
        explicit result set — surviving paths are re-stat'd (vanished ones dropped),
        then filtered/sorted in memory. This is the single choke point that makes
        sort, filter, and post-op reconciliation Just Work on a virtual pane.

        Args:
            pane_data: Dictionary containing pane state (``path``,
                ``filter_pattern``, ``sort_mode``, ``sort_reverse``, cursor,
                selection).

        Updates ``pane_data['files']`` and ``pane_data['file_info']``, and
        reconciles ``focused_index`` / ``selected_files``.
        """
        virtual = pane_data.get('virtual')
        if virtual:
            # Re-stat the found set: drop entries that have vanished (moved/
            # deleted by a prior op) and prune their metadata in step.
            survivors = [p for p in virtual['results'] if self._path_exists(p)]
            virtual['results'] = survivors
            keys = {str(p) for p in survivors}
            virtual['meta'] = {k: v for k, v in virtual.get('meta', {}).items()
                               if k in keys}
            result = self.compute_listing_from_paths(
                survivors,
                filter_pattern=pane_data.get('filter_pattern'),
                sort_mode=pane_data['sort_mode'],
                sort_reverse=pane_data['sort_reverse'],
            )
            self.apply_listing(pane_data, result)
            return
        result = self.compute_listing(
            pane_data['path'],
            filter_pattern=pane_data.get('filter_pattern'),
            sort_mode=pane_data['sort_mode'],
            sort_reverse=pane_data['sort_reverse'],
        )
        self.apply_listing(pane_data, result)

    @staticmethod
    def _path_exists(path):
        """Whether ``path`` still resolves — tolerant of a raised error (a broken
        remote handle counts as gone rather than crashing the re-stat)."""
        try:
            return path.exists()
        except Exception:
            return False

    def compute_listing(self, path, *, filter_pattern=None, sort_mode='name',
                        sort_reverse=False):
        """Read ``path`` and return its listing as a plain dict — **no pane
        mutation**, so this is safe to call on a worker thread.

        Does the blocking work (``iterdir`` + per-entry ``is_dir``/``stat`` for
        the sort and the display cache), honouring ``self.show_hidden`` and the
        optional ``filter_pattern``. Returns
        ``{"ok": bool, "files": [...], "file_info": {...}}``; on any error
        ``ok`` is False with empty lists (the error is logged, as before). The
        caller installs the result with :meth:`apply_listing`.
        """
        try:
            # Import archive exceptions for specific error handling
            from xefm.archive import (
                ArchiveError, ArchiveNavigationError, ArchiveCorruptedError,
                ArchivePermissionError
            )

            # Read the directory and every entry's attributes in one pass, so a
            # large directory on a network mount costs one bulk enumeration
            # rather than a round trip per file (see xefm.dir_scan).
            all_entries = path.listdir_attrs()

            # Filter hidden files if needed
            if not self.show_hidden:
                all_entries = [(entry, attrs) for entry, attrs in all_entries
                               if not entry.name.startswith('.')]

            return self._assemble_listing(
                all_entries, filter_pattern=filter_pattern,
                sort_mode=sort_mode, sort_reverse=sort_reverse)

        except ArchiveNavigationError as e:
            # Archive navigation error - path doesn't exist in archive
            user_msg = getattr(e, 'user_message', str(e))
            self.logger.error(f"Archive navigation error: {user_msg}")
            self.logger.error(f"Archive navigation error: {path}: {e}")
        except ArchiveCorruptedError as e:
            # Archive is corrupted
            user_msg = getattr(e, 'user_message', str(e))
            self.logger.error(f"Corrupted archive: {user_msg}")
            self.logger.error(f"Corrupted archive: {path}: {e}")
        except ArchivePermissionError as e:
            # Permission denied for archive
            user_msg = getattr(e, 'user_message', str(e))
            self.logger.error(f"Permission denied: {user_msg}")
            self.logger.error(f"Archive permission denied: {path}: {e}")
        except ArchiveError as e:
            # Generic archive error
            user_msg = getattr(e, 'user_message', str(e))
            self.logger.error(f"Archive error: {user_msg}")
            self.logger.error(f"Archive error: {path}: {e}")
        except PermissionError as e:
            self.logger.error(f"Permission denied accessing directory {path}: {e}")
        except FileNotFoundError as e:
            self.logger.error(f"Directory not found: {path}: {e}")
        except OSError as e:
            self.logger.error(f"System error reading directory {path}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error reading directory {path}: {e}")
        return {"ok": False, "files": [], "file_info": {}}

    def compute_listing_from_paths(self, paths, *, filter_pattern=None,
                                   sort_mode='name', sort_reverse=False):
        """Build a listing dict from an explicit list of ``Path`` objects — a
        virtual / search-results pane — instead of reading a directory. Applies
        the filename filter and the sort in memory and builds the display-info
        cache, mirroring :meth:`compute_listing`'s tail so :meth:`apply_listing`
        installs it unchanged. Always ``ok`` (there is no directory I/O to fail);
        a per-entry ``stat`` error is absorbed into the info cache as ``---``.

        Unlike :meth:`compute_listing` this does **not** apply the hidden-file
        filter: the search that produced ``paths`` already honoured
        ``show_hidden``, and a scattered result set has no single directory whose
        dotfiles to hide."""
        all_entries = [(p, attrs_via_path(p)) for p in paths]
        return self._assemble_listing(
            all_entries, filter_pattern=filter_pattern,
            sort_mode=sort_mode, sort_reverse=sort_reverse)

    def _assemble_listing(self, entries, *, filter_pattern=None,
                          sort_mode='name', sort_reverse=False):
        """Turn ``[(Path, attrs), …]`` into a listing dict: apply the filename
        filter, sort, and build the display cache — all from ``attrs``, with no
        filesystem access at all.

        This is the half of a listing that does not depend on the disk, split
        out so it can run twice: once behind :meth:`compute_listing`, and again
        on every later sort or filter change straight from the snapshot it
        returns in ``entries`` (see :meth:`recompute_listing`).
        """
        attrs = {str(p): a for p, a in entries}
        paths = [p for p, _ in entries]

        # Apply filename filter if active (only to files, not directories)
        if filter_pattern:
            pattern = filter_pattern.lower()
            paths = [p for p in paths
                     if attrs[str(p)]['is_dir']
                     or fnmatch.fnmatch(p.name.lower(), pattern)]

        files = self.sort_entries(paths, sort_mode, sort_reverse, attrs=attrs)
        return {"ok": True, "files": files,
                "file_info": self._build_file_info(files, attrs=attrs),
                "entries": entries}

    def recompute_listing(self, pane_data, *, filter_pattern=None,
                          sort_mode='name', sort_reverse=False):
        """Re-filter and re-sort a pane from the snapshot its last listing left
        behind — **no filesystem access**, so it costs microseconds where a
        re-read of the same directory on a NAS costs seconds.

        A sort or filter change needs no information the previous listing did
        not already collect: ``entries`` holds every entry with its
        ``is_dir``/``size``/``mtime``. Returns a listing dict for
        :meth:`apply_listing`, or ``None`` if the pane has no snapshot yet
        (nothing listed, or the listing failed) and the caller must re-list.

        The snapshot is taken *before* the filename filter, so widening or
        clearing a filter restores entries without re-reading. It is taken
        *after* the hidden-file filter, so toggling ``show_hidden`` does need a
        real re-list.
        """
        entries = pane_data.get('_listing_entries')
        if entries is None:
            return None
        return self._assemble_listing(
            entries, filter_pattern=filter_pattern,
            sort_mode=sort_mode, sort_reverse=sort_reverse)

    def _build_file_info(self, files, attrs=None):
        """Populate the per-entry display cache (size/date strings, is_dir) once
        at load time, so rendering never issues a ``stat``. Shared by the
        directory listing and the virtual (search-results) listing.

        ``attrs`` maps ``str(path)`` to the record the listing already collected
        (see :mod:`xefm.dir_scan`); an entry missing from it is read per file, so
        a caller that has no attributes still works.
        """
        attrs = attrs or {}
        file_info = {}
        for file_path in files:
            file_key = str(file_path)
            a = attrs.get(file_key) or attrs_via_path(file_path)
            try:
                if a['ok']:
                    size_str = "<DIR>" if a['is_dir'] else format_size(
                        a['size'], compact=True)
                    date_str = self._format_date(a['mtime'])
                else:
                    # Unreadable (typically a broken symlink): is_link stays
                    # true, describing the link rather than its missing target.
                    size_str = date_str = '---'
            except Exception:
                # One entry that will not format (an out-of-range timestamp, say)
                # shows as unknown rather than costing the whole listing.
                size_str = date_str = '---'
            file_info[file_key] = {
                'size_str': size_str,
                'date_str': date_str,
                'is_dir': a['is_dir'],
                'is_link': a['is_link'],
            }
        return file_info

    def apply_listing(self, pane_data, result):
        """Install a :meth:`compute_listing` result into ``pane_data`` and
        reconcile the cursor and selection — the pane-mutating tail of a refresh,
        run on the UI thread. On an error result (``ok`` False) the pane is
        emptied and the cursor reset, matching the old ``refresh_files`` error
        path (selection is left untouched)."""
        if not result.get("ok"):
            pane_data['files'] = []
            pane_data['focused_index'] = 0
            # Drop the snapshot: a failed listing must not leave a later sort
            # re-filtering entries from a directory we can no longer read.
            pane_data['_listing_entries'] = None
            return
        pane_data['files'] = result['files']
        pane_data['file_info'] = result['file_info']
        # Keep the pre-filter entry snapshot so a later sort or filter change
        # rebuilds from it instead of re-reading the directory (#183).
        pane_data['_listing_entries'] = result.get('entries')

        # Ensure focused index is valid
        if pane_data['files']:
            pane_data['focused_index'] = min(pane_data['focused_index'], len(pane_data['files']) - 1)
        else:
            pane_data['focused_index'] = 0

        # Clean up selected files - remove any that no longer exist
        current_file_paths = {str(f) for f in pane_data['files']}
        pane_data['selected_files'] = pane_data['selected_files'] & current_file_paths
    
    def _natural_sort_key(self, text):
        """
        Generate a natural sort key that handles numeric parts as numbers.
        
        Converts "Test10.txt" into ['test', 10, '.txt'] so it sorts numerically.
        
        Args:
            text: String to convert to natural sort key
            
        Returns:
            List of alternating strings and integers for natural sorting
        """
        import re
        
        def convert(part):
            """Convert numeric strings to integers, leave others as lowercase strings"""
            return int(part) if part.isdigit() else part.lower()
        
        # Split on digit sequences, keeping the digits
        parts = re.split(r'(\d+)', text)
        return [convert(part) for part in parts]
    
    def sort_entries(self, entries, sort_mode, reverse=False, attrs=None):
        """Sort file entries based on the specified mode

        Args:
            entries: List of Path objects to sort
            sort_mode: 'name', 'ext', 'size', or 'date'
            reverse: Whether to reverse the sort order
            attrs: Optional ``{str(path): record}`` from the listing that
                produced ``entries`` (see :mod:`xefm.dir_scan`). Every key the
                sort needs — is_dir, size, mtime — comes from here, so sorting
                issues no filesystem calls. Entries missing from it are read per
                file, so callers with no attributes still work.

        Returns:
            Sorted list with directories always first
        """
        attrs = dict(attrs) if attrs else {}
        for entry in entries:
            key = str(entry)
            if key not in attrs:
                attrs[key] = attrs_via_path(entry)

        def get_sort_key(entry):
            """Generate sort key for an entry, from the cached attributes"""
            a = attrs[str(entry)]
            if sort_mode == 'size':
                # Directories and unreadable entries sort as 0, as before.
                return a['size']
            elif sort_mode == 'date':
                return a['mtime']
            elif sort_mode == 'type':
                if a['is_dir']:
                    return ""  # Directories first
                else:
                    return entry.suffix.lower()
            elif sort_mode == 'ext':
                if a['is_dir']:
                    return ""  # Directories first (no extension)
                else:
                    # Use the same extension logic as rendering
                    filename = entry.name
                    dot_index = filename.rfind('.')
                    if dot_index <= 0:
                        return ""  # No extension
                    extension = filename[dot_index:]
                    # Check extension length limit (same as rendering)
                    max_ext_length = self.config.MAX_EXTENSION_LENGTH
                    if len(extension) > max_ext_length:
                        return ""  # Extension too long, treat as no extension
                    return extension.lower()
            else:  # name (default)
                return self._natural_sort_key(entry.name)

        # Separate directories and files using the cached attributes
        directories = [e for e in entries if attrs[str(e)]['is_dir']]
        files = [e for e in entries if not attrs[str(e)]['is_dir']]

        # Sort each group separately
        sorted_dirs = sorted(directories, key=get_sort_key, reverse=reverse)
        sorted_files = sorted(files, key=get_sort_key, reverse=reverse)
        
        # Always put directories first
        return sorted_dirs + sorted_files
    
    def get_sort_description(self, pane_data):
        """Get a human-readable description of the current sort mode, using the
        same key names the sort dialog and the menu show (Filename / Extension /
        Size / Timestamp)."""
        mode = pane_data['sort_mode']
        reverse = pane_data['sort_reverse']

        descriptions = {
            'name': 'Filename',
            'ext':  'Extension',
            'size': 'Size',
            'date': 'Timestamp',
            'type': 'Extension',  # legacy suffix sort (the pre-dialog menu)
        }

        description = descriptions.get(mode, 'Filename')
        if reverse:
            description += ' ↓'
        else:
            description += ' ↑'
        
        return description
    def _format_date(self, timestamp):
        """Format date/time based on configured format.
        
        Args:
            timestamp: Unix timestamp
            
        Returns:
            str: Formatted date/time string
        """
        from xefm.const import DATE_FORMAT_FULL, DATE_FORMAT_SHORT
        
        dt = datetime.fromtimestamp(timestamp)
        date_format = self.config.DATE_FORMAT
        
        if date_format == DATE_FORMAT_FULL:
            # YYYY-MM-DD HH:mm:ss
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        else:  # DATE_FORMAT_SHORT (default)
            # YY-MM-DD HH:mm
            return dt.strftime("%y-%m-%d %H:%M")
    
    def get_file_info(self, path, pane_data=None):
        """Get file information for display.
        
        This method first checks the file_info cache to avoid filesystem calls
        during rendering. If cache miss, falls back to stat() call.
        
        Args:
            path: Path object for the file
            pane_data: Optional pane data dictionary containing file_info cache
            
        Returns:
            Tuple of (size_str, date_str)
        """
        # Try cache first if pane_data provided
        if pane_data and 'file_info' in pane_data:
            file_key = str(path)
            if file_key in pane_data['file_info']:
                info = pane_data['file_info'][file_key]
                return info['size_str'], info['date_str']
        
        # Cache miss or no pane_data - fall back to stat()
        try:
            stat_info = path.stat()
            
            # Format size - display "<DIR>" for directories
            if path.is_dir():
                size_str = "<DIR>"
            else:
                size_str = format_size(stat_info.st_size, compact=True)
            
            # Format date based on configured format
            date_str = self._format_date(stat_info.st_mtime)
            
            return size_str, date_str
        except Exception:
            # Catch all exceptions including SSH errors, permission errors, etc.
            # Return placeholder values instead of propagating the error
            return "---", "---"
    
    def toggle_selection(self, pane_data, move_cursor=True, direction=1):
        """Toggle selection of current file/directory and optionally move cursor.
        
        This method toggles the selection state of the currently focused file
        and optionally moves the cursor to the next/previous file.
        
        Args:
            pane_data: Dictionary containing pane state
            move_cursor: If True, move cursor after toggling selection
            direction: Direction to move cursor (1 for down, -1 for up)
        
        Returns:
            Tuple of (success: bool, message: str)
        
        Updates:
            - pane_data['selected_files']: Set of selected file paths
            - pane_data['focused_index']: Current cursor position (if move_cursor=True)
        """
        if not pane_data['files']:
            return False, "No files to select"
            
        focused_file = pane_data['files'][pane_data['focused_index']]
        file_path_str = str(focused_file)
        
        if file_path_str in pane_data['selected_files']:
            pane_data['selected_files'].remove(file_path_str)
            message = f"Deselected: {focused_file.name}"
        else:
            pane_data['selected_files'].add(file_path_str)
            message = f"Selected: {focused_file.name}"
        
        # Move cursor if requested
        if move_cursor:
            if direction > 0 and pane_data['focused_index'] < len(pane_data['files']) - 1:
                pane_data['focused_index'] += 1
            elif direction < 0 and pane_data['focused_index'] > 0:
                pane_data['focused_index'] -= 1
        
        return True, message
    
    def toggle_all_files_selection(self, pane_data):
        """Toggle selection status of all files (not directories) in current pane"""
        if not pane_data['files']:
            return False, "No files to select in current directory"
        
        # Get all files (not directories) in current pane
        files_only = []
        for file_path in pane_data['files']:
            if not file_path.is_dir():
                files_only.append(file_path)
        
        if not files_only:
            return False, "No files to select in current directory"
        
        # Inverse selection status for each file
        files_only_str = {str(f) for f in files_only}
        selected_count = 0
        deselected_count = 0
        
        for file_str in files_only_str:
            if file_str in pane_data['selected_files']:
                # Currently selected, deselect it
                pane_data['selected_files'].discard(file_str)
                deselected_count += 1
            else:
                # Currently not selected, select it
                pane_data['selected_files'].add(file_str)
                selected_count += 1
        
        message = f"Inversed selection: {selected_count} selected, {deselected_count} deselected"
        return True, message
    
    def toggle_all_items_selection(self, pane_data):
        """Toggle selection status of all items (files and directories) in current pane"""
        if not pane_data['files']:
            return False, "No items to select in current directory"
        
        # Get all items
        all_items = pane_data['files']
        
        if not all_items:
            return False, "No items to select in current directory"
        
        # Inverse selection status for each item
        all_items_str = {str(f) for f in all_items}
        selected_count = 0
        deselected_count = 0
        
        for item_str in all_items_str:
            if item_str in pane_data['selected_files']:
                # Currently selected, deselect it
                pane_data['selected_files'].discard(item_str)
                deselected_count += 1
            else:
                # Currently not selected, select it
                pane_data['selected_files'].add(item_str)
                selected_count += 1
        
        message = f"Inversed selection: {selected_count} selected, {deselected_count} deselected"
        return True, message
    
    def find_matches(self, pane_data, pattern, match_all=False, return_indices_only=False):
        """Find all files matching the fnmatch patterns in current pane
        
        Args:
            pane_data: Pane data dictionary
            pattern: Search pattern (supports multiple patterns separated by spaces)
            match_all: If True, all patterns must match (AND logic). If False, any pattern can match (OR logic)
            return_indices_only: If True, return list of indices. If False, return list of (index, filename) tuples
            
        Returns:
            List of matches (either indices or (index, filename) tuples based on return_indices_only)
        """
        if not pattern or not pane_data['files']:
            return []
        
        matches = []
        
        # Split pattern by spaces to get individual patterns
        patterns = pattern.strip().split()
        if not patterns:
            return []
        
        # Convert all patterns to lowercase for case-insensitive matching
        # and wrap each pattern with wildcards to match "contains" behavior
        wrapped_patterns = []
        for p in patterns:
            p_lower = p.lower()
            # If pattern doesn't start with *, add it for "contains" matching
            if not p_lower.startswith('*'):
                p_lower = '*' + p_lower
            # If pattern doesn't end with *, add it for "contains" matching  
            if not p_lower.endswith('*'):
                p_lower = p_lower + '*'
            wrapped_patterns.append(p_lower)
        
        for i, file_path in enumerate(pane_data['files']):
            filename_lower = file_path.name.lower()
            
            if match_all:
                # Check if filename matches ALL patterns (AND logic)
                all_match = True
                for wrapped_pattern in wrapped_patterns:
                    if not fnmatch.fnmatch(filename_lower, wrapped_pattern):
                        all_match = False
                        break
                
                if all_match:
                    if return_indices_only:
                        matches.append(i)
                    else:
                        matches.append((i, file_path.name))
            else:
                # Check if filename matches ANY of the patterns (OR logic)
                match_found = False
                for wrapped_pattern in wrapped_patterns:
                    if fnmatch.fnmatch(filename_lower, wrapped_pattern):
                        match_found = True
                        break
                
                if match_found:
                    if return_indices_only:
                        matches.append(i)
                    else:
                        matches.append((i, file_path.name))
        
        return matches
    
    def set_filter(self, pane_data, pattern):
        """Set a pane's filename filter and reset the view state a filter change
        invalidates — **without** re-reading the directory.

        Split out of :meth:`apply_filter` for the same reason ``compute_listing``
        is split out of ``refresh_files``: a caller that re-lists on a worker
        thread still gets the pane-state half in one place, so "what a filter
        change resets" is defined once. See ``XeFMApp._apply_filter``.

        Args:
            pane_data: Dictionary containing pane state
            pattern: Filename pattern (e.g., "*.txt", "test*")
                    Empty string clears the filter
        """
        pane_data['filter_pattern'] = pattern

        # Reset selection and scroll when filter changes
        pane_data['focused_index'] = 0
        pane_data['scroll_offset'] = 0
        pane_data['selected_files'].clear()  # Clear selections when filter changes

    def apply_filter(self, pane_data, pattern):
        """Apply filename filter pattern to the specified pane, synchronously.

        This method sets the filter pattern and refreshes the file list to
        show only files matching the pattern. Directories are always shown.

        Args:
            pane_data: Dictionary containing pane state
            pattern: Filename pattern (e.g., "*.txt", "test*")
                    Empty string clears the filter

        Updates:
            - pane_data['filter_pattern']: Current filter pattern
            - pane_data['files']: Filtered file list (via refresh_files)
        """
        self.set_filter(pane_data, pattern)

        # Refresh files with new filter
        self.refresh_files(pane_data)

        return len(pane_data['files'])
    
    def clear_filter(self, pane_data):
        """Clear the filter for the specified pane"""
        if pane_data['filter_pattern']:
            pane_data['filter_pattern'] = ""
            pane_data['focused_index'] = 0
            pane_data['scroll_offset'] = 0
            self.refresh_files(pane_data)
            return True
        return False
    
    def toggle_hidden_files(self):
        """Toggle showing hidden files"""
        self.show_hidden = not self.show_hidden
        return self.show_hidden
