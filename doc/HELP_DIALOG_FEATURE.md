# Help Dialog (F1 Key)

English \| [日本語](HELP_DIALOG_FEATURE.ja.md)

XeFM includes a scrollable help dialog listing the key bindings for whatever is
on screen. Press **F1** in the file list to open the one described here. The
viewers (text, image, file diff, directory diff) answer **F1** as well, each with
its own key list rather than this dialog.

## Usage

- **F1** — open the help dialog
- **↑/↓** — scroll line by line (the mouse wheel scrolls too)
- **Page Up/Down** — scroll by page
- **Home/End** — jump to top/bottom
- **Tab / Shift-Tab** — step to the next / previous link
- **Enter** — open the link stepped to; with none, close the dialog
- **Escape** — close (clicking outside the dialog closes it too)

## Details for an action

Where an action has more to say than its one line — what it needs, how it
treats the selection, what it refuses — its description in the dialog is a
link. Click it, or Tab to it and press Enter, and a page about that action
opens over the help: what it does, its keys, whether it needs a selection.
**Escape** returns to the help, where you left it. Your own actions get a page
when their docstring has more than a first line.

The same page opens from the [command palette](COMMAND_PALETTE_FEATURE.md) with
F1 on a row.

## Content

The help is generated from your current key bindings, so it always reflects your
configuration, including any customizations. Each row shows the key and what
it does, followed by the action's name (`Move cursor up · cursor_up`). That
name is what you write in `KEY_BINDINGS` to rebind the key, so you can find it
here. That is also why the list below
names what each section covers instead of quoting keys — the dialog itself is
the place to read which key does what on *your* setup.

When the active pane shows marks from an extra — the tag dots, a Git status —
the help opens with **Markers in this pane**: each mark, its color, and what it
means, for the extras active in this tab only (see
[File List Layouts](FILE_LIST_LAYOUTS_FEATURE.md)). The key sections follow,
in order:

- **Navigation** — moving the cursor, opening an item, going to the parent or
  the root, switching panes, and the jump dialogs (favorites, history, drives, a
  typed path, the other pane's directory)
- **Selection** — marking items one at a time or in bulk, clearing the marks,
  stepping between marked items, and comparing against the other pane
- **File Operations** — create, rename, copy, move and delete, archive and
  extract, file details, editing, copying names or paths to the clipboard, and
  handing the selection to the OS, an external program, or a shell
- **Search** — incremental search, the filename filter, and the recursive
  filename and content (grep) searches, plus the search dialog's own options
  (case, pattern syntax, subfolders)
- **Incremental Search (while the search bar is open)** — the keys the search bar
  itself answers while it is open: stepping between matches, selecting matches,
  accepting, cancelling
- **View** — the text viewer, comparing two files, hidden files, the color
  theme, and sorting (the sort dialog and the quick sorts)
- **Log Pane** — scrolling the log, resizing it, and copying from it
- **Other** — the menu bar, editing and reloading your config, help, and quit
- **Your Actions (config.py)** — the actions your own config defines, listed
  with the first line of each one's docstring. Absent unless your config defines at
  least one (see [Customization](CUSTOMIZATION_FEATURE.md))
- **Archive Formats** — which archive formats this copy of XeFM can browse,
  extract and create, and the libarchive it found. Built when XeFM starts rather
  than written down, because the list depends on what is installed (see
  [Archives](ARCHIVE_FEATURE.md))

A few rows appear only where they work. The terminal build lists the in-window
menu bar; the desktop builds leave it out, because there the menu bar is the
operating system's own.

An action your configuration leaves unbound shows an em dash instead of a key,
followed by the menu that reaches it — several useful actions ship unbound on
purpose, and the menu is how you run them until you bind one.

Usage tips are *not* here — they live in the separate Tip of the Day dialog
(Help → Tip of the Day…), described in [Tips](TIPS_FEATURE.md).

## Configuration

Help is bound to **F1** by default. Rebind the `help` action in `KEY_BINDINGS`
to use a different key:

```python
KEY_BINDINGS = {
    'help': ['F1', 'H'],  # F1 or H shows help
    # ... other bindings
}
```

## About dialog

Separate from the help dialog, the **About** dialog shows XeFM's name, version
number, the Python it runs on, and GitHub repository URL as a clickable link.
Open it from the menu bar, under **Help → About XeFM**, on every platform.

The Python line gives the version, the CPU architecture the Python was built
for (`x64`, `arm64` or `x86`; an x64 Python running emulated on an ARM machine
says `x64`), and whether the GIL is off:

- `Python 3.15.2 arm64 (free-threaded, GIL off)`: a free-threaded Python, with
  threads running in parallel.
- `Python 3.15.2 x64 (free-threaded build, GIL on)`: a free-threaded Python that
  turned the GIL back on, because an extension module does not support running
  without it, or because `PYTHON_GIL=1` is set.
- `Python 3.14.10 x64 (GIL on)`: a regular Python.

Close it with the OK button, or by pressing Enter, Space or ESC. Under a color
theme that carries a text effect (Sci-Fi) the text decodes into place as the box
opens; under every other theme it simply appears.
