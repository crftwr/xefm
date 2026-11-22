# File Monitoring Implementation

## Overview

This document provides technical implementation details for XeFM's automatic file list reloading feature. It is intended for developers who need to understand, maintain, or extend the file monitoring system.

### Purpose

The file monitoring system enables XeFM to automatically detect and reflect filesystem changes made by external applications without requiring manual user refresh actions. This keeps the displayed file list synchronized with the actual filesystem state.

### Key Components

- **FileMonitorManager** (`xefm/file_monitor_manager.py`) - Central coordinator for filesystem monitoring
- **FileMonitorObserver** (`xefm/file_monitor_observer.py`) - Per-directory watcher wrapping watchdog library
- **XeFMFileSystemEventHandler** (`xefm/file_monitor_observer.py`) - Event handler for processing watchdog events
- **XeFMApp Integration** (`xefm/app.py`) - Main application integration and reload handling

### Dependencies

- **watchdog** (v4.0.0+) - Cross-platform filesystem monitoring library
- **queue** (Python stdlib) - Thread-safe communication between monitor and main threads

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                          XeFMApp                             │
│                     (Main Application)                       │
│  - reload_queue: Queue                                       │
│  - file_monitor: FileMonitorManager                          │
└────────────┬────────────────────────────────┬───────────────┘
             │                                 │
             │ creates/manages                 │ re-lists (_list_pane)
             │                                 │
             ▼                                 ▼
┌────────────────────────┐          ┌──────────────────────────┐
│   FileMonitorManager   │          │   FileListManager        │
│  (Monitoring Control)  │          │   (File List Ops)        │
│  - monitoring_state    │          └──────────────────────────┘
│  - coalesce_timers     │
│  - reload_times        │
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
- Posts reload requests to the app's `reload_queue` (thread-safe) and calls
  its `_wake_pump()`
- Implements error recovery with retry logic and fallback mechanisms

**State Management**:
```python
self.monitoring_state = {   # Per pane: path, observer, attempt, error/retry counts, ...
    'left': {...},
    'right': {...}
}
self.coalesce_timers = {'left': None, 'right': None}  # Coalescing timers per pane
self.reload_times = {'left': [], 'right': []}         # Rate limiting timestamps per pane
self.suppressed_paths = {}  # str(path) -> refcount, see suppress_path()
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

#### XeFMApp Integration

**Location**: `xefm/app.py`

**Purpose**: Integrates monitoring into the application's pump.

**Key Integration Points**:

1. **Initialization** (`XeFMApp.__init__`):
```python
self.reload_queue: queue.Queue = queue.Queue()
self._result_queue: queue.Queue = queue.Queue()   # completed async listings
self.file_monitor = FileMonitorManager(self.config, self)
self._fileops.monitor = self.file_monitor          # see Suppression During ...
self._monitored = {"left": None, "right": None}
self._sync_monitored_dirs()
```
The app never calls `start_monitoring()`. `_sync_monitored_dirs()` sees both
panes' paths differ from `_monitored` and calls `update_monitored_directory()`
for each, which posts the start to the monitor worker (see The Monitor Worker).

2. **The pump** (`_pump_monitoring`): one method drains everything that worker
threads produce. It is called from `on_event` (every input event), and either
from `_on_pump_wake` (event-driven backends, woken by `_wake_pump()`) or from
the `_reload_tick` animation tick (poll-loop backends such as the TUI, which
cannot dispatch to the main thread), plus `_loading_tick` while a listing is in
flight:
```python
def _pump_monitoring(self) -> bool:
    self._sync_monitored_dirs()
    self.file_monitor.check_observer_health()
    self._process_reload_queue()        # side effect only; see Absorbing Spurious Reloads
    listed = self._process_result_queue()
    ...
    return listed or loading or ...      # True -> caller re-renders
```

3. **Directory Navigation**: no navigation site knows about monitoring.
`_sync_monitored_dirs()`, on every pump, re-points a pane's watcher when its
path changed:
```python
def _sync_monitored_dirs(self):
    if not self.file_monitor.is_monitoring_enabled():
        return
    for name in ("left", "right"):
        path = self.pane(name)["path"]
        if path != self._monitored[name]:
            self._monitored[name] = path
            self.file_monitor.update_monitored_directory(name, path)
```

4. **Cleanup** (`_quit`):
```python
if getattr(self, "file_monitor", None) is not None:
    self.file_monitor.stop_monitoring()
