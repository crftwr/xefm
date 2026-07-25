"""
FileMonitorObserver - Monitors a single directory for filesystem changes.

This module wraps watchdog Observer and provides error handling and status
reporting for monitoring a single directory.
"""

import platform
import sys
from pathlib import Path
from typing import Callable, Optional
from xefm.log_manager import getLogger

try:
    from watchdog.observers import Observer
    from watchdog.observers.polling import PollingObserver
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    PollingObserver = None
    FileSystemEventHandler = None


if WATCHDOG_AVAILABLE:
    class XeFMFileSystemEventHandler(FileSystemEventHandler):
        """
        Handles filesystem events from watchdog.
        
        Filters events and forwards relevant changes to FileMonitorManager.
        Only processes events for immediate children of the watched directory,
        ignoring subdirectory events.
        """
        
        def __init__(self, callback: Callable, watched_path: str):
            """
            Initialize event handler.
            
            Args:
                callback: Function to call on events (event_type: str, filename: str) -> None
                watched_path: Directory being watched (for filtering subdirectory events)
            """
            super().__init__()
            self.callback = callback
            self.watched_path = Path(watched_path)
            self.logger = getLogger("FileMonitor")
        
        def _is_immediate_child(self, event_path: str) -> bool:
            """
            Check if the event path is an immediate child of the watched directory.
            
            Args:
                event_path: Path of the file/directory that triggered the event
                
            Returns:
                True if the path is an immediate child, False if it's in a subdirectory
            """
            event_path_obj = Path(event_path)
            
            # Get the parent directory of the event path
            parent = event_path_obj.parent
            
            # Check if the parent is exactly the watched directory
            return parent == self.watched_path
        
        def _get_filename(self, event_path: str) -> str:
            """
            Extract the filename from an event path.
            
            Args:
                event_path: Full path from the event
                
            Returns:
                Just the filename (last component of the path)
            """
            return Path(event_path).name
        
        def on_created(self, event):
            """
            Handle file/directory creation.
            
            Args:
                event: FileSystemEvent from watchdog
            """
            try:
                # Filter out subdirectory events first
                if not self._is_immediate_child(event.src_path):
                    return
                
                filename = self._get_filename(event.src_path)
                item_type = "Directory" if event.is_directory else "File"
                self.logger.debug(f"{item_type} created: {filename}")
                self.callback("created", filename)
            except Exception as e:
                self.logger.error(f"Error handling creation event: {e}")
        
        def on_deleted(self, event):
            """
            Handle file/directory deletion.
            
            Args:
                event: FileSystemEvent from watchdog
            """
            try:
                # Filter out subdirectory events first
                if not self._is_immediate_child(event.src_path):
                    return
                
                filename = self._get_filename(event.src_path)
                item_type = "Directory" if event.is_directory else "File"
                self.logger.debug(f"{item_type} deleted: {filename}")
                self.callback("deleted", filename)
            except Exception as e:
                self.logger.error(f"Error handling deletion event: {e}")
        
        def on_modified(self, event):
            """
            Handle file/directory modification.
            
            Args:
                event: FileSystemEvent from watchdog
            """
            try:
                event_path_obj = Path(event.src_path)
                
                # Special case: If the modified path IS the watched directory itself,
                # this indicates a change to its contents (child added/removed/modified).
                # This is how FSEvents reports directory content changes on macOS.
                # We should trigger a reload but not log a specific filename.
                if event_path_obj.resolve() == self.watched_path.resolve():
                    if event.is_directory:
                        self.logger.debug(f"Directory contents modified: {self.watched_path.name}")
                        self.callback("modified", "")
                        return
                
                # Filter out subdirectory events
                if not self._is_immediate_child(event.src_path):
                    return
                
                filename = self._get_filename(event.src_path)
                item_type = "Directory" if event.is_directory else "File"
                self.logger.debug(f"{item_type} modified: {filename}")
                self.callback("modified", filename)
            except Exception as e:
                self.logger.error(f"Error handling modification event: {e}")
        
        def on_moved(self, event):
            """
            Handle file/directory rename/move.
            
            Handles four cases:
            1. Move within watched directory (rename) - treat as modified
            2. Move into watched directory from outside - treat as creation
            3. Move out of watched directory - treat as deletion
            4. Move within subdirectory - ignore
            
            Args:
                event: FileSystemMovedEvent from watchdog
            """
            try:
                src_is_child = self._is_immediate_child(event.src_path)
                dest_is_child = self._is_immediate_child(event.dest_path)
                
                item_type = "Directory" if event.is_directory else "File"
                
                # Case 1: Move within watched directory (rename)
                if src_is_child and dest_is_child:
                    # This is a rename operation within the watched directory
                    # We could treat this as a delete + create, but a single "modified" is more efficient
                    src_filename = self._get_filename(event.src_path)
                    dest_filename = self._get_filename(event.dest_path)
                    self.logger.debug(f"{item_type} renamed: {src_filename} -> {dest_filename}")
                    # Trigger a reload to show both the deletion and creation
                    self.callback("modified", dest_filename)
                
                # Case 2: Move into watched directory from outside (move-in)
                elif not src_is_child and dest_is_child:
                    # File/directory moved into the watched directory - treat as creation
                    filename = self._get_filename(event.dest_path)
                    self.logger.debug(f"{item_type} moved in: {filename}")
                    self.callback("created", filename)
                
                # Case 3: Move out of watched directory (move-out)
                elif src_is_child and not dest_is_child:
                    # File/directory moved out of the watched directory - treat as deletion
                    filename = self._get_filename(event.src_path)
                    self.logger.debug(f"{item_type} moved out: {filename}")
                    self.callback("deleted", filename)
                
                # Case 4: Move within subdirectory - ignore
                # (both src_is_child and dest_is_child are False)
            except Exception as e:
                self.logger.error(f"Error handling move event: {e}")

