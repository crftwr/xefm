"""FilterListDialog — a modal, filterable list picker for the PuiKit port.

The searchable-list workhorse: a modal
overlay with a **filter text field** on top of a **scrollable list**, used for
discrete selection (favorites, drives, programs, …). It reuses PuiKit primitives
rather than re-implementing them:

- ``TextEdit`` for the filter field — so it carries the real caret, selection,
  clipboard, and (crucially) focus-gated IME. Because the dialog is a
  ``FocusContainer`` and the *top layer is the focus root*, the field's
  ``wants_text_input`` engages the backend's text-input system while the dialog
  is open and releases it when the dialog closes — no app branching.
- ``ListView`` for the results — virtualized draw, smooth scroll, a scrollbar,
  and ``on_select`` activation, all for free.

An optional **background loader** (``load_more``) streams extra rows in after
the dialog is already open: the callable runs once on a daemon worker thread
and yields values, which are appended below the eager rows on the UI thread —
via the animation tick, mirroring :class:`ProgressiveSearchDialog`'s threading
model — with whatever filter text is active re-applied and a small spinner in
the title while the scan runs. The drives picker uses this for S3 buckets, a
credentialed network scan that must not delay the dialog (issue #274). On a
still backend with no animation ticks (chiefly tests) the loader is settled
synchronously: the worker is joined and its rows drained in one shot.

Interaction: typing filters the list (substring,
case-insensitive, plus Migemo so romaji finds Japanese labels — see
``xefm.migemo_search``); ↑/↓/PageUp/PageDown move the selection; Enter accepts
the selected value; Esc cancels; a click selects/activates a row. The dialog is
modal — it owns events while open — and reports its outcome through
``on_accept(value)`` / ``on_cancel()``.

Push it with :func:`show_filter_list`, which sizes and centers the layer with the
shared drop-shadow intent the other PuiKit modals use.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Iterator, Sequence

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, focus_on_click
from puikit.panel import Rect
from puikit.widgets.base import Widget
from puikit.widgets.list import ListView
from puikit.widgets.text_edit import TextEdit

from xefm import migemo_search
from xefm.dialog_geometry import animate_open, draw_title_bar, pane_anchored_box

#: Navigation keys the *list* owns even while the filter field holds focus —
#: typing filters, but the arrows still drive the selection.
#: Backend key names are unsuffixed ("pageup"/"pagedown"), matching ListView.
_LIST_KEYS = frozenset({"up", "down", "pageup", "pagedown"})

#: Braille spinner frames for the title's background-loading indicator.
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class FilterListDialog(FocusContainer, Widget):
    """Modal filter-list picker. Construct via :func:`show_filter_list`, which
    sizes and pushes the layer; this class owns layout, focus, and events."""

    focusable = True
    # Always handles keys itself (escape closes), so it is a focus stop even when
    # the filtered list is momentarily empty.
    focus_stop_when_empty = True

    def __init__(
        self,
        items: Sequence[Any],
        *,
        title: str = "",
        to_label: Callable[[Any], str] = str,
        on_accept: Callable[[Any], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_accept_text: Callable[[str], None] | None = None,
        ellipsis: str = "",
        elide_where: str = "end",
        load_more: Callable[[threading.Event], Iterator[Any]] | None = None,
    ):
        self.all_items = list(items)
        self.to_label = to_label
        self.title = title
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        #: Optional free-text fallback: when Enter is pressed with no list row
        #: matching the query, the raw filter text is handed here instead — so the
        #: picker can double as an editor (e.g. the Filter prompt applies a
        #: brand-new pattern that isn't in its history).
        self.on_accept_text = on_accept_text
        self._panel: Any = None
        # Values currently passing the filter, parallel to ``self.list.items``.
        self.filtered: list[Any] = list(self.all_items)

        #: Optional background loader (see the module docstring): runs once on a
        #: worker thread when the dialog opens, yielding values that stream in
        #: below ``items``. ``None`` -> fully eager, no thread.
        self._load_more = load_more
        self._loading = False
        self._closed = False
        self._load_queue: queue.Queue = queue.Queue()
        self._load_cancel = threading.Event()
        self._load_thread: threading.Thread | None = None
        self._ticking = False
        self._spin = 0

        self.filter_edit = TextEdit(on_change=self._refilter)
        self.list = ListView(
            [self.to_label(v) for v in self.all_items],
            on_select=lambda i, _label: self._accept_index(i),
            ellipsis=ellipsis,
            elide_where=elide_where,
        )
        # The filter field holds focus so typing flows there and the IME engages;
        # the arrows are routed to the list explicitly (see handle_event).
        self._focused: Any = self.filter_edit
        self._filter_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._list_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._size: tuple[float, float] = (0.0, 0.0)

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self.filter_edit]

    # --- filtering -----------------------------------------------------------

    def _label_hit(self, value: Any, q: str, regex) -> bool:
        """Whether a row passes the filter: case-insensitive substring on the
        rendered label, unioned with the query's Migemo regex (romaji finds
        Japanese labels, #302 — ``regex`` is None when Migemo doesn't apply)."""
        label = self.to_label(value)
        return q in label.lower() or (
            regex is not None and migemo_search.search_nfc(regex, label))

    def _refilter(self, text: str) -> None:
        q = text.lower()
        regex = migemo_search.get_regex(text)
        self.filtered = [v for v in self.all_items if self._label_hit(v, q, regex)]
        self.list.set_items([self.to_label(v) for v in self.filtered])
        self.list.selected = 0

    def add_items(self, values: Sequence[Any]) -> None:
        """Append ``values`` below the existing rows, re-applying the active
        filter text. Appending never reorders: rows already passing the filter
        keep their indices, so the selection and scroll position carry over
        (unlike ``_refilter``, which resets both for a changed query)."""
        if not values:
            return
        self.all_items.extend(values)
        q = self.filter_edit.text.lower()
        regex = migemo_search.get_regex(self.filter_edit.text)
        matches = [v for v in values if self._label_hit(v, q, regex)]
        if not matches:
            return
        self.filtered.extend(matches)
        selected, offset = self.list.selected, self.list.offset
        self.list.set_items([self.to_label(v) for v in self.filtered])
        self.list.selected = selected
        self.list.offset = offset

    # --- background loading --------------------------------------------------

    def _start_load_more(self) -> None:
        """Start the optional background loader (a no-op without one). Called by
        :func:`show_filter_list` once the layer is pushed, so the streamed rows
        land in a dialog that is already on screen."""
        if self._load_more is None or self._load_thread is not None:
            return
        cancel = self._load_cancel
        load = self._load_more
        self._loading = True

        def worker() -> None:
            try:
                for value in load(cancel):
                    if cancel.is_set():
                        return
                    self._load_queue.put(([value], False))
            except Exception:
                pass  # best-effort extras; the eager rows are already shown
            finally:
                if not cancel.is_set():
                    self._load_queue.put(([], True))

        self._load_thread = threading.Thread(
            target=worker, name="xefm-filter-load", daemon=True)
        self._load_thread.start()
        self._ensure_ticking()

    def _ensure_ticking(self) -> None:
        """Register the per-frame drain. On a still backend (no animation ticks)
        fall back to settling synchronously so the rows still land — used by
        tests and non-animated backends."""
        if self._ticking:
            return
        self._ticking = True
        started = self._panel.request_animation_ticks(self._drain) if self._panel else False
        if not started:
            self._ticking = False
            self._settle()

    def _settle(self) -> None:
        """Join the loader and drain its rows in one shot (still backends)."""
        thread = self._load_thread
        if thread is not None:
            thread.join()
        self._drain()

    def _drain(self) -> bool:
        """Animation-tick pump: install streamed rows, advance the spinner, and
        re-render. Returns True to keep ticking while the loader runs, False to
        unregister once done (or once the dialog closed)."""
        if self._closed:
            self._ticking = False
            return False
        added: list[Any] = []
        was_loading = self._loading
        while True:
            try:
                batch, done = self._load_queue.get_nowait()
            except queue.Empty:
                break
            added.extend(batch)
            if done:
                self._loading = False
        if added:
            self.add_items(added)
        if self._loading:
            self._spin += 1
        if added or was_loading:
            self._render()  # new rows, the next spinner frame, or clearing it
        if not self._loading:
            self._ticking = False
            return False
        return True

    def _render(self) -> None:
        if not self._closed and self._panel is not None:
            self._panel.render()

    # --- outcome -------------------------------------------------------------

    def _accept_index(self, index: int) -> None:
        if 0 <= index < len(self.filtered):
            value = self.filtered[index]
            self._close()
            if self.on_accept is not None:
                self.on_accept(value)

    def _cancel(self) -> None:
        self._close()
        if self.on_cancel is not None:
            self.on_cancel()

    def _close(self) -> None:
        self._closed = True
        self._load_cancel.set()  # stop a background loader; its rows are dropped
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme
        wu, hu = ctx.size_units
        surface_bg = theme.popup_bg if theme is not None else None
        box_style = Style(bg=surface_bg, fg=theme.popup_border if theme else None)
        # Exact (fractional) extent, not ctx.width/height: those truncate to whole
        # units and draw the frame short of the fill on a fractional-height GUI box.
        ctx.draw_box(0, 0, *ctx.size_units, box_style, hints={"fill": True})

        pad = 1.0
        y = pad
        if self.title:
            border = theme.popup_border if theme else None
            title = self.title
            if self._loading:
                # The background loader is still scanning: a spinner after the
                # title, advanced by the drain tick, so the extra rows read as
                # "on their way" rather than missing.
                title = f"{self.title}  {_SPINNER[self._spin % len(_SPINNER)]}"
            y = draw_title_bar(ctx, title, surface_bg=surface_bg, border=border, y=y)

        # Filter field — one row, focused so the caret blinks and the IME stays on.
        # A magnifier icon sits on the dialog surface just left of the field; the
        # field box shifts right to make room. (Grid backends reserve a bit more
        # since the emoji occupies two cells there.)
        vector = ctx.vector_shapes
        field_h = 1.0
        icon_gap = 2.5 if vector else 3.0  # left columns claimed by the icon
        box_x = 2.0 + icon_gap

        # Breathing room above/below the field. The title rule already leaves a
        # small gap above, so on a vector backend widen it a touch and match the
        # gap below, centering the field between the header and the list. A grid
        # keeps its whole-row rhythm (field row, one blank row, then the list).
        if vector:
            if self.title:
                y += 0.25
            below_gap = 0.9
        else:
            below_gap = 1.0

        # The field's right edge lines up with the list below it (both end at the
        # 2-unit right margin). TextEdit caps its box at ``self.width``, so widen
        # it to the rect first.
        self._filter_rect = Rect(box_x, y, max(1.0, wu - 2.0 - box_x), field_h)
        self.filter_edit.width = int(self._filter_rect.w) + 1
        ctx.draw_child(
            self.filter_edit, self._filter_rect.x, self._filter_rect.y,
            self._filter_rect.w, self._filter_rect.h, hints={"focused": True},
        )
        # Magnifier left of the field, on the dialog surface, on the field row.
        ty = (field_h - 1.0) / 2.0
        ctx.draw_text(
            2.0, self._filter_rect.y + ty,
            "\U0001F50D", Style(fg=theme.text if theme else None, bg=surface_bg),
        )
        y += field_h + below_gap

        # Result list fills the rest, above the bottom padding. On a vector
        # backend it reads as a bounded inset panel: a rounded frame (in the popup
        # frame color) whose outer edges line up with the search box, with the
        # rows/scrollbar inset inside it. A grid keeps the flush, frameless list.
        list_h = max(1.0, hu - y - pad)
        frame = Rect(2.0, y, max(1.0, wu - 4.0), list_h)
        if vector:
            ctx.round_rect(
                frame.x, frame.y, frame.w, frame.h,
                Style(fg=theme.popup_border if theme else None),
                radius=4.0,
            )
            inset = 0.6
            self._list_rect = Rect(
                frame.x + inset, frame.y + inset,
                max(1.0, frame.w - 2 * inset), max(1.0, frame.h - 2 * inset),
            )
        else:
            self._list_rect = frame
        # The "bg" hint hands the list the popup surface as its inherited
        # background — otherwise its bg=None rows fall through to the terminal's
        # default colors on a grid backend (dark bands over the dialog).
        ctx.draw_child(
            self.list, self._list_rect.x, self._list_rect.y,
            self._list_rect.w, self._list_rect.h,
            hints={"focused": False, "bg": surface_bg},
        )

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.IME_COMPOSITION:
            # Forward IME composition (preedit) to the filter field so CJK input
            # renders inline. The modal layer gets every event, so it must relay
            # composition to the field itself (the list is not a text input).
            self.filter_edit.handle_event(event)
            return True
        if event.type is EventType.KEY:
            key = event.key
            if key == "escape":
                self._cancel()
            elif key == "enter":
                # A row matched the query -> take it; otherwise fall back to the
                # raw typed text (so a brand-new value still applies), if a
                # free-text handler was given.
                if not self.filtered and self.on_accept_text is not None:
                    text = self.filter_edit.text
                    self._close()
                    self.on_accept_text(text)
                else:
                    self._accept_index(self.list.selected)
            elif key in _LIST_KEYS:
                self.list.handle_event(event)  # arrows drive the list selection
            else:
                self.filter_edit.handle_event(event)  # typing/editing filters
            return True

        if event.type in (
            EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
            EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL,
        ):
            if event.x is not None and self._list_rect.contains(event.x, event.y):
                local = event.translated(-self._list_rect.x, -self._list_rect.y)
                self.list.handle_event(local)
            elif event.x is not None and self._filter_rect.contains(event.x, event.y):
                if event.type is EventType.MOUSE_DOWN:
                    focus_on_click(self, self.filter_edit)
                local = event.translated(-self._filter_rect.x, -self._filter_rect.y)
                self.filter_edit.handle_event(local)
            elif event.type is EventType.MOUSE_CLICK and event.x is not None and not (
                0 <= event.x < self._size[0] and 0 <= event.y < self._size[1]
            ):
                self._cancel()  # click outside the dialog dismisses it
            return True
        return True  # modal: swallow everything else


