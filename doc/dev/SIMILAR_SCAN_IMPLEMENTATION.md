# Similar-File Scans — Implementation

[#571](https://github.com/crftwr/xefm/issues/571), from discussion
[#474](https://github.com/crftwr/xefm/discussions/474). User-facing behavior is
in [`doc/FIND_SIMILAR_FILES_FEATURE.md`](../FIND_SIMILAR_FILES_FEATURE.md).

## Why a separate process

Detection belongs to [similar-files](https://github.com/crftwr/similar-files):
#474 settled that XeFM's part is an adapter and UI. Similar videos are in
scope from the start, and a video scan runs for hours. A `Task` (#567) lives
in XeFM's process and dies with it. So the scan is **similar-files' own CLI,
started in its own session**, and XeFM only launches it, watches it, and opens
what it wrote.

The two share **only files**, with no pipe and no signal. That makes it work
the same on every platform, and across XeFM quitting and starting again.
similar-files 0.2 added the options this needs (its
[`doc/STATUS_FORMAT.md`](https://github.com/crftwr/similar-files/blob/main/doc/STATUS_FORMAT.md),
and `--format tree` / `--snapshot-interval`):

- `--status FILE`: progress as JSON, replaced whole on each write, rewritten
  every 5 s while the scan runs, with a final `state` and `exit_code`;
- `--stop-file FILE`: once it exists, the scan stops as on Ctrl-C and writes
  the groups found so far.

## `xefm/similar_scan.py`

| Piece | |
|---|---|
| `start(roots, method, base=, python=)` | Makes the job folder, writes `job.json`, starts `python -m similar_files scan … --out result.xft --format tree --method M --status status.json --stop-file stop`, with stdout and stderr going to `scan.log` |
| `ScanJob` | One folder: `info()`, `status()`, `state()`, `progress_text()`, `summary()`, `seen` / `mark_seen()`, `stop()`, `remove()` (deletes the folder; `ValueError` while running) |
| `jobs(base)` | Every scan folder, newest first (ids are `YYYYmmdd-HHMMSS-<hex>`) |
| `prune(base, keep=10)` | Removes finished scans beyond the newest ten, seen ones before unseen (#822). Never a running one |
| `unavailable(method)` | Why a method cannot run (similar-files missing or older than 0.2, the extractor's own `install_hint()`), or None |
| `pid_alive(pid)` | `os.kill(pid, 0)` on POSIX, `OpenProcess` / `GetExitCodeProcess` on Windows |

**Detaching.** POSIX uses `start_new_session=True`, so the scan is not in
XeFM's process group or terminal session, and neither quitting XeFM nor
closing its terminal signals it. Windows uses `DETACHED_PROCESS |
CREATE_NEW_PROCESS_GROUP` plus the usual no-window flag. stdin is
`DEVNULL`, and the working directory is the job folder.

**Interpreter.** `external_programs.xefm_python`: the bundled interpreter
inside the macOS app and the Windows build, `sys.executable` otherwise. The
bundled interpreter does not see the app's own package folder, so
`PYTHONPATH` is prefixed with the directory holding the imported
`similar_files` package.

**States.** `state()` reads `status.json` first:

- no status yet: `starting` while the pid lives or for `STALE_S` (30 s)
  after `created`, then `lost`;
- `running` with `updated` within `STALE_S`: `running`;
- `running` but quiet: `running` if the pid lives (a machine that slept),
  otherwise `lost`;
- any final state is reported as written.

The heartbeat, not the pid, is the primary signal. A pid can be reused after a
reboot, but a status that stopped changing cannot be mistaken for a live one.

## The app

- `find_similar` (Tools → Find Similar Files…, unbound): the scope is the
  selection or the directory. A virtual or remote pane is refused, because
  the CLI reads local paths. A `ChoiceDialog` offers the methods, with the
  `unavailable()` reason in the label.
- `_scan_rows`: `(job, state, text)` for the status bar and the jobs list,
  rebuilt by `_refresh_scans()`, never read per frame. While any scan runs, a
  daemon poller sets `_scans_dirty` every 2 s and calls `_wake_pump()`.
  `_pump_monitoring` calls `_pump_scans()`, which refreshes the rows, logs a
  scan that has just finished, and asks for a frame only when the rows
  changed. The poller ends with the last running scan.
- `_jobs_parts` appends, after the in-process jobs, **at most two** scan
  parts (#822): the running scans (`busy`, behind the spinner: `Similar
  videos extract 42%`, or `2 scans running`) and the finished, unseen ones
  (`✓ Similar videos: 12 groups`, or `✓ 3 scans finished`). A part each let
  ten finished scans squeeze the hints down to `F…`, since the job segment
  takes its width first. A stopped (`cancelled`) scan is `done`; `failed`
  (`⚠`, with `, N failed` in the count) is only for failed or lost ones.
- `show_jobs` lists in-process jobs and scans together. A running scan offers
  **Look at the groups so far** (once `result.xft` exists), **Stop the scan**
  (`job.stop()`) and **Show its log**. A finished one is marked seen. For both,
  the active pane goes into `xft://<job>/result.xft#` (#573), and the
  tree's own provisional handling (header, re-read on rewrite, follow by
  anchor) does the rest. A failed or lost one opens its log.
- Clearing without opening (#822): the jobs list ends with **Mark N finished
  scans as seen** while any is unseen, and its `ChoiceDialog` gets
  `on_remove`, so `remove_list_item` (the filter-list key, read by action)
  deletes a finished scan with `ScanJob.remove()` and refuses a running one.
  Before this, opening was the only way to set `seen`, and each open made a
  tab.

## Why a tree file, rewritten

The output was first one `.m3u8` per group in a `groups/` folder. It became
one `.xft` tree (similar-files `--format tree`, #549) so that a long scan's
groups can be looked at **before it ends**. Appending finished groups works
for identical files only: similar-files closes a size bucket at a time. For
similar files, anchors are chosen over all features, largest file first, so a
file read later can join a group or become a new anchor. Partial results are
therefore **provisional**. similar-files regroups what it has read every few
minutes and replaces the file whole (`final: false`, `generation` counting
up). The last write is final, and a stopped scan keeps its last snapshot with
`complete: false`.
- At startup, the log says how many scans finished while XeFM was closed and
  how many still run.

## Dependency

`similar-files` is **optional at runtime**. Its import is checked by
`unavailable()`, and nothing imports it at module level, because the 0.2
release carrying `--status` is not on PyPI yet. Once it is, it belongs in
`requirements.txt` (and so in the desktop bundles), and a note above the pin
should say why 0.2 is the floor. For development: `pip install -e
../similar-files`.

## Not done

Remote roots (they need the library in-process and XeFM's path layer), similar
images and audio in the launcher, running scans on a NAS (similar-files'
Docker prototype), a "select all but the anchor" helper, and showing
similarity in the list.

## Tests

`test/test_similar_scan.py`, skipped without similar-files 0.2. A real
identical scan runs to the end and writes its final tree, runs in its own
session, and lists newest first; a running scan with a tree offers its
provisional groups. Hand-written job folders cover a fresh
heartbeat, stale with a dead pid (`lost`), stale with a live pid (`running`),
finished states, no status yet, the stop file, and prune keeping running
scans. In the app, the launcher's dialog starts a scan, the poller's pump
reports it finished, and the jobs list takes the pane to its groups. A remote
pane is refused. Every scan in the tests uses its own cache
(`SIMILAR_FILES_CACHE`), never the user's.
