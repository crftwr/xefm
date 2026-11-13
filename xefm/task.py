"""xefm.task — a small central task system for XeFM's background operations.

XeFM runs long jobs (copy / move / delete, and later archive / search) on a worker
thread while the UI stays live. This module gives those jobs a *single, linear*
shape instead of a callback state machine:

- a :class:`Task` owns a background worker plus a :class:`ProgressManager`, a
  cancel flag, and a **blocking UI bridge** — :meth:`Task.ask` lets the worker
  thread pop a modal on the main thread and *wait* for the answer, so an operation
  reads top-to-bottom (prepare → ask about each conflict → execute) rather than
  being split across states.
- a :class:`TaskManager` (one per app) knows which tasks exist, shows each running
  task's :class:`ProgressDialog`, and pumps the bridge on the animation tick. It also
  runs tasks in the background, one at a time through a queue (#567, #599).

Threading contract: the worker only touches its own ``Task`` (progress, cancel
flag, request queue). Everything that draws or reads the panel happens on the main
thread inside :meth:`TaskManager._tick`. The worker never calls ``panel.*``.
"""

from __future__ import annotations

import itertools
import math
import queue
import threading
import time
from contextlib import contextmanager
from enum import Enum
from typing import Any, Callable, Optional

from puikit.backend import DEFAULT_STYLE, Style, TextAttribute
from puikit.event import Event, EventType
from puikit.widgets import BusyIndicator, Button, ProgressBar, show_message_box
from puikit.widgets.base import Widget

from xefm.dialog_geometry import OPEN_MS_VIEWER, animate_open
from xefm.log_manager import getLogger
from xefm.progress_manager import ProgressManager
from xefm.str_format import abbreviate_path, format_size

logger = getLogger("TaskMgr")

#: Transfer rows the progress dialog reserves — the local copy pool's size.
#: A wider pool (S3) folds its overflow into a final "… N more files" row.
_TRANSFER_ROWS = 4
#: A transfer row prints its byte counts only for files at least this large;
#: below it the copy is one shot and the numbers would just flicker.
_BYTE_TEXT_MIN = 1024 * 1024
#: Space between the progress dialog's buttons, and under them on a vector
#: backend (a grid backend keeps a whole row) — the message box's spacing.
_BUTTON_GAP = 1.0
_GUI_BUTTON_FOOT = 0.65


class TaskStatus(Enum):
    """Lifecycle of a :class:`Task`. Preparing / running / cancelling are *not*
    here — they are display states derived from the progress manager and cancel
    flag (see :class:`ProgressDialog`); only the true lifecycle is stored."""
    PENDING = "pending"      # created / enqueued, worker not started yet
    RUNNING = "running"      # worker thread active
    DONE = "done"            # finished normally
    CANCELLED = "cancelled"  # cancelled (before or during the run)
    FAILED = "failed"        # worker raised an unexpected exception


class Cancelled(Exception):
    """Raised out of :meth:`Task.ask` / :meth:`Task.checkpoint` to unwind a
    cancelled worker back to the top of its ``run`` body."""


class _UiRequest:
    """One worker→main-thread request: run ``show_fn(panel, deliver)`` on the main
    thread, then block the worker on :attr:`event` until ``deliver(answer)`` fires."""

    __slots__ = ("show_fn", "answer", "event")

    def __init__(self, show_fn: Callable[[Any, Callable[[Any], None]], None]):
        self.show_fn = show_fn
        self.answer: Any = None
        self.event = threading.Event()

    def deliver(self, answer: Any) -> None:
        self.answer = answer
        self.event.set()


_task_ids = itertools.count(1)


