# Search Results Pane Implementation

Accepting a hit from the progressive search dialog does **not** navigate to that
one file — it **feeds the whole result set into the active pane** as a flat,
virtual listing ("Search Results" pane, à la Total Commander's *Feed to
listbox*). The result set spans many directories, and every existing pane
operation (copy/move, archive, view/diff, delete/rename, sort & filter, info,
edit, run-command) then acts on it as if it were an ordinary directory.

Source: [`xefm/app.py`](../../xefm/app.py) (the app-side wiring),
[`xefm/file_list_manager.py`](../../xefm/file_list_manager.py) (the listing
choke point), [`xefm/file_pane.py`](../../xefm/file_pane.py) (name-column
rendering). Tests: [`test/test_search_results_pane.py`](../../test/test_search_results_pane.py).

The dialog that *produces* these hits — the live, search-as-you-type
filename/content finder, its cancel-on-keystroke background worker, and its result
caps — is `ProgressiveSearchDialog` in
[`xefm/progressive_search_dialog.py`](../../xefm/progressive_search_dialog.py);
see that module's docstring for the threading model. This document covers only
what happens *after* a hit is accepted (feeding the result set into the pane).

---

## Why a virtual pane (not an in-dialog action surface)

Three approaches were considered: (A) navigate-then-operate on one file — the
status quo, too thin; (B) mark files and act **inside** the search dialog —
rejected because it rebuilds a second selection + operations surface that
duplicates what the pane already offers; (C) **feed results into a virtual pane**
— chosen. C reuses the real selection UI, the real menu, and every existing op.

The enabling fact: operations read their targets from `pane["files"]` +
`pane["selected_files"]`, and each target is a **self-describing `Path`**. Copy /
move send to the *other* pane, so a flat listing of scattered paths makes those
operations Just Work — the cost is concentrated in teaching the *pane model* that
its listing may be virtual, not in touching each operation.

---

## The virtual-pane data model

A pane becomes virtual by carrying a `virtual` marker alongside its normal
fields (set by `XeFMApp._feed_search_results`):

```python
pane["virtual"] = {
    "kind": "search",
    "root":  Path,                 # search root the walk started from
    "mode":  "filename" | "content",
    "query": str,
    "results": list[Path],         # full found set — the immutable source of truth
    "meta":  dict[str, dict],      # per-path extras, keyed by str(path)
}
```

- `pane["files"]` holds the **currently displayed** view — `results` after the
  pane's own sort + filter applied *in memory*. `results` is the source; `files`
  is the derived view.
- `pane["path"]` is retained as the search **root** for display/context, but is
  never re-listed while virtual.
- `selected_files`, `focused_index`, `scroll_offset` behave exactly as normal.
- Non-virtual panes leave `pane.get("virtual")` as `None`; every guard below is
  an `if pane.get("virtual")` branch, so real panes are untouched.

`meta` carries what isn't part of the `Path` — chiefly, for **content** hits, the
matched line number and text (`{"line": int, "text": str}`). It is not rendered
in the file list; it surfaces in the Info dialog and drives reveal-at-line. A
filename-search set leaves it empty.

---

## Single choke point: `FileListManager.refresh_files`

All virtual behavior funnels through `FileListManager.refresh_files`
([xefm/file_list_manager.py](../../xefm/file_list_manager.py)): when
`pane['virtual']` is set it re-stats the result set (drops vanished paths, prunes
`meta`), then filters + sorts **in memory** via `compute_listing_from_paths`. So
sort, filter, and post-operation reconciliation all Just Work, and every existing
`refresh_files` / `_refresh` caller is unchanged.

`XeFMApp._refresh` gained a virtual branch (synchronous re-stat, no re-list). The
subsystems that assumed `files == children of path` each got a virtual guard:

- **Listing / refresh** — a virtual pane must never re-list `pane["path"]` (that
  would destroy the result set); `_refresh` re-stats the surviving result paths
  and re-applies the in-memory sort/filter instead.
- **File monitoring** — the reload pump (`_handle_reload_request`) skips virtual
  panes; there is no single directory to watch, so monitoring is suspended and
  the set is a snapshot.
