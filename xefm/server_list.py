"""The saved-server list behind the Connect to Server dialog.

Two sources, merged into one list:

1. ``NETWORK_SERVERS`` in ``~/.xefm/config.py`` — hand-written, and therefore
   not removable from the UI. The config is the source of truth for those, the
   same way it is for Favorites.
2. Servers saved from the connection form — kept in the state DB, and removable
   with the picker's remove key.

Deduplication is by canonical URL with config winning, so a user who promotes a
server they first saved from the dialog into their config ends up with one row,
not two.

**No password is stored here, in either source.** Passwords go to the operating
system's credential store through :mod:`xefm.netmount`; this module only says
which servers exist and which account each one uses.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from xefm import netmount
from xefm.config import get_network_servers
from xefm.log_manager import getLogger
from xefm.state_manager import get_state_manager

logger = getLogger("ServerList")

#: State DB key holding the servers saved from the dialog (a list of dicts).
_STATE_KEY = "network_servers"

#: How many saved servers to keep. Generous — these are typed by hand, so the
#: list is short in practice and the cap only exists so a runaway cannot grow
#: the state DB without bound.
_MAX_SAVED = 100

CONFIG = "config"
STATE = "state"


@dataclass(frozen=True)
class ServerEntry:
    """One row of the Connect to Server list."""

    name: str
    url: str
    user: str = ""
    origin: str = STATE

    @property
    def removable(self) -> bool:
        """Whether the picker's remove key may forget this row. A config entry
        cannot be: deleting it here would be undone by the next config load, so
        offering it would be a lie."""
        return self.origin == STATE

    @property
    def target(self) -> Optional[netmount.MountTarget]:
        """The parsed address, or ``None`` if the entry is unusable (a typo in
        the config). Rows that cannot be parsed are still *shown* — a row the
        user can see and fix beats a row that silently vanished."""
        return netmount.parse_address(self.url)


def _key(url: str) -> str:
    """The identity of a server, for deduplication and for matching a mount back
    to the row it came from. The parsed canonical URL where the address is
    valid, and the raw text lowercased where it is not."""
    target = netmount.parse_address(url)
    return target.url if target is not None else url.strip().rstrip("/").lower()


def _from_config() -> list[ServerEntry]:
    """The ``NETWORK_SERVERS`` rows. ``xefm.config`` hands them over as plain
    dicts — it validates and warns, but it cannot build a :class:`ServerEntry`
    without importing this module, which imports it."""
    return [ServerEntry(name=row["name"], url=row["url"],
                        user=row.get("user", ""), origin=CONFIG)
            for row in get_network_servers()]


def _from_state() -> list[ServerEntry]:
    try:
        rows = get_state_manager().get_state(_STATE_KEY, []) or []
    except Exception as e:
        logger.error(f"Could not read saved servers: {e}")
        return []
    entries = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("url"):
            continue
        url = str(row["url"])
        entries.append(ServerEntry(name=str(row.get("name") or url),
                                   url=url, user=str(row.get("user") or ""),
                                   origin=STATE))
    return entries


def _write_state(entries: list[ServerEntry]) -> bool:
    rows = [{"name": e.name, "url": e.url, "user": e.user}
            for e in entries[:_MAX_SAVED]]
    try:
        return bool(get_state_manager().set_state(_STATE_KEY, rows))
    except Exception as e:
        logger.error(f"Could not save the server list: {e}")
        return False


def get_servers() -> list[ServerEntry]:
    """The merged list, config rows first. Touches no network and no
    filesystem beyond the state DB — this runs while the dialog is opening."""
    merged: list[ServerEntry] = []
    seen: set[str] = set()
    for entry in _from_config() + _from_state():
        key = _key(entry.url)
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    return merged


def save_server(name: str, url: str, user: str = "") -> bool:
    """Remember a server, or update the account on one already remembered.

    Saving is a no-op for an address that is already in the config: the config
    row would win anyway, and writing a shadow copy into the state DB would
    leave a stale duplicate behind the day the config changes.
    """
    key = _key(url)
    if any(_key(e.url) == key for e in _from_config()):
        return False
    kept = [e for e in _from_state() if _key(e.url) != key]
    # Newest first: the list is ordered by when each server was last saved, so
    # the one just connected to is the one at the top next time.
    return _write_state([ServerEntry(name=name or url, url=url, user=user)] + kept)


def forget_server(entry: ServerEntry) -> bool:
    """Forget a saved server and its stored password.

    Returns False for a config row, which is also what the picker needs from
    its remove hook to leave that row alone.
    """
    if not entry.removable:
        return False
    key = _key(entry.url)
    kept = [e for e in _from_state() if _key(e.url) != key]
    if not _write_state(kept):
        return False
    target = entry.target
    if target is not None:
        # The password is the user's, not the row's — but a server they have
        # said to forget should not leave its password behind either.
        netmount.forget_password(target, entry.user)
    return True


def with_user(entry: ServerEntry, user: str) -> ServerEntry:
    """A copy of ``entry`` with a different account, for the form's edits."""
    return replace(entry, user=user)


def mounted_at(entry: ServerEntry, mounts: list[netmount.MountInfo]) -> str:
    """Where ``entry`` is mounted right now, or ``""``.

    Matching is on host and share, with the account and the case ignored,
    because the mount table writes the source its own way — macOS reports an SMB
    mount as ``//me@nas/photo`` and Windows as ``\\\\nas\\photo``.
    """
    target = entry.target
    if target is None:
        return ""
    host = target.host.lower()
    share = target.share.strip("/").lower()
    for info in mounts:
        if info.kind != netmount.NETWORK:
            continue
        source = info.source.replace("\\", "/").lstrip("/").lower()
        if "@" in source:
            source = source.split("@", 1)[1]
        source_host, _, source_share = source.partition("/")
        if source_host == host and source_share.strip("/") == share:
            return info.path
    return ""
