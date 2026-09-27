# External Terminal (desktop mode)

In terminal mode, XeFM lends its own terminal to anything that needs one: the
subshell (`subshell`, Shift-X) and `PROGRAMS` entries marked
`'options': {'terminal': True}` — `vim`, `less`, a REPL. The desktop app has no
terminal of its own, so it opens one instead: a new terminal window, in the
current directory, running your shell or the program.

The same `config.py` therefore works in both modes. The differences are:

- **XeFM does not wait.** The terminal window is its own application. XeFM
  keeps running, and the panes pick up changes you make there through file
  monitoring rather than a refresh when you return.
- **The environment is a snapshot.** The `XEFM_*` variables (pane
  directories, selection, `XEFM_ACTIVE`) and the `[XeFM]` prompt marker are
  set when the window opens, exactly as in a terminal-mode subshell. They do
  not follow later changes in XeFM.
- **Local directories only**, as in terminal mode.

A `terminal: True` program that exits with an error holds its window open
until you press Enter, so its last output stays readable. A subshell closes
its window the way your terminal normally does when the shell exits.

## Choosing the terminal

`TERMINAL` in `~/.xefm/config.py` picks the application; `SUBSHELL` still picks
the shell inside it. Leave `TERMINAL` as `None` for the platform default:

| Platform | Default |
|---|---|
| macOS | Terminal.app |
| Windows | Windows Terminal (`wt.exe`) when installed, otherwise a new console window |

To use another terminal, give its command line. What XeFM needs to run is
appended to it as trailing arguments, so name a terminal the way you would to
have it run a command:

```python
TERMINAL = ['open', '-a', 'iTerm']        # macOS: an app that runs a script it opens
TERMINAL = ['wezterm', 'start', '--']     # takes the command as trailing arguments
TERMINAL = ['alacritty', '-e']
TERMINAL = ['wt.exe', '-w', '0', 'nt']    # Windows Terminal: a tab in the current window
```

A string works too (`'wezterm start --'`), split like a shell would; use a list
for a Windows path with spaces in it.

## If nothing opens

The log pane says why:

- *No terminal configured: set TERMINAL* — the platform has no default; set one.
- *Terminal not found: …* — the command in `TERMINAL` is not installed or not
  on `PATH`.

## See also

- [External Programs](EXTERNAL_PROGRAMS_FEATURE.md) — `PROGRAMS` and `terminal: True`
- [User Guide — Subshell](XEFM_USER_GUIDE.md#subshell) — the prompt marker and `SUBSHELL`
