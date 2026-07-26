# File Operations System

## Overview

Copy, move, duplicate, and delete are provided by a single class, `FileOperationService` (`xefm/file_operations.py`). It confirms the operation on the main thread, then runs the actual work as a background **task** (see [Task Framework](TASK_FRAMEWORK_IMPLEMENTATION.md)) whose body is one **linear** function — prepare → resolve conflicts → count → execute, top to bottom. There is no state machine and no separate UI / executor / list-manager split; the earlier four-layer design was removed in the PuiKit port.

The same service instance serves any view. `XeFMApp` owns one (`self._fileops = FileOperationService(config, self.tasks)`); a full-window modal such as the directory-diff viewer can construct its own and pass a higher `z` so its dialogs stack above itself.

## Copy operation — end to end

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant App as XeFMApp
    participant Svc as FileOperationService
    participant Mgr as TaskManager + ProgressDialog
    participant W as worker thread — _run()

    U->>App: press C (copy)
    App->>Svc: copy(panel, targets, dest_dir, on_complete)
    Svc->>U: CONFIRM_COPY message box (if enabled)
    U-->>Svc: confirm
    Svc->>Mgr: submit(task, run=_run)
    Mgr->>U: show ProgressDialog (modal)
    Mgr->>W: spawn worker
    W->>W: _resolve() — build plan of survivors
    loop each colliding destination
        W->>U: ask() → ConflictDialog (via pump)
        U-->>W: Overwrite / Skip / Keep both / Cancel
    end
    W->>W: _count() → set progress total
    loop each planned target
        W->>W: checkpoint(); _execute_one(); update progress
    end
    W-->>Mgr: result {done, skipped, failed, items, errors, cancelled}
    Mgr->>U: close dialog
    Mgr->>App: on_complete(result) → summary in the log
```

## Public API

```python
FileOperationService(config, tasks: TaskManager | None = None)
```

Each entry point takes the `panel` to draw on plus keyword options (`on_complete`, `log`, `z`, `background`):

| Method | Destination | Confirm flag | Conflict handling |
|---|---|---|---|
| `copy(panel, targets, dest_dir, …)` | `dest_dir/name` | `CONFIRM_COPY` | per-file prompt |
| `move(panel, targets, dest_dir, …)` | `dest_dir/name` | `CONFIRM_MOVE` | per-file prompt |
| `duplicate(panel, targets, dest_dir, …)` | in place (source's own dir) | `CONFIRM_DUPLICATE` | none — always auto-renamed `name (N)` |
| `delete(panel, targets, …)` | — | `CONFIRM_DELETE` (default button = Cancel) | — |

`_start` shows the relevant `CONFIRM_*` message box (skipped when its config flag is off); on confirm, `_submit` builds a `Task` and hands it to `TaskManager.submit(run=self._run, …)`.

## The linear worker (`_run`)

Runs on the task thread, top to bottom:

1. **Plan.** Build a list of `(target, dest_base, overwrite)`:
   - **delete** — trivial (one entry per target).
   - **duplicate** — pre-plan a fresh ` (N)` name per target (an in-place copy always collides, so it never prompts).
   - **copy / move** — `_resolve` checks each destination for an existing file and prompts only for collisions.
2. **Count.** `_count` recursively totals the nodes and bytes to process, so the progress bar is determinate. A move that stays within one *filesystem* is a single atomic rename, so it counts as one node and its subtree is never walked (`_is_atomic_move`); a move to another filesystem is walked like a copy, because that is what it is.
3. **Execute.** For each planned target: `task.checkpoint()` (cancellation point), then `_execute_one`, updating `task.progress`. Per-target exceptions are recorded in `errors` and processing continues; a `Cancelled` unwinds the loop.

### Result summary

`_run` returns a dict the caller reports via `format_op_summary` / `format_op_errors`:

| Key | Meaning |
|---|---|
| `done` / `skipped` / `failed` | counts of **top-level targets** (what the user selected) |
| `items` | total individual entries actually processed (recursive) |
| `errors` | list of `(name, message)` for failed targets |
| `cancelled` | `True` if a checkpoint or a "Cancel" conflict choice unwound the run |

A top-level target is `done` if any of its entries succeeded; `failed` only if it produced nothing and raised. Inner file failures stay in `errors` without sinking the whole target.

## Conflict resolution (`ConflictDialog`)

For copy/move, `_resolve` prompts per collision through the task's UI bridge — `task.ask(_conflict_prompt(...))` pushes a `ConflictDialog` (a `FocusContainer` + `Widget`) that stacks just above the progress dialog. It offers four actions plus an **apply-to-all-remaining** checkbox, and reports `(action, apply_to_all)`:

| Action | Key | Effect |
|---|---|---|
| Overwrite | `o` | replace the destination (`overwrite=True`) |
| Skip | `s` | leave it; increment `skipped` |
| Keep both | `k` | write to a fresh `name (N)` (via `_unique_dest`) |
| Cancel | `c` / `Esc` | raise `Cancelled` — abort the whole operation |

`a` / Space toggles apply-to-all, Tab moves focus, Enter activates the focused button. Left/Right walk the button row (wrapping at its ends, as `MessageBox` does); Up/Down hop between the row and the checkbox above it, returning to the button last focused. When apply-to-all is checked, the chosen action is reused for every remaining collision without prompting.

**Skip is the default** (`_DEFAULT_CONFLICT_ACTION`): it starts focused *and* wears the accent `primary` fill, while the other three are `secondary`. The two must name the same button — the accent reads as "this is what Enter does", so it belongs on the safe resolution, matching the app's other destructive confirms (Delete, archive overwrite), which put the accent on Cancel.

## Duplicate

In-place duplication (GitHub issue #192) is a thin `"duplicate"` operation kind layered onto the shared copy engine, plus app wiring for the two entry points. No new copy/rename logic was written — it reuses `_unique_dest()` and the existing threaded task pipeline.

### Engine — `xefm/file_operations.py`

`"duplicate"` is registered alongside `copy`/`move`/`delete`:

- `_VERB["duplicate"] = "Duplicate"`, `_OP_TYPE["duplicate"] = OperationType.COPY`.
- `FileOperationService.duplicate(panel, targets, dest_dir, …)` mirrors `copy()` and calls `_start(..., "duplicate", ...)`. `dest_dir` is the source's own directory.

It differs from copy in exactly one place — plan building in `_run()`. A duplicate always collides with itself, so it **never prompts**; instead every target is pre-planned to a fresh ` (N)` name up front:

```python
elif kind == "duplicate":
    plan = [(t, _unique_dest(dest_dir, t.name, is_dir=t.is_dir()), False)
            for t in targets]
    result["created"] = [dest.name for _t, dest, _o in plan]
