"""The dialog an AI agent's multiple-choice question is answered in (#959).

Claude Code's ``AskUserQuestion`` asks one or more questions, each with a few
options - pick one, or (``multiSelect``) any number - and always takes an
answer of the user's own as well. One dialog per question, in the
:class:`~xefm.choice_dialog.ChoiceDialog` mold: the question over its
options, each option's description muted after its label, then an
**Other** row whose field takes a typed answer.

- Single choice: ``( )`` rows. **Enter** (or a click, or the option's
  number) answers with the row under the cursor.
- Multiple choice: ``[ ]`` rows. **Space** (a click, the number) checks or
  unchecks; **Enter** answers with what is checked - the row under the
  cursor when nothing is.
- On the **Other** row typing goes into its field; Enter answers with it
  (with the checked rows too, in a multiple-choice question).
- **Escape** declines: the result is None.

The result is the list of the chosen labels (the typed answer as typed).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer
from puikit.font import Font
from puikit.theme import DEFAULT_THEME
from puikit.widgets.base import CONTROL_HEIGHT, Widget
from puikit.widgets.text_edit import TextEdit

from xefm.dialog_geometry import HINT_ROWS, animate_open, draw_hint_row, draw_title_bar

_GRID_ROW_PITCH = 1.0
_GUI_ROW_PITCH = 1.3
_MAX_W = 96.0
_OTHER = "Other:"


def _wrap(text: str, width: float, measure) -> list[str]:
    """``text`` wrapped to ``width``: at a space where one fits, else at the
    character that would cross (Japanese has no spaces)."""
    out: list[str] = []
    for para in text.split("\n"):
        line = ""
        for ch in para:
            if measure(line + ch) > width and line:
                cut = line.rfind(" ")
                if cut > 0 and ch != " ":
                    out.append(line[:cut])
                    line = line[cut + 1:] + ch
                else:
                    out.append(line.rstrip())
                    line = "" if ch == " " else ch
            else:
                line += ch
        out.append(line)
    return out


class QuestionDialog(FocusContainer, Widget):
    focusable = True
    focus_stop_when_empty = True

    def __init__(self, question: str, options: list[dict], *, multi: bool = False,
                 title: str = "Question",
                 on_result: Callable[[Optional[list[str]]], None] | None = None):
        self.question = question
        self.options = [o for o in options if isinstance(o.get("label"), str)]
        self.multi = multi
        self.title = title
        self.on_result = on_result
        self.checked: set[int] = set()
        #: The row under the cursor; ``len(options)`` is the Other row.
        self.index = 0
        self.other = TextEdit(width=40, placeholder="type your own answer")
        self._focused: Any = None
        self._panel: Any = None
        self._size = (0.0, 0.0)
        self._row_hits: list[tuple[int, float, float]] = []
        self._closed = False

    # --- rows --------------------------------------------------------------------

    @property
    def _on_other(self) -> bool:
        return self.index == len(self.options)

    def _mark(self, i: int) -> str:
        if self.multi:
            return "[x]" if i in self.checked else "[ ]"
        return "(•)" if i == self.index else "( )"

    def _label(self, i: int) -> tuple[str, str]:
        opt = self.options[i]
        num = f"{i + 1}. " if i < 9 else ""
        return f"{self._mark(i)} {num}{opt['label']}", str(opt.get("description") or "")

    def focus_children(self) -> list[Any]:
        return [self.other] if self._on_other else []

    def _hint(self) -> str:
        if self.multi:
            return "↑/↓ move · Space check · Enter answer · Esc decline"
        return "↑/↓ or number to choose · Enter answer · Esc decline"

    # --- sizing ------------------------------------------------------------------

    def _layout(self, measure, w: float) -> list[str]:
        return _wrap(self.question, w - 4.0, measure)

    def show(self, panel: Any, *, z: int = 90) -> None:
        self._panel = panel
        sw, sh = panel.backend.size_units
        prop = Style(font=Font())
        measure = lambda t: panel.backend.measure_text(t, prop)  # noqa: E731
        vector = panel.backend.capabilities.supports("vector_shapes")
        pitch = _GUI_ROW_PITCH if vector else _GRID_ROW_PITCH
        widest = max([measure(self.question) + 4.0, measure(self._hint()) + 4.0]
                     + [measure(self._label(i)[0] + "   " + self._label(i)[1]) + 6.0
                        for i in range(len(self.options))])
        w = float(min(sw - 4.0, _MAX_W, max(48.0, widest)))
        lines = self._layout(measure, w)
        other_h = CONTROL_HEIGHT if vector else 1.0
        h = 3.0 + len(lines) + 1.0 + len(self.options) * pitch + other_h + 1.0 + HINT_ROWS
        panel.push_layer(self, z=z, hints={"shadow": True, "w": w, "h": min(sh - 2.0, h)})
        animate_open(panel, self)

    # --- drawing -----------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme or DEFAULT_THEME
        bg = theme.popup_bg
        w, h = ctx.size_units
        ctx.draw_box(0, 0, w, h, Style(bg=bg, fg=theme.popup_border), hints={"fill": True})
        y = draw_title_bar(ctx, self.title, surface_bg=bg, border=theme.popup_border, y=1.0)
        y += 0.5 if ctx.vector_shapes else 0.0
        for line in self._layout(ctx.measure_text, w):
            ctx.draw_text(2.0, y, line, Style(fg=theme.text, bg=bg))
            y += 1.0
        y += 1.0
        line_h = ctx.line_height()
        pitch = _GUI_ROW_PITCH if ctx.vector_shapes else _GRID_ROW_PITCH
        vy = max(0.0, (pitch - line_h) / 2.0)
        self._row_hits = []
        for i in range(len(self.options)):
            sel = i == self.index
            row_bg = theme.selection_active_bg if sel else bg
            if sel:
                ctx.round_rect(2.0, y + vy - 0.1, w - 4.0, line_h + 0.2,
                               Style(bg=row_bg), radius=None, hints={"fill": True})
            label, desc = self._label(i)
            ctx.draw_text(3.0, y + vy, label, Style(fg=theme.text, bg=row_bg))
            if desc:
                x = 3.0 + ctx.measure_text(label + "   ")
                room = w - 3.0 - x
                while desc and ctx.measure_text(desc) > room:
                    desc = desc[:-2] + "…" if len(desc) > 2 else ""
                if desc:
                    ctx.draw_text(x, y + vy, desc, Style(fg=theme.muted_text, bg=row_bg))
            self._row_hits.append((i, y, y + pitch))
            y += pitch
        # The Other row: a label, then a field taking a typed answer.
        sel = self._on_other
        other_h = CONTROL_HEIGHT if ctx.vector_shapes else 1.0
        row_bg = theme.selection_active_bg if sel else bg
        if sel:
            ctx.round_rect(2.0, y - 0.1, w - 4.0, other_h + 0.2,
                           Style(bg=row_bg), radius=None, hints={"fill": True})
        mark = ("[x]" if self.other.text.strip() else "[ ]") if self.multi else \
            ("(•)" if sel else "( )")
        label = f"{mark} {_OTHER}"
        ty = y + (other_h - line_h) / 2.0
        ctx.draw_text(3.0, ty, label, Style(fg=theme.text, bg=row_bg))
        fx = 3.0 + ctx.measure_text(label + " ")
        self.other.width = int(max(8.0, w - fx - 3.0))
        ctx.draw_child(self.other, fx, y, w - fx - 3.0, other_h, hints={"focused": sel})
        self._row_hits.append((len(self.options), y, y + other_h))
        draw_hint_row(ctx, self._hint(), surface_bg=bg, border=theme.popup_border)

    # --- events ------------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY:
            self._key(event)
        elif event.type is EventType.IME_COMPOSITION and self._on_other:
            self.other.handle_event(event)
        elif event.type is EventType.MOUSE_CLICK:
            self._click(event)
        self._render()
        return True  # modal

    def _key(self, event: Event) -> None:
        key = event.key
        n = len(self.options) + 1
        if key == "escape":
            self._finish(None)
        elif key == "enter":
            self._answer()
        elif key == "up":
            self.index = (self.index - 1) % n
        elif key == "down" or (key == "tab" and not self._on_other):
            self.index = (self.index + 1) % n
        elif self._on_other:
            self.other.handle_event(event)
        elif key == "space" and self.multi:
            self.checked ^= {self.index}
        elif event.char and event.char.isdigit() and event.char != "0" \
                and int(event.char) <= len(self.options) and not event.modifiers - {"shift"}:
            i = int(event.char) - 1
            self.index = i
            if self.multi:
                self.checked ^= {i}
            else:
                self._answer()

    def _click(self, event: Event) -> None:
        if event.x is None or event.y is None:
            return
        w, h = self._size
        if not (0 <= event.x < w and 0 <= event.y < h):
            return  # a question is answered or declined, not clicked away
        for i, y0, y1 in self._row_hits:
            if y0 <= event.y < y1 and 2.0 <= event.x < w - 2.0:
                self.index = i
                if i == len(self.options):
                    return
                if self.multi:
                    self.checked ^= {i}
                else:
                    self._answer()
                return

    def _answer(self) -> None:
        typed = self.other.text.strip()
        if self.multi:
            picked = [self.options[i]["label"] for i in sorted(self.checked)]
            if typed:
                picked.append(typed)
            if not picked and not self._on_other:
                picked = [self.options[self.index]["label"]]
            if picked:
                self._finish(picked)
            return
        if self._on_other:
            if typed:
                self._finish([typed])
            return
        self._finish([self.options[self.index]["label"]])

    def _finish(self, result: Optional[list[str]]) -> None:
        if self._closed:
            return
        self._closed = True
        if self._panel is not None and self._panel.has_layer(self):
            self._panel.remove_layer(self)
        if self.on_result is not None:
            self.on_result(result)

    def _render(self) -> None:
        if self._panel is not None and not self._closed:
            self._panel.render()


def show_question_dialog(panel: Any, question: str, options: list[dict], *,
                         multi: bool = False, title: str = "Question",
                         on_result: Callable[[Optional[list[str]]], None] | None = None,
                         z: int = 90) -> QuestionDialog:
    """Push a :class:`QuestionDialog`; ``on_result`` gets the chosen labels,
    or None when the user declined."""
    dialog = QuestionDialog(question, options, multi=multi, title=title, on_result=on_result)
    dialog.show(panel, z=z)
    return dialog
