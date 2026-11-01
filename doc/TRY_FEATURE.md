# Trying XeFM in a Throwaway Home

English \| [日本語](TRY_FEATURE.ja.md)

`xefm try` starts XeFM in the terminal inside a temporary home folder. Your
own `~/.xefm` — your config, your favorites, your extensions — is never read
or changed, and the temporary home is deleted when XeFM exits. Use it to:

- **try an extension** before installing it;
- **test** a change automatically: a script presses keys and saves what the
  screen shows;
- **record a demo** for a README or a release note.

## Trying it by hand

```bash
xefm try                              # plain XeFM
xefm try --ext ./hello-xefm           # with an extension package
xefm try --config ~/.xefm/config.py   # with a copy of your config
```

XeFM opens in this terminal. The keymap preset is already chosen and the Tip
of the Day is off. The left pane opens on a few sample files. Quit XeFM as
usual.

| Option | What it does |
|---|---|
| `--ext SOURCE` | install this extension package: a folder, a `.zip`, an `https://` zip or `github:owner/repo`. Repeat it for more than one |
| `--config FILE` | use this `config.py` instead of XeFM's template. XeFM uses a copy, so your file is not changed |
| `--keymap afx` / `orthodox` / `native` / `vim` | the [keymap preset](KEYMAP_PRESETS_FEATURE.md) (default: `afx`) |
| `--left DIR`, `--right DIR` | open these folders instead of the samples |
| `--keep-home` | keep the temporary home, and print where it is |

## Running a script

```bash
xefm try --ext ./hello-xefm --keys steps.json --screens out/ --record demo.cast
```

With `--keys`, XeFM runs out of sight in a terminal of its own and follows the
script. After each step it saves the screen as text. It exits when the script
ends, so nothing is left waiting. The script is a JSON list of steps:

```json
[
  {"intent": "open the command palette", "keys": ["Ctrl-T"]},
  {"intent": "find the action", "keys": [{"text": "hello"}]},
  {"intent": "run it", "keys": ["Enter"]}
]
```

- The keys a script sends are the preset's keys: `Ctrl-T` opens the command
  palette in AFX style, the default here, but not in every preset (see
  [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side)).
- Keys are written like `Ctrl-T`, `Shift-Down`, `Enter`, `Esc`, `F5` or `a`.
  `{"text": "..."}` types text, and `{"pause": 2}` waits two seconds.
- After its keys, a step waits until the screen stops changing, for up to 10
  seconds. `"patience": 30` waits longer.
- `intent` says what the step is for. It is saved with the step and becomes
  the chapter title in the recording.

| Option | What it does |
|---|---|
| `--screens DIR` | where the screens go (default: `try-screens/`) |
| `--record FILE` | also record the whole session as an asciicast file |
| `--size COLSxROWS` | the terminal's size (default: `120x40`) |

In the `--screens` folder:

- `00.txt` is the screen after XeFM started, and `01.txt`, `02.txt`, … the
  screen after each step. Below the screen, under `--- highlighted ---`, are
  the parts drawn on a coloured background, such as selected files, the menu
  item under the cursor and the status bars, each with its line and columns;
- `steps.jsonl` has one line per step: the keys, whether the screen settled,
  what was highlighted, and every message XeFM logged during it, including
  errors.

A recording plays with `asciinema play demo.cast`, or becomes a GIF with
[agg](https://github.com/asciinema/agg): `agg demo.cast demo.gif`.

Scripts need an extra package, `pip install 'quality-loop[tui]'`. They run on
macOS, Linux and Windows, like trying XeFM by hand.

### Things to know

- The screens are plain text. Colour survives only as the highlighted list
  under each screen; a theme that marks the selection in grey would not show
  there.
- While a long task runs, its progress keeps the screen changing, so the step
  waits its full patience. To press keys during a task (to cancel it), put
  them in one step with pauses: `["Enter", {"pause": 1}, "Esc"]`.
- Copying to the clipboard does not reach your system clipboard here.

## See also

- [Extension Packages](EXTENSIONS_FEATURE.md)
- [The XeFM Skill for AI Agents](AGENT_SKILL_FEATURE.md) — the skill teaches
  an assistant to use `xefm try` to check its own work
