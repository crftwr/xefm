"""Geometry (and shared chrome) for pane-anchored dialogs.

A picker that acts on one pane (filter, favorites, drives, an input prompt) is
anchored over that pane so the user can see which side it targets. It reads as
belonging to the pane by being *centered over it*, but its width is independent
of the pane: a narrow pane (splitter dragged over) must not shrink the dialog.
The box keeps its own desired width and just leans over its target pane.

This module also owns :func:`draw_title_bar` and :func:`draw_hint_row`, the one
place every XeFM modal draws its two chrome bands, so they look identical across
the input, filter-list, scroll, and batch-rename dialogs. The two are mirrors:
a bold title above a frame-connecting rule at the top, a muted line of keys
below one at the bottom, and the content framed between them.
"""

from __future__ import annotations

from typing import Any

from puikit.backend import Style, TextAttribute
from puikit.text import elide


#: How every XeFM modal enters. Defined once here — the module that already owns
#: the shared modal chrome — so the app has a single opening gesture rather than
#: nine call sites drifting apart.
#:
#: A ``scale`` that also fades ("materialize"): the box grows from 92% to full
#: size around its own center while fading in. 92% rather than something deeper
#: because a modal is *already* the focus — the motion is there to say "this
#: arrived", not to make the user watch it travel.
#:
#: ``ease_out_expo`` is what makes it read as engineered rather than floaty:
#: ~90% of the growth happens in the first third of the duration and then it
#: glides in, so the dialog snaps to attention and settles. This is the curve the
#: Sci-Fi theme's tactical-HUD look is built on, but it suits every theme, so it
#: is the app-wide default rather than a per-theme one.
#:
#: On a terminal none of this is composited: the Panel's 2-frame policy renders
#: the same intent as one inset frame then the full box, and deliberately ignores
#: the curve (an eased midpoint would collapse the intermediate frame onto the
#: target). The app states the intent once and never branches.
_OPEN_TRANSITION = {
    "transition": "scale",
    "from_scale": 0.92,
    "fade": True,
    "easing": "ease_out_expo",
}

#: Viewers (text, diff, directory-diff) open a little faster than pickers: they
#: are full-screen and usually opened deliberately, so a shorter beat keeps them
#: from feeling like they lag behind the keystroke.
OPEN_MS_DIALOG = 180
OPEN_MS_VIEWER = 140


def animate_open(panel: Any, widget: Any, duration_ms: int = OPEN_MS_DIALOG) -> bool:
    """Play the standard XeFM modal entrance for ``widget`` on ``panel``.

    A theme may opt out of the entrance entirely with ``dialog_effect=False``
    (carried in ``Theme.extras``) — for a look whose physical metaphor has no
    room for a box that grows, such as Segment LCD, where a modal simply
    switches on. Reading it here rather than at the nine call sites keeps the
    per-theme choice a data change, matching ``text_effect``.

    Returns whether a transition was actually scheduled — ``False`` on a still
    backend, under reduced motion, or when the theme opted out, where the widget
    is simply already in its final state on the next render.
    """
    theme = getattr(panel, "theme", None)
    extras = getattr(theme, "extras", None) if theme is not None else None
    if extras is not None and not extras.get("dialog_effect", True):
        return False
    return panel.animate(widget, hints={**_OPEN_TRANSITION, "duration_ms": duration_ms})


def pane_anchored_box(
    desired_w: float,
    screen_w: float,
    region: tuple[float, float],
    *,
    margin: float = 2.0,
) -> tuple[float, float]:
    """Return ``(w, x)`` in base units for a dialog anchored over the pane whose
    column span is ``region`` (its ``(x, width)``).

    The width is ``desired_w`` regardless of the pane's width — the splitter
    position never changes the dialog's size — subject only to an on-screen cap
    that keeps a ``margin`` on each side. The box is centered on the pane's
    center so it leans over the pane it acts on (near a screen edge the on-screen
    clamp shifts it inward, but it stays over its target pane rather than the
    other)."""
    region_x, region_w = region
    w = min(desired_w, max(1.0, screen_w - 2.0 * margin))
    center = region_x + region_w / 2.0
    if w >= screen_w - 2.0 * margin:
        # Too wide to keep both margins: center it in the whole window.
        x = max(0.0, (screen_w - w) / 2.0)
    else:
        x = max(margin, min(center - w / 2.0, screen_w - w - margin))
    return w, x


# Vector (GUI) title-bar metrics, in base units. On a character grid the title
# and the rule each need a whole cell (title on row ``y``, rule on ``y+1``,
# content on ``y+2``). On a vector backend those full base-unit rows read as an
# airy, over-tall header with the proportional title floating in its cell, so the
# bar is sized to the *measured* title line instead: a small equal pad above and
# below the title's line box (so it reads balanced and thin), then the rule, then
# the content a gap below.
_GUI_TITLE_PAD = 0.18     # equal pad above/below the title line box
_GUI_CONTENT_GAP = 0.65   # gap from the rule down to the first content row


