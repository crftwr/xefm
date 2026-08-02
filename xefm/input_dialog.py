"""InputDialog — a modal single-line text prompt for the PuiKit port.

The text-entry counterpart to :class:`xefm.filter_list_dialog.FilterListDialog`: a
small centered modal with a title, a prompt label, and one ``TextEdit``. It is
the single-line prompts — Create Directory,
Create File, Rename — collapsed into one reusable primitive.

Like the filter-list dialog it reuses PuiKit primitives rather than
re-implementing them:

- ``TextEdit`` for the field — real caret, selection, clipboard, and focus-gated
  IME. Because the dialog is a ``FocusContainer`` and the top layer is the focus
  root, the field's ``wants_text_input`` engages the backend's text-input system
  while the dialog is open and releases it when it closes.

Interaction: typing edits the field; Enter accepts (the text is handed to
``on_accept``); Esc or an outside click cancels. An optional ``validate(text)``
returning an error string keeps the dialog open and shows the message inline
(empty / duplicate names), so a bad value never silently closes the dialog.

Push it with :func:`show_input`, which sizes and centers the layer with the
shared drop-shadow intent the other PuiKit modals use, and can anchor it
over the active pane via ``region`` (the same contract as ``show_filter_list``).
"""

from __future__ import annotations

from typing import Any, Callable

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, focus_on_click
from puikit.panel import Rect
from puikit.widgets.base import Widget
from puikit.widgets.text_edit import TextEdit

from xefm.dialog_geometry import animate_open, draw_title_bar, pane_anchored_box
from xefm.completion import Completer, CompletionController
from xefm.candidate_list import CandidateListOverlay, overlay_geometry

#: Keys the candidate list consumes for navigation while it is showing; up/pageup
#: step the highlight backward, down/pagedown forward.
_NAV_KEYS = frozenset({"up", "down", "pageup", "pagedown"})
_NAV_UP = frozenset({"up", "pageup"})


