# Text Editor Integration

XeFM can hand files straight to your text editor. Put the cursor on a file —
or select several with `Space` — and press `E`: XeFM steps aside while the
editor runs and comes back automatically when you save and quit. Any editor
that takes filename arguments works.

## Usage

1. Move the cursor to the file you want to edit, or select multiple files.
2. Press `E`. With a selection, every selected file is passed to the editor in
   one launch (`vim a.txt b.txt`), so you get one session over all of them.
3. Edit, save, and exit the editor — XeFM redraws where you left off.

Editing is available for local files only. Directories (and the `..` parent)
can't be edited, and a warning is shown if you try; in a mixed selection they
are simply skipped. `E` is rebindable via the `edit_file` action in your
config's `KEY_BINDINGS`.

## Which editor is used

When you press `E`, XeFM picks the editor like this:

1. **A matching `edit` entry in `FILE_ASSOCIATIONS`** wins — so you can send,
   say, images to an image editor and `.md` files to a Markdown app. If an
   entry is set explicitly to `None`, that file type has *no* editor and XeFM
   won't fall back. See [File Associations](FILE_ASSOCIATIONS_FEATURE.md).
2. **Otherwise the `TEXT_EDITOR` setting** is used.

Set `TEXT_EDITOR` in `~/.xefm/config.py`:

```python
class Config:
    TEXT_EDITOR = 'nano'   # your preferred editor
```

If the editor needs arguments, write the setting as a list — each element is
one argument, exactly as typed on a command line:

```python
class Config:
    TEXT_EDITOR = ['code', '--wait']          # wait for the window to close
    TEXT_EDITOR = ['wt', 'nt', 'vim']         # vim in a new Windows Terminal tab
    TEXT_EDITOR = [r'C:\Program Files\Vim\vim.exe']   # a path with spaces
```

Use the list form on Windows whenever the command is a full path: a plain
string is split the way a POSIX shell would, which eats the backslashes.

A launcher that opens the editor elsewhere — `wt`, or a GUI editor without a
wait flag — returns as soon as it has handed the file over, so XeFM comes back
immediately rather than when you finish editing. What you save then shows up
the way any outside change does; see
[File Monitoring](FILE_MONITORING_FEATURE.md).

The shipped default depends on how you run XeFM: `vim` in a terminal, and VS Code
(`code`) in the desktop app. Common choices include `vim`, `nano`, `emacs`,
`code` (VS Code), `subl` (Sublime Text), and `gedit`. In terminal mode, prefer a
terminal editor (vim, nano, emacs) so it can take over the screen; in the
desktop app, a GUI editor works well.

If the configured editor can't be found or exits with an error, XeFM reports it
and restores the file view.

## See also

- [File Associations](FILE_ASSOCIATIONS_FEATURE.md) — per-file-type editors and viewers
- [Diff Viewer](DIFF_VIEWER_FEATURE.md) — `TEXT_DIFF` sets the external merge / diff tool
- [Text Viewer](TEXT_VIEWER_FEATURE.md) — read-only viewing with `V`
