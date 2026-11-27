"""The tab strip over a terminal or AI agent screen (discussion #1019).

Each session's screen carries one, a layer of its own under the session's
view, at the top of the window; it lists the screens of the same group - the
terminal's, or the AI agents' - as tabs, the one on now in front, and a ``+``
last that opens another of the group. It shows only while the group has two
screens or more, the way a pane shows its folder tabs; the view below gives
up the strip's height while it does.

The layer sits above the view (PuiKit draws a screen from its topmost
``cover`` layer up, and the view is one, so a layer under it is never drawn)
but takes no events (it is not interactive): the keys and the focus stay the
view's, and a click on the strip reaches the view, above its own top edge,
which hands it back to the app (``on_strip_event``); the app asks
:meth:`ScreenStrip.hit` what was clicked. Code that looks for the topmost
layer of a screen skips it (:func:`is_strip`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from puikit.widgets.base import CONTROL_HEIGHT, Widget

from xefm.file_pane import DEFAULT_BG, _mix
from xefm.tab_strip import NEW_TAB, TAB_HEIGHT_GUI, Tab, TabStrip, tab_height

#: The inset above the tabs and at the sides, in device pixels, where the
#: backend draws them (a terminal's strip is one row, flush).
PAD_PX = 4.0

#: What :meth:`ScreenStrip.hit` returns for a tab's close button, with the
#: tab's index: ``(CLOSE, index)``.
CLOSE = "close"


def is_strip(layer: Any) -> bool:
    """Whether ``layer`` is the chrome a session's screen draws over its view
    (#1019): never what a screen shows on top."""
    return isinstance(layer, (ScreenStrip, SessionFrame))


def top_surface(panel: Any, under: Any = None) -> Any:
    """The topmost shown layer (under ``under``) that is not a screen strip,
    or None: the view, viewer or dialog a screen shows on top."""
    layers = [layer for layer in panel.shown_layers(under) if not is_strip(layer)]
    return layers[-1] if layers else None


def strip_height(backend: Any) -> float:
    """The strip's height in base units on ``backend``: one row on a grid,
    the taller tab and the inset above it where it draws vector shapes (the
    tabs stand on the strip's bottom edge)."""
    caps = getattr(backend, "capabilities", None)
    if caps is None or not caps.supports("vector_shapes"):
        return 1.0
    bh = backend.base_size[1] or 1
    return TAB_HEIGHT_GUI + PAD_PX / bh


class ScreenStrip(Widget):
    """The window's tab strip (#1019): ``tabs()`` returns the tabs
    (:class:`Tab`) - the file manager's first, pinned - and the index of the
    one on screen; the ``+`` chip is added here. It shows while there is a
    session (two tabs or more) and takes no room otherwise. One instance: the
    file manager's layout places it under the menu bar, and a session's
    :class:`SessionFrame` draws the same one at the same place."""

    focusable = False
    #: The tabs before this one stay where they are (the file manager's).
    PINNED = 1

    def __init__(self, tabs: Callable[[], tuple[list, int]],
                 on_event: Callable[[Any, float, float], bool] | None = None) -> None:
        self._tabs = tabs
        self._strip = TabStrip()
        self._count = 0
        #: Where the app handles a pointer event on the strip:
        #: ``on_event(event, x, y)`` in the strip's own units.
        self.on_event = on_event

    def shown(self) -> bool:
        return len(self._tabs()[0]) >= 2

    def measure(self, ctx, axis, available):
        from puikit.layout import SizeRequest
        if axis != "y":
            return SizeRequest()
        if not self.shown():
            return SizeRequest(min=0.0, preferred=0.0, max=0.0)
        base_h = getattr(ctx, "base_h", 0) or 0
        h = 1.0 if getattr(ctx, "snap", True) else \
            TAB_HEIGHT_GUI + (PAD_PX / base_h if base_h else 0.0)
        return SizeRequest(min=h, preferred=h, max=h)

    def draw(self, ctx) -> None:
        tabs, current = self._tabs()
        if len(tabs) < 2:
            self._strip.clear()
            self._count = 0
            return
        self._count = len(tabs)
        wu, hu = ctx.size_units
        if ctx.vector_shapes:
            bw, _bh = ctx.base_size
            pad_x = PAD_PX / bw if bw else 0.0
        else:
            pad_x = 1.0
        tab_h = tab_height(ctx)
        # The current tab wears the session's page (the content surface the
        # terminal and the conversation paint), so it runs on into it; the
        # strip's ground is the header band a viewer's title sits on, set back
        # from the page - or the page nudged toward the text where a theme
        # gives both one colour. The tabs stand on the strip's bottom edge.
        theme = ctx.theme
        page = theme.surface_bg("content") or DEFAULT_BG
        ground = theme.surface_bg("header")
        if ground is None or tuple(ground) == tuple(page):
            ground = _mix(page, theme.text, 0.08)
        self._strip.draw(ctx, [*tabs, Tab(NEW_TAB)], current, pad_x, max(0.0, hu - tab_h),
                         max(0.0, wu - 2 * pad_x), emphasis=True, ground_height=hu,
                         ground=ground, current_bg=page, height=tab_h)

    def hit(self, x: float, y: float) -> int | str | tuple | None:
        """What a click at ``(x, y)`` (the strip's own units) lands on: a tab's
        index, ``(CLOSE, index)`` for its close button, :data:`NEW_TAB`, or
        None."""
        closing = self._strip.hit_close(x, y)
        if closing is not None:
            return (CLOSE, closing)
        index = self._strip.hit(x, y)
        if index is None:
            return None
        return NEW_TAB if index == self._count else index

    # Dragging a tab to another place (the strip's own units), as
    # :class:`~xefm.tab_strip.TabStrip` keeps it; the pinned tab and the
    # ``+`` never move.

    def press(self, x: float, y: float) -> bool:
        return self._strip.press(x, y, self._count, self.PINNED)

    def drag(self, x: float) -> bool:
        return self._strip.drag(x, self._count)

    def release(self) -> tuple[int, int] | None:
        return self._strip.release()

    def take_click(self) -> bool:
        return self._strip.take_click()

    def handle_event(self, event) -> bool:
        """In the file manager's layout the strip gets its pointer events
        itself, in its own units."""
        if self.on_event is None or event.x is None or event.y is None:
            return False
        return bool(self.on_event(event, event.x, event.y))


class SessionFrame(Widget):
    """What a session's screen shows around its view (#1019): the window's
    chrome - the menu bar (where it is in the window, not the OS's), the tab
    strip, the status bar - the very widgets the file manager's layout
    places, drawn here at the same places and heights, so moving between
    screens changes only what is between them. A full-window layer over the
    view, not interactive: it draws only the bands, and the view, laid out
    between them, hands the app a pointer event that lands on one."""

    focusable = False

    def __init__(self, app: Any) -> None:
        self.app = app

    def draw(self, ctx) -> None:
        app = self.app
        wu, hu = ctx.size_units
        menu_h, strip_h, status_h = app._chrome_bands()
        if menu_h:
            ctx.draw_child(app.menu_bar, 0, 0, wu, menu_h, hints={"surface": "header"})
        if strip_h:
            ctx.draw_child(app.window_tabs, 0, menu_h, wu, strip_h)
        if status_h:
            ctx.draw_child(app.status, 0, hu - status_h, wu, status_h,
                           hints={"surface": "status"})

    def handle_event(self, event) -> bool:
        return False


def chrome_bands(backend: Any, *, menu_in_window: bool, strip: bool) -> tuple[float, float, float]:
    """The heights of a screen's chrome on ``backend``, in base units, as the
    file manager's layout measures them: the menu bar (none where the OS
    has it), the tab strip (none without a session), the status bar."""
    caps = getattr(backend, "capabilities", None)
    pixel = caps is not None and caps.supports("pixel_layout")
    base_h = backend.base_size[1] if pixel else 0
    menu_h = (CONTROL_HEIGHT if pixel else 1.0) if menu_in_window else 0.0
    strip_h = strip_height(backend) if strip else 0.0
    from xefm.app import BAR_PAD_PX
    status_h = 1.0 + (BAR_PAD_PX / base_h if base_h else 0.0)
    return menu_h, strip_h, status_h
