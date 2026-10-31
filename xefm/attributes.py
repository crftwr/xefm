"""Per-entry attributes for the file list (#633).

An *attribute* is a named, typed value XeFM can know about one entry: its size,
its tags, its Git status. This module is the attribute layer only — what the
values are and how they are obtained. Where and how they are drawn is
:mod:`xefm.layouts` (#756); the two are kept apart so that showing a value is
the user's choice, never the provider's.

Three kinds, by how a value is had:

- **Built-in, synchronous** — ``name``, ``ext``, ``mtime``: read straight
  off the record the listing already collected. Never cached, never pending.
- **Automatic** (``compute = 'auto'``) — computed in the background for every
  row of a listing as soon as something on screen uses the attribute (a column
  or a marker of the pane's layout). ``tags`` is one, and so is anything
  ``config.ATTRIBUTES`` registers unless it says otherwise. A provider is
  automatic only if a directory's worth of it comes back before anyone would
  call it a wait.
- **On request** (``compute = 'on_request'``) — computed only when the user
  asks, for the entries they asked about (the ``resolve_attribute`` action).
  ``size`` is one, half of it: a file's size is read off its record like a
  synchronous value, a folder's is a recursive walk, on request.

A provider is one function, ``read(directory, entries) -> [value, ...]``:
``entries`` are rows of one folder, ``directory`` is that folder, and the
values come back in the order of ``entries``. How many rows one call gets is
XeFM's choice — a whole folder for an automatic attribute, so a source like
``git status`` answers it in one call; one at a time for an on-request one, so
a slow computation shows its progress and stops when asked.

Values live in an :class:`AttributeStore`, one per pane (tab). Sort and filter
never wait on it: they see what is already there
(doc/dev/FILE_LIST_LAYOUTS_IMPLEMENTATION.md).
"""

from __future__ import annotations

import inspect
import queue
import threading
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from xefm import name_key
from xefm.log_manager import getLogger

logger = getLogger("Attributes")

#: The value types. A type decides the default format, the default alignment,
#: and how values compare when a column is sorted.
TYPES = ("text", "count", "size", "time", "enum", "tags")
#: When a provider's values are computed — see the module docstring.
COMPUTE = ("auto", "on_request")
#: The storage kinds ``where`` may name besides a ``PATH_SCHEMES`` scheme.
#: ``local`` is the local disk (``Path.scheme == 'file'``).
LOCAL = "local"


@dataclass(frozen=True)
class Attribute:
    """One attribute: what it is, and how its values are computed."""
    name: str
    label: str
    type: str = "text"
    #: ``read(directory, entries) -> [value, ...]`` — see the module docstring.
    read: Optional[Callable] = None
    #: For an ``enum``: ``{value: {"label": ..., "color": ...}}``. The label is
    #: the value's meaning; the color is only a default display hint.
    values: dict = field(default_factory=dict)
    #: Storage kinds the provider is asked about: ``local``, ``archive``,
    #: ``ssh``, ``s3`` or a ``PATH_SCHEMES`` scheme.
    where: tuple = (LOCAL,)
    compute: str = "auto"
    #: Built-in synchronous attributes: ``fn(path, record) -> value`` over the
    #: listing's own record. Not for providers.
    sync: Optional[Callable] = None
    #: Built-in: a finer test than ``where`` (``tags`` asks only cheap stores).
    applies: Optional[Callable] = None
    source: str = "builtin"

    @property
    def is_sync(self) -> bool:
        return self.sync is not None

    def applies_to(self, path) -> bool:
        if self.applies is not None:
            try:
                return bool(self.applies(path))
            except Exception:
                return False
        try:
            scheme = path.scheme
        except AttributeError:
            scheme = "file"
        kind = LOCAL if scheme == "file" else scheme
        return kind in self.where


# --- built-ins ------------------------------------------------------------------

