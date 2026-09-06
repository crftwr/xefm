# Archive System

Canonical developer reference for XeFM's archive support. Two independent paths:

- **Read / browse** — treat an archive as a virtual directory you can navigate,
  view, and copy out of, without extracting. Implemented in `xefm/archive.py`
  (`ArchivePathImpl` + handlers + cache), plugged into the `Path` abstraction.
- **Create / extract** — build a new archive from a selection, or unpack one to a
  directory. Implemented in `xefm/app.py` (the `XeFMApp` create/extract methods), using
  the stdlib `zipfile` / `tarfile` modules directly, and falling back to the
  registered handler for anything they cannot read (§1.1).

**Which formats are readable is decided at import, not written down.** Reading
goes through a registry (§1.1) whose libarchive-backed entries depend on what the
library that actually loaded can do, so anything enumerating formats — the user
guide, a dialog, a message — has to be generated from
`archive_readable_suffixes()` rather than kept as a list somewhere.

Source of truth is the code; this document summarizes structure and intent, not
every line.

---

## 1. Read / browse path (virtual directory)

Browsing an archive works because `xefm/archive.py` implements the `PathImpl`
interface, so archive contents flow through the same `Path` machinery as local
and S3 paths.

### Archive URI format

```
archive://<absolute_path_to_archive>#<internal_path>

archive:///home/user/data.zip#                  (archive root)
archive:///home/user/data.zip#folder/           (a directory inside)
archive:///home/user/data.zip#folder/file.txt   (a file inside)
```

The `#` separates the archive file path from the internal path. `Path()` detects
the `archive://` scheme and constructs an `ArchivePathImpl` (`xefm/path.py`).

### ArchiveEntry

A `@dataclass` giving a uniform view of an entry across formats: `name`,
`internal_path`, `is_dir`, `size`, `compressed_size`, `mtime`, `mode`,
`archive_type`. Helpers:

- `to_stat_result()` — an `os.stat_result` so archive entries interoperate with
  filesystem-shaped code.
- `from_zip_info(zip_info, archive_type='zip')` / `from_tar_info(tar_info,
  archive_type='tar')` — classmethod factories from `zipfile.ZipInfo` /
  `tarfile.TarInfo`.

### ArchiveHandler and subclasses

`ArchiveHandler` is the base interface for reading an archive: `open()`,
`close()`, `list_entries(internal_path="")`, `get_entry_info(internal_path)`,
`extract_to_bytes(internal_path)`, `extract_to_file(internal_path, target_path)`,
`iter_member_bytes(internal_path, chunk_size)`, `entry_count()`,
`iter_extract(dest_dir, password=None)`, `encryption_status()`,
`verify_password(pwd)`, plus context-manager support. The last five are what a
third format needed and the first two did not have: extraction and encryption
used to be answered by asking whether the handler *was a* `ZipHandler`, and
reading one member was a single opaque call (§1.3).

`_build_index(entries, archive_type)` on the base class fills `_entry_cache` and
`_directory_cache` and synthesizes a virtual directory entry for every parent an
archive names only implicitly. `iter_extract` has a generic implementation there
too, walking that index one entry at a time and refusing members whose path
escapes the destination (`is_safe_member_path`).

Three concrete handlers exist:

- **`ZipHandler`** — ZIP via `zipfile`. Caches entries on open, with lazy loading
  for large archives (>1000 entries: only shallow structure is cached up front,
  deeper entries load on demand via `getinfo`). Keeps its own copy of the
  indexing loop rather than calling `_build_index`, because that lazy policy is
  zip-only. Also carries the encryption read path (see §3).
- **`TarHandler(archive_path, compression=None)`** — tar and compressed variants
  (`gz`, `bz2`, `xz`) via `tarfile`, indexed through `_build_index`.
- **`LibarchiveHandler(archive_path, label)`** — everything libarchive
  contributes: `.7z`, `.rar`, `.iso`, `.cab`, `.cpio`, `.rpm` (§1.2).

All three download a remote archive (`is_remote()`) to a temp file on `open()`
and delete it on `close()`.

### 1.1 The readable-format registry

`ARCHIVE_HANDLERS` is a list of `ArchiveFormat(label, suffixes, factory,
description)`, and it is the single answer to "can XeFM read this file". It
replaced an if/elif chain in `ArchiveCache._create_handler` plus two
`isinstance(handler, ZipHandler)` tests in the password gate.

