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

Downstream of those, the Homebrew tap's cask and formula point at the DMG and
the sdist. They are bumped by hand, so they *can* drift; see
[The Homebrew tap](#the-homebrew-tap-not-in-the-makefile).

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

It then runs `make release-skill`, which builds
`dist/xefm-X.Y.Z-skill.zip` (`make skill-zip`) and uploads it with
`--clobber`. That zip is the AI-agent skill for XeFM (config edits and
extensions). Its name carries the version, since it describes that release's
config and API; `doc/AGENT_SKILL_FEATURE.md` tells agents how to find the
latest tag and build the URL. Releases up to 1.8.0 carry the older
`xefm-extension-authoring.zip` instead. The zip is pure Python and builds on
any machine, so it rides along with the Release instead of being a fourth
artifact to remember.

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

### The Homebrew tap (not in the Makefile)

[crftwr/homebrew-tap](https://github.com/crftwr/homebrew-tap) carries two
`xefm` entries, each built from an artifact the steps above publish:

| Entry | Built from | Bump with |
|---|---|---|
| `Casks/xefm.rb` — desktop app, macOS arm64 | the DMG on the Release | `brew bump-cask-pr --no-fork --version X.Y.Z crftwr/tap/xefm` |
| `Formula/xefm.rb` — terminal app, macOS + Linux | the sdist on PyPI | `brew bump-formula-pr --no-fork --url <PyPI sdist URL> crftwr/tap/xefm` |

So the tap is bumped last, once `release-whl` and `release-macos-dmg` are
done; bumping either earlier points it at a file that does not exist yet. A
release that ships no DMG (one that fixes only Windows) bumps the formula and
leaves the cask on the older tag, as the DMG table above already does.

**The formula waits a day.** `bump-formula-pr` resolves the resources with
`pip install --uploaded-prior-to=P1D`, a supply-chain cooldown: it ignores
anything uploaded to PyPI in the last 24 hours, so on release day it cannot see
the new `xefm` sdist, nor a PuiKit released the same day, and fails with
"Unable to determine dependencies … Please update the resources manually".
So the release bumps only the cask. The formula is bumped by the tap's
**autobump** workflow (`.github/workflows/autobump.yml`, added after 1.9.0
missed its day): every six hours it compares PyPI with the formula, and once
the new sdist is a day old it runs Homebrew's `bump-packages` action, which
opens the formula's PR. It opens the PR and nothing else. It uses the
`HOMEBREW_TAP_BUMP_TOKEN` secret, because a PR opened with the default
`GITHUB_TOKEN` would not start the tests that build the bottles. Both bumps
push a branch named `bump-xefm-X.Y.Z`. So while a PR from that branch is still
open, whether it is the cask's or an earlier formula bump nobody has published
yet, autobump waits and logs the PR instead of bumping again. A second bump
would only fail pushing over the open PR's branch.

Running `bump-formula-pr` by hand on release day fails the same way. A failed
bump has already rewritten the formula's `url` and `sha256` in the local tap
checkout (`$(brew --repo crftwr/tap)`) and leaves the edit uncommitted. That
checkout is the machine's live Homebrew, so `brew upgrade` there offers the new
version with no bottle behind it (a 404). Restore it with
`git -C "$(brew --repo crftwr/tap)" checkout -- Formula/xefm.rb`.

`bump-formula-pr` regenerates the formula's Python resources. Its
`pypi_packages exclude_packages:` stanza keeps Pillow (taken from Homebrew's
formula), PuiKit's desktop-only PyObjC frameworks and the Windows-only packages
out. PyObjC Core, Cocoa and truststore are kept by hand under `on_macos`, which
regeneration leaves alone; the terminal app needs PyObjC for the Trash, Connect
to Server and the OS image decoder, and truststore to verify HTTPS through
Security.framework. Autobump resolves on Ubuntu, so any requirement marked for
macOS only never reaches the formula on its own: add it to that block by hand.
Bump PyObjC there when PuiKit raises its PyObjC floor, and truststore when
`requirements.txt` raises its floor.

Each bump opens a PR on the tap. Its CI (`brew test-bot`, macOS and Ubuntu)
builds the formula's bottles. The formula PR is opened with the owner's own
token, and GitHub notifies nobody about their own actions, so once test-bot
passes on a `bump-*` PR, a `notify` job in `tests.yml` comments as
github-actions[bot] and mentions the owner. That comment is the signal to act:

- **Formula PR:** the comment gives the exact command, and it publishes the
  bottles and merges the PR in one step. Do **not** press Merge.
  ```
  gh workflow run publish.yml -R crftwr/homebrew-tap -f pull_request=<n> -f head_sha=<sha>
  ```
  That workflow runs `brew pr-pull`, which is what merges the PR and writes the
  bottle block. Merging with the button publishes no bottles. 1.9.0 and 1.10.0
  went out that way, and the formula kept naming the 1.8.0 bottles, so
  installing the new version 404'd.
- **Cask-only PR:** it has no bottles, so the comment says to merge it with
  the button. The Keyhac cask in the same tap gets the same comment.

A formula PR that was merged with the button anyway can still get its bottles:

```
gh workflow run publish.yml -R crftwr/homebrew-tap -f pull_request=<n> -f already_merged=true
```

`pr-pull` cannot do this. Cherry-picking fails because main already has the
commits. `--no-cherry-pick` diffs main against itself, finds no formula to
bottle, and amends main's tip commit. So `already_merged` skips `pr-pull`. It
downloads the `bottles_*` artifacts from the test-bot run for the PR's head and
runs `brew pr-upload` on them, which commits the bottle block and uploads to
the release. 1.10.0's bottles were recovered this way. The artifacts last 90
days.

Casks are moved only by the release, and the formula only by the autobump
workflow above.

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

The bundle builds (DMG, Windows zip, MSIX) ship whatever the build venv
holds, so `tools/collect_dependencies.py` **refuses** a venv that is not what
the release depends on:

- **An editable install other than PuiKit**: its RECORD names only the
  `.dist-info` and the shim, and the package would silently be missing from
  the bundle.
- **Anything not installed from a package index** (#809), PuiKit included:
  an editable or local-directory install, a local wheel, a VCS URL (a PEP 610
  `direct_url.json`). Each may be a build no one released — a `../puikit`
  checkout with uncommitted edits or past its last release, a `similar-files`
  wheel built from a branch.
- **A version outside a requirement** (#809): every collected distribution
  must satisfy `requirements.txt` and the requirements of whatever depends on
  it. A venv left at `puikit 1.15.2` under `puikit>=1.16.1`, or
  `similar-files 0.2.1` under `>=0.3.0`, would otherwise ship that.

Before building, put the released versions into the venv: `make
install-puikit PUIKIT_DIR=` for PuiKit, `pip install --force-reinstall
--no-deps doc-files similar-files` for the others, then `pip install -r
requirements.txt`; switch back to editable installs afterwards to go on
developing. For a local development build only, `XEFM_BUNDLE_ALLOW_LOCAL`
names the ones to let through anyway (comma-separated, e.g.
`XEFM_BUNDLE_ALLOW_LOCAL=puikit,doc-files make macos-app`); an editable
PuiKit's metadata keeps the version current at its install, so its version
goes unchecked then. An unpinned requirement is not checked against PyPI:
`watchdog` ships at whatever version the venv has. The collector also honours
requirement extras (`doc-files[pdf]` brings pypdf).

## Target reference

| Target | Publishes | Use |
|--------|-----------|-----|
| `make tag VERSION=x.y.z` | the tag | bump `__version__`, commit, tag, push |
| `make release-github` | the Release | open the GitHub Release at that tag, with the agent skill zip attached |
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
