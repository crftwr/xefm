#!/usr/bin/env python3
"""
XeFM in-process customization API.

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

It may also define what the panes *show*: ``SORT_KEYS`` and ``FILTERS`` are
functions over one entry, ``IMAGE_DECODERS`` is how a picture in a format XeFM
does not read becomes one it does, and ``PATH_SCHEMES`` is a browsable location
that is not a directory at all — a class, named by its scheme, that XeFM then
treats as a place. ``LEXERS`` names the Pygments lexer that colors a file in
the text viewer (:mod:`xefm.lexer_registry`).

An action can also be put in a menu — the File menu, a row's context menu —
with ``MENU_ITEMS``, keyed by the action's name:

    class Config:
        MENU_ITEMS = {"select-docs": {"menus": ["context"], "label": "Select Documents"}}

    class Config:
        IMAGE_DECODERS = {".dcm": open_dicom}
        PATH_SCHEMES = {"reg": RegistryPathImpl}
        LEXERS = {"*.dcl": DclLexer, "*.mnl": "newlisp"}

The class to inherit is :class:`xefm.path_base.ReadOnlyPathImpl`, never
:class:`~xefm.path.PathImpl`: the intermediate class is where a method added to
the storage interface later arrives carrying a default, so a config written
against today's XeFM keeps loading. See ``doc/VIRTUAL_FOLDERS_FEATURE.md``.

The public names
----------------

**What an extension or a config may use is exactly** ``__all__`` **below** —
``xefm ext check`` refuses any other name taken from this module, and
``help(xefm.user_api)`` lists only these. Everything else here (the loader,
the registries, ``run_guarded``, the names imported from elsewhere such as
``Path``) is XeFM's own and moves without notice, however public it looks.
On the objects, the same line runs through the leading underscore:
``ctx.pane`` is the API, ``ctx._app`` is not.

Stable and Preview
------------------

``API_VERSION`` is ``1``: what is not Preview is stable, and a breaking change
to it bumps the number. Stable today are the ``ACTIONS``, ``SORT_KEYS`` and
``FILTERS`` tables, :class:`EntryInfo`, :class:`PaneApi` and the core of
:class:`ActionContext` — the panes, ``invoke``, ``run_program``, ``message``,
``action_names``. Additions to them do not bump it.

Everything else is Preview, marked one API at a time (:mod:`xefm.preview`):
``open_list``, the prompts (``input`` / ``choose`` / ``confirm`` — whether
the callback shape is livable is not settled), ``run_task`` and its job and
outcome, ``show_markdown`` / ``copy_text`` and the Markdown helpers,
``actions()`` and :class:`ActionInfo`,
``extension()``, ``EVENT_HOOKS`` and :class:`HookEvent`, and the
``IMAGE_DECODERS``, ``PATH_SCHEMES``, ``LEXERS`` and ``MENU_ITEMS`` tables.
A config that uses a Preview table gets one line in the log pane saying so at
load time; nothing else gates it.

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
Long work belongs in :meth:`ActionContext.run_task`, which runs a function on a
worker thread behind XeFM's progress dialog — Cancel, *Run in background* and
all — and hands its outcome back on the UI thread. The worker touches only the
:class:`TaskJob` it is given, never ``ctx``. Prompts are the same story from the
other side: the app never blocks on a modal, so :meth:`ActionContext.input`,
:meth:`~ActionContext.choose` and :meth:`~ActionContext.confirm` hand their
answer to a callback rather than returning it.

Failure isolation
-----------------

An exception raised by a user action or hook is caught at the boundary, logged
with its traceback, and dropped — a crashing action never takes the file manager
down with it. A malformed entry in any of the tables above is a validation
warning that skips that entry, never a load failure.
"""

import contextlib
import inspect
import os
import re
import threading
import traceback
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Mapping, NamedTuple

from xefm import actions as _actions
from xefm import attributes as _attributes
from xefm import filters as _filters
from xefm import image_decoders as _image_decoders
from xefm import layouts as _layouts
from xefm import lexer_registry as _lexers
from xefm import name_key
from xefm import path_schemes as _path_schemes
from xefm import sort_keys as _sort_keys
from xefm.backend_detector import is_desktop_mode
from xefm.external_programs import xefm_python, xefm_tool
from xefm.log_manager import getLogger
from xefm.path import Path, PathImpl
from xefm.path_base import UriPathImpl
from xefm.preview import DEPRECATED_APIS as _DEPRECATED_APIS
from xefm.preview import PREVIEW_APIS as _PREVIEW_APIS, preview


#: A piece of formatted text and its look — what a ``LAYOUTS`` format may
#: return. Defined beside the layouts that draw it; published here.
Cell = preview(_layouts.Cell)
_PREVIEW_APIS.add("xefm.user_api.Cell")


class _SeededStat(NamedTuple):
    """The two fields :class:`EntryInfo` reads off a ``stat`` result, filled from
    a listing's attribute record instead of a syscall."""

    st_size: int
    st_mtime: float


logger = getLogger("UserAPI")

#: The public API: the only names an extension or a config may take from this
#: module (see *The public names* above). ``xefm ext check`` reads this list.
__all__ = [
    # versioning: what is promised, what is not yet, and what is on its way out
    "API_VERSION", "PREVIEW_APIS", "DEPRECATED_APIS",
    # what an action or a hook is handed
    "ActionContext", "PaneApi", "EntryInfo", "HookEvent",
    # an extension package's own settings, state and files
    "extension",
    # background work
    "TaskJob", "TaskOutcome",
    # what ctx.copy / ctx.move report per item
    "ItemResult",
    # what ctx.actions() describes
    "ActionInfo",
    # building Markdown for ctx.show_markdown
    "md_code_block", "md_escape",
    # what a LAYOUTS format may return
    "Cell",
    # for PROGRAMS and the rest of config.py; also importable, for configs
    # written before they lived here, from xefm.external_programs and
    # xefm.backend_detector — those three names only
    "xefm_tool", "xefm_python", "is_desktop_mode",
]


#: Bumped only on a breaking change to an API that is not Preview. Each API is
#: Preview on its own (:data:`PREVIEW_APIS`); ``0`` was the version in which
#: every one of them still was, and ``1`` the first with a stable part.
API_VERSION = 1

#: ``PREVIEW_APIS`` — which APIs are Preview — is set at the foot of this
#: module, once every ``@preview`` below has run.

#: The keys each table's dict form accepts — the schema the API snapshot fixes
#: (test/test_api_snapshot.py). A builder reads the ones it uses and ignores a
#: key not listed, except ``MENU_ITEMS``, which refuses one.
TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "ACTIONS": ("func", "context", "description", "override"),
    "SORT_KEYS": ("key", "label", "explain", "hotkey", "override"),
    "FILTERS": ("match", "pattern", "label"),
    "IMAGE_DECODERS": ("open", "label"),
    "PATH_SCHEMES": ("class", "override"),
    "MENU_ITEMS": ("menus", "label", "when"),
    "ATTRIBUTES": ("label", "type", "read", "values", "where", "compute"),
    "LAYOUTS": _layouts.LAYOUT_KEYS,
    "LAYOUT_EXTRAS": _layouts.EXTRA_KEYS,
}

#: The menus ``MENU_ITEMS`` can put an action in: the menu bar's File menu, and
#: the context menu of a file-list row.
MENUS = ("file", "context")

#: When a ``MENU_ITEMS`` entry is enabled, mapped to what that means. An item
#: whose condition fails is greyed out, as the built-in items are, not hidden.
MENU_WHEN = {
    "always": "always",
    "entry": "there is an entry under the cursor",
    "selection": "at least one entry is selected",
}

