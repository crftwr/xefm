# Stable API plan — `API_VERSION` 1

**Status: implemented (#713).** Settled in conversation on 2026-10-23. One
change while implementing: `DISPLAY_PREFIX` and `get_display_title()` turned
out to be read nowhere in XeFM, so they are Preview rather than stable
overrides (§3.1).

The per-API Preview mechanism from #632 (`xefm/preview.py`, `@preview`,
`PREVIEW_APIS`, the `STABLE` test in `test/test_user_task_api.py`) is already in
place, and today every public API but `ActionContext.api_version` is still
Preview. Shipping a stable API means four things:

1. Remove the mark from the APIs we are confident in.
2. Settle the APIs whose boundary is unclear today: XeFM's `Path`,
   `PathImpl` subclassing, and the names `config.py` imports.
3. Set `API_VERSION = 1`.
4. Make the docs, the log notices and `xefm ext check` say the same thing,
   and tell extension authors which Preview APIs they use (§4.1).
5. Make future changes to the API impossible to miss (§7).

The rule for what stays Preview: mark it Preview if it is new, has an open
design question, has planned work that would reshape it, or exposes a type we
do not own.

---

## 1. Classification

### Stable

| API | Notes |
|---|---|
| `config.ACTIONS`, `manifest.contributes.actions` | Oldest surface (2026-08-22). The `context` key accepts only `'filer'`; viewer contexts would be an addition later. |
| `config.SORT_KEYS`, `manifest.contributes.sort_keys` | 2026-09-05 |
| `config.FILTERS`, `manifest.contributes.filters` | 2026-09-05 |
| `manifest.contributes.key_suggestions` | Plain data |
| `EntryInfo` | All of it except the constructor's `name=` (§2.4). `from_attrs` becomes `_from_attrs`. |
| `PaneApi` | All of it except `open_list` |
| `ActionContext.pane` / `other` / `left` / `right` | |
| `ActionContext.invoke` | Built-in action names already keep resolving after a rename (`Action.aliases`). That becomes a stated promise. |
| `ActionContext.run_program` | |
| `ActionContext.message` | |
| `ActionContext.action_names()` | **Without its `context` parameter** (§2.3) |
| `ActionContext.api_version` | Already stable |
| `Path`, as reached through `EntryInfo.path`, `PaneApi.path` and `cd()` | The stable member set in §2.1 |
| `xefm_tool`, `xefm_python`, `is_desktop_mode` | §2.5 |
| `PATH_SCHEMES`, `manifest.contributes.path_schemes` | The stable parts of the table in §3.3 |
| `ReadOnlyPathImpl`, `UriStatResult` | The members in tiers A, C and B-high of §3.1 |

### Preview

| API | Why |
|---|---|
| `PaneApi.open_list` | Renamed once (`show_list`), and its semantics are intricate |
| `ActionContext.input` / `choose` / `confirm` | Whether the callback shape is livable is still open (CUSTOMIZATION_API_IMPLEMENTATION §8) |
| `ActionContext.run_task`, `TaskJob`, `TaskOutcome` | 2026-10-22; `item_progress` arrived the same week |
| `ActionContext.show_markdown` / `copy_text`, `md_code_block`, `md_escape` | 2026-10-22 |
| `extension()`, `manifest.settings` | 2026-10-22, when it replaced `ctx.extension` |
| `config.EVENT_HOOKS`, `HookEvent`, `manifest.contributes.event_hooks` | The `(ctx, event)` shape is from 2026-10-22. Whether `directory_changed` fires on virtual panes is open. |
| `config.MENU_ITEMS`, `manifest.contributes.menus` | Viewer-specific menus are planned |
| `config.IMAGE_DECODERS`, `manifest.contributes.image_decoders` | The contract names PuiKit's `RasterImage`, and the thumbnail view (#638) is likely to touch it |
| `config.LEXERS`, `manifest.contributes.lexers` | Markdown fences need a PuiKit hook, and a hand check is still owed |
| `manifest.contributes.themes`, `manifest.requires`, `manifest.extension.updates` | New |
| `UriPathImpl` | Newly published, as Preview (§3.2) |
| `PATH_SCHEMES` `"override": True`; `ReadOnlyPathImpl` members in tier B-low/mid | §3 |

