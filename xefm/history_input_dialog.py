"""HistoryInputDialog — a text field with its history below it.

For text the user *types and uses*: a command to run, a filter pattern to
apply. :class:`~xefm.filter_list_dialog.FilterListDialog` is the wrong shape
for that. It is a picker — Enter takes the highlighted row, and typed text is
only a fallback for when nothing matches — so typing ``rg -l`` with
``rg -l TODO`` in the history highlights the old command, and Enter runs it.
Here the field is what Enter uses, always; the history is where it can come
from.

**Focus is on one side at a time.**

- *Typing*: the caret is in the field, and no row is highlighted. What is
  typed narrows the history, with the query the file pane's incremental
  search takes (``xefm.search_match``): whitespace-separated tokens, globs,
  Migemo.
- *Browsing*: ↓ enters the history, and the highlighted row's text is copied
  into the field; moving along the history copies each row in turn. Enter
  here *chooses* the row rather than using it: focus returns to the field
  with the row's text in it, to use with a second Enter or to edit first.
  Typing while browsing edits the copied text directly. **The list is not re-filtered by the
  copied text**, or it would collapse to the one row just copied; it stays
  filtered by what was typed, as a browser's address bar does. ↑ past the
  first row, or Esc, returns to typing with the typed text put back.
- Editing the copied text returns to typing, and the edited text becomes the
  query.

A row may draw something other than the text it stands for — the Filter
prompt's defined filters draw a label and are applied by name — so the dialog
takes ``to_label`` for the list and ``to_text`` for the field.

Mouse: a click copies a row in, like ↓ to it; a second click on the same row
within :data:`_DOUBLE_CLICK_S` uses it. The remove key (``remove_list_item``,
in the ``filter_list`` context — the one surface every picker shares) forgets
the highlighted row while browsing.

It looks like a text prompt rather than a search: a prompt label before the
field, no magnifier, and the history under a heading of its own.

Push it with :func:`show_history_input`.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Sequence

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, focus_on_click
from puikit.panel import Rect
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

_REMOVE_ACTION = "remove_list_item"

#: Two clicks on one row within this many seconds use it — the directory diff
#: viewer's threshold, so the two agree.
_DOUBLE_CLICK_S = 0.4


class HistoryInputDialog(FocusContainer, Widget):
    """Modal text field over its history. Construct via
    :func:`show_history_input`."""

    focusable = True
    focus_stop_when_empty = True

    def __init__(
        self,
        items: Sequence[Any],
        *,
        title: str = "",
        prompt: str = "",
        heading: str = "History",
        to_label: Callable[[Any], str] = str,
        to_text: Callable[[Any], str] = str,
        on_accept: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_remove: Callable[[Any], bool] | None = None,
        accept_label: str = "use",
    ):
        self.all_items = list(items)
        self.title = title
        self.prompt = prompt
        self.heading = heading
        self.to_label = to_label
        self.to_text = to_text
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        #: Called with a row's value when the remove key is pressed on it; the
        #: row goes only if this returns True, so the owner decides what can be
        #: forgotten (the Filter prompt's "clear filter" row cannot).
        self.on_remove = on_remove
        self.accept_label = accept_label

        #: What was last *typed* — the query the list is filtered by. Distinct
        #: from the field's text while browsing, which holds a copied row.
        self.query = ""
        self.filtered: list[Any] = list(self.all_items)
        self.field = TextEdit(on_change=self._typed)
        self.list = ListView([self.to_label(v) for v in self.filtered],
                             on_select=self._clicked, ellipsis="…",
                             allow_no_selection=True)
        self._focused: Any = self.field
        self._panel: Any = None
        self._size: tuple[float, float] = (0.0, 0.0)
        self._field_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._list_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._last_click = (-1, 0.0)
        self._closed = False

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self.field]

    @property
    def browsing(self) -> bool:
        """Whether a history row is highlighted (and copied into the field)."""
        return self.list.selected >= 0

    # --- the two sides -------------------------------------------------------

    def _set_field(self, text: str) -> None:
        """Put ``text`` in the field, caret at the end, *without* it counting as
        typing — no re-filter."""
        self.field.text = text
        self.field.cursor = len(text)
        self.field._anchor = None

    def _browse(self, index: int) -> None:
        """Highlight row ``index`` and copy its text into the field."""
        self.list.selected = index
        self._set_field(self.to_text(self.filtered[index]))

    def choose(self) -> None:
        """Leave the history keeping the highlighted row's text in the field —
        Enter while browsing. The list stays as it was filtered, as it does
        when the field is clicked."""
        self.list.selected = -1

    def _back_to_typing(self) -> None:
        """Leave the history: no row highlighted, the typed text back."""
        self.list.selected = -1
        self._set_field(self.query)

    def _typed(self, text: str) -> None:
        """The field was edited — by typing, not by a copied row. Whatever is
        there is now the query."""
        self.query = text
        self.list.selected = -1
        self._refilter()

    def _refilter(self) -> None:
        tokens = search_match.compile_query(self.query)
        self.filtered = [v for v in self.all_items
                         if search_match.hit(tokens, self.to_label(v))]
        self.list.set_items([self.to_label(v) for v in self.filtered])
        self.list.selected = -1
        self.list.offset = 0

    def move(self, step: int) -> None:
        """Move through the history by ``step`` rows: into it from the field
        (downward only), along it, and back out past the first row."""
        if not self.filtered:
            return
        index = self.list.selected
        if index < 0:
            if step > 0:
                self._browse(0)
            return
        target = index + step
        if target < 0:
            if index == 0:
                self._back_to_typing()
            else:
                self._browse(0)
            return
        self._browse(min(target, len(self.filtered) - 1))

    def remove_selected(self) -> bool:
        """Forget the highlighted row, if ``on_remove`` agrees. The next row
        slides into its place and is copied in; with none left, back to
        typing."""
        index = self.list.selected
        if self.on_remove is None or not 0 <= index < len(self.filtered):
            return False
        value = self.filtered[index]
        if not self.on_remove(value):
            return False
        del self.filtered[index]
        try:
            self.all_items.remove(value)
        except ValueError:
            pass
        offset = self.list.offset
        self.list.set_items([self.to_label(v) for v in self.filtered])
        self.list.offset = offset
        if self.filtered:
            self._browse(min(index, len(self.filtered) - 1))
        else:
            self._back_to_typing()
        return True

    # --- outcome -------------------------------------------------------------

    def accept(self) -> None:
        """Use the field's text — typed, copied, or copied and edited."""
        text = self.field.text
        self._close()
        if self.on_accept is not None:
            self.on_accept(text)

    def _cancel(self) -> None:
        self._close()
        if self.on_cancel is not None:
            self.on_cancel()

    def _close(self) -> None:
        self._closed = True
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()

    def _clicked(self, index: int, _label: Any) -> None:
        """A row was clicked: copy it in; a second click on it soon after uses
        it."""
        if not 0 <= index < len(self.filtered):
            return
        now = time.monotonic()
        last_index, last_time = self._last_click
        self._browse(index)
        if index == last_index and now - last_time <= _DOUBLE_CLICK_S:
            self._last_click = (-1, 0.0)
            self.accept()
        else:
            self._last_click = (index, now)

    # --- hint line -----------------------------------------------------------

    def hint(self) -> str:
        """The keys live on the side that has focus."""
        remove = ""
        if self.on_remove is not None:
            keys, _ = get_keys_for_action(_REMOVE_ACTION, FILTER_LIST)
            if keys:
                remove = f"{format_key_for_display(keys[0])} remove"
        if self.browsing:
            parts = ["↑/↓ history", "Enter choose", "type to edit"]
            if remove:
                parts.append(remove)
            parts.append("Esc back")
        else:
            parts = [f"Enter {self.accept_label}"]
            if self.filtered:
                parts.insert(0, "↓ history")
            parts.append("Esc cancel")
        return " · ".join(parts)

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme
        wu, _hu = ctx.size_units
        surface_bg = theme.popup_bg if theme is not None else None
        border = theme.popup_border if theme else None
        ctx.draw_box(0, 0, *ctx.size_units, Style(bg=surface_bg, fg=border),
                     hints={"fill": True})

        y = 1.0
        if self.title:
            y = draw_title_bar(ctx, self.title, surface_bg=surface_bg,
                               border=border, y=y)
        vector = ctx.vector_shapes
        if vector and self.title:
            y += 0.25

        # A prompt and a field, as the plain input dialog lays them out — this
        # is a place to type, not a search box.
        field_x = 2.0
        if self.prompt:
            ctx.draw_text(2.0, y, self.prompt, Style(bg=surface_bg))
            field_x = 2.0 + ctx.measure_text(self.prompt + " ")
        field_w = max(1.0, wu - field_x - 2.0)
        self.field.width = field_w
        self._field_rect = Rect(field_x, y, field_w, 1.0)
        ctx.draw_child(self.field, field_x, y, field_w, 1.0,
                       hints={"focused": not self.browsing})
        y += 1.0 + (0.9 if vector else 1.0)

        # The history under a heading of its own, so it reads as the source of
        # what goes in the field rather than as search results.
        if self.heading:
            ctx.draw_text(2.0, y, self.heading, hint_style(ctx, surface_bg))
            y += 1.0
        list_h = max(1.0, hint_content_bottom(ctx, surface_bg) - y)
        frame = Rect(2.0, y, max(1.0, wu - 4.0), list_h)
        if vector:
            ctx.round_rect(frame.x, frame.y, frame.w, frame.h,
                           Style(fg=border), radius=4.0)
            inset = 0.6
            self._list_rect = Rect(frame.x + inset, frame.y + inset,
                                   max(1.0, frame.w - 2 * inset),
                                   max(1.0, frame.h - 2 * inset))
        else:
            self._list_rect = frame
        ctx.draw_child(self.list, self._list_rect.x, self._list_rect.y,
                       self._list_rect.w, self._list_rect.h,
                       hints={"focused": self.browsing, "bg": surface_bg})

        draw_hint_row(ctx, self.hint(), surface_bg=surface_bg, border=border)

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.IME_COMPOSITION:
            self.field.handle_event(event)
            return True
        if event.type is EventType.KEY:
            key = event.key
            if key == "escape":
                if self.browsing:
                    self._back_to_typing()
                else:
                    self._cancel()
            elif key == "enter":
                if self.browsing:
                    self.choose()
                else:
                    self.accept()
            elif (self.on_remove is not None and self.browsing
                  and is_action_for_event(event, _REMOVE_ACTION,
                                          context=FILTER_LIST)):
                # Ahead of the field, which would read the key as its own
                # forward-delete; resolved by action so a rebind holds.
                self.remove_selected()
            elif key == "down":
                self.move(1)
            elif key == "up":
                self.move(-1)
            elif key == "pagedown":
                self.move(max(1, self.list._viewport_h))
            elif key == "pageup" and self.browsing:
                self.move(-max(1, self.list._viewport_h))
            else:
                # Editing — of the typed text, or of a copied row, which then
                # becomes the query (see ``_typed``).
                self.field.handle_event(event)
            return True

        if event.type in (EventType.MOUSE_DOWN, EventType.MOUSE_UP,
                          EventType.MOUSE_CLICK, EventType.MOUSE_DRAG,
                          EventType.MOUSE_SCROLL):
            if event.x is not None and self._list_rect.contains(event.x, event.y):
                local = event.translated(-self._list_rect.x, -self._list_rect.y)
                self.list.handle_event(local)
            elif event.x is not None and self._field_rect.contains(event.x, event.y):
                if event.type is EventType.MOUSE_DOWN:
                    # Clicking into the field is choosing to type: the copied
                    # row stays as the text to edit, and nothing is highlighted.
                    self.list.selected = -1
                    focus_on_click(self, self.field)
                local = event.translated(-self._field_rect.x, -self._field_rect.y)
                self.field.handle_event(local)
            elif event.type is EventType.MOUSE_CLICK and event.x is not None and not (
                    0 <= event.x < self._size[0] and 0 <= event.y < self._size[1]):
                self._cancel()
            return True
        return True  # modal


