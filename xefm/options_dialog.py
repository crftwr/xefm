"""OptionsDialog — the one surface behind the ``options`` key.

Every XeFM surface that grows live settings (:mod:`xefm.options`) reaches them
through the same key and the same box: a titled list of its declared options,
each row a name and whether it is on. Changes apply as they are made — the
search behind the box re-runs while you watch — so the box has nothing to
accept: Enter and Esc both simply close it, and the hint band says *done*
rather than *cancel* so neither is mistaken for an undo.

The point of it being a separate surface is the keyboard. There is no text field
here, which means every plain letter is free: an option is toggled by its
label's initial, and a surface can grow a tenth option without spending a tenth
chord. That is the whole argument for one entry key over one key per option —
see :mod:`xefm.options`.

The letters are not drawn, for the reason the Sort dialog does not draw its
own: the word already carries its initial, and a column of single letters costs
more width than it explains.

Built in :class:`~xefm.choice_dialog.ChoiceDialog`'s mold (self-sizing box,
shared title/hint chrome, click-to-act rows), because a reader who has met one
of these should not have to learn the other.
"""

from __future__ import annotations

from typing import Any, Callable

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.font import Font
from puikit.theme import DEFAULT_THEME
from puikit.widgets.base import Widget

from xefm.dialog_geometry import (HINT_ROWS, animate_open, draw_hint_row,
                                  draw_title_bar)
from xefm.options import Option, OptionSet, accel_map, state_label

#: Vertical pitch of a row — whole cells on a grid, extra air on a vector
#: backend (matches ChoiceDialog / SortDialog).
_GRID_ROW_PITCH = 1.0
_GUI_ROW_PITCH = 1.3

#: Least gap between a row's label and the on/off column at its right end.
_VALUE_GAP = 3.0