### Not public

These are neither Stable nor Preview:
- `PathImpl` subclassed directly (§3.2)
- The seven `Path` methods moved out in §2.2
- Every `_`-prefixed name
- Everything outside `xefm.user_api` and `xefm.path_base`, except the
  compatibility import paths in §2.5

---

## 2. The caller side

### 2.1 `Path` — the stable member set

`Path` reaches stable signatures, but it is not importable (`xefm.path` is
internal). What a stable API promises is therefore its **member set**:

- **pathlib-compatible members that `Path` implements today**
  - Path arithmetic: `name`, `stem`, `suffix`, `suffixes`, `parent`,
    `parents`, `parts`, `anchor`, `joinpath`, `/`, `with_name`, `with_stem`,
    `with_suffix`, `relative_to`, `is_absolute`, `absolute`, `resolve`,
    `expanduser`, `match`, `as_posix`, `as_uri`
  - Queries: `exists`, `is_dir`, `is_file`, `is_symlink`, `stat`, `lstat`,
    `samefile`, `iterdir`, `glob`, `rglob`
  - I/O: `open`, `read_bytes`, `read_text`, `write_bytes`, `write_text`,
    `mkdir`, `rmdir`, `unlink`, `rename`, `replace`, `touch`, `chmod`,
    `symlink_to`, `hardlink_to`
  - The exact list is taken from the code when this is implemented.
- **`str(path)`**: a filesystem path for local files and a URI
  (`ssh://…`, `s3://…`, `archive://…#…`) otherwise.
- **XeFM additions**
  - `supports(capability)`. Promised capabilities: `write_operations`,
    `directory_rename`, `file_editing` and `streaming_read`. Unknown names
    return `False`.
  - `target()`
  - `is_remote()`
  - **`scheme`**, a new read-only property that replaces `get_scheme()`.
    `Path.get_scheme()` is removed and its 31 internal callers are moved to
    the property. `PathImpl.get_scheme()` stays, because it belongs to the
    implementer side.

Stated in the docs:
- Write operations may raise `OSError` where the storage is read-only
  (archives, read-only virtual folders).
- pathlib members that `Path` lacks (`walk`, `is_relative_to`, `readlink`, …)
  may be added later; that is not a breaking change.

The API snapshot (§7.1) fixes the public `dir(Path)` to this list, so a new
public member has to be classified on purpose.
`Path`'s docstring lists the set.

### 2.2 `Path` methods that leave the class

Seven methods move from `Path` methods to module functions in `xefm.path`
(`path.copy_to(dest)` becomes `copy_to(path, dest)`). Extensions cannot import
`xefm.path`, so the existing import rule in `ext check` enforces this with no
new heuristics.

| Method | Why not public |
|---|---|
| `copy_to`, `move_to` | Two failure channels (`False` and exceptions). `overwrite` replaces a file but silently merges a directory. Copying behaves differently per storage. Bypasses XeFM's file operations (conflict dialog, job queue, progress, archive owners #516). Diverges from Python 3.14's `pathlib.Path.copy` / `move`. If extensions need copy or move, that gets designed as a separate Preview `ctx` API that goes through file operations. |
| `listdir_attrs` | Returns the internal `dir_scan` record (`alloc`, `ok`, `cmp_name`, …) |
| `concurrency` | Internal tuning |
| `forget_cached_metadata` | Exposes a cache detail |
| `get_display_title` | UI string whose format may change |
| `get_extended_metadata` | Shaped for the info dialog (`format_hint`); #635 will change it |

The `PathImpl` hooks of the same names stay where they are (§3.1, tier B).

