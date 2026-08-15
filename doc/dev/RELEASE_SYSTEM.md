# Release System

Releasing is **one target per artifact**. There is no single release command,
because the artifacts build on three different platforms and no one machine can
produce them all.

```bash
make tag VERSION=x.y.z     # any machine: bump __version__, commit, tag, push
make release-github        # any machine: open the GitHub Release at that tag
make release-whl           # any machine: sdist + wheel -> PyPI (+ the Release)
make release-macos-dmg     # on macOS:    XeFM-<ver>-macos.dmg  -> the Release
make release-windows-zip   # on Windows:  XeFM-<ver>-win64.zip  -> the Release
make release-status        #              what has landed so far
```

Order matters exactly twice: `tag` first (everything else names the tag it
creates), then `release-github` (the three `release-<artifact>` targets upload
into the Release it opens). Those three are **peers** — independent,
re-runnable, and runnable in any order, minutes or days later. Each builds its
artifact if it is missing, re-checks its preconditions, then uploads.

Only `tag` takes a `VERSION=`. The rest read `xefm/__init__.py`'s `__version__`,
so they act on the release the checkout is on — pass `VERSION=x.y.z` to override
(e.g. re-uploading an asset for an older tag).

## Target naming

Targets are named `<verb>-<artifact>`, and the verb says how far the thing goes:

| Verb | Reach | macOS | Windows | Windows Store | Python |
|------|-------|-------|---------|---------------|--------|
| *(none)* — build | your build dir | `macos-dmg` | `windows-zip` | `windows-msix` | `build` |
| `install-` | your machine | `install-macos-dmg` | `install-windows-zip` | `install-windows-msix` | — |
| `uninstall-` | your machine | `uninstall-macos-dmg` | `uninstall-windows-zip` | `uninstall-windows-msix` | — |
| `release-` | the public | `release-macos-dmg` | `release-windows-zip` | never | `release-whl` |
| `clean-` | your build dir | `clean-macos` | `clean-windows` | (same) | — |

Each names its **artifact**, not its platform's app bundle, so the rows line up:
`macos-dmg`, `windows-zip` and `windows-msix` are siblings, and each takes
whichever verbs make sense for it. Only the `release-*` row is the pipeline; the
others publish nothing and can be run as often as you like.

The one deliberate gap is the MSIX's missing `release-`: an unsigned MSIX can
never be a download (see below), so there is nothing to publish.

Every `uninstall-*` target is idempotent — removing something that was never
installed reports that and succeeds — and none of them depend on the artifact
they installed from, so uninstalling still works after `make clean-macos` or
`make clean-windows` has removed the build directory. Pass whichever
`MACOS_INSTALL_DIR` / `WINDOWS_INSTALL_DIR` you installed with.

The `install-*` targets deliberately install **from the distributable artifact**
— `install-macos-dmg` mounts the DMG, `install-windows-zip` expands the zip —
rather than copying the build directory. That makes them a real check on the
thing users download: a packaging, signing or truncation problem surfaces on
your machine instead of on theirs.

`make publish-testpypi` is deliberately outside the `release-*` family: it needs
neither a tag nor a GitHub Release and publishes nothing permanent.

## What a finished release looks like

Four artifacts that all name the same version and cannot drift apart:

1. **A git tag** `vX.Y.Z` (annotated), pushed to `origin` — `tag`.
2. **A GitHub Release** at that tag with auto-generated notes — `release-github`,
   which the three `release-<artifact>` targets then attach to.
3. **A PyPI release** — sdist + wheel uploaded with twine, and the same two
   files attached to the GitHub Release — `release-whl`.
4. **The desktop bundles** — `XeFM-<ver>-macos.dmg` and `XeFM-<ver>-win64.zip`
   attached to the GitHub Release — `release-macos-dmg` / `release-windows-zip`.

All three artifact targets pass `--clobber`, so re-uploading a rebuilt artifact
supersedes the previous one instead of erroring, and all three share one guard
(`check_release_exists` in the Makefile) so they cannot drift into checking
different preconditions. `release-github` is idempotent too: an existing Release
is reported and left alone rather than erroring.

### Why tagging and publishing are separate

They were one command once. Splitting them follows the shape of the work: a tag
is git state, and each artifact is a different toolchain with different
credentials on a different machine. `make tag` needs no `gh` and no PyPI token;
`release-whl` needs both. A failure in any publish step now costs only that
step — the tag and the Release stay final, and you re-run the one target.

