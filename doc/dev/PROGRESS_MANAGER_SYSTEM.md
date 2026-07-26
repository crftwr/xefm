# Progress Manager System

Module: `xefm/progress_manager.py`

`ProgressManager` tracks the state of one long-running file operation and formats
it for display. It is deliberately small: it holds the current operation's counts
and current item, drives a `ProgressAnimator` frame, and renders a status line or
rich text segments. It does **not** own threads, cancellation, priorities, time
estimates, or persistence — those belong to the task layer (`xefm/task.py`)
and the file-operations worker (`xefm/file_operations.py`).

## Scope

What `ProgressManager` does:

- Track a single active operation (`OperationType`, total, processed, current
  item, byte progress, error count, and a "still counting" flag).
- Advance a spinner frame via an internal `ProgressAnimator`.
- Format the operation as a plain status line or as layout segments.
- Optionally push updates to a `progress_callback` (throttled).

What it does **not** do (handled elsewhere):

- Threading and the worker loop → `TaskManager` / the file-ops worker.
- Cancellation → `Task.checkpoint()` / `Task.request_cancel()` raising
  `Cancelled`.
- Rendering the modal dialog and prompts → `ProgressDialog` (in `xefm/task.py`).

There is no operation priority system, no ETA calculation, and no
resume/replay — earlier drafts of this document described those, but they are not
in the code.

## OperationType

```python
class OperationType(Enum):
    COPY = "copy"
    MOVE = "move"
    DELETE = "delete"
    ARCHIVE_CREATE = "archive_create"
    ARCHIVE_EXTRACT = "archive_extract"
```

## API

```python
ProgressManager(config=None)          # builds its own spinner ProgressAnimator

start_operation(operation_type, total_items, description="", progress_callback=None)
update_operation_total(total_items, description="")   # ends the "counting" phase
update_progress(current_item, processed_items=None)   # None → auto-increment
update_file_byte_progress(bytes_copied, bytes_total)  # per-file byte bar
refresh_animation()                                   # force a callback (no data change)
increment_errors()                                    # bump the error counter
finish_operation()                                    # clears state; callback(None)

is_operation_active() -> bool
get_current_operation() -> dict | None
get_progress_percentage() -> int
get_progress_text(max_width=80) -> str
get_progress_segments() -> list
```

Notes on the real shapes (these differ from older drafts):

- `finish_operation()` takes **no** arguments; it clears state and, if a callback
  is set, calls it once with `None` to clear the display.
- `update_progress(current_item, processed_items=None)` — the first argument is
  the item name; the count auto-increments unless overridden.
- Errors are a simple integer counter (`increment_errors()`), not a structured
  error list.
- The current operation is a plain dict with keys: `type`, `total_items`,
  `processed_items`, `current_item`, `description`, `errors`,
  `file_bytes_copied`, `file_bytes_total`, `counting`.

### Two-phase progress: counting then determinate

An operation starts with `counting=True` and (typically) `total_items=0`, so the
UI shows an indeterminate "Preparing…" state. Once the worker has recursively
counted the work, it calls `update_operation_total(total)`, which flips
`counting` off and makes the primary bar determinate. `update_progress` also
clears `counting` as a safety net.

### Byte-level progress

`update_file_byte_progress(copied, total)` feeds a secondary bar for the current
file. It is only surfaced for files larger than 1 MiB (`file_bytes_total > 1024*1024`),
rendered compactly (e.g. `[15M/32.0G]`); small files show no byte bar.

### Rendering

- `get_progress_text(max_width)` — a single flat line
  (`"⠋ Copying... 42/120 - report.pdf [15M/32.0G]"`), handy for logs and tests.
- `get_progress_segments()` — rich segments for the layout engine
  (`AsIsSegment` + a middle-abbreviating `FilepathSegment` for the filename + an
  `AllOrNothingSegment` for byte progress), so the line degrades gracefully as
  width shrinks.
- `get_progress_percentage()` is available for a bar fraction but is not part of
  the text line.

The spinner frame comes from an internal `ProgressAnimator`
(`pattern_override='spinner'`, `speed_override=0.08`); see
[Progress Animation System](PROGRESS_ANIMATION_SYSTEM.md).

### Update throttling

Callbacks are throttled to at most one per `callback_throttle_ms` (50 ms), with
`force=True` and the final update bypassing the throttle. This is only relevant
when a `progress_callback` is used (push mode). The task UI renders in pull mode
(below), reading state each frame instead.