| Function | Answers |
| --- | --- |
| `register_archive_format(fmt)` | add, replacing any entry with the same label |
| `archive_format_for_name(name)` | the matching `ArchiveFormat`, or `None` |
| `archive_format_label(name)` | its label — `'zip'`, `'tar.gz'`, `'7z'` |
| `archive_strip_suffix(name)` | the name with its archive suffix removed |
| `archive_readable_suffixes()` | every readable suffix, longest first |
| `archive_writable_formats()` | the formats that brought a writer with them |

Three rules hold for anything registered:

- **Longest suffix wins**, independent of registration order. The old chain got
  `.tar.gz` before `.tar` right only because of where the branches sat in the
  source; matching now sorts by suffix length, and a test pins it both ways round.
- **Reading is the question it answers.** Whether a format can also be
  *created* is a second, weaker property: `ArchiveFormat.writer`, set only where
  the writer arrives with the engine that reads it. zip and tar leave it `None`
  and are created by `XeFMApp` through zipfile / tarfile, so "what can P create"
  is the union of two sources (§2) — libarchive reads strictly more formats than
  it writes (rar, lha and cab are read-only), so the two lists cannot be one.
- **Worker-thread safe.** Handlers are built and driven from the listing worker,
  so nothing reached through the registry may touch the UI, and handlers for
  different archives run on different threads at once.

Registration happens at import: `_register_builtin_formats()` at the bottom of
`xefm/archive.py` for zip and tar, then `register_libarchive_formats()` for
whatever the loaded library justifies. `xefm/archive_libarchive.py` imports
`xefm/archive.py` in turn; the cycle resolves because the registration call sits
below every name it needs.

### 1.2 The libarchive engine (`xefm/archive_libarchive.py`)

`libarchive-c` is a pure-ctypes binding that carries no binary, so the shared
library comes from one of three places, in this order: the **`LIBARCHIVE`
environment variable**, a **bundled copy**, or **`find_library("archive")`** —
the system copy. Nothing is required: with no usable library the registry simply
has fewer entries and zip and tar are unaffected.

