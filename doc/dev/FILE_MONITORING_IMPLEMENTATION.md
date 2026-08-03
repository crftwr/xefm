# File Monitoring Implementation

## Overview

This document provides technical implementation details for XeFM's automatic file list reloading feature. It is intended for developers who need to understand, maintain, or extend the file monitoring system.

### Purpose

The file monitoring system enables XeFM to automatically detect and reflect filesystem changes made by external applications without requiring manual user refresh actions. This keeps the displayed file list synchronized with the actual filesystem state.

### Key Components

- **FileMonitorManager** (`xefm/file_monitor_manager.py`) - Central coordinator for filesystem monitoring
- **FileMonitorObserver** (`xefm/file_monitor_observer.py`) - Per-directory watcher wrapping watchdog library
- **XeFMFileSystemEventHandler** (`xefm/file_monitor_observer.py`) - Event handler for processing watchdog events
- **FileManager Integration** (`xefm/app.py`) - Main application integration and reload handling

### Dependencies

- **watchdog** (v4.0.0+) - Cross-platform filesystem monitoring library
- **queue** (Python stdlib) - Thread-safe communication between monitor and main threads

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        FileManager                           │
│                     (Main Application)                       │
│  - reload_queue: Queue                                       │
│  - file_monitor_manager: FileMonitorManager                  │
└────────────┬────────────────────────────────┬───────────────┘
             │                                 │
             │ creates/manages                 │ triggers reload
             │                                 │
             ▼                                 ▼
┌────────────────────────┐          ┌──────────────────────────┐
│   FileMonitorManager   │          │   FileListManager        │
│  (Monitoring Control)  │          │   (File List Ops)        │
│  - monitors: dict      │          └──────────────────────────┘
│  - reload_timers: dict │
│  - rate_limit_times    │
└────────┬───────────────┘
         │
         │ manages (one per pane)
         │
         ▼
┌────────────────────────┐
│  FileMonitorObserver   │
│  (Per-Directory Watch) │
│  - observer: Observer  │
│  - event_handler       │
└────────┬───────────────┘
         │
         │ uses
         │
         ▼
┌────────────────────────┐
│   watchdog library     │
│  (Native FS Events)    │
└────────────────────────┘
```


### Component Responsibilities

#### FileMonitorManager

**Location**: `xefm/file_monitor_manager.py`

**Purpose**: Central coordinator for all filesystem monitoring operations.

**Key Responsibilities**:
- Manages lifecycle of directory watchers for both left and right panes
- Implements event coalescing to batch rapid changes into single reloads
- Enforces rate limiting to prevent UI thrashing
- Handles monitoring mode selection (native vs fallback/polling)
- Provides configuration-based enable/disable control
- Posts reload requests to `file_manager.reload_queue` (thread-safe)
- Implements error recovery with retry logic and fallback mechanisms

**State Management**:
```python
self.monitors = {
    "left": MonitorState,   # Left pane monitoring state
    "right": MonitorState   # Right pane monitoring state
}
self.reload_timers = {}     # Coalescing timers per pane
self.rate_limit_times = {}  # Rate limiting timestamps per pane
```

**Configuration Properties**:
- `FILE_MONITORING_ENABLED` - Master enable/disable flag
- `FILE_MONITORING_COALESCE_DELAY_MS` - Event batching window (default: 200ms)
- `FILE_MONITORING_MAX_RELOADS_PER_SECOND` - Rate limit (default: 5/sec)
- `FILE_MONITORING_FALLBACK_POLL_INTERVAL_S` - Polling interval (default: 5s)

#### FileMonitorObserver

**Location**: `xefm/file_monitor_observer.py`

**Purpose**: Wraps watchdog Observer for a single directory.

**Key Responsibilities**:
- Detects and reports filesystem events (create, delete, modify, rename)
- Handles platform-specific monitoring API selection
- Provides error handling and status reporting
- Supports both native and polling modes
- Manages observer lifecycle (start, stop, health checks)

**Platform Detection**:
```python
def _detect_platform_and_api(self) -> tuple[str, str]:
    """
    Returns: (platform, api)
    - Linux: ("linux", "inotify")
    - macOS: ("darwin", "fsevents")
    - Windows: ("windows", "read_directory_changes")
    """
```

**Monitoring Modes**:
- **Native**: Uses OS-specific APIs (inotify, FSEvents, ReadDirectoryChangesW)
- **Polling**: Periodic directory scanning (fallback for unsupported backends)


#### XeFMFileSystemEventHandler

**Location**: `xefm/file_monitor_observer.py`

**Purpose**: Processes watchdog events and filters them appropriately.

**Key Responsibilities**:
- Filters events to only immediate children of watched directory (no subdirectories)
- Converts watchdog events to XeFM event types
- Handles move operations (move-in as create, move-out as delete)
- Invokes callback with event type and filename

**Event Filtering**:
```python
def _is_immediate_child(self, event_path: str) -> bool:
    """
    Only process events for files directly in watched directory.
    Subdirectory events are ignored to avoid unnecessary reloads.
    """
```

**Event Type Mapping**:
- `on_created()` → "created"
- `on_deleted()` → "deleted"
- `on_modified()` → "modified"
- `on_moved()` → "created" (move-in) or "deleted" (move-out)

#### FileManager Integration

**Location**: `xefm/app.py`

**Purpose**: Integrates monitoring into main application event loop.

**Key Integration Points**:

1. **Initialization** (`__init__`):
```python
# Create thread-safe queue for reload requests
self.reload_queue = queue.Queue()

# Initialize and start monitoring
self.file_monitor_manager = FileMonitorManager(self.config, self)
self.file_monitor_manager.start_monitoring(
    self.pane_manager.left_pane['path'],
    self.pane_manager.right_pane['path']
)
```

2. **Main Event Loop** (`run`):
```python
while True:
    # Check reload queue BEFORE processing events
    try:
        while True:
            pane_name = self.reload_queue.get_nowait()
            self._handle_reload_request(pane_name)
            self.mark_dirty()  # Trigger redraw
    except queue.Empty:
        pass
    
    # Process events (blocks waiting for input)
    self.renderer.run_event_loop_iteration(timeout_ms=timeout_ms)
    
    # Draw interface
    self.draw_interface()
