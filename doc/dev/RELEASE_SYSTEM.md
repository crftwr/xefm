# Release System

A release is **cut once, then published one artifact at a time**. Cutting is a
single command; each artifact is a separate command, because the three artifacts
build on three different machines and no one machine can produce them all.

```bash
make release VERSION=x.y.z    # 1. any machine: bump, tag, push, open the GitHub Release
make publish-pypi             # 2. any machine: sdist + wheel -> PyPI
make macos-dmg-upload         # 3. on macOS:    XeFM-<ver>-macos.dmg -> Release
make windows-app-zip-upload   # 4. on Windows:  XeFM-<ver>-win64.zip -> Release
make release-status           #    what has landed so far
```

Steps 2–4 are **peers**: independent, re-runnable, and runnable in any order,
minutes or days after the tag was cut. Each one builds its artifact if it is
missing, checks that the GitHub Release for this version exists, then uploads.
Only step 1 takes a `VERSION=`; the rest read `xefm/__init__.py`'s
`__version__`, so they target the release the checkout is on — pass
`VERSION=x.y.z` to override (e.g. re-uploading an asset for an older tag).

## What a finished release looks like

Four artifacts that all name the same version and cannot drift apart:

1. **A git tag** `vX.Y.Z` (annotated), pushed to `origin` — step 1.
2. **A GitHub Release** at that tag with auto-generated notes — step 1, then
   steps 2–4 attach their artifacts to it.
3. **A PyPI release** — sdist + wheel uploaded with twine, and the same two
   files attached to the GitHub Release — step 2.
4. **The desktop bundles** — `XeFM-<ver>-macos.dmg` and `XeFM-<ver>-win64.zip`
   attached to the GitHub Release — steps 3 and 4.

All three publish steps pass `--clobber`, so re-uploading a rebuilt artifact
supersedes the previous one instead of erroring, and all three share one guard
(`check_release_exists` in the Makefile) so they cannot drift into checking
different preconditions.

### Why PyPI is a separate step

It used to be part of `make release`. It is not, for the same reason the macOS
and Windows uploads never were: cutting a tag and publishing an artifact are
different acts with different toolchains and credentials, and each is worth
re-running on its own. Splitting them also means a failed PyPI upload no longer
leaves a half-cut release behind — the tag and the GitHub Release are already
final, and only step 2 needs retrying.

The split gives up one guarantee that the monolithic recipe had for free: that
the uploaded build matched the tag. `publish-pypi` restores it explicitly by
refusing to run unless `HEAD` sits exactly on `vX.Y.Z` (`make release` leaves
the checkout there; publishing an older release means checking its tag out
first). A PyPI version can never be re-uploaded, so this one is a hard error.

The **unsigned `.msix` is never uploaded to a release**. Windows will not
install an unsigned MSIX, so that artifact exists solely as a Microsoft Store
submission (Microsoft signs it during certification). The portable zip is the
form end users can actually run — see
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
| Clean `main`, up to date with `origin` | step 1 | the release commits, tags and pushes |
| `gh` installed and authenticated (`gh auth login`) | steps 1–4 | creates the GitHub Release, then uploads into it |
| `[pypi]` API token in `~/.pypirc` | step 2 | twine uploads without prompting |
| Apple Developer ID + notarytool profile | step 3 | see [MACOS_APP_BUILD_SYSTEM.md](MACOS_APP_BUILD_SYSTEM.md) |

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

## Step order

### Step 1 — `make release VERSION=x.y.z`

1. `tools/release_preflight.py` — all checks below, **before any mutation**
2. `pytest test` — the suite must pass before anything is built
3. `tools/bump_version.py` — rewrites `__version__`
4. `git commit` (stages `xefm/__init__.py` only) + `git tag -a vX.Y.Z`
5. `make build` — cleans `dist/`, builds sdist + wheel, `twine check`
6. `git push` + `git push origin vX.Y.Z`
7. `gh release create vX.Y.Z --generate-notes --verify-tag`

Step 5 publishes nothing; it is a **gate**. It proves the distributions build
and pass `twine check` while the tag is still local and retractable, and it
leaves `dist/` populated so step 2 of the pipeline has nothing left to build.

Preflight runs first precisely because steps 6–7 are irreversible: a pushed tag
is public. A failed precondition therefore aborts with nothing committed or
tagged.

### Step 2 — `make publish-pypi`

1. Builds `dist/xefm-<ver>.tar.gz` + `.whl` **only if missing** — after
   `make release` they already exist and are published as-is.
2. Guards: the GitHub Release exists, the tag exists locally, and `HEAD` is at
   that tag.
3. `twine upload` of the two files, named explicitly rather than as `dist/*`,
   so a stale artifact from an older version can never be swept in.
4. `gh release upload --clobber` attaches the same two files to the release.

### Steps 3 and 4 — the desktop bundles

`make macos-dmg-upload` / `make windows-app-zip-upload`, on their own platform.
Each builds its artifact if missing (an existing one is never rebuilt — that
would re-run notarization), checks the release exists, and uploads with
`--clobber`.

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
- `gh` is installed and authenticated

It also prints a **non-fatal warning** when PuiKit is installed editable from
`PUIKIT_DIR`: the release depends on the *published* PuiKit
(`requirements.txt` pins `puikit>=1.0`), so if XeFM has come to rely on
unreleased PuiKit changes, release PuiKit first.

## Target reference

| Target | Pipeline step | Use |
|--------|---------------|-----|
| `make release VERSION=x.y.z` | 1 | bump, commit, tag, push, create the GitHub Release |
| `make publish-pypi` | 2 | sdist + wheel → PyPI, and attached to the release |
| `make macos-dmg-upload` | 3 | attach the macOS DMG to the release (macOS only) |
| `make windows-app-zip-upload` | 4 | attach the Windows portable zip to the release (Windows only) |
| `make release-status` | — | list the release's assets and whether PyPI has the version |
| `make build` | — | sdist + wheel into `dist/`, plus `twine check` |
| `make publish-testpypi` | — | rehearsal against TestPyPI (needs a `[testpypi]` token) |

`make publish-testpypi` is the safe rehearsal: it exercises the same build and
upload path, needs neither a tag nor a GitHub Release, and a bad TestPyPI
version costs nothing.

## If a step fails partway

Preflight makes this unlikely, but the recovery order matters — the steps get
progressively harder to undo:

- **Inside step 1, before its `git push`** — nothing is public.
  `git reset --hard HEAD~1` and `git tag -d vX.Y.Z`.
- **Inside step 1, after the tag push** — either finish the remaining commands
  by hand, or delete the remote tag (`git push --delete origin vX.Y.Z`) and
  start over.
- **Steps 2–4** — each is independently re-runnable, so a failure there costs
  only that step. Fix the cause and run the same target again; `--clobber`
  makes a repeated GitHub upload harmless.
- **After `publish-pypi` reaches `twine upload`** — that version is permanently
  taken on PyPI. Do not try to reuse it: bump to the next patch version and cut
  a new release. (A failure *after* twine but before the GitHub attach is safe
  to re-run: twine will refuse the duplicate, so re-run
  `gh release upload vX.Y.Z dist/xefm-<ver>* --clobber` by hand instead.)