- **Navigation that sets a real `path`** — enter-directory, go-up, and
  jump-to-favorite/drive/history call `_exit_virtual` first, which clears
  `pane["virtual"]` and returns the pane to a normal listing. This is the natural
  "exit."
- **Header / status** — a virtual pane renders a `⌕ "query" — N results` banner
  instead of the path, so it's clear this is a result set, not a directory.

---

## Operations on a virtual pane

`_selected_or_focused(pane)` returns scattered `Path`s; unless noted, the
operation consumes that and works **unchanged**.

| Op | Notes |
|----|-------|
| Copy / move | Source = scattered paths; dest = other pane. Post-op re-stat drops moved sources. A **virtual destination is blocked** with a message; the same-dir guard is skipped for a virtual source. |
| Archive create | Operates on an arbitrary path list already; archive lands in the other pane. |
| View / Diff / Edit | Read the focused / selected `Path`(s) directly. |
| Delete / Rename / batch-rename | Use `entry.parent / name`; post-op re-stat drops or re-points affected entries. |
| Info / details | For a content hit, appends the matched **line number** (+ text) from `virtual["meta"]`. |
| Sort / Filter | Re-sort / re-filter the in-memory `results` (via `refresh_files` → `compute_listing_from_paths`), not a directory re-list. The existing sort/filter actions just set the knobs and call `_refresh`; no new key bindings. |
| Run-command | Passes **absolute paths** with `cwd` = search root (bare names with `cwd=pane["path"]` would not resolve for scattered files). |

**Post-operation reconciliation.** A virtual pane can't re-list, so after a
mutating op `_refresh` re-stats each `Path` in `results` (dropping vanished ones,
re-pointing renamed ones), re-applies sort + filter, and clamps `focused_index` /
`selected_files` to the survivors.

---

## Entry & reveal UX

**Entry — feed-by-default.** The dialog's `on_accept` closes it and calls
`_feed_search_results(mode, dialog.results, root, query, focus=value)` with the
dialog's full result list *plus* the accepted hit. For **content** mode, results
collapse to **one entry per file** (operations act on files, not lines), keeping
the *first* match's `{line, text}` in `virtual["meta"]`. The set is fed at the
dialog's `_RESULT_CAP` (1000); the cap is noted in the header banner.

The accepted `value` does not navigate, but it does decide **where the cursor
lands**: `_focus_result` places the cursor on that hit's row in the fed listing
and scrolls it into view (issue #224). Matching is by **full path**, not name —
a result set spans directories, so two hits can share a basename. The fed order
is the walk order while `pane["files"]` is sorted, so the row must be looked up
after `refresh_files`. Feeding without a `focus` (or with one that filtered out)
leaves the cursor at the top, as before.

**Reveal a result's location.** Since accept no longer navigates, the pane-sync
keys reveal the highlighted hit's real location, driven by **whichever pane holds
the results** — so you can stand on a *normal* pane (results on the other side)
and pull the highlighted hit's location in. **Neither key destroys the results
listing.**

- **O** (`sync_current_to_other`) = "go to the other pane's location, cursor
  there." If the **other** pane is the results view, its location is the
  highlighted hit's directory (cursor on that file) — so from a normal pane you
  pull the highlighted hit's location *here*. If **this** pane is the results
  view, O behaves like a normal pane: leave the results and open the *other*
  pane's directory, cursor synced. Both go through `_go_to_dir`; neither keeps a
  stale virtual listing.
- **Shift-O** (`sync_other_to_current`) → `_reveal_result_other`: from the
  results pane, open the highlighted result in the *other* pane, keeping the
  results intact. Blocked (with a message) if the other pane is the results view.

The name column shows each hit's **root-relative path** (`FilePane._display_name`,
middle-elided) so a scattered result set reveals where each file lives.

---

## Scope

First cut is **local-filesystem** results only (no S3/SSH-remote result sets), no
persistent/saved-search abstraction, and — deliberately — no second in-dialog
operations surface (approach B above). If **both** panes are virtual, copy/move
into the virtual destination is blocked with a clear message rather than
supported.