class Task:
    """A cancellable background job with a progress model and a blocking UI bridge.

    The worker body is an ordinary function ``run(task)`` handed to
    :meth:`TaskManager.submit`; it drives ``task.progress`` and calls
    :meth:`ask` / :meth:`checkpoint`. It must never touch the panel directly."""

    #: Poll interval (s) while a blocked ``ask`` waits, so cancellation interrupts
    #: a pending prompt promptly without a busy-spin.
    _WAIT_TICK = 0.05

    def __init__(self, title: str, *, config: Any = None, kind: str = "",
                 busy_label: str = "Preparing…", exclusive: bool = True):
        self.id = next(_task_ids)
        self.title = title
        self.kind = kind
        #: What the dialog says while the task has no item total to show — the
        #: counting phase of a copy, or the whole of a task that never has one.
        self.busy_label = busy_label
        self.status = TaskStatus.PENDING
        self.progress = ProgressManager(config)
        #: Files seen so far during the (pre-total) counting phase — display only.
        self.counted = 0
        self.result: Optional[dict] = None
        self.error: Optional[BaseException] = None
        self._cancel = threading.Event()
        self._requests: "queue.Queue[_UiRequest]" = queue.Queue()
        #: In synchronous (test) mode there is no main-thread pump, so ``ask``
        #: returns the caller's headless default instead of blocking on a dialog.
        self._headless = False
        #: Running (or queued) without its progress dialog on screen (#567). A
        #: prompt it raises meanwhile waits until it is brought forward.
        self.background = False
        #: What the task works on, for the jobs list (#599): "12 items
        #: ~/photos → s3://bucket/". Empty when the title says it all.
        self.detail = ""
        #: Clear while the task is suspended (#599): the worker waits at its
        #: next pausable :meth:`checkpoint`. Set by default — a task runs.
        self._running = threading.Event()
        self._running.set()
        #: The threads of this task that are at work: past a pausable
        #: checkpoint, and not yet waiting at the next one, on a prompt, or
        #: in :meth:`idle` (#887). A copy has several (its pool workers), so
        #: "paused" is this set being empty, not one thread having stopped.
        #: Read and changed under ``_lock``, together with ``_running``, so a
        #: thread cannot slip past a checkpoint as the task is suspended.
        self._inflight: set[int] = set()
        self._lock = threading.Lock()
        #: Whether the task writes. A task that only reads (#632, #887) says
        #: so by clearing this. It then never waits for another task and
        #: never makes one wait: in the background it runs beside the slot's
        #: job instead of behind it, and in front it does not suspend that job.
        self.exclusive = exclusive
        #: What a writer in front is waiting for, while it waits for a
        #: background job to pause (#887) — that job's title, for the dialog.
        self.waiting_for: Optional[str] = None

    # --- worker-side API (called on the worker thread) -----------------------

    def ask(self, show_fn: Callable[[Any, Callable[[Any], None]], None], *,
            headless: Any) -> Any:
        """Show a modal via ``show_fn(panel, deliver)`` on the main thread and
        block until it delivers an answer; return that answer. Raises
        :class:`Cancelled` if the task is cancelled while waiting. In headless
        mode returns ``headless`` without prompting."""
        if self._headless:
            return headless
        if self._cancel.is_set():
            raise Cancelled()
        req = _UiRequest(show_fn)
        self._requests.put(req)
        # Waiting on the user is not writing: a job blocked here counts as
        # paused, so a writer in front need not wait for its answer (#887).
        with self.idle():
            while not req.event.wait(self._WAIT_TICK):
                if self._cancel.is_set():
                    raise Cancelled()
        return req.answer

    def checkpoint(self, pausable: bool = True) -> None:
        """Raise :class:`Cancelled` if cancellation was requested. Call between
        units of work (e.g. per file / per chunk).

        A **pausable** checkpoint also waits here while the task is suspended
        (:meth:`suspend`), until it is resumed or cancelled. Inside a transfer
        pass ``pausable=False``: a remote stream left stalled for as long as
        another job takes can time out, so a task pauses only between files.

        Passing a pausable checkpoint marks the calling thread as at work
        until it stops at the next one (or in :meth:`idle`, or a prompt):
        that is what :attr:`paused` counts."""
        if self._cancel.is_set():
            raise Cancelled()
        if pausable:
            self._join(raise_on_cancel=True)

    def _join(self, raise_on_cancel: bool) -> None:
        """Mark the calling thread at work, first waiting while the task is
        suspended. The check and the mark are one step under ``_lock``, so a
        :meth:`suspend` either comes before (and the thread waits) or after
        (and the thread is counted, so the task is not :attr:`paused` until it
        stops again)."""
        me = threading.get_ident()
        while True:
            with self._lock:
                if self._running.is_set():
                    self._inflight.add(me)
                    return
                self._inflight.discard(me)
            while not self._running.wait(self._WAIT_TICK):
                if self._cancel.is_set():
                    if raise_on_cancel:
                        raise Cancelled()
                    return
            if self._cancel.is_set():
                if raise_on_cancel:
                    raise Cancelled()
                return

    def leave(self) -> None:
        """The calling thread has stopped working for this task — a pool
        worker between jobs, or the worker once ``run`` returns."""
        with self._lock:
            self._inflight.discard(threading.get_ident())

    @contextmanager
    def idle(self):
        """A stretch in which the calling thread writes nothing but waits on
        something else — other threads of this task, a lock, the user. It
        does not count as at work meanwhile, so the task can be :attr:`paused`
        while it waits; leaving it is a pausable checkpoint (without the
        cancel: the caller unwinds as it would have)."""
        self.leave()
        yield
        self._join(raise_on_cancel=False)

    @property
    def paused(self) -> bool:
        """Suspended, and none of its threads at work any more: the files it
        had in flight have landed. A thread blocked on a prompt counts as
        stopped, since it writes nothing until it is answered."""
        with self._lock:
            return not self._running.is_set() and not self._inflight

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def needs_attention(self) -> bool:
        """A background task waiting on an answer only the user can give — a
        conflict prompt it raised while its dialog was off screen."""
        return self.background and not self._requests.empty()

    # --- control (main thread) -----------------------------------------------

    def request_cancel(self) -> None:
        """Ask the worker to stop. Sets the cooperative flag; a blocked
        :meth:`ask` — or a suspended :meth:`checkpoint` — wakes within
        :attr:`_WAIT_TICK` and unwinds."""
        self._cancel.set()

    def suspend(self) -> None:
        """Hold the worker at its next pausable checkpoint. The files it has
        in flight finish first; :attr:`paused` says when they have."""
        with self._lock:
            self._running.clear()

    def resume(self) -> None:
        with self._lock:
            self._running.set()
        self.waiting_for = None

    @property
    def suspended(self) -> bool:
        return not self._running.is_set()

    def _next_request(self) -> Optional[_UiRequest]:
        try:
            return self._requests.get_nowait()
        except queue.Empty:
            return None


