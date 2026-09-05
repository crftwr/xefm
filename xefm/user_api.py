#!/usr/bin/env python3
"""
XeFM in-process customization API — **Preview**.

``~/.xefm/config.py`` is an executed Python module, so it can already hold real
logic. This module is the step that makes it a scripting surface: a config may
define plain functions and bind them to keys (``ACTIONS``) or to moments in the
app's life (``EVENT_HOOKS``), and those functions are handed a small, stable
object through which they read and manipulate the panes.

    def select_docs(ctx):
        ctx.pane.select(lambda entry: entry.name.endswith(".docx"))

    class Config:
        ACTIONS = {"select-docs": select_docs}
        KEY_BINDINGS = {"select-docs": ["U"], ...}

Preview status
--------------

``API_VERSION`` is ``0``: everything here may change — signatures, config
variable formats, the set of events — until it reaches ``1``. A config that uses
``ACTIONS`` or ``EVENT_HOOKS`` gets one line in the log pane saying so at load
time; nothing else gates it, and nothing about the rest of the config changes.

The firewall
------------

**No PuiKit type, widget or :class:`~xefm.app.XeFMApp` internal appears in any
signature here.** That is the whole point of the module: XeFM's internals stay
free to move as long as the small surface below keeps meaning the same thing.
The pane is reached as :class:`PaneApi` — a model-level view of one file pane —
never as the dict the app actually keeps, and never as the widget that draws it.
Additions to this surface are cheap; removals break configs, so it starts
minimal.

Threading
---------

Actions and hooks run **on the UI thread**, synchronously, while XeFM waits.
Long work will freeze the window; there is deliberately no background-work
helper in this version. Prompts are the same story from the other side: the app
never blocks on a modal, so :meth:`ActionContext.input`, :meth:`~ActionContext.choose`
and :meth:`~ActionContext.confirm` hand their answer to a callback rather than
returning it.

Failure isolation
-----------------

An exception raised by a user action or hook is caught at the boundary, logged
with its traceback, and dropped — a crashing action never takes the file manager
down with it. A malformed ``ACTIONS`` / ``EVENT_HOOKS`` entry is a validation
warning that skips that entry, never a load failure.
"""

import traceback
from typing import Any, Callable, Iterable, Mapping, NamedTuple

from xefm import actions as _actions
from xefm import filters as _filters
from xefm import name_key
from xefm import sort_keys as _sort_keys
from xefm.log_manager import getLogger
from xefm.path import Path


class _SeededStat(NamedTuple):
    """The two fields :class:`EntryInfo` reads off a ``stat`` result, filled from
    a listing's attribute record instead of a syscall."""

    st_size: int
    st_mtime: float


logger = getLogger("UserAPI")


#: Bumped only on a breaking change to the façade below or to the ``ACTIONS`` /
#: ``EVENT_HOOKS`` formats. ``0`` means Preview: it may change in any release.
API_VERSION = 0

#: Whether this API is still a preview. Kept as a name so a config can branch on
#: it (``if user_api.PREVIEW: ...``) rather than on a version number.
PREVIEW = True

#: The events ``EVENT_HOOKS`` understands, mapped to the extra arguments each
#: passes after ``ctx``. Used for validation messages and for the docs.
EVENTS: dict[str, str] = {
    "startup": "fn(ctx) — after the app is up, before the first key",
    "quit": "fn(ctx) — before XeFM shuts down",
    "directory_changed": "fn(ctx, pane, old_path, new_path)",
    "file_open": "fn(ctx, path) -> True to claim the open",
}


# --------------------------------------------------------------------------- #
# Entries
# --------------------------------------------------------------------------- #

