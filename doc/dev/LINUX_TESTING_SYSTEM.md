# Linux Testing System

XeFM is developed on macOS and shipped for Windows as well, which leaves Linux
as the platform nobody runs the suite on by hand — despite it being the one
`pip install xefm` most often lands on. These targets are that hand.

```bash
make test-linux        # the whole suite, on glibc (Debian)
make test-linux-musl   # can libarchive be found on musl? and does its absence degrade cleanly?

make run-linux         # XeFM's TUI, on glibc, interactively
make run-linux-musl    # the same on musl
make run-linux-shell   # a shell in that container
```

All of them need a running Docker daemon and nothing else.

---

## Why two images

They answer different questions, and the second one is not a smaller version of
the first.

| | `tools/docker/Dockerfile` | `tools/docker/Dockerfile.musl` |
| --- | --- | --- |
| Base | `python:3.13-slim` (Debian, glibc) | `python:3.13-alpine` (musl) |
| Installs | libarchive13 + `requirements.txt` + pytest | libarchive + `requirements.txt` + `libarchive-c` |
| `make test-…` runs | `pytest test/` | `tools/docker/probe_libarchive.py` |
| Answers | does XeFM work on Linux | can the shared library be *found* |

The musl image carries XeFM's dependencies as well, but not to run the suite
twice — every one of them has a musl wheel, so they cost about five seconds, and
having them is what makes `make run-linux-musl` possible. What only Alpine can
*tell* us is whether the library is found at all, so that is all
`make test-linux-musl` asks.

`libarchive-dev` is installed in neither. The runtime package alone is the state
a user's machine is in, and coping with that state is part of what is being
tested.

## Why the source is mounted, not copied

The images hold the **dependencies**; the working tree is bind-mounted read-only
at `/src` when the container runs. So an edit needs no rebuild, and a test run
cannot write into the tree it is testing. `PYTHONDONTWRITEBYTECODE=1` is set for
the same reason — bytecode beside a read-only mount would fail.

Only `requirements.txt` is `COPY`ed into the image, which means Docker rebuilds
the pip layer exactly when the dependencies change and reuses it every other
time. `.dockerignore` keeps the macOS virtualenv and the git history out of the
build context.

Overridable: `LINUX_PYTHON` (default 3.13), `DOCKER`, `LINUX_IMAGE`,
`LINUX_MUSL_IMAGE`.

## Running the TUI

A suite that passes says the logic works; it says nothing about what the screen
looks like under a different terminfo, a different libc's `wcwidth`, or a locale
XeFM did not choose. `make run-linux` is for looking.

```bash
make run-linux                          # /src on the left, /work on the right
make run-linux LEFT=/work RIGHT=/etc    # or wherever
make run-linux-musl                     # the same, under musl
make run-linux-shell TUI_IMAGE=xefm-test-linux-musl
```

The container gets `-it --init` — the second so Ctrl-C reaches XeFM instead of
PID 1 — and `TERM` and `COLORTERM` are carried in from the host, because a TUI
under the wrong terminfo tells you nothing about the TUI.

Two directories, deliberately different:

- **`/src`** is the working tree, **read-only**. A file manager is exactly the
  program you do not want writing into your checkout by accident.
- **`/work`** is empty and writable — the pane to copy into, delete from, and
  make archives in.

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

- The images are built for the host's architecture. On Apple Silicon that is
  `linux/aarch64`; pass `--platform` through `DOCKER` if x86-64 matters.
- Only the headless/memory backend is exercised. Nothing here opens a terminal
  or a window, so the curses and GUI backends are not covered — the suite does
  not cover them anywhere.
- Debian and Alpine are two data points, not a distribution matrix. They were
  chosen because glibc/musl is the axis that has actually broken something.
