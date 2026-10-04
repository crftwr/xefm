"""The favorites list behind the Go to Favorite picker (J).

Two sources, merged into one list — the same shape as :mod:`xefm.server_list`:

1. ``FAVORITE_DIRECTORIES`` in ``~/.xefm/config.py`` — hand-written, and
   therefore not removable from the UI. XeFM never rewrites a user-authored
   Python file, so the config stays the source of truth for those rows.
2. Favorites added with ``add_favorite`` (B) — kept in the state DB, removable
   with the picker's remove key, and listed after the config rows in the order
   they were added.

A favorite added from the UI may name a **file** as well as a directory.
Selecting one goes to the file's directory and lands the cursor on it, as Jump
to Path does with a typed file path (#351). Whether a row is a file is recorded
when it is added — from the listing the pane already holds — so the picker never
has to ask the filesystem (#430).

Deduplication is by normalized path with config winning, so a user who copies a
favorite they added here into their config ends up with one row, not two.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from xefm import path_schemes
from xefm.config import get_favorite_directories
from xefm.log_manager import getLogger
from xefm.state_manager import get_state_manager

logger = getLogger("Favorites")

#: State DB key holding the favorites added from the UI (a list of dicts).
_STATE_KEY = "favorites"

#: How many added favorites to keep. Generous — each is added by hand, so the
#: list is short in practice and the cap only exists so a runaway cannot grow
#: the state DB without bound.
_MAX_SAVED = 200

CONFIG = "config"
STATE = "state"

#: What :func:`add_favorite` did.
ADDED = "added"
RENAMED = "renamed"
IN_CONFIG = "in_config"
FAILED = "failed"


@dataclass(frozen=True)
class FavoriteEntry:
    """One row of the favorites picker."""

    name: str
    path: str
    is_file: bool = False
    origin: str = STATE

    @property
    def removable(self) -> bool:
        """Whether the picker's remove key may forget this row. A config entry
        cannot be: deleting it here would be undone by the next config load, so
        offering it would be a lie."""
        return self.origin == STATE


def _key(path: str) -> str:
    """The identity of a favorite, for deduplication. String work only: a
    trailing separator does not make a second favorite, and on Windows neither
    does case. Nothing is resolved — a symlinked favorite stays the path the
    user chose, as everywhere else in XeFM."""
    path = path.strip()
    if path_schemes.is_uri(path):
        stripped = path.rstrip("/")
        return path if stripped.endswith(":") else stripped
    return os.path.normcase(os.path.normpath(path))


def _from_config() -> list[FavoriteEntry]:
    return [FavoriteEntry(name=row["name"], path=row["path"], origin=CONFIG)
            for row in get_favorite_directories()]


def _from_state() -> list[FavoriteEntry]:
    try:
        rows = get_state_manager().get_state(_STATE_KEY, []) or []
    except Exception as e:
        logger.error(f"Could not read saved favorites: {e}")
        return []
    entries = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("path"):
            continue
        path = str(row["path"])
        entries.append(FavoriteEntry(name=str(row.get("name") or path), path=path,
                                     is_file=bool(row.get("is_file")),
                                     origin=STATE))
    return entries


def _write_state(entries: list[FavoriteEntry]) -> bool:
    rows = [{"name": e.name, "path": e.path, "is_file": e.is_file}
            for e in entries[:_MAX_SAVED]]
    try:
        return bool(get_state_manager().set_state(_STATE_KEY, rows))
    except Exception as e:
        logger.error(f"Could not save the favorites list: {e}")
        return False


def get_favorites() -> list[FavoriteEntry]:
    """The merged list, config rows first. Touches nothing beyond the state DB
    — this runs while the picker is opening."""
    merged: list[FavoriteEntry] = []
    seen: set[str] = set()
    for entry in _from_config() + _from_state():
        key = _key(entry.path)
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    return merged


def find_favorite(path: str) -> FavoriteEntry | None:
    """The row ``path`` already has in the merged list, or ``None``."""
    key = _key(path)
    return next((e for e in get_favorites() if _key(e.path) == key), None)


def add_favorite(name: str, path: str, *, is_file: bool = False) -> str:
    """Remember ``path`` under ``name``.

    Adding a path that is already a saved favorite renames it where it stands
    rather than adding a second row (returns :data:`RENAMED`); adding one the
    config already lists is a no-op (:data:`IN_CONFIG`) — the config row would
    win anyway, and a shadow copy in the state DB would turn into a stale
    duplicate the day the config changes. A new favorite goes to the end, so
    the list keeps the order the user built it in.
    """
    key = _key(path)
    if any(_key(e.path) == key for e in _from_config()):
        return IN_CONFIG
    saved = _from_state()
    entry = FavoriteEntry(name=name or path, path=path, is_file=is_file)
    for i, old in enumerate(saved):
        if _key(old.path) == key:
            saved[i] = entry
            return RENAMED if _write_state(saved) else FAILED
    return ADDED if _write_state(saved + [entry]) else FAILED


def remove_favorite(entry: FavoriteEntry) -> bool:
    """Forget a saved favorite. Returns False for a config row, which is also
    what the picker needs from its remove hook to leave that row alone."""
    if not entry.removable:
        return False
    key = _key(entry.path)
    return _write_state([e for e in _from_state() if _key(e.path) != key])