class EntryInfo:
    """One item in a pane — a file, a directory or a symlink.

    ``path`` is XeFM's :class:`~xefm.path.Path`, which behaves like
    ``pathlib.Path`` and also addresses entries inside archives and on remote
    (S3 / SFTP) storage, so ``entry.path.suffix`` and friends work as expected
    everywhere.

    ``is_dir`` and ``is_link`` come from the listing the pane already read, so
    they cost nothing. ``size`` and ``mtime`` are *not* in that cache — the pane
    only keeps them pre-formatted for display — so they ``stat`` on first access
    and are then remembered. A predicate that only looks at names therefore
    touches the filesystem not at all, which is what keeps
    :meth:`PaneApi.select` cheap over a large directory.

    **``name`` is the name the pane shows, not the bytes on disk.** It is the
    compared name (:mod:`xefm.name_key`): composed, and on a search-results pane
    the whole path below the search root, exactly as the row reads and exactly
    what the built-in sorts order by. Handing over the raw name instead would put
    the bug that module exists to fix inside every config that touched
    ``entry.name`` — a decomposed ``が`` never matching the ``が`` its author
    typed. ``stem`` and ``suffix`` are composed for the same reason.

    ``path`` is the one verbatim thing here, and is what a filesystem call must
    use. On a volume that matches names byte for byte, opening ``entry.name``
    would fail on precisely the entries this distinction exists for.
    """

    __slots__ = ("path", "name", "is_dir", "is_link", "_stat")

    def __init__(self, path, *, is_dir: bool = False, is_link: bool = False,
                 name: str | None = None):
        self.path = path
        #: The listing knows the compared name and passes it; a caller holding
        #: only a path composes the basename, which is the same answer wherever
        #: there is no pane root to be relative to.
        self.name = name or name_key.compare_name(path)
        self.is_dir = is_dir
        self.is_link = is_link
        self._stat: Any = None

    @property
    def is_file(self) -> bool:
        return not self.is_dir

    @property
    def suffix(self) -> str:
        """The extension including its dot, ``''`` when there is none. Composed,
        like :attr:`name` — a predicate comparing it is comparing text."""
        return name_key.nfc(self.path.suffix)

    @property
    def stem(self) -> str:
        """The name without its extension, composed. This is the *file's* own
        stem even on a search-results pane, where :attr:`name` is the whole
        relative path."""
        return name_key.nfc(self.path.stem)

    @classmethod
    def from_attrs(cls, path, attrs: Mapping[str, Any]):
        """An entry whose ``size`` and ``mtime`` come from a listing's attribute
        record instead of a fresh ``stat``.

        The sort hands user keys these. A key is called once per entry, and the
        whole point of the listing snapshot is that it already read is_dir, size
        and mtime for every one of them — letting a key go back to disk would put
        10,000 round trips on a network mount behind an ordering that needs none.
        An entry the listing could not read reports zeroes rather than retrying,
        the same answer :meth:`_stat_result` gives for a broken symlink."""
        entry = cls(path, is_dir=bool(attrs.get("is_dir")),
                    is_link=bool(attrs.get("is_link")),
                    name=attrs.get("cmp_name"))
        entry._stat = (_SeededStat(int(attrs.get("size") or 0),
                                   float(attrs.get("mtime") or 0.0))
                       if attrs.get("ok") else False)
        return entry

    def _stat_result(self):
        if self._stat is None:
            try:
                self._stat = self.path.stat()
            except Exception:
                # An entry that cannot be stat'ed (a broken symlink, a file that
                # vanished between the listing and now) reports zeroes rather
                # than raising through a user predicate.
                self._stat = False
        return self._stat or None

    @property
    def size(self) -> int:
        st = self._stat_result()
        return int(getattr(st, "st_size", 0) or 0)

    @property
    def mtime(self) -> float:
        st = self._stat_result()
        return float(getattr(st, "st_mtime", 0.0) or 0.0)

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:
        kind = "dir" if self.is_dir else "file"
        return f"<EntryInfo {kind} {self.name!r}>"


# --------------------------------------------------------------------------- #
# Panes
# --------------------------------------------------------------------------- #