def gui_title_bar_height(ctx: Any, title_style: Any) -> float:
    """Height (base units) of the vector title bar: the title line box framed by
    an equal pad above and below. Shared with a dialog's size calculation so the
    box reserves exactly what :func:`draw_title_bar` draws."""
    return ctx.line_height(title_style) + 2.0 * _GUI_TITLE_PAD


def draw_title_bar(
    ctx: Any,
    title: str,
    *,
    surface_bg: Any,
    border: Any,
    y: float = 1.0,
) -> float:
    """Draw a modal's title bar and return the first content row.

    The bar is a bold ``title`` with a frame-connecting rule just beneath it, so
    the title reads as a distinct band separated from the content instead of
    floating above it. The rule joins the box frame at both ends (tee glyphs on a
    grid, a full-width stroke on a vector backend) and is drawn in ``border`` (the
    popup frame color) on the dialog surface — ``surface_bg`` both pins the title
    to that surface and backs the rule so it never sits on the layer's default
    (darker) fill. On a grid the title, rule, and content take whole rows
    (``y``, ``y+1``, ``y+2``); on a vector backend the bar is sized to the measured
    title line (see the ``_GUI_*`` metrics) so it is thin and vertically balanced."""
    title_style = Style(bg=surface_bg, attr=TextAttribute.BOLD)
    rule_style = Style(fg=border, bg=surface_bg)
    if ctx.vector_shapes:
        # Center the title's line box in the bar: an equal pad above and below,
        # the rule at the bar's bottom edge, content a small gap under it.
        ctx.draw_text(2, _GUI_TITLE_PAD, title, title_style)
        rule_y = gui_title_bar_height(ctx, title_style)
        ctx.draw_frame_divider(rule_y, style=rule_style)
        return rule_y + _GUI_CONTENT_GAP
    ctx.draw_text(2, y, title, title_style)
    ctx.draw_frame_divider(y + 1.0, style=rule_style)
    return y + 2.0


def hint_style(ctx: Any, surface_bg: Any) -> Any:
    """The hint bar's text style: muted, on the dialog surface. Built here rather
    than at each call site because the bar's *height* is measured from it, the
    way the title bar's is measured from the title's."""
    theme = ctx.theme
    return Style(fg=theme.muted_text if theme else None, bg=surface_bg)


def gui_hint_bar_height(ctx: Any, style: Any) -> float:
    """Height (base units) of the vector hint bar — the title bar's mirror: the
    hint's line box framed by the same equal pad above and below, so the two
    bands read as a matched pair rather than one being visibly heavier."""
    return ctx.line_height(style) + 2.0 * _GUI_TITLE_PAD


def hint_content_bottom(ctx: Any, surface_bg: Any) -> float:
    """The y a modal's content must stop at, above its hint bar.

    The mirror of what :func:`draw_title_bar` returns: the content lives between
    the two rules, a ``_GUI_CONTENT_GAP`` clear of each on a vector backend and
    flush against the rule row on a grid, which spends no fractions of a row."""
    _wu, hu = ctx.size_units
    if ctx.vector_shapes:
        bar_h = gui_hint_bar_height(ctx, hint_style(ctx, surface_bg))
        return hu - bar_h - _GUI_CONTENT_GAP
    return hu - 3.0  # bottom border, hint row, rule


def draw_hint_row(ctx: Any, text: str, *, surface_bg: Any, border: Any,
                  x: float = 2.0) -> None:
    """Draw a modal's key hint as a bar pinned to the bottom of the box — the
    mirror of :func:`draw_title_bar`, and the one place every XeFM modal names
    its keys.

    Same construction, upside down: a frame-connecting rule, then the muted line
    of keys in the band beneath it, hard against the bottom border. A modal is
    then framed by two matched bands — what it is at the top, what it answers to
    at the bottom — with the content between them, instead of a hint floating in
    the client area with nothing to separate it from the content above.

    Elided from the right, so a narrow box drops the tail of the line rather than
    running under its own frame."""
    wu, hu = ctx.size_units
    style = hint_style(ctx, surface_bg)
    rule_style = Style(fg=border, bg=surface_bg)
    label = elide(text, max(1.0, wu - 2 * x), where="end", measure=ctx.measure_text)
    if ctx.vector_shapes:
        # Center the hint's line box in the bar, the rule at the bar's top edge —
        # draw_title_bar's own layout, reflected.
        rule_y = hu - gui_hint_bar_height(ctx, style)
        ctx.draw_frame_divider(rule_y, style=rule_style)
        ctx.draw_text(x, rule_y + _GUI_TITLE_PAD, label, style)
        return
    ctx.draw_frame_divider(hu - 3.0, style=rule_style)
    ctx.draw_text(x, hu - 2.0, label, style)
