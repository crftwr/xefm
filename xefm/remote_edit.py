"""Edit anywhere — remote files opened in the editor and written back (#581).

An editor can only open a file on this filesystem, so editing ``ssh://host/a.py``
means editing a local copy of it and sending that copy back: the WinSCP model.
An :class:`EditSession` is one such file — where it came from, where its copy
lives, and what the two last agreed on. :class:`EditSessions` holds them all for
the app, which drives the polling and the uploads (``XeFMApp._edit_remote``).

Three things the design turns on:

- **Saves are found by polling the copy**, not by waiting for the editor. A
  terminal editor blocks until it is done, but a GUI one returns at once and
  saves whenever the user likes, so the copy is checked for as long as the
  session lives — a cheap stat each time, and a hash only when the stat moved.
  An editor that saves by writing a new file and renaming it over the old one
  is seen the same way, since the path is what is checked.
- **The remote file is checked before every upload.** The session remembers
  the remote's mtime and size as of the download (and of each upload since);
  anything different means someone else wrote it, and the app asks before
  overwriting that. The backend's metadata cache is bypassed for that one stat
  (:func:`xefm.path.forget_cached_metadata`), or a change made within the cache's
  lifetime would go unseen.
- **The copy outlives every failure.** An upload that fails or is declined
  leaves the session *pending*, and a pending copy is never deleted — not on
  the next open, and not when XeFM exits — because it may be the only place the
  user's edit exists.

Copies live under ``~/.xefm/edit/`` in a tree that mirrors the remote path
(``edit/ssh/host/srv/app/a.py``), so the editor's title bar names the file the
user meant to open rather than a random temp name.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path as LocalPath
from typing import Any, Optional

from xefm.log_manager import getLogger
from xefm.path import forget_cached_metadata

logger = getLogger("RemoteEdit")

#: Characters no path component may hold on any of the three platforms.
_UNSAFE = re.compile(r'[<>:"|?*\\\x00-\x1f]')


def can_write_back(remote: Any) -> bool:
    """Whether ``remote`` is somewhere an edited copy can be sent back to — a
    backend that declares ``write_operations``. Archives and read-only backends
    do not, so editing there is refused rather than offered without a way home."""
    supports = getattr(remote, "supports", None)
    return bool(supports and supports("write_operations"))


def local_copy_path(root: LocalPath, remote: Any) -> LocalPath:
    """Where ``remote``'s editable copy lives under ``root``: the URI's scheme,
    then its authority and path, one directory per component. A component that
    is empty, ``.``/``..`` or holds a character some platform refuses is made
    safe, so a hostile name can neither escape ``root`` nor fail to be created."""
    text = str(remote)
    scheme, sep, rest = text.partition("://")
    if not sep:
        scheme, rest = "file", text
    parts = [scheme] + [p for p in rest.split("/") if p]
    safe = []
    for part in parts:
        part = _UNSAFE.sub("_", part)
        if part in ("", ".", ".."):
            part = part.replace(".", "_") or "_"
        safe.append(part)
    return root.joinpath(*safe)


def _remote_state(remote: Any) -> Optional[tuple[float, int]]:
    """The remote file's (mtime, size) straight from the storage, or None when
    it is gone. Other failures propagate: an unreachable host is not "gone"."""
    forget_cached_metadata(remote)
    try:
        st = remote.stat()
    except FileNotFoundError:
        return None
    return (float(getattr(st, "st_mtime", 0) or 0), int(getattr(st, "st_size", 0) or 0))


def _digest(path: LocalPath) -> bytes:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.digest()


def _local_stat(path: LocalPath) -> Optional[tuple[int, int]]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class RemoteChanged(Exception):
    """The remote file moved since the session last agreed with it."""


class EditSession:
    """One remote file being edited through a local copy."""

    def __init__(self, remote: Any, local: LocalPath):
        self.remote = remote
        self.local = local
        #: The remote's (mtime, size) when the copy last matched it.
        self.remote_state: Optional[tuple[float, int]] = None
        #: Hash of the content the remote is known to hold.
        self.sent_digest: bytes = b""
        #: The copy's stat when it was last looked at, the cheap save detector.
        self.seen_stat: Optional[tuple[int, int]] = None
        #: The last upload's failure, phrased for the user; None once one lands.
        self.error: Optional[str] = None

    @property
    def pending(self) -> bool:
        """Whether the copy holds an edit the remote has not received."""
        try:
            return _digest(self.local) != self.sent_digest
        except OSError:
            return False

    def __repr__(self) -> str:
        return f"EditSession({self.remote!s} -> {self.local})"


class EditSessions:
    """Every live :class:`EditSession`, keyed by remote path."""

    def __init__(self, root: LocalPath):
        self.root = LocalPath(root)
        self._sessions: dict[str, EditSession] = {}

    def __len__(self) -> int:
        return len(self._sessions)

    def __iter__(self):
        return iter(list(self._sessions.values()))

    def get(self, remote: Any) -> Optional[EditSession]:
        return self._sessions.get(str(remote))

    # --- worker-side: these talk to the remote ---------------------------------

    def open(self, remote: Any) -> EditSession:
        """Download ``remote`` to its copy and start (or refresh) its session.

        A session already holding an unsent edit is reused as it stands: fetching
        the remote again would overwrite the only copy of that edit. Otherwise
        the copy is fetched fresh, so reopening a file shows what the server
        holds now."""
        session = self._sessions.get(str(remote))
        if session is not None and session.pending:
            return session
        local = local_copy_path(self.root, remote)
        local.parent.mkdir(parents=True, exist_ok=True)
        state = _remote_state(remote)
        if state is None:
            raise FileNotFoundError(f"{remote} no longer exists")
        data = remote.read_bytes()
        tmp = local.with_name(local.name + ".xefm-download")
        tmp.write_bytes(data)
        os.replace(tmp, local)
        session = session or EditSession(remote, local)
        session.remote_state = state
        session.sent_digest = hashlib.sha256(data).digest()
        session.seen_stat = _local_stat(local)
        session.error = None
        self._sessions[str(remote)] = session
        logger.info(f"Opened {remote} for editing as {local}")
        return session

    def upload(self, session: EditSession, *, force: bool = False) -> None:
        """Send the copy back. Raises :class:`RemoteChanged` — before writing
        anything — when the remote moved since the session last matched it and
        ``force`` is not set; other failures propagate as they come."""
        if not force:
            current = _remote_state(session.remote)
            if current != session.remote_state:
                raise RemoteChanged(str(session.remote))
        data = session.local.read_bytes()
        session.remote.write_bytes(data)
        session.sent_digest = hashlib.sha256(data).digest()
        session.remote_state = _remote_state(session.remote)
        session.error = None
        logger.info(f"Uploaded {session.local} to {session.remote}")

    # --- UI-thread side: local stats only --------------------------------------

    def saved(self) -> list[EditSession]:
        """The sessions whose copy was saved since the last call with content
        the remote has not got. Cheap when nothing moved: one stat per copy."""
        out = []
        # A copy: open() adds sessions from a worker thread meanwhile.
        for session in list(self._sessions.values()):
            stat = _local_stat(session.local)
            if stat is None or stat == session.seen_stat:
                continue
            session.seen_stat = stat
            if session.pending:
                out.append(session)
        return out

    def close_all(self) -> list[EditSession]:
        """End every session: remove the copies the remote already matches and
        keep the rest, which are returned so the caller can name them."""
        kept = []
        for session in list(self._sessions.values()):   # a copy, as in saved()
            if session.pending:
                kept.append(session)
                continue
            try:
                session.local.unlink()
            except OSError:
                pass
            self._prune(session.local.parent)
        self._sessions.clear()
        return kept

    def _prune(self, directory: LocalPath) -> None:
        """Remove now-empty directories from ``directory`` up to the root."""
        root = self.root.resolve()
        while True:
            try:
                resolved = directory.resolve()
            except OSError:
                return
            if resolved == root or root not in resolved.parents:
                return
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

