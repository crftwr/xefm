# Help Dialog (? Key)

XeFM includes a scrollable help dialog listing the key bindings for whatever is
on screen. Press **?** in the file list to open the one described here. The
viewers (text, image, file diff, directory diff) answer **?** as well, each with
its own key list rather than this dialog.

## Usage

- **?** — open the help dialog
- **↑/↓** — scroll line by line (the mouse wheel scrolls too)
- **Page Up/Down** — scroll by page
- **Home/End** — jump to top/bottom
- **Escape** or **Enter** — close (clicking outside the dialog closes it too)

## Content

The help is generated from your current key bindings, so it always reflects your
configuration, including any customizations. That is also why the list below
names what each section covers instead of quoting keys — the dialog itself is
the place to read which key does what on *your* setup. The sections, in order:

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
  with the descriptions you gave them. Absent unless your config defines at
  least one (see [Customization](CUSTOMIZATION_FEATURE.md))
- **Archive Formats** — which archive formats this copy of XeFM can browse,
  extract and create, and the libarchive it found. Built when XeFM starts rather
  than written down, because the list depends on what is installed (see
  [Archives](ARCHIVE_FEATURE.md))

A few rows appear only where they work. The terminal build lists the in-window
menu bar and the subshell; the desktop builds leave both out, because there the
menu bar is the operating system's own and there is no terminal to hand over.

An action your configuration leaves unbound shows an em dash instead of a key,
followed by the menu that reaches it — several useful actions ship unbound on
purpose, and the menu is how you run them until you bind one.

Usage tips are *not* here — they live in the separate Tip of the Day dialog
(Help → Tip of the Day…), described in [Tips](TIPS_FEATURE.md).

## Configuration

Help is bound to **?** by default. Rebind the `help` action in `KEY_BINDINGS`
to use a different key:

```python
KEY_BINDINGS = {
    'help': ['?'],  # ? shows help
    # ... other bindings
}
```

## About dialog

Separate from the help dialog, the **About** dialog shows XeFM's name, version
number, and GitHub repository URL as a clickable link. Open it from the menu
bar, under **Help → About XeFM**, on every platform.

Close it with the OK button, or by pressing Enter, Space or ESC. Under a color
theme that carries a text effect (Sci-Fi) the text decodes into place as the box
opens; under every other theme it simply appears.
