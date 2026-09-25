# File Details (I Key)

Press **I** to open a scrollable dialog with detailed information about files and
directories.

## Usage

- **I** — show details
  - If files are selected, shows details for every selected item
  - If nothing is selected, shows details for the item under the cursor
- **↑/↓** — scroll line by line
- **Page Up/Down** — scroll by page
- **Home/End** — jump to top/bottom
- **Q** or **ESC** — close

## Information shown

### Files

- **Name** and full **path**
- **Type** — File / Directory / Symbolic Link / Special
- **Size** — human-readable (B, KB, MB, GB)
- **Timestamps** — last modified and last accessed
- **Permissions** — Unix-style `rwxrwxrwx`, plus owner and group
- **Symlink target** — for symbolic links

### Directories

Directories show the same fields, plus a recursive total and a contents count:

- **Total size** — how many bytes everything inside adds up to, shown
  human-readable and in exact bytes
- **On disk** — how much space it actually takes up on the drive
- **Contents** — how many files and folders it contains, recursively

These are counted in the background *after* the dialog opens: the dialog
appears instantly and the numbers climb until the count finishes, so a large
(or remote) directory never blocks the UI. While counting, the row is marked
*scanning…*; if some subdirectories could not be read, the result notes how
many were unreadable. Closing the dialog stops the counting.

Symbolic links are counted as single entries and never followed, so a link
pointing back into the same tree cannot inflate the total.

When multiple items are selected, the summary at the top shows the live
**Total size**, **On disk** and **Total items** (files and folders) across the
whole selection, including everything inside selected directories.

#### Why there are two size rows

They are the same two numbers Finder shows as *Size* and *on disk*, and for
most folders they differ only by rounding — every file takes up a whole number
of blocks. They come apart when a folder holds something stored compactly:

- a **sparse** file, which is mostly empty space that was never written — a
  virtual machine disk image is the usual case, and can be a terabyte long
  while taking up twenty gigabytes
- a **compressed** file, which macOS stores smaller than its contents
- a **cloned** copy, which shares its storage with the original until one of
  them changes

For a folder like `~/Library/Containers`, holding a Docker disk image, **Total
size** can read close to a terabyte while **On disk** reads a few dozen
gigabytes. Both are true; the second is the one that tells you what you get
back by deleting it.

**On disk** is shown only where it can be measured: local drives on macOS and
Linux. It is left out for Windows paths, for SSH and S3 connections, and for
files inside an archive, none of which report the figure — rather than showing
a number that would be a guess.

Example:

```
┌─────────────── Details: filename.txt ───────────────┐
│ File: filename.txt                                   │
│ Path: /home/user/documents/filename.txt              │
│ Type: File                                           │
│ Size: 1.2 MB                                          │
│ Modified: 2024-03-15 14:30:22                        │
│ Accessed: 2024-03-15 16:45:10                        │
│ Permissions: -rw-r--r--                              │
│ Owner: user:staff                                    │
└──────────────────────────────────────────────────────┘
```

When multiple items are selected, each one's details are listed in turn,
separated by dividers.

## Notes

- **Permission and access errors** are handled gracefully: unreadable symlink
  targets show as `<unreadable>`, and inaccessible directories show
  `<permission denied>` rather than failing.
- On **Windows**, owner/group fall back to numeric UID/GID.
- Works the same in both panes, and can inspect the results of a search or a
  multi-file selection (select with **Space** or **A** first).
