#!/usr/bin/env python3
"""
XeFM State Manager - Persistent Application State Management

Manages persistent application state using SQLite database.
Handles multiple XeFM instances safely with proper locking and error handling.
"""

import sqlite3
import json
import time
import threading
import os
import socket
from xefm.path import Path
from contextlib import contextmanager
from typing import Any, Dict, Optional, List
from xefm.log_manager import getLogger


class StateManager:
    """
    Manages persistent application state using SQLite database.
    
    Features:
    - Thread-safe operations with proper locking
    - Multiple instance support with retry logic
    - Automatic database creation and migration
    - JSON serialization for complex data types
    - Graceful error handling and fallback behavior
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the state manager.
        
        Args:
            db_path: Optional custom database path. Defaults to ~/.xefm/state.db
        """
        self.logger = getLogger("State")
        
        if db_path is None:
            self.db_path = Path.home() / '.xefm' / 'state.db'
        else:
            self.db_path = Path(db_path)
        
        # Ensure the directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Thread lock for database operations
        self._lock = threading.RLock()
        
        # Connection settings for better concurrency
        self._connection_timeout = 30.0  # 30 seconds
        self._retry_attempts = 3
        self._retry_delay = 0.1  # 100ms
        
        # Initialize database
        self._initialize_database()
    
    def _initialize_database(self):
        """Initialize the database with required tables."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Create state table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS app_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        instance_id TEXT
                    )
                ''')
                
                # Create session table for tracking active instances
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sessions (
                        instance_id TEXT PRIMARY KEY,
                        pid INTEGER NOT NULL,
                        started_at REAL NOT NULL,
                        last_seen REAL NOT NULL,
                        hostname TEXT
                    )
                ''')
                
                # Create index for better performance
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_state_updated 
                    ON app_state(updated_at)
                ''')
                
                conn.commit()
                
        except Exception as e:
            self.logger.warning(f"Could not initialize state database: {e}")
    
    @contextmanager
    def _get_connection(self):
        """
        Get a database connection with proper error handling and retry logic.
        
        Yields:
            sqlite3.Connection: Database connection
        """
        conn = None
        for attempt in range(self._retry_attempts):
            try:
                conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=self._connection_timeout,
                    isolation_level=None  # Autocommit mode
                )
                
                # Enable WAL mode for better concurrency
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA synchronous=NORMAL')
                conn.execute('PRAGMA temp_store=MEMORY')
                conn.execute('PRAGMA mmap_size=268435456')  # 256MB
                
                yield conn
                return
                
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower() and attempt < self._retry_attempts - 1:
                    time.sleep(self._retry_delay * (2 ** attempt))  # Exponential backoff
                    continue
                else:
                    raise
            except Exception as e:
                raise
            finally:
                if conn:
                    conn.close()
    
    def _serialize_value(self, value: Any) -> str:
        """
        Serialize a value to JSON string.
        
        Args:
            value: Value to serialize
            
        Returns:
            str: JSON string representation
        """
        try:
            # First try with default=str
            return json.dumps(value, default=str, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            # If that fails, try without default (will fail for non-serializable types)
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                raise ValueError(f"Cannot serialize value: {e}")
    
    def _deserialize_value(self, json_str: str) -> Any:
        """
        Deserialize a JSON string to Python value.
        
        Args:
            json_str: JSON string to deserialize
            
        Returns:
            Any: Deserialized Python value
        """
        try:
            return json.loads(json_str)
        except Exception as e:
            raise ValueError(f"Cannot deserialize value: {e}")
    
    def set_state(self, key: str, value: Any, instance_id: Optional[str] = None) -> bool:
        """
        Set a state value.
        
        Args:
            key: State key
            value: State value (will be JSON serialized)
            instance_id: Optional instance identifier
            
        Returns:
            bool: True if successful, False otherwise
        """
        with self._lock:
            try:
                serialized_value = self._serialize_value(value)
                current_time = time.time()
                
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR REPLACE INTO app_state 
                        (key, value, updated_at, instance_id)
                        VALUES (?, ?, ?, ?)
                    ''', (key, serialized_value, current_time, instance_id))
                
                return True
                
            except Exception as e:
                self.logger.warning(f"Could not set state '{key}': {e}")
                return False
    
    def get_state(self, key: str, default: Any = None) -> Any:
        """
        Get a state value.
        
        Args:
            key: State key
            default: Default value if key not found
            
        Returns:
            Any: State value or default
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT value FROM app_state WHERE key = ?
                    ''', (key,))
                    
                    row = cursor.fetchone()
                    if row:
                        return self._deserialize_value(row[0])
                    else:
                        return default
                        
            except Exception as e:
                self.logger.warning(f"Could not get state '{key}': {e}")
                return default
    
    def delete_state(self, key: str) -> bool:
        """
        Delete a state value.
        
        Args:
            key: State key to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM app_state WHERE key = ?', (key,))
                
                return True
                
            except Exception as e:
                self.logger.warning(f"Could not delete state '{key}': {e}")
                return False
    
    def get_all_states(self, prefix: Optional[str] = None) -> Dict[str, Any]:
        """
        Get all state values, optionally filtered by key prefix.
        
        Args:
            prefix: Optional key prefix filter
            
        Returns:
            Dict[str, Any]: Dictionary of all matching state values
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    if prefix:
                        cursor.execute('''
                            SELECT key, value FROM app_state 
                            WHERE key LIKE ? 
                            ORDER BY key
                        ''', (f"{prefix}%",))
                    else:
                        cursor.execute('''
                            SELECT key, value FROM app_state 
                            ORDER BY key
                        ''')
                    
                    result = {}
                    for key, value in cursor.fetchall():
                        try:
                            result[key] = self._deserialize_value(value)
                        except Exception as e:
                            self.logger.warning(f"Could not deserialize state '{key}': {e}")
                    
                    return result
                    
            except Exception as e:
                self.logger.warning(f"Could not get all states: {e}")
                return {}
    
    def clear_all_states(self, prefix: Optional[str] = None) -> bool:
        """
        Clear all state values, optionally filtered by key prefix.
        
        Args:
            prefix: Optional key prefix filter
            
        Returns:
            bool: True if successful, False otherwise
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    if prefix:
                        cursor.execute('DELETE FROM app_state WHERE key LIKE ?', (f"{prefix}%",))
                    else:
                        cursor.execute('DELETE FROM app_state')
                
                return True
                
            except Exception as e:
                self.logger.warning(f"Could not clear states: {e}")
                return False


class XeFMStateManager(StateManager):
    """
    XeFM-specific state manager with convenience methods for common state operations.
    """
    
    def __init__(self, instance_id: Optional[str] = None, db_path: Optional[Path] = None):
        """
        Initialize XeFM state manager.

        Args:
            instance_id: Optional instance identifier for this XeFM session
            db_path: Optional custom database path. Defaults to ~/.xefm/state.db.
                Mainly useful for tests that must not touch the real state store.
        """
        super().__init__(db_path=db_path)
        
        # Generate instance ID if not provided
        if instance_id is None:
            self.instance_id = f"xefm_{os.getpid()}_{socket.gethostname()}_{int(time.time())}"
        else:
            self.instance_id = instance_id
        
        # Register this session
        self._register_session()
    
    def _register_session(self):
        """Register this XeFM session in the sessions table."""
        try:
            current_time = time.time()
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO sessions 
                    (instance_id, pid, started_at, last_seen, hostname)
                    VALUES (?, ?, ?, ?, ?)
                ''', (self.instance_id, os.getpid(), current_time, current_time, socket.gethostname()))
                
        except Exception as e:
            self.logger.warning(f"Could not register session: {e}")
    
    def update_session_heartbeat(self):
        """Update the last_seen timestamp for this session."""
        try:
            current_time = time.time()
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE sessions SET last_seen = ? WHERE instance_id = ?
                ''', (current_time, self.instance_id))
                
        except Exception as e:
            self.logger.warning(f"Could not update session heartbeat: {e}")
    
    def cleanup_session(self):
        """Clean up this session from the sessions table."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM sessions WHERE instance_id = ?', (self.instance_id,))
                
        except Exception as e:
            self.logger.warning(f"Could not cleanup session: {e}")
    
    def get_active_sessions(self, timeout_seconds: float = 300.0) -> List[Dict[str, Any]]:
        """
        Get list of active XeFM sessions.
        
        Args:
            timeout_seconds: Session timeout in seconds (default 5 minutes)
            
        Returns:
            List[Dict[str, Any]]: List of active session information
        """
        try:
            current_time = time.time()
            cutoff_time = current_time - timeout_seconds
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT instance_id, pid, started_at, last_seen, hostname
                    FROM sessions 
                    WHERE last_seen > ?
                    ORDER BY last_seen DESC
                ''', (cutoff_time,))
                
                sessions = []
                for row in cursor.fetchall():
                    sessions.append({
                        'instance_id': row[0],
                        'pid': row[1],
                        'started_at': row[2],
                        'last_seen': row[3],
                        'hostname': row[4]
                    })
                
                return sessions
                
        except Exception as e:
            self.logger.warning(f"Could not get active sessions: {e}")
            return []
    
    def cleanup_stale_sessions(self, timeout_seconds: float = 300.0):
        """
        Clean up stale sessions from the database.
        
        Args:
            timeout_seconds: Session timeout in seconds (default 5 minutes)
        """
        try:
            current_time = time.time()
            cutoff_time = current_time - timeout_seconds
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM sessions WHERE last_seen <= ?', (cutoff_time,))
                
        except Exception as e:
            self.logger.warning(f"Could not cleanup stale sessions: {e}")
    
    # XeFM-specific convenience methods
    
    def save_pane_state(self, pane_name: str, pane_data: Dict[str, Any]) -> bool:
        """
        Save pane state (directory, selection, scroll position, etc.).
        
        Args:
            pane_name: Name of the pane ('left' or 'right')
            pane_data: Pane data dictionary
            
        Returns:
            bool: True if successful
        """
        # Extract serializable state
        state = {
            'path': str(pane_data.get('path', '')),
            'selected_index': pane_data.get('focused_index', 0),
            'scroll_offset': pane_data.get('scroll_offset', 0),
            'sort_mode': pane_data.get('sort_mode', 'name'),
            'sort_reverse': pane_data.get('sort_reverse', False),
            'filter_pattern': pane_data.get('filter_pattern', ''),
            'selected_files': list(pane_data.get('selected_files', set()))
        }
        
        return self.set_state(f"pane.{pane_name}", state, self.instance_id)
    
    def load_pane_state(self, pane_name: str) -> Optional[Dict[str, Any]]:
        """
        Load pane state.
        
        Args:
            pane_name: Name of the pane ('left' or 'right')
            
        Returns:
            Optional[Dict[str, Any]]: Pane state or None if not found
        """
        return self.get_state(f"pane.{pane_name}")
    
    def save_window_layout(self, left_pane_ratio: float, log_height_ratio: float,
                           log_height_default: Optional[float] = None) -> bool:
        """
        Save window layout settings.

        Args:
            left_pane_ratio: Left pane width ratio
            log_height_ratio: Log pane height ratio
            log_height_default: The configured default log height at save time,
                so the next launch can tell an untouched log_height_ratio (keep
                following the config) from one the user dragged (#316)

        Returns:
            bool: True if successful
        """
        layout = {
            'left_pane_ratio': left_pane_ratio,
            'log_height_ratio': log_height_ratio
        }
        if log_height_default is not None:
            layout['log_height_default'] = log_height_default

        return self.set_state("window.layout", layout, self.instance_id)
    
    def load_window_layout(self) -> Optional[Dict[str, float]]:
        """
        Load window layout settings.
        
        Returns:
            Optional[Dict[str, float]]: Layout settings or None if not found
        """
        return self.get_state("window.layout")
    
    def save_recent_directories(self, directories: List[str], max_count: int = 50) -> bool:
        """
        Save recent directories list.
        
        Args:
            directories: List of recent directory paths
            max_count: Maximum number of directories to keep
            
        Returns:
            bool: True if successful
        """
        # Limit the list size
        recent_dirs = directories[:max_count]
        
        return self.set_state("recent.directories", recent_dirs, self.instance_id)
    
    def load_recent_directories(self) -> List[str]:
        """
        Load recent directories list.
        
        Returns:
            List[str]: List of recent directory paths
        """
        return self.get_state("recent.directories", [])
    
    def add_recent_directory(self, directory: str, max_count: int = 50) -> bool:
        """
        Add a directory to the recent directories list.
        
        Args:
            directory: Directory path to add
            max_count: Maximum number of directories to keep
            
        Returns:
            bool: True if successful
        """
        recent_dirs = self.load_recent_directories()
        
        # Remove if already exists
        if directory in recent_dirs:
            recent_dirs.remove(directory)
        
        # Add to front
        recent_dirs.insert(0, directory)
        
        # Limit size
        recent_dirs = recent_dirs[:max_count]
        
        return self.save_recent_directories(recent_dirs, max_count)
    
    def save_search_history(self, search_terms: List[str], max_count: int = 100) -> bool:
        """
        Save search history.
        
        Args:
            search_terms: List of search terms
            max_count: Maximum number of terms to keep
            
        Returns:
            bool: True if successful
        """
        # Limit the list size
        history = search_terms[:max_count]
        
        return self.set_state("search.history", history, self.instance_id)
    
    def load_search_history(self) -> List[str]:
        """
        Load search history.
        
        Returns:
            List[str]: List of search terms
        """
        return self.get_state("search.history", [])
    
    def add_search_term(self, term: str, max_count: int = 100) -> bool:
        """
        Add a search term to history.
        
        Args:
            term: Search term to add
            max_count: Maximum number of terms to keep
            
        Returns:
            bool: True if successful
        """
        if not term.strip():
            return False
        
        history = self.load_search_history()
        
        # Remove if already exists
        if term in history:
            history.remove(term)
        
        # Add to front
        history.insert(0, term)
        
        # Limit size
        history = history[:max_count]
        
        return self.save_search_history(history, max_count)
    
    def save_pane_cursor_position(self, pane_name: str, directory_path: str, filename: str, max_entries: Optional[int] = None) -> bool:
        """
        Save cursor position for a specific pane and directory path.
        
        Args:
            pane_name: Name of the pane ('left' or 'right')
            directory_path: Directory path
            filename: Filename where cursor was positioned
            max_entries: Maximum number of entries to keep (uses config if None)
            
        Returns:
            bool: True if successful
        """
        try:
            # Use pane-specific key
            state_key = f"path_history_{pane_name}"
            
            # Get current history for this pane (list of [timestamp, path, filename])
            history = self.get_state(state_key, [])
            
            # Ensure it's a list (for backward compatibility with old dict format)
            if isinstance(history, dict):
                # Convert old dict format to new list format
                history = [[time.time(), path, fname] for path, fname in history.items()]
            
            # Remove any existing entry for this directory path
            history = [entry for entry in history if entry[1] != directory_path]
            
            # Add new entry at the end (most recent)
            current_time = time.time()
            history.append([current_time, directory_path, filename])
            
            # Determine maximum entries from config or parameter
            if max_entries is None:
                # Try to get from config, default to 100
                try:
                    from xefm.config import get_config
                    config = get_config()
                    max_entries = config.MAX_HISTORY_ENTRIES
                except ImportError as e:
                    self.logger.warning(f"Could not import config module: {e}")
                    max_entries = 100
                except Exception as e:
                    self.logger.warning(f"Could not get config for history limit: {e}")
                    max_entries = 100
            
            # Limit the size of the history (keep most recent entries)
            if len(history) > max_entries:
                history = history[-max_entries:]
            
            return self.set_state(state_key, history, self.instance_id)
            
        except Exception as e:
            self.logger.warning(f"Could not save position for {pane_name} pane: {e}")
            return False
    
    def load_pane_cursor_position(self, pane_name: str, directory_path: str) -> Optional[str]:
        """
        Load cursor position for a specific pane and directory path.
        
        Args:
            pane_name: Name of the pane ('left' or 'right')
            directory_path: Directory path
            
        Returns:
            Optional[str]: Filename where cursor was positioned, or None if not found
        """
        try:
            # Use pane-specific key
            state_key = f"path_history_{pane_name}"
            history = self.get_state(state_key, [])
            
            # Handle backward compatibility with old dict format
            if isinstance(history, dict):
                return history.get(directory_path)
            
            # Search through the list for the directory path
            for entry in history:
                if len(entry) >= 3 and entry[1] == directory_path:
                    return entry[2]  # Return filename
            
            return None
            
        except Exception as e:
            self.logger.warning(f"Could not load position for {pane_name} pane: {e}")
            return None
    
    def get_pane_cursor_positions(self, pane_name: str) -> Dict[str, str]:
        """
        Get all saved cursor positions for a specific pane as a dictionary.
        
        Args:
            pane_name: Name of the pane ('left' or 'right')
            
        Returns:
            Dict[str, str]: Dictionary mapping directory paths to filenames
        """
        try:
            # Use pane-specific key
            state_key = f"path_history_{pane_name}"
            history = self.get_state(state_key, [])
            
            # Handle backward compatibility with old dict format
            if isinstance(history, dict):
                return history
            
            # Convert list format to dictionary
            result = {}
            for entry in history:
                if len(entry) >= 3:
                    result[entry[1]] = entry[2]  # path -> filename
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Could not load positions for {pane_name} pane: {e}")
            return {}
    
    def get_ordered_pane_history(self, pane_name: str) -> List[Dict[str, Any]]:
        """
        Get history for a specific pane in chronological order (oldest to newest).
        
        Args:
            pane_name: Name of the pane ('left' or 'right')
            
        Returns:
            List[Dict[str, Any]]: List of history entries with timestamp, path, and filename
        """
        try:
            # Use pane-specific key
            state_key = f"path_history_{pane_name}"
            history = self.get_state(state_key, [])
            
            # Handle backward compatibility with old dict format
            if isinstance(history, dict):
                # Convert to list format with current timestamp
                current_time = time.time()
                return [
                    {
                        'timestamp': current_time,
                        'path': path,
                        'filename': filename
                    }
                    for path, filename in history.items()
                ]
            
            # Convert list format to structured format
            result = []
            for entry in history:
                if len(entry) >= 3:
                    result.append({
                        'timestamp': entry[0],
                        'path': entry[1],
                        'filename': entry[2]
                    })
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Could not load history for {pane_name} pane: {e}")
            return []
    
    def clear_pane_history(self, pane_name: str) -> bool:
        """
        Clear all saved positions for a specific pane.
        
        Args:
            pane_name: Name of the pane ('left' or 'right')
            
        Returns:
            bool: True if successful
        """
        try:
            # Use pane-specific key
            state_key = f"path_history_{pane_name}"
            return self.set_state(state_key, [], self.instance_id)
        except Exception as e:
            self.logger.warning(f"Could not clear history for {pane_name} pane: {e}")
            return False
    
    def cleanup_non_existing_directories(self) -> bool:
        """
        Remove cursor history entries for directories that no longer exist.
        
        This method checks all saved cursor positions and removes entries
        for directories that no longer exist on the filesystem.
        For performance reasons, remote storage paths (S3, etc.) are skipped
        during existence checks to avoid slow network operations.
        
        Returns:
            bool: True if cleanup was successful
        """
        try:
            from xefm.path import Path
            
            success = True
            cleaned_count = 0
            skipped_remote_count = 0
            
            # Clean up both left and right pane histories
            for pane_name in ['left', 'right']:
                try:
                    # Get current history for this pane
                    state_key = f"path_history_{pane_name}"
                    history = self.get_state(state_key, [])
                    
                    if not history:
                        continue
                    
                    # Handle backward compatibility with old dict format
                    if isinstance(history, dict):
                        # Convert to list format and filter
                        filtered_entries = []
                        for path, filename in history.items():
                            path_obj = Path(path)
                            # Skip existence check for remote paths to improve performance
                            if path_obj.is_remote():
                                filtered_entries.append([time.time(), path, filename])
                                skipped_remote_count += 1
                            elif path_obj.exists():
                                filtered_entries.append([time.time(), path, filename])
                            else:
                                cleaned_count += 1
                        history = filtered_entries
                    else:
                        # Filter list format
                        original_count = len(history)
                        filtered_history = []
                        for entry in history:
                            if len(entry) >= 3:
                                path_obj = Path(entry[1])
                                # Skip existence check for remote paths to improve performance
                                if path_obj.is_remote():
                                    filtered_history.append(entry)
                                    skipped_remote_count += 1
                                elif path_obj.exists():
                                    filtered_history.append(entry)
                                else:
                                    cleaned_count += 1
                        history = filtered_history
                    
                    # Save the cleaned history back
                    if not self.set_state(state_key, history, self.instance_id):
                        success = False
                        
                except Exception as e:
                    self.logger.warning(f"Could not clean history for {pane_name} pane: {e}")
                    success = False
            
            if cleaned_count > 0:
                self.logger.info(f"Cleaned up {cleaned_count} non-existing directory entries from cursor history")
            if skipped_remote_count > 0:
                self.logger.info(f"Skipped existence check for {skipped_remote_count} remote storage entries")
            
            return success
            
        except Exception as e:
            self.logger.warning(f"Could not cleanup non-existing directories: {e}")
            return False


# Global state manager instance
_state_manager = None


def get_state_manager() -> XeFMStateManager:
    """
    Get the global XeFM state manager instance.
    
    Returns:
        XeFMStateManager: Global state manager instance
    """
    global _state_manager
    if _state_manager is None:
        _state_manager = XeFMStateManager()
    return _state_manager


def cleanup_state_manager():
    """Clean up the global state manager."""
    global _state_manager
    if _state_manager is not None:
        _state_manager.cleanup_session()
        _state_manager = None