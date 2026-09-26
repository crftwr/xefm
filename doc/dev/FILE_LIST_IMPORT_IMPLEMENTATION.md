# File List Import — Implementation

Stage ① of [#453](https://github.com/crftwr/xefm/discussions/453): a list of
paths from outside XeFM becomes a virtual pane. User-facing behavior is in
[`doc/FILE_LIST_IMPORT_FEATURE.md`](../FILE_LIST_IMPORT_FEATURE.md); the
virtual pane itself is described in
[SEARCH_RESULTS_PANE_IMPLEMENTATION.md](SEARCH_RESULTS_PANE_IMPLEMENTATION.md).

## Why not a search-engine API

#432 asked for Everything search. #446 worked out what a plugin API for search
engines would need — a generator contract, cancellation, option ownership, a
query language per engine — and #453 split out the cheaper answer: every such
tool already prints paths. Taking a list of paths needs no contract at all,
works with any tool, and can be tested on any machine. Everything itself is not
supported in tree; it is one source among many.

## Pieces

| Piece | Where |
|---|---|
| Parse, resolve, common root, probe — storage-agnostic, pane-free | `xefm/path_list.py` |
| One door for every source | `XeFMApp.show_path_list(pane_name, paths, *, title, base=None)` |
| The clipboard source | `XeFMApp.import_list_from_clipboard` (action `import_list_from_clipboard`, unbound) |
| The public door | `PaneApi.show_list(paths, *, title)` in `xefm/user_api.py` |
| Listing a virtual pane off the UI thread | `XeFMApp._list_virtual`, `FileListManager.compute_virtual_listing` / `prune_virtual` |
| Whole-path names | `name_key.WHOLE_PATH` |

Stages ② (a file) and ③ (a command's stdout) are further sources calling
`show_path_list`; each chooses its own `base` for relative lines (the list
file's directory, the command's cwd).

## The flow

1. **UI thread.** `path_list.parse` splits the text; `path_list.resolve` turns
   lines into `Path`s — URIs and absolute paths as they are, relative ones
   joined onto `base` and counted. Duplicates collapse. Nothing is read from
   disk.
2. `show_path_list` builds `{"kind": "list", "title": …, "root": None,
   "results": [...], "meta": {}}` and hands it to `_list_virtual`. The pane is
   **not** touched yet.
3. **Worker.** `compute_virtual_listing(..., derive_root=True)` probes every
   path, derives the root from the **survivors**, and assembles the listing
   (`cmp_name` relative to that root).
4. **UI thread**, via `_result_queue` and its `prepare` step: if nothing
   survived, `on_empty` logs why and the pane is left alone. Otherwise the
   virtual dict goes on the pane (root filled in), the filter, selection and
   cursor reset, the set is pruned to the survivors, and the listing installs.
   `on_ready` logs the count and what was left out.

The search feed (`_feed_search_results`) now enters through the same
`_list_virtual`, with its root given rather than derived.

## `probe`: one read per path, one attempt per location

`attrs_via_path` is the existence check — no `exists()` first. Before any path
is read, its `Path.anchor` (drive root, `ssh://host/`, bucket root) is tried
once with `exists()`; if that raises or says no, every path under it counts as
**unreachable** without being tried. SSH connects with `BatchMode=yes`, so an
unreachable or unauthenticated host fails rather than prompting, and without
this each of its rows would pay a connection timeout.

`missing` and `unreachable` are counted separately, because they call for
different things: one is gone, the other may come back after a reconnect. The
backends do not agree on exception types for "not found" (`FileNotFoundError`
locally and on S3, `SSHPathNotFoundError` over SSH), which is why the
distinction is drawn by location rather than by exception.

On a refresh after an operation the same pass runs, and both kinds are dropped
from the set, as a vanished search hit always was.

## `common_root`

Built from `parent` alone, which every backend answers without I/O, so it works
the same for local paths, URIs and archive members. Candidates are the first
path's ancestors, nearest first; each further path drops candidates until one
lies on its own chain. No candidate left means no common root.

`None` could not mean "no common root": `name_key.rel_name(path, None)` is the
basename, and that fallback is load-bearing for every ordinary directory pane.
`WHOLE_PATH` is a separate sentinel. Because every consumer of a virtual root —
`FilePane._display_name`, the sort's `cmp_name`, Copy Name(s), the compare's
path match — already goes through `name_key`, handling the sentinel there is
the whole change. The one consumer that needs a *directory*, `_program_env`'s
cwd, falls back to `pane["path"]`, the directory ⌫ returns to.

## Header

`PaneHeader` reads `virtual["kind"]`, which the search feed had written since
the start and nothing had read: `"list"` renders `{title} — N items`; anything
else keeps the search banner. The Info dialog's content-hit metadata reads
`virtual.get("mode")`, since a list has none.

## Deliberately not done

- **No cap.** `_RESULT_CAP` belongs to the search dialog. The user chose this
  exact set; truncating it silently would be worse than a slow import, and the
  probe is off the UI thread.
- **No history.** A clipboard list cannot be reopened; saved lists belong with
  the command source, which has something to re-run.
- **No native file-list clipboard** (CF_HDROP, `NSFilenamesPboardType`). PuiKit
  reads plain text only; that is stage ④.
- **No attributes from the source.** A source that already knows size and
  mtime (an `.efu` export, `find -printf`) still has them re-read. Accepting
  `EntryInfo` in `show_list` is additive if it is ever wanted.

## Tests

`test/test_path_list.py` covers the pure half against a `fake://` scheme
registered for the test (host as root, like `ssh://`, including a down host
that must be tried once), and the app half headless on the memory backend.
`test/test_search_results_pane.py` and `test/test_xefm_app_async_listing.py`
cover the virtual listing moving to a worker.
