"""ProgressiveSearchDialog — a live, search-as-you-type file/content finder.

This is the PuiKit port of XeFM/ttk's ``SearchDialog``: a single modal that
combines a **query field** with a **streaming results list**, with no separate
prompt step. Typing re-runs the search on every keystroke; results stream in
from a background worker thread while the UI stays responsive.

It reuses the same PuiKit primitives as :class:`FilterListDialog` — ``TextEdit``
for the query (real caret, selection, focus-gated IME) and ``ListView`` for the
results (virtualized draw, scrollbar, click-to-activate) — but the query field
drives a **filesystem search** rather than an in-memory re-filter.

Threading model (mirrors the port's async pane listing):

- Each keystroke bumps a generation counter, signals the previous search's
  ``threading.Event`` to cancel, and starts a fresh daemon thread that pulls
  from a caller-supplied ``search_iter(mode, query, cancel)`` generator.
- The worker batches results onto a ``queue.Queue``; a per-frame animation tick
  (``panel.request_animation_ticks``) drains the queue on the UI thread, extends
  the list, and re-renders — so results appear progressively and a stale
  generation (a newer keystroke) is dropped.
- On a still backend with no animation ticks (chiefly tests), the search is
  settled synchronously: the worker is joined and the queue drained in one shot.

``Tab`` switches between ``filename`` and ``content`` search in place and re-runs
against the same root — the ttk behavior. Enter accepts the selected row via
``on_accept(mode, value)``; Esc (or an outside click) cancels and stops the
worker. Push it with :func:`show_progressive_search`.
"""

from __future__ import annotations

import queue
import re
import threading
from typing import Any, Callable, Iterator

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, focus_on_click
from puikit.panel import Rect
from puikit.widgets.base import Widget
from puikit.widgets.list import ListView
from puikit.widgets.text_edit import TextEdit

from xefm.dialog_geometry import animate_open, draw_title_bar, pane_anchored_box

#: Navigation keys the *list* owns even while the query field holds focus.
_LIST_KEYS = frozenset({"up", "down", "pageup", "pagedown"})

#: Braille spinner frames for the "Searching…" indicator.
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

#: Batch cadence: how many hits accumulate before a partial update is published
#: to the UI thread. Content lines are rarer/heavier, so publish them sooner.
_BATCH = {"filename": 50, "content": 10}

#: Default cap on results — a huge tree can't grow the list without bound.
_RESULT_CAP = 1000


