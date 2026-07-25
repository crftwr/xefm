"""CandidateListOverlay — the popup that lists TAB-completion candidates.

A small, presentational PuiKit widget pushed as its **own non-interactive layer**
directly below (or above) the text field being completed — above the dialog in the
z-order, so it visually hugs the field, while the dialog beneath keeps keyboard
focus (see the non-interactive layer support in ``puikit.panel``).

It draws no heavy frame: the rows sit on a distinct ``popup_bg`` surface, which is
all a terminal needs to separate them; a GUI backend adds a hairline outline and
inherits the layer's drop shadow. Scrolling uses PuiKit's standard scrollbar
(``ctx.draw_scrollbar``). The highlighted row (if any) is filled with the
active-selection color.

The widget holds no completion logic and no field state: a host (``InputDialog``)
syncs it with :meth:`set_state` from a :class:`xefm.completion.CompletionController`
and positions it with :func:`overlay_geometry`. Because the overlay is not the
event-owning layer, the host forwards clicks that fall inside it to
:meth:`handle_event`, which reports the clicked row through ``on_activate``.
"""

from __future__ import annotations

from typing import Any, Callable, List

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.text import truncate_to_width
from puikit.widgets.base import Widget

#: Most candidate rows the popup shows at once; the rest scroll.
MAX_ROWS = 8
#: Cap on the popup width, in base units.
MAX_WIDTH = 60.0
#: Left inset of the candidate text within the popup. The popup is shifted left by
#: this much when positioned, so the text lines up with the token in the field.
ROW_PAD_L = 1.0


class CandidateListOverlay(Widget):
    # Driven programmatically by the host dialog, which stays the focus/event
    # owner; the overlay never takes focus of its own.
    focusable = False

    def __init__(self, on_activate: Callable[[int], None] | None = None):
        #: Chosen row index (from a mouse click) is reported here.
        self.on_activate = on_activate
        self.candidates: List[str] = []
        self.focused_index = -1  # -1 == no row highlighted
        self.offset = 0          # first visible row
        self._row_h = 1.0        # last-drawn row pitch, read by mouse hit-testing

    # --- state ---------------------------------------------------------------

    def set_state(self, candidates: List[str], focused_index: int) -> None:
        """Sync the rows and highlight from the controller, scrolling so the
        highlighted row stays visible."""
        self.candidates = candidates
        self.focused_index = focused_index
        self._scroll_into_view()

    def visible_rows(self) -> int:
        return min(len(self.candidates), MAX_ROWS)

    def _scroll_into_view(self) -> None:
        n = len(self.candidates)
        max_off = max(0, n - MAX_ROWS)
        if self.focused_index < 0:
            self.offset = max(0, min(self.offset, max_off))
            return
        if self.focused_index < self.offset:
            self.offset = self.focused_index
        elif self.focused_index >= self.offset + MAX_ROWS:
            self.offset = self.focused_index - MAX_ROWS + 1
        self.offset = max(0, min(self.offset, max_off))

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx: Any) -> None:
        theme = ctx.theme
        wu, hu = ctx.size_units
        surface_bg = theme.popup_bg if theme is not None else None
        fg = theme.text if theme is not None else None
        sel_bg = theme.selection_active_bg if theme is not None else None
        text_style = Style(fg=fg)
        row_h = ctx.line_height(text_style)
        self._row_h = row_h

        # A distinct surface, no frame — a terminal reads the rows by this
        # contrasting fill alone; a GUI backend adds the hairline outline below
        # and inherits the layer's drop shadow.
        ctx.fill_rect(0, 0, wu, hu, Style(bg=surface_bg))

        n = len(self.candidates)
        vis = self.visible_rows()
        has_bar = n > vis
        bar_w = 1.0 if has_bar else 0.0
        pad_l = ROW_PAD_L
        text_w = max(1.0, wu - pad_l - bar_w)
        ty = (row_h - 1.0) / 2.0  # center the text line within the row box
        measure = lambda t: ctx.measure_text(t)

        for row in range(vis):
            index = self.offset + row
            if index >= n:
                break
            y = row * row_h
            label = truncate_to_width(self.candidates[index], text_w, measure=measure)
            if index == self.focused_index and sel_bg is not None:
                ctx.fill_rect(0, y, wu - bar_w, row_h, Style(bg=sel_bg))
                ctx.draw_text(pad_l, y + ty, label, Style(bg=sel_bg, fg=fg))
            else:
                ctx.draw_text(pad_l, y + ty, label, Style(bg=surface_bg, fg=fg))

        if has_bar:
            ratio = vis / n
            denom = n - vis
            pos = self.offset / denom if denom > 0 else 0.0
            ctx.draw_scrollbar(wu - 1.0, 0.0, hu, max(0.0, min(1.0, pos)), ratio, text_style)

        if ctx.vector_shapes and theme is not None:
            ctx.round_rect(0, 0, wu, hu, Style(fg=theme.popup_border), radius=4.0)

    # --- events (forwarded by the host; coords already overlay-local) --------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.MOUSE_CLICK and event.y is not None:
            row = int(event.y / max(self._row_h, 1e-6))
            index = self.offset + row
            if 0 <= row < self.visible_rows() and 0 <= index < len(self.candidates):
                if self.on_activate is not None:
                    self.on_activate(index)
            return True
        return False


def overlay_geometry(
    field_x: float,
    field_y: float,
    field_h: float,
    token_x: float,
    candidates: List[str],
    measure: Callable[[str], float],
    row_h: float,
    screen_w: float,
    screen_h: float,
) -> tuple[float, float, float, float]:
    """Rect (x, y, w, h) at which to place the candidate popup for a field at
    ``(field_x, field_y, .., field_h)`` whose token being completed starts at
    absolute column ``token_x``.

    Placed just **below** the field, or **above** it when there isn't room below
    (Req 2.2/2.3), left-anchored so the candidate *text* lines up with the token
    column (Req 6.7) — the popup left edge is shifted left by the row's text inset
    (:data:`ROW_PAD_L`). Sized to the longest candidate (measured, so it fits on a
    proportional font too) and capped at :data:`MAX_ROWS` rows — no border rows."""
    vis = min(len(candidates), MAX_ROWS)
    h = max(row_h, vis * row_h)
    longest = max((measure(c) for c in candidates), default=8.0)
    bar = 1.0 if len(candidates) > MAX_ROWS else 0.0
    w = min(longest + ROW_PAD_L + 1.0 + bar, MAX_WIDTH, max(8.0, screen_w))

    x = max(0.0, min(token_x - ROW_PAD_L, max(0.0, screen_w - w)))
    below = field_y + field_h
    if below + h <= screen_h:
        y = below
    elif field_y - h >= 0.0:
        y = field_y - h
    else:
        y = max(0.0, min(below, screen_h - h))
    return (x, y, w, h)
