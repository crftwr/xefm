# Parallel Copy & APFS Clone — Implementation Notes

GitHub issue #248 asked whether reader/writer threads or multi-file worker
threads would speed up file operations. Benchmarks (Apple M5, APFS SSD) said:

- A reader-thread/writer-thread pipeline for one file: **no** — 2–5%, within
  noise. `write()` lands in the page cache and returns immediately, so the
  sequential loop is already read-bound. Not implemented.
- Parallel workers across files: **yes, modestly** on local disk (~1.3–1.5×,
  saturating at ~4 workers), and **structurally** for S3, where each object
  costs a network round trip. Implemented.
- Not in the issue, but the biggest local win: same-volume copies as APFS
  **clones** (`clonefile(2)`) — a 1 GiB copy drops from ~200 ms to ~0.3 ms,
  and it is what Finder's Duplicate does. Implemented.

Both live entirely in `xefm/file_operations.py`.

## The clone fast path

`_clone_file(src, dest, overwrite)` runs first in `_copy_file` for a
local↔local, non-symlink source:

- Declines (returns False) without attempting the syscall when the source and
  `dest.parent` report different `st_dev` — the same `_entry_device` seam the
  atomic-move check uses, and the one tests monkeypatch to fake a second
  volume. Everything that declines falls through to the unchanged
  streaming/`copy_to` path.
- `clonefile` never replaces an existing file; on `EEXIST` with
  `overwrite=True` the old file is unlinked and the clone retried once.
- `shutil.copystat` runs after a successful clone so metadata is bit-identical
  to what the streaming path produces.
- The libc symbol is resolved lazily under a lock; on non-macOS (or a libc
  without the symbol) the whole path is a single `False` check per file.

A clone shares data blocks copy-on-write: the copy consumes no space until one
side is modified. Cancellation mid-file is moot — the clone is one syscall.

## The worker pool

`_run` hands the resolved plan to `_run_parallel` when `_copy_workers` returns
more than 1 **and** the operation covers more than one item:

| Schemes involved       | Workers | Why |
|------------------------|---------|-----|
| `file` only            | `FILE_OP_WORKERS_LOCAL` (default 4) | local disk saturates fast; >4 measured slower |
| `file` + `s3`          | `FILE_OP_WORKERS_S3` (default 8) | per-object latency dominates; boto3 clients are thread-safe (creation serialized in `s3.py`) |
| anything else (`ssh`, archives) | 1 — sequential path | ssh transfers share one control-master connection per host with per-connection progress state |

The two knobs are independent because the sweet spots genuinely differ: local
parallelism is bounded by the disk and the GIL, S3 parallelism by round-trip
latency. Set a knob to 1 to force that class sequential; a value below 1 (or
non-numeric) falls back to the built-in default. Neither knob ever forces a
scheme off the sequential path.

The task thread stays the **walker**: it performs atomic-move renames inline,
creates directories in order (a child job must never race its parent's
mkdir), and submits each *file* as one pool job (`_copy_file_job`). Rules that
keep the semantics identical to the sequential path:

- **Per-target bookkeeping.** Each top-level target gets its own error list
  and its own futures; they fold into the result dict in plan order, so
  `done`/`failed`/`items`/`errors` match the sequential accounting exactly.
- **Moves never drop an unverified source.** A directory move drains its own
  target's futures and deletes the source only if the whole tree copied
  cleanly; a single-file move carries its source unlink inside the job, so a
  many-file move still pipelines across targets.
- **Cancellation** is the existing cooperative flag: jobs `checkpoint()` on
  entry and per chunk; the walker checkpoints per node. On unwind, pending
  futures are cancelled, running jobs finish or unwind, and whatever actually
  landed is still folded into `items`.
- **Conflict resolution never runs on a worker** — `_resolve` completes before
  any copying starts, so `Task.ask` stays single-threaded.

## Shared-state rules

- `ProgressManager` mutators now hold a lock (several workers report into one
  operation dict). Each in-flight file claims a **transfer slot**
  (`file_begin` / `file_bytes` / `file_end`, see
  [Progress Manager System](PROGRESS_MANAGER_SYSTEM.md)): concurrent workers
  each drive their own byte row instead of fighting over a single bar, the
  item count advances when a file *finishes* rather than when a worker picks
  it up, and every byte lands in the operation-wide `processed_bytes` that
  weights the primary bar.
- The `log` sink is wrapped by `_serialized_log` in the parallel path —
  `LogView.append` (line list + wrap cache) is not built for concurrent
  writers.
- `boto3.client()` creation is serialized by `_s3_client_create_lock` in
  `xefm/s3.py`: clients are thread-safe to use, but creating one goes through
  the shared default session loader, which is not.

## Tests

`test/test_parallel_copy.py` covers both features: clone correctness
(content, mtime, copy-on-write independence, overwrite, cross-device
decline), parallel copy/duplicate/move including per-target failure
accounting and the move source-retention rule, cancellation mid-batch,
lost-increment progress accounting, worker-count selection, and the transfer
slots (count-at-completion, per-slot byte ownership, unstreamed-byte crediting,
slot reuse, byte-weighted percentage, and whole-operation byte totals). The
pre-existing suites in `test_file_operations.py` run the same
engine through both the sequential (single-item) and parallel (multi-item)
entry conditions.