Documented limit: dynamic access (`getattr(p, "_x")`) is beyond any static
check. "Names starting with `_` and functions in `xefm.path` are not API. The
check helps you keep to that; it does not guarantee it."

### 2.3 `action_names()`

Remove the `context` parameter. It exposes nine internal context names
(`isearch`, `filter_list`, `search`, …), yet `invoke()` runs only `filer`
actions. The no-argument form is the stable one.

### 2.4 Constructors

- `ActionContext(app)` and `PaneApi(app, name)` take `XeFMApp`. Only XeFM
  constructs them, and the docs say so.
- `EntryInfo(path, *, is_dir=False, is_link=False)` is promised, because
  extension tests build fakes with it. `name=` carries the listing's compared
  name and is internal.

### 2.5 `xefm_tool`, `xefm_python`, `is_desktop_mode`

PROGRAMS depends on these, and nothing else does their job. They become Stable.

- Their home becomes `xefm.user_api`, added to `__all__`, so extensions get
  them too.
- **The old import paths stay working, as a promise.** Every generated
  `config.py` contains `from xefm.external_programs import xefm_tool,
  xefm_python` and `from xefm.backend_detector import is_desktop_mode`. Only
  these three names are promised at those paths; the rest of both modules
  stays internal. A test checks that both paths give the same object.
- The `config.py` templates (`xefm/_config.py` and
  `xefm/skills/xefm/references/config-template.md`) switch to importing from
  `xefm.user_api`. Check for circular imports during implementation.
- What each one promises:
  - `xefm_python`: the path (a `str`) of a Python 3 interpreter that can run a
    script found by `xefm_tool`. Which packages it has is not promised.
  - `xefm_tool(name)`: searches `~/.xefm/tools/` and then the bundled
    `xefm/tools/`, and returns a `str` path. If nothing is found it returns
    `name` unchanged.
  - `is_desktop_mode()`: `bool`.
- **The bundled tool names are part of the promise**: `vscode.py`, `kiro.py`
  and `example_tool.py`. Default PROGRAMS entries copied into users' configs
  name them.

---

## 3. The implementer side (`PATH_SCHEMES`)

### 3.1 Tiers for a `ReadOnlyPathImpl` subclass

**A. Required.** `SCHEME`, `exists()`, `is_dir()`, `iterdir()`, `stat()`, `open()`

**B. May override.** Each has a default.

| Member | Confidence | Status |
|---|---|---|
| `READ_ONLY_MESSAGE`, `IS_REMOTE` | high | Stable |
| `target()` (default `None`) | high | Stable |
| `DISPLAY_PREFIX`, `get_display_title()` | — nothing in XeFM reads them (found while implementing), so there is no behaviour to promise | Preview |
| `parse_uri(uri)` / `root_prefix()` (the URI parsing hooks) | mid | Preview |
| `CAPABILITIES`, `SEARCH_STRATEGY` | low: the vocabulary mixes in search tuning | Preview |
| `listdir_attrs()` | low: internal record shape | Preview |
| `get_extended_metadata()` | low: #635 | Preview |
| `forget_cached_metadata()`, `CONCURRENCY` / `READ_CONCURRENCY` / `WRITE_CONCURRENCY` | low: implementation detail | Preview |

**C. Helpers a backend calls.** `child(name)`, `at(key)`, `key`, `UriStatResult`. Stable.

**D. Do not override.** Everything else: path arithmetic, `__eq__` /
`__hash__`, the write refusals, `supports`, …

**Renames**, free while Preview. They take the contract off private names.

| Today | After |
|---|---|
| `_child(name)` | `child(name)` |
| `_at(key)` | `at(key)` |
| `_key` | `key` (read-only property) |
| `_parse(uri)` | `parse_uri(uri)` |
| `_root_prefix()` | `root_prefix()` |

These live on `UriPathImpl`. `Path` does not delegate them, so they do not
leak into §2.1. Update `doc/VIRTUAL_FOLDERS_FEATURE.md`, the skill references
and the tests that use `_child`.

