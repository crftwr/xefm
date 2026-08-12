# Archive System

Canonical developer reference for XeFM's archive support. Two independent paths:

- **Read / browse** — treat an archive as a virtual directory you can navigate,
  view, and copy out of, without extracting. Implemented in `xefm/archive.py`
  (`ArchivePathImpl` + handlers + cache), plugged into the `Path` abstraction.
- **Create / extract** — build a new archive from a selection, or unpack one to a
  directory. Implemented in `xefm/app.py` (the `XeFMApp` create/extract methods), using
  the stdlib `zipfile` / `tarfile` modules directly.

Source of truth is the code; this document summarizes structure and intent, not
every line.

---

## 1. Read / browse path (virtual directory)

Browsing an archive works because `xefm/archive.py` implements the `PathImpl`
interface, so archive contents flow through the same `Path` machinery as local
and S3 paths.

### Archive URI format

```
archive://<absolute_path_to_archive>#<internal_path>

archive:///home/user/data.zip#                  (archive root)
archive:///home/user/data.zip#folder/           (a directory inside)
archive:///home/user/data.zip#folder/file.txt   (a file inside)
```

The `#` separates the archive file path from the internal path. `Path()` detects
the `archive://` scheme and constructs an `ArchivePathImpl` (`xefm/path.py`).

### ArchiveEntry

A `@dataclass` giving a uniform view of an entry across formats: `name`,
`internal_path`, `is_dir`, `size`, `compressed_size`, `mtime`, `mode`,
`archive_type`. Helpers:

- `to_stat_result()` — an `os.stat_result` so archive entries interoperate with
  filesystem-shaped code.
- `from_zip_info(zip_info, archive_type='zip')` / `from_tar_info(tar_info,
  archive_type='tar')` — classmethod factories from `zipfile.ZipInfo` /
  `tarfile.TarInfo`.

### ArchiveHandler and subclasses

`ArchiveHandler` is the base interface for reading an archive: `open()`,
`close()`, `list_entries(internal_path="")`, `get_entry_info(internal_path)`,
`extract_to_bytes(internal_path)`, `extract_to_file(internal_path, target_path)`,
plus context-manager support.

Two concrete handlers exist:

- **`ZipHandler`** — ZIP via `zipfile`. Caches entries on open, with lazy loading
  for large archives (>1000 entries: only shallow structure is cached up front,
  deeper entries load on demand via `getinfo`). Synthesizes virtual directory
  entries for implicit directories. Also carries the encryption read path
  (see §3).
- **`TarHandler(archive_path, compression=None)`** — tar and compressed variants
  (`gz`, `bz2`, `xz`) via `tarfile`. Caches all entries on open and synthesizes
  virtual directory entries the same way.

Both download a remote archive (`is_remote()`) to a temp file on `open()` and
delete it on `close()`.

> There is no RAR / 7z handler in the codebase. To add a format you would write a
> new `ArchiveHandler` subclass and register it in `ArchiveCache._create_handler`,
> but nothing beyond ZIP and TAR is implemented today.

### ArchiveCache

`ArchiveCache(max_open=5, ttl=300)` keeps recently used handlers open so
repeated navigation doesn't re-open the archive each time:

- **LRU eviction** once `max_open` handlers are live.
- **TTL expiration** — a handler untouched for `ttl` seconds is closed on next
  access.
- **Thread-safe** via a single `threading.RLock`.
- **Metrics** via `get_stats()` (`open_archives`, `cache_hits`, `cache_misses`,
  `hit_rate`, `evictions`, `avg_open_time`, …).

`_create_handler` picks the handler by filename suffix (`.zip` → `ZipHandler`;
`.tar` / `.tar.gz` / `.tgz` / `.tar.bz2` / `.tbz2` / `.tar.xz` / `.txz` →
`TarHandler` with the matching compression). A process-wide instance is returned
by `get_archive_cache()`, which reads `ARCHIVE_CACHE_MAX_OPEN` /
`ARCHIVE_CACHE_TTL` from config (falling back to 5 / 300).

### ArchivePathImpl