class OptionsDialog(Widget):
    """Modal option list for one surface. Construct via
    :func:`show_options_dialog`, which sizes and pushes the layer."""

    focusable = True

    _TITLE_ROWS = 3.0
    _HINT = "↑/↓ select · Space or letter toggles · Esc done"

    def __init__(self, options: OptionSet, *, title: str = "Options",
                 mode: str | None = None,
                 on_close: Callable[[], None] | None = None):
        self.options = options
        self.title = title
        self.mode = mode
        self.on_close = on_close
        #: Only the options that apply in ``mode`` — captured once, so the list
        #: cannot reorder or resize under the cursor while it is open.
        self.rows: list[Option] = options.visible(mode)
        self._accels = accel_map(self.rows)
        self._index = 0
        self._panel: Any = None
        self._row_hits: list[tuple[int, float, float]] = []
        self._size: tuple[float, float] = (0.0, 0.0)

    # --- geometry ------------------------------------------------------------

    @staticmethod
    def _row_pitch(vector: bool) -> float:
        return _GUI_ROW_PITCH if vector else _GRID_ROW_PITCH

    @staticmethod
    def _rows_top(title_bottom: float) -> float:
        return title_bottom + 1.0

    def _box_height(self, title_bottom: float, pitch: float) -> float:
        return self._rows_top(title_bottom) + len(self.rows) * pitch + 1.0 + HINT_ROWS

    def _content_width(self, measure) -> float:
        """Width of the widest content line (base units, excluding margins).

        The on/off column is measured at its widest word, not its current one,
        so the box does not resize as an option is toggled — a box that breathed
        under the cursor would make the list impossible to read.
        """
        widest_state = max(measure(state_label(v)) for v in (False, True))
        rows = max((measure(o.label) for o in self.rows), default=0.0)
        return max(rows + _VALUE_GAP + widest_state, measure(self._HINT))

    # --- lifecycle -----------------------------------------------------------

    def show(self, panel: Any, *, z: int = 90) -> None:
        self._panel = panel
        sw, sh = panel.backend.size_units
        prop = Style(font=Font())
        measure = lambda t: panel.backend.measure_text(t, prop)  # noqa: E731
        pitch = self._row_pitch(panel.backend.capabilities.supports("vector_shapes"))
        w = float(min(int(sw) - 4, self._content_width(measure) + 4.0))
        h = float(min(sh - 2.0, self._box_height(self._TITLE_ROWS, pitch)))
        panel.push_layer(self, z=z, hints={"shadow": True, "w": w, "h": h})
        animate_open(panel, self)

    def close(self) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()
        if self.on_close is not None:
            self.on_close()

    # --- changing ------------------------------------------------------------

    def toggle_row(self, index: int) -> None:
        """Flip the option on row ``index``. The change goes through
        :class:`~xefm.options.OptionSet`, which is what notifies the surface —
        this dialog never re-runs anything itself."""
        if 0 <= index < len(self.rows):
            self._index = index
            self.options.toggle(self.rows[index].name)

    def _accel(self, char: str) -> bool:
        """Act on a plain letter: select that option's row and flip it. Returns
        whether the letter belonged to an option."""
        option = self._accels.get(char.lower())
        if option is None:
            return False
        self.toggle_row(self.rows.index(option))
        return True

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

        line_h = ctx.line_height()
        pitch = self._row_pitch(ctx.vector_shapes)
        row_vy = max(0.0, (pitch - line_h) / 2.0)

        self._row_hits = []
        y = self._rows_top(title_bottom)
        for i, option in enumerate(self.rows):
            selected = i == self._index
            if selected:
                ctx.round_rect(2.0, y + row_vy - 0.1, box_w - 4.0, line_h + 0.2,
                               Style(bg=theme.selection_active_bg),
                               radius=None, hints={"fill": True})
            row_bg = theme.selection_active_bg if selected else surface_bg
            on = self.options.get(option.name)
            ctx.draw_text(3.0, y + row_vy, option.label,
                          Style(fg=theme.text, bg=row_bg))
            # The on/off word carries the same accent/muted reading as the chip
            # strip, so the two surfaces say the same thing about the same option.
            state = state_label(on)
            ctx.draw_text(max(3.0, box_w - 3.0 - ctx.measure_text(state)),
                          y + row_vy, state,
                          Style(fg=theme.accent if on else theme.muted_text, bg=row_bg))
            self._row_hits.append((i, y, y + pitch))
            y += pitch

        draw_hint_row(ctx, self._HINT, surface_bg=surface_bg,
                      border=theme.popup_border)

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
        if key in ("escape", "enter"):
            # Nothing to accept — every change already applied — so both keys
            # mean the same thing, and neither is an undo.
            self.close()
            return
        if not self.rows:
            self._render()
            return
        if key == "up":
            self._index = (self._index - 1) % len(self.rows)
        elif key == "down":
            self._index = (self._index + 1) % len(self.rows)
        elif key in ("space", "left", "right"):
            self.toggle_row(self._index)
        elif event.char and len(event.char) == 1 and event.char.isalpha() \
                and not (event.modifiers - {"shift"}):
            self._accel(event.char)
        self._render()

    def _on_click(self, event: Event) -> None:
        if event.x is None or event.y is None:
            return
        w, h = self._size
        if not (0 <= event.x < w and 0 <= event.y < h):
            self.close()  # a click outside dismisses, as everywhere else
            return
        for i, y0, y1 in self._row_hits:
            if 2.0 <= event.x < w - 2.0 and y0 <= event.y < y1:
                self.toggle_row(i)  # a row click flips it and stays open
                self._render()
                return

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()


def show_options_dialog(panel: Any, options: OptionSet, *, title: str = "Options",
                        mode: str | None = None,
                        on_close: Callable[[], None] | None = None,
                        z: int = 90) -> OptionsDialog:
    """Push a modal :class:`OptionsDialog` over ``panel`` and return it.

    ``mode`` gates which of the declared options are listed (an option that
    cannot apply is absent, not dimmed). Changes reach the owner through
    ``options.on_change``; ``on_close`` fires once the box goes away."""
    dialog = OptionsDialog(options, title=title, mode=mode, on_close=on_close)
    dialog.show(panel, z=z)
    return dialog
