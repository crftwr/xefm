"""The tab strip XeFM draws: a pane's folder tabs and a screen group's tabs
(discussion #1019).

One look for both: a chip per tab with a gap between chips, the strip's
ground set back from the surface below it, the current tab in that surface's
own colour so it runs on into the row beneath like a browser's tab, the
others halfway between ground and surface with muted text. When the tabs do
not all fit, each gets an equal share and its label is elided to it.

This is XeFM's own drawing, not a PuiKit widget, by decision (#1019): PuiKit's
``Tabs`` is a dialog's page switcher - it takes focus and the arrow keys and
holds the page under it - while these strips take no focus and no keys, and
the host decides which tab is current and how loud it is. The one capability
read here, ``ctx.vector_shapes``, only rounds the chips' top corners.

:class:`TabStrip` draws and remembers where each tab landed, so the host can
tell which tab a click hit (:meth:`TabStrip.hit`).
"""

from __future__ import annotations

from dataclasses import dataclass

from puikit import Style, TextAttribute
from puikit.text import elide

from xefm.file_pane import DEFAULT_BG, LC_BODY, LC_LARGE, _mix


#: What a closable tab's close button says.
CLOSE_GLYPH = "×"
#: What the chip after the tabs says: open another one.
NEW_TAB = "+"
#: A tab's height in rows where the backend draws sub-row (the desktop app):
#: the text row and 30% of one above and below it. A terminal's is one row.
TAB_HEIGHT_GUI = 1.6


def tab_height(ctx) -> float:
    """A tab's height in base units in ``ctx``: :data:`TAB_HEIGHT_GUI` where
    it draws vector shapes, one row on a grid."""
    return TAB_HEIGHT_GUI if ctx.vector_shapes else 1.0


@dataclass
class Tab:
    """One tab: its label and, optionally, what is drawn in front of it - an
    ``icon`` saying what the tab is, which a ``mark`` (``⚠``, ``✓``: the
    status bar's marks for a session out of view) takes the place of while
    there is one - and a close button after it (``closable``)."""

    label: str
    mark: str = ""
    icon: str = ""
    closable: bool = False

    @property
    def lead(self) -> str:
        """What stands in front of the label: the mark, else the icon."""
        return self.mark or self.icon