def _ext_of(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _sync_name(path, record):
    return record.get("cmp_name") or name_key.compare_name(path)


def _sync_ext(path, record):
    return "" if record.get("is_dir") else _ext_of(_sync_name(path, record))


def _sync_size(path, record):
    if record.get("is_dir") or not record.get("ok", True):
        return None
    return int(record.get("size") or 0)


def _sync_mtime(path, record):
    if not record.get("ok", True):
        return None
    return float(record.get("mtime") or 0.0)


def _tags_apply(path) -> bool:
    from xefm import tags
    store = tags.store_for(path)
    return store is not None and store.cheap


def _tags_read(directory, entries):
    from xefm import tags
    out = []
    for entry in entries:
        try:
            found = tags.read(entry.path)
        except (tags.TagError, OSError):
            found = []
        for tag in found:
            tags.SEEN.setdefault(tag.name.casefold(), tag)
        out.append(found)
    return out


BUILTIN: dict[str, Attribute] = {a.name: a for a in (
    Attribute("name", "Name", "text", sync=_sync_name),
    Attribute("ext", "Extension", "text", sync=_sync_ext),
    # A file's own size, a folder's recursive total once it has been counted.
    # The file half is synchronous; the folder half is the on-request part,
    # computed by the resolve_attribute action (see AttributeStore.request).
    Attribute("size", "Size", "size", compute="on_request",
              where=(LOCAL, "ssh", "s3", "archive")),
    Attribute("mtime", "Modified", "time", sync=_sync_mtime),
    Attribute("tags", "Tags", "tags", read=_tags_read, applies=_tags_apply),
)}

#: Names a sort can already order by without this module: these map to the
#: built-in sort modes rather than to an attribute sort. ``size``'s built-in
#: mode orders files only; its folder totals are an attribute sort.
SORT_MODE_OF = {"name": "filename", "ext": "extension", "size": "size",
                "mtime": "timestamp"}

_user: dict[str, Attribute] = {}


def register(attr: Attribute) -> None:
    _user[attr.name] = attr


def clear() -> None:
    """Drop every registration (a config reload rebuilds from scratch)."""
    _user.clear()


def get(name: str) -> Optional[Attribute]:
    return _user.get(name) or BUILTIN.get(name)


def names() -> list[str]:
    return list(BUILTIN) + [n for n in _user if n not in BUILTIN]


def is_known(name: str) -> bool:
    return get(name) is not None


def sync_value(name: str, path, record):
    """A synchronous attribute's value, or the file half of ``size``."""
    attr = get(name)
    if attr is None:
        return None
    if attr.sync is not None:
        return attr.sync(path, record)
    if name == "size" and not record.get("is_dir"):
        return _sync_size(path, record)
    return None


def has_value(value) -> bool:
    """Whether ``value`` is something to sort by: not None, and not an empty
    list or string — a file with no tags has ``[]``, and it must go where a
    file with no Git status (``None``) goes: last, whichever way the sort
    runs."""
    return value is not None and value != [] and value != "" and value != ()


def sort_key(kind: str, value):
    """How a value of ``kind`` compares in an attribute sort. Tags compare by
    their names; everything else as itself."""
    if kind == "tags":
        return tuple(getattr(t, "name", str(t)).casefold() for t in value or ())
    if isinstance(value, str):
        return value.casefold()
    return value


def build(name: str, spec) -> tuple[Optional[Attribute], Optional[str]]:
    """Validate one ``ATTRIBUTES`` entry: an :class:`Attribute`, or a problem."""
    where = f"ATTRIBUTES['{name}']"
    if not isinstance(name, str) or not name:
        return None, f"{where}: the name must be a non-empty string"
    if name in BUILTIN:
        return None, f"{where} is a built-in attribute and cannot be replaced"
    if not isinstance(spec, dict):
        return None, f"{where} must be a dict with 'read'"
    read = spec.get("read")
    if not callable(read):
        return None, (f"{where} needs 'read', a function read(directory, entries) "
                      f"returning one value per entry")
    problem = _arity_problem(read, 2)
    if problem:
        return None, f"{where}: {problem} — it is called as read(directory, entries)"
    kind = spec.get("type", "text")
    if kind not in TYPES:
        return None, f"{where}: type '{kind}' is not one of {', '.join(TYPES)}"
    compute = spec.get("compute", "auto")
    if compute not in COMPUTE:
        return None, f"{where}: compute '{compute}' is not one of {', '.join(COMPUTE)}"
    values = spec.get("values") or {}
    if not isinstance(values, dict) or not all(
            isinstance(v, dict) for v in values.values()):
        return None, f"{where}: 'values' must map each value to a dict of label and color"
    places = spec.get("where", (LOCAL,))
    if isinstance(places, str):
        places = (places,)
    if not isinstance(places, (list, tuple)) or not all(isinstance(p, str) for p in places):
        return None, f"{where}: 'where' must be a list of storage kinds ('local', 'ssh', …)"
    label = spec.get("label") or name
    return Attribute(name, str(label), kind, read=read,
                     values=dict(values), where=tuple(places), compute=compute,
                     source="user"), None


def _arity_problem(func, n: int) -> Optional[str]:
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return None
    try:
        sig.bind(*range(n))
    except TypeError:
        return f"it cannot be called with {n} argument(s)"
    return None


# --- the store ------------------------------------------------------------------

#: Called (on a worker thread) when new values have landed — the app turns it
#: into a repaint. Set once by the app.
on_ready: Optional[Callable[[], None]] = None

#: Every live store, for :func:`lookup`.
_stores: "weakref.WeakSet[AttributeStore]" = weakref.WeakSet()


def store_of(pane: dict) -> "AttributeStore":
    """``pane``'s store, created the first time it is asked for. One per tab, so
    switching tabs keeps what each one computed."""
    store = pane.get("_attr_store")
    if store is None:
        store = pane["_attr_store"] = AttributeStore()
    return store


def lookup(key: str, name: str):
    """The cached value of ``name`` for the entry at ``key`` in any pane, or
    None. Never computes (``EntryInfo.attr``)."""
    for store in list(_stores):
        found, value = store.value(key, name)
        if found:
            return value
    return None


def _parent(path):
    """The folder a row is in — what ``read`` is handed as ``directory``."""
    return getattr(path, "parent", None)


def _stamp(record) -> tuple:
    return (record.get("size"), record.get("mtime"))


class AttributeStore:
    """The attribute values of one pane, computed off the UI thread.

    :meth:`sync` is called by the pane each time it draws: it is a no-op unless
    the listing or the set of attributes in use changed, and otherwise asks
    ``read`` again for the whole folder — a Git status can change without the
    file it is about changing — leaving the old values on screen until the new
    ones replace them. An on-request value is kept across a re-read while its
    entry's size and mtime are unchanged. Another directory, or :meth:`clear`,
    starts over.
    """

    def __init__(self):
        self._lock = threading.Lock()
        #: ``{str(path): {name: value}}``
        self._values: dict[str, dict[str, Any]] = {}
        #: ``{(name, str(path)): stamp}`` — the record a value was computed from.
        self._stamps: dict[tuple[str, str], tuple] = {}
        self._queue: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._generation = 0
        #: Bumped whenever a value comes or goes, so the pane knows when the
        #: widths it measured from the values are stale.
        self.version = 0
        self._listing = None          # id() of the files list last synced
        self._wanted: frozenset = frozenset()
        self._directory: Optional[str] = None
        self._records: dict = {}
        self._failed: set[str] = set()
        #: Running on-request jobs, cancelled by a new directory or clear().
        self._requests: list[threading.Event] = []
        _stores.add(self)

    # --- reading ---------------------------------------------------------------

    def value(self, key: str, name: str) -> tuple[bool, Any]:
        """``(True, value)`` when known, ``(False, None)`` while it is not."""
        with self._lock:
            row = self._values.get(key)
            if row is not None and name in row:
                return True, row[name]
        return False, None

    def get(self, path, record, name: str):
        """The value to show for one row: synchronous ones straight off the
        record, the rest from the cache (None while pending or absent)."""
        attr = get(name)
        if attr is None:
            return None
        if attr.is_sync:
            return attr.sync(path, record)
        found, value = self.value(str(path), name)
        if found:
            return value
        if name == "size":
            return sync_value(name, path, record)
        return None

    def ready(self, name: str, files: Iterable, records: dict) -> bool:
        """Whether every row ``name`` applies to has its value — what an
        attribute sort needs before it is offered."""
        attr = get(name)
        if attr is None:
            return False
        if attr.is_sync or attr.compute == "on_request":
            return True
        with self._lock:
            for path in files:
                key = str(path)
                if not attr.applies_to(path):
                    continue
                row = self._values.get(key)
                if row is None or name not in row:
                    return False
        return True

    def snapshot(self, name: str, files: Iterable, records: dict) -> dict:
        """``{str(path): value}`` for a sort to read on a worker thread."""
        out = {}
        for path in files:
            key = str(path)
            out[key] = self.get(path, records.get(key, {}), name)
        return out

    # --- scheduling ------------------------------------------------------------

    def sync(self, files: list, records: dict, directory, wanted: Iterable[str]) -> None:
        """Bring the store up to ``files`` (the pane's rows, ``records`` their
        listing records) for the attributes ``wanted``. Cheap when nothing
        changed — the pane calls it on every draw."""
        wanted = frozenset(n for n in wanted
                           if (a := get(n)) is not None and not a.is_sync
                           and a.compute == "auto")
        directory = str(directory) if directory is not None else None
        if id(files) == self._listing and wanted == self._wanted \
                and directory == self._directory:
            return
        with self._lock:
            if directory != self._directory:
                self._cancel_requests()
                self._values.clear()
                self._stamps.clear()
            else:
                self._drop_stale(files, records, wanted)
            self._generation += 1
            self.version += 1
            self._failed.clear()
            self._listing = id(files)
            self._wanted = wanted
            self._directory = directory
            self._records = records
            generation = self._generation
        jobs = []
        for name in sorted(wanted):
            attr = get(name)
            # One call per folder: a search-results pane holds rows of many.
            groups: dict[str, tuple] = {}
            for p in files:
                if attr.applies_to(p):
                    parent = _parent(p)
                    groups.setdefault(str(parent), (parent, []))[1].append(p)
            for parent, members in groups.values():
                jobs.append((generation, name, parent, members))
        for job in jobs:
            self._queue.put(job)
        if jobs:
            self._ensure_worker()

    def _drop_stale(self, files, records, wanted) -> None:
        """Drop the values of rows that left the listing, and the on-request
        values of entries that changed. An automatic value stays on screen
        until the re-run replaces it. Caller holds the lock."""
        present = {str(p) for p in files}
        for key in list(self._values):
            if key not in present:
                del self._values[key]
        for (name, key), stamp in list(self._stamps.items()):
            if key not in present:
                del self._stamps[(name, key)]
                continue
            attr = get(name)
            if attr is not None and attr.compute == "auto":
                continue
            if _stamp(records.get(key, {})) != stamp:
                del self._stamps[(name, key)]
                row = self._values.get(key)
                if row is not None:
                    row.pop(name, None)

    def clear(self) -> None:
        """Forget everything — a manual re-read asks every provider again."""
        with self._lock:
            self._cancel_requests()
            self._values.clear()
            self._stamps.clear()
            self._listing = None
            self._generation += 1
            self.version += 1

    def forget(self, paths: Iterable, name: Optional[str] = None) -> None:
        """Drop the values of ``paths`` (all attributes, or ``name``) — after
        XeFM itself changed them (a tag write). The next draw recomputes."""
        with self._lock:
            for path in paths:
                key = str(path)
                row = self._values.get(key)
                if row is None:
                    continue
                for n in ([name] if name else list(row)):
                    row.pop(n, None)
                    self._stamps.pop((n, key), None)
            self._listing = None
            self.version += 1

    def _put(self, generation: int, name: str, path, value) -> bool:
        key = str(path)
        with self._lock:
            if generation != self._generation:
                return False
            self._values.setdefault(key, {})[name] = value
            self._stamps[(name, key)] = _stamp(self._records.get(key, {}))
            self.version += 1
        return True

    # --- the worker -----------------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._work, name="xefm-attrs",
                                            daemon=True)
            self._thread.start()

    #: Values landed between two repaint requests while more are queued, so a
    #: large folder fills in as it goes without asking for a frame per row.
    _READY_EVERY = 64

    def _work(self) -> None:
        unannounced = 0
        while True:
            try:
                generation, name, parent, paths = self._queue.get(timeout=5)
            except queue.Empty:
                return
            if generation != self._generation:
                continue
            attr = get(name)
            if attr is None:
                continue
            values = self._read(attr, parent, paths)
            landed = 0
            for path, value in zip(paths, values):
                landed += self._put(generation, attr.name, path, value)
            unannounced += landed
            if unannounced and on_ready is not None and (
                    self._queue.empty() or unannounced >= self._READY_EVERY):
                unannounced = 0
                on_ready()

    def _entry_info(self, path):
        from xefm.user_api import EntryInfo   # user_api imports this module
        return EntryInfo._from_attrs(path, self._records.get(str(path), {}))

    def _read(self, attr: Attribute, directory, paths: list) -> list:
        """``attr.read`` over ``paths``, rows of ``directory``: one value per
        path. A provider that raises, or answers with the wrong number of
        values, costs this call's values — logged once."""
        entries = [self._entry_info(p) for p in paths]
        try:
            values = list(attr.read(directory, entries))
            if len(values) != len(entries):
                raise ValueError(f"returned {len(values)} values for {len(entries)} entries")
            return values
        except Exception as exc:  # noqa: BLE001 — a provider's failure costs its values
            self._report(attr, exc)
            return [None] * len(paths)

    def _report(self, attr: Attribute, exc: Exception) -> None:
        if attr.name in self._failed:
            return
        self._failed.add(attr.name)
        logger.error(f"Attribute '{attr.name}' failed: {exc}")

    # --- on request ---------------------------------------------------------------

    def request(self, name: str, paths: list, records: dict,
                on_done: Optional[Callable[[int, bool], None]] = None) -> bool:
        """Compute an on-request attribute for ``paths`` on a thread of its own.
        ``on_done(count, cancelled)`` runs on that thread when it stops.
        Returns False when ``name`` is not an on-request attribute."""
        attr = get(name)
        if attr is None or attr.compute != "on_request":
            return False
        cancel = threading.Event()
        with self._lock:
            self._requests.append(cancel)
            generation = self._generation
            for p in paths:
                key = str(p)
                self._records.setdefault(key, records.get(key, {}))

        def run() -> None:
            count = 0
            for path in paths:
                if cancel.is_set():
                    break
                if not attr.applies_to(path):
                    continue
                value = self._compute_requested(attr, path, cancel)
                if cancel.is_set():
                    break
                if self._put(generation, attr.name, path, value):
                    count += 1
                    if on_ready is not None:
                        on_ready()
            with self._lock:
                if cancel in self._requests:
                    self._requests.remove(cancel)
            if on_done is not None:
                on_done(count, cancel.is_set())

        threading.Thread(target=run, name="xefm-attr-request", daemon=True).start()
        return True

    def _compute_requested(self, attr: Attribute, path, cancel: threading.Event):
        if attr.name == "size":
            record = self._records.get(str(path), {})
            if not record.get("is_dir"):
                return _sync_size(path, record)
            from xefm.disk_usage import UsageScan
            scan = UsageScan([path])
            scan._cancel = cancel
            scan.run_sync()
            return None if cancel.is_set() else scan.grand_totals()[0]
        return self._read(attr, _parent(path), [path])[0]

    def _cancel_requests(self) -> None:
        """Caller holds the lock."""
        for cancel in self._requests:
            cancel.set()
        self._requests.clear()

    def busy(self) -> bool:
        with self._lock:
            return bool(self._requests)

    def cancel_requests(self) -> None:
        with self._lock:
            self._cancel_requests()
