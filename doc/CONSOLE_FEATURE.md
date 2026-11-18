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
the panes. Ask XeFM with the [`xefm` command](#asking-xefm-from-the-shell)
instead.

The keys are on [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

## Asking XeFM from the shell

In a shell XeFM started (the console, the subshell, a `PROGRAMS` entry, or a
shell opened through `TERMINAL`) the `xefm` command asks that XeFM for its
state at the moment it runs:

| Command | What it does |
|---|---|
| `xefm selected` | Prints the full paths of the selected items, one per line (`-0`: separated by NUL, for `xargs -0`) |
| `xefm focused` | Prints the full path of the item under the cursor |
| `xefm pwd` | Prints the pane's directory |
| `xefm cd [PATH]` | Points the pane at `PATH`, relative to the shell's directory; without `PATH`, at the shell's directory. A file: its folder, with the cursor on it |
| `xefm view FILE` | Opens `FILE` in XeFM's viewer |
| `xefm sessions` | Lists the console sessions; `*` marks the one you are in |

`--pane this` (the default, the active pane), `--pane other`, `--pane left`
or `--pane right` picks the pane. For example:

```sh
cp $(xefm selected) /tmp           # names without spaces
xefm selected -0 | xargs -0 du -sh
xefm cd .                          # bring the active pane to this shell's directory
xefm view build.log
```

Other `xefm` commands, such as `xefm ext check`, work there as usual. If the
XeFM that started the shell has quit, the command says so. While a subshell
in terminal mode runs, XeFM is waiting for it, so only the commands that read
(`selected`, `focused`, `pwd`, `sessions`) work there.

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
