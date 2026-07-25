# File Operations

XeFM's core file operations — copy, move, duplicate, and rename — all share the
same conflict handling and progress display. This document covers how each one
works and the options you can configure.

For the complete list of key bindings, see the
[XeFM User Guide](XEFM_USER_GUIDE.md) or press **?** in XeFM.

## Copy

Copy the selected file(s) to the other pane.

1. Select one or more items (**Space** to toggle, **A** to select all files).
2. Press **C**.
3. Confirm the destination when prompted.

Directories are copied recursively. If a name already exists at the
destination, XeFM asks how to resolve it (see
[Conflict resolution](#conflict-resolution)).

XeFM confirms before copying by default. To skip the confirmation:

```python
CONFIRM_COPY = False   # default: True
```

## Move

Move the selected file(s) to the other pane.

1. Select one or more items.
2. Press **M**.
3. Confirm the destination when prompted.

(With nothing selected, **M** instead prompts for a new directory name — see
[Create File Operations](#create-file-operations).)

XeFM confirms before moving by default:

```python
CONFIRM_MOVE = False   # default: True
```

### Moving between storage types

Move works the same whether the source and destination are on your computer or
on cloud storage such as Amazon S3.

- **Same storage** (local → local, or within one S3 bucket): XeFM uses a fast
  rename — the move happens instantly with no data copying.
- **Different storage** (local → S3, S3 → local, S3 → S3): XeFM copies the file
  to the destination, verifies the copy, and only then removes the original.
  Large transfers show progress.

Because the original is removed only after a verified copy, **a failed
cross-storage move never deletes your source files**. Directory moves work too —
all contained files are moved recursively.

For S3 you need AWS credentials configured and the `boto3` package installed.
Cross-storage transfers depend on your network speed, so test with small files
first when setting up a new storage backend.

## Duplicate

Make an in-place copy of a file or directory — XeFM's equivalent of Finder's
**Duplicate** (⌘D). The copy lands in the **same directory** as the original,
automatically renamed so it never collides.

Select one or more items (or just place the cursor on one), then choose
**Duplicate** from either:

- the **File** menu in the menu bar, or
- the **right-click context menu** on a file row.

When nothing is explicitly selected, the entry under the cursor is duplicated;
afterward the cursor lands on the new copy.

There is **no default keyboard shortcut**. To add one, bind the
`duplicate_files` action in your config, e.g.:

```python
KEY_BINDINGS['duplicate_files'] = ['Shift-D']
```

**Copy to Other Pane** (**C**) also duplicates: when both panes show the same
directory, copying auto-renames exactly like Duplicate instead of erroring.
(Move still refuses a same-directory target.)

### Naming

Duplicates use the same ` (N)` scheme as "Keep both" conflict resolution:

| Original            | Duplicate            | Next duplicate         |
|---------------------|----------------------|------------------------|
| `report.pdf`        | `report (1).pdf`     | `report (2).pdf`       |
| `photos` (folder)   | `photos (1)`         | `photos (2)`           |
| `.bashrc` (dotfile) | `.bashrc (1)`        | `.bashrc (2)`          |
| `archive.tar.gz`    | `archive.tar (1).gz` | `archive.tar (2).gz`   |

The suffix is inserted before the last extension for files and appended for
directories and extension-less names.

Duplicating shows a confirmation dialog by default. Turn it off for instant,
Finder-like behavior:

```python
CONFIRM_DUPLICATE = False   # default: True
```

Directories are duplicated recursively, so the confirmation is a useful guard
against duplicating a large tree by accident.

### Notes and limits

- **Read-only archives**: you cannot duplicate into a browsed archive.
- **Search-results (virtual) panes**: Duplicate is unavailable — those results
  span many directories, so there is no single place to write the copy.
- Large files show byte-level progress and can be cancelled mid-copy.

## Conflict resolution

When a copy, move, or archive extraction would overwrite an existing file, XeFM
stops and asks what to do instead of silently overwriting. The dialog offers:

- **o — Overwrite**: replace the existing file with the new one.
- **s — Skip**: skip this file and continue (copy/move only).
- **r — Rename**: type a different destination name.
- **c — Cancel**: abort the whole operation.

### Rename

Choosing **Rename** opens an input field pre-filled with the original name. Edit
it to whatever you want and press **Enter**. If the new name *also* collides,
the dialog reappears so you can overwrite, rename again, or cancel — this
repeats until you pick a free name or cancel.

Renaming lets you keep both files (the original and the incoming one) rather
than overwriting, which is a safer choice for important files.

### Multiple conflicts

When several files collide, XeFM walks through them one at a time. For each
conflict you can Overwrite, Rename, or Skip that file — or choose **Skip All**
to skip every remaining conflict at once. Files with no conflict are copied or
moved automatically. Each conflict is handled individually; there is no
automatic numbering or pattern-based batch renaming (for that, see
[Batch Rename](BATCH_RENAME_FEATURE.md)).

Conflict resolution works across every storage type XeFM supports (local ↔ S3,
and so on) and is available whenever the corresponding confirmation setting is
enabled:

```python
CONFIRM_COPY = True             # copy conflicts
CONFIRM_MOVE = True             # move conflicts
CONFIRM_EXTRACT_ARCHIVE = True  # extraction conflicts
```

All three are on by default.

## Progress display

Copy and move operations show detailed, real-time progress — especially useful
for large files or directories with many files. The UI stays responsive while
the transfer runs in the background.

The status bar shows an animated spinner, a file count, the current filename,
and — for large files — byte-level progress:

```
⠋ Copying (to destination)... 45/100 (45%) - subdir/large_file.dat [67%]
```

- **⠋** — spinner confirming the operation is active (not frozen).
- **Copying (to destination)** — operation type and where it is going.
- **45/100 (45%)** — files processed out of the total.
- **subdir/large_file.dat** — the file currently being transferred, shown with
  its relative path inside subdirectories.
- **[67%]** — byte-level progress for the current large file, in human-readable
  units (B, K, M, G, T).

Byte-level progress appears only for files large enough to take multiple
read/write passes; small files complete too quickly to need it. Long filenames
are truncated to fit the terminal width.

### Cancelling

While an operation runs, normal input is blocked so you can't move the cursor or
start another command. Press **ESC** to cancel. Cancellation is checked between
files and, for large files, at each chunk — so it may take a moment to stop at
the next checkpoint. Partial files are removed cleanly, leaving nothing
half-written behind.

Progress works across storage types, so local, cross-storage, and S3-to-S3
transfers all show the same feedback. No configuration is required — it is
always on and adapts automatically to file size, file count, and terminal width.

## Create file operations

- **Create directory**: press **M** with nothing selected, type a name, and
  press **Enter**.
- **Create file**: press **Shift-E**, type a filename, and press **Enter**. The
  new empty file opens immediately in your configured text editor.

Both check that the current directory is writable and refuse to overwrite an
existing name.

## See Also

- [Batch Rename](BATCH_RENAME_FEATURE.md) — rename many files with regex patterns
- [Archive](ARCHIVE_FEATURE.md) — create, extract, and browse archives
- [XeFM User Guide](XEFM_USER_GUIDE.md) — complete documentation
