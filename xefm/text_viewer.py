"""TextViewer — a modal syntax-highlighting text viewer for the PuiKit port.

The text viewer: a full-window read-only
viewer with line numbers, vertical + horizontal scroll, line wrapping, and
optional pygments syntax highlighting (a soft dependency — without it the text
shows plain). Incremental search (the ``search`` binding) opens the same
``ISearchBar`` overlay the main file manager uses: every match is highlighted and
``Up``/``Down`` walk between them.

Content is drawn in a fixed-advance face so the line-number gutter, horizontal
scroll, and search highlights line up by column on the GUI as well as the TUI.
File reading goes through ``xefm.path.Path`` so it works for every storage
backend. Push it with :func:`show_text_viewer`.

Keys resolve through the shared ``KEY_BINDINGS`` (so they honour the user's
rebinds): ``search`` opens incremental search, ``toggle_wrap`` toggles line wrap,
``help`` and ``quit`` do the obvious. ↑/↓/PageUp/PageDown/Home/End scroll
vertically and ←/→ scroll horizontally (viewer-local); Esc closes.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.font import Font
from puikit.panel import Rect
from puikit.text import elide, word_bounds
from puikit.widgets._input import MultiClickTracker
from puikit.widgets.base import Widget

from xefm.config import (get_keys_for_action, is_action_for_event,
                        keys_label_for_action)
from xefm.dialog_geometry import OPEN_MS_VIEWER, animate_open
from xefm.isearch_bar import ViewerISearch
from xefm.log_manager import getLogger
from xefm.text_dialog import keys_markdown, show_markdown
from xefm.viewer_registry import rich_renderer_for

logger = getLogger("TextViewer")

try:
    from pygments.lexers import get_lexer_for_filename, get_lexer_by_name, TextLexer
    from pygments.util import ClassNotFound
    _PYGMENTS = True
except ImportError:
    _PYGMENTS = False

#: Content is fixed-advance so columns (gutter, h-scroll, highlights) align.
MONO = Font(monospace=True)
_TAB = 8

#: State-manager key prefix for a file type's remembered view mode. The value
#: ("rich" | "text") is stored per lower-cased extension (e.g. "viewer_mode:.md"),
#: so a type reopens in the mode last chosen for it (issue #217).
_VIEW_MODE_STATE_PREFIX = "viewer_mode:"


def _content_bg(theme) -> tuple[int, int, int] | None:
    """The file-pane content surface, so a full-window viewer sits on XeFM's own
    background instead of the lighter ``popup_bg`` (which reads as a floating
    menu). Falls back to ``popup_bg`` for a theme without surface roles."""
    if theme is None:
        return None
    return theme.surface_bg("content") or getattr(theme, "popup_bg", None)


def _status_bg(theme) -> tuple[int, int, int] | None:
    """The themed status-bar surface — the same ``status`` role the main window's
    bottom bar uses (its theme recipe / headroom pass already guarantees legible
    chrome text) — so a full-window viewer ends in a bar consistent with XeFM
    proper instead of a dim hint on the content background. Falls back to the
    content surface for a theme without the role."""
    if theme is None:
        return None
    return theme.surface_bg("status") or _content_bg(theme)


def _header_bg(theme) -> tuple[int, int, int] | None:
    """The themed header surface — the same ``header`` role the main window's pane
    header bars use — so a viewer's title reads as a distinct band above the
    content rather than text floating on the content background. Falls back to the
    content surface for a theme without the role."""
    if theme is None:
        return None
    return theme.surface_bg("header") or _content_bg(theme)


def draw_status_bar(ctx, y: float, text: str, *, font=None, pad_x: float = 0.0,
                    bottom_pad: float = 0.0) -> None:
    """Paint a viewer's bottom status bar, exactly like the main window's
    ``StatusBar``: the ``status`` surface fills the **full** window width (edge to
    edge) and reaches the bottom edge (``bottom_pad`` extra height below the row),
    while only the *text* is inset — ``pad_x`` from the left. The bar text is
    auto-inked so it reads on every theme's status recipe. ``font`` pins a fixed
    advance where the caller needs columns to line up (the search field)."""
    wu, _hu = ctx.size_units
    theme = ctx.theme
    bar_bg = _status_bg(theme)
    fg = theme.muted_text if theme is not None else (150, 150, 150)
    ctx.fill_rect(0, y, wu, 1.0 + bottom_pad, Style(bg=bar_bg))
    label = elide(text, max(0.0, wu - 2 * pad_x), where="end", measure=ctx.measure_text)
    ctx.draw_text(pad_x, y, label, Style(fg=fg, bg=bar_bg, font=font))


#: Content inset for the full-window modal viewers (text / diff / directory diff),
#: matching the main window's ``BAR_PAD_PX``. A viewer fills the window with its
#: own surface and draws its chrome (header, gutter, rows, scrollbars, footer)
#: inset by this much, so it breathes in from the frame the same amount XeFM's bars
#: and log do. GUI only — a character grid has no sub-cell, so it collapses flush.
VIEWER_PAD_PX = 4.0


def viewer_layer_hints(sw: float, sh: float) -> dict:
    """Layer hints shared by the three full-window modal viewers (text / file diff /
    directory diff), so all three sit on the background the same way.

    ``cover`` replaces the file manager beneath rather than floating over it.
    ``surface: content`` names the surface they paint — the Panel resolves the color
    and hands it down the draw context (text inheritance, auto-ink) even though
    ``self_paint`` leaves the painting to the viewer, which owns the fallback for a
    theme without the role. That combination is what lets a viewer drop its page fill
    over an animated background (``ctx.wallpaper``) and show the scene at full
    strength, exactly as the file panes do — see :meth:`TextViewer.draw`."""
    return {"x": 0, "y": 0, "w": sw, "h": sh,
            "cover": True, "surface": "content", "self_paint": True}


def viewer_pad(ctx) -> tuple[float, float]:
    """The (x, y) content inset for a modal viewer, in base units: ``VIEWER_PAD_PX``
    device pixels on a vector backend, zero on a character grid. The bars keep
    their full-width surfaces (see :func:`draw_status_bar`); only text and the
    scrolling body are inset by this, so a viewer breathes in like the main
    window's chrome rather than sitting in a bordered card."""
    if not ctx.vector_shapes:
        return (0.0, 0.0)
    bw, bh = ctx.base_size
    return (VIEWER_PAD_PX / bw if bw else 0.0, VIEWER_PAD_PX / bh if bh else 0.0)

