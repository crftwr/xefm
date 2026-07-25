"""CompareSelectDialog — the modal that builds a :class:`~xefm.compare_selection.CompareCriteria`
for the ``compare_selection`` action (ttk XeFM's ``W`` key, rebuilt for PuiKit).

A compact, keyboard-first list (no Tab, no buttons):

- **Up / Down** move focus between rows — the three condition rows (Size /
  Modified / Content) and the "Preserve current selection" toggle.
- Each condition row is a real :class:`~puikit.widgets.Checkbox` (enable this
  attribute) plus a segmented option picker: **Space** toggles the checkbox,
  **Left / Right** choose the relation. The chosen segment is drawn with a filled
  highlight — a rounded pill on a vector (GUI) backend, a background block on a
  character grid — never a font-weight change (which would resize proportional
  text). ``any`` = the checkbox is off, i.e. don't compare this attribute.
- **Enter** accepts, **Esc** cancels.

The selection folds into the active pane, replacing the current selection unless
Preserve is on. (The engine still supports orphan selection; this dialog does not
expose it.)
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Optional

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer
from puikit.font import Font
from puikit.layout import LayoutContext, SizeRequest
from puikit.theme import DEFAULT_THEME
from puikit.widgets import Checkbox
from puikit.widgets.base import Widget

from xefm.compare_selection import CompareCriteria
from xefm.dialog_geometry import animate_open, draw_title_bar, pane_anchored_box

# (label, relation options). The Checkbox is the on/off; the options are the real
# relations (no "any" — that is the box being unchecked). Values are CompareCriteria's.
_SIZE = ("Size", ["equal", "differs"])
_MTIME = ("Modified", ["same", "newer", "older"])
_CONTENT = ("Content", ["equal", "differs"])

_OPT_GAP = 2.0  # base units between option segments
_CB_MARK = 4.0  # checkbox mark + gap gutter in base units (PuiKit "[ ] " label_x)


class ConditionRow(Widget):
    """One attribute on a single line: a :class:`Checkbox` (enable) + a segmented
    relation picker. ``value`` is ``"any"`` while the box is unchecked, else the
    chosen relation. Space toggles the box; Left/Right move the relation."""

    focusable = True

    #: x (base units) where the option run starts, set by the dialog so the rows
    #: align their segments under a common gutter past the widest checkbox.
    opt_x0 = 14.0

    def __init__(self, label: str, options: list[str]):
        self.checkbox = Checkbox(label, checked=False)
        self.options = options
        self.index = 0
        self._cb_x = (1.0, 1.0)                       # checkbox hit range, set at draw
        self._opt_hits: list[tuple[float, float, int]] = []

    @property
    def value(self) -> str:
        return self.options[self.index] if self.checkbox.checked else "any"

    def toggle(self) -> None:
        self.checkbox.toggle()

    def move(self, delta: int) -> None:
        self.index = max(0, min(len(self.options) - 1, self.index + delta))

    def set_index(self, i: int) -> None:
        if 0 <= i < len(self.options):
            self.index = i

    def measure(self, ctx: LayoutContext, axis: str, available: float) -> SizeRequest:
        if axis == "y":
            return self.checkbox.measure(ctx, "y", available)  # match the checkbox height
        return SizeRequest(min=self.opt_x0 + 6.0, preferred=self.opt_x0 + 24.0,
                           max=float("inf"))

    def draw(self, ctx) -> None:
        theme = ctx.theme or DEFAULT_THEME
        hu = ctx.size_units[1]
        focused = ctx.focused
        # Row surface: the dialog filled it (via the draw_child "bg" hint) with the
        # popup surface or, when focused, the hover tint. Text/marks must carry
        # that bg explicitly — a bare bg=None resolves to the layer default (dark),
        # which shows through as black on a grid backend.
        row_bg = theme.hover_bg if focused else theme.popup_bg

        active = self.checkbox.checked
        cb_w = _CB_MARK + ctx.measure_text(self.checkbox.label)  # proportional, matches render
        ctx.draw_child(self.checkbox, 0.0, 0, cb_w, hu, hints={"focused": focused})
        self._cb_x = (0.0, cb_w)

        # Segments. The current one gets a filled highlight (a pill on vector, a
        # block on a grid); selection/enabled state is color only — no bold, so a
        # proportional font never reflows the row when it changes.
        pad = 0.6 if ctx.vector_shapes else 0.0
        line_h = ctx.line_height()
        vy = max(0.0, (hu - line_h) / 2.0)
        x = self.opt_x0
        self._opt_hits = []
        for i, opt in enumerate(self.options):
            w = ctx.measure_text(opt)
            current = i == self.index
            if current:
                seg_bg = theme.selection_active_bg if active else theme.selection_inactive_bg
                ctx.round_rect(x - pad, vy - 0.1, w + 2 * pad, line_h + 0.2,
                               Style(bg=seg_bg), radius=None, hints={"fill": True})
                fg = theme.text
            else:
                seg_bg = row_bg
                fg = theme.text if active else theme.muted_text
            ctx.draw_text(x, vy, opt, Style(fg=fg, bg=seg_bg))
            self._opt_hits.append((x - pad, x + w + pad, i))
            x += w + _OPT_GAP

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.MOUSE_CLICK and event.x is not None:
            if self._cb_x[0] <= event.x < self._cb_x[1]:
                self.checkbox.toggle()
                return True
            for x0, x1, i in self._opt_hits:
                if x0 <= event.x < x1:
                    self.set_index(i)
                    return True
        return False


def _layout_context(backend):
    """Build a ``LayoutContext`` for ``backend`` off-draw, so :meth:`show` can
    measure row heights (and thus size the box) before a DrawContext exists.
    Mirrors ``DrawContext.layout_context`` — the same capability resolution."""
    cw, ch = backend.base_size
    caps = backend.capabilities
    return LayoutContext(
        cw, ch,
        snap=not caps.supports("pixel_layout"),
        hairline=caps.supports("hairline"),
        native_menus=caps.supports("native_menus"),
        measure=backend.measure_text,
        line_height=backend.measure_line_height,
        scrollbar_units=backend.scrollbar_units,
        image_size=backend.image_size,
    )


class CompareSelectDialog(FocusContainer, Widget):
    """Modal criteria picker. Construct via :func:`show_compare_select`, which sizes
    and pushes the layer; this class owns layout, focus, and events."""

    focusable = True
    focus_stop_when_empty = True

    _TITLE_ROWS = 3.0  # rows the title bar occupies when sizing (grid; vector is less)
    _INTRO = "Select items that also exist in the other pane, matching:"
    _HINT_COND = "←/→ choose · Space on/off · Enter select · Esc cancel"
    _HINT_OTHER = "Space toggle · Enter select · Esc cancel"

    def __init__(self, on_result: Callable[[Optional[CompareCriteria]], None]):
        self.title = "Compare and Select"
        self.on_result = on_result
        self._panel: Any = None

        self._size = ConditionRow(*_SIZE)
        self._mtime = ConditionRow(*_MTIME)
        self._content = ConditionRow(*_CONTENT)
        self._conditions = [self._size, self._mtime, self._content]
        self._preserve = Checkbox("Preserve current selection", checked=False)

        self._focused: Any = self._size
        self._child_rects: list[tuple[Any, tuple[float, float, float, float]]] = []

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self._size, self._mtime, self._content, self._preserve]

    def _move_focus(self, delta: int) -> None:
        kids = self.focus_children()
        i = kids.index(self._focused) if self._focused in kids else 0
        self._focused = kids[(i + delta) % len(kids)]

    # --- geometry ------------------------------------------------------------

    def _hint_y(self, title_bottom: float, row_h: float) -> float:
        """Row of the key-hint line for the top-down layout — the single source of
        truth shared by :meth:`show` (sizing), :meth:`draw` (placement), and the
        fit resize. Rows are ``row_h`` tall (a Checkbox — taller than a cell on
        vector)."""
        cond_top = float(int(title_bottom) + 2)   # blank row under the intro
        preserve_y = cond_top + 3.0 * row_h + 1.0  # conditions + a gap
        return preserve_y + row_h + 1.0            # preserve row + a gap

    def _box_height(self, title_bottom: float, row_h: float) -> float:
        return self._hint_y(title_bottom, row_h) + 2.0  # hint row + bottom border/pad

    def _opt_gutter(self, measure) -> float:
        """x where the option segments start: past the widest checkbox (mark gutter
        + label) + a gap. ``measure`` is a text-width function — pass the proportional
        ``ctx.measure_text`` at draw so the gutter matches the rendered labels."""
        return _CB_MARK + max(measure(r.checkbox.label) for r in self._conditions) + 2.0

    def _content_width(self, measure) -> float:
        """Width of the widest content line (base units), so the box hugs its text
        instead of a fixed span: the intro, the longest key hint, the Preserve
        checkbox, and the widest condition row (gutter + segments). ``measure`` must
        be the *rendering* text measurer (proportional on GUI) — a LayoutContext's
        monospace measure would over-size the box on a proportional backend."""
        opt_x0 = self._opt_gutter(measure)
        row_w = max(
            opt_x0 + sum(measure(o) for o in r.options)
            + _OPT_GAP * (len(r.options) - 1) + 0.7  # trailing pill pad
            for r in self._conditions)
        return max(
            measure(self._INTRO),
            measure(self._HINT_COND),
            _CB_MARK + measure(self._preserve.label),
            row_w,
        )

    # --- lifecycle -----------------------------------------------------------

    def show(self, panel: Any, *, region=None, z: int = 70) -> None:
        self._panel = panel
        sw, sh = panel.backend.size_units
        # Size to the content up front, measuring through the backend with the
        # proportional UI font — the same face it renders in (a bare column count
        # would over-size the box on a GUI backend). Grid backends ignore the font
        # and count columns. This mirrors how show_message_box sizes itself, so no
        # draw-time re-fit is needed.
        prop = Style(font=Font())
        measure = lambda t: panel.backend.measure_text(t, prop)  # noqa: E731
        lc = _layout_context(panel.backend)
        row_h = self._size.measure(lc, "y", 0.0).preferred
        w = float(min(int(sw) - 4, self._content_width(measure) + 4.0))  # +2 margin/side
        h = float(min(sh - 2.0, self._box_height(self._TITLE_ROWS, row_h)))
        hints: dict[str, Any] = {"shadow": True, "w": w, "h": h}
        if region is not None:
            w, x = pane_anchored_box(w, sw, region)
            hints["w"] = w
            hints["x"] = x
        panel.push_layer(self, z=z, hints=hints)
        animate_open(panel, self)

    def _finish(self, criteria: Optional[CompareCriteria]) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()
        if self.on_result is not None:
            self.on_result(criteria)

    def _accept(self) -> None:
        self._finish(self._criteria())

    def _criteria(self) -> CompareCriteria:
        return CompareCriteria(
            size=self._size.value,
            mtime=self._mtime.value,
            content=self._content.value,
            include_missing=False,
            mode=("add" if self._preserve.checked else "replace"),
        )

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        theme = ctx.theme
        surface_bg = theme.popup_bg if theme is not None else None
        border = theme.popup_border if theme is not None else None
        text_fg = theme.text if theme is not None else None
        muted_fg = theme.muted_text if theme is not None else None
        box_style = Style(bg=surface_bg, fg=border)
        box_w, box_h = ctx.size_units
        ctx.draw_box(0, 0, box_w, box_h, box_style, hints={"fill": True})
        y = draw_title_bar(ctx, self.title, surface_bg=surface_bg, border=border, y=1.0)
        self._child_rects = []
        lc = ctx.layout_context()
        row_h = self._size.measure(lc, "y", 0.0).preferred

        ctx.draw_text(2, y, self._INTRO, Style(bg=surface_bg, fg=text_fg))

        # Align the segments under one gutter, past the widest checkbox. Measured
        # with ctx.measure_text (proportional on GUI) so it matches the rendered
        # labels — a monospace measure would push the options too far right.
        opt_x0 = self._opt_gutter(ctx.measure_text)

        # Each row gets an explicit "bg" hint so its children inherit the popup
        # surface (or the hover tint when focused) instead of the dark layer
        # default — otherwise bg=None text shows through black on a grid backend.
        hover_bg = theme.hover_bg if theme is not None else None

        cond_top = float(int(y) + 2)
        row_y = cond_top
        for row in self._conditions:
            row.opt_x0 = opt_x0
            focused = self._focused is row
            ctx.draw_child(row, 2, row_y, box_w - 4, row_h,
                           hints={"focused": focused,
                                  "bg": hover_bg if focused else surface_bg})
            self._child_rects.append((row, (2.0, box_w - 2.0, row_y, row_y + row_h)))
            row_y += row_h

        preserve_y = cond_top + 3.0 * row_h + 1.0
        pfocus = self._focused is self._preserve
        ctx.draw_child(self._preserve, 2, preserve_y, box_w - 4, row_h,
                       hints={"focused": pfocus,
                              "bg": hover_bg if pfocus else surface_bg})
        self._child_rects.append(
            (self._preserve, (2.0, box_w - 2.0, preserve_y, preserve_y + row_h)))

        hint_y = self._hint_y(y, row_h)
        ctx.draw_text(2, hint_y, self._hint(), Style(bg=surface_bg, fg=muted_fg))

    def _hint(self) -> str:
        return self._HINT_COND if isinstance(self._focused, ConditionRow) else self._HINT_OTHER

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY:
            self._on_key(event)
            return True
        if event.type in (EventType.MOUSE_DOWN, EventType.MOUSE_UP,
                          EventType.MOUSE_CLICK):
            self._on_mouse(event)
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
            self._move_focus(-1)
        elif key == "down":
            self._move_focus(1)
        elif key in ("left", "right") and isinstance(self._focused, ConditionRow):
            self._focused.move(-1 if key == "left" else 1)
        elif key == "space":
            f = self._focused
            if isinstance(f, ConditionRow):
                f.toggle()
            elif f is self._preserve:
                self._preserve.toggle()
        self._render()

    def _on_mouse(self, event: Event) -> None:
        if event.x is None or event.type is not EventType.MOUSE_CLICK:
            return
        for widget, (x0, x1, y0, y1) in self._child_rects:
            if x0 <= event.x < x1 and y0 <= event.y < y1:
                self._focused = widget
                if isinstance(widget, ConditionRow):
                    widget.handle_event(dataclasses.replace(
                        event, x=event.x - x0, y=event.y - y0))
                elif widget is self._preserve:
                    self._preserve.toggle()
                self._render()
                return

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()


def show_compare_select(panel: Any, *, region=None,
                        on_result: Callable[[Optional[CompareCriteria]], None],
                        z: int = 70) -> CompareSelectDialog:
    """Push a modal :class:`CompareSelectDialog` over ``panel`` and return it. The
    assembled :class:`CompareCriteria` is reported through ``on_result`` (``None``
    on cancel). ``region`` anchors it over a pane like the other pickers."""
    dialog = CompareSelectDialog(on_result=on_result)
    dialog.show(panel, region=region, z=z)
    return dialog
