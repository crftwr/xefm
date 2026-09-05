#!/usr/bin/env python3
"""The filters the ';' picker offers — a typed glob, and any a config defines.

The pane filter has always been one ``fnmatch`` pattern typed into the Filter
prompt, which answers "show me the ``.py`` files" and nothing else: "show me
what changed today", "show me anything over 100 MB", "show me the images" are
all questions about an entry rather than about its name, and a glob cannot ask
them. Rather than grow a pattern language for each, this exposes the predicate,
exactly as :mod:`xefm.sort_keys` exposes the sort's key.

A config supplies ``FILTERS``:

```python
FILTERS = {
    "images": ["*.jpg", "*.png", "*.gif"],            # globs, OR'ed
    "today": {"label": "Modified today",
              "match": lambda e: e.mtime >= start_of_today()},
    "big": {"label": "Over 100 MB", "match": lambda e: e.size > 100 << 20},
}
```

Each becomes a fixed row in the Filter picker, straight under "clear filter" and
above the patterns typed here before — the picker's own history stays a history,
and a defined filter is always in the same place rather than scrolling away as
it ages. A bare callable is shorthand for ``{"match": ...}``; a bare string or
list of strings is shorthand for ``{"pattern": ...}``, which is the glob case
written in one line.

**The contract.**

* ``match`` takes one :class:`~xefm.user_api.EntryInfo` and returns whether the
  entry is shown — the same object a sort key is handed, with the same
  guarantees: ``name`` is the name the pane *shows* (composed, and the whole
  path below the search root on a search-results pane), ``path`` is the verbatim
  one for anything that has to reach the filesystem, and ``size`` and ``mtime``
  are free, seeded from the listing's own attribute record.
* **Directories are not the predicate's business.** They are always shown, as
  they are under a typed glob: a filter that hid them would strand navigation —
  the subdirectory you were about to enter is gone. So a predicate only ever
  decides which *files* are visible, and "directories only" is spelled
  ``lambda e: False``.
* **It may run on a worker thread**, and does for the first listing of a
  directory, so it must not touch the UI. Same rule, and same reason, as a sort
  key: this is per-entry work over a whole directory.
* A predicate that raises loses the *filter*, not the listing: the pane shows
  every entry and says so once in the log, rather than hiding files by accident
  or emitting a traceback per file. Failing open is the deliberate direction —
  a filter that silently hides half a directory is how a file gets deleted by a
  selection its user could not see.

A registered filter is remembered by name where a typed one is remembered by
pattern: :func:`matcher` reads the registry first and falls back to ``fnmatch``,
which is what makes ``pane['filter_pattern']`` a single string throughout — the
status bar, the saved pane state and the search narrowing all keep working
unchanged. Names may not contain ``*``, ``?`` or ``[`` for exactly that reason:
nothing must be readable both as a name and as a pattern someone typed.
"""

from __future__ import annotations

import fnmatch
from typing import Any, Callable, Mapping, NamedTuple

from xefm import name_key

#: Characters a filter name may not contain — the ``fnmatch`` metacharacters.
#: A name is stored where a typed pattern is stored, so one that could also be
#: read as a glob would make "did the user mean their filter or their pattern?"
#: an unanswerable question.
GLOB_CHARS = "*?["


class Row(NamedTuple):
    """One registered filter as the picker lists it: the name it is stored and
    resolved under, and the text the row draws."""
    name: str
    label: str


#: ``name -> {"label", "match", "globs"}``, in registration order. Rebuilt
#: wholesale on a config reload, exactly as ``SORT_KEYS`` is.
_user: dict[str, dict[str, Any]] = {}


def clear() -> None:
    """Drop every registration. A config reload rebuilds from scratch, so a
    filter removed from the config stops being offered."""
    _user.clear()


def register(name: str, *, match: Callable | None = None,
             globs: tuple[str, ...] | None = None,
             label: str | None = None) -> None:
    """Add or replace one filter. Later registration wins, as in
    :mod:`xefm.sort_keys`.

    Exactly one of ``match`` (a predicate over an entry) and ``globs`` (patterns
    matched against the shown name, any one of which is enough) carries the
    filter; ``label`` is the row text, defaulting to the name."""
    _user[name] = {"label": label, "match": match, "globs": globs}


def get(name: str) -> dict[str, Any] | None:
    """The registered entry for ``name``, or ``None`` when nothing is registered
    under it — in which case the string is a pattern, not a name."""
    return _user.get(name)


def is_known(name: str) -> bool:
    """Whether ``name`` still names a filter a config defines.

    A pane's filter is remembered across sessions (``state_manager``) and its
    history outlives any one config, so a name here may be one that was defined
    when it was written and is not now. It then resolves as the glob it looks
    like — matching nothing, under a name the status bar still shows — which is
    recoverable in one keypress; this is how a caller checks instead."""
    return name in _user


def rows() -> list[Row]:
    """Every registered filter, in the order the config defined them — which is
    the order the picker pins them under its "clear filter" row."""
    return [Row(name, entry["label"] or name) for name, entry in _user.items()]


def label(pattern: str) -> str:
    """What to *call* ``pattern`` on screen: a registered filter's label, or the
    pattern itself, which is already its own name."""
    entry = _user.get(pattern)
    return (entry["label"] or pattern) if entry else pattern


def matcher(pattern: str) -> Callable[[Any, Mapping[str, Any]], bool]:
    """The ``(path, attrs) -> bool`` test ``pattern`` stands for.

    ``attrs`` is the listing's own record for that path (see
    :mod:`xefm.dir_scan`); ``cmp_name`` is used when the assembling listing has
    already filled it in and composed from the path when it has not, so a caller
    walking a tree — the content search's narrowing — can pass the raw records it
    reads.

    A name nothing is registered under is a pattern: this is the single point
    where "which of the two is it?" is decided, so every caller applies a filter
    the same way whichever it holds.
    """
    entry = _user.get(pattern)
    if entry is None:
        return _glob_matcher((pattern,))
    if entry["globs"] is not None:
        return _glob_matcher(entry["globs"])
    match = entry["match"]
    # Imported here: user_api imports the config-facing modules, not the other
    # way round, and this is the only line of this module that needs it.
    from xefm.user_api import EntryInfo

    def run(path, attrs) -> bool:
        return bool(match(EntryInfo.from_attrs(path, attrs)))

    return run


def _glob_matcher(globs) -> Callable[[Any, Mapping[str, Any]], bool]:
    """Match the shown name against any one of ``globs``, case-insensitively and
    composed — the built-in filter, and what a ``pattern`` entry compiles to."""
    patterns = [name_key.nfc(g).lower() for g in globs]

    def run(path, attrs) -> bool:
        name = (attrs.get("cmp_name") or name_key.compare_name(path)).lower()
        return any(fnmatch.fnmatch(name, p) for p in patterns)

    return run
