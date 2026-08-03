# External Programs System

## Overview

The External Programs system lets users run configured external programs from
within XeFM with access to the current file-manager state through environment
variables. It also provides the interactive sub-shell feature.

The live launch path for the picker (**X**) is `XeFMApp._run_program` /
`_watch_program` in `xefm/app.py`; the shared helpers (environment building,
tool resolution) and the sub-shell live in `xefm/external_programs.py`. That
module's `ExternalProgramManager.execute_external_program` is the **legacy**
blocking launcher — it suspends the renderer and hands the terminal to the
child — and is currently not wired to the picker.

This document covers the implementation. For the interactive shell in
particular, see [SUBSHELL_SYSTEM.md](SUBSHELL_SYSTEM.md); for the user-facing
description see [External Programs Feature](../EXTERNAL_PROGRAMS_FEATURE.md).

## Architecture

### `ExternalProgramManager`

```python
ExternalProgramManager(config, log_manager, renderer=None)
```

The class holds the config, the log manager, and the active renderer, and
exposes two entry points:

| Method | Purpose |
|---|---|
| `execute_external_program(pane_manager, program)` | Run one configured program with XeFM environment variables set. |
| `enter_subshell_mode(pane_manager)` | Start an interactive shell (`$SHELL`) with the same environment. |

Both follow the same shape: set up the XeFM environment, suspend the renderer,
run the child process, then restore the renderer and stdio in a `finally` block.

### Module-level helpers

- `xefm_tool(tool_name)` — resolve a tool script to an absolute path, searching
  `~/.xefm/tools/` (user tools, highest priority) then the `tools/` directory
  next to the module (bundled tools; `xefm/tools/` in a source checkout). Returns
  the original name if not found, so execution fails later with a clear error.
- `xefm_python` — path to the correct Python interpreter, accounting for the
  macOS app bundle where a bundled `python3` lives inside the `.app`.
- `build_xefm_env(left_pane, right_pane, current_pane, other_pane)` — the
  `XEFM_*` variables as a dict, ready to merge into a subprocess environment.
  The single source of truth, shared by `_run_program`, the legacy manager,
  and the sub-shell.
