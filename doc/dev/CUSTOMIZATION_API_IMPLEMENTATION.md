# Customization API — Implementation

Implements steps 1–3 of [`CUSTOMIZATION_API_DESIGN.md`](CUSTOMIZATION_API_DESIGN.md),
shipped as a **Preview**: the action registry with contexts, the `ACTIONS`
config variable with its invocation-time façade, and `EVENT_HOOKS`. Step 4
(exposed registries — `VIEWER_RENDERERS` and friends) is not implemented.

Motivated by [issue #287](https://github.com/crftwr/xefm/issues/287).

User-facing documentation: [`doc/CUSTOMIZATION_FEATURE.md`](../CUSTOMIZATION_FEATURE.md).

---

## Modules

| File | Holds |
|---|---|
| `xefm/actions.py` | `Action`, `ActionRegistry`, the context names, the built-in action tables |
| `xefm/user_api.py` | `ActionContext`, `PaneApi`, `EntryInfo`, `EventHooks`, the `ACTIONS`/`EVENT_HOOKS` loader, `API_VERSION` |
| `xefm/config.py` | per-context key resolution inside `KeyBindings` |
| `xefm/app.py` | the `filer` handler table, `_run_action`, hook firing |
| `xefm/{text,image,diff,directory_diff}_viewer.py` | per-viewer handler tables |

---

## 1. Metadata here, behavior there

The registry holds what an action *is* — name, context, description, default
keys, selection requirement. It does **not** hold what a built-in action *does*.

That split is forced by binding: a built-in's behavior is a bound method of a
live `XeFMApp` or a live viewer, and neither exists when `xefm/actions.py` is
imported. So each owner keeps its own `{name: handler}` table, built lazily on
first key and cached on the instance:

- `XeFMApp._filer_handlers()` → `{name: (callable, redraw)}`
- `TextViewer._raw_handlers()`, `ImageViewer._handlers_table()`,
  `DiffViewer._handlers_table()`, `DirectoryDiffView._handlers_table()` →
  `{name: callable}`

`Action.func` is therefore `None` for a built-in, and holds the callable only
for a **user** action, where the config supplies it directly and there is nothing
to bind against. `Action.source` (`"builtin"` / `"user"`) is what separates the
two everywhere else.

`test_every_registered_filer_action_has_a_handler` asserts the two halves stay
in agreement — a name in the registry with no handler is a key that resolves to
nothing, and a handler with no registered name is a key that never resolves.

### The `redraw` column

`dispatch()` has always returned "does the screen need a repaint", and the old
`if/elif` chain expressed that by where it returned from: falling through to the
final `return True`, or returning `False` early for anything that opens a dialog
and drives its own redraw. The table keeps that distinction explicitly —
`True`, `False`, or `None` for the handful (`copy_files`, `delete_files`,
`create_archive`, …) that decide per call and return the flag themselves.

---

## 2. Contexts

Six contexts: `filer`, `text_viewer`, `image_viewer`, `file_diff`, `dir_diff`,
and `common`. Every context inherits `common`, which holds `quit`, `help`,
`isearch` and `edit_file` — the four names that mean something on every surface.
Each context supplies its own handler for an inherited name, which is how one
`quit` binding closes a viewer here and quits the app there.

`file_diff` rather than `diff_viewer` (which is what the module is called): the
two diff surfaces are symmetric, and `diff_viewer` next to `dir_diff` never said
which was which. A context is a user-facing name in `KEY_BINDINGS`, so it is
named for the reader rather than after its module — `dir_diff` never matched
`directory_diff_viewer.py` either.

Dialogs (sort, rename, input, …) deliberately have no context. They are forms,
not customization surfaces.

### Names, and why `KEY_BINDINGS` stayed flat

`KEY_BINDINGS` is still one dictionary, so context lives in the name — but only
where a name genuinely belongs to one surface. The test is what the *bare* name
would mean:

- **Dot-qualified** when the action is specific to that surface and the bare name
  would be meaningless or misleading elsewhere: `file_diff.next_block`,
  `image_viewer.next`, `dir_diff.switch_side`.
- **Unqualified** when the name is a *capability* another surface could plausibly
  grow: `toggle_wrap`, `change_encoding`, `copy_files`. A name may be registered
  in several contexts, each with its own handler — `copy_files` already is, in
  `filer` and `dir_diff` — so one binding covers all of them, and adding the
  second implementation later changes nothing in anyone's config.
- The file list's own actions stay unqualified regardless: `filer` is the
  namespace's incumbent, every config in existence binds `cursor_up`, and letting
  the absence of a dot mean "not one specific viewer" is worth more than
  uniformity.

A config narrows an unqualified action to one surface with the `context.` prefix
(`'file_diff.quit': ['X']`) — which is *not* an alias and never warns; see
§3. Note the two forms are mutually exclusive per action: if both `scroll_up` and
`file_diff.scroll_up` were registered as separate actions, a config key
`file_diff.scroll_up` would bind the second rather than narrowing the first, and
both keys would end up live. An action is named one way or the other.

The design sketch wrote `diff.next_block`; this uses `file_diff.next_block`.
Making the prefix *exactly* the context name means the resolution rule is one
sentence with no lookup table.

Nine actions that already existed had to be renamed to fit — the `image_*`
family. See "Renamed actions" below.

A nested `KEY_BINDINGS_BY_CONTEXT` was rejected in the design and is not here:
two dictionaries with overlapping meaning, and every existing config would sit
in the legacy one forever.

---

## 3. Key resolution

`KeyBindings.find_action_for_event(event, has_selection, context=None)` keeps
its old flat behavior when `context` is `None` — that path is still the public
API and several tests exercise it. With a context it consults a compiled table
built by `_context_entries`, which is a list of `(parsed_key, action, selection)`
in match order.

Three sources feed it, each supplying keys for actions the previous one did not:

1. **Context-qualified config entries** — `'file_diff.quit': ['x']`, where
   `quit` is a registered name in that context and `file_diff.quit` is not.
   A rebind scoped to one surface, so it wins over the unqualified one.
2. **Config entries under the action's own registered name**, iterated in the
   config's own dict order.
3. **The action's built-in defaults**, for every registered name the config
   never mentions.

Only names the context understands — its own table plus inherited `common` — are
considered at all.

### Why source 3 exists

`_copy_missing_fields` can add a whole missing config *field* to an old config
but never a missing key inside `KEY_BINDINGS`. A config written before an action
existed has no entry for it and never will, so without per-action defaults every
action added after a user first wrote their config would be unreachable forever.

This is the general mechanism that replaces the hand-rolled fallbacks the
viewers had grown for exactly this problem — `TextViewer._wrap_pressed`,
`ImageViewer._pressed` / `_pressed_key`, each with a hardcoded historical key.
Those are deleted. See "Behavior changes" below for what that means for a config
old enough to have relied on them.

### Where the defaults live

Each action's default keys live in exactly one place:

- An action already listed in the shipped `_config.py` template reads its
  defaults **from the template**, lazily, via `actions._template_bindings()`.
  There is no second copy to drift.
- An action the template does not list (the scroll/navigation actions the
  viewers gained here, plus `duplicate_files`, which is deliberately unbound)
  declares `default_keys` on its `Action`.

The template documents those in a comment block rather than as live entries.
Adding them as entries would have put them in the flat `_key_to_actions` table
too, where they would compete with file-list keys in the context-free lookup
that still exists. The viewer actions the template *already* listed stay listed,
under their current names — renaming a key is not the same as adding one.

### Compatibility

The refactor's central claim is that the file list resolves exactly as before.
`test_filer_resolves_every_default_key_exactly_as_the_flat_table_did` checks it
directly: for the shipped keymap, every key it binds, both selection states,
flat result must equal `filer`-context result.

It holds because the template's dict order already put every file-list action
ahead of every viewer-local one, so the flat lookup was already picking the
file-list meaning of `W`, `-`, `↓` and the rest. What changes is that this no
longer *depends* on dict order — a user config that happens to list its wrap
binding before `compare_selection` used to resolve `W` to the viewer action in
the file list, and now cannot.

### Caching

The compiled table is cached per context on the `KeyBindings` instance and
dropped whenever `ActionRegistry.generation` changes. The generation bumps on
every registration and every `unregister_source`, which is what makes a config
reload's new user actions bindable with no restart. `self._bindings` never
changes under a live instance — a reload builds a new `KeyBindings`.

---

## 4. `ACTIONS`

`user_api.load_user_entries(config)` drops every `source == "user"` entry, clears
the hook table, and rebuilds both from the config. Running it *is* the reload
path, which is why the config carries no idempotence contract and no lifecycle
rules — the declarative shape is what buys that.

`validate_user_entries(config)` runs the identical scan with `apply=False`, so
`ConfigManager.validate_config` reports exactly the warnings a load would
produce without installing anything.

Both forms are accepted, mirroring `KEY_BINDINGS`' own simple/extended duality:

```python
ACTIONS = {
    "select-docs": select_docs,                          # simple
    "quit": {"func": noisy_quit, "override": True},      # extended
}
```

Extended keys: `func`, `override`, `context`, `description`.

### Override and `invoke`

A name colliding with a built-in in the same context is refused — one warning,
entry skipped — unless `override: True`. `ActionRegistry.register` then files the
displaced built-in in `_overridden` rather than discarding it, so
`registry.builtin()` can still find it and `unregister_source` can put it back.

`ctx.invoke(name)` is `XeFMApp._run_action`, which resolves the user action
first. The re-entrancy guard is what makes wrapping work:

```python
def noisy_quit(ctx):
    ctx.message("bye!")
    ctx.invoke("quit")     # -> the built-in, not itself
```

`_run_action` adds the name to `ActionContext._invoking` before calling, so a
nested `invoke` of the *same* name sees it already running and falls through to
the handler table. A nested invoke of a *different* name runs that user action
normally.

A user action always reports "redraw needed": it can change anything about the
panes and has no way to say what it touched.

### Context restriction

`context` defaults to `"filer"`, and for this version a value other than
`"filer"` is a warning and a skipped entry. The design's reasoning, unchanged:
a user function running inside a viewer needs a per-view API surface (scroll
position, block list, zoom) that has not been designed, and shipping half of one
would freeze it by accident. Rebinding a viewer's *built-in* actions is
unaffected and fully supported. Widening later is additive — the registry
mechanics already allow it; only `_build_action`'s guard would move.

---

## 5. `EVENT_HOOKS`

`user_api.hooks` is an `EventHooks` holding `{event: [callable]}`. `fire()` runs
every hook for an event in order and returns whether any returned `True`.

Hooks behind one that raises still run, and a hook that claims an event does not
suppress the ones after it — a claim decides what *XeFM* does next, not whether
another hook's side effect happens.

| Event | Fired from |
|---|---|
| `startup` | `XeFMApp.run`, after the first render |
| `quit` | `XeFMApp._quit`, before monitoring stops and state is saved |
| `directory_changed` | `XeFMApp._fire_directory_changed`, called from `_list_pane` |
| `file_open` | `XeFMApp._open`, before the dir / archive / file branch |

### `directory_changed`'s choke point

Every listing funnels through `_list_pane` — navigation, the `O`-sync that calls
it directly, a jump, a drive change, a monitor reload — which makes it the one
place that sees all of them. `_fire_directory_changed` compares the pane's path
against `pane["_hook_path"]`, the last path it reported, and fires only on a
difference. That is what keeps the event meaning "changed": a post-operation
reload, a filesystem-monitor reload and a sort change all re-list the same
directory and stay silent.

`_hook_path` defaults to the pane's current path on the first call, so the two
startup listings are silent — `startup` is the event for that. It is recorded
whether or not any hook is installed, so a hook added by a mid-session reload
starts from where the pane actually is instead of missing the first change.

### `file_open`

Fires in `_open` for non-directories only, ahead of the archive / viewer branch.
Entering a directory is navigation, not opening. `entry.is_dir()` can raise on a
vanished or unreadable entry, so that probe is inside the same try/except the
open path already used.

---

## 6. The façade

`xefm/user_api.py` contains no PuiKit type, no widget, and no `XeFMApp`
internal in any signature. It is the firewall that lets the internals keep
moving: `PaneApi` is a model-level view of one pane, holding the app and the
pane's *name* — not the pane dict — so it stays valid across a re-list that
replaces the listing wholesale.

`EntryInfo` reads `is_dir` / `is_link` from the pane's existing `file_info`
cache, which costs nothing, and `stat`s lazily for `size` / `mtime`, which the
cache does not hold (it keeps them pre-formatted for display). A name-only
predicate over a large directory therefore touches the filesystem not at all.

### Dialogs return nothing

The design sketched `ctx.input(prompt) -> str | None`. XeFM has no blocking
modal to build that on — every dialog is a layer pushed onto the panel with an
`on_result` callback, and the event loop keeps running. `input`, `choose` and
`confirm` therefore take callbacks and return `None`. The alternative would have
been a nested event loop, which is a much larger commitment than a preview API
should make.

### Failure isolation

`run_guarded` is the single crossing into user code — actions, hooks and dialog
callbacks all go through it. It logs the exception and a formatted traceback and
returns `None`. `_guard` wraps dialog callbacks specifically, because an
exception escaping into the dialog machinery would leave a modal layer stuck
open with no way to dismiss it.

---

## 6b. Renamed actions

Naming every key made the names already there worth auditing. Nineteen were
changed. Every old spelling survives as an entry in `Action.aliases`, so a config
binding one still resolves to the action — that is the only thing making a
rename possible at all, since every config generated from the template carries
the nine `image_*` names.

The user-facing table is in
[`KEY_BINDINGS_FEATURE.md`](../KEY_BINDINGS_FEATURE.md#renamed-actions);
`test_customization_api.py`'s `SHIPPED_RENAMES` is the authoritative list and is
parameterized over, so an alias cannot be dropped by accident.

Three groups:

**The image viewer's actions gained their viewer's prefix.** `image_zoom_in` →
`image_viewer.zoom_in`. That family was the dotted convention already, spelled
with an underscore, and the rename leaves the plain `zoom_in` / `next` free to
become shared actions if a second viewer grows them.

The text viewer's `toggle_wrap`, `toggle_view_mode` and `change_encoding` were
**not** renamed, and the reason is worth recording because the first pass got it
wrong. Qualifying them would have made the bare name a permanent alias — and an
alias can never become a current name again (`test_no_alias_collides_with_a_current_name`),
so `text_viewer.change_encoding` would have spent `change_encoding`, which is
exactly the name the rule existed to preserve. The `image_*` renames do not have
this problem: their aliases are `image_zoom_in`, not `zoom_in`.

The concern is concrete rather than theoretical. `DiffViewer` already reads
through `text_viewer._read_lines`, which already takes an `encoding` override
and is called there with the detected value discarded — adding the picker is
small, and it would want the same binding. `toggle_wrap` is further along still:
`TextViewer` already forwards it to a rich renderer with its own wrap
(`JsonView`).

**`image_scroll_*` became `image_viewer.pan_*`.** The code is `_pan_by`, the
help says "pan", and the keys move a viewport over a zoomed image. Only the name
was ever wrong.

**Three unrelated things called "search" got names that distinguish them.**
`search` → `isearch` (jump to a match as you type), `search_dialog` →
`find_files`, `search_content` → `find_in_files`. Alongside that, `sort_menu` →
`sort` (it opens a dialog; there is no menu), `drives_dialog` → `drives`
(dropping a suffix that named the widget, which `favorites`/`history`/`programs`
never had), `rename_file` → `rename` (it batch-renames a multi-selection), and
the four selection toggles → `toggle_select_*`, which separates them from
`select_all` / `unselect_all` — those set and clear outright rather than
toggling, and `select_all` sitting one character from `select_all_items` hid
that.

The file list's other 60-odd actions were left alone. `filer` is the default
context and the namespace's incumbent; prefixing `cursor_up` would churn every
config alive to say what the absence of a dot already says.

### How an alias resolves

`ActionRegistry.canonical(context, name)` returns the current name for either
spelling, backed by a per-context alias index rebuilt on `generation` change.
`_context_entries` runs its config pass twice — current names first, then
aliases — so a config carrying **both** spellings of an action resolves to the
current one rather than to whichever it happened to list first; the stale entry
is simply not reached. `_context_binding` walks the same order for one name.

`config.deprecated_names_notice()` produces the nudge, as **one line** however
many names are involved: a config predating several renames would otherwise open
every session with a wall of warnings about bindings that all still work. A name
the config spells both ways is not reported — the current spelling already wins,
and telling someone to rename what they have already renamed is noise.

Aliases are permanent, and an alias may never be reused for a different action —
`test_no_alias_collides_with_a_current_name` enforces the second half.

## 7. Behavior changes

Four, all deliberate:

0. **Nineteen actions were renamed**, old names kept as aliases. See
   "Renamed actions" above.

1. **Viewer keys are rebindable.** The visible win of the refactor.

2. **A key bound to a viewer action no longer fires in the file list**, and vice
   versa. Previously the flat lookup could return either, decided by dict order.
   With the shipped template the outcome is identical (verified by test); a user
   config whose dict order differed could see a change, always in the direction
   of "the key now does what that surface's action says".

3. **A config predating a viewer action now gets that action's current default,
   not the viewer's old hardcoded fallback.** `ImageViewer` used to fall back to
   `n`/`p` for stepping and plain arrows for panning when those actions were
   absent from `KEY_BINDINGS`; it now falls back to the registry defaults
   (`↓`/`↑` and Shift-arrows) — the same keys a freshly written config gets.
   Such a config converges on the documented defaults instead of keeping
   pre-release ones. `test_image_viewer.py`'s `legacy_config` tests assert the
   new behavior.

---

## 8. Preview status

`API_VERSION = 0` and `PREVIEW = True` in `xefm/user_api.py`. The gate is a
notice, not a switch: a config using either variable gets one line in the log
pane at load and at every reload —

```
Customization API (Preview, API_VERSION 0): 2 action(s), 1 event hook(s) loaded
— this API may change without notice.
```

`preview_notice()` returns `None` when both counts are zero, so a config that
does not use the API says nothing.

Reaching `1` means committing to `ActionContext`, `PaneApi`, `EntryInfo` and the
two config variable formats. Before that, the questions worth settling with real
use: whether user functions should be allowed in viewer contexts and what a
per-view API looks like; whether the callback-shaped prompts are livable or want
a different idiom; whether `directory_changed` should also fire on entering and
leaving a search-results (virtual) pane.

---

## 9. Not implemented

**Step 4, exposed registries.** `VIEWER_RENDERERS` feeding
`viewer_registry.register()`, and sort keys / filter predicates as user
callables. `xefm/viewer_registry.py` still anticipates it in its own docstring.
The design flags the reason to wait: a renderer builder returns a PuiKit widget,
which is the one place a PuiKit type must cross the façade, and that is the
hardest part of this API to keep stable across PuiKit releases.

**Add-ons (`~/.xefm/addons/`).** Out of scope by design — the same machinery
plus discovery and lifecycle, and a stability promise to third parties that
should wait until this API has survived a few releases of real config-level use.

**A command palette.** The registry makes it straightforward (fuzzy-run any
action of the active context by name) and it is the obvious next thing to build
on top, but it is a feature, not part of this API.

---

## References

- Design: [`CUSTOMIZATION_API_DESIGN.md`](CUSTOMIZATION_API_DESIGN.md)
- Key bindings: [`KEY_BINDINGS_IMPLEMENTATION.md`](KEY_BINDINGS_IMPLEMENTATION.md)
- Config system: [`CONFIGURATION_SYSTEM.md`](CONFIGURATION_SYSTEM.md)
- Tests: `test/test_customization_api.py`