```


## Threading Model

### XeFM's Event Loop Architecture

The main (UI) thread runs the PuiKit backend's event loop; XeFM does not own a
loop of its own. Work from other threads reaches it through `_pump_monitoring()`,
which runs on the UI thread in one of two ways, chosen in `XeFMApp.__init__` by
`self._event_driven = self.panel.dispatches_to_main_thread`:

- **Event-driven backends** (GUI): there is no idle timer. A producer thread
  calls `_wake_pump()`, which coalesces a burst of signals into one
  `panel.call_on_main_thread(self._on_pump_wake)`; `_on_pump_wake` clears the
  pending flag, pumps, and renders (`_pump_render`) if something changed.
- **Poll-loop backends** (TUI): `panel.request_animation_ticks(self._reload_tick)`
  pumps every frame.

`on_event` also pumps before handling each input event.

### Thread-Safe Communication

Since the monitor thread cannot directly call UI methods, we use a thread-safe queue:

```
UI Thread                             Monitor / timer threads
    │                                      │
    │ _sync_monitored_dirs()              │
    │   update_monitored_directory() ─────>│ start observer (monitor worker)
    │                                      │
    │                                      │ [filesystem change detected]
    │                                      │ coalesce timer → _post_reload_request()
    │                                      │ reload_queue.put(pane_name)
    │ <──────────────────────────── _wake_pump()
    │ _pump_monitoring()                  │
    │   _process_reload_queue()           │
    │     _handle_reload_request(pane)    │
    │       _list_pane(keep_visible=True) ─> listing worker
    │   _process_result_queue()  <──────── result
    │ render if the listing changed       │
```

### Implementation Details

**Queue Creation** (`XeFMApp.__init__`):
```python
self.reload_queue: queue.Queue = queue.Queue()
```
`FileMonitorManager.__init__` keeps a reference to it (`self.reload_queue =
file_manager.reload_queue`).

**Draining** (`XeFMApp._process_reload_queue`, called from `_pump_monitoring`):
```python
def _process_reload_queue(self) -> bool:
    reloaded = False
    while True:
        try:
            pane_name = self.reload_queue.get_nowait()
        except queue.Empty:
            break
        if self._handle_reload_request(pane_name):
            reloaded = True
    return reloaded
```

**Monitor-side posting** (`FileMonitorManager._post_reload_request`, on a
coalesce-timer thread):
```python
self.reload_queue.put(pane_name)
wake = getattr(self.file_manager, "_wake_pump", None)
if wake is not None:
    wake()
```

### The Monitor Worker

Starting a watcher is filesystem work, and watchdog does it on whichever thread
calls `observer.start()`: `BaseThread.start()` runs `on_thread_start()` in the
*caller*, which stats the directory and, in polling mode, `scandir`s all of it
for the emitter's first snapshot. On a slow or unreachable mount that is
seconds.

Until #410 it ran on the UI thread. `_sync_monitored_dirs()` re-points a pane's
watcher from the animation tick whenever that pane's path has changed — so no
navigation site has to know about monitoring — and the re-point called
`_start_pane_monitoring()` inline. Navigating into an SMB share froze the whole
app: the stall detector from #407 caught 4.2 s inside a single
`os.path.exists()`, on the frame that noticed the pane had moved. The listing
itself had been off the UI thread since ASYNC_LISTING_SYSTEM.md; the watcher
that follows it had not.

Now `update_monitored_directory()` only records the pane's new directory and
posts a job:

```
UI thread (animation tick)          Monitor worker ("xefm-monitor")
------------------------------------------------------------------
_sync_monitored_dirs()
  update_monitored_directory()
    _requested_paths[pane] = path
    _post_job("point", ...)  ------>  _start_pane_monitoring()
  returns immediately                   detach old observer (state_lock)
                                        _detect_monitoring_mode()   <- stats
                                        observer.start()            <- blocks
                                        install it   (state_lock)
