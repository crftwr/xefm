"""xefm.file_operations — shared copy / move / delete engine for the PuiKit port.

Both the main view (:class:`xefm.app.XeFMApp`) and the directory diff viewer run their
file operations through one :class:`FileOperationService`, so the confirmation
policy (``CONFIRM_*``), conflict resolution, threading, and progress are written
once. The service is view-agnostic: it takes a list of ``Path`` targets + a
destination directory and reports a summary through ``on_complete``.

An operation runs as a single **linear** :class:`~xefm.task.Task` worker (no state
machine): it counts recursively, resolves each conflict by *asking the main
thread* through the task's blocking UI bridge, then copies/moves/deletes
file-by-file with byte-level progress — all off the UI thread, driving a
:class:`~xefm.progress_manager.ProgressManager` that the modal
:class:`~xefm.task.ProgressDialog` reads each frame. The initial ``CONFIRM_*``
prompt stays a plain main-thread message box before the task starts.

Two accelerations sit under that linear surface (issue #248, see
``doc/dev/PARALLEL_COPY_IMPLEMENTATION.md``): a same-volume local copy is
attempted as one macOS ``clonefile`` syscall before falling back to streaming,
and a multi-file copy/move fans individual files out to a small worker pool
(``_run_parallel``) while the task thread keeps walking directories. The
resolve/confirm phase stays strictly single-threaded; workers only touch the
task's cancel flag, its (locked) progress manager, and their own target's
error list.

Pass ``background=False`` (tests) to run the operation inline and resolve
conflicts headlessly (skip existing) — deterministic, no dialog, no thread.
"""

from __future__ import annotations

import ctypes
import errno
import math
import os
import re
import shutil
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, move_focus
from puikit.widgets import Button, Checkbox, MarkdownView, show_message_box
from puikit.widgets.base import Widget

from xefm import tags
from xefm.archive import (ArchiveInUseError, get_archive_cache,
                          get_member_archive_path, release_archives_under)
from xefm.dialog_geometry import (OPEN_MS_VIEWER, animate_open, draw_title_bar,
                                  title_content_top)
from xefm.diff_viewer import show_diff_viewer
from xefm.path import Path, concurrency, copy_to, move_to, readonly_lifted
from xefm.progress_manager import OperationType, ProgressManager
from xefm.str_format import format_size, format_timestamp
from xefm.task import Cancelled, Task, TaskManager
from xefm.tree_walk import parallel_reads
from xefm import trash as trash_mod

#: Operation kind -> (verb label, progress-manager op type).
_VERB = {"copy": "Copy", "move": "Move", "delete": "Delete", "duplicate": "Duplicate",
         "trash": "Trash"}
def _home_short(path) -> str:
    """``path`` as the jobs list shows it: under the home directory as ``~``."""
    text = str(path)
    home = os.path.expanduser("~")
    if text == home or text.startswith(home + os.sep):
        return "~" + text[len(home):]
    return text


def describe_operation(kind: str, targets: list, dest_dir: Optional[Path]) -> str:
    """What an operation works on, in one line for the jobs list (#599):
    ``report.pdf  ~/Downloads → ~/Documents``, ``12 items in ~/tmp``."""
    if not targets:
        return ""
    what = targets[0].name if len(targets) == 1 else f"{len(targets)} items"
    source = _home_short(targets[0].parent)
    if dest_dir is not None and kind in ("copy", "move"):
        return f"{what}  {source} → {_home_short(dest_dir)}"
    return f"{what} in {source}"


_OP_TYPE = {
    "copy": OperationType.COPY,
    "move": OperationType.MOVE,
    "delete": OperationType.DELETE,
    "duplicate": OperationType.COPY,
    "trash": OperationType.DELETE,
}

#: Copy in 1 MiB chunks; files at least this large are chunk-copied so the byte
#: bar advances and cancellation can interrupt mid-file (smaller files copy in one
#: shot — instant, no byte bar).
_CHUNK = 1024 * 1024
_BYTE_BAR_MIN = 1024 * 1024

#: macOS ``clonefile(2)``: a same-volume APFS copy is one copy-on-write
#: syscall — instant regardless of size, sharing data blocks until either side
#: is modified (exactly what Finder's Duplicate does). Resolved lazily:
#: ``None`` = not looked up yet, ``False`` = unavailable (non-macOS, or libc
#: without the symbol).
_clonefile = None if sys.platform == "darwin" else False
_clonefile_lock = threading.Lock()


def _clonefile_fn():
    """The libc ``clonefile`` function, or ``None`` where it doesn't exist."""
    global _clonefile
    if _clonefile is None:
        with _clonefile_lock:
            if _clonefile is None:
                try:
                    libc = ctypes.CDLL(None, use_errno=True)
                    fn = libc.clonefile
                    fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
                    fn.restype = ctypes.c_int
                    _clonefile = fn
                except (OSError, AttributeError):
                    _clonefile = False
    return _clonefile or None


def _clone_file(src: Path, dest: Path, overwrite: bool) -> bool:
    """Try to copy ``src`` to ``dest`` as an APFS clone; return True when the
    clone landed. False means "use the byte path" — cross-volume, a non-cloning
    filesystem (exFAT, NFS), or not macOS — and is never an error: the caller's
    ordinary copy handles those exactly as before.

    The device check up front keeps a cross-volume copy from ever attempting
    (and failing) the syscall, and doubles as the seam tests already fake to
    simulate a second filesystem. ``copystat`` afterwards makes the cloned
    file's metadata bit-identical to what the streaming path produces."""
    fn = _clonefile_fn()
    if fn is None:
        return False
    src_dev = _entry_device(src)
    if src_dev is None or src_dev != _entry_device(dest.parent):
        return False
    src_b, dest_b = os.fsencode(str(src)), os.fsencode(str(dest))
    rc = fn(src_b, dest_b, 0)
    if rc != 0 and overwrite and ctypes.get_errno() == errno.EEXIST:
        # clonefile never replaces; drop the old file and try once more. If the
        # retry still fails, the streaming fallback recreates dest anyway.
        try:
            dest.unlink()
        except Exception:  # noqa: BLE001 — undeletable dest: let the copy path report it
            return False
        rc = fn(src_b, dest_b, 0)
    if rc != 0:
        return False
    try:
        shutil.copystat(str(src), str(dest))
    except OSError:
        pass  # the clone itself carries the data; stat parity is best-effort
    return True


def _pin_source_archives(targets: list, label: str) -> list:
    """Pin the archive behind each target that is an entry inside one, under
    ``label``; return the functions that let go."""
    archives = {}
    for target in targets:
        archive = get_member_archive_path(target)
        if archive is not None:
            archives.setdefault(str(archive), archive)
    cache = get_archive_cache() if archives else None
    return [cache.pin(archive, label) for archive in archives.values()]


def recursive_delete(entry: Path) -> None:
    """Delete a file or directory (recursing into directories) through the
    storage-agnostic Path API."""
    if entry.is_dir() and not entry.is_symlink():
        for child in entry.iterdir():
            recursive_delete(child)
        entry.rmdir()
    else:
        entry.unlink()


def _unique_dest(dest_dir: Path, name: str, *, is_dir: bool = False) -> Path:
    """First free ``dest_dir/name`` variant for a "keep both" resolution: insert
    ` (N)` before the **last** extension for a file (``foo (1).txt``,
    ``photo.2020 (1).jpg``), or append it for a directory / extension-less name
    (``foo (1)``), incrementing ``N`` until free.

    The split is on the last dot (``os.path.splitext``), so only the real
    extension moves — a filename with dots in its stem (``… 5.36.02 PM.png``)
    keeps them and gets ``… 5.36.02 PM (1).png``. Directories always append (a
    dotted directory name is not an extension)."""
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    if is_dir:
        stem, ext_suffix = name, ""
    else:
        # Last-extension split. splitext ignores a leading dot, so a dotfile like
        # ".bashrc" -> (".bashrc", "") and appends cleanly instead of moving.
        stem, ext_suffix = os.path.splitext(name)
    n = 1
    while True:
        candidate = dest_dir / f"{stem} ({n}){ext_suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _code(text: str) -> str:
    """Wrap ``text`` as CommonMark inline code so a filename / path with Markdown
    specials (``_ * [ ] `` …) renders literally as a code span. The fence is a run
    of backticks longer than any inside ``text``, with a pad space when the content
    itself begins or ends with a backtick (the CommonMark rule)."""
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    if not text or text.startswith("`") or text.endswith("`"):
        return f"{fence} {text} {fence}"
    return f"{fence}{text}{fence}"


def _item_list_md(targets: list, limit: int = 6) -> list:
    """Markdown bullet lines naming the targets (as code spans), capped with an
    "…and N more" tail — the shared item preview for the confirm dialogs."""
    lines = [f"- {_code(t.name)}" for t in targets[:limit]]
    if len(targets) > limit:
        lines.append(f"- …and {len(targets) - limit} more")
    return lines