```

Because distinct targets in one directory have distinct names, computing all destinations against the pre-op filesystem state is collision-free (unlike duplicating the *same* file twice, which cannot happen — targets are distinct list entries). `result["created"]` carries the new names back to the caller for cursor placement.

Everything else falls through the copy path: `_count()` walks the plan, `_execute_one()` routes to `_copy_tree()` (the `if kind == "move"` source-delete is skipped, so the original is never removed), and the per-file log line reads "Duplicated" via the verb map `{"move": "Moved", "duplicate": "Duplicated"}.get(kind, "Copied")`.

The confirm prompt in `_start()` gets a duplicate-specific line ("Duplicate **N** item(s) in `<dir>`?") and honors `CONFIRM_DUPLICATE` through the existing `getattr(config, f"CONFIRM_{verb.upper()}", True)` — no special casing needed. `CONFIRM_DUPLICATE = True` lives in `xefm/_config.py`.

### App wiring — `xefm/app.py`

Two entry points, one shared runner:

- `duplicate_files()` — guards (virtual pane, read-only archive, empty targets), gathers `_selected_or_focused(pane)`, then delegates to `_run_duplicate`. Returns `True` on a synchronous guard bail, `False` after handoff — same contract as `copy_files()`.
- `_run_duplicate(pane, targets)` — calls `self._fileops.duplicate(...)` with `pane["path"]` as the destination. `on_complete` clears the source selection, refreshes via `_refresh(pane, on_ready=lambda p: _select_by_name(p, created[0]))` so the cursor lands on the new copy, logs `format_op_summary("Duplicate", …)`, and reports failures.

Reachability (no default key binding):

- Dispatch: `elif action == "duplicate_files": return self.duplicate_files()` — so a user-defined `duplicate_files` key binding works.
- Menu bar (`_build_menu` → File menu) and right-click context menu (`_show_context_menu`): a **Duplicate** item after **Rename…**.

The same-directory copy relaxation lives in `_transfer()`: when `dest_dir == src_pane["path"]` and `kind == "copy"`, it routes to `_run_duplicate(src_pane, targets)` instead of logging the old "source and destination are the same directory" error. Move keeps that error.

### Tests

`test/test_file_operations.py` — the `cfg` fixture sets `CONFIRM_DUPLICATE = False` for headless runs; tests exercise file, directory, and multi-target duplication (each getting its own ` (N)`) plus the "Duplicated" log line, all via the existing `_run_sync(svc, svc.duplicate, …)` harness.

## Helpers

- `recursive_delete(entry)` — delete a file or directory tree.
- `_unique_dest(dest_dir, name, is_dir=…)` — the shared ` (N)` non-colliding-name scheme (used by duplicate and "Keep both").
- `_is_atomic_move(kind, target, dest_dir)` — true when a move stays within one *filesystem* (a single rename); anything wider copies the tree then deletes the source.
- `_entry_device(path)` — `st_dev` of the filesystem holding `path`, or `None` when it isn't local / can't be stat'ed.

  One storage backend is not one filesystem. `rename` only works inside a single filesystem, so a local move to an external drive, another partition, or a network share is really a copy followed by a delete — it takes as long as a copy and needs the same feedback. `_is_atomic_move` therefore compares schemes *and* devices: the device holding the source's parent (where its directory entry lives) against the one holding `dest_dir` (where the new entry lands). When either device is unknown the scheme test decides alone, which is safe: `Path.move_to` still falls back to copy+delete on `EXDEV`, so the only cost of guessing "atomic" is an unprogressed move rather than a wrong one.
- `format_op_summary(verb, result)` / `format_op_errors(verb, result)` — human-readable reporting from the result dict.

## Integration

- `XeFMApp.__init__` — `self.tasks = TaskManager()`, `self._fileops = FileOperationService(self.config, self.tasks)`.
- `XeFMApp.copy_files()` / `move_files()` / `duplicate_files()` / `delete_files()` gather the active pane's selection and delegate to `self._fileops`, passing an `on_complete` that refreshes panes and logs the summary.

## References

- [Task Framework](TASK_FRAMEWORK_IMPLEMENTATION.md)
- [Task Cancellation](TASK_FRAMEWORK_IMPLEMENTATION.md#cancellation)
- [Progress Manager System](PROGRESS_MANAGER_SYSTEM.md)
- [Path Polymorphism System](PATH_POLYMORPHISM_SYSTEM.md) — storage-agnostic operations behind `Path`
