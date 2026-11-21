# Terminal

English \| [日本語](TERMINAL_FEATURE.ja.md)

Some things XeFM runs need a terminal: the subshell (`subshell`, **Tools →
Subshell Here**) and programs that draw a screen or read the keyboard, such as
`vim`, `less` or a REPL. How XeFM gives them one depends on how it runs:

- **In a terminal**, XeFM hands over the terminal it runs in, waits until the
  program exits, then re-reads the panes.
- **In the desktop app**, XeFM has a terminal of its own, drawn in its window.
  Each shell or program runs there as a *terminal session* on a *screen* of
  its own, which you can leave while it keeps running.

## Which commands get a terminal

`TEXT_EDITOR`, `TEXT_DIFF`, the `open`, `view` and `edit` commands in
`FILE_ASSOCIATIONS`, and `PROGRAMS` entries can all be marked the same way:

```python
TEXT_EDITOR = {'command': 'vim', 'terminal': True}
TEXT_DIFF = {'command': ['code', '--diff', '--wait'], 'terminal': False}
{'pattern': '*.log', 'view': {'command': ['less'], 'terminal': True}},
{'name': 'Python REPL', 'command': ['python3'], 'terminal': True},
```

| Marking | In a terminal | In the desktop app |
|---|---|---|
| `'terminal': True` | gets the terminal; XeFM waits | runs in a terminal session |
| `'terminal': False` | runs in the background, output in the log pane | the same |
| unmarked (a plain string or list) | gets the terminal; XeFM waits | runs in the background, output in the log pane |

A `PROGRAMS` entry without a marking runs in the background in both modes, as
it always has. See [External Programs](EXTERNAL_PROGRAMS_FEATURE.md) and
[File Associations](FILE_ASSOCIATIONS_FEATURE.md) for the rest of those
settings.

A program in the background is never waited for. If it exits with an error,
the log pane says so. A program that keeps running after XeFM quits, such as
an editor, is not stopped by XeFM quitting.

## In the desktop app: terminal sessions and screens

**Subshell Here** starts your shell in the active pane's directory, in XeFM's
terminal over the panes. A program marked `'terminal': True` opens the same
way. Each is a terminal session, shown on a screen of its own.

A *screen* is what fills the window: the file manager's (the panes) or a
session's. A screen keeps what is open on it. A viewer you opened over the
panes is still there when you come back from a terminal, so you can look at a
file and a terminal by turns, switching between the two screens.

- **Switch** with **Tools → Screens…** (`screens`, which works over a viewer
  too, or `terminal.screens` from inside a session). The list holds the file
  manager's screen, each session's, and last rows that start another shell,
  or a session of each [AI agent](AI_AGENT_SESSIONS_FEATURE.md) you set up,
  in the active pane's directory. Each row says what is on that screen: the
  command running in a session - the title the program gives itself, as a
  terminal's tab shows it - and the directory its shell is in now
  (`make test - ~/src`, or `zsh - ~/src` at the prompt), or the viewer open
  over the panes (`File manager - viewing notes.txt`). The screen you
  are on comes first and the rest follow in the order you last used them,
  with the cursor on the one you were on before, so `Enter` takes you back
  there. A session you leave keeps running. Coming back to the file manager
  re-reads the panes. The remove key (`remove_list_item`) ends the
  highlighted session.
- **When it ends.** `exit` in a shell, or a program that finishes, closes the
  session and returns to the screen you were on before it, whether it was on
  screen or not. A shell or program that fails keeps its last screen up so
  you can read it. For a shell, `Enter` starts it again and `Esc` goes back
  to the panes; for a program, `Enter` or `Esc` closes it.
- **Close it** with `terminal.close` while it still runs. XeFM asks first,
  since that stops whatever runs there.
- **Quitting XeFM** asks first only when a session is busy: a program
  running, or a shell in the middle of a command. A shell waiting at its
  prompt just ends.

The keys are on [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

XeFM's terminal runs on libghostty, which the macOS and Windows apps include.
XeFM installed with pip has no libghostty, so its desktop app has no terminal:
the subshell and terminal programs do not start there, and the log says why.
Run XeFM in a terminal (`--backend vt`) for them instead.

### The shell's environment

A shell XeFM starts gets the `XEFM_*` variables with the pane directories and
selections, `XEFM_ACTIVE`, and the `[XeFM]` prompt marker (see
[User Guide: Subshell](XEFM_USER_GUIDE.md#subshell)). Those variables hold the
panes as they were when the shell started; a session you keep for a while
should ask [`xefmctl`](XEFMCTL_FEATURE.md) instead.

For zsh and for bash 4.4 or later (macOS's own bash is 3.2), XeFM adds a few
lines of shell integration when it starts them, so it can tell when the shell
waits at its prompt and when a command ends. Your own startup files still run
as usual.

### News from a hidden session

While a session is hidden, the status bar shows what needs your attention: a
command that ran for 10 seconds or more has finished or failed, a program
failed, or a program sent a notification (OSC 9 or OSC 777), as Claude Code
and other tools can. A program that reports its progress (OSC 9;4) shows it
there too. Click it to bring the session back.

Shell integration also tells the switcher the command line running in a
session. Without it, macOS and Linux still show the name of the program
running there; on Windows, the title the program sets.

## In a terminal

XeFM in a terminal does not draw a second terminal inside itself. The subshell
and terminal programs get the terminal XeFM runs in, and you return to XeFM
when they exit. There are no terminal sessions and no screens to switch
between, so **Screens** is not in the menu or the command palette.

This is the one difference between the two: the desktop app can keep a shell
running behind the panes, and XeFM in a terminal cannot. To work in parallel
there, use the tabs or windows of your terminal, or tmux. To open another
terminal window from XeFM, add a `PROGRAMS` entry for it; the config template
has examples for Terminal.app, iTerm, Windows Terminal and tmux.

## Asking XeFM from the shell

In a shell XeFM started (the subshell, a terminal session, a `PROGRAMS`
entry), the [`xefmctl`](XEFMCTL_FEATURE.md) command asks that XeFM for its
state at the moment it runs, and acts on its file manager:

```sh
xefmctl state                                  # what XeFM shows now
cp $(xefmctl pane selected) /tmp               # names without spaces
xefmctl pane cd .                              # bring the active pane here
xefmctl view build.log                         # Screens takes you back to compare
xefmctl screen show files
```

It also searches anywhere XeFM can go, shows lists in a pane, copies
through XeFM and asks you questions: see [xefmctl](XEFMCTL_FEATURE.md) for
every command. An [AI agent](AI_AGENT_SESSIONS_FEATURE.md) that XeFM opens
uses it to work beside you.

## The `TERMINAL` setting

Earlier versions read `TERMINAL` in `config.py` to choose a terminal
application for the desktop app. XeFM's own terminal runs those things now,
and `TERMINAL` is no longer used: XeFM says so once when it loads a config
that still sets it. To open your terminal application from XeFM, add a
`PROGRAMS` entry for it.

## See also

- [xefmctl](XEFMCTL_FEATURE.md): every command a shell XeFM started can send it
- [AI agent sessions](AI_AGENT_SESSIONS_FEATURE.md): an AI agent as a terminal session
- [External Programs](EXTERNAL_PROGRAMS_FEATURE.md): `PROGRAMS` and `'terminal': True`
- [File Associations](FILE_ASSOCIATIONS_FEATURE.md): commands per file type
- [User Guide: Subshell](XEFM_USER_GUIDE.md#subshell): the prompt marker and `SUBSHELL`