class TabStrip:
    """A row of tabs, drawn on demand. Keeps the last draw's row and each
    tab's span for :meth:`hit`."""

    #: The rounding of a tab's top corners, in device pixels, where the
    #: backend draws vector shapes.
    RADIUS_PX = 6.0
    #: The gap between two chips, in base units.
    GAP = 1.0
    #: How far a press must travel along the strip before it drags its tab.
    DRAG_THRESHOLD = 1.0

    def __init__(self) -> None:
        #: The row drawn last, ``(y0, y1)`` in the drawing context's units,
        #: or None when nothing was drawn.
        self.row: tuple[float, float] | None = None
        #: Each tab's ``(x0, x1, index)`` from the last draw.
        self.hits: list[tuple[float, float, int]] = []
        #: Each close button's ``(x0, x1, index)`` from the last draw.
        self.close_hits: list[tuple[float, float, int]] = []
        #: The tab pressed (and, once it moved, dragged): its index, the x
        #: the press began at, whether it is being dragged. None between
        #: presses.
        self._press: list | None = None
        #: Where the dragged tab would go if dropped now: the gap before tab
        #: ``n`` (``count`` for after the last), shown as a line; None while
        #: nothing is dragged or the drop would leave it where it is.
        self.drop_slot: int | None = None
        #: Set when a drag ended, so the click the release brings is not
        #: also a click on the tab.
        self._dragged = False

    def clear(self) -> None:
        """Nothing drawn this frame: no tab can be hit."""
        self.row = None
        self.hits = []
        self.close_hits = []

    def hit_close(self, x: float, y: float) -> int | None:
        """The index of the tab whose close button is at ``(x, y)``, or None."""
        if self.row is None or not self.row[0] <= y < self.row[1]:
            return None
        for x0, x1, index in self.close_hits:
            if x0 <= x < x1:
                return index
        return None

    def hit(self, x: float, y: float) -> int | None:
        """The index of the tab at ``(x, y)`` (the same units it was drawn
        in), or None: off the row, or between chips."""
        if self.row is None or not self.row[0] <= y < self.row[1]:
            return None
        for x0, x1, index in self.hits:
            if x0 <= x < x1:
                return index
        return None

    # --- dragging a tab to another place ----------------------------------

    def press(self, x: float, y: float, count: int, first: int = 0) -> bool:
        """A press at ``(x, y)``: arm a drag of the tab under it - one of
        tabs ``first`` to ``count - 1`` (not a pinned one before ``first``,
        not ``+``), and not on its close button. Whether it armed one."""
        self._dragged = False
        self._first = first
        index = self.hit(x, y)
        if index is None or not first <= index < count or self.hit_close(x, y) is not None:
            self._press = None
            return False
        self._press = [index, x, False]
        return True

    def drag(self, x: float, count: int) -> bool:
        """The pointer moved to ``x`` with the press held. Once it has
        travelled far enough it drags the tab, and the gap it would land in
        - before the first tab whose middle is past ``x`` - is shown as a
        line (:attr:`drop_slot`). Whether that changed, so the caller
        redraws."""
        if self._press is None:
            return False
        index, x0, moving = self._press
        if not moving:
            if abs(x - x0) < self.DRAG_THRESHOLD:
                return False
            self._press[2] = True
        spans = sorted((h for h in self.hits if h[2] < count), key=lambda h: h[2])
        slot = sum(1 for x0_, x1_, _ in spans if (x0_ + x1_) / 2 < x)
        slot = max(slot, getattr(self, "_first", 0))  # never before a pinned tab
        if slot in (index, index + 1):
            slot = None  # dropped there it stays where it is
        changed = slot != self.drop_slot
        self.drop_slot = slot
        return changed

    def release(self) -> tuple[int, int] | None:
        """The press ended: ``(from, to)`` when the dragged tab was dropped in
        another place (the caller moves it), else None. A press that dragged
        makes the click the release brings no click (:meth:`take_click`)."""
        press, slot = self._press, self.drop_slot
        self._press = None
        self.drop_slot = None
        self._dragged = bool(press is not None and press[2])
        if press is None or slot is None:
            return None
        frm = press[0]
        return frm, (slot if slot < frm else slot - 1)

    @property
    def dragging(self) -> bool:
        return self._press is not None and self._press[2]

    def take_click(self) -> bool:
        """Whether a click should act: not the one ending a drag."""
        if self._dragged:
            self._dragged = False
            return False
        return True

    def on_row(self, y: float) -> bool:
        return self.row is not None and self.row[0] <= y < self.row[1]

    def draw(self, ctx, tabs: list, current: int, x: float, y: float, avail: float,
             *, emphasis: bool, ground_height: float | None = None,
             ground=None, current_bg=None, height: float = 1.0) -> None:
        """Draw ``tabs`` (:class:`Tab`, or plain labels) ``height`` units high
        (one row by default; the text is centred in it) at ``(x, y)`` in
        ``avail`` units, ``current`` the one in front. The
        current label is bold, in the accent when ``emphasis`` (the active
        pane, the screen on now). The ground fills the context's whole width
        from the top down to ``ground_height`` (the row's bottom by default),
        so the strip reads as one band. ``current_bg`` is the colour of the
        surface the strip sits on (the context's background by default), which
        the current tab wears to run on into it; ``ground`` the strip's own,
        set back from it (the ``content`` surface by default).

        Three distinct fills - ground, idle tab, current tab - so every tab
        has an edge and the current one is plain on any theme (#563, #620
        hand checks). Text is inked against the chip it sits on."""
        tabs = [t if isinstance(t, Tab) else Tab(str(t)) for t in tabs]
        theme = ctx.theme
        if current_bg is None:
            current_bg = ctx.background or DEFAULT_BG
        if ground is None:
            ground = theme.surfaces.get("content", DEFAULT_BG)
        idle_bg = _mix(ground, current_bg, 0.5)
        idle_fg = ctx.ink(theme.muted_text, on=idle_bg, target=LC_LARGE)
        current_fg = ctx.ink(theme.accent if emphasis else theme.text, on=current_bg,
                             target=LC_BODY)
        bottom = ground_height if ground_height is not None else y + height
        ty = y + (height - 1.0) / 2  # the text row, centred in the chip
        ctx.fill_rect(0.0, 0.0, ctx.size_units[0], bottom, Style(bg=ground))
        gap = self.GAP
        # The inset at each end of a chip, and the room between the icon, the
        # label and the close button: roomy where the backend draws sub-cell,
        # whole cells on a grid - where a fraction would floor to nothing on
        # one side and leave it all on the other (#563 hand check).
        inset = 1.0
        sep = 0.75 if ctx.vector_shapes else 1.0
        # The current tab's label is bold, and bold is wider on a proportional
        # font: it is measured, and elided, in that style.
        bold = Style(attr=TextAttribute.BOLD)

        def measure_of(i):
            if i == current:
                return lambda text: ctx.measure_text(text, bold)
            return ctx.measure_text

        # A tab is: inset, [lead, sep], label, [sep, close], inset. The lead
        # and the close button keep their width when the tabs are squeezed;
        # the label gives way.
        close_w = ctx.measure_text(CLOSE_GLYPH)

        def fixed(t: Tab) -> float:
            w = 2 * inset
            if t.lead:
                w += ctx.measure_text(t.lead) + sep
            if t.closable:
                w += sep + close_w
            return w

        widths = [fixed(t) + measure_of(i)(t.label) for i, t in enumerate(tabs)]
        if tabs:
            share = (avail - gap * (len(tabs) - 1)) / len(tabs)
            if sum(widths) + gap * (len(tabs) - 1) > avail:
                widths = [min(w, max(share, fixed(t), 2.0)) for t, w in zip(tabs, widths)]
        self.row = (y, y + height)
        self.hits = []
        self.close_hits = []
        left = x
        for i, (tab, w) in enumerate(zip(tabs, widths)):
            if x >= left + avail:
                break
            w = min(w, left + avail - x)
            room = max(0.0, w - fixed(tab))
            label = tab.label
            # A label that fits exactly stays whole: elide's own comparison
            # can lose it to rounding, and a one-glyph label (``+``) then
            # vanished altogether.
            shown = label if measure_of(i)(label) <= room + 1e-6 else \
                elide(label, room, where="end", measure=measure_of(i))
            chip = current_bg if i == current else idle_bg
            if ctx.vector_shapes:
                # Rounded on top only, the way a tab is: a fully rounded face,
                # then its lower half filled square. Per-corner rounding is not
                # something every vector backend draws (Windows' does not).
                ctx.round_rect(x, y, w, height, Style(bg=chip), radius=self.RADIUS_PX,
                               hints={"fill": True})
                ctx.fill_rect(x, y + height / 2, w, height / 2, Style(bg=chip))
            else:
                ctx.fill_rect(x, y, w, height, Style(bg=chip))
            if i == current:
                style = Style(fg=current_fg, bg=chip, attr=TextAttribute.BOLD)
            else:
                style = Style(fg=idle_fg, bg=chip)
            quiet = Style(fg=current_fg if i == current else idle_fg, bg=chip)
            cx = x + inset
            if tab.lead:
                ctx.draw_text(cx, ty, tab.lead, quiet, ink=False)
                cx += ctx.measure_text(tab.lead) + sep
            ctx.draw_text(cx, ty, shown, style, ink=False)
            if tab.closable:
                bx = x + w - inset - close_w
                # The button - what a click hits and what the backing covers
                # under the pointer, one and the same: a little wider than
                # the glyph where the backend draws sub-cell, exactly its cell
                # on a grid (a half cell there would round onto the next one).
                pad = sep / 2 if ctx.vector_shapes else 0.0
                self.close_hits.append((bx - pad, bx + close_w + pad, i))
                # Shown only while the pointer is over the tab, as a browser's
                # or VS Code's; its room is kept either way, so the tabs do
                # not shift. Over the button itself it gets a backing.
                if ctx.pointer_in(x, y, w, height):
                    glyph_style = quiet
                    if ctx.pointer_in(bx - pad, y, close_w + 2 * pad, height):
                        backing = _mix(chip, theme.text, 0.15)
                        ctx.fill_rect(bx - pad, ty, close_w + 2 * pad, 1.0, Style(bg=backing))
                        # On the backing: on a grid the glyph's own cell
                        # background is what shows, so it must be the backing.
                        glyph_style = Style(fg=quiet.fg, bg=backing)
                    ctx.draw_text(bx, ty, CLOSE_GLYPH, glyph_style, ink=False)
            self.hits.append((x, x + w, i))
            x += w + gap
        self._draw_drop_line(ctx, y, height, gap)

    def _draw_drop_line(self, ctx, y: float, height: float, gap: float) -> None:
        """Where a dragged tab would land: a line in the accent, in the gap
        before tab :attr:`drop_slot` (after the last one for the slot past
        it), as tall as the tabs. A pixel line where the backend draws
        sub-cell, a box-drawing bar in the gap's cell on a grid."""
        slot = self.drop_slot
        spans = sorted(self.hits, key=lambda h: h[2])
        if slot is None or not spans:
            return
        if slot < len(spans):
            at = spans[slot][0] - gap / 2
        else:
            at = spans[slot - 1][1] + gap / 2
        accent = ctx.theme.accent
        if ctx.vector_shapes:
            bw = ctx.base_size[0] or 1
            w = 2.0 / bw
            ctx.fill_rect(at - w / 2, y, w, height, Style(bg=accent))
        else:
            ctx.draw_text(float(int(at)), y, "│", Style(fg=accent, attr=TextAttribute.BOLD),
                          ink=False)