def show_filter_list(
    panel: Any,
    items: Sequence[Any],
    *,
    title: str = "",
    to_label: Callable[[Any], str] = str,
    on_accept: Callable[[Any], None] | None = None,
    on_cancel: Callable[[], None] | None = None,
    on_accept_text: Callable[[str], None] | None = None,
    region: tuple[float, float] | None = None,
    ellipsis: str = "…",
    elide_where: str = "end",
    load_more: Callable[[threading.Event], Iterator[Any]] | None = None,
    z: int = 70,
) -> FilterListDialog:
    """Push a modal :class:`FilterListDialog` over ``panel`` and return it.

    Sized to a comfortable fraction of the window and centered, with the shared
    drop-shadow modal intent. The chosen value is reported through
    ``on_accept``; ``on_cancel`` fires on escape / outside-click.

    ``region`` is an optional ``(x, width)`` column span (in base units) to anchor
    the dialog within instead of the whole window — used to place a pane-targeting
    picker (favorites, drives, …) over the active pane, so the user can tell which
    pane it will act on. The dialog is centered on the pane's center and may run a
    bit wider than the pane for comfort (see :func:`xefm.dialog_geometry`).

    ``ellipsis``/``elide_where`` control how over-long rows are abbreviated (see
    ``ListView``): the default marks a truncated row with a trailing ``…``; pass
    ``elide_where="middle"`` for a path list so the meaningful tail stays visible
    (History, Favorites and Drives do this). Pass ``ellipsis=""`` for a hard clip
    with no marker.

    ``load_more`` optionally streams extra rows in after the dialog opens: it is
    called once on a daemon worker thread with a ``threading.Event`` that is set
    when the dialog closes (poll it and stop), and the values it yields append
    below ``items`` with the active filter applied, a spinner in the title while
    the scan runs. For rows that need a network round-trip — the drives picker's
    S3 buckets — so the dialog never waits on them."""
    dialog = FilterListDialog(
        items, title=title, to_label=to_label, on_accept=on_accept, on_cancel=on_cancel,
        on_accept_text=on_accept_text, ellipsis=ellipsis, elide_where=elide_where,
        load_more=load_more,
    )
    sw, sh = panel.backend.size_units
    w = max(36.0, min(sw * 0.6, 72.0))
    # Height follows the window, not the item count: a short list still opens at a
    # comfortable, consistent size (empty rows show below) rather than a stubby box
    # that snaps to however many items it happens to hold.
    h = max(8.0, sh * 0.6)
    hints: dict[str, Any] = {"shadow": True, "w": w, "h": h}
    if region is not None:
        # Anchor over the pane, but a bit wider than it for comfort (still
        # centered on the pane's center, so it leans over its target pane).
        w, x = pane_anchored_box(w, sw, region)
        hints["w"] = w
        hints["x"] = x
    dialog._panel = panel
    panel.push_layer(dialog, z=z, hints=hints)
    animate_open(panel, dialog)
    dialog._start_load_more()
    return dialog