**What XeFM promises the backend:**
- XeFM calls only tiers A and B. Reads go through `open`, `iterdir` and
  `stat`.
- Calls may come from any thread, the UI thread or a worker, possibly at the
  same time.
- Write operations are refused before the call (`supports`) and refuse if
  called anyway. A virtual folder can be the source of a copy.
- A method XeFM calls never gains an argument. Something new arrives as a new
  member that has a default. This rule already exists in the design doc.

The `@preview` mark moves from the class to the individual Preview members.
The API snapshot (§7.1) fixes the tiers, as it does for `Path`.
`test_published_base.py` keeps guarding that no new abstract method reaches
`ReadOnlyPathImpl`.

### 3.2 `UriPathImpl` → Preview, `PathImpl` → unsupported

- **`UriPathImpl`** is the writable route. It joins `path_base.__all__` with
  `@preview` on the class.
  - It works today: the cross-storage copy has a generic branch
    (`read_bytes` → `write_bytes`) for any scheme.
  - `test_published_base.py` already pins its abstract set to the five plus
    nine writes.
  - Documented as Preview:
    - Declare `write_operations` (and, if it applies, `directory_rename`) in
      `CAPABILITIES`.
    - A copy across schemes reads the whole file into memory and shows no
      progress.
    - A move is `rename` within a scheme and copy + delete across schemes.
- **`PathImpl` subclassed directly** is not supported. It is deliberately
  strict (48 abstract methods, nine added between v0.98 and v1.0.4), and
  `UriPathImpl` leaves no reason to start from it. `PATH_SCHEMES` validation
  **warns** when a class is not a `UriPathImpl` subclass, and loads it anyway.

### 3.3 The `PATH_SCHEMES` table

| Item | Status |
|---|---|
| Key: a scheme name (lowercase, starts with a letter, may contain `+ - .`) | Stable |
| Value: a `ReadOnlyPathImpl` subclass, or `{"class": cls}` | Stable |
| `{"impl": cls}`, an undocumented alias | Removed |
| `"override": True` (replacing `s3://`, `ssh://`, `archive://`) | Preview |
| A class not based on `ReadOnlyPathImpl` | Outside the promise. `UriPathImpl` is Preview; `PathImpl` gets the warning above. |
| The same key from two sources | Stable, as it behaves today (below) |

How a key from two sources resolves today, in `extensions._apply`, for every
table: `config.py` wins over an extension. Between two extensions, the one
loaded first wins, and extensions load in ascending order of their package
directory name. **Bug to fix:** when one extension loses to another, its
warning says "is also in config.py". It should name the extension that won.

---

## 4. Version, notices, check

- `API_VERSION = 1`. Its comment says that 0 meant everything was Preview.
- Extensions declaring `api_version = 0` keep loading with the existing
  "written for API version 0" warning. Nothing is refused.
- `preview_notice()` reports only the Preview tables (`EVENT_HOOKS`,
  `IMAGE_DECODERS`, `PATH_SCHEMES` with `override`, `LEXERS`, `MENU_ITEMS`).
  Its signature narrows to those counts. A config that uses only stable
  tables gets no line.
- `app._report_extensions`: `(Preview API 0)` becomes `(API 1)`.
### 4.1 Telling an extension author which Preview APIs they use

Without this, the Stable / Preview split exists only in docstrings and docs.
Nothing in the workflow (write → `xefm ext check` → `xefm try` → install)
would tell an author that they rely on Preview. It ships with `API_VERSION` 1.

**Static: `xefm ext check` reports every Preview use.**

