"""ISearchBar — the incremental-search input, rendered *in* the pane footer.

Unlike the other prompts (which are centered modals), isearch has to sit exactly
on the active pane's footer bar — same slot, same size — while the file list
above it stays fully visible and its cursor keeps moving as you type. So the
controller pushes this widget as a thin overlay layer positioned at the footer's
captured rect (see ``XeFMApp.enter_isearch``).

Being the top layer makes it the focus root, which is what lets its ``TextEdit``
engage the IME and blink a caret — a plain in-footer draw could do neither.

Layout is one row: a bold prompt on the left and the editable pattern field
stretched across the rest. ``Up``/``Down`` walk the match set (they never reach
the single-line field); ``Enter`` stops at the current match (the controller also
records the pattern in the filter history); ``Esc`` (or a click outside) cancels.
The controller owns what those outcomes mean and passes them in as callbacks.
"""

from __future__ import annotations

from typing import Callable

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, focus_on_click
from puikit.panel import Rect
from puikit.widgets.base import Widget
from puikit.widgets.text_edit import TextEdit

# Context rows kept visible above and below the match a search jumps to.
SEARCH_SCROLL_MARGIN = 3


def match_scroll_top(top: float, row: int, view_h: int,
                     margin: int = SEARCH_SCROLL_MARGIN) -> float:
    """Scroll position that keeps a search match visible *with context*.

    Returns the new ``top`` for a viewer jumping to the match at display row
    ``row``: unchanged when the row already sits at least ``margin`` rows from
    both edges of the ``view_h``-row viewport (issue #321 — landing a match on
    the very first or last row hid the lines around it), otherwise the scroll
    that puts the row at the viewport's vertical center, so a far jump lands
    with equal context above and below instead of hugging an edge. The margin
    shrinks on short viewports so the row itself always stays visible. The
    caller clamps the result to its content bounds, which is also what lets
    the centering collapse at the very start and end of the document.
    PuiKit's rich viewers (Markdown / JSON / table) follow the same rule via
    ``puikit/widgets/_scroll.py``.
    """
    m = min(margin, max(0, (view_h - 1) // 2))
    t = int(top)
    if t + m <= row <= t + (view_h - 1) - m:
        return top
    return float(row - (view_h - 1) // 2)


class ISearchBar(FocusContainer, Widget):
    """One-row footer overlay: prompt + pattern field. Construct it and push it as
    a layer at the footer's rect; it owns layout, focus, and key routing, and
    reports outcomes through the callbacks."""

    focusable = True
    # Responds to keys on its own (escape, up/down) so it stays a focus stop.
    focus_stop_when_empty = True

    def __init__(
        self,
        *,
        text: str = "",
        prompt: str = "I-Search:",
        surface: str = "status",
        on_change: Callable[[str], None] | None = None,
        on_navigate: Callable[[int], None] | None = None,
        on_submit: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        get_status: Callable[[], tuple[int, int]] | None = None,
    ):
        self.prompt = prompt
        self.surface = surface
        #: Live pattern edits (every keystroke), for the incremental jump.
        self.on_change = on_change
        #: ``-1`` (Up) / ``+1`` (Down) — walk to the previous / next match.
        self.on_navigate = on_navigate
        #: Enter in the field: accept the current match and close.
        self.on_submit = on_submit
        #: Esc / outside click: cancel and restore the pre-search cursor.
        self.on_cancel = on_cancel
        #: Returns ``(position, total)`` for the match counter on the right edge —
        #: the 1-based index of the cursor within the matches, and the match count.
        self.get_status = get_status

        self._panel = None
        self.edit = TextEdit(text=text, on_change=self._edit_changed,
                             on_submit=self._edit_submitted)
        self.edit.cursor = len(text)
        self._focused = self.edit
        self._edit_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._size: tuple[float, float] = (0.0, 0.0)

    @property
    def pattern(self) -> str:
        return self.edit.text

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[object]:
        return [self.edit]

    # --- child callbacks -----------------------------------------------------

    def _edit_changed(self, text: str) -> None:
        if self.on_change is not None:
            self.on_change(text)

    def _edit_submitted(self, _text: str) -> None:
        if self.on_submit is not None:
            self.on_submit()

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme
        wu, hu = ctx.size_units
        # The layer was pushed with a "surface" hint, so the Panel has already
        # filled the row with the status background; the prompt uses the same
        # text color the footer draws on that bar (NOT the accent — on the GUI
        # theme the status surface *is* the accent, so accent text would vanish).
        bg = theme.surface_bg(self.surface) if theme is not None else None
        fg = theme.text if theme is not None else None

        label = f"  {self.prompt}  "
        ctx.draw_text(0, 0, label, Style(bg=bg, fg=fg, attr=TextAttribute.BOLD))
        label_w = ctx.measure_text(label)

        # Match counter "position/total" pinned to the right edge (same background
        # as the footer). Always shown while searching; "0/0" reads as no matches
        # (and is what an empty pattern shows too).
        status = ""
        if self.get_status is not None:
            pos, total = self.get_status()
            status = f"{pos}/{total}"
        status_style = Style(bg=bg, fg=fg)
        status_w = ctx.measure_text(status, status_style) if status else 0.0
        right_reserve = status_w + 2.0 if status else 0.0
        if status:
            ctx.draw_text(wu - status_w - 1.0, 0, status, status_style)

        edit_x = label_w
        edit_w = max(1.0, wu - edit_x - right_reserve)
        self.edit.width = edit_w
        self._edit_rect = Rect(edit_x, 0.0, edit_w, hu)
        ctx.draw_child(self.edit, edit_x, 0, edit_w, hu,
                       hints={"focused": self._focused is self.edit})

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.IME_COMPOSITION:
            # Forward IME composition (preedit) to the field so CJK input renders
            # inline; the bar is the top layer and receives every event, so it must
            # relay composition to the field itself.
            self.edit.handle_event(event)
            return True
        if event.type is EventType.KEY:
            key = event.key
            if key == "escape":
                if self.on_cancel is not None:
                    self.on_cancel()
            elif key in ("up", "down"):
                # Match navigation — the single-line field has no use for vertical
                # arrows anyway.
                if self.on_navigate is not None:
                    self.on_navigate(-1 if key == "up" else 1)
            else:
                # Everything else goes to the field: typing / editing (which fires
                # on_change / on_submit).
                self.edit.handle_event(event)
            return True

        if event.type in (
            EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
            EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL,
        ):
            if event.x is not None and self._edit_rect.contains(event.x, event.y):
                if event.type is EventType.MOUSE_DOWN:
                    focus_on_click(self, self.edit)
                self.edit.handle_event(
                    event.translated(-self._edit_rect.x, -self._edit_rect.y))
                return True
            # A click outside the bar entirely dismisses it (like the modals).
            if event.type is EventType.MOUSE_CLICK and event.x is not None and not (
                0 <= event.x < self._size[0] and 0 <= event.y < self._size[1]
            ):
                if self.on_cancel is not None:
                    self.on_cancel()
            return True
        return True  # modal: swallow everything else


class ViewerISearch:
    """Drives an :class:`ISearchBar` for a full-window modal viewer (text / diff).

    The viewer owns match computation and highlighting; this owns the bar's
    lifecycle — building it, pushing it as a thin overlay pinned to the viewer's
    footer row, and tearing it down on Enter / Esc — so both viewers get the main
    file manager's incremental-search UX without each re-implementing the
    plumbing (the same reason the main window's search lives in ``ISearchBar``).

    The viewer supplies five callbacks:
        recompute(pattern): fired live on every keystroke — recompute the match
            set, repaint highlights, and jump to the nearest match.
        navigate(delta):    Up (``-1``) / Down (``+1``) — walk to the prev / next
            match.
        status():           returns ``(position, total)`` for the bar's counter.
        accept():           Enter — keep the current match; clear the search chrome.
        cancel():           Esc / outside click — restore the pre-search view.
    """

    def __init__(self, *, recompute, navigate, status, accept, cancel):
        self._recompute = recompute
        self._navigate = navigate
        self._status = status
        self._accept = accept
        self._cancel = cancel
        self.active = False
        self._bar: ISearchBar | None = None
        self._panel = None

    def open(self, panel, footer_rect, z: int) -> None:
        """Open the search bar over ``footer_rect`` (``(x, y, w, h)`` in the
        panel's size units, e.g. the viewer's footer row). No-op when already open
        or the footer hasn't been captured yet (nothing to anchor to)."""
        if self.active or panel is None or footer_rect is None:
            return
        self.active = True
        self._panel = panel
        self._bar = ISearchBar(
            on_change=self._recompute,
            on_navigate=self._navigate,
            on_submit=self._accept_and_close,
            on_cancel=self._cancel_and_close,
            get_status=self._status,
        )
        x, y, w, h = footer_rect
        # Pinned over the footer with the "status" surface so it reads as the
        # viewer's bottom bar; z sits above the viewer's own layer so it becomes
        # the focus root (its TextEdit engages the IME and blinks a caret).
        panel.push_layer(self._bar, z=z,
                         hints={"surface": "status", "x": x, "y": y, "w": w, "h": h})
        panel.render()

    @property
    def pattern(self) -> str:
        return self._bar.pattern if self._bar is not None else ""

    def _teardown(self) -> None:
        self.active = False
        panel = self._panel
        if (panel is not None and panel.has_layers
                and panel._layers[-1].widget is self._bar):
            panel.pop_layer()
        self._bar = None

    def _accept_and_close(self) -> None:
        self._teardown()
        self._accept()

    def _cancel_and_close(self) -> None:
        self._teardown()
        self._cancel()
