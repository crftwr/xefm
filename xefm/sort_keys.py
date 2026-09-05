#!/usr/bin/env python3
"""The sort keys a pane can order by — the four built in, and any a config adds.

XeFM sorts by codepoint, which is not how either shell orders a directory:
Explorer puts symbols before digits and orders kanji by the platform's collation,
Finder differs again (#380). Rather than build one of those in — the native
routes are comparators, `CompareStringW` and `localizedStandardCompare:`, and a
comparator costs O(N log N) calls where a key costs O(N) — this exposes the
choice, so a config can write the order it wants and pay for exactly what it asks
for.

A config supplies ``SORT_KEYS``:

```python
def explorer(entry):
    # digit runs numerically, text runs through the platform's collation
    parts = re.split(r'(\\d+)', entry.name)
    return [int(p) if i % 2 else locale.strxfrm(p) for i, p in enumerate(parts)]

SORT_KEYS = {
    "explorer": {"label": "Explorer order", "key": explorer},
    "name": {"key": explorer, "override": True},   # replace the built-in
}
```

A bare callable is shorthand for ``{"key": ...}``. Naming a built-in mode
replaces it, which needs ``"override": True`` for the same reason ``ACTIONS``
does — otherwise a typo silently changes what Filename means.

**The contract.**

* The key takes one :class:`~xefm.user_api.EntryInfo` and returns anything
  sortable. Tuples and lists are fine and are the usual answer — they compare
  element by element, which is how a "text, number, text" natural order is built.
  Every key in one sort must be mutually comparable: an ``int`` meeting a ``str``
  at the same position raises, which is why the built-in natural key splits on
  a capture group, keeping text at even positions.
* **Directories first and reverse are not the key's business.** The pane splits
  directories from files and sorts each group, then reverses if asked; a key only
  has to order entries within one group.
* ``entry.size`` and ``entry.mtime`` are free here — the listing's own attribute
  record is seeded into the entry, so reading them costs no ``stat`` even over a
  network mount (see :meth:`~xefm.user_api.EntryInfo.from_attrs`).
* **It may run on a worker thread**, and does for the first listing of a
  directory. It must not touch the UI or anything else the UI thread owns. This
  is the opposite of the promise ``ACTIONS`` and ``EVENT_HOOKS`` make, and
  deliberately: sorting is the slow, per-entry work, so it is the one thing that
  cannot be pinned to the UI thread.
* A key that raises, or returns values that will not compare, loses the whole
  sort — not one entry. The pane falls back to the built-in name order and says
  so once in the log, rather than emitting a traceback per file.
"""

from __future__ import annotations

from typing import Any, Callable

#: The built-in keys in row order: (``sort_mode`` value, label, hotkey).
#: ``"type"`` is a legacy alias for ``"ext"`` and is deliberately not listed.
BUILTIN: tuple[tuple[str, str, str], ...] = (
    ("name", "Filename", "F"),
    ("ext", "Extension", "E"),
    ("size", "Size", "S"),
    ("date", "Timestamp", "T"),
)

BUILTIN_NAMES = frozenset(m for m, _l, _h in BUILTIN) | {"type"}

#: The explanation line per (mode, reverse) the sort dialog draws: three values
#: in the order the list would show them, plus the plain-words reading.
BUILTIN_EXPLANATIONS: dict[tuple[str, bool], str] = {
    ("name", False): "a.txt → m.txt → z.txt  (A to Z)",
    ("name", True): "z.txt → m.txt → a.txt  (Z to A)",
    ("ext", False): ".c → .md → .py  (A to Z)",
    ("ext", True): ".py → .md → .c  (Z to A)",
    ("size", False): "1 KB → 1 MB → 1 GB  (smallest first)",
    ("size", True): "1 GB → 1 MB → 1 KB  (largest first)",
    ("date", False): "2024 → 2025 → 2026  (oldest first)",
    ("date", True): "2026 → 2025 → 2024  (newest first)",
}

_DEFAULT_EXPLANATION = "a key from your config"

#: ``mode -> {"label", "key", "explain", "hotkey"}``, in registration order.
#: Rebuilt wholesale on a config reload, exactly as ``EVENT_HOOKS`` is.
_user: dict[str, dict[str, Any]] = {}


def clear() -> None:
    """Drop every registration. A config reload rebuilds from scratch, so a key
    removed from the config stops being offered."""
    _user.clear()


def register(name: str, key: Callable, *, label: str | None = None,
             explain: str | None = None, hotkey: str | None = None) -> None:
    """Add or replace one sort key. Later registration wins, as in
    :mod:`xefm.viewer_registry`."""
    _user[name] = {"label": label or name, "key": key,
                   "explain": explain, "hotkey": hotkey}


def get(name: str) -> dict[str, Any] | None:
    """The registered entry for ``name``, or ``None`` when the built-in applies."""
    return _user.get(name)


def key_for(name: str) -> Callable | None:
    """The user key function for ``name``, or ``None`` to use the built-in."""
    entry = _user.get(name)
    return entry["key"] if entry else None


def is_known(name: str) -> bool:
    """Whether ``name`` still names a sort a pane can use.

    A pane's mode is remembered across sessions (``state_manager``), so a config
    that registered ``"explorer"`` and no longer does leaves a saved mode naming
    nothing. Callers restoring one ask this and fall back rather than sorting by
    a key that is gone."""
    return name in BUILTIN_NAMES or name in _user


def rows() -> list[tuple[str, str, str | None]]:
    """``(mode, label, hotkey)`` for every sort a pane can use, in the order the
    dialog and the menu list them: the built-ins first, in their fixed order and
    keeping their hotkeys, then whatever the config added.

    A config entry naming a built-in *replaces its label in place* rather than
    adding a row, so overriding Filename still reads as Filename unless the
    config renamed it too."""
    out: list[tuple[str, str, str | None]] = []
    taken = {h for _m, _l, h in BUILTIN}
    for mode, label, hotkey in BUILTIN:
        entry = _user.get(mode)
        if entry:
            label = entry["label"] if entry["label"] != mode else label
            hotkey = entry["hotkey"] or hotkey
        out.append((mode, label, hotkey))
    for mode, entry in _user.items():
        if mode in BUILTIN_NAMES:
            continue
        hotkey = entry["hotkey"] or _free_hotkey(entry["label"], taken)
        if hotkey:
            taken.add(hotkey)
        out.append((mode, entry["label"], hotkey))
    return out


def explanation(mode: str, reverse: bool) -> str:
    """The dialog's line under the order segments, for any mode."""
    entry = _user.get(mode)
    if entry is None:
        return BUILTIN_EXPLANATIONS.get(
            (mode, reverse), BUILTIN_EXPLANATIONS[("name", reverse)])
    text = entry["explain"] or _DEFAULT_EXPLANATION
    return f"({text}, reversed)" if reverse else f"({text})"


def label(mode: str) -> str:
    """``mode``'s label for the status bar, falling back to the mode itself."""
    for name, text, _hotkey in rows():
        if name == mode:
            return text
    return "Filename" if mode == "type" else mode


def _free_hotkey(text: str, taken: set) -> str | None:
    """``text``'s initial, when no other row has claimed it — otherwise ``None``.

    Only the initial. The dialog deliberately does not draw the hotkeys, because
    each row's initial *is* its key; picking some later letter would give a row a
    shortcut nothing on screen hints at. A row with none is still reachable with
    the arrow keys, and a config that wants one anyway passes ``"hotkey"``."""
    initial = text[:1].upper()
    return initial if initial.isalpha() and initial not in taken else None