```

One worker thread, FIFO, so a burst of navigation queues attempts instead of
racing them. Two rules keep that honest:

- **`state_lock` is never held across a start.** The UI thread takes that same
  lock on its own hot path (`check_observer_health()`), so holding it across a
  slow start would relocate the freeze rather than fix it. The lock is taken for
  the bookkeeping at either end and released around the start — see
  `_start_and_adopt()`.
- **Each attempt claims the pane by number.** Every attempt to start an observer
  — a re-point, a retry, the polling fallback — bumps `state['attempt']` and
  remembers the value; only an attempt whose number still matches installs what
  it started, and the rest stop theirs. That is what stops a start that finished
  late from swapping out a newer one and leaking its thread.

A queued re-point the user has already navigated past is dropped unstarted
(`_requested_paths` runs ahead of `state['path']`), so walking down a tree on a
slow mount starts one observer for the directory the user stopped on, not one
per directory passed through. Because that skipped visit is never started, the
give-up verdict of #416 is cleared in `update_monitored_directory()` itself:
leaving an unwatchable directory has to count even when the leaving is coalesced
away.

Retries go the same way: the `threading.Timer` only posts a `"retry"` job when
its backoff elapses, and the attempt itself runs on the worker.

`wait_for_idle(timeout)` waits for the worker to run every job posted so far.
It exists for tests, which used to be able to call `update_monitored_directory()`
and look at `state['observer']` on the next line.

### Thread Safety Guarantees

- `queue.Queue` is thread-safe for put/get operations
- Monitor thread only posts pane names to queue (no UI access)
- Main thread is sole consumer of queue (processes reloads)
- All UI operations (`_handle_reload_request`, installing listings, rendering) occur on the main thread
- FileMonitorManager uses locks only for its own state management
- No observer is started or stopped on the UI thread, and `state_lock` is never
  held while one is (#410)
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
                                                    XeFMApp._handle_reload_request()   
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
       
       # Drop events for a directory one of XeFM's own file operations is
       # mutating (see Suppression During XeFM's Own File Operations)
       if str(state['path']) in self.suppressed_paths:
           return
       
       # Per pane watching this directory: check the rate limit, then
       # (re)arm the coalescing timer (200ms)
       if self.coalesce_timers[pane] is not None:
           self.coalesce_timers[pane].cancel()
       timer = threading.Timer(coalesce_delay_s, coalesced_reload)
       self.coalesce_timers[pane] = timer
       timer.start()
   ```

4. **Coalescing Timer Fires**
   ```python
   def _post_reload_request(self, pane_name: str):
       # Drop it if the directory became suppressed meanwhile
       # Record the reload time for rate limiting, then post to queue
       self.reload_queue.put(pane_name)
       self.file_manager._wake_pump()   # wake the UI thread
   ```

5. **Main Thread Processes Reload**
   ```python
   def _handle_reload_request(self, pane_name):
       pane = self.pm.left_pane if pane_name == "left" else self.pm.right_pane
       if pane.get("virtual") or pane.get("loading"):
           return False   # search results / a listing already in flight

       # Store current context
       anchor = self._cursor_anchor(pane)

       # Re-list on a worker, restoring the cursor when the result lands
       self._list_pane(pane_name, on_ready=lambda p: self._apply_cursor_anchor(p, anchor),
                       keep_visible=True)
       return True
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

1. **Cursor Position**: Stays on the same file if it still exists
2. **Scroll Position**: Maintained when possible
3. **A vanished cursor entry**: Falls to the row that took its place

A reload that installs nothing leaves cursor and scroll exactly where the user put
them — the restore callback never runs.

### Implementation

Nothing here is specific to monitoring: a reload restores the cursor through the
same pair of helpers every in-place re-list uses — a delete, a copy, a sort,
`show_hidden` (see
[`ASYNC_LISTING_SYSTEM.md`](ASYNC_LISTING_SYSTEM.md#holding-the-cursor-across-a-re-list)).

```python
def _handle_reload_request(self, pane_name):
    ...
    # Snapshot the focused row *and the order around it*, before the listing
    # that is about to replace it.
    anchor = self._cursor_anchor(pane)

    def restore(pane):
        self._apply_cursor_anchor(pane, anchor)

    self._list_pane(pane_name, on_ready=restore, keep_visible=True)