The bundled copy is found by `bundled_library_path()`, which looks in
`xefm/_bin/` — inside XeFM's own package, which is the one directory this module
can locate from `__file__` without knowing anything about the bundle around it.
A source checkout leaves it empty; `windows_app/build.ps1` fills it in the
*copied* package (§ "Step 4b" of
[WINDOWS_APP_BUILD_SYSTEM.md](WINDOWS_APP_BUILD_SYSTEM.md)) with a DLL downloaded
from [crftwr/xefm-bin-deps](https://github.com/crftwr/xefm-bin-deps), pinned by
release tag and SHA-256.

Finding one is how `LIBARCHIVE` comes to be *set* when the user did not set it:
`libarchive-c` reads that variable once, at import, and offers no other way to
choose a library, so `_use_bundled_library()` puts the path there before
`_probe()` imports the binding. That is also why this lives in the module that
does the import rather than in XeFM's startup, where it would be one
import-order mistake away from having no effect. A `LIBARCHIVE` the user set
themselves is left alone — naming a library is answering exactly this question.

Because two of those three paths are built by someone else, **capability is
probed, never inferred from a version.** `archive_version_details()` names the
codecs actually compiled in; `_CANDIDATES` says what each format needs, and a
format registers only when the library exports every reader symbol it lists,
every filter symbol, *and* reports every codec.

| Label | Suffixes | Needs | Writer |
| --- | --- | --- | --- |
| `7z` | `.7z` | 7zip reader, liblzma | `7zip`, `compression=lzma2` |
| `rar` | `.rar` | rar **and** rar5 readers | — |
| `iso` | `.iso` | iso9660 reader | `iso9660` |
| `cab` | `.cab` | cab reader, zlib (MSZIP is deflate) | — |
| `cpio` | `.cpio` | cpio reader | `cpio_newc`, `hdrcharset=UTF-8` |
| `rpm` | `.rpm` | cpio reader, **rpm filter**, zlib + liblzma | — |

RAR requires both generations because a `.rar` is RAR4 or RAR5 and offering the
suffix on one reader would be a lie for half of them; the win over `rarfile` is
that libarchive implements them itself, with none of the non-free `unrar` binary.
`cpio_newc` rather than the plain `cpio` writer: the historic odc format stores
sizes in eight octal digits and so cannot hold a member over 8 GB.

Probing is also what keeps the silent external-program fallback out of reach:
libarchive answers a missing stream codec by spawning `gzip -d` or `zstd -d`, one
process per archive, and on Windows those binaries do not exist. **This is not
hypothetical.** macOS's system libarchive reports no libzstd and still reads a
`.tar.zst` — with `PATH` emptied it admits why:

```
ArchiveError Can't initialize filter; unable to run program "zstd -d -qq"
```

It had been shelling out to Homebrew's `zstd`. A format whose codec is missing
must never be offered, which is why `.tar.zst` goes through the standard library
instead (§2) and not through here. The one case the probe cannot cover is a codec
*inside* a container: an RPM with a zstd payload can still reach for the external
program, because nothing outside the file says what its payload uses.

`register_libarchive_formats()` logs one line at import naming the library, its
version, its codecs and the suffixes it contributed. With three supply paths, a
bug report has to carry that automatically.

**No random access.** libarchive is a forward stream of headers: `open()` makes
one pass to build the index, and every later read re-opens the file and scans to
its entry. Browsing suits that (the structure is cached once), but extracting *n*
entries one at a time is O(n²) on a solid archive — which is why
`LibarchiveHandler` overrides `iter_extract` with a single pass, and why
`entry_count()` is overridden too: that pass yields the archive's *stored*
members, not the directories the index invented for them.

**Writing** is `write_archive(archive_path, sources, format_name=…, options=…,
on_entry=…, on_bytes=…)`, registered as the 7z format's `writer` when the library
exports `archive_write_set_format_7zip`. `member_walk()` produces members
depth-first, a directory before its children, deliberately matching
`_count_archive_entries(include_dirs=True)` member for member — including
counting an unlistable directory as itself and not descending — because that
pass's total is the one the write has to reach. Directories are stored rather
than implied, so an empty one survives. `options='compression=lzma2'` is
explicit: libarchive's 7z writer defaults to LZMA1, while 7-Zip itself has
written LZMA2 for years. libarchive's 7z writer has no encryption, so XeFM
cannot create a password-protected 7z.

**Progress, both directions.** Neither path uses libarchive's own
`archive_read_extract_set_progress_callback`: XeFM does not use
`archive_read_extract` at all, writing the blocks itself, which is what makes
block-level granularity available for free. On extraction `iter_extract` yields
each entry *before* writing its payload and calls `on_bytes(n)` per block; on
creation `write_archive` calls `on_entry(arcname, size)` before each member and
`on_bytes(n)` as the source is read. Both feed the same
:class:`~xefm.archive_progress.ByteProgress` the stdlib paths use — see the note
at the end of §2.

**Encryption is two questions, not one.** Which entries are encrypted comes from
`archive_entry_is_encrypted` on the headers read at `open()`. Whether they can be
decrypted at all is `can_decrypt_7z()`, which decrypts a 183-byte AES-256 7z
embedded in the module. libarchive compiles its AES support in behind
`HAVE_LIBCRYPTO` / CNG / CommonCrypto, none of which `archive_version_details()`
mentions, so there is no other way to ask — and macOS's system build (3.7.4,
zlib + liblzma + bz2lib) has none of them. Without the probe an encrypted 7z
would reject every password the user typed with no way to say why.

### ArchiveCache

`ArchiveCache(max_open=5, ttl=300)` keeps recently used handlers open so
repeated navigation doesn't re-open the archive each time:

- **LRU eviction** once `max_open` handlers are live.
- **TTL expiration** — a handler untouched for `ttl` seconds is closed on next
  access.
- **Thread-safe** via a single `threading.RLock`.
- **Metrics** via `get_stats()` (`open_archives`, `cache_hits`, `cache_misses`,
  `hit_rate`, `evictions`, `avg_open_time`, …).

`_create_handler` is a lookup in the registry (§1.1) — `archive_format_for_name`
then `fmt.factory(archive_path)` — raising `ArchiveFormatError` when nothing
registered reads the name. A process-wide instance is returned
by `get_archive_cache()`, which reads `ARCHIVE_CACHE_MAX_OPEN` /
`ARCHIVE_CACHE_TTL` from config (falling back to 5 / 300).

### ArchivePathImpl