## Copy progress (worked example)

File copy is the richest consumer of `ProgressManager` and shows how the pieces
fit. The threading and UI belong to the task layer; `ProgressManager` is just the
shared state both sides read and write.

### Threading model

A copy (like move/delete/duplicate) runs as a `Task`:

1. `FileOperations` builds a `Task`, calls `task.progress.start_operation(...)`,
   and hands a `run(task)` closure to `TaskManager.submit`.
2. `TaskManager.submit` shows a `ProgressDialog` for the task and spawns a
   **daemon worker thread** running `run(task)`. On the **main thread** it
   registers an animation tick that, each frame, pumps the task's UI bridge and
   repaints the panel; when the worker signals completion it tears down the
   dialog and reports the result.
3. The worker mutates `task.progress` as it goes; the `ProgressDialog` only
   *reads* that state during `draw`. This pull-based rendering is what keeps the
   spinner and bars moving smoothly — the per-frame repaint re-reads the animator
   (which advances by elapsed time), independent of how often the worker updates
   counts. No separate animation-refresh thread is needed.

Because the worker only ever touches its own `Task`/`ProgressManager` and the
main thread only reads during draw, there is no shared mutable UI state across
the boundary.

### The worker (linear, top-to-bottom)

`FileOperations._run` executes prepare → resolve → execute:

- **Resolve conflicts** first (cheap existence checks). Destination collisions are
  resolved one-by-one through the task's UI bridge (`task.ask(...)`), which posts
  a request the main-thread pump turns into a conflict dialog and blocks on the
  answer — so prompts appear sequentially. Choices: skip, overwrite, keep-both
  (a fresh ` (N)` name), or cancel.
- **Count** the surviving plan recursively (`_count` / `_count_node`) to get
  `total_items`, then `prog.update_operation_total(total_items)` to leave the
  "Preparing…" phase.
- **Execute** each top-level target. Before each unit, `task.checkpoint()` raises
  `Cancelled` if cancellation was requested. `prog.update_progress(name)` marks
  the current entry.

### Byte-level copy

`_copy_file` streams a file through `_copy_bytes` when it is large
(`size >= 1 MiB`) or crosses storage backends; otherwise it uses a plain
`copy_to`. A move to another *filesystem* reaches this path too — it is not a
rename, so `_is_atomic_move` sends it down the copy tree and each large file
drives the byte bar (see [File Operations System](FILE_OPERATIONS_SYSTEM.md)). For local large files it copies in 1 MiB chunks, calling
`prog.update_file_byte_progress(copied, size)` per chunk and checkpointing between
chunks (a cancel deletes the partial file so no stub is left). Cross-storage
copies delegate to `Path.copy_to(..., progress_callback=prog.update_file_byte_progress)`,
letting the backend drive the same byte bar.

### Errors and cancellation

- Per-entry failures are collected as `(path, reason)` and reported to the caller;
  one bad file never aborts the rest of the target. `prog.increment_errors()`
  bumps the visible error count.
- Cancellation flows through `Cancelled` raised from a checkpoint (or a "Cancel"
  conflict choice), unwinding into a clean partial summary. `finish_operation()`
  runs in a `finally` so progress state is always cleared.

## Integration

```python
# One TaskManager per app; each Task owns a ProgressManager as task.progress.
task = Task("Copy…", config=self.config, kind="copy")
task.progress.start_operation(OperationType.COPY, 0, description="")
task_manager.submit(task, panel, run=run, on_done=on_complete)
```

Synchronous mode (used by tests) runs the worker inline with no dialog, and
`task.ask` resolves to its headless default.

## Testing

- Progress calculations: start/update/finish, percentage, counting→determinate
  transition, byte-progress thresholds.
- Text and segment rendering at varying widths.
- Copy/move/delete workers: conflict resolution, per-entry error collection,
  cancellation via checkpoints, and partial-file cleanup.

## Related

- [Progress Animation System](PROGRESS_ANIMATION_SYSTEM.md) — the frame engine.
- `xefm/task.py` — `Task` / `TaskManager` / `ProgressDialog` (threading, UI
  bridge, rendering).
- `xefm/file_operations.py` — the copy/move/delete worker.
- `doc/FILE_OPERATIONS_FEATURE.md` — end-user documentation.
</content>
