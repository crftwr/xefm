# In-Process Customization API — Draft Design

**Status: steps 1–3 implemented as a Preview.** The action registry with
contexts, `ACTIONS` with its invocation-time façade, and `EVENT_HOOKS` all
ship; step 4 (exposed registries) does not. What was built, where it differs
from this sketch, and why, is in
[`CUSTOMIZATION_API_IMPLEMENTATION.md`](CUSTOMIZATION_API_IMPLEMENTATION.md);
the user-facing side is [`doc/CUSTOMIZATION_FEATURE.md`](../CUSTOMIZATION_FEATURE.md).
This document is kept as the design record it was, action names included —
several were corrected during implementation, and the current spellings are
in the implementation doc.

Motivated by [issue #287](https://github.com/crftwr/xefm/issues/287): bind
arbitrary keys to arbitrary functions, and let those functions manipulate
pane state (e.g. "select every item matching a condition").

The design realizes this in-process, making the **live-Python config a
first-class scripting surface**. `~/.xefm/config.py` is already an executed
Python module with runtime logic; the step to "config defines functions" is a
continuation, not a new paradigm.

---

## Current state (what the design has to work with)

Three facts about the codebase shape this design:

1. **The config is live Python.** `ConfigManager.load_config()` imports
   `~/.xefm/config.py` via importlib and merges missing fields from the
   `_config.py` template. `reload_config()` re-executes it at runtime and
   rebuilds the keymap.

2. **Key dispatch is split across two tiers with different mechanics.**
   - The *main window* is table-driven up to the last step: an event resolves
     through `KeyBindings.find_action_for_event()` to an action **name**, and
     `XeFMApp.dispatch()` maps the name to behavior — through a ~700-line
     hardcoded `if/elif` chain (`xefm/app.py`).
   - Each *modal view* (`diff_viewer`, `text_viewer`, `image_viewer`,
     `directory_diff_viewer`, dialogs) has its own `handle_event()` that
     resolves a few shared names (`quit`, `help`, `search`, `edit_file`)
     through the global `KEY_BINDINGS` via `is_action_for_event()`, and
     hardcodes everything view-local (arrow scrolling, `n`/`N` block jump…)
     as raw key comparisons — invisible to config, not rebindable.

3. **The action namespace is flat.** `KEY_BINDINGS` is one dictionary; the
   name `quit` means "quit the app" in the filer and "close this viewer"
   inside a modal view. That overloading is a feature (one rebind applies
   everywhere), but it means the design needs an explicit notion of *context*
   before per-view customization can exist.

---

## Design overview

Customization stays **declarative, in the existing config idiom**: new
UPPER_CASE `Config` variables whose values may be Python callables defined in
the same file. There is no imperative registration API — the app reads the
variables and populates its registries, exactly as it already does for
`KEY_BINDINGS` (see "Alternative considered" in §2).

Four pieces, each shippable on its own, each enlarging what a config can do
without introducing a new concept:

1. **Action registry with contexts** — internal refactor. Every action,
   main-window and view-local alike, becomes a named entry in a per-context
   table. No user-visible change except: view-local keys become rebindable.
2. **`ACTIONS`** — a config variable mapping action names to user functions;
   `KEY_BINDINGS` binds them by name exactly like built-ins.
3. **`EVENT_HOOKS`** — a config variable mapping event names to user
   functions.
4. **Exposed registries** — rich-viewer renderers, sort/filter predicates,
   as further config variables (`VIEWER_RENDERERS`, …).

An add-on/plugin package system (`~/.xefm/addons/`) is deliberately **out of
scope**: it is the same machinery plus discovery and lifecycle, and it is a
stability promise to third parties that should wait until the API has
survived a few releases of real config-level use. A separate add-on module
needs a callable entry point (`setup()`) anyway, so that concept can be
introduced there when the time comes, without the config ever having one.

---

## 1. Action registry and contexts

### Contexts

A **context** names one key-consuming surface:

| Context | Owner | Today's dispatch |
|---------|-------|------------------|
| `filer` | main window (panes) | `XeFMApp.dispatch()` if/elif |
| `text_viewer` | `text_viewer.py` | local `handle_event` |
| `image_viewer` | `image_viewer.py` | local `handle_event` |
| `diff_viewer` | `diff_viewer.py` | local `handle_event` |
| `dir_diff` | `directory_diff_viewer.py` | local `handle_event` |
| `common` | shared | `is_action_for_event()` calls in every view |

`common` holds the actions every surface understands (`quit`, `help`,
`search`); each view context *inherits* it. Dialogs (sort, rename, input…)
keep their hardcoded handling for now — they are forms, not customization
surfaces — but nothing prevents giving one a context later.

### The registry

A new module `xefm/actions.py`:

```python
@dataclass(frozen=True)
class Action:
    name: str            # "cursor_up", "diff.next_block"
    func: Callable       # receives an ActionContext (see §3)
    description: str     # feeds help dialogs and the future command palette
    source: str          # "builtin" | "user" — user entries rebuilt on reload

class ActionRegistry:
    def register(self, context: str, action: Action, *, override=False) -> None
    def resolve(self, context: str, name: str) -> Action | None
        # search order: context table -> "common" table
```

Built-ins register at startup: the `filer` table is `dispatch()` decomposed
into a name→method dict; each view registers its table when its module loads,
turning today's hardcoded branches into named actions (`text_viewer.scroll_up`,
`diff.next_block`, `image.zoom_in`, …). User entries come from the config's
`ACTIONS` variable (§2).