`ArchivePathImpl(archive_uri, metadata=None)` implements `PathImpl` for archive
members: URI parsing, path properties (`name`, `stem`, `suffix`, `parent`,
`parts`, …), path manipulation (`joinpath`, `with_name`, `relative_to`, …),
queries (`exists`, `is_dir`, `is_file`, `stat`), directory traversal (`iterdir`,
`glob`, `rglob`), and read-only I/O (`open`, `read_text`, `read_bytes`). All
write/mutate operations (`write_*`, `mkdir`, `unlink`, `rename`, `chmod`, …)
raise `OSError("Archive files are read-only")`.

It also answers storage-strategy queries the app uses elsewhere:
`get_scheme() == 'archive'`, `requires_extraction_for_reading() == True`,
`supports_streaming_read() == False`, `get_search_strategy() == 'extracted'`, and
`get_extended_metadata()` for the info dialog. A per-instance `_property_cache`
memoizes `name` / `parts`; a `_metadata['entry']` slot caches the resolved
`ArchiveEntry`.

### Navigation integration

`xefm/app.py` handles entering an archive: when the cursor is on a recognized archive
file and Enter is pressed, it remembers the cursor and sets the pane path to
`Path(f"archive://{entry.absolute()}#")`. Because `ArchivePathImpl.parent` of the
archive root is the archive file's containing directory, "up" exits the archive
naturally. Nested archives (an archive inside a browsed archive) are not
supported.

### Error handling

A small exception hierarchy under `ArchiveError` (each carries a technical
`message` and a user-facing `user_message`): `ArchiveFormatError`,
`ArchiveCorruptedError`, `ArchiveExtractionError`, `ArchiveNavigationError`,
`ArchivePermissionError`, `ArchiveDiskSpaceError`, plus the encryption pair
`ArchivePasswordRequired` and `ArchiveEncryptionUnsupported` (§3).

### Thread safety

`ArchiveCache` is lock-guarded; handlers are read-only and independent. Multiple
threads may read the same or different archives concurrently through the cache.
Archives are never modified while open.

---

## 2. Create / extract path

Creation and extraction are **not** in `xefm/archive.py` — they live on `XeFMApp`
in `xefm/app.py` and operate on local filesystem paths using the stdlib directly.
There is no separate `ArchiveOperations`/`ArchiveUI` class.

### Format detection

Class data on `XeFMApp`:

- `_ARCHIVE_EXTS` — recognized extensions → format label, longest-suffix-first so
  `.tar.gz` wins over `.tar`. Covers `.zip`, `.tar`, `.tar.gz`/`.tgz`,
  `.tar.bz2`/`.tbz2`, `.tar.xz`/`.txz`.
- `_TAR_MODES` — format label → `tarfile` write mode (`w`, `w:gz`, `w:bz2`,
  `w:xz`); ZIP is handled separately.
- `_archive_format(name)` → format label or `None`.
- `_archive_basename(name)` → name with the archive extension stripped (the
  default extraction subdirectory name).

### Creation

- `_add_to_zip(zf, path, arcname, task=None, prog=None)` — adds a path to an open
  `ZipFile`, recursing into directories (zipfile, unlike tarfile, does not recurse
  on its own).
- `_write_archive(sources, archive_path, fmt, task=None, prog=None)` — writes
  `sources` into a new archive. ZIP uses `zipfile.ZipFile(..., "w", ZIP_DEFLATED)`;
  tar formats use `tarfile.open(..., _TAR_MODES[fmt])` (tarfile recurses into
  directories, and its `add(filter=…)` hook is where per-member progress and
  cancellation are taken). Returns the number of files added.
- `_count_archive_entries(sources, include_dirs)` — the counting pass that makes
  the progress bar determinate: leaf files only for ZIP, files *and* directories
  for tar, matching what each writer actually adds. An unreadable directory counts
  as itself and is not descended.
