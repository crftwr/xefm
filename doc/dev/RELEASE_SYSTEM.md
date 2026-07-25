# Release System

How a XeFM version gets cut: one command, `make release VERSION=x.y.z`, run from
a clean `main` checkout. It mirrors PuiKit's release flow (`../puikit/Makefile`),
so the two repos release the same way.

## What it produces

Three artifacts that all name the same version and cannot drift apart:

1. **A git tag** `vX.Y.Z` (annotated), pushed to `origin`.
2. **A PyPI release** — sdist + wheel uploaded with twine.
3. **A GitHub Release** at that tag, with `dist/*` attached and auto-generated notes.

The macOS `.app`/`.dmg` and the Windows bundle are **not** built by `make release`
— they only build on their own platform. Produce them there and attach them to
the release afterwards, one target per platform:

```bash
make macos-dmg-upload         # on macOS:  builds the DMG if needed, then uploads it
make windows-app-zip-upload   # on Windows: builds XeFM-<ver>-win64.zip, then uploads it
```

Both refuse to run unless the GitHub Release for the current `__version__`
already exists, and both pass `--clobber`, so re-uploading a rebuilt artifact
supersedes the previous one instead of erroring. Override the target release
with `VERSION=x.y.z`.

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

| Requirement | Why |
|-------------|-----|
| `[pypi]` API token in `~/.pypirc` | twine uploads without prompting |
| `gh` installed and authenticated (`gh auth login`) | creates the GitHub Release |
| Clean `main`, up to date with `origin` | the release commits, tags and pushes |

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

`make release VERSION=x.y.z` runs, in this order:

1. `tools/release_preflight.py` — all checks below, **before any mutation**
2. `pytest test` — the suite must pass before anything is built
3. `tools/bump_version.py` — rewrites `__version__`
4. `git commit` (stages `xefm/__init__.py` only) + `git tag -a vX.Y.Z`
5. `make build` — cleans `dist/`, builds sdist + wheel, `twine check`
6. `git push` + `git push origin vX.Y.Z`
7. `twine upload dist/*`
8. `gh release create vX.Y.Z dist/* --generate-notes --verify-tag`

Preflight runs first precisely because steps 6–8 are irreversible: a PyPI
version can never be re-uploaded, and a pushed tag is public. A failed
precondition therefore aborts with nothing committed, tagged or published.

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

## Related targets

| Target | Use |
|--------|-----|
| `make build` | sdist + wheel into `dist/`, plus `twine check` |
| `make publish-testpypi` | dry run against TestPyPI (needs a `[testpypi]` token) |
| `make publish-pypi` | upload only, without the tag/GitHub-Release steps |
| `make macos-dmg-upload` | attach the macOS DMG to the release (macOS only) |
| `make windows-app-zip-upload` | attach the Windows portable zip to the release (Windows only) |

`make publish-testpypi` is the safe rehearsal: it exercises the same build and
upload path, and a bad TestPyPI version costs nothing.

## If a release fails partway

Preflight makes this unlikely, but the recovery order matters — the steps get
progressively harder to undo:

- **Before step 6** — nothing is public. `git reset --hard HEAD~1` and
  `git tag -d vX.Y.Z`.
- **After the tag push, before the upload** — either re-run the remaining steps
  by hand, or delete the remote tag (`git push --delete origin vX.Y.Z`) and start over.
- **After `twine upload`** — that version is permanently taken on PyPI. Do not
  try to reuse it: bump to the next patch version and release again.
