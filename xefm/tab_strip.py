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
read here, ``ctx.vector_shapes``, only rounds the chips' corners.

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
#: the text row and 15% of one above and below it. A terminal's is one row.
TAB_HEIGHT_GUI = 1.3


#: The least lightness difference (CIE L*, 0-100) a strip keeps: its ground
#: from the bands it meets (the path bar, the other strip), the current tab
#: from the ground it shows on. Taken from the theme's colours alone, a theme
#: whose header and page are one colour (Segment LCD) gave three bands and
#: two kinds of chip that could not be told apart (#1019 hand check).
GROUND_SEPARATION = 7.0
CURRENT_SEPARATION = 14.0
#: The least opacity a strip's ground keeps over a scene (a wallpaper, an
#: animated background): at a theme's own surface opacity (0.2 - 0.6) the
#: ground was the scene, and a chip in the page colour vanished into it.
GROUND_OPACITY = 0.8


@dataclass(frozen=True)
class StripColors:
    """A tab strip's fills: its ``ground``, the ``current`` tab's, the
    ``idle`` tabs', and the least opacity the ground keeps over a scene."""

    ground: tuple
    current: tuple
    idle: tuple
    ground_opacity: float


def _lightness(color) -> float:
    """CIE L* (0 black - 100 white) of an sRGB colour."""
    def linear(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in tuple(color)[:3])
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 116.0 * (y ** (1.0 / 3.0) if y > 0.008856 else 7.787 * y + 16.0 / 116.0) - 16.0


def _set_apart(color, margin, lighter: bool) -> tuple:
    """``color``, or the nearest colour toward white (``lighter``) or black
    for which ``margin(c)`` - how far it clears what it must keep apart from,
    negative while it does not - is no longer negative; the other way when
    that end cannot get there; the one that came closest when neither can."""
    color = tuple(color)[:3]
    if margin(color) >= 0:
        return color
    best = color
    for toward in ((255, 255, 255), (0, 0, 0)) if lighter else ((0, 0, 0), (255, 255, 255)):
        for step in range(1, 41):
            moved = _mix(color, toward, step / 40)
            if margin(moved) >= 0:
                return moved
            if margin(moved) > margin(best):
                best = moved
    return best


def _apart(least: float, *others):
    """A ``margin`` for :func:`_set_apart`: lightness ``least`` from each of
    ``others``."""
    lights = [_lightness(o) for o in others]
    return lambda c: min(abs(_lightness(c) - l) for l in lights) - least


def strip_colors(theme, *, pane: bool = False, opacity: float = 1.0) -> StripColors:
    """The fills of a tab strip on ``theme`` (``pane``: a pane's, under the
    window's), its surfaces painted at ``opacity`` (the theme's, below 1 over
    a scene).

    The current tab wears the page - the content surface the panes, a
    terminal and a conversation paint - so it reads as the one shown below.
    The grounds are stacked from the header band a title sits on toward the
    text, by lightness: a pane's strip apart from its path bar, the window's
    apart from both - and each, as it is seen, apart from the page the
    current tab wears: over a scene it
    keeps :data:`GROUND_OPACITY` and the page shows through the rest. Only
    where the ground cannot get far enough does the current tab move off the
    page. The idle tabs stand halfway between, so every kind of chip has an
    edge (#563, #620, #1019 hand checks)."""
    page = tuple(theme.surface_bg("content") or DEFAULT_BG)[:3]
    header = theme.surface_bg("header")
    header = tuple(header)[:3] if header is not None else _mix(page, theme.text, 0.08)
    text_lighter = _lightness(theme.text) > _lightness(page)
    ground_opacity = max(GROUND_OPACITY, opacity) if opacity < 1.0 else 1.0

    def seen(ground):
        return _mix(page, ground, ground_opacity)

    def ground_margin(*bands):
        bands_apart = _apart(GROUND_SEPARATION, *bands)
        page_apart = _apart(CURRENT_SEPARATION, page)
        return lambda c: min(bands_apart(c), page_apart(seen(c)))

    # Stacked toward the text, one step per band: the path bar, then a pane's
    # strip, then the window's above it - the same order on every theme.
    pane_ground = _set_apart(header, ground_margin(header), lighter=text_lighter)
    window = _set_apart(pane_ground, ground_margin(header, pane_ground), lighter=text_lighter)
    ground = pane_ground if pane else window
    under = seen(ground)
    lighter = (_lightness(page) > _lightness(under)
               if abs(_lightness(page) - _lightness(under)) > 0.5 else text_lighter)
    current = _set_apart(page, _apart(CURRENT_SEPARATION, under), lighter=lighter)
    return StripColors(ground, current, _mix(under, current, 0.5), ground_opacity)


