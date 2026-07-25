"""
SSH/SFTP Caching System for XeFM

This module provides caching for SSH/SFTP operations to improve performance
by reducing redundant network calls for directory listings and file metadata.
"""

import hashlib
import json
import threading
import time
from typing import Any, Dict, Optional
from xefm.log_manager import getLogger


class SSHCache:
    """
    Caching system for SSH/SFTP operations to improve response times.
    
    Features:
    - Configurable cache TTL (default 30 seconds for data, 300 seconds for errors)
    - Thread-safe operations
    - Partial cache invalidation
    - LRU-style cache management
    - Per-hostname caching
    - Negative caching (caches errors to avoid repeated failed operations)
    
    Cached operations:
    - list_directory: Directory listings
    - stat: File/directory metadata
    
    Error caching:
    - Errors are cached with a longer TTL (5 minutes) than successful results (30 seconds)
    - This prevents repeated SFTP calls for operations that will consistently fail
    - Examples: Permission denied, path not found
    """
    
    def __init__(self, default_ttl: int = 30, max_entries: int = 1000, error_ttl: int = 300):
        """
        Initialize SSH cache.
        
        Args:
            default_ttl: Default time-to-live in seconds for successful results (default: 30)
            max_entries: Maximum number of cache entries (default: 1000)
            error_ttl: Time-to-live in seconds for cached errors (default: 300 = 5 minutes)
        """
        self.default_ttl = default_ttl
        self.error_ttl = error_ttl
        self.max_entries = max_entries
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.logger = getLogger("SSHCache")
    
    def _generate_cache_key(self, operation: str, hostname: str, path: str = "", **kwargs) -> str:
        """
        Generate a unique cache key for the operation and parameters.
        
        Args:
            operation: Operation name (e.g., 'list_directory', 'stat')
            hostname: Remote hostname
            path: Remote path
            **kwargs: Additional parameters
            
        Returns:
            MD5 hash of the parameters as cache key
        """
        # Create a deterministic key from operation parameters
        params = {
            'operation': operation,
            'hostname': hostname,
            'path': path,
            **kwargs
        }
        # Sort parameters for consistent key generation
        param_str = json.dumps(params, sort_keys=True)
        return hashlib.md5(param_str.encode()).hexdigest()
    
    def get(self, operation: str, hostname: str, path: str = "", **kwargs) -> Optional[Any]:
        """
        Get cached result if available and not expired.
        
        Args:
            operation: Operation name
            hostname: Remote hostname
            path: Remote path
            **kwargs: Additional parameters
            
        Returns:
            Cached data if available and not expired, None otherwise
            
        Raises:
            Cached exception if an error was cached
        """
        cache_key = self._generate_cache_key(operation, hostname, path, **kwargs)
        
        with self._lock:
            if cache_key not in self._cache:
                return None
            
            entry = self._cache[cache_key]
            current_time = time.time()
            
            # Check if entry has expired
            if current_time - entry['timestamp'] > entry['ttl']:
                del self._cache[cache_key]
                self.logger.debug(f"Cache expired for {operation} on {hostname}:{path}")
                return None
            
            # Update access time for LRU behavior
            entry['last_access'] = current_time
            
            # If this is a cached error, re-raise it
            if entry.get('error'):
                self.logger.debug(f"Cache hit (error) for {operation} on {hostname}:{path}")
                raise entry['error']
            
            # Otherwise return cached data
            self.logger.debug(f"Cache hit for {operation} on {hostname}:{path}")
            return entry['data']
    
    def put(self, operation: str, hostname: str, path: str = "", data: Any = None, 
            ttl: Optional[int] = None, error: Optional[Exception] = None, **kwargs):
        """
        Store result in cache with optional custom TTL.
        
        Args:
            operation: Operation name
            hostname: Remote hostname
            path: Remote path
            data: Data to cache (None if caching an error)
            ttl: Custom TTL in seconds (uses default_ttl for data, error_ttl for errors if None)
            error: Exception to cache (for negative caching)
            **kwargs: Additional parameters
        """
        cache_key = self._generate_cache_key(operation, hostname, path, **kwargs)
        current_time = time.time()
        
        with self._lock:
            # Enforce max entries limit using LRU eviction
            if len(self._cache) >= self.max_entries and cache_key not in self._cache:
                self._evict_lru()
            
            # Use error_ttl for errors, default_ttl for successful results
            if ttl is None:
                ttl = self.error_ttl if error else self.default_ttl
            
            self._cache[cache_key] = {
                'data': data,
                'error': error,  # Store error for negative caching
                'timestamp': current_time,
                'last_access': current_time,
                'ttl': ttl,
                'hostname': hostname,
                'path': path,
                'operation': operation
            }
            if error:
                self.logger.debug(f"Cached error for {operation} on {hostname}:{path}: {type(error).__name__} (TTL: {ttl}s)")
            else:
                self.logger.debug(f"Cached {operation} for {hostname}:{path} (TTL: {ttl}s)")
    
    def invalidate_hostname(self, hostname: str):
        """
        Invalidate all cache entries for a specific hostname.
        
        Args:
            hostname: Remote hostname to invalidate
        """
        with self._lock:
            keys_to_remove = []
            for cache_key, entry in self._cache.items():
                if entry['hostname'] == hostname:
                    keys_to_remove.append(cache_key)
            
            for key in keys_to_remove:
                del self._cache[key]
            
            if keys_to_remove:
                self.logger.debug(f"Invalidated {len(keys_to_remove)} cache entries for {hostname}")
    
    def invalidate_path(self, hostname: str, path: str):
        """
        Invalidate cache entries for a specific path and its parent directories.
        
        This is called when a file/directory is modified, created, or deleted.
        
        Args:
            hostname: Remote hostname
            path: Remote path that was modified
        """
        with self._lock:
            keys_to_remove = []
            
            # Normalize path
            import posixpath
            normalized_path = posixpath.normpath(path)
            
            for cache_key, entry in self._cache.items():
                if entry['hostname'] == hostname:
                    entry_path = entry['path']
                    
                    # Invalidate exact path matches
                    if entry_path == normalized_path:
                        keys_to_remove.append(cache_key)
                    
                    # Invalidate parent directory listings
                    # If we modified /home/user/file.txt, invalidate /home/user listing
                    elif entry['operation'] == 'list_directory':
                        parent_dir = posixpath.dirname(normalized_path)
                        if entry_path == parent_dir:
                            keys_to_remove.append(cache_key)
                    
                    # Invalidate child paths if we're modifying a directory
                    # If we modified /home/user, invalidate /home/user/file.txt
                    elif entry_path.startswith(normalized_path.rstrip('/') + '/'):
                        keys_to_remove.append(cache_key)
            
            for key in keys_to_remove:
                del self._cache[key]
            
            if keys_to_remove:
                self.logger.debug(f"Invalidated {len(keys_to_remove)} cache entries for {hostname}:{path}")
    
    def invalidate_directory(self, hostname: str, directory: str):
        """
        Invalidate cache entries for a directory and all its contents.
        
        Args:
            hostname: Remote hostname
            directory: Remote directory path
        """
        with self._lock:
            keys_to_remove = []
            
            # Normalize directory path
            import posixpath
            normalized_dir = posixpath.normpath(directory)
            
            for cache_key, entry in self._cache.items():
                if entry['hostname'] == hostname:
                    entry_path = entry['path']
                    
                    # Invalidate the directory itself
                    if entry_path == normalized_dir:
                        keys_to_remove.append(cache_key)
                    
                    # Invalidate all paths under this directory
                    elif entry_path.startswith(normalized_dir.rstrip('/') + '/'):
                        keys_to_remove.append(cache_key)
            
            for key in keys_to_remove:
                del self._cache[key]
            
            if keys_to_remove:
                self.logger.debug(f"Invalidated {len(keys_to_remove)} cache entries for directory {hostname}:{directory}")
    
    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            if count > 0:
                self.logger.debug(f"Cleared {count} cache entries")
    
    def _evict_lru(self):
        """Evict the least recently used cache entry."""
        if not self._cache:
            return
        
        # Find the entry with the oldest last_access time
        oldest_key = min(self._cache.keys(), 
                        key=lambda k: self._cache[k]['last_access'])
        entry = self._cache[oldest_key]
        del self._cache[oldest_key]
        self.logger.debug(f"Evicted LRU cache entry for {entry['hostname']}:{entry['path']}")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.
        
        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            current_time = time.time()
            expired_count = sum(1 for entry in self._cache.values() 
                              if current_time - entry['timestamp'] > entry['ttl'])
            
            # Count entries by operation type
            operation_counts = {}
            for entry in self._cache.values():
                op = entry['operation']
                operation_counts[op] = operation_counts.get(op, 0) + 1
            
            return {
                'total_entries': len(self._cache),
                'expired_entries': expired_count,
                'max_entries': self.max_entries,
                'default_ttl': self.default_ttl,
                'error_ttl': self.error_ttl,
                'operation_counts': operation_counts
            }


# Global SSH cache instance
_ssh_cache = None


def get_ssh_cache() -> SSHCache:
    """
    Get or create the global SSH cache instance.
    
    Returns:
        Global SSHCache instance
    """
    global _ssh_cache
    if _ssh_cache is None:
        # Get TTL from configuration
        try:
            from xefm.config import get_config
            config = get_config()
            ttl = config.SSH_CACHE_TTL
            error_ttl = config.SSH_CACHE_ERROR_TTL
        except (ImportError, Exception):
            ttl = 30  # Fallback to default
            error_ttl = 300  # Fallback to 5 minutes for errors
        
        _ssh_cache = SSHCache(default_ttl=ttl, error_ttl=error_ttl)
    
    return _ssh_cache
