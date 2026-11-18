# The xefm Command: Implementation

`xefm selected`, `xefm cd .` and friends from a shell XeFM started
(discussion #900, "Interaction between the file manager and a persistent
shell", channel 1). User documentation:
[CONSOLE_FEATURE.md](../CONSOLE_FEATURE.md#asking-xefm-from-the-shell).

## Why

A persistent shell cannot use the `XEFM_*_SELECTED` snapshot: it is stale
from its first prompt on. Each `xefm` command instead asks the running XeFM
for its state at that moment. The same socket is meant to carry the MCP
bridge, one-shot results and hook reports later (#880); only the shell
commands exist so far.

## Pieces

```
shell ── xefm (shim on PATH) ── python -I remote_cli.py ──┐
                                                           │ multiprocessing.connection
XeFM:  RemoteServer (listener thread) ── XeFMApp._remote_handle ── _call_later ── _remote_answer (UI thread)
```

- `xefm/remote_cli.py`: the client. Standard library only, run as a script
  with `-I` (safe path: `xefm/` is not put on `sys.path`, so no XeFM module
  can shadow the stdlib). Commands it does not know (`ext`, `--help`) are
  `exec`ed as `XEFM_PYTHON -m xefm ...`. Messages are ASCII
  (`test_stream_text_ascii`), stdout/stderr use `errors="replace"`.
- `xefm/remote_server.py`: the listener. `multiprocessing.connection` gives
  a Unix socket (in a `mkdtemp` 0700 directory) or a named pipe (Windows)
  with an HMAC challenge on a per-process 32-byte key before any request byte
  is read. Requests and answers are JSON (`send_bytes` / `recv_bytes`, at
  most 64 KiB), never pickles. One thread accepts; each connection is
  answered on a short-lived thread. A `weakref.finalize` removes the
  directory at exit even when `close()` never runs.
- The shim: `bin/xefm` (`sh`) or `bin\xefm.cmd` in the same directory,
  running the client with `external_programs.xefm_python`, so it works from
  the app bundles, where no `xefm` is on the system `PATH`, and answers
  without importing the UI.
- `app.main()` also dispatches these commands, for a pip-installed `xefm`
  that comes before the shim on `PATH` (a login shell's `path_helper`). A
  directory named like a command is still opened when no `XEFM_SOCKET` is set.

## Environment

`XeFMApp._with_remote_env(env, session)` (starting the server lazily, once):

| Variable | Value |
|---|---|
| `XEFM_SOCKET` | the address |
| `XEFM_TOKEN` | the key, hex |
| `XEFM_SESSION` | the console session's id, or `subshell`, `program`, `console` (a `TERMINAL` window) |
| `XEFM_PYTHON` | the interpreter the shim and forwarding use |
| `XEFM_BIN` | the shim directory |
| `PATH` | the shim directory prepended |

Given to console sessions, the subshell (both modes), every `PROGRAMS` /
`ctx.run_program` launch (`_program_env`) and the console opened through
`TERMINAL`. The external terminal wrapper does not deliver `PATH` (the
terminal's own shell sets it up better), so both wrappers prepend
`$XEFM_BIN` themselves.

The key says a request comes from a shell XeFM started; it does not keep out
other processes of the same user, which can read it from that shell's
environment.

## Answering

`_remote_handle` runs on a request thread. It queues `_remote_answer` with
`_call_later` and waits up to `_REMOTE_WAIT` (8 s, under the client's 10 s),
so pane state is only touched on the UI thread. Modal dialogs do not block
it: the pump runs between frames.

Terminal mode's hand-over (`_terminal_handed_over`) parks the UI thread in
the child's wait, so nothing would ever run the queued call. The read-only
commands (`_REMOTE_READS`) are answered directly then, which is safe for
the same reason; `cd` and `view` are refused with a message.

`_remote_answer`: `pwd`, `selected` (pane order, selection only), `focused`,
`sessions`, `cd` (`_resolve_jump_target` against the pane, then
`_go_to_dir`; a file lands the cursor on it) and `view` (`_open_viewer`).

## Not yet

- The session registry built from socket registrations, so shells in a
  `TERMINAL` window appear in the session list (#900).
- MCP and hooks on the same socket (#880).

## Tests

`test/test_remote.py`: argument parsing, a real server round trip, a wrong
key, the server gone, the shim run as its own process, what the app answers,
the hand-over rule, and the wrapper's `PATH` line.