`ArchivePathImpl(archive_uri, metadata=None)` implements `PathImpl` for archive
members: URI parsing, path properties (`name`, `stem`, `suffix`, `parent`,
`parts`, …), path manipulation (`joinpath`, `with_name`, `relative_to`, …),
queries (`exists`, `is_dir`, `is_file`, `stat`), directory traversal (`iterdir`,
`glob`, `rglob`), and read-only I/O (`open`, `read_text`, `read_bytes`). All
write/mutate operations (`write_*`, `mkdir`, `unlink`, `rename`, `chmod`, …)
raise `OSError("Archive files are read-only")`.

`extract_to_stream(stream, progress_callback)` is the copy-out path (§1.3).

It also answers storage-strategy queries the app uses elsewhere:
`get_scheme() == 'archive'`, `requires_extraction_for_reading() == True`,
`supports_streaming_read() == False`, `get_search_strategy() == 'extracted'`, and
`get_extended_metadata()` for the info dialog. A per-instance `_property_cache`
memoizes `name` / `parts`; a `_metadata['entry']` slot caches the resolved
`ArchiveEntry`.

#### Filenames on Windows

libarchive keeps an entry's pathname in both a wide and a narrow form, and
converts between them using a code page it gets by calling
`setlocale(LC_CTYPE, NULL)` in its own C runtime — `get_current_codepage()` in
`archive_string.c`. On macOS and Linux that resolves to UTF-8 and none of this is
visible. On Windows it is the ANSI code page, 1252 on a US install, and any name
1252 cannot spell makes `archive_entry_pathname()` return NULL. What that does
depends on who asked:

- the **iso9660 writer** reads the NULL as its virtual root and drops the file
  with no error at all — an ISO that silently lacks the file you put in it;
- the **cpio writer** reports `Pathname required` and fails the whole archive;
- **7z, RAR and ISO's Joliet** never notice, because they ask for the wide form.

Two things answer this, and they are separate because they fix different halves.

`_use_utf8_ctype()` puts the process's C locale on UTF-8 (Windows only, before
the binding is imported). Python's own encodings are untouched — it derives those
from `GetACP()`, not from the C locale — so the only code this reaches is
libarchive's conversions. This is also why `crftwr/xefm-bin-deps` links the
**shared** MSVC runtime: a statically linked one is private to `archive.dll` and
cannot be reached from here at all.

That fixes ISO but not cpio, whose default is the **OEM** code page (437), which
libarchive derives from a table of locale *names* and which the `.UTF8` suffix
therefore does not move. So cpio is told its charset outright, on both sides —
`write_options='hdrcharset=UTF-8'` and the matching `_CHARSET_BY_LABEL` entry
that `_open_reader()` reads.

`_open_reader()` exists only for that: `hdrcharset` has to be set between
`archive_read_new` and `archive_read_open`, and `libarchive-c`'s `file_reader`
does both in one call. It rebuilds the reader from the same pieces, and falls
back to plain `file_reader` if that package is ever rearranged.

**`_CHARSET_BY_LABEL` deliberately holds only cpio and rpm.** Forcing UTF-8 on a
CAB whose names are CP932 does not garble them — it makes every entry's pathname
NULL, so the archive opens and looks *empty*. Mojibake is a bad listing; nothing
at all is a broken one, and libarchive's own default is the better answer for
every format that stores a legacy code page.

### 1.3 Copying a member out

`Path.copy_to` has a branch for `archive` → `file` that streams the member into
the destination through `ArchivePathImpl.extract_to_stream`, which walks
`iter_member_bytes()` and calls the progress callback per block. Without it the
copy fell into `copy_to`'s generic arm — `read_bytes()` then `write_bytes()` —
and that one opaque call cost three things at once: the whole member in memory,
no byte bar, and **no cancellation**, because for a cross-storage copy
`FileOperationService._remote_progress` puts `task.checkpoint()` *inside* the
progress callback and nothing ever called it. A large file inside a 7z is where
that is unmissable, but zip and tar behaved identically.

`LibarchiveHandler.iter_member_bytes` coalesces libarchive's own ~16 KiB blocks
up to `chunk_size` (1 MiB, matching `file_operations._CHUNK`): the consumer takes
a lock on the UI's progress state per block, and a gigabyte at 16 KiB would do
that sixty thousand times.

A cancel raised inside the callback propagates unchanged — `copy_to` guards the
callback so it comes back as the caller's own exception rather than an `OSError`
about a failed copy — and the branch removes the truncated destination on the way
out.