class _Job:
    """What the manager keeps for one running task: the dialog it shows when it
    is in the foreground, and how to finish it."""

    __slots__ = ("task", "panel", "dialog", "finished", "on_done", "z",
                 "last_render")

    def __init__(self, task, panel, dialog, on_done, z):
        self.task = task
        self.panel = panel
        self.dialog = dialog
        self.finished = threading.Event()
        self.on_done = on_done
        self.z = z
        self.last_render = 0.0


class _Waiting:
    """One entry of the background queue: a task not started yet (with what
    starting it takes), or a started one suspended until its turn (``job``)."""

    __slots__ = ("task", "panel", "run", "on_done", "z", "job")

    def __init__(self, task, panel, *, run=None, on_done=None, z=70, job=None):
        self.task = task
        self.panel = panel
        self.run = run
        self.on_done = on_done
        self.z = z
        self.job = job


class TaskManager:
    """Central registry + main-thread pump for :class:`Task` s. One per app.

    Holds every live task, shows each foreground task's :class:`ProgressDialog`,
    and services its UI bridge on the animation tick.

    A task can run in the **background** (#567): its dialog leaves the screen
    and the user goes on working. Background jobs go through a **serial
    queue** — they compete for the same disk or connection — and only one of
    them runs at a time: the one holding the **slot** (#599). ``submit(...,
    detached=True)`` queues a task before it starts. :meth:`detach` sends a
    running one back: it is **suspended first** (it stops at its next file
    boundary) and then queued, and the queue resumes it when the slot frees.

    **One writer at a time** (#887). A foreground task that writes does not
    wait for the queue, but it does not write beside the slot's job either:
    that job is suspended, and the foreground task starts once it has paused
    (:attr:`Task.paused`) — its dialog says it is waiting meanwhile. The slot's
    job resumes when no writer is in front any more. :meth:`_arbitrate` holds
    the rule; a task that only reads (``exclusive`` clear) is outside it.

    :meth:`bring_forward` puts a job's dialog back, which is also how a
    background job's pending prompt gets answered: a prompt never opens on its
    own while the job is out of sight, it waits and the job is flagged
    (:attr:`Task.needs_attention`). The slot's job keeps the slot while it is
    in front; a queued one brought forward leaves the queue and runs in front
    at once."""

    #: How often a background job repaints, for the status bar's progress.
    _BACKGROUND_REPAINT_S = 0.25

    def __init__(self):
        self.tasks: list[Task] = []
        self._jobs: dict[int, _Job] = {}
        #: Background jobs waiting for the slot, in order.
        self._queue: list[_Waiting] = []
        #: The one background job allowed to run.
        self._slot: Optional[_Job] = None

    def active_tasks(self) -> list[Task]:
        return [t for t in self.tasks
                if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]

    def has_active(self) -> bool:
        return any(t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
                   for t in self.tasks)

    def background_tasks(self) -> list[Task]:
        """The slot's job first (in front or not), then the non-exclusive jobs
        running beside it, then the queue in order."""
        running = [self._slot.task] if self._slot is not None else []
        return running + self._beside() + [entry.task for entry in self._queue]

    def running_task(self) -> Optional[Task]:
        """The background job holding the slot — or, with the slot free, the
        first non-exclusive one running beside it — or None."""
        if self._slot is not None:
            return self._slot.task
        beside = self._beside()
        return beside[0] if beside else None

    def _beside(self) -> list[Task]:
        """Non-exclusive background jobs, running outside the slot."""
        return [job.task for job in self._jobs.values()
                if job.task.background and not job.task.exclusive
                and job is not self._slot]

    def queued_count(self) -> int:
        return len(self._queue)

    def is_queued(self, task: Task) -> bool:
        return any(entry.task is task for entry in self._queue)

    def submit(self, task: Task, panel: Any, *, run: Callable[[Task], dict],
               on_done: Optional[Callable[[dict], None]] = None,
               z: int = 70, background: bool = True,
               detached: bool = False) -> Task:
        """Run ``run(task)``. In background mode: show a :class:`ProgressDialog`,
        spawn the worker, and pump the bridge + repaint each frame, closing the
        dialog and calling ``on_done(result)`` on the main thread when it ends. In
        synchronous mode (tests): run inline, ``ask`` resolves to its headless
        default, no dialog, ``on_done`` fires immediately. A backend that cannot
        drive animation ticks gets the synchronous treatment too — with no tick
        there would be nothing to pump prompts, service Cancel, or close the
        dialog.

        ``detached`` starts the task in the background instead, with no dialog,
        through the serial queue: it waits while another background job holds
        the slot. A task that is not :attr:`Task.exclusive` never waits: it
        starts at once, beside whatever holds the slot."""
        self.tasks.append(task)

        if not background:
            task._headless = True
            task.status = TaskStatus.RUNNING
            result = self._run_inline(task, run)
            self._finish(task)
            if on_done is not None:
                on_done(result)
            return task

        if detached and not task.exclusive:
            task.background = True
            self._start(task, panel, run, on_done, z)
            panel.render()
            return task
        if detached:
            task.background = True
            self._queue.append(_Waiting(task, panel, run=run, on_done=on_done, z=z))
            self._start_next()
            panel.render()
            return task
        self._start(task, panel, run, on_done, z)
        self._arbitrate()
        return task

    def _start(self, task: Task, panel: Any, run, on_done, z: int) -> Optional[_Job]:
        dialog = ProgressDialog(task, on_background=self.detach)
        job = _Job(task, panel, dialog, on_done, z)
        if not task.background:
            dialog.show(panel, z=z)
        task.status = TaskStatus.RUNNING
        if task.exclusive:
            # A writer starts held, at the checkpoint below, until _arbitrate
            # lets it go: suspended before its thread exists, it cannot write
            # a byte beside another writer (#887).
            task.suspend()

        def worker() -> None:
            try:
                try:
                    task.checkpoint()  # a writer's turn
                except Cancelled:
                    task.result = dict(_empty_result(), cancelled=True)
                    return
                task.result = run(task)
            except BaseException as exc:  # noqa: BLE001 — recorded, surfaced on tick
                task.error = exc
            finally:
                task.leave()
                job.finished.set()

        def tick() -> bool:
            return self._tick(job)

        # Register the tick before the worker exists: if this backend cannot
        # drive frame ticks, nothing would ever pump the prompt bridge, service
        # Cancel, or close the dialog — the worker would mutate the filesystem
        # behind a dialog that can never be dismissed. Fall back to running the
        # task inline (prompts resolve to their headless defaults), exactly as
        # the synchronous mode above does.
        if not panel.request_animation_ticks(tick):
            dialog.close()
            task.resume()  # nothing would ever let it go
            task._headless = True
            result = self._run_inline(task, run)
            self._finish(task)
            if on_done is not None:
                on_done(result)
            return None

        self._jobs[task.id] = job
        threading.Thread(target=worker, name=f"xefm-task-{task.id}", daemon=True).start()
        return job

    def _tick(self, job: _Job) -> bool:
        """Main thread, each frame: service at most one pending prompt (only
        while the job is in the foreground), repaint, and on completion tear
        down and report the result."""
        task, panel, dialog = job.task, job.panel, job.dialog
        self._arbitrate()
        if not task.background:
            dialog.pump(panel)
        if not job.finished.is_set():
            # A repaint that raises must not end the tick: the backend drops a
            # raising tick, and this one is the only thing that tears the job
            # down — a background job would then hold the queue's slot for good.
            try:
                if not task.background:
                    panel.render()
                else:
                    now = time.monotonic()
                    if now - job.last_render >= self._BACKGROUND_REPAINT_S:
                        job.last_render = now
                        panel.render()
            except Exception as exc:  # noqa: BLE001 — logged, the job goes on
                logger.error(f"Repaint during task {task.title!r} failed: {exc}")
            return True
        # Teardown runs exactly once (the tick unregisters below), so it must
        # not be derailed: close first, and keep an on_done failure from
        # escaping into the backend's tick dispatch.
        dialog.close()
        self._jobs.pop(task.id, None)
        # A suspended job can still end — cancelled while it waited.
        self._queue = [e for e in self._queue if e.task is not task]
        if self._slot is job:
            self._slot = None
        self._finish(task)
        if job.on_done is not None:
            try:
                job.on_done(_result_of(task))
            except Exception as exc:  # noqa: BLE001 — logged, teardown completes
                logger.error(f"Task completion callback failed: {exc}")
        self._start_next()
        # One repaint so the closed dialog leaves the screen even when
        # on_done did not render (or was None / raised).
        panel.render()
        return False

    def _start_next(self) -> None:
        """Hand the slot to the next queued job, if it is free: a suspended
        one, or one that has not run yet. :meth:`_arbitrate` then decides
        whether it runs at once or waits for a writer in front."""
        while self._slot is None and self._queue:
            entry = self._queue.pop(0)
            task = entry.task
            if entry.job is not None:
                self._slot = entry.job
                break
            if task.cancelled():
                self._finish(task)
                if entry.on_done is not None:
                    entry.on_done(dict(_empty_result(), cancelled=True))
                continue
            self._slot = self._start(task, entry.panel, entry.run, entry.on_done,
                                     entry.z)
        self._arbitrate()

    def _arbitrate(self) -> None:
        """Let one writer run at a time (#887), on the main thread.

        The writers that should run are the foreground ones — the user is
        watching them — or, with none in front, the slot's job. Every other
        writer is suspended. One that should run is let go only once all the
        others have paused, so a job suspended mid-file finishes that file
        before anything else writes: a transfer cannot stop mid-file, since a
        remote stream left stalled times out. Until then it stays held, and a
        foreground one's dialog names what it waits for.

        Called whenever the set of writers changes and on every tick, which
        is what notices a job has paused. A task that only reads (``exclusive``
        clear) is neither held nor waited for."""
        writers = [j for j in self._jobs.values()
                   if j.task.exclusive and not j.finished.is_set()]
        front = [j for j in writers
                 if not j.task.background and j is not self._slot]
        if front:
            runners = front
        else:
            runners = [self._slot] if self._slot in writers else []
        others = [j for j in writers if j not in runners]
        for job in others:
            job.task.suspend()
        blocker = next((j for j in others if not j.task.paused), None)
        for job in runners:
            if not job.task.suspended:
                continue
            if blocker is None:
                job.task.resume()
            else:
                job.task.waiting_for = blocker.task.title.rstrip("… ")

    def cancel_all(self, timeout: float = 3.0) -> bool:
        """Cancel every task — the running ones and the queue — and wait up to
        ``timeout`` seconds for the running workers to unwind, so a half-written
        file is cleaned up before the process exits. True when all of them
        did. For quitting: nothing is reported, the app is going away."""
        for entry in self._queue:
            entry.task.request_cancel()
        self._queue.clear()
        jobs = list(self._jobs.values())
        for job in jobs:
            job.task.request_cancel()
        deadline = time.monotonic() + timeout
        for job in jobs:
            if not job.finished.wait(max(0.0, deadline - time.monotonic())):
                return False
        return True

    def detach(self, task: Task) -> None:
        """Send a running foreground task to the background: its dialog leaves
        the screen, and unless it already holds the slot it is suspended and
        queued — it runs again when its turn comes, which is at once when the
        slot is free. A non-exclusive task is neither: it goes on running."""
        job = self._jobs.get(task.id)
        if job is None or task.background:
            return
        job.dialog.close()
        task.background = True
        if self._slot is not job and task.exclusive:
            task.suspend()
            self._queue.append(_Waiting(task, job.panel, job=job))
            self._start_next()
        self._arbitrate()
        job.panel.render()

    def bring_forward(self, task: Task) -> bool:
        """Put a background task's dialog back on screen — where its pending
        prompt is answered and Esc can cancel it. A queued task that has not
        started is cancelled instead of shown: there is nothing to show yet,
        and the only thing to do with it is drop it. A suspended one leaves the
        queue and runs in front, as a foreground task. False when ``task`` is
        none of these."""
        for i, entry in enumerate(self._queue):
            if entry.task is not task:
                continue
            self._queue.pop(i)
            if entry.job is not None:
                # In front it is a writer the user watches: the slot's job is
                # suspended, and this one runs once that job has paused.
                task.background = False
                self._arbitrate()
                entry.job.dialog.show(entry.job.panel, z=entry.job.z)
                entry.job.panel.render()
                return True
            task.request_cancel()
            self._finish(task)
            if entry.on_done is not None:
                entry.on_done(dict(_empty_result(), cancelled=True))
            entry.panel.render()
            return True
        job = self._jobs.get(task.id)
        if job is None or not task.background:
            return False
        task.background = False
        job.dialog.show(job.panel, z=job.z)
        job.panel.render()
        return True

    @staticmethod
    def _run_inline(task: Task, run: Callable[[Task], dict]) -> dict:
        try:
            task.result = run(task)
        except BaseException as exc:  # noqa: BLE001
            task.error = exc
        return _result_of(task)

    def _finish(self, task: Task) -> None:
        if task.error is not None:
            task.status = TaskStatus.FAILED
        elif task.cancelled() or (task.result or {}).get("cancelled"):
            task.status = TaskStatus.CANCELLED
        else:
            task.status = TaskStatus.DONE
        if task in self.tasks:
            self.tasks.remove(task)


