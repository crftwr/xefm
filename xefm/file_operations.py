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
import os
import re
import shutil
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

from puikit.backend import Style
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, move_focus
from puikit.widgets import Button, Checkbox, MarkdownView, show_message_box
from puikit.widgets.base import Widget

from xefm.dialog_geometry import OPEN_MS_VIEWER, animate_open, draw_title_bar
from xefm.path import Path
from xefm.progress_manager import OperationType, ProgressManager
from xefm.task import Cancelled, Task, TaskManager

#: Operation kind -> (verb label, progress-manager op type).
_VERB = {"copy": "Copy", "move": "Move", "delete": "Delete", "duplicate": "Duplicate"}
_OP_TYPE = {
    "copy": OperationType.COPY,
    "move": OperationType.MOVE,
    "delete": OperationType.DELETE,
    "duplicate": OperationType.COPY,
}

#: Copy in 1 MiB chunks; files at least this large are chunk-copied so the byte
#: bar advances and cancellation can interrupt mid-file (smaller files copy in one
#: shot — instant, no byte bar).
_CHUNK = 1024 * 1024
_BYTE_BAR_MIN = 1024 * 1024

#: Copy-worker pool sizes by storage latency class — the fallbacks behind
#: ``config.FILE_OP_WORKERS_LOCAL`` / ``FILE_OP_WORKERS_S3``. Local disk
#: saturates fast — measured ~1.3–1.9× at 2–4 workers on APFS SSD, and *worse*
#: beyond that (GIL + filesystem metadata serialization). S3 is per-object
#: round-trip latency, so more concurrency keeps paying. ssh stays at 1:
#: transfers share one control-master connection per host whose progress state
#: is per-connection, not per-transfer.
_WORKERS_LOCAL = 4
_WORKERS_REMOTE = 8

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

    # --- public API ----------------------------------------------------------

    def copy(self, panel: Any, targets: list, dest_dir: Path, *,
             on_complete: Optional[Callable[[dict], None]] = None,
             log: Optional[Callable[[str], None]] = None,
             z: int = 70, background: bool = True) -> None:
        """Copy ``targets`` into ``dest_dir`` (each becomes ``dest_dir/name``),
        confirming per ``CONFIRM_COPY`` then resolving conflicts per file."""
        self._start(panel, "copy", targets, dest_dir, on_complete, log, z, background)

    def move(self, panel: Any, targets: list, dest_dir: Path, *,
             on_complete: Optional[Callable[[dict], None]] = None,
             log: Optional[Callable[[str], None]] = None,
             z: int = 70, background: bool = True) -> None:
        """Move ``targets`` into ``dest_dir``, confirming per ``CONFIRM_MOVE``."""
        self._start(panel, "move", targets, dest_dir, on_complete, log, z, background)

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
               z: int = 70, background: bool = True) -> None:
        """Delete ``targets`` (directories recursively), confirming per
        ``CONFIRM_DELETE`` (whose confirm button defaults to Cancel)."""
        self._start(panel, "delete", targets, None, on_complete, log, z, background)

    # --- confirm + submit ----------------------------------------------------

    def _start(self, panel: Any, kind: str, targets: list, dest_dir: Optional[Path],
               on_complete, log, z: int, background: bool) -> None:
        """Show the initial ``CONFIRM_*`` prompt (main thread), then submit the
        operation as a linear task. The prompt is skipped when its config flag is
        off; conflicts are *not* mentioned here — they are detected and resolved
        inside the task."""
        if not targets:
            if log is not None:
                log(f"No file to {kind}")
            return
        verb = _VERB[kind]

        def go() -> None:
            self._submit(panel, kind, targets, dest_dir, on_complete, log, z, background)

        confirm = getattr(self.config, f"CONFIRM_{verb.upper()}", True)
        if not confirm:
            go()
            return

        if kind == "delete":
            lines = [f"Delete **{len(targets)}** item(s)?", ""]
            lines += _item_list_md(targets)
            lines += ["", "**This cannot be undone.**"]
            buttons, icon, default = ("Delete", "Cancel"), "warning", 1
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
        message = "\n".join(lines)
        ok_label = buttons[0]

        def on_result(label: str) -> None:
            if label == ok_label:
                go()
            else:
                panel.render()

        show_message_box(panel, message, title=verb, icon=icon, buttons=buttons,
                         default=default, cancel=1, on_result=on_result, z=z, markdown=True)
        panel.render()

    def _submit(self, panel: Any, kind: str, targets: list, dest_dir: Optional[Path],
                on_complete, log, z: int, background: bool) -> None:
        task = Task(f"{_VERB[kind]}…", config=self.config, kind=kind)
        task.progress.start_operation(_OP_TYPE[kind], 0, description="")

        def run(task: Task) -> dict:
            return self._run(task, kind, targets, dest_dir, panel, log, z)

        self.tasks.submit(task, panel, run=run, on_done=on_complete, z=z,
                          background=background)

    # --- the linear worker (runs on the task thread) -------------------------

    def _run(self, task: Task, kind: str, targets: list, dest_dir: Optional[Path],
             panel: Any, log, z: int) -> dict:
        """Prepare → resolve → execute, top to bottom. `Cancelled` from a checkpoint
        or a "Cancel" conflict choice unwinds here into a clean partial summary."""
        # ``done`` / ``skipped`` / ``failed`` count **top-level** targets (what the
        # user selected); ``items`` is the total individual entries actually
        # processed (recursive); ``errors`` collects (name, message) per failed
        # target so the caller can show them rather than bury them in the log.
        result = {"done": 0, "skipped": 0, "failed": 0, "cancelled": False,
                  "items": 0, "errors": []}
        prog = task.progress
        mutated = self._mutated_dirs(kind, targets, dest_dir) if self.monitor else []
        for d in mutated:
            self.monitor.suppress_path(d)
        try:
            # Resolve conflicts first (cheap existence checks; may prompt), so the
            # recursive count only covers what will actually be processed.
            if kind == "delete":
                plan = [(t, None, False) for t in targets]
            elif kind == "duplicate":
                # In-place copy always collides with itself — never prompt; pre-plan
                # every target to a fresh ` (N)` name. Distinct target names ⇒
                # distinct slots, so computing all up front is collision-free.
                plan = [(t, _unique_dest(dest_dir, t.name, is_dir=t.is_dir()), False)
                        for t in targets]
                result["created"] = [dest.name for _t, dest, _o in plan]
            else:
                plan, result["skipped"] = self._resolve(task, targets, dest_dir, z, panel)

            if dest_dir is not None:
                try:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                except Exception:  # noqa: BLE001 — per-target op will surface it
                    pass

            total_items, total_bytes = self._count(task, kind, dest_dir,
                                                   [p[0] for p in plan])
            # Delete never reports bytes, so weighting its bar by them would
            # freeze it; copy/move/duplicate report every byte they touch.
            prog.update_operation_total(
                total_items, total_bytes=0 if kind == "delete" else total_bytes)

            errors = result["errors"]
            workers = self._copy_workers(kind, plan, dest_dir)
            if workers > 1 and total_items > 1:
                self._run_parallel(task, kind, plan, dest_dir, prog, log,
                                   result, workers)
            else:
                for target, dest_base, overwrite in plan:
                    task.checkpoint()
                    before = len(errors)
                    try:
                        ok = self._execute_one(task, kind, target, dest_base,
                                               overwrite, dest_dir, prog, log,
                                               errors)
                    except Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 — unexpected; record + go on
                        errors.append((str(target), str(exc)))
                        if log is not None:
                            log(f"{_VERB[kind]} failed for {target.name}: {exc}")
                        ok = 0
                    result["items"] += ok
                    # A top-level target "done" if any of its entries succeeded;
                    # "failed" only if it produced nothing and did raise (a single
                    # bad file / an uncreatable dir). Inner file failures stay in
                    # ``errors`` and don't sink the target.
                    if ok > 0 or len(errors) == before:
                        result["done"] += 1
                    else:
                        result["failed"] += 1
        except Cancelled:
            result["cancelled"] = True
        finally:
            for d in mutated:
                self.monitor.release_path(d)
            prog.finish_operation()
        return result

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
        if kind in ("move", "delete"):
            for target in targets:
                parent = target.parent
                dirs.setdefault(str(parent), parent)
        return list(dirs.values())

    def _resolve(self, task: Task, targets: list, dest_dir: Path, z: int,
                 panel: Any) -> tuple[list, int]:
        """Detect top-level conflicts and resolve each, file-by-file, through the
        task's UI bridge. Returns ``(plan, skipped)`` where plan is a
        list of ``(target, dest_base, overwrite)`` for the survivors."""
        conflicts = [t for t in targets if (dest_dir / t.name).exists()]
        total = len(conflicts)
        plan: list = []
        skipped = 0
        apply_all: Optional[str] = None
        idx = 0
        for t in targets:
            dest = dest_dir / t.name
            if not dest.exists():
                plan.append((t, dest, False))
                continue
            idx += 1
            action = apply_all
            if action is None:
                action, apply = task.ask(
                    _conflict_prompt(t.name, idx, total, z),
                    headless=("skip", False))
                if apply:
                    apply_all = action
            if action == "cancel":
                raise Cancelled()
            if action == "skip":
                skipped += 1
            elif action == "keep_both":
                plan.append((t, _unique_dest(dest_dir, t.name, is_dir=t.is_dir()), False))
            else:  # overwrite
                plan.append((t, dest, True))
        return plan, skipped

    def _count(self, task: Task, kind: str, dest_dir: Optional[Path],
               targets: list) -> tuple[int, int]:
        """Recursively count the nodes (files + dirs) and total bytes to process,
        so the primary bar is determinate. A move that stays on one filesystem is
        one atomic rename, so it counts as a single node (its subtree is never
        walked); a move to another filesystem is walked like a copy."""
        items = 0
        bytes_ = 0
        for t in targets:
            if _is_atomic_move(kind, t, dest_dir):
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
                     dest_base: Optional[Path], overwrite: bool,
                     dest_dir: Optional[Path], prog: ProgressManager, log,
                     errors: list) -> int:
        """Process one top-level target, returning the count of individual entries
        that succeeded and appending ``(path, reason)`` to ``errors`` for any that
        failed. A single bad entry never aborts the rest of the target."""
        if kind == "delete":
            return self._delete_tree(task, target, prog, log, errors)
        if kind == "move" and _is_atomic_move(kind, target, dest_dir):
            prog.update_progress(target.name)
            try:
                target.move_to(dest_base, overwrite=overwrite)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                errors.append((str(target), str(exc)))
                return 0
            _log_op(log, "Moved", target, dest_base)  # atomic: one line per target
            return 1
        # Copy, duplicate, or a move that crosses a filesystem / storage boundary
        # (copy the tree, then — move only — drop the source).
        verb = {"move": "Moved", "duplicate": "Duplicated"}.get(kind, "Copied")
        before = len(errors)
        ok = self._copy_tree(task, target, dest_base, overwrite, prog, log, verb, errors)
        if kind == "move" and ok > 0 and len(errors) == before:
            # Only remove the source once the whole tree copied cleanly — never
            # drop files a partial copy left behind. Cleanup errors are ignored.
            self._delete_tree(task, target, None, None, [])
        return ok

    # --- the parallel copy pool -----------------------------------------------

    def _copy_workers(self, kind: str, plan: list,
                      dest_dir: Optional[Path]) -> int:
        """How many pool workers this operation may use; 1 means the sequential
        path runs unchanged. Local↔local gets a small pool
        (``config.FILE_OP_WORKERS_LOCAL``), S3 a larger one
        (``config.FILE_OP_WORKERS_S3`` — per-object round-trip latency
        dominates there, and boto3 clients are thread-safe). Anything else
        stays sequential regardless of the knobs: ssh transfers share one
        control-master connection per host whose progress state is
        per-connection, not per-transfer, and archive/unknown schemes make no
        thread-safety promises."""
        if kind not in ("copy", "duplicate", "move"):
            return 1
        schemes = {t.get_scheme() for t, _dest, _ow in plan}
        if dest_dir is not None:
            schemes.add(dest_dir.get_scheme())
        if not schemes <= {"file", "s3"}:
            return 1
        if "s3" in schemes:
            workers = getattr(self.config, "FILE_OP_WORKERS_S3", _WORKERS_REMOTE)
            fallback = _WORKERS_REMOTE
        else:
            workers = getattr(self.config, "FILE_OP_WORKERS_LOCAL", _WORKERS_LOCAL)
            fallback = _WORKERS_LOCAL
        try:
            workers = int(workers)
        except (TypeError, ValueError):
            workers = fallback
        return workers if workers >= 1 else fallback

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
            log = _serialized_log(log)
        n = len(plan)
        sync_ok = [0] * n          # dirs + atomic renames, tallied by the walker
        per_async = [0] * n        # files, tallied from the jobs' futures
        per_errors: list[list] = [[] for _ in range(n)]
        futures: list[tuple[int, Future]] = []
        completed = False
        ex = ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix=f"xefm-{kind}")
        try:
            for i, (target, dest_base, overwrite) in enumerate(plan):
                task.checkpoint()
                terr = per_errors[i]
                if kind == "move" and _is_atomic_move(kind, target, dest_dir):
                    prog.update_progress(target.name)
                    try:
                        target.move_to(dest_base, overwrite=overwrite)
                    except Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        terr.append((str(target), str(exc)))
                        continue
                    _log_op(log, "Moved", target, dest_base)
                    sync_ok[i] = 1
                    continue
                dir_target = target.is_dir() and not target.is_symlink()
                cleanup_src = kind == "move" and not dir_target

                def submit(src: Path, dest: Path, i=i, terr=terr,
                           overwrite=overwrite, cleanup=cleanup_src) -> None:
                    futures.append((i, ex.submit(
                        self._copy_file_job, task, src, dest, overwrite,
                        prog, log, verb, terr, cleanup)))

                try:
                    sync_ok[i] = self._copy_tree(task, target, dest_base,
                                                 overwrite, prog, log, verb,
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
                    ok_async = sum(f.result() for j, f in futures if j == i)
                    if sync_ok[i] + ok_async > 0 and not terr:
                        self._delete_tree(task, target, None, None, [])
            for j, f in futures:
                per_async[j] += f.result()  # re-raises a job's Cancelled
            completed = True
        finally:
            if not completed:
                for _j, f in futures:
                    f.cancel()  # drop the queue; running jobs see the cancel flag
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
                    # Same rule as the sequential loop: done if anything landed
                    # or nothing went wrong; failed only when a target produced
                    # nothing but errors. Cancelled targets are not judged.
                    if sync_ok[i] + per_async[i] > 0 or not per_errors[i]:
                        result["done"] += 1
                    else:
                        result["failed"] += 1

    def _copy_file_job(self, task: Task, src: Path, dest: Path, overwrite: bool,
                       prog: ProgressManager, log, verb: str, errors: list,
                       cleanup_src: bool) -> int:
        """One pool worker's unit: copy a single already-resolved file with the
        same per-file error absorption as the sequential walk. Returns the
        entry count (1 copied, 0 skipped or failed). ``cleanup_src`` drops the
        source after a clean copy — a single-file cross-filesystem move, whose
        cleanup errors are ignored exactly as the sequential path ignores
        them."""
        task.checkpoint()
        slot = prog.file_begin(src.name)
        try:
            copied = self._copy_file(task, src, dest, overwrite, prog, slot)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad file, keep going
            errors.append((str(src), str(exc)))
            prog.file_end(slot)
            return 0
        prog.file_end(slot)
        if not copied:
            return 0  # skipped (inner collision under a non-overwrite dir)
        _log_op(log, verb, src, dest)
        if cleanup_src:
            try:
                src.unlink()
            except Exception:  # noqa: BLE001
                pass
        return 1

    # --- per-node IO ---------------------------------------------------------

    def _copy_tree(self, task: Task, src: Path, dest: Path, overwrite: bool,
                   prog: ProgressManager, log, verb: str, errors: list,
                   submit: Optional[Callable[[Path, Path], None]] = None) -> int:
        """Copy one node (recursing into directories); return the number of entries
        copied, collecting per-entry failures in ``errors`` and continuing.

        With ``submit`` (the parallel path), directories are still created here,
        synchronously — a child job must never race its parent's mkdir — but each
        *file* is handed to ``submit`` for a pool worker and is not counted in the
        return value; the pool tallies those as the jobs finish."""
        task.checkpoint()
        if src.is_dir() and not src.is_symlink():
            try:
                dest.mkdir(parents=True, exist_ok=True)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 — can't copy into it; skip children
                errors.append((str(src), str(exc)))
                return 0
            prog.update_progress(src.name)  # counted once it exists, like files
            ok = 1  # the directory itself
            for child in src.iterdir():
                ok += self._copy_tree(task, child, dest / child.name,
                                      overwrite, prog, log, verb, errors, submit)
            return ok
        if submit is not None:
            submit(src, dest)
            return 0  # counted by the pool when the job completes
        slot = prog.file_begin(src.name)
        try:
            copied = self._copy_file(task, src, dest, overwrite, prog, slot)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad file, keep going
            errors.append((str(src), str(exc)))
            prog.file_end(slot)
            return 0
        prog.file_end(slot)
        if copied:
            _log_op(log, verb, src, dest)  # one line per file, with the real dest
            return 1
        return 0  # skipped (inner collision under a non-overwrite dir)

    def _copy_file(self, task: Task, src: Path, dest: Path, overwrite: bool,
                   prog: ProgressManager, slot: int) -> bool:
        """Copy one file; return True if it was written, False if skipped (an inner
        collision under a non-overwrite directory), so the caller logs only real
        copies. ``slot`` is the file's progress slot (``ProgressManager.file_begin``);
        the size is published to it up front so ``file_end`` can credit the bytes
        of whatever path the copy then takes — stream, clone, one-shot, or skip."""
        try:
            size = 0 if src.is_symlink() else src.stat().st_size
        except Exception:  # noqa: BLE001
            size = 0
        prog.file_bytes(slot, 0, size)
        if dest.exists() and not overwrite:
            return False  # inner collision under a non-overwrite dir — leave it
        same = src.get_scheme() == dest.get_scheme()
        local = same and src.get_scheme() == "file"
        if local and not src.is_symlink() and _clone_file(src, dest, overwrite):
            prog.file_bytes(slot, size, size)  # one syscall, all bytes landed
            return True
        if not src.is_symlink() and (not same or size >= _BYTE_BAR_MIN):
            self._copy_bytes(task, src, dest, size, overwrite, local, prog, slot)
        else:
            src.copy_to(dest, overwrite=overwrite)
        return True

    @staticmethod
    def _remote_progress(task: Task, prog: ProgressManager, slot: int):
        """Byte-progress callback for a remote transfer, doubling as the cancel
        checkpoint.

        A local copy checkpoints between chunks in its own loop; a remote one is
        a single call into S3 or SFTP, so the progress callback is the only
        thread of control that comes back often enough to notice a cancel. The
        ``Cancelled`` raised here unwinds the transfer and is re-raised
        unchanged by ``Path.copy_to``. ``slot`` is the file's progress slot, so
        parallel transfers each drive their own row."""
        def report(bytes_copied: int, bytes_total: int) -> None:
            task.checkpoint()
            prog.file_bytes(slot, bytes_copied, bytes_total)
        return report

    def _copy_bytes(self, task: Task, src: Path, dest: Path, size: int,
                    overwrite: bool, local: bool, prog: ProgressManager,
                    slot: int) -> None:
        """Copy a large / cross-storage file while driving its byte slot. Local
        files are streamed in chunks here (so ``shutil`` doesn't hide progress);
        cross-storage copies delegate to ``Path.copy_to``'s own progress callback."""
        if not local:
            try:
                src.copy_to(dest, overwrite=overwrite,
                            progress_callback=self._remote_progress(task, prog,
                                                                    slot))
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
            with open(str(src), "rb") as fi, open(str(dest), "wb") as fo:
                while True:
                    task.checkpoint()
                    chunk = fi.read(_CHUNK)
                    if not chunk:
                        break
                    fo.write(chunk)
                    copied += len(chunk)
                    prog.file_bytes(slot, copied, size)
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


def _log_del(log, path: Path) -> None:
    """Log one delete compactly: the name once, then its directory."""
    if log is not None:
        log(f"Deleted '{path.name}': {path.parent}")


def _serialized_log(log: Callable[[str], None]) -> Callable[[str], None]:
    """Wrap a log sink so parallel workers take turns. The app's sink appends
    to a LogView — a line list plus an incremental wrap cache — which copes
    with one background writer but was never built for several at once."""
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
        if path.get_scheme() != "file":
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
    if target.get_scheme() != dest_dir.get_scheme():
        return False
    src_dev = _entry_device(target.parent)
    dest_dev = _entry_device(dest_dir)
    if src_dev is not None and dest_dev is not None:
        return src_dev == dest_dev
    return True


# --- conflict dialog ---------------------------------------------------------

#: (action id, button label) for the conflict dialog, in row order.
_CONFLICT_ACTIONS = (
    ("overwrite", "Overwrite"),
    ("skip", "Skip"),
    ("keep_both", "Keep both"),
    ("cancel", "Cancel"),
)

#: The dialog's default action: initially focused *and* drawn as the accent
#: "primary" button. The two must name the same button — an accent fill reads as
#: "this is what Enter does", so putting it on a button Enter would not press is
#: a lie about the default. Skip is the safe resolution, matching the app's other
#: destructive confirms (Delete, archive overwrite), where the accent sits on the
#: harmless choice rather than the one that destroys data.
_DEFAULT_CONFLICT_ACTION = "skip"


def _conflict_prompt(name: str, index: int, total: int, z: int):
    """Return a ``show_fn(panel, deliver)`` for ``Task.ask``: it pushes a
    :class:`ConflictDialog` whose result ``(action, apply_to_all)`` is handed to
    ``deliver``. The dialog stacks just above the progress dialog (``z + 5``)."""
    def show(panel: Any, deliver: Callable[[Any], None]) -> None:
        dialog = ConflictDialog(name, index, total, on_result=deliver)
        dialog.show(panel, z=z + 5)
        panel.render()
    return show


class ConflictDialog(FocusContainer, Widget):
    """Per-conflict resolution modal: names the colliding file (``i of N``), a row
    of actions (Overwrite / Skip / Keep both / Cancel), and an "apply to all
    remaining" checkbox. Reports ``(action, apply_to_all)`` through ``on_result``.
    Keyboard: ``o/s/k/c`` shortcuts, ``a``/Space toggles the checkbox, Tab and
    Left/Right move focus (Left/Right along the button row, as in a regular
    message box; Up/Down hop between the row and the checkbox), Enter activates
    the focused button, Esc cancels."""

    focusable = True
    focus_stop_when_empty = True

    def __init__(self, name: str, index: int, total: int,
                 on_result: Callable[[tuple[str, bool]], None]):
        self.name = name
        self.title = f"File exists ({index} of {total})" if total > 1 else "File exists"
        self.on_result = on_result
        self._panel: Any = None
        self._size = (0.0, 0.0)
        # The filename renders as a Markdown `code` span so it stands out from the
        # prose (matching the confirm dialogs). Display-only — not a focus child.
        self._msg = MarkdownView(f"{_code(name)} already exists in the destination.")
        self._checkbox = Checkbox("Apply to all remaining", checked=False)
        self._buttons = [
            Button(label,
                   variant=("primary" if action == _DEFAULT_CONFLICT_ACTION else "secondary"),
                   on_click=(lambda a=action: self._resolve(a)))
            for action, label in _CONFLICT_ACTIONS
        ]
        default = next(i for i, (action, _l) in enumerate(_CONFLICT_ACTIONS)
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
        sw, _sh = panel.backend.size_units
        w = float(max(48, min(72, int(sw) - 4)))
        h = 9.0  # title + message (may wrap 2 rows) + checkbox + button row
        panel.push_layer(self, z=z, hints={"shadow": True, "w": w, "h": h})
        animate_open(panel, self, OPEN_MS_VIEWER)

    def _resolve(self, action: str) -> None:
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

        # Button row along the bottom; the checkbox sits one row above it, snapped
        # to an integer grid row (a Checkbox clips at a fractional y on the
        # character grid). The message fills the gap between title and checkbox.
        lc = ctx.layout_context()
        bh = self._buttons[0].measure(lc, "y", 0.0).preferred
        by = box_h - bh - 1.0  # a full row of bottom padding (clear of the border)
        cb_y = float(int(by) - 1)

        # Markdown message (the filename as a `code` span), on the popup surface.
        self._msg.style = Style(bg=surface_bg)
        ctx.draw_child(self._msg, 2, y, max(1.0, box_w - 4), max(1.0, cb_y - y - 0.25))

        ctx.draw_child(self._checkbox, 2, cb_y, box_w - 4, 1.0,
                       hints={"focused": self._focused is self._checkbox})
        self._child_rects.append((self._checkbox, (2.0, box_w - 2.0, cb_y, cb_y + 1.0)))

        bx = 2.0
        for btn in self._buttons:
            bw = btn.measure(lc, "x", bh).preferred
            ctx.draw_child(btn, bx, by, bw, bh, hints={"focused": self._focused is btn})
            self._child_rects.append((btn, (bx, bx + bw, by, by + bh)))
            bx += bw + 1.0

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
        else:
            for action, _label in _CONFLICT_ACTIONS:
                if char == action[0]:  # o / s / k / c
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