> **Still generic: `archive` → `s3` / `ssh`.** Those combinations have no branch
> and fall through to `read_bytes()` / `write_bytes()`, so copying a member
> straight from a browsed archive to remote storage still buffers it and still
> cannot be cancelled. The fix is the same shape as the local one, needing a
> file-like adapter over `iter_member_bytes()` for `upload_from_stream`.

### Navigation integration

`xefm/app.py` handles entering an archive: when the cursor is on a recognized archive
file and Enter is pressed, it remembers the cursor and sets the pane path to
`Path(f"archive://{entry.absolute()}#")`. Because `ArchivePathImpl.parent` of the
archive root is the archive file's containing directory, "up" exits the archive
naturally. Nested archives (an archive inside a browsed archive) are not
supported.

### Error handling

A small exception hierarchy under `ArchiveError` (each carries a technical
`message` and a user-facing `user_message`): `ArchiveFormatError`,
`ArchiveCorruptedError`, `ArchiveExtractionError`, `ArchiveNavigationError`,
`ArchivePermissionError`, `ArchiveDiskSpaceError`, plus the encryption pair
`ArchivePasswordRequired` and `ArchiveEncryptionUnsupported` (§3).

### Thread safety

`ArchiveCache` is lock-guarded; handlers are read-only and independent. Multiple
threads may read the same or different archives concurrently through the cache.
Archives are never modified while open.

---

## 2. Create / extract path

Creation and extraction are **not** in `xefm/archive.py` — they live on `XeFMApp`
in `xefm/app.py` and operate on local filesystem paths using the stdlib directly.
There is no separate `ArchiveOperations`/`ArchiveUI` class.

### Format detection

Creation has two implementations, so "what can P create" has two sources. The
stdlib half is class data on `XeFMApp`:

- `_ARCHIVE_EXTS` — the extensions zipfile / tarfile can create → format label.
- `_TAR_MODES` — format label → `tarfile` write mode (`w`, `w:gz`, `w:bz2`,
  `w:xz`, `w:zst`); ZIP is handled separately.

Both grow a Zstandard row when `xefm.archive.tar_zstd_supported()` is true —
`'zst' in TarFile.OPEN_METH`, which is Python 3.14 and up. The readable registry
applies the same condition, so `.tar.zst` is creatable exactly when it is
openable. Zstandard deliberately does **not** come from libarchive: see the
external-program evidence in §1.2.

The other half is the registry's writers (§1.1). `_writable_formats()` is their
union, sorted longest-suffix-first — sorted rather than concatenated for the
same reason the read registry sorts, so `.tar.gz` beats `.tar` whichever list
each came from. On top of it:

- `_archive_format(name)` → the label P can *create*, or `None`.
- `_readable_archive_format(name)` → the label Enter browses and U extracts.
- `_archive_basename(name)` → `archive_strip_suffix(name)`, the default
  extraction subdirectory.

A name the registry reads but brought no writer for is refused by P with a
message saying so, rather than silently gaining a `.tar.gz` suffix.

### Creation

- `_add_to_zip(zf, path, arcname, task=None, prog=None, bytes_=None)` — adds a
  path to an open `ZipFile`, recursing into directories (zipfile, unlike tarfile,
  does not recurse on its own).
- `_write_archive(sources, archive_path, fmt, task=None, prog=None)` — writes
  `sources` into a new archive. ZIP uses `ProgressZipFile(..., "w", ZIP_DEFLATED)`;
  tar formats use `ProgressTarFile.open(..., _TAR_MODES[fmt])` (tarfile recurses
  into directories, and its `add(filter=…)` hook is where per-member progress and
  cancellation are taken). Both subclasses are stdlib passthroughs that count
  bytes — see *The byte bar* below. Returns the number of files added.
- `_entry_size(path)` — a source file's size for the byte bar, 0 when unreadable
  (the writer is what reports a genuinely broken file).
- `_count_archive_entries(sources, include_dirs)` — the counting pass that makes
  the progress bar determinate: leaf files only for ZIP, files *and* directories
  for tar, matching what each writer actually adds. An unreadable directory counts
  as itself and is not descended.