#: The events ``EVENT_HOOKS`` understands, mapped to the extra arguments each
#: passes after ``ctx``. Used for validation messages and for the docs.
EVENTS: dict[str, str] = {
    "startup": "after the app is up, before the first key",
    "quit": "before XeFM shuts down",
    "directory_changed": "a pane moved — event.pane, event.old_path, event.new_path",
    "file_open": "Enter on a file — event.path; return True to claim the open",
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
    def _from_attrs(cls, path, attrs: Mapping[str, Any]):
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

    @preview
    def attr(self, name: str):
        """The value of attribute ``name`` (``config.ATTRIBUTES``, or a built-in
        such as ``'tags'`` or ``'size'``) for this entry, as far as XeFM
        already knows it — ``None`` while it is being computed, when it was
        never asked for, or when there is none. Never computes and never waits,
        so it is as cheap in an action on the UI thread as in a sort key.

        ``'name'``, ``'ext'`` and ``'mtime'`` are always known, and so is a
        file's ``'size'``; a folder's is its total once it has been counted."""
        if name in ("name", "ext", "mtime") or (name == "size" and not self.is_dir):
            record = {"cmp_name": self.name, "is_dir": self.is_dir, "ok": True,
                      "size": self.size, "mtime": self.mtime}
            return _attributes.sync_value(name, self.path, record)
        return _attributes.lookup(str(self.path), name)

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

    def activate(self) -> None:
        """Move the cursor into this pane. Does nothing if it is already there.

        ``ctx.pane`` and ``ctx.other`` follow on the next read; a ``PaneApi``
        already in hand keeps naming the pane it was made for.
        """
        self._app._activate_pane(self._name)

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
        target = path if isinstance(path, Path) else Path(str(path))
        self._app._go_to_dir(self._pane, target, focus_name)

    def refresh(self) -> None:
        """Re-read the directory. Also asynchronous — see :meth:`cd`."""
        self._app._relist(self._pane)

    @preview
    def open_list(self, paths, *, title: str) -> None:
        """Open ``paths`` in this pane as a flat list headed ``title``, in place
        of a directory — the door a search of your own comes through.

        *Open* in the sense ``open_item`` opens an archive: the pane now holds
        something other than a directory, every file operation works on it,
        and ``go_parent`` leaves it. Not *show*, which in XeFM means a dialog.

        ``paths`` are strings, ``Path`` objects or entries, absolute or
        relative to :attr:`path`; URIs (``ssh://…``, ``s3://…``) stand as they
        are, and one list may mix drives, hosts and schemes. Rows are named
        relative to the deepest directory they all share, or by their whole
        path where they share none. Nothing on disk changes: every file operation works on the
        rows, and ``go_parent`` returns to :attr:`path`.

        Which paths exist is found on a worker thread, and the pane changes
        only once that lands — to the ones that do, or not at all if none do,
        with the status line saying how many were left out. Like :meth:`cd`,
        then, :attr:`entries` does not hold the list on the next line.

        Producing ``paths`` is the caller's work, and runs where every action
        runs — on the UI thread (see *Threading* above). A search that takes
        seconds freezes the window for those seconds.
        """
        self._app.open_path_list(self._name, list(paths), title=str(title))

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
# Markdown
# --------------------------------------------------------------------------- #

@preview
def md_code_block(text: str, lang: str = "") -> str:
    """``text`` as a fenced Markdown code block, shown exactly as written.

    The fence is one backtick longer than the longest run of backticks in
    ``text``, and never shorter than three, so no line of ``text`` can close
    the block early — a file name with backticks in it, or text that is itself
    Markdown. ``lang`` names the language for syntax coloring (``"python"``).

    In :meth:`ActionContext.show_markdown` the block gets a Copy button, which
    is how a result meant to be pasted elsewhere is best shown::

        ctx.show_markdown("Compute Hash",
                          "**SHA-256**\\n\\n" + md_code_block("\\n".join(lines)))
    """
    text = str(text)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{text}\n{fence}"


#: Characters that mean something to Markdown anywhere in a line.
_MD_INLINE = re.compile(r"([\\`*_{}\[\]()<>!|~])")
#: What makes a line a block — a heading, quote, list item or rule — once the
#: inline characters are escaped: ``#``, ``>``, ``-``, ``+``, ``=``, or a number
#: followed by ``.`` or ``)``, after any indentation.
_MD_LINE_START = re.compile(r"^(\s*)(?:([#>+=-])|(\d+)([.)]))")


@preview
def md_escape(text: str) -> str:
    """``text`` with its Markdown-special characters backslash-escaped, so it
    reads literally in prose: ``md_escape("a_b*.txt")`` shows ``a_b*.txt``,
    not an italic ``b``, and a name that starts ``# `` or ``1.`` stays a
    name rather than becoming a heading or a list. For a file name in a
    sentence; a name in a code block (:func:`md_code_block`) needs no
    escaping, and a URL should not be escaped at all."""
    def line(text: str) -> str:
        text = _MD_INLINE.sub(r"\\\1", text)
        return _MD_LINE_START.sub(
            lambda m: m.group(1) + (f"\\{m.group(2)}" if m.group(2)
                                    else f"{m.group(3)}\\{m.group(4)}"), text)
    return "\n".join(line(part) for part in str(text).split("\n"))


# --------------------------------------------------------------------------- #
# Background tasks
# --------------------------------------------------------------------------- #

@preview
class TaskJob:
    """The handle a :meth:`ActionContext.run_task` worker is given — the one
    thing it may touch, on its own thread.

    It is small on purpose and grows by addition: report progress, and stop
    when asked to."""

    def __init__(self, task):
        self._task = task

    def progress(self, done: int, total: int, *, detail: str = "") -> None:
        """Say how far the work is: ``done`` of ``total`` units, and ``detail``
        (what it is on now — a file name, say) under the title. Until the first
        call, or while ``total`` is 0, the dialog shows a spinner instead of a
        bar. Cheap enough to call once per item."""
        from xefm.progress_manager import OperationType
        pm = self._task.progress
        total = max(0, int(total))
        op = pm.get_current_operation()
        if op is None:
            pm.start_operation(OperationType.TASK, total)
            op = pm.get_current_operation()
        if total <= 0:
            return
        if op["counting"] or op["total_items"] != total:
            pm.update_operation_total(total)
        pm.update_progress(str(detail), processed_items=max(0, int(done)))

    def item_progress(self, done: int, total: int) -> None:
        """Say how far the work is *inside* the current item, in bytes:
        ``done`` of the item's ``total`` bytes. The dialog adds a second bar
        under the item count, with the sizes (``1.2 GB / 30.0 GB``) — what a
        copy shows for a large file. :meth:`progress` starts the next item
        and clears it. Without a :meth:`progress` call first, the work counts
        as one item (#680)."""
        pm = self._task.progress
        if pm.get_current_operation() is None:
            self.progress(0, 1)
        pm.update_file_byte_progress(max(0, int(done)), max(0, int(total)))

    def checkpoint(self) -> None:
        """Stop here if the user cancelled: raises an exception that unwinds
        the worker, and the outcome says ``"cancelled"``. Call it between
        units of work. Let it propagate — a broad ``except Exception`` around
        it would swallow it (the outcome still says cancelled, but the work
        goes on for nothing)."""
        self._task.checkpoint()

    def cancelled(self) -> bool:
        """Whether the user cancelled — for a worker that would rather wind
        down on its own than be unwound by :meth:`checkpoint`."""
        return self._task.cancelled()


@preview
class TaskOutcome:
    """How a :meth:`ActionContext.run_task` ended, handed to its ``on_done`` —
    and likewise how a :meth:`ActionContext.copy` or ``move`` ended.

    ``status`` is ``"done"`` (``value`` is what the work returned),
    ``"cancelled"`` or ``"failed"`` (``error`` is the exception, whose
    traceback XeFM has already logged)."""

    __slots__ = ("status", "value", "error")

    def __init__(self, status: str, value: Any = None,
                 error: BaseException | None = None):
        self.status = status
        self.value = value
        self.error = error

    @property
    def ok(self) -> bool:
        return self.status == "done"

    def __repr__(self) -> str:
        return f"<TaskOutcome {self.status}>"


@preview
class ItemResult:
    """How one item fared in a file operation started from the API —
    :meth:`ActionContext.copy` or :meth:`ActionContext.move` — a list of which
    is the ``value`` of the :class:`TaskOutcome` its ``on_done`` gets.

    ``source`` is the item as given; ``dest`` where it went (or would have);
    ``status`` is ``"done"``, ``"skipped"`` (passed over in the conflict
    dialog) or ``"failed"``. ``errors`` lists ``(name, message)`` for what
    went wrong under it: a folder can be ``"done"`` with a file inside it in
    ``errors``, and is ``"failed"`` only when nothing of it got through."""

    __slots__ = ("source", "dest", "status", "errors")

    def __init__(self, source: Path, dest: Path | None, status: str,
                 errors: Iterable[tuple[str, str]] = ()):
        self.source = source
        self.dest = dest
        self.status = status
        self.errors = list(errors)

    @property
    def ok(self) -> bool:
        return self.status == "done"

    def __repr__(self) -> str:
        return f"<ItemResult {self.status} {self.source}>"


@preview
class ActionInfo:
    """One action, as :meth:`ActionContext.actions` describes it.

    ``name`` is what ``invoke()`` takes; ``description`` the one line the
    command palette shows; ``aliases`` the names it used to have, which still
    resolve to it; ``keys`` the keys bound to it in the file list right now —
    the keymap preset's, with ``KEY_BINDINGS`` applied — empty when unbound."""

    __slots__ = ("name", "description", "aliases", "keys")

    def __init__(self, name: str, description: str = "",
                 aliases: tuple[str, ...] = (), keys: tuple[str, ...] = ()):
        self.name = name
        self.description = description
        self.aliases = tuple(aliases)
        self.keys = tuple(keys)

    def __repr__(self) -> str:
        return f"<ActionInfo {self.name}>"


# --------------------------------------------------------------------------- #
# Extension packages
# --------------------------------------------------------------------------- #

@preview
def extension(module: str):
    """The extension package that ``module`` belongs to — call it with
    ``__name__``::

        from xefm.user_api import extension

        def compute(ctx):
            state = extension(__name__).state

    It returns a handle with ``id``, ``version``, ``settings`` (the package's
    defaults overlaid with the plain ``config.py`` class named after it, e.g.
    ``ComputeHashConfig``), ``state`` (a key-value store in XeFM's state
    database, safe from any thread) and ``data_dir`` (its own directory under
    ``~/.xefm/extension-data/``). ``None`` for code that is not in a loaded
    package — ``config.py`` itself, or a hand-written module.

    The package is found from the module's own name, not from what is running
    at the moment, so the answer is the same in an action, a prompt's callback,
    a ``run_task`` worker or a sort key — the places a value handed in through
    ``ctx`` could not reach. Nothing is written twice: the id stays in the
    manifest alone."""
    from xefm.extensions import handle_for_module
    return handle_for_module(module)


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #

@preview
class HookEvent:
    """What an ``EVENT_HOOKS`` function is handed after ``ctx``: every hook is
    ``fn(ctx, event)``, whatever the event.

    ``event.name`` is the event's name; the rest is what happened, as
    attributes — ``pane``, ``old_path`` and ``new_path`` for
    ``directory_changed``, ``path`` for ``file_open`` (see ``EVENTS``).

    One object rather than one argument per fact is what lets an event say
    more later: a new fact is a new attribute, and a hook that does not read
    it never notices. A hook written ``fn(ctx, pane, old, new)`` would break
    the day a fifth argument arrived."""

    def __init__(self, name: str, **facts: Any):
        self.name = name
        for key, value in facts.items():
            setattr(self, key, value)

    def __repr__(self) -> str:
        facts = ", ".join(f"{k}={v!r}" for k, v in vars(self).items() if k != "name")
        return f"<HookEvent {self.name}{': ' + facts if facts else ''}>"


def _call_problem(func: Callable, n_args: int, shape: str) -> str | None:
    """Why ``func`` cannot be called with ``n_args`` positional arguments — the
    way XeFM calls the callback documented as ``shape`` — or None. A function
    whose signature cannot be read is given the benefit of the doubt."""
    try:
        inspect.signature(func).bind(*range(n_args))
    except TypeError:
        name = getattr(func, "__name__", repr(func))
        return f"{name} cannot be called as {shape}"
    except ValueError:
        return None
    return None


def _operation_path(item: Any, what: str) -> Path:
    """An item or destination of a file operation as a :class:`Path`: an
    :class:`EntryInfo`'s path, a :class:`Path` as is, a string only when it is
    absolute (a local path or a URI) — a relative one would resolve against
    whatever XeFM's own working directory happens to be."""
    if isinstance(item, EntryInfo):
        return item.path
    if isinstance(item, Path):
        return item
    if isinstance(item, os.PathLike):
        item = os.fspath(item)
    if isinstance(item, str):
        if "://" not in item and not os.path.isabs(item):
            raise ValueError(f"{what}: {item!r} is not an absolute path")
        return Path(item)
    raise ValueError(f"{what}: expected an EntryInfo, a Path or a str, "
                     f"not {type(item).__name__}")


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

    # --- running external programs ------------------------------------------ #

    def run_program(self, command, *, terminal: bool = False,
                    cwd: str | None = None,
                    env: Mapping[str, str] | None = None) -> int | None:
        """Run an external program the way a ``PROGRAMS`` entry runs — but from
        an action, so it can have a key of its own.

        ``command`` is a list (argv, taken as written) or a string (a command
        line, split like a shell would). Unlike a ``PROGRAMS`` entry, **no file
        names are appended**: build the argv yourself from
        ``ctx.pane.selected()`` / ``ctx.pane.focused`` if the program wants
        them. The program sees the same ``XEFM_*`` variables either way, merged
        under ``env``. ``cwd`` defaults to the active pane's directory (XeFM's
        own when the pane is not on the local disk).

        - ``terminal=False`` (the default) starts the program in the
          background, streams its output into the log pane, and returns
          ``None`` at once.
        - ``terminal=True`` hands the terminal over to the program — an editor,
          a pager, anything that draws a screen or reads the keyboard — and
          waits for it. The panes are re-read on return, and the exit code is
          returned (``None`` if it could not be started). A nonzero exit holds
          the screen until Enter so its last words stay readable. The desktop
          window has no terminal to lend, so there the program opens in the
          ``TERMINAL`` application instead and ``None`` comes back at once —
          the terminal window is on its own from then on.

        Never call :mod:`subprocess` directly for an interactive program: XeFM
        owns the terminal, and a child drawing on it unannounced leaves the
        screen corrupted and the keyboard fought over (#454). To run one
        yourself — to feed it input or read what it prints — do it inside
        :meth:`terminal_backend_suspended`.

        Call it on the UI thread, as an action or hook runs; from any other
        thread it raises RuntimeError.
        """
        self._require_ui_thread("run_program")
        from xefm.external_programs import command_argv
        argv = command_argv(command)
        if not argv:
            raise ValueError("run_program: the command is empty")
        launch = self.program_env()
        if env:
            launch["env"].update({str(k): str(v) for k, v in env.items()})
        if cwd is None:
            cwd = launch["cwd"]
        return self._app._launch_program(
            argv[0], argv, cwd=str(cwd) if cwd is not None else None,
            env=launch["env"], terminal=terminal)

    @preview
    def program_env(self) -> dict[str, Any]:
        """``{"cwd": ..., "env": ...}`` for a program you start yourself with
        :mod:`subprocess` — ``subprocess.run(argv, **ctx.program_env())`` —
        what :meth:`run_program` gives its own: the active pane's directory
        (``None`` when the pane is not on the local disk, so the program runs in
        XeFM's) and XeFM's environment with the ``XEFM_*`` variables added. The
        dict is new on every call; change it as you like.

        It reads the panes, so call it on the UI thread; from any other thread
        it raises RuntimeError.
        """
        self._require_ui_thread("program_env")
        env, cwd = self._app._program_env(self._app.active_pane())
        return {"cwd": str(cwd) if self._app._is_local(cwd) else None,
                "env": env}

    @property
    @preview
    def is_terminal_backend(self) -> bool:
        """Whether XeFM is drawing in a terminal — the terminal app — so that
        :meth:`terminal_backend_suspended` has a terminal to hand over. False in
        the desktop app."""
        return not is_desktop_mode()

    @preview
    @contextlib.contextmanager
    def terminal_backend_suspended(self) -> Iterator[None]:
        """Hand the terminal to programs you run yourself, inside a ``with``::

            with ctx.terminal_backend_suspended():
                r = subprocess.run(["fzf"], input="\\n".join(names), text=True,
                                   stdout=subprocess.PIPE, **ctx.program_env())
            if r.returncode == 0:
                ctx.pane.cd(r.stdout.strip())

        Inside, XeFM's terminal backend is suspended: the screen and the
        keyboard belong to the terminal, and anything :mod:`subprocess` can do —
        ``input``, capturing ``stdout`` or ``stderr`` on its own, ``Popen``,
        several programs in a row — works as it would in a shell. On the way
        out, an exception included, XeFM takes the terminal back, re-reads both
        panes and repaints. It yields nothing.

        Raises RuntimeError in the desktop app, which has no terminal to hand
        over (check :attr:`is_terminal_backend` first), when called off the UI
        thread, and when the terminal is already handed over.

        What :meth:`run_program` does on top is yours to do here: hold the
        screen after a failure if you want it held — a picker that exits
        nonzero on Esc usually does not — and on Windows resolve a ``.cmd``
        program with :func:`shutil.which`, since :mod:`subprocess` does not
        search PATHEXT.
        """
        self._require_ui_thread("terminal_backend_suspended")
        if not self.is_terminal_backend:
            raise RuntimeError("terminal_backend_suspended: the desktop app "
                               "has no terminal to hand over")
        with self._app._terminal_suspended():
            yield

    def _require_ui_thread(self, api: str) -> None:
        """Raise unless called on the thread that runs XeFM's UI. An API that
        lends the terminal or reads the panes must not run beside the UI thread
        that owns them."""
        ui_thread = getattr(self._app, "_ui_thread", None)
        if ui_thread is not None and threading.current_thread() is not ui_thread:
            raise RuntimeError(
                f"{api} must be called on XeFM's UI thread — from the action "
                f"or hook itself, not from run_task's work or a thread of yours")

    # --- background work ---------------------------------------------------- #

    @preview
    def run_task(self, title: str, work: Callable[[TaskJob], Any], *,
                 on_done: Callable[["ActionContext", TaskOutcome], None] | None = None,
                 read_only: bool = False) -> None:
        """Run ``work(job)`` on a worker thread, the way XeFM runs a copy: a
        progress dialog headed ``title``, with Cancel and *Run in background*.
        Returns at once.

        ``work`` may touch only ``job`` (:class:`TaskJob`) — never ``ctx``, a
        pane, or anything else of XeFM's, which belong to the UI thread. What
        it reads (an ``EntryInfo.path``, a setting) it should take from the
        action before the task starts.

        ``on_done(ctx, outcome)`` runs on the UI thread when the work ends, with
        a new ``ctx`` — the one the action held is stale by then — and a
        :class:`TaskOutcome`. It runs whether the work finished, was cancelled
        or raised; a raised exception is logged with its traceback first.

        ``read_only=True`` states that the work changes nothing on disk. XeFM
        then lets it run beside a background copy rather than queue behind one;
        how such tasks are scheduled is XeFM's to decide, and may change.
        """
        from xefm.task import Task
        app = self._app
        task = Task(str(title), config=app.config, kind="user",
                    busy_label="Working…")
        task.exclusive = not read_only
        job = TaskJob(task)

        def run(_task) -> dict:
            return {"value": work(job)}

        def done(result: dict) -> None:
            if task.error is not None and not task.cancelled():
                _report_exception(f"Task '{task.title}'", task.error)
                outcome = TaskOutcome("failed", error=task.error)
            elif task.cancelled():
                outcome = TaskOutcome("cancelled")
            else:
                outcome = TaskOutcome("done", result.get("value"))
            if on_done is not None:
                ctx = ActionContext(app)
                run_guarded(f"'{task.title}' completion", on_done, ctx, outcome)
            app.panel.render()

        app.tasks.submit(task, app.panel, run=run, on_done=done)

    # --- file operations ---------------------------------------------------- #

    @preview
    def copy(self, items: Iterable["EntryInfo | Path | str"], dest: "Path | str",
             *, on_done: Callable[["ActionContext", TaskOutcome], None]
             | None = None) -> None:
        """Copy ``items`` into the directory ``dest`` the way the built-in copy
        does — its confirmation, the conflict dialog, the job queue, progress
        with Cancel and *Run in background* — then re-list the panes showing
        ``dest``. Returns at once.

        ``items`` takes what ``ctx.pane.selected()`` returns, paths, or
        absolute path strings; which items to copy is yours to decide (an empty
        list copies nothing). ``dest`` is a directory, created if missing; it
        may be on SSH or S3, never inside an archive.

        ``on_done(ctx, outcome)`` runs on the UI thread once the operation is
        over — not when it is handed to the queue — and never before ``copy``
        returns, with a new ``ctx``. ``outcome`` is a :class:`TaskOutcome`:
        ``"done"`` with ``value`` a list of :class:`ItemResult`, one per item;
        ``"cancelled"`` (at the confirmation, in the conflict dialog or during
        the run) with the items settled so far; ``"failed"`` with ``error``
        when the operation itself broke.

        Wrong arguments raise ValueError at once: a relative path string, an
        archive destination, or an item whose own folder is ``dest``.
        """
        self._transfer("copy", items, dest, on_done)

    @preview
    def move(self, items: Iterable["EntryInfo | Path | str"], dest: "Path | str",
             *, on_done: Callable[["ActionContext", TaskOutcome], None]
             | None = None) -> None:
        """Move ``items`` into the directory ``dest`` — :meth:`copy`, but a
        move: the panes showing an item's old folder are re-listed too, and an
        item inside an archive is a ValueError, since an archive cannot give
        one up."""
        self._transfer("move", items, dest, on_done)

    def _transfer(self, kind: str, items, dest, on_done) -> None:
        self._require_ui_thread(kind)
        app = self._app
        targets = [_operation_path(item, f"{kind}: item") for item in items]
        dest_dir = _operation_path(dest, f"{kind}: dest")
        if app._is_archive(dest_dir):
            raise ValueError(f"{kind}: {dest_dir} is inside an archive, "
                             f"which is read-only")
        for target in targets:
            if str(target.parent) == str(dest_dir):
                raise ValueError(f"{kind}: {target} is already in {dest_dir}")
            if kind == "move" and app._is_archive(target):
                raise ValueError(f"move: {target} is inside an archive — "
                                 f"copy it instead")

        def report(outcome: TaskOutcome) -> None:
            if on_done is not None:
                run_guarded(f"{kind} completion", on_done,
                            ActionContext(app), outcome)

        def complete(result: dict) -> None:
            error = result.get("error")
            if error is not None:
                _report_exception(f"{kind.capitalize()}", error)
                outcome = TaskOutcome("failed", error=error)
            else:
                value = [ItemResult(t, d, status, errors)
                         for t, d, status, errors in result.get("targets", [])]
                outcome = TaskOutcome(
                    "cancelled" if result.get("cancelled") else "done", value)
            app._call_later(lambda: report(outcome))

        def declined() -> None:
            app._call_later(lambda: report(TaskOutcome("cancelled", [])))

        if not targets:
            app._call_later(lambda: report(TaskOutcome("done", [])))
            return
        app._transfer_for_api(kind, targets, dest_dir, complete, declined)

    # --- talking to the user ------------------------------------------------ #

    def message(self, text: str) -> None:
        """Write one line to the log pane."""
        self._app.log_info(str(text))

    @preview
    def show_markdown(self, title: str, source: str) -> None:
        """Show ``source``, Markdown, in a scrollable dialog headed ``title`` —
        the one Help and File Details use. Returns at once; the user closes it
        with Esc or Enter.

        Every fenced code block in it gets a Copy button (a Tab stop, so Enter
        copies it from the keyboard too), and any part of the text can be
        selected and copied. Build the source with :func:`md_code_block` for
        text to be copied and :func:`md_escape` for names in prose."""
        from xefm.text_dialog import show_markdown
        show_markdown(self._app.panel, str(source), title=str(title))
        self._app.panel.render()

    @preview
    def diff(self, left: "EntryInfo | Path | str", right: "EntryInfo | Path | str",
             *, left_title: str | None = None,
             right_title: str | None = None) -> None:
        """Compare two files the way **Compare Selected Files** does, without
        their being selected: side by side in the diff viewer when both are
        text, byte for byte in a message box when either is binary. Returns at
        once.

        ``left`` and ``right`` take entries, paths or absolute path strings, on
        anything XeFM can read — the local disk, an archive, SSH, S3 or a
        virtual folder of your own, so a file can be compared with an older
        version of itself that a ``PATH_SCHEMES`` class serves. Each side's
        header shows the file name unless ``left_title`` / ``right_title``
        names it (``"HEAD"``, ``"Working tree"``).

        A folder on either side, or one that does not exist, is not compared:
        the log pane says so. Wrong argument types raise ValueError at once.
        """
        self._require_ui_thread("diff")
        paths = [_operation_path(left, "diff: left"),
                 _operation_path(right, "diff: right")]
        for path in paths:
            try:
                is_file = path.is_file()
            except OSError:
                is_file = False
            if not is_file:
                self._app.log_info(f"Compare: {path} is not a file")
                return
        self._app.open_diff(paths[0], paths[1], titles=(left_title, right_title))

    @preview
    def copy_text(self, text: str) -> None:
        """Put ``text`` on the clipboard — the system one where XeFM can reach
        it. Like any copy, it replaces files XeFM's clipboard was holding."""
        self._app._set_text_clipboard(str(text))

    @preview
    def input(self, prompt: str, default: str = "", *,
              title: str = "", on_accept: Callable[[str], None] | None = None,
              on_cancel: Callable[[], None] | None = None,
              complete: str | None = None) -> None:
        """Ask for a line of text.

        XeFM never blocks on a modal, so this returns immediately and the answer
        arrives in ``on_accept``; ``on_cancel`` fires on Esc. Write the rest of
        the action inside the callback.

        ``complete`` gives the field Tab completion of paths, the one Jump to
        Path and Copy to Path use, remote paths included:

        - ``"path"`` — files and folders.
        - ``"directory"`` — folders only.

        A relative path — ``./``, ``../``, or a bare name — completes against
        the active pane's directory, and hidden entries follow the panes'
        toggle. The answer is the text as typed; resolving a relative one
        against ``ctx.pane.path`` is the action's to do. An unknown
        ``complete`` is a ValueError, which the action boundary logs.
        """
        from xefm.input_dialog import show_input
        completer = None
        if complete is not None:
            if complete not in ("path", "directory"):
                raise ValueError(
                    f"input(complete={complete!r}): expected 'path' or 'directory'")
            from xefm.completion import FilepathCompleter
            completer = FilepathCompleter(
                base_directory=str(self._app.active_pane()["path"]),
                directories_only=complete == "directory",
                show_hidden=self._app.flm.show_hidden)
        show_input(self._app.panel, title=title or "XeFM", prompt=prompt,
                   text=default,
                   on_accept=_guard("input callback", on_accept, arity=1),
                   on_cancel=_guard("input callback", on_cancel, arity=0),
                   completer=completer)
        self._app.panel.render()

    @preview
    def choose(self, title: str, items: Iterable[Any], *, type: str = "choice",
               on_result: Callable[[int | None], None] | None = None) -> None:
        """Offer a list to pick from. The chosen item's **index** — or ``None``
        on cancel — is handed to ``on_result``. Items are shown via ``str()``.

        ``type`` names the dialog, because a list of three and a list of three
        hundred want different ones:

        - ``"choice"`` — a compact box sized to its items, where typing jumps
          the selection and a second of quiet forgets what was typed. The
          default, and right for a handful of alternatives.
        - ``"filter"`` — the picker the built-in Favorites and History lists
          use: a filter field over a scrolling list, anchored over the active
          pane. It takes the same query the file pane's incremental search
          takes — whitespace-separated tokens, wildcards, and Migemo, so romaji
          finds Japanese labels — and holds it until it is erased. For a list
          long enough to search (#467).

        An unknown ``type`` is a ValueError, which the action boundary logs.
        """
        callback = _guard("choose callback", on_result, arity=1)
        if type == "choice":
            from xefm.choice_dialog import show_choice_dialog
            rows = [(i, str(item)) for i, item in enumerate(items)]
            show_choice_dialog(self._app.panel, title, rows, on_result=callback)
        elif type == "filter":
            # The dialog reports the *value* it was given, so the values are the
            # indices themselves and the labels are read off a list built once —
            # `items` is an Iterable and may well be a generator.
            from xefm.filter_list_dialog import show_filter_list
            labels = [str(item) for item in items]
            show_filter_list(
                self._app.panel, range(len(labels)), title=title,
                to_label=lambda i: labels[i],
                on_accept=callback,
                on_cancel=(lambda: callback(None)) if callback else None,
                region=self._app._active_pane_region(),
            )
        else:
            raise ValueError(
                f"choose(type={type!r}): expected 'choice' or 'filter'")
        self._app.panel.render()

    @preview
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

    def action_names(self) -> list[str]:
        """Every action name ``invoke()`` accepts — the file list's."""
        return _actions.registry.names(_actions.FILER)

    @preview
    def actions(self) -> list[ActionInfo]:
        """Every action ``invoke()`` accepts, as :class:`ActionInfo` — in the
        order :meth:`action_names` lists them."""
        keys = self._app.keys
        return [ActionInfo(a.name, a.description, a.aliases,
                           keys.get_keys_for_action(a.name, _actions.FILER)[0])
                for a in _actions.registry.actions(_actions.FILER)]


def _guard(what: str, func: Callable | None, *, arity: int) -> Callable | None:
    """Wrap a user callback so an exception inside it is logged, not raised into
    the dialog machinery — where it would leave a modal layer stuck open."""
    if func is None:
        return None

    def wrapper(*args):
        run_guarded(what, func, *args[:arity])

    return wrapper


def report_user_failure(what: str, exc: BaseException) -> None:
    """Log a failure in config-supplied code, with its traceback.

    Split out of :func:`run_guarded` because not every crossing into user code
    can be a call-and-discard: a ``PATH_SCHEMES`` backend is asked questions
    whose *answer* the caller needs — does this path exist, is it a directory —
    so the caller has to see that the question failed, and only the reporting is
    shared. Must be called while the exception is being handled; the traceback
    comes from :func:`sys.exc_info`.
    """
    logger.error(f"{what} failed: {exc.__class__.__name__}: {exc}")
    for line in traceback.format_exc().rstrip().splitlines():
        logger.error(f"  {line}")


def _report_exception(what: str, exc: BaseException) -> None:
    """:func:`report_user_failure` for an exception caught somewhere else — on
    a worker thread — and reported later, from its own traceback."""
    logger.error(f"{what} failed: {exc.__class__.__name__}: {exc}")
    for chunk in traceback.format_exception(type(exc), exc, exc.__traceback__):
        for line in chunk.rstrip().splitlines():
            logger.error(f"  {line}")


def run_guarded(what: str, func: Callable, *args) -> Any:
    """Call ``func``, reporting any exception instead of letting it escape.

    Every crossing into user code goes through here — that is what keeps a
    config's mistake to one logged traceback rather than a dead file manager.
    """
    try:
        return func(*args)
    except Exception as exc:
        report_user_failure(what, exc)
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

    def fire(self, event: str, ctx: "ActionContext", **facts) -> bool:
        """Run every hook for ``event`` in order, as ``fn(ctx, HookEvent)``
        carrying ``facts``. Returns ``True`` as soon as one claims the event by
        returning ``True`` — the remaining hooks still run, so a claim never
        silently disables another hook's side effect."""
        claimed = False
        info = HookEvent(event, **facts)
        for func in self.get(event):
            if run_guarded(f"'{event}' hook", func, ctx, info) is True:
                claimed = True
        return claimed


#: The process-wide hook table, populated from the config alongside the actions.
hooks = EventHooks()


class MenuEntry(NamedTuple):
    """One loaded ``MENU_ITEMS`` entry: put ``action`` in each of ``menus``,
    labeled ``label``, enabled per ``when`` (a :data:`MENU_WHEN` key)."""

    action: str
    label: str
    menus: tuple[str, ...]
    when: str


#: The loaded ``MENU_ITEMS``, in the config's order. Rebuilt on reload.
menu_entries: list[MenuEntry] = []


def menu_items(menu: str) -> list[MenuEntry]:
    """The loaded entries that go in ``menu`` (one of :data:`MENUS`)."""
    return [entry for entry in menu_entries if menu in entry.menus]


class LoadResult(NamedTuple):
    """What :func:`load_user_entries` loaded: the warnings, then how many
    entries of each table. ``scheme_overrides`` counts the ``PATH_SCHEMES``
    entries that replace a built-in scheme — the Preview part of a table that
    is otherwise stable."""

    warnings: list
    actions: int
    hooks: int
    sort_keys: int
    filters: int
    image_decoders: int
    path_schemes: int
    lexers: int
    menu_items: int = 0
    scheme_overrides: int = 0
    attributes: int = 0
    layouts: int = 0
    extras: int = 0


def load_user_entries(config, registry=None) -> LoadResult:
    """Install a config's ``ACTIONS``, ``EVENT_HOOKS``, ``SORT_KEYS``,
    ``FILTERS``, ``IMAGE_DECODERS``, ``PATH_SCHEMES`` and ``LEXERS``.

    Every previously loaded user entry is dropped first, so this doubles as the
    reload path: edit the config, reload, and the new definitions replace the old
    ones with no restart and no idempotence contract on the config's part.

    Returns a :class:`LoadResult`. Its warnings are the same kind of non-fatal,
    report-them-all diagnostics the rest of ``validate_config`` produces; a
    warned entry is skipped, never fatal.
    """
    return _process_user_entries(config, registry, apply=True)


def validate_user_entries(config, registry=None) -> list[str]:
    """The warnings :func:`load_user_entries` *would* produce, without loading
    anything — what ``ConfigManager.validate_config`` reports."""
    return _process_user_entries(config, registry, apply=False)[0]


def _process_user_entries(config, registry, apply: bool) -> LoadResult:
    registry = registry if registry is not None else _actions.registry
    if apply:
        registry.unregister_source("user")
        hooks.clear()
        _sort_keys.clear()
        _filters.clear()
        _image_decoders.clear()
        _path_schemes.unregister_source("user")
        _lexers.clear()
        menu_entries.clear()
        _attributes.clear()
        _layouts.clear()

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
        # Every hook is fn(ctx, event). One written for the old per-event
        # arguments (fn(ctx, pane, old_path, new_path)) would fail on every
        # firing; say so once, here, and leave it out.
        for func in list(good):
            problem = _call_problem(func, 2, "fn(ctx, event)")
            if problem:
                warnings.append(
                    f"EVENT_HOOKS['{event}']: {problem} and was ignored — every "
                    f"hook takes (ctx, event) and reads what happened from "
                    f"the event's attributes")
                good.remove(func)
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

    decoder_count = 0
    for name, spec in _items(getattr(config, "IMAGE_DECODERS", None),
                             "IMAGE_DECODERS", warnings):
        entry, problem = _build_image_decoder(name, spec)
        if problem:
            warnings.append(problem)
            continue
        if apply:
            _image_decoders.register(entry["suffix"], entry["open"],
                                     label=entry["label"])
        decoder_count += 1

    scheme_count = scheme_overrides = 0
    for name, spec in _items(getattr(config, "PATH_SCHEMES", None), "PATH_SCHEMES", warnings):
        impl, problem = _build_path_scheme(name, spec)
        if problem:
            warnings.append(problem)
            continue
        if not issubclass(impl, UriPathImpl):
            # Loaded anyway: it worked yesterday, and refusing it would take the
            # user's folder away over a promise, not a fault.
            warnings.append(
                f"PATH_SCHEMES['{name}'] is {impl.__name__}, which does not "
                f"build on xefm.path_base.ReadOnlyPathImpl or UriPathImpl — "
                f"subclassing PathImpl directly is not supported and breaks "
                f"whenever XeFM's storage interface grows")
        if name in _path_schemes.schemes("builtin"):
            scheme_overrides += 1
        if apply:
            _path_schemes.register(name, impl, source="user")
        scheme_count += 1

    lexer_count = 0
    lexer_items = _items(getattr(config, "LEXERS", None), "LEXERS", warnings)
    if lexer_items and not _lexers.PYGMENTS:
        warnings.append("LEXERS was ignored: Pygments is not installed, so "
                        "nothing is syntax-highlighted")
        lexer_items = []
    # Classes before aliases, so '*.dclx': 'dcl' finds the DclLexer registered
    # in the same table whichever line comes first. Without applying, there is
    # no table to find it in: check the classes' own aliases instead.
    lexer_items.sort(key=lambda item: isinstance(item[1], str))
    table_aliases = {a.lower() for _, v in lexer_items if isinstance(v, type)
                     for a in getattr(v, "aliases", ())}
    for pattern, spec in lexer_items:
        problem = _check_lexer(pattern, spec, None if apply else table_aliases)
        if problem:
            warnings.append(problem)
            continue
        if apply:
            _lexers.register(pattern, spec)
        lexer_count += 1

    # After ACTIONS, so an item can name an action the same config defines.
    # Without applying, those are not registered: take their names from the
    # table instead.
    table = getattr(config, "ACTIONS", None)
    own = set(table) if isinstance(table, dict) and not apply else set()
    menu_count = 0
    for name, spec in _items(getattr(config, "MENU_ITEMS", None), "MENU_ITEMS", warnings):
        entry, problem = _build_menu_entry(name, spec, registry, own)
        if problem:
            warnings.append(problem)
            continue
        if apply:
            menu_entries.append(entry)
        menu_count += 1

    attr_count = 0
    attr_names = set(_attributes.BUILTIN)
    for name, spec in _items(getattr(config, "ATTRIBUTES", None), "ATTRIBUTES", warnings):
        attr, problem = _attributes.build(name, spec)
        if problem:
            warnings.append(problem)
            continue
        if apply:
            _attributes.register(attr)
        attr_names.add(name)
        attr_count += 1

    layout_count = 0
    layout_names = {_layouts.DEFAULT}
    for name, spec in _items(getattr(config, "LAYOUTS", None), "LAYOUTS", warnings):
        layout, problem = _layouts.build(name, spec)
        if problem:
            warnings.append(problem)
            continue
        unknown = sorted(n for n in layout.attributes() if n not in attr_names)
        if unknown:
            # Loaded anyway: the rest of the layout is fine, and the column
            # appears once the attribute does (an extension enabled later).
            warnings.append(
                f"LAYOUTS['{name}'] names attribute(s) nothing defines: "
                f"{', '.join(unknown)} — those columns are left out"
                f"{_renamed_hint(unknown)}")
        if apply:
            _layouts.register(layout)
        layout_names.add(name)
        layout_count += 1

    if getattr(config, "LAYOUT_RULES", None):
        warnings.append("LAYOUT_RULES is gone: an entry of LAYOUT_EXTRAS says where it "
                        "applies with 'when', and a tab's layout is chosen with "
                        "View > Layout (DEFAULT_LAYOUT for new tabs)")

    default = getattr(config, "DEFAULT_LAYOUT", None) or _layouts.DEFAULT
    if default not in layout_names:
        warnings.append(f"DEFAULT_LAYOUT names '{default}', which LAYOUTS does not "
                        f"define; 'default' is used")
        default = _layouts.DEFAULT
    if apply:
        _layouts.set_default(default)

    # A name an extension or the built-ins already define is overridden key by
    # key: config.py names only what it changes.
    extra_count = 0
    built = [e for e in (_layouts.build_extra(n, spec, source="builtin")[0]
                         for n, spec in _layouts.BUILTIN_EXTRA_SPECS.items()) if e]
    built = {e.name: e for e in built}
    for name, spec in _items(getattr(config, "LAYOUT_EXTRAS", None), "LAYOUT_EXTRAS", warnings):
        base = _layouts.BUILTIN_EXTRA_SPECS.get(name)
        if base is not None and isinstance(spec, dict):
            spec = {**base, **spec}
        extra, problem = _layouts.build_extra(name, spec)
        if problem:
            warnings.append(problem)
            continue
        unknown = sorted(n for n in extra.attributes() if n not in attr_names)
        if unknown:
            warnings.append(
                f"LAYOUT_EXTRAS['{name}'] names attribute(s) nothing defines: "
                f"{', '.join(unknown)} — those are left out"
                f"{_renamed_hint(unknown)}")
        if apply:
            _layouts.register_extra(extra)
        built[name] = extra
        extra_count += 1
    if apply:
        # The sample entry a user format is handed, when the check renders
        # each value — never a real file.
        warnings.extend(_layouts.collisions(
            list(built.values()), lambda: EntryInfo(Path("."))))

    return LoadResult(warnings, count, hook_count, sort_count, filter_count,
                      decoder_count, scheme_count, lexer_count, menu_count,
                      scheme_overrides, attr_count, layout_count, extra_count)


def _renamed_hint(unknown) -> str:
    """A note for an attribute name a release has since renamed."""
    return " ('total_size' is now 'size')" if "total_size" in unknown else ""


def _items(value, label: str, warnings: list[str]):
    """``value.items()`` when it is a dict, nothing (with a warning) otherwise."""
    if value is None:
        return []
    if not isinstance(value, dict):
        warnings.append(f"{label} must be a dictionary, not {type(value).__name__}")
        return []
    return list(value.items())


def _build_menu_entry(name, spec, registry, own: set) -> tuple[MenuEntry | None, str | None]:
    """Validate one ``MENU_ITEMS`` entry, or explain why it cannot be one.

    Where an item goes is a fact XeFM places, not a position the config
    picks: an action's items gather in a group of their own near the foot of
    each menu, in table order, so a menu XeFM later rearranges cannot leave a
    config pointing at a slot that moved."""
    if not isinstance(name, str) or not name:
        return None, f"MENU_ITEMS keys must be action names; ignored {name!r}"
    if not isinstance(spec, dict):
        return None, (f"MENU_ITEMS['{name}'] must be a dict with 'menus' and "
                      f"'label', not {type(spec).__name__}")
    if name not in own and registry.resolve(_actions.FILER, name) is None:
        return None, (f"MENU_ITEMS['{name}'] names no action — define it in "
                      f"ACTIONS, or name a built-in one")
    unknown = sorted(set(spec) - set(TABLE_KEYS["MENU_ITEMS"]))
    if unknown:
        return None, (f"MENU_ITEMS['{name}'] has unknown keys "
                      f"{', '.join(unknown)} — known: "
                      f"{', '.join(sorted(TABLE_KEYS['MENU_ITEMS']))}")
    menus = spec.get("menus")
    if isinstance(menus, str):
        menus = [menus]
    if not isinstance(menus, (list, tuple)) or not menus \
            or not all(m in MENUS for m in menus):
        return None, (f"MENU_ITEMS['{name}'] needs 'menus', a list of "
                      f"{', '.join(MENUS)}")
    label = spec.get("label")
    if not isinstance(label, str) or not label.strip():
        return None, f"MENU_ITEMS['{name}'] needs a 'label', the text the menu shows"
    when = spec.get("when", "always")
    if when not in MENU_WHEN:
        return None, (f"MENU_ITEMS['{name}'] has 'when' {when!r} — known: "
                      f"{', '.join(MENU_WHEN)}")
    return MenuEntry(name, label.strip(), tuple(dict.fromkeys(menus)), when), None


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


def _build_image_decoder(name, spec) -> tuple[dict | None, str | None]:
    """Validate one ``IMAGE_DECODERS`` entry, or explain why it cannot be one.

    The key is a file suffix, normalized the way :mod:`xefm.image_decoders`
    normalizes every suffix it is asked about, so ``'heic'``, ``'.heic'`` and
    ``'.HEIC'`` are one entry and a config need not know which spelling is meant.
    There is no ``override`` here: registering a decoder for a format XeFM
    already reads *is* the statement that yours should be used — that is the only
    way to replace Pillow's reading of one — so asking a second time would be
    asking about the thing the entry says.
    """
    if not isinstance(name, str) or not name.strip():
        return None, f"IMAGE_DECODERS keys must be file suffixes; ignored {name!r}"
    suffix = _image_decoders.normalize(name)
    if len(suffix) < 2 or not suffix[1:].replace(".", "").isalnum():
        return None, (f"IMAGE_DECODERS['{name}'] is not a file suffix — it must "
                      f"read like '.heic', letters and digits after the dot")
    if callable(spec):
        spec = {"open": spec}
    if not isinstance(spec, dict):
        return None, (f"IMAGE_DECODERS['{name}'] must be a function or a dict "
                      f"with an 'open' key, not {type(spec).__name__}")
    func = spec.get("open")
    if not callable(func):
        return None, f"IMAGE_DECODERS['{name}'] has no callable 'open'"
    return {"suffix": suffix, "open": func,
            "label": (str(spec["label"]) if spec.get("label") else None)}, None


def _check_lexer(pattern, spec, table_aliases: set[str] | None) -> str | None:
    """Why one ``LEXERS`` entry cannot be used, or ``None``.

    The key is a file-name pattern as Pygments writes them in a lexer's
    ``filenames`` (``'*.dcl'``, ``'Jenkinsfile'``), or a bare suffix (``'.dcl'``)
    as the other tables take. The value is a Pygments lexer class or the alias of
    one. ``table_aliases`` is set when validating without loading, standing in
    for the classes the same table would have registered first. There is no
    ``override``: naming a pattern Pygments already claims is the way to color it
    differently."""
    if not isinstance(pattern, str) or not pattern.strip():
        return f"LEXERS keys must be file-name patterns like '*.dcl'; ignored {pattern!r}"
    if table_aliases is not None and isinstance(spec, str) \
            and spec.strip().lower() in table_aliases:
        return None
    try:
        _lexers.resolve(spec)
    except ValueError as e:
        return f"LEXERS['{pattern}'] was ignored: {e}"
    return None


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
    problem = _call_problem(func, 1, "fn(ctx)")
    if problem:
        return None, f"ACTIONS['{name}']: {problem} — an action takes ctx alone"
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
    # The action is described the way any Python function is: by its
    # docstring, whose summary line is the one-liner the help dialog and the
    # command palette show, and whose body is the palette's help page. A
    # 'description' entry is read the same way and replaces the docstring
    # whole — for a function that cannot carry one, such as a lambda.
    text = spec.get("description")
    if text is None:
        text = inspect.getdoc(func) or ""
    summary, details = _split_description(str(text))
    return _actions.Action(
        name=name,
        context=context,
        description=summary or f"User action '{name}'",
        default_keys=(),
        func=func,
        source="user",
        details=details,
    ), None


def _split_description(text: str) -> tuple[str, str]:
    """``(summary, details)`` from a description, split the PEP 257 way: the
    first paragraph is the summary — joined onto one line, in case it was
    wrapped — and everything after the first blank line is the details. Used
    alike for a docstring and for an ``ACTIONS`` entry's 'description'."""
    summary, _, details = inspect.cleandoc(text).partition("\n\n")
    return " ".join(summary.split()), details.strip()


def _build_path_scheme(name, spec) -> tuple[type | None, str | None]:
    """Validate one ``PATH_SCHEMES`` entry, or explain why it cannot be one.

    The failures worth catching here are the ones that would otherwise show up
    as something else entirely: an abstract class raises ``TypeError`` from
    whichever pane first tries to list it, and a class whose ``SCHEME``
    disagrees with the key it is registered under builds paths under a prefix
    the registry does not answer to — so its own ``parent`` leaves the folder.
    """
    problem = _path_schemes.validate_scheme(name)
    if problem:
        return None, f"PATH_SCHEMES keys must be schemes: {problem}"

    override = _override_requested(spec)
    if isinstance(spec, dict):
        spec = spec.get("class")

    if not isinstance(spec, type) or not issubclass(spec, PathImpl):
        return None, (f"PATH_SCHEMES['{name}'] must be a PathImpl subclass, or "
                      f"a dict with a 'class' key, not {type(spec).__name__} — "
                      f"see xefm.path_base.ReadOnlyPathImpl")

    missing = sorted(getattr(spec, "__abstractmethods__", ()))
    if missing:
        return None, (f"PATH_SCHEMES['{name}'] cannot be used: "
                      f"{spec.__name__} does not implement "
                      f"{', '.join(missing)}")

    if name in _path_schemes.schemes() and not override:
        return None, (f"PATH_SCHEMES['{name}'] would replace the built-in "
                      f"'{name}://' backend and was ignored — pass "
                      f"{{'class': ..., 'override': True}} if that is intended")

    declared = getattr(spec, "SCHEME", "")
    if declared and declared != name:
        return None, (f"PATH_SCHEMES['{name}'] is {spec.__name__}, whose SCHEME "
                      f"is '{declared}' — a class registered under one scheme "
                      f"cannot build paths under another")
    if not declared:
        # The key already said it. Filling it in beats asking for the same
        # word twice, and a class left with the empty default reports its
        # scheme as '' — which file operations read as "same storage as
        # everything else that forgot".
        if "get_scheme" not in vars(spec):
            spec.SCHEME = name

    return spec, None


def preview_notice(*, hooks: int = 0, image_decoders: int = 0,
                   lexers: int = 0, menu_items: int = 0,
                   scheme_overrides: int = 0, attributes: int = 0,
                   layouts: int = 0, extras: int = 0) -> str | None:
    """The one line a config gets in the log pane when it uses a Preview
    table, or ``None`` when it uses none. ``ACTIONS``, ``SORT_KEYS``,
    ``FILTERS`` and ``PATH_SCHEMES`` (short of replacing a built-in scheme)
    are stable and take no part: a config that keeps to them has nothing to be
    told."""
    parts = [f"{count} {label}" for count, label in (
        (hooks, "event hook(s)"),
        (image_decoders, "image decoder(s)"),
        (lexers, "lexer(s)"),
        (menu_items, "menu item(s)"),
        (attributes, "attribute(s)"),
        (layouts, "layout(s)"),
        (extras, "extra(s)"),
        (scheme_overrides, "built-in scheme override(s)")) if count]
    if not parts:
        return None
    return (f"Customization API {API_VERSION}: {', '.join(parts)} loaded from "
            f"Preview tables — these may change in any release.")


#: The names of the APIs that are Preview — free to change in any release —
#: such as ``xefm.user_api.ActionContext.run_task``, ``config.MENU_ITEMS`` or
#: ``manifest.contributes.menus``. A class's entry covers its members. Each
#: Preview function, method and class also opens its docstring saying so. Set
#: last, so every ``@preview`` in this module is in it; ``xefm.path_base``,
#: imported at the top, has registered its own by then.
PREVIEW_APIS = frozenset(_PREVIEW_APIS)

#: The deprecated APIs, mapped to what to use instead — still working, and
#: removed no earlier than the next minor release, with an ``API_VERSION``
#: bump. Read-only; set last for the same reason as :data:`PREVIEW_APIS`.
DEPRECATED_APIS = MappingProxyType(dict(_DEPRECATED_APIS))
