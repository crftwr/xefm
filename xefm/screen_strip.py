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

from puikit.widgets.base import Widget

from xefm.file_pane import DEFAULT_BG, _mix
from xefm.tab_strip import NEW_TAB, TAB_HEIGHT_GUI, Tab, TabStrip, tab_height

#: The inset above the tabs and at the sides, in device pixels, where the
#: backend draws them (a terminal's strip is one row, flush).
PAD_PX = 4.0

#: What :meth:`ScreenStrip.hit` returns for a tab's close button, with the
#: tab's index: ``(CLOSE, index)``.
CLOSE = "close"


def is_strip(layer: Any) -> bool:
    """Whether ``layer`` is a screen strip: never what a screen shows on top."""
    return isinstance(layer, ScreenStrip)


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
    """One screen's strip. ``tabs()`` returns the group's tabs (:class:`Tab`)
    and the index of this screen's, or ``([], -1)`` when the strip is not
    shown; the ``+`` chip is added here."""

    focusable = False

    def __init__(self, tabs: Callable[[], tuple[list, int]]) -> None:
        self._tabs = tabs
        self._strip = TabStrip()
        self._count = 0

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
    # :class:`~xefm.tab_strip.TabStrip` keeps it; the ``+`` never moves.

    def press(self, x: float, y: float) -> bool:
        return self._strip.press(x, y, self._count)

    def drag(self, x: float) -> bool:
        return self._strip.drag(x, self._count)

    def release(self) -> tuple[int, int] | None:
        return self._strip.release()

    def take_click(self) -> bool:
        return self._strip.take_click()

    def handle_event(self, event) -> bool:
        return False