class InputDialog(FocusContainer, Widget):
    """Modal single-line text prompt. Construct via :func:`show_input`, which
    sizes and pushes the layer; this class owns layout, focus, and events."""

    focusable = True
    # Always handles keys itself (escape closes), so it stays a focus stop.
    focus_stop_when_empty = True

    def __init__(
        self,
        *,
        title: str = "",
        prompt: str = "",
        text: str = "",
        on_accept: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_change: Callable[[str], None] | None = None,
        validate: Callable[[str], str | None] | None = None,
        select_all: bool = True,
        select_range: tuple[int, int] | None = None,
        completer: Completer | None = None,
        password: bool = False,
    ):
        self.title = title
        self.prompt = prompt
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        #: Fires with the field's current text after every edit keystroke, for
        #: live-updating prompts (incremental search). Never fires on Enter/Esc.
        self.on_change = on_change
        self.validate = validate
        self._panel: Any = None
        self._error = ""

        # ``password`` masks the field with a bullet glyph and disables clipboard
        # copy/cut of its contents (PuiKit ``TextEdit(mask=...)``), for prompts
        # like an encrypted-archive password.
        self.edit = TextEdit(text=text, mask="•" if password else None)
        # Caret at the end. With ``select_all`` the whole value is also selected,
        # so the first keystroke replaces it; without it the caret just sits at
        # the end, ready to append (jump-to-path's trailing separator).
        # ``select_range`` overrides both with a sub-span — rename selects only
        # the stem, so typing replaces the name body but keeps the extension.
        if select_range is not None:
            start, end = select_range
            start = max(0, min(start, len(text)))
            self.edit.cursor = max(start, min(end, len(text)))
            self.edit._anchor = start
        else:
            self.edit.cursor = len(text)
            self.edit._anchor = 0 if select_all else len(text)
        # Focus the field so the Panel's focus leaf resolves to it: that is what
        # engages the backend's text input (``begin_text_input`` → IME) while the
        # dialog is open. Without it ``focused_leaf`` stops at the dialog (which is
        # not a text widget), so IME never turns on — the field draws focused and
        # keys are routed manually, but composition never starts.
        self._focused: Any = self.edit
        self._field_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._size: tuple[float, float] = (0.0, 0.0)

        # TAB completion (optional). The controller mutates ``self.edit`` and
        # tracks the candidate state; the overlay is a separate, lower-z layer this
        # dialog pushes/positions/removes (created lazily on first activation). The
        # z is the dialog's own layer z, set by ``show_input``. Threaded: the
        # candidate listing runs on a worker, applied via ``_drain_completion`` /
        # ``_pump_completion``, so a slow mount never freezes the dialog (#246).
        self._completion = (CompletionController(self.edit, completer, threaded=True)
                            if completer is not None else None)
        self._completion_pump_cancel: Callable[[], None] | None = None
        self._overlay: CandidateListOverlay | None = None
        self._z = 70
        # Captured each draw so the overlay can be anchored to the field: the
        # dialog's absolute layer rect (to translate forwarded mouse coords) and
        # the field's absolute rect (to place the popup under/above it).
        self._dialog_rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._field_screen_rect = Rect(0.0, 0.0, 0.0, 0.0)

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self.edit]

    # --- outcome -------------------------------------------------------------

    def _accept(self) -> None:
        text = self.edit.text
        if self.validate is not None:
            error = self.validate(text)
            if error:
                self._error = error
                if self._panel is not None:
                    self._panel.render()
                return
        self._close()
        if self.on_accept is not None:
            self.on_accept(text)

    def _cancel(self) -> None:
        self._close()
        if self.on_cancel is not None:
            self.on_cancel()

    def _close(self) -> None:
        if self._completion_pump_cancel is not None:
            self._completion_pump_cancel()
            self._completion_pump_cancel = None
        if self._completion is not None:
            self._completion.dismiss()  # drop any in-flight candidate fetch
        self._remove_overlay()  # never leave a stray candidate layer behind
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()

    # --- completion overlay --------------------------------------------------

    def _overlay_slot(self) -> Any:
        """The candidate overlay's layer slot, or None when it isn't pushed."""
        panel = self._panel
        if panel is None or self._overlay is None:
            return None
        for slot in panel._layers:
            if slot.widget is self._overlay:
                return slot
        return None

    def _remove_overlay(self) -> None:
        if self._overlay is not None and self._panel is not None:
            self._panel.remove(self._overlay)  # no-op if it isn't pushed

    def _sync_overlay(self) -> None:
        """Reflect the controller's state onto the overlay layer: create+push it
        while candidates are showing, tear it down otherwise. The rect is a
        placeholder — ``draw`` positions the overlay each frame from measured field
        geometry (it draws after this dialog), so it never flashes at a wrong spot."""
        c = self._completion
        panel = self._panel
        if c is None or panel is None:
            return
        if c.active and c.candidates:
            if self._overlay is None:
                self._overlay = CandidateListOverlay(on_activate=self._on_candidate_click)
            if self._overlay_slot() is None:
                # Above the dialog (higher z) so the popup hugs the field, but
                # NON-INTERACTIVE so events/focus stay with the dialog beneath.
                r = self._field_screen_rect
                panel.push_layer(
                    self._overlay, z=self._z + 1, interactive=False,
                    hints={"x": r.x, "y": r.y + r.h, "w": 1.0, "h": 1.0, "shadow": True},
                )
            self._overlay.set_state(c.candidates, c.focused_index)
        else:
            self._remove_overlay()

    def _drain_completion(self) -> None:
        """Apply a threaded candidate fetch. A brief synchronous window lets a
        fast (local) listing land within the triggering key event — the overlay
        opens in the same frame, exactly as the old inline listing did — and a
        listing still running after it (a slow mount) is left to finish on its
        worker, its result picked up by a short ``call_later`` poll. Either way
        the dialog keeps taking keys throughout."""
        c = self._completion
        if c is None:
            return
        c.wait(0.02)
        c.pump()
        self._sync_overlay()
        if c.fetch_pending() and self._completion_pump_cancel is None and self._panel is not None:
            self._completion_pump_cancel = self._panel.call_later(0.03, self._pump_completion)

    def _pump_completion(self) -> None:
        """Poll tick for a fetch that outlived its synchronous window: apply an
        arrived result and repaint, re-arming until nothing is pending."""
        self._completion_pump_cancel = None
        c = self._completion
        if c is None or self._panel is None:
            return
        if c.pump():
            self._sync_overlay()
            self._panel.render()
        if c.fetch_pending():
            self._completion_pump_cancel = self._panel.call_later(0.03, self._pump_completion)

    def _on_candidate_click(self, index: int) -> None:
        """A candidate row was clicked: apply it, close the list, and notify a
        live prompt of the changed text (the enclosing event still triggers a
        render)."""
        c = self._completion
        if c is None:
            return
        c.apply_index(index)
        self._remove_overlay()
        if self.on_change is not None:
            self.on_change(self.edit.text)

    def _forward_overlay_click(self, event: Event) -> bool:
        """If a mouse event falls within the (lower-z, so non-topmost) overlay,
        consume it here — forwarding a click to the overlay's row hit-test — so it
        doesn't read as an outside-click that cancels the dialog. Coords arrive
        dialog-local; convert to absolute, then to overlay-local."""
        slot = self._overlay_slot()
        if slot is None or event.x is None:
            return False
        dx, dy, _dw, _dh = self._dialog_rect
        if not slot.rect.contains(event.x + dx, event.y + dy):
            return False
        if event.type is EventType.MOUSE_CLICK:
            self._overlay.handle_event(event.translated(dx - slot.rect.x, dy - slot.rect.y))
        return True

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme
        wu, _ = ctx.size_units
        surface_bg = theme.popup_bg if theme is not None else None
        box_style = Style(bg=surface_bg, fg=theme.popup_border if theme else None)
        # Frame the box at its exact (fractional) extent, not ctx.width/height —
        # those truncate to whole units and would draw the frame short of the fill
        # on a GUI backend where the height is fractional (grid rounds back the same).
        ctx.draw_box(0, 0, *ctx.size_units, box_style, hints={"fill": True})

        pad = 1.0
        y = pad
        if self.title:
            border = theme.popup_border if theme else None
            y = draw_title_bar(ctx, self.title, surface_bg=surface_bg, border=border, y=y)

        # Prompt label + field on one row; the field fills the rest of the width.
        field_x = 2.0
        if self.prompt:
            ctx.draw_text(2, y, self.prompt, Style(bg=surface_bg))
            field_x = 2.0 + ctx.measure_text(self.prompt + " ")
        field_w = max(1.0, wu - field_x - 2.0)
        # The field's own ``width`` caps how wide its box draws, so stretch it to
        # the slot we hand it — otherwise it keeps its default 24u and leaves a gap
        # to the dialog's right edge.
        self.edit.width = field_w
        self._field_rect = Rect(field_x, y, field_w, 1.0)
        ctx.draw_child(
            self.edit, field_x, y, field_w, 1.0, hints={"focused": True},
        )

        # Anchor geometry for the completion overlay. Capture this layer's absolute
        # rect (to translate forwarded mouse coords) and the field's absolute rect
        # (a placeholder anchor for the push). The overlay is a higher-z layer, so
        # it draws *after* this dialog: position its slot here, from the measured
        # width of the text before the token, and it lands correctly under the field
        # this same frame — on a proportional (GUI) font too, with no flash.
        dx, dy, dw, dh = ctx.screen_rect
        self._dialog_rect = (dx, dy, dw, dh)
        self._field_screen_rect = Rect(dx + field_x, dy + y, field_w, 1.0)
        c = self._completion
        if c is not None and c.active and self._overlay is not None:
            slot = self._overlay_slot()
            if slot is not None:
                # On-screen x of the token: measured from the field's *scroll*
                # position (``_view``), so a long, horizontally-scrolled path still
                # anchors the popup under the visible token, not off the right edge.
                # If the token start is scrolled off the left, anchor at the field.
                view = self.edit._view
                start = max(c.completion_start_pos, view)
                token_x = dx + field_x + 1.0 + ctx.measure_text(self.edit.text[view:start])
                row_h = ctx.line_height(Style(fg=theme.text if theme else None))
                sw, sh = self._panel.backend.size_units
                slot.rect = Rect(*overlay_geometry(
                    dx + field_x, dy + y, 1.0, token_x, c.candidates,
                    ctx.measure_text, row_h, sw, sh,
                ))
        y += 1

        if self._error:
            ctx.draw_text(2, y, self._error,
                          Style(bg=surface_bg, fg=(229, 110, 110), attr=TextAttribute.DIM))

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.IME_COMPOSITION:
            # In-progress IME composition (preedit): forward it to the field so it
            # renders inline. The modal layer receives every event exclusively, so
            # without this the composition never reaches the TextEdit and CJK input
            # is invisible until it commits (which arrives as ordinary KEY events).
            self.edit.handle_event(event)
            return True
        if event.type is EventType.KEY:
            key = event.key
            c = self._completion
            if key == "tab" and c is not None:
                # TAB completes the token: insert the common prefix and, when
                # several matches remain, open (or refresh) the candidate list.
                # The listing runs threaded; _drain_completion applies it.
                c.on_tab()
                self._drain_completion()
                return True
            if key == "escape":
                # Esc closes the candidate list first; a second Esc cancels.
                if c is not None and c.active:
                    c.dismiss()
                    self._remove_overlay()
                else:
                    self._cancel()
                return True
            if key == "enter":
                # A highlighted candidate is accepted into the field; with none
                # highlighted, Enter is an ordinary submit.
                if c is not None and c.accept():
                    self._remove_overlay()
                    if self.on_change is not None:
                        self.on_change(self.edit.text)
                else:
                    self._accept()
                return True
            if c is not None and c.active and key in _NAV_KEYS:
                c.move_focus(-1 if key in _NAV_UP else 1)
                self._sync_overlay()
                return True
            # Ordinary editing. Clears a stale validation message as the user
            # retypes, and refreshes the candidate list if it's open.
            self._error = ""
            before = self.edit.text
            self.edit.handle_event(event)
            if self.edit.text != before:
                if c is not None:
                    c.on_text_changed()
                    self._drain_completion()
                if self.on_change is not None:
                    self.on_change(self.edit.text)
            return True

        if event.type in (
            EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
            EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL,
        ):
            if event.x is not None and self._field_rect.contains(event.x, event.y):
                if event.type is EventType.MOUSE_DOWN:
                    focus_on_click(self, self.edit)
                local = event.translated(-self._field_rect.x, -self._field_rect.y)
                self.edit.handle_event(local)
            elif self._forward_overlay_click(event):
                pass  # a click on the candidate list, not an outside-click cancel
            elif event.type is EventType.MOUSE_CLICK and event.x is not None and not (
                0 <= event.x < self._size[0] and 0 <= event.y < self._size[1]
            ):
                self._cancel()  # click outside the dialog dismisses it
            return True
        return True  # modal: swallow everything else