def _snap_row(ctx, y: float, height: float) -> tuple[float, float, float]:
    """``(y, height, text_y)`` for a row of chips ``height`` high at ``y``:
    the text row centred in it. Where the backend draws sub-cell, the chip's
    edges land on whole device pixels and the text's baseline a fixed whole
    number of pixels below its top: the OS puts a baseline on a whole pixel
    and a chip's edge where it falls, so a strip whose place had a fraction
    in it showed its labels a pixel or two low (#1019 hand check: a pane's
    tabs under the window's)."""
    text_y = y + (height - 1.0) / 2
    if not getattr(ctx, "vector_shapes", False):
        return y, height, text_y
    bh = (getattr(ctx, "base_size", None) or (0, 0))[1]
    rect = getattr(ctx, "screen_rect", None)
    if not bh or rect is None:
        return y, height, text_y
    top = rect[1]
    top_px = round((top + y) * bh)
    height_px = round(height * bh)
    try:
        ascent = ctx.font_metrics().ascent
    except (AttributeError, NotImplementedError):
        ascent = 0.8
    # The baseline, centred as the text row is, then made whole relative to
    # the chip's top - the same offset in every strip.
    baseline_px = top_px + round(((height - 1.0) / 2 + ascent) * bh)
    y = top_px / bh - top
    text_y = (baseline_px - ascent * bh) / bh - top
    return y, height_px / bh, text_y


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

    #: The rounding of a tab's corners, in device pixels, where the
    #: backend draws vector shapes.
    RADIUS_PX = 6.0
    #: The gap between two chips, in base units.
    GAP = 1.0
    #: How far a press must travel along the strip before it drags its tab.
    DRAG_THRESHOLD = 1.0
    #: The glyphs a tab's lead is drawn with - the hosts' icons and the
    #: marks that take their place. The lead gets the room of the widest, so
    #: a mark coming or going does not resize its tab and move the rest
    #: (#1019 hand check); a lead not listed here widens the room for itself.
    LEAD_SAMPLES = "▤$>✦⚠✓…▸▣⌕≡"

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
             ground=None, current_bg=None, height: float = 1.0,
             colors: "StripColors | None" = None) -> None:
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
        hand checks). Text is inked against the chip it sits on. ``colors``
        (:func:`strip_colors`) gives all three, and the least opacity the
        ground keeps over a scene, in place of ``ground`` and ``current_bg``."""
        tabs = [t if isinstance(t, Tab) else Tab(str(t)) for t in tabs]
        theme = ctx.theme
        if current_bg is None:
            current_bg = ctx.background or DEFAULT_BG
        if ground is None:
            ground = theme.surfaces.get("content", DEFAULT_BG)
        idle_bg = _mix(ground, current_bg, 0.5)
        ground_opacity = None
        if colors is not None:
            ground, current_bg, idle_bg = colors.ground, colors.current, colors.idle
            if colors.ground_opacity < 1.0:
                ground_opacity = colors.ground_opacity
        idle_fg = ctx.ink(theme.muted_text, on=idle_bg, target=LC_LARGE)
        current_fg = ctx.ink(theme.accent if emphasis else theme.text, on=current_bg,
                             target=LC_BODY)
        bottom = ground_height if ground_height is not None else y + height
        y, height, ty = _snap_row(ctx, y, height)
        if ground_opacity is None:
            ctx.fill_rect(0.0, 0.0, ctx.size_units[0], bottom, Style(bg=ground))
        else:
            ctx.fill_rect(0.0, 0.0, ctx.size_units[0], bottom, Style(bg=ground),
                          opacity=ground_opacity)
        gap = self.GAP
        # The inset at each end of a chip, and the room between the icon, the
        # label and the close button: roomy where the backend draws sub-cell,
        # whole cells on a grid - where a fraction would floor to nothing on
        # one side and leave it all on the other (#563 hand check).
        inset = 1.0
        sep = 0.75 if ctx.vector_shapes else 1.0
        # The current tab's label is bold, and bold is wider on a proportional
        # font. Every tab is sized and elided as if bold, so a tab keeps its
        # width and place whichever one is current: switching tabs moved them
        # all a little (#1019 hand check).
        bold = Style(attr=TextAttribute.BOLD)

        def measure_bold(text):
            return ctx.measure_text(text, bold)

        # A tab is: inset, [lead, sep], label, [sep, close], inset. The lead
        # and the close button keep their width when the tabs are squeezed;
        # the label gives way.
        close_w = ctx.measure_text(CLOSE_GLYPH)
        lead_w = max([ctx.measure_text(g) for g in self.LEAD_SAMPLES]
                     + [ctx.measure_text(t.lead) for t in tabs if t.lead] + [0.0])

        def fixed(t: Tab) -> float:
            w = 2 * inset
            if t.lead:
                w += lead_w + sep
            if t.closable:
                w += sep + close_w
            return w

        widths = [fixed(t) + measure_bold(t.label) for t in tabs]
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
            shown = label if measure_bold(label) <= room + 1e-6 else \
                elide(label, room, where="end", measure=measure_bold)
            chip = current_bg if i == current else idle_bg
            if ctx.vector_shapes:
                # Rounded at all four corners (#1019 hand check).
                ctx.round_rect(x, y, w, height, Style(bg=chip), radius=self.RADIUS_PX,
                               hints={"fill": True})
            else:
                ctx.fill_rect(x, y, w, height, Style(bg=chip))
            if i == current:
                style = Style(fg=current_fg, bg=chip, attr=TextAttribute.BOLD)
            else:
                style = Style(fg=idle_fg, bg=chip)
            quiet = Style(fg=current_fg if i == current else idle_fg, bg=chip)
            cx = x + inset
            if tab.lead:
                # Centred in its room (whole cells on a grid).
                off = (lead_w - ctx.measure_text(tab.lead)) / 2
                if not ctx.vector_shapes:
                    off = float(int(off))
                ctx.draw_text(cx + off, ty, tab.lead, quiet, ink=False)
                cx += lead_w + sep
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
