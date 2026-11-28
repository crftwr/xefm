"""Key hints: what a bar says it answers to, drawn and clicked one way.

The file manager's status bar, a session's screen, a viewer's status bar and
a dialog's hint band all name keys - ``C copy``, ``Enter choose``, ``q/Esc
close``. They are built here as :class:`Hint` parts and drawn by
:func:`draw_hints`, so they look the same everywhere and each can be clicked:

- **The look.** A part's key is drawn in the full text colour (bold where the
  backend draws sub-cell), its words muted, and parts stand :data:`GAP` apart
  - the key's emphasis is what shows where one part ends and the next begins
  (a `` · `` or a run of spaces between parts of one colour did not).
- **The click.** A part with one key is a target over its whole text; a part
  naming several - a pair (``q/Esc``, ``n/Shift-N``) or an arrow cluster
  (``↑↓``, ``Shift-↑↓←→``) - makes each key a target of its own. A target runs
  its :attr:`Key.run`: a callable is called; left ``None``, the click presses
  the key, handing the widget the key event it would have sent, so it does
  exactly what the key does under any keymap. A part with no keys
  (:func:`note`: ``12 rows``, ``type to edit``) is no target.
- **Under the pointer** a target shows it can be clicked (:func:`hover_part`).

:func:`click_hint` is what a widget calls first in ``handle_event`` with the
targets :func:`draw_hints` returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.text import elide

#: The space between two parts, in base units: two cells on a grid.
GAP = 2.0
#: The plain-text form's gap (:func:`hints_text`) - two cells, as drawn.
GAP_TEXT = "  "

#: Display modifier -> key expression modifier (the inverse of
#: ``KeyBindings._MOD_DISPLAY``).
_MODS = {"cmd": "Command", "command": "Command", "ctrl": "Ctrl", "control": "Ctrl",
         "opt": "Option", "option": "Option", "alt": "Alt", "shift": "Shift"}

#: Display name -> key expression name, for the named keys (lower-cased; the
#: inverse of ``KeyBindings._KEY_DISPLAY``).
_NAMED = {"enter": "ENTER", "return": "ENTER", "esc": "ESCAPE", "escape": "ESCAPE",
          "tab": "TAB", "space": "SPACE", "backspace": "BACKSPACE", "del": "DELETE",
          "delete": "DELETE", "ins": "INSERT", "insert": "INSERT", "pgup": "PAGE_UP",
          "pgdn": "PAGE_DOWN", "home": "HOME", "end": "END",
          "↑": "UP", "↓": "DOWN", "←": "LEFT", "→": "RIGHT"}

_ARROWS = "↑↓←→"
_MOD_PREFIX = re.compile(r"^(cmd|command|ctrl|control|opt|option|alt|shift)[-+]",
                         re.IGNORECASE)
_FKEY = re.compile(r"^f([1-9]|1[0-9]|2[0-4])$", re.IGNORECASE)


# --- the parts ------------------------------------------------------------------


@dataclass(frozen=True)
class Key:
    """One key a part names, as shown (``text``). ``press`` is the key a
    click presses when it is not the text itself (an arrow of a cluster
    under a shared modifier: ``↓`` pressing ``Shift-↓``). ``run`` is what a
    click does instead of pressing it: a callable."""
    text: str
    press: str = ""
    run: Callable[[], Any] | None = None


@dataclass(frozen=True)
class Hint:
    """One part of a hint line: its keys, then its words."""
    keys: tuple[Key, ...] = ()
    label: str = ""
    #: Between the keys as shown: ``/`` for a pair, nothing for a cluster.
    joiner: str = "/"

    @property
    def key_text(self) -> str:
        return self.joiner.join(k.text for k in self.keys)

    @property
    def text(self) -> str:
        return " ".join(t for t in (self.key_text, self.label) if t)


def _nothing() -> None:
    """The run of a key this module cannot press: shown, never a target."""
    return None


def key(display: str, label: str = "", run: Callable[[], Any] | None = None) -> Hint:
    """The part naming ``display`` - one key (``"Enter"``, ``"Shift-Tab"``),
    a pair (``"q/Esc"``) or an arrow cluster (``"↑↓"``, ``"Shift-↑↓←→"``) -
    and saying ``label``. ``run`` is what a click on the part does instead of
    pressing its key (a part of one key)."""
    if not display:
        return note(label)
    if _is_key(display):
        return Hint((Key(display, run=run),), label)
    if "/" in display[1:-1]:
        pieces = display.split("/")
        if all(p and _is_key(p) for p in pieces):
            return Hint(tuple(Key(p) for p in pieces), label, "/")
    _mods, rest = _split_mods(display)
    if len(rest) > 1 and all(c in _ARROWS for c in rest):
        prefix = display[:len(display) - len(rest)]
        keys = tuple(Key(prefix + c if i == 0 else c, press=prefix + c)
                     for i, c in enumerate(rest))
        return Hint(keys, label, "")
    # Not a key this module can read (a sequence such as "g g", a phrase):
    # shown as a key, run only where the caller said what it runs.
    return Hint((Key(display, run=run or _nothing),), label)


def note(text: str) -> Hint:
    """A part that names no key - a count, a state, a word of guidance."""
    return Hint((), text)


def hints_text(hints: Sequence[Hint] | str) -> str:
    """The line as plain text, parts :data:`GAP_TEXT` apart - for a sizing
    estimate, a log or a test."""
    if isinstance(hints, str):
        return hints
    return GAP_TEXT.join(h.text for h in hints if h.text)


def hints_width(hints: Sequence[Hint] | str, measure: Callable[[str], float]) -> float:
    """About how wide the line draws, by ``measure`` (plain text): the parts
    and the gaps between them."""
    if isinstance(hints, str):
        return measure(hints)
    parts = [h for h in hints if h.text]
    # A key draws bold where the backend draws sub-cell: a tenth wider, about.
    bold = sum(measure(h.key_text) for h in parts if h.keys) * 0.1
    return sum(measure(h.text) for h in parts) + GAP * max(0, len(parts) - 1) + bold


# --- reading a displayed key ------------------------------------------------------


def _split_mods(token: str) -> tuple[list[str], str]:
    """``"Shift-Ctrl-x"`` -> ``(["Shift", "Ctrl"], "x")``."""
    mods = []
    while len(token) > 1:
        m = _MOD_PREFIX.match(token)
        if m is None or len(token) == m.end():
            break
        mods.append(_MODS[m.group(1).lower()])
        token = token[m.end():]
    return mods, token


def _base_expr(base: str) -> str | None:
    """The key expression for a displayed key name, or None if it is none."""
    named = _NAMED.get(base.lower())
    if named is not None:
        return named
    if len(base) == 1:
        return base if base.isprintable() and not base.isspace() else None
    if _FKEY.match(base):
        return base.upper()
    return None


def _is_key(display: str) -> bool:
    return _base_expr(_split_mods(display)[1]) is not None


def key_event_for(display: str) -> Event | None:
    """The key event a displayed key (``"Enter"``, ``"Shift-Tab"``,
    ``"Ctrl+J"``, ``"Cmd--"``, ``"q"``) sends, or None if ``display`` names
    no key."""
    mods, base = _split_mods(display)
    expr = _base_expr(base)
    if expr is None:
        return None
    from xefm.terminal import key_event
    try:
        return key_event("-".join(mods + [expr]))
    except Exception:  # noqa: BLE001 - a name the keymap cannot parse is no key
        return None


# --- drawing ------------------------------------------------------------------------


@dataclass(frozen=True)
class HintHit:
    """One click target drawn on a hint row, in the widget's own units: what
    it runs (a callable), or the key event it presses."""
    x0: float
    x1: float
    y0: float
    y1: float
    target: Any


def key_style(ctx, muted: Style, base=None) -> Style:
    """A part's key: the full text colour, inked on the bar, bold where the
    backend draws sub-cell (on a grid the colour alone sets it apart, and a
    terminal's bold may change the colour as well)."""
    theme = ctx.theme
    fg = theme.text if theme is not None else muted.fg
    on = base or muted.bg
    if fg is not None and on is not None and hasattr(ctx, "ink"):
        fg = ctx.ink(fg, on=on)
    attr = TextAttribute.BOLD if getattr(ctx, "vector_shapes", False) else TextAttribute.NORMAL
    return Style(fg=fg, bg=muted.bg, attr=attr, font=muted.font)


def hover_part(ctx, x: float, part, style: Style | None = None, y: float = 0.0,
               base=None) -> bool:
    """Show that ``part`` - text already drawn at ``x`` on a bar's row in
    ``style``, or a list of ``(text, style)`` runs drawn one after another -
    is clickable, while the pointer is over it: a backing behind it (rounded
    where the backend draws sub-cell, its cells on a grid), its text in the
    full text colour, and the pointing hand (#1019 hand check). ``base`` is
    the colour the bar is drawn in, where the draw context does not carry it.
    Whether it is hovered."""
    runs = [(part, style or Style())] if isinstance(part, str) else list(part)
    widths = [ctx.measure_text(t, s) for t, s in runs]
    w = sum(widths)
    if w <= 0 or not ctx.pointer_in(x, y, w, 1.0):
        return False
    from xefm.file_pane import DEFAULT_BG
    from xefm.tab_strip import hover_backing
    theme = ctx.theme
    base = (getattr(ctx, "background", None) or base or runs[0][1].bg
            or theme.surface_bg("status") or DEFAULT_BG)
    backing = hover_backing(theme, base, getattr(ctx, "surface_opacity", 1.0))
    ink = ctx.ink(theme.text, on=backing) if hasattr(ctx, "ink") else theme.text
    if ctx.vector_shapes:
        bw = (ctx.base_size or (0, 0))[0]
        pad = 3.0 / bw if bw else 0.3
        ctx.round_rect(x - pad, y, w + 2 * pad, 1.0, Style(bg=backing), radius=4.0,
                       hints={"fill": True})
    at = x
    for (text, s), tw in zip(runs, widths):
        bg = None if ctx.vector_shapes else backing
        ctx.draw_text(at, y, text, Style(fg=ink, bg=bg, attr=s.attr, font=s.font))
        at += tw
    ctx.set_cursor("pointer")
    return True


def draw_hints(ctx, x: float, y: float, hints: Sequence[Hint] | str, *,
               avail: float, muted: Style, base=None) -> list[HintHit]:
    """Draw the line ``hints`` at ``(x, y)`` within ``avail`` units: each
    part's keys emphasised (:func:`key_style`), its words in ``muted``, parts
    :data:`GAP` apart. A part that does not fit is cut short with an ellipsis
    and the line ends there. A plain string is drawn whole in ``muted`` (a
    state such as a type-ahead buffer). ``base`` is the bar's colour, where
    ``muted`` carries none. The click targets drawn come back, for
    :func:`click_hint`."""
    if isinstance(hints, str):
        ctx.draw_text(x, y, elide(hints, max(0.0, avail), where="end",
                                  measure=lambda t: ctx.measure_text(t, muted)), muted)
        return []
    kstyle = key_style(ctx, muted, base)
    end = x + max(0.0, avail)
    hits: list[HintHit] = []
    first = True
    for hint in hints:
        if not hint.text:
            continue
        if not first:
            x += GAP
        first = False
        if x >= end:
            break
        runs = _runs(hint, kstyle, muted)
        widths = [ctx.measure_text(t, s) for t, s in runs]
        if x + sum(widths) > end:
            _draw_cut(ctx, x, y, runs, widths, end)
            break
        at = x
        for (text, style), w in zip(runs, widths):
            ctx.draw_text(at, y, text, style)
            at += w
        hits.extend(_targets(ctx, hint, runs, widths, x, y, base or muted.bg))
        x = at
    return hits


def _runs(hint: Hint, kstyle: Style, muted: Style) -> list[tuple[str, Style]]:
    """The part as ``(text, style)`` runs: each key, the joiners, the words."""
    runs: list[tuple[str, Style]] = []
    for i, k in enumerate(hint.keys):
        if i and hint.joiner:
            runs.append((hint.joiner, muted))
        runs.append((k.text, kstyle))
    if hint.label:
        runs.append(((" " if hint.keys else "") + hint.label, muted))
    return runs


def _draw_cut(ctx, x, y, runs, widths, end) -> None:
    """The last part, cut at ``end`` with an ellipsis."""
    for (text, style), w in zip(runs, widths):
        if x + w + ctx.measure_text("…", style) <= end:
            ctx.draw_text(x, y, text, style)
            x += w
            continue
        room = max(0.0, end - x)
        cut = elide(text, room, where="end",
                    measure=lambda t, s=style: ctx.measure_text(t, s))
        if not cut.strip(" …"):
            # Nothing of it fits but the mark that it goes on.
            cut = "…" if ctx.measure_text("…", style) <= room else ""
        if cut:
            ctx.draw_text(x, y, cut, style)
        return


def _targets(ctx, hint: Hint, runs, widths, x, y, base) -> list[HintHit]:
    """The part's click targets, each lit under the pointer."""
    if not hint.keys:
        return []
    if len(hint.keys) == 1:
        target = _target(hint.keys[0])
        if target is None:
            return []
        hover_part(ctx, x, runs, y=y, base=base)
        return [HintHit(x, x + sum(widths), y, y + 1.0, target)]
    # Several keys: each its own target. The runs alternate key, joiner, key
    # (a cluster has no joiners), then the words.
    hits = []
    at, index = x, 0
    step = 2 if hint.joiner else 1
    for i, ((text, style), w) in enumerate(zip(runs, widths)):
        if i % step == 0 and index < len(hint.keys):
            target = _target(hint.keys[index])
            index += 1
            if target is not None:
                hits.append(HintHit(at, at + w, y, y + 1.0, target))
                hover_part(ctx, at, [(text, style)], y=y, base=base)
        at += w
    return hits


def _target(k: Key):
    """What a click on ``k`` runs: its callable, or the key event it presses
    (None: not a target)."""
    if k.run is not None:
        return None if k.run is _nothing else k.run
    return key_event_for(k.press or k.text)


# --- clicking ---------------------------------------------------------------------


def hint_target(hits: Iterable[HintHit], event) -> Any:
    """What a pointer ``event`` on a hint row means: the target (a callable
    or a key event) for a left click on one, True for any other button event
    on one (it is the hint's, not the content's under it), None otherwise."""
    if not hits or event.x is None or event.y is None:
        return None
    if event.type not in (EventType.MOUSE_DOWN, EventType.MOUSE_UP,
                          EventType.MOUSE_CLICK, EventType.MOUSE_DRAG):
        return None
    for hit in hits:
        if hit.x0 <= event.x < hit.x1 and hit.y0 <= event.y < hit.y1:
            if event.type is EventType.MOUSE_CLICK and event.button in (None, "left"):
                return hit.target
            return True
    return None


def run_target(target, press: Callable[[Event], Any]) -> None:
    """Run what a click on a target means: call it, or ``press`` its key."""
    if isinstance(target, Event):
        press(target)
    elif callable(target):
        target()


def click_hint(widget, hits, event) -> bool:
    """Handle ``event`` if it is on one of ``hits``: a left click runs the
    target - a key is handed to ``widget.handle_event`` as though it were
    pressed. Whether the event was the hint's."""
    target = hint_target(hits, event)
    if target is None:
        return False
    if target is not True:
        run_target(target, widget.handle_event)
        panel = getattr(widget, "_panel", None)
        if panel is not None and hasattr(panel, "render"):
            panel.render()
    return True