def show_input(
    panel: Any,
    *,
    title: str = "",
    prompt: str = "",
    text: str = "",
    on_accept: Callable[[str], None] | None = None,
    on_cancel: Callable[[], None] | None = None,
    on_change: Callable[[str], None] | None = None,
    validate: Callable[[str], str | None] | None = None,
    select_all: bool = True,
    select_range: tuple[int, int] | None = None,
    completer: Completer | None = None,
    region: tuple[float, float] | None = None,
    anchor: str = "center",
    z: int = 70,
    password: bool = False,
) -> InputDialog:
    """Push a modal :class:`InputDialog` over ``panel`` and return it.

    Sized to a comfortable fraction of the window and centered, with the shared
    drop-shadow modal intent. The entered text is reported through
    ``on_accept``; ``on_cancel`` fires on escape / outside-click; ``on_change``
    fires live on every keystroke (incremental search). ``region`` is an optional
    ``(x, width)`` column span to anchor the dialog over the pane it acts on (see
    :func:`xefm.filter_list_dialog.show_filter_list`). ``anchor="top"`` pins the box
    near the top of the window instead of centering it, keeping the list below
    visible.

    Pass ``completer`` (a :class:`xefm.completion.Completer`, e.g.
    :class:`xefm.completion.FilepathCompleter`) to enable TAB completion: TAB then
    inserts the longest common prefix and, when several matches remain, opens a
    candidate list (a separate overlay layer below/above the field) that narrows
    as you type and is navigable with the arrow keys.

    Pass ``password=True`` for a masked field (typed characters show as bullets
    and copy/cut of the value is disabled) — used for encrypted-archive
    passwords."""
    dialog = InputDialog(
        title=title, prompt=prompt, text=text,
        on_accept=on_accept, on_cancel=on_cancel, on_change=on_change,
        validate=validate, select_all=select_all, select_range=select_range,
        completer=completer, password=password,
    )
    dialog._z = z
    sw, sh = panel.backend.size_units
    w = max(36.0, min(sw * 0.6, 64.0))
    # pad + title bar + field + error row + pad. Error shares the row directly
    # below the field, so no blank line is reserved for it. The compact GUI title
    # bar pulls the field up ~1 row, so the box is one row shorter there to keep
    # the bottom padding balanced (grid keeps the whole-row title bar).
    if title:
        h = 5.0 if panel.backend.capabilities.supports("vector_shapes") else 6.0
    else:
        h = 4.0
    hints: dict[str, Any] = {"shadow": True, "w": w, "h": h}
    if anchor == "top":
        hints["y"] = 2.0
    if region is not None:
        w, x = pane_anchored_box(w, sw, region)
        hints["w"] = w
        hints["x"] = x
    dialog._panel = panel
    panel.push_layer(dialog, z=z, hints=hints)
    animate_open(panel, dialog)
    return dialog