#: pygments token category → RGB — the default syntax palette (VS Code Dark+),
#: categorised by substring of the token name (see
#: ``get_syntax_color``). A theme overrides any subset of these via its
#: ``extras['syntax']`` (see :func:`_syntax_palette` and xefm/app.py's ``_theme``); the
#: viewer bakes the resolved palette at show time.
DEFAULT_SYNTAX = {
    "keyword": (86, 156, 214),
    "string": (206, 145, 120),
    "comment": (106, 153, 85),
    "number": (181, 206, 168),
    "operator": (212, 212, 212),
    "builtin": (78, 201, 176),
    "name": (156, 220, 254),
}
_ERROR_FG = (229, 110, 110)
#: Search-match highlight = the content background blended toward amber; the
#: current match is a firmer blend. Derived (not a fixed dark constant) so the
#: highlight tracks the theme — a dark wash on a dark theme, a pale one on light.
_MATCH_HUE = (200, 175, 55)
_MATCH_TINT = 0.24
_CURRENT_MATCH_TINT = 0.46


def _mix(a, b, t):
    """Linear RGB blend a→b by ``t`` (0..1)."""
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _is_light(bg) -> bool:
    """True when ``bg`` is a light surface (Rec.601 luma). Lets a caller flip a
    polarity-dependent choice — e.g. keep the dark-tuned syntax palette exact on
    a dark theme but let auto-ink re-tone it for a light one."""
    if bg is None:
        return False
    return (0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]) >= 140


def _match_bg(content, current: bool):
    """Search-highlight background for ``content``, firmer for the current match."""
    return _mix(content or (30, 30, 38), _MATCH_HUE,
                _CURRENT_MATCH_TINT if current else _MATCH_TINT)


def _syntax_palette(panel) -> dict:
    """The active theme's text-viewer syntax palette — its ``extras['syntax']``
    merged onto :data:`DEFAULT_SYNTAX` — resolved from ``panel.theme`` at show
    time. A theme names only the tokens it wants to recolor; the rest fall back to
    the VS Code default. Resolved once when the viewer opens (the modal viewer
    swallows the theme-toggle key, so the palette can't change while it is up)."""
    theme = getattr(panel, "theme", None)
    extra = theme.extras.get("syntax") if theme is not None else None
    return {**DEFAULT_SYNTAX, **extra} if extra else DEFAULT_SYNTAX

_EXT_LEXERS = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".json": "json",
    ".md": "markdown", ".yml": "yaml", ".yaml": "yaml", ".xml": "xml",
    ".html": "html", ".css": "css", ".sh": "bash", ".bash": "bash", ".c": "c",
    ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".java": "java", ".go": "go",
    ".rs": "rust", ".php": "php", ".rb": "ruby", ".sql": "sql", ".ini": "ini",
    ".cfg": "ini", ".conf": "ini", ".toml": "toml",
}


def _expand_tabs(line: str) -> str:
    """Column-aware tab expansion to ``_TAB`` stops."""
    if "\t" not in line:
        return line
    out: list[str] = []
    col = 0
    for ch in line:
        if ch == "\t":
            n = _TAB - (col % _TAB)
            out.append(" " * n)
            col += n
        else:
            out.append(ch)
            col += 1
    return "".join(out)


def _syntax_fg(token_type, palette: dict) -> tuple[int, int, int] | None:
    name = str(token_type)
    if "Keyword" in name:
        return palette["keyword"]
    if "String" in name:
        return palette["string"]
    if "Comment" in name:
        return palette["comment"]
    if "Number" in name:
        return palette["number"]
    if "Operator" in name or "Punctuation" in name:
        return palette["operator"]
    if "Builtin" in name:
        return palette["builtin"]
    if "Name" in name:
        return palette["name"]
    return None  # default text color


def looks_binary(path, sample_size: int = 1024) -> bool:
    """Whether ``path`` holds binary content, judged by a NUL byte in its first
    ``sample_size`` bytes.

    Returns False when the file cannot be sampled at all — "unreadable" is not
    "binary", and the caller's own error handling gives a better message than a
    misleading binary verdict would.

    This is deliberately a content check: XeFM keeps no list of binary
    extensions, because any such list is wrong for a file with no extension, an
    unknown one, or a misleading one.
    """
    try:
        with path.open("rb") as f:
            chunk = f.read(sample_size)
    except Exception:
        return False
    return b"\x00" in chunk


def _read_lines(path) -> tuple[list[str], bool]:
    """Read ``path`` into display lines (tabs expanded). Returns ``(lines,
    is_error)``; a binary file yields a one-line placeholder with error=True."""
    # Sniff *before* decoding, not after. latin-1 maps all 256 byte values and
    # so never raises UnicodeDecodeError — any decode loop containing it always
    # succeeds, which previously left this placeholder unreachable and rendered
    # binaries as thousands of lines of mojibake.
    if looks_binary(path):
        return ["[Binary file — cannot display as text]"], True
    content = None
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            content = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except (FileNotFoundError, OSError) as exc:
            return [f"Error reading file: {exc}"], True
    if content is None:
        return ["[Binary file — cannot display as text]"], True
    return [_expand_tabs(line) for line in content.splitlines()], False


