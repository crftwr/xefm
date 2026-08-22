# XeFM Configuration Feature

## Overview

XeFM is customized through a Python configuration file. On first run XeFM creates it
from a template; edit it to change appearance, behavior, key bindings, and
external-program integration. Every option below is a real attribute of the
config class — see `xefm/_config.py` for the authoritative, fully-commented
template.

## Configuration File Location

XeFM stores its configuration in:

```
~/.xefm/config.py
```

On first run, XeFM creates this file with default settings. You can edit it with
any text editor.

## Quick Start

```bash
# View it
cat ~/.xefm/config.py

# Edit it
vim ~/.xefm/config.py        # or: nano / code / your editor of choice
```

Changes take effect the next time you start XeFM.

## Editing and Reloading Config

You can also edit and apply your config without leaving XeFM. Both actions live
under the **Tools** menu (neither is bound to a key by default):

- **Edit Configuration…** opens `~/.xefm/config.py` in your configured
  `TEXT_EDITOR`, creating it from the template first if needed. With a terminal
  editor (e.g. `vim`) XeFM reloads automatically when you save and quit; with a
  GUI editor (e.g. VS Code) XeFM can't tell when you're done, so save and then run
  **Reload Configuration**.
- **Reload Configuration** re-reads `~/.xefm/config.py` from disk and applies it
  without opening an editor — handy when you edit the file in a separate window.

To bind either action, add it to `KEY_BINDINGS`:

```python
KEY_BINDINGS = {
    'edit_config':   ['Y'],
    'reload_config': ['Ctrl-R'],
}
```

Reloading applies **live** to key bindings, file associations, external programs,
favorite directories, confirmation prompts, and the text-editor / diff-tool
settings. Themes and post-effects, fonts (desktop mode), the pane-split and
log-height ratios, and file-monitoring intervals are read once at startup and
only fully apply on the **next launch**. XeFM logs a reminder after each reload.

If your edited config has a Python error, XeFM logs it and falls back to built-in
defaults rather than crashing; out-of-range values are still applied but logged
as a `Config warning:`.

## Appearance

### Fonts (GUI / desktop mode only)

These apply in desktop mode (the native macOS / Windows backend); the terminal
backend uses your terminal's font and ignores them.

```python
UI_FONT_NAME  = None   # proportional face for names/labels (None = bundled/OS default)
MONO_FONT_NAME = None  # monospaced face for the aligned grid (None = bundled default)
FONT_SIZE      = 12    # point size applied to BOTH faces (8-72)
```

`MONO_FONT_NAME` must be a monospaced font; the on-screen grid is derived from its
glyph box. In desktop mode you can also change `FONT_SIZE` live with `Cmd-+` /
`Cmd--`.

### Themes / colors

XeFM ships with built-in themes (Dark+, Monokai, Dracula, Nord, Solarized, Gruvbox
Dark, Light+, Solarized Light). Switch at runtime via **View → Theme** or the `T`
key; XeFM starts on Dark+ and remembers the last theme across restarts. There is no
`COLOR_SCHEME` string setting — instead you register your own named themes:

```python
THEMES = {
    'Ocean': {                    # builds on Dark+ by default
        'accent':     (0, 120, 160),
        'background': (18, 26, 32),
    },
}
```

See [Color Schemes](COLOR_SCHEMES_FEATURE.md) for the full theme key reference
(including the optional GUI `post_effect` CRT/phosphor look).

## Display and Layout

```python
SHOW_HIDDEN_FILES       = False  # show hidden files (toggle at runtime with '.')
DEFAULT_LEFT_PANE_RATIO = 0.5    # left pane width as a ratio (0.1 - 0.9)
DEFAULT_LOG_HEIGHT_RATIO = 0.25  # log pane height as a ratio (0.1 - 0.5)
DATE_FORMAT             = 'short'  # 'short' (YY-MM-DD HH:mm) or 'full' (YYYY-MM-DD HH:mm:ss)
SEPARATE_EXTENSIONS     = True   # show extensions in their own column
MAX_EXTENSION_LENGTH    = 5      # longer extensions stay with the filename
```

Adjust the pane split at runtime with `[` / `]`, and the log-pane height with
`{` / `}`. `DEFAULT_LOG_HEIGHT_RATIO` sets the log pane's height as long as you
haven't dragged or `{`/`}`-adjusted it — a height you set by hand persists
across restarts and wins over the config. Press `_` to return to the configured
default (which also makes the height follow the config again). Layout ratios
are read at launch, so changing them in the config takes effect on the next
start.