```

### Where a vanished cursor entry lands

`_apply_cursor_anchor` walks the **old** order outward from the anchored row,
down first, and lands on the first entry that survived: the row that took its
place, or the one above it when the tail is gone. Because the walk is over the
order the pane was showing, it is right for any sort — by name, size or date,
forward or reversed.

This replaced an alphabetical guess ("where would this name have sorted?"), which
was only ever right for a name-sorted pane and landed somewhere arbitrary on the
others.


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

#### What Counts as a Failed Start

`FileMonitorObserver.start()` checks `path.is_dir()` before it hands the
directory to watchdog. That looks like it only buys a nicer error message, and
#410 proposed dropping it to take a blocking stat off the re-point path — but it
is load-bearing on macOS: FSEvents accepts a path that does not exist and
watches it silently forever, so without the check a vanished directory would
report a healthy observer and never reach the retry chain below. (Polling and
the Windows API both fail loudly on their own.) It is one stat rather than the
two it used to be, and it now runs on the monitor worker, where blocking on a
slow mount costs nothing.

A directory that exists but cannot be listed (`C:\System Volume Information`
for a non-elevated process, a profile's compatibility junction) passes that
check, so `start()` then opens it to list (`os.scandir`, first entry
only). It has to find the `PermissionError` itself: watchdog's Windows
reader opens the directory on a thread of its own, so the native start only
waits 2 s and raises an empty `queue.Empty`, and the thread's traceback goes
to stderr. (A `PermissionError` from either start is still caught too.) No
retry can fix that, so the observer marks itself `unreadable` and the manager gives up at once (`_give_up_unreadable`),
recording `failed_path` as below, with one debug line. The listing has already
said "Permission denied"; before #909 the watcher added fourteen errors and a
warning while it walked the ladder.

#### Giving Up, and Resuming

When the polling fallback fails too, the manager records the *directory* that
could not be watched (`state['failed_path']`) rather than writing off the pane:

- while the pane stays there nothing is retried — there is nothing new to try;
- pointing the pane anywhere else clears the record and monitoring resumes;
- browsing back to it later gets a fresh set of attempts, since the directory may
  have been remounted or recreated in the meantime.

Before #416 this was a per-pane `failed_permanently` flag that nothing ever
cleared. One directory that vanished under the watcher — an unmounted volume, a
directory deleted while the pane sat in it — left that pane unmonitored for the
rest of the session, answering every later navigation with
`Monitoring for right pane has failed permanently, not retrying`.

A pending retry is also abandoned if the pane navigated away while it waited out
its backoff (1s + 2s + 4s is ample time to move on). Installing an observer for
the directory the pane has left would swap out the live one *without stopping
it* — a leaked observer thread — and then feed the pane a stale directory's
events.

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

`XeFMApp._pump_monitoring()` calls this on every drain: a watcher that dies is
silent about it — no events is exactly what a dead watcher looks like — so
nothing else would ever notice. The real work is rate-limited to
`HEALTH_CHECK_INTERVAL_S` (5s), which is what makes it free to ask for from the
UI thread's hot path.


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
XeFM `Path` abstraction (`path.scheme`); string heuristics are a fallback for
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
    scheme = getattr(path, "scheme", None)
    if isinstance(scheme, str) and scheme != "file":
        return "disabled"

    path_str = str(path)

    # Fallback heuristics for plain str/pathlib paths, which have no scheme.
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
FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5       # Polling interval for fallback mode (seconds)
```

### Configuration Validation

Configuration validation is performed in `xefm/config.py` (`ConfigManager.validate_config`; excerpt):

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
    
    # Validate fallback poll interval
    if not isinstance(config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S, (int, float)) or \
       config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S <= 0:
        errors.append("FILE_MONITORING_FALLBACK_POLL_INTERVAL_S must be a positive number")
    
    return errors
```

### Runtime Configuration Changes

There is no runtime on/off toggle. `FileMonitorManager.__init__` reads
`FILE_MONITORING_ENABLED` once into `self.enabled`. `XeFMApp.reload_config`
re-points `self.file_monitor.config` at the reloaded config, so the values the
manager reads on demand (`FILE_MONITORING_COALESCE_DELAY_MS` and
`FILE_MONITORING_MAX_RELOADS_PER_SECOND` per event,
`FILE_MONITORING_FALLBACK_POLL_INTERVAL_S` when an observer is next started)
follow the new config; turning monitoring on or off takes a restart.


## Testing Approach

### Dual Testing Strategy

The file monitoring feature uses both unit tests and property-based tests for comprehensive coverage:

**Unit Tests** (`test/test_*.py`):
- Specific examples of each event type (create, delete, modify, rename)
- Platform-specific monitoring initialization
- Configuration loading and validation
- Error handling for specific error conditions
- Integration between FileMonitorManager and XeFMApp
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
- `test/test_xefm_app_file_monitoring.py` - App wiring: reload queue, cursor/scroll preservation (`ContextPreservation`)

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
xefm/
├── file_monitor_manager.py           # Central monitoring coordinator
├── file_monitor_observer.py          # Per-directory watcher
├── app.py                            # XeFMApp integration
└── _config.py                        # Configuration defaults

test/
├── test_end_to_end_file_monitoring.py              # End-to-end workflow tests
├── test_file_monitor_manager_lifecycle.py          # Manager lifecycle tests
├── test_file_monitor_manager_reload_posting.py     # Reload posting tests
├── test_xefm_filesystem_event_handler.py            # Event handler tests
├── test_file_monitor_error_handling.py             # Error recovery tests
├── test_file_monitoring_config.py                  # Configuration tests
├── test_polling_interval.py                        # Polling mode tests
└── test_xefm_app_file_monitoring.py                # App wiring + context preservation tests

doc/
├── FILE_MONITORING_FEATURE.md       # End-user documentation
└── dev/
    └── FILE_MONITORING_IMPLEMENTATION.md  # This document
```