class PaneApi:
    """One file pane, at the model level.

    Everything here is expressed in entries, paths and indices — never in
    widgets — so a config written against it behaves identically in the terminal
    and in the desktop window.
    """

    def __init__(self, app, pane_name: str):
        self._app = app
        self._name = pane_name

    # --- identity ----------------------------------------------------------- #

    @property
    def _pane(self) -> dict:
        return self._app.pane(self._name)

    @property
    def name(self) -> str:
        """``'left'`` or ``'right'``."""
        return self._name

    @property
    def is_active(self) -> bool:
        """Whether this is the pane the cursor is in."""
        return self._app.pm.active_pane == self._name

    def __repr__(self) -> str:
        return f"<PaneApi {self._name} {self.path}>"

    # --- location ----------------------------------------------------------- #

    @property
    def path(self):
        """The directory this pane is showing."""
        return self._pane["path"]

    def cd(self, path, focus_name: str | None = None) -> None:
        """Show ``path`` in this pane, optionally landing the cursor on the entry
        called ``focus_name``.

        The listing runs on a worker thread, exactly as ordinary navigation does,
        so ``pane.entries`` is empty for a moment after this returns — read the
        new listing from a later action rather than from the next line.
        """
        target = path if hasattr(path, "iterdir") else Path(str(path))
        self._app._go_to_dir(self._pane, target, focus_name)

    def refresh(self) -> None:
        """Re-read the directory. Also asynchronous — see :meth:`cd`."""
        self._app._relist(self._pane)

    # --- entries ------------------------------------------------------------ #

    @property
    def entries(self) -> list[EntryInfo]:
        """Every item currently listed, in the pane's own sort order."""
        pane = self._pane
        info = pane.get("file_info") or {}
        out = []
        for entry in pane["files"]:
            meta = info.get(str(entry)) or {}
            out.append(EntryInfo(entry,
                                 is_dir=bool(meta.get("is_dir")),
                                 is_link=bool(meta.get("is_link")),
                                 name=meta.get("cmp_name")))
        return out

    @property
    def cursor(self) -> int:
        """The focused row's index. Assigning clamps to the listing."""
        return self._pane["focused_index"]

    @cursor.setter
    def cursor(self, index: int) -> None:
        pane = self._pane
        last = max(0, len(pane["files"]) - 1)
        pane["focused_index"] = max(0, min(int(index), last))
        self._app.pm.adjust_scroll_for_focus(pane, self._app._display_height())

    @property
    def focused(self) -> EntryInfo | None:
        """The entry under the cursor, or ``None`` in an empty directory."""
        entries = self.entries
        index = self.cursor
        return entries[index] if 0 <= index < len(entries) else None

    # --- selection ---------------------------------------------------------- #

    def selected(self) -> list[EntryInfo]:
        """The selected entries, in listing order. Empty when nothing is
        selected — this never falls back to the focused entry, so a caller can
        tell the two states apart and apply its own rule."""
        chosen = self._pane["selected_files"]
        return [e for e in self.entries if str(e.path) in chosen]

    def select(self, predicate: Callable[[EntryInfo], bool] | None = None) -> int:
        """Add every entry matching ``predicate`` to the selection, leaving what
        was already selected alone. With no predicate, selects everything.
        Returns how many entries were newly selected.

        A predicate that raises is reported once and treated as "no match", so
        one bad entry cannot abort the sweep.
        """
        pane = self._pane
        chosen = pane["selected_files"]
        added = 0
        for entry in self.entries:
            key = str(entry.path)
            if key in chosen:
                continue
            if predicate is None or _match(predicate, entry):
                chosen.add(key)
                added += 1
        return added

    def unselect(self, predicate: Callable[[EntryInfo], bool] | None = None) -> int:
        """Remove every entry matching ``predicate`` from the selection. With no
        predicate, clears the selection. Returns how many were removed."""
        pane = self._pane
        chosen = pane["selected_files"]
        if predicate is None:
            removed = len(chosen)
            chosen.clear()
            return removed
        removed = 0
        for entry in self.entries:
            key = str(entry.path)
            if key in chosen and _match(predicate, entry):
                chosen.discard(key)
                removed += 1
        return removed


def _match(predicate: Callable[[EntryInfo], bool], entry: EntryInfo) -> bool:
    try:
        return bool(predicate(entry))
    except Exception as exc:
        logger.error(f"Selection predicate failed on {entry.name}: {exc}")
        return False