def _empty_result() -> dict:
    return {"done": 0, "skipped": 0, "failed": 0, "cancelled": False}


def _result_of(task: Task) -> dict:
    """What a finished task hands its ``on_done``: its result, and under
    ``"error"`` the exception its worker raised, if it raised."""
    result = task.result or _empty_result()
    if task.error is not None:
        result = dict(result, error=task.error)
    return result


def transfer_bytes_text(transfer: dict) -> str:
    """The right-hand column of one transfer row.

    Normally the file's byte counts, and nothing at all for a file too small
    for them to be worth the width. While the file is being *closed* it says so
    instead, with the seconds it has been at it.

    That last case is the one that earns this its own function. Where the
    destination holds a file in a local cache until it is closed — WebDAV, and
    NFS's close-to-open flush — the close is where the bytes actually travel,
    and the row would otherwise hold at its total for the whole of it: the
    operation's real work, shown as a number that had stopped moving. Nothing
    here is specific to such a destination, though. One whose close is instant
    passes through this in a single frame."""
    if transfer.get("closing_since") and not transfer.get("done"):
        waited = int(max(0.0, time.monotonic() - transfer["closing_since"]))
        return f"finishing… {waited}s" if waited else "finishing…"
    if transfer["total"] >= _BYTE_TEXT_MIN:
        return (f"{format_size(transfer['copied'], compact=True)}"
                f" / {format_size(transfer['total'], compact=True)}")
    return ""


