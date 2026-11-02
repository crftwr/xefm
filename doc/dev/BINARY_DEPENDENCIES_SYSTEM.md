# Binary dependencies: installed where they have wheels

XeFM and the libraries it is built on (PuiKit, similar-files, doc-files)
depend on a few packages that are compiled code. Those are installed
**automatically wherever PyPI has a ready-built wheel for them, and left out
everywhere else**, so that `pip install xefm` (pipx, uv, Homebrew's formula)
never fails on a machine they do not support. This page records how that is
done, why, and what was decided along the way (2026-11-01 – 11-02).

## The rule

- **The code runs without them.** Every feature that needs a compiled
  package degrades when it is missing: the image viewer shows its metadata
  card without Pillow, Find Similar Files groups videos in pure Python
  without numpy. This is CLAUDE.md's "supported, not required", unchanged.
- **The install brings them where it can.** A compiled package is a default
  dependency under an environment marker that lists the **OS and machine
  pairs it publishes wheels for**. Nobody has to name an extra.
- **Where the marker leaves it out, pip never tries to build it.** A build
  from source needs a compiler and the library's headers; without them it
  fails, and one failed dependency fails the whole install.

## Which dependencies this is about

A survey of the whole dependency closure (25 distributions, 2026-11-02):

| Package | Comes from | Wheels | Gated |
|---|---|---|---|
| Pillow | XeFM (image viewer), PuiKit (terminal pictures), similar-files (similar images) | macOS x86_64/arm64, Linux x86_64/aarch64 (glibc 2.27+ or musl), Windows x86/x64/arm64 | yes, in all three |
| numpy | similar-files (video grouping); PuiKit on Windows (GUI backend) | the same pairs as Pillow | yes in similar-files; PuiKit's is Windows-only, where every machine has wheels |
| watchdog | XeFM | the above plus armv7, i686, ppc64le, s390x, … | no need |
| pyobjc | PuiKit, macOS only | universal2 | no need |
| windows-curses | PuiKit, Windows only, until 1.19.0 | Windows x86/x64 only, **no arm64, no sdist** | dropped (see below) |

The other 18 are pure Python and install everywhere. pypdf (doc-files) is
one of them, which is why it needs no marker.

## The marker

```
(sys_platform == 'darwin' and (platform_machine == 'x86_64' or platform_machine == 'arm64'))
or (sys_platform == 'linux' and (platform_machine == 'x86_64' or platform_machine == 'aarch64'))
or (sys_platform == 'win32' and (platform_machine == 'AMD64' or platform_machine == 'ARM64' or platform_machine == 'x86'))
```

It mirrors how the wheels are published: per OS, per machine.

**Why the OS is in it.** The first version listed machine names alone
(`x86_64`, `AMD64`, `arm64`, `aarch64`, `ARM64`, `x86`). A machine name with
wheels on one OS can have none on another: Cygwin and MSYS2 report `x86_64`,
FreeBSD on ARM reports `arm64`. pip then built Pillow and numpy there and
failed. similar-files 0.5.0 shipped that version; 0.5.1 fixed it.

**Why not extras.** `similar-files[image,fast]` worked, but every host had to
know to ask, and asking on a machine without wheels failed the install. A
marker on a default dependency gets the same packages to the same machines
without anyone asking, and leaves them out where asking would fail.

**Why not "try, and skip on failure".** pip has no such dependency. A
package either is required for an environment or is not; the marker is the
only way to say "only here".

## Where it is applied, and what holds it

| Where | What | Test |
|---|---|---|
| PuiKit `pyproject.toml` | `pillow>=9` | `tests/test_dependencies.py` |
| similar-files `pyproject.toml` (0.5.1) | `Pillow>=10`, `numpy>=2.0` | `test/test_dependencies.py` |
| XeFM `requirements.txt` | `pillow` | `test/test_requirements.py` |

Each test evaluates the marker for the platforms with wheels (must apply) and
for a list without (must not: armv7l, armv6l, i686, ppc64le, s390x, riscv64
on Linux; Cygwin, MSYS2, FreeBSD). The three markers are the same string;
change them together.

similar-files and doc-files had a "core: standard library only" rule, with
Pillow, numpy and pypdf as extras. The user chose (2026-11-02) to make them
default dependencies so a host names the library alone: similar-files 0.5.0
for Pillow and numpy, doc-files 0.2.0 for pypdf (pure Python, so no marker).
Their CLAUDE.md files record the new rule, and each `make test-core` installs
the package with `--no-deps`, so the suites still prove the code runs
without them.

XeFM's `requirements.txt` therefore reads `similar-files>=0.5.1` and
`doc-files>=0.2.0`, with no extras.

## numpy, and why XeFM ships it

Find Similar Files compares every video with every other (O(N²)). On a real
library of 14,921 feature-length videos (20.9 million keyframes), the
comparison took an estimated **18.6 hours and 9.3 GB** with similar-files
0.3.2. similar-files 0.4.0 keeps the index in flat arrays (**76 minutes,
4.9 GB**), and in numpy when it is installed (**18 minutes**), with exactly
the same results. The numbers and what was tried are in similar-files'
`doc/dev/VIDEO_SIMILARITY.md`.

numpy reached Windows installs already, as PuiKit's dependency. The user
decided (2026-11-02) to ship it everywhere it has wheels, which is what the
marker above does. Its cost: 34 MB installed on macOS (a 5.5 MB wheel),
licensed BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0, which the
notices generator picks up. The DMG and the Windows builds collect it with
the rest of the closure, with no build-script change.

A scan's log says which comparison ran, for example
`video: comparing 14921 videos (20949116 keyframes) with numpy 2.5.4`, or
`with pure Python (install numpy 2 …)`.

## What a user without wheels gets

On a machine the marker leaves out, `pip install xefm` succeeds without
Pillow and numpy. The image viewer shows its metadata card, similar images
are unavailable with a hint, and videos are grouped in pure Python. A user
who installs Pillow or numpy by hand (`pip install pillow numpy`, or
`uv tool install xefm --with pillow --with numpy`) gets the features back:
everything finds them at runtime.

## Known gaps

The marker cannot see these, and they still fail the install as before:

- **glibc older than 2.27.** The Linux wheels need it; markers cannot test
  the libc version.
- **A 32-bit userland on a 64-bit kernel** (32-bit Raspberry Pi OS):
  `platform_machine` reports the kernel's `aarch64`.
- **Termux on Android** reports `linux` and `aarch64`, but manylinux wheels
  do not run there.

## windows-curses, and the curses backend

windows-curses has no arm64 wheel and no sdist, and PuiKit required it on
every Windows machine, so native ARM64 Python on Windows could not install
XeFM at all. It served only PuiKit's curses backend, which `tui` has not
chosen on Windows since the VT backend replaced it there (PDCurses mis-sizes
wide glyphs and swallows inline images, #283, #306).

The user decided (2026-11-02) to drop the dependency and the backend. PuiKit
1.19.0 no longer requires windows-curses, refuses `create_backend("curses")`
on Windows with a hint to use `tui` (unless windows-curses was installed by
hand), and deprecates the curses backend everywhere; PuiKit 2.0 removes it,
as its compatibility policy allows only in a major version. XeFM follows:
`--backend curses` is refused on Windows and logs a deprecation warning on
macOS and Linux, where it stays as the fallback for terminals off the xterm
dialect until PuiKit 2.0.

## The extras that remain

similar-files keeps `[image]` and `[fast]`, doc-files keeps `[pdf]`, for
installs that still name them. Asking for an extra a package no longer has
only makes pip and uv warn, so they can be removed in any later minor
release: `[pdf]` already does nothing, and `[image]`/`[fast]` only force
Pillow or numpy on a machine the marker leaves out, which `pip install pillow
numpy` does as well. When removing them, update the hints that name them
(similar-files' image extractor and its video log line).

## Keeping it current

When Pillow or numpy start or stop publishing wheels for a pair, update the
marker in all three places and the tests' lists. To see what a package
publishes:

```bash
curl -fsSL https://pypi.org/pypi/numpy/json | python3 -c "
import json, sys
for f in json.load(sys.stdin)['urls']:
    if f['filename'].endswith('.whl'): print(f['filename'])"
```

Any new compiled dependency gets the same treatment: check its wheels first,
gate it by OS and machine if they do not cover every platform, and make the
code run without it.