def _read_source(path) -> str | None:
    """Read ``path`` as raw text (tabs and line endings intact) for a rich
    renderer, trying the same encodings as :func:`_read_lines`. Returns ``None``
    when it can't be read at all (missing / OS error); a binary file still
    decodes via the latin-1 fallback, so the renderer — not this reader — decides
    what to make of it."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except (FileNotFoundError, OSError):
            return None
    return None


def _highlight(lines: list[str], path, palette: dict | None = None) -> list[list[tuple[str, Any]]]:
    """Map each line to a list of ``(text, fg)`` segments, colored per ``palette``
    (a token-category → RGB map; the active theme's syntax palette, defaulting to
    :data:`DEFAULT_SYNTAX`). With pygments off (or on failure) each line is a
    single default-colored segment."""
    palette = {**DEFAULT_SYNTAX, **(palette or {})}
    plain = [[(line, None)] for line in lines]
    if not _PYGMENTS or not lines:
        return plain
    try:
        try:
            lexer = get_lexer_for_filename(path.name)
        except ClassNotFound:
            lexer = get_lexer_by_name(_EXT_LEXERS[path.suffix.lower()]) \
                if path.suffix.lower() in _EXT_LEXERS else TextLexer()
        text = "\n".join(lines)
        result: list[list[tuple[str, Any]]] = []
        current: list[tuple[str, Any]] = []
        for token_type, value in lexer.get_tokens(text):
            fg = _syntax_fg(token_type, palette)
            if "\n" in value:
                parts = value.split("\n")
                if parts[0]:
                    current.append((parts[0], fg))
                result.append(current)
                for part in parts[1:-1]:
                    result.append([(part, fg)] if part else [])
                current = [(parts[-1], fg)] if parts[-1] else []
            elif value:
                current.append((value, fg))
        if current:
            result.append(current)
        if not result:
            return plain
        # Keep exactly one row per source line: pygments' token stream ends at
        # the last real newline, so a file ending in blank line(s) yields fewer
        # rows than splitlines() — pad with empty rows (drawing bounds line_idx
        # by self.lines, then indexes self.highlighted, so a short list crashes).
        result = result[:len(lines)]
        result += [[] for _ in range(len(lines) - len(result))]
        return result
    except Exception:
        return plain


def draw_hscrollbar(ctx, x: float, y: float, w: float, left: float,
                    content_w: int, max_line: int) -> None:
    """Draw a horizontal scrollbar spanning ``w`` columns in the row at ``y``.
    ``left`` is the first visible column, ``content_w`` the visible width, and
    ``max_line`` the longest line. A thin convenience wrapper that computes the
    thumb position/ratio and defers to the ``draw_scrollbar`` primitive (which
    renders the bar at the vertical bar's thickness, centered in the row).

    The viewer's surface (``popup_bg``) is passed so the half-block bar's upper
    half blends with the client area on a character grid."""
    ratio = min(1.0, content_w / max_line) if max_line > 0 else 1.0
    denom = max_line - content_w
    pos = max(0.0, min(1.0, left / denom)) if denom > 0 else 0.0
    surface = _content_bg(ctx.theme)
    ctx.draw_scrollbar(x, y, w, pos, ratio, orientation="horizontal", surface=surface)


def _word_span(pos, lines):
    """The (start, end) positions of the word under ``pos`` — the maximal run of
    one character class on that source line (:func:`puikit.text.word_bounds`),
    the unit a double-click grabs. Character space (monospace), matching the
    viewer's ``len(line)`` column math."""
    line, col = pos
    chars = list(lines[line]) if 0 <= line < len(lines) else []
    start, end = word_bounds(chars, col)
    return (line, start), (line, end)


def _line_span(pos, lines):
    """The (start, end) positions spanning the whole source line under ``pos``."""
    line = pos[0]
    n = len(lines[line]) if 0 <= line < len(lines) else 0
    return (line, 0), (line, n)


class _RawTextSelection:
    """Read-only text selection for the raw text view, over source lines as
    ``(line, col)`` character positions (monospace, so a column is a character).

    The read-only counterpart to PuiKit's ``SelectableText`` mixin, kept here
    because the viewer scrolls (vertical + horizontal) and draws its own gutter,
    so selection can't ride the mixin's uniform-pitch-from-y=0 model. A press
    seeds the anchor and escalates caret -> word -> line by repeat count; a drag
    extends, growing by whole words/lines after a double/triple click. Copy is
    plain text (the raw source), so no rich representation is produced here."""

    def __init__(self):
        self.anchor: tuple[int, int] | None = None  # fixed end
        self.cursor: tuple[int, int] | None = None  # moving end (drag)
        self._granularity = 1                       # 1 caret / 2 word / 3 line
        self._base: tuple[tuple[int, int], tuple[int, int]] | None = None
        self._clicks: MultiClickTracker = MultiClickTracker()
        self.pressed = False

    def range(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        a, b = self.anchor, self.cursor
        if a is None or b is None or a == b:
            return None
        return (a, b) if a <= b else (b, a)

    def clear(self) -> None:
        self.anchor = self.cursor = self._base = None
        self.pressed = False

    def press(self, pos, lines, shift: bool) -> None:
        self.pressed = True
        count = self._clicks.press(pos)
        self._granularity = (count - 1) % 3 + 1
        if self._granularity == 2:
            self._base = _word_span(pos, lines)
            self.anchor, self.cursor = self._base
        elif self._granularity == 3:
            self._base = _line_span(pos, lines)
            self.anchor, self.cursor = self._base
        elif shift and self.anchor is not None:
            self._base = None
            self.cursor = pos  # shift+press extends from the existing anchor
        else:
            self._base = None
            self.anchor = pos  # a plain press starts a fresh selection here
            self.cursor = pos

    def drag(self, pos, lines) -> None:
        if not self.pressed:
            return
        self._clicks.note_drag()
        if self.anchor is None:
            self.anchor = pos
        if self._base is None:
            self.cursor = pos
            return
        b0, b1 = self._base
        p0, p1 = _word_span(pos, lines) if self._granularity == 2 else _line_span(pos, lines)
        self.anchor = min(b0, p0)
        self.cursor = max(b1, p1)

    def release(self) -> None:
        self.pressed = False

    def select_all(self, lines) -> None:
        if not lines:
            return
        self.anchor = (0, 0)
        self.cursor = (len(lines) - 1, len(lines[-1]))
        self._base = None
        self._granularity = 1

    def text(self, lines) -> str:
        """The selected text, source lines joined by newlines (empty when nothing
        is selected)."""
        r = self.range()
        if r is None:
            return ""
        (l0, c0), (l1, c1) = r
        if l0 == l1:
            return lines[l0][c0:c1]
        parts = [lines[l0][c0:]]
        parts += [lines[l] for l in range(l0 + 1, l1)]
        parts.append(lines[l1][:c1])
        return "\n".join(parts)


class _ScrollBody(Widget):
    """A clip region whose draw delegates to a callback. Lets a viewer render its
    scrolling rows at a *fractional* vertical offset (smooth GUI scroll): the
    partial top/bottom rows are trimmed by this child's clip instead of bleeding
    into the header/footer the parent drew."""

    def __init__(self, render):
        self._render = render

    def draw(self, ctx) -> None:
        self._render(ctx)


class TextViewer(Widget):
    """Full-window modal text viewer. Construct via :func:`show_text_viewer`."""

    focusable = True

    #: How this viewer's text arrives, when the active theme animates text at all
    #: (see puikit.textfx). ``scatter`` + ``flash``: characters land in random
    #: order, each striking its final column as a solid block for an instant
    #: before settling — a screenful materializing rather than being typed.
    #:
    #: Typing suits a *line* — a pane row, a status message — because the eye
    #: follows one reveal left to right. A full screen of text has no single
    #: place to follow, so a left-to-right reveal reads as a slow wipe; landing
    #: everywhere at once fills the page in the same time and gives the eye
    #: somewhere to settle immediately.
    #:
    #: Whether text animates at all stays with the theme: this is inert under
    #: every theme that does not opt in, and inherits the theme's duration.
    #:
    #: The pacing is overridden though, because a screenful is not a list of
    #: rows: the whole page materializes on one clock rather than cascading down
    #: it. With no stagger there is no cascade to bound, so the row cap has no
    #: purpose here either and every visible line takes part.
    text_effect = {"kind": "scatter", "flash": 0.10,
                   "stagger_ms": 0, "max_rows": 0}

    def __init__(self, path, *, syntax: dict | None = None, state_manager=None):
        self.path = path
        self.lines, self.is_error = _read_lines(path)
        self.highlighted = _highlight(self.lines, path, syntax)
        # Optional rich (formatted) renderer for this file type — Markdown for
        # *.md today (see xefm.viewer_registry). When a renderer exists,
        # ``toggle_view_mode`` swaps to it in place; the rich widget is built
        # lazily — on first switch, or on the first draw when we open straight
        # into rich — and cached, so each mode keeps its own scroll position
        # across toggles. ``mode`` is "text" | "rich" and starts at the mode last
        # chosen for this file *type* (persisted per extension via the state
        # manager, e.g. ".md" -> "rich"), so a preference for rendered Markdown
        # survives close/reopen and restarts (issue #217). It falls back to raw
        # "text" when the type has no renderer or nothing was stored.
        self._rich = rich_renderer_for(path)
        self._state_manager = state_manager
        self.mode = self._remembered_view_mode()
        self._rich_widget: Widget | None = None
        self._panel: Any = None
        self._child_z = 90  # z for the help overlay; raised above this viewer in show_
        self.top = 0.0       # first visible display row (vertical scroll)
        self.left = 0.0      # horizontal scroll, columns — float for smooth pan
        self.wrap = False
        self._view_h = 1
        self._content_w = 1
        self._max_line = max((len(line) for line in self.lines), default=0)
        # Wrap layout cache: keyed on content width, maps display row -> (line,
        # chunk) so wrapped rows virtualize without re-splitting every frame.
        self._wrap_w = -1
        self._row_map: list[tuple[int, int]] = []
        # Incremental search state. The ISearchBar overlay drives input; this holds
        # the live pattern (drives highlighting), the ordered match line indices,
        # and the current match. ``_search_origin_top`` is the pre-search scroll,
        # restored on cancel. ``_footer_rect`` is captured each draw so the bar can
        # be pinned exactly over the footer.
        self.pattern = ""
        self.matches: list[int] = []  # source line indices containing pattern
        self.match_pos = -1
        self._search_origin_top = 0.0
        self._footer_rect: tuple[float, float, float, float] | None = None
        self._isearch = ViewerISearch(
            recompute=self._search_recompute,
            navigate=self._search_step,
            status=self._search_status,
            accept=self._search_accept,
            cancel=self._search_cancel,
        )
        # Layout captured each draw, read by the clipped scroll body.
        self._body = _ScrollBody(self._draw_rows)
        self._gutter = 2
        self._content_x = 2
        self._bg = self._text_fg = self._muted = None
        # Read-only text selection over source lines (raw mode; rich mode's
        # embedded MarkdownView owns its own). ``_body_rect`` is the scrolling
        # body's layer-local (x, y, w, h), captured each draw so a mouse event
        # (which arrives in layer coords) maps to a (line, col) — and, in rich
        # mode, translates into the embedded widget's coordinate space.
        self._sel = _RawTextSelection()
        self._body_rect: tuple[float, float, float, float] | None = None

    # --- layout helpers ------------------------------------------------------

    def _gutter_w(self) -> int:
        return len(str(max(1, len(self.lines)))) + 1

    def _rebuild_wrap(self, content_w: int) -> None:
        if self.wrap and self._wrap_w == content_w:
            return
        self._wrap_w = content_w
        row_map: list[tuple[int, int]] = []
        for i, line in enumerate(self.lines):
            chunks = max(1, math.ceil(len(line) / content_w)) if content_w > 0 else 1
            for c in range(chunks):
                row_map.append((i, c))
        self._row_map = row_map

    def _total_rows(self) -> int:
        return len(self._row_map) if self.wrap else len(self.lines)

    def _clamp(self) -> None:
        max_top = max(0, self._total_rows() - self._view_h)
        self.top = max(0.0, min(self.top, float(max_top)))
        # No horizontal scroll while wrapping; otherwise clamp to the content.
        self.left = 0.0 if self.wrap else max(0.0, min(self.left, float(max(0, self._max_line - 1))))

    # --- search --------------------------------------------------------------

    def _search_target_is_rich(self) -> bool:
        """Whether an open search should drive the embedded rich renderer (rich
        mode with its widget built) instead of the raw-text match set. The rich
        widget owns its own search (match finding / scroll / highlight over its
        wrapped, proportional layout); this viewer only delegates."""
        return self.mode == "rich" and self._rich_widget is not None

    def _enter_search(self) -> None:
        """Open the incremental-search overlay pinned to the footer (the ``search``
        binding), in either view mode. Reuses the main file manager's ``ISearchBar``
        via :class:`ViewerISearch`; in rich mode the callbacks below drive the
        embedded renderer's own search instead of the raw-text match set."""
        if self._isearch.active or self._footer_rect is None:
            return
        if self._search_target_is_rich():
            self._rich_widget.search_begin()
        else:
            self._search_origin_top = self.top
            self._clear_search()
        self._isearch.open(self._panel, self._footer_rect, self._child_z)

    def _clear_search(self) -> None:
        """Drop the highlight chrome (pattern + match set)."""
        self.pattern = ""
        self.matches = []
        self.match_pos = -1

    def _search_recompute(self, pattern: str) -> None:
        """Live per-keystroke: recompute the matching lines (case-insensitive
        *contains*), highlight them, and jump to the nearest match at/after the
        current scroll position — or back to the pre-search view when nothing
        matches (mirrors the main file manager's isearch). In rich mode the
        embedded renderer runs the same search over its own layout."""
        if self._search_target_is_rich():
            self._rich_widget.search_set(pattern)
            self._render()
            return
        self.pattern = pattern
        pat = pattern.lower()
        self.matches = [i for i, line in enumerate(self.lines) if pat in line.lower()] \
            if pat else []
        if self.matches:
            cur = int(self.top)
            self.match_pos = next((k for k, m in enumerate(self.matches) if m >= cur), 0)
            self._scroll_to_line(self.matches[self.match_pos])
        else:
            self.match_pos = -1
            self.top = self._search_origin_top
            self._clamp()
        self._render()

    def _search_step(self, delta: int) -> None:
        """Up (``delta<0``) / Down (``delta>0``): walk to the previous / next
        match, wrapping at the ends. A no-op with no matches."""
        if self._search_target_is_rich():
            self._rich_widget.search_navigate(delta)
            self._render()
            return
        if not self.matches:
            return
        self.match_pos = (self.match_pos + delta) % len(self.matches)
        self._scroll_to_line(self.matches[self.match_pos])
        self._render()

    def _search_status(self) -> tuple[int, int]:
        """``(position, total)`` for the bar's counter: the 1-based index of the
        current match (0 when off any match) and the match count."""
        if self._search_target_is_rich():
            return self._rich_widget.search_status()
        n = len(self.matches)
        return (self.match_pos + 1 if (n and self.match_pos >= 0) else 0, n)

    def _search_accept(self) -> None:
        """Enter: keep the current match's scroll position; clear the highlights."""
        if self._search_target_is_rich():
            self._rich_widget.search_accept()
            self._render()
            return
        self._clear_search()
        self._render()

    def _search_cancel(self) -> None:
        """Esc / outside click: restore the pre-search scroll and clear."""
        if self._search_target_is_rich():
            self._rich_widget.search_cancel()
            self._render()
            return
        self.top = self._search_origin_top
        self._clear_search()
        self._clamp()
        self._render()

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()

    def _scroll_to_line(self, line: int) -> None:
        if self.wrap:
            for row, (src, chunk) in enumerate(self._row_map):
                if src == line and chunk == 0:
                    self.top = float(row)
                    break
        else:
            self.top = float(line)
        self._clamp()

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        theme = ctx.theme
        wu, hu = ctx.size_units  # exact (sub-cell) extent — anchor chrome to it
        # Like the main window: the chrome surfaces fill the whole window, only
        # text and the scrolling body are inset (pad_x left/right, pad_y for the
        # header's top and the footer's bottom). Scroll is the only pointer event
        # and carries no position, so the geometry needs no un-insetting.
        pad_x, pad_y = viewer_pad(ctx)
        bg = _content_bg(theme)  # sit on XeFM's own pane background, not popup_bg
        # Over an animated / image background the page fill is dropped entirely so
        # the scene reads at full strength — the file panes it replaces do the same
        # (``reveal_mode="transparent"``), and painting it here would dim the scene to
        # the theme's surface opacity, so the animation faded the moment a viewer
        # opened. ``bg`` still describes the surface the chrome and text sit on (the
        # draw context carries it for inheritance / auto-ink), it just isn't painted.
        if not ctx.wallpaper:
            ctx.fill_rect(0, 0, wu, hu, Style(bg=bg))

        text_fg = theme.text if theme is not None else (212, 212, 212)
        muted = theme.muted_text if theme is not None else (150, 150, 150)
        accent = theme.accent if theme is not None else (0, 122, 204)

        # Header — a distinct 'header' surface band across the top (reaching the
        # top edge, like the main window's pane headers), with the text inset from
        # the top/left/right.
        head_h = 1.0 + pad_y
        header_bg = _header_bg(theme)
        ctx.fill_rect(0, 0, wu, head_h, Style(bg=header_bg))
        total = len(self.lines)
        pos = int(self.top) + 1
        iw = max(1.0, wu - 2 * pad_x)            # content width inside the l/r pad
        header = f" {self.path.name}  ({total} lines)"
        ctx.draw_text(pad_x, pad_y, elide(header, iw, where="end", measure=ctx.measure_text),
                      Style(fg=accent, bg=header_bg, attr=TextAttribute.BOLD))
        # The right-aligned tag names the current view: the rendered renderer's
        # name in rich mode, the line position (+ WRAP) in raw text mode.
        if self.mode == "rich" and self._rich_widget is not None:
            info = f"{self._rich.name} "
        else:
            info = f"{pos}/{total}  {'WRAP' if self.wrap else ''} "
        ctx.draw_text(max(pad_x, wu - pad_x - len(info)), pad_y, info, Style(fg=muted, bg=header_bg))

        self._bg, self._text_fg, self._muted = bg, text_fg, muted
        # Rich (formatted) mode: the embedded renderer owns the whole body — it
        # draws and scrolls itself, with its own scrollbar — so the plain gutter,
        # h-scrollbar and row layout are skipped entirely. When we open straight
        # into a *remembered* rich mode the widget is built here on the first
        # frame, now that the content colors are known; if the source can't be
        # rendered we quietly drop back to raw for this file.
        if self.mode == "rich" and self._rich_widget is None and not self._ensure_rich_widget():
            self.mode = "text"
        if self.mode == "rich" and self._rich_widget is not None:
            self._draw_rich(ctx, wu, hu, pad_x, pad_y, iw, head_h)
            return

        gutter_w = self._gutter_w()
        self._gutter = gutter_w
        self._content_x = gutter_w
        self._content_w = max(1, int(iw) - gutter_w - 1)
        # Fractional visible width for the h-scrollbar thumb (columns can be
        # sub-cell); text still lays out on the whole-column ``_content_w``.
        content_wf = max(1.0, iw - gutter_w - 1)
        # The footer takes one row plus its bottom pad (its status surface reaches
        # the bottom edge). A horizontal scrollbar (no-wrap only) steals a row when
        # a line overruns the width. (``head_h`` was set with the header above.)
        fy = hu - 1.0 - pad_y                     # footer text row (surface below)
        show_hbar = not self.wrap and self._max_line > self._content_w
        hbar_y = fy - 1.0                          # h-scrollbar, just above footer
        body_h = (hbar_y if show_hbar else fy) - head_h
        self._view_h = max(1, int(body_h))
        if self.wrap:
            self._rebuild_wrap(self._content_w)
        self._clamp()

        # Scrolling rows live in a clipped child, inset by the l/r pad and sitting
        # below the header; a fractional self.top renders partial top/bottom rows.
        # Its layer-local rect is kept so a mouse event maps to a (line, col).
        self._body_rect = (pad_x, head_h, iw, body_h)
        ctx.draw_child(self._body, pad_x, head_h, iw, body_h)

        # Vertical scrollbar, at the content's right edge (inset by the l/r pad).
        total_rows = self._total_rows()
        if total_rows > self._view_h:
            ratio = min(1.0, body_h / total_rows)
            denom = total_rows - self._view_h
            sbpos = self.top / denom if denom > 0 else 0.0
            ctx.draw_scrollbar(wu - pad_x - 1, head_h, body_h,
                               max(0.0, min(1.0, sbpos)), ratio)

        # Horizontal scrollbar, in the row between the content and the footer.
        if show_hbar:
            draw_hscrollbar(ctx, pad_x + self._content_x, hbar_y, content_wf,
                            self.left, content_wf, self._max_line)

        # Footer status bar — full-width 'status' surface reaching the bottom edge,
        # its text inset by the l/r pad, matching the main window's StatusBar. Its
        # rect is captured so the ISearchBar overlay can pin exactly over it (the
        # bar covers this hint while a search is open, showing pattern + counter).
        self._footer_rect = (0.0, fy, wu, hu - fy)
        wrap_k = keys_label_for_action("toggle_wrap", "w")
        search_k = keys_label_for_action("search", "F")
        quit_k = keys_label_for_action("quit", "q")
        # When a rich renderer exists, advertise the toggle to it (e.g. "M markdown");
        # elide handles the longer hint on a narrow window.
        if self._rich is not None:
            view_k = keys_label_for_action("toggle_view_mode", "M")
            hint = (f" ↑↓ scroll · {wrap_k} wrap · {search_k} search · "
                    f"{view_k} {self._rich.name.lower()} · {quit_k}/Esc close ")
        else:
            hint = (f" ↑↓ scroll · ←→ pan · {wrap_k} wrap · {search_k} search · "
                    f"{quit_k}/Esc close ")
        draw_status_bar(ctx, fy, hint, pad_x=pad_x, bottom_pad=pad_y)

    def _draw_rich(self, ctx, wu, hu, pad_x, pad_y, iw, head_h) -> None:
        """Draw the rich (formatted) body: the embedded renderer fills the area
        between the header and footer, inset by the l/r pad like the raw body, and
        scrolls itself. Only the footer chrome (toggle-back hint) is XeFM's."""
        fy = hu - 1.0 - pad_y                     # footer text row (surface below)
        body_h = max(1.0, fy - head_h)
        # The embedded renderer's rect, so a mouse event forwarded to it (for its
        # own text selection / link clicks) translates into its coordinate space.
        self._body_rect = (pad_x, head_h, iw, body_h)
        ctx.draw_child(self._rich_widget, pad_x, head_h, iw, body_h)
        self._footer_rect = (0.0, fy, wu, hu - fy)
        view_k = keys_label_for_action("toggle_view_mode", "M")
        search_k = keys_label_for_action("search", "F")
        quit_k = keys_label_for_action("quit", "q")
        hint = (f" ↑↓ scroll · {search_k} search · {view_k} raw text · "
                f"{quit_k}/Esc close ")
        draw_status_bar(ctx, fy, hint, pad_x=pad_x, bottom_pad=pad_y)

    def _draw_rows(self, ctx) -> None:
        """Render the visible rows into the clipped body. ``self.top``'s fractional
        part shifts every row up by ``frac``, so the first/last rows are partial
        (smooth scroll); the body's clip trims them at the content edges."""
        first = int(self.top)
        frac = self.top - first
        # Two extra rows, not one: a fractional body height (the l/r-padded viewer
        # rarely lands on a whole cell) plus the fractional scroll offset can push
        # the visible span up to two rows past the whole count, so the partial
        # bottom row is always drawn to be clipped rather than vanishing early.
        for vis in range(self._view_h + 2):
            row = first + vis
            if row >= self._total_rows():
                break
            y = vis - frac
            if self.wrap:
                line_idx, chunk = self._row_map[row]
                col0 = float(chunk * self._content_w)
                show_no = chunk == 0
            else:
                line_idx, col0, show_no = row, self.left, True
            # Content first, then the gutter — the gutter fill masks the partial
            # left column that a fractional horizontal offset bleeds leftward.
            self._draw_line(ctx, y, line_idx, col0)
            ctx.fill_rect(0, y, self._content_x, 1.0, Style(bg=self._bg))
            if show_no:
                num = str(line_idx + 1).rjust(self._gutter - 1)
                ctx.draw_text(0, y, num, Style(fg=self._muted, bg=self._bg, font=MONO))

    def _draw_line(self, ctx, y, line_idx, col0) -> None:
        """Draw source line ``line_idx`` showing columns [col0, col0+content_w).
        ``col0`` may be fractional: the view shifts left by its fractional part
        (``xfrac``) for smooth horizontal scroll; the gutter (drawn after) masks
        the left bleed and the clip trims the right."""
        content_x, text_fg, bg = self._content_x, self._text_fg, self._bg
        col0_int = int(col0)
        xfrac = col0 - col0_int
        # Two extra columns: a fractional visible width plus the fractional pan
        # offset can push the visible span up to two columns past the whole count,
        # so the partial right-edge column is drawn to be clipped, not dropped early.
        window_end = col0_int + self._content_w + 2
        col = 0
        for text, fg in self.highlighted[line_idx]:
            seg_end = col + len(text)
            vis_start = max(col, col0_int)
            vis_end = min(seg_end, window_end)
            if vis_end > vis_start:
                sub = text[vis_start - col: vis_end - col]
                style_fg = _ERROR_FG if self.is_error else (fg if fg is not None else text_fg)
                # The syntax palette is tuned for a dark background, so on a dark
                # theme a real syntax color is kept exact (ink=False) and reads as
                # designed — recessive comments and all. On a light theme that same
                # palette would be unreadable, so auto-ink re-tones each token
                # (hue preserved, darkened to the light surface). The error color
                # and the uncolored fallback are always auto-inked.
                ctx.draw_text(content_x + (vis_start - col0_int) - xfrac, y, sub,
                              Style(fg=style_fg, bg=bg, font=MONO),
                              ink=self.is_error or fg is None or _is_light(bg))
            col = seg_end
            if col >= window_end:
                break
        # Overlay search highlights, then the text selection, for this window.
        if self.pattern:
            self._draw_matches(ctx, y, line_idx, col0_int, xfrac, window_end, content_x, text_fg)
        self._draw_selection(ctx, y, line_idx, col0_int, xfrac, window_end, content_x, text_fg)

    def _draw_selection(self, ctx, y, line_idx, col0_int, xfrac, window_end, content_x, text_fg) -> None:
        """Overlay the selection highlight on this display row's visible column
        window: the selected span of ``line_idx`` clipped to [col0_int,
        window_end), repainted over the theme's text-selection background (like
        :meth:`_draw_matches`, so a styled token flattens to a legible fg under
        the tint). The modal viewer is the active layer, so the active-selection
        color is used unconditionally."""
        r = self._sel.range()
        if r is None:
            return
        (l0, c0), (l1, c1) = r
        if not l0 <= line_idx <= l1:
            return
        line = self.lines[line_idx]
        # An intermediate line of a multi-line selection is selected end to end;
        # the first/last line only from/through the caret column.
        sel_start = c0 if line_idx == l0 else 0
        sel_end = c1 if line_idx == l1 else len(line)
        vis_start = max(sel_start, col0_int)
        vis_end = min(sel_end, window_end)
        if vis_end <= vis_start:
            return
        theme = ctx.theme
        sel_bg = theme.text_selection_bg if theme is not None else (38, 79, 120)
        sub = line[vis_start:vis_end]
        ctx.draw_text(content_x + (vis_start - col0_int) - xfrac, y, sub,
                      Style(fg=text_fg, bg=sel_bg, font=MONO))

    def _draw_matches(self, ctx, y, line_idx, col0_int, xfrac, window_end, content_x, text_fg) -> None:
        plain = self.lines[line_idx].lower()
        pat = self.pattern.lower()
        if not pat:
            return
        is_current = self.match_pos >= 0 and self.matches[self.match_pos] == line_idx
        start = 0
        while True:
            hit = plain.find(pat, start)
            if hit < 0:
                break
            s, e = hit, hit + len(pat)
            start = e
            vis_start = max(s, col0_int)
            vis_end = min(e, window_end)
            if vis_end <= vis_start:
                continue
            sub = self.lines[line_idx][vis_start:vis_end]
            hl_bg = _match_bg(self._bg, is_current)
            ctx.draw_text(content_x + (vis_start - col0_int) - xfrac, y, sub,
                          Style(fg=text_fg, bg=hl_bg, font=MONO))

    # --- events --------------------------------------------------------------

    def _close(self) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()

    def _ensure_rich_widget(self) -> bool:
        """Build (once) and cache this file's rich renderer widget on the viewer's
        current content surface, returning whether a rich widget is available.
        ``False`` when the type has no renderer or the source can't be read as
        text — the caller then stays in (or falls back to) raw text mode. Uses the
        content colors captured by the last :meth:`draw`, so the rendered document
        sits on the same surface as the raw view."""
        if self._rich is None:
            return False
        if self._rich_widget is not None:
            return True
        source = _read_source(self.path)
        if source is None:
            logger.warning(f"Cannot render {self.path.name}: unreadable as text")
            return False
        style = Style(fg=self._text_fg or (212, 212, 212), bg=self._bg)
        # A renderer may reject malformed input (an unparseable .json / .csv). Keep
        # the viewer in raw text mode on failure rather than letting the toggle
        # crash — raw still renders the file fine (pygments-highlighted).
        try:
            self._rich_widget = self._rich.build(source, style=style)
        except Exception as e:
            logger.warning(f"Cannot render {self.path.name} as {self._rich.name}: {e}")
            return False
        return True

    def _view_mode_state_key(self) -> str | None:
        """State-manager key for this file type's remembered view mode, or
        ``None`` when persistence doesn't apply — no state manager, or a type with
        no rich renderer (nothing to remember)."""
        if self._state_manager is None or self._rich is None:
            return None
        return _VIEW_MODE_STATE_PREFIX + self.path.suffix.lower()

    def _remembered_view_mode(self) -> str:
        """The persisted view mode ("rich" | "text") for this file's type,
        defaulting to raw "text" when nothing is stored or persistence doesn't
        apply. Read once at construction to pick the opening mode (issue #217)."""
        key = self._view_mode_state_key()
        if key is None:
            return "text"
        return "rich" if self._state_manager.get_state(key) == "rich" else "text"

    def _remember_view_mode(self) -> None:
        """Persist the current view mode for this file's type, so files of the
        same type reopen the same way (issue #217)."""
        key = self._view_mode_state_key()
        if key is not None:
            self._state_manager.set_state(key, self.mode)

    def _toggle_view_mode(self) -> None:
        """Switch between the raw text view and this file type's rich renderer
        (the ``toggle_view_mode`` action) and remember the choice for the type, so
        same-type files reopen the same way (issue #217). A no-op for a type with
        no registered renderer. The rich widget is built once, from the file
        source, and cached — so each mode keeps its own scroll position across
        toggles. If the source can't be read as text, the switch is refused, the
        viewer stays raw, and nothing is persisted."""
        if self._rich is None:
            return
        if self.mode == "rich":
            self.mode = "text"
        elif self._ensure_rich_widget():
            self.mode = "rich"
        else:
            return  # unreadable as text; stay raw, don't persist
        self._remember_view_mode()

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.MOUSE_SCROLL:
            # Rich mode: the embedded renderer owns scrolling (its own offset).
            if self.mode == "rich" and self._rich_widget is not None:
                self._rich_widget.handle_event(event)
                return True
            uy = event.hints.get("scroll_units")
            self.top -= float(uy) if uy is not None else float(event.scroll)
            ux = event.hints.get("scroll_units_x")  # precise horizontal swipe
            if ux is not None and not self.wrap:
                self.left -= float(ux)
            self._clamp()
            return True
        # Mouse press / drag / release / click drive text selection. In rich mode
        # they are forwarded to the embedded renderer (its own selection + link
        # clicks); in raw mode this viewer owns the (line, col) selection.
        if event.type in (EventType.MOUSE_DOWN, EventType.MOUSE_UP,
                          EventType.MOUSE_DRAG, EventType.MOUSE_CLICK):
            if self.mode == "rich" and self._rich_widget is not None:
                self._forward_mouse_to_rich(event)
            else:
                self._selection_mouse(event)
            return True
        if event.type is not EventType.KEY:
            return True  # modal: swallow other non-key events
        key = event.key
        # Config-driven keys (quit / help / search / wrap) resolve through
        # KEY_BINDINGS by name, so they honour the user's rebinds; each action is
        # matched independently, which lets ``toggle_wrap`` share ``W`` with the
        # file manager's ``compare_selection``. Esc is the universal modal dismiss;
        # the scroll keys below are viewer-local. While a search is open the
        # ISearchBar is the top layer and receives keys, so this isn't reached.
        # Quit / help / the view-mode toggle apply in both raw and rich modes.
        if key == "escape" or is_action_for_event(event, "quit"):
            self._close()
            return True
        if is_action_for_event(event, "help"):
            self._show_help()
            return True
        if self._view_mode_pressed(event):
            self._toggle_view_mode()
            return True
        # Incremental search applies in both modes: open it before the rich
        # renderer would swallow the key (it has no search of its own — this
        # viewer drives the shared bar and delegates to the renderer's match set).
        if is_action_for_event(event, "search"):
            self._enter_search()
            return True
        # Rich mode: the embedded renderer owns navigation (arrows / page / home /
        # end / in-document link jumps); forward and let it repaint. Line-wrap is
        # raw-text-only, so it doesn't apply here.
        if self.mode == "rich" and self._rich_widget is not None:
            self._rich_widget.handle_event(event)
            return True
        # From here on it is raw text mode. Cmd/Ctrl+C copies the selected text
        # (plain, the raw source); Cmd/Ctrl+A selects the whole document.
        if event.modifiers & {"ctrl", "cmd"} and key in ("c", "a"):
            if key == "c":
                self._copy_selection()
            else:
                self._sel.select_all(self.lines)
            return True
        if self._wrap_pressed(event):
            self.wrap = not self.wrap
            self.left = 0.0
            self._wrap_w = -1
        elif key == "down":
            self.top += 1
        elif key == "up":
            self.top -= 1
        elif key == "pagedown":
            self.top += self._view_h
        elif key == "pageup":
            self.top -= self._view_h
        elif key == "home":
            self.top = 0.0
        elif key == "end":
            self.top = float(max(0, self._total_rows() - self._view_h))
        elif key == "right" and not self.wrap:
            self.left += 4
        elif key == "left" and not self.wrap:
            self.left = max(0.0, self.left - 4)
        self._clamp()
        return True

    # --- text selection (raw mode) / mouse forwarding (rich mode) -------------

    def _in_body(self, ex: float, ey: float) -> bool:
        """Whether layer-local ``(ex, ey)`` falls within the scrolling body — so a
        press that lands on the header / footer / a scrollbar starts no selection."""
        if self._body_rect is None:
            return False
        bx, by, bw, bh = self._body_rect
        return bx <= ex < bx + bw and by <= ey < by + bh

    def _pos_at(self, ex: float, ey: float) -> tuple[int, int]:
        """Layer-local ``(ex, ey)`` to a ``(line, col)`` selection position, via
        the body rect and the current vertical (``top``) / horizontal (``left``)
        scroll. Columns are characters (monospace); the x is rounded to the
        nearest character boundary and clamped to the line."""
        if self._body_rect is None or not self.lines:
            return (0, 0)
        bx0, by0, _, _ = self._body_rect
        by = max(0.0, ey - by0)
        disp = int(self.top + by)
        disp = max(0, min(disp, max(0, self._total_rows() - 1)))
        if self.wrap and self._row_map:
            line_idx, chunk = self._row_map[disp]
            col_off = float(chunk * self._content_w)
        else:
            line_idx = disp
            col_off = self.left
        line_idx = max(0, min(line_idx, len(self.lines) - 1))
        line = self.lines[line_idx]
        char_index = col_off + (ex - bx0 - self._content_x)
        col = max(0, min(int(char_index + 0.5), len(line)))
        return (line_idx, col)

    def _selection_mouse(self, event: Event) -> None:
        """Raw-mode selection from a press / drag / release (a click is inert —
        there are no links in raw text). A press outside the body clears the
        selection; inside, it seeds/extends per the multi-click gesture."""
        ex, ey = event.x, event.y
        if event.type is EventType.MOUSE_CLICK:
            return
        if event.type is EventType.MOUSE_UP:
            self._sel.release()
            return
        if ex is None or ey is None:
            return
        if event.type is EventType.MOUSE_DOWN:
            if self._in_body(ex, ey):
                self._sel.press(self._pos_at(ex, ey), self.lines, "shift" in event.modifiers)
            else:
                self._sel.clear()
        elif event.type is EventType.MOUSE_DRAG:
            self._sel.drag(self._pos_at(ex, ey), self.lines)

    def _forward_mouse_to_rich(self, event: Event) -> None:
        """Forward a mouse event to the embedded rich widget in its own coords, so
        its text selection and link clicks work through this modal viewer."""
        if self._body_rect is None or self._rich_widget is None:
            return
        bx0, by0, _, _ = self._body_rect
        self._rich_widget.handle_event(event.translated(-bx0, -by0))

    def _copy_selection(self) -> None:
        """Put the raw-mode selection on the clipboard as plain text."""
        text = self._sel.text(self.lines)
        if text and self._panel is not None:
            self._panel.set_clipboard(text)

    def _wrap_pressed(self, event: Event) -> bool:
        """Whether ``event`` toggles line wrap — the ``toggle_wrap`` binding, with a
        literal ``w`` fallback for user configs predating that action (so wrap keeps
        working when KEY_BINDINGS has no ``toggle_wrap`` entry)."""
        if is_action_for_event(event, "toggle_wrap"):
            return True
        return not get_keys_for_action("toggle_wrap")[0] and event.char == "w"

    def _view_mode_pressed(self, event: Event) -> bool:
        """Whether ``event`` toggles the view mode — the ``toggle_view_mode``
        binding, with a literal ``m`` fallback for user configs predating that
        action (so the Markdown toggle works even when a user's ``KEY_BINDINGS``
        — merged from an older template — has no ``toggle_view_mode`` entry)."""
        if is_action_for_event(event, "toggle_view_mode"):
            return True
        return not get_keys_for_action("toggle_view_mode")[0] and event.char == "m"

    def _show_help(self) -> None:
        if self._panel is None:
            return
        rows = [
            ("↑ / ↓", "scroll line"),
            ("PgUp / PgDn", "scroll page"),
            ("Home / End", "top / bottom"),
            ("← / →", "scroll horizontally (no-wrap)"),
            (keys_label_for_action("toggle_wrap", "w"), "toggle line wrap"),
            (keys_label_for_action("search", "F"), "incremental search"),
            ("↑ / ↓ (in search)", "next / prev match"),
        ]
        # Only offer the view-mode toggle for a file type that has a rich renderer.
        if self._rich is not None:
            rows.append((keys_label_for_action("toggle_view_mode", "M"),
                         f"toggle {self._rich.name} / raw text"))
        rows += [
            (keys_label_for_action("help", "?"), "this help"),
            (keys_label_for_action("quit", "q") + " / Esc", "close"),
        ]
        show_markdown(self._panel, keys_markdown(rows),
                      title="Text Viewer — Keys", z=self._child_z)


def show_text_viewer(panel: Any, path, z: int = 80, state_manager=None) -> TextViewer:
    """Push a full-window modal :class:`TextViewer` over ``panel``. The ``reflow``
    callback re-derives the layer rect from the live window size each render, so
    the viewer follows terminal / window resizes. When a ``state_manager`` is
    given, the last view mode chosen for each file type is remembered through it,
    so e.g. Markdown files reopen rendered once you've toggled one (issue #217);
    without one the viewer just opens raw and persists nothing."""
    viewer = TextViewer(path, syntax=_syntax_palette(panel),
                        state_manager=state_manager)
    sw, sh = panel.backend.size_units
    viewer._panel = panel
    viewer._child_z = z + 10  # help overlay stacks above the viewer's own layer
    panel.push_layer(viewer, z=z, hints=viewer_layer_hints(sw, sh),
                     reflow=lambda sw, sh: Rect(0, 0, sw, sh))
    animate_open(panel, viewer, OPEN_MS_VIEWER)
    return viewer
