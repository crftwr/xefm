# Background Jobs — Implementation

[#567](https://github.com/crftwr/xefm/issues/567) and
[#599](https://github.com/crftwr/xefm/issues/599), part 1 of discussion
[#468](https://github.com/crftwr/xefm/discussions/468). User-facing behavior is
in [`doc/BACKGROUND_JOBS_FEATURE.md`](../BACKGROUND_JOBS_FEATURE.md). The task
system it extends is described in
[TASK_FRAMEWORK_IMPLEMENTATION.md](TASK_FRAMEWORK_IMPLEMENTATION.md).

## What was already true

A `Task`'s worker already ran off the UI thread. What kept the user waiting was
the `ProgressDialog`: a modal layer, and while a layer is up `on_event`
routes every key to it. So "background" here means only this: **the dialog
leaves the screen while the worker goes on.** Nothing about the worker
changes.

## `TaskManager`

| Piece | |
|---|---|
| `_Job` | One running task: its dialog, `finished` event, `on_done`, `z` |
| `_Waiting` | One queue entry: a task not started yet (with its `run`, `on_done`, `z`), or a started one suspended (`job`) |
| `_slot` | The one background job allowed to run |
| `submit(..., detached=True)` | Queue the task; `_start_next` starts it when the slot is free |
| `detach(task)` | Close the dialog, set `task.background`; unless it holds the slot, suspend it and queue it |
| `bring_forward(task)` | Show the dialog again; a suspended queued task leaves the queue and resumes in front; a not-started one is dropped |
| `background_tasks()`, `running_task()`, `queued_count()`, `is_queued()` | For the status bar and the jobs list |
| `_tick(job)` | The per-frame pump, per job; teardown frees the slot and drops the task from the queue |
| `_start_next()` | Give the slot to the next queued job: resume a suspended one, or start one |

**The serial queue** (#599). At most one background job runs: the one in
`_slot`. #567 first queued only the jobs *started* detached. A job sent back
from the foreground kept running, so several ran at once, and the status bar,
which named one running job and the queue's length, under-reported them.
Now a job sent back that does not already hold the slot is **suspended
first, then queued**. Every background job in motion other than the slot's
is therefore in the queue and stopped. `_start_next` runs on every teardown
and every enqueue. The slot's job keeps the slot while it is brought forward,
so answering its prompt does not let the next one start. A foreground
`submit` does not join the queue, because the user chose to watch it, but
since #887 it does not write beside the slot's job either (below).

**Non-exclusive tasks** (#632). A task whose `exclusive` is False — one an
extension started with `ctx.run_task(..., read_only=True)`, and since #887
XeFM's own read-only tasks (`Task(..., exclusive=False)`: reading and finding
tags, document text, index search, flat view, list commands, both compares,
the download for a remote edit) — is outside the queue altogether: detached,
it starts at once; sent back, it keeps running. It holds up no writer, so
there is nothing to serialize it against. `background_tasks()` lists these
after the slot's job (`_beside()`), and `running_task()` names one when the
slot is free. Tag *writes* stay exclusive: they write, if only metadata.

**One writer at a time** (#887). A foreground writer used to run beside the
slot's job, and its conflicts were decided against that job's half-written
files. `_arbitrate()` (main thread) now holds the rule: the writers that
should run are the foreground exclusive jobs, or with none, the slot's job;
every other exclusive job is suspended, and one that should run is resumed
only once all the others are `paused`. So a foreground writer starts once
the slot's job has stopped at a file boundary, the slot's job resumes once
the foreground one finishes or is sent back (and, if sent back, has itself
paused), and a suspended job brought forward waits the same way.

- Every exclusive task is **suspended before its thread starts** (`_start`),
  and the worker's first act is a pausable `checkpoint()`; `_arbitrate`
  releases it. Suspending after the thread starts would leave a window in
  which it writes beside another writer.
- `_arbitrate` runs on every change to the set of writers (`submit`,
  `_start_next`, `detach`, `bring_forward`, teardown) and on every `_tick`,
  which is what notices that a job has paused.
- While held, `Task.waiting_for` is the blocker's title, and the
  `ProgressDialog` shows `Waiting for <title> to pause…` instead of its
  progress. A writer cancelled while it waits never runs: its result is
  `cancelled`.
- A held slot job reads `paused` in the jobs list and the status bar.

**Suspension.** `Task.suspend()` clears `_running`, and the worker waits at
its next **pausable** `checkpoint()`. `resume()` and `request_cancel()` both
release it; cancel unwinds as usual.

**`paused` counts threads** (#887). A copy has several threads (the walker
and its pool), so one thread stopped says nothing. `Task._inflight` holds the
threads at work: a thread enters it by passing a pausable checkpoint while
the task runs, and leaves it by stopping at one, waiting in `ask`, entering
`Task.idle()`, or `Task.leave()` (a pool job's end, the worker's end).
`paused` is suspended **and** `_inflight` empty. The check-and-enter in
`_join` and `suspend` / `resume` share `Task._lock`, so a thread cannot pass a
checkpoint unseen as the task is suspended. `idle()` is for a thread that
waits on something other than the disk: the walker draining its pool's
futures and shutting it down, a pool worker waiting its turn to ask. Leaving
`idle()` is a pausable checkpoint without the cancel. Without it, the walker
blocked on futures whose workers had paused would never count as stopped.
The checkpoints inside a transfer pass `pausable=False`: the remote byte
callback, and the local chunk loop, which may be filling a cache that is
streamed to a remote on close. A remote stream held for as long as another
job runs can time out, so a job pauses only between files. In the parallel
copy, each pool worker's per-file checkpoint is pausable, so the pool drains
the files in flight and then every worker waits. A task suspended while
blocked in `ask` stays there until brought forward, which resumes it.

**Prompts wait.** `Task.ask` already blocks the worker on a request that the
main thread services. The wait is `idle()`: a job blocked on a prompt writes
nothing, so it counts as paused. `_tick` now calls `dialog.pump` only while the task is
in the foreground. A background job's request stays queued.
`Task.needs_attention` (background and a request pending) is what the status
bar shows. `bring_forward` puts the dialog back, and the next tick's pump
opens the prompt. This is #468's option (a). Option (b), a policy chosen when
detaching, would sit in front of it later.

**Repaint.** A foreground job repaints every frame, as before. A background
one repaints every 0.25 s (`_BACKGROUND_REPAINT_S`), enough for the status
bar's percentage.

## `ProgressDialog`

It takes `on_background` (the manager's `detach`). Two `Button`s along the
foot, drawn the way PuiKit's message box draws its row: **Run in
background** (only when there is a manager to take it) and **Cancel**. Tab
and the arrows move focus, Enter and Space press, and a click is routed
through the rects captured in `draw`. The content above lays out in the
height that is left, floored to a whole unit so the foot-anchored rows keep
their spacing on a vector backend. The box grew from 10 to 12 rows for the
buttons.

The **B** key that #567 used is gone, because nothing on screen said it
existed. **Cancel** and Esc open the same box, **Cancel operation / Keep
running**. Keep running is both the default and the cancel button, so a
stray Enter or Esc changes nothing.

## `FileOperationService`

The `CONFIRM_*` box gains **Background** between the verb and Cancel, for
copy, duplicate and move when `background=True` (synchronous test runs have
no pump to run a detached task on). The defaults are unchanged: the verb.
Duplicate had none at first, for no recorded reason; #828 gave it one, since
duplicating a large tree takes as long as copying it. Delete and
trash had it too at first, and #601 took it away. A delete is usually over at
once, and on the permanent delete, whose default is Cancel, the button put
Delete two steps away from the focus. `_submit(..., detached=)` passes it through
to `TaskManager.submit`.

## The app

- `StatusBar.draw` draws `XeFMApp._jobs_parts()` at the right end, in the
  accent color, and the key hints give way to it. The segment is kept short
  (#599): `Copy 42% +2`, no key hint. Each part is `(kind, text)`. A `busy`
  part is drawn behind PuiKit's `BusyIndicator`, which runs its own animation
  ticks and is one cell wide on every backend. That is why it is not an
  emoji: emoji widths disagree between terminals, and an emoji ignores the
  accent color. `attention` (a job waiting on a prompt), `done` and `failed`
  get a still glyph, `⚠` or `✓`. An `attention` part is easy to miss as one
  more accent-colored word (#887 hand check), so `StatusBar._draw_jobs` draws
  it highlighted — the status surface's background as the ink, on the theme's
  text color — and blinks it: `_watch_attention` notes when a wait begins and
  registers an animation tick that repaints at each flip, half of each
  `_ATTENTION_PERIOD_S` (1 s) lit, for `_ATTENTION_BLINK_S` (10 s); then the
  tick ends and the part stays lit, so a job left waiting for an hour does not
  repaint the window for an hour. A backend that cannot tick shows the still
  highlight at once. One style on every backend, no capability branch. When the bar is short of room, the texts are
  elided and the marks are kept. The segment's rect is kept as `_jobs_hit`,
  and a click there opens `show_jobs`, the way `_clip_hit` opens the
  clipboard.
- `show_jobs` (action `jobs`, `Ctrl-G`, Tools → Background Jobs…) is a
  `ChoiceDialog` of `background_tasks()`. Each row is the title,
  `Task.detail` (set by `FileOperationService` through
  `describe_operation`: "12 items  ~/photos → s3://bucket", "3 items in
  ~/tmp"; a sync names its counts), and the state: percent with bytes,
  needs you, paused and queued, or queued. Choosing one calls
  `bring_forward`. The rows are live: `show_choice_dialog(..., refresh=)`
  makes the `ChoiceDialog` ask for them again on every draw and repaint
  itself every 0.5 s on its own animation tick. The selection stays on the
  same value, and the dialog closes when no rows are left.
- `confirm_quit` with background jobs names them and defaults to Cancel.
  Quitting anyway calls `TaskManager.cancel_all(timeout=3.0)`, which cancels
  the queue and every running task and waits for the workers to unwind at
  their next checkpoint (which removes a half-written file) instead of dying
  mid-write with the process. A worker still busy after three seconds is
  logged and abandoned.

`on_done` needed nothing new. A background job's completion runs the same
callback on the main thread, which refreshes the panes and logs the summary.

## Not done

From #468: delete to the trash, the operation journal and undo, a guard
against operating on paths a job owns, a conflict policy at detach time, and
parallel background jobs.

From #887: a foreground operation can still move or delete what a suspended
job reads from or writes to; that job reports errors when it resumes, and
nothing disappears silently. Two foreground writers at once (possible only
from code, since the progress dialog is modal) are not serialized against
each other.

## Tests

`test/test_background_jobs.py`, on the memory backend with real animation
ticks. Each task body waits on an `Event` the test releases, and calls
`checkpoint()` while it waits. Covered:

- detach: the dialog goes and the task completes;
- detached jobs running in order;
- a foreground task not waiting for the queue;
- a background prompt waiting until brought forward, then answered;
- dropping a queued job;
- the dialog's two buttons, the Background button, `B` no longer a key, and
  the Cancel confirm;
- a job sent back while another runs being suspended and finishing only after
  it, and one sent back to a free slot running on;
- a suspended job brought forward running in front, and a suspended job
  cancelled;
- `checkpoint(pausable=False)` not pausing;
- one writer at a time (#887): a foreground writer pausing the slot's job and
  that job resuming after it, the writer waiting (and saying so) while the
  job's file lands, a read-only task leaving it running, a waiting writer sent
  back, a writer cancelled while it waits, and `paused` over several threads;
- `describe_operation`, and the jobs list's detail and states;
- the copy confirmation's Background button copying with no dialog, and
  delete still defaulting to Cancel;
- the status bar text, the quit guard, and `cancel_all` waiting for the
  workers.
