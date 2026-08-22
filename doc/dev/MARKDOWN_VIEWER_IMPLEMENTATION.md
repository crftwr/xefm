# Markdown Viewer — Implementation

End-user behavior: `doc/MARKDOWN_VIEWER_FEATURE.md`.

The Markdown viewer is **not** a new modal. It is a second *body renderer* inside
the existing full-window `TextViewer`, selected by file type and toggled in
place. This keeps one set of viewer chrome (header band, footer status bar,
resize/reflow, close/help) and makes future formatted viewers (JSON, CSV) a
matter of registering a renderer — no new modal, no chrome duplication.

## Pieces

### `xefm/viewer_registry.py` — the extensibility seam

A tiny registry mapping a file extension to an optional **rich renderer**:

```python
@dataclass(frozen=True)
class RichRenderer:
    name: str                              # shown in viewer chrome, e.g. "Markdown"
    build: Callable[..., Widget]           # build(source, *, style) -> puikit Widget

def rich_renderer_for(path) -> RichRenderer | None
```

Markdown is registered for `.md` / `.markdown`, building PuiKit's
`MarkdownView(source, style=...)`. `rich_renderer_for` returns `None` for a type
with no rendered view (the common case) — the raw text view is the universal
fallback, so an unregistered type simply has nothing to toggle to.

**Adding a viewer (JSON, CSV, …):** implement a `build(source, *, style)` that
returns a scrollable `puikit.widgets.base.Widget`, then
`register(RichRenderer("JSON", _build_json), ".json")`. Nothing else changes —
`TextViewer` picks it up through the registry and the same **M** toggle drives
it.

### `xefm/text_viewer.py` — raw + rich in one modal

`TextViewer` gained a small amount of state and three seams:

- `__init__`: `self._rich = rich_renderer_for(path)` (renderer or `None`),
  `self._state_manager` (optional, for per-type memory — see below),
  `self.mode` (starts at `self._remembered_view_mode()`, defaulting to `"text"`),
  and `self._rich_widget` (the built widget, lazily created and cached).
- `_ensure_rich_widget()`: builds (once) and caches the renderer widget, reading
  the file source via `_read_source(path)` (backend-agnostic `xefm.path.Path`,
  same encoding ladder as `_read_lines`) and styling it on the content-surface
  colors captured by the last `draw`. Returns whether a rich widget is available
  (`False` for no renderer or an unreadable source). Shared by the toggle and the
  open-straight-into-rich path so both build identically.
- `_toggle_view_mode()`: flips `mode` (building the rich widget via
  `_ensure_rich_widget()` on the first switch), then persists the new mode with
  `_remember_view_mode()`. The widget is cached, so **each mode keeps its own
  scroll position** across toggles. A no-op when `self._rich is None`; refuses
  (stays raw, persists nothing) if the source can't be read as text.
- `draw()`: after the shared header, if `mode == "rich"` it delegates the whole
  body to `_draw_rich`, which draws the embedded widget via `ctx.draw_child(...)`
  in the area between header and footer and paints the footer's toggle-back hint.
  The renderer draws and scrolls itself (own scrollbar), so the raw gutter,
  h-scrollbar and row layout are skipped. When the viewer *opens* straight into a
  remembered rich mode, the widget is `None` on the first frame; `draw` builds it
  there (`_ensure_rich_widget`, now that colors are known) and, if the source
  can't be rendered, drops back to raw for that file. Raw mode is unchanged.
- `handle_event()`: `quit` / `help` / the view toggle / **incremental search**
  are handled in **both** modes. The `isearch` key is intercepted *before* the
  rich forward (the renderer has no search of its own, so it would swallow the
  key); every other key and mouse-scroll in rich mode is **forwarded** to the
  embedded widget (it owns arrows / page / home / end / in-document link jumps).
  Line wrap remains raw-text-only.

### Incremental search in the rendered view (issue #213)

Search reuses the same `ViewerISearch` / `ISearchBar` overlay the raw view uses;
only the match set changes target by mode. `TextViewer` keeps its five search
callbacks (`_search_recompute` / `_search_step` / `_search_status` /
`_search_accept` / `_search_cancel`) and `_enter_search`, each of which now
branches on `_search_target_is_rich()` (rich mode with a built widget):

- **Raw mode** — unchanged: the callbacks drive `TextViewer`'s own line-based
  match set (`self.matches`, `self.match_pos`, highlighted in `_draw_matches`).
- **Rich mode** — the callbacks delegate to the embedded `MarkdownView`'s
  `search_*` API: `search_begin` (remember the pre-search scroll on open),
  `search_set` (live per-keystroke recompute + scroll), `search_navigate`
  (±1 match), `search_status` (counter), `search_accept` / `search_cancel`.