# --------------------------------------------------------------------------- #
# Action context
# --------------------------------------------------------------------------- #

class ActionContext:
    """What a user action or event hook is handed when it fires.

    It is created per invocation and is cheap; hold on to one past the call at
    your own risk — the panes it points at keep changing underneath it.
    """

    def __init__(self, app):
        self._app = app
        #: Names currently executing as *user* actions. ``invoke()`` consults it
        #: so that an action which overrides a built-in and then invokes its own
        #: name reaches the built-in rather than recurring into itself.
        self._invoking: set[str] = set()

    # --- panes -------------------------------------------------------------- #

    @property
    def pane(self) -> PaneApi:
        """The active pane — the one the cursor is in."""
        return PaneApi(self._app, self._app.pm.active_pane)

    @property
    def other(self) -> PaneApi:
        """The inactive pane."""
        return PaneApi(self._app, "right" if self._app.pm.active_pane == "left" else "left")

    @property
    def left(self) -> PaneApi:
        return PaneApi(self._app, "left")

    @property
    def right(self) -> PaneApi:
        return PaneApi(self._app, "right")

    # --- running other actions ---------------------------------------------- #

    def invoke(self, action_name: str) -> None:
        """Run another action by name, in the file-list context.

        This is the way to reuse built-in behavior instead of reimplementing it,
        and the way an action that *overrides* a built-in still gets at what it
        replaced: invoking your own name from inside your own action runs the
        built-in, not you again.
        """
        self._app._run_action(_actions.FILER, action_name, ctx=self)

    # --- talking to the user ------------------------------------------------ #

    def message(self, text: str) -> None:
        """Write one line to the log pane."""
        self._app.log_info(str(text))

    def input(self, prompt: str, default: str = "", *,
              title: str = "", on_accept: Callable[[str], None] | None = None,
              on_cancel: Callable[[], None] | None = None) -> None:
        """Ask for a line of text.

        XeFM never blocks on a modal, so this returns immediately and the answer
        arrives in ``on_accept``; ``on_cancel`` fires on Esc. Write the rest of
        the action inside the callback.
        """
        from xefm.input_dialog import show_input
        show_input(self._app.panel, title=title or "XeFM", prompt=prompt,
                   text=default,
                   on_accept=_guard("input callback", on_accept, arity=1),
                   on_cancel=_guard("input callback", on_cancel, arity=0))
        self._app.panel.render()

    def choose(self, title: str, items: Iterable[Any], *,
               on_result: Callable[[int | None], None] | None = None) -> None:
        """Offer a list to pick from. The chosen item's **index** — or ``None``
        on cancel — is handed to ``on_result``. Items are shown via ``str()``."""
        from xefm.choice_dialog import show_choice_dialog
        rows = [(i, str(item)) for i, item in enumerate(items)]
        show_choice_dialog(self._app.panel, title, rows,
                           on_result=_guard("choose callback", on_result, arity=1))
        self._app.panel.render()

    def confirm(self, prompt: str, *, title: str = "Confirm",
                on_result: Callable[[bool], None] | None = None) -> None:
        """Ask a yes/no question. ``on_result`` receives ``True`` for OK."""
        from puikit.widgets import show_message_box
        callback = _guard("confirm callback", on_result, arity=1)
        show_message_box(
            self._app.panel, prompt, title=title, icon="question",
            buttons=("OK", "Cancel"), default=0, cancel=1,
            on_result=(lambda label: callback(label == "OK")) if callback else None,
        )
        self._app.panel.render()

    # --- introspection ------------------------------------------------------- #

    @property
    def api_version(self) -> int:
        return API_VERSION

    def action_names(self, context: str = _actions.FILER) -> list[str]:
        """Every action name ``context`` understands — what ``invoke()`` accepts."""
        return _actions.registry.names(context)