- `create_archive()` (the **P** key) — the UI flow: takes the active pane's
  selection (or the focused entry), prompts for a filename, and writes the
  archive into the **other** pane's directory. An unrecognized extension defaults
  to `.tar.gz`. A single selected item prefills `"<basename>."`. Overwrite is
  confirmed via a message box. Guards refuse to archive entries that live inside a
  read-only archive or to write into one.

### Extraction

- `_extract_archive(archive_path, dest_dir, fmt, pwd=None, task=None, prog=None)`
  — extracts into `dest_dir` (created if absent) and returns the entry count. Tar
  extraction uses the `filter="data"` argument where available (Python 3.12+) to
  reject unsafe member paths, falling back when the argument is unsupported. `pwd`
  is the password for an encrypted ZIP, verified up front (see §3) so a wrong
  password fails before any file is written.
- `_reporting_members(members, describe, task, prog, bytes_=None)` — the generator
  handed to `extractall(members=…)`; `describe(member)` yields its `(name, size)`.
  Progress and cancellation are taken *per member yielded* rather than by
  hand-rolling the loop, so `extractall`'s deferred directory-permission fix-up (a
  read-only directory would otherwise block writing into it) and zipfile's member
  path sanitization both still run.
- `extract_archive()` (the **U** key) — the UI flow: extracts the focused archive
  into a subdirectory named after the archive (`_archive_basename`) in the other
  pane's directory. Confirms when `CONFIRM_EXTRACT_ARCHIVE` is set or the
  destination already exists. Refuses non-archives, nested archives, and
  extracting into a read-only archive.

### Running as a task

