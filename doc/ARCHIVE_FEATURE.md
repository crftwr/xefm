# Archives

XeFM works with archive files as a first-class feature: you can **create**
archives from selected files, **extract** them, and **browse** their contents
in place — navigating into an archive as if it were a regular directory, without
unpacking it to disk first.

**Browse and extract:**

| | Formats |
| --- | --- |
| Always | **ZIP** (`.zip`), **TAR** (`.tar`), compressed TAR (`.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`) |
| Python 3.14+ | **Zstandard TAR** (`.tar.zst`, `.tzst`) |
| With libarchive | **7-Zip** (`.7z`), **RAR** (`.rar`), **ISO 9660** disc images (`.iso`), **Cabinet** (`.cab`), **cpio** (`.cpio`), **RPM packages** (`.rpm`) |

**Create:** everything above except `.rar`, `.cab` and `.rpm`, which XeFM can
read but not write — nothing writes RAR but WinRAR, and libarchive has no writer
for the other two. Typing one of those names at the create prompt says so rather
than quietly making a `.tar.gz`. A `.7z` created by XeFM uses LZMA2, the same
compression 7-Zip itself writes by default; no format can be given a password
(see [Supported encryption](#supported-encryption)).

The bottom row needs a system library (see
[If those formats do not appear](#if-those-formats-do-not-appear) below). The
rest need nothing at all — Zstandard included, which comes from Python itself
rather than from libarchive.

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

Copying to a **local** destination shows a byte-level progress bar for each file
and can be interrupted with **Esc** part way through a large one; the partly
written file is removed. Copying straight to S3 does not yet report progress
within a file — extract to a local directory first if you want to be able to
stop it.

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

XeFM can extract and browse password-protected archives — ZIP always, and 7z
where the system library supports it (see
[Supported encryption](#supported-encryption)). When a password is needed, XeFM
prompts for it in a masked field — typed characters show as `•`,
and the value can't be copied or cut from the field.

### Extracting a password-protected archive

1. Put the cursor on the encrypted archive and press **U** (Extract Archive).
2. Confirm the destination as usual.
3. XeFM detects that the archive is encrypted and asks for its password.
4. Enter the password and press **Enter**. The archive extracts into a
   subdirectory in the other pane.

If the password is wrong, XeFM says so and asks again — nothing is written to
disk until the password is confirmed correct, so a wrong password never leaves a
half-extracted folder behind. Press **Esc** to cancel.

### Viewing a file inside a password-protected archive

1. Press **ENTER** on the archive to browse it. The file list is readable
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
- **AES-encrypted ZIP** (WinZip AES) is **not** supported — the Python runtime
  XeFM builds on can't decrypt it.
- **Encrypted 7z** cannot be read on any platform. libarchive decrypts ZIP and
  nothing else, so an encrypted `.7z` lists its filenames and then refuses its
  contents. XeFM detects this and says so, rather than asking for a password no
  answer would satisfy.
- **Creating an encrypted archive is not supported in any format.** XeFM reads
  password-protected archives; it does not make them.

Where XeFM cannot decrypt an archive it says "its encryption is not supported"
and does not prompt, rather than rejecting every password you type. TAR archives
(`.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`) are never encrypted.

Passwords are held only in memory for the running session — never written to disk
or logged — and are sent to the archive as UTF-8 bytes (plain ASCII passwords
always work).

## Read-only browsing

When you browse an archive in place, its contents are **read-only**. You can
copy files out, view them, browse, and search — but you cannot delete, move, or
copy files *into* a browsed archive; XeFM shows an explanatory message if you
try. To change an archive's contents, extract it (**U**), edit the files, and
create a new archive (**P**).

Other notes:

- **Nested archives** are shown as plain files; extract the inner archive first,
  then browse it.
- **7z and RAR entries are read one at a time.** Those archives are usually one
  compressed block, so opening a file near the end means decompressing what comes
  before it. Browsing and viewing single files is fine; extracting the whole
  archive with **U** is the efficient way to get everything out.
- **Symbolic links** inside archives are shown but may not extract correctly on
  all platforms, and file permissions may not be fully preserved.

## If those formats do not appear

7z, RAR, ISO, CAB, cpio and RPM are not something Python can handle on its own:
XeFM uses **libarchive**, a system library. If pressing Enter on one of those
files opens it in the viewer instead of browsing into it — or if typing a `.7z`
name at the create prompt produces a `.tar.gz` — XeFM did not find a usable one.
(ZIP, TAR and `.tar.zst` are unaffected; they never go near it.)

**Press ? and scroll to "Archive Formats".** That table is built when XeFM
starts, so it lists exactly what this copy can open and create, and the line
under it names the libarchive in use:

```
Using libarchive 3.7.4 zlib/1.2.12 liblzma/5.4.3 bz2lib/1.0.8 — /usr/lib/libarchive.dylib
```

A format missing from the table is one the library was built without the pieces
for; XeFM leaves it out rather than offering it and failing later. If no library
was found the line says so instead, with the reason, and the log pane (**L**)
carries the same message. What to do about it:

- **macOS** — nothing to install. The built-in `/usr/lib/libarchive.dylib` is
  new enough, and the desktop app uses that same system copy.
- **Linux** — install your distribution's libarchive package (`libarchive13`,
  `libarchive`, …) if it is not already present.
- **Windows** — Windows has no system libarchive. The desktop app ships one and
  needs no setup. For the terminal version, download `archive.dll` from
  [xefm-bin-deps](https://github.com/crftwr/xefm-bin-deps/releases) — the build
  XeFM's own desktop app uses — and point XeFM at it:

  ```powershell
  setx LIBARCHIVE "C:\path\to\libarchive-3.8.9-windows-x64\bin\archive.dll"
  ```

  The variable is read when XeFM starts, so open a new terminal afterwards.

To use a specific library rather than the system one, set `LIBARCHIVE` to its
full path before starting XeFM:

```bash
export LIBARCHIVE=/opt/libarchive/lib/libarchive.so
```

Nothing else changes when libarchive is missing — ZIP and TAR keep working
exactly as before, and those files simply behave like ordinary files. You can
still hand them to an external unpacker with a `FILE_ASSOCIATIONS` entry (see
[File Associations](FILE_ASSOCIATIONS_FEATURE.md)) if you would rather not
install anything.

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
