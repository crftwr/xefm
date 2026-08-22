"""DiffViewer — a modal side-by-side text diff for the PuiKit port.

The diff viewer: compares two text files
side by side using ``difflib``, line-by-line with character-level highlighting
within changed lines. Deletions, insertions, and replacements are tinted; the
matched/changed spans inside a replaced line are highlighted more strongly.

It reuses the text viewer's file reading and syntax highlighting
(:mod:`xefm.text_viewer`), so each side keeps its syntax colors with the diff
tint laid over them. Push it with :func:`show_diff_viewer`.

Config-driven keys resolve through the shared ``KEY_BINDINGS`` (honouring the
user's rebinds): the ``search`` binding opens the same ``ISearchBar`` overlay the
main file manager uses (matches highlighted on both sides, ``Up``/``Down`` walk
them); the ``edit_file`` binding launches the configured ``TEXT_DIFF`` tool on
the two files and re-reads them when it returns; ``help`` and ``quit`` do the
obvious. ↑/↓/PageUp/PageDown/Home/End scroll, ←/→ scroll horizontally, and
``n``/``N`` jump to the next/previous *change block* (viewer-local, independent
of search); Esc closes.
"""

from __future__ import annotations

import difflib
import shlex
import subprocess
from typing import Any

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.panel import Rect
from puikit.widgets import Splitter, show_message_box
from puikit.widgets.base import Widget

from xefm import migemo_search
from xefm.actions import DIFF_VIEWER as _CONTEXT
from xefm.config import (find_action_for_event, format_key_for_display,
                         get_config, get_keys_for_action)
from xefm.file_pane import CONTENT_PAD_CELLS  # same l/r content inset as the main panes
from xefm.dialog_geometry import OPEN_MS_VIEWER, animate_open
from xefm.isearch_bar import ViewerISearch, match_scroll_top
from xefm.text_dialog import keys_markdown, show_markdown
from xefm.text_viewer import (MONO, _ScrollBody, _content_bg, _header_bg, _highlight,
                             _is_light, _match_bg, _read_lines, _syntax_palette,
                             draw_hscrollbar, draw_status_bar, span_x,
                             viewer_layer_hints, viewer_pad)
from puikit.text import display_width

def _label(action: str, fallback: str = "") -> str:
    """Display label for ``action``'s keys **as this viewer resolves them** — in
    the ``diff_viewer`` context, so a scoped rebind (``'diff_viewer.quit'``) and
    the action's built-in defaults both show up, formatted for the UI
    (``DOWN`` -> ↓)."""
    keys, _ = get_keys_for_action(action, _CONTEXT)
    if not keys:
        return fallback
    return " / ".join(format_key_for_display(k) for k in keys)


def _pair(first: str, second: str) -> str:
    """One help row's label for two actions that read as a pair (``↑ / ↓``)."""
    return f"{_label(first)} / {_label(second)}"


#: Semantic diff hues. The whole-row tints and the stronger changed-character
#: tints are the theme's *content background* blended toward these, so a diff
#: band tracks the theme — a dark band on a dark theme, a pastel one on a light
#: theme — instead of a fixed dark color that reads wrong on the light themes.
_HUE_DEL = (180, 40, 40)       # red   (deleted / left-side change)
_HUE_INS = (40, 150, 50)       # green (inserted / right-side change)
_HUE_REPLACE = (150, 130, 40)  # amber (replaced line, both sides)
_EMPTY_HUE = (128, 128, 128)   # neutral fill for the empty side of an ins/del row
_ROW_TINT = 0.20               # whole-row band strength
_CHAR_TINT = 0.50              # changed-character span (stronger than the row)
_EMPTY_TINT = 0.08             # faint neutral, just off the content background


