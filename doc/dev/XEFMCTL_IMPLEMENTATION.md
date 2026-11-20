# xefmctl: Implementation

`xefmctl selected`, `xefmctl cd .` and friends from a shell XeFM started
(discussion #900, "Interaction between the file manager and a persistent
shell", channel 1). User documentation:
[TERMINAL_FEATURE.md](../TERMINAL_FEATURE.md#asking-xefm-from-the-shell).

## Why

A shell that keeps running cannot use the `XEFM_*_SELECTED` snapshot: it is
stale from its first prompt on. Each `xefmctl` command instead asks the
running XeFM for its state at that moment.

It was first called `xefm`, which collided with the command that starts
XeFM: `xefm ext check` and `xefm selected` read as one program, and a shim
named `xefm` had to forward everything it did not know to the real one. The
in-shell command has its own name now and answers only its own commands.

It is the one channel to XeFM. MCP was considered for agents (#880), but an
agent running in a shell XeFM started can run `xefmctl` like any command and
read `xefmctl --help`, and the key is only in XeFM's own children either way.
If MCP is wanted later, it is a thin `xefmctl mcp` (a stdio server over the
same socket), not a second protocol.

## Pieces

```
shell ── xefmctl (shim on PATH) ── python -I remote_cli.py ──┐
                                                              │ multiprocessing.connection
XeFM:  RemoteServer (listener thread) ── XeFMApp._remote_handle ── _call_later ── _remote_answer (UI thread)
```

- `xefm/remote_cli.py`: the client. Standard library only, run as a script
  with `-I` (safe path: `xefm/` is not put on `sys.path`, so no XeFM module
  can shadow the stdlib). An unknown command is a usage error (exit 2).
  Messages are ASCII (`test_stream_text_ascii`), stdout/stderr use
  `errors="replace"`.
- `xefm/remote_server.py`: the listener. `multiprocessing.connection` gives
  a Unix socket (in a `mkdtemp` 0700 directory) or a named pipe (Windows)
  with an HMAC challenge on a per-process 32-byte key before any request byte
  is read. Requests and answers are JSON (`send_bytes` / `recv_bytes`, at
  most 64 KiB), never pickles. One thread accepts; each connection is
  answered on a short-lived thread. A `weakref.finalize` removes the
  directory at exit even when `close()` never runs.
- The shim: `bin/xefmctl` (`sh`) or `bin\xefmctl.cmd` in the same directory,
  running the client with `external_programs.xefm_python`, so it works from
  the app bundles, where nothing of XeFM's is on the system `PATH`, and
  answers without importing the UI. There is no pip entry point: the shim is
  first on `PATH` in every shell XeFM starts, the only place the command
  means anything.

## Environment

`XeFMApp._with_remote_env(env, session)` (starting the server lazily, once):

| Variable | Value |
|---|---|
| `XEFM_SOCKET` | the address |
| `XEFM_TOKEN` | the key, hex |
| `XEFM_SESSION` | the terminal session's id, or `subshell` (terminal mode), `program` (a background `PROGRAMS` / `ctx.run_program` launch) |
| `XEFM_PYTHON` | XeFM's interpreter |
| `XEFM_BIN` | the shim directory |
| `PATH` | the shim directory prepended |

Given to every terminal session (`_start_session`), terminal mode's subshell
and every `PROGRAMS` / `ctx.run_program` launch (`_program_env`).

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
`cd` (`_resolve_jump_target` against the pane, then `_go_to_dir`; a file
lands the cursor on it), `view` (`_view_on_file_manager`), `screen list`,
`screen switch ID` (`_show_screen`; desktop only) and `session list`.

The grammar (#952): a command about a pane is one verb (`selected`, `cd`,
`view`); one about anything else is a noun and a verb, sent as
`{"cmd": noun, "verb": verb}` (`VERBS` in the client). Every command acts on
the file manager, whichever session it comes from: `view` opens on the file
manager's screen and switches there (#951), so the switcher goes back to the
terminal for a side-by-side look. `sessions` became `session list`; it was
out in 1.17.0 RCs only, so no alias is kept.

## Exit reports: `ctx.run_program(on_done=)`

`_launch_program(..., on_exit=)` calls `on_exit(code)` on the UI thread (via
`_call_later`, so never inside the call) on every path: terminal mode's
hand-over, a terminal session (`Session.on_done`, when it ends), the
background waiter thread, and a launch that failed or found no terminal
(`None`). The socket is no longer involved: the `TERMINAL` window and its
wrapper's `xefm _exited` report are gone with `TERMINAL` itself.

`on_done` is a new optional parameter on the stable `run_program`; the
docstring and the docs mark it Preview.

## Not yet

- More commands - selection, `action NAME`, `view -` and the rest - are
  discussed in #952.
- MCP and hooks on the same socket (#880), as `xefmctl` subcommands.

## Tests

`test/test_remote.py`: argument parsing, a real server round trip, a wrong
key, the server gone, the shim run as its own process, what the app answers,
the hand-over rule, and that `xefmctl` forwards nothing.
`test/test_run_program_on_done.py`: `on_done` on every launch path.
