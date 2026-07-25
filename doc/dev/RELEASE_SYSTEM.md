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
— they only build on their own platform. Produce them there and attach them
afterwards:

```bash
make macos-dmg                                    # on macOS
make windows-app-zip                              # on Windows
gh release upload v1.0.1 macos_app/build/XeFM-1.0.1.dmg
```

See [MACOS_APP_BUILD_SYSTEM.md](MACOS_APP_BUILD_SYSTEM.md) and
[WINDOWS_APP_BUILD_SYSTEM.md](WINDOWS_APP_BUILD_SYSTEM.md) for signing and
notarization, which the bundles need and the PyPI artifacts do not.

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
