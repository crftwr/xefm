# Archives

XeFM works with archive files as a first-class feature: you can **create**
archives from selected files, **extract** them, and **browse** their contents
in place — navigating into an archive as if it were a regular directory, without
unpacking it to disk first.

Supported formats: **ZIP** (`.zip`), **TAR** (`.tar`), and compressed TAR
(`.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`).

For the complete list of key bindings, see the
[XeFM User Guide](XEFM_USER_GUIDE.md) or press **?** in XeFM.

## Creating an archive

1. Select the file(s) and/or directories you want to archive
   (**Space** to toggle, **A** to select all files).
2. Press **P**.
3. Enter a name for the archive (the extension you use determines the format,
   e.g. `.zip` or `.tar.gz`) and confirm.

The archive is created in the other pane. Directories are added recursively.
XeFM confirms before creating by default:

```python
CONFIRM_ARCHIVE_CREATE = False   # default: True
```

## Extracting an archive

1. Put the cursor on an archive file.
2. Press **U**.
3. Confirm the destination.

The archive is extracted into a subdirectory (named after the archive) in the
other pane. If that directory already exists, XeFM asks whether to overwrite,
rename the extraction directory, or cancel. XeFM confirms before extracting by
default:

```python
CONFIRM_EXTRACT_ARCHIVE = False   # default: True
```

## Browsing an archive in place

Instead of extracting, you can open an archive and look inside it directly.

1. Position the cursor on the archive file.
2. Press **ENTER**.

The archive contents appear as a virtual directory — files and folders with
their names, sizes, and modification dates, just like a normal directory. The
path display shows an `archive://` URL with a `#` separating the archive path
from your location inside it, for example
`archive:///home/user/documents/backup.zip#projects/`.

### Navigating

| Key | Action |
|-----|--------|
| **↑ / ↓** | Move cursor |
| **Page Up / Down** | Scroll by page |
| **Home / End** | Jump to first / last entry |
| **ENTER** | Enter a directory within the archive |
| **Backspace** | Go to the parent directory (at the root, exit the archive) |

Example: from `/home/user/documents/`, press **ENTER** on `backup.zip` to view
`archive:///home/user/documents/backup.zip#`, **ENTER** on `projects/` to go
deeper, then **Backspace** twice to return to the filesystem.

### Viewing files inside an archive

Put the cursor on a file and press **V**. XeFM extracts it to a temporary
location, shows it in the built-in viewer (the title shows the full archive
path), and cleans up the temporary file automatically when you close the viewer.

### Copying files out of an archive

Copying is how you extract individual files or folders from a browsed archive.

1. Select the file(s) or directory you want (**Space** to select, or just place
   the cursor on one item).
2. Press **C**.
3. Choose the destination directory.

Selected files are extracted to the destination; a selected directory is
extracted recursively with its full structure. The destination can be a local
directory or S3 — XeFM extracts and uploads directly. (Archive → archive is not
supported, since archives are read-only.)

### File details

Press **I** on an entry to see its details: name, uncompressed and compressed
size, compression ratio, modification time, permissions, archive type, and the
internal path within the archive.

### Sorting

Sort the archive listing with the same quick-sort keys used everywhere in XeFM:

| Key | Sort by |
|-----|---------|
| **1** | Name |
| **2** | Extension |
| **3** | Size |
| **4** | Modification date |

Directories are always listed first, regardless of sort mode.

### Searching inside an archive

While browsing an archive, press **Shift-F** to open the filename search dialog.
Enter a pattern (wildcards like `*.txt` work) and XeFM lists matching files with
their full paths inside the archive. Press **ENTER** on a result to jump to it.
The search covers the current archive only, starting from your current location
and descending recursively. Large archives show a progress indicator while the
search runs.

### Dual-pane and archives

Archive browsing works with XeFM's two panes: browse an archive in one pane while
a regular directory (or a different archive) is shown in the other, and copy
files between them. **O** / **Shift-O** sync directories between panes and work
with archives too.

## Password-protected archives

XeFM can extract and browse **password-protected ZIP** archives. When a password
is needed, XeFM prompts for it in a masked field — typed characters show as `•`,
and the value can't be copied or cut from the field.

### Extracting a password-protected ZIP

1. Put the cursor on the encrypted `.zip` file and press **U** (Extract Archive).
2. Confirm the destination as usual.
3. XeFM detects that the archive is encrypted and asks for its password.
4. Enter the password and press **Enter**. The archive extracts into a
   subdirectory in the other pane.

If the password is wrong, XeFM says so and asks again — nothing is written to
disk until the password is confirmed correct, so a wrong password never leaves a
half-extracted folder behind. Press **Esc** to cancel.

### Viewing a file inside a password-protected ZIP

1. Press **ENTER** on the `.zip` file to browse it. The file list is readable
   without a password.
2. Open a file inside it (**ENTER**, or **V** to view).
3. XeFM asks for the archive's password the first time you open a file from it.
4. Enter the password. The file opens in the built-in viewer.

The password is remembered for the rest of the session, so you're only asked
once per archive. Extracting an archive and later browsing the *same* archive
share the remembered password.

### Supported encryption

- **Legacy ZipCrypto** (the "traditional PKWARE" encryption produced by
  `zip -e`, most OS "compress with password" tools, and many archivers) is fully
  supported.
- **AES encryption** (WinZip AES / `7z -mem=AES256`) is **not** supported — the
  Python runtime XeFM builds on can't decrypt it. XeFM detects this and shows a
  clear "AES-encrypted zips are not supported" message instead of a cryptic
  error.

Only the ZIP format supports passwords; TAR archives (`.tar`, `.tar.gz`,
`.tar.bz2`, `.tar.xz`) are not encrypted. Passwords are held only in memory for
the running session — never written to disk or logged — and are sent to the
archive as UTF-8 bytes (plain ASCII passwords always work).

## Read-only browsing

When you browse an archive in place, its contents are **read-only**. You can
copy files out, view them, browse, and search — but you cannot delete, move, or
copy files *into* a browsed archive; XeFM shows an explanatory message if you
try. To change an archive's contents, extract it (**U**), edit the files, and
create a new archive (**P**).

Other notes:

- **Nested archives** are shown as plain files; extract the inner archive first,
  then browse it.
- **Symbolic links** inside archives are shown but may not extract correctly on
  all platforms, and file permissions may not be fully preserved.

## Tips

- Use **Shift-F** to find files quickly in large archives instead of browsing by
  hand.
- Select several files before pressing **C** to extract them all at once.
- Check sizes with **I** before extracting large entries.
- Keep the destination visible in one pane while browsing the archive in the
  other.

## See Also

- [File Operations](FILE_OPERATIONS_FEATURE.md) — copy, move, and progress display
- [XeFM User Guide](XEFM_USER_GUIDE.md) — complete documentation
