# Linux Testing System

XeFM is developed on macOS and shipped for Windows as well, which leaves Linux
as the platform nobody runs the suite on by hand — despite it being the one
`pip install xefm` most often lands on. These targets are that hand.

```bash
make test-linux        # the whole suite, on glibc (Debian) - the qa-linux guest
make test-linux-musl   # can libarchive be found on musl? and does its absence degrade cleanly?

make run-linux         # XeFM's TUI, on glibc, interactively
make run-linux-musl    # the same on musl
make run-linux-shell   # a shell in the glibc container, on the stage
```

All of them need a running Docker daemon and nothing else.

---

## glibc is a guest, like the VMs

Since #842 the glibc run is the `qa-linux` guest of
[VM_TESTING_SYSTEM.md](VM_TESTING_SYSTEM.md): `make test-linux` is `make
test-vm GUEST=qa-linux`. It is staged, installed and reported exactly as the
macOS and Windows runs are, so the three differ only in the OS:

- a fresh `python:3.15-slim` container per run, removed after it (`--init`,
  so what a test orphans is reaped as a real system's init would);
- `libarchive13` installed at the start - the runtime package, not
  `libarchive-dev`, because the runtime package alone is the state a user's
  machine is in, and whether XeFM can find the library in that state is part
  of what is tested (on Debian it can: ldconfig knows the soname);
- the working tree staged as git sees it, our packages from this checkout or
  (`PACKAGES=pypi`, a release) from PyPI, and the rest installed into a venv
  from `requirements.txt` and `requirements-dev.txt`;
- the log and JUnit XML in `temp/vm-test-qa-linux-<time>/`.

`qa-linux-floor` is the same container on the lowest Python XeFM declares -
`python:3.11-slim` while `requires-python` is `>=3.11`, read from
`pyproject.toml` each run - and `make release-test` runs both.

A table named `qa-linux` in `~/.config/quality-loop/guests.toml` overrides the
built-in one - another image (`docker = "python:3.11-slim"`), another share.

## musl keeps its own image

`tools/docker/Dockerfile.musl` (`python:3.13-alpine`) answers a different
question, and is not a smaller version of the suite: can the shared library be
*found*. Every one of XeFM's dependencies has a musl wheel, so they are in the
image too (about five seconds), which is what makes `make run-linux-musl`
possible. Only `requirements.txt` is `COPY`ed in, so Docker rebuilds the pip
layer exactly when the dependencies change; the working tree is bind-mounted
read-only at `/src` when the container runs, so an edit needs no rebuild and
the probe cannot write into the tree. `PYTHONDONTWRITEBYTECODE=1` for the same
reason. `.dockerignore` keeps the macOS virtualenv and the git history out of
the build context. Overridable: `DOCKER`, `LINUX_MUSL_IMAGE`.

## Running the TUI

A suite that passes says the logic works; it says nothing about what the screen
looks like under a different terminfo, a different libc's `wcwidth`, or a locale
XeFM did not choose. `make run-linux` is for looking.

```bash
make run-linux                          # the stage's tree on the left, /work on the right
make run-linux-musl                     # the same under musl, /src on the left
make run-linux-shell                    # a shell on the stage; python -m xefm starts XeFM
```

`TERM` and `COLORTERM` are carried in from the host, because a TUI under the
wrong terminfo tells you nothing about the TUI. The left pane is a copy of the
working tree (glibc: the stage) or the read-only tree (musl: `/src`) - a file
manager is exactly the program you do not want writing into your checkout by
accident - and **`/work`** is empty and writable, the pane to copy into, delete
from, and make archives in.

Config and state land in the container's `/root/.xefm` and go away with it, so
every run starts from XeFM's defaults. That is useful for seeing what a new
user sees, and it does mean your own `config.py` is not in play.

## What the first run found

Worth recording, because it is the argument for the targets existing.

**`ctypes.util.find_library('archive')` does not work on musl.** It returned
None on Alpine with libarchive installed at `/usr/lib/libarchive.so.13`, and
returned None still with the `-dev` symlink beside it: musl's `ldconfig` has no
`-p` for CPython to read, and the remaining strategies need a compiler. Since
that call is how `libarchive-c` locates the library, XeFM offered **no** archive
formats beyond zip and tar on Alpine — with libarchive sitting right there.
`_use_known_soname()` answers it by naming `libarchive.so.13` directly, which
`dlopen` resolves without help. `probe_libarchive.py` is the regression test.

**Three tests were environment-dependent, not Linux-specific.** Each failed on
Linux for a reason that had nothing to do with Linux:

- `test_external_programs_path_fix.py` asserted the behaviour of
  `ensure_common_paths_in_env`, whose body is entirely inside
  `if sys.platform == 'darwin'`. Off macOS it was asserting that a no-op had
  done something. Now the macOS assertions are guarded and there is a test that
  the function leaves other platforms alone.
- `test_file_details_disk_usage.py` scrolled the details dialog to line 3 and
  checked it stayed there. Whether line 3 exists depends on how many lines the
  temp directory's *path* wraps to — long under macOS's `/var/folders` TMPDIR,
  short under `/tmp`. `TMPDIR=/tmp` reproduced it on macOS. It scrolls by one
  line now.
- `test_startup_cursor_restoration.py` focused "file2.py (index 1)" in a listing
  built with `iterdir()`, which is in filesystem order. On another filesystem
  index 1 was a different file, so the file the test then deleted was still
  there and restoration succeeded — failing an assertion about something else
  entirely. It looks the name up now.

None of them was a bug in XeFM. All three would have kept working on macOS
forever.

## What Linux gets that macOS does not

Distributions build libarchive with more in it than Apple does:

```
macOS 3.7.4    zlib liblzma bz2lib
Debian 3.7.4   zlib liblzma bz2lib liblz4 libzstd
Alpine 3.8.7   zlib liblzma bz2lib liblz4 libzstd expat openssl libb2 libacl libattr
```

The extra codecs do not change which formats XeFM registers — the candidates in
`xefm/archive_libarchive.py` need only zlib and liblzma — but they do mean a
zstd-compressed 7z entry reads on Linux and fails on macOS, and that a
`.tar.zst` would not reach for an external `zstd` there. XeFM routes `.tar.zst`
through the standard library regardless; see §1.2 of
[ARCHIVE_SYSTEM.md](ARCHIVE_SYSTEM.md).

## Limits

- The containers are the host's architecture. On Apple Silicon that is
  `linux/aarch64`; x86-64 is not run (#842 keeps the platforms to what is
  already run).
- Only the headless/memory backend is exercised. Nothing here opens a terminal
  or a window, so the terminal and GUI backends are not covered — the suite does
  not cover them anywhere.
- Debian and Alpine are two data points, not a distribution matrix. They were
  chosen because glibc/musl is the axis that has actually broken something.