def _guard(what: str, func: Callable | None, *, arity: int) -> Callable | None:
    """Wrap a user callback so an exception inside it is logged, not raised into
    the dialog machinery — where it would leave a modal layer stuck open."""
    if func is None:
        return None

    def wrapper(*args):
        run_guarded(what, func, *args[:arity])

    return wrapper


def run_guarded(what: str, func: Callable, *args) -> Any:
    """Call ``func``, reporting any exception instead of letting it escape.

    Every crossing into user code goes through here — that is what keeps a
    config's mistake to one logged traceback rather than a dead file manager.
    """
    try:
        return func(*args)
    except Exception as exc:
        logger.error(f"{what} failed: {exc.__class__.__name__}: {exc}")
        for line in traceback.format_exc().rstrip().splitlines():
            logger.error(f"  {line}")
        return None


# --------------------------------------------------------------------------- #
# Loading ACTIONS / EVENT_HOOKS from a config
# --------------------------------------------------------------------------- #

class EventHooks:
    """The ``EVENT_HOOKS`` table, as loaded. Rebuilt wholesale on reload."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable]] = {}

    def clear(self) -> None:
        self._hooks.clear()

    def set(self, event: str, funcs: list[Callable]) -> None:
        self._hooks[event] = list(funcs)

    def get(self, event: str) -> list[Callable]:
        return self._hooks.get(event, [])

    def count(self) -> int:
        return sum(len(v) for v in self._hooks.values())

    def fire(self, event: str, ctx: "ActionContext", *args) -> bool:
        """Run every hook for ``event`` in order. Returns ``True`` as soon as one
        claims the event by returning ``True`` — the remaining hooks still run,
        so a claim never silently disables another hook's side effect."""
        claimed = False
        for func in self.get(event):
            if run_guarded(f"'{event}' hook", func, ctx, *args) is True:
                claimed = True
        return claimed


#: The process-wide hook table, populated from the config alongside the actions.
hooks = EventHooks()


def load_user_entries(config, registry=None) -> tuple[list[str], int, int, int, int]:
    """Install a config's ``ACTIONS``, ``EVENT_HOOKS``, ``SORT_KEYS`` and ``FILTERS``.

    Every previously loaded user entry is dropped first, so this doubles as the
    reload path: edit the config, reload, and the new definitions replace the old
    ones with no restart and no idempotence contract on the config's part.

    Returns ``(warnings, action_count, hook_count, sort_key_count, filter_count)``. Warnings are the same kind
    of non-fatal, report-them-all diagnostics the rest of ``validate_config``
    produces; a warned entry is skipped, never fatal.
    """
    return _process_user_entries(config, registry, apply=True)


def validate_user_entries(config, registry=None) -> list[str]:
    """The warnings :func:`load_user_entries` *would* produce, without loading
    anything — what ``ConfigManager.validate_config`` reports."""
    return _process_user_entries(config, registry, apply=False)[0]


