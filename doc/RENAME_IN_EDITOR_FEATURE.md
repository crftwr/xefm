# Rename in the Editor

English \| [日本語](RENAME_IN_EDITOR_FEATURE.ja.md)

Rename many files by editing their names in your text editor. You can use
everything your editor offers: multi-cursor editing, search and replace,
column selection, or typing a full-width space. You can also read long names
in full before anything is renamed.

## Usage

1. Select the files to rename (or put the cursor on one) and choose
   **File → Rename ▸ Rename in Editor…** (`rename_in_editor`).
2. Your editor (`TEXT_EDITOR`) opens a file listing the names, one per line.
3. Change the names in place, save, and close the editor.
4. XeFM lists every change (`old  →  new`). Choose **Rename** to apply them,
   **Edit Again** to go back to the editor, or **Cancel**.

Lines you leave unchanged are left alone. If the cursor was on a file that got
renamed, it stays on that file under its new name.

## Rules

- **Don't add, remove or reorder lines.** Each line belongs to the file it
  started with. If the number of lines changes, XeFM refuses and offers
  **Edit Again**.
- **Swaps work.** Changing `a.txt` to `b.txt` and `b.txt` to `a.txt` swaps the
  two names, and so does any longer cycle or shift.
- **Conflicts are refused, with the line number:** an empty name, a name with
  `/` or another character file names can't hold, two lines with the same new
  name, or a new name already used by a file outside the selection.
- **Names are compared the way the disk compares them.** Where the disk ignores
  case (Windows, and macOS by default), `Foo.txt` and `foo.txt` are one name:
  changing only the case of a name works, and two lines that differ only in case
  are refused. Where case matters (Linux by default), they are two names.
- Spaces at the start or end of a line are kept as part of the name.

## Editors that open their own window

A GUI editor such as VS Code (without `--wait`) returns right away, before you
have edited anything. In the desktop app XeFM never waits for the editor, with
or without `--wait`, so this is always the case there. XeFM then shows **Edit the names in your editor and save
the file, then choose Apply.** Choose **Apply** once you've saved, or
**Cancel** to drop the rename.

## Compared with batch rename

**File → Rename ▸ Rename…** (`rename`) on a selection opens [Batch Rename](BATCH_RENAME_FEATURE.md), which renames
with a regular expression and a replacement pattern. Use batch rename when one
pattern describes the whole change. Use rename in the editor when the names
need individual edits, or when a pattern is hard to write. Both are available.
Only AFX style gives `rename_in_editor` a key (see
[Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side)); give it one in any preset with
`KEY_BINDINGS`.