| Target | How it is found | Confidence |
|---|---|---|
| Manifest sections (`contributes.menus`, `[settings]`, `[requires]`, `[extension] updates`, …) | The manifest itself | exact |
| Preview names from `xefm.user_api` / `xefm.path_base` (`TaskJob`, `md_escape`, `extension`, `UriPathImpl`, …) | The existing lint already binds these modules and resolves names | exact |
| A `ReadOnlyPathImpl` subclass defining a Preview tier-B member (`listdir_attrs`, `CAPABILITIES`, `parse_uri`, …) | Class bodies whose bases resolve to path_base classes | exact |
| A `PATH_SCHEMES` entry with `"override": True` in a manifest-referenced table | The table entry | exact |
| `ctx.<member>` / `ctx.pane.<member>` where the member is Preview (`run_task`, `show_markdown`, `copy_text`, `input`, `choose`, `confirm`, `open_list`) | Attribute access whose receiver is the first parameter of a function, or a name `ctx` (entry points take `ctx` first; so do `on_done` callbacks), matched against the Preview member names of `ActionContext` / `PaneApi` | near-exact |

The member and name lists come from `PREVIEW_APIS` at check time, so the check
never needs a hand-kept list.

- **A new severity, `preview`, beside `error` and `warning`.** Using Preview is
  legitimate. Reporting it as a warning would make every normal package noisy
  until warnings stopped being read. Output:

  ```
  preview: compute_hash/actions.py:42: ctx.run_task — Preview, may change in any release
  preview: xefm-extension.toml: contributes.menus — Preview
  4 Preview APIs in use; everything else this package uses is stable.
  ```

  A package with no Preview use prints nothing extra.
- **`--stable-only`** turns every `preview` finding into an `error`, for
  authors and CI that want to stay on the stable surface.
- Install, `xefm try` and startup loading never refuse a package for Preview
  use. Only errors gate them, and without `--stable-only` a `preview` finding
  is not an error. Callers that filter `Problem`s by severity (`errors()`, the
  install pre-check, the startup check) need checking so that the new severity
  is neither dropped nor promoted.
- The authoring skill (`references/extensions.md`) tells the agent to relay
  the `preview` lines to the user. That is what makes its existing "tell the
  user when the package rests on Preview APIs" instruction actionable.

**Runtime: one log line the first time a Preview API is used.**

- `@preview` wraps functions and methods. On the first call per (caller,
  API), it identifies the caller from the calling frame's module:
  - An extension module, through `handle_for_module`:
    `Extension compute-hash uses Preview API ActionContext.run_task`
  - Any other non-XeFM module (`config.py`, a hand-written module):
    `config.py uses Preview API ActionContext.run_task`
  - XeFM's own modules: not recorded, since XeFM calls some Preview APIs
    itself.
- After the first call, the cost is one set lookup.
- Subclassing `UriPathImpl` is recorded from `__init_subclass__`. Classes that
  XeFM instantiates and hands over (`TaskJob`, `TaskOutcome`, `HookEvent`) are
  not wrapped: they are reached only through a Preview entry point that is
  already recorded.
- Config tables keep their existing `preview_notice()` line. An extension's
  Preview manifest sections are named once in the startup "Extensions: …"
  report.
- It catches what static analysis cannot (dynamic access, `config.py`), but
  only on paths that actually run. Pair it with `xefm try`.

## 5. Docs and skill

- `doc/CUSTOMIZATION_FEATURE.md`, `doc/EXTENSIONS_FEATURE.md`,
  `doc/VIRTUAL_FOLDERS_FEATURE.md`
  - Replace the all-Preview banners with a short Stable / Preview list.
  - Use `api_version = 1` in examples.
  - `EXTENSIONS_FEATURE.md` documents the `preview` findings,
    `--stable-only` and the runtime log line (§4.1).
- `xefm/user_api.py`, `xefm/path_base.py`, `xefm/preview.py`,
  `xefm/extensions.py`: module docstrings.
- `doc/dev/CUSTOMIZATION_API_IMPLEMENTATION.md` §8 and
  `doc/dev/VIRTUAL_FOLDERS_IMPLEMENTATION.md` "Preview Status".
- `doc/dev/EXTENSIONS_IMPLEMENTATION.md`: the API_VERSION 1 note.
- `xefm/_config.py`, plus the skill's `config-template.md`, `config.md` and
  `extensions.md`: imports, the Preview comment, the
  "ACTIONS (Preview API)" heading.