def _process_user_entries(config, registry, apply: bool) -> tuple[list[str], int, int, int, int]:
    registry = registry if registry is not None else _actions.registry
    if apply:
        registry.unregister_source("user")
        hooks.clear()
        _sort_keys.clear()
        _filters.clear()

    warnings: list[str] = []
    count = 0
    for name, spec in _items(getattr(config, "ACTIONS", None), "ACTIONS", warnings):
        action, problem = _build_action(name, spec)
        if problem:
            warnings.append(problem)
            continue
        existing = registry.resolve(action.context, action.name)
        override = _override_requested(spec)
        if existing is not None and not existing.is_user and not override:
            warnings.append(
                f"ACTIONS['{name}'] would shadow the built-in action '{name}' in "
                f"context '{action.context}' and was ignored — pass "
                f"{{'func': ..., 'override': True}} if that is intended")
            continue
        if apply:
            registry.register(action, override=True)
        count += 1

    hook_count = 0
    for event, spec in _items(getattr(config, "EVENT_HOOKS", None), "EVENT_HOOKS", warnings):
        if event not in EVENTS:
            warnings.append(
                f"EVENT_HOOKS['{event}'] is not a known event and was ignored — "
                f"known events: {', '.join(sorted(EVENTS))}")
            continue
        funcs = [spec] if callable(spec) else list(spec) if isinstance(spec, (list, tuple)) else None
        if funcs is None:
            warnings.append(
                f"EVENT_HOOKS['{event}'] must be a function or a list of "
                f"functions, not {type(spec).__name__}")
            continue
        good = [f for f in funcs if callable(f)]
        if len(good) != len(funcs):
            warnings.append(
                f"EVENT_HOOKS['{event}'] contains "
                f"{len(funcs) - len(good)} entr(y/ies) that are not callable; "
                f"they were ignored")
        if good:
            if apply:
                hooks.set(event, good)
            hook_count += len(good)

    sort_count = 0
    for name, spec in _items(getattr(config, "SORT_KEYS", None), "SORT_KEYS", warnings):
        entry, problem = _build_sort_key(name, spec)
        if problem:
            warnings.append(problem)
            continue
        if apply:
            _sort_keys.register(name, entry["key"], label=entry["label"],
                                explain=entry["explain"], hotkey=entry["hotkey"])
        sort_count += 1

    filter_count = 0
    for name, spec in _items(getattr(config, "FILTERS", None), "FILTERS", warnings):
        entry, problem = _build_filter(name, spec)
        if problem:
            warnings.append(problem)
            continue
        if apply:
            _filters.register(name, match=entry["match"], globs=entry["globs"],
                              label=entry["label"])
        filter_count += 1

    return warnings, count, hook_count, sort_count, filter_count


def _items(value, label: str, warnings: list[str]):
    """``value.items()`` when it is a dict, nothing (with a warning) otherwise."""
    if value is None:
        return []
    if not isinstance(value, dict):
        warnings.append(f"{label} must be a dictionary, not {type(value).__name__}")
        return []
    return list(value.items())


def _build_sort_key(name, spec) -> tuple[dict | None, str | None]:
    """Validate one ``SORT_KEYS`` entry, or explain why it cannot be one.

    Shadowing a built-in mode needs ``"override": True``, as an action does: the
    four built-in names are short and ordinary, and a config that meant to add
    ``"size_then_name"`` and wrote ``"size"`` should hear about it rather than
    quietly redefine what the Size row does."""
    if not isinstance(name, str) or not name:
        return None, f"SORT_KEYS keys must be non-empty strings; ignored {name!r}"
    if callable(spec):
        spec = {"key": spec}
    if not isinstance(spec, dict):
        return None, (f"SORT_KEYS['{name}'] must be a function or a dict with a "
                      f"'key' key, not {type(spec).__name__}")
    func = spec.get("key")
    if not callable(func):
        return None, f"SORT_KEYS['{name}'] has no callable 'key'"
    if name in _sort_keys.BUILTIN_NAMES and not _override_requested(spec):
        return None, (
            f"SORT_KEYS['{name}'] would replace the built-in '{name}' sort and "
            f"was ignored — pass {{'key': ..., 'override': True}} if that is "
            f"intended")
    hotkey = spec.get("hotkey")
    if hotkey is not None:
        hotkey = str(hotkey)[:1].upper()
        if not hotkey.isalpha():
            return None, f"SORT_KEYS['{name}'] has a 'hotkey' that is not a letter"
    return {"label": (str(spec["label"]) if spec.get("label") else None),
            "key": func,
            "explain": (str(spec["explain"]) if spec.get("explain") else None),
            "hotkey": hotkey}, None


