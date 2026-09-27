# File List Import — Implementation

Stages ①, ② and ③ of [#453](https://github.com/crftwr/xefm/discussions/453):
a list of paths from outside XeFM — the clipboard, a list file, or a
command's output — becomes a virtual pane. User-facing behavior is in
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
| One door for every source | `XeFMApp.open_path_list(pane_name, paths, *, title, base=None)` |
| The clipboard source | `XeFMApp.import_list_from_clipboard` (action `import_list_from_clipboard`, unbound) |
| The command source | `XeFMApp.import_list_from_command` → `_run_list_command` → `_open_command_output`; the blocking half in `xefm/command_list.py` |
| The file source | `XeFMApp.import_list_from_file` (action `import_list_from_file`, unbound; "Open as List" on the context menu); `path_list.read_lists` |
| The shared report | `XeFMApp._open_list(pane_name, *, title, load, relative_to)` |
| The public door | `PaneApi.open_list(paths, *, title)` in `xefm/user_api.py` |
| Listing a virtual pane off the UI thread | `XeFMApp._list_virtual`, `FileListManager.compute_virtual_listing` / `prune_virtual` |
| Whole-path names | `name_key.WHOLE_PATH` |

Every source ends in `_open_list` and chooses its own base for relative
lines: the pane's directory for the clipboard, the command's cwd for a command,
each list file's own directory for a file.

`_open_list` hands `_list_virtual` a `load()` callable that runs **on the
listing worker** and returns the `Resolved` set, rather than a set resolved on
the UI thread. For the clipboard and `open_list` that only moves resolving;
for a list file it moves the read itself, which on an `ssh://` or `s3://` list
is a network round trip. The worker adds `total`, `relative` and `problems`
(unreadable list files) to the result for the report.

## The flow

1. **UI thread.** `path_list.parse` splits the text; `path_list.resolve` turns
   lines into `Path`s — URIs and absolute paths as they are, relative ones
   joined onto `base` and counted. Duplicates collapse. Nothing is read from
   disk.
2. `open_path_list` builds `{"kind": "list", "title": …, "root": None,
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

## The file source

`import_list_from_file` takes the selection, or the file under the cursor,
skipping directories, and `path_list.read_lists` reads each through
`Path.read_bytes` — so a list on any backend works, and its relative lines
resolve on that backend. The base is **the list file's own directory**, the
M3U / `.gitignore` / response-file convention: a list kept beside what it
names survives the folder moving and reads the same from either pane. Several
lists merge in order, each path once; one that cannot be read is skipped and
named in the report.

Decoding is `path_list.decode`, shared with the command source and moved here
from `command_list`. It honours a byte-order mark first — UTF-32, UTF-8, or
**UTF-16**, which is what Windows PowerShell 5.1's `Out-File` and `>` write and
Notepad calls "Unicode", and which would otherwise read as NUL-riddled ANSI —
then UTF-8, then the ANSI code page on Windows or the filesystem encoding with
`surrogateescape` on POSIX.

## The command source

`import_list_from_command` opens a command field over the command history
(state key `list_command.history`, most recent first, capped at 100), and
`_run_list_command` runs the field's text on a `Task`, so the existing
`ProgressDialog` shows it and Esc cancels it.

The field is `xefm/history_input_dialog.py`'s `HistoryInputDialog`, which the
`;` Filter prompt uses too. It exists because the searchable picker
(`FilterListDialog`) is the wrong shape for text that is typed and used: its
Enter takes the highlighted row and falls back to the typed text only when
nothing matches, so typing `rg -l` with `rg -l TODO` remembered ran the old
command. Here Enter always takes the field. Focus is on one side at a time
(`ListView(allow_no_selection=True)`): typing narrows the list but highlights
nothing; ↓ highlights a row and copies `to_text(row)` into the field without
re-filtering — the list stays filtered by `query`, the last *typed* text, as
an address bar does; editing the copied text makes it the new query; ↑ past
the first row or Esc puts the typed text back. `to_label` / `to_text` let a
row draw one thing and stand for another: the Filter prompt's defined filters
draw a label and go into the field as their name, and "clear filter" as an
empty field. A second click on a row within 0.4 s uses it (the directory diff
viewer's threshold; PuiKit reports no double-click).

It replaced a first attempt on the picker itself — a Tab key (`edit_list_item`)
that closed the picker and reopened the row in an input dialog — which fixed
the trap only for a user who knew to press Tab, and was removed before any
release.

The progress dialog has no item total to show, so it stays in its busy phase;
`Task.busy_label` (new, default `"Preparing…"`) lets it say `Running… (N items)`
with `task.counted` fed from the line count.

`command_list.run` is the blocking half:

- **Shell.** `Popen(command, shell=True)`: the user typed a command line, and
  pipes and quoting should mean what they mean at a prompt.
- **Environment and cwd** come from `_program_env(pane)`, the function
  `PROGRAMS` and `ctx.run_program` already share, so the `XEFM_*` contract
  cannot drift. A cwd that is a URI (`ssh://`, `s3://`, an archive) is refused
  before prompting; remote execution is a later stage.
- **Reading.** Two reader threads drain stdout and stderr as bytes (`read1`, so
  the line count moves while output arrives); stdin is `DEVNULL`.
- **Cancel.** The run loop polls the task's flag. POSIX starts the command in
  its own session and `killpg`s it; Windows runs `taskkill /T /F`. Killing only
  the shell would leave its children writing into a pipe nobody reads, and the
  readers would never see EOF.
- **UTF-8 on Windows.** Console programs write to a pipe in their console's
  output code page, and the hidden console a child of the GUI gets is the
  system OEM one: on an English system (cp437) `es.exe` and `dir /b` print a
  Japanese name as `????`, lost before XeFM reads a byte. `chcp 65001` fixes
  external programs, but `cmd` reads the code page once at startup, so its
  built-ins keep cp437. The command therefore runs in a second `cmd` started
  after `chcp`:
  `cmd /d /v:on /s /c "chcp 65001>nul & cmd /d /s /c "!XEFM_LIST_COMMAND!""`.
  The command travels in `XEFM_LIST_COMMAND` and is expanded by *delayed*
  expansion, after the outer `cmd` has parsed its line, so only the inner
  `cmd` parses it — `%VAR%`, `!`, quoted `|`, `^&` and `&&` behave as at a
  prompt, and the exit code is the command's (`_windows_command_line`).
- **Decoding** happens once, over the whole output (`path_list.decode`,
  described under the file source): UTF-8; else the ANSI code page on Windows (programs that
  ignore the console's code page — the C runtime's `printf`, Python); else the
  filesystem encoding with `surrogateescape` on POSIX, so an undecodable name
  still round-trips to the bytes on disk.

`_open_command_output` routes the last five stderr lines to the log pane as
STDERR, and shows whatever paths arrived **regardless of the exit code** —
`grep`/`rg` exit 1 for "no match" and `find` exits 1 after one unreadable
directory. The code is reported only when no path arrived.

**Refresh does not re-run the command.** #453's follow-up proposed re-running
it on refresh. Refresh here is the post-operation reconciliation, which fires
after every delete, move and rename: re-running `find` there is slow, and a
re-run can reorder rows under the cursor. The pane prunes vanished rows like
any list, and re-running is the menu item (whose field holds the command).
A re-runnable list belongs with saved lists, where there is an explicit verb
for it.

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
the start and nothing had read (`_virtual_header_text`). Neither form carries a
row count; the footer already shows one.

- `"list"` renders `[title] root`, and the **root has priority**. It is derived
  from the paths rather than chosen by the user, so the header is the only
  place that says what a row's `src/main.py` is relative to. When space runs
  out the title is cut first, down to `Cl…`, and only then is the root
  shortened by whole components (`abbreviate_path`). `WHOLE_PATH` shows the
  title alone.
- A search renders `⌕ "query" (mode)  ·  root`, and there the banner has
  priority: the root is the directory the user searched from, and it is
  dropped rather than shown as a fragment.

The Info dialog's content-hit metadata reads
`virtual.get("mode")`, since a list has none.

## Deliberately not done

- **No cap.** `_RESULT_CAP` belongs to the search dialog. The user chose this
  exact set; truncating it silently would be worse than a slow import, and the
  probe is off the UI thread.
- **No saved lists, no named commands.** A clipboard list cannot be
  reopened, and a command list is re-run from its history. Named commands (a
  `PROGRAMS`-like table) and a list that re-runs on request would need a verb
  for "run it again", which a post-operation refresh is not.
- **No remote execution.** On an `ssh://` pane the command could run on the
  server and its output be read as `ssh://` paths; not done yet, and refused
  rather than run locally.
- **No native file-list clipboard** (CF_HDROP, `NSFilenamesPboardType`). PuiKit
  reads plain text only; that is stage ④.
- **No attributes from the source.** A source that already knows size and
  mtime (an `.efu` export, `find -printf`) still has them re-read. Accepting
  `EntryInfo` in `open_list` is additive if it is ever wanted.

## Tests

`test/test_command_list.py` runs real subprocesses through the shell (this
Python, so nothing needs installing): output and line counts, cwd, exit code
and stderr tail, a pipe, stdin at EOF, cancel stopping the whole tree (timed:
a surviving child would hold stdout open), a command that cannot start, and
the app half on the memory backend.

`test/test_path_list.py` covers the pure half against a `fake://` scheme
registered for the test (host as root, like `ssh://`, including a down host
that must be tried once), and the app half headless on the memory backend.
`test/test_search_results_pane.py` and `test/test_xefm_app_async_listing.py`
cover the virtual listing moving to a worker.
