# UI Watchdog System

XeFM's rule is that no slow work runs on the UI thread: a listing goes through
[`ASYNC_LISTING_SYSTEM.md`](ASYNC_LISTING_SYSTEM.md), a file operation through
[`xefm/task.py`](../../xefm/task.py). Nothing enforced that rule. A path that
broke it did not fail a test or raise — the app stopped repainting for a moment
and the user reported "it froze", with no way to say where. The `performance`
label's history is that report, filed over and over, each time found by hand:
archive creation (#280), S3 bucket listing (#274), TAB completion (#246),
Compare and Select (#245), long listings on a NAS (#183), drag & drop (#172).

The detector answers it once: when the UI thread stops for longer than a
threshold, the stack it is stuck in is written to the log.

**The detector itself is PuiKit's** — it brackets the event loop, animation
ticks and timer callbacks, so it can only live where those are. Its design,
report format and limits are in
[`../../../puikit/docs/ui_watchdog.md`](https://github.com/crftwr/puikit/blob/main/docs/ui_watchdog.md).
This document covers only XeFM's two contributions.

Source: [`xefm/app.py`](../../xefm/app.py) (`create_parser`, `main`),
[`xefm/log_manager.py`](../../xefm/log_manager.py) (`route_library_logger`).
Tests: [`test/test_ui_watchdog.py`](../../test/test_ui_watchdog.py).

---

## 1. Turning it on for one run

```bash
python -m xefm --ui-watchdog            # report stalls over 250 ms
python -m xefm --ui-watchdog 500        # ...over 500 ms
```

`main` copies the value into `PUIKIT_UI_WATCHDOG` **before** `create_backend`,
because PuiKit reads the variable when the backend opens. Setting the variable
directly works the same way, which is what the tests and CI do.

It is a command-line switch rather than a config setting on purpose: it belongs
to the run being investigated, not to the user's configuration. Off by default,
and while off it costs an `is None` per event.

## 2. Getting the reports into the log pane

PuiKit logs under `puikit.*`, which is not one of XeFM's loggers, so
`getLogger` never attached the sink handler to it and Python fell back to
`logging.lastResort` — everything below WARNING dropped, the rest written
unformatted to a `sys.stderr` that a GUI-subsystem process does not have.

`route_library_logger("puikit")`, called from `main`, hangs XeFM's own
`_sink_handler` on that logger. Reports then arrive in the log pane formatted
like every other line, and the ones logged before the pane exists (the
watchdog's own "on" notice, emitted while the backend opens) are buffered and
replayed like every other early record — see
[`LOGGING_SYSTEM.md`](LOGGING_SYSTEM.md).

The bridge is not watchdog-specific: PuiKit's other diagnostic (an animation
tick callback that raised, and was dropped) now reaches the pane too.

---

## Reading a report

```
14:22:07 [puikit._watchdog] WARNING: UI thread blocked 312 ms in key 'f5'
14:22:07 [puikit._watchdog] WARNING:   xefm/app.py:2140 in _reload_pane    ...
14:22:08 [puikit._watchdog] WARNING: UI thread unblocked after 1.2 s in key 'f5'
```

The label names the unit of work (the event, `animation tick`,
`timer callback`); the frames under it are the UI thread's, innermost last. A
stall that keeps going is reported again as it grows, so one that *moves* is
visible rather than frozen at the first sample.

Two things that look like stalls and are not, and which PuiKit already excludes:
a native menu the user is holding open, and a shell-out to an external program
(`backend.suspended()`), where XeFM blocks the UI thread on purpose until the
editor exits.

## What it does not cover

Work outside the event loop's three seams: module import, config loading, and
app construction all happen before the loop starts. A stall there is a slow
*startup*, which is visible on its own.