class ProgressiveSearchDialog(FocusContainer, Widget):
    """Modal live search picker. Construct via :func:`show_progressive_search`,
    which sizes and pushes the layer; this class owns layout, focus, events, and
    the background search worker."""

    focusable = True
    focus_stop_when_empty = True

    def __init__(
        self,
        *,
        search_iter: Callable[[str, str, threading.Event], Iterator[Any]],
        to_label: Callable[[str, Any], str],
        on_accept: Callable[[str, Any], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        titles: dict[str, str] | None = None,
        initial_mode: str = "filename",
        result_cap: int = _RESULT_CAP,
        ellipsis: str = "…",
        elide_where: str = "end",
    ):
        self._search_iter = search_iter
        self.to_label = to_label
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        self._titles = titles or {"filename": "Search Files", "content": "Search Content"}
        self.mode = initial_mode
        self.result_cap = result_cap

        self._panel: Any = None
        self._size: tuple[float, float] = (0.0, 0.0)
        self._closed = False

        # Search state.
        self.results: list[Any] = []
        self._queue: queue.Queue = queue.Queue()
        self._gen = 0
        self._cancel: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._searching = False
        self._ticking = False
        self._spin = 0
        self._error: str | None = None

        self.query_edit = TextEdit(on_change=lambda _t: self._start_search())
        # Mark over-long result rows with a trailing "…" rather than a silent
        # hard clip (issue #211). End elision suits both modes: a filename row
        # keeps its leading directories, a "path:line: text" row keeps the file
        # and the start of the matched line.
        self.list = ListView([], on_select=lambda i, _label: self._accept_index(i),
                             ellipsis=ellipsis, elide_where=elide_where)
        self._focused: Any = self.query_edit
        self._query_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._list_rect = Rect(0.0, 0.0, 0.0, 0.0)

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self.query_edit]

    # --- search --------------------------------------------------------------

    def _start_search(self) -> None:
        """Cancel any running search and start a fresh one for the current query
        and mode. Runs on the UI thread (keystroke handler)."""
        self._gen += 1
        gen = self._gen
        if self._cancel is not None:
            self._cancel.set()  # ask the previous worker to stop
        self.results = []
        self.list.set_items([])
        self.list.selected = 0
        self._error = None
        self._searching = False

        query = self.query_edit.text.strip()
        if not query:
            self._render()
            return

        cancel = self._cancel = threading.Event()
        mode = self.mode
        cap = self.result_cap
        self._searching = True
        self._spin = 0

        def worker() -> None:
            batch: list[Any] = []
            flush_at = _BATCH.get(mode, 50)
            error: str | None = None
            count = 0
            try:
                for value in self._search_iter(mode, query, cancel):
                    if cancel.is_set():
                        return
                    batch.append(value)
                    count += 1
                    if len(batch) >= flush_at:
                        self._queue.put((gen, batch, False, None))
                        batch = []
                    if count >= cap:  # enough for the list; stop walking the tree
                        break
            except re.error as exc:
                error = f"Invalid pattern: {exc}"
            except Exception:
                pass
            finally:
                if not cancel.is_set():
                    self._queue.put((gen, batch, True, error))

        self._thread = threading.Thread(target=worker, name="xefm-search", daemon=True)
        self._thread.start()
        self._ensure_ticking()
        self._render()

    def _ensure_ticking(self) -> None:
        """Register the per-frame drain if it isn't already running. On a still
        backend (no animation ticks) fall back to settling synchronously so the
        results still land — used by tests and non-animated backends."""
        if self._ticking:
            return
        self._ticking = True
        started = self._panel.request_animation_ticks(self._drain) if self._panel else False
        if not started:
            self._ticking = False
            self._settle()

    def _settle(self) -> None:
        """Join the worker and drain its results in one shot (still backends)."""
        thread = self._thread
        if thread is not None:
            thread.join()
        self._drain()

    def _drain(self) -> bool:
        """Animation-tick pump: install streamed result batches, drop stale ones,
        advance the spinner, and re-render. Returns True to keep ticking while a
        search is in flight, False to unregister once idle."""
        if self._closed:
            self._ticking = False
            return False
        updated = False
        while True:
            try:
                gen, batch, done, error = self._queue.get_nowait()
            except queue.Empty:
                break
            if gen != self._gen:
                continue  # superseded by a newer keystroke
            if batch:
                self.results.extend(batch)
                updated = True
            if done:
                self._searching = False
                if error is not None:
                    self._error = error
                updated = True
        if updated:
            capped = self.results[: self.result_cap]
            if len(capped) != len(self.results):
                self.results = capped
            self.list.set_items([self.to_label(self.mode, v) for v in self.results])
        if self._searching:
            self._spin += 1
        if updated or self._searching:
            self._render()
        keep = self._searching
        if not keep:
            self._ticking = False
        return keep

    # --- outcome -------------------------------------------------------------

    def _accept_index(self, index: int) -> None:
        if 0 <= index < len(self.results):
            value = self.results[index]
            mode = self.mode
            self._close()
            if self.on_accept is not None:
                self.on_accept(mode, value)

    def _cancel_dialog(self) -> None:
        self._close()
        if self.on_cancel is not None:
            self.on_cancel()

    def _close(self) -> None:
        self._closed = True
        if self._cancel is not None:
            self._cancel.set()  # stop the worker; its results are dropped
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()

    def _switch_mode(self) -> None:
        self.mode = "content" if self.mode == "filename" else "filename"
        self._start_search()  # re-run against the same root in the new mode

    def _render(self) -> None:
        if not self._closed and self._panel is not None:
            self._panel.render()

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme
        wu, hu = ctx.size_units
        surface_bg = theme.popup_bg if theme is not None else None
        box_style = Style(bg=surface_bg, fg=theme.popup_border if theme else None)
        ctx.draw_box(0, 0, *ctx.size_units, box_style, hints={"fill": True})

        pad = 1.0
        y = pad
        border = theme.popup_border if theme else None
        title = self._titles.get(self.mode, "Search")
        y = draw_title_bar(ctx, title, surface_bg=surface_bg, border=border, y=y)

        # Query field — one row, focused so the caret blinks and the IME stays on.
        # A magnifier icon sits on the dialog surface just left of the field.
        vector = ctx.vector_shapes
        field_h = 1.0
        icon_gap = 2.5 if vector else 3.0
        box_x = 2.0 + icon_gap
        if vector:
            y += 0.25
            below_gap = 0.9
        else:
            below_gap = 1.0

        self._query_rect = Rect(box_x, y, max(1.0, wu - 2.0 - box_x), field_h)
        self.query_edit.width = int(self._query_rect.w) + 1
        ctx.draw_child(
            self.query_edit, self._query_rect.x, self._query_rect.y,
            self._query_rect.w, self._query_rect.h, hints={"focused": True},
        )
        ty = (field_h - 1.0) / 2.0
        ctx.draw_text(
            2.0, self._query_rect.y + ty,
            "\U0001F50D", Style(fg=theme.text if theme else None, bg=surface_bg),
        )
        y += field_h + below_gap

        # Status line: spinner + live count (or an error / mode hint).
        status = self._status_text()
        ctx.draw_text(2.0, y, status, Style(fg=theme.text if theme else None, bg=surface_bg))
        y += 1.0

        # Result list fills the rest, above the bottom padding.
        list_h = max(1.0, hu - y - pad)
        frame = Rect(2.0, y, max(1.0, wu - 4.0), list_h)
        if vector:
            ctx.round_rect(
                frame.x, frame.y, frame.w, frame.h,
                Style(fg=theme.popup_border if theme else None), radius=4.0,
            )
            inset = 0.6
            self._list_rect = Rect(
                frame.x + inset, frame.y + inset,
                max(1.0, frame.w - 2 * inset), max(1.0, frame.h - 2 * inset),
            )
        else:
            self._list_rect = frame
        ctx.draw_child(
            self.list, self._list_rect.x, self._list_rect.y,
            self._list_rect.w, self._list_rect.h, hints={"focused": False},
        )

    def _status_text(self) -> str:
        other = "content" if self.mode == "filename" else "filename"
        hint = f"  •  Tab: {other}"
        if self._error:
            return self._error + hint
        n = len(self.results)
        if self._searching:
            spin = _SPINNER[self._spin % len(_SPINNER)]
            capped = " (limit)" if n >= self.result_cap else ""
            return f"{spin} Searching…  {n} found{capped}{hint}"
        if not self.query_edit.text.strip():
            return f"Type to search{hint}"
        capped = " (limit reached)" if n >= self.result_cap else ""
        return f"{n} result{'' if n == 1 else 's'}{capped}{hint}"

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.IME_COMPOSITION:
            # Forward IME composition (preedit) to the query field so CJK input
            # renders inline; the modal layer receives every event, so it must
            # relay composition to the field (the results list is not a text input).
            self.query_edit.handle_event(event)
            return True
        if event.type is EventType.KEY:
            key = event.key
            if key == "escape":
                self._cancel_dialog()
            elif key == "enter":
                self._accept_index(self.list.selected)
            elif key == "tab":
                self._switch_mode()
            elif key in _LIST_KEYS:
                self.list.handle_event(event)
            else:
                self.query_edit.handle_event(event)  # typing re-runs the search
            return True

        if event.type in (
            EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
            EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL,
        ):
            if event.x is not None and self._list_rect.contains(event.x, event.y):
                local = event.translated(-self._list_rect.x, -self._list_rect.y)
                self.list.handle_event(local)
            elif event.x is not None and self._query_rect.contains(event.x, event.y):
                if event.type is EventType.MOUSE_DOWN:
                    focus_on_click(self, self.query_edit)
                local = event.translated(-self._query_rect.x, -self._query_rect.y)
                self.query_edit.handle_event(local)
            elif event.type is EventType.MOUSE_CLICK and event.x is not None and not (
                0 <= event.x < self._size[0] and 0 <= event.y < self._size[1]
            ):
                self._cancel_dialog()
            return True
        return True  # modal: swallow everything else


