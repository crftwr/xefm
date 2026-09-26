"""Surface options — one declaration, read by four things.

An option here is a small live setting that belongs to *the surface in front of
you* rather than to the app: whether this search reads case, whether it descends
into subfolders. They are deliberately not config-file settings — the moment you
want to change one is the moment you are looking at the results it changes.

**Why they share one key.** A dialog with a query field has no keys to spare:
every printable key belongs to the query (the rule ``xefm.actions`` already
states for ``isearch`` and ``filter_list``), and what is left is countable —
Ctrl, minus what the text field owns (A/C/X/V), minus what a terminal renames
(Ctrl+I/M/J/H/[). Spending three of those on one
dialog's options leaves nothing for the next dialog that wants some. So options
are not reached by a key each: they are reached by *one* key — ``options``,
Ctrl-O — which opens :mod:`xefm.options_dialog`, a surface with no text field,
where every plain letter is free. One key, spent once, for as many options as
any surface ever grows.

**Every option is on or off.** Not a simplification of a richer thing that was
tried and cut down: two states is what makes the whole idiom legible. A chip can
say "on" by being filled, a row can say it in a word, and a key can *toggle*
rather than cycle through states a user has to press repeatedly to find. Where a
setting has three answers, the surface owns three declared options or a picker of
its own — it does not go here.

**What one declaration feeds.** A surface declares its options once and four
readers use that same list, so they cannot drift apart:

1. the always-visible chip strip (:meth:`OptionSet.chips`), which is how an
   option is seen before anyone needs it;
2. the options dialog's rows and their letters;
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
    """One declared on/off option.

    ``flag`` names the chip in the strip; ``label`` names the row in the options
    dialog, and **its initial is the key that toggles it** — the Sort dialog's
    convention, where the hotkey is not drawn because the word already carries
    it. ``accel`` overrides that initial for the case where two labels on one
    surface start with the same letter.

    ``modes`` gates the option to the surface modes it applies to — the search
    dialog's ``"filename"`` / ``"content"`` — and empty means "always". A gated
    option is not dimmed but *absent*: an option that cannot do anything must
    not look like one that is merely off.

    ``persist`` is whether the value outlives one opening of the surface.
    Options that change how a query is read persist for the session; options
    that change *what is walked* do not, because a scope narrowed for one search
    must not silently narrow the next one.
    """

    name: str
    label: str
    flag: str
    default: bool = False
    modes: tuple[str, ...] = ()
    accel: str = ""
    persist: bool = True

    @property
    def key(self) -> str:
        """The letter that toggles this option in the options box."""
        return (self.accel or self.label[:1]).lower()

    def applies(self, mode: str | None) -> bool:
        """Whether this option means anything in ``mode`` (always, if it named
        no modes, or if the surface has none)."""
        return not self.modes or mode is None or mode in self.modes


def state_label(value: bool) -> str:
    """How a value reads in the options dialog's right-hand column."""
    return "on" if value else "off"


class OptionSet:
    """The live values for one surface's declared options.

    Mutating one fires ``on_change(name, value)``, which is how a surface re-runs
    what the option changed. The owner assigns that callback rather than passing
    it in, because the surface that *shows* the options (the dialog) is usually
    not the one that *declared* them (the app).
    """

    def __init__(self, options: Iterable[Option],
                 values: dict[str, bool] | None = None,
                 on_change: Callable[[str, bool], None] | None = None):
        self.options: tuple[Option, ...] = tuple(options)
        self._by_name = {o.name: o for o in self.options}
        self.values: dict[str, bool] = {o.name: o.default for o in self.options}
        if values:
            for name, value in values.items():
                if name in self._by_name:
                    self.values[name] = bool(value)
        self.on_change = on_change

    # --- reading -------------------------------------------------------------

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __getitem__(self, name: str) -> bool:
        return self.values[name]

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def option(self, name: str) -> Option | None:
        return self._by_name.get(name)

    def visible(self, mode: str | None = None) -> list[Option]:
        """The options that apply in ``mode``, in declaration order."""
        return [o for o in self.options if o.applies(mode)]

    def chips(self, mode: str | None = None) -> list[tuple[Option, bool]]:
        """``(option, on)`` for the strip — one entry per applicable option, in
        declaration order, so the strip never reorders itself under the eye.

        The whole option rather than just its ``flag``: a chip is a control, not
        a readout — the surface drawing it needs the name to hand back when one
        is clicked."""
        return [(o, self.values[o.name]) for o in self.visible(mode)]

    def snapshot(self) -> dict[str, bool]:
        return dict(self.values)

    # --- writing -------------------------------------------------------------

    def set(self, name: str, value: bool) -> bool:
        """Set one value. Returns whether it actually changed — the caller's cue
        to re-run, and what keeps a no-op keystroke from restarting a search."""
        option = self._by_name.get(name)
        value = bool(value)
        if option is None or self.values[name] == value:
            return False
        self.values[name] = value
        if self.on_change is not None:
            self.on_change(name, value)
        return True

    def toggle(self, name: str) -> bool:
        """Flip one option and return its new value (``False`` for a name this
        set does not know, which is also what an unknown option is worth)."""
        if name not in self._by_name:
            return False
        self.set(name, not self.values[name])
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
    duplicated initial degrades to "the second one has no letter" rather than
    stealing the first one's — which is what ``Option.accel`` is for."""
    table: dict[str, Option] = {}
    for option in options:
        key = option.key
        if key and key not in table:
            table[key] = option
    return table