- `create_archive()` (the **P** key) — the UI flow: takes the active pane's
  selection (or the focused entry), prompts for a filename, and writes the
  archive into the **other** pane's directory. An unrecognized extension defaults
  to `.tar.gz`. A single selected item prefills `"<basename>."`. Overwrite is
  confirmed via a message box. Guards refuse to archive entries that live inside a
  read-only archive or to write into one.

### Extraction

- `_extract_archive(archive_path, dest_dir, fmt, pwd=None, task=None, prog=None)`
  — extracts into `dest_dir` (created if absent) and returns the entry count. Tar
  extraction uses the `filter="data"` argument where available (Python 3.12+) to
  reject unsafe member paths, falling back when the argument is unsupported. `pwd`
  is the password for an encrypted ZIP, verified up front (see §3) so a wrong
  password fails before any file is written.
- `_reporting_members(members, name_of, task, prog)` — the generator handed to
  `extractall(members=…)`. Progress and cancellation are taken *per member yielded*
  rather than by hand-rolling the loop, so `extractall`'s deferred
  directory-permission fix-up (a read-only directory would otherwise block writing
  into it) still runs.
- `extract_archive()` (the **U** key) — the UI flow: extracts the focused archive
  into a subdirectory named after the archive (`_archive_basename`) in the other
  pane's directory. Confirms when `CONFIRM_EXTRACT_ARCHIVE` is set or the
  destination already exists. Refuses non-archives, nested archives, and
  extracting into a read-only archive.

### Running as a task