def show_progressive_search(
    panel: Any,
    *,
    search_iter: Callable[[str, str, threading.Event], Iterator[Any]],
    to_label: Callable[[str, Any], str],
    on_accept: Callable[[str, Any], None] | None = None,
    on_cancel: Callable[[], None] | None = None,
    titles: dict[str, str] | None = None,
    initial_mode: str = "filename",
    result_cap: int = _RESULT_CAP,
    region: tuple[float, float] | None = None,
    ellipsis: str = "…",
    elide_where: str = "end",
    z: int = 70,
) -> ProgressiveSearchDialog:
    """Push a modal :class:`ProgressiveSearchDialog` over ``panel`` and return it.

    ``search_iter(mode, query, cancel)`` yields result values for the given mode
    (``"filename"`` / ``"content"``); it runs on a worker thread and should poll
    ``cancel`` and honor generation via early return. ``to_label(mode, value)``
    renders a row; ``on_accept(mode, value)`` fires on Enter/click.

    ``region`` anchors the dialog over the active pane (see
    :func:`show_filter_list` for the same convention)."""
    dialog = ProgressiveSearchDialog(
        search_iter=search_iter, to_label=to_label, on_accept=on_accept,
        on_cancel=on_cancel, titles=titles, initial_mode=initial_mode,
        result_cap=result_cap, ellipsis=ellipsis, elide_where=elide_where,
    )
    sw, sh = panel.backend.size_units
    w = max(36.0, min(sw * 0.6, 72.0))
    h = max(8.0, sh * 0.6)
    hints: dict[str, Any] = {"shadow": True, "w": w, "h": h}
    if region is not None:
        w, x = pane_anchored_box(w, sw, region)
        hints["w"] = w
        hints["x"] = x
    dialog._panel = panel
    panel.push_layer(dialog, z=z, hints=hints)
    animate_open(panel, dialog)
    return dialog