Match finding, scroll-to-match and highlight drawing live in `MarkdownView`
(PuiKit), not `TextViewer`, because they need the widget's own wrapped,
proportional layout (row tops, per-span x positions). The navigable unit is the
**display row** that contains the pattern (mirroring the raw view, which walks
matching *lines*); every occurrence is highlighted in place by redrawing the
matched substrings with an amber-tinted background, preserving each styled run's
own color/font so headings, `code`, links, etc. stay recognisable. The match set
is keyed on `(pattern, wrap width)` so a resize that re-wraps the document
rebuilds it (`_sync_search` in `draw`). The footer hint in `_draw_rich` advertises
the `isearch` key in rich mode.

### Key binding

`text_viewer.toggle_view_mode` → `M`, added to `_config.py` (`M` is shared with
`move_files` / `create_directory`, which only apply in the file list; the viewer
matches its own action by name, the same pattern `text_viewer.toggle_wrap` uses for `W`).

Because `ConfigManager._copy_missing_fields` only merges whole **missing
attributes**, an existing user's `~/.xefm/config.py` — which already has a
`KEY_BINDINGS` dict — will **not** gain the new key automatically. That is now
handled generally rather than per viewer: the action carries its own default
keys in `xefm/actions.py`, used whenever the config does not name it, so a
config written before the action existed still gets `M` and a rebind still
wins. (Before the action registry, `_view_mode_pressed()` did this on its own
with a hardcoded literal-`m` fallback; that method is gone — see
[`CUSTOMIZATION_API_IMPLEMENTATION.md`](CUSTOMIZATION_API_IMPLEMENTATION.md).)

### Remembering the view mode (issue #217)

The chosen mode is persisted **per file extension** through the state manager, so
a type reopens the way it was last viewed:

- `_view_mode_state_key()` → `"viewer_mode:" + path.suffix.lower()` (e.g.
  `"viewer_mode:.md"`), or `None` when there's no state manager or no renderer
  for the type (nothing to remember).
- `_remembered_view_mode()` reads that key at construction to pick the opening
  mode (`"rich"` only when the stored value is exactly `"rich"`; anything else,
  including unset, is `"text"`).
- `_remember_view_mode()` writes the current mode after every explicit toggle.

The `state_manager` is threaded in from `XeFMApp` via `show_text_viewer(...,
state_manager=self.state_manager)` — the same instance XeFM uses for theme/pane
persistence, mirroring how the `theme` preference is stored. It's **optional**:
when absent (a bare `TextViewer(path)` or a `show_text_viewer` call with no state
manager, as in most tests), the key helpers return `None`, so the viewer just
opens raw and persists nothing — no writes to the real state store as a side
effect. Storage is per-extension by design: `.md` and `.markdown` are remembered
independently even though they share the Markdown renderer.

## Design notes / limitations

- **Why embed, not push a new layer.** The UX is "toggle in place"; the opening
  mode is raw unless the type's remembered choice is rich. Embedding as a body
  renderer reuses `TextViewer`'s chrome and resize handling and keeps a single
  modal on the layer stack, so the toggle is a flag flip, not a push/pop.
- **Source is read twice** for a Markdown file that gets toggled (once as lines
  for the raw view in `__init__`, once as raw source on first toggle). The raw
  view is the default and most files are never toggled, so the second read is
  lazy and paid only on demand; the cost is negligible next to a modal file view.
- **Link clicks inside rendered Markdown are not wired yet.** Links *render*
  (styled/underlined) and keyboard navigation works, but `TextViewer` forwards
  events to the embedded widget without translating pointer coordinates into the
  child's local space, so `MarkdownView`'s click hit-testing (open URL / jump to
  heading) would be off. Deferred; needs the same widget-local pointer transform
  the splitter uses. Keyboard + wheel scrolling is fully functional.

## Tests

`test/test_markdown_viewer.py` (parametrized TUI + GUI profiles): the registry
mapping and plain-type fallback; a `.md` opening raw with a renderer available; a
plain file having no renderer (toggle no-op); toggle builds/caches the
`MarkdownView` and each mode keeps its scroll; the `M` key path (via the literal
fallback); both modes draw without crashing; rich-mode scroll forwarding; quit
closing from rich mode; and **rich-mode incremental search** — opening the bar
with `F`, the counter/status delegating to the embedded widget, `↑`/`↓`
navigation moving the offset, `Enter` keeping the position, `Esc` restoring the
pre-search scroll and clearing, a no-match showing `0/0`, and the search key being
intercepted rather than swallowed by the renderer.

The `MarkdownView.search_*` API itself (match finding, case-insensitivity,
nearest-at/after-offset, wrap navigation, no-match origin restore, in-place
highlighting that preserves run color, and rebuild-on-rewrap) is covered
exhaustively in PuiKit's `tests/test_markdown_view.py`.

`test/test_viewer_mode_memory.py` (parametrized TUI + GUI profiles) covers the
per-type memory: no state manager or nothing stored → opens raw; a remembered
`"rich"` opens rich and builds the `MarkdownView` on first draw; a remembered
`"text"` opens raw; toggling persists the choice so a *different* same-extension
file reopens the same way (both directions); the memory is per-extension (`.md`
doesn't leak to `.markdown`); and an unregistered type (`.txt`) opens raw, its
toggle is a no-op, and no state key is written for it.
