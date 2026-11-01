---
name: xefm
description: Work with the XeFM file manager on the user's behalf — edit its configuration file (~/.xefm/config.py) and write, check and install extension packages. Use when the user wants to change how XeFM behaves or looks ("bind Ctrl-T to …", "make the editor code --wait", "add a favorite", "open .log files with less", "add an external program", "use the function-key keymap", "define a theme"), or wants a new XeFM feature that can live outside the core ("add an XeFM action that…", "make an XeFM extension", "turn my config.py action into an extension"), or asks to fix an extension that `xefm ext check` rejects.
metadata:
  xefm-version: "{XEFM_VERSION}"
---

# Working with XeFM

XeFM is a dual-pane file manager that runs as a desktop app (macOS, Windows)
and in the terminal (macOS, Windows, Linux). Everything the user customizes
lives in one folder, `~/.xefm/`, shared by every XeFM install on the machine:

```
~/.xefm/
  config.py          # the configuration: a Python file with `class Config:`
  extensions/        # installed extension packages (managed by `xefm ext`)
  tools/             # the user's own scripts for PROGRAMS entries
```

On Windows `~` is the user's profile folder (`C:\Users\<name>`).

## Which XeFM this describes

This skill was packaged from **XeFM {XEFM_VERSION}** and describes that
version's settings, actions and extension API. An installed skill does not
update itself when XeFM does. If `xefm` is on PATH, `xefm --version` prints
the XeFM the user runs (`XeFM X.Y.Z`); if it is not, skip this check.

- **Same major.minor** (patch and `+dev` parts aside): carry on. Patch
  releases do not change what this skill describes.
- **Different:** tell the user **once, in one sentence**, to install the skill
  from their release (`xefm skill --install <skills dir>` does it), then carry
  on, treating the names this skill gives as unconfirmed. If XeFM or
  `xefm ext check` rejects a setting, action or API name taken from here, name
  the version mismatch as the likely cause instead of working around it.

## Ground rules

- **Never launch XeFM.** `xefm`, `python -m xefm` and the app itself open an
  interactive file manager that blocks until a person quits it. `xefm ext …`,
  `xefm keys` and `xefm skill` are safe: they never open a window. The one
  exception is `xefm try --keys steps.json`, which runs XeFM in a temporary
  home and a pseudo-terminal and exits when the script ends
  (`references/try.md`); without `--keys` it blocks like `xefm`.
- **XeFM applies a change when the user asks it to.** Finish with: run
  **Tools ▸ Reload Configuration** in XeFM, or restart it. Say which of the two
  the change needs (the config reference lists what only a restart applies).
- `xefm` may not be on PATH (`xefm --version` tells). Editing `config.py`
  never needs it; the `xefm ext …` commands and `xefm keys` do. If it is
  missing, tell the user rather than searching the disk for an XeFM to run.

## Which reference to read

| The user wants… | Read |
|---|---|
| a setting changed: keys, editor, diff tool, favorites, file associations, external programs, themes, confirmations, fonts, the keymap preset | `references/config.md` |
| a small function of their own bound to a key, in their config | `references/config.md` (*Actions*) |
| an action's exact name, or which keys a preset already uses | `references/actions.md` (generated from XeFM) |
| what a setting is called, its default, what it does | `references/config-template.md` (XeFM's template, generated) |
| a feature to package, share, or keep apart from their config; anything with settings of its own, tests, or several files | `references/extensions.md` |
| an extension fixed that `xefm ext check` rejects | `references/extensions.md` |
| to see a change work in XeFM itself — an extension's dialogs, a key a config edit bound — or a recorded demo | `references/try.md` |

**`config.py` or an extension?** Edit `config.py` for the user's own settings
and for a short function only they will use. Write an extension instead when
the code is more than a screenful, needs its own settings or saved state,
should be shared or tested, or depends on another library. To move an action
from `config.py` into a package, follow *Start a package* in
`references/extensions.md`.
