# Directory Scan System

Listing a pane means answering four questions about every entry: **is it a
directory, is it a symlink, how big is it, when was it modified**. Asking the OS
per file costs one round trip per file. On a local disk that is free. On a
network mount it is the entire cost of the listing.

Measured on a 1,680-file SMB directory from a Synology NAS (~9 ms RTT), cold
cache:

| Approach | Time |
|---|---|
| `readdir` alone | 13 ms |
| `getattrlistbulk` — one bulk enumeration | **2.0 s** |
| `os.scandir` + one `stat` per entry | 20.8 s |
| `iterdir` + 4 attribute calls per entry (the old path) | 24.9 s |

Finder lists the same directory in about 3 s, so ~2 s is close to the floor this
NAS imposes; the old path sat roughly 8× above it.

The cost model, which the measurements match to within 1%:

* the **first** attribute call on a file is a network round trip, ~12.4 ms
* every **later** call on that file is served from the smbfs cache, ~0.8 ms

`1,680 × 12.4 ms ≈ 20.8 s`, plus `5,040 × 0.8 ms ≈ 4 s` of redundant calls,
`≈ 24.8 s` against 24.9 s measured.

The consequence is the important part: **the redundancy was only ~17% of the
cost.** Deduplicating four calls per entry down to one still leaves 20.8 s. What
matters is not touching files individually at all — SMB2 already returns size,
mtime and type alongside the directory listing, and the old path discarded them
and asked again per file.

Source: [`xefm/dir_scan.py`](../../xefm/dir_scan.py),
[`PathImpl.listdir_attrs`](../../xefm/path.py).
Tests: [`test/test_dir_scan.py`](../../test/test_dir_scan.py),
[`test/test_hidden_files.py`](../../test/test_hidden_files.py).

---

## The attribute record

Every backend returns the same record per entry, so callers never branch on
platform:

```python
{'is_dir': bool, 'is_link': bool, 'size': int, 'mtime': float,
 'hidden': bool, 'ok': bool}
```

`is_dir`, `size` and `mtime` describe the **target** of a symlink; `is_link`
describes the link itself. That is exactly what `stat()`/`is_dir()` and
`is_symlink()` reported when callers asked per file, so nothing downstream
changed meaning. `ok` is False when the target could not be stat'd — a broken
symlink — and the pane renders it as a link with `---` for size and date.
`hidden` is the exception to `ok`: it describes the directory entry itself, so
it stays valid for an entry whose target is gone.

`hidden` is the **platform's** mark, not the dot convention — see
[hidden entries](#hidden-entries) below.

Directories report `size: 0` on every backend. The bulk syscall cannot supply a
directory's size, and nothing displays or sorts on it (a directory renders as
`<DIR>` and sorts as 0), so the backends are normalised rather than left to
disagree.

## Per platform

| Platform | Mechanism | Per-entry cost |
|---|---|---|
| macOS | `getattrlistbulk(2)` — what Finder itself uses | none |
| Windows | `os.scandir` — `DirEntry` already carries the enumeration's attributes | none |
| Linux, other | `os.scandir` — `d_type` answers is_dir/is_symlink, `stat` is cached | one `stat` |

Linux has no portable bulk equivalent, so it keeps one `stat` per entry — still
a 4–6× reduction in calls, and local disks were never the problem. The win where
it matters (macOS to a NAS, the case in issue #183) is the bulk syscall.

Symlinks are the one thing bulk enumeration cannot answer: its record describes
the link, so `dir_scan` follows each one individually. A directory of symlinks
costs what it always did; ordinary directories cost one scan.

`getattrlistbulk` failing on a volume that does not support it (some FUSE and
network filesystems) falls back to `os.scandir` for that directory. Real
directory errors — missing, permission denied, not a directory — still raise, so
callers keep the error handling they had when this was `iterdir`.

## Where it plugs in

`PathImpl.listdir_attrs()` returns `[(Path, attrs), …]` — `iterdir` plus
everything a listing needs, in one call.

The default implementation *is* `iterdir` + per-entry `stat`, so backends with
no bulk form (S3, SSH, archives) keep working untouched; `LocalPathImpl`
overrides it with `dir_scan.scan_dir`. S3 already caches its
`list_objects_v2` response, which carries `Size` and `LastModified`, so the
bulk-metadata idea has precedent — the local backend was the one asking per file.

---

## Hidden entries

A leading dot hides an entry on POSIX. Windows says the same thing with a file
attribute and no dot, and XeFM only ever tested the name — so with hidden files
off, a Windows pane still listed `AppData`, `$Recycle.Bin`,
`System Volume Information` and every `desktop.ini` (issue #284).

The attribute is part of the record because reading it is free where it exists:
`DirEntry.stat(follow_symlinks=False)` on Windows is served from the
enumeration, so the one-pass scan already has it. Elsewhere `hidden` is False
and costs nothing to fill in.

Two predicates in `dir_scan` put the two conventions together, and every
consumer of the hidden-files toggle calls one of them:

| Predicate | For a caller holding | Cost |
|---|---|---|
| `is_hidden(name, attrs)` | a scan record | none |
| `is_hidden_path(path)` | only a path | one `lstat`, Windows only |

`FILE_ATTRIBUTE_HIDDEN` alone decides it. `FILE_ATTRIBUTE_SYSTEM` on its own
sits on folders a user still expects to see — `C:\Windows\Fonts`, a customized
`Documents` — while everything Explorer calls a *protected operating system
file* carries HIDDEN as well as SYSTEM. Testing HIDDEN therefore catches
`pagefile.sys` and `System Volume Information` without swallowing `Fonts`.

`hidden` is read from the entry, never from a symlink's target: a followed
`stat` describes something else, so `attrs_via_path` and `attrs_for_path` take
a second `lstat` for links only.

macOS has `UF_HIDDEN`, which Finder honours; `dir_scan` does not read it. The
bulk record would need `ATTR_CMN_FLAGS`, which shifts every offset in
`_parse_bulk_entry`, and nothing on macOS commonly carries the flag.

---

## Sorting and filtering without re-reading

The second half of issue #183, and the one users actually felt. Sorting a
directory needs no information the listing did not already collect, yet every
sort and filter change used to re-read the whole directory — paying the full
cost above to produce a list the pane could already derive.

`FileListManager` now splits the listing in two:

| Method | Reads the disk? | What it does |
|---|---|---|
| `compute_listing(path, …)` | yes, once | scan the directory, then assemble |
| `_assemble_listing(entries, …)` | no | filter, sort, build the display cache |
| `recompute_listing(pane, …)` | no | re-assemble from the pane's snapshot |

`apply_listing` stores the scan in `pane['_listing_entries']`, and
`XeFMApp._resort` rebuilds from it on the current tick. A re-sort of the 1,680-
file NAS directory costs **microseconds** instead of a full re-read.

The snapshot is taken **after** the hidden-file filter and **before** the
filename filter. So:

* changing or clearing a filter re-filters from the snapshot — widening a filter
  restores entries without going back to the directory
* toggling `show_hidden` changes what the snapshot should contain, so it still
  does a real re-list (`_list_pane`)

`_resort` falls back to `_relist` whenever the pane has no snapshot — nothing
listed yet, or the last listing failed — so behaviour is unchanged when there is
nothing to reuse. A failed listing clears the snapshot rather than leaving a
later sort to re-filter a directory that can no longer be read.

### Two user-visible consequences

**The cursor now follows the file, not the row.** Re-sorting used to leave
`focused_index` where it was, so the cursor landed on whatever file happened to
occupy that row. `_resort` keeps it on the same file. Filter changes still reset
the cursor to the top, which is what `set_filter` has always done.

**No blank-then-repopulate.** `_relist` clears `pane['files']` until a worker
reports back, which on a slow mount left the pane empty for the whole re-read.
An in-memory re-sort lands on the same tick, so the list never empties.

### What a sort no longer picks up

A sort used to re-read the directory, so it incidentally refreshed the pane.
It no longer does. External changes arrive through
[`FileMonitorManager`](../../xefm/file_monitor_manager.py), which watches the
directory and posts a reload — that is the mechanism responsible for freshness,
and it is unaffected. `Ctrl-R` and every post-operation path still re-list for
real. The trade-off is only visible where file monitoring is unavailable *and*
the directory changed underneath: previously a sort would have surfaced it by
accident, now it waits for an explicit refresh.

---

## Other readers of the snapshot

Sorting was the first consumer of `pane['_listing_entries']`, not the only one.
Any feature that wants is_dir / size / mtime for entries a pane has **already
listed** should read them from there rather than ask the filesystem again —
otherwise it reintroduces exactly the per-file round trips this system exists to
remove, on top of a listing that already paid for the answers.

### Compare & Select (issue #245)

[`compute_compare_selection`](../../xefm/compare_selection.py) joins the two
panes by name and tests each pair against the enabled relations. It used to call
`is_dir()` on every entry of both sides for the join, then `stat()` on both
halves of every matched pair — **two per-file calls per entry, per side, for
every criteria**, including the pure filename join that reads no attributes at
all. Two 1,680-entry panes meant ~6,700 calls, or roughly 45 s under the cost
model above, for a comparison whose every input the panes already held.

It now takes the records instead:

```python
compute_compare_selection(current_files, other_files, criteria,
                          current_attrs=..., other_attrs=...)   # {str(path): record}
```

`XeFMApp._pane_attrs(pane)` builds one side's mapping from `_listing_entries`;
both the inline path and the content-comparison worker pass it. Measured on two
200-file directories, all relations: **1,200 per-file calls → 0.**

Three rules this follows, and any future consumer should:

* **The snapshot is a superset of the displayed rows** — it is taken before the
  filename filter — so a filtered pane is fully covered.
* **A missing record falls back to reading that entry**, so a caller with no
  attributes still works. `_attrs_of` deliberately does *not* use
  `attrs_via_path` for this: that also asks `is_symlink`, which a comparison
  never reads, and the fallback exists for exactly the storage where a wasted
  call is a wasted round trip.
* **`ok: False` satisfies no relation.** An entry whose target cannot be read
  can never be asserted equal, newer or larger, so it is never selected through
  a counterpart — but it still *counts* as a counterpart, so the other side's
  entry is not reported as an orphan. That is what raising `OSError` out of the
  old `stat()` did, preserved.

The staleness trade-off is the one `_resort` already made: a comparison now
reflects the same snapshot the pane's own size and date columns are drawn from,
so it agrees with what the user is looking at, and is refreshed by the same
mechanisms. Content comparison is unaffected in kind — no snapshot can answer
"are these bytes equal", so it still reads both files on the task worker; only
the size short-circuit that decides *whether* to read now comes for free.
