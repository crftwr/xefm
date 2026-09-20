# Virtual Folders — Implementation

`PATH_SCHEMES` lets a `~/.xefm/config.py` add a browsable location of its own.
This is the config-facing half of discussion #426; the storage layer it stands
on is documented in
[`PATH_POLYMORPHISM_SYSTEM.md`](PATH_POLYMORPHISM_SYSTEM.md).

## Where the Pieces Are

| | |
|---|---|
| `xefm/path.py` | `PathImpl`, the strict ABC, and the `Path` façade |
| `xefm/path_base.py` | `UriPathImpl` / `ReadOnlyPathImpl` — **the published extension point** |
| `xefm/path_schemes.py` | the one registry of schemes, and `source` grouping |
| `xefm/user_api.py` | `PATH_SCHEMES` validation and loading |
| `xefm/_config.py` | the commented template a new config starts from |
| `doc/VIRTUAL_FOLDERS_FEATURE.md` | the user-facing page, with a worked sample |

## Why Four Tracks and Not One

Registering a scheme is the visible ask and the cheap half. Landing it alone
would have advertised a registration point for something nobody could write:
`PathImpl` has 61 methods and 48 abstract, so the answer to "I registered, now
what?" would have been "implement 48 methods, and expect to break on the next
release". So the order was:

1. **Capabilities become a declaration** — ten of the twelve methods describing
   what a backend *is* had no caller. Fixing that *before* publication mattered,
   because changing what a capability means afterwards is the breaking change
   the whole exercise exists to avoid.
2. **`UriPathImpl` / `ReadOnlyPathImpl`** — 27 shared methods, and the
   compatibility buffer.
3. **The scheme registry** — one list where there were four.
4. **`PATH_SCHEMES`** — this document.

## The Load Path

`PATH_SCHEMES` is one more table in the pass `xefm/user_api.py` already runs for
`ACTIONS` / `EVENT_HOOKS` / `SORT_KEYS` / `FILTERS`, and it inherits that pass's
contract wholesale:

- **Warn per entry, never fail the load.** A malformed entry is skipped with one
  log line; the rest of the config still loads.
- **Reload is re-run.** `_process_user_entries` calls
  `path_schemes.unregister_source("user")` before it registers anything, so
  editing a config and reloading replaces the table with no restart and no
  idempotence contract on the config's part.
- **Validation without loading.** `validate_user_entries` walks the same code
  with `apply=False`, which is what `ConfigManager.validate_config` reports.

```python
scheme_count = 0
for name, spec in _items(getattr(config, "PATH_SCHEMES", None), "PATH_SCHEMES", warnings):
    impl, problem = _build_path_scheme(name, spec)
    if problem:
        warnings.append(problem)
        continue
    if apply:
        _path_schemes.register(name, impl, source="user")
    scheme_count += 1
```

### What `_build_path_scheme` Checks

Each check exists because the failure it prevents would otherwise surface
somewhere unrelated:

| check | what it would otherwise look like |
|---|---|
| the key is a valid scheme | a prefix nothing can ever match, silently |
| the value is a `PathImpl` subclass | `AttributeError` from deep inside a listing |
| no `__abstractmethods__` left | `TypeError` from whichever pane first opens it |
| not shadowing a built-in without `override` | a typo quietly taking S3 away |
| `SCHEME` agrees with the key | the class builds paths under a prefix the registry does not answer to, so its own `parent` leaves the folder |

The abstract-methods check is the one worth keeping in mind: it names the
missing methods, because "does not implement `open`, `stat`" is the message the
author can act on and `TypeError: Can't instantiate abstract class` is not.

### `SCHEME` Comes from the Key

`PATH_SCHEMES = {'reg': RegistryPathImpl}` has already named the scheme, so a
class that leaves `SCHEME` at its empty default gets it filled in from the key.
Asking for the same word twice invites them to disagree, and the `''` default is
not benign: `get_scheme()` returns it, and file operations compare two paths'
schemes to decide whether a move can be a rename.

A class that overrides `get_scheme()` itself is left alone — `UnsupportedPathImpl`
is one, because it serves every unimplemented scheme from one class.

### Registering Over a Built-in

`path_schemes.register` keeps whatever an entry covers, and `unregister_source`
puts it back. That is what makes `{'s3': {'class': ..., 'override': True}}`
survivable: a reload uncovers the built-in rather than deleting it. Registering
the same source over itself — which is exactly what a reload does — does not
stack, so the covered entry stays the one that was there before that source
first arrived.

## Preview Status

`PATH_SCHEMES` is covered by `user_api.API_VERSION`, which is `0`. A config that
defines one gets the existing one-line preview notice in the log pane, now
counting `N path scheme(s)` alongside actions, hooks, sort keys and filters.

The surface this promise is actually about is `ReadOnlyPathImpl`, not
`PATH_SCHEMES` — see "Why the Published Base Is Not `PathImpl`" in
[`PATH_POLYMORPHISM_SYSTEM.md`](PATH_POLYMORPHISM_SYSTEM.md). `test_published_base.py`
fails when an abstract method reaches it without a default, which is the rule
that has to outlive anyone remembering it.

## Read-only, and Why

`PATH_SCHEMES` is designed around `ReadOnlyPathImpl`. Nothing stops a config
from registering a writable `UriPathImpl` subclass — the registry's contract is
`PathImpl` — but the nine write operations are then the config's problem, and
the preview does not promise anything about how file operations drive them.

The cases asking for this (#413's registry browser, a bookmark database, a
device list) are all browse-and-hand-off: the editing goes to the tool that owns
the data. `READ_ONLY_MESSAGE` exists so the refusal can say which tool.

## Tests

| file | |
|---|---|
| `test/test_virtual_folders.py` | the config surface: end-to-end browsing, reload, and every refusal |
| `test/test_path_schemes.py` | one registration reaching all four call sites |
| `test/test_published_base.py` | the five-method promise and the read-only policy |
| `test/test_path_capabilities.py` | the capability declarations |

`test_virtual_folders.py` is mostly refusals on purpose. A config is edited by
hand, and the thing that has to hold is that a bad entry costs that entry and
nothing else.

## Not in This Version

- Writable virtual folders as a promised surface.
- Per-entry icons or colours.
- A virtual-folder-specific details panel — `get_extended_metadata()` exists and
  has no caller (see #426 §5); wiring it up is its own change.
- Background listing with progress. A virtual folder's `iterdir` runs on the
  same worker thread every listing uses, but there is no way for it to report
  progress or be cancelled mid-flight.
