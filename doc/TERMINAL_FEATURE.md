# Terminal

English \| [日本語](TERMINAL_FEATURE.ja.md)

Some things XeFM runs need a terminal: the subshell (`subshell`, **Tools →
Terminal**, or **Subshell Here** in a terminal) and programs that draw a screen or read the keyboard, such as
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

**Tools → Terminal** (`subshell`) starts your shell in the active pane's
directory, in XeFM's terminal over the panes. A program marked
`'terminal': True` opens the same way. Each is a terminal session, shown on
a screen of its own.

A *screen* is what fills the window: the file manager's (the panes) or a
session's. A screen keeps what is open on it. A viewer you opened over the
panes is still there when you come back from a terminal, so you can look at a
file and a terminal by turns, switching between the two screens.

Every session's screen is a tab of the window, after the file manager's:
shells, terminal programs and [AI agents](AI_AGENT_SESSIONS_FEATURE.md) in
one strip. Going back to a session is one key; starting another is a
separate, deliberate step, so sessions do not pile up behind the panes
unnoticed.

- **The window around it.** A session's screen keeps the window's menu bar
  (where it is in the window, as in a terminal), the strip of tabs and the
  status bar, at the same places as the file manager; only what is between
  them changes. The status bar says the keys for the session. The menu
  items that act on the file manager are off while a session is on screen.
- **Tabs.** While there is a session, the strip of tabs runs under the menu
  bar on every screen, the file manager's included: **Files** first, then
  one tab per session in the order they were started, the one on screen in
  front. Each tab starts with what it shows - `▤` the file manager, `$` a
  shell, `>` a terminal program, `✦` an AI agent - and a session's tab, while
  the pointer is over it, ends with `×`, which closes it (asking first only
  when that would stop something). Click a tab to go there, or use
  `next_screen` and `prev_screen` (`terminal.next_tab` and
  `terminal.prev_tab` inside a session), Ctrl-Tab in the desktop app as in a
  browser. Going between tabs is at once: nothing slides or fades. Drag a tab along the strip to
  move it: a line shows where it will go, and it moves there when you let go
  (or use `terminal.move_tab_left` and `terminal.move_tab_right`); **Files**
  stays first. A tab whose session is waiting on you shows `⚠` in place of
  its icon, one that has finished something since you last looked `✓`.
- **Go back to a session.** **Terminal** (`subshell`) goes back to the
  terminal session you used last, and starts a shell only when there is none.
  **AI Agent** (`agent`) does the same for the AI agent sessions.
  **Switch Screen** (`switch_screen`, `terminal.switch_screen` inside a
  session) goes from the file manager to the screen you used last, and from
  any session back to the file manager; with no session yet it starts a
  shell (in a terminal, the subshell) - never an AI agent, which only
  `agent` starts. A session you leave keeps running. Coming back to the file
  manager re-reads the panes.
- **Start another session.** The `+` after the tabs (or `terminal.new` inside
  a session) starts a shell or an AI agent session, asking which when there
  is more than one to choose from. **New Shell Here** (`new_shell`) and **New
  AI Agent Here** (`new_agent`) start one even when a session is open.
  **Subshell Here** in the directory's context menu starts a new shell in
  that directory.
- **Screens.** **Tools → Screens…** (`screens`, which works over a viewer too,
  or `terminal.screens` from inside a session) lists every screen there is,
  to go to, close or rename one: the file manager first, then each session.
  A session's row says what runs in it - the title the program gives itself,
  as a terminal's tab shows it - and the directory its shell is in now
  (`make test - ~/src`, or `zsh - ~/src` at the prompt), with its kind, its
  state and when you last used it on the right. The ones waiting on you come
  first and the rest in the order you last used them; the cursor starts on
  the screen you used last that is not on now. The last row, **Close N idle
  sessions**, closes every session that is not in the middle of something.
  The remove key (`remove_list_item`) closes the highlighted session, and the
  rename key (`rename_list_item`) gives it a name of your own, which its tab
  shows too. Starting a session is the `+` after the tabs, and an [AI
  conversation you closed](AI_AGENT_SESSIONS_FEATURE.md#closing-loses-nothing)
  comes back from **Resume AI Conversation…**.
- **When it ends.** `exit` in a shell, or a program that finishes, closes the
  session, whether it was on screen or not. If it was on screen, the screen
  you were on before it comes back - the file manager an editor was opened
  from, say - as a browser goes back to the tab used last. `exit` closes a shell even when it passes on an
  error from an earlier command, as cmd's `exit` does. A program that fails,
  or a shell that ends before you typed anything into it (it could not start),
  keeps its last screen up so you can read it; `Enter` or `Esc` closes it. To
  start a shell again, open a new one (**New Shell Here**).
- **Close it** with `terminal.close`. XeFM asks first only when that would
  stop something: a program still running, or a shell in the middle of a
  command. A shell waiting at its prompt just closes.
- **Quitting XeFM** asks first only when a session is busy: a program
  running, or a shell in the middle of a command. A shell waiting at its
  prompt just ends.

The keys are on [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

XeFM's terminal runs on libghostty, which the macOS and Windows apps include.
XeFM installed with pip has no libghostty, so its desktop app has no terminal:
the subshell and terminal programs do not start there, and the log says why.
Run XeFM in a terminal (`--backend vt`) for them instead.

### Selecting, copying and pasting

Drag to select text; double-click selects a word, triple-click a line, and
`Alt`+drag a rectangle. In a program that uses the mouse itself (vim, htop),
hold `Shift` while you drag.

| | Every system | macOS | Also on Windows |
|---|---|---|---|
| Copy the selection | `Ctrl+Shift+C`, `Ctrl+Insert` | `Cmd+C` | `Ctrl+C` |
| Paste | `Ctrl+Shift+V`, `Shift+Insert` | `Cmd+V` | `Ctrl+V` |

A copy key with nothing selected goes to the program, so `Ctrl+C` still
interrupts it. On Windows, `Ctrl+C` copies a selection and then clears it, so
pressing it again interrupts. If a program needs `Ctrl+C` and `Ctrl+V` itself
(vim's block selection, Emacs), set `TERMINAL_CTRL_CLIPBOARD = False` in
`config.py`: both keys then go to the program, and the other keys still copy
and paste.

A right-click copies the selection and clears it, or pastes when nothing is
selected, as in Windows Terminal. A program that uses the mouse gets the
right-click instead; hold `Shift` to copy or paste.

A pasted line break is sent as `Enter`, so pasting several lines runs them
one after another.

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
there too, and on the session's tab. Click it to bring the session back.

Shell integration also tells Screens the command line running in a
session. Without it, macOS and Linux still show the name of the program
running there; on Windows, the title the program sets.

## In a terminal

XeFM in a terminal does not draw a second terminal inside itself. The subshell
and terminal programs get the terminal XeFM runs in, and you return to XeFM
when they exit. There are no terminal sessions and no screens to switch
between, so **Screens** is in the menu and the command palette only with an
[AI agent conversation XeFM draws](AI_AGENT_SESSIONS_FEATURE.md#conversations-drawn-by-xefm)
set up.

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
xefmctl view build.log                         # Switch Screen takes you back to compare
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
