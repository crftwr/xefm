# Remote Editing

English \| [日本語](REMOTE_EDIT_FEATURE.ja.md)

Edit a file on an SSH or S3 pane (**File → Open With ▸ Text Editor**, `edit_files`) and it
opens in your editor like a local file. Each time you save, XeFM uploads your changes to where the file
came from.

## How it works

1. Put the cursor on a remote file (or select several) and choose
   **File → Open With ▸ Text Editor** (`edit_files`; its key depends on your keymap preset —
   see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side)).
2. XeFM downloads the file and opens the copy in your editor (`TEXT_EDITOR`, or
   the `edit` program in `FILE_ASSOCIATIONS`).
3. Edit and save as often as you like. Each save is uploaded, and the log
   says so: `Uploaded ssh://host/srv/app/config.yaml`.

The copy is kept under `~/.xefm/edit/`, in folders that follow the remote path
(`~/.xefm/edit/ssh/host/srv/app/config.yaml`), so your editor's title bar
shows which file you are editing.

Saving works the same with a terminal editor like vim and with a GUI editor
like VS Code. XeFM checks the copy about once a second for as long as it is
running, so an editor in its own window doesn't need a wait flag.

## When someone else changed the file

Before every upload XeFM checks whether the remote file changed since you
opened it (or since your last upload). If it did, XeFM asks before
overwriting:

- **Overwrite** replaces the remote file with your version.
- **Keep Remote** leaves the remote file as it is. Your edit stays in the local
  copy, and the message tells you where that is.

## When an upload fails

A failed upload — lost connection, permission denied — shows a message naming
the error and the local copy that still holds your edit. Nothing is deleted.
Save again to retry, or copy the file up by hand.

## When XeFM exits

Local copies that match the remote file are deleted. A copy holding an edit
that never reached the remote is kept, and the log names it.

Running `edit_files` again on a file you are already editing reopens the same copy
when it holds an edit that hasn't been uploaded. Otherwise XeFM downloads the
file again, so you start from what the server holds now.

## Limits

- **Archives are read-only.** Files inside a zip, tar or other archive can be
  viewed but not edited in place; copy one out to edit it.
- **Whole-file uploads.** Each save uploads the whole file, which suits the
  configuration files and scripts this is meant for.
- **Change detection uses the file's time and size.** A remote change that
  keeps both the same is not detected.

## See also

- [Text Editor Integration](TEXT_EDITOR_FEATURE.md) — choosing the editor
- [S3 Support](S3_SUPPORT_FEATURE.md)