class FileOperationService:
    """Runs copy / move / delete for any view. Construct once per owner (bound to
    its ``config`` and a :class:`~xefm.task.TaskManager`); each call takes the
    ``panel`` to draw on and a ``z`` so a full-window modal (the diff viewer) can
    stack its dialogs above itself."""

    def __init__(self, config: Any, tasks: Optional[TaskManager] = None,
                 monitor: Any = None):
        self.config = config
        #: Central task registry — shared with the app when passed, else private.
        self.tasks = tasks if tasks is not None else TaskManager()
        #: Optional FileMonitorManager (duck-typed: ``suppress_path`` /
        #: ``release_path``). When set, each operation silences the filesystem
        #: watchers on the directories it mutates for its duration — the
        #: caller's ``on_complete`` refresh reconciles the panes (issue #243).
        #: The app attaches this after construction (its monitor is built
        #: later); the diff viewer passes it here.
        self.monitor = monitor
        #: One large file closed at a time — where the destination transfers a
        #: file at its close, that is the only concurrency worth refusing.
        self.close_gate = CloseGate()
        #: Source tags read ahead for each running copy, by task id (#763).
        self._tag_ahead: dict[int, tags.CarryAhead] = {}
        #: Each running operation's conflict answers, by task id (#887): the
        #: plan and the writes share them, so "Apply to all" given once
        #: covers both.
        self._answers_of: dict[int, _Answers] = {}

    # --- public API ----------------------------------------------------------

    def copy(self, panel: Any, targets: list, dest_dir: Path, *,
             on_complete: Optional[Callable[[dict], None]] = None,
             log: Optional[Callable[[str], None]] = None,
             z: int = 70, background: bool = True,
             on_declined: Optional[Callable[[], None]] = None) -> None:
        """Copy ``targets`` into ``dest_dir`` (each becomes ``dest_dir/name``),
        confirming per ``CONFIRM_COPY`` then resolving conflicts per file.
        ``on_declined`` is called instead of ``on_complete`` when the user
        cancels at the confirmation, before anything ran."""
        self._start(panel, "copy", targets, dest_dir, on_complete, log, z, background,
                    on_declined=on_declined)

    def move(self, panel: Any, targets: list, dest_dir: Path, *,
             on_complete: Optional[Callable[[dict], None]] = None,
             log: Optional[Callable[[str], None]] = None,
             z: int = 70, background: bool = True,
             on_declined: Optional[Callable[[], None]] = None) -> None:
        """Move ``targets`` into ``dest_dir``, confirming per ``CONFIRM_MOVE``;
        ``on_declined`` as for :meth:`copy`."""
        self._start(panel, "move", targets, dest_dir, on_complete, log, z, background,
                    on_declined=on_declined)

    def duplicate(self, panel: Any, targets: list, dest_dir: Path, *,
                  on_complete: Optional[Callable[[dict], None]] = None,
                  log: Optional[Callable[[str], None]] = None,
                  z: int = 70, background: bool = True) -> None:
        """Duplicate ``targets`` in place inside ``dest_dir`` (the source's own
        directory), auto-renaming each with the shared ` (N)` scheme — no conflict
        prompt, since an in-place copy always collides. Honors ``CONFIRM_DUPLICATE``."""
        self._start(panel, "duplicate", targets, dest_dir, on_complete, log, z, background)

    def delete(self, panel: Any, targets: list, *,
               on_complete: Optional[Callable[[dict], None]] = None,
               log: Optional[Callable[[str], None]] = None,
               z: int = 70, background: bool = True,
               note: Optional[str] = None,
               on_declined: Optional[Callable[[], None]] = None) -> None:
        """Delete ``targets`` (directories recursively), confirming per
        ``CONFIRM_DELETE`` (whose confirm button defaults to Cancel). ``note``
        is a line for the confirmation — why this is not going to the trash;
        ``on_declined`` as for :meth:`copy`."""
        self._start(panel, "delete", targets, None, on_complete, log, z, background,
                    note=note, on_declined=on_declined)

    def goes_to_trash(self, path) -> bool:
        """Whether deleting ``path`` sends it to the system's trash: there is
        one there, and ``DELETE_TO_TRASH`` is not turned off. A sync's
        deletions and the directory diff's ``K`` ask this per item (#603)."""
        return (getattr(self.config, "DELETE_TO_TRASH", True)
                and trash_mod.available(path))

    def trash(self, panel: Any, targets: list, *,
              on_complete: Optional[Callable[[dict], None]] = None,
              log: Optional[Callable[[str], None]] = None,
              z: int = 70, background: bool = True,
              on_declined: Optional[Callable[[], None]] = None) -> None:
        """Send ``targets`` to the system's trash (:mod:`xefm.trash`), each as
        one move — a directory goes whole — confirming per ``CONFIRM_TRASH``.
        The caller checks :func:`xefm.trash.available` first. ``on_declined``
        as for :meth:`copy`."""
        self._start(panel, "trash", targets, None, on_complete, log, z, background,
                    on_declined=on_declined)

    def sync(self, panel: Any, copies: list, deletes: list, *,
             on_complete: Optional[Callable[[dict], None]] = None,
             log: Optional[Callable[[str], None]] = None,
             z: int = 70, background: bool = True) -> None:
        """Run a directory sync plan (:mod:`xefm.dir_sync`) as one task: every
        ``(source, destination, overwrite)`` in ``copies``, then every path in
        ``deletes``.

        Unlike :meth:`copy`, each copy names its own destination — a plan
        writes into many directories at once — and nothing is confirmed or
        asked: the caller showed the whole plan and the user agreed to it, so
        an existing destination is overwritten exactly when the plan says.
        Copies come first, so a Mirror that is cancelled part-way has added
        before it has removed. The result has the usual ``done`` / ``failed``
        / ``errors`` / ``items`` counts, over copies and deletions together."""
        if not copies and not deletes:
            if log is not None:
                log("Nothing to sync")
            return
        task = Task("Sync…", config=self.config, kind="sync")
        task.detail = (f"{len(copies)} cop{'y' if len(copies) == 1 else 'ies'}, "
                       f"{len(deletes)} deletion{'' if len(deletes) == 1 else 's'}")
        task.progress.start_operation(OperationType.COPY, 0, description="")
        sources = [src for src, _dest, _ow in copies]
        unpins = _pin_source_archives(sources, "used by a running sync")

        def run(task: Task) -> dict:
            # A conflict found while writing stacks above the caller (#887).
            self._answers(task, z)
            try:
                return self._run_sync(task, copies, deletes, log)
            finally:
                for unpin in unpins:
                    unpin()

        self.tasks.submit(task, panel, run=run, on_done=on_complete, z=z,
                          background=background)

    def _run_sync(self, task: Task, copies: list, deletes: list, log) -> dict:
        """The task body of :meth:`sync`, on the task thread."""
        result = {"done": 0, "skipped": 0, "failed": 0, "cancelled": False,
                  "items": 0, "errors": []}
        prog = task.progress
        mutated: dict = {}
        if self.monitor:
            for path in [dest for _src, dest, _ow in copies] + list(deletes):
                parent = path.parent
                mutated.setdefault(str(parent), parent)
        for d in mutated.values():
            self.monitor.suppress_path(d)
        errors = result["errors"]
        try:
            steps = self._release_archives(
                "copy", [(src, dest, ow) for src, dest, ow in copies], result, log)
            steps = [("copy", src, dest, ow) for src, dest, ow in steps]
            self._tag_ahead[task.id] = ahead = tags.CarryAhead()
            ahead.read((src, dest) for _k, src, dest, _ow in steps)
            doomed = self._release_archives(
                "delete", [(p, None, False) for p in deletes], result, log)
            # To the trash wherever there is one (#603): a Mirror can delete a
            # great deal, and that is where being able to undo matters most.
            steps += [("trash" if self.goes_to_trash(p) else "delete", p, None, False)
                      for p, _d, _o in doomed]

            copy_items, copy_bytes = self._count(
                task, "copy", None, [s[1] for s in steps if s[0] == "copy"])
            del_items, _ = self._count(
                task, "delete", None, [s[1] for s in steps if s[0] == "delete"])
            # A trash is one move per target, a directory included.
            del_items += sum(1 for s in steps if s[0] == "trash")
            prog.update_operation_total(copy_items + del_items,
                                        total_bytes=copy_bytes)
            for kind, target, dest, overwrite in steps:
                task.checkpoint()
                before = len(errors)
                collide = _Collide.of(overwrite, dest)
                try:
                    ok = self._execute_one(
                        task, kind, target, dest, collide,
                        dest.parent if dest is not None else None,
                        prog, log, errors)
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 — record + go on
                    errors.append((str(target), str(exc)))
                    if log is not None:
                        log(f"Sync failed for {target.name}: {exc}")
                    ok = 0
                result["items"] += ok
                result[_outcome(ok, len(errors) > before, collide)] += 1
        except Cancelled:
            result["cancelled"] = True
        finally:
            self._tag_ahead.pop(task.id, None)
            self._answers_of.pop(task.id, None)
            for d in mutated.values():
                self.monitor.release_path(d)
            prog.finish_operation()
        return result

    # --- confirm + submit ----------------------------------------------------

    def _start(self, panel: Any, kind: str, targets: list, dest_dir: Optional[Path],
               on_complete, log, z: int, background: bool,
               note: Optional[str] = None,
               on_declined: Optional[Callable[[], None]] = None) -> None:
        """Show the initial ``CONFIRM_*`` prompt (main thread), then submit the
        operation as a linear task. The prompt is skipped when its config flag is
        off; conflicts are *not* mentioned here — they are detected and resolved
        inside the task."""
        if not targets:
            if log is not None:
                log(f"No file to {kind}")
            return
        verb = _VERB[kind]

        def go(detached: bool = False) -> None:
            self._submit(panel, kind, targets, dest_dir, on_complete, log, z,
                         background, detached=detached)

        confirm = getattr(self.config, f"CONFIRM_{verb.upper()}", True)
        if not confirm:
            go()
            return

        if kind == "delete":
            lines = [f"Delete **{len(targets)}** item(s)?", ""]
            lines += _item_list_md(targets)
            lines += ["", "**This cannot be undone.**"]
            if note:
                lines += ["", note]
            buttons, icon, default = ("Delete", "Cancel"), "warning", 1
        elif kind == "trash":
            # Recoverable, so the confirm button is the default.
            lines = [f"Move **{len(targets)}** item(s) to the {trash_mod.NAME}?", ""]
            lines += _item_list_md(targets)
            buttons, icon, default = (f"Move to {trash_mod.NAME}", "Cancel"), "question", 0
        elif kind == "duplicate":
            # In-place copy: the destination is the source's own directory, so name
            # it as "in <dir>" rather than the copy/move "to <dir>".
            lines = [f"Duplicate **{len(targets)}** item(s) in {_code(str(dest_dir))}?", ""]
            lines += _item_list_md(targets)
            buttons, icon, default = ("Duplicate", "Cancel"), "info", 0
        else:
            lines = [f"{verb} **{len(targets)}** item(s) to {_code(str(dest_dir))}?", ""]
            lines += _item_list_md(targets)
            buttons, icon, default = (verb, "Cancel"), "info", 0
        # "Background" starts the operation with no progress dialog, queued
        # behind any other background job (#567). Offered only where there is
        # a pump to run it on — tests run synchronously — and only for a copy,
        # a duplicate or a move (#828): a delete, to the trash or not, is
        # usually over at once, and the extra button only put Delete two steps
        # from its default, Cancel (#601).
        if background and kind in ("copy", "duplicate", "move"):
            buttons = (buttons[0], "Background", buttons[1])
            default = 2 if default == 1 else 0
        message = "\n".join(lines)
        ok_label = buttons[0]

        def on_result(label: str) -> None:
            if label == ok_label:
                go()
            elif label == "Background":
                go(detached=True)
                if log is not None:
                    log(f"{verb} {len(targets)} item(s) in the background")
            else:
                if on_declined is not None:
                    on_declined()
                panel.render()

        show_message_box(panel, message, title=verb, icon=icon, buttons=buttons,
                         default=default, cancel=len(buttons) - 1,
                         on_result=on_result, z=z, markdown=True)
        panel.render()

    def _submit(self, panel: Any, kind: str, targets: list, dest_dir: Optional[Path],
                on_complete, log, z: int, background: bool, *,
                detached: bool = False) -> None:
        task = Task(f"{_VERB[kind]}…", config=self.config, kind=kind)
        task.detail = describe_operation(kind, targets, dest_dir)
        task.progress.start_operation(_OP_TYPE[kind], 0, description="")
        # The archives this task reads out of are its own from the moment it is
        # submitted, so they stay open between its reads, and deleting one
        # meanwhile fails naming the task rather than with a sharing violation.
        unpins = _pin_source_archives(targets, f"used by a running {kind}")

        def run(task: Task) -> dict:
            try:
                return self._run(task, kind, targets, dest_dir, panel, log, z)
            finally:
                for unpin in unpins:
                    unpin()

        self.tasks.submit(task, panel, run=run, on_done=on_complete, z=z,
                          background=background, detached=detached)

    # --- the linear worker (runs on the task thread) -------------------------

    def _run(self, task: Task, kind: str, targets: list, dest_dir: Optional[Path],
             panel: Any, log, z: int) -> dict:
        """Prepare → resolve → execute, top to bottom. `Cancelled` from a checkpoint
        or a "Cancel" conflict choice unwinds here into a clean partial summary."""
        # ``done`` / ``skipped`` / ``failed`` count **top-level** targets (what the
        # user selected); ``items`` is the total individual entries actually
        # processed (recursive); ``errors`` collects (name, message) per failed
        # target so the caller can show them rather than bury them in the log.
        # ``targets`` holds one ``(target, dest, status, errors)`` per top-level
        # target whose outcome is known — ``status`` ``"done"`` / ``"skipped"`` /
        # ``"failed"``, ``errors`` its own ``(name, message)`` pairs — in the
        # order the targets were given. A target a cancel cut off has none.
        result = {"done": 0, "skipped": 0, "failed": 0, "cancelled": False,
                  "items": 0, "errors": [], "targets": []}
        if kind == "trash":
            # The targets that turned out to have no trash (online-only items
            # in cloud storage, #765) — also in ``errors``, which the caller
            # may take them out of when it offers a permanent delete instead.
            result["no_trash"] = []
        prog = task.progress
        mutated = self._mutated_dirs(kind, targets, dest_dir) if self.monitor else []
        for d in mutated:
            self.monitor.suppress_path(d)
        self._answers(task, z)
        try:
            # Resolve conflicts first (cheap existence checks; may prompt), so the
            # recursive count only covers what will actually be processed.
            if kind in ("delete", "trash"):
                plan = [(t, None, False) for t in targets]
            elif kind == "duplicate":
                # In-place copy always collides with itself — never prompt; pre-plan
                # every target to a fresh ` (N)` name. Distinct target names ⇒
                # distinct slots, so computing all up front is collision-free.
                # A name taken by the time it is written is chosen again then.
                plan = [(t, _unique_dest(dest_dir, t.name, is_dir=t.is_dir()),
                         KeepBoth()) for t in targets]
                result["created"] = [dest.name for _t, dest, _o in plan]
            else:
                skipped: list = []
                plan, result["skipped"] = self._resolve(task, targets, dest_dir, z,
                                                        panel, skipped_out=skipped)
                result["targets"] += [(t, dest_dir / t.name, "skipped", [])
                                      for t in skipped]
            plan = self._release_archives(kind, plan, result, log)
            if kind in ("copy", "duplicate", "move"):
                self._tag_ahead[task.id] = ahead = tags.CarryAhead()
                ahead.read((t, dest) for t, dest, _ow in plan
                           if not (_is_atomic_move(kind, t, dest_dir)
                                   and not _merges_into(t, dest)))

            if dest_dir is not None:
                try:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                except Exception:  # noqa: BLE001 — per-target op will surface it
                    pass

            total_items, total_bytes = self._count(task, kind, dest_dir,
                                                   [p[0] for p in plan],
                                                   [p[1] for p in plan])
            # Delete never reports bytes, so weighting its bar by them would
            # freeze it; copy/move/duplicate report every byte they touch.
            prog.update_operation_total(
                total_items, total_bytes=0 if kind in ("delete", "trash") else total_bytes)

            errors = result["errors"]
            workers = self._copy_workers(kind, plan, dest_dir)
            if workers > 1 and total_items > 1:
                self._run_parallel(task, kind, plan, dest_dir, prog, log,
                                   result, workers)
            else:
                for target, dest_base, overwrite in plan:
                    task.checkpoint()
                    before = len(errors)
                    collide = _Collide.of(overwrite, dest_base)
                    try:
                        ok = self._execute_one(task, kind, target, dest_base,
                                               collide, dest_dir, prog, log,
                                               errors, result.get("no_trash"))
                    except Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 — unexpected; record + go on
                        errors.append((str(target), str(exc)))
                        if log is not None:
                            log(f"{_VERB[kind]} failed for {target.name}: {exc}")
                        ok = 0
                    result["items"] += ok
                    status = _outcome(ok, len(errors) > before, collide)
                    result[status] += 1
                    result["targets"].append((target, collide.top, status,
                                              errors[before:]))
        except Cancelled:
            result["cancelled"] = True
        finally:
            order = {id(t): i for i, t in enumerate(targets)}
            result["targets"].sort(key=lambda r: order.get(id(r[0]), len(order)))
            if kind == "duplicate" and result["targets"]:
                # The names actually written: one taken since the plan moved on.
                result["created"] = [dest.name for _t, dest, status, _e
                                     in result["targets"] if status == "done"]
            self._tag_ahead.pop(task.id, None)
            self._answers_of.pop(task.id, None)
            for d in mutated:
                self.monitor.release_path(d)
            prog.finish_operation()
        return result

    @staticmethod
    def _release_archives(kind: str, plan: list, result: dict, log) -> list:
        """Close the archives XeFM holds open inside what ``plan`` will delete,
        move away or overwrite, and drop — as failed, with the reason — each
        target one is still in use under (issue #516). On Windows an open
        archive cannot be removed, and the OS error would not say why."""
        kept = []
        for target, dest_base, overwrite in plan:
            doomed = [target] if kind in ("delete", "move", "trash") else []
            if overwrite and dest_base is not None:
                doomed.append(dest_base)
            try:
                for path in doomed:
                    release_archives_under(path)
            except ArchiveInUseError as exc:
                result["errors"].append((str(target), str(exc)))
                result["failed"] += 1
                result.setdefault("targets", []).append(
                    (target, dest_base, "failed", [(str(target), str(exc))]))
                if log is not None:
                    log(f"{_VERB[kind]} failed for {target.name}: {exc}")
                continue
            kept.append((target, dest_base, overwrite))
        return kept

    def _mutated_dirs(self, kind: str, targets: list,
                      dest_dir: Optional[Path]) -> list:
        """The directories this operation writes into or removes entries from —
        the ones whose filesystem watchers its own writes would spam: the
        destination, plus each target's parent for the kinds that take the
        target out of it (move/delete). Deduped, order preserved. Copy reads
        its sources without mutating their directories, so only the destination
        is included; for duplicate the destination *is* the source directory."""
        dirs: dict = {}
        if dest_dir is not None:
            dirs.setdefault(str(dest_dir), dest_dir)
        if kind in ("move", "delete", "trash"):
            for target in targets:
                parent = target.parent
                dirs.setdefault(str(parent), parent)
        return list(dirs.values())

    def _resolve(self, task: Task, targets: list, dest_dir: Path, z: int,
                 panel: Any, skipped_out: Optional[list] = None) -> tuple[list, int]:
        """Detect top-level conflicts and resolve each, file-by-file, through the
        task's UI bridge. Returns ``(plan, skipped)`` where plan is a
        list of ``(target, dest_base, overwrite)`` for the survivors; the
        skipped targets themselves go to ``skipped_out`` when given.
        ``overwrite`` is a bool, an :class:`OverwriteOlder` for a folder
        merged under "overwrite older", whose files are decided one by one,
        or a :class:`KeepBoth` for a target written under a free name."""
        taken = _existing(task, [dest_dir / t.name for t in targets], dest_dir)
        total = sum(taken)
        plan: list = []
        skipped = 0
        # "Apply to all" is kept where the writes find it too (#887): a
        # conflict that turns up only then gets the same answer, unasked.
        answers = self._answers(task, z)
        idx = 0
        for t, exists in zip(targets, taken):
            dest = dest_dir / t.name
            if not exists:
                plan.append((t, dest, False))
                continue
            idx += 1
            action = answers.apply_all
            if action is None:
                summary = (_merge_summary(task, t, dest)
                           if _merges_into(t, dest) else None)
                action, apply = task.ask(
                    _conflict_prompt(t, dest, idx, total, z, summary),
                    headless=("skip", False))
                if apply:
                    answers.apply_all = action
            if action == "cancel":
                raise Cancelled()
            if action == "overwrite_older":
                if _merges_into(t, dest):
                    # A folder merge: decided file by file inside it.
                    plan.append((t, dest, OverwriteOlder()))
                    continue
                action = "overwrite" if _dest_is_older(t, dest) else "skip"
            if action == "skip":
                skipped += 1
                if skipped_out is not None:
                    skipped_out.append(t)
            elif action == "keep_both":
                plan.append((t, _unique_dest(dest_dir, t.name, is_dir=t.is_dir()),
                             KeepBoth()))
            else:  # overwrite
                plan.append((t, dest, True))
        return plan, skipped

    def _count(self, task: Task, kind: str, dest_dir: Optional[Path],
               targets: list, dests: Optional[list] = None) -> tuple[int, int]:
        """Recursively count the nodes (files + dirs) and total bytes to process,
        so the primary bar is determinate. A move that stays on one filesystem is
        one atomic rename, so it counts as a single node (its subtree is never
        walked); a move to another filesystem, or a directory merged into an
        existing one (``dests`` holds each target's destination), is walked like
        a copy."""
        items = 0
        bytes_ = 0
        if dests is None:
            dests = [None] * len(targets)
        for t, dest in zip(targets, dests):
            # A trash is one move per target, a directory included, so its
            # subtree is never walked — counting it would cost as much as the
            # delete it replaces and report nothing true.
            if kind == "trash" or (_is_atomic_move(kind, t, dest_dir)
                                   and not _merges_into(t, dest)):
                items += 1
                task.counted = items
                continue
            n, b = self._count_node(task, t, items)
            items += n
            bytes_ += b
            task.counted = items
        return items, bytes_

    def _count_node(self, task: Task, path: Path, base: int) -> tuple[int, int]:
        task.checkpoint()
        if path.is_dir() and not path.is_symlink():
            items, bytes_ = 1, 0
            for child in path.iterdir():
                n, b = self._count_node(task, child, base + items)
                items += n
                bytes_ += b
                task.counted = base + items
            return items, bytes_
        try:
            size = 0 if path.is_symlink() else path.stat().st_size
        except Exception:  # noqa: BLE001 — unreadable stat shouldn't abort counting
            size = 0
        return 1, size

    def _execute_one(self, task: Task, kind: str, target: Path,
                     dest_base: Optional[Path], overwrite: Any,
                     dest_dir: Optional[Path], prog: ProgressManager, log,
                     errors: list, no_trash: Optional[list] = None) -> int:
        """Process one top-level target, returning the count of individual entries
        that succeeded and appending ``(path, reason)`` to ``errors`` for any that
        failed. A single bad entry never aborts the rest of the target. A trash
        target that turned out to have no trash is also added to ``no_trash``.

        ``overwrite`` is the plan's answer for the target, or the
        :class:`_Collide` the caller made of it to read back afterwards whether
        the target was skipped after all and where it landed."""
        collide = _Collide.of(overwrite, dest_base)
        if kind == "delete":
            return self._delete_tree(task, target, prog, log, errors)
        if kind == "trash":
            prog.update_progress(target.name)
            try:
                trash_mod.send(target)
            except trash_mod.NoTrashError as exc:
                errors.append((str(target), exc.strerror or str(exc)))
                if no_trash is not None:
                    no_trash.append(target)
                return 0
            except OSError as exc:
                errors.append((str(target), exc.strerror or str(exc)))
                return 0
            if log is not None:
                log(f"Moved to {trash_mod.NAME}: {target}")
            return 1
        if (kind == "move" and _is_atomic_move(kind, target, dest_dir)
                and not _merges_into(target, dest_base)):
            prog.update_progress(target.name)
            try:
                moved = self._move_atomic(task, target, collide)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                errors.append((str(target), str(exc)))
                return 0
            if moved is None:
                _log_kept(log, collide, target)
                return 0
            _log_op(log, "Moved", target, moved)  # atomic: one line per target
            return 1
        # Copy, duplicate, or a move that crosses a filesystem / storage boundary
        # (copy the tree, then — move only — drop the source).
        verb = {"move": "Moved", "duplicate": "Duplicated"}.get(kind, "Copied")
        before = len(errors)
        ok = self._copy_tree(task, target, collide.top, collide, prog, log, verb,
                             errors)
        if (kind == "move" and ok > 0 and len(errors) == before
                and not collide.left_any):
            # Only remove the source once the whole tree copied cleanly — never
            # drop files a partial copy left behind, nor ones left in place
            # because the destination held them ("overwrite older" finding its
            # copy newer, or a Skip). Cleanup errors are ignored.
            self._delete_tree(task, target, None, None, [])
        return ok

    def _move_atomic(self, task: Task, target: Path,
                     collide: "_Collide") -> Optional[Path]:
        """Rename ``target`` to ``collide.top``; return where it landed, or
        None when it was left where it is. The rename refuses an existing
        destination unless overwriting, and a refusal the plan did not
        foresee is a conflict like any other (#887)."""
        dest = collide.top
        try:
            move_to(target, dest, overwrite=bool(collide))
            return dest
        except FileExistsError:
            if collide:
                raise
        settled = self._settle(task, target, dest, collide)
        if settled is None:
            return None
        dest, replace = settled
        move_to(target, dest, overwrite=replace)
        return dest

    # --- the parallel copy pool -----------------------------------------------

    def _copy_workers(self, kind: str, plan: list,
                      dest_dir: Optional[Path]) -> int:
        """How many pool workers this operation may use; 1 means the sequential
        path runs unchanged. Only copy-shaped work is parallel at all; the number
        itself is :func:`transfer_workers`' to decide, from what the storages at
        both ends declare."""
        if kind not in ("copy", "duplicate", "move"):
            return 1
        return transfer_workers(self.config, (t for t, _dest, _ow in plan),
                                dest_dir)

    def _run_parallel(self, task: Task, kind: str, plan: list,
                      dest_dir: Optional[Path], prog: ProgressManager, log,
                      result: dict, workers: int) -> None:
        """Execute the plan with a pool of file-copy workers.

        The task thread stays the *walker*: it renames atomic moves inline,
        creates directories in order (a child job must never race its parent's
        mkdir), and turns every file into one pool job. Copy and duplicate
        never wait between targets — files from the second folder stream while
        the first folder's stragglers finish. A cross-filesystem move of a
        directory drains that target's own jobs before dropping the source
        (never delete what didn't fully copy); a single-file move carries its
        source cleanup inside the job, so a many-file move still pipelines.

        Bookkeeping is per-target so the summary counts match the sequential
        path exactly: each target has its own error list and its jobs' futures,
        folded into ``result`` in plan order at the end — or, on cancel, only
        the jobs that actually finished."""
        verb = {"move": "Moved", "duplicate": "Duplicated"}.get(kind, "Copied")
        if log is not None:
            log = serialized_log(log)
        n = len(plan)
        collides = [_Collide.of(ow, dest) for _t, dest, ow in plan]
        sync_ok = [0] * n          # dirs + atomic renames, tallied by the walker
        per_async = [0] * n        # files, tallied from the jobs' futures
        per_errors: list[list] = [[] for _ in range(n)]
        futures: list[tuple[int, Future]] = []
        completed = False
        ex = ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix=f"xefm-{kind}")
        try:
            for i, (target, dest_base, _overwrite) in enumerate(plan):
                task.checkpoint()
                terr = per_errors[i]
                collide = collides[i]
                if (kind == "move" and _is_atomic_move(kind, target, dest_dir)
                        and not _merges_into(target, dest_base)):
                    prog.update_progress(target.name)
                    try:
                        moved = self._move_atomic(task, target, collide)
                    except Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        terr.append((str(target), str(exc)))
                        continue
                    if moved is None:
                        _log_kept(log, collide, target)
                        continue
                    _log_op(log, "Moved", target, moved)
                    sync_ok[i] = 1
                    continue
                dir_target = target.is_dir() and not target.is_symlink()
                cleanup_src = kind == "move" and not dir_target

                def submit(src: Path, dest: Path, i=i, terr=terr,
                           collide=collide, cleanup=cleanup_src) -> None:
                    futures.append((i, ex.submit(
                        self._copy_file_job, task, src, dest, collide,
                        prog, log, verb, terr, cleanup)))

                try:
                    sync_ok[i] = self._copy_tree(task, target, collide.top,
                                                 collide, prog, log, verb,
                                                 terr, submit=submit)
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 — unexpected; record + go on
                    terr.append((str(target), str(exc)))
                    if log is not None:
                        log(f"{_VERB[kind]} failed for {target.name}: {exc}")
                if kind == "move" and dir_target:
                    # Wait for this target's own files (the pool keeps other
                    # targets' jobs running), then drop the source only if the
                    # whole tree copied cleanly. ``result()`` here only tallies
                    # locally — ``per_async`` is filled once, in the final drain.
                    # Waiting writes nothing: the task can pause meanwhile,
                    # its pool workers stopped at their checkpoints (#887).
                    with task.idle():
                        ok_async = sum(f.result() for j, f in futures if j == i)
                    if (sync_ok[i] + ok_async > 0 and not terr
                            and not collide.left_any):
                        self._delete_tree(task, target, None, None, [])
            with task.idle():
                for j, f in futures:
                    per_async[j] += f.result()  # re-raises a job's Cancelled
            completed = True
        finally:
            if not completed:
                for _j, f in futures:
                    f.cancel()  # drop the queue; running jobs see the cancel flag
            with task.idle():
                ex.shutdown(wait=True)
            if not completed:
                # Fold in what did land before the unwind, so the summary's
                # item count reflects the files actually copied.
                for j, f in futures:
                    if f.done() and not f.cancelled():
                        try:
                            per_async[j] += f.result()
                        except BaseException:  # noqa: BLE001 — job unwound with the cancel
                            pass
            for i in range(n):
                result["items"] += sync_ok[i] + per_async[i]
                result["errors"].extend(per_errors[i])
                if completed:
                    # Same rule as the sequential loop. Cancelled targets are
                    # not judged.
                    status = _outcome(sync_ok[i] + per_async[i],
                                      bool(per_errors[i]), collides[i])
                    result[status] += 1
                    result.setdefault("targets", []).append(
                        (plan[i][0], collides[i].top, status,
                         list(per_errors[i])))

    def _copy_file_job(self, task: Task, src: Path, dest: Path, overwrite: bool,
                       prog: ProgressManager, log, verb: str, errors: list,
                       cleanup_src: bool) -> int:
        """One pool worker's unit: copy a single already-resolved file with the
        same per-file error absorption as the sequential walk. Returns the
        entry count (1 copied, 0 skipped or failed). ``cleanup_src`` drops the
        source after a clean copy — a single-file cross-filesystem move, whose
        cleanup errors are ignored exactly as the sequential path ignores
        them.

        The worker counts as at work for this task from its checkpoint until
        the job returns, and not between jobs (#887)."""
        try:
            task.checkpoint()
            slot = prog.file_begin(src.name)
            try:
                written = self._copy_file(task, src, dest, overwrite, prog, slot)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 — one bad file, keep going
                errors.append((str(src), str(exc)))
                prog.file_end(slot)
                return 0
            prog.file_end(slot)
            if written is None:
                _log_kept(log, overwrite, src)
                return 0  # left in place: the destination holds that name
            _log_op(log, verb, src, written)
            if cleanup_src:
                try:
                    src.unlink()
                except Exception:  # noqa: BLE001
                    pass
            return 1
        finally:
            task.leave()

    # --- per-node IO ---------------------------------------------------------

    def _copy_tree(self, task: Task, src: Path, dest: Path, overwrite: bool,
                   prog: ProgressManager, log, verb: str, errors: list,
                   submit: Optional[Callable[[Path, Path], None]] = None) -> int:
        """Copy one node (recursing into directories); return the number of entries
        copied, collecting per-entry failures in ``errors`` and continuing.

        With ``submit`` (the parallel path), directories are still created here,
        synchronously — a child job must never race its parent's mkdir — but each
        *file* is handed to ``submit`` for a pool worker and is not counted in the
        return value; the pool tallies those as the jobs finish.

        ``overwrite`` is the target's :class:`_Collide` (a plan value is made
        into one). A top-level folder the plan did not expect to exist is a
        conflict, asked about before anything merges into it (#887)."""
        task.checkpoint()
        overwrite = _Collide.of(overwrite, dest)
        if src.is_dir() and not src.is_symlink():
            try:
                if (overwrite.is_top(dest) and overwrite.mode == "ask"
                        and dest.exists()):
                    settled = self._settle(task, src, dest, overwrite)
                    if settled is None:
                        _log_kept(log, overwrite, src)
                        return 0
                    dest = settled[0]
                dest.mkdir(parents=True, exist_ok=True)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 — can't copy into it; skip children
                errors.append((str(src), str(exc)))
                return 0
            prog.update_progress(src.name)  # counted once it exists, like files
            self._carry_tags(task, src, dest)  # a folder's tags, best-effort
            ok = 1  # the directory itself
            children = list(src.iterdir())
            ahead = self._tag_ahead.get(task.id)
            if ahead is not None:
                ahead.read((child, dest / child.name) for child in children)
            for child in children:
                ok += self._copy_tree(task, child, dest / child.name,
                                      overwrite, prog, log, verb, errors, submit)
            return ok
        if submit is not None:
            submit(src, dest)
            return 0  # counted by the pool when the job completes
        slot = prog.file_begin(src.name)
        try:
            written = self._copy_file(task, src, dest, overwrite, prog, slot)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad file, keep going
            errors.append((str(src), str(exc)))
            prog.file_end(slot)
            return 0
        prog.file_end(slot)
        if written is not None:
            _log_op(log, verb, src, written)  # one line per file, with the real dest
            return 1
        _log_kept(log, overwrite, src)
        return 0  # left in place: the destination holds that name

    def _copy_file(self, task: Task, src: Path, dest: Path, overwrite: Any,
                   prog: ProgressManager, slot: int) -> Optional[Path]:
        """Copy one file; return where it was written (``dest``, or a free
        ` (N)` name a "keep both" chose), or None when it was not, so the
        caller logs only real copies. ``slot`` is the file's progress slot
        (``ProgressManager.file_begin``); the size is published to it up front
        so ``file_end`` can credit the bytes of whatever path the copy then
        takes — stream, clone, one-shot, or skip.

        A destination that exists is settled here, as the file is written:
        overwritten when the plan said so, otherwise a conflict (#887)."""
        overwrite = _Collide.of(overwrite, dest)
        try:
            size = 0 if src.is_symlink() else src.stat().st_size
        except Exception:  # noqa: BLE001
            size = 0
        prog.file_bytes(slot, 0, size)
        exists = dest.exists()
        replace = False
        if exists:
            settled = self._settle(task, src, dest, overwrite)
            if settled is None:
                return None
            dest, replace = settled
            exists = replace
        overwrite = replace  # the storage layer takes a plain flag
        same = src.scheme == dest.scheme
        local = same and src.scheme == "file"
        # Overwriting a read-only file goes through, as in Explorer (#767)
        with readonly_lifted(dest) if exists else nullcontext():
            if local and not src.is_symlink() and _clone_file(src, dest, overwrite):
                prog.file_bytes(slot, size, size)  # one syscall, all bytes landed
                return dest  # a clone carries every xattr, tags included
            if not src.is_symlink() and (not same or size >= _BYTE_BAR_MIN):
                self._copy_bytes(task, src, dest, size, overwrite, local, prog, slot)
            else:
                copy_to(src, dest, overwrite=overwrite)
        # Neither path keeps tags everywhere: copystat copies xattrs on Linux
        # only, and nothing carries them across storages (#585).
        if not src.is_symlink():
            self._carry_tags(task, src, dest)
        return dest

    # --- conflicts found while writing (#887) --------------------------------

    def _answers(self, task: Task, z: int = 70) -> "_Answers":
        return self._answers_of.setdefault(task.id, _Answers(z))

    def _settle(self, task: Task, src: Path, dest: Path,
                collide: "_Collide") -> Optional[tuple[Path, bool]]:
        """Decide what to do about ``dest`` existing as ``src`` is written:
        ``(where to write, whether to replace what is there)``, or None to
        leave it and not write ``src``. Records on ``collide`` what was left —
        the top-level target itself (``skipped``) or something inside it
        (``kept``, which keeps a move from deleting its source).

        What the plan already settled is applied without asking: an overwrite,
        or "overwrite older" file by file. Otherwise the plan expected nothing
        there, so whatever is there arrived since: a conflict, asked about with
        the same dialog as at the start. The answer for a top-level folder sets
        how its contents merge."""
        top = collide.is_top(dest)
        src_dir = src.is_dir() and not src.is_symlink()
        merge = src_dir and dest.is_dir()

        def leave() -> None:
            if top:
                collide.skipped = True
            else:
                collide.kept = True

        if collide.mode == "overwrite":
            return dest, True
        if collide.mode == "older":
            if merge or _dest_is_older(src, dest):
                return dest, True
            leave()
            return None
        if top and collide.keep_both:
            # The free name the plan chose has been taken since: choose again.
            dest = _unique_dest(dest.parent, src.name, is_dir=src_dir)
            collide.top = dest
            return dest, False
        action = self._ask_write(task, src, dest, merge)
        if action is None:
            return dest, False  # gone again by the time it was answered
        if action == "cancel":
            raise Cancelled()
        if action == "skip":
            leave()
            return None
        if action == "keep_both":
            dest = _unique_dest(dest.parent, src.name, is_dir=src_dir)
            if top:
                collide.top = dest
            return dest, False
        if action == "overwrite_older":
            if merge:
                collide.mode = "older"
                return dest, True
            if _dest_is_older(src, dest):
                return dest, True
            leave()
            return None
        if merge:  # overwrite: merge the folder, replacing what collides
            collide.mode = "overwrite"
        return dest, True

    def _ask_write(self, task: Task, src: Path, dest: Path,
                   merge: bool) -> Optional[str]:
        """The answer to a conflict found while writing: an "Apply to all"
        already given, or the conflict dialog's. None when ``dest`` is gone
        by the time it is answered — a job's prompt can wait while another
        operation runs — so the file is simply written.

        Pool workers ask one at a time, and one whose turn comes looks first
        for an "Apply to all" given meanwhile. Waiting for the turn writes
        nothing, so it does not keep the task from pausing."""
        answers = self._answers(task)
        with task.idle():
            answers.lock.acquire()
        try:
            if not dest.exists():
                return None
            action = answers.apply_all
            if action is None:
                summary = _merge_summary(task, src, dest) if merge else None
                # No "i of N": how many more there will be is not known yet.
                action, apply = task.ask(
                    _conflict_prompt(src, dest, 0, 0, answers.z, summary),
                    headless=("skip", False))
                if apply:
                    answers.apply_all = action
                if action != "cancel" and not dest.exists():
                    return None
            return action
        finally:
            answers.lock.release()

    def _carry_tags(self, task: Task, src: Path, dest: Path) -> None:
        """Give ``dest`` the tags of ``src``, from what this task read ahead
        when it has (#763)."""
        ahead = self._tag_ahead.get(task.id)
        if ahead is not None:
            ahead.carry(src, dest)
        else:
            tags.carry(src, dest)

    @staticmethod
    def _remote_progress(task: Task, prog: ProgressManager, slot: int):
        """Byte-progress callback for a remote transfer, doubling as the cancel
        checkpoint.

        A local copy checkpoints between chunks in its own loop; a remote one is
        a single call into S3 or SFTP, so the progress callback is the only
        thread of control that comes back often enough to notice a cancel. The
        ``Cancelled`` raised here unwinds the transfer and is re-raised
        unchanged by :func:`xefm.path.copy_to`. ``slot`` is the file's progress slot, so
        parallel transfers each drive their own row."""
        def report(bytes_copied: int, bytes_total: int) -> None:
            # Never a pause here: a remote stream held for as long as another
            # background job runs can time out (#599).
            task.checkpoint(pausable=False)
            prog.file_bytes(slot, bytes_copied, bytes_total)
        return report

    def _copy_bytes(self, task: Task, src: Path, dest: Path, size: int,
                    overwrite: bool, local: bool, prog: ProgressManager,
                    slot: int) -> None:
        """Copy a large / cross-storage file while driving its byte slot. Local
        files are streamed in chunks here (so ``shutil`` doesn't hide progress);
        cross-storage copies delegate to :func:`xefm.path.copy_to`'s own progress callback."""
        if not local:
            try:
                copy_to(src, dest, overwrite=overwrite,
                        progress_callback=self._remote_progress(task, prog, slot))
            except Cancelled:
                try:
                    dest.unlink()  # a half-sent remote file is not a copy
                except Exception:  # noqa: BLE001
                    pass
                raise
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        copied = 0
        try:
            with open(str(src), "rb") as fi:
                # The destination is closed explicitly, and a big one under the
                # gate: on a mounted volume that defers a file's transfer to its
                # close, this loop only fills a local cache and the close below
                # is the whole of the copy.
                out = open(str(dest), "wb")
                closed = False
                try:
                    while True:
                        # Between files only: the destination may stream to a
                        # remote on close, and a suspended task pauses whole.
                        task.checkpoint(pausable=False)
                        chunk = fi.read(_CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        copied += len(chunk)
                        prog.file_bytes(slot, copied, size)
                    with self.close_gate.closing():
                        out.close()
                    closed = True
                finally:
                    if not closed:
                        # Cancelled or failed: this file is about to be removed,
                        # so it does not queue behind anyone else's transfer.
                        out.close()
            shutil.copystat(str(src), str(dest))
        except Cancelled:
            try:
                dest.unlink()  # drop the partial file so a cancel leaves no stub
            except Exception:  # noqa: BLE001
                pass
            raise

    def _delete_tree(self, task: Task, path: Path,
                     prog: Optional[ProgressManager], log,
                     errors: list) -> int:
        """Delete one node (recursing, children first); return entries removed,
        collecting per-entry failures in ``errors`` and continuing. A directory
        whose children didn't all delete will fail its own ``rmdir`` (recorded)."""
        task.checkpoint()
        if path.is_dir() and not path.is_symlink():
            ok = 0
            for child in list(path.iterdir()):
                ok += self._delete_tree(task, child, prog, log, errors)
            try:
                if prog is not None:
                    prog.update_progress(path.name)
                path.rmdir()
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                errors.append((str(path), str(exc)))
                return ok
            _log_del(log, path)
            return ok + 1
        try:
            if prog is not None:
                prog.update_progress(path.name)
            path.unlink()
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append((str(path), str(exc)))
            return 0
        _log_del(log, path)
        return 1


def format_op_summary(verb: str, result: dict) -> str:
    """One-line status for a finished file op. ``done`` / ``skipped`` / ``failed``
    count the **top-level** selected items (``failed`` = a target that produced
    nothing); when a target expands to more than that (directories) the total
    entries processed is shown too — so "11 done" for 11 folders of many files
    isn't read as 11 files — along with the count of individual files that failed
    (bad files are skipped, not fatal to their folder)."""
    done = result["done"]
    skipped = result.get("skipped", 0)
    failed = result.get("failed", 0)
    items = result.get("items", 0)
    n_err = len(result.get("errors") or [])
    top = done + skipped + failed
    parts = [f"{done} done"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if failed:
        parts.append(f"{failed} failed")
    summary = f"{verb}: {', '.join(parts)}"
    extra = []
    if items > top:  # nested — the counts above are top-level
        extra.append(f"{top} top-level items")
        extra.append(f"{items} items total")
    if n_err > failed:  # per-file failures beyond any wholesale target failures
        extra.append(f"{n_err} file{'s' if n_err != 1 else ''} failed")
    if extra:
        summary += f" ({', '.join(extra)})"
    if result.get("cancelled"):
        summary += " — cancelled"
    return summary


def format_op_errors(verb: str, result: dict, limit: int = 12) -> Optional[str]:
    """Markdown body naming the items that failed (and why) for a message box, or
    ``None`` when nothing failed — so a failure in a large batch is shown, not
    buried among the per-file log lines."""
    errors = result.get("errors") or []
    if not errors:
        return None
    shown = errors[:limit]
    lines = [f"**{verb}** failed for {len(errors)} item(s):", ""]
    lines += [f"- {_code(name)} — {msg}" for name, msg in shown]
    if len(errors) > len(shown):
        lines.append(f"- …and {len(errors) - len(shown)} more")
    return "\n".join(lines)


def _log_op(log, verb: str, src: Path, dest: Path) -> None:
    """Log one copy/move compactly: the file name once, then the source and
    destination *directories* (the name is not repeated in each full path). When
    the name changed — a "keep both" / rename resolution — show both names so the
    ` (N)` result is visible."""
    if log is None:
        return
    if src.name == dest.name:
        log(f"{verb} '{dest.name}': {src.parent} → {dest.parent}")
    else:
        log(f"{verb} '{src.name}' → '{dest.name}': {src.parent} → {dest.parent}")


def _log_kept(log, overwrite: Any, src: Path) -> None:
    """Log an entry not written because the destination holds its name —
    "overwrite older" finding the destination's copy as new, or a Skip — so
    a move that leaves part of its source behind says why."""
    if log is None:
        return
    older = (isinstance(overwrite, OverwriteOlder)
             or (isinstance(overwrite, _Collide) and overwrite.mode == "older"))
    if older:
        log(f"Kept '{src.name}': the destination's copy is not older")
    else:
        log(f"Skipped '{src.name}': it exists at the destination")


def _log_del(log, path: Path) -> None:
    """Log one delete compactly: the name once, then its directory."""
    if log is not None:
        log(f"Deleted '{path.name}': {path.parent}")


class CloseGate:
    """Lets one file be closed at a time, whoever is writing it.

    Where a destination holds a file in a local cache until it is closed — a
    WebDAV or SMB volume, NFS under close-to-open — that close *is* the
    transfer. Two at once move no more data than one, because a single stream
    already saturates the link: 12.2 MiB/s measured alone against 11.8 aggregate
    across four workers. And one WebDAV server stopped answering while two large
    uploads were in flight, and did not recover on a remount.

    Serialising every close, not merely the large ones, costs about 8%: the same
    file set went 11.89s with one closer thread against 10.98s with closes
    overlapping. The overlap that pays is not between two closes — it is between
    one file's close and the *next* file's open and write, and that is untouched
    by this. 8% is a small price for not having to decide, per file and per
    destination, which closes are safe to run together.

    Nothing here is specific to a network volume: a destination whose close is
    instant passes through an uncontended lock in microseconds. One gate per
    operation is enough, because the progress dialog is modal and XeFM runs one
    file operation at a time.

    Known limit: on a link fast enough that one stream does not saturate it,
    this gives up throughput that is really there. The measurements behind it
    come from a 12.2 MiB/s link. A knob to lift it belongs to whoever measures
    such a destination, not here in advance of one."""

    def __init__(self):
        self._lock = threading.Lock()

    @contextmanager
    def closing(self):
        """Hold the gate for the duration of one file's close."""
        with self._lock:
            yield


def transfer_workers(config: Any, sources: Iterable[Path],
                     dest: Optional[Path] = None) -> int:
    """How many files an operation reading ``sources`` and writing into
    ``dest`` may have in flight.

    Three lines, in order:

    1. What the storages declare (:func:`xefm.path.concurrency`): every
       source's read ceiling and the destination's write ceiling, the smallest
       of them. Each file in flight is a read at one end and a write at the
       other, so neither end is asked for more than it said it serves. When a
       source is the same storage as the destination, each file is both of
       those requests against it, and the files in flight are held to half
       its total. A storage that declares nothing serves one — guessing
       upwards is the guess that hurts — and caps the operation at one.
    2. ``TRANSFER_CONCURRENCY`` overrides the number from line 1, unless that
       was one: ``"none"`` for one, an integer of at least one for that many,
       ``"auto"`` (the default) for neither. Anything else is not a worker
       count and the declarations answer.
    3. No ``sources`` (an extraction, whose reader is serialised by its handler
       whatever this returns) is sized by the destination alone.

    This is the whole worker-count decision. Safety is not part of it — that is
    :class:`CloseGate`'s, unconditionally — which is why ``file`` can afford
    not to know whether a path is a local disk or a mounted volume.

    "Same storage" is the same scheme, which over-counts two SSH hosts or two
    buckets as one: the safe direction, since it only ever lowers the count."""
    reads = {}
    for src in sources:
        if src.scheme not in reads:
            reads[src.scheme] = concurrency(src).read
    ceilings = list(reads.values())
    if dest is not None:
        ends = concurrency(dest)
        ceilings.append(ends.write)
        if dest.scheme in reads:
            ceilings.append(max(1, ends.total // 2))
    declared = min(ceilings, default=1)
    if declared <= 1:
        return 1
    setting = getattr(config, "TRANSFER_CONCURRENCY", "auto")
    if setting == "none":
        return 1
    if setting != "auto":
        try:
            value = int(setting)
        except (TypeError, ValueError):
            value = 0
        if value >= 1:
            return value
        # 0, a negative, or something that is not a number at all: nothing a
        # worker count can mean, so the declarations answer instead.
    return declared


def serialized_log(log: Callable[[str], None]) -> Callable[[str], None]:
    """Wrap a log sink so parallel workers take turns. The app's sink appends
    to a LogView — a line list plus an incremental wrap cache — which copes
    with one background writer but was never built for several at once.

    Shared with archive extraction, whose workers write into the same sink for
    the same reason."""
    lock = threading.Lock()

    def write(message: str) -> None:
        with lock:
            log(message)
    return write


def _entry_device(path: Path) -> Optional[int]:
    """``st_dev`` of the filesystem holding ``path`` — the identity a rename has to
    match on both sides. ``None`` when ``path`` isn't local or can't be stat'ed, so
    the caller falls back to the storage-scheme test alone."""
    try:
        if path.scheme != "file":
            return None
        return path.stat().st_dev
    except Exception:  # noqa: BLE001 — unknown device just means "can't tell"
        return None


def _is_atomic_move(kind: str, target: Path, dest_dir: Optional[Path]) -> bool:
    """A move that stays within one *filesystem* is a single rename — no per-file
    walk, no byte bar.

    One storage backend is not enough: ``rename`` only works inside a single
    filesystem, so moving to another mount point (an external drive, a network
    share, another partition) is really a copy followed by a delete. Those get the
    tree walk, the per-file log lines and the byte bar, exactly as a cross-storage
    move does — the wait is just as long, so the progress has to be just as real.

    The devices compared are the ones that hold the directory *entries*: the
    source's parent, and the destination directory the new entry lands in."""
    if kind != "move" or dest_dir is None:
        return False
    if target.scheme != dest_dir.scheme:
        return False
    src_dev = _entry_device(target.parent)
    dest_dev = _entry_device(dest_dir)
    if src_dev is not None and dest_dev is not None:
        return src_dev == dest_dev
    return True


def _existing(task: Task, paths: list, where: Path) -> list:
    """``[p.exists() for p in paths]``, the checks run side by side on a
    remote storage that serves them (#540): a copy of many files into an SSH
    directory otherwise spent most of its time asking about each destination
    in turn, one round trip apiece, before sending anything. ``exists`` itself
    is asked, not a listing of ``where`` matched by name, because only the
    storage knows which names it treats as the same file (case, Unicode
    normalisation)."""
    workers = min(parallel_reads(where), len(paths))
    if workers <= 1:
        return [p.exists() for p in paths]
    task.checkpoint()
    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix="xefm-exists") as pool:
        return list(pool.map(lambda p: p.exists(), paths))


def _merges_into(target: Path, dest: Optional[Path]) -> bool:
    """An overwrite of a directory onto an existing directory is a merge: no
    rename can do it (Windows refuses any existing destination, POSIX a non-empty
    one), so the move copies the tree into it and then drops the source."""
    return (dest is not None and target.is_dir() and not target.is_symlink()
            and dest.is_dir())


# --- "overwrite older" -------------------------------------------------------

#: Modification times closer than this count as equal. FAT and exFAT store
#: them at 2-second resolution, and a copy to or from one routinely lands a
#: second or two off its original — which without slack would read as "older"
#: and be re-copied on every pass (rsync's ``--modify-window`` answers the same
#: thing).
_MTIME_SLACK = 2.0


def _mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except Exception:  # noqa: BLE001 — unreadable: no basis to compare on
        return None


def compare_mtimes(a: Optional[float], b: Optional[float]) -> int:
    """1 when ``a`` is clearly newer than ``b``, -1 when ``b`` is, 0 when they
    are within :data:`_MTIME_SLACK` of each other or either is unknown. The one
    rule behind "Overwrite older" and every "newer" mark XeFM shows, so what a
    dialog or viewer marks is what the action does."""
    if a is None or b is None:
        return 0
    if a - b > _MTIME_SLACK:
        return 1
    if b - a > _MTIME_SLACK:
        return -1
    return 0


def _dest_is_older(src: Path, dest: Path) -> bool:
    """True when ``dest`` was modified clearly before ``src`` — the case
    "overwrite older" replaces. Either time unreadable means no: the rule
    never overwrites on a guess."""
    return compare_mtimes(_mtime(src), _mtime(dest)) > 0


class OverwriteOlder:
    """The plan's ``overwrite`` value for a folder merged under "overwrite
    older": each colliding file inside is overwritten only when its
    destination is older. Truthy, so everything that treats ``overwrite`` as
    a flag sees a merge. The writes carry it as a :class:`_Collide` in mode
    ``"older"``, which records what was left in place."""

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return "OverwriteOlder()"


class KeepBoth:
    """The ``overwrite`` value of a target written under a free ` (N)` name —
    "keep both", or a duplicate. Falsy: nothing is overwritten. The name was
    free when the plan was made; one taken by the time it is written is
    chosen again then (#887)."""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "KeepBoth()"


class _Collide:
    """How one top-level target's writes treat what they find at the
    destination (#887), made from the plan's ``overwrite`` value and carried
    down the target's tree:

    - ``mode``: ``"overwrite"``, ``"older"`` (file by file), or ``"ask"`` —
      the plan expected nothing there, so what is there arrived since and is
      a conflict. Answering one for the top-level folder changes the mode
      for everything inside it.
    - ``top``: where the target itself is written — moved when a "keep both"
      picks a free name. ``keep_both``: that name may be chosen again.
    - ``kept``: something inside was left in place; ``skipped``: the target
      itself was. Either keeps a move from deleting its source. Plain
      assignments, so pool workers set them without a lock.

    Truthy unless asking, so code that treats ``overwrite`` as a flag still
    reads it as one."""

    __slots__ = ("mode", "top", "keep_both", "kept", "skipped")

    def __init__(self, mode: str, top: Optional[Path], keep_both: bool = False):
        self.mode = mode
        self.top = top
        self.keep_both = keep_both
        self.kept = False
        self.skipped = False

    @classmethod
    def of(cls, overwrite: Any, top: Optional[Path]) -> "_Collide":
        if isinstance(overwrite, _Collide):
            return overwrite
        if isinstance(overwrite, OverwriteOlder):
            return cls("older", top)
        if isinstance(overwrite, KeepBoth):
            return cls("ask", top, keep_both=True)
        return cls("overwrite" if overwrite else "ask", top)

    def __bool__(self) -> bool:
        return self.mode != "ask"

    def is_top(self, dest: Path) -> bool:
        return self.top is not None and str(dest) == str(self.top)

    @property
    def left_any(self) -> bool:
        return self.kept or self.skipped

    def __repr__(self) -> str:
        return (f"_Collide({self.mode!r}, top={self.top}, kept={self.kept}, "
                f"skipped={self.skipped})")


class _Answers:
    """One operation's conflict answers, shared by its plan and its writes
    (#887): the "Apply to all" answer, once given, and the lock that lets
    pool workers ask one at a time. ``z`` places the dialog."""

    def __init__(self, z: int) -> None:
        self.z = z
        self.apply_all: Optional[str] = None
        self.lock = threading.Lock()


def _outcome(ok: int, failed: bool, collide: _Collide) -> str:
    """A top-level target's status: ``"skipped"`` when it was left in place
    as it was written (#887), else ``"done"`` if any of its entries landed or
    nothing went wrong, and ``"failed"`` only if it produced nothing but
    errors (a single bad file, an uncreatable folder). Inner file failures
    stay in ``errors`` and do not sink the target."""
    if collide.skipped and ok == 0 and not failed:
        return "skipped"
    if ok > 0 or not failed:
        return "done"
    return "failed"


# --- conflict dialog ---------------------------------------------------------

#: (action id, button label, shortcut key) for the conflict dialog, in row
#: order. "compare" is the one that answers nothing: it opens the two files in
#: the diff viewer above the dialog, which is still there when that closes.
_CONFLICT_ACTIONS = (
    ("overwrite", "Overwrite", "o"),
    ("overwrite_older", "Overwrite older", "u"),
    ("skip", "Skip", "s"),
    ("keep_both", "Keep both", "k"),
    ("compare", "Compare", "d"),
    ("cancel", "Cancel", "c"),
)

#: The dialog's default action: the button focus starts on, so the one a bare
#: Enter presses. Skip is the safe resolution, matching the app's other
#: destructive confirms (Delete, archive overwrite), where focus starts on the
#: harmless choice rather than the one that destroys data. No button wears the
#: accent "primary" fill: Enter presses the focused button and focus always
#: rests on one, so the focus ring is the one cue for what Enter does — as in
#: PuiKit's MessageBox.
_DEFAULT_CONFLICT_ACTION = "skip"

#: Widest the dialog grows (it shrinks to the window): enough for the six
#: buttons in one row on a character grid.
_DIALOG_W = 84
#: Gap between the message and the checkbox row below it: one blank row, the
#: same on a grid and on a vector backend.
_MSG_GAP = 1.0
#: Gap between the checkbox row and the buttons on a vector backend, where
#: both are taller than a row and would otherwise touch. A grid keeps them on
#: adjacent rows, which already read apart.
_CHECKBOX_GAP = 0.5


class ConflictSide:
    """What the dialog shows of one side of a conflict: the path (for Compare),
    whether it is a folder, its size and its modification time (``None`` when
    unreadable). Gathered by :meth:`of` on the task thread, so a remote stat
    never runs on the UI thread."""

    def __init__(self, path: Any, is_dir: bool, size: Optional[int],
                 mtime: Optional[float]):
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.mtime = mtime

    @classmethod
    def of(cls, path: Path) -> "ConflictSide":
        try:
            is_dir = path.is_dir() and not path.is_symlink()
        except Exception:  # noqa: BLE001
            is_dir = False
        try:
            st = path.stat()
            size, mtime = (None if is_dir else st.st_size), st.st_mtime
        except Exception:  # noqa: BLE001 — shown as unknown
            size, mtime = None, None
        return cls(path, is_dir, size, mtime)


def _sides_markdown(source: ConflictSide, existing: ConflictSide) -> str:
    """A two-row table of both sides' size and modification time, the newer and
    the larger side each marked. Times closer than :data:`_MTIME_SLACK` are not
    called newer — the same rule "Overwrite older" decides by."""
    newer = {1: source, -1: existing}.get(compare_mtimes(source.mtime, existing.mtime))
    larger = None
    if source.size is not None and existing.size is not None \
            and source.size != existing.size:
        larger = source if source.size > existing.size else existing

    def row(label: str, side: ConflictSide) -> str:
        if side.is_dir:
            size = "folder"
        elif side.size is None:
            size = "?"
        else:
            size = format_size(side.size)
            if side is larger:
                size += " · **larger**"
        if side.mtime is None:
            when = "?"
        else:
            when = format_timestamp(side.mtime)
            if side is newer:
                when += " · **newer**"
        return f"| **{label}** | {size} | {when} |"

    return "\n".join(["| | Size | Modified |", "|---|--:|---|",
                      row("Source", source), row("Existing", existing)])


#: How many source files a folder conflict's summary counts before it stops —
#: a huge or remote tree would otherwise hold the prompt back for as long as
#: walking it takes.
_SUMMARY_LIMIT = 10_000


@dataclass
class MergeSummary:
    """What merging a source folder into an existing one would meet, counted
    file by file: ``older`` files exist at the destination and are older there
    (what "Overwrite older" replaces), ``not_older`` exist and are not,
    ``only_source`` do not exist there yet. ``capped`` when the count stopped
    at :data:`_SUMMARY_LIMIT`."""
    older: int = 0
    not_older: int = 0
    only_source: int = 0
    capped: bool = False


def _merge_summary(task: Task, src: Path, dest: Path,
                   limit: int = _SUMMARY_LIMIT) -> MergeSummary:
    """Walk ``src`` (symlinks are not followed, as the copy does not) and
    classify each file against its counterpart under ``dest`` with the rule
    "Overwrite older" applies. A subtree missing at the destination is counted
    without a stat per file. Runs on the task thread and stops on cancel."""
    summary = MergeSummary()
    counted = 0

    def walk(s: Path, d: Path, d_exists: bool) -> bool:
        nonlocal counted
        try:
            children = list(s.iterdir())
        except Exception:  # noqa: BLE001 — unreadable: the copy will report it
            return True
        for child in children:
            task.checkpoint()
            counterpart = d / child.name
            there = d_exists and counterpart.exists()
            if child.is_dir() and not child.is_symlink():
                if not walk(child, counterpart, there and counterpart.is_dir()):
                    return False
                continue
            if counted >= limit:
                summary.capped = True
                return False
            counted += 1
            if not there:
                summary.only_source += 1
            elif _dest_is_older(child, counterpart):
                summary.older += 1
            else:
                summary.not_older += 1
        return True

    walk(src, dest, True)
    return summary


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def _summary_markdown(summary: MergeSummary) -> str:
    """The folder conflict's body: what the merge meets, in the terms the
    choices act on — "Overwrite older" replaces exactly the ``older`` count."""
    both = summary.older + summary.not_older
    lines = []
    if both:
        lines.append(f"- **{_plural(both, 'file')}** in both: "
                     f"**{summary.older:,}** older at the destination, "
                     f"{summary.not_older:,} not")
    elif summary.capped:
        lines.append("- No file is in both among those counted")
    else:
        lines.append("- No file is in both — nothing would be overwritten")
    if summary.only_source:
        lines.append(f"- {_plural(summary.only_source, 'file')} only in the source")
    if summary.capped:
        lines.append(f"\n*Counted the first {_SUMMARY_LIMIT:,} files; the rest "
                     "were not checked.*")
    return "\n".join(lines)


def _conflict_prompt(target: Path, dest: Path, index: int, total: int, z: int,
                     summary: Optional[MergeSummary] = None):
    """Return a ``show_fn(panel, deliver)`` for ``Task.ask``: it pushes a
    :class:`ConflictDialog` whose result ``(action, apply_to_all)`` is handed to
    ``deliver``. Both sides are stat'ed here, on the task thread; the dialog
    stacks just above the progress dialog (``z + 5``). ``summary`` is a folder
    merge's count (:func:`_merge_summary`), shown in place of the two folders'
    own size and date, which say nothing about their contents."""
    source, existing = ConflictSide.of(target), ConflictSide.of(dest)

    def show(panel: Any, deliver: Callable[[Any], None]) -> None:
        dialog = ConflictDialog(target.name, index, total, on_result=deliver,
                                source=source, existing=existing, summary=summary)
        dialog.show(panel, z=z + 5)
        panel.render()
    return show


class ConflictDialog(FocusContainer, Widget):
    """Per-conflict resolution modal: names the colliding file (``i of N``),
    tabulates both sides' size and modification time, a row of actions
    (Overwrite / Overwrite older / Skip / Keep both / Compare / Cancel), and an
    "apply to all remaining" checkbox. Reports ``(action, apply_to_all)``
    through ``on_result``. Compare is offered only when both sides are files.
    Keyboard: ``o/u/s/k/d/c`` shortcuts (``=`` compares too, as in the main
    view), ``a``/Space toggles the checkbox, Tab and Left/Right move focus
    (Left/Right along the button row, as in a regular message box; Up/Down hop
    between the row and the checkbox), Enter activates the focused button, Esc
    cancels."""

    focusable = True
    focus_stop_when_empty = True

    def __init__(self, name: str, index: int, total: int,
                 on_result: Callable[[tuple[str, bool]], None], *,
                 source: Optional[ConflictSide] = None,
                 existing: Optional[ConflictSide] = None,
                 summary: Optional[MergeSummary] = None):
        self.name = name
        noun = "Folder" if summary is not None else "File"
        self.title = (f"{noun} exists ({index} of {total})" if total > 1
                      else f"{noun} exists")
        self.on_result = on_result
        self.source, self.existing = source, existing
        self._panel: Any = None
        self._z = 75
        self._size = (0.0, 0.0)
        # The filename renders as a Markdown `code` span so it stands out from the
        # prose (matching the confirm dialogs). Display-only — not a focus child.
        text = f"{_code(name)} already exists in the destination."
        if summary is not None:
            # Two folders' own times and sizes say nothing about the files the
            # merge decides on, so the body counts those instead.
            text += " The folders are merged.\n\n" + _summary_markdown(summary)
        elif source is not None and existing is not None:
            text += "\n\n" + _sides_markdown(source, existing)
        self._msg = MarkdownView(text)
        self._checkbox = Checkbox("Apply to all remaining", checked=False)
        comparable = (source is not None and existing is not None
                      and not source.is_dir and not existing.is_dir)
        #: The (action, label, key) rows this dialog offers.
        self._actions = [a for a in _CONFLICT_ACTIONS
                         if a[0] != "compare" or comparable]
        self._buttons = [
            Button(label, variant="secondary",
                   on_click=(lambda a=action: self._resolve(a)))
            for action, label, _key in self._actions
        ]
        default = next(i for i, (action, _l, _k) in enumerate(self._actions)
                       if action == _DEFAULT_CONFLICT_ACTION)
        self._focused: Any = self._buttons[default]
        #: The button focus returns to when Down leaves the checkbox row.
        self._last_button: Any = self._buttons[default]
        self._child_rects: list[tuple[Any, tuple[float, float, float, float]]] = []

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self._checkbox, *self._buttons]

    # --- lifecycle -----------------------------------------------------------

    def show(self, panel: Any, z: int = 75) -> None:
        self._panel = panel
        self._z = z
        sw, _sh = panel.backend.size_units
        w = float(max(48, min(_DIALOG_W, int(sw) - 4)))
        # Sized to what draw() lays out, bottom-up: border row, button rows,
        # checkbox row, the gap, the message as it wraps at this width (the
        # size/date table's height is the backend's, not a row count), title.
        lc = panel.layout_context()
        msg_h = self._msg.measure(lc, "y", w - 4).preferred
        h = (title_content_top(lc) + msg_h + _MSG_GAP + self._checkbox_h(lc)
             + self._buttons_h(lc, w - 4) + 1.0)
        if not lc.vector_shapes:
            h = float(math.ceil(h))  # whole rows on a grid
        panel.push_layer(self, z=z, hints={"shadow": True, "w": w, "h": h})
        animate_open(panel, self, OPEN_MS_VIEWER)

    def _compare(self) -> None:
        """Open both files in the diff viewer above this dialog. The dialog stays
        pushed beneath it, so closing the viewer lands back here, still waiting
        for an answer."""
        panel = self._panel
        if panel is None or self.source is None or self.existing is None:
            return
        show_diff_viewer(panel, self.source.path, self.existing.path, z=self._z + 5)
        panel.render()

    def _resolve(self, action: str) -> None:
        if action == "compare":
            self._compare()
            return
        apply_all = self._checkbox.checked
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()
        if self.on_result is not None:
            self.on_result((action, apply_all))

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme
        surface_bg = theme.popup_bg if theme is not None else None
        border = theme.popup_border if theme is not None else None
        box_style = Style(bg=surface_bg, fg=border)
        box_w, box_h = ctx.size_units
        ctx.draw_box(0, 0, box_w, box_h, box_style, hints={"fill": True})
        y = draw_title_bar(ctx, self.title, surface_bg=surface_bg, border=border, y=1.0)
        self._child_rects = []

        # Button rows along the bottom; the checkbox sits above them (a gap
        # apart on a vector backend), snapped to a whole row on a grid (a
        # Checkbox clips at a fractional y there). The message fills the space
        # between title and checkbox.
        lc = ctx.layout_context()
        bh = self._buttons[0].measure(lc, "y", 0.0).preferred
        rows = self._button_rows(lc, box_w - 4)
        # a full row of bottom padding (clear of the border)
        by = box_h - 1.0 - self._buttons_h(lc, box_w - 4)
        cb_h = self._checkbox.measure(lc, "y", 0.0).preferred
        cb_y = by - self._checkbox_h(lc)
        if not ctx.vector_shapes:
            cb_y = float(math.floor(cb_y))  # a whole grid row (it clips otherwise)

        # Markdown message (the filename as a `code` span), on the popup surface.
        self._msg.style = Style(bg=surface_bg)
        # Children draw on the popup surface: without the "bg" hint they inherit
        # the layer's own background, which a grid paints as the terminal's
        # default under the table borders and the checkbox label.
        ctx.draw_child(self._msg, 2, y, max(1.0, box_w - 4), max(1.0, cb_y - y - _MSG_GAP),
                       hints={"bg": surface_bg})

        ctx.draw_child(self._checkbox, 2, cb_y, box_w - 4, cb_h,
                       hints={"focused": self._focused is self._checkbox,
                              "bg": surface_bg})
        self._child_rects.append((self._checkbox, (2.0, box_w - 2.0, cb_y, cb_y + cb_h)))

        for row in rows:
            bx = 2.0
            for btn, bw in row:
                ctx.draw_child(btn, bx, by, bw, bh,
                               hints={"focused": self._focused is btn})
                self._child_rects.append((btn, (bx, bx + bw, by, by + bh)))
                bx += bw + 1.0
            by += bh + 1.0

    def _checkbox_h(self, lc: Any) -> float:
        """Height of the checkbox row, with its gap above the buttons."""
        cb_h = self._checkbox.measure(lc, "y", 0.0).preferred
        return cb_h + (_CHECKBOX_GAP if lc.vector_shapes else 0.0)

    def _buttons_h(self, lc: Any, avail: float) -> float:
        """Height of the button rows at ``avail`` wide, a row of gap between."""
        bh = self._buttons[0].measure(lc, "y", 0.0).preferred
        n = len(self._button_rows(lc, avail))
        return bh * n + (n - 1)

    def _button_rows(self, lc: Any, avail: float) -> list:
        """The buttons as ``[(button, width), …]`` rows, a row breaking where
        the next button would cross ``avail`` — six of them do not fit one row
        of a narrow window."""
        bh = self._buttons[0].measure(lc, "y", 0.0).preferred
        rows: list = [[]]
        x = 0.0
        for btn in self._buttons:
            bw = btn.measure(lc, "x", bh).preferred
            if rows[-1] and x + bw > avail:
                rows.append([])
                x = 0.0
            rows[-1].append((btn, bw))
            x += bw + 1.0
        return rows

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY:
            self._on_key(event)
            return True
        if event.type in (EventType.MOUSE_DOWN, EventType.MOUSE_UP,
                          EventType.MOUSE_CLICK):
            self._on_mouse(event)
            return True
        return True  # modal: swallow the rest

    def _on_key(self, event: Event) -> None:
        key = event.key
        char = (event.char or "").lower()
        if key == "escape":
            self._resolve("cancel")
        elif key == "tab":
            move_focus(self, -1 if "shift" in event.modifiers else 1, wrap=True)
            self._render()
        elif key in ("left", "right"):
            self._move_in_row(1 if key == "right" else -1)
            self._render()
        elif key in ("up", "down"):
            self._hop_row()
            self._render()
        elif key == "enter":
            if self._focused is self._checkbox:
                self._checkbox.toggle()
                self._render()
            else:
                self._focused.on_click()
        elif char == "a" or key == "space":
            self._checkbox.toggle()
            self._render()
        elif char == "=":
            self._resolve("compare")
        else:
            for action, _label, shortcut in self._actions:
                if char == shortcut:
                    self._resolve(action)
                    return

    def _move_in_row(self, step: int) -> None:
        """Left/Right walk the button row, wrapping at its ends — the traversal a
        regular message box gives its buttons. From the checkbox they step into
        the row from the matching edge (Right → first, Left → last)."""
        if self._focused is self._checkbox:
            self._focused = self._buttons[0 if step > 0 else -1]
        else:
            i = self._buttons.index(self._focused)
            self._focused = self._buttons[(i + step) % len(self._buttons)]
        self._last_button = self._focused

    def _hop_row(self) -> None:
        """Up/Down move between the two rows the dialog actually has — the button
        row and the checkbox above it — returning to the button that last held
        focus, so a round trip does not lose your place."""
        if self._focused is self._checkbox:
            self._focused = self._last_button
        else:
            self._last_button = self._focused
            self._focused = self._checkbox

    def _on_mouse(self, event: Event) -> None:
        if event.x is None:
            return
        if event.type is EventType.MOUSE_CLICK:
            for widget, (x0, x1, y0, y1) in self._child_rects:
                if x0 <= event.x < x1 and y0 <= event.y < y1:
                    if widget is self._checkbox:
                        self._checkbox.toggle()
                        self._render()
                    else:
                        widget.on_click()
                    return

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()