## 6. Tests to touch

- `test_user_task_api.py`: the `STABLE` set moves into the snapshot (§7.1);
  update the docstring assertions.
- New: `test_api_snapshot.py` (it covers the `dir(Path)` set, the
  `ReadOnlyPathImpl` tiers and the compatibility import paths) and
  `test_stable_api_contract.py` (§7.2).
- `test_customization_api.py`, `test_sort_keys.py`, `test_filters.py`,
  `test_image_decoders.py`, `test_lexer_registry.py`,
  `test_virtual_folders.py`: notice expectations.
- `test_extensions.py`, `test_extension_updates.py`,
  `test_extension_python_packages.py`: `api_version = 0` fixtures. Decide per
  test whether to bump to 1 or keep as the "older version" case.
- Every caller of `get_scheme()`, the seven moved methods and `_child`.
- §4.1, static: each row of the detection table, with one positive and one
  negative case for each; the `preview` severity not gating install;
  `--stable-only` turning findings into errors; compute-hash's real code as a
  fixture-level smoke test, expected to report `run_task`, `show_markdown`,
  `choose`, `extension`, `md_code_block`, `md_escape` and `contributes.menus`.
- §4.1, runtime: one line per (caller, API), not one per call; attribution to
  an extension, to `config.py`, and none for XeFM's own calls.

## 7. Detecting API changes in future development

Today, `STABLE` in `test_user_task_api.py` catches only an *unclassified new
name*. `test_published_base.py` pins only the abstract-method set. Nothing
catches a signature change, a member removed from `PaneApi` / `EntryInfo`, a
config-table or manifest schema change, or a behavioral test whose
expectation was quietly edited. There is no CI, so all of the following runs
under local pytest and at the release pre-tag check.

### 7.1 API snapshot

- `tools/api_snapshot.py` (run as `PYTHONPATH=. python tools/api_snapshot.py`)
  writes the whole public surface to `test/data/api_snapshot.txt`, one sorted
  line per item:
  - Every public name in `xefm.user_api` / `xefm.path_base`, with its Stable or
    Preview status, its kind and its `inspect.signature`. Classes are listed
    per member, properties included.
  - `API_VERSION`.
  - The `Path` stable member set (§2.1) and the `ReadOnlyPathImpl` /
    `UriPathImpl` tiers (§3.1).
  - The compatibility import paths (§2.5).
  - The keys each config table accepts.
  - The manifest's sections, `[extension]` keys and `contributes` kinds.
  - The promised capability vocabulary.
- **Prerequisite:** the `SORT_KEYS`, `FILTERS`, `ACTIONS`, `IMAGE_DECODERS`
  and `PATH_SCHEMES` builders in `user_api.py` read their accepted keys from
  module constants, so the snapshot can read the schema rather than parse
  validation code. Builders that silently ignore unknown keys today
  (`_build_sort_key`, `_build_filter`, …) keep doing so; only the declared set
  is snapshotted.
- `test/test_api_snapshot.py` regenerates the snapshot in memory, diffs it
  against the file, and classifies every difference:

  | Difference | Examples | Result |
  |---|---|---|
  | Breaking change to Stable | Removed; a parameter removed, renamed or reordered; a required parameter added; a default changed; Stable demoted to Preview; a table key or manifest key removed | Fails until `API_VERSION` is bumped **and** the snapshot regenerated. The message names the item and says why it counts as breaking. |
  | Addition to Stable | A new member; a new optional keyword parameter; Preview promoted to Stable | Fails with "regenerate the snapshot" |
  | Any change to Preview | Anything | Fails with "regenerate the snapshot". No version rule. |

  Every API change then shows up as a snapshot diff in the PR, so a reviewer
  sees it whether or not it was intended.
- **The snapshot replaces the `STABLE` set** in `test_user_task_api.py`. That
  test's check (every public name is classified) becomes part of the snapshot
  test, and so do the `dir(Path)` and `ReadOnlyPathImpl` member-set tests
  planned in §2.1 and §3.1. One mechanism, not four.

