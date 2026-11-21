"""Modal scrollable-info viewers for the PuiKit port.

The read-only counterparts to the input / filter dialogs: a centered modal that
shows a title and a scrollable body. They cover XeFM's
``InfoDialog`` (help, file details, …).

Two flavors share the same modal chrome (box, title, hint line, drop shadow,
Enter/Esc/outside-click to dismiss), differing only in the body widget:

- :func:`show_text` hosts a PuiKit ``ListView`` — a flat list of preformatted
  lines. Cheapest for log-like or already-aligned content.
- :func:`show_markdown` hosts a ``MarkdownView`` — CommonMark-ish rich text with
  headings, bold/italic, tables, ``code`` and links — so information that reads
  better as *structured* prose (help, file details) lays itself out instead of
  being hand-aligned into columns. Its text can be selected and copied, and each
  fenced code block carries a Copy button (#632).

Both reuse the body widget's own virtualized draw, smooth scroll, scrollbar, and
↑/↓/PageUp/PageDown navigation; the modal simply forwards those keys and closes
on Enter / Esc / outside-click.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from puikit.backend import DEFAULT_STYLE, Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer
from puikit.panel import Rect
from puikit.widgets.base import Widget
from puikit.widgets.list import ListView
from puikit.widgets.markdown_view import MarkdownView

from xefm.dialog_geometry import (HINT_ROWS, animate_open, draw_hint_row, draw_title_bar,
                                  hint_content_bottom, title_content_top)

#: Keys the body widget consumes for scrolling while the dialog is open. (Backend
#: key names are unsuffixed: "pageup"/"pagedown", matching ListView / MarkdownView.)
_SCROLL_KEYS = frozenset({"up", "down", "pageup", "pagedown", "home", "end"})

_MOUSE_EVENTS = (
    EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
    EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL,
)


class _ScrollModal(FocusContainer, Widget):
    """Shared chrome for a modal that hosts a single scrollable ``body`` widget.

    Owns layout, focus, the title bar and bottom hint row, and event routing: navigation
    keys and mouse go to the body, Enter / Esc / outside-click close. Subclasses
    supply the body and may override :meth:`_style_body` to theme it each draw."""

    focusable = True
    focus_stop_when_empty = True

    def __init__(
        self,
        body: Widget,
        *,
        title: str = "",
        hint: str = "↑/↓ scroll · Esc close",
        on_close: Callable[[], None] | None = None,
    ):
        self.title = title
        self.hint = hint
        self.on_close = on_close
        self._panel: Any = None
        self.body = body
        self._body_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._size: tuple[float, float] = (0.0, 0.0)

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self.body]

    # --- outcome -------------------------------------------------------------

    def _close(self) -> None:
        panel = self._panel
        if panel is not None and panel.has_layer(self):
            panel.remove_layer(self)
        if self.on_close is not None:
            self.on_close()

    # --- drawing -------------------------------------------------------------

    def _style_body(self, theme, surface_bg) -> None:
        """Hook: let a subclass push theme-derived colors onto its body before it
        draws (a MarkdownView needs its base fg/bg to match the popup surface).
        Default: nothing — a ListView carries its own row styles."""

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme
        wu, _hu = ctx.size_units
        surface_bg = theme.popup_bg if theme is not None else None
        box_style = Style(bg=surface_bg, fg=theme.popup_border if theme else None)
        # Exact (fractional) extent, not ctx.width/height: those truncate to whole
        # units and draw the frame short of the fill on a fractional-height GUI box.
        ctx.draw_box(0, 0, *ctx.size_units, box_style, hints={"fill": True})

        pad = 1.0
        y = pad
        border = theme.popup_border if theme else None
        if self.title:
            y = draw_title_bar(ctx, self.title, surface_bg=surface_bg, border=border, y=y)

        self._style_body(theme, surface_bg)
        body_h = max(1.0, hint_content_bottom(ctx, surface_bg) - y)
        self._body_rect = Rect(2.0, y, max(1.0, wu - 4.0), body_h)
        # Give the body the popup surface as its inherited background, so any
        # bg=None content (a table's un-striped rows, gaps between prose) resolves
        # to the dialog gray rather than the darker content default beneath the
        # layer — otherwise those rows read as dark bands over the popup.
        ctx.draw_child(
            self.body, self._body_rect.x, self._body_rect.y,
            self._body_rect.w, self._body_rect.h,
            hints={"focused": False, "bg": surface_bg},
        )

        # The keys go in the bottom band, mirroring the title bar: this one used
        # to carry them in the header, which put chrome between the title and the
        # body the title describes, and left the dialog reading title / keys /
        # body instead of title / body / keys.
        draw_hint_row(ctx, self.hint, surface_bg=surface_bg, border=border)

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY:
            key = event.key
            if key in ("a", "c") and event.modifiers & {"ctrl", "cmd"}:
                self.body.handle_event(event)  # select all / copy, where selectable
            elif key == "tab":
                self._step_link(-1 if "shift" in event.modifiers else 1)
            elif key == "enter" and self._follow_link():
                pass  # a keyboard-focused link was followed; the dialog stays
            elif key in ("escape", "enter"):
                self._close()
            elif key in _SCROLL_KEYS:
                self.body.handle_event(event)
            return True

        if event.type in _MOUSE_EVENTS:
            if event.x is not None and self._body_rect.contains(event.x, event.y):
                local = event.translated(-self._body_rect.x, -self._body_rect.y)
                self.body.handle_event(local)
            elif event.type is EventType.MOUSE_CLICK and event.x is not None and not (
                0 <= event.x < self._size[0] and 0 <= event.y < self._size[1]
            ):
                self._close()  # click outside dismisses
            return True
        return True  # modal: swallow everything else


    # --- links -----------------------------------------------------------------

    def _step_link(self, direction: int) -> None:
        """Tab / Shift-Tab: move the body's keyboard link focus, cycling — off
        one end, the next press starts again from the other. A body without
        links (or one that is not a MarkdownView) ignores the key."""
        advance = getattr(self.body, "focus_advance", None)
        if advance is not None and not advance(direction):
            advance(direction)

    def _follow_link(self) -> bool:
        """Enter on a keyboard-focused link follows it; False when no link is
        focused, so Enter keeps closing the dialog."""
        activate = getattr(self.body, "activate_focused_link", None)
        return bool(activate is not None and activate())


class TextDialog(_ScrollModal):
    """Modal scrollable plain-text viewer. Construct via :func:`show_text`, which
    sizes and pushes the layer; the body is a ``ListView`` of preformatted lines."""

    def __init__(
        self,
        lines: Sequence[str],
        *,
        title: str = "",
        on_close: Callable[[], None] | None = None,
    ):
        super().__init__(
            ListView([str(line) for line in lines]),
            title=title, on_close=on_close,
        )
        #: Kept as an alias for the ListView body (older call sites / tests).
        self.list = self.body


class MarkdownDialog(_ScrollModal):
    """Modal scrollable Markdown viewer. Construct via :func:`show_markdown`; the
    body is a ``MarkdownView`` that renders headings, emphasis, tables and links."""

    def __init__(
        self,
        source: str,
        *,
        title: str = "",
        on_close: Callable[[], None] | None = None,
        on_link: Callable[[str], bool] | None = None,
        hint: str | None = None,
    ):
        # Selectable, and a Copy button on each code block: a dialog is where
        # XeFM shows a result (an extension's, #632) as well as help, and what
        # is shown there is often wanted elsewhere — a digest, a path.
        body = MarkdownView(source, on_link=on_link, selectable=True, code_copy=True)
        super().__init__(body, title=title, on_close=on_close,
                         hint=hint if hint is not None else _hint_for(body))
        self.md = self.body

    def _style_body(self, theme, surface_bg) -> None:
        # The MarkdownView colors inline roles from the live theme, but its base
        # prose fg/bg must match the popup surface (fg=None would fall back to the
        # backend default, wrong on some palettes). Colors don't affect wrapping,
        # so mutating the style between draws is safe.
        if theme is not None:
            self.md.style = Style(fg=theme.text, bg=surface_bg)


#: The footer for each set of Tab stops a Markdown body can have (#681): the
#: keys are only worth naming when Tab reaches something.
_STOP_HINTS = {
    frozenset(): "↑/↓ scroll · Esc close",
    frozenset({"link"}): "↑/↓ scroll · Tab next link · Enter open · Esc close",
    frozenset({"copy"}): "↑/↓ scroll · Tab Copy button · Enter copy · Esc close",
    frozenset({"link", "copy"}):
        "↑/↓ scroll · Tab next link or Copy · Enter open / copy · Esc close",
}


def _hint_for(body: MarkdownView) -> str:
    """The footer for ``body``: what Tab reaches in it, if anything."""
    return _STOP_HINTS.get(body.focus_stop_kinds, _STOP_HINTS[frozenset()])


def show_text(
    panel: Any,
    lines: Sequence[str],
    *,
    title: str = "",
    on_close: Callable[[], None] | None = None,
    z: int = 70,
) -> TextDialog:
    """Push a modal :class:`TextDialog` over ``panel`` and return it.

    Sized to a comfortable fraction of the window and centered, with the shared
    drop-shadow modal intent. Closes on Enter / Esc / outside-click."""
    dialog = TextDialog(lines, title=title, on_close=on_close)
    _push(panel, dialog, rows=len(lines), z=z)
    return dialog


def keys_markdown(
    rows: Sequence[tuple[str, str]], *, intro: str = "",
) -> str:
    """Build a Markdown source for a viewer's key-help overlay: an optional
    ``intro`` line over a two-column ``| Key(s) | Action |`` table, with the key
    cells rendered as ``code`` spans. ``|`` in either cell is escaped so a key
    label or description containing a pipe can't break the table.

    Shared by the viewers' ``_show_help`` so every help overlay reads as the same
    rich-text table (matching the app's main help)."""
    def esc(text: str) -> str:
        return text.replace("|", "\\|")
    lines = []
    if intro:
        lines += [intro, ""]
    lines += ["| Key(s) | Action |", "| --- | --- |"]
    for keys, desc in rows:
        lines.append(f"| `{esc(keys)}` | {esc(desc)} |")
    return "\n".join(lines)


def show_markdown(
    panel: Any,
    source: str,
    *,
    title: str = "",
    on_close: Callable[[], None] | None = None,
    on_link: Callable[[str], bool] | None = None,
    hint: str | None = None,
    over: Any = None,
    z: int = 70,
) -> MarkdownDialog:
    """Push a modal :class:`MarkdownDialog` over ``panel`` and return it.

    Same chrome and sizing as :func:`show_text`, but ``source`` is Markdown and
    lays out as rich text (headings, tables, emphasis, links).

    Links are followed by a click, or from the keyboard: Tab / Shift-Tab step
    through them and Enter follows the stepped-to one (Enter with none stepped
    to still closes). ``on_link(href)`` sees every followed link first and
    returns True for one it handled — how a dialog gives its links an in-app
    meaning (``xefm-action:`` in the Help dialog); declined, a link opens the
    way PuiKit opens it. ``hint`` replaces the bottom band's text, for a dialog
    that wants to name its link keys.

    ``over`` is the dialog this one opens on top of, when it is a page *about*
    something in that dialog (an action's page over the Help dialog or the
    command palette). The two would otherwise be the same chrome on the same
    surface, one exactly covering the other, and read as one box; so the page
    goes in front of it (``z`` is then ignored) and is inset within it, so the
    frame below shows on every side and the page's drop shadow falls on that
    dialog's surface rather than off its edge. Nothing is dimmed: a page over a
    dialog is a smaller step than the dialog was, and a veil over the whole
    screen would make it read as the bigger one."""
    dialog = MarkdownDialog(source, title=title, on_close=on_close,
                            on_link=on_link, hint=hint)
    below = _layer_of(panel, over)
    w = _box_width(panel)
    if below is not None:
        w = max(36.0, min(w, below.rect.w - 2 * _NESTED_INSET))
    # Measured, not estimated: the view's own layout of the document at the
    # body's width, so a table's borders and a heading's spacing are counted —
    # a source-line count came up short of them and opened the Details dialog
    # already needing a scroll (#651).
    lc = panel.layout_context()
    body_h = dialog.md.measure(lc, "y", w - 4.0).preferred
    _push(panel, dialog, rows=0, z=below.z + 10 if below is not None else z,
          w=w, over=below, height=title_content_top(lc) + body_h + HINT_ROWS)
    return dialog


#: How far a page opened over another dialog sits inside it, on each side, in
#: base units — enough for the frame underneath to stay visible around it.
_NESTED_INSET = 4.0


def _layer_of(panel: Any, widget: Any) -> Any:
    """The layer slot holding ``widget``, or None (no widget, or not pushed)."""
    if widget is None:
        return None
    for slot in getattr(panel, "_layers", ()):
        if slot.widget is widget:
            return slot
    return None


def _box_width(panel: Any) -> float:
    """The width a scroll-modal opens at: a comfortable fraction of the window."""
    sw, _sh = panel.backend.size_units
    return max(48.0, min(sw * 0.7, 96.0))


def _push(panel: Any, dialog: _ScrollModal, *, rows: int, z: int,
          w: float | None = None, over: Any = None,
          height: float | None = None) -> None:
    """Size, center, and push a scroll-modal, with the shared modal intent. Height
    is ``height`` when the caller measured the whole box, else ``rows`` of body
    plus the chrome. ``over`` is the layer slot of a dialog this one is stacked
    on (see :func:`show_markdown`): the height is then kept inside it too."""
    _sw, sh = panel.backend.size_units
    if w is None:
        w = _box_width(panel)
    if height is None:
        # rows + chrome: top border, title, rule, body, rule, hint, bottom border.
        height = float(rows + 6)
    h = max(10.0, min(sh * 0.8, height))
    hints: dict[str, Any] = {"shadow": True, "w": w, "h": h}
    if over is not None:
        h = max(8.0, min(h, over.rect.h - 2.0))
        hints["h"] = h
    dialog._panel = panel
    panel.push_layer(dialog, z=z, hints=hints)
    animate_open(panel, dialog)
