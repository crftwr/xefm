# Terminal Sessions and Screens: Implementation

The desktop app's terminal (discussion #900) and the screens it switches
between (#951). User documentation:
[TERMINAL_FEATURE.md](../TERMINAL_FEATURE.md).

## One kind of session

Everything the desktop app runs in its terminal is a terminal session:
PuiKit's `TerminalView` (libghostty-vt over a pty) wrapped by
`xefm.terminal.TerminalView`, registered in
`xefm.terminal_sessions.SessionRegistry` (`XeFMApp._sessions`). Started by:

| | kind | how |
|---|---|---|
| `subshell`, the switcher's "New shell" row | shell | `_new_shell_session` → `_start_session(shell=True)` |
| `'terminal': True` from `PROGRAMS`, Open With, `ctx.run_program`, `TEXT_EDITOR`, `TEXT_DIFF`, `FILE_ASSOCIATIONS` | program | `_start_program` / `_run_configured` → `_start_session(shell=False)` |

Each runs on a screen of its own and keeps running while another screen is
on (the switcher, the exit bar's Escape: `_hide_session`). The kind decides
only the end:

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
waits. `screens` is in `_BACKEND_GATED`
(palette, help) and `_terminal_menu` (menu) for the desktop only, and log a
note when a binding reaches them in terminal mode (`_desktop_only`). The
parity difference is that one: the desktop can keep a shell running behind
the panes.

## Screens and the layer tree

A *screen* is what fills the window: the file manager's or a session's. It is
a `LayerGroup` in PuiKit's layer tree (puikit#233), kept by
`xefm.screens.ScreenManager` (`XeFMApp._screens`, made with the Panel, in
both modes):

- The file manager's group (z 0) holds what is opened over the panes; the
  panes themselves are the Panel's base. A session's group (z 10, above, so
  the entrance and exit cross the right way) holds its terminal view (z 1
  inside the group) and what is opened over it.
- Only the current screen's group is shown; the others are hidden with
  `set_layer_hidden`, **not removed**, so a viewer over the panes is still
  there when the file manager comes back, and a dialog that closes itself
  while its screen is out of view (a progress dialog finishing) is simply
  gone. The self-closing dialogs and the viewers remove themselves with
  `remove_layer` wherever they sit (`has_layer`), not "pop if on top".
- The current screen's group is the Panel's default layer parent
  (`set_default_layer_parent`), so a dialog opened by code that knows nothing
  of screens lands on it. `_over_top_layer` narrows it to the topmost layer
  for the command palette and an app-wide action run from a viewer or the
  terminal: their dialogs are children of that surface instead of computing
  a z above it (the old `max(top + 1)`, `_child_z` and `slot.z` rewriting).
- Screen and session are separate objects linked both ways
  (`Screen.session`, `Session.screen`): the session is the process, the
  screen what shows it. A failed session keeps its screen; `_close_session`
  removes the group (`ScreenManager.remove`) before `view.close()`.
- `ScreenManager.recent()` is the most-recently-shown order the switcher and
  `ctx.screens()` use; `make_current` keeps it, the default parent and every
  `view.shown`.
- A viewer is a child of one screen, never a screen. `xefmctl view` switches
  to the file manager, closes a viewer already open there (a screen shows
  one viewer at a time) and opens the new one: `xefmctl` acts on the file
  manager.

`xefm/terminal_sessions.py` stays UI-free: `Session` (the view, `kind`,
`name`, `cwd`, the process-unique `id` that `XEFM_SESSION` says, `on_done`,
`program`, `started_at`, `command`; `state`, `running`, `busy`, `activity`,
`label`) and `SessionRegistry` (start order, `for_view`, `running()`,
`busy()`, `next_name`).

## Showing, leaving, closing

`_show_screen(screen)`:

- file manager → terminal: reveal the session's group (the file manager's
  stays shown), `animate_from_behind` the view - `Panel.beneath` gives the
  base and any viewer over the panes, which zoom away together - and hide
  the file manager's group when it lands.
- terminal → file manager: make the file manager current (its group shows
  beneath the terminal), fade the view out (`view.closing` swallows input),
  hide the session's group when it lands, re-read the panes.
- terminal → terminal, or no motion: at once.

`_close_session` forgets the session; when its screen is on and the screen
before it is the file manager it fades out first, otherwise the switch to
the screen before is at once. Then the group goes, `view.close()` (a view
closed under a running child would start a fresh one on its next draw),
the panes re-read and `on_done(view.exit_code)` runs.

A session started with `show=False` (`ctx.start_terminal_session`) is pushed
hidden and started with PuiKit's `TerminalView.start(panel)`, since a hidden
layer is never drawn and PuiKit otherwise starts the program on the first
draw.

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
- C carries the command line as `cmdline_url=` (percent-encoded `%`, `;`,
  newline, BEL, ESC): zsh from `preexec`'s `$1`, bash from `history 1` in
  `PS0` (empty with history off, then C goes alone). libghostty hands it to
  `on_prompt` with `OUTPUT_START`; `_session_prompt` keeps it in
  `session.command` until `COMMAND_END` (#954).
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

## The switcher

`screens` (common, so viewers run it through `surface_actions`) and
`terminal.screens` (terminal) open one list and share one key, Ctrl-` in
both desktop apps (VS Code's terminal toggle); the terminal takes it because
the action is `terminal.*` (`TerminalView.takes_binding`). There is no
default in the common table: terminal mode has no screens to switch.

Rows: `ScreenManager.recent()` (the screen on now first), then "New shell".
The cursor starts on row 1 - the screen before this one, or "New shell" with
no session - so Enter flips back. A row is `_screen_label`: the file manager
or `Session.label` (name, `activity`, directory), then `viewing NAME` when a
viewer is open on that screen. `activity` is the shell integration command
line, else PuiKit's `foreground_program` (POSIX) when it is not the shell
itself, else a shell's title (cmd, PowerShell). The file manager and "New
shell" refuse the remove key.

A second press of the key as "accept" (flip in key, key) is left for later.

## The public API

`ctx.screens(order=)`, `ctx.current_screen`, `ctx.terminal_sessions()` and
`ctx.start_terminal_session(...)` (all Preview) hand out `user_api.Screen`
and `user_api.TerminalSession`, thin wrappers over the internal objects (no
PuiKit type crosses). In terminal mode `start_terminal_session` hands the
terminal over through `_run_in_terminal` and returns a `TerminalSession`
over an `_EndedSession`; `on_done` is scheduled with `_call_later` in both
modes, so it never runs before the call returns. `ACTIONS` may name the
`terminal` context; `xefm.terminal.TerminalView` runs those through
`on_user_action` (`_run_terminal_user_action` → `_run_action(TERMINAL, ...)`)
and takes their keys from the program like a `terminal.*` action.

## Without libghostty

`_terminal_ready` logs why (`terminal.unavailable`) and what to do instead
(the app bundles include it; terminal mode); nothing starts, and an
`on_done` gets `None`. A PyPI install has no libghostty, so its desktop app
has no terminal. The `TERMINAL` application that used to stand in is gone,
with its wrappers (`external_terminal.py`); a config that still sets
`TERMINAL` gets a warning from `validate_config`.

## Not yet

Agent presets (#880); what a late `on_done` may change on screen (#946).
Panes do not follow the shell's `cd` (decided in #900): OSC 7 is emitted for
libghostty but nothing reads it; `xefmctl cd` moves a pane explicitly.

## Tests

`test/test_terminal_sessions.py`: the registry; the switcher, subshell, switch,
exit, program sessions' `on_done`, quit only when busy, terminal mode's
hand-over and missing actions, no libghostty; screens (closing back to the
previous one, hidden start, a dialog closing out of view, row labels), the
`ctx` API in both modes, `xefmctl screen` / `session` / `view`, the terminal
context - against a PuiKit Panel on the memory backend and a stand-in view.
`test/test_terminal_transition.py`: the entrance, a viewer zooming away with
the panes and staying, and the fade-out close. `test/test_shell_integration.py`: `apply` per shell, a real zsh in a
pty read through libghostty (skipped without zsh or a PuiKit with prompt
marks), attention. `test/test_configured_commands.py`: the marking and the
launcher.
