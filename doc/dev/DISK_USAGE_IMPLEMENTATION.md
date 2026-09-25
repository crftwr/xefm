# Disk Usage in the Details Dialog — Implementation

The Details dialog (`XeFMApp.file_details`) shows a directory's recursive
size, the space it occupies on disk, and its item counts, filled in *after* the
dialog is already open by a background walk. Two pieces:

## Two numbers, not one

`Total size` and `On disk` are Finder's two fields. The first is the sum of
`st_size`, the second the sum of allocated blocks; they agree on any tree with
no sparse, compressed or cloned file in it, which is why one row labelled
`Disk usage` showing the first went unnoticed until someone opened
`~/Library/Containers` and found a 994 GB total against Finder's 30.54 GB on
disk ([issue #275](https://github.com/crftwr/xefm/issues/275)). One sparse
`Docker.raw` was the whole gap. The number was not wrong; it was the wrong
number for its label.

So the row was renamed to what it measures, and the other quantity was added
beside it rather than substituted for it — Finder shows both, and both are
worth knowing.

## The walk — `xefm/disk_usage.py`

`UsageScan` holds one `RootTotals` record per scanned directory (`bytes`,
`alloc`, `alloc_unknown`, `files`, `dirs`, `errors`, `done`) plus a grand
aggregate. `start()` runs the walk on a daemon thread; `run_sync()` is the same
walk on the calling thread (what the unit tests use). `cancel()` is checked per
entry.

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
- `alloc` comes from the same record as `size`, so the second number costs no
  extra syscalls — see [the attribute record](DIRECTORY_SCAN_SYSTEM.md#size-and-alloc).
  A backend that cannot report it sends `None`, which increments
  `alloc_unknown` instead of adding 0. `RootTotals.on_disk` (and
  `grand_alloc()` over the selection) is then `None` rather than a sum missing
  some of its terms — which would read as a smaller directory rather than as an
  unmeasured one. The walk reads the field with `.get`, because a backend
  living outside this repository (`xefm/path_base.py` is a published extension
  point) may predate the key entirely, which is the same "cannot say".

### Which roots get an `On disk` row

`reports_allocation(path)` asks the backend once per root, *before* the
document is built: can a `stat` here produce an allocation. Local says yes on
macOS and Linux and no on Windows; SSH, S3 and archive say no.

It has to be settled up front rather than read off the running totals, because
the live rows are swapped into an already-open document whose **shape must not
change** — `refresh()` saves and restores the scroll offset around
`set_source()`, and a row appearing or disappearing mid-walk would leave the
restored offset pointing at a different line. `RootTotals.on_disk` can turn
`None` partway through a walk; the row's existence cannot. When it does turn,
the row stays and reads `*unavailable*`.

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

For a multi-file selection the header's **Total size** / **On disk** /
**Total items** are one live segment over `scan.grand_totals()` and
`scan.grand_alloc()` plus the non-directory targets' own sizes and allocations
(summed once, statically); each selected directory's table also gets its own
live rows bound to its per-root record, so roots finish independently. The
header's **On disk** line appears only when *every* part of the selection can
report one — each plain file, and each walked directory.

## Tests

- `test/test_disk_usage.py` — the walk: totals, multi-root records, symlinks
  not followed, unreadable directories, cancellation, empty-roots born done;
  and for the second number, a sparse file separating the two totals, a dense
  tree rounding up past its byte count, a backend that reports no allocation
  (unknown, not zero), one unreported entry poisoning an otherwise known
  total, and `reports_allocation` over local, remote and unstattable paths.
- `test/test_dir_scan.py` — that every backend reports `alloc` identically,
  including for a sparse file, against a per-file `st_blocks × 512` reference.
- `test/test_file_details_disk_usage.py` — end-to-end on the memory backend:
  opens the real dialog, pumps `run_animation_ticks()` until the final update
  lands, and asserts the rendered rows, the multi-selection aggregates, that
  the document's line count is identical across every in-place update, and
  that the scroll offset survives the swap.
