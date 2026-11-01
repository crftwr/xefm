# Open With

English \| [日本語](OPEN_WITH_FEATURE.ja.md)

**Open With** asks which application should open a file this time, as
Finder's and Explorer's *Open With* do. The default application and the
`open` rule in [File Associations](FILE_ASSOCIATIONS_FEATURE.md) still decide
what `open_with_os` does every other time; Open With is for the time you want
something else.

## Using it

Choose **File → Open With ▸ Choose App…**, or **Open With…** in the
[context menu](CONTEXT_MENU_FEATURE.md), or run `open_with` from the
[command palette](COMMAND_PALETTE_FEATURE.md). It has no key in any keymap
preset; give it one in `KEY_BINDINGS` if you use it often (see
[Key Bindings](KEY_BINDINGS_FEATURE.md)).

A list of applications opens over the active pane. Type to narrow it, and
press `Enter` to open the selected files — or the file under the cursor — in
the one highlighted. The line under the list shows the command it runs or
where the application is, and the OS's default application for the file says
`default` on the right.

The application you chose last for a file type is listed first the next time,
and XeFM remembers it after a restart.

## What is listed

Two kinds of entries, in this order:

1. **Your own programs** — the `open_with` lists of the
   `FILE_ASSOCIATIONS` rules the file matches (see below).
2. **The OS's applications** — what Finder (macOS), Explorer (Windows) or the
   desktop's file-type database (Linux, through `gio`) offers for the file.

The OS's applications are listed in the desktop app, and in the terminal app
when it runs on the computer you sit at. Over SSH they are left out: they
would open on the other machine, not on yours. On Linux the terminal app also
needs a graphical session (`DISPLAY` or `WAYLAND_DISPLAY`).

### Several files

With several files selected, only the applications that can open **every**
one of them are listed, and all the files go to the one you choose in one
launch. Photos and a PDF together, say, list what opens both. When nothing
opens them all, XeFM says *No app can open all selected files.*

A program from a `'*'` rule matches every file, so it is always listed — a
good place for an editor or a hex viewer.

### What is skipped

- **Directories.** Open With opens files.
- **Files on a remote or inside an archive.** An application needs a file on
  this computer; copy the file out first. Each skipped file is named in the
  log pane, and the rest still open.

## Adding your own programs

Give a `FILE_ASSOCIATIONS` rule an `open_with` list in `~/.xefm/config.py`.
Each entry is shaped like a [`PROGRAMS`](EXTERNAL_PROGRAMS_FEATURE.md) entry:
a `name`, a `command` list, and optional `options`.

```python
FILE_ASSOCIATIONS = [
    {
        'pattern': ['*.jpg', '*.png'],
        'open': ['open', '-a', 'Preview'],
        'open_with': [
            {'name': 'GIMP', 'command': ['open', '-a', 'GIMP']},
            {'name': 'Pixelmator', 'command': ['open', '-a', 'Pixelmator Pro']},
        ],
    },
    {
        'pattern': '*',
        'open_with': [
            {'name': 'VS Code', 'command': ['code']},
            {'name': 'Hex view', 'command': ['hexyl'], 'options': {'terminal': True}},
        ],
    },
]
```

- **Every matching rule adds its list.** This is unlike `open`, `view` and
  `edit`, where the first matching rule wins. The lists are joined top to
  bottom, so a photo above is offered GIMP, Pixelmator, VS Code and Hex view.
- **A name declared twice keeps its first entry,** so a specific rule can
  give a program a different command for its files.
- **The files are added to the end of the command,** with their full paths.
  The program runs in the active pane's directory with the same `XEFM_*`
  environment a `PROGRAMS` entry gets.
- **`'terminal': True`** hands the terminal to the program and waits, for
  full-screen tools like `less` or `hexyl` — in the desktop app it opens in a
  terminal window instead (see [External Terminal](EXTERNAL_TERMINAL_FEATURE.md)).
  Without it the program runs in the background and its output goes to the
  log pane.

## Open With and External Programs

[External Programs](EXTERNAL_PROGRAMS_FEATURE.md) (`programs`) lists every
`PROGRAMS` entry whatever the cursor is on: it is for commands that work on
XeFM's state — a Git command, a disk-usage report, a script reading
`XEFM_*`. Open With lists only what fits the files: it is for opening them in
an application.

## Related

- [File Associations](FILE_ASSOCIATIONS_FEATURE.md) — `open`, `view` and `edit` per file type
- [External Programs](EXTERNAL_PROGRAMS_FEATURE.md) — `PROGRAMS` and the `terminal` option
- [Menu Bar](MENU_BAR_FEATURE.md) — where **Choose App…** is
