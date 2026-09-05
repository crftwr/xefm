"""SortDialog — the specialized sort picker for the ``sort`` action (the
``S`` key), replacing the generic popup menu (issue #237).

A compact, keyboard-first modal (no Tab, no buttons):

- **Up / Down** choose the sort key (Filename / Extension / Size / Timestamp).
- **Left / Right** choose the order — Left is always ascending, Right always
  descending, regardless of which key row is selected.
- **F / E / S / T** choose the matching sort key directly and close the dialog
  immediately (keeping the current order), so the common case stays two
  keystrokes: ``S`` then a letter. (The letters are not displayed — the rows'
  initials are the keys.)
- **Enter** applies, **Esc** cancels. A click on a key row applies it (like the
  menu it replaces); a click on an order segment just switches the order.

Below the Ascending/Descending segments sits an **explanation line** — e.g.
``1 KB → 1 MB → 1 GB  (smallest first)`` — because Ascending/Descending is
hard to grasp in the abstract, especially for size and timestamp. It follows
the selected key and order live.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.font import Font
from puikit.theme import DEFAULT_THEME
from puikit.widgets.base import Widget

from xefm import sort_keys
from xefm.dialog_geometry import animate_open, draw_title_bar, pane_anchored_box

#: Order segments, indexed by ``sort_reverse`` (False = Ascending).
_ORDERS = ("Ascending", "Descending")

_OPT_GAP = 2.0  # base units between the order segments (matches compare_dialog)

#: Vertical pitch of a key row. A character grid needs whole rows; on a vector
#: (GUI) backend a 1.0-unit pitch packs the proportional lines edge to edge, so
#: the rows get extra air between them.
_GRID_ROW_PITCH = 1.0
_GUI_ROW_PITCH = 1.3


class SortDialog(Widget):
    """Modal sort picker. Construct via :func:`show_sort_dialog`, which sizes
    and pushes the layer; this class owns layout, selection, and events."""

    focusable = True

    _TITLE_ROWS = 3.0  # rows the title bar occupies when sizing (grid; vector is less)
    _HINT = "↑/↓ key · ←/→ order · Enter apply · Esc cancel"

    def __init__(self, *, mode: str = "name", reverse: bool = False,
                 on_result: Callable[[Optional[tuple[str, bool]]], None] | None = None):
        self.title = "Sort By"
        self.on_result = on_result
        self._panel: Any = None
        # 'type' (the pre-dialog menu's suffix sort) seeds as Extension — the
        # same attribute, minus the display-matched length cap.
        seed = "ext" if mode == "type" else mode
        # Snapshotted at construction: the rows include whatever the config
        # registered, and a reload mid-dialog must not renumber them underneath
        # the selection (:mod:`xefm.sort_keys`).
        self._keys = sort_keys.rows()
        self._index = next((i for i, (m, _l, _h) in enumerate(self._keys)
                            if m == seed), 0)
        self._reverse = bool(reverse)
        # Hit rects captured during draw, dialog-local: key rows as
        # (index, y0, y1) full-width bands, order segments as
        # (x0, x1, y0, y1, reverse).
        self._row_hits: list[tuple[int, float, float]] = []
        self._order_hits: list[tuple[float, float, float, float, bool]] = []
        self._size: tuple[float, float] = (0.0, 0.0)

    # --- geometry ------------------------------------------------------------

    @staticmethod
    def _row_pitch(vector: bool) -> float:
        return _GUI_ROW_PITCH if vector else _GRID_ROW_PITCH

    @staticmethod
    def _rows_top(title_bottom: float) -> float:
        return title_bottom + 1.0  # a blank row under the title rule

    def _order_y(self, title_bottom: float, pitch: float) -> float:
        return self._rows_top(title_bottom) + len(self._keys) * pitch + 1.0

    def _explain_y(self, title_bottom: float, pitch: float) -> float:
        return self._order_y(title_bottom, pitch) + 1.0  # right under the segments

    def _hint_y(self, title_bottom: float, pitch: float) -> float:
        return self._explain_y(title_bottom, pitch) + 2.0

    def _box_height(self, title_bottom: float, pitch: float) -> float:
        return self._hint_y(title_bottom, pitch) + 2.0  # hint row + bottom border/pad

    def _content_width(self, measure) -> float:
        """Width of the widest content line (base units, excluding the 2-unit
        margins): the widest key row, the order-segment pair, the widest
        explanation of *every* row in both directions (so the box never resizes
        as the selection moves), and the key hint. ``measure`` must be the
        *rendering* text measurer (proportional on GUI)."""
        row_w = 1.0 + max(measure(label) for _m, label, _h in self._keys)
        order_w = (1.0 + sum(measure(o) for o in _ORDERS)
                   + _OPT_GAP + 0.7)  # trailing pill pad
        explain_w = 1.0 + max(
            measure(sort_keys.explanation(mode, rev))
            for mode, _l, _h in self._keys for rev in (False, True))
        return max(row_w, order_w, explain_w, measure(SortDialog._HINT))

    # --- lifecycle -----------------------------------------------------------

    def show(self, panel: Any, *, region=None, z: int = 70) -> None:
        self._panel = panel
        sw, sh = panel.backend.size_units
        # Size to the content up front, measuring through the backend with the
        # proportional UI font — the same face it renders in (a bare column
        # count would over-size the box on a GUI backend). Grid backends ignore
        # the font and count columns. Mirrors CompareSelectDialog.show.
        prop = Style(font=Font())
        measure = lambda t: panel.backend.measure_text(t, prop)  # noqa: E731
        pitch = self._row_pitch(panel.backend.capabilities.supports("vector_shapes"))
        w = float(min(int(sw) - 4, self._content_width(measure) + 4.0))  # +2 margin/side
        h = float(min(sh - 2.0, self._box_height(self._TITLE_ROWS, pitch)))
        hints: dict[str, Any] = {"shadow": True, "w": w, "h": h}
        if region is not None:
            w, x = pane_anchored_box(w, sw, region)
            hints["w"] = w
            hints["x"] = x
        panel.push_layer(self, z=z, hints=hints)
        animate_open(panel, self)

    def _finish(self, result: Optional[tuple[str, bool]]) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()
        if self.on_result is not None:
            self.on_result(result)

    def _accept(self) -> None:
        self._finish((self._keys[self._index][0], self._reverse))

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

        # Center each text line (and the selection band) in its row: key rows
        # are one pitch tall (1.0 on a grid; taller on vector, where a 1.0
        # pitch would pack the proportional lines edge to edge), the rest stay
        # one base unit.
        line_h = ctx.line_height()
        pitch = self._row_pitch(ctx.vector_shapes)
        row_vy = max(0.0, (pitch - line_h) / 2.0)
        vy = max(0.0, (1.0 - line_h) / 2.0)
        pad = 0.6 if ctx.vector_shapes else 0.0

        # Key rows: the selected one wears a full-width selection band (a filled
        # block on a grid, the same fill rounded on vector). Color only — no
        # bold, so a proportional font never reflows the row when the selection
        # moves. The hotkeys (F/E/S/T) are deliberately not displayed — each
        # row's initial is its key.
        self._row_hits = []
        y = self._rows_top(title_bottom)
        for i, (_mode, label, _hotkey) in enumerate(self._keys):
            selected = i == self._index
            if selected:
                ctx.round_rect(2.0, y + row_vy - 0.1, box_w - 4.0, line_h + 0.2,
                               Style(bg=theme.selection_active_bg),
                               radius=None, hints={"fill": True})
            row_bg = theme.selection_active_bg if selected else surface_bg
            ctx.draw_text(3.0, y + row_vy, label, Style(fg=theme.text, bg=row_bg))
            self._row_hits.append((i, y, y + pitch))
            y += pitch

        # Order: a segmented picker — the chosen segment gets the same filled
        # highlight the compare dialog's relation segments use.
        order_y = self._order_y(title_bottom, pitch)
        x = 3.0
        self._order_hits = []
        for rev, opt in zip((False, True), _ORDERS):
            w = ctx.measure_text(opt)
            if rev == self._reverse:
                ctx.round_rect(x - pad, order_y + vy - 0.1, w + 2 * pad, line_h + 0.2,
                               Style(bg=theme.selection_active_bg),
                               radius=None, hints={"fill": True})
                seg = Style(fg=theme.text, bg=theme.selection_active_bg)
            else:
                seg = Style(fg=theme.muted_text, bg=surface_bg)
            ctx.draw_text(x, order_y + vy, opt, seg)
            self._order_hits.append((x - pad, x + w + pad, order_y, order_y + 1.0, rev))
            x += w + _OPT_GAP

        # The explanation of the resulting order, right under the segments —
        # what "Descending" means in the selected key's own terms.
        ctx.draw_text(3.0, self._explain_y(title_bottom, pitch) + vy,
                      self.explanation(), Style(fg=theme.muted_text, bg=surface_bg))

        ctx.draw_text(2.0, self._hint_y(title_bottom, pitch) + vy, self._HINT,
                      Style(fg=theme.muted_text, bg=surface_bg))

    def explanation(self) -> str:
        """The explanation line for the selected key and order."""
        return sort_keys.explanation(self._keys[self._index][0], self._reverse)

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
            self._index = (self._index - 1) % len(self._keys)
        elif key == "down":
            self._index = (self._index + 1) % len(self._keys)
        elif key == "left":
            self._reverse = False
        elif key == "right":
            self._reverse = True
        elif not (event.modifiers - {"shift"}):
            for i, (_mode, _label, hotkey) in enumerate(self._keys):
                if hotkey and key == hotkey.lower():
                    self._index = i
                    self._accept()  # a hotkey chooses and closes in one stroke
                    return
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
                self._accept()  # a row click chooses and closes, like the menu
                return
        for x0, x1, y0, y1, rev in self._order_hits:
            if x0 <= event.x < x1 and y0 <= event.y < y1:
                self._reverse = rev
                self._render()
                return

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()


def show_sort_dialog(panel: Any, *, mode: str = "name", reverse: bool = False,
                     region=None,
                     on_result: Callable[[Optional[tuple[str, bool]]], None] | None = None,
                     z: int = 70) -> SortDialog:
    """Push a modal :class:`SortDialog` over ``panel``, seeded with the pane's
    current ``(mode, reverse)``, and return it. The chosen ``(sort_mode,
    sort_reverse)`` pair is reported through ``on_result`` (``None`` on cancel).
    ``region`` anchors it over a pane like the other pickers."""
    dialog = SortDialog(mode=mode, reverse=reverse, on_result=on_result)
    dialog.show(panel, region=region, z=z)
    return dialog
