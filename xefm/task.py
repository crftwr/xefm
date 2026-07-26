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
  task's :class:`ProgressDialog`, and pumps the bridge on the animation tick. It is
  deliberately more than this change needs: it is the seam for future *background*
  (non-modal) execution, a task queue, and a common task-management UI. For now it
  runs one modal task at a time.

Threading contract: the worker only touches its own ``Task`` (progress, cancel
flag, request queue). Everything that draws or reads the panel happens on the main
thread inside :meth:`TaskManager._tick`. The worker never calls ``panel.*``.
"""

from __future__ import annotations

import itertools
import queue
import threading
from enum import Enum
from typing import Any, Callable, Optional

from puikit.backend import DEFAULT_STYLE, Style, TextAttribute
from puikit.event import Event, EventType
from puikit.widgets import BusyIndicator, ProgressBar, show_message_box
from puikit.widgets.base import Widget

from xefm.dialog_geometry import OPEN_MS_VIEWER, animate_open
from xefm.progress_manager import ProgressManager
from xefm.str_format import abbreviate_path, format_size


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

    def __init__(self, title: str, *, config: Any = None, kind: str = ""):
        self.id = next(_task_ids)
        self.title = title
        self.kind = kind
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
        while not req.event.wait(self._WAIT_TICK):
            if self._cancel.is_set():
                raise Cancelled()
        return req.answer

    def checkpoint(self) -> None:
        """Raise :class:`Cancelled` if cancellation was requested. Call between
        units of work (e.g. per file / per chunk)."""
        if self._cancel.is_set():
            raise Cancelled()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # --- control (main thread) -----------------------------------------------

    def request_cancel(self) -> None:
        """Ask the worker to stop. Sets the cooperative flag; a blocked
        :meth:`ask` wakes within :attr:`_WAIT_TICK` and unwinds."""
        self._cancel.set()

    def _next_request(self) -> Optional[_UiRequest]:
        try:
            return self._requests.get_nowait()
        except queue.Empty:
            return None


class TaskManager:
    """Central registry + main-thread pump for :class:`Task` s. One per app.

    Holds every live task (so the app — and, later, a task UI — can see what is
    running), shows each task's :class:`ProgressDialog`, and services its UI bridge
    on the animation tick. Runs one modal task at a time today; the shape supports
    background/queued execution later."""

    def __init__(self):
        self.tasks: list[Task] = []

    def active_tasks(self) -> list[Task]:
        return [t for t in self.tasks
                if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]

    def has_active(self) -> bool:
        return any(t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
                   for t in self.tasks)

    def submit(self, task: Task, panel: Any, *, run: Callable[[Task], dict],
               on_done: Optional[Callable[[dict], None]] = None,
               z: int = 70, background: bool = True) -> Task:
        """Run ``run(task)``. In background mode: show a :class:`ProgressDialog`,
        spawn the worker, and pump the bridge + repaint each frame, closing the
        dialog and calling ``on_done(result)`` on the main thread when it ends. In
        synchronous mode (tests): run inline, ``ask`` resolves to its headless
        default, no dialog, ``on_done`` fires immediately."""
        self.tasks.append(task)

        if not background:
            task._headless = True
            task.status = TaskStatus.RUNNING
            result = self._run_inline(task, run)
            self._finish(task)
            if on_done is not None:
                on_done(result)
            return task

        dialog = ProgressDialog(task)
        dialog.show(panel, z=z)
        task.status = TaskStatus.RUNNING
        finished = threading.Event()

        def worker() -> None:
            try:
                task.result = run(task)
            except BaseException as exc:  # noqa: BLE001 — recorded, surfaced on tick
                task.error = exc
            finally:
                finished.set()

        threading.Thread(target=worker, name=f"xefm-task-{task.id}", daemon=True).start()

        def tick() -> bool:
            # Main thread: service at most one pending prompt (sequential), repaint
            # the live dialog, and on completion tear down + report the result.
            dialog.pump(panel)
            if not finished.is_set():
                panel.render()
                return True
            dialog.close()
            self._finish(task)
            if on_done is not None:
                on_done(task.result or _empty_result())
            return False

        panel.request_animation_ticks(tick)
        return task

    @staticmethod
    def _run_inline(task: Task, run: Callable[[Task], dict]) -> dict:
        try:
            task.result = run(task)
        except BaseException as exc:  # noqa: BLE001
            task.error = exc
        return task.result or _empty_result()

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


class ProgressDialog(Widget):
    """Modal progress surface for a running :class:`Task`. Generic — it renders
    only from ``task.title`` + ``task.progress`` (the :class:`ProgressManager`), so
    any task type reuses it:

    - **Preparing** (``ProgressManager`` still ``counting``): a :class:`BusyIndicator`
      and a "Preparing…" line — an indeterminate phase with no total yet.
    - **Running**: a determinate primary :class:`ProgressBar` (items done / total),
      the current file name, and a **secondary byte bar** shown only while the
      current file reports a byte total (large / remote copies).
    - **Cancelling** (derived from the cancel flag): a "Cancelling…" line until the
      worker unwinds.

    ``Esc`` opens a confirm box; confirming requests cancellation on the task. The
    dialog only *reads* progress state during ``draw`` — the worker mutates it."""

    focusable = True

    def __init__(self, task: Task):
        self.task = task
        self._panel: Any = None
        self._bar = ProgressBar()
        self._byte_bar = ProgressBar()
        self._busy = BusyIndicator(label="")
        #: True while a bridged prompt (conflict dialog) is on screen, so the pump
        #: shows one at a time and the worker's next request waits its turn.
        self._request_in_flight = False
        #: True while the cancel-confirm box is up, so Esc doesn't stack another.
        self._confirming_cancel = False

    # --- lifecycle -----------------------------------------------------------

    def show(self, panel: Any, z: int = 70) -> None:
        self._panel = panel
        self._z = z
        sw, _sh = panel.backend.size_units
        w = float(max(44, min(70, int(sw) - 4)))
        # title + current item + primary bar/label + secondary bar/label. The last
        # two rows are reserved whether or not the current file reports bytes: an
        # operation alternates between files that do and files that don't, and a
        # box that resized under each one would jitter for its whole run.
        h = 8.0
        panel.push_layer(self, z=z, hints={"shadow": True, "w": w, "h": h})
        animate_open(panel, self, OPEN_MS_VIEWER)

    def close(self) -> None:
        panel = self._panel
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()

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
        box_w, box_h = ctx.size_units
        ctx.draw_box(0, 0, box_w, box_h, box_style, hints={"fill": True})
        text_style = Style(bg=surface_bg)
        ctx.draw_text(2, 0.5, self.task.title, Style(bg=surface_bg, attr=TextAttribute.BOLD))

        op = self.task.progress.get_current_operation()
        width = max(1.0, box_w - 4)
        if op is None or op.get("counting"):
            self._draw_preparing(ctx, op, box_w, box_h, text_style)
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
        ctx.draw_child(self._bar, 2, 3.4, width, 1.0)
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
            ctx.draw_child(self._byte_bar, 2, label_y - 1.0, width, 1.0)
            ctx.draw_text(
                2, label_y,
                f"{format_size(bc, compact=True)} / {format_size(bt, compact=True)}",
                text_style)

    def _draw_preparing(self, ctx, op, box_w, box_h, text_style) -> None:
        ctx.draw_child(self._busy, 2, 3.0, 2.0, 1.0)
        n = self.task.counted
        label = f"Preparing… ({n} item{'s' if n != 1 else ''})" if n else "Preparing…"
        ctx.draw_text(4, 3.0, label, text_style)

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY and event.key == "escape":
            self._confirm_cancel()
        return True  # modal: swallow everything else

    def _confirm_cancel(self) -> None:
        """Esc: pop a confirm box (above this dialog); on Yes, request cancel. The
        worker keeps running while the user decides — cancel only takes effect if
        confirmed."""
        if self._confirming_cancel or self.task.cancelled() or self._panel is None:
            return
        self._confirming_cancel = True

        def on_result(label: str) -> None:
            self._confirming_cancel = False
            if label == "Cancel operation":
                self.task.request_cancel()
            if self._panel is not None:
                self._panel.render()

        show_message_box(
            self._panel, f"Cancel {self.task.title.rstrip('… ')}?",
            title="Cancel", icon="warning",
            buttons=("Cancel operation", "Keep running"),
            default=1, cancel=1, on_result=on_result, z=getattr(self, "_z", 70) + 5)