### Key Classes and Methods

#### FileMonitorManager

**Public Methods**:
- `start_monitoring(left_path, right_path)` - Start monitoring both panes, on the
  calling thread (not for the UI thread; see The Monitor Worker)
- `update_monitored_directory(pane_name, new_path)` - Point a pane's watcher at a
  new directory; returns immediately, the worker does the work
- `wait_for_idle(timeout)` - Wait for the monitor worker to run its queued jobs
- `stop_monitoring()` - Stop all monitoring
- `is_monitoring_enabled()` - Check if monitoring is enabled
- `get_monitoring_mode(path)` - Get monitoring mode for path
- `suppress_path(path)` / `release_path(path)` - Drop events for a directory
  while one of XeFM's own file operations mutates it (refcounted)
- `check_observer_health()` - Check and recover dead observers
- `is_in_fallback_mode()` - Check if any pane is in fallback mode

**Private Methods**:
- `_post_job(kind, pane_name, path)` / `_run_jobs()` - The monitor worker
- `_start_pane_monitoring(pane_name, path)` - Start monitoring single pane
- `_start_and_adopt(pane_name, path, attempt, ...)` - Start an observer with no
  lock held, install it if the attempt still owns the pane
- `_schedule_retry(pane_name, path)` - Schedule monitoring retry
- `_retry_pane_monitoring(pane_name, path)` - Run one retry, on the worker
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

#### Suppression During File Operations

Prevents redundant reloads while XeFM's own copy/move/delete runs: the
mutated directories are suppressed for the operation's duration and the
operation's completion refresh reconciles the panes (see Suppression During
XeFM's Own File Operations).

**Benefits**:
- Eliminates duplicate reloads
- Keeps re-lists from competing with the operation for disk I/O

**Trade-offs**:
- An external change to a suppressed directory shows up only at the
  operation's completion refresh

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
3. Check if suppressed: a file operation into that directory is still running
   (debug log "Suppressing filesystem events for ...")
4. Check if in polling mode: Polling has inherent delay

**Solutions**:
- Decrease coalescing delay: `FILE_MONITORING_COALESCE_DELAY_MS = 100`
- Increase rate limit: `FILE_MONITORING_MAX_RELOADS_PER_SECOND = 10`
- Use native monitoring instead of polling

#### Issue: Cursor Jumps After Reload

**Symptoms**: Cursor moves to unexpected file after automatic reload

**Diagnosis**:
1. Check if the file under the cursor was deleted
2. Verify the cursor anchor is being applied (`_apply_cursor_anchor`)

**Solutions**:
- This is expected behavior when the cursor entry is deleted
- The cursor drops to the row that took its place in the pane's own order
- If unexpected, check for race conditions in file operations

### Diagnostic Commands

**Check monitoring status**:
```python
# In XeFM Python console or debug session
app.file_monitor.is_monitoring_enabled()
app.file_monitor.get_monitoring_mode(Path("/path/to/dir"))
app.file_monitor.is_in_fallback_mode()
```

**Check observer health**:
```python
app.file_monitor.check_observer_health()
```

**Manually trigger reload**:
```python
app.reload_queue.put("left"); app._wake_pump()
```

**Check queue status**:
```python
app.reload_queue.qsize()  # Number of pending reloads
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
   - Use `suppress_path()` / `release_path()` in tests if needed, or fake the
     monitor (as `test/test_xefm_app_file_monitoring.py` does with `FakeMonitor`)


## References

### Related Documentation

- **End-User Documentation**: `doc/FILE_MONITORING_FEATURE.md`

### Source Files

- **FileMonitorManager**: `xefm/file_monitor_manager.py`
- **FileMonitorObserver**: `xefm/file_monitor_observer.py`
- **XeFMApp Integration**: `xefm/app.py`
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
- **App Wiring / Context Preservation**: `test/test_xefm_app_file_monitoring.py`

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

