# Disk Usage in the Details Dialog — Implementation

The Details dialog (`XeFMApp.file_details`) shows a directory's recursive
size and item counts, filled in *after* the dialog is already open by a
background walk. Two pieces:

## The walk — `xefm/disk_usage.py`

`UsageScan` holds one `RootTotals` record per scanned directory (`bytes`,
`files`, `dirs`, `errors`, `done`) plus a grand aggregate. `start()` runs the
walk on a daemon thread; `run_sync()` is the same walk on the calling thread
(what the unit tests use). `cancel()` is checked per entry.

- The walk descends via `Path.listdir_attrs()` — one bulk call per directory
  (a bulk syscall locally via `dir_scan`, a single request over SSH), so no
  per-entry `stat` round trips on any storage backend. This is why the walk is
  storage-agnostic for free: local, SSH, S3 and archive paths all implement it
  (or inherit the `iterdir` + per-entry fallback).
- Symlinks are counted where they stand (`is_link` attr) and never descended —
  following links can cycle or pull in content outside the chosen root.
  A broken entry arrives from `dir_scan` as a size-0 non-dir and is counted
  as a file. An unlistable directory increments `errors` and is skipped.
- Thread-safety is single-writer/single-reader on plain int attributes: a torn
  read at worst shows a stale number the next repaint corrects, so no lock.

## The live dialog — `file_details()` in `xefm/app.py`

The Markdown document is assembled as a list of segments, each either a fixed
string or a **callable** that renders the live rows from the current counters.
A rebuild joins the segments — it never re-`stat`s the entries, only
re-formats the numbers.

Update loop, in order:

1. The dialog opens immediately via `show_markdown(..., on_close=scan.cancel)`
   with the rows reading `0 B — *scanning…*`.
2. `panel.request_animation_ticks(tick)` registers a per-frame tick, then
   `scan.start()` launches the walk. If tick registration fails (a still
   backend — none of the real backends), the walk is dropped and the rows
   render `*n/a*` instead of claiming to scan forever.
3. `tick()` rebuilds at most every 0.2 s (0.5 s when the document is over 400
   lines — a big multi-selection re-parses more slowly), and immediately once
   `scan.done`. It compares the rebuilt source against the last one and does
   nothing when identical — so `MarkdownView.set_source()` (a full re-parse
   and re-wrap) and `panel.render()` run only when a number actually changed.
4. `set_source()` resets the view's scroll offset; `refresh()` saves and
   restores `md.offset` around it so an update never yanks the view. This is
   safe because the document's shape is stable between updates — only the
   number strings change.
5. Closing the dialog fires `on_close` → `scan.cancel()`; the next tick
   returns `False`, which unregisters it, and the worker exits at its next
   cancellation check.

For a multi-file selection the header's **Total size** / **Total items** are
one live segment over `scan.grand_totals()` plus the non-directory targets'
own sizes (summed once, statically); each selected directory's table also gets
its own live rows bound to its per-root record, so roots finish independently.

## Tests

- `test/test_disk_usage.py` — the walk: totals, multi-root records, symlinks
  not followed, unreadable directories, cancellation, empty-roots born done.
- `test/test_file_details_disk_usage.py` — end-to-end on the memory backend:
  opens the real dialog, pumps `run_animation_ticks()` until the final update
  lands, and asserts the rendered rows, the multi-selection aggregates, and
  that the scroll offset survives the in-place swap.