```

3. **Directory Navigation**:
```python
def navigate_to_dir(self, pane_data, new_path):
    # ... navigation logic ...
    
    # Update monitoring for this pane
    pane_name = "left" if pane_data == self.pane_manager.left_pane else "right"
    self.file_monitor_manager.update_monitored_directory(pane_name, new_path)
```

4. **Cleanup** (`run` exit):
```python
# Stop file monitoring before cleanup
if hasattr(self, 'file_monitor_manager'):
    self.file_monitor_manager.stop_monitoring()
```


## Threading Model

### XeFM's Event Loop Architecture

XeFM's main thread runs a blocking event loop that waits for user input:

```python
# Main thread in FileManager.run()
while True:
    # Process events (blocks waiting for keyboard/mouse input)
    self.renderer.run_event_loop_iteration(timeout_ms=timeout_ms)
    
    # Redraw interface
    self.draw_interface()
```

When an event arrives (keyboard, mouse, resize), `run_event_loop_iteration()` immediately invokes callbacks synchronously on the main thread before returning. This means callbacks execute within the event processing, not as separate scheduled tasks.

### Thread-Safe Communication

Since the monitor thread cannot directly call UI methods, we use a thread-safe queue:

```
Main Thread                           Monitor Thread
    │                                      │
    │ Check reload_queue                  │
    │ (at start of each loop)             │
    │                                      │
    │ navigate_to_dir()                   │
    ├─────────────────────────────────────>│
    │                                      │ start_watching()
    │                                      │
    │                                      │ [filesystem change detected]
    │                                      │
    │                                      │ reload_queue.put(pane_name)
    │ <─────────────────────────────────────┤
    │ reload_queue.get_nowait()           │
    │ _handle_reload_request(pane_name)   │
    │ refresh_files()                      │
    │                                      │
    │ run_event_loop_iteration()          │
    │ draw_interface()                     │
    │                                      │
```

### Implementation Details

**Queue Creation** (`FileManager.__init__`):
```python
import queue
self.reload_queue = queue.Queue()  # Thread-safe queue for reload requests
```

**Main Loop Processing** (`FileManager.run`):
```python
while True:
    # Check reload queue BEFORE processing events
    try:
        while True:
            pane_name = self.reload_queue.get_nowait()
            self._handle_reload_request(pane_name)
            self.mark_dirty()  # Trigger redraw
    except queue.Empty:
        pass
    
    # ... rest of event loop ...
```

**Monitor Thread Callback** (safe to call from any thread):
```python
def _on_filesystem_change(self, pane_name: str):
    # Just post to queue - no UI operations
    self.file_manager.reload_queue.put(pane_name)
```

### Thread Safety Guarantees

- `queue.Queue` is thread-safe for put/get operations
- Monitor thread only posts pane names to queue (no UI access)
- Main thread is sole consumer of queue (processes reloads)
- All UI operations (`refresh_files`, `draw_interface`) occur on main thread
- FileMonitorManager uses locks only for its own state management
- No direct callback invocation from monitor thread to UI code


## Event Processing Flow

### Event Detection and Coalescing

```
External Change → watchdog → XeFMFileSystemEventHandler → FileMonitorManager
                                                                │
                                                                ▼
                                                    ┌───────────────────────┐
                                                    │ Event Coalescing      │
                                                    │ (200ms window)        │
                                                    └───────────┬───────────┘
                                                                │
                                                                ▼
                                                    ┌───────────────────────┐
                                                    │ Rate Limiting         │
                                                    │ (5 reloads/sec max)   │
                                                    └───────────┬───────────┘
                                                                │
                                                                ▼
                                                    reload_queue.put(pane_name)
                                                                │
                                                                ▼
                                                    FileManager._handle_reload_request()
                                                                │
                                                                ▼
                                                    ┌───────────────────────┐
                                                    │ Re-list (keep_visible)│
                                                    │ pane keeps its entries│
                                                    └───────────┬───────────┘
                                                                │
                                                                ▼
                                                    ┌───────────────────────┐
                                                    │ Compare vs. on-screen │
                                                    │ equal → drop, no draw │
                                                    └───────────────────────┘
```

### Detailed Event Flow

1. **External Change Occurs**
   - File created, deleted, modified, or renamed in watched directory
   - OS notifies watchdog library (or polling detects change)

2. **Event Handler Processes Event**
   ```python
   # XeFMFileSystemEventHandler
   def on_created(self, event):
       if not self._is_immediate_child(event.src_path):
           return  # Ignore subdirectory events
       
       filename = self._get_filename(event.src_path)
       self.callback("created", filename)
   ```

3. **FileMonitorManager Receives Event**
   ```python
   def _on_filesystem_event(self, pane_name: str, event_type: str, filename: str):
       # Log the event
       self.logger.info(f"Filesystem event: {event_type} - {filename} in {pane_name} pane")
       
       # Check if suppressed
       if time.time() < self.suppress_until:
           return
       
       # Set up coalescing timer (200ms)
       if pane_name in self.reload_timers:
           self.reload_timers[pane_name].cancel()
       
       timer = threading.Timer(coalesce_delay_s, self._post_reload_request, args=[pane_name])
       self.reload_timers[pane_name] = timer
       timer.start()
   ```

4. **Coalescing Timer Fires**
   ```python
   def _post_reload_request(self, pane_name: str):
       # Check rate limit
       if not self._check_rate_limit(pane_name):
           return  # Too many reloads, skip this one
       
       # Post to queue
       self.file_manager.reload_queue.put(pane_name)
   ```

5. **Main Thread Processes Reload**
   ```python
   def _handle_reload_request(self, pane_name):
       # Get pane data
       pane_data = self.pane_manager.left_pane if pane_name == "left" else self.pane_manager.right_pane
       
       # Store current context
       selected_filename = pane_data['files'][pane_data['focused_index']].name
       
       # Refresh file list
       self.refresh_files(pane_data)
       
       # Restore cursor position
       # ... (see Context Preservation section)
   ```


## Absorbing Spurious Reloads

Most reload requests that reach `_handle_reload_request` change nothing the user
can see. A "modified" event does not mean the file's *contents* changed: on macOS
watchdog's FSEvents backend maps inode-metadata, extended-attribute and ownership
changes onto an ordinary `FileModifiedEvent`, indistinguishable from a real write
(`_is_meta_mod` in `watchdog/observers/fsevents.py`). Opening a file in a GUI app
writes exactly those — `com.apple.macl`, `com.apple.lastuseddate#PS`, a quarantine
flag update — and a media player checkpointing playback position emits a stream of
them. Reading a file produces no event at all; the writes around the open do.

