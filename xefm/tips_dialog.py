"""TipsDialog — the "Tip of the Day" modal (issue #261).

A centered modal showing one tip from :mod:`xefm.tips` at a time:

- **Left / Right** step to the previous / next tip (wrapping), with a ``3/26``
  counter in the footer showing where the rotation stands.
- **Up / Down / PageUp / PageDown** scroll the body — a tip should not need it,
  but a small window must not clip one.
- **Space** toggles the *Don't show tips at startup* checkbox (a click on it
  works too). The checkbox arrives pre-checked when startup tips are already
  off, so reopening the dialog from **Help ▸ Tip of the Day** and unchecking it
  turns them back on.
- **Enter / Esc / outside-click** close. Closing reports ``(index, dont_show)``
  through ``on_result`` — the app persists the rotation position and the
  enabled flag from there; this widget touches no storage itself.

The body is a ``MarkdownView`` fed by :func:`xefm.tips.render_tip`, which
resolves ``{key:action}`` placeholders through the app's live keymap — the same
labels the help dialog shows.
"""

from __future__ import annotations

from typing import Any, Callable

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer
from puikit.font import Font
from puikit.panel import Rect
from puikit.theme import DEFAULT_THEME
from puikit.widgets import Checkbox
from puikit.widgets.base import Widget
from puikit.widgets.markdown_view import MarkdownView

from xefm.dialog_geometry import animate_open, draw_title_bar
from xefm.tips import render_tip, tip_count

#: Keys the body consumes for scrolling while the dialog is open (backend key
#: names are unsuffixed, matching MarkdownView).
_SCROLL_KEYS = frozenset({"up", "down", "pageup", "pagedown", "home", "end"})

_MOUSE_EVENTS = (
    EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
    EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL,
)

_CB_MARK = 4.0  # checkbox mark + gap gutter in base units (PuiKit "[ ] " label_x)


