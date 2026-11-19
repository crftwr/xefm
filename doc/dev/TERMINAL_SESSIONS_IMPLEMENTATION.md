# Terminal Sessions: Implementation

The desktop app's terminal (discussion #900). User documentation:
[TERMINAL_FEATURE.md](../TERMINAL_FEATURE.md).

## One kind of session

Everything the desktop app runs in its terminal is a terminal session:
PuiKit's `TerminalView` (libghostty-vt over a pty) wrapped by
`xefm.terminal.TerminalView`, registered in
`xefm.terminal_sessions.SessionRegistry` (`XeFMApp._sessions`). Started by:

| | kind | how |
|---|---|---|
| `subshell`, `toggle_terminal` with none, the list's "New shell" | shell | `_new_shell_session` → `_start_session(shell=True)` |
| `'terminal': True` from `PROGRAMS`, Open With, `ctx.run_program`, `TEXT_EDITOR`, `TEXT_DIFF`, `FILE_ASSOCIATIONS` | program | `_start_program` / `_run_configured` → `_start_session(shell=False)` |

Each can be hidden (`terminal.hide`, `_hide_session`) and keeps running. The
kind decides only the end:

| | shell | program |
|---|---|---|
| clean exit (shown or hidden) | session closes | session closes, then `on_done(code)` |
| failed exit | exit bar; Enter restarts (PuiKit), Esc hides | exit bar; Enter / Esc close, then `on_done(code)` |
| failed while hidden | `attention` in the status bar | the same |

This replaced two policies, a modal one-shot (`_run_in_terminal_view`) and
the persistent "console", which were one mechanism with two names. A
subshell started for a quick look closes on `exit` as before; one that
turned into a long task is hidden instead of being restarted elsewhere.

An earlier draft kept result-returning launches (`on_done`, pickers) modal.
That was unnecessary: `on_done` fires when the session ends, shown or not.
What a late result may then do to the panes is Discussion #946's question,
not this module's.

Terminal mode has no sessions: `_run_in_terminal` hands the terminal over and
waits. `toggle_terminal` and `terminal_sessions` are in `_BACKEND_GATED`
(palette, help) and `_terminal_menu` (menu) for the desktop only, and log a
note when a binding reaches them in terminal mode (`_desktop_only`). The
parity difference is that one: the desktop can keep a shell running behind
the panes.

## `xefm/terminal_sessions.py`

UI-free, so it is tested on its own:

- `Session`: the view, `kind` (`shell` / `program`), `name`, `cwd`, a
  process-unique `id` (what `XEFM_SESSION` says), `on_done`; `state`,
  `running` and `busy` read the view.
- `SessionRegistry`: sessions in start order, `last` (what the toggle shows;
  `touch` on every show, the next newest after a remove), `for_view`,
  `running()`, `busy()` (what quitting asks about), `next_name` (`zsh`,
  `zsh 2`, ...).

## Showing, hiding, closing

