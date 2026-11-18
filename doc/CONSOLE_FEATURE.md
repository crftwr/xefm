# Console

English \| [日本語](CONSOLE_FEATURE.ja.md)

The console is a shell that keeps running while you work in the panes. Open it
with **Tools → Console** (`toggle_terminal`). The first time, it starts your
shell in the active pane's directory. The same key hides it again and brings
it back later with everything still in it: the command you were typing, the
output, a build still running.

The subshell (`subshell`) is different: it is one-shot. XeFM waits for it,
and when you exit the shell you are back in the panes. Use the subshell for a
quick command in this directory, and the console for work that goes on while
you do other things.

## In the desktop app

The console is drawn in XeFM's window, in place of the panes, by XeFM's own
terminal (see [External Terminal](EXTERNAL_TERMINAL_FEATURE.md#choosing-the-terminal)
for where that runs).

- **Hide it** with the same key, or `Esc` once its program has exited. The
  panes re-read their directories when it hides.
- **`exit`** in the shell ends the session and returns to the panes. A
  program that fails leaves its last screen up: `Enter` starts it again,
  `Esc` hides it.
- **Close it** with `terminal.close` while its shell is still running. XeFM
  asks first, since that stops whatever runs there.
- **Several sessions.** **Tools → Terminal Sessions…** (`terminal_sessions`,
  or `terminal.sessions` from inside the console) lists each session with its
  state. `Enter` switches to the one you pick, the last row starts another
  shell in the active pane's directory, and the remove key (`remove_list_item`)
  ends the highlighted one. The console key returns to the one you used last.
- **Quitting XeFM** while a session is still running asks first, and then
  stops it.

The console's shell gets `XEFM_ACTIVE` and the `[XeFM]` prompt marker, but not
the `XEFM_*` variables with the pane directories and selections that the
subshell gets: those would be out of date as soon as you changed anything in
the panes.

The keys are on [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

## In a terminal

XeFM in a terminal does not draw a second terminal inside itself. The console
opens as a window of its own instead, in the active pane's directory:

| XeFM runs in | The console opens as |
|---|---|
| tmux | a new tmux window |
| WezTerm | a new tab (`wezterm cli spawn`) |
| kitty | a new tab (needs `allow_remote_control` in `kitty.conf`) |
| anything else, on this computer | a window of the platform's terminal, as in [External Terminal](EXTERNAL_TERMINAL_FEATURE.md#choosing-the-terminal) |
| anything else, over SSH | nothing: set `TERMINAL`, or run XeFM inside tmux |

`TERMINAL` in `config.py`, when set, is used instead. Such a window belongs
to the terminal application, not to XeFM: the console key opens another one
rather than hiding it, and it keeps running after XeFM quits.

## See also

- [External Terminal](EXTERNAL_TERMINAL_FEATURE.md): `TERMINAL`, and XeFM's own terminal in the desktop app
- [User Guide: Subshell](XEFM_USER_GUIDE.md#subshell): the prompt marker and `SUBSHELL`
