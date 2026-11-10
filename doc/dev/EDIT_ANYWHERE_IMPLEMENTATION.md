# Edit Anywhere and Rename in the Editor — Implementation

Issue #581, from discussion #470. Two features that send more editing through
`TEXT_EDITOR`, rather than adding an editor to XeFM.

## Remote editing (`xefm/remote_edit.py`)

`EditSessions` (one per app, created lazily by `XeFMApp.edit_sessions`) maps
each remote path to an `EditSession`. A session holds:

- `local`, the copy's path;
- `remote_state`, the remote file's `(mtime, size)` when the copy last matched
  it;
- `sent_digest`, a SHA-256 of the content the remote holds;
- `seen_stat`, the copy's `(mtime_ns, size)` at the last poll.

The copy is *pending* when its digest differs from `sent_digest`.

### Flow

`XeFMApp._edit_entries` sends a non-local entry to `_edit_remote` only when
`can_write_back(entry)` holds. That means the backend declares
`write_operations`; archives never do, and `_is_archive` is checked as well.
Everything else is refused with a log line, so archive write-back is out of
scope.

1. `_edit_remote` runs `EditSessions.open` for each entry in a `Task`. Opening
   a session is a remote round trip.
2. `on_done` hands the copies back to `_edit_entries` as local paths. They then
   get the normal editor resolution: FILE_ASSOCIATIONS first, then
   TEXT_EDITOR, batched per program.
3. When the editor returns, `_poll_edit_sessions(reschedule=False)` runs once.
   A blocking terminal editor's save is uploaded right away, without waiting
   for a timer. In desktop mode the editor is detached (`_run_editor`, #644)
   and returns at once, so the timer picks up its saves.
4. `_schedule_edit_poll` keeps one `panel.call_later` timer
   (`_EDIT_POLL_SECONDS`) armed while any session exists. Each poll calls
   `EditSessions.saved()`. That costs one `os.stat` per copy; a hash is taken
   only when the stat moved, and a session is reported only when the content
   differs from what the remote holds.
5. `_upload_edits` runs the uploads as a `Task`. `EditSessions.upload` re-stats
   the remote and raises `RemoteChanged` before writing anything if the stat
   differs from `remote_state`. The worker then asks through `Task.ask`
   (Overwrite / Keep Remote) and uploads with `force=True` on Overwrite.
6. Failures and declines set `session.error`, leave the copy pending, log the
   problem, and show a message box naming the copy.

A poll that finds another task active skips that round and tries again later.
Nothing is lost by waiting, because an unsent copy stays pending.

### The fresh stat

SSH and S3 cache stats (30 s and 60 s TTL), so a conflict check could read a
stat from before the remote changed. `PathImpl.forget_cached_metadata()`
(default: no-op) lets a backend drop what it remembers about a path.
`SSHPathImpl` invalidates its `SSHCache` entry; `S3PathImpl` clears its
instance metadata and its `S3Cache` key. `Path` delegates to the backend.

### Copies on disk

`local_copy_path` maps `scheme://authority/a/b` to
`~/.xefm/edit/scheme/authority/a/b`. Each component has characters that are
invalid on any platform replaced, and `..` neutralized, so a remote name can't
escape the root. A download is written to `name.xefm-download` and moved into
place with `os.replace`.

The lifecycle rules protect unsent edits:

- `open()` on a pending session reuses the copy and does not download again.
- `close_all()` (called from `_quit`) deletes only clean copies, prunes empty
  mirror directories, and returns the pending sessions, which the app logs.

## Rename in the editor (`xefm/rename_in_editor.py`)

The module is pure:

- `names_text(files)` writes NFC names one per line. It refuses names
  containing a line break (`UnlistableName`).
- `parse_plan(files, text)` matches lines to files by position. It normalizes
  CRLF and a missing final newline and strips nothing else. It returns a
  `RenamePlan` with `renames` or with per-line `errors`:
  - line count mismatch;
  - invalid name (`xefm.rename_check.is_valid_name`, shared with batch rename);
  - two lines claiming one name in a directory, including the name of a batch
    file that keeps its name;
  - a name that exists on disk and is not being vacated by the batch, unless
    the file found there is the one being renamed, in another case
    (`is_itself`: casefold-equal names and `samefile`).

  "One name" is decided the way the directory's disk decides it
  (`xefm.rename_check`): `folding_dirs` looks one batch file per directory up
  under its name with the case swapped, and `landing_key` casefolds names in
  the directories where that finds the file. So on a disk that folds case,
  `b.txt` is taken when `B.txt` leaves the batch (#869), and `X.txt` and
  `x.txt` on two lines collide; where case matters, `foo.txt -> Foo.txt` does
  not skip the existence check and cannot replace a separate `Foo.txt` (#873).
  A directory whose batch names have no cased letter counts as folding, the
  cautious side. The rename prompt and the batch rename dialog use the same
  module (`is_itself`, and `landing_key` for the dialog's row-against-row
  check).
- `apply_plan(plan, rename)` renames in three phases:
  1. Entries whose target is another renamed entry's current name, compared
     with `landing_key`, are parked under `.xefm-rename-<i>-<hex>`.
  2. Direct renames run.
  3. Parked entries move to their targets.

  By phase 3 every target has been vacated, so swaps, cycles and shifts work.
  A failure in phase 3 names the temporary file in its error.

`XeFMApp.rename_in_editor` writes the list with `tempfile.mkstemp`, and
`_rename_edit_round` runs the editor through `_run_editor`, which hands over
the terminal and waits in terminal mode and detaches in desktop mode (#644). An
editor that cannot be started drops the list. If the list is unchanged and the
editor returned quickly (under `_EDITOR_RETURNED_AT_ONCE`) or XeFM is in
desktop mode, the editor is assumed to be a window that is still open. In that case an Apply/Cancel box waits for the user, which is the
explicit apply step the discussion asked for. Otherwise
`_review_rename_list` shows the errors (Edit Again / Cancel) or the
`old → new` preview (Rename / Edit Again / Cancel). The preview is capped at
`_RENAME_PREVIEW_ROWS`. `_apply_rename_plan` releases archive handles before
each rename, as batch rename does, and keeps the cursor on the focused file
under its new name.

The regex batch rename (`R` on a selection) is unchanged. Rename in the editor
has its own action, `rename_in_editor`, bound to `Shift-R`.

## Tests

- `test/test_rename_in_editor.py`: list format, plan validation, swaps and
  cycles on disk, the failure message for a parked file, and the app round
  trip with `subprocess.run` mocked (confirm, cancel, edit again, the GUI
  Apply step).
- `test/test_rename_case_folding.py`: every rename path against an in-memory
  disk that folds case and one that does not, plus a real-disk test for
  whichever kind the host has.
- `test/test_remote_edit.py`: copy paths, sessions against a fake writable
  remote (save detection, conflict, force, reopen, close), and the app flow
  (upload on return, poll-found save, conflict prompt, loud failure, read-only
  refusal, quit cleanup).

## Hand checks owed

- Real SSH and S3 round trips, including a conflict from a second client.
- A GUI editor that saves by replacing the file (VS Code's safe write) on
  macOS and Windows.
- Windows paths for `~/.xefm/edit/` with long remote paths.
