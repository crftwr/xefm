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
synchronously: the worker is joined and its rows drained in one shot, with the
join bounded because a loader is allowed to run until the dialog closes and on
a still backend nothing ever closes it (see :meth:`FilterListDialog._settle`).

Interaction: typing filters the list with the same query the file pane's
incremental search takes (``xefm.search_match``) — whitespace-separated tokens
that all have to match, case-insensitively, each one a "contains" glob or a
Migemo match so romaji finds Japanese labels (#349); ↑/↓/PageUp/PageDown move
the selection; Enter accepts
the selected value; Esc cancels; a click selects/activates a row. A picker whose
rows are *remembered* rather than declared (History, the ';' Filter prompt) also
passes ``on_remove``, which binds the ``remove_list_item`` action to dropping
the highlighted row (#271). A hint band along the
bottom, mirroring the title bar, says which keys are live — the remove key among
them read back from the keymap, so a rebind shows up there.

Four more opt-in hooks let a picker say more about each row than its label —
each one off unless passed, so a call site that uses none of them looks exactly
as before (discussion #550, which the command palette is built on):

- ``to_right(value)`` — a right-aligned column, kept whole while the label
  elides (the palette's key for each action);
- ``to_detail(value)`` — one line about the highlighted row, in a row of its own
  between the list and the hint band. It is not a key, so it stays out of the
  band, which is where a modal names its keys and nothing else;
- ``to_marks(value)`` — colored marks drawn before the label, as
  ``(text, rgb)`` runs (``rgb`` None for the muted ink): the tag dots of
  #792. They are not part of the label, so the filter never matches them;
- ``to_help(value)`` — a longer Markdown page for the highlighted row, opened
  over the picker by the ``describe_list_item`` key (F1); closing it returns to
  the picker with the query and the cursor where they were.

The dialog is modal — it owns events while open — and reports its outcome through
``on_accept(value)`` / ``on_cancel()``.

Push it with :func:`show_filter_list`, which sizes and centers the layer with the
shared drop-shadow intent the other PuiKit modals use.
"""

from __future__ import annotations

import bisect
import queue
import threading
from typing import Any, Callable, Iterator, Sequence

from puikit.backend import Style
from puikit.color import LC_LARGE
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, focus_on_click
from puikit.panel import Rect
from puikit.layout import SizeRequest
from puikit.text import elide
from puikit.widgets.base import Widget
from puikit.widgets.list import ListView
from puikit.widgets.text_edit import TextEdit

from xefm import search_match
from xefm.actions import FILTER_LIST
from xefm.config import (format_key_for_display, get_keys_for_action,
                         is_action_for_event)
from xefm.dialog_geometry import (animate_open, draw_hint_row, draw_title_bar,
                                  hint_content_bottom, hint_style,
                                  pane_anchored_box)

#: Navigation keys the *list* owns even while the filter field holds focus —
#: typing filters, but the arrows still drive the selection.
#: Backend key names are unsuffixed ("pageup"/"pagedown"), matching ListView.
_LIST_KEYS = frozenset({"up", "down", "pageup", "pagedown"})

#: The one key of this dialog's that a config can rebind. Everything else here
#: (arrows, Enter, Esc) is structural to a modal picker and stays fixed; removal
#: is the operation a user may well want on a key of their own choosing.
_REMOVE_ACTION = "remove_list_item"

#: The key that opens the highlighted row's help — offered only by a picker
#: given ``to_help``, the way the remove key needs ``on_remove``.
_DESCRIBE_ACTION = "describe_list_item"

#: Braille spinner frames for the title's background-loading indicator.
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _ColumnRow(Widget):
    """One list row with a right-aligned second column: the label on the left,
    eliding as the row narrows, and ``right`` kept whole against the right edge
    in the muted text color; ``marks``, colored runs, lead the label. The list
    paints the selection fill behind it (the ``bg`` hint ``ListView`` hands a
    selected widget row), so the row draws only its texts."""

    def __init__(self, label: str, right: str, marks=(), *, ellipsis: str,
                 elide_where: str):
        self.label = label
        self.right = right
        self.marks = marks
        self._ellipsis = ellipsis
        self._elide_where = elide_where

    def measure(self, ctx, axis: str, available: float) -> SizeRequest:
        if axis == "x":
            return SizeRequest()
        h = ctx.measure_line_height()
        return SizeRequest(min=h, preferred=h, max=h)

    def draw(self, ctx) -> None:
        theme = ctx.theme
        style = Style(fg=theme.text if theme else None)
        wu, _hu = ctx.size_units
        reserved = 0.0
        if self.right:
            right_w = ctx.measure_text(self.right, style)
            gap = ctx.measure_text("  ", style)
            # The second column goes first, and only while the label keeps some
            # room beside it: on a very narrow row the name is what matters.
            if right_w + gap < wu / 2:
                ctx.draw_text(wu - right_w - 1.0, 0, self.right,
                              Style(fg=theme.muted_text if theme else None))
                reserved = right_w + gap + 1.0
        x = 0.0
        for text, rgb in self.marks:
            # ink() lifts the color against this row's own surface — the
            # selection fill when the row is highlighted.
            mark = Style(fg=ctx.ink(rgb if rgb is not None else theme.muted_text,
                                    target=LC_LARGE) if theme else None)
            ctx.draw_text(x, 0, text, mark)
            x += ctx.measure_text(text, mark)
        if self.marks:
            x += ctx.measure_text(" ", style)
        label = elide(self.label, max(0.0, wu - reserved - x), self._ellipsis or "",
                      where=self._elide_where,
                      measure=lambda t: ctx.measure_text(t, style))
        ctx.draw_text(x, 0, label, style)


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
        on_remove: Callable[[Any], bool] | None = None,
        remove_label: str = "remove",
        load_more: Callable[[threading.Event], Iterator[Any]] | None = None,
        to_right: Callable[[Any], str] | None = None,
        to_detail: Callable[[Any], str] | None = None,
        to_help: Callable[[Any], str] | None = None,
        to_marks: Callable[[Any], list] | None = None,
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
        #: Optional remove hook: called with the highlighted value when the
        #: ``remove_list_item`` key is pressed, and the row disappears only if it
        #: returns True. The owner does the forgetting — this dialog knows how a
        #: list is shown, never where it is stored — and its return value is also
        #: how a row that is *not* removable (the Filter picker's "clear filter")
        #: stays put. ``None`` leaves the dialog with no remove key at all.
        self.on_remove = on_remove
        #: The verb the hint line uses for the remove key. "remove" is right for
        #: a list of remembered rows, and wrong for the Drives picker, where the
        #: same key disconnects a share or ejects a disk.
        self.remove_label = remove_label
        #: Optional second column, right-aligned on every row (see the module
        #: docstring). With it the list draws widget rows instead of plain text.
        self.to_right = to_right
        #: Optional colored marks before each label (see the module docstring).
        #: With it, too, the list draws widget rows.
        self.to_marks = to_marks
        #: Optional one-line description of the highlighted row, drawn in a row
        #: of its own above the hint band.
        self.to_detail = to_detail
        #: Optional Markdown help for the highlighted row, opened by the
        #: ``describe_list_item`` key. ``None`` leaves the dialog without it.
        self.to_help = to_help
        self._hint_cache: str | None = None
        self._panel: Any = None
        # Values currently passing the filter, parallel to ``self.list.items``.
        self.filtered: list[Any] = list(self.all_items)
        # Each filtered value's ``search_match.rank``, parallel to ``filtered``
        # and sorted, so a streamed row can be inserted where it ranks.
        self._ranks: list[Any] = [(0, 0)] * len(self.filtered)

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
        row_factory = None
        if to_right is not None or to_marks is not None:
            def row_factory(row: tuple) -> Widget:
                return _ColumnRow(*row, ellipsis=ellipsis, elide_where=elide_where)
        self.list = ListView(
            self._rows(self.all_items),
            on_select=lambda i, _label: self._accept_index(i),
            ellipsis=ellipsis,
            elide_where=elide_where,
            row_factory=row_factory,
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

    # --- rows ----------------------------------------------------------------

    def _rows(self, values: Sequence[Any]) -> list[Any]:
        """What the list holds for ``values``: the labels, or ``(label, right)``
        — plus ``marks`` when given — for the widget rows they need."""
        if self.to_right is None and self.to_marks is None:
            return [self.to_label(v) for v in values]
        right = self.to_right or (lambda _v: "")
        if self.to_marks is None:
            return [(self.to_label(v), right(v)) for v in values]
        return [(self.to_label(v), right(v), self.to_marks(v)) for v in values]

    def selected_value(self) -> Any:
        """The value behind the highlighted row, or ``None`` when no row passes
        the filter."""
        index = self.list.selected
        if 0 <= index < len(self.filtered):
            return self.filtered[index]
        return None

    # --- filtering -----------------------------------------------------------

    def _label_hit(self, value: Any,
                   tokens: Sequence[search_match.Token]) -> bool:
        """Whether a row passes the filter: the shared incremental-search query
        against the rendered label — every whitespace-separated token matching it
        as a "contains" glob or through Migemo (romaji finds Japanese labels,
        #302), the same matcher the file pane's isearch uses (#349). ``tokens``
        comes from ``search_match.compile_query``, hoisted out of the row loop."""
        return search_match.hit(tokens, self.to_label(value))

    def _ranked(self, values: Sequence[Any],
                tokens: Sequence[search_match.Token]) -> list[tuple[Any, Any]]:
        """``(rank, value)`` for each of ``values`` passing the filter, best
        match first (#742); a stable sort, so rows that rank alike — every row,
        under an empty query — keep the order they were given in."""
        ranked = [(search_match.rank(tokens, self.to_label(v)), v)
                  for v in values if self._label_hit(v, tokens)]
        ranked.sort(key=lambda pair: pair[0])
        return ranked

    def _refilter(self, text: str) -> None:
        tokens = search_match.compile_query(text)
        ranked = self._ranked(self.all_items, tokens)
        self._ranks = [r for r, _v in ranked]
        self.filtered = [v for _r, v in ranked]
        self.list.set_items(self._rows(self.filtered))
        self.list.selected = 0

    def add_items(self, values: Sequence[Any]) -> None:
        """Add streamed ``values`` to the rows, re-applying the active filter
        text. Each one goes where its rank puts it — after every row that ranks
        as well, so with no query they simply append, as before ranking.

        The highlighted row stays highlighted, and the scroll position carries
        over (unlike ``_refilter``, which resets both for a changed query) —
        except at the top: a highlight still on the first row stays on the first
        row, which is the best match so far, whatever just arrived."""
        if not values:
            return
        self.all_items.extend(values)
        tokens = search_match.compile_query(self.filter_edit.text)
        ranked = self._ranked(values, tokens)
        if not ranked:
            return
        selected, offset = self.list.selected, self.list.offset
        for rank, value in ranked:
            index = bisect.bisect_right(self._ranks, rank)
            self._ranks.insert(index, rank)
            self.filtered.insert(index, value)
            if 0 < selected and index <= selected:
                selected += 1
        self.list.set_items(self._rows(self.filtered))
        self.list.selected = selected
        self.list.offset = offset

    def remove_selected(self) -> bool:
        """Drop the highlighted row, if ``on_remove`` accepts it.

        The value goes to ``on_remove`` first: only when the owner reports it
        actually forgot the thing does the row leave the list, so a row it
        declines (the Filter picker's "clear filter") simply stays. The removal
        is then local — no re-filter — which is what keeps the query, the
        selection and the scroll position where the user left them; ``set_items``
        resets the offset, so it is restored explicitly, the same way
        :meth:`add_items` does.
        """
        if self.on_remove is None or not self.filtered:
            return False
        index = self.list.selected
        if not 0 <= index < len(self.filtered):
            return False
        value = self.filtered[index]
        if not self.on_remove(value):
            return False
        del self.filtered[index]
        del self._ranks[index]
        try:
            self.all_items.remove(value)
        except ValueError:
            pass  # streamed in and already gone; the visible list is what matters
        offset = self.list.offset
        self.list.set_items(self._rows(self.filtered))
        # Hold the position rather than the index: after removing a row the next
        # one slides up into it, which is where a repeat press should land.
        self.list.selected = min(index, max(0, len(self.filtered) - 1))
        # Restored verbatim — offset is in base units, not rows, and a shrunk
        # list is clamped against the real viewport by ``ListView.draw``.
        self.list.offset = offset
        return True

    # --- hint line -----------------------------------------------------------

    def hint(self) -> str:
        """The key hint drawn along the bottom, built once per dialog.

        Arrows, Enter and Esc are named as the literals the dialog hard-codes;
        the remove key is read back from the keymap so a rebind is what the line
        says, and the whole segment drops out where no ``on_remove`` was given —
        a picker of declared rows (Favorites, Drives, Programs) must not offer a
        key that does nothing.
        """
        if self._hint_cache is None:
            parts = ["↑/↓ select", "Enter choose"]
            if self.to_help is not None:
                keys, _ = get_keys_for_action(_DESCRIBE_ACTION, FILTER_LIST)
                if keys:
                    parts.append(f"{format_key_for_display(keys[0])} help")
            if self.on_remove is not None:
                keys, _ = get_keys_for_action(_REMOVE_ACTION, FILTER_LIST)
                if keys:
                    parts.append(
                        f"{format_key_for_display(keys[0])} {self.remove_label}")
            parts.append("Esc cancel")
            self._hint_cache = " · ".join(parts)
        return self._hint_cache

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

    #: How long :meth:`_settle` waits before it stops an unfinished loader.
    #: Only an endless one ever reaches it, so this is not a budget for slow
    #: work — a loader that ends on its own is joined the moment it does.
    SETTLE_SECONDS = 2.0

    def _settle(self) -> None:
        """Join the loader and drain its rows in one shot (still backends).

        **The join is bounded, because a loader is allowed to be endless.** A
        bucket listing ends when the buckets run out, but network discovery
        keeps browsing on purpose — a NAS that wakes up ten seconds later is a
        new row — and what it watches for is the cancel flag the dialog sets
        when it closes. Here there are no animation ticks and so no dialog
        lifecycle to speak of: nothing will ever set that flag, and an
        unqualified join waits for a thread with no reason to finish. So the
        wait is bounded, the loader is then told to stop, and what arrived
        inside the wait is what the picker shows.
        """
        thread = self._load_thread
        if thread is not None:
            thread.join(self.SETTLE_SECONDS)
            if thread.is_alive():
                self._load_cancel.set()
                thread.join(self.SETTLE_SECONDS)
                # No sentinel is coming -- the worker only sends one when it
                # was not cancelled -- so the spinner is cleared here instead.
                self._loading = False
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

    # --- item help -----------------------------------------------------------

    def describe_selected(self) -> bool:
        """Open the highlighted row's help (``to_help``) over the picker.

        A dialog of its own, stacked rather than replacing this one: closing it
        pops only itself, so the query, the filtered rows and the cursor are
        exactly where the user left them. Returns whether anything opened."""
        value = self.selected_value()
        if self.to_help is None or value is None or self._panel is None:
            return False
        from xefm.text_dialog import show_markdown
        show_markdown(self._panel, self.to_help(value),
                      title=self.to_label(value), over=self)
        return True

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

        # Result list fills the rest, down to where the hint row starts. On a
        # vector backend it reads as a bounded inset panel: a rounded frame (in the
        # popup frame color) whose outer edges line up with the search box, with
        # the rows/scrollbar inset inside it. A grid keeps the flush, frameless
        # list.
        bottom = hint_content_bottom(ctx, surface_bg)
        detail_style = hint_style(ctx, surface_bg)
        detail_y = None
        if self.to_detail is not None:
            # The detail row sits between the list and the hint band: one line,
            # a small gap above it on a vector backend, flush on a grid.
            line_h = ctx.line_height(detail_style)
            detail_y = bottom - line_h
            bottom = detail_y - (0.4 if vector else 0.0)
        list_h = max(1.0, bottom - y)
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

        if detail_y is not None:
            value = self.selected_value()
            text = self.to_detail(value) if value is not None else ""
            if text:
                text = elide(text, max(1.0, wu - 4.0), "…",
                             measure=lambda t: ctx.measure_text(t, detail_style))
                ctx.draw_text(2.0, detail_y, text, detail_style)

        # Key hint as the bottom band, mirroring the title bar — the list's own
        # left inset, so the three line up down the left edge.
        draw_hint_row(ctx, self.hint(), surface_bg=surface_bg, border=border)

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
            elif (self.on_remove is not None
                  and is_action_for_event(event, _REMOVE_ACTION,
                                          context=FILTER_LIST)):
                # Ahead of the field, which would otherwise read the remove
                # key as its own forward-delete. Resolving by *action* rather
                # than by key is what keeps a rebind working here, and what
                # keeps a plain Delete typing in the query field.
                self.remove_selected()
            elif (self.to_help is not None
                  and is_action_for_event(event, _DESCRIBE_ACTION,
                                          context=FILTER_LIST)):
                # By action, like the remove key — so F1 here means this
                # picker's row help, never the inherited ``help``.
                self.describe_selected()
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
    on_remove: Callable[[Any], bool] | None = None,
    remove_label: str = "remove",
    region: tuple[float, float] | None = None,
    ellipsis: str = "…",
    elide_where: str = "end",
    load_more: Callable[[threading.Event], Iterator[Any]] | None = None,
    to_right: Callable[[Any], str] | None = None,
    to_marks: Callable[[Any], list] | None = None,
    to_detail: Callable[[Any], str] | None = None,
    to_help: Callable[[Any], str] | None = None,
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

    ``on_remove(value)`` opts the picker into the remove key
    (``remove_list_item``, in the ``filter_list`` context):
    it is called with the highlighted value and the row goes only if it returns
    True, so the caller both does the forgetting and decides what is removable at
    all. For the pickers whose rows accumulate — History and the ';' Filter
    prompt (#271); a list that comes from the config or from the system has
    nothing to forget, and without this hook shows no remove key.
    ``remove_label`` names the key in the hint line: in the Drives picker it
    disconnects a share or ejects a disk, which "remove" describes badly enough
    to be worth a word of its own.

    ``load_more`` optionally streams extra rows in after the dialog opens: it is
    called once on a daemon worker thread with a ``threading.Event`` that is set
    when the dialog closes (poll it and stop), and the values it yields append
    below ``items`` with the active filter applied, a spinner in the title while
    the scan runs. For rows that need a network round-trip — the drives picker's
    S3 buckets — so the dialog never waits on them.

    ``to_right``, ``to_marks``, ``to_detail`` and ``to_help`` describe each row
    beyond its label — a right-aligned column, colored marks before it, a
    one-line detail row for the highlighted entry, and a Markdown help page for
    it on the ``describe_list_item`` key. All are optional and independent; see
    the module docstring.

    A picker's Enter takes a row. For text the user types and uses — a command,
    a filter pattern — see :mod:`xefm.history_input_dialog`, whose Enter takes
    the field."""
    dialog = FilterListDialog(
        items, title=title, to_label=to_label, on_accept=on_accept, on_cancel=on_cancel,
        on_accept_text=on_accept_text, on_remove=on_remove,
        remove_label=remove_label,
        ellipsis=ellipsis, elide_where=elide_where, load_more=load_more,
        to_right=to_right, to_marks=to_marks, to_detail=to_detail, to_help=to_help,
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
