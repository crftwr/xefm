# Log Clipboard Copy Implementation

How the log pane's contents reach the system clipboard: two named actions,
`copy_log_selection` and `copy_log_all`, both living in the `filer` context and
both reaching into the `LogView` without needing it to hold focus.

User-facing description: [LOGGING_FEATURE.md](../LOGGING_FEATURE.md#copy-log-to-clipboard).

## How it got here

Before the PuiKit port, an `Edit` menu carried "Copy Visible Logs" / "Copy All
Logs", served by `LogManager.get_visible_log_text()` and
`get_all_log_text()` reading a `LogPaneHandler` buffer. The port replaced the
whole rendering path — the pane is now a PuiKit `LogView` fed by a queue — and
took the menu with it. What survived was a single hardcoded chord in
`XeFMApp._copy_log_selection`: `event.key == "c"` plus a modifier chosen by
sniffing the backend class name (`cmd` on `MacOSBackend`, `ctrl` otherwise),
tested ahead of the keymap and gated on `panel.focused_leaf() is self.log`.

It worked, and nothing named it. It could not be rebound, the help dialog and
the menu never mentioned it, and issue #360 was filed as "the TUI has no way to
copy the log, and the desktop app has no Edit menu". The fix is not new
copying — it is giving the copying a name.

## Two actions, no new context

Both are ordinary `filer` actions ([`xefm/actions.py`](../../xefm/actions.py)),
registered next to the seven `scroll_log_*` / `adjust_log_*` / `reset_log_height`
actions that already drive the log pane.

That placement is the whole design decision. A `log` context — resolved only
while the pane holds focus, the way `isearch` is — was the obvious shape and is
the wrong one here: XeFM moves keyboard focus **only on a mouse press** (PuiKit's
`Panel._route_mouse` → `focus_on_click`; `switch_pane` flips
`pm.active_pane` and the panes' `active` flags, never PuiKit focus), so anything
confined to a log context would be unreachable without a mouse. The existing log
actions already answer this: a `filer` action that operates on `self.log`
directly. The two new ones do the same.

Dropping the focus gate follows from that, and costs nothing: the file panes
have no text selection to compete for the chord, the viewers and the isearch bar
are modal layers that consume keys before the keymap sees them, and a log
selection is drawn on screen — so acting on what the user can see is more
predictable than acting on where focus happens to sit. `LogView` keeps a
selection across a blur (only `clear`, `set_lines` and a max-lines trim reset
it), which is exactly the case the old gate got wrong: select in the log, click a
pane, press the chord, nothing happened.

## The two handlers

Both are in [`xefm/app.py`](../../xefm/app.py), next to `copy_names_to_clipboard`
and friends, and both are entries in the action handler table.

- **`copy_log_selection()`** — `self.log.selection_text()`, pushed with
  `panel.set_clipboard()`, then `self.log.clear_selection()`. Empty selection is
  a no-op, which is what keeps the chord inert in the common case. The text comes
  back as **display rows**, so a wrapped line arrives split at its wrap points —
  that is what the user highlighted.
- **`copy_log_all()`** — joins `self.log.lines` (the widget's own ring buffer,
  capped at 2000 by its constructor), so it takes **logical** lines, unwrapped,
  including everything scrolled out of view. It reports the count through
  `log_info`, after the snapshot, so the confirmation is never part of what was
  copied.

Neither goes near `LogManager.get_all_log_text()` / `get_visible_log_text()`.
Those read a `LogPaneHandler` that the running app never installs — XeFM routes
records through `set_log_sink` instead (see `getLogger` in
[`xefm/log_manager.py`](../../xefm/log_manager.py)), and `XeFMApp.log_info`
appends to the `LogView` without touching `logging` at all — so they return `""`
in production. They are exercised only by `test/test_copy_log_clipboard.py`,
which builds a `LogManager` by hand. Don't wire new code to them.

## Bindings

In the [`_config.py`](../../xefm/_config.py) template, under "Log Pane Control":

```python
'copy_log_selection': ['Command-C', 'Ctrl-C'],
'copy_log_all': [],
```

Both chords are listed because one machine runs both frontends: the macOS GUI
answers `Command-C`, while no terminal ever delivers Command — so the pair
reproduces exactly what the backend sniffing used to compute at runtime, without
the sniffing. The `sys.platform == 'win32'` branch narrows it to `['Ctrl-C']`, so
the menu's shortcut hint reads `Ctrl-C` there rather than `⌘C`.

`copy_log_all` ships deliberately unbound: this key family has few chords left,
and the action's home is the menu. An empty list is meaningful to
`KeyBindings._context_entries` — the name is *claimed* with no keys, which is
what stops the registry default from filling one in — and a user who wants a key
writes one in their own config.

Existing configs predate both names, and `_copy_missing_fields` adds whole
missing *fields*, never a missing key inside `KEY_BINDINGS`. The keys therefore
have to come from `Action.resolved_default_keys()`, which reads the shipped
template at runtime — including its platform branch, evaluated on the user's own
machine.

## Where they surface

- **Edit menu** — new in `_build_menu()`, between File and Go: `Copy Name(s)` and
  `Copy Full Path(s)` moved here from File, then the two log copies. Items go
  through `_menu()` (dispatch + render) rather than the bare method, because
  their only feedback is a log line and a native macOS menu activation renders
  nothing on its own (#253). `enabled` predicates read live widget state:
  `bool(self.log.selection_text())` and `bool(self.log.lines)`.
  `_menu_shortcut()` now resolves in the `filer` context rather than reading the
  flat `KEY_BINDINGS` dict, so an item whose action the user's config never
  names — every action added after that config was written, these two included —
  shows the default key instead of a blank hint.
- **Help dialog** — a new "Log Pane" section listing all nine log actions. The
  seven older ones had never appeared there at all.
- **Tip of the day** — "Take the log with you", next to the existing log tip.

## Tests

[`test/test_log_clipboard.py`](../../test/test_log_clipboard.py) drives a live
`XeFMApp` on the memory backend: the selection copy works with focus elsewhere
and clears the highlight, an empty selection leaves the clipboard alone,
`copy_log_all` takes lines scrolled out of view and reports the count on screen,
the chord resolves to the action both from the template and from an empty config,
`copy_log_all` resolves to no keys, and the Edit menu carries both items with
their enable predicates.

`test/test_menu_bar_activation.py` pins the bar's titles and Alt+letter indices,
so it moved with the new menu.
