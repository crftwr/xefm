# Text Editor Integration

XeFM can hand a file straight to your text editor. Put the cursor on the file and
press `E` — XeFM steps aside while the editor runs and comes back automatically
when you save and quit. Any editor that takes a filename argument works.

## Usage

1. Move the cursor to the file you want to edit.
2. Press `E`.
3. Edit, save, and exit the editor — XeFM redraws where you left off.

Editing is available for local files only. Directories (and the `..` parent)
can't be edited, and a warning is shown if you try. `E` is rebindable via the
`edit_file` action in your config's `KEY_BINDINGS`.

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
