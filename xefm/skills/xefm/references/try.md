# Seeing XeFM run: `xefm try`

`xefm try` runs the terminal XeFM in a **temporary home** and, with `--keys`,
follows a script in a pseudo-terminal of its own, saves the screen after each
step as text, and exits. It is the one way for you to launch XeFM. Without
`--keys` it hands the terminal to XeFM and blocks like `xefm` does: that form
is for the user.

Use it to see what static checks cannot:

- **an extension** — its menus, prompts, dialogs, a task's progress, cancel
  (`--ext <dir>`; see `references/extensions.md`, *Testing*, for the unit
  tests that come first);
- **a config edit** — that `config.py` loads, and that a key now does what was
  asked (`--config ~/.xefm/config.py`);
- **a demo** the user asked for — `--record` writes a session they can replay
  or turn into a GIF.

```bash
xefm try --ext hello-xefm --keys steps.json --screens out/ --record out/session.cast
```

- The home is temporary: the user's `~/.xefm` is never read or written, and
  the home is removed at exit. It holds XeFM's template config (or the one
  `--config FILE` names), the packages `--ext` names (a directory, a zip or
  `github:owner/repo`, repeatable) and nothing else — not the user's other
  extensions. The `afx` keymap preset is already chosen (`--keymap orthodox`
  for the other) and the Tip of the Day is off.
- The left pane opens on a few fixture files (`a.txt`, `b.txt`, `c.md`,
  `folder/`); `--left DIR` opens another directory.
- It needs `pip install 'quality-loop[tui]'` (a terminal emulator and the key
  notation below). If that is missing, tell the user. What can be checked
  without it: an extension with its unit tests and `xefm ext check`, a key a
  config edit bound with `xefm keys` (`references/config.md` §4).

The script is a JSON list of steps. Each step sends its keys, then waits until
the screen has stopped changing:

```json
[
  {"intent": "open the command palette", "keys": ["Ctrl-T"]},
  {"intent": "find the action", "keys": [{"text": "hello"}]},
  {"intent": "run it", "keys": ["Enter"]}
]
```

Keys are named like `Ctrl-T`, `Shift-Down`, `Enter`, `Esc`, `F5` or `a`;
`{"text": "..."}` types text and `{"pause": 2}` waits. In the default `afx`
preset, `Ctrl-T` opens the command palette, which runs any action by name;
`references/actions.md` has every other key.

What comes back, in `--screens` (default `try-screens/`):

- `00.txt` (after start-up) and `NN.txt` after each step: the screen as text,
  then, under a dashed `highlighted (line:columns)` rule, every run drawn on a
  coloured background or in reverse. That is how the selection (file rows) and
  the menu or list row under the cursor show; the status bars are always
  there too. A file list's cursor row needs no list: it sits between `[` and
  `]` in the text itself. The same runs are in `steps.jsonl` as
  `highlighted`.
- `steps.jsonl`: per step, the keys sent, whether the screen settled
  (`"settled": false` means it was still drawing after `patience` seconds, 10
  by default), and `events` — every line XeFM wrote to its log pane during the
  step (`"kind": "message"`) and every exception it logged
  (`"kind": "exception"`, with the traceback). Read the events rather than the
  log pane on the screen: a message can scroll out of view.
- With `--record`, an asciicast v2 file of the whole session, each step a
  chapter. The user can watch it with `asciinema play` or turn it into a GIF
  with `agg`.

Things that will catch you out:

- **Colour is only in the highlighted list.** Find the menu row you are on
  there instead of counting `Down` presses; confirm a selection there or by
  its `Selected: …` event.
- **A running task never goes quiet.** Its progress dialog keeps redrawing, so
  a step during a task waits its full `patience`. To press keys while a task
  runs (to cancel it, say), put them in one step with pauses:
  `["Enter", {"pause": 1}, "Esc"]`.
- **The clipboard is not the system's.** In a terminal XeFM copies through the
  terminal, and this terminal is an emulator: nothing reaches the OS clipboard.

No step needs to quit XeFM: `xefm try` ends it when the script runs out.