else:
    # Dummy class when watchdog is not available
    class XeFMFileSystemEventHandler:
        """Dummy event handler when watchdog is not available."""
        def __init__(self, callback: Callable, watched_path: str):
            pass


class FileMonitorObserver:
    """
    Monitors a single directory for filesystem changes.
    
    Wraps watchdog Observer and provides error handling and status reporting.
    """
    
    def __init__(self, path: Path, event_callback: Callable, logger, force_polling: bool = False, polling_interval: float = 5.0):
        """
        Initialize observer for a directory.
        
        Args:
            path: Directory path to monitor
            event_callback: Function to call on events (event_type: str, filename: str) -> None
            logger: Logger instance
            force_polling: If True, use polling mode even if native monitoring is available
            polling_interval: Polling interval in seconds for fallback mode (default: 5.0)
        """
        self.path = path
        self.event_callback = event_callback
        self.logger = logger
        self.force_polling = force_polling
        self.polling_interval = polling_interval
        
        # Observer state
        self.observer = None
        self.monitoring_mode = "disabled"
        self._event_handler = None
        
        # Log initialization with monitoring mode (Requirement 12.1)
        mode = "polling" if force_polling else "native (will attempt, may fallback to polling)"
        self.logger.debug(f"FileMonitorObserver initialized for {path} - monitoring mode: {mode}, polling interval: {polling_interval}s")
    
    def _detect_platform_and_api(self) -> tuple[str, str]:
        """
        Detect the current platform and available native monitoring API.
        
        Returns:
            Tuple of (platform_name, api_name) where:
            - platform_name: "Linux", "macOS", "Windows", or "Unknown"
            - api_name: "inotify", "FSEvents", "ReadDirectoryChangesW", or "unavailable"
        """
        system = platform.system()
        
        if system == "Linux":
            # Check if inotify is available
            # On Linux, watchdog uses inotify which is available in kernel 2.6.13+
            # We can check if the inotify module can be imported
            try:
                # Try to import the inotify module that watchdog uses
                from watchdog.observers.inotify import InotifyObserver
                return ("Linux", "inotify")
            except ImportError:
                return ("Linux", "unavailable")
        
        elif system == "Darwin":
            # macOS uses FSEvents
            # Check if FSEvents is available
            try:
                from watchdog.observers.fsevents import FSEventsObserver
                return ("macOS", "FSEvents")
            except ImportError:
                return ("macOS", "unavailable")
        
        elif system == "Windows":
            # Windows uses ReadDirectoryChangesW
            # Check if the Windows API is available
            try:
                from watchdog.observers.read_directory_changes import WindowsApiObserver
                return ("Windows", "ReadDirectoryChangesW")
            except ImportError:
                return ("Windows", "unavailable")
        
        else:
            return (system, "unavailable")
    
    def start(self) -> bool:
        """
        Start monitoring the directory.
        
        Returns:
            True if monitoring started successfully, False otherwise
        """
        if not WATCHDOG_AVAILABLE:
            self.logger.error("watchdog library not available - cannot start monitoring")
            return False
        
        # Check if directory exists
        if not self.path.exists():
            self.logger.error(f"Cannot monitor non-existent directory: {self.path}")
            return False
        
        if not self.path.is_dir():
            self.logger.error(f"Cannot monitor non-directory path: {self.path}")
            return False
        
        # Detect platform and monitoring API (Requirement 5.1, 5.2, 5.3)
        platform_name, api_name = self._detect_platform_and_api()
        self.logger.debug(f"Platform detected: {platform_name}, Native monitoring API: {api_name}")
        
        # If force_polling is True, skip native monitoring and go straight to polling
        if self.force_polling:
            self.logger.debug(f"Force polling mode requested for: {self.path}")
            return self._start_polling_observer()
        
        # If native API is unavailable, use polling
        if api_name == "unavailable":
            self.logger.debug(f"Native monitoring API not available on {platform_name}, using polling mode")
            return self._start_polling_observer()
        
        try:
            # Try to use native Observer first
            self.logger.debug(f"Attempting to start native monitoring for: {self.path} using {api_name}")
            self.observer = Observer()
            self.monitoring_mode = "native"
            
            # Create XeFMFileSystemEventHandler
            self._event_handler = XeFMFileSystemEventHandler(self.event_callback, str(self.path))
            
            # Schedule the observer to watch the directory
            # recursive=False means only watch the directory itself, not subdirectories
            self.observer.schedule(self._event_handler, str(self.path), recursive=False)
            
            # Start the observer thread
            self.observer.start()
            
            self.logger.debug(f"Successfully started native monitoring for: {self.path} using {api_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Native monitoring failed for {self.path}: {e}")
            self.logger.debug(f"Mode transition: native -> polling (reason: native monitoring initialization failed - {e})")
            
            return self._start_polling_observer()
    
    def _start_polling_observer(self) -> bool:
        """
        Start monitoring using polling observer.
        
        Uses the configured polling interval (default 5 seconds) for checking
        filesystem changes. This is used when native monitoring is unavailable
        or for unsupported backends like S3, network mounts, etc.
        
        Returns:
            True if polling started successfully, False otherwise
        """
        try:
            self.logger.debug(f"Starting polling observer for: {self.path} with interval: {self.polling_interval}s")
            
            # Fall back to polling observer with configured interval
            # The timeout parameter sets how often the observer checks for changes
            self.observer = PollingObserver(timeout=self.polling_interval)
            self.monitoring_mode = "polling"
            
            # Create XeFMFileSystemEventHandler
            self._event_handler = XeFMFileSystemEventHandler(self.event_callback, str(self.path))
            
            self.observer.schedule(self._event_handler, str(self.path), recursive=False)
            self.observer.start()
            
            self.logger.debug(f"Successfully started polling monitoring for: {self.path} (interval: {self.polling_interval}s)")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start polling monitoring for {self.path}: {e}")
            self.logger.error(f"Monitoring disabled for {self.path} - all monitoring methods failed")
            self.observer = None
            self.monitoring_mode = "disabled"
            return False
    
    def stop(self) -> None:
        """Stop monitoring and cleanup resources."""
        if self.observer is None:
            self.logger.debug(f"No active monitoring to stop for: {self.path}")
            return
        
        try:
            self.logger.debug(f"Stopping monitoring for: {self.path}")
            self.observer.stop()
            self.observer.join(timeout=5.0)  # Wait up to 5 seconds for thread to finish
            
            if self.observer.is_alive():
                self.logger.warning(f"Observer thread did not stop cleanly for: {self.path}")
            else:
                self.logger.debug(f"Successfully stopped monitoring for: {self.path}")
            
        except Exception as e:
            self.logger.error(f"Error stopping observer for {self.path}: {e}")
        
        finally:
            self.observer = None
            self._event_handler = None
            self.monitoring_mode = "disabled"
    
    def is_alive(self) -> bool:
        """Check if observer is running."""
        if self.observer is None:
            return False
        
        try:
            return self.observer.is_alive()
        except Exception as e:
            self.logger.error(f"Error checking observer status for {self.path}: {e}")
            return False
    
    def get_monitoring_mode(self) -> str:
        """
        Get current monitoring mode.
        
        Returns:
            "native" or "polling"
        """
        return self.monitoring_mode