Two mechanisms keep those free (issue #239):

**1. The pane is never blanked for a reload nobody asked for.**
`_list_pane(..., keep_visible=True)` re-reads the directory without first clearing
`files` / `file_info`. The listing stays on screen and stays actionable for the
whole re-read, and no "Loading…" indicator is armed. The default (blanking) path
is still correct for a *navigation*, where the old directory's entries must not
remain actionable under the new path.

**2. A result matching what is on screen is dropped.**
`_listing_unchanged` compares the incoming `files` (rows and their order) and
`file_info` (every column drawn from disk: size, date, dir/link flags) against
what the pane already holds. Equal means installing it could not change one cell,
so it is discarded — no `apply_listing`, no cursor reconciliation, no re-render.
The `entries` snapshot is still refreshed, so a later sort or filter rebuilds from
current data at no cost.

Two ordering rules make this safe:

- A result is only droppable while the pane is **not** `loading`. One still blanked
  by an in-flight navigation must install even a matching result — an empty
  directory would otherwise compare equal to the blank pane and leave it stuck
  loading forever.
- `_handle_reload_request` returns early when a listing is already in flight for
  the pane. That listing is at least as fresh, and superseding it would discard
  the cursor placement its `on_ready` carries.

Because starting a reload no longer changes anything on screen, `_pump_monitoring`
excludes `_process_reload_queue` from its "needs a redraw" answer; only a result
that actually differs triggers a frame.

### Two flags, not one

`loading` means "this pane is blanked and showing (or about to show) an
indicator". `_load_pending` means "a filesystem read is in flight". A
`keep_visible` re-list sets only the second. `_listings_pending` (and therefore
`_settle_listings`) must consult `_load_pending`, or such a listing looks settled
the moment it starts.

## Suppression During XeFM's Own File Operations

A copy, move, delete or duplicate mutates the very directories the panes watch,
so the operation's own writes stream events at the watchers for its whole
duration. Unchecked, that drives re-lists at the configured rate limit (up to
`FILE_MONITORING_MAX_RELOADS_PER_SECOND` full `scandir`+stat passes per second)
competing with the operation for disk I/O — and arms one `threading.Timer` (a
real thread) per event just to keep resetting the coalesce window. None of it
buys anything: every operation already performs an explicit refresh of the
affected panes in its `on_complete`, which is strictly fresher (issue #243).

`FileMonitorManager.suppress_path(path)` / `release_path(path)` therefore
bracket each operation. `FileOperationService._run` computes the mutated
directories up front — the destination, plus each target's parent for
move/delete (`_mutated_dirs`) — suppresses them before the first write, and
releases them in its `finally`, so errors and cancellation cannot leak a
silenced watcher. The set is refcounted per `str(path)`, letting overlapping
operations on the same directory nest.

Suppressed events are **dropped, not deferred** — at the top of
`_on_filesystem_event`, before any timer is armed — and a guard in
`_post_reload_request` catches a coalesce timer armed just before suppression
began. The completion refresh is the reconciliation, and it also picks up any
external change that happened to land mid-operation. Events for directories the
operation does not touch flow normally throughout, so a background watcher on
the other pane stays live.

The app attaches its monitor to the shared operation service right after
constructing it (`self._fileops.monitor = self.file_monitor`); the directory
diff viewer receives it through `show_directory_diff_viewer(..., monitor=...)`.
A service with no monitor (unit tests, standalone use) skips the bracketing
entirely.

## Context Preservation

### User Context During Reload

When a reload does install a change, XeFM preserves the user's context to avoid disrupting their workflow:

1. **Cursor Position**: Stays on the same filename if it still exists
2. **Scroll Position**: Maintained when possible
3. **Selection**: Moves to nearest file if selected file was deleted

A reload that installs nothing leaves cursor and scroll exactly where the user put
them — the restore callback never runs.

### Implementation

```python
def _handle_reload_request(self, pane_name):
    # Get pane data
    pane_data = self.pane_manager.left_pane if pane_name == "left" else self.pane_manager.right_pane
    
    # Store current context before reload
    old_focused_index = pane_data['focused_index']
    old_scroll_offset = pane_data['scroll_offset']
    selected_filename = None
    
    # Get currently selected filename (if any files exist)
    if pane_data['files'] and 0 <= old_focused_index < len(pane_data['files']):
        selected_file = pane_data['files'][old_focused_index]
        selected_filename = selected_file.name
    
    # Refresh the file list for this pane
    self.refresh_files(pane_data)
    
    # Restore cursor position after reload
    if selected_filename and pane_data['files']:
        # Try to find the same file in the refreshed list
        found = False
        for i, file_path in enumerate(pane_data['files']):
            if file_path.name == selected_filename:
                # File still exists - restore cursor to it
                pane_data['focused_index'] = i
                found = True
                break
        
        if not found:
            # Selected file no longer exists - find nearest file alphabetically
            filenames = [f.name for f in pane_data['files']]
            
            # Find insertion point where selected_filename would go
            nearest_index = 0
            for i, filename in enumerate(filenames):
                if filename < selected_filename:
                    nearest_index = i + 1
                else:
                    break
            
            # Clamp to valid range
            if nearest_index >= len(pane_data['files']):
                nearest_index = len(pane_data['files']) - 1
            
            pane_data['focused_index'] = nearest_index
        
        # Preserve scroll position when possible
        max_offset = max(0, len(pane_data['files']) - display_height)
        pane_data['scroll_offset'] = min(old_scroll_offset, max_offset)
        
        # Ensure focused item is visible
        if pane_data['focused_index'] < pane_data['scroll_offset']:
            pane_data['scroll_offset'] = pane_data['focused_index']
        elif pane_data['focused_index'] >= pane_data['scroll_offset'] + display_height:
            pane_data['scroll_offset'] = pane_data['focused_index'] - display_height + 1
```

### Nearest File Algorithm

When the selected file is deleted, XeFM positions the cursor on the nearest remaining file by alphabetical order:

1. Build sorted list of filenames
2. Find insertion point where deleted filename would have been
3. Use that index as the new cursor position
4. Clamp to valid range if at end of list

This provides intuitive behavior where the cursor stays in approximately the same position in the list.


## Error Handling and Recovery

### Error Categories

1. **Initialization Errors**
   - Directory does not exist
   - Insufficient permissions to monitor directory
   - Native monitoring API unavailable
   - Resource limits exceeded (too many watches)

2. **Runtime Errors**
   - Connection loss to native monitoring API
   - Event processing exceptions
   - Observer thread death
   - Callback execution failures

3. **Backend-Specific Errors**
   - S3 access denied
   - Network mount disconnection
   - SSH connection timeout
   - Archive path monitoring attempts

### Recovery Strategies

#### Graceful Degradation

```python
def _start_pane_monitoring(self, pane_name: str, path: Path) -> None:
    try:
        # Attempt native monitoring
        observer = FileMonitorObserver(path, event_callback, self.logger)
        if observer.start():
            # Success - store observer
            self.monitors[pane_name] = MonitorState(path, observer, "native")
        else:
            # Native failed - schedule retry
            self._schedule_retry(pane_name, path)
    except Exception as e:
        self.logger.error(f"Failed to start monitoring: {e}")
        self._schedule_retry(pane_name, path)
```

#### Retry Logic with Exponential Backoff

```python
def _schedule_retry(self, pane_name: str, path: Path) -> None:
    state = self.monitors.get(pane_name)
    if state and state.error_count >= 3:
        # Too many failures - fall back to polling
        self._attempt_polling_fallback(pane_name, path)
        return
    
    # Calculate backoff delay: 1s, 2s, 4s
    retry_delay = 2 ** state.error_count if state else 1
    
    # Schedule retry
    timer = threading.Timer(retry_delay, self._retry_monitoring, args=[pane_name, path])
    timer.start()
```

#### Fallback to Polling Mode

```python
def _attempt_polling_fallback(self, pane_name: str, path: Path) -> None:
    self.logger.warning(f"Falling back to polling mode for {pane_name} pane")
    
    # Create observer with force_polling flag
    observer = FileMonitorObserver(
        path, 
        event_callback, 
        self.logger, 
        force_polling=True,
        polling_interval=self.config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S
    )
    
    if observer.start():
        self.monitors[pane_name] = MonitorState(path, observer, "polling")
        self.logger.info(f"Polling mode active for {pane_name} pane")
    else:
        self.logger.error(f"Polling mode failed for {pane_name} pane")
```

### Health Monitoring

FileMonitorManager includes a health check mechanism:

```python
def check_observer_health(self) -> None:
    """Check if observers are still alive and attempt recovery if needed."""
    for pane_name, state in self.monitors.items():
        if state.observer and not state.observer.is_alive():
            self.logger.warning(f"Observer for {pane_name} pane died, attempting recovery")
            self._schedule_retry(pane_name, state.path)
```

This is called periodically from the main event loop to detect and recover from observer failures.


## Platform-Specific Monitoring

### Native Monitoring APIs

#### Linux - inotify

**API**: `inotify` via watchdog's `InotifyObserver`

**Characteristics**:
- Event-driven, low latency
- Efficient for large numbers of watches
- Requires file descriptors (system limit applies)
- Supports all event types (create, delete, modify, move)

**Detection**:
```python
if sys.platform.startswith('linux'):
    return ("linux", "inotify")
```

**Limitations**:
- File descriptor limits (`/proc/sys/fs/inotify/max_user_watches`)
- Network filesystems may not support inotify
- Some virtual filesystems don't generate events

#### macOS - FSEvents

**API**: `FSEvents` via watchdog's `FSEventsObserver`

**Characteristics**:
- Event-driven, directory-level monitoring
- Efficient, low overhead
- Coalesces events automatically at OS level
- Supports all event types

**Detection**:
```python
if sys.platform == 'darwin':
    return ("darwin", "fsevents")
```

**Limitations**:
- Directory-level events (not file-level)
- May have slight delay in event delivery
- Some network mounts may not support FSEvents

#### Windows - ReadDirectoryChangesW

**API**: `ReadDirectoryChangesW` via watchdog's `WindowsApiObserver`

**Characteristics**:
- Event-driven, directory monitoring
- Supports all event types
- Requires directory handle

**Detection**:
```python
if sys.platform == 'win32':
    return ("windows", "read_directory_changes")
```

**Limitations**:
- Buffer overflow possible with many rapid changes
- Network drives may have limited support
- Some filesystem types not supported

### Fallback Polling Mode

When native monitoring is unavailable, XeFM falls back to periodic polling:

```python
class PollingObserver(BaseObserver):
    """
    Polls directory at regular intervals to detect changes.
    Used when native monitoring is unavailable.
    """
    def __init__(self, timeout=5.0):
        super().__init__(timeout=timeout)
```

**Characteristics**:
- Works on all filesystems
- Higher latency (5 second default)
- Higher CPU usage than native monitoring
- Detects all change types

**Use Cases**:
- Network mounts without notification support
- Local filesystems whose native API is unavailable
- After native monitoring failures on a local path

> **Note:** Polling only works on the **local** filesystem. watchdog's
> `PollingObserver` still calls `os.scandir()`/`os.stat()` on the raw path, so
> it cannot watch remote/virtual backends (S3, SSH/SFTP, archives) — those are
> **disabled**, not polled. Attempting to poll `s3://bucket/` raised
> `[Errno 2] No such file or directory` (issue #181).

### Backend Detection

FileMonitorManager decides per-path whether native monitoring, polling, or no
monitoring applies. The primary signal is the storage scheme reported by the
XeFM `Path` abstraction (`get_scheme()`); string heuristics are a fallback for
plain `str`/`pathlib` paths that don't expose it.

```python
def _detect_monitoring_mode(self, path: Path) -> str:
    """
    Detect appropriate monitoring mode for a path.

    Returns:
        "native" - Use OS-native monitoring
        "polling" - Use fallback polling mode (local paths only)
        "disabled" - Monitoring not possible (remote/virtual backends)
    """
    # Preferred: watchdog only understands local ('file') paths; disable
    # monitoring for every other backend (s3, ssh, scp, ftp, archive, …).
    get_scheme = getattr(path, "get_scheme", None)
    if callable(get_scheme):
        scheme = get_scheme()
        if scheme is not None and scheme != "file":
            return "disabled"

    path_str = str(path)

    # Fallback heuristics for plain str/pathlib paths without get_scheme().
    if path_str.startswith(('s3:', '/s3/', 'ssh:', 'sftp:', 'scp:', 'ftp:', 'archive:')):
        return "disabled"

    # Network mounts are real local paths, so polling can watch them.
    if any(p in path_str for p in ['/mnt/', '/net/', '//']) and not path.exists():
        return "polling"

    # Default to native for local paths
    return "native"
```

When `_detect_monitoring_mode()` returns `"disabled"`, `_start_pane_monitoring()`
skips observer creation entirely — it does **not** create an observer, increment
`error_count`, or schedule retries — so browsing an S3/SSH/archive pane no longer
cascades through failing polling fallbacks.


## Configuration

### Configuration Schema

File monitoring configuration is defined in `xefm/_config.py`:

```python
# File monitoring settings
FILE_MONITORING_ENABLED = True                      # Enable/disable automatic file list reloading
FILE_MONITORING_COALESCE_DELAY_MS = 200            # Event coalescing window in milliseconds
FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5         # Maximum reloads per second (rate limiting)
FILE_MONITORING_SUPPRESS_AFTER_ACTION_MS = 1000    # Suppress automatic reloads after user actions (milliseconds)
FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5       # Polling interval for fallback mode (seconds)
```

### Configuration Validation

Configuration validation is performed in `xefm/config.py`:

```python
def validate_config(config):
    errors = []
    
    # Validate enabled flag
    if not isinstance(config.FILE_MONITORING_ENABLED, bool):
        errors.append("FILE_MONITORING_ENABLED must be a boolean")
    
    # Validate coalesce delay
    if not isinstance(config.FILE_MONITORING_COALESCE_DELAY_MS, int) or \
       config.FILE_MONITORING_COALESCE_DELAY_MS < 0:
        errors.append("FILE_MONITORING_COALESCE_DELAY_MS must be a non-negative integer")
    
    # Validate max reloads per second
    if not isinstance(config.FILE_MONITORING_MAX_RELOADS_PER_SECOND, int) or \
       config.FILE_MONITORING_MAX_RELOADS_PER_SECOND < 1:
        errors.append("FILE_MONITORING_MAX_RELOADS_PER_SECOND must be a positive integer")
    
    # Validate suppress after action
    if not isinstance(config.FILE_MONITORING_SUPPRESS_AFTER_ACTION_MS, int) or \
       config.FILE_MONITORING_SUPPRESS_AFTER_ACTION_MS < 0:
        errors.append("FILE_MONITORING_SUPPRESS_AFTER_ACTION_MS must be a non-negative integer")
    
    # Validate fallback poll interval
    if not isinstance(config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S, (int, float)) or \
       config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S <= 0:
        errors.append("FILE_MONITORING_FALLBACK_POLL_INTERVAL_S must be a positive number")
    
    return errors
```

### Runtime Configuration Changes

Monitoring can be toggled at runtime without restarting XeFM:

```python
# In FileManager
def toggle_file_monitoring(self):
    """Toggle file monitoring on/off at runtime."""
    if self.file_monitor_manager.is_monitoring_enabled():
        # Currently enabled - disable it
        self.file_monitor_manager.stop_monitoring()
        self.config.FILE_MONITORING_ENABLED = False
        self.logger.info("File monitoring disabled")
    else:
        # Currently disabled - enable it
        self.config.FILE_MONITORING_ENABLED = True
        self.file_monitor_manager.start_monitoring(
            self.pane_manager.left_pane['path'],
            self.pane_manager.right_pane['path']
        )
        self.logger.info("File monitoring enabled")
```


## Testing Approach

### Dual Testing Strategy

The file monitoring feature uses both unit tests and property-based tests for comprehensive coverage:

**Unit Tests** (`test/test_*.py`):
- Specific examples of each event type (create, delete, modify, rename)
- Platform-specific monitoring initialization
- Configuration loading and validation
- Error handling for specific error conditions
- Integration between FileMonitorManager and FileManager
- UI state preservation during reloads

**Property-Based Tests** (`test/test_*.py` with `@given` decorator):
- Universal properties that hold for all inputs
- Event detection across randomly generated file operations
- Coalescing behavior with varying event patterns
- Rate limiting under high event frequency
- Cursor preservation across random file changes
- Error resilience with randomly injected failures

### Property-Based Testing Framework

**Library**: `hypothesis` (Python property-based testing library)

**Configuration**:
- Minimum 100 iterations per property test
- Tests tagged with property numbers from design document
- Temporary directories for filesystem operations
- Automatic cleanup after each iteration

**Example Property Test**:

```python
from hypothesis import given, strategies as st
import pytest

@given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=20))
@pytest.mark.property_test
def test_property_1_filesystem_event_detection(filenames):
    """
    **Validates: Requirements 1.1, 2.1, 3.1, 4.1**
    
    Property 1: For any filesystem event (create, delete, modify, rename) 
    occurring in the watched directory, the File_Monitor shall detect 
    and report the event.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set up monitoring
        config = MockConfig()
        file_manager = MockFileManager()
        manager = FileMonitorManager(config, file_manager)
        manager.start_monitoring(Path(tmpdir), Path(tmpdir))
        
        # Generate random file operations
        for filename in filenames:
            filepath = Path(tmpdir) / filename
            filepath.write_text("test content")
            time.sleep(0.1)
        
        # Verify events were detected
        time.sleep(0.5)  # Allow coalescing
        assert not file_manager.reload_queue.empty()
```

### Test Organization

**End-to-End Tests** (`test/test_end_to_end_file_monitoring.py`):
- Complete workflow tests
- Dual-pane monitoring
- Directory navigation
- Configuration control
- Runtime toggling
- Error scenarios
- Event coalescing

**Component Tests**:
- `test/test_file_monitor_manager_lifecycle.py` - Manager lifecycle and state
- `test/test_file_monitor_manager_reload_posting.py` - Reload queue posting
- `test/test_xefm_filesystem_event_handler.py` - Event handler filtering
- `test/test_file_monitor_error_handling.py` - Error recovery
- `test/test_file_monitoring_config.py` - Configuration validation
- `test/test_polling_interval.py` - Polling mode behavior
- `test/test_reload_context_preservation.py` - Cursor/scroll preservation

### Running Tests

**All file monitoring tests**:
```bash
python -m pytest test/test_*file_monitor*.py -v
```

**Property-based tests only**:
```bash
python -m pytest test/ -v -m property_test
```

**Specific test file**:
```bash
python -m pytest test/test_end_to_end_file_monitoring.py -v
```

**With coverage**:
```bash
python -m pytest test/test_*file_monitor*.py --cov=xefm --cov-report=html
```


## Code Organization

### File Structure

```
src/
├── xefm/file_monitor_manager.py      # Central monitoring coordinator
├── xefm/file_monitor_observer.py     # Per-directory watcher
├── xefm/app.py                       # FileManager integration
└── _config.py                        # Configuration defaults

test/
├── test_end_to_end_file_monitoring.py              # End-to-end workflow tests
├── test_file_monitor_manager_lifecycle.py          # Manager lifecycle tests
├── test_file_monitor_manager_reload_posting.py     # Reload posting tests
├── test_xefm_filesystem_event_handler.py            # Event handler tests
├── test_file_monitor_error_handling.py             # Error recovery tests
├── test_file_monitoring_config.py                  # Configuration tests
├── test_polling_interval.py                        # Polling mode tests
└── test_reload_context_preservation.py             # Context preservation tests

doc/
├── FILE_MONITORING_FEATURE.md       # End-user documentation
└── dev/
    └── FILE_MONITORING_IMPLEMENTATION.md  # This document
```

### Key Classes and Methods

#### FileMonitorManager

**Public Methods**:
- `start_monitoring(left_path, right_path)` - Start monitoring both panes
- `update_monitored_directory(pane_name, new_path)` - Update monitored directory
- `stop_monitoring()` - Stop all monitoring
- `is_monitoring_enabled()` - Check if monitoring is enabled
- `get_monitoring_mode(path)` - Get monitoring mode for path
- `suppress_reloads(duration_ms)` - Temporarily suppress reloads
- `check_observer_health()` - Check and recover dead observers
- `is_in_fallback_mode()` - Check if any pane is in fallback mode

**Private Methods**:
- `_start_pane_monitoring(pane_name, path)` - Start monitoring single pane
- `_schedule_retry(pane_name, path)` - Schedule monitoring retry
- `_attempt_polling_fallback(pane_name, path)` - Fall back to polling
- `_detect_monitoring_mode(path)` - Detect appropriate mode for path
- `_on_filesystem_event(pane_name, event_type, filename)` - Handle events
- `_check_rate_limit(pane_name)` - Check rate limiting
- `_post_reload_request(pane_name)` - Post reload to queue

#### FileMonitorObserver

**Public Methods**:
- `start()` - Start monitoring
- `stop()` - Stop monitoring
- `is_alive()` - Check if observer is running
- `get_monitoring_mode()` - Get current monitoring mode

**Private Methods**:
- `_detect_platform_and_api()` - Detect platform and API
- `_start_polling_observer()` - Start polling mode observer

#### XeFMFileSystemEventHandler

**Public Methods**:
- `on_created(event)` - Handle file creation
- `on_deleted(event)` - Handle file deletion
- `on_modified(event)` - Handle file modification
- `on_moved(event)` - Handle file move/rename

**Private Methods**:
- `_is_immediate_child(event_path)` - Check if event is immediate child
- `_get_filename(event_path)` - Extract filename from path

### Logger Names

All file monitoring components use the unified logging system:

- **FileMonitorManager**: Logger name `"FileMonitor"`
- **FileMonitorObserver**: Uses logger passed from FileMonitorManager
- **XeFMFileSystemEventHandler**: Uses logger passed from FileMonitorObserver

Example logging:
```python
self.logger.info("Starting monitoring for left pane: /home/user/documents")
self.logger.warning("Falling back to polling mode for right pane")
self.logger.error("Failed to start monitoring: Permission denied")
```


## Performance Considerations

### Resource Usage

**Memory**:
- FileMonitorManager: ~1KB base overhead
- FileMonitorObserver per pane: ~5MB (target, varies by platform)
- Event queue: Minimal (typically < 10 entries)
- Total for dual-pane: ~10MB

**CPU**:
- Native monitoring (idle): < 1% CPU
- Polling mode (idle): ~2-5% CPU (depends on poll interval)
- Event processing: Negligible (< 0.1% per event)

**File Descriptors** (Linux):
- One inotify watch per monitored directory
- System limit: `/proc/sys/fs/inotify/max_user_watches` (default: 8192)
- XeFM uses 2 watches (left + right pane)

### Optimization Strategies

#### Event Coalescing

Batches multiple rapid changes into single reload:

```python
# Without coalescing: 10 events = 10 reloads
# With coalescing (200ms): 10 events in 150ms = 1 reload
```

**Benefits**:
- Reduces UI thrashing
- Improves responsiveness during bulk operations
- Lowers CPU usage

**Trade-offs**:
- Slight delay (200ms) before reload
- Multiple changes appear simultaneously

#### Rate Limiting

Prevents excessive reloads during high-frequency events:

```python
# Maximum 5 reloads per second
# If 20 events occur in 1 second, only 5 reloads execute
```

**Benefits**:
- Prevents UI from becoming unresponsive
- Maintains consistent frame rate
- Protects against event storms

**Trade-offs**:
- Some intermediate states may not be visible
- Eventual consistency (all changes reflected, but not immediately)

#### Suppression After User Actions

Prevents redundant reloads after user-initiated operations:

```python
# User creates file → XeFM reloads immediately
# Monitor detects same change → Suppressed for 1 second
```

**Benefits**:
- Eliminates duplicate reloads
- Improves perceived performance
- Reduces unnecessary work

**Trade-offs**:
- External changes within suppression window are delayed

### Performance Tuning

**For High-Frequency Environments**:
```python
FILE_MONITORING_COALESCE_DELAY_MS = 500        # Increase coalescing window
FILE_MONITORING_MAX_RELOADS_PER_SECOND = 2     # Reduce reload frequency
```

**For Low-Latency Requirements**:
```python
FILE_MONITORING_COALESCE_DELAY_MS = 100        # Decrease coalescing window
FILE_MONITORING_MAX_RELOADS_PER_SECOND = 10    # Increase reload frequency
```

**For Resource-Constrained Systems**:
```python
FILE_MONITORING_ENABLED = False                # Disable monitoring entirely
# Or use polling with longer interval:
FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 10  # Poll every 10 seconds
```


## Debugging and Troubleshooting

### Logging

All file monitoring operations are logged using XeFM's unified logging system (via `getLogger`), so their messages appear in the in-app log pane alongside everything else.

**Key Log Messages**:

```
# Initialization
INFO [FileMonitor] File monitoring initialized (enabled: True)
INFO [FileMonitor] Starting monitoring for left pane: /home/user/documents
INFO [FileMonitor] Monitoring mode: native (inotify)

# Events
INFO [FileMonitor] Filesystem event: created - newfile.txt in left pane
INFO [FileMonitor] Coalescing events for left pane (200ms window)
INFO [FileMonitor] Posting reload request for left pane

# Errors
WARNING [FileMonitor] Failed to start native monitoring: Permission denied
WARNING [FileMonitor] Falling back to polling mode for left pane
ERROR [FileMonitor] Observer for right pane died, attempting recovery

# Mode transitions
INFO [FileMonitor] Monitoring mode changed: native -> polling (reason: connection lost)
```

### Common Issues

#### Issue: Monitoring Not Working

**Symptoms**: File changes not reflected automatically

**Diagnosis**:
1. Check if monitoring is enabled: `FILE_MONITORING_ENABLED = True`
2. Check log for initialization errors
3. Verify observer is alive: Look for "Observer died" messages
4. Check if in fallback mode: Look for "Falling back to polling" messages

**Solutions**:
- Enable monitoring in configuration
- Check directory permissions
- Increase system watch limits (Linux: `fs.inotify.max_user_watches`)
- Use polling mode for unsupported filesystems

#### Issue: High CPU Usage

**Symptoms**: XeFM consuming excessive CPU

**Diagnosis**:
1. Check if in polling mode: Look for "Polling mode active" in logs
2. Check poll interval: `FILE_MONITORING_FALLBACK_POLL_INTERVAL_S`
3. Check for event storms: Look for many rapid events in logs

**Solutions**:
- Increase polling interval: `FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 10`
- Increase coalescing delay: `FILE_MONITORING_COALESCE_DELAY_MS = 500`
- Reduce max reloads: `FILE_MONITORING_MAX_RELOADS_PER_SECOND = 2`
- Disable monitoring for problematic directories

#### Issue: Delayed Updates

**Symptoms**: Changes take several seconds to appear

**Diagnosis**:
1. Check coalescing delay: `FILE_MONITORING_COALESCE_DELAY_MS`
2. Check if rate limited: Look for "Rate limit exceeded" in logs
3. Check if suppressed: Look for "Reload suppressed" in logs
4. Check if in polling mode: Polling has inherent delay

**Solutions**:
- Decrease coalescing delay: `FILE_MONITORING_COALESCE_DELAY_MS = 100`
- Increase rate limit: `FILE_MONITORING_MAX_RELOADS_PER_SECOND = 10`
- Decrease suppression time: `FILE_MONITORING_SUPPRESS_AFTER_ACTION_MS = 500`
- Use native monitoring instead of polling

#### Issue: Cursor Jumps After Reload

**Symptoms**: Cursor moves to unexpected file after automatic reload

**Diagnosis**:
1. Check if selected file was deleted
2. Check log for "Selected file deleted, moved cursor to nearest file"
3. Verify nearest file algorithm is working correctly

**Solutions**:
- This is expected behavior when selected file is deleted
- Cursor moves to nearest file alphabetically
- If unexpected, check for race conditions in file operations

### Diagnostic Commands

**Check monitoring status**:
```python
# In XeFM Python console or debug session
file_monitor_manager.is_monitoring_enabled()
file_monitor_manager.get_monitoring_mode(Path("/path/to/dir"))
file_monitor_manager.is_in_fallback_mode()
```

**Check observer health**:
```python
file_monitor_manager.check_observer_health()
```

**Manually trigger reload**:
```python
file_manager.reload_queue.put("left")
```

**Check queue status**:
```python
file_manager.reload_queue.qsize()  # Number of pending reloads
```


## Extension Points

### Adding New Event Types

To add support for new filesystem event types:

1. **Update XeFMFileSystemEventHandler**:
```python
def on_new_event_type(self, event):
    """Handle new event type."""
    if not self._is_immediate_child(event.src_path):
        return
    
    filename = self._get_filename(event.src_path)
    self.callback("new_event_type", filename)
```

2. **Update FileMonitorManager event handling**:
```python
def _on_filesystem_event(self, pane_name: str, event_type: str, filename: str):
    # Add handling for new event type
    if event_type == "new_event_type":
        # Custom logic for new event type
        pass
    
    # Continue with normal event processing
    # ...
```

3. **Add tests** for new event type in `test/test_xefm_filesystem_event_handler.py`

### Adding New Monitoring Backends

To add support for new storage backends:

1. **Update backend detection** in `FileMonitorManager._detect_monitoring_mode()`:
```python
def _detect_monitoring_mode(self, path: Path) -> str:
    path_str = str(path)

    # Add detection for new backend. Remote/virtual backends that aren't
    # mounted in the local filesystem must return "disabled" — watchdog
    # (even PollingObserver) can only watch real local paths. Return
    # "polling" only for backends that DO present as local paths.
    if path_str.startswith('newbackend://'):
        return "disabled"  # or "native"/"polling" if it maps to a local path

    # ... existing detection logic ...
```

2. **Add backend-specific observer** (if needed):
```python
class NewBackendObserver(FileMonitorObserver):
    """Observer for new backend."""
    
    def start(self) -> bool:
        # Backend-specific initialization
        pass
```

3. **Add tests** for new backend in `test/test_end_to_end_file_monitoring.py`

### Custom Event Filtering

To add custom event filtering logic:

1. **Extend XeFMFileSystemEventHandler**:
```python
class CustomFileSystemEventHandler(XeFMFileSystemEventHandler):
    """Custom event handler with additional filtering."""
    
    def __init__(self, callback, watched_path, filter_func=None):
        super().__init__(callback, watched_path)
        self.filter_func = filter_func
    
    def on_created(self, event):
        # Apply custom filter
        if self.filter_func and not self.filter_func(event):
            return
        
        # Continue with normal processing
        super().on_created(event)
```

2. **Use custom handler** in FileMonitorObserver:
```python
self.event_handler = CustomFileSystemEventHandler(
    callback=self._on_event,
    watched_path=str(self.path),
    filter_func=lambda event: not event.src_path.endswith('.tmp')
)
```

### Monitoring Multiple Directories Per Pane

To monitor additional directories beyond the current pane directories:

1. **Extend FileMonitorManager state**:
```python
self.additional_monitors = {}  # Additional watches beyond panes
```

2. **Add method to start additional monitoring**:
```python
def start_additional_monitoring(self, watch_id: str, path: Path, callback):
    """Start monitoring an additional directory."""
    observer = FileMonitorObserver(path, callback, self.logger)
    if observer.start():
        self.additional_monitors[watch_id] = observer
```

3. **Update cleanup** to stop additional monitors:
```python
def stop_monitoring(self):
    # Stop pane monitors
    # ... existing logic ...
    
    # Stop additional monitors
    for watch_id, observer in self.additional_monitors.items():
        observer.stop()
    self.additional_monitors.clear()
```


## Future Enhancements

### Potential Improvements

1. **Selective File Monitoring**
   - Monitor only specific file types (e.g., only `.txt` files)
   - Ignore patterns (e.g., `.git/`, `node_modules/`)
   - User-configurable filters

2. **Event Aggregation**
   - Provide detailed event information to UI
   - Show "3 files created, 2 deleted" instead of just reloading
   - Allow user to review changes before accepting

3. **Smart Coalescing**
   - Adaptive coalescing delay based on event frequency
   - Different delays for different event types
   - Learn user patterns over time

4. **Recursive Monitoring**
   - Option to monitor subdirectories
   - Configurable depth limit
   - Efficient handling of large directory trees

5. **Network Optimization**
   - Smarter polling for network filesystems
   - Detect network disconnection and pause monitoring
   - Resume monitoring when connection restored

6. **Performance Monitoring**
   - Track monitoring overhead (CPU, memory, I/O)
   - Expose metrics via logging or UI
   - Automatic adjustment based on system load

7. **Event History**
   - Keep history of recent filesystem events
   - Allow user to review what changed
   - Undo/redo support based on event history

### Known Limitations

1. **Subdirectory Events**
   - Currently only monitors immediate children
   - Subdirectory changes not detected
   - Workaround: Navigate into subdirectory to monitor it

2. **Archive Paths**
   - Cannot monitor inside archives (zip, tar, etc.)
   - Archives are read-only snapshots
   - Workaround: Extract archive to monitor contents

3. **Remote Filesystems**
   - Some network mounts don't support native monitoring
   - Falls back to polling (higher latency, CPU usage)
   - Workaround: Increase poll interval to reduce overhead

4. **System Limits**
   - Linux: Limited by `fs.inotify.max_user_watches`
   - macOS: Limited by system file descriptor limits
   - Windows: Buffer overflow possible with many rapid changes
   - Workaround: Increase system limits or use polling

5. **Event Ordering**
   - Events may arrive out of order on some platforms
   - Coalescing can hide intermediate states
   - Workaround: Disable coalescing for strict ordering

### Migration Notes

If upgrading from a version without file monitoring:

1. **Configuration Migration**
   - New configuration options added with sensible defaults
   - No action required unless customization desired
   - Old configurations remain compatible

2. **Performance Impact**
   - Minimal impact on most systems (< 1% CPU, ~10MB RAM)
   - May need tuning on resource-constrained systems
   - Can be disabled entirely if needed

3. **Behavior Changes**
   - File lists now update automatically
   - May surprise users expecting manual refresh
   - Can be disabled via configuration

4. **Testing Considerations**
   - Automated tests may need adjustment
   - Tests that create files should account for automatic reloads
   - Use `suppress_reloads()` in tests if needed


## References

### Related Documentation

- **End-User Documentation**: `doc/FILE_MONITORING_FEATURE.md`
- **Design Document**: `.kiro/specs/automatic-file-list-reloading/design.md`
- **Requirements Document**: `.kiro/specs/automatic-file-list-reloading/requirements.md`
- **Tasks Document**: `.kiro/specs/automatic-file-list-reloading/tasks.md`

### Source Files

- **FileMonitorManager**: `xefm/file_monitor_manager.py`
- **FileMonitorObserver**: `xefm/file_monitor_observer.py`
- **FileManager Integration**: `xefm/app.py`
- **Configuration**: `xefm/_config.py`
- **Configuration Manager**: `xefm/config.py`

### Test Files

- **End-to-End Tests**: `test/test_end_to_end_file_monitoring.py`
- **Manager Lifecycle**: `test/test_file_monitor_manager_lifecycle.py`
- **Reload Posting**: `test/test_file_monitor_manager_reload_posting.py`
- **Event Handler**: `test/test_xefm_filesystem_event_handler.py`
- **Error Handling**: `test/test_file_monitor_error_handling.py`
- **Configuration**: `test/test_file_monitoring_config.py`
- **Polling Interval**: `test/test_polling_interval.py`
- **Context Preservation**: `test/test_reload_context_preservation.py`

### External Dependencies

- **watchdog**: Cross-platform filesystem monitoring library
  - Documentation: https://python-watchdog.readthedocs.io/
  - GitHub: https://github.com/gorakhargosh/watchdog
  - Version: 4.0.0+

- **hypothesis**: Property-based testing framework
  - Documentation: https://hypothesis.readthedocs.io/
  - GitHub: https://github.com/HypothesisWorks/hypothesis
  - Version: 6.0.0+

### Platform-Specific Documentation

- **Linux inotify**: https://man7.org/linux/man-pages/man7/inotify.7.html
- **macOS FSEvents**: https://developer.apple.com/documentation/coreservices/file_system_events
- **Windows ReadDirectoryChangesW**: https://docs.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-readdirectorychangesw

### Related XeFM Systems

- **Logging System**: `doc/dev/LOGGING_SYSTEM.md`
- **Configuration System**: `xefm/config.py`
- **File List Manager**: `xefm/file_list_manager.py`
- **Pane Manager**: `xefm/pane_manager.py`

---

**Document Version**: 1.0  
**Last Updated**: 2024  
**Author**: XeFM Development Team  
**Maintained By**: XeFM Core Contributors

