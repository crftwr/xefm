# Async Listing System

Reading a directory — the entry list plus each entry's type, size and date — is
the one piece of blocking I/O XeFM does on behalf of nearly every action. On a
local disk it costs microseconds; on a network mount, a spun-down drive, a huge
directory, or a remote (`s3://`, `ssh://`) path it can cost seconds. **No
listing runs on the UI thread.** Every path that produces a pane listing goes
through one worker-thread mechanism, and the result is installed on the UI
thread.

Two companion documents cover the cost of the read itself rather than the thread
it runs on: [`DIRECTORY_SCAN_SYSTEM.md`](DIRECTORY_SCAN_SYSTEM.md) explains why
the directory is scanned in one pass instead of stat'd per file, and why a sort
or filter change rebuilds from the previous scan rather than re-reading.

Source: [`xefm/app.py`](../../xefm/app.py) (`_list_pane` and its callers),
[`xefm/file_list_manager.py`](../../xefm/file_list_manager.py) (the split between
the I/O and the pane mutation). Tests:
[`test/test_xefm_app_async_listing.py`](../../test/test_xefm_app_async_listing.py).

---

## The split that makes it possible

`FileListManager` separates the blocking half from the mutating half:

| Method | Thread | Touches the pane? |
|---|---|---|
| `compute_listing(path, …)` | any (worker) | no — returns a plain dict |
| `compute_listing_from_paths(paths, …)` | any | no — the virtual-pane variant |
| `apply_listing(pane, result)` | UI only | yes — installs files, reconciles cursor + selection |
| `refresh_files(pane)` | caller's | both, back to back — the **synchronous** API |
| `set_filter(pane, pattern)` | UI only | pane state only, no I/O |
| `apply_filter(pane, pattern)` | caller's | `set_filter` + `refresh_files` — synchronous |

`refresh_files` / `apply_filter` remain as the simple synchronous contract for
non-UI callers and for virtual panes; the app itself no longer calls them on a
directory pane.

---

## The one mechanism: `XeFMApp._list_pane`

```
_list_pane(name, on_ready=…)
  ├─ bump pane["_load_gen"]          single-flight token
  ├─ pane["loading"] = True, files/file_info cleared
  ├─ snapshot path + filter + sort   (the worker never reads the pane dict)
  └─ Thread → flm.compute_listing(…) → _result_queue.put(…) → _wake_pump()

_process_result_queue()   (UI thread, on the monitoring pump)
  ├─ drop the result if its generation no longer matches   (superseded nav)
  ├─ flm.apply_listing(pane, result)
  ├─ pane["loading"] = False
  └─ on_ready(pane)
```

Three properties fall out of this:

- **Single-flight per pane.** A newer navigation bumps `_load_gen`; the older
  worker's result is dropped rather than clobbering the newer directory.
- **The worker owns nothing.** It reads a snapshot of the inputs and returns a
  dict. The pane dict stays exclusively the UI thread's.
- **No indicator flash.** `pane["loading"]` alone draws nothing; only a listing
  still pending past `_LOADING_INDICATOR_DELAY` (120 ms) sets `_loading_shown`,
  which is what the pane renders as `Loading…`. A fast local listing swaps in
  with no visible change.

`on_ready(pane)` is the hook for anything that reads the *new* listing — placing
a cursor by filename, reporting an item count. It runs on the UI thread once the
files are in place. **Nothing may read `pane["files"]` between calling
`_list_pane` and `on_ready`:** the pane is deliberately empty in that window, so
a stale entry can never be acted on under a listing that no longer exists.

---

## The two entry points callers use

Callers rarely reach for `_list_pane` directly. They pick one of two wrappers,
which differ only in what they reset:

| | `_relist(pane)` | `_refresh(pane)` | `_resort(pane)` |
|---|---|---|---|
| Meaning | re-list the **same** directory | the pane **navigated** | re-order what is already listed |
| Reads the disk | yes, on a worker | yes, on a worker | **no** — rebuilds from the snapshot, on a worker |
| Cursor / scroll | untouched (clamped when the result lands) | reset to the top | held on the same **file** |
| History record | no | yes | no |
| Used by | post-operation reload, startup, `show_hidden` | enter/leave a directory, jump, favorites | sort, filter |

Both re-reading wrappers are virtual-pane aware: a search-results feed has no
directory to read, so it is rebuilt from its in-memory result set
(`flm.refresh_files`) and `on_ready` fires synchronously. `_refresh` is literally
`_relist` plus the cursor reset and the history record, so the two can never
drift.

`_resort` is the one that does no I/O: a sort or filter change needs nothing the
previous listing did not already collect, so it re-filters and re-sorts the
snapshot, falling back to `_relist` only when the pane has no snapshot to reuse.
See
[`DIRECTORY_SCAN_SYSTEM.md`](DIRECTORY_SCAN_SYSTEM.md#sorting-and-filtering-without-re-reading).

**It runs on a worker like the others**, and did not always. Reusing the snapshot
took the disk read out of a sort; what was left was microseconds of arithmetic,
so it landed on the tick, and landing on the tick was the point — `_relist`
blanks the pane until a worker reports, which on a slow mount left it empty for
the whole re-read. That argument stopped holding when a config could supply the
sort key ([`SORT_KEYS`](CUSTOMIZATION_API_IMPLEMENTATION.md), and see
[`FILENAME_NORMALIZATION_SYSTEM.md`](FILENAME_NORMALIZATION_SYSTEM.md) for why it
can): the ordering became arbitrary code called once per entry, which must not be
able to hold the UI thread.

The flicker argument is answered differently rather than abandoned. `_resort`
posts through the same queue as everything else but **does not blank the pane**,
the way a filesystem-monitor reload does not: the current rows stay on screen and
stay actionable for the whole re-sort. Two details follow from that:

* The queue item carries `drop_if_unchanged` separately from `keep_visible`. They
  used to be the same flag, because the only non-blanking listing was the monitor
  reload, which *wants* to be dropped when it would redraw nothing. A re-sort
  keeps the pane visible too but must never be dropped: a caller waiting on
  `on_ready` has to hear back even when the new order is identical.
* The cursor is held on the file that was focused **when the sort was asked
  for**. The old rows stay live while the worker runs, so a cursor moved in the
  meantime lands back on what the user was looking at when they pressed the key.

Filter changes get a thin wrapper on top — `XeFMApp._apply_filter(pane, pattern,
on_count=…)` — because the *count* the log line reports is a property of the
listing, not of the pane state: `set_filter` lands immediately, and `on_count(n)`
fires when the listing does.

---

## Startup is deferred, not synchronous

The two first listings cannot be started where the panes are created: the panel,
the result queue and the pump are all built later in `__init__`. Rather than
letting launch block on `iterdir` (the last synchronous listing in the app),
`XeFMApp.__init__` ends with `_start_initial_listings()`, which lists both panes
the same way everything else does.

One consequence: the saved cursor is matched **by filename**, so it can only be
placed once the files are in. It rides along as each pane's `on_ready`
(`_restore_remembered_cursor`) instead of running inline.

---

## Writing a test against a pane listing

A listing is no longer in place when the call that requested it returns. Tests
that assert on `pane["files"]` — including right after constructing an
`XeFMApp` — must settle first:

```python
self.app = xefm_app.XeFMApp(backend, left, right, ...)
self.app._settle_listings()          # startup lists on workers; wait for it
```

`_settle_listings(timeout=2.0)` blocks until every in-flight listing has been
installed, draining results as workers post them. **The interactive UI never
calls it** — it drains on the idle pump so it never blocks. It exists for
callers that need a directory listed before they can proceed deterministically,
which in practice means unit tests.