### 7.2 Contract tests

- Signatures cannot see meaning. Behavioral tests of Stable APIs move or are
  written into `test/test_stable_api_contract.py`:
  - `select` / `unselect` / `selected` semantics (never falling back to the
    focused entry; a raising predicate counts as no match)
  - `EntryInfo.name` as the composed, displayed name versus the verbatim
    `path`; `size` / `mtime` reporting zero on failure
  - The sort-key contract (directories-first and reverse are not the key's
    business; a failing key falls back to name order)
  - The filter contract (fails open)
  - `invoke` reaching the built-in when an action invokes its own name
  - `run_program` return values (`None` in the background; the exit code with
    `terminal=True`)
  - Old action names still resolving
  - How XeFM calls the five tier-A backend methods; the write refusals;
    duplicate-key resolution (§3.3)
  - `xefm_tool`'s search order and fallback
- The rule, stated at the top of the file and added to `CLAUDE.md` so that AI
  sessions follow it too: **changing an expectation in this file is a breaking
  change to the stable API.** Either the change is reverted, or `API_VERSION`
  is bumped and the change is called out in the release notes. Adding a test
  is always fine.

### 7.3 Real extensions and the release check

- `make api-compat` checks out `crftwr/xefm-extensions` into `temp/` (or uses
  `../xefm-extensions` when present). For every package it runs
  `xefm ext check` and the package's own tests against the working tree, with
  the package's `requires.python_packages` installed for the run. This
  is the "compatibility check against real extensions" that
  `EXTENSIONS_IMPLEMENTATION.md` deferred to API_VERSION 1 (discussion #469).
- The xefm-release skill's pre-tag checks gain two steps:
  - Run `make api-compat`.
  - Print the snapshot diff since the previous tag
    (`git diff vX.Y.Z -- test/data/api_snapshot.txt`). The release then knows
    whether `API_VERSION` moved, and which API changes belong in the notes'
    "Also" paragraph, or in a bullet if users would notice.

## 8. After release

- Bump `compute-hash` in `crftwr/xefm-extensions` to `api_version = 1` and
  `min_xefm` to the release that ships this.
- Follow-up issues:
  - A `ctx` copy/move API that goes through file operations, if one is needed.
    (Done: `ctx.copy` / `ctx.move`, #716, and `ctx.trash` / `ctx.delete`,
    #782 — see §10.)
  - Stabilizing the Preview tiers of `PATH_SCHEMES` once a real extension uses
    them.

## 9. Deprecation — how a stable API goes away

Added after the first release of this plan (discussion #469 asked for "how
deprecation works" as part of the compatibility promise).

1. **Deprecate first.** `@deprecated("use … instead")` in `xefm/preview.py`
   marks a stable function, method, property getter or class. A `config.py`
   table or a manifest section goes into `DEPRECATED_APIS` by name. The API
   keeps working. Its docstring opens with "Deprecated — …", it is listed
   in `xefm.user_api.DEPRECATED_APIS` with what replaces it, its first use
   from outside XeFM logs a warning naming the caller, and `xefm ext check`
   reports each use as a warning (`deprecated_uses`, part of
   `check_manifest`). The snapshot records it as `deprecated`, which is not a
   breaking change.
2. **Keep it for at least one minor release.** The release that deprecates
   it says so in its notes, with the replacement.
3. **Then remove it, and bump `API_VERSION`.** Removing a deprecated API is
   a breaking change, so `make api-snapshot` refuses it without the bump.
   Removing a stable API that was never deprecated is refused the same way,
   and the message asks for deprecation first. A bump overrides it for the
   rare case that cannot wait (a security problem), and the release notes
   must say why.

Preview APIs need none of this: they change or go in any release.

## 10. Operations from the API — dedicated calls, one shape (#716)

Added with `ctx.copy` / `ctx.move`. An action reaches a built-in operation
through a **dedicated call**, added where one is needed, not through a general
way to run any action with its inputs given up front.

### 10.1 The shape every dedicated call follows

- **Items** are `Iterable[EntryInfo | Path | str]`, so `ctx.pane.selected()`
  passes as is; a string must be absolute (a local path or a URI). A
  directory argument is `Path | str`.
- **Which items** is the caller's to decide. No call applies "the selection,
  else the focused item" — `PaneApi.selected()` already leaves that rule to
  its caller.
- **Asynchronous by contract.** The call returns `None` at once and takes
  `on_done(ctx, outcome)`, run on the UI thread exactly once, with a new
  `ctx`, and never before the call returns (`XeFMApp._call_later`). This
  holds even where the operation could finish at once, because a
  confirmation added later would make it asynchronous.
- **The outcome** is `TaskOutcome`: `done` / `cancelled` / `failed`, `value`,
  `error`. No new outcome type.
- **Per-item results**, where an operation has them, are a list of
  `ItemResult(source, dest, status, errors, permanent)`, in the order the
  items were given; `status` is `done` / `skipped` / `failed`, and `errors` holds the
  `(name, message)` pairs under that item. A folder is `done` with an inner
  file in `errors`, and `failed` only when nothing of it got through. On
  cancel, `value` holds the items whose outcome is known.
- **Confirmations stay.** The confirmation, the conflict dialog and the
  permanent-delete fallback (#765) are shown even when the API starts the
  operation. Nothing skips them.
- **UI thread only**, like the rest of `ctx`; checked on entry.
- **Wrong arguments raise `ValueError` at once** — a caller's bug, not an
  outcome.

### 10.2 Set aside: `invoke()` with inputs

`ctx.invoke(name, operands=..., args=...)` would have made every action
callable with its inputs: `operands` the panes' state (`this` / `other` /
`left` / `right`, each a `dir`, `selected` and `focused`, as dataclasses), and
`args` the values an action prompts for today (a name, a pattern). It was set
aside because:

- What `operands` means differs by action. For a file operation it is a
  hypothetical state — the panes on screen do not move. For `filter`, `sort`
  or a cursor action it only makes sense applied to the real panes. One
  argument with two meanings, chosen per action.
- Every action author would have one more thing to consider: which operands
  their action reads, and in which of the two meanings.
- Built-in actions read pane state directly in many places
  (`self.pm.active_pane`, `pane["selected_files"]`, …). A hypothetical state
  swapped in for the call would be gone by an operation's later ticks — after
  its prompt or the conflict dialog.

`invoke()` stays as it is.

### 10.3 Future idea: `args`

If a dedicated call ever needs the values a built-in prompts for, the shape
considered was a per-action dataclass (`CreateDirectoryArgs(name="build")`),
declared in the action's metadata (#718) so the snapshot covers it. A value
given skips its prompt; one not given is still asked for. Safety
confirmations are not `args` and are never skipped by them. Nothing needs
this yet.

### 10.4 `ctx.trash` / `ctx.delete` (#782)

Two calls, mirroring the two built-ins rather than one call that follows
`DELETE_TO_TRASH`: the setting is the user's choice for a key, and an action
that asks for the trash should get it, or be told why not.

- `ctx.trash` is `delete_files` with the trash on, step for step: where some
  item has no trash at all, the confirmation says so and everything is
  deleted for good; an item that turns out to have none part-way
  (`NoTrashError`, #765) is offered a permanent delete after the run, and
  one kept by declining it comes back `skipped`. A cancelled run makes no
  offer.
- `ctx.delete` is `delete_permanently`: its confirmation defaults to Cancel.
- `dest` is always `None`. `ItemResult.permanent` says which items were
  deleted for good, so an action can tell a trash that fell back from one
  that did not. The two steps of a trash with a fallback come back as one
  outcome.
- An item inside an archive is a `ValueError`.
- `XeFMApp._remove_for_api` holds the flow; `_delete` (the keys) shares its
  notes and failure reporting.