- `quote_filenames_with_double_quotes(filenames)` — quote filenames with double
  quotes (escaping `"` and `\`) for safe use in the `XEFM_*_SELECTED` variables.
- `get_selected_or_cursor_files(pane_data)` — the selected files, or the file
  under the cursor when nothing is selected.
- `ensure_common_paths_in_env(env)` — on macOS, prepend common binary paths
  (`/usr/local/bin`, `/opt/homebrew/bin`, …) to `PATH`, since an app launched
  from Finder/Dock does not inherit the user's shell `PATH`.

## Configuration

External programs are configured as a `PROGRAMS` list in the config
(`xefm/_config.py`, overridable in `~/.xefm/config.py`). Each entry:

- `name` — display name.
- `command` — command as a list of arguments (executed without a shell, so no
  shell injection).
- `options` (optional) — `terminal` (bool, default `False`): divert the launch
  to `_run_in_terminal` so a full-screen program gets the tty (terminal mode
  only; desktop mode ignores it). `auto_return` is deprecated and ignored —
  `validate_config` emits a config warning naming the entries that still carry
  it (the legacy blocking launcher honored it; the picker never blocks).

```python
PROGRAMS = [
    {'name': 'Git Status', 'command': ['git', 'status']},
    {'name': 'Git Log', 'command': ['git', 'log', '--oneline', '-10']},
    {'name': 'My Tool', 'command': [xefm_python, xefm_tool('my_script.py')]},
    {'name': 'Python REPL', 'command': ['python3'],
     'options': {'terminal': True}},
]
```

## Environment variables

Before running a program (or the sub-shell), `ExternalProgramManager` copies the
current environment and adds:

- `XEFM_ACTIVE` — set to `'1'` to indicate XeFM launched the program.
- `XEFM_LEFT_DIR` / `XEFM_RIGHT_DIR` — left / right pane directory paths.
- `XEFM_THIS_DIR` / `XEFM_OTHER_DIR` — active / inactive pane directory paths.
- `XEFM_LEFT_SELECTED` / `XEFM_RIGHT_SELECTED` — space-separated, double-quoted
  selected filenames in the left / right panes.
- `XEFM_THIS_SELECTED` / `XEFM_OTHER_SELECTED` — same for the active / inactive
  panes.

If no files are selected in a pane, the file under the cursor is used instead.

The working directory is set to the active pane's directory, except when that
pane is browsing a remote path (e.g. S3), in which case it falls back to XeFM's
own working directory.

## Execution flow

### Live path: `XeFMApp._run_program`

The picker launches the program without blocking the UI, identically in
terminal and desktop mode:

1. Resolve arguments and working directory from the active pane (a virtual
   search-results pane passes absolute paths and runs from the search root;
   its `XEFM_THIS_DIR` / `XEFM_THIS_SELECTED` are overridden to match).
2. Build the environment: `ensure_common_paths_in_env` + `build_xefm_env`.
   An entry with `options {'terminal': True}` diverts here in terminal mode:
   `_run_in_terminal(command + args, cwd, env)` suspends the display via
   `backend.suspended()` and blocks until the child exits — the same hand-off
   `edit_file` and the sub-shell use. Desktop mode ignores the flag and
   continues below.
3. `subprocess.Popen` with `stdin=DEVNULL`, `stdout=PIPE`, `stderr=PIPE` — the
   child never touches the terminal. In TUI mode a direct write would corrupt
   the curses screen (newlines without carriage returns under raw mode); in
   desktop mode there may be no terminal at all.
4. `_watch_program` starts daemon reader threads that post complete lines to
   `XeFMApp._log_queue` — the same thread-safe channel as the app's own
   captured stdout/stderr, drained only by the UI thread — tagged `STDOUT`
   (dim) or `STDERR` (red). A waiter thread reports a nonzero exit code once
   both streams close.

Because stdin reads EOF on the piped path, interactive terminal programs must
opt into the hand-off with `options {'terminal': True}`.

### Legacy path: `ExternalProgramManager.execute_external_program`

Branches on `is_desktop_mode()`: in terminal mode it restores stdio, suspends
the renderer and gives the child the terminal, then waits for Enter unless
`auto_return` is set; in desktop mode it runs with `capture_output=True` and
echoes output to the log pane. Errors are logged with a hint to use
`xefm_tool()`, and a `finally` block resumes the renderer, re-initializes
colors, and restores stdio capture. Kept as the reference implementation for a
future terminal hand-off; not called by the app today.

## Comparison with sub-shell mode

| | External program | Sub-shell mode |
|---|---|---|
| Purpose | Run one specific program | Interactive shell session |
| Configuration | Pre-configured `PROGRAMS` list | Uses `$SHELL` |
| Environment | XeFM variables set | XeFM variables + `[XeFM]` prompt hint |
| Interaction | Program runs and exits | Full shell session |
| Use case | Quick operations, scripts | Extended command-line work |

`enter_subshell_mode` additionally sets a `[XeFM]` prefix on `PS1`/`PROMPT` and
logs snippets the user can add to their shell config to show the marker
themselves. See [SUBSHELL_SYSTEM.md](SUBSHELL_SYSTEM.md).

## Authoring external programs

Standards for scripts that integrate with XeFM, folded in from the former
External Programs Policy.

### Use environment variables, not arguments

External programs **must** read XeFM's environment variables rather than expect
command-line arguments. This keeps every program integrated with XeFM's
selection and navigation state in the same way, and lets a program adapt to the
user's current context automatically. (The picker *also* appends the selected
filenames as argv — a convenience for generic launchers like `open` — but XeFM
tools must not rely on it: the environment carries the full four-pane state,
argv only the active selection.)

Directory variables: `XEFM_THIS_DIR`, `XEFM_OTHER_DIR`, `XEFM_LEFT_DIR`,
`XEFM_RIGHT_DIR`. Selection variables (space-separated, double-quoted filenames):
`XEFM_THIS_SELECTED`, `XEFM_OTHER_SELECTED`, `XEFM_LEFT_SELECTED`,
`XEFM_RIGHT_SELECTED`. Status: `XEFM_ACTIVE` (set to `"1"` under XeFM).

### Script placement

Bundled end-user programs live in **`xefm/tools/`** and may be executable shell
scripts; user-specific tools go in `~/.xefm/tools/`. Reference them from a
`PROGRAMS` entry via `xefm_tool('script_name.sh')`, which resolves either
location to an absolute path. Follow a descriptive naming convention
(`descriptive_name.sh`).

`ConfigManager.ensure_user_tools_dir()` (called from `load_config()`, i.e. on
every launch) seeds `~/.xefm/tools/` with a copy of the bundled
`example_tool.py` — but only when the directory does not exist yet, so a
deleted example is never resurrected and user files are never overwritten. It
runs before the config module executes, so `xefm_tool('example_tool.py')` in a
config resolves to the user copy from the very first launch.

### Script structure

```bash
#!/bin/bash
# script_name.sh - Brief description
# Uses XeFM environment variables for integration.

# Validate the XeFM environment.
if [ -z "$XEFM_THIS_DIR" ]; then
    echo "Error: XeFM environment variables not set"
    echo "This script should be run from within XeFM"
    exit 1
fi

CURRENT_DIR="$XEFM_THIS_DIR"

if [ -n "$XEFM_THIS_SELECTED" ]; then
    # Parse selected files (properly handles quoted filenames).
    eval "SELECTED_FILES=($XEFM_THIS_SELECTED)"
    for file in "${SELECTED_FILES[@]}"; do
        [ -n "$file" ] && process_file "$CURRENT_DIR/$file"
    done
else
    # No selection — operate on the current directory.
    process_directory "$CURRENT_DIR"
fi
```

Guidelines:

- Always validate that XeFM variables are set; provide clear error messages and
  meaningful exit codes.
- Support both the "files selected" and "no selection" cases, and validate file
  existence before operating.
- Use `eval` to parse the quoted selection variables, and build absolute paths
  by joining `XEFM_THIS_DIR` with each filename, so spaces and special
  characters are handled correctly.
- When launching a GUI application, `unset` the `XEFM_*` variables first so
  they don't leak into an unrelated long-lived process.

### Registering the program

Add it to the `PROGRAMS` list in `xefm/_config.py` (or the user's
`~/.xefm/config.py`). Platform-specific programs can be appended conditionally:

```python
import platform

if platform.system() == 'Darwin':
    PROGRAMS.append({'name': 'macOS Program',
                     'command': [xefm_tool('macos_program.sh')]})
```

`auto_return: True` is deprecated and ignored (the picker never blocks); use
`terminal: True` for programs that need the tty.

## Related documentation

- [External Programs Feature](../EXTERNAL_PROGRAMS_FEATURE.md) — user documentation
- [Subshell System](SUBSHELL_SYSTEM.md) — interactive sub-shell details
- [Configuration System](CONFIGURATION_SYSTEM.md) — configuration management