class TipsDialog(FocusContainer, Widget):
    """Modal tip browser. Construct via :func:`show_tips_dialog`, which sizes
    and pushes the layer; this class owns layout, navigation, and events."""

    focusable = True
    focus_stop_when_empty = True

    _HINT = "←/→ tip · ↑/↓ scroll · Space toggle · Esc close"
    _CHECKBOX_LABEL = "Don't show tips at startup"

    def __init__(self, *, index: int = 0, dont_show: bool = False,
                 resolve: Callable[[str], str] | None = None,
                 on_result: Callable[[int, bool], None] | None = None):
        self.title = "Tip of the Day"
        self.on_result = on_result
        self._resolve = resolve
        self._panel: Any = None
        self.index = index % tip_count()
        self.md = MarkdownView(render_tip(self.index, resolve))
        self.checkbox = Checkbox(self._CHECKBOX_LABEL, checked=dont_show)
        self._body_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._cb_rect = (0.0, 0.0, 0.0, 0.0)  # checkbox hit rect, set at draw
        self._size: tuple[float, float] = (0.0, 0.0)

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self.md]

    # --- lifecycle -----------------------------------------------------------

    def show(self, panel: Any, *, z: int = 70) -> None:
        self._panel = panel
        sw, sh = panel.backend.size_units
        # A fixed, content-independent size: tips differ in length, and a box
        # that resized on every Left/Right would jitter. Wide enough for the
        # footer (hint + counter) and the checkbox; the body scrolls if a tip
        # ever overflows. Measured through the backend with the proportional UI
        # font, like the other dialogs — a bare column count would over-size
        # the box on a GUI backend.
        prop = Style(font=Font())
        measure = lambda t: panel.backend.measure_text(t, prop)  # noqa: E731
        min_w = max(
            measure(self._HINT) + measure("99/99") + 7.0,  # hint · gap · counter
            _CB_MARK + measure(self._CHECKBOX_LABEL) + 4.0,
            48.0,
        )
        w = float(min(int(sw) - 4, max(min_w, min(sw * 0.7, 72.0))))
        h = float(max(12.0, min(sh - 2.0, min(sh * 0.8, 19.0))))
        panel.push_layer(self, z=z, hints={"shadow": True, "w": w, "h": h})
        animate_open(panel, self)

    def _finish(self) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()
        if self.on_result is not None:
            self.on_result(self.index, self.checkbox.checked)

    def _show_tip(self, index: int) -> None:
        self.index = index % tip_count()
        # set_source resets the scroll offset, so every tip starts at its top.
        self.md.set_source(render_tip(self.index, self._resolve))
        self._render()

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme or DEFAULT_THEME
        surface_bg = theme.popup_bg
        border = theme.popup_border
        wu, hu = ctx.size_units
        ctx.draw_box(0, 0, wu, hu, Style(bg=surface_bg, fg=border),
                     hints={"fill": True})
        y = draw_title_bar(ctx, self.title, surface_bg=surface_bg, border=border,
                           y=1.0)

        # The body's base prose fg/bg must match the popup surface (fg=None
        # would fall back to the backend default, wrong on some palettes).
        self.md.style = Style(fg=theme.text, bg=surface_bg)

        # Bottom-up footer: hint row inside the bottom border, checkbox above
        # it, body filling the rest. Whole rows on a grid; measured line boxes
        # with small pads on vector.
        line_h = ctx.line_height()
        lc = ctx.layout_context()
        row_h = self.checkbox.measure(lc, "y", 0.0).preferred
        pad_bottom = 0.5 if ctx.vector_shapes else 1.0
        gap = 0.25 if ctx.vector_shapes else 0.0
        hint_y = hu - pad_bottom - line_h
        cb_y = hint_y - gap - row_h
        body_gap = 0.5 if ctx.vector_shapes else 1.0
        body_h = max(1.0, cb_y - body_gap - y)
        self._body_rect = Rect(2.0, y, max(1.0, wu - 4.0), body_h)
        ctx.draw_child(self.md, self._body_rect.x, self._body_rect.y,
                       self._body_rect.w, self._body_rect.h,
                       hints={"focused": False, "bg": surface_bg})

        cb_w = _CB_MARK + ctx.measure_text(self.checkbox.label)
        ctx.draw_child(self.checkbox, 2.0, cb_y, cb_w, row_h,
                       hints={"focused": False, "bg": surface_bg})
        self._cb_rect = (2.0, 2.0 + cb_w, cb_y, cb_y + row_h)

        muted = Style(fg=theme.muted_text, bg=surface_bg)
        ctx.draw_text(2.0, hint_y, self._HINT, muted)
        counter = f"{self.index + 1}/{tip_count()}"
        ctx.draw_text(wu - 2.0 - ctx.measure_text(counter), hint_y, counter, muted)

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY:
            self._on_key(event)
            return True
        if event.type in _MOUSE_EVENTS:
            self._on_mouse(event)
            return True
        return True  # modal: swallow the rest

    def _on_key(self, event: Event) -> None:
        key = event.key
        if key in ("escape", "enter"):
            self._finish()
        elif key in ("left", "right"):
            self._show_tip(self.index + (1 if key == "right" else -1))
        elif key == "space":
            self.checkbox.toggle()
            self._render()
        elif key in _SCROLL_KEYS:
            self.md.handle_event(event)
            self._render()

    def _on_mouse(self, event: Event) -> None:
        if event.x is None or event.y is None:
            return
        x0, x1, y0, y1 = self._cb_rect
        if event.type is EventType.MOUSE_CLICK and x0 <= event.x < x1 \
                and y0 <= event.y < y1:
            self.checkbox.toggle()
            self._render()
            return
        if self._body_rect.contains(event.x, event.y):
            local = event.translated(-self._body_rect.x, -self._body_rect.y)
            self.md.handle_event(local)
            self._render()
            return
        w, h = self._size
        if event.type is EventType.MOUSE_CLICK and not (
                0 <= event.x < w and 0 <= event.y < h):
            self._finish()  # click outside the dialog dismisses it

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()


def show_tips_dialog(panel: Any, *, index: int = 0, dont_show: bool = False,
                     resolve: Callable[[str], str] | None = None,
                     on_result: Callable[[int, bool], None] | None = None,
                     z: int = 70) -> TipsDialog:
    """Push a modal :class:`TipsDialog` over ``panel``, opened at tip ``index``
    (modulo the rotation), and return it. ``dont_show`` pre-checks the startup
    opt-out; ``resolve`` maps keymap actions to display key labels for the
    ``{key:...}`` placeholders. On close, ``on_result(index, dont_show)``
    reports the last tip viewed and the checkbox state."""
    dialog = TipsDialog(index=index, dont_show=dont_show, resolve=resolve,
                        on_result=on_result)
    dialog.show(panel, z=z)
    return dialog