Concretely, a view's `handle_event` shrinks from an `if/elif` chain to:

```python
def handle_event(self, event):
    ...mouse handling unchanged...
    action = self._keys.find_action_for_event("diff_viewer", event)
    if action:
        return self._run(action)
```

### Key binding resolution

`KEY_BINDINGS` stays one flat dictionary — no breaking change, and the
existing extended entry format (`{'keys': [...], 'selection': ...}`) is
preserved. Context is expressed in the **name**, dot-qualified:

```python
KEY_BINDINGS = {
    "quit": ["Q"],              # unqualified — common/filer, as today
    "cursor_up": ["UP", "K"],
    "diff.next_block": ["n"],   # view-local, now rebindable
    "viewer.scroll_up": ["UP", "K"],
}
```

Per-context resolution for an event: the context's own qualified bindings
first, then unqualified (common) bindings, then the context's built-in
defaults for anything the user's config doesn't mention. The template
`_config.py` gains the qualified defaults so they are discoverable; the
merge-missing-fields mechanism keeps old configs working untouched.

*Alternative considered:* a nested `KEY_BINDINGS_BY_CONTEXT` dict. Rejected:
two dictionaries with overlapping meaning, and every existing config would
sit in the "legacy" one forever. Dotted names keep one namespace, one merge
path, and read naturally in the help dialog.

### Side benefits

