"""ChoiceDialog — a compact, keyboard-first single-choice list picker.

A generic modal in the Sort dialog's mold: a titled box of rows — ``(value,
label)`` pairs supplied by the caller — where **Up/Down** move, **Enter**
applies, **Esc** cancels; a click applies its row, a click outside dismisses.
The selection seeds on the ``current`` value, so opening the dialog also
*shows* the current state. The chosen row's *value* is reported through
``on_result`` (``None`` on cancel — callers wanting "none" as a real choice
give it a row of its own, the way the encoding picker's Auto row does).

Type-ahead: quickly typing a keyword jumps the selection — printable keys
accumulate into a buffer matched case-insensitively against the labels, a
prefix match winning over a substring match. The buffer shows in the hint band
along the bottom while it is live, Backspace trims it, and a second of quiet
resets it, so a mistyped jump costs a beat, not an Esc.

First (and so far only) user: the text viewer's encoding picker. The Sort
dialog predates this widget and keeps its own two-axis layout (key rows × an
order segment) — this one is for flat pick-one lists.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.font import Font
from puikit.theme import DEFAULT_THEME
from puikit.widgets.base import Widget

from xefm.dialog_geometry import (HINT_ROWS, animate_open, draw_hint_row,
                                  draw_title_bar)

#: Quiet time after which the type-ahead buffer resets.
_TYPEAHEAD_TIMEOUT_S = 1.0

#: Vertical pitch of a row: whole cells on a character grid; a 1.0-unit pitch
#: packs the proportional lines edge to edge on a vector (GUI) backend, so the
#: rows get extra air there (matches SortDialog).
_GRID_ROW_PITCH = 1.0
_GUI_ROW_PITCH = 1.3


class ChoiceDialog(Widget):
    """Modal pick-one list. Construct via :func:`show_choice_dialog`, which
    sizes and pushes the layer; this class owns layout, selection, and events."""

    focusable = True

    _TITLE_ROWS = 3.0  # rows the title bar occupies when sizing (grid; vector is less)
    _HINT = "↑/↓ or type to choose · Enter apply · Esc cancel"

    def __init__(self, title: str, rows: list[tuple[Any, str]], *,
                 current: Any = None,
                 on_result: Callable[[Optional[Any]], None] | None = None):
        self.title = title
        self.on_result = on_result
        self._rows = list(rows)
        self._index = next((i for i, (v, _l) in enumerate(self._rows) if v == current), 0)
        self._panel: Any = None
        # Type-ahead state: the live buffer and the last keystroke's time.
        # The clock is an attribute so tests can inject a fake one.
        self._typed = ""
        self._typed_at = 0.0
        self._clock = time.monotonic
        # Row hit bands captured during draw, dialog-local (index, y0, y1).
        self._row_hits: list[tuple[int, float, float]] = []
        self._size: tuple[float, float] = (0.0, 0.0)

    # --- geometry ------------------------------------------------------------

    @staticmethod
    def _row_pitch(vector: bool) -> float:
        return _GUI_ROW_PITCH if vector else _GRID_ROW_PITCH

    @staticmethod
    def _rows_top(title_bottom: float) -> float:
        return title_bottom + 1.0  # a blank row under the title rule

    def _content_bottom(self, title_bottom: float, pitch: float) -> float:
        """Where the rows end. The hint band is chrome and hangs off the bottom of
        the box, not off the content."""
        return self._rows_top(title_bottom) + len(self._rows) * pitch

    def _box_height(self, title_bottom: float, pitch: float) -> float:
        # Rows, a blank row of air, then the band's rule / keys / bottom border.
        return self._content_bottom(title_bottom, pitch) + 1.0 + HINT_ROWS

    def _content_width(self, measure) -> float:
        """Width of the widest content line (base units, excluding the 2-unit
        margins): the widest row label or the key hint. ``measure`` must be the
        *rendering* text measurer (proportional on GUI)."""
        row_w = 1.0 + max(measure(label) for _v, label in self._rows)
        return max(row_w, measure(self._HINT))

    # --- lifecycle -----------------------------------------------------------

    def show(self, panel: Any, *, z: int = 90) -> None:
        self._panel = panel
        sw, sh = panel.backend.size_units
        # Size to the content up front, measuring through the backend with the
        # proportional UI font — the same face it renders in (a bare column
        # count would over-size the box on a GUI backend). Mirrors SortDialog.
        prop = Style(font=Font())
        measure = lambda t: panel.backend.measure_text(t, prop)  # noqa: E731
        pitch = self._row_pitch(panel.backend.capabilities.supports("vector_shapes"))
        w = float(min(int(sw) - 4, self._content_width(measure) + 4.0))  # +2 margin/side
        h = float(min(sh - 2.0, self._box_height(self._TITLE_ROWS, pitch)))
        panel.push_layer(self, z=z, hints={"shadow": True, "w": w, "h": h})
        animate_open(panel, self)

    def _finish(self, result: Optional[Any]) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()
        if self.on_result is not None:
            self.on_result(result)

    def _accept(self) -> None:
        self._finish(self._rows[self._index][0])

    # --- type-ahead -----------------------------------------------------------

    def _typeahead_buffer(self) -> str:
        """The live type-ahead buffer — empty once the quiet timeout has
        passed, so a stale prefix never silently prepends to the next jump."""
        if self._typed and self._clock() - self._typed_at > _TYPEAHEAD_TIMEOUT_S:
            self._typed = ""
        return self._typed

    def _typeahead(self, char: str) -> None:
        """Append ``char`` to the buffer and jump to the first label matching
        it — a prefix match anywhere in the list wins over a substring match.
        With no match at all the selection stays and the buffer keeps what was
        typed (it shows in the footer, so the miss is visible, and the timeout
        clears it)."""
        self._typed = self._typeahead_buffer() + char.lower()
        self._typed_at = self._clock()
        self._jump_to(self._typed)

    def _typeahead_backspace(self) -> None:
        buffer = self._typeahead_buffer()
        if not buffer:
            return
        self._typed = buffer[:-1]
        self._typed_at = self._clock()
        if self._typed:
            self._jump_to(self._typed)

    def _jump_to(self, text: str) -> None:
        labels = [label.lower() for _v, label in self._rows]
        hit = next((i for i, label in enumerate(labels) if label.startswith(text)),
                   None)
        if hit is None:
            hit = next((i for i, label in enumerate(labels) if text in label), None)
        if hit is not None:
            self._index = hit

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme or DEFAULT_THEME
        surface_bg = theme.popup_bg
        box_w, box_h = ctx.size_units
        ctx.draw_box(0, 0, box_w, box_h,
                     Style(bg=surface_bg, fg=theme.popup_border), hints={"fill": True})
        title_bottom = draw_title_bar(ctx, self.title, surface_bg=surface_bg,
                                      border=theme.popup_border, y=1.0)

        # Center each text line (and the selection band) in its row, exactly as
        # the Sort dialog does. Color only — no bold, so a proportional font
        # never reflows the row when the selection moves.
        line_h = ctx.line_height()
        pitch = self._row_pitch(ctx.vector_shapes)
        row_vy = max(0.0, (pitch - line_h) / 2.0)

        self._row_hits = []
        y = self._rows_top(title_bottom)
        for i, (_value, label) in enumerate(self._rows):
            selected = i == self._index
            if selected:
                ctx.round_rect(2.0, y + row_vy - 0.1, box_w - 4.0, line_h + 0.2,
                               Style(bg=theme.selection_active_bg),
                               radius=None, hints={"fill": True})
            row_bg = theme.selection_active_bg if selected else surface_bg
            ctx.draw_text(3.0, y + row_vy, label, Style(fg=theme.text, bg=row_bg))
            self._row_hits.append((i, y, y + pitch))
            y += pitch

        # The band shows the live type-ahead buffer while one is building
        # (feedback for the jump — including a miss), else the key hint: what the
        # dialog answers to, which for the moment you are typing *is* the buffer.
        buffer = self._typeahead_buffer()
        draw_hint_row(ctx, f"Jump to: {buffer}▏" if buffer else self._HINT,
                      surface_bg=surface_bg, border=theme.popup_border)

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY:
            self._on_key(event)
            return True
        if event.type is EventType.MOUSE_CLICK:
            self._on_click(event)
            return True
        return True  # modal: swallow the rest

    def _on_key(self, event: Event) -> None:
        key = event.key
        if key == "escape":
            self._finish(None)
            return
        if key == "enter":
            self._accept()
            return
        if key == "up":
            self._index = (self._index - 1) % len(self._rows)
        elif key == "down":
            self._index = (self._index + 1) % len(self._rows)
        elif key == "backspace":
            self._typeahead_backspace()
        elif event.char and len(event.char) == 1 and event.char.isprintable() \
                and not (event.modifiers - {"shift"}):
            self._typeahead(event.char)
        self._render()

    def _on_click(self, event: Event) -> None:
        if event.x is None or event.y is None:
            return
        w, h = self._size
        if not (0 <= event.x < w and 0 <= event.y < h):
            self._finish(None)  # click outside the dialog dismisses it
            return
        for i, y0, y1 in self._row_hits:
            if 2.0 <= event.x < w - 2.0 and y0 <= event.y < y1:
                self._index = i
                self._accept()  # a row click chooses and closes
                return

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()


def show_choice_dialog(panel: Any, title: str, rows: list[tuple[Any, str]], *,
                       current: Any = None,
                       on_result: Callable[[Optional[Any]], None] | None = None,
                       z: int = 90) -> ChoiceDialog:
    """Push a modal :class:`ChoiceDialog` over ``panel`` and return it.
    ``rows`` are ``(value, label)`` pairs; ``current`` seeds the selection on
    the row with that value (first row otherwise). The chosen row's value is
    reported through ``on_result`` — ``None`` on cancel."""
    dialog = ChoiceDialog(title, rows, current=current, on_result=on_result)
    dialog.show(panel, z=z)
    return dialog
