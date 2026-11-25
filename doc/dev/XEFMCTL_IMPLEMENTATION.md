# xefmctl: Implementation

`xefmctl` from a shell XeFM started (discussions #900, #951, #952). User
documentation: [XEFMCTL_FEATURE.md](../XEFMCTL_FEATURE.md).

## Why

A shell that keeps running cannot use the `XEFM_*_SELECTED` snapshot: it is
stale from its first prompt on. Each `xefmctl` command instead asks the
running XeFM for its state at that moment.

Its first user is an AI agent in a terminal session XeFM started, with the
`xefm` skill, beside a user looking at XeFM (#952). That decided the shape:

- **One vocabulary.** A command is an `ActionContext` call, named the same
  with `-` for `_`: `pane cd` is `ctx.pane.cd`, `invoke` is `ctx.invoke`, a
  list is `X list` for `ctx.Xs()` (`screen list` for `ctx.screens()`). The
  skill already teaches the API for extensions, so the agent learns one set
  of names. A command that runs a search is named after the action that
  opens it (`find-files`, `find-in-files`, `index-search`).
- **Nothing exists only in xefmctl.** What the API lacked was added to it
  first, as Preview: `ctx.view`, `ctx.find_files`, `ctx.find_in_files`,
  `ActionInfo.details`; then (#962) `ctx.index_search` and `ctx.entries`
  (which `index-search` and `entries` had reached around), `ctx.find_similar`,
  `ctx.path_schemes`, `ctx.tags` / `add_tags` / `remove_tags`,
  `ctx.attributes` / `get_attributes`, `ctx.rename`, `pane.pick`,
  `pane.selected_or_focused` and `pane.shows_list`. Extensions get them too.
- **Freer than an action in one way only** (#962). An action takes its items
  from the pane (the folder, or the selection); the API and xefmctl are told
  them - any number, anywhere XeFM can go - and do with each what the action
  does: a folder is searched below, a file is itself
  (`tree_walk.walk_root`, the `named_root` of the search iterators).
  `--from pane|selection` takes the items from the pane the same way for
  every command that takes them (`_from_pane`): `pane` is
  `PaneApi.path`, or `PaneApi.entries` when `shows_list`; `selection` is
  `selected_or_focused()`. A test holds that every command with item
  arguments takes `--from`.
- **`xefm` vs `xefmctl`.** `xefm` works without a running XeFM (`config
  check`, `ext`, `keys`, `skill`, `ext guide`); `xefmctl` acts on the one
  running.
- **Orientation in one call** (`state`), `--json` on every command (JSON
  Lines), streamed searches, `--wait` where the user takes part, and
  refusals that say why, with an exit status.

It was first called `xefm`, which collided with the command that starts
XeFM. MCP was considered for agents (#880), but an agent in a shell XeFM
started can run `xefmctl` like any command and read `xefmctl help --json`. A
sandboxed shell cannot reach the socket, so an agent's session also gets the
commands as MCP tools, over HTTP
([AI_AGENT_SANDBOX_SYSTEM.md](AI_AGENT_SANDBOX_SYSTEM.md)).

## Pieces

```
shell ── xefmctl (shim on PATH) ── python -I remote_cli.py ──┐
                                                              │ multiprocessing.connection
XeFM:  RemoteServer (listener) ── remote_dispatch.handle ── _call_later ── handler (UI thread)
```

- `xefm/remote_commands.py`: **the command table**. Each `Command` has its
  words, arguments (`Arg`: nargs, a path, `-` for stdin), options (`Opt`),
  its effect (`read`, `change`, `write`, `ask`), how an item reads as text,
  whether it streams and whether it waits. The parser, `xefmctl help`,
  `help --json` (`describe()`) and the skill's `references/xefmctl.md`
  (`reference_markdown()`, written by `make skill-references`) are all made
  from it. Standard library only.
- `xefm/remote_cli.py`: the client, standard library only, run as a script
  with `-I` (safe path: `xefm/` is not on `sys.path`). It loads the table by
  path. It parses (paths relative to the shell's directory; URLs as they
  are; `-` reads paths or JSON lines from stdin), sends one request, prints
  each answered chunk as it arrives (text from the command's format, or
  JSON with `--json`), and exits with the answer's `status`. A command that
  streams, waits for the user, or may be confirmed first (a write, `read`,
  `fetch`) is waited on with no time limit; others time out after 10 s.
- `xefm/remote_server.py`: the listener. `multiprocessing.connection` gives
  a Unix socket (in a 0700 `mkdtemp` directory) or a named pipe with an HMAC
  challenge on a per-process key before any request byte is read. Requests
  and answers are JSON, never pickles. A request is at most
  `remote_commands.MAX_REQUEST` (8 MiB: it carries what `show-markdown -`
  and `pane open-list -` read from stdin); the client refuses a longer one
  with exit 2 before sending, since the listener can only drop it. An answer that is an iterator is sent
  as several, all but the last marked `more`; the iterator is closed when
  the client goes away (Ctrl-C ends a search).
- `xefm/remote_dispatch.py`: what each command does. `handle()` runs on the
  request thread, queues the handler on the UI thread (`_call_later`) and
  waits up to 8 s for it to *start*: only then is XeFM "busy" (exit 4), and
  a request refused that way is dropped when the UI thread reaches it.
  While terminal mode has handed the terminal over (`_terminal_handed_over`)
  the UI thread is parked in the child's wait, so `READ` commands are
  answered on the request thread and the rest refused with exit 6
  (`SUSPENDED`), not 4: it lasts until the shell exits, and an agent that
  took it for "busy" would retry (#961). `state` carries `suspended`, and
  `remote_commands.needs_screen()` marks those commands in the help and
  the skill's reference.
  Work that has started is waited for however long it takes; past 2 s
  (`ACK_AFTER`) the client is sent an empty answer first, so it stops
  timing out, then the real one. The client keeps the `status` and `note`
  of whichever piece carried them. A handler returns an answer, a `Pending` (the
  request thread then waits for a dialog's callback or an operation's
  `on_done`), or an iterator built on the UI thread and run on the request
  thread (a search reads off the UI thread, as the search dialog's worker
  does).
- The shim: `bin/xefmctl` or `bin\xefmctl.cmd`, running the client with
  `xefm_python`, first on `PATH` in every shell XeFM starts. In the Store
  package it calls the package's app execution alias instead (below).

## The Store (MSIX) package (#983)

Nothing under `C:\Program Files\WindowsApps` can be started by a process
without the package's identity: `CreateProcess` fails with
`STATUS_ACCESS_DENIED` ("Access is denied"), although the files stay
readable. And no shell XeFM starts has the identity: Windows starts a
child whose program lies outside the package (`cmd.exe`, `pwsh.exe`,
`bash.exe`) without it, while a child inside the package keeps it. So the
shim's `runtime\python.exe` was refused from every shell, cmd included,
while a `PROGRAMS` entry that XeFM starts as `[xefm_python, ...]` works.

(Checked on an installed package by asking each process
`GetPackageFullName`: `XeFM.exe` has the identity, the terminal session's
`cmd.exe` under it has none. Through ConPTY, `runtime\python.exe` started
directly kept it and `cmd.exe` -> `runtime\python.exe` was refused.
`Invoke-CommandInDesktopPackage` is no stand-in for this: it puts the
process it starts into the package whatever its program, which is how the
first look at #983 wrongly concluded that cmd worked.)

The way in from anywhere is an app execution alias. The manifest
(`windows_app/build_msix.ps1`) declares `xefmctl.exe` as one; Windows puts a
stub in `%LOCALAPPDATA%\Microsoft\WindowsApps`, and the stub starts the
target with the package's identity. An alias names an `.exe` of the same
file name and carries no arguments, so `xefmctl.exe`
(`windows_app/src/xefmctl.c`) bakes in `runtime\python.exe -I
app\xefm\remote_cli.py`, forwards its arguments verbatim, its standard
handles and the exit status, and leaves Ctrl-C to the client. Keyhac's
`keyhac-mcp-bridge.exe` is the same thing for the same reason.

`remote_server.windows_shim()` picks the shim's line:

- no package identity (`GetCurrentPackageFullName` answers
  `APPMODEL_ERROR_NO_PACKAGE`): the interpreter, as before;
- package identity and the stub present (`os.path.lexists`: it is a
  reparse point): the stub;
- package identity and no stub (the user turned the alias off): a line
  saying how to turn it on, exit 3. Never the interpreter's path, which
  exists there and cannot work.

The stub also puts `xefmctl` on the `PATH` of every shell, where without
`XEFM_SOCKET` it says it is not in a shell XeFM started.

What a shell cannot do there stays undone: it cannot start anything else
in the package either. That is accepted and written in the user doc.
`XEFM_PYTHON` (XeFM's interpreter, in 1.17.0 only, undocumented and read by
nothing) was removed rather than hand every Store shell a path it can never
run; the config's `xefm_python` stays, since XeFM starts it itself.

## Session keys and policies

`RemoteServer.register(session, policy)` hands out a key per shell
(`XEFM_SESSION_KEY`); `apply_env(env, session, policy)` puts it in the
environment with the rest. The server reads the request's key and sets
`session` and `policy` from it, so a request cannot pass for another
session by changing `XEFM_SESSION`; a missing or unknown key is refused
(exit 3). Policies: `user` (the subshell, terminal sessions, programs) and
`agent` (an `AGENTS` entry with `restrict`, see
[AI_AGENT_SESSIONS_IMPLEMENTATION.md](AI_AGENT_SESSIONS_IMPLEMENTATION.md)).

| Variable | Value |
|---|---|
| `XEFM_SOCKET` | the address |
| `XEFM_TOKEN` | the connection key, hex |
| `XEFM_SESSION_KEY` | this shell's own key |
| `XEFM_SESSION` | the session's id, `subshell`, `program` or `agent`, to read |
| `XEFM_BIN` | the shim directory |
| `PATH` | the shim directory prepended |

The keys say which shell XeFM started asks; they do not keep out other
processes of the same user, which can read them from a shell's environment.

## The gate: only what a hand could do

A command whose effect is not `read` is checked against the file manager's
screen (`files_top()`: its topmost layer, shown or hidden):

- the panes on top: let in;
- a viewer (a layer with `palette_actions`): let in, except `invoke` of an
  action outside the `common` context;
- anything else (a dialog, a menu, the palette): refused, exit 5, naming it.

`message`, `screen show` and `terminal-session start|close` are not about
that screen and skip the gate.

What a command opens lands on the file manager's screen whichever screen is
shown: `on_files()` sets PuiKit's default layer parent to the file manager's
group for the duration. `_bring_user()` then switches there when a layer
was added; a question asked for the agent (`_ask`, the remote-read
question) returns the user to the asking screen once answered, and an
agent's write once it has ended or been declined (`_go_back`).

`view`, `diff` and `show-markdown` switch to the file manager first and close
its viewers inside `dialog_geometry.no_motion()`, which makes
`close_viewer`'s fade a no-op: the old viewer is gone before the new one
arrives. Two viewers open at once, the second unclosable while the first's
fade never completed, was the bug that started this.

Terminal mode's hand-over parks the UI thread in the child's wait: `read`
commands are answered on the request thread then (`--show` dropped), the
rest refused with exit 4.

## Commands

| Command | Through |
|---|---|
| `state` | `PaneApi` for both panes, `ScreenManager`, `files_top()` |
| `pane path\|entries\|focused\|selected\|cd\|select\|unselect\|open-list\|refresh\|activate` | `PaneApi` (`cd`: `_resolve_jump_target` first; a file lands the cursor on it) |
| `entries` | `ctx.entries` (`path.listdir_attrs`, or `tree_walk.walk` with `--recursive` / `--depth`) |
| `find-files`, `find-in-files` | `ctx.find_files`, `ctx.find_in_files` (the search dialog's iterators, with `named_root`) |
| `index-search` | `ctx.index_search` (`_iter_index_matches`), once per root |
| `find-similar` | `ctx.find_similar`: `similar_scan.start`, polled until the job ends, then its `result.xft` read with `xft.parse`; `--threshold` names map through `threshold_steps` |
| `path-scheme list` | `ctx.path_schemes` (`path_schemes.schemes()`, the package from `extensions.package_of`) |
| `--show` | `_feed_search_results` (a search), `pane.cd` to the result's `xft://` URI (`find-similar`) or `PaneApi.open_list` (`entries`) |
| `--from` | `_from_pane` / `_roots` / `_operands`; the client makes the item arguments optional with it and refuses both |
| `read`, `fetch` | `Path.open("rb")` |
| `view`, `diff`, `show-markdown` | `ctx.view`, `ctx.diff` / `show_directory_diff_viewer`, `ctx.show_markdown` |
| `copy`, `move`, `trash`, `delete` | `ctx.copy` / `move` / `trash` / `delete`, `on_done` for `--wait` |
| `rename` | `ctx.rename` → `_rename_for_api`: `parse_plan` over the names (one line each), the Rename in Editor review without Edit Again, `apply_plan`. The client reads `--plan` (a file or `-`) and makes its paths absolute |
| `tag list\|add\|remove` | `ctx.tags` (`_known_tags`), `ctx.add_tags` / `remove_tags` → `_change_tags_for_api` (`_rewrite_tags`, a task for a store that is not cheap). An agent's session is asked first (`_write(ask_agent=)`): the tag write has no confirmation of its own |
| `attribute list\|get` | `ctx.attributes`, `ctx.get_attributes` → `attributes.compute` (one provider call per folder; a folder's `size` through `UsageScan`) |
| `pane pick` | `PaneApi.pick` → `_start_pick`; `on_event` hands Enter / Esc to `_pick_key` before the keymap while one is open |
| `confirm`, `choose`, `input`, `message` | `ctx.confirm` / `choose` / `input` / `message` |
| `action list`, `action show` | the registry, keys from `app.keys`, the package from `extensions.package_of` |
| `invoke` | `ctx.invoke` |
| `screen list\|show`, `terminal-session list\|start\|close` | `ScreenManager`, `ctx.start_terminal_session`, `_close_session` |

`action show` appends the package's agent guide (`[extension] agent_guide`)
for an action that comes from an extension: an agent in the app bundle has
no `xefm` on `PATH` for `xefm ext guide`.

## Exit reports: `ctx.run_program(on_done=)`

`_launch_program(..., on_exit=)` calls `on_exit(code)` on the UI thread on
every path (unchanged by #952).

## Tests

`test/test_xefmctl_962.py`: a named root (file as itself), `--from` for
every command, the new APIs and commands, the pick keys, rename's review.
`test/test_remote.py`: the table (every command has a handler and a
reference entry, names), parsing, help, a real server round trip with
session keys, streamed answers, exit statuses, the shim as its own process,
what XeFM answers, the hand-over rule, the remote-read question.
`test/test_xefmctl_msix_983.py`: the shim's three lines, the manifest's
alias, the launcher's client path against the tree, the shim as cmd runs it.
`test/test_terminal_sessions.py`: screens, `view` replacing a viewer at
once, the gate, an agent's writes and refusals, forced confirmations on
`invoke`. `test/test_run_program_on_done.py`: `on_done` on every launch path.