def _build_filter(name, spec) -> tuple[dict | None, str | None]:
    """Validate one ``FILTERS`` entry, or explain why it cannot be one.

    Three shorthands collapse into one shape: a callable is a ``match``
    predicate, a string or a list of strings is a ``pattern`` (globs, any one of
    which is enough), and a dict carries either plus a ``label``. There is no
    ``override`` here — unlike a sort mode or an action, a filter name collides
    with nothing built in.
    """
    if not isinstance(name, str) or not name:
        return None, f"FILTERS keys must be non-empty strings; ignored {name!r}"
    if any(c in name for c in _filters.GLOB_CHARS):
        return None, (
            f"FILTERS['{name}'] must not contain the glob characters "
            f"{' '.join(_filters.GLOB_CHARS)} — a filter is remembered under its "
            f"name where a typed pattern is remembered as itself, so a name that "
            f"reads as a pattern could not be told from one; put the glob in "
            f"{{'pattern': '{name}'}} and give the filter a plain name")
    if callable(spec):
        spec = {"match": spec}
    elif isinstance(spec, (str, list, tuple)):
        spec = {"pattern": spec}
    if not isinstance(spec, dict):
        return None, (f"FILTERS['{name}'] must be a function, a pattern, or a "
                      f"dict with a 'match' or 'pattern' key, not "
                      f"{type(spec).__name__}")
    match, pattern = spec.get("match"), spec.get("pattern")
    if match is not None and pattern is not None:
        return None, (f"FILTERS['{name}'] has both 'match' and 'pattern'; a "
                      f"filter is one or the other")
    if match is None and pattern is None:
        return None, f"FILTERS['{name}'] has no 'match' function and no 'pattern'"
    if match is not None and not callable(match):
        return None, f"FILTERS['{name}'] has a 'match' that is not callable"
    globs = None
    if pattern is not None:
        globs = (pattern,) if isinstance(pattern, str) else tuple(pattern)
        if not globs or not all(isinstance(g, str) and g for g in globs):
            return None, (f"FILTERS['{name}'] has a 'pattern' that is not a "
                          f"non-empty string or list of them")
    return {"label": (str(spec["label"]) if spec.get("label") else None),
            "match": match, "globs": globs}, None


def _override_requested(spec) -> bool:
    return isinstance(spec, dict) and bool(spec.get("override"))


def _build_action(name, spec) -> tuple[_actions.Action | None, str | None]:
    """Turn one ``ACTIONS`` entry into an :class:`~xefm.actions.Action`, or
    explain why it cannot be one."""
    if not isinstance(name, str) or not name:
        return None, f"ACTIONS keys must be non-empty strings; ignored {name!r}"
    if callable(spec):
        spec = {"func": spec}
    if not isinstance(spec, dict):
        return None, (f"ACTIONS['{name}'] must be a function or a dict with a "
                      f"'func' key, not {type(spec).__name__}")
    func = spec.get("func")
    if not callable(func):
        return None, f"ACTIONS['{name}'] has no callable 'func'"
    context = spec.get("context", _actions.FILER)
    if context not in _actions.CONTEXTS:
        return None, (f"ACTIONS['{name}'] names unknown context '{context}' — "
                      f"known contexts: {', '.join(_actions.CONTEXTS)}")
    if context != _actions.FILER:
        # Deliberate for this version: a user function running inside a viewer
        # would need a per-view API (scroll position, block list, zoom) that has
        # not been designed yet, and shipping a half-one would freeze it by
        # accident. Rebinding a viewer's *built-in* actions is unaffected.
        return None, (f"ACTIONS['{name}'] targets context '{context}'; user "
                      f"functions are accepted only in '{_actions.FILER}' in this "
                      f"preview (viewer key bindings are rebindable via KEY_BINDINGS)")
    return _actions.Action(
        name=name,
        context=context,
        description=str(spec.get("description") or f"User action '{name}'"),
        default_keys=(),
        func=func,
        source="user",
    ), None


def preview_notice(action_count: int, hook_count: int,
                   sort_key_count: int = 0, filter_count: int = 0) -> str | None:
    """The one line a config using this API gets in the log pane, or ``None``
    when it uses none of it."""
    if not action_count and not hook_count and not sort_key_count and not filter_count:
        return None
    parts = [f"{action_count} action(s)", f"{hook_count} event hook(s)"]
    if sort_key_count:
        parts.append(f"{sort_key_count} sort key(s)")
    if filter_count:
        parts.append(f"{filter_count} filter(s)")
    return (f"Customization API (Preview, API_VERSION {API_VERSION}): "
            f"{', '.join(parts)} loaded — this API may change without notice.")
