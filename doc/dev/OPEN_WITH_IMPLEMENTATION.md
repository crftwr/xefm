# Open With — Implementation

Issue #634. User-facing behavior: [doc/OPEN_WITH_FEATURE.md](../OPEN_WITH_FEATURE.md).

## Decisions

The issue laid out three sources (A: the OS's list, B: XeFM's own list,
C: both) and three ways to relate the result to External Programs. What was
chosen, and why:

- **C, both merged.** XeFM's entries first, then the OS's. B alone shows
  nothing until configured; A alone is GUI-only and meaningless over SSH.
- **Kept apart from `programs` (X).** `PROGRAMS` stays the unfiltered list of
  commands about XeFM's state; Open With lists what fits the files. The
  config key is `open_with` on FILE_ASSOCIATIONS rules, not a `pattern` on
  `PROGRAMS` entries — patterns already live in FILE_ASSOCIATIONS.
- **Strict intersection** for a mixed selection, as Finder does. The
  partial variant (`3/5 files`) needs UI to say what was skipped; it can
  come later on demand.
- **Local files only.** Same rule as the `open` / `view` / `edit`
  associations (`_launch_associated`). A download-first path like Remote
  Edit is a possible follow-up.

## Pieces

| Where | What |
|---|---|
| `xefm/config.py` `get_open_with_for_file` | Concatenates the `open_with` lists of every matching rule, deduplicated by name (first wins). `open_with` is in `_RESERVED_KEYS`, so `_lookup_action` never mistakes it for an action. Entries are normalized by `_program_entry`, shared with `get_programs`. |
| `xefm/open_with.py` | `Candidate`, `intersect`, `xefm_candidates`, `os_candidates`, `os_apps_available`, `launch`, plus `remembered_first` / `type_key`. No UI. |
| `xefm/app.py` `open_with` / `_open_with_candidate` | Filters the targets, builds the list, opens a `FilterListDialog`, launches, remembers. |
| `xefm/actions.py` | The `open_with` action (FILER), unbound in every preset. Reached by File → Open With ▸ Choose App…, the item context menu and the palette. |

## Identity and intersection

A `Candidate.key` decides "the same candidate" across files:

- XeFM's entries: `xefm:<name>`. Matching by command was rejected — one
  argument's difference would split an entry in two.
- macOS: `os:<bundle identifier>` (the app path when there is none).
- Windows: `os:<IAssocHandler::GetName>` lowercased — the handler's
  executable, which is what makes `.jpg`'s and `.png`'s Photos one entry.
- Linux: `os:<desktop ID>`.

`intersect` keeps the first file's order and entries, so a name two rules
declare with different commands runs the first file's. `default` is kept only
when it held for every file.

The OS is asked once per extension (`_type_of`), not per file: a hundred
photos is one LaunchServices query.

## The OS side, per platform

- **macOS** — `NSWorkspace.URLsForApplicationsToOpenURL:` (macOS 12+; on 11
  only `URLForApplicationToOpenURL:`, the default, is listed). pyobjc comes
  with PuiKit. Launch: `open -a <app path> <files…>`.
- **Windows** — `SHAssocEnumHandlers(ext, ASSOC_FILTER_RECOMMENDED)` over
  comtypes, with the `IAssocHandler` / `IEnumAssocHandlers` /
  `IShellItemArray` vtables declared by hand (shell32 ships no typelib for
  them). The default is told by comparing `AssocQueryStringW(
  ASSOCSTR_EXECUTABLE)` with the handler's name. Launch: the files become
  PIDLs → `SHCreateShellItemArrayFromIDLists` → `BindToHandler(BHID_DataObject)`
  → `IAssocHandler::Invoke`, which is how Explorer hands several files to one
  handler and is the only way that reaches packaged (Store) apps. The handlers
  are COM objects of the UI thread's apartment and are used on that thread
  only; `_windows_com_ready` initializes COM there if comtypes was first
  imported elsewhere.
- **Linux** — `gio info` for the content type, `gio mime <type>` (under
  `LC_ALL=C`, since its headings are what is parsed) for the default and
  registered desktop IDs, the `.desktop` file's `Name=` for the label.
  Launch: `gio launch <desktop file> <files…>`.

Launches are detached with stdio on `/dev/null`: in the TUI the child must
not write over the screen.

`os_apps_available(desktop)` is the gate: always in desktop mode; in a TUI not
when `SSH_CONNECTION` / `SSH_CLIENT` / `SSH_TTY` is set, and on Linux only
with `DISPLAY` or `WAYLAND_DISPLAY`.

A failure while asking the OS is logged as a warning and yields no OS rows;
XeFM's own entries are still offered.

## Launching XeFM's entries

Through `_launch_program`, exactly as a `PROGRAMS` entry — `_program_env`
supplies the pane directory and `XEFM_*`, `options['terminal']` picks
suspend/resume (TUI) or a `TERMINAL` window (desktop) — with one difference:
the files are passed as absolute paths, since an Open With selection is
already resolved to real files (`_real_entry`, for `.xft` references).

## Remembering

`state_manager` key `open_with.last`: a dict from `type_key(paths)` — the
selection's distinct extensions, sorted and comma-joined — to the chosen
`Candidate.key`. `.jpg` alone and `.jpg` + `.pdf` are separate keys because
they offer different lists.

## Not done

- Partial matches for a mixed selection.
- Remote / in-archive files (download first).
- "Always open this type with…" writing the `open` association.
- Icons in the list.

## Tests

`test/test_open_with.py` — config concatenation and normalization, that
`open_with` is not an action, intersection and `default`, per-type caching,
the SSH / Linux gates, `gio mime` parsing, the macOS argv, and
`XeFMApp.open_with` on a stand-in self (ordering, skipping, launch, memory,
the empty case). The Windows COM path has no automated test; it needs a hand
check on Windows.
