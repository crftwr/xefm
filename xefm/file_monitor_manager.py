"""
FileMonitorManager - Central coordinator for filesystem monitoring.

This module manages filesystem monitoring for XeFM directories, coordinating
monitoring of both left and right pane directories, handling event coalescing,
and triggering file list reloads via a thread-safe queue mechanism.
"""

from pathlib import Path
from typing import Optional, Dict
import threading
import time
from xefm.log_manager import getLogger
from xefm.file_monitor_observer import FileMonitorObserver, WATCHDOG_AVAILABLE


class FileMonitorManager:
    """
    Manages filesystem monitoring for XeFM directories.
    
    Coordinates monitoring of both left and right pane directories,
    handles event coalescing, and triggers file list reloads via
    a thread-safe queue mechanism.
    """
    
    def __init__(self, config, file_manager):
        """
        Initialize the file monitor manager.
        
        Args:
            config: XeFM configuration object
            file_manager: FileManager instance (for accessing reload_queue)
        """
        # Initialize logger with name "FileMonitor" as per requirement 12.4
        self.logger = getLogger("FileMonitor")
        
        # Store configuration and file_manager reference
        self.config = config
        self.file_manager = file_manager
        
        # Store reference to file_manager.reload_queue for thread-safe communication
        # This queue is used to post reload requests from the monitor thread to the main UI thread
        self.reload_queue = file_manager.reload_queue
        
        # Initialize monitoring state dictionaries for left and right panes
        # Each pane has its own monitoring state to track independently
        self.monitoring_state = {
            'left': {
                'path': None,
                'observer': None,
                'last_reload_time': 0.0,
                'pending_reload': False,
                'error_count': 0,
                'retry_count': 0,
                'last_successful_start': 0.0,
                'failed_permanently': False
            },
            'right': {
                'path': None,
                'observer': None,
                'last_reload_time': 0.0,
                'pending_reload': False,
                'error_count': 0,
                'retry_count': 0,
                'last_successful_start': 0.0,
                'failed_permanently': False
            }
        }
        
        # Set up event coalescing timer and rate limiting state
        # Coalescing timer is used to batch multiple rapid events into a single reload
        self.coalesce_timers: Dict[str, Optional[threading.Timer]] = {
            'left': None,
            'right': None
        }
        
        # Rate limiting state to prevent excessive reloads
        # Tracks reload times to enforce max_reloads_per_second limit
        self.reload_times: Dict[str, list] = {
            'left': [],
            'right': []
        }
        
        # Suppression state for temporarily disabling automatic reloads
        # Used after user-initiated actions to avoid redundant reloads
        self.suppress_until: Dict[str, float] = {
            'left': 0.0,
            'right': 0.0
        }
        
        # Lock for thread-safe access to internal state
        self.state_lock = threading.Lock()
        
        # Read monitoring enabled flag from configuration (requirement 11.1)
        self.enabled = config.FILE_MONITORING_ENABLED
        
        # If the watchdog library is not installed, filesystem monitoring cannot
        # run at all (even polling mode is provided by watchdog). Disable monitoring
        # up front and emit a single clear message instead of letting every pane
        # cascade through retries and polling fallbacks that all fail the same way.
        if self.enabled and not WATCHDOG_AVAILABLE:
            self.logger.warning(
                "File monitoring disabled: the 'watchdog' library is not installed. "
                "Install it with 'pip install watchdog' to enable automatic file list reloading."
            )
            self.enabled = False
        
        # Log initialization with monitoring status (Requirement 12.1)
        if self.enabled:
            self.logger.debug("FileMonitorManager initialized - monitoring enabled")
        else:
            self.logger.debug("FileMonitorManager initialized - monitoring disabled by configuration")
    
    def start_monitoring(self, left_path: Path, right_path: Path) -> None:
        """
        Start monitoring both pane directories.
        
        Args:
            left_path: Path object for left pane directory
            right_path: Path object for right pane directory
        """
        if not self.enabled:
            self.logger.debug("Monitoring is disabled by configuration")
            return
        
        # Log watched directories on start_monitoring (Requirement 12.1)
        self.logger.debug(f"Starting monitoring for directories - left: {left_path}, right: {right_path}")
        
        # Start monitoring for left pane
        self._start_pane_monitoring('left', left_path)
        
        # Start monitoring for right pane
        self._start_pane_monitoring('right', right_path)
    
    def _start_pane_monitoring(self, pane_name: str, path: Path) -> None:
        """
        Start monitoring for a specific pane.
        
        Includes retry logic with exponential backoff and automatic fallback to polling
        mode after repeated failures (requirement 9.2, 9.3).
        
        If both panes are monitoring the same directory, they will share the same observer
        to avoid FSEvents "already scheduled" errors.
        
        Args:
            pane_name: "left" or "right"
            path: Directory path to monitor
        """
        with self.state_lock:
            state = self.monitoring_state[pane_name]
            other_pane = 'right' if pane_name == 'left' else 'left'
            other_state = self.monitoring_state[other_pane]
            
            # Check if this pane has failed permanently
            if state['failed_permanently']:
                self.logger.warning(f"Monitoring for {pane_name} pane has failed permanently, not retrying")
                return
            
            # Check if the other pane is already monitoring this same directory
            # If so, share the observer instead of creating a new one
            if other_state['path'] == path and other_state['observer'] is not None:
                self.logger.debug(f"Both panes monitoring same directory: {path} - sharing observer")
                
                # Stop existing observer for this pane if any
                if state['observer'] is not None and state['observer'] != other_state['observer']:
                    self.logger.debug(f"Stopping separate observer for {pane_name} pane")
                    state['observer'].stop()
                
                # Share the other pane's observer
                # Note: The observer's callback will trigger events for both panes
                # because _on_filesystem_event checks which panes are monitoring the path
                state['observer'] = other_state['observer']
                state['path'] = path
                state['error_count'] = 0
                state['retry_count'] = 0
                state['last_successful_start'] = time.time()
                self.logger.debug(f"Successfully started monitoring for {pane_name} pane: {path} (shared observer, mode: {state['observer'].get_monitoring_mode()})")
                return
            
            # Stop existing observer if any (and it's not shared with the other pane)
            if state['observer'] is not None:
                # Only stop if this observer is not shared with the other pane
                if state['observer'] != other_state['observer']:
                    self.logger.debug(f"Stopping existing observer for {pane_name} pane")
                    state['observer'].stop()
                state['observer'] = None
            
            # Update path
            state['path'] = path

            # Check if this is an unsupported backend (S3, SSH/SFTP, network mounts)
            # Requirements 6.4, 6.5
            monitoring_mode = self._detect_monitoring_mode(path)

            # Remote/virtual backends (S3, SSH/SFTP, archives) cannot be watched
            # by watchdog at all — not even in polling mode, which still stats the
            # raw path and raises [Errno 2] on e.g. "s3://bucket/" (issue #181).
            # Skip monitoring cleanly instead of cascading through failing retries
            # and polling fallbacks that all log errors and end up disabled anyway.
            if monitoring_mode == "disabled":
                self.logger.debug(
                    f"Filesystem monitoring not supported for {pane_name} pane backend: {path} "
                    f"- skipping (watchdog only monitors local paths)"
                )
                state['observer'] = None
                state['error_count'] = 0
                state['retry_count'] = 0
                return

            force_polling = (monitoring_mode == "polling")

            if force_polling:
                self.logger.debug(f"Unsupported backend detected for {pane_name} pane: {path} - forcing polling mode")
            
            # Create event callback for this pane
            def event_callback(event_type: str, filename: str):
                self._on_filesystem_event(pane_name, event_type, filename)
            
            # Create and start observer with configured polling interval
            polling_interval = self.config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S
            observer = FileMonitorObserver(path, event_callback, self.logger, force_polling=force_polling, polling_interval=polling_interval)
            
            if observer.start():
                state['observer'] = observer
                state['error_count'] = 0
                state['retry_count'] = 0
                state['last_successful_start'] = time.time()
                self.logger.debug(f"Successfully started monitoring for {pane_name} pane: {path} (mode: {observer.get_monitoring_mode()})")
            else:
                self.logger.error(f"Failed to start monitoring for {pane_name} pane: {path} (error_count: {state['error_count'] + 1})")
                state['observer'] = None
                state['error_count'] += 1
                
                # Attempt reinitialization with retry logic (requirement 9.2)
                self.logger.debug(f"Scheduling retry for {pane_name} pane (attempt will be {state['retry_count'] + 1}/3)")
                self._schedule_retry(pane_name, path)
    
    def _schedule_retry(self, pane_name: str, path: Path) -> None:
        """
        Schedule a retry attempt to reinitialize monitoring.
        
        Implements exponential backoff: 1s, 2s, 4s for up to 3 attempts.
        After 3 failures, falls back to polling mode permanently (requirement 9.3).
        
        Args:
            pane_name: "left" or "right"
            path: Directory path to monitor
        """
        state = self.monitoring_state[pane_name]
        
        # Check if we've exceeded retry limit
        if state['retry_count'] >= 3:
            self.logger.error(f"Monitoring initialization failed 3 times for {pane_name} pane at {path}")
            self.logger.debug(f"Mode transition: native -> polling (reason: 3 consecutive initialization failures)")
            self.logger.debug(f"Marking {pane_name} pane as failed permanently, attempting final polling fallback")
            state['failed_permanently'] = True
            
            # Try one last time with polling mode explicitly
            self._attempt_polling_fallback(pane_name, path)
            return
        
        # Calculate backoff delay: 1s, 2s, 4s
        backoff_delay = 2 ** state['retry_count']
        state['retry_count'] += 1
        
        self.logger.debug(f"Retry attempt {state['retry_count']}/3 scheduled for {pane_name} pane in {backoff_delay}s (exponential backoff)")
        
        # Schedule retry with exponential backoff
        def retry_monitoring():
            self.logger.debug(f"Executing retry attempt {state['retry_count']}/3 for {pane_name} pane at {path}")
            with self.state_lock:
                # Create event callback for this pane
                def event_callback(event_type: str, filename: str):
                    self._on_filesystem_event(pane_name, event_type, filename)
                
                # Create and start observer with configured polling interval
                polling_interval = self.config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S
                observer = FileMonitorObserver(path, event_callback, self.logger, polling_interval=polling_interval)
                
                if observer.start():
                    state['observer'] = observer
                    state['error_count'] = 0
                    state['retry_count'] = 0
                    state['last_successful_start'] = time.time()
                    self.logger.debug(f"Retry {state['retry_count']}/3 successful for {pane_name} pane: {path} (mode: {observer.get_monitoring_mode()})")
                else:
                    self.logger.error(f"Retry {state['retry_count']}/3 failed for {pane_name} pane at {path}")
                    state['error_count'] += 1
                    
                    # Schedule next retry if we haven't exceeded the limit
                    if state['retry_count'] < 3:
                        self._schedule_retry(pane_name, path)
                    else:
                        # Final failure - fall back to polling
                        self.logger.error(f"All retry attempts exhausted for {pane_name} pane")
                        self._schedule_retry(pane_name, path)  # This will trigger permanent failure
        
        timer = threading.Timer(backoff_delay, retry_monitoring)
        timer.daemon = True
        timer.start()
    
    def _attempt_polling_fallback(self, pane_name: str, path: Path) -> None:
        """
        Attempt to start monitoring in polling mode as a last resort.
        
        This is called after all retry attempts have failed.
        
        Args:
            pane_name: "left" or "right"
            path: Directory path to monitor
        """
        state = self.monitoring_state[pane_name]
        
        self.logger.debug(f"Attempting polling mode fallback for {pane_name} pane at {path}")
        
        # Create event callback for this pane
        def event_callback(event_type: str, filename: str):
            self._on_filesystem_event(pane_name, event_type, filename)
        
        # Create observer with force_polling flag and configured polling interval
        polling_interval = self.config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S
        observer = FileMonitorObserver(path, event_callback, self.logger, force_polling=True, polling_interval=polling_interval)
        
        if observer.start():
            state['observer'] = observer
            state['error_count'] = 0
            state['last_successful_start'] = time.time()
            self.logger.debug(f"Polling mode fallback successful for {pane_name} pane: {path}")
            self.logger.debug(f"Fallback mode activated: using polling observer after repeated native monitoring failures")
        else:
            self.logger.error(f"Polling mode fallback failed for {pane_name} pane at {path}")
            self.logger.error(f"Monitoring completely disabled for {pane_name} pane - all monitoring methods exhausted")
            state['observer'] = None
    
    def _detect_monitoring_mode(self, path: Path) -> str:
        """
        Detect the appropriate monitoring mode for a path.

        watchdog (both its native and PollingObserver backends) can only watch
        paths that live in the local filesystem — it ultimately calls
        os.scandir()/os.stat() on the raw path string. Remote and virtual
        backends (S3, SSH/SFTP, archives) are not mounted locally, so even
        polling mode fails: scheduling a watch on "s3://bucket/" raises
        [Errno 2] No such file or directory (issue #181). For those backends
        monitoring must be disabled entirely rather than attempted.

        Args:
            path: Path to check

        Returns:
            "native", "polling", or "disabled"
        """
        # Preferred check: the XeFM Path abstraction knows its own storage
        # scheme. watchdog only understands local ('file') paths, so disable
        # monitoring for every other backend (s3, ssh, scp, ftp, archive, …).
        get_scheme = getattr(path, "get_scheme", None)
        if callable(get_scheme):
            try:
                scheme = get_scheme()
            except Exception as e:
                self.logger.debug(f"Could not determine scheme for {path}: {e}")
                scheme = None
            if scheme is not None and scheme != "file":
                self.logger.debug(f"Remote/virtual backend detected ({scheme}): {path} - monitoring disabled")
                return "disabled"

        path_str = str(path)

        # Fallback heuristics for plain str/pathlib paths that don't expose
        # get_scheme(). These remote/virtual URIs cannot be watched by watchdog
        # either. Note: pathlib normalizes "s3://" to "s3:", so match the bare
        # scheme prefix as well as the collapsed "/s3/" form.
        if path_str.startswith(('s3:', '/s3/', 'ssh:', 'sftp:', 'scp:', 'ftp:', 'archive:')):
            self.logger.debug(f"Remote/virtual path detected: {path} - monitoring disabled")
            return "disabled"

        # Check for network mounts (common patterns). Unlike the backends above,
        # network mounts present as real local filesystem paths, so watchdog's
        # polling observer can watch them. This is a heuristic - network mounts
        # can be mounted anywhere but commonly appear in /mnt, /net, or use
        # UNC-style paths.
        if any(pattern in path_str for pattern in ['/mnt/', '/net/', '//']) and not path.exists():
            self.logger.debug(f"Detected potential network mount: {path} - will use polling mode")
            return "polling"

        # For local filesystem, let FileMonitorObserver try native first
        # It will automatically fall back to polling if native fails
        return "native"
    
    def _on_filesystem_event(self, pane_name: str, event_type: str, filename: str) -> None:
        """
        Handle a filesystem event from an observer.
        
        This method is called from the observer thread, so it must be thread-safe.
        It implements event coalescing and rate limiting before posting reload requests.
        Includes error handling to ensure monitoring continues even if event processing fails.
        
        When both panes are monitoring the same directory, this method will be called
        with the pane_name of whichever pane created the observer first. We need to
        check if both panes are monitoring the same path and post reload requests for both.
        
        Args:
            pane_name: "left" or "right" (the pane that created the observer)
            event_type: Type of event ("created", "deleted", "modified")
            filename: Name of the affected file
        """
        try:
            with self.state_lock:
                state = self.monitoring_state[pane_name]
                other_pane = 'right' if pane_name == 'left' else 'left'
                other_state = self.monitoring_state[other_pane]
                
                # Check if both panes are monitoring the same directory
                # If so, we need to post reload requests for both panes
                panes_to_reload = [pane_name]
                if other_state['path'] == state['path'] and other_state['observer'] == state['observer']:
                    panes_to_reload.append(other_pane)
                    self.logger.debug(f"Event detected in shared directory, will reload both panes (event: {event_type}, file: {filename})")
                
                # Process reload for each pane that's monitoring this directory
                for pane in panes_to_reload:
                    pane_state = self.monitoring_state[pane]
                    
                    # Check if reloads are currently suppressed for this pane
                    current_time = time.time()
                    if current_time < self.suppress_until[pane]:
                        self.logger.debug(f"Reload suppressed for {pane} pane (event: {event_type}, file: {filename})")
                        continue
                    
                    # Check rate limiting for this pane
                    if not self._check_rate_limit(pane):
                        self.logger.warning(f"Rate limit exceeded for {pane} pane, skipping reload (event: {event_type}, file: {filename})")
                        continue
                    
                    # Cancel existing coalesce timer if any
                    if self.coalesce_timers[pane] is not None:
                        self.coalesce_timers[pane].cancel()
                    
                    # Mark that a reload is pending
                    pane_state['pending_reload'] = True
                    
                    # Set up coalescing timer
                    coalesce_delay_s = self.config.FILE_MONITORING_COALESCE_DELAY_MS / 1000.0
                    
                    def coalesced_reload(pane_to_reload=pane):
                        try:
                            self._post_reload_request(pane_to_reload)
                        except Exception as e:
                            self.logger.error(f"Error posting reload request for {pane_to_reload} pane: {e}")
                    
                    timer = threading.Timer(coalesce_delay_s, coalesced_reload)
                    self.coalesce_timers[pane] = timer
                    timer.start()
        
        except Exception as e:
            # Log error but continue monitoring (requirement 9.1)
            self.logger.error(f"Error processing filesystem event for {pane_name} pane (event: {event_type}, file: {filename}, path: {self.monitoring_state[pane_name].get('path', 'unknown')}): {e}")
            # Don't re-raise - we want monitoring to continue
    
    def _check_rate_limit(self, pane_name: str) -> bool:
        """
        Check if a reload is allowed under the rate limit.
        
        Args:
            pane_name: "left" or "right"
            
        Returns:
            True if reload is allowed, False if rate limit exceeded
        """
        current_time = time.time()
        max_reloads = self.config.FILE_MONITORING_MAX_RELOADS_PER_SECOND
        
        # Clean up old reload times (older than 1 second)
        self.reload_times[pane_name] = [
            t for t in self.reload_times[pane_name]
            if current_time - t < 1.0
        ]
        
        # Check if we've exceeded the rate limit
        if len(self.reload_times[pane_name]) >= max_reloads:
            return False
        
        return True
    
    def _post_reload_request(self, pane_name: str) -> None:
        """
        Post a reload request to the file manager's reload queue.
        
        This method is called from the coalescing timer thread, so it must be thread-safe.
        
        Args:
            pane_name: "left" or "right"
        """
        with self.state_lock:
            state = self.monitoring_state[pane_name]
            
            # Clear pending reload flag
            state['pending_reload'] = False
            
            # Record reload time for rate limiting
            current_time = time.time()
            self.reload_times[pane_name].append(current_time)
            state['last_reload_time'] = current_time
            
            # Post to reload queue (thread-safe)
            self.reload_queue.put(pane_name)
            self.logger.debug(f"Posted reload request for {pane_name} pane")

        # Wake the UI thread to drain the queue (event-driven backends have no
        # idle polling timer). Outside the state lock; a no-op where unsupported.
        wake = getattr(self.file_manager, "_wake_pump", None)
        if wake is not None:
            wake()
    
    def update_monitored_directory(self, pane_name: str, new_path: Path) -> None:
        """
        Update the monitored directory for a specific pane.
        
        Args:
            pane_name: "left" or "right"
            new_path: New directory path to monitor
        """
        if not self.enabled:
            return
        
        self.logger.debug(f"Updating monitored directory: pane={pane_name}, path={new_path}")
        
        # Stop monitoring the old directory and start monitoring the new one
        self._start_pane_monitoring(pane_name, new_path)
    
    def stop_monitoring(self) -> None:
        """Stop all monitoring and cleanup resources."""
        self.logger.debug("Stopping all monitoring")
        
        with self.state_lock:
            # Stop observers for both panes
            for pane_name in ['left', 'right']:
                state = self.monitoring_state[pane_name]
                
                # Cancel coalesce timer if any
                if self.coalesce_timers[pane_name] is not None:
                    self.coalesce_timers[pane_name].cancel()
                    self.coalesce_timers[pane_name] = None
                
                # Stop observer if any
                if state['observer'] is not None:
                    self.logger.debug(f"Stopping observer for {pane_name} pane")
                    state['observer'].stop()
                    state['observer'] = None
                
                # Clear state
                state['path'] = None
                state['pending_reload'] = False
        
        self.logger.debug("All monitoring stopped")
    
    def is_monitoring_enabled(self) -> bool:
        """Check if monitoring is currently enabled."""
        return self.enabled
    
    def is_watchdog_available(self) -> bool:
        """
        Check whether the watchdog library is installed.
        
        Filesystem monitoring (including polling fallback) requires the watchdog
        library. When it is not installed, monitoring cannot be enabled.
        
        Returns:
            True if watchdog is available, False otherwise
        """
        return WATCHDOG_AVAILABLE
    
    def get_monitoring_mode(self, path: Path) -> str:
        """
        Get the monitoring mode for a path.
        
        Returns:
            "native", "polling", or "disabled"
        """
        if not self.enabled:
            return "disabled"
        
        # Check if this path is currently being monitored
        with self.state_lock:
            for pane_name in ['left', 'right']:
                state = self.monitoring_state[pane_name]
                if state['path'] == path and state['observer'] is not None:
                    return state['observer'].get_monitoring_mode()
        
        # If not currently monitored, detect what mode would be used
        return self._detect_monitoring_mode(path)
    
    def suppress_reloads(self, duration_ms: int) -> None:
        """
        Temporarily suppress automatic reloads.
        
        Used after user-initiated actions to avoid redundant reloads.
        
        Args:
            duration_ms: Suppression duration in milliseconds
        """
        suppress_until = time.time() + (duration_ms / 1000.0)
        
        with self.state_lock:
            for pane_name in ['left', 'right']:
                self.suppress_until[pane_name] = suppress_until
        
        self.logger.debug(f"Suppressing reloads for {duration_ms}ms")
    
    def check_observer_health(self) -> None:
        """
        Check if observers are still alive and attempt recovery if needed.
        
        This method should be called periodically to detect connection loss
        and trigger reinitialization (requirement 9.2).
        """
        with self.state_lock:
            for pane_name in ['left', 'right']:
                state = self.monitoring_state[pane_name]
                
                # Skip if no observer or already failed permanently
                if state['observer'] is None or state['failed_permanently']:
                    continue
                
                # Check if observer is still alive
                if not state['observer'].is_alive():
                    path = state['path']
                    self.logger.error(f"Observer for {pane_name} pane has died unexpectedly (path: {path})")
                    self.logger.debug(f"Connection loss detected for {pane_name} pane, attempting recovery")
                    
                    # Stop the dead observer
                    try:
                        state['observer'].stop()
                    except Exception as e:
                        self.logger.error(f"Error stopping dead observer for {pane_name} pane: {e}")
                    
                    state['observer'] = None
                    state['error_count'] += 1
                    
                    # Attempt reinitialization
                    self.logger.debug(f"Initiating reinitialization for {pane_name} pane after connection loss")
                    self._schedule_retry(pane_name, path)
    
    def is_in_fallback_mode(self) -> bool:
        """
        Check if any pane is operating in fallback (polling) mode.
        
        Returns:
            True if any pane is in polling mode, False otherwise
        """
        if not self.enabled:
            return False
        
        with self.state_lock:
            for pane_name in ['left', 'right']:
                state = self.monitoring_state[pane_name]
                if state['observer'] is not None:
                    if state['observer'].get_monitoring_mode() == "polling":
                        return True
        
        return False