def show_history_input(
    panel: Any,
    items: Sequence[Any],
    *,
    title: str = "",
    prompt: str = "",
    heading: str = "History",
    to_label: Callable[[Any], str] = str,
    to_text: Callable[[Any], str] = str,
    on_accept: Callable[[str], None] | None = None,
    on_cancel: Callable[[], None] | None = None,
    on_remove: Callable[[Any], bool] | None = None,
    accept_label: str = "use",
    region: tuple[float, float] | None = None,
    z: int = 70,
) -> HistoryInputDialog:
    """Push a modal :class:`HistoryInputDialog` over ``panel`` and return it.

    ``items`` are the history, most recent first. ``on_accept(text)`` gets the
    field's text on Enter; ``to_text(value)`` is what a row puts in the field
    and ``to_label(value)`` what it draws. ``on_remove(value)`` enables the
    remove key while browsing. ``accept_label`` names Enter in the hint line
    ("run", "apply"). Sized and placed as :func:`~xefm.filter_list_dialog.
    show_filter_list` is, so the two families sit in the same spot."""
    dialog = HistoryInputDialog(
        items, title=title, prompt=prompt, heading=heading, to_label=to_label,
        to_text=to_text, on_accept=on_accept, on_cancel=on_cancel,
        on_remove=on_remove, accept_label=accept_label)
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
