# External Terminal — Implementation

Desktop mode's answer to "run this in a terminal" (discussion #472). User
documentation: [EXTERNAL_TERMINAL_FEATURE.md](../EXTERNAL_TERMINAL_FEATURE.md).

## Shape

One launcher, two callers:

```
subshell (Shift-X)          ─┐
PROGRAMS terminal: True     ─┼─► desktop:  XeFMApp._open_terminal → external_terminal
ctx.run_program(terminal=…) ─┘   terminal: XeFMApp._run_in_terminal (unchanged)
```

Both callers build the command, directory and environment exactly as before
and branch on `is_desktop_mode()` only at the point of delivery. The subshell
passes no `pause_on_error`; a program passes `pause_on_error=True`, as it does
to `_run_in_terminal`. The desktop path returns `None` at once — there is no
exit code to wait for — which is what `ctx.run_program` documents.

`subshell` left `_BACKEND_GATED`, and the Tools ▸ Subshell Here item lost its
`enabled` predicate: both frontends can perform it now.

## Why an external terminal

An embedded terminal (pty + VT parser in a PuiKit pane) is the only design that
would make desktop mode behave *identically* to the TUI, and it commits XeFM to
ConPTY, IME composition, East Asian width disagreements between shell and
renderer, and an open-ended escape-sequence tail — all solved better by the
terminal the user already chose. XeFM owns only which terminal, which
directory, which environment.

## `xefm/external_terminal.py`

- `default_terminal()` — `['open', '-a', 'Terminal']` on macOS; on Windows
  `['wt.exe']` when `shutil.which('wt')` finds it, else `[]` meaning "a new
  console window"; `None` elsewhere (desktop mode does not run there, and
  guessing a Linux terminal is not worth it until it does).
- `terminal_command(config)` — `TERMINAL` through `command_argv` (string or
  list, like `TEXT_EDITOR`), falling back to the default.
- `delivered_env(env)` — the variables the wrapper sets: those that differ from
  XeFM's own `os.environ`, minus `PATH`. That is `XEFM_*`, the prompt marker,
  and a `ctx.run_program` caller's extras. Everything else the terminal's own
  login shell sets up better; `PATH` especially, which XeFM only patched
  (`ensure_common_paths_in_env`) because a Finder-launched app lacks the user's.
- `write_wrapper(...)` / `launch_in_terminal(terminal, argv, cwd, env,
  pause_on_error)` — write the wrapper to a `tempfile.mkstemp` file named
  `xefm-terminal-*` and `Popen` `terminal + <run the wrapper>`, with stdio on
  `DEVNULL`. With `terminal == []` the wrapper is started directly under
  `CREATE_NEW_CONSOLE` and keeps its stdio. A failed `Popen` removes the
  wrapper again and re-raises; `_open_terminal` turns `NoTerminalError`,
  `FileNotFoundError` and anything else into a log line.

### The wrapper

A terminal application does not reliably pass its caller's environment on:
Terminal.app starts a fresh login shell, and `wt.exe` may hand the request to
an already-running Windows Terminal whose environment is its own. So the
command appended to `TERMINAL` is never the program itself but a generated
script that sets the variables, `cd`s, and then runs it. This makes delivery
independent of each terminal's behavior rather than something to verify per
terminal.

- **POSIX** — `#!/bin/sh`, every value through `shlex.quote`, mode `0700`,
  suffix `.command` on macOS (what Finder treats as "run in Terminal";
  `open -a Terminal x.command` runs it). Without `pause_on_error` the last line
  is `exec <argv>`, so the shell's exit ends the script the way a terminal's own
  shell does. With it, the command runs, a nonzero status prints a prompt and
  `read`s a line, and the status is passed on. Variable names `sh` cannot
  `export` are skipped. No `PATH` lookup happens in XeFM: the terminal's login
  `PATH` is the better one.
- **Windows** — a Python script run by `xefm_python` (the bundle's console
  `python.exe`). Batch quoting cannot carry `XEFM_*_SELECTED` — double-quoted
  names that may hold `&` or `%` — while `repr()` can. There is no `exec`, so
  the script `subprocess.call`s the command with `SIGINT` ignored in itself
  (Ctrl+C belongs to the command) and exits with its code. The argv is resolved
  through `resolve_command` in XeFM first, since `CreateProcess` ignores
  `PATHEXT`. A command that cannot start at all always pauses, or the window
  would close before the error is read.

Both remove themselves first thing. A wrapper whose terminal never ran it is
left behind in the temp directory; that is the only leak, and it is small.

## Still to verify by hand

These are properties of real terminals and packaging, not of the code above:

- **Terminal.app** runs `open -a Terminal <file>.command` as expected, and the
  `[XeFM]` prompt survives `/etc/zshrc` only via the `XEFM_ACTIVE` snippet (same
  as the TUI).
- **Windows Terminal** with window reuse: the new tab gets the variables through
  the wrapper even when an existing instance takes the request.
- **MSIX**: the packaged app can start `wt.exe` (an app execution alias) and the
  bundled `python.exe`, and the wrapper written to the packaged app's temp
  directory is readable from outside the package.
- **Window closing**: per terminal and profile setting, whether the window/tab
  closes when a `terminal: True` program exits cleanly.

## Out of scope

- `ssh://` panes: an external terminal could open `ssh -t host 'cd …; exec
  $SHELL'`, which the TUI cannot do at all — a separate thread.
- Talking back to the running XeFM (send a path list to a pane, sync a pane to
  the shell's directory) depends on the local socket planned for MCP.

## Tests

- `test/test_external_terminal.py` — terminal resolution, `delivered_env`, and
  both wrappers run for real (`sh`, and this interpreter for the Windows one)
  against awkward `XEFM_*_SELECTED` values, self-deletion, pause and exit codes.
- `test/test_run_program_output.py` — the subshell, the picker and
  `ctx.run_program` reach `launch_in_terminal` in desktop mode with the same
  env, cwd and pause they give `_run_in_terminal`.
- `test/test_help_backend.py` — the subshell row is listed in both frontends.
