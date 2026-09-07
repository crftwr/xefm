"""Surface options — one declaration, read by four things.

An option here is a small live setting that belongs to *the surface in front of
you* rather than to the app: whether this search reads case, whether it descends
into subfolders. They are deliberately not config-file settings — the moment you
want to change one is the moment you are looking at the results it changes.

**Why they share one key.** A dialog with a query field has no keys to spare:
every printable key belongs to the query (the rule ``xefm.actions`` already
states for ``isearch`` and ``filter_list``), and what is left is countable —
Ctrl, minus what the text field owns (A/C/X/V), minus what a terminal renames
(Ctrl+I/M/J/H/[), minus the hardcoded Ctrl+L. Spending three of those on one
dialog's options leaves nothing for the next dialog that wants some. So options
are not reached by a key each: they are reached by *one* key — ``options``,
Ctrl-O — which opens :mod:`xefm.options_dialog`, a surface with no text field,
where every plain letter is free to be an accelerator. One key, spent once, for
as many options as any surface ever grows.

**What one declaration feeds.** A surface declares its options once and four
readers use that same list, so they cannot drift apart:

1. the always-visible chip strip (:meth:`OptionSet.chips`), which is how an
   option is seen before anyone needs it;
2. the options dialog's rows, labels and accelerators;
3. an unbound ``toggle_<name>`` action per option (``xefm.actions``), so a
   config can still put a direct chord on the one option it changes hourly;
4. the search itself, which reads the values out of :class:`OptionSet`.

:class:`Option` is the declaration and is immutable; :class:`OptionSet` is the
live half that holds the values and tells its owner when one changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence


@dataclass(frozen=True)
class Option:
    """One declared option.

    ``values`` is the cycle order and its **first entry is the default** — the
    state a chip reads as "nothing unusual here". A plain on/off option leaves
    it at ``(False, True)``.

    ``flag`` names the chip in the strip. ``flags``, when given, names it *per
    value* instead, which is how an option whose off-state needs saying ("no
    sub") says it in the one place the user is looking. ``labels`` does the same
    for the options dialog's value column.

    ``modes`` gates the option to the surface modes it applies to — the search
    dialog's ``"filename"`` / ``"content"`` — and empty means "always". A gated
    option is not dimmed but *absent*: an option that cannot do anything must
    not look like one that is merely off.

    ``active`` decides whether the chip is lit. The default rule is "not at its
    default value", which is what an on/off option wants. An option whose real
    state depends on something else — smart case, which reads the query — passes
    its own predicate, taking ``(value, hint)`` where ``hint`` is whatever the
    surface hands :meth:`OptionSet.chips` (the query text, for the search
    dialog). This is what lets the strip show *what the search is actually
    doing* rather than which mode was selected.

    ``persist`` is whether the value outlives one opening of the surface.
    Options that change how a query is read persist for the session; options
    that change *what is walked* do not, because a scope narrowed for one search
    must not silently narrow the next one.
    """

    name: str
    label: str
    accel: str
    flag: str
    values: tuple[Any, ...] = (False, True)
    flags: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    modes: tuple[str, ...] = ()
    active: Callable[[Any, str], bool] | None = None
    persist: bool = True

    @property
    def default(self) -> Any:
        return self.values[0]

    def applies(self, mode: str | None) -> bool:
        """Whether this option means anything in ``mode`` (always, if it named
        no modes, or if the surface has none)."""
        return not self.modes or mode is None or mode in self.modes

    def index_of(self, value: Any) -> int:
        """Where ``value`` sits in the cycle — 0 for anything unrecognized, so a
        stale persisted value degrades to the default instead of raising."""
        try:
            return self.values.index(value)
        except ValueError:
            return 0

    def next_value(self, value: Any, step: int = 1) -> Any:
        return self.values[(self.index_of(value) + step) % len(self.values)]

    def flag_for(self, value: Any) -> str:
        """The chip's text for ``value`` — the per-value name where one was
        declared, the constant one otherwise."""
        if self.flags:
            return self.flags[self.index_of(value)]
        return self.flag

    def label_for(self, value: Any) -> str:
        """The options dialog's value-column text. Booleans get on/off rather
        than Python's True/False, which is not what a reader is looking for."""
        if self.labels:
            return self.labels[self.index_of(value)]
        if isinstance(value, bool):
            return "on" if value else "off"
        return str(value)

    def is_active(self, value: Any, hint: str = "") -> bool:
        """Whether the chip is lit for ``value`` (see ``active``)."""
        if self.active is not None:
            return bool(self.active(value, hint))
        return value != self.default


class OptionSet:
    """The live values for one surface's declared options.

    Mutating one fires ``on_change(name, value)``, which is how a surface re-runs
    what the option changed. The owner assigns that callback rather than passing
    it in, because the surface that *shows* the options (the dialog) is usually
    not the one that *declared* them (the app).
    """

    def __init__(self, options: Iterable[Option],
                 values: dict[str, Any] | None = None,
                 on_change: Callable[[str, Any], None] | None = None):
        self.options: tuple[Option, ...] = tuple(options)
        #: What ``Option.active`` predicates read — the surface's live query, for
        #: the search dialog. Kept on the set rather than passed down every call
        #: so the chip strip and the options dialog cannot disagree about it.
        self.hint: str = ""
        self._by_name = {o.name: o for o in self.options}
        self.values: dict[str, Any] = {o.name: o.default for o in self.options}
        if values:
            for name, value in values.items():
                if name in self._by_name:
                    self.values[name] = value
        self.on_change = on_change

    # --- reading -------------------------------------------------------------

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __getitem__(self, name: str) -> Any:
        return self.values[name]

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def option(self, name: str) -> Option | None:
        return self._by_name.get(name)

    def visible(self, mode: str | None = None) -> list[Option]:
        """The options that apply in ``mode``, in declaration order."""
        return [o for o in self.options if o.applies(mode)]

    def chips(self, mode: str | None = None,
              hint: str | None = None) -> list[tuple[str, bool]]:
        """``(text, lit)`` for the strip — one entry per applicable option, in
        declaration order, so the strip never reorders itself under the eye."""
        text = self.hint if hint is None else hint
        return [(o.flag_for(self.values[o.name]),
                 o.is_active(self.values[o.name], text))
                for o in self.visible(mode)]

    def snapshot(self) -> dict[str, Any]:
        return dict(self.values)

    # --- writing -------------------------------------------------------------

    def set(self, name: str, value: Any) -> bool:
        """Set one value. Returns whether it actually changed — the caller's cue
        to re-run, and what keeps a no-op keystroke from restarting a search."""
        option = self._by_name.get(name)
        if option is None or self.values[name] == value:
            return False
        self.values[name] = value
        if self.on_change is not None:
            self.on_change(name, value)
        return True

    def cycle(self, name: str, step: int = 1) -> Any:
        """Advance one option to its next value (``step=-1`` for the previous)
        and return it."""
        option = self._by_name.get(name)
        if option is None:
            return None
        self.set(name, option.next_value(self.values[name], step))
        return self.values[name]

    def reset_transient(self) -> None:
        """Restore every ``persist=False`` option to its default — what a
        surface calls as it opens, so a scope narrowed for one search does not
        quietly narrow the next."""
        for option in self.options:
            if not option.persist:
                self.values[option.name] = option.default


def accel_map(options: Sequence[Option]) -> dict[str, Option]:
    """``{letter: option}`` for the options dialog. First declaration wins, so a
    duplicated accelerator degrades to "the second one has no letter" rather
    than stealing the first one's."""
    table: dict[str, Option] = {}
    for option in options:
        key = option.accel.lower()
        if key and key not in table:
            table[key] = option
    return table
