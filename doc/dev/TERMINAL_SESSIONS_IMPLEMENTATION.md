# Terminal Sessions: Implementation

The console: persistent terminal sessions (discussion #900, "Update: the
session model"). User documentation: [CONSOLE_FEATURE.md](../CONSOLE_FEATURE.md).

## One mechanism, two launch policies

A terminal session is one program in a terminal: PuiKit's `TerminalView`
(libghostty-vt over a pty) wrapped by `xefm.terminal.TerminalView`. What it
does around its program is a policy of the view, not a separate class:

| | one-shot | persistent |
|---|---|---|
| started by | `subshell`, `PROGRAMS` `terminal: True`, a terminal `TEXT_EDITOR` | `toggle_terminal`, the session list |
| app methods | `_run_in_terminal_view`, `_terminal_exited`, `_close_terminal` | `new_terminal_session`, `_session_exited`, `_close_session` |
| clean exit | closes, panes re-read, `on_done(code)` | session ends, panes re-read |
| failed exit | exit bar; Enter / Esc close | exit bar; Enter restarts (PuiKit), Esc hides |
| hidden | never | `terminal.hide`, `_hide_session`; the program keeps running |
| registry | none | `xefm.terminal_sessions.SessionRegistry` (`XeFMApp._sessions`) |

A one-shot never runs inside a persistent shell. Typing a command into a
long-lived shell only works while it is idle at a prompt, and the subshell
and terminal programs must work whatever the console is doing.

The clean-exit rule follows #880's for agent sessions (a clean exit closes,
an error keeps the screen) rather than "stays after its program exits": a
shell left with `exit` is one the user is done with.

## `xefm/terminal_sessions.py`

UI-free, so it is tested on its own:

- `Session`: the view, `kind` (`shell`, later `program` / agent presets),
  `name`, `cwd`, a process-unique `id`; `state` / `running` read the view.
- `SessionRegistry`: sessions in start order, `last` (what the toggle shows;
  `touch` on every show, the next newest after a remove), `for_view`,
  `running()` (what quitting stops), `next_name` (`zsh`, `zsh 2`, ...).

## Showing and hiding

- `_show_session` removes another session's layer at once (crossing two
  terminals through the file manager would only flash the panes), then
  pushes through the one-shot's `_push_terminal`: same z rule (over every
  layer), same `animate_from_behind` entrance.
- `_hide_session` plays `animate_from_behind(out=True)` and removes the layer
  on completion **without** `view.close()`. The child keeps its pty; its
  output still reaches libghostty through `call_on_main_thread`, since the
  view kept the panel from its first draw. `view.closing` swallows input
  while it fades and is reset when it lands; `view.shown` says which session
  is on screen.
- `_close_session` forgets the session first, then fades and closes. A view
  closed under a running child would start a fresh one on its next draw
  (PuiKit's lifecycle), so `close()` comes after the layer is gone, as in
  `_close_terminal`.

## Environment

`_console_env` gives the shell XeFM's environment with the common `PATH`
entries, `XEFM_ACTIVE=1` and the prompt marker, but **no** `XEFM_*_DIR`,
`_SELECTED` or `_FOCUSED`: a snapshot taken when a session starts is stale
from its first prompt on. The live channel that replaces it is the `xefm`
command ([XEFM_COMMAND_IMPLEMENTATION.md](XEFM_COMMAND_IMPLEMENTATION.md));
`XEFM_SESSION` is the session's `id`, allocated (`next_id`) before the view
is built.

## Shell integration

`xefm/shell_integration.py` `apply(argv, env)` runs in `new_terminal_session`
and the desktop subshell (XeFM's terminal only; not `TERMINAL` windows, not
terminal mode). It makes the shell emit OSC 133 A/B/C/D and OSC 7:

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

PuiKit (≥ the release after 1.27.3) binds libghostty's semantic-prompt
callback, `CURSOR_AT_PROMPT`, notifications and progress, and `TerminalView`
passes them on (`on_prompt`, `at_prompt`, `on_notification`,
`on_progress`). `xefm.terminal.TerminalView` forwards only the keywords the
installed PuiKit takes (`_supported_kwargs`), so an older PuiKit simply never
reports "at prompt".

## Typing at the prompt

`_console_type(make_text)`: the text depends on the session's shell
(`_shell_quote`: `shlex.quote` for POSIX shells, double quotes for cmd and
PowerShell). It is sent with `view.send` only when `view.idle_at_prompt`; a
session not started yet keeps it in `pending_insert` until its first
`INPUT_START` mark. A busy shell, one without integration, terminal mode
and the no-libghostty desktop get the clipboard and a log line instead. The
user presses Enter; XeFM never runs the command.

## Attention

`_session_prompt` times commands between `OUTPUT_START` and `COMMAND_END`;
one of at least `_LONG_COMMAND_S` (10 s) ending while the session is hidden
sets `session.attention` (`done` / `failed`). A notification while hidden sets
`attention`; progress sets `session.progress`. `_session_parts` adds those to
`_jobs_parts`, so they share the job segment's drawing (blink for
`attention`); a click goes to `_jobs_part_clicked`, which shows the session
(or the list) when nothing else is in the segment. Showing a session clears
its `attention`.

## Keys

`toggle_terminal` (filer) and `terminal.hide` (terminal) share one key,
Ctrl-` in both desktop apps (VS Code's terminal toggle). The terminal takes
it because the action is `terminal.*` (`TerminalView.takes_binding`). There
is no default in the common table: in a terminal the action opens a window
XeFM cannot hide, so a toggle key would only stack windows.
`terminal.sessions` lets the list be opened from inside the console; the
list is pushed above the top layer for that.

## Terminal mode and no libghostty

`_open_console_elsewhere` launches the shell through
`external_terminal.launch_in_terminal` with
`terminal_command(config, terminal_mode=True, cwd=...)`. Unset `TERMINAL` in
terminal mode resolves through `terminal_mode_default`: `$TMUX` → `tmux
new-window -c`, `$WEZTERM_PANE` → `wezterm cli spawn --cwd ... --`,
`$KITTY_WINDOW_ID` → `kitty @ launch --type=tab --cwd` (remote control must
be on), then `None` over SSH (a GUI terminal would open on the far screen),
then `default_terminal()`. The desktop app without libghostty uses
`default_terminal()` as before. XeFM does not own those processes; they are
not in the registry and do not end with XeFM.

## Quitting

`confirm_quit` counts `self._sessions.running()` as a reason to ask, also for
`quit_app` (`only_if_busy`), defaulting to Cancel. `_quit` hangs every
session up in `_close_terminal_sessions` before saving state.

## Not yet

From #900's list: pane following (OSC 7 is emitted; nothing reads it yet),
shell integration reported through the socket from `TERMINAL` windows,
`ctx.start_session`, agent presets (#880), the session list built from
socket registrations, the one-shot drawn as a dialog over dimmed panes.

## Tests

`test/test_shell_integration.py`: `apply` per shell, a real zsh in a pty
read through libghostty (skipped without zsh or a PuiKit with prompt marks),
typing at the prompt, attention. `test/test_terminal_sessions.py`: the registry; toggle, switch, exit and
quit against a stand-in panel and view; `terminal_mode_default` per
environment.