- Per-view help dialogs (`_show_help`'s hand-maintained row lists) can be
  generated from the context table.
- A **command palette** (fuzzy-run any action of the active context by name)
  becomes a straightforward feature on top of the registry.

---

## 2. User-defined actions: the `ACTIONS` variable

The config gains one new variable. Its values are callables defined in the
same file; each receives an `ActionContext` (§3) when it fires:

```python
def select_docs(ctx):
    ctx.pane.select(lambda entry: entry.name.endswith(".docx"))

def noisy_quit(ctx):
    ctx.message("bye!")
    ctx.invoke("quit")           # the wrapped built-in stays reachable

class Config:
    ACTIONS = {
        # simple form: name -> callable
        "select-docs": select_docs,

        # extended form: name -> dict, mirroring KEY_BINDINGS' extended format
        "quit": {"func": noisy_quit, "override": True},
    }

    KEY_BINDINGS = {
        "select-docs": ["U"],    # user actions bind by name, same as built-ins
        ...
    }
```

Design points:

- **Keys live in `KEY_BINDINGS` only.** `ACTIONS` defines behavior;
  `KEY_BINDINGS` binds it. One namespace, one place for conflict checking,
  and an action with no binding is still reachable from the future command
  palette. This is the issue's original `KEY_BINDINGS`-references-`PROGRAMS`
  intuition, with in-process functions in place of subprocesses.
- **Simple/extended duality.** A bare callable covers the common case; the
  dict form (`func`, `override`, `context`, `description`) mirrors the
  extended format `KEY_BINDINGS` already uses for selection requirements —
  an idiom existing configs already know.
- **Override is explicit.** A name colliding with a built-in is a validation
  warning and is ignored unless `"override": True` is present. A wrapped
  built-in stays reachable via `ctx.invoke(name)`, so before/after
  decoration works (see `noisy_quit` above).
- **Context, defaulting to `"filer"`.** *Recommendation for v1:* accept user
  **rebinding and overriding** in every context, but accept user
  **functions** only in `filer`. A view-context user function needs a
  per-view API surface (scroll position, block list, zoom…) that should be
  designed per view, deliberately, once someone asks — not frozen by
  accident in v1. The registry mechanics already allow it, so widening later
  is additive.
- **Dynamic construction needs no special hook.** The config is an executed
  module, so "an action per entry of X" is a module-level comprehension;
  anything that needs the *running* app at startup is a `startup` entry in
  `EVENT_HOOKS` (§4).

### Reload and validation

Both come for free from the declarative shape:

- `reload_config()` already re-executes the module and rebuilds `KeyBindings`
  from the new `KEY_BINDINGS`; user actions reload the same way — drop all
  `source == "user"` registry entries and repopulate from the new config's
  `ACTIONS`/`EVENT_HOOKS`. No idempotence contract, no lifecycle rules.
  Iterating on a custom action is edit → reload — no restart.
- `validate_config()` checks shapes (callable / well-formed dict), flags
  built-in collisions lacking `"override": True`, and unknown context or
  event names — reporting *all* problems as warnings in one pass, like every
  other config field. `_copy_missing_fields` gives old configs the empty
  defaults, so absence needs no probing.

### Alternative considered: `Config.configure(api)`

An earlier draft added an imperative hook — an optional method on `Config`,
called after app init, receiving a registration object
(`api.register_action(...)`, `api.on(...)`). This is the Keyhac/cfiler idiom,
and it was rejected for XeFM:

- XeFM's config idiom is data-first UPPER_CASE variables, and all the
  supporting machinery (template merge, validation, reload) is built around
  that shape. Declarative variables slot into all three untouched; the
  imperative hook needed its own lifecycle contract (clear user entries,
  re-run, require idempotence) and raised on the first error instead of
  warning on all of them.
- Half the frozen API surface disappears: the registration object's methods
  become variables, leaving only the invocation-time façade (§3) to design
  and stabilize.
- The one capability an imperative hook uniquely offers — user code running
  at registration time against a live handle — has no v1 use case: dynamic
  registration is module-level Python, and running against the live app is
  the `startup` event hook.

---

## 3. The API façade

With registration handled declaratively, the façade reduces to the
**invocation-time** objects passed into user callables, defined in a new
module `xefm/user_api.py`. **No PuiKit type, widget, or `XeFMApp` internal
appears in any signature** — the façade is the firewall that lets internals
keep moving without breaking user configs (the cfiler lesson: exposing
`MainWindow` made every refactor a config-breaking change).

`ActionContext` — passed to every user action and event hook when it fires:

```python
class ActionContext:
    pane: PaneApi          # active pane
    other: PaneApi         # inactive pane
    left, right: PaneApi
    def invoke(self, action_name) -> None      # run a built-in (or user) action
    def message(self, text) -> None            # log-pane line
    def input(self, prompt, default="") -> str | None
    def choose(self, title, items) -> int | None
    def confirm(self, prompt) -> bool

class PaneApi:
    path: Path                               # read
    def cd(self, path, focus_name=None) -> None
    entries: list[EntryInfo]                 # name, is_dir, size, mtime
    cursor: int                              # read/write (clamped)
    def selected(self) -> list[EntryInfo]
    def select(self, predicate) -> None       # add matches to selection
    def unselect(self, predicate=None) -> None
    def refresh(self) -> None
```

`ctx.invoke()` is quietly the most powerful primitive: users compose and wrap
existing behavior instead of asking for each internal to be exposed.

What is deliberately **not** in v1: widgets, layout, rendering, viewer
internals, task scheduling, direct `XeFMApp` access. Additions are cheap;
removals are breaking — start minimal.

---

## 4. Event hooks: the `EVENT_HOOKS` variable

String-named events mapping to lists of callables, fired in list order:

```python
class Config:
    EVENT_HOOKS = {
        "startup": [restore_session],          # fn(ctx)
        "quit": [save_session],                # fn(ctx)
        "directory_changed": [log_visit],      # fn(ctx, pane, old_path, new_path)
        "file_open": [route_psd],              # fn(ctx, path) -> True to swallow
    }
```

`file_open` fires before the built-in open logic; returning `True` claims the
event — per-type routing (send `.psd` to a specific app) without touching
`FILE_ASSOCIATIONS`. Hook exceptions are caught and logged like action
exceptions (§6); a `file_open` hook that raises falls through to the default
open.

---

## 5. Exposed registries

`xefm/viewer_registry.py` already anticipates this ("later registrations for
the same suffix win, so a config could override a built-in renderer in the
future"). A future `VIEWER_RENDERERS` config variable maps suffixes to
builder callables, feeding `viewer_registry.register()` at load. The builder
is the one place a PuiKit widget necessarily crosses the façade; that is
acceptable because renderers are inherently UI extensions, and it is the same
contract the built-in renderers use.

Sort keys and filter predicates as user callables fit the same pattern.

**Sort keys have** — `SORT_KEYS`, shipped for #380, and the first of these to
land. It went first precisely because it is *not* the renderer: a key returns
data, so the machinery could be shaken down without committing to a PuiKit type
crossing the façade. It also forced §6's threading rule to be answered rather
than deferred — a sort key runs on a worker, the opposite of what actions and
hooks promise. See
[`CUSTOMIZATION_API_IMPLEMENTATION.md`](CUSTOMIZATION_API_IMPLEMENTATION.md)
§8b.

**Filters have** — `FILTERS`, and the second registry to land. It rides the
machinery `SORT_KEYS` shook down (same `EntryInfo`, same worker-thread rule, same
validate-and-warn loading) and needed one new answer of its own: a filter is
stored where a typed pattern is stored, so `xefm.filters.matcher` is the single
point that decides which of the two a string is, and a name that could be read as
a glob is refused at load. See
[`CUSTOMIZATION_API_IMPLEMENTATION.md`](CUSTOMIZATION_API_IMPLEMENTATION.md)
§8c.

---

## 6. Cross-cutting rules

- **Failure isolation.** An exception in a user action or hook is caught at
  the invoke boundary, logged to the log pane with a traceback, and the app
  keeps running. Malformed `ACTIONS`/`EVENT_HOOKS` entries are validation
  warnings that skip the entry, never load failures — same tolerance the
  field-merge already shows for incomplete configs. A user action that
  crashes the file manager on keypress would poison trust in the mechanism.
- **Threading.** Actions and hooks run on the UI thread; the API docs state
  this from day one. Long work belongs in the existing task framework — v1
  documents the restriction rather than exposing a background-work helper.
- **Dual backend.** Every façade signature is expressed at the pane-model
  level, so TUI/desktop parity holds by construction (§5's renderer builder
  being the sole, deliberate exception).
- **Versioning.** `xefm.user_api.API_VERSION`, an integer bumped only on a
  breaking change to the façade or the config-variable formats. The façade
  being minimal is the main stability strategy; the version number is the
  escape hatch.

---

## Sequencing

Each step is independently shippable:

1. **Registry refactor** — decompose `dispatch()` into the `filer` table;
   convert the modal viewers' local keys into named, dot-qualified actions
   with defaults in `_config.py`. Pure refactor + "view keys are now
   rebindable" as the visible win. Closes the letter of #287's rebinding ask.
2. **`ACTIONS`** — façade v1 (`ActionContext`, `PaneApi`), user actions in
   the `filer` context, override semantics, validation, reload. Closes the
   spirit of #287 (arbitrary function on any key, with pane manipulation).
3. **`EVENT_HOOKS`.**
4. **Exposed registries** (`VIEWER_RENDERERS` first).

Open questions to settle during step 1:

- Exact context names and whether dialogs ever get one.
- Whether `common` actions may be overridden per-context in `KEY_BINDINGS`
  (e.g. rebind `quit` only inside `diff_viewer`). The dotted-name scheme
  allows it (`"diff.quit": [...]`) — cheap to support, worth deciding
  explicitly.
- Whether `find_action_for_event`'s selection-requirement mechanism stays a
  binding property or becomes an action property in the registry.