Both flows hand the work to `xefm.task` rather than doing it in the dialog
callback that started it (issue #280) — compressing a large tree, or building a
compressed tar's member list, would otherwise block the event loop for its whole
duration: no repaint, no keys, no way out.

`_submit_archive_task(task, run, on_done, dest_dir)` is the shared submit. Each
flow builds a `Task` (`kind="archive_create"` / `"archive_extract"`, progress
started as `OperationType.ARCHIVE_CREATE` / `ARCHIVE_EXTRACT`) whose `run` body
counts, then writes or extracts, and returns its outcome as a dict —
`{"added": n}` / `{"count": n}`, `{"cancelled": True}`, or `{"error": exc}` —
which `on_done` reports on the main thread. The submit also brackets `dest_dir`'s
filesystem watcher for the run, the same suppression copy/move/delete use so an
operation's own writes don't re-list the watching pane throughout (issue #243).

This buys the standard `ProgressDialog`: a determinate items bar, the current
entry's name, and **Esc to cancel**. Cancellation unwinds from the per-entry
checkpoint; a cancelled *create* deletes the half-written archive (it either did
not exist before, or an overwrite truncated it the moment the file opened), while
a cancelled *extract* leaves what landed — the destination may be a directory the
user already had files in, so removing it wholesale could take those with it.

Extraction's failure dispatch is ordered most-specific-first, because
`NotImplementedError` **is a** `RuntimeError`: AES is reported as unsupported, and
only a plain `RuntimeError` re-opens the password prompt.

### The byte bar (`xefm/archive_progress.py`)

The dialog's secondary bar shows the *current member's* bytes, the same meaning
it has for a copy — without it a single large member (a VM image, a video) leaves
the item bar still for minutes.

The payload copy is buried inside `zipfile` / `tarfile`, and rewriting those loops
to count bytes would mean re-deriving each member's metadata and, on the extract
side, their safety checks: zipfile's path sanitization and tarfile's sparse-file
and deferred directory-permission handling. So `ProgressZipFile` /
`ProgressTarFile` instead override the one method the payload actually flows
through and wrap the file object passing by. The stdlib loop runs untouched:

| Operation | Seam | Counts |
|---|---|---|
| zip create | `ZipFile.open(zinfo, 'w')` — `write()` copies into it | writes |
| zip extract | `ZipFile.open(member)` — `_extract_member` copies out of it | reads |
| tar create | `TarFile.addfile(tarinfo, fileobj)` — `add()` hands it the source | reads |
| tar extract | `TarFile.makefile` — proxy swapped over `self.fileobj` for the call | reads |

`ByteProgress` holds the current member's total (from `stat()`, `ZipInfo.file_size`
or `TarInfo.size`) and rate-limits reports by *volume* — at most ~200 per member,
never oftener than every 64 KiB — so an 8 KiB-chunked gigabyte does not cost a
hundred thousand lock acquisitions. `start()` must be called *after*
`update_progress`, which clears the byte fields for the incoming item. With no
`ByteProgress` attached both classes are pure passthroughs.

Measured overhead of the whole task path, 1500 files: ~1.06x for zip, within noise
for `.tar.xz` (the counting pass is 11 ms of it).

### Supported formats

Create: ZIP, TAR, TAR.GZ (`.tgz`), TAR.BZ2 (`.tbz2`), TAR.XZ (`.txz`) and — on
3.14+ — TAR.ZST (`.tzst`) from the `_ARCHIVE_EXTS` table, all of it stdlib, plus
`.7z`, `.iso` and `.cpio` from the registry's writers. `.rar`, `.cab` and `.rpm`
are readable and not creatable. Ask `_writable_formats()`.

Extract and browse: those, plus whatever libarchive contributed (§1.2) — `.7z`
where a usable library loaded. Ask `archive_readable_suffixes()`; do not restate
the list.

Both `_extract_archive` and `_write_archive` route a format that is neither
`"zip"` nor in `_TAR_MODES` away from the stdlib: to `_extract_via_handler`,
which drives the handler's `iter_extract`, and to `_write_via_handler`, which
calls the registry entry's `writer`. Both supply the per-entry bookkeeping the
stdlib paths get from `_reporting_members` / the tar `filter=report` hook —
`task.checkpoint()`, `prog.update_progress(name)`, `bytes_.start(size)` — and
hand `bytes_.advance` down as the block callback.

Single-file gzip/bzip2/xz streams are readable as members but are not first-class
create targets in the flow above.

> The create/extract flow works on local filesystem paths and does not perform
> cross-storage staging. (Remote-archive support exists only on the read/browse
> side, where a handler downloads the archive to a temp file.)

---

## 3. Encryption

Password-protected ZIP support (extract and browse). Python's `zipfile` decrypts
only legacy **ZipCrypto**; **WinZip AES** (compression method 99) cannot be
decrypted and is detected and refused with a clear message. No third-party
dependency (`pyzipper` etc.) is used.

### Password registry (`xefm/archive.py`)

A module-level dict keyed by the archive file's absolute path, guarded by a lock,
holding passwords for the session (in-memory only, nothing persisted):
`set_archive_password`, `get_archive_password`, `clear_archive_password`.

### Classification / verification helpers

The handler contract speaks a **format-neutral** vocabulary —
`encryption_status()` → `'none' | 'password' | 'unsupported'` — because 7z is
routinely encrypted and the gate could not go on naming zip's schemes. The
zip-level names survive one level down, inside `ZipHandler`:

- `zip_encryption_status(zf)` → `'none' | 'zipcrypto' | 'aes'` (AES wins if any
  entry uses it). `ZipHandler.encryption_status()` maps `zipcrypto` → `'password'`
  and `aes` → `'unsupported'`.
- `archive_encryption_status_path(path)` — the same classification from a file
  path, for the extract flow, which works on a raw file rather than a browsed
  handler. It goes through the registry (so any format can answer) but not
  through `ArchiveCache` (extraction is not browsing).
- `verify_zip_password(zf, pwd)` — opens the smallest encrypted entry to validate
  the ZipCrypto header cheaply. No-op when nothing is encrypted; raises
  `RuntimeError` (missing/wrong password) or `NotImplementedError` (AES).

### ZipHandler read path

`extract_to_bytes` / `extract_to_file` pass `pwd=get_archive_password(...)` to
`ZipFile.read`, mapping `RuntimeError` → `ArchivePasswordRequired` (via
`_read_runtime_error`) and `NotImplementedError` → `ArchiveEncryptionUnsupported`.
`encryption_status()` and `verify_password(pwd)` expose the helpers per handler.

### UI-facing gate helpers

Thin wrappers so the app never reaches into `_impl` / cache internals:

- `get_member_archive_path(path)` — the archive file behind an `archive://`
  member Path, else `None`.
- `archive_password_state(path)` → `'ok' | 'need' | 'unsupported'`. Ordinary paths return
  `'ok'` cheaply (nothing opened), so every read can route through it.
- `try_archive_password(path, password)` — verify (UTF-8 encoded) and, on success,
  remember it; returns a bool.

### Flows (`xefm/app.py`)

- **Extract** — `extract_archive` classifies the ZIP: `'aes'` stops with a
  message; `'zipcrypto'` prompts for a password; otherwise extracts directly. The
  up-front `verify_zip_password` means a wrong password re-prompts with an error
  and never leaves a half-extracted directory. A working password is stored so a
  later browse reuses it.
- **Browse / view** — `_ensure_archive_password` gates opening a file that may
  live in an encrypted ZIP: `'ok'` runs the open callback immediately; `'aes'`
  shows a message; `'need'` shows a masked prompt, verifies via
  `try_archive_password`, and re-prompts on failure. Listing an encrypted archive
  needs no password (the ZIP central directory is unencrypted); the prompt is
  deferred to the first file open.

### Masked input (PuiKit)

The password prompt is a masked field. `xefm/input_dialog.py`'s
`show_input(..., password=True)` forwards `mask="•"` to PuiKit's `TextEdit`, whose
masking is length-preserving (cursor/selection/hit-test still map onto the real
buffer) and disables copy/cut so plaintext never reaches the clipboard. The
widget itself lives in the PuiKit repo (`puikit/widgets/text_edit.py`).

---

## Configuration

```python
# xefm/_config.py
ARCHIVE_CACHE_MAX_OPEN = 5      # max archives kept open by the browse cache
ARCHIVE_CACHE_TTL      = 300    # cache TTL in seconds
CONFIRM_EXTRACT_ARCHIVE = True  # confirm before extracting

# Key bindings
'create_archive': {'keys': ['P'], 'selection': 'required'}
'extract_archive': ['U']
```

## Tests

- `test/test_archive_*.py` — entry conversion, handlers, cache (LRU/TTL), and
  `ArchivePathImpl`.
- `test/test_archive_path_impl.py` — `ArchivePathImpl`, plus (in
  `TestStreamingOutOfAnArchive`) the copy-out path of §1.3: that
  `iter_member_bytes` really streams for zip and tar, that `copy_to` reports more
  than once, and that a cancel raised from the callback propagates and leaves no
  partial file.
- `test/test_archive_registry.py` — the readable-format table: longest-suffix
  matching both ways round, replacement by label, dispatch through
  `_create_handler`, the base class's unencrypted defaults, `is_safe_member_path`,
  and the generic `iter_extract`.
- `test/test_archive_libarchive.py` — the 7z path, skipped wholesale where no
  usable libarchive exists: browsing, extraction, creation, the count agreeing
  with the counting pass, both progress bars moving (a multi-block member has to
  report more than once and land on full), and cancellation mid-archive.
  Fixtures are written with libarchive's own writers, so no external `7z` binary
  is needed; the encrypted one is a stored blob, because libarchive cannot
  *write* an encrypted 7z. ISO and cpio round-trip through XeFM's own create and
  extract, with a long name and a non-ASCII one in the tree because plain ISO
  9660 would mangle both and only Rock Ridge / Joliet keep them. RAR, CAB and RPM
  have **no content fixture** — libarchive writes none of them and there is no
  way to generate one on the test machine — so what is pinned is their
  registration and their read-only property; that a real `.rar` opens is a
  hand-check. Its encryption assertions
  branch on `can_decrypt_7z()`, which is False on macOS's system library — so the
  correct-password case is exercised only where a crypto-capable build is loaded.
- `test/test_archive_password.py` — classification, verification, the registry,
  the `ZipHandler` read path, and the gate helpers (hermetic base64 ZipCrypto
  fixture).
- `test/test_xefm_app_archive_password.py` — `_extract_archive` and the extract UI
  flow (prompt, wrong-then-right retry, AES refusal, plain zip), and
  `_ensure_archive_password`.
- `test/test_archive_task.py` — the task path: per-entry progress and
  cancellation in both loops, the counting pass agreeing with each writer, the
  byte bar streaming inside a large member in all four directions (plus the
  metadata and path-sanitization the stdlib hooks exist to preserve), what a
  cancelled or failed create leaves on disk, and a real app on a MemoryBackend
  running both flows on the worker.

## References

- Read/browse: `xefm/archive.py`; `Path` factory in `xefm/path.py`.
- Create/extract: `XeFMApp` in `xefm/app.py`; byte counting in
  `xefm/archive_progress.py`.
- Task system: `xefm/task.py`; the copy/move/delete equivalent in
  `xefm/file_operations.py`.
- Similar virtual filesystem: `xefm/s3.py`.