`DATE_FORMAT` chooses how modification times are shown in the file panes:
`'short'` gives `YY-MM-DD HH:mm` (compact, no seconds) and `'full'` gives
`YYYY-MM-DD HH:mm:ss` (four-digit year plus seconds). Both use ISO-8601 ordering,
and the date column widens automatically for the longer form. After editing the
setting, **Tools → Reload Configuration** applies it without restarting.

## Incremental search (Migemo)

```python
MIGEMO_SEARCH    = True  # add Migemo (romaji -> Japanese) matches to incremental search
MIGEMO_MIN_LENGTH = 3    # shortest pattern handed to Migemo
```

With Migemo on, incremental search (the file panes, the text/diff viewers,
and the filter-list dialogs) also matches Japanese names from typed romaji —
`kensaku` finds `検索`. Plain matching always still applies, glob patterns
(`* ? [`) keep their exact wildcard behavior, and patterns shorter than
`MIGEMO_MIN_LENGTH` skip Migemo. See
[Migemo Search](MIGEMO_SEARCH_FEATURE.md).

## Text viewer encodings

```python
TEXT_ENCODINGS = ['utf-8', 'cp932', 'euc-jp', 'iso-2022-jp', 'latin-1']
```

The encodings offered by the text viewer's manual encoding picker (`Shift-E` in
the viewer). Automatic detection is built in and always the default; this list only
feeds the picker, for when detection gets a file wrong. Any
[Python codec name](https://docs.python.org/3/library/codecs.html#standard-encodings)
works. See [Text Encodings](TEXT_ENCODING_FEATURE.md).

## Sorting

```python
DEFAULT_SORT_MODE    = 'name'   # 'name', 'size', or 'date'
DEFAULT_SORT_REVERSE = False
```

Change sorting at runtime via the sort menu (`s`) or the quick-sort keys.

Name sorting is **natural** (alphanumeric): embedded numbers are compared as
numbers, so `file2` sorts before `file10`, and leading zeros (`Report001`,
`Report010`) order as expected. It is case-insensitive, always applies to the
`'name'` sort mode, and can't be turned off; the `'size'` and `'date'` modes are
unaffected. Directories are always listed before files regardless of sort mode.

## Confirmations

```python
CONFIRM_DELETE          = True   # before deleting files/directories
CONFIRM_QUIT            = True   # before quitting XeFM
CONFIRM_COPY            = True   # before copying
CONFIRM_MOVE            = True   # before moving
CONFIRM_EXTRACT_ARCHIVE = True   # before extracting an archive
CONFIRM_ARCHIVE_CREATE  = True   # before creating an archive
```

## Key Bindings

```python
KEY_BINDINGS = {
    'quit': ['Q'],
    'help': ['?'],
    'toggle_hidden': ['.'],
    # ... many more actions
}
```

Each action maps to a list of keys. Keys can be single characters (`'a'`, `'Q'`)
or special names (`'HOME'`, `'END'`, `'F1'`…`'F12'`, `'UP'`, `'DELETE'`, …). Letter
keys are **case-insensitive**: a bare `'q'` and a bare `'Q'` bind the *same*
physical key (the default template simply happens to spell them uppercase, e.g.
`'Q'`, `'C'`, `'M'`, `'K'`). To bind the shifted/uppercase variant on its own, use
`Shift-<letter>` (e.g. `'Shift-F'`). Non-alphabet characters such as `'?'` and
`'/'` stay case-sensitive.

Some actions use the extended, selection-aware form:

```python
KEY_BINDINGS = {
    'copy_files':       {'keys': ['C'], 'selection': 'required'},
    'create_directory': {'keys': ['M'], 'selection': 'none'},
}
```

Selection modes: `'any'` (default), `'required'` (only with a selection), `'none'`
(only without one). See [Key Bindings](KEY_BINDINGS_FEATURE.md) for the full
action list.

## Favorite Directories

```python
FAVORITE_DIRECTORIES = [
    {'name': 'Home', 'path': '~'},
    {'name': 'Documents', 'path': '~/Documents'},
    {'name': 'Projects', 'path': '~/Projects'},
]
```

Access favorites with the `J` key. See [Navigation Dialogs](NAVIGATION_DIALOGS_FEATURE.md).

## History and Logging

```python
MAX_HISTORY_ENTRIES = 100    # directory-history entries kept
MAX_LOG_MESSAGES    = 1000   # messages retained in the log pane
```

See [Logging](LOGGING_FEATURE.md).

## Progress Animation

```python
PROGRESS_ANIMATION_PATTERN = 'spinner'  # spinner, dots, progress, bounce, pulse, wave, clock, arrow
PROGRESS_ANIMATION_SPEED   = 0.2        # frame interval in seconds
```

## External Tools

```python
# Editor launched by edit_file. String ('vim') or list (['code', '--wait']).
# Defaults are chosen per backend: 'vim' in the terminal, 'code' in desktop mode.
TEXT_EDITOR = 'code' if is_desktop_mode() else 'vim'

# Diff tool launched from the diff viewers. Same string/list forms.
TEXT_DIFF   = ['code', '--diff'] if is_desktop_mode() else 'vimdiff'
```

### External Programs

```python
PROGRAMS = [
    {'name': 'Git Status', 'command': ['git', 'status']},
    {'name': 'Disk Usage', 'command': ['du', '-sh', '*']},
]
```

Each entry has a `name`, a `command` (list or string), and optional `options`
(e.g. `{'terminal': True}` for full-screen programs like `vim` or `less`).
Access programs with `x`. See
[External Programs](EXTERNAL_PROGRAMS_FEATURE.md).

### File Associations

```python
FILE_ASSOCIATIONS = [
    {'pattern': '*.pdf', 'open|view': ['open', '-a', 'Preview']},
    {'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif'], 'open|view': ['open', '-a', 'Preview']},
]
```

Each entry has a `pattern` (single fnmatch string or list) and one or more of
`open` / `view` / `edit` (or the combined `open|view`). Commands are lists or
strings. See [File Associations](FILE_ASSOCIATIONS_FEATURE.md).

## Caches

```python
S3_CACHE_TTL          = 60    # S3 directory-listing cache TTL (seconds)
SSH_CACHE_TTL         = 30    # SSH/SFTP cache TTL for successful results (seconds)
SSH_CACHE_ERROR_TTL   = 300   # SSH/SFTP cache TTL for cached errors (seconds)
ARCHIVE_CACHE_MAX_OPEN = 5    # max archives kept open at once
ARCHIVE_CACHE_TTL      = 300  # archive cache TTL (seconds)
```

## File Monitoring

Automatic reloading of a pane when its directory changes on disk:

```python
FILE_MONITORING_ENABLED                  = True  # enable/disable auto-reload
FILE_MONITORING_COALESCE_DELAY_MS        = 200   # event coalescing window (ms)
FILE_MONITORING_MAX_RELOADS_PER_SECOND   = 5     # rate limit
FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5     # polling interval when native events are unavailable (s)
```

See [File Monitoring](FILE_MONITORING_FEATURE.md).

## Backend and Window

The rendering backend is **not** a config option — it is chosen only by the
`--backend` command-line flag (`tui`, the default, `curses`, or `gui`/`macos`). In
desktop mode the window's size and position are remembered automatically across
runs; there are no window-geometry config keys. See
[Desktop Mode Guide](DESKTOP_MODE_GUIDE.md).

## Configuration Examples

### Faster workflow (fewer prompts)

```python
SHOW_HIDDEN_FILES = False
CONFIRM_COPY = False
CONFIRM_MOVE = False
MAX_LOG_MESSAGES = 500
```

### Power user

```python
DATE_FORMAT = 'full'
SHOW_HIDDEN_FILES = True
DEFAULT_LEFT_PANE_RATIO = 0.5
DEFAULT_LOG_HEIGHT_RATIO = 0.3
MAX_LOG_MESSAGES = 2000
PROGRESS_ANIMATION_PATTERN = 'wave'
```

### Desktop appearance (macOS)

```python
MONO_FONT_NAME = 'Menlo'
UI_FONT_NAME   = 'Helvetica Neue'
FONT_SIZE      = 14
TEXT_EDITOR    = 'code'
```

## Troubleshooting

### Changes don't take effect
1. Confirm the file path: `~/.xefm/config.py`
2. Check for Python syntax errors
3. Restart XeFM

### XeFM fails to start after editing
Likely a syntax error (missing quote/comma/bracket). Restore defaults:

```bash
rm ~/.xefm/config.py   # XeFM recreates it from the template on next run
```

### Can't find an option
Check `xefm/_config.py` — it is the authoritative, fully-commented list of every
available setting.

## Related Documentation

- [Color Schemes](COLOR_SCHEMES_FEATURE.md) - Themes and colors
- [Logging](LOGGING_FEATURE.md) - Logging configuration
- [External Programs](EXTERNAL_PROGRAMS_FEATURE.md) - External program integration
- [File Associations](FILE_ASSOCIATIONS_FEATURE.md) - File type associations
- [File Monitoring](FILE_MONITORING_FEATURE.md) - Automatic directory reloading
- [Key Bindings](KEY_BINDINGS_FEATURE.md) - Key binding configuration
- [Desktop Mode](DESKTOP_MODE_GUIDE.md) - Desktop mode (macOS)
- [XeFM User Guide](XEFM_USER_GUIDE.md) - Complete user guide
