# File Operations

English \| [日本語](FILE_OPERATIONS_FEATURE.ja.md)

XeFM's core file operations — copy, move, duplicate, and rename — all share the
same conflict handling and progress display. This document covers how each one
works and the options you can configure.

The keys for these operations depend on your keymap preset — see
[Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side), or press
**F1** in XeFM for the keys you have.

## Copy

Copy the selected file(s) to the other pane.

1. Select one or more items (`toggle_select_down` to toggle one,
   `toggle_select_files` for all files).
2. Choose **File → Copy to Other Pane** (`copy_files`).
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
2. Choose **File → Move to Other Pane** (`move_files`).
3. Confirm the destination when prompted.

(In AFX style, `move_files` and `create_directory` share one key: with nothing
selected, it prompts for a new directory name instead — see
[Create File Operations](#create-file-operations).)

XeFM confirms before moving by default:

```python
CONFIRM_MOVE = False   # default: True
```

### Moving between disks and storage types

Move works the same whether the source and destination are on the same disk, on
two different disks, or on cloud storage such as Amazon S3.

- **Same disk** (within one drive, or within one S3 bucket): XeFM uses a fast
  rename — the move happens instantly with no data copying.
- **Different disk** (to an external drive, another partition, or a network
  share): a rename cannot cross a disk, so XeFM copies the file across and then
  removes the original. This takes as long as a copy does, and it shows the same
  progress a copy does — a bar per file with the bytes transferred so far.
- **Different storage** (local → S3, S3 → local, S3 → S3): XeFM copies the file
  to the destination, verifies the copy, and only then removes the original.
  Large transfers show progress.

Because the original is removed only after a verified copy, **a failed move
across disks or storage never deletes your source files**. Directory moves work
too — all contained files are moved recursively.

For S3 you need AWS credentials configured and the `boto3` package installed.
Cross-storage transfers depend on your network speed, so test with small files
first when setting up a new storage backend.

## Copy / Move to a typed directory

**File → Copy to…** (`copy_files_to`) and **File → Move to…**
(`move_files_to`) copy or move the selected file(s) somewhere other than the
other pane, without navigating there first.

1. Select one or more items.
2. Choose **File → Copy to…** or **File → Move to…**.
3. Edit the destination and press **Enter**. The prompt starts with the other
   pane's directory; **Tab** completes directory names.

A relative path is taken from the **current** pane: `.` is the current
directory, `..` its parent, `sub` a directory inside it. `~` and absolute paths
work as in Jump to Path, as do `s3://…` / `ssh://…` locations. The destination
must be an existing directory; anything else is refused in the prompt. From
there it is an ordinary copy or move — the same confirmation, conflict handling
and progress — and copying into the current directory itself duplicates, as
**Copy to Other Pane** does.

The menu bar's File menu and the item context menu carry these as **Copy to…**
and **Move to…**.

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

AFX style ships it with **no keyboard shortcut** (Orthodox has one — see
[Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side)). To add one,
bind the `duplicate_files` action in your config, e.g.:

```python
KEY_BINDINGS['duplicate_files'] = ['Shift-D']
```

**Copy to Other Pane** (`copy_files`) also duplicates: when both panes show the same
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

## Delete

**File → Move to Trash…** (`delete_files`, also on `Delete`) moves the
selection, or the item under the cursor, to the **Trash**, called the Recycle
Bin on Windows. You can restore it from Finder, Explorer or your desktop's file
manager. **File → Delete Permanently…** (`delete_permanently`, also on
`Shift-Delete`) deletes for good, without the Trash. Each asks first. In AFX
style their keys act only on marked items, as do that preset's keys for
copying, moving and creating an archive; with nothing marked, the delete keys
do nothing. The menu commands still take the item under the cursor. See
[Deleting to the Trash](TRASH_FEATURE.md).

## Conflict resolution

When a copy or move would land on a file or folder that already exists, XeFM
stops and asks what to do instead of silently overwriting. The dialog names the
item and shows both sides side by side — size and modification time of the
**Source** and of the **Existing** one — with the newer and the larger side
marked, so you can decide without leaving the dialog:

```
 File exists (2 of 5)
 report.pdf already exists in the destination.

 │          │              Size │ Modified                 │
 │ Source   │ 120.6 KB · larger │ 2026-10-13 09:43 · newer │
 │ Existing │            2.0 KB │ 2026-10-12 09:43         │

 [ ] Apply to all remaining
   Overwrite   Overwrite older   [ Skip ]   Keep both   Compare   Cancel
```

| Key | Choice | What happens |
|---|---|---|
| `o` | **Overwrite** | Replace the existing item. A folder is merged: its files are copied into the existing folder, replacing same-named ones. |
| `u` | **Overwrite older** | Replace the existing item only if it is older than the source; otherwise skip it. For a folder, the merge decides file by file. |
| `s` | **Skip** | Leave the existing item alone and go on (the default — Enter). |
| `k` | **Keep both** | Copy under a free name instead: `report (1).pdf`. |
| `d` or `=` | **Compare** | Open the two files in the [diff viewer](DIFF_VIEWER_FEATURE.md). Close it (Esc) to come back to the same dialog. Shown only when both sides are files. |
| `c` / Esc | **Cancel** | Stop the whole operation. |

`a` or Space toggles **Apply to all remaining**. Checked, your choice answers
every later conflict of the same operation without asking again. With
**Overwrite older** that is "overwrite all older": each remaining file is
still judged on its own dates.

### When a folder already exists

Copying or moving a folder onto a folder of the same name **merges** them: the
dialog asks once for the folder, not for each file inside, and the choice acts on
the files in it — **Overwrite** replaces every file that exists in both,
**Overwrite older** replaces only those older at the destination, **Skip** leaves
the whole folder, **Keep both** copies it as `name (1)`.

So instead of the two folders' own size and date, which say nothing about their
contents, the dialog counts what the merge would meet:

```
 Folder exists
 photos already exists in the destination. The folders are merged.

 • 12 files in both: 8 older at the destination, 4 not
 • 40 files only in the source
```

"8 older at the destination" is exactly what **Overwrite older** would replace.
The count stops after 10,000 files, so a huge or remote folder doesn't hold the
question back; the dialog then says the rest were not checked.

### When something appears at the destination later

The questions above are asked when the operation starts. If something with the
same name turns up at the destination after that — another program wrote it,
or a background job ran there in the meantime — XeFM notices when it gets to
that file, and asks then, with the same dialog. Nothing is merged or skipped
without your say:

- **Apply to all remaining** keeps working. An answer you gave at the start
  also covers what turns up later, and an answer you give later covers the
  rest of the operation.
- The dialog has no "2 of 5" count, since how many more will turn up isn't
  known yet.
- If the item is gone again by the time you answer, the file is copied
  anyway.
- **Keep both** picks its free name when the file is written, so a
  `report (1).pdf` that has appeared in the meantime makes it
  `report (2).pdf`. Duplicate works the same way.
- A **move** that leaves anything at the destination alone keeps its source.
  Nothing is deleted from the source that didn't arrive at the destination.
- A job in the background waits with the question until you bring it forward
  (see [Background Jobs](BACKGROUND_JOBS_FEATURE.md#when-a-job-needs-an-answer)).

XeFM runs one writing operation at a time (see
[Background Jobs](BACKGROUND_JOBS_FEATURE.md#one-at-a-time)), so between
checking a name and writing it, no other XeFM operation can get in. A program
outside XeFM still can, as with any file manager.

### What "older" means

The existing item counts as older when its modification time is more than
two seconds before the source's. Times closer than that count as equal and the
file is skipped, because FAT/exFAT drives (USB sticks, SD cards) store times in
2-second steps and would otherwise look "older" on every copy. If either time
can't be read, the file is skipped, so nothing is overwritten on a guess.

When a **move** merges a folder under Overwrite older, files whose existing copy
was newer stay in the source folder, and the source folder is not removed. The
log names each one (`Kept '…': the destination's copy is not older`).

Conflict resolution works across every storage type XeFM supports (local ↔ S3,
SFTP, and so on). It always asks, even with `CONFIRM_COPY` / `CONFIRM_MOVE`
turned off; those settings control only the "Copy N item(s) to …?" question
before the operation starts. Extracting an archive into a folder that already
exists asks its own question first (`CONFIRM_EXTRACT_ARCHIVE`).

## Progress display

Copy and move operations show detailed, real-time progress — especially useful
for large files or directories with many files. The UI stays responsive while
the transfer runs in the background.

The progress dialog shows one overall bar and, below it, the files currently
in flight:

```
Copy…
[███████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]
12 / 100 items — 350.2M / 2.1G

photos/IMG_2041.jpg                 8.1M / 24.5M
photos/IMG_2042.jpg                12.9M / 31.0M
notes.txt
video/trip.mov                    310.5M / 1.4G
```

- **The overall bar** tracks the whole operation by *bytes* as well as file
  count, so one huge file among many small ones does not park the bar near
  the end while most of the actual work is still ahead.
- **12 / 100 items** counts files that have *finished*. When several files copy
  in parallel, starting four files does not read as four files done.
- **350.2M / 2.1G** — bytes moved so far out of the operation's total, in
  human-readable units (B, K, M, G, T).
- **One row per file in flight** — parallel copies show each worker's current
  file with its own byte counts, not just whichever file started most recently.
  Rows show byte counts only for files large enough to take multiple
  read/write passes; small files complete too quickly to need them. Long
  filenames are truncated to fit.

### Cancelling

While an operation's progress dialog is open, the rest of XeFM waits for it.
To keep working instead, send the operation to the
[background](BACKGROUND_JOBS_FEATURE.md) with the dialog's **Run in
background** button.

Press **Cancel** (or **ESC**), then **Cancel operation**, to cancel. It asks first, and
Enter or **ESC** again keeps the operation running. Cancellation is checked between
files and, for large files, at each chunk — so it may take a moment to stop at
the next checkpoint. Partial files are removed cleanly, leaving nothing
half-written behind.

This applies to remote transfers too: a slow upload to S3 or an SFTP server
stops when you cancel it, rather than running on to completion. A cancelled S3 upload leaves no object behind and no partially
uploaded pieces to be billed for; a cancelled download leaves no file on disk.
An SFTP transfer stops within about half a second of the keypress.

Progress works across disks and storage types, so a move to an external drive
gets the same per-file byte progress that a local copy, a cross-storage transfer,
or an S3-to-S3 transfer does. No configuration is required — it is
always on and adapts automatically to file size, file count, and terminal width.

## Create file operations

- **Create directory**: **File → New Folder…** (`create_directory`; in AFX
  style the same key as `move_files`, with nothing selected), type a name, and
  press **Enter**.
- **Create file**: **File → New File…** (`create_file`), type a filename, and
  press **Enter**. The
  new empty file opens immediately in your configured text editor.

Both check that the current directory is writable and refuse to overwrite an
existing name.

## Where the cursor ends up

An operation never sends the cursor back to the top of the pane. After a delete,
a copy, a move, a duplicate or a rename, the cursor is still on the file it was
on — even though rows above it have come or gone, and even on a pane sorted by
size or date, or sorted in reverse.

When the file under the cursor is the one that disappeared — you deleted it,
moved it out, or deleted a whole block of selected files — the cursor drops to
the entry that took its place, so repeating `delete_files` deletes down through
a directory. At the end of the listing it moves up to the new last entry
instead, and in a directory you have just emptied it returns to the top.

A rename keeps the cursor on the renamed file under its new name, whether you
renamed one file or ran a [batch rename](BATCH_RENAME_FEATURE.md) over many, and
a duplicate leaves the cursor on the new copy. The same holds for changes XeFM
did not make itself: a file appearing or vanishing in a directory another program
is writing to moves the rows, not your cursor.

The one place the cursor deliberately does return to the top is a **filter**
change (**View → Filter…**, `filter`), which clears the selection and starts the narrowed listing fresh.

## See Also

- [Batch Rename](BATCH_RENAME_FEATURE.md) — rename many files with regex patterns
- [Archive](ARCHIVE_FEATURE.md) — create, extract, and browse archives
- [XeFM User Guide](XEFM_USER_GUIDE.md) — complete documentation
