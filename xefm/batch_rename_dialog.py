"""BatchRenameDialog — modal regex batch-rename for the PuiKit port.

The batch-rename dialog: rename many files at
once with a regular-expression *search* pattern and a *replace* pattern, with a
live preview of every ``original → new`` result before anything touches disk.

The replace pattern supports these macros:

- ``\\0`` — the whole match; ``\\1``..``\\9`` — capture groups.
- ``\\d`` — the 1-based index of the file in the batch.

Only the matched span of each name is replaced; the rest is kept. The preview
flags names that are invalid or that collide (with an existing file or with
another row in the batch), and Enter refuses to run while any collision stands.

Two ``TextEdit`` fields (Tab switches between them) sit above a ``ListView``
preview. Push it with :func:`show_batch_rename`.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Sequence

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, focus_on_click
from puikit.panel import Rect
from puikit.widgets.base import Widget
from puikit.widgets.list import ListView

from xefm import name_key
from xefm.dialog_geometry import animate_open, draw_title_bar

#: Characters we refuse in a result name.
_INVALID_CHARS = set('/\\:*?"<>|')
#: Preview-list scroll keys (unsuffixed backend names, matching ListView).
_SCROLL_KEYS = frozenset({"up", "down", "pageup", "pagedown", "home", "end"})


def _is_valid_name(name: str) -> bool:
    if not name or name in (".", ".."):
        return False
    return not any(ch in _INVALID_CHARS for ch in name)


def compute_preview(files: Sequence[Any], search: str, replace: str) -> list[dict]:
    """Compute the ``original → new`` plan for ``files`` under the search/replace
    patterns. Returns one dict per file with ``original``, ``new``, ``valid``,
    ``conflict``, and ``file``. Pure (no filesystem writes), so it is unit-test
    friendly and safe to call on every keystroke for the live preview.

    Everything here runs on NFC: the name matched against, the pattern, the
    replacement, and the name written back (:mod:`xefm.name_key`). Matching has
    to, or a pattern typed at an IME — which emits composed text — silently finds
    nothing in a decomposed name, which is the name the pane displays; Finder
    normalizes before matching for the same reason. Writing NFC is where XeFM
    parts company with Finder, which still composes *down* to NFD as HFS+ did:
    the choice is cosmetic on APFS, whose lookup ignores the difference, and this
    is one program on three platforms that copies files between them, where a
    per-OS spelling of the same rename is not cosmetic at all.

    A name the pattern does not match comes out equal to what went in, so it is
    skipped by the apply loop: normalization only ever rides along with a rename
    that was asked for, never on its own."""
    rows: list[dict] = []
    try:
        # Metacharacters are ASCII, so composing the pattern only touches its
        # literals — which is exactly the half that has to match the name.
        pattern = re.compile(name_key.nfc(search)) if search else None
    except re.error:
        pattern = None  # invalid regex → everything shown unchanged
    replace = name_key.nfc(replace)

    for i, entry in enumerate(files):
        name = name_key.nfc(entry.name)
        match = pattern.search(name) if pattern else None
        if match:
            repl = replace
            for group in range(10):
                placeholder = f"\\{group}"
                if placeholder in repl:
                    if group == 0:
                        repl = repl.replace(placeholder, match.group(0))
                    elif group <= len(match.groups()):
                        repl = repl.replace(placeholder, match.group(group) or "")
                    else:
                        repl = repl.replace(placeholder, "")
            repl = repl.replace("\\d", str(i + 1))
            # Composed name spliced with composed replacement is very nearly
            # composed already — but a replacement opening on a combining mark
            # would join the character before it, so settle it here and let
            # everything downstream, the collision key included, assume NFC.
            new = name_key.nfc(name[: match.start()] + repl + name[match.end():])
            valid = _is_valid_name(new)
            conflict = (entry.parent / new).exists() and new != name
        else:
            new, valid, conflict = name, True, False
        rows.append({"original": name, "new": new, "valid": valid,
                     "conflict": conflict, "file": entry})

    # Second pass: two rows producing the same new name in the same directory
    # collide with each other, even if neither exists on disk yet. The names are
    # NFC by construction, which is what makes this catch the collision that used
    # to slip through — two rows landing on the same file under different
    # spellings of one name. Finder catches it too, and disambiguates with a
    # " 2"; here it is the conflict that blocks the rename.
    seen: dict[tuple, list[dict]] = {}
    for row in rows:
        if row["original"] == row["new"]:
            continue
        key = (str(row["file"].parent), row["new"])
        seen.setdefault(key, []).append(row)
    for group_rows in seen.values():
        if len(group_rows) > 1:
            for row in group_rows:
                row["conflict"] = True
    return rows


class BatchRenameDialog(FocusContainer, Widget):
    """Modal batch-rename dialog. Construct via :func:`show_batch_rename`."""

    focusable = True
    focus_stop_when_empty = True

    def __init__(
        self,
        files: Sequence[Any],
        *,
        on_done: Callable[[int, list[str]], None] | None = None,
    ):
        from puikit.widgets.text_edit import TextEdit
        self.files = list(files)
        self.on_done = on_done
        self._panel: Any = None
        self._status = ""

        self.search_edit = TextEdit(on_change=lambda _t: self._refresh_preview())
        self.replace_edit = TextEdit(on_change=lambda _t: self._refresh_preview())
        self.active = self.search_edit
        self.preview_list = ListView([])
        self.preview: list[dict] = []

        self._search_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._replace_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._list_rect = Rect(0.0, 0.0, 0.0, 0.0)
        self._size: tuple[float, float] = (0.0, 0.0)
        self._refresh_preview()

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self.active]

    def get_focused(self) -> Any:
        # The active field IS the focused leaf, so report it directly (Tab flips
        # ``active``). This is what makes the Panel resolve focus to a TextEdit and
        # engage the backend's text input / IME while the dialog is open.
        return self.active

    # --- preview -------------------------------------------------------------

    def _refresh_preview(self) -> None:
        search = self.search_edit.text
        self.preview = compute_preview(self.files, search, self.replace_edit.text)
        rows = []
        for row in self.preview:
            if row["conflict"] or not row["valid"]:
                mark = "! "
            elif row["original"] != row["new"]:
                mark = "→ "
            else:
                mark = "  "
            if row["original"] == row["new"]:
                rows.append(f"{mark}{row['original']}")
            else:
                rows.append(f"{mark}{row['original']}  →  {row['new']}")
        self.preview_list.set_items(rows)

        changed = sum(1 for r in self.preview if r["original"] != r["new"])
        problems = sum(1 for r in self.preview if r["conflict"] or not r["valid"])
        if search and not self._regex_ok(search):
            self._status = "Invalid regex pattern"
        elif problems:
            self._status = f"{changed} to rename · {problems} conflict/invalid (resolve to proceed)"
        else:
            self._status = f"{changed} to rename"

    @staticmethod
    def _regex_ok(pattern: str) -> bool:
        try:
            re.compile(pattern)
            return True
        except re.error:
            return False

    # --- outcome -------------------------------------------------------------

    def _accept(self) -> None:
        if any(r["conflict"] or not r["valid"] for r in self.preview):
            self._status = "Resolve conflicts / invalid names before renaming"
            self._render()
            return
        success = 0
        errors: list[str] = []
        for row in self.preview:
            if row["original"] == row["new"]:
                continue
            try:
                row["file"].rename(row["file"].parent / row["new"])
                success += 1
            except OSError as exc:
                errors.append(f"{row['original']}: {exc}")
        self._close()
        if self.on_done is not None:
            self.on_done(success, errors)

    def _cancel(self) -> None:
        self._close()

    def _close(self) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme
        wu, hu = ctx.size_units
        surface_bg = theme.popup_bg if theme is not None else None
        muted = theme.muted_text if theme is not None else None
        box_style = Style(bg=surface_bg, fg=theme.popup_border if theme else None)
        # Exact (fractional) extent, not ctx.width/height: those truncate to whole
        # units and draw the frame short of the fill on a fractional-height GUI box.
        ctx.draw_box(0, 0, *ctx.size_units, box_style, hints={"fill": True})

        pad = 1.0
        y = pad
        border = theme.popup_border if theme else None
        y = draw_title_bar(ctx, f"Batch Rename — {len(self.files)} files",
                           surface_bg=surface_bg, border=border, y=y)

        # Both fields share a left edge past the wider of the two labels.
        labels = ("Search:", "Replace:")
        field_x = 2.0 + max(ctx.measure_text(s + " ") for s in labels)
        field_w = max(1.0, wu - field_x - 2.0)

        ctx.draw_text(2, y, labels[0], Style(bg=surface_bg))
        self._search_rect = Rect(field_x, y, field_w, 1.0)
        ctx.draw_child(self.search_edit, field_x, y, field_w, 1.0,
                       hints={"focused": self.active is self.search_edit})
        y += 1
        ctx.draw_text(2, y, labels[1], Style(bg=surface_bg))
        self._replace_rect = Rect(field_x, y, field_w, 1.0)
        ctx.draw_child(self.replace_edit, field_x, y, field_w, 1.0,
                       hints={"focused": self.active is self.replace_edit})
        y += 2

        ctx.draw_text(2, y, r"\0 match · \1-\9 groups · \d index · Tab switch · Enter rename · Esc cancel",
                      Style(bg=surface_bg, fg=muted, attr=TextAttribute.DIM))
        y += 1
        if self._status:
            ctx.draw_text(2, y, self._status, Style(bg=surface_bg, fg=muted))
        y += 2

        list_h = max(1.0, hu - y - pad)
        self._list_rect = Rect(2.0, y, max(1.0, wu - 4.0), list_h)
        # The "bg" hint hands the list the popup surface as its inherited
        # background — otherwise its bg=None rows fall through to the terminal's
        # default colors on a grid backend (dark bands over the dialog).
        ctx.draw_child(self.preview_list, self._list_rect.x, self._list_rect.y,
                       self._list_rect.w, self._list_rect.h,
                       hints={"focused": False, "bg": surface_bg})

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.IME_COMPOSITION:
            # Forward IME composition (preedit) to the active field (Tab switches
            # which) so CJK input renders inline. The modal layer receives every
            # event, so composition must be relayed to the field explicitly.
            self.active.handle_event(event)
            return True
        if event.type is EventType.KEY:
            key = event.key
            if key == "escape":
                self._cancel()
            elif key == "enter":
                self._accept()
            elif key == "tab":
                self.active = (self.replace_edit if self.active is self.search_edit
                               else self.search_edit)
            elif key in _SCROLL_KEYS:
                self.preview_list.handle_event(event)
            else:
                self.active.handle_event(event)  # typing edits the active field
            return True

        if event.type in (
            EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
            EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL,
        ):
            if event.x is None:
                return True
            for rect, editor in ((self._search_rect, self.search_edit),
                                 (self._replace_rect, self.replace_edit)):
                if rect.contains(event.x, event.y):
                    if event.type is EventType.MOUSE_DOWN:
                        self.active = editor
                        focus_on_click(self, editor)
                    editor.handle_event(event.translated(-rect.x, -rect.y))
                    return True
            if self._list_rect.contains(event.x, event.y):
                self.preview_list.handle_event(
                    event.translated(-self._list_rect.x, -self._list_rect.y))
            elif event.type is EventType.MOUSE_CLICK and not (
                0 <= event.x < self._size[0] and 0 <= event.y < self._size[1]
            ):
                self._cancel()
            return True
        return True  # modal: swallow everything else


def show_batch_rename(
    panel: Any,
    files: Sequence[Any],
    *,
    on_done: Callable[[int, list[str]], None] | None = None,
    z: int = 70,
) -> BatchRenameDialog:
    """Push a modal :class:`BatchRenameDialog` over ``panel`` and return it.

    Sized large (the preview wants room) and centered, with the shared drop-shadow
    modal intent. ``on_done(success_count, errors)`` fires after a successful run;
    the dialog reports nothing on cancel."""
    dialog = BatchRenameDialog(files, on_done=on_done)
    sw, sh = panel.backend.size_units
    w = max(56.0, min(sw * 0.8, 110.0))
    h = max(14.0, min(sh * 0.85, float(len(files) + 10)))
    dialog._panel = panel
    panel.push_layer(dialog, z=z, hints={"shadow": True, "w": w, "h": h})
    animate_open(panel, dialog)
    return dialog