class ProgressDialog(Widget):
    """Modal progress surface for a running :class:`Task`. Generic — it renders
    only from ``task.title`` + ``task.progress`` (the :class:`ProgressManager`), so
    any task type reuses it:

    - **Preparing** (``ProgressManager`` still ``counting``): a :class:`BusyIndicator`
      and a "Preparing…" line — an indeterminate phase with no total yet.
    - **Running**: a determinate primary :class:`ProgressBar` (weighted by items
      *and* bytes when the operation measured them), then either the current file
      name with a **secondary byte bar** (operations that work one file at a
      time — delete, archives), or — once the copy engine's per-file transfer
      slots report in — **one row per in-flight file**, each with its own byte
      counts, so a parallel copy shows every worker's file rather than whichever
      one most recently started.
    - **Cancelling** (derived from the cancel flag): a "Cancelling…" line until the
      worker unwinds.

    Along the bottom, **Run in background** (when a manager can take it there)
    and **Cancel** (#599). Cancel, and ``Esc``, open a confirm box; confirming
    requests cancellation on the task. Tab and the arrows move between the
    buttons, Enter or Space presses one. The dialog only *reads* progress
    state during ``draw`` — the worker mutates it."""

    focusable = True

    def __init__(self, task: Task,
                 on_background: Optional[Callable[[Task], None]] = None):
        self.task = task
        #: Sends the task to the background (:meth:`TaskManager.detach`);
        #: None hides the choice, for a dialog with no manager behind it.
        self._on_background = on_background
        self._panel: Any = None
        self._bar = ProgressBar()
        self._byte_bar = ProgressBar()
        self._busy = BusyIndicator(label="")
        #: True while a bridged prompt (conflict dialog) is on screen, so the pump
        #: shows one at a time and the worker's next request waits its turn.
        self._request_in_flight = False
        #: True while the cancel-confirm box is up, so Esc doesn't stack another.
        self._confirming_cancel = False
        #: The open cancel-confirm box itself, so close() can dismiss it along
        #: with the dialog — its question is moot once the task has ended.
        self._cancel_box: Any = None
        self._buttons = []
        if on_background is not None:
            self._buttons.append(Button("Run in background", variant="secondary",
                                        on_click=self._send_to_background))
        self._buttons.append(Button("Cancel", variant="secondary",
                                    on_click=self._confirm_cancel))
        self._focused = 0
        #: Each button's (x0, x1, y0, y1), captured in draw for click routing.
        self._button_rects: list = []

    # --- lifecycle -----------------------------------------------------------

    def show(self, panel: Any, z: int = 70) -> None:
        self._panel = panel
        self._z = z
        sw, _sh = panel.backend.size_units
        w = float(max(44, min(70, int(sw) - 4)))
        # title + primary bar/label + either (current item + secondary bar/label)
        # or up to four per-file transfer rows. The rows are reserved whether or
        # not anything fills them: an operation alternates between files that
        # report bytes and files that don't, and a box that resized under each
        # one would jitter for its whole run. The height stays *even*: an odd box
        # centers onto a half cell, and the rounding then walks the foot-anchored
        # rows onto the bottom border.
        # Two more rows for the buttons along the bottom.
        h = 12.0
        panel.push_layer(self, z=z, hints={"shadow": True, "w": w, "h": h})
        animate_open(panel, self, OPEN_MS_VIEWER)

    def close(self) -> None:
        """Remove this dialog's layer — and the cancel-confirm box, if one is
        still open above it. Removal is by identity, wherever each layer sits:
        the dialog is *not* necessarily topmost at teardown (the task can
        finish while the confirm box is covering it), and the old "pop only if
        topmost" guard then silently skipped the pop, stranding the dialog on
        screen with nothing left to ever close it (#333)."""
        panel = self._panel
        if panel is None:
            return
        if self._cancel_box is not None:
            panel.remove_layer(self._cancel_box)
            self._cancel_box = None
            self._confirming_cancel = False
        panel.remove_layer(self)

    # --- bridge pump (main thread) -------------------------------------------

    def pump(self, panel: Any) -> None:
        """Service at most one pending UI request from the worker: pop it and show
        its dialog. Only one runs at a time — the worker blocks on the answer
        before it can post the next, so conflicts prompt sequentially."""
        if self._request_in_flight:
            return
        req = self.task._next_request()
        if req is None:
            return
        self._request_in_flight = True

        def deliver(answer: Any) -> None:
            self._request_in_flight = False
            req.deliver(answer)

        req.show_fn(panel, deliver)

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        theme = ctx.theme
        box_style = (Style(bg=theme.popup_bg, fg=theme.popup_border)
                     if theme is not None else DEFAULT_STYLE)
        surface_bg = theme.popup_bg if theme is not None else None
        box_w, full_h = ctx.size_units
        ctx.draw_box(0, 0, box_w, full_h, box_style, hints={"fill": True})
        # The buttons take the foot; everything above lays out in what is left,
        # as if the box ended where the button row begins — a whole number of
        # units, so the foot-anchored rows keep their whole-row spacing on a
        # vector backend too (a fractional foot rounded two of them together).
        box_h = float(math.floor(self._draw_buttons(ctx, box_w, full_h)))
        text_style = Style(bg=surface_bg)
        ctx.draw_text(2, 0.5, self.task.title, Style(bg=surface_bg, attr=TextAttribute.BOLD))
        # The popup surface, handed to the child widgets (bars, spinner)
        # explicitly: their glyph runs name no background, and on a grid backend
        # an unbackgrounded cell falls to the *terminal default* rather than the
        # theme surface — a light theme showed dark strips through the dialog.
        child_hints = {"bg": surface_bg}

        op = self.task.progress.get_current_operation()
        width = max(1.0, box_w - 4)
        waiting = self.task.waiting_for
        if waiting and self.task.suspended and not self.task.cancelled():
            # A writer in front, held until a background job pauses (#887).
            ctx.draw_child(self._busy, 2, 3.0, 2.0, 1.0, hints=child_hints)
            ctx.draw_text(4, 3.0, f"Waiting for {waiting} to pause…", text_style)
            return
        if op is None or op.get("counting"):
            self._draw_preparing(ctx, op, box_w, box_h, text_style, child_hints)
            return
        transfers = self.task.progress.get_transfers()
        if transfers:
            self._draw_transfers(ctx, op, transfers, box_h, width, text_style,
                                 child_hints)
            return
        if self.task.cancelled():
            ctx.draw_text(2, 2.2, "Cancelling…", text_style)

        # Current item above the bars, abbreviated the way the pane header is:
        # measured through the backend, so a wide CJK glyph and a proportional
        # GUI font each count for what they really take rather than for one
        # character, and cut in the middle, so the extension — the part that
        # says what the file *is* — survives a name too long to show whole.
        item = (op.get("current_item") or "") if not self.task.cancelled() else ""
        if item:
            ctx.draw_text(2, 2.2, abbreviate_path(item, width, measure=ctx.measure_text),
                          text_style)

        # Primary bar: items processed / total.
        self._bar.value = self.task.progress.get_progress_percentage() / 100.0
        ctx.draw_child(self._bar, 2, 3.4, width, 1.0, hints=child_hints)
        ctx.draw_text(2, 4.3, f"{op['processed_items']} / {op['total_items']} items", text_style)

        # Secondary bar: bytes of the current file (only when a total is known).
        # Placed by measuring up from the foot of the box — label on the last row
        # inside the frame, bar above it — rather than at absolute offsets. A
        # centered box can land on a half cell, and absolute offsets then round a
        # row further down: that is how the label came to be drawn *on* the border.
        bc, bt = op.get("file_bytes_copied", 0), op.get("file_bytes_total", 0)
        if bt > 0:
            label_y = box_h - 2.0
            self._byte_bar.value = min(1.0, bc / bt) if bt else 0.0
            ctx.draw_child(self._byte_bar, 2, label_y - 1.0, width, 1.0,
                           hints=child_hints)
            ctx.draw_text(
                2, label_y,
                f"{format_size(bc, compact=True)} / {format_size(bt, compact=True)}",
                text_style)

    def _draw_buttons(self, ctx, box_w: float, box_h: float) -> float:
        """The button row, centered along the foot, drawn as real Buttons (the
        message box's look: flat fill, focus ring on the focused one). Returns
        where the row begins, which is where the content above must end."""
        lc = ctx.layout_context()
        bh = self._buttons[0].measure(lc, "y", 0.0).preferred
        widths = [b.measure(lc, "x", bh).preferred for b in self._buttons]
        total = sum(widths) + _BUTTON_GAP * (len(widths) - 1)
        bx = max(2.0, (box_w - total) / 2.0)
        by = max(0.0, box_h - bh - (_GUI_BUTTON_FOOT if ctx.vector_shapes else 1.0))
        if lc.snap:
            # A half-unit origin would round the focus brackets and the label
            # apart on a grid (the message box's reason, too).
            bx, by = round(bx), round(by)
        self._button_rects = []
        for i, (button, w) in enumerate(zip(self._buttons, widths)):
            ctx.draw_child(button, bx, by, w, bh, hints={"focused": i == self._focused})
            self._button_rects.append((bx, bx + w, by, by + bh))
            bx += w + _BUTTON_GAP
        return by

    def _draw_transfers(self, ctx, op, transfers, box_h, width, text_style,
                        child_hints) -> None:
        """The copy engine's layout: the primary bar (items and, when measured,
        bytes) directly under the title, then one row per transfer slot — each
        worker's current file with its own byte counts. Rows are keyed by slot,
        and a finished file holds its row until the worker's next file replaces
        it, so the lines stay put instead of blinking."""
        self._bar.value = self.task.progress.get_progress_percentage() / 100.0
        ctx.draw_child(self._bar, 2, 1.9, width, 1.0, hints=child_hints)
        label = f"{op['processed_items']} / {op['total_items']} items"
        if op.get("total_bytes"):
            label += (f" — {format_size(op['processed_bytes'], compact=True)}"
                      f" / {format_size(op['total_bytes'], compact=True)}")
        ctx.draw_text(2, 2.9, label, text_style)
        # The file rows are anchored up from the foot of the box (the same
        # proven-safe rule as the single-file byte label), which leaves a blank
        # line under the summary — the operation total and the per-file section
        # read as two parts on the grid backends as well as the vector ones.
        foot = box_h - 2.0
        first_row = foot - (_TRANSFER_ROWS - 1) * 0.9
        if self.task.cancelled():
            ctx.draw_text(2, first_row, "Cancelling…", text_style)
            return
        rows = transfers
        extra = len(rows) - _TRANSFER_ROWS
        if extra > 0:
            rows = rows[:_TRANSFER_ROWS - 1]
        for i, (_slot, t) in enumerate(rows):
            y = first_row + i * 0.9
            bytes_text = transfer_bytes_text(t)
            bytes_w = ctx.measure_text(bytes_text) if bytes_text else 0.0
            name_w = max(1.0, width - (bytes_w + 2.0 if bytes_text else 0.0))
            ctx.draw_text(2, y, abbreviate_path(t["item"], name_w,
                                                measure=ctx.measure_text),
                          text_style)
            if bytes_text:
                ctx.draw_text(2 + width - bytes_w, y, bytes_text, text_style)
        if extra > 0:
            ctx.draw_text(2, foot, f"… {extra + 1} more files", text_style)

    def _draw_preparing(self, ctx, op, box_w, box_h, text_style,
                        child_hints) -> None:
        ctx.draw_child(self._busy, 2, 3.0, 2.0, 1.0, hints=child_hints)
        n = self.task.counted
        busy = self.task.busy_label
        label = f"{busy} ({n} item{'s' if n != 1 else ''})" if n else busy
        ctx.draw_text(4, 3.0, label, text_style)

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY:
            n = len(self._buttons)
            if event.key == "escape":
                self._confirm_cancel()
            elif event.key in ("left", "up"):
                self._focused = (self._focused - 1) % n
            elif event.key in ("right", "down", "tab"):
                self._focused = (self._focused + 1) % n
            elif event.key in ("enter", "space") or event.char == " ":
                self._buttons[self._focused].handle_event(event)
        elif event.type is EventType.MOUSE_CLICK and event.x is not None:
            ey = event.y or 0
            for i, (x0, x1, y0, y1) in enumerate(self._button_rects):
                if x0 <= event.x < x1 and y0 <= ey < y1:
                    self._focused = i
                    self._buttons[i].handle_event(event)
                    break
        return True  # modal: swallow everything else

    def _send_to_background(self) -> None:
        if self._on_background is not None and not self.task.cancelled():
            self._on_background(self.task)

    def _confirm_cancel(self) -> None:
        """Esc: pop a confirm box (above this dialog); on Yes, request cancel. The
        worker keeps running while the user decides — cancel only takes effect if
        confirmed."""
        if self._confirming_cancel or self.task.cancelled() or self._panel is None:
            return
        self._confirming_cancel = True

        def on_result(label: str) -> None:
            self._confirming_cancel = False
            self._cancel_box = None
            if label == "Cancel operation":
                self.task.request_cancel()
            if self._panel is not None:
                self._panel.render()

        # The operation keeps running while this is asked. Enter and Esc both
        # keep it running, so a stray key changes nothing; sending it to the
        # background is the dialog's own button.
        buttons = ("Cancel operation", "Keep running")
        self._cancel_box = show_message_box(
            self._panel, f"Stop waiting for {self.task.title.rstrip('… ')}?",
            title="Running", icon="warning", buttons=buttons,
            default=len(buttons) - 1, cancel=len(buttons) - 1,
            on_result=on_result, z=getattr(self, "_z", 70) + 5)