def _mix(a, b, t):
    """Linear RGB blend a→b by ``t`` (0..1)."""
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _diff_bgs(content):
    """Diff band backgrounds derived from the theme content background, so every
    band adapts to the active theme's polarity. ``content`` falls back to a dark
    surface when the theme reports none."""
    c = content or (30, 30, 38)
    return {
        "delete": _mix(c, _HUE_DEL, _ROW_TINT),
        "insert": _mix(c, _HUE_INS, _ROW_TINT),
        "replace": _mix(c, _HUE_REPLACE, _ROW_TINT),
        "char_del": _mix(c, _HUE_DEL, _CHAR_TINT),
        "char_ins": _mix(c, _HUE_INS, _CHAR_TINT),
        "empty": _mix(c, _EMPTY_HUE, _EMPTY_TINT),
    }


def _char_ranges(a: str, b: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Per-side character spans that differ between ``a`` and ``b``."""
    matcher = difflib.SequenceMatcher(None, a, b)
    ra: list[tuple[int, int]] = []
    rb: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            ra.append((i1, i2))
        if j2 > j1:
            rb.append((j1, j2))
    return ra, rb


def compute_diff(lines1: list[str], lines2: list[str]) -> tuple[list[dict], list[int]]:
    """Side-by-side diff of two line lists. Returns ``(rows, block_starts)``:
    one row dict per display line (``tag``, ``l1``/``l2`` text, ``n1``/``n2``
    line numbers or None, and ``cr1``/``cr2`` changed-char ranges), and the row
    index where each change block begins (for next/prev-change navigation)."""
    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    rows: list[dict] = []
    blocks: list[int] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"tag": "equal", "l1": lines1[i1 + k], "l2": lines2[j1 + k],
                             "n1": i1 + k + 1, "n2": j1 + k + 1, "cr1": None, "cr2": None})
            continue
        blocks.append(len(rows))
        if tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                has1, has2 = i1 + k < i2, j1 + k < j2
                l1 = lines1[i1 + k] if has1 else ""
                l2 = lines2[j1 + k] if has2 else ""
                cr1 = cr2 = None
                if has1 and has2 and l1 and l2:
                    cr1, cr2 = _char_ranges(l1, l2)
                rows.append({"tag": "replace", "l1": l1, "l2": l2,
                             "n1": (i1 + k + 1) if has1 else None,
                             "n2": (j1 + k + 1) if has2 else None, "cr1": cr1, "cr2": cr2})
        elif tag == "delete":
            for i in range(i1, i2):
                rows.append({"tag": "delete", "l1": lines1[i], "l2": "",
                             "n1": i + 1, "n2": None, "cr1": None, "cr2": None})
        elif tag == "insert":
            for j in range(j1, j2):
                rows.append({"tag": "insert", "l1": "", "l2": lines2[j],
                             "n1": None, "n2": j + 1, "cr1": None, "cr2": None})
    return rows, blocks


def _side_bg(row: dict, side: str, pal: dict) -> tuple[int, int, int] | None:
    """Whole-row tint for one side of a diff row (None for an unchanged line),
    picked from the theme-derived palette ``pal`` (see :func:`_diff_bgs`)."""
    tag = row["tag"]
    if tag == "equal":
        return None
    if tag == "replace":
        return pal["replace"]
    if tag == "delete":
        return pal["delete"] if side == "l" else pal["empty"]
    return pal["empty"] if side == "l" else pal["insert"]  # insert


class _DiffPane(Widget):
    """One side of the diff — its filename header, gutter, and scrolling content.
    Reads shared scroll state (``top``/``left``/``_view_h``) from the parent
    :class:`DiffViewer`, so the two sides stay row-aligned and pan together; only
    the split *width* differs (the Splitter owns that). The scrolling rows live
    in a clipped child for smooth fractional scroll on both axes."""

    def __init__(self, viewer: "DiffViewer", side: str):
        self.v = viewer
        self.side = side                 # "l" (left/old) or "r" (right/new)
        self._body = _ScrollBody(self._draw_rows)
        self._w = 1
        self._gutter = 2
        self._content_x = 2
        self._content_w = 1
        self._pad = 0.0                  # l/r content inset, set per draw
        self._bg = self._text_fg = self._muted = None

    def draw(self, ctx) -> None:
        v = self.v
        theme = ctx.theme
        w = ctx.width
        bg = _content_bg(theme)  # sit on XeFM's own pane background, not popup_bg
        accent = theme.accent if theme is not None else (0, 122, 204)
        self._bg = bg
        # Diff band tints derived from the current theme's content background, so
        # the viewer isn't a fixed dark palette on the light themes.
        self._diffpal = _diff_bgs(bg)
        self._text_fg = theme.text if theme is not None else (212, 212, 212)
        self._muted = theme.muted_text if theme is not None else (150, 150, 150)
        # Inset the gutter + content from both pane edges by the same amount the
        # main file panes use (CONTENT_PAD_CELLS), so the rows breathe rather than
        # butting the pane edge — most visibly the shared splitter between them.
        # Zero on a character grid (no sub-cell), like the main panes.
        mx = CONTENT_PAD_CELLS if ctx.vector_shapes else 0.0
        self._pad = mx
        self._gutter = v._gutter_w()
        self._content_x = mx + self._gutter
        self._w = w
        # The right pane leaves a column for the shared scrollbar at the edge.
        reserve = 1 if self.side == "r" else 0
        self._content_w = max(1, int(w - self._gutter - reserve - 2 * mx))

        # The filename sits on the parent's 'header' surface band (drawn full-width
        # in DiffViewer.draw), so use that bg rather than the content background.
        name = v.path1.name if self.side == "l" else v.path2.name
        ctx.draw_text(0, 0, f" {name}"[:w],
                      Style(fg=accent, bg=_header_bg(theme), attr=TextAttribute.BOLD))
        # Content below the filename header, clipped for smooth scroll. Uses the
        # parent's fractional body height so the last row reaches the footer flush
        # with the pixel bottom (no whole-cell grid-snap gap).
        ctx.draw_child(self._body, 0, 1, w, v._body_h)

    def _draw_rows(self, ctx) -> None:
        v = self.v
        side = self.side
        bg, muted, text_fg = self._bg, self._muted, self._text_fg
        pal = self._diffpal
        content_x, content_w = self._content_x, self._content_w
        highlighted = v.hl1 if side == "l" else v.hl2
        char_bg = pal["char_del"] if side == "l" else pal["char_ins"]
        first = int(v.top)
        vfrac = v.top - first
        col0_int = int(v.left)
        xfrac = v.left - col0_int
        # Two extra columns: a fractional visible width plus the fractional pan
        # offset can push the visible span up to two columns past the whole count,
        # so the partial right-edge column is drawn to be clipped, not dropped early.
        window_end = col0_int + content_w + 2
        # Two extra rows: a fractional body height plus the fractional scroll
        # offset can push the visible span up to two rows past the whole count,
        # so the partial bottom row is drawn to be clipped, not dropped early.
        for vis in range(v._view_h + 2):
            ri = first + vis
            if ri >= len(v.rows):
                break
            y = vis - vfrac
            row = v.rows[ri]
            lineno = row["n1"] if side == "l" else row["n2"]
            plain = row["l1"] if side == "l" else row["l2"]
            cranges = row["cr1"] if side == "l" else row["cr2"]
            side_bg = _side_bg(row, side, pal)
            row_bg = side_bg if side_bg is not None else bg
            if side_bg is not None:
                ctx.fill_rect(0, y, self._w, 1.0, Style(bg=side_bg))
            if lineno is not None:
                segs = highlighted[lineno - 1] if 0 <= lineno - 1 < len(highlighted) else [(plain, None)]
                col = 0
                x_disp = 0.0  # display cols drawn from col0_int (CJK spans two)
                for text, fg in segs:
                    seg_end = col + len(text)
                    vis_start = max(col, col0_int)
                    vis_end = min(seg_end, window_end)
                    if vis_end > vis_start:
                        sub = text[vis_start - col: vis_end - col]
                        # A syntax-colored span keeps its exact (dark-tuned) palette
                        # on a dark theme; on a light theme auto-ink re-tones it to
                        # the light surface. The uncolored fallback is always inked.
                        ctx.draw_text(content_x + x_disp - xfrac, y, sub,
                                      Style(fg=fg if fg is not None else text_fg, bg=row_bg, font=MONO),
                                      ink=fg is None or _is_light(bg))
                        x_disp += display_width(sub)
                    col = seg_end
                    if col >= window_end:
                        break
                for s, e in (cranges or []):
                    vs, ve = max(s, col0_int), min(e, window_end)
                    if ve > vs:
                        ctx.draw_text(content_x + span_x(plain, col0_int, vs) - xfrac, y, plain[vs:ve],
                                      Style(fg=text_fg, bg=char_bg, font=MONO))
                # Incremental-search highlights overlay the diff tint for this side.
                if v.search_pattern:
                    self._draw_search(ctx, y, ri, plain, col0_int, xfrac,
                                      window_end, content_x, text_fg)
            # Gutter (after content) masks the left horizontal bleed, then numbers
            # (inset by the l/r pad so they don't butt the pane edge / splitter).
            ctx.fill_rect(0, y, content_x, 1.0, Style(bg=row_bg))
            if lineno is not None:
                ctx.draw_text(self._pad, y, str(lineno).rjust(self._gutter - 1),
                              Style(fg=muted, bg=row_bg, font=MONO))

    def _draw_search(self, ctx, y, ri, plain, col0_int, xfrac,
                     window_end, content_x, text_fg) -> None:
        """Overlay incremental-search highlights on this side's visible line —
        every occurrence of the pattern, with the current match row emphasised
        (firmer tint, like the text viewer)."""
        v = self.v
        pat = v.search_pattern.lower()
        if not pat:
            return
        low = plain.lower()
        is_current = bool(v.search_matches and v.search_pos >= 0
                          and v.search_matches[v.search_pos] == ri)
        # Literal occurrences, then Migemo hits (#302); overlapping spans just
        # repaint the same cells with the same tint.
        spans = []
        start = 0
        while True:
            hit = low.find(pat, start)
            if hit < 0:
                break
            spans.append((hit, hit + len(pat)))
            start = hit + len(pat)
        migemo_spans = migemo_search.find_spans(v.search_pattern, plain)
        if migemo_spans:
            spans.extend(migemo_spans)
        for s, e in spans:
            vs, ve = max(s, col0_int), min(e, window_end)
            if ve > vs:
                ctx.draw_text(content_x + span_x(plain, col0_int, vs) - xfrac, y, plain[vs:ve],
                              Style(fg=text_fg, bg=_match_bg(self._bg, is_current), font=MONO))


class DiffViewer(Widget):
    """Full-window modal side-by-side diff. Two :class:`_DiffPane` children sit in
    a draggable :class:`Splitter`; a shared scrollbar and footer are chrome.
    Construct via :func:`show_diff_viewer`."""

    focusable = True

    _MOUSE = frozenset({
        EventType.MOUSE_DOWN, EventType.MOUSE_UP,
        EventType.MOUSE_CLICK, EventType.MOUSE_DRAG,
    })

    def __init__(self, path1, path2, *, syntax: dict | None = None, on_edited=None):
        self.path1, self.path2 = path1, path2
        # ``syntax`` is kept so a reload after the external TEXT_DIFF tool can
        # re-highlight; ``on_edited`` tells the opener the files may have changed.
        self._syntax = syntax
        self._on_edited = on_edited
        self.lines1, _, _ = _read_lines(path1)
        self.lines2, _, _ = _read_lines(path2)
        self.hl1 = _highlight(self.lines1, path1, syntax)
        self.hl2 = _highlight(self.lines2, path2, syntax)
        self.rows, self.blocks = compute_diff(self.lines1, self.lines2)
        self._panel: Any = None
        # Chrome surfaces fill the window; text and the panes inset (see draw).
        # _pad is cached to translate pointer events into the inset splitter.
        self._pad = (0.0, 0.0)
        #: Action handlers, built on first key (see _handlers_table).
        self._handlers: dict | None = None
        self._child_z = 90  # z for the help overlay; raised above this viewer in show_
        self.top = 0.0
        self.left = 0.0
        self._view_h = 1
        self._body_h = 1.0   # fractional body height (panes read it, pixel-flush)
        self._max_line = max((len(line) for line in self.lines1 + self.lines2), default=0)
        self.left_pane = _DiffPane(self, "l")
        self.right_pane = _DiffPane(self, "r")
        self.splitter = Splitter(self.left_pane, self.right_pane,
                                 orientation="horizontal", fraction=0.5,
                                 min_first=10, min_second=10)
        # Incremental search state (the ``search`` binding). A match is a display
        # row whose left or right line contains the pattern; both panes highlight
        # occurrences and the current match row is emphasised. ``_search_origin_top``
        # is the pre-search scroll (restored on cancel); ``_footer_rect`` is
        # captured each draw so the ISearchBar can pin over the footer.
        self.search_pattern = ""
        self.search_matches: list[int] = []   # display-row indices with a hit
        self.search_pos = -1
        self._search_origin_top = 0.0
        self._footer_rect: tuple[float, float, float, float] | None = None
        self._isearch = ViewerISearch(
            recompute=self._search_recompute,
            navigate=self._search_step,
            status=self._search_status,
            accept=self._search_accept,
            cancel=self._search_cancel,
        )

    def _gutter_w(self) -> int:
        return len(str(max(1, len(self.lines1), len(self.lines2)))) + 1

    def _clamp(self) -> None:
        self.top = max(0.0, min(self.top, float(max(0, len(self.rows) - self._view_h))))
        self.left = max(0.0, min(self.left, float(max(0, self._max_line - 1))))

    def _pane_columns(self, wu: float, gutter: int, mx: float = 0.0) -> tuple[float, float, float, float]:
        """``(left_x, left_content_w, right_x, right_content_w)`` for the two panes'
        content regions (after the gutter; the right side reserves the scrollbar
        column). ``mx`` is the per-edge content inset the panes apply, so the
        h-scrollbars and the overflow test track where the rows actually sit. Uses
        the splitter's actual rects once it has drawn, falling back to the fraction
        before the first draw. Widths are kept *fractional* so the h-scrollbar thumb
        reflects the exact sub-cell viewport."""
        fr, sr = self.splitter._first_rect, self.splitter._second_rect
        if fr.w > 0:
            lx, lw = fr.x, fr.w
            rx, rw = sr.x, sr.w
        else:  # before the first splitter draw
            frac = self.splitter.fraction
            lx, lw = 0.0, frac * wu
            rx, rw = lw, wu - lw
        return (lx + gutter + mx, max(1.0, lw - gutter - 2 * mx),
                rx + gutter + mx, max(1.0, rw - gutter - 1 - 2 * mx))

    def _step_block(self, delta: int) -> None:
        if not self.blocks:
            return
        cur = int(self.top)
        if delta > 0:
            nxt = next((b for b in self.blocks if b > cur), self.blocks[0])
        else:
            nxt = next((b for b in reversed(self.blocks) if b < cur), self.blocks[-1])
        self.top = float(nxt)
        self._clamp()

    # --- external edit -------------------------------------------------------

    def _notify(self, message: str) -> None:
        if self._panel is not None:
            show_message_box(self._panel, message, title="File Diff", icon="info",
                             z=self._child_z)

    def _reload(self) -> None:
        """Re-read both sides and recompute the highlights and diff (after the
        external tool returns), keeping the scroll clamped to the new rows."""
        self.lines1, _, _ = _read_lines(self.path1)
        self.lines2, _, _ = _read_lines(self.path2)
        self.hl1 = _highlight(self.lines1, self.path1, self._syntax)
        self.hl2 = _highlight(self.lines2, self.path2, self._syntax)
        self.rows, self.blocks = compute_diff(self.lines1, self.lines2)
        self._max_line = max((len(line) for line in self.lines1 + self.lines2), default=0)
        self._clear_search()
        self._clamp()

    def _edit_in_tool(self) -> None:
        """Launch the configured ``TEXT_DIFF`` tool (e.g. ``vimdiff`` / ``code
        --diff``) on the two compared files so the user can edit/merge them (the
        ``edit_file`` binding), handing the terminal over via the backend
        suspend/resume, then re-read both sides so the diff shows the result. A
        GUI tool returns immediately and the reload is a no-op. Local files
        only."""
        if "://" in str(self.path1) or "://" in str(self.path2):
            self._notify("Editing is only available for local files.")
            return
        tool = getattr(get_config(), "TEXT_DIFF", None)
        if not tool:
            self._notify("No TEXT_DIFF tool is configured.")
            return
        argv = (shlex.split(tool) if isinstance(tool, str) else list(tool))
        argv = argv + [str(self.path1), str(self.path2)]
        backend = getattr(self._panel, "backend", None)
        try:
            with backend.suspended():
                subprocess.run(argv)
        except FileNotFoundError:
            self._notify(f"Command not found: {argv[0]}")
            return
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Diff tool failed: {exc}")
            return
        self._reload()
        if self._on_edited is not None:
            self._on_edited()
        self._render()

    # --- search --------------------------------------------------------------

    def _enter_search(self) -> None:
        """Open the incremental-search overlay pinned to the footer (the ``search``
        binding), reusing the main file manager's ``ISearchBar`` via
        :class:`ViewerISearch`. Independent of ``n``/``N`` diff-block navigation."""
        if self._isearch.active or self._footer_rect is None:
            return
        self._search_origin_top = self.top
        self._clear_search()
        self._isearch.open(self._panel, self._footer_rect, self._child_z)

    def _clear_search(self) -> None:
        """Drop the highlight chrome (pattern + match set)."""
        self.search_pattern = ""
        self.search_matches = []
        self.search_pos = -1

    def _search_recompute(self, pattern: str) -> None:
        """Live per-keystroke: rows whose left or right line contains ``pattern``
        (case-insensitive, unioned with the Migemo regex so romaji finds
        Japanese, #302) become the match set; jump to the nearest match at/after
        the current scroll, or restore the pre-search view when nothing matches."""
        self.search_pattern = pattern
        pat = pattern.lower()
        # Migemo matches raw lines, not an NFC form: _draw_search indexes
        # highlight spans into the line as drawn (see migemo_search.find_spans).
        regex = migemo_search.get_regex(pattern)
        self.search_matches = [
            i for i, r in enumerate(self.rows)
            if pat in r["l1"].lower() or pat in r["l2"].lower()
            or (regex is not None
                and (migemo_search.has_hit(regex, r["l1"])
                     or migemo_search.has_hit(regex, r["l2"])))
        ] if pat else []
        if self.search_matches:
            cur = int(self.top)
            self.search_pos = next(
                (k for k, m in enumerate(self.search_matches) if m >= cur), 0)
            # Keep context rows around the match (#321), same as the text viewer.
            self.top = match_scroll_top(
                self.top, self.search_matches[self.search_pos], self._view_h)
        else:
            self.search_pos = -1
            self.top = self._search_origin_top
        self._clamp()
        self._render()

    def _search_step(self, delta: int) -> None:
        """Up (``delta<0``) / Down (``delta>0``): walk to the previous / next match
        row, wrapping at the ends. A no-op with no matches."""
        if not self.search_matches:
            return
        self.search_pos = (self.search_pos + delta) % len(self.search_matches)
        self.top = match_scroll_top(
            self.top, self.search_matches[self.search_pos], self._view_h)
        self._clamp()
        self._render()

    def _search_status(self) -> tuple[int, int]:
        """``(position, total)`` for the bar's counter."""
        n = len(self.search_matches)
        return (self.search_pos + 1 if (n and self.search_pos >= 0) else 0, n)

    def _search_accept(self) -> None:
        """Enter: keep the current match's scroll; clear the highlights."""
        self._clear_search()
        self._render()

    def _search_cancel(self) -> None:
        """Esc / outside click: restore the pre-search scroll and clear."""
        self.top = self._search_origin_top
        self._clear_search()
        self._clamp()
        self._render()

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        theme = ctx.theme
        wu, hu = ctx.size_units  # exact (sub-cell) extent — anchor chrome to it
        # Like the main window: chrome surfaces (footer, content bg) fill the whole
        # window; only text and the panes inset — pad_x left/right, pad_y at the
        # header top (via the splitter's y origin) and the footer bottom.
        pad_x, pad_y = viewer_pad(ctx)
        self._pad = (pad_x, pad_y)
        bg = _content_bg(theme)  # sit on XeFM's own pane background, not popup_bg
        # Dropped over a wallpaper so the scene shows at full strength — see
        # TextViewer.draw for why the page fill is the one surface that goes.
        if not ctx.wallpaper:
            ctx.fill_rect(0, 0, wu, hu, Style(bg=bg))
        # A distinct 'header' surface band across the top (reaching the top edge);
        # each pane draws its filename onto it (see _DiffPane.draw).
        ctx.fill_rect(0, 0, wu, 1.0 + pad_y, Style(bg=_header_bg(theme)))

        # Each pane gets its own horizontal scrollbar (the panes pan together by
        # self.left but have different widths). A row is reserved below the panes
        # when either side's content overruns its width. The reserve decision uses
        # the splitter's geometry from the *previous* frame (it persists), since
        # the current rects are only set when the splitter draws below; the bars
        # are then positioned from the fresh rects.
        gutter = self._gutter_w()
        iw = max(1.0, wu - 2 * pad_x)             # splitter width inside the l/r pad
        mx = CONTENT_PAD_CELLS if ctx.vector_shapes else 0.0  # per-pane content inset
        lx, lcw, rx, rcw = self._pane_columns(iw, gutter, mx)
        show_hbar = self._max_line > lcw or self._max_line > rcw
        fy = hu - 1.0 - pad_y                     # footer text row (surface below)
        hbar_y = fy - 1.0
        content_bottom = hbar_y if show_hbar else fy
        splitter_h = max(1.0, content_bottom - pad_y)  # splitter spans pad_y..content
        self._body_h = splitter_h - 1.0           # pane body = splitter minus header
        self._view_h = max(1, int(self._body_h))
        self._clamp()

        # Two panes + the draggable divider, inset from the top/left/right.
        ctx.draw_child(self.splitter, pad_x, pad_y, iw, splitter_h)

        # Shared vertical scrollbar at the content's right edge (inset by l/r pad).
        if len(self.rows) > self._view_h:
            denom = len(self.rows) - self._view_h
            ratio = min(1.0, self._body_h / len(self.rows))
            ctx.draw_scrollbar(wu - pad_x - 1, pad_y + 1, self._body_h,
                               max(0.0, min(1.0, self.top / denom if denom else 0.0)), ratio)

        # One horizontal scrollbar per pane, from the current splitter rects
        # (splitter-local, so shifted by the l/r pad into screen space).
        if show_hbar:
            lx, lcw, rx, rcw = self._pane_columns(iw, gutter, mx)
            if self._max_line > lcw:
                draw_hscrollbar(ctx, pad_x + lx, hbar_y, lcw, self.left, lcw, self._max_line)
            if self._max_line > rcw:
                draw_hscrollbar(ctx, pad_x + rx, hbar_y, rcw, self.left, rcw, self._max_line)

        # Bottom status bar — full-width 'status' surface reaching the bottom edge,
        # text inset, matching the main window (and the other two viewers). Its rect
        # is captured so the ISearchBar can pin over it during a search.
        self._footer_rect = (0.0, fy, wu, hu - fy)
        search_k = _label("search", "F")
        edit_k = _label("edit_file", "E")
        quit_k = _label("quit", "q")
        hint = (f" {len(self.rows)} rows · {len(self.blocks)} changes · "
                f"n/N jump · {search_k} search · {edit_k} edit · ←→ pan · "
                f"{quit_k}/Esc close ")
        draw_status_bar(ctx, fy, hint, pad_x=pad_x, bottom_pad=pad_y)

    # --- events --------------------------------------------------------------

    def _close(self) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.MOUSE_SCROLL:
            uy = event.hints.get("scroll_units")
            self.top -= float(uy) if uy is not None else float(event.scroll)
            ux = event.hints.get("scroll_units_x")
            if ux is not None:
                self.left -= float(ux)
            self._clamp()
            return True
        if event.type in self._MOUSE:
            # Route to the splitter so the divider can be dragged (the panes
            # themselves are display-only). The splitter is drawn inset, so the
            # pointer event is shifted into that inset space first.
            px, py = self._pad
            ev = event.translated(-px, -py) if (px or py) and event.x is not None else event
            self.splitter.handle_event(ev)
            return True
        if event.type is not EventType.KEY:
            return True
        # Every key this viewer understands is a named action in the
        # ``diff_viewer`` context (xefm.actions) — the scroll keys and the n/N
        # block jumps included, which used to be raw comparisons here and so
        # could not be rebound at all. Esc is the universal modal dismiss and
        # stays hardcoded. While a search is open the ISearchBar is the top
        # layer and receives keys, so this isn't reached.
        action = find_action_for_event(event, context=_CONTEXT)
        if event.key == "escape" or action == "quit":
            self._close()
        else:
            handler = self._handlers_table().get(action)
            if handler is not None:
                handler()
        self._clamp()
        return True

    def _handlers_table(self) -> dict:
        """This viewer's actions, by name."""
        if self._handlers is None:
            self._handlers = {
                "help": self._show_help,
                "search": self._enter_search,
                "edit_file": self._edit_in_tool,
                "diff_viewer.next_block": lambda: self._step_block(1),
                "diff_viewer.prev_block": lambda: self._step_block(-1),
                "diff_viewer.scroll_down": lambda: self._scroll(1),
                "diff_viewer.scroll_up": lambda: self._scroll(-1),
                "diff_viewer.page_down": lambda: self._scroll(self._view_h),
                "diff_viewer.page_up": lambda: self._scroll(-self._view_h),
                "diff_viewer.scroll_top": lambda: setattr(self, "top", 0.0),
                "diff_viewer.scroll_bottom": self._scroll_bottom,
                "diff_viewer.scroll_right": lambda: self._pan(4),
                "diff_viewer.scroll_left": lambda: self._pan(-4),
            }
        return self._handlers

    def _scroll(self, rows: float) -> None:
        self.top += rows

    def _scroll_bottom(self) -> None:
        self.top = float(max(0, len(self.rows) - self._view_h))

    def _pan(self, cells: float) -> None:
        self.left = max(0.0, self.left + cells)

    def _show_help(self) -> None:
        if self._panel is None:
            return
        rows = [
            (_pair("diff_viewer.scroll_up", "diff_viewer.scroll_down"), "scroll line"),
            (_pair("diff_viewer.page_up", "diff_viewer.page_down"), "scroll page"),
            (_pair("diff_viewer.scroll_top", "diff_viewer.scroll_bottom"), "top / bottom"),
            (_pair("diff_viewer.scroll_left", "diff_viewer.scroll_right"),
             "scroll horizontally"),
            (_pair("diff_viewer.next_block", "diff_viewer.prev_block"),
             "next / prev diff block"),
            (_label("search", "F"), "incremental search"),
            ("↑ / ↓ (in search)", "next / prev match"),
            (_label("edit_file", "E"), "edit both sides in $TEXT_DIFF"),
            ("Drag gutter", "move centre split"),
            (_label("help", "?"), "this help"),
            (_label("quit", "q") + " / Esc", "close"),
        ]
        show_markdown(self._panel, keys_markdown(rows),
                      title="File Diff — Keys", z=self._child_z)


def show_diff_viewer(panel: Any, path1, path2, z: int = 80, on_edited=None) -> DiffViewer:
    """Push a full-window modal :class:`DiffViewer` comparing two files.
    ``on_edited`` is called after the external ``TEXT_DIFF`` tool has run (the
    ``edit_file`` binding), so the opener can refresh anything it derived from
    the files."""
    viewer = DiffViewer(path1, path2, syntax=_syntax_palette(panel), on_edited=on_edited)
    sw, sh = panel.backend.size_units
    viewer._panel = panel
    viewer._child_z = z + 10  # help overlay stacks above the viewer's own layer
    panel.push_layer(viewer, z=z, hints=viewer_layer_hints(sw, sh),
                     reflow=lambda sw, sh: Rect(0, 0, sw, sh))
    animate_open(panel, viewer, OPEN_MS_VIEWER)
    return viewer
