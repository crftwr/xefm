# TAB Completion — Implementation

User-facing behaviour: [TAB_COMPLETION_FEATURE.md](../TAB_COMPLETION_FEATURE.md).

TAB completion is built as a **reusable component**, decoupled from any single
dialog, so the same engine can drive completion anywhere a single-line field is
edited.

## Pieces

| Layer | File | Role |
|-------|------|------|
| Logic | `xefm/completion.py` | LCP helper, `Completer` protocol, `FilepathCompleter`, `CompletionController` |
| Widget | `xefm/candidate_list.py` | `CandidateListOverlay` + `compute_overlay_rect` |
| Host | `xefm/input_dialog.py` | owns the overlay layer's lifecycle + event routing |
| Callers | `xefm/app.py` | pass a `FilepathCompleter` to the five prompts |

### `xefm/completion.py` (UI-agnostic — no PuiKit draw code)

- `calculate_common_prefix(candidates)` — case-sensitive longest common prefix;
  `[]` → `""`, a single candidate → the whole candidate.
- `Completer` (`typing.Protocol`) — `get_candidates(text, cursor_pos) -> list[str]`
  and `get_completion_start_pos(text, cursor_pos) -> int`.
- `FilepathCompleter(base_directory=None, directories_only=False, show_hidden=True)`
  — splits the text before the caret at the last `os.sep` into a directory +
  filename prefix, reads that directory in **one pass** via
  `xefm.dir_scan.scan_dir` — the same bulk enumeration the pane listing uses
  (`getattrlistbulk` on macOS, `os.scandir` elsewhere), so a large directory
  costs one enumeration instead of a per-entry `isdir` stat (issue #246); a
  leading `~`/`~user` is expanded for the lookup only — and returns names that
  start with the prefix (case-sensitive), sorted, with `os.sep` appended to
  directories (`attrs["is_dir"]`; a broken symlink reads as not-a-directory,
  as `os.path.isdir` did).
  `directories_only` drops files. `show_hidden=False` (issue #258) drops
  dot-entries **unless the token itself starts with `.`** — the shell convention,
  so an explicitly typed dot still reaches `.config` while hidden files are off;
  the app passes the panes' `flm.show_hidden` at each of the five call sites.
  It also drops entries whose `attrs["hidden"]` is set (the Windows hidden
  attribute, issue #284) — with no dot-escape, since the attribute has no
  spelling in the typed token.
  Filesystem errors (`FileNotFoundError`, `PermissionError`, `NotADirectoryError`,
  `OSError`) return `[]` — so a not-yet-existing or non-local path is a no-op, not
  a crash. The completer itself stays synchronous; *threading is the
  controller's job* (below).
- `CompletionController(edit, completer, threaded=False)` — the **reusable
  seam**. It reads/writes only `edit.text` / `edit.cursor` (and clears
  `edit._anchor`), so it depends on no particular dialog. State: `active`,
  `candidates`, `focused_index` (`-1` = no highlight), `completion_start_pos`.
  Key methods:
  - `on_tab()` — insert the common prefix if it extends the typed token; open the
    list when `len(candidates) > 1`.
  - `on_text_changed()` — refresh after an edit; hide on zero matches, keep open
    for one; typing clears the highlight (arrows navigate).
  - `move_focus(delta)` — wrap the highlight; from none, forward → first, back →
    last.
  - `accept()` — apply the highlighted candidate and return `True`; return `False`
    when nothing is highlighted (so Enter is an ordinary submit — this is why the
    "no highlight" state is functionally, not just visually, distinct).
  - `apply_index(i)` / `dismiss()` — mouse-selection and Esc.

### Threaded candidate listing (issue #246)

With `threaded=True`, `on_tab()` / `on_text_changed()` no longer run the
completer inline: each spawns a daemon worker (`_spawn_fetch`) that calls
`completer.get_candidates` off-thread and posts `(gen, kind, text, cursor,
candidates)` to a thread-safe queue. The UI side applies results with:

- `pump()` — drain the queue on the UI thread; a result is **dropped** when a
  newer fetch or a `dismiss()` superseded it (generation mismatch) or when the
  field's text/caret moved on while it ran (snapshot mismatch), so a slow
  listing can never clobber later typing. The LCP insertion for a TAB happens
  here, at apply time.
- `wait(timeout)` / `fetch_pending()` — let the host give a fetch a brief
  synchronous window and keep polling while one is in flight.

The worker touches only its snapshot arguments and the queue; all controller
state stays UI-thread-owned. `dismiss()` also invalidates any in-flight fetch
(generation bump), which is what makes closing the dialog mid-fetch safe.

### `xefm/candidate_list.py` (presentational)

`CandidateListOverlay(Widget)` draws the popup with **no heavy frame**: rows sit
on a distinct `popup_bg` surface (all a terminal needs to separate them), the
highlighted row filled with `selection_active_bg`, and PuiKit's standard scrollbar
(`ctx.draw_scrollbar`) past `MAX_ROWS = 8`. A GUI backend adds a hairline
`round_rect` outline and inherits the layer's drop shadow. Row pitch is
`ctx.line_height`, so it matches the standard list look. Rows are drawn directly
rather than via `ListView` so the "no row highlighted" state is faithful. It holds
no logic: the host calls `set_state(candidates, focused_index)` and, for forwarded
clicks, `handle_event`, which reports the row through `on_activate`.
`overlay_geometry(...)` returns the rect: directly **below the field**, or above
when there's no room (Req 2.2/2.3), left-anchored at the token column, sized to the
longest (measured) candidate — no border rows reserved.

### Overlay as a non-interactive TOP layer (key design decision)

The candidate list is its **own layer, above the dialog** (`z = dialog_z + 1`), so
it visually hugs the field — but it must not steal the keyboard from the field.
That required a small **PuiKit layer-system extension** (`puikit/panel.py`): a
layer can be pushed **non-interactive** (`push_layer(..., interactive=False)`).

- `_Slot` gains `interactive: bool = True`; `Panel._top_interactive_slot()`
  returns the top-most interactive layer.
- `dispatch_event`, `focused_leaf`, and the per-layer `focused` draw flag now
  target the **top-most interactive** layer, not simply `_layers[-1]`. So a
  non-interactive overlay draws on top (by z) yet is transparent to events and
  focus: the dialog beneath keeps event routing, the focus leaf, and the
  `focused` flag — its text field keeps the caret and IME.
- This is covered by `tests/test_panel.py::test_non_interactive_layer_is_transparent_to_events_and_focus`.

The dialog **drives the overlay programmatically** (holds the reference; the
overlay never receives events itself). `panel.remove(overlay)` tears it down.

Because the overlay is now higher-z, it draws **after** the dialog in the same
render pass — so the dialog positions it (in its own `draw`, from measured field
geometry) *before* it draws, and it lands correctly the first frame. This is what
removed the one-frame position jump on GUI.

### InputDialog wiring (`xefm/input_dialog.py`)

`show_input(..., completer=...)` enables completion. `InputDialog`:

- creates a `CompletionController` up front (**threaded**) and the
  `CandidateListOverlay` lazily on first activation;
- `handle_event`: `tab` → `on_tab`; `up/down/pageup/pagedown` (while active) →
  `move_focus`; `enter` → `accept()` or fall through to the normal submit;
  `escape` → close the list first, else cancel; ordinary edits → `on_text_changed`.
  Each of these calls `_sync_overlay()`, which pushes (non-interactive, `z+1`, with
  a placeholder rect) or removes the overlay to match the controller. The app
  re-renders after every consumed event (`on_event` in `xefm/app.py`), so the handlers
  don't render themselves.
- `tab` and edits go through `_drain_completion()`: `wait(0.02)` gives the
  threaded fetch a 20 ms synchronous window — a local listing lands inside it,
  so the overlay opens within the same key event, exactly like the old inline
  listing — then `pump()` + `_sync_overlay()`. A fetch still running after the
  window (a slow mount) is left to its worker and picked up by a 30 ms
  `panel.call_later` poll (`_pump_completion`, which renders on apply);
  `call_later` works on every backend, so there is no capability branch.
  `_close()` cancels the poll and `dismiss()`es the controller, dropping any
  in-flight result.
- `draw` captures the dialog's `screen_rect` and the field's rect, then sets the
  overlay slot's rect via `overlay_geometry` using the *measured* text width before
  the token — running before the overlay draws, so no reflow flash.
- Mouse: because the overlay isn't the interactive layer, its clicks arrive at the
  dialog; `_forward_overlay_click` converts dialog-local → absolute → overlay-local
  and forwards a click that lands inside the overlay (so it isn't read as an
  outside-click cancel).

## Reusing it elsewhere

Attach a `CompletionController` to any widget that owns a `TextEdit`: forward TAB
to `on_tab()`, arrows to `move_focus()`, Enter to `accept()`, Esc to `dismiss()`,
and call `on_text_changed()` after edits; render the candidates from
`controller.candidates` / `focused_index` (reuse `CandidateListOverlay`, or draw
your own). Supply any `Completer` — `FilepathCompleter` is one implementation.

## Tests

`test/test_completion.py` (34 tests, `python -m pytest`): the LCP helper,
`FilepathCompleter` against a temp tree (prefix/sep/sorted/case/`~`/absolute/
missing-dir, hidden-file filtering incl. the explicit-dot override), and
`CompletionController` on a real `TextEdit` (LCP insert, single full-completion,
narrow/hide, focus wrap, accept consumed-vs-not, apply/dismiss). Threaded mode is
tested with a gate-blocked completer (`GatedCompleter`): apply-on-pump, a stale
snapshot dropped after further typing, dismiss invalidating an in-flight fetch,
and a live refresh cycle.
The overlay layer lifecycle and event routing were verified end-to-end through a
`MemoryBackend` panel (including that `focused_leaf` stays on the field, so IME
survives, while the popup is on top). The PuiKit non-interactive-layer primitive
has its own test in `puikit/tests/test_panel.py`.