- `_show_session` removes another session's layer at once (crossing two
  terminals through the file manager would only flash the panes), then
  `_push_terminal`: above every layer already up (a session opened from a
  viewer's edit key must take the keys), with the `animate_from_behind`
  entrance.
- `_hide_session` plays `animate_from_behind(out=True)` and removes the layer
  on completion **without** `view.close()`. The child keeps its pty; its
  output still reaches libghostty through `call_on_main_thread`. `view.closing`
  swallows input while it fades and is reset when it lands; `view.shown`
  says which session is on screen. The panes re-read.
- `_close_session` returns at once if the session is already gone (a second
  close while the first fades), forgets it, fades it out, and only then
  `view.close()`: a view closed under a running child would start a fresh
  one on its next draw (PuiKit's lifecycle). Then the panes re-read and
  `on_done(view.exit_code)` runs.

## Environment

`_shell_launch` gives a shell XeFM's environment with the common `PATH`
entries, the `XEFM_*` snapshot (`build_xefm_env`), `XEFM_ACTIVE` and the
prompt marker - the same for the terminal-mode subshell and every shell
session. The snapshot goes stale in a session kept for a while; the live
channel is `xefmctl` ([XEFMCTL_IMPLEMENTATION.md](XEFMCTL_IMPLEMENTATION.md)).
`_start_session` adds the socket variables with `XEFM_SESSION` = the
session's `id`, allocated (`next_id`) before the view is built.

## Shell integration

`xefm/shell_integration.py` `apply(argv, env)` runs in `_start_session` for
shells. It makes the shell emit OSC 133 A/B/C/D and OSC 7:

- zsh: `ZDOTDIR` → a per-process temp dir whose `.zshenv`, `.zprofile`,
  `.zshrc`, `.zlogin` source the user's own file (from `XEFM_USER_ZDOTDIR`,
  the `ZDOTDIR` the user had, else `$HOME`), following a `ZDOTDIR` the user's
  `.zshenv` sets. `.zshrc` adds `precmd` / `preexec` hooks after the user's
  rc (themes are set up by then); the last file read gives `ZDOTDIR` back.
  `precmd` re-appends the B mark when a theme rebuilt `PS1`.
- bash ≥ 4.4: `--rcfile`; `-l` is dropped and `XEFM_BASH_LOGIN=1` makes the
  rc read `/etc/profile` and the first profile file instead of `~/.bashrc`.
  C comes from `PS0`, which bash < 4.4 lacks, so there the rc adds nothing:
  without C, libghostty would keep reporting "at prompt" while a command runs.
- Left alone: `-c` commands, `--norc` / `--rcfile` / `--posix`, any other
  shell.

PuiKit binds libghostty's semantic-prompt callback, `CURSOR_AT_PROMPT`,
notifications and progress, and `TerminalView` passes them on (`on_prompt`,
`at_prompt`, `on_notification`, `on_progress`). `xefm.terminal.TerminalView`
forwards only the keywords the installed PuiKit takes (`_supported_kwargs`).

## Quitting

`confirm_quit` asks only about `self._sessions.busy()`. `TerminalView.busy`:
a program running is busy; a shell is not when it is idle at its prompt -
`idle_at_prompt` (shell integration) or, without it, PuiKit's
`child_in_foreground` (the pty's foreground process group is the shell's
own; POSIX only). A shell neither can read (cmd.exe, PowerShell, an old
bash on Windows) counts as busy, so quitting asks. `_quit` hangs every
session up in `_close_terminal_sessions`.

## Attention

`_session_prompt` times commands between `OUTPUT_START` and `COMMAND_END`;
one of at least `_LONG_COMMAND_S` (10 s) ending while the session is hidden
sets `session.attention` (`done` / `failed`). A failed exit while hidden, a
notification while hidden, and progress (`session.progress`) do the same.
`_session_parts` adds those to `_jobs_parts`, so they share the job
segment's drawing; a click goes to `_jobs_part_clicked`, which shows the
session (or the list) when nothing else is in the segment. Showing a session
clears its `attention`.

## Keys

`toggle_terminal` (filer) and `terminal.hide` (terminal) share one key,
Ctrl-` in both desktop apps (VS Code's terminal toggle). The terminal takes
it because the action is `terminal.*` (`TerminalView.takes_binding`). There
is no default in the common table: terminal mode has no sessions.
`terminal.sessions` opens the list from inside a session; the list is pushed
above the top layer for that.

## Without libghostty

`_terminal_ready` logs why (`terminal.unavailable`) and what to do instead
(the app bundles include it; terminal mode); nothing starts, and an
`on_done` gets `None`. A PyPI install has no libghostty, so its desktop app
has no terminal. The `TERMINAL` application that used to stand in is gone,
with its wrappers (`external_terminal.py`); a config that still sets
`TERMINAL` gets a warning from `validate_config`.

## Not yet

From #900's list: pane following (OSC 7 is emitted; nothing reads it yet),
`ctx.start_session`, agent presets (#880), the session drawn as a dialog over
dimmed panes.

## Tests

`test/test_terminal_sessions.py`: the registry; toggle, subshell, switch,
exit, program sessions' `on_done`, quit only when busy, terminal mode's
hand-over and missing actions, no libghostty - against a stand-in panel and
view. `test/test_terminal_transition.py`: the entrance and the fade-out
close. `test/test_shell_integration.py`: `apply` per shell, a real zsh in a
pty read through libghostty (skipped without zsh or a PuiKit with prompt
marks), attention. `test/test_configured_commands.py`: the marking and the
launcher.
