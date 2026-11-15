# Text Editor Integration

English \| [日本語](TEXT_EDITOR_FEATURE.ja.md)

XeFM can hand files straight to your text editor. Put the cursor on a file —
or select several — and choose **File → Open With ▸ Text Editor** (`edit_files`): XeFM steps aside while the
editor runs and comes back automatically when you save and quit. Any editor
that takes filename arguments works.

## Usage

1. Move the cursor to the file you want to edit, or select multiple files.
2. Choose **File → Open With ▸ Text Editor** (`edit_files`). With a selection, every selected file is passed to the editor in
   one launch (`vim a.txt b.txt`), so you get one session over all of them.
3. Edit, save, and exit the editor — XeFM redraws where you left off.

Files on SSH and S3 panes can be edited too: XeFM edits a local copy and
uploads it each time you save — see [Remote Editing](REMOTE_EDIT_FEATURE.md).
Files inside archives are read-only and can't be edited in place. Directories
(and the `..` parent) can't be edited, and a warning is shown if you try; in a
mixed selection they are simply skipped. `edit_file` edits only the file
under the cursor, whatever is selected; no preset binds it. The key of
`edit_files` depends on
your keymap preset — see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side) — and can be rebound in your
config's `KEY_BINDINGS`.

## Which editor is used

When you run `edit_files` or `edit_file`, XeFM picks the editor like this:

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
    TEXT_EDITOR = ['code', '--wait']          # terminal: wait for the tab to close
    TEXT_EDITOR = ['wt', 'nt', 'vim']         # vim in a new Windows Terminal tab
    TEXT_EDITOR = [r'C:\Program Files\Vim\vim.exe']   # a path with spaces
```

Use the list form on Windows whenever the command is a full path: a plain
string is split the way a POSIX shell would, which eats the backslashes.

In terminal mode XeFM waits for the editor to exit. A launcher that opens the
editor elsewhere — `wt`, or a GUI editor without a wait flag — returns as soon
as it has handed the file over, so XeFM comes back immediately rather than when
you finish editing. What you save then shows up the way any outside change
does; see [File Monitoring](FILE_MONITORING_FEATURE.md).

In the desktop app XeFM never waits for the editor: it opens in a window of its
own and XeFM's window keeps responding, even with a wait flag such as
`code --wait` or `subl -w`.

The shipped default depends on how you run XeFM: `vim` in a terminal, and VS Code
(`code`) in the desktop app. Common choices include `vim`, `nano`, `emacs`,
`code` (VS Code), `subl` (Sublime Text), and `gedit`. In terminal mode, prefer a
terminal editor (vim, nano, emacs) so it can take over the screen; in the
desktop app, a GUI editor works well.

If the configured editor can't be found or exits with an error, XeFM reports it
and restores the file view.

## See also

- [Remote Editing](REMOTE_EDIT_FEATURE.md) — editing files on SSH and S3
- [Rename in the Editor](RENAME_IN_EDITOR_FEATURE.md) — rename many files by editing their names
- [File Associations](FILE_ASSOCIATIONS_FEATURE.md) — per-file-type editors and viewers
- [Diff Viewer](DIFF_VIEWER_FEATURE.md) — `TEXT_DIFF` sets the external merge / diff tool
- [Text Viewer](TEXT_VIEWER_FEATURE.md) — read-only viewing with **File → Open With ▸ Viewer** (`view_file`)