The split gives up one guarantee the monolith had for free: that the uploaded
build matched the tag. `release-whl` restores it explicitly by refusing to run
unless `HEAD` sits exactly on `vX.Y.Z` (`make tag` leaves the checkout there;
publishing an older release means checking its tag out first). A PyPI version
can never be re-uploaded, so that one is a hard error.

The **unsigned `.msix` is never uploaded to a release**. Windows will not
install an unsigned MSIX, so that artifact exists solely as a Microsoft Store
submission (Microsoft signs it during certification; the signed result is the
[Store listing](https://apps.microsoft.com/detail/9PK2X44W810V)). The portable
zip is the form end users can run straight from a release — see
[DESKTOP_MODE_GUIDE.md](../DESKTOP_MODE_GUIDE.md#installing-the-desktop-app-package)
for the Mark-of-the-Web / SmartScreen instructions that go with it.

See [MACOS_APP_BUILD_SYSTEM.md](MACOS_APP_BUILD_SYSTEM.md) and
[WINDOWS_APP_BUILD_SYSTEM.md](WINDOWS_APP_BUILD_SYSTEM.md) for signing and
notarization, which the bundles need and the PyPI artifacts do not.

## Linking to the latest release

`https://github.com/crftwr/xefm/releases/latest` always redirects to the newest
release that is neither a draft nor a pre-release, so documentation can link to
it once and never touch it again. That is what the README and the Desktop Mode
Guide use.

GitHub also serves `…/releases/latest/download/<asset-name>` as a direct
download, but only for an asset whose **name does not change between releases**.
XeFM's bundle filenames embed the version (`XeFM-1.0.1-macos.dmg`,
`XeFM-1.0.1-win64.zip`), so that form does not apply — a permanent direct link
would mean also attaching a second, version-less copy of each asset
(`XeFM-macOS.dmg`, `XeFM-Windows-x64.zip`) on every release. The plain
`/releases/latest` page link avoids that duplication and is what the docs use.

## Prerequisites

| Requirement | Needed by | Why |
|-------------|-----------|-----|
| Clean `main`, up to date with `origin` | `tag` | it commits, tags and pushes |
| `gh` installed and authenticated (`gh auth login`) | every `release-*` | opens the Release, then uploads into it |
| `[pypi]` API token in `~/.pypirc` | `release-whl` | twine uploads without prompting |
| Apple Developer ID + notarytool profile | `release-macos-dmg` | see [MACOS_APP_BUILD_SYSTEM.md](MACOS_APP_BUILD_SYSTEM.md) |

`make tag` needs none of the publishing credentials — it is pure git and version
work. Preflight still *warns* when `gh` is missing or unauthenticated, since
every target after `tag` needs it and finding out before the tag is public is
cheaper than after, but it will not block the tag.

`build` and `twine` are installed into `.venv` on demand by `make build`; they
are release-time tooling and deliberately stay out of `requirements.txt`.

## The version literal

`xefm/__init__.py`'s `__version__` is the **only** place the version string
appears in this repo. Everything else derives it:

- `pyproject.toml` — `dynamic = ["version"]`, `version = { attr = "xefm.__version__" }`
- `xefm.const` / `xefm.app` — re-export it for `xefm --version`
- `macos_app/build.sh`, `macos_app/create_dmg.sh` — `sed` the literal out
- `windows_app/build.ps1` — `Select-String` the literal out (→ `XeFM.rc`)

`tools/bump_version.py` rewrites that one line (via `tools/_version_source.py`,
which both release scripts share so they can never disagree about where the
literal lives). It reads the literal statically — no `import xefm` — so the
release tooling never needs XeFM's runtime dependencies just to learn the
version.

## What each target does

### `make tag VERSION=x.y.z`

1. `tools/release_preflight.py` — all checks below, **before any mutation**
2. `pytest test` — the suite must pass before anything is built
3. `tools/bump_version.py` — rewrites `__version__`
4. `git commit` (stages `xefm/__init__.py` only) + `git tag -a vX.Y.Z`
5. `make build` — cleans `dist/`, builds sdist + wheel, `twine check`
6. `git push` + `git push origin vX.Y.Z`

Step 5 publishes nothing; it is a **gate**. It proves the distributions build
and pass `twine check` while the tag is still local and retractable, and it
leaves `dist/` populated so `release-whl` has nothing left to build.

Preflight runs first precisely because step 6 is irreversible: a pushed tag is
public. A failed precondition therefore aborts with nothing committed or tagged.

### `make release-github`

Checks `gh` is usable and the tag is **on `origin`** (`--verify-tag` will not
invent a tag GitHub does not have, which is why `tag` pushes it), then
`gh release create vX.Y.Z --generate-notes --verify-tag`. If the Release already
exists it says so and changes nothing, so re-running the pipeline is free.

### `make release-whl`

1. Builds `dist/xefm-<ver>.tar.gz` + `.whl` **only if missing** — after
   `make tag` they already exist and are published as-is.
2. Guards: the GitHub Release exists, the tag exists locally, and `HEAD` is at
   that tag.
3. `twine upload` of the two files, named explicitly rather than as `dist/*`,
   so a stale artifact from an older version can never be swept in.
4. `gh release upload --clobber` attaches the same two files to the Release.

The name is for the headline artifact; the sdist rides along in the same step.

### `make release-macos-dmg` / `make release-windows-zip`

On their own platform. Each builds its artifact if missing (an existing one is
never rebuilt — that would re-run notarization), checks the Release exists, and
uploads with `--clobber`. To force a fresh artifact first, run `make macos-dmg`
or `make windows-zip`.

## Preflight checks

`tools/release_preflight.py <version>` collects *all* problems and reports them
together rather than stopping at the first:

- `VERSION` is well-formed `X.Y.Z` (optionally `rc1` / `.post1` / `.dev1`)
- `VERSION` is strictly ahead of the current `__version__` (no re-release, no rollback)
- `pyproject.toml` still *derives* the version — a static `[project].version`
  would silently win at build time, so the wheel could ship a different number
  than `xefm --version` reports
- on branch `main`, working tree clean
- tag `vX.Y.Z` does not already exist
- local branch is not behind its upstream (a non-fast-forward push mid-release)

It also prints **non-fatal warnings** for the two things a checkout cannot
decide for you:

- PuiKit is installed editable from `PUIKIT_DIR` — the release depends on the
  *published* PuiKit (the `puikit` pin in `requirements.txt`), so if XeFM has
  come to rely on unreleased PuiKit changes, release PuiKit first.
- `gh` is missing or unauthenticated — `make tag` does not need it, but every
  target after it does.

## Target reference

| Target | Publishes | Use |
|--------|-----------|-----|
| `make tag VERSION=x.y.z` | the tag | bump `__version__`, commit, tag, push |
| `make release-github` | the Release | open the GitHub Release at that tag |
| `make release-whl` | PyPI + Release | sdist + wheel → PyPI, and attached to the Release |
| `make release-macos-dmg` | Release | attach the macOS DMG (macOS only) |
| `make release-windows-zip` | Release | attach the Windows portable zip (Windows only) |
| `make release-status` | — | list the Release's assets and whether PyPI has the version |
| `make build` | — | sdist + wheel into `dist/`, plus `twine check` |
| `make macos-dmg` | — | build the DMG locally (macOS only) |
| `make windows-zip` | — | build the portable zip locally (Windows only) |
| `make install-macos-dmg` | — | install this machine's copy from the DMG (macOS only) |
| `make install-windows-zip` | — | install this machine's copy from the zip (Windows only) |
| `make uninstall-macos-dmg` | — | remove that installed `XeFM.app` (macOS only) |
| `make uninstall-windows-zip` | — | remove that installed bundle (Windows only) |
| `make publish-testpypi` | TestPyPI | rehearsal (needs a `[testpypi]` token) |

`make publish-testpypi` is the safe rehearsal: it exercises the same build and
upload path, needs neither a tag nor a GitHub Release, and a bad TestPyPI
version costs nothing.

## If a step fails partway

Preflight makes this unlikely, but the recovery order matters — the steps get
progressively harder to undo:

- **Inside `tag`, before its `git push`** — nothing is public.
  `git reset --hard HEAD~1` and `git tag -d vX.Y.Z`.
- **Inside `tag`, after the tag push** — the tag is public. Either carry on
  (nothing is wrong with a tag that has no Release yet), or delete the remote
  tag (`git push --delete origin vX.Y.Z`) and start over.
- **Any `release-*` target** — each is independently re-runnable, so a failure
  costs only that target. Fix the cause and run the same one again; `--clobber`
  makes a repeated GitHub upload harmless, and `release-github` no-ops on an
  existing Release.
- **After `release-whl` reaches `twine upload`** — that version is permanently
  taken on PyPI. Do not try to reuse it: bump to the next patch version and cut
  a new release. (A failure *after* twine but before the GitHub attach is safe
  to fix by hand: twine would refuse the duplicate, so run
  `gh release upload vX.Y.Z dist/xefm-<ver>* --clobber` instead of the target.)
