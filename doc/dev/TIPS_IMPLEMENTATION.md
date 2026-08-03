# Tip of the Day — Implementation

Issue #261. Two new modules plus a small wiring in `app.py`.

## Modules

- **`xefm/tips.py`** — the content. `TIPS` is a tuple of `(title, body)`
  pairs; bodies are Markdown and may reference key bindings as `{key:action}`
  placeholders. `render_tip(index, resolve)` produces the final Markdown
  (`### title` + body), resolving each placeholder through `resolve` — the app
  passes `XeFMApp._keys_label`, the same live-keymap labeler the help dialog
  uses, so tips always quote the user's actual keys. `referenced_actions()`
  exists for the tests. The index is taken modulo `tip_count()` everywhere, so
  the list can grow or shrink between versions without invalidating a saved
  rotation position.

- **`xefm/tips_dialog.py`** — `TipsDialog`, the standard XeFM modal shape
  (a `Widget` pushed as a Panel layer; `sort_dialog.py` is the template). Body
  is a PuiKit `MarkdownView` (`set_source` on navigation resets the scroll),
  the opt-out is a PuiKit `Checkbox`, footer is the usual muted hint line plus
  a right-aligned `3/26` counter. Fixed box size — tips differ in length and a
  box that resized on every ←/→ would jitter; the body scrolls instead. On
  close it reports `(index, dont_show)` through `on_result` and touches no
  storage itself.

## App wiring (`app.py`)

- `show_tips()` — opens the dialog at the persisted rotation index; wired to
  **Help ▸ Tip of the Day…** and used by startup.
- `_tips_closed(index, dont_show)` — the `on_result` handler; persists
  `tips.index = (index + 1) % tip_count()` and `tips.enabled = not dont_show`.
  Best-effort, like the other state writes.
- `_maybe_show_startup_tip()` — called from `run()` after the first render
  (not `__init__`, so tests constructing `XeFMApp` directly never get a
  surprise layer). Returns quietly unless `tips.enabled` (default `True`) and
  `tips.last_shown` differs from today's local date; writes the date *before*
  opening, so a same-day relaunch stays quiet regardless of how the dialog is
  closed.

## State keys (state DB, `state_manager`)

| Key | Meaning |
| --- | --- |
| `tips.enabled` | Startup dialog on/off (the checkbox, inverted). Default `True`. |
| `tips.index` | Next unseen tip. Advanced past the last tip *viewed* on close. |
| `tips.last_shown` | ISO date of the last startup showing (once-per-day gate). |

There is no config-file switch: the opt-out is app-written state, and the
dialog itself (opened from the menu) is the UI to flip it back.

## Adding a tip

Append a `(title, body)` pair to `TIPS`. Keep the Welcome tip first — a fresh
install starts at index 0. Only reference `{key:action}` for actions that are
**bound in the template keymap** (`xefm/_config.py` `KEY_BINDINGS`); actions
shipped unbound (`edit_config`, `toggle_color_scheme`, …) must be described by
their menu path instead, or they render as `—`.
`test_tips_dialog.py::test_all_referenced_actions_are_bound_by_default`
enforces this.

## Tests

`test/test_tips_dialog.py` — content checks (rotation size, Welcome first,
placeholder resolution, template-keymap coverage) and app-integration tests via
MemoryBackend + a temp state DB (navigation and wrapping, rotation
persistence, the opt-out round-trip, checkbox click, once-per-day startup).