Both flows hand the work to `xefm.task` rather than doing it in the dialog
callback that started it (issue #280) — compressing a large tree, or building a
compressed tar's member list, would otherwise block the event loop for its whole
duration: no repaint, no keys, no way out.

`_submit_archive_task(task, run, on_done, dest_dir)` is the shared submit. Each
flow builds a `Task` (`kind="archive_create"` / `"archive_extract"`, progress
started as `OperationType.ARCHIVE_CREATE` / `ARCHIVE_EXTRACT`) whose `run` body
counts, then writes or extracts, and returns its outcome as a dict —
`{"added": n}` / `{"count": n}`, `{"cancelled": True}`, or `{"error": exc}` —
which `on_done` reports on the main thread. The submit also brackets `dest_dir`'s
filesystem watcher for the run, the same suppression copy/move/delete use so an
operation's own writes don't re-list the watching pane throughout (issue #243).

This buys the standard `ProgressDialog`: a determinate items bar, the current
entry's name, and **Esc to cancel**. Cancellation unwinds from the per-entry
checkpoint; a cancelled *create* deletes the half-written archive (it either did
not exist before, or an overwrite truncated it the moment the file opened), while
a cancelled *extract* leaves what landed — the destination may be a directory the
user already had files in, so removing it wholesale could take those with it.

Extraction's failure dispatch is ordered most-specific-first, because
`NotImplementedError` **is a** `RuntimeError`: AES is reported as unsupported, and
only a plain `RuntimeError` re-opens the password prompt.

There is no byte-level (secondary) bar: `zf.write()` / `tf.add()` are per-file
opaque calls, and streaming around them would mean rebuilding each member's
metadata by hand.

### Supported formats

Multi-file: ZIP, TAR, TAR.GZ (`.tgz`), TAR.BZ2 (`.tbz2`), TAR.XZ (`.txz`).
Single-file gzip/bzip2/xz streams are readable as members but are not first-class
create targets in the flow above.

> The create/extract flow works on local filesystem paths and does not perform
> cross-storage staging. (Remote-archive support exists only on the read/browse
> side, where a handler downloads the archive to a temp file.)

---

## 3. Encryption

Password-protected ZIP support (extract and browse). Python's `zipfile` decrypts
only legacy **ZipCrypto**; **WinZip AES** (compression method 99) cannot be
decrypted and is detected and refused with a clear message. No third-party
dependency (`pyzipper` etc.) is used.

### Password registry (`xefm/archive.py`)

A module-level dict keyed by the archive file's absolute path, guarded by a lock,
holding passwords for the session (in-memory only, nothing persisted):
`set_archive_password`, `get_archive_password`, `clear_archive_password`.

### Classification / verification helpers

- `zip_encryption_status(zf)` → `'none' | 'zipcrypto' | 'aes'` (AES wins if any
  entry uses it). `zip_encryption_status_path(path)` does the same from a file
  path (used by the extract flow, which works on a raw file, not a handler).
- `verify_zip_password(zf, pwd)` — opens the smallest encrypted entry to validate
  the ZipCrypto header cheaply. No-op when nothing is encrypted; raises
  `RuntimeError` (missing/wrong password) or `NotImplementedError` (AES).

### ZipHandler read path

`extract_to_bytes` / `extract_to_file` pass `pwd=get_archive_password(...)` to
`ZipFile.read`, mapping `RuntimeError` → `ArchivePasswordRequired` (via
`_read_runtime_error`) and `NotImplementedError` → `ArchiveEncryptionUnsupported`.
`encryption_status()` and `verify_password(pwd)` expose the helpers per handler.

### UI-facing gate helpers

Thin wrappers so the app never reaches into `_impl` / cache internals:

- `get_member_archive_path(path)` — the archive file behind an `archive://`
  member Path, else `None`.
- `archive_password_state(path)` → `'ok' | 'need' | 'aes'`. Ordinary paths return
  `'ok'` cheaply (nothing opened), so every read can route through it.
- `try_archive_password(path, password)` — verify (UTF-8 encoded) and, on success,
  remember it; returns a bool.

### Flows (`xefm/app.py`)

- **Extract** — `extract_archive` classifies the ZIP: `'aes'` stops with a
  message; `'zipcrypto'` prompts for a password; otherwise extracts directly. The
  up-front `verify_zip_password` means a wrong password re-prompts with an error
  and never leaves a half-extracted directory. A working password is stored so a
  later browse reuses it.
- **Browse / view** — `_ensure_archive_password` gates opening a file that may
  live in an encrypted ZIP: `'ok'` runs the open callback immediately; `'aes'`
  shows a message; `'need'` shows a masked prompt, verifies via
  `try_archive_password`, and re-prompts on failure. Listing an encrypted archive
  needs no password (the ZIP central directory is unencrypted); the prompt is
  deferred to the first file open.

### Masked input (PuiKit)

The password prompt is a masked field. `xefm/input_dialog.py`'s
`show_input(..., password=True)` forwards `mask="•"` to PuiKit's `TextEdit`, whose
masking is length-preserving (cursor/selection/hit-test still map onto the real
buffer) and disables copy/cut so plaintext never reaches the clipboard. The
widget itself lives in the PuiKit repo (`puikit/widgets/text_edit.py`).

---

## Configuration

```python
# xefm/_config.py
ARCHIVE_CACHE_MAX_OPEN = 5      # max archives kept open by the browse cache
ARCHIVE_CACHE_TTL      = 300    # cache TTL in seconds
CONFIRM_EXTRACT_ARCHIVE = True  # confirm before extracting

# Key bindings
'create_archive': {'keys': ['P'], 'selection': 'required'}
'extract_archive': ['U']
```

## Tests

- `test/test_archive_*.py` — entry conversion, handlers, cache (LRU/TTL), and
  `ArchivePathImpl`.
- `test/test_archive_password.py` — classification, verification, the registry,
  the `ZipHandler` read path, and the gate helpers (hermetic base64 ZipCrypto
  fixture).
- `test/test_xefm_app_archive_password.py` — `_extract_archive` and the extract UI
  flow (prompt, wrong-then-right retry, AES refusal, plain zip), and
  `_ensure_archive_password`.
- `test/test_archive_task.py` — the task path: per-entry progress and
  cancellation in both loops, the counting pass agreeing with each writer, what a
  cancelled or failed create leaves on disk, and a real app on a MemoryBackend
  running both flows on the worker.

## References

- Read/browse: `xefm/archive.py`; `Path` factory in `xefm/path.py`.
- Create/extract: `XeFMApp` in `xefm/app.py`.
- Task system: `xefm/task.py`; the copy/move/delete equivalent in
  `xefm/file_operations.py`.
- Similar virtual filesystem: `xefm/s3.py`.

