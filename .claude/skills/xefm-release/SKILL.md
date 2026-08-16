---
name: xefm-release
description: Release a new version of XeFM — confirm the version bump, run the pre-tag checks, cut the tag, publish the GitHub Release with a hand-written note, attach the PyPI sdist + wheel, macOS DMG, and Windows zip, and submit the MSIX to the Microsoft Store. Use when the user says "release XeFM", "release a patch/minor/major version of XeFM", or "ship xefm X.Y.Z" — and also on the Windows machine afterwards, when they say "finish the XeFM release on Windows" or "attach the Windows artifacts" (step 6: no new tag — the Windows zip and the Store MSIX at the existing tag).
---

# Releasing XeFM

Run every command from the root of the xefm checkout. One version
(`__version__` in `xefm/__init__.py`) covers everything, but the artifacts
build on three platforms — the sdist/wheel anywhere, the DMG on macOS, the
win64 zip (and the Store MSIX) on Windows — so a release usually finishes
across two sessions. Run each OS's targets on that OS and report the other
side as remaining; never mark the release done with artifacts missing. The
pipeline is documented in `doc/dev/RELEASE_SYSTEM.md`; the note-writing step
(4) is the one part no Makefile target does.

## 1. Decide the version and confirm it

The single source of truth is `__version__` in `xefm/__init__.py`
(pyproject derives from it via `dynamic = ["version"]`). Map the request:

- "patch" → bump Z (1.0.6 → 1.0.7)
- "minor" → bump Y, reset Z (1.0.6 → 1.1.0)
- "major" → bump X, reset Y and Z
- An explicit version wins; preflight also accepts pre-releases (`1.1.0a1`).

**Confirm the number with the user before proceeding.** State the mapping
explicitly — "current is X.Y.Z, this releases X.Y.Z′" — and wait for a yes
(AskUserQuestion in interactive sessions) before the step-2 checks, which cost
minutes, and long before `make tag`, which publishes: a pushed tag, and later
a PyPI version that can never be re-uploaded. A misread request must be caught
here, not discovered on PyPI.

Do not edit `__version__` yourself — `make tag` bumps, commits, and tags it.

## 2. Judgment checks before tagging

`tools/release_preflight.py` (run by `make tag`) enforces the mechanics: a
well-formed version strictly ahead of the current one, pyproject still
dynamic, on `main`, clean tree, tag free, not behind upstream. It also warns
when PuiKit is installed **editable**: the wheel this release builds depends
on the *published* PuiKit named by requirements.txt's `puikit>=` pin, so if
XeFM has come to rely on unreleased PuiKit changes, release PuiKit first (its
own skill in `../puikit`: `puikit-release`) and raise the pin. Before invoking
any of that, do the checks preflight cannot:

- `git log v<current>..origin/main --oneline` — everything meant for this
  release is merged, nothing unexpected rode along. This list is also the raw
  material for the release note.
- `make icons-check` (macOS only) — the committed icon assets must still
  match their SVG masters in `tools/icon/` before they ship inside bundles.
- The pytest suite runs inside `make tag`, but nothing automated exercises
  the real UI, and Claude cannot run it (the TUI/GUI blocks — per CLAUDE.md,
  never launch it). Ask the user whether they have actually run the app on
  the release code recently, on the backends this release touches (macOS GUI,
  Windows, TUI); anything not exercised is *recorded as skipped* in the
  conversation, never silently assumed.
- Draft the release note now (style in step 4). Writing it forces a review of
  what is actually shipping while the tag is still retractable.

## 3. The Makefile pipeline

```
make tag VERSION=x.y.z   # preflight → pytest → bump __version__ → commit
                         # "Releasing x.y.z" → tag vx.y.z → build gate
                         # (sdist+wheel+twine check) → push commit and tag
make release-github      # open the GitHub Release (auto body — replaced in step 4)
make release-whl         # HEAD must sit exactly on the tag; sdist + wheel
                         # → PyPI, both also attached to the Release
make release-macos-dmg   # macOS: build, sign and notarize the DMG, attach it
make release-status      # read-only: GitHub assets + PyPI published?
```

On the Windows machine, from the same checkout at the tag, run both Windows
targets: `make release-windows-zip` attaches the portable zip, and
`make release-windows-msix` — the odd one out — submits the *unsigned* MSIX
to the Microsoft Store rather than the GitHub Release. The Store re-signs the
package during certification, which proceeds asynchronously (poll with
`msstore submission status`).

- `make tag` commits directly to `main` — sanctioned for release commits only.
- Each target is independently re-runnable; `release-github` is idempotent,
  and the artifact uploads pass `--clobber`. The DMG/zip/sdist file targets
  do **not** rebuild an existing artifact (so a re-upload never re-runs
  notarization); `make macos-dmg` / `make windows-zip` / `make build` force a
  fresh one.
- Only `tag` takes `VERSION=`. The other targets read `__version__` from the
  checkout, so they act on the release the checkout is on; pass `VERSION=` to
  target an older release (and for `release-whl`, check out its tag first —
  HEAD must sit on it).
- Prereqs: `[pypi]` token in `~/.pypirc`, authenticated `gh`,
  `macos_app/signing.env` for sign/notarize, and for the Store submission the
  configured `msstore` CLI plus `windows_app/store.env` (the Partner Center
  identity values and `XEFM_STORE_PRODUCT_ID`) — without store.env the pack
  falls back to a `XeFM.Prototype` identity that cannot be submitted, and the
  Makefile target refuses to run.
- `make publish-testpypi` is the safe rehearsal for `release-whl` — same
  build and upload path, publishes nothing permanent.

## 4. The hand-written release note (not in the Makefile)

`make release-github` creates the Release with GitHub's `--generate-notes` PR
list — two dozen lines that tell a user nothing. That body is a placeholder;
replace it with a hand-written note. The style is codified in CLAUDE.md's
"Release notes" section; the model is v1.0.6. In short:

- Body starts `## XeFM X.Y.Z`. Leave the Release title as `vX.Y.Z`.
- **At most three bullets**, one per change a user of a file manager would
  actually notice: a **bold headline in user terms**, then one to three
  sentences of prose — what changed for them, not how it was built. Name the
  platform or backend when a change is specific to one (macOS, Windows, GUI,
  TUI).
- Fold everything else — smaller fixes, packaging, docs — into one short
  "Also:" paragraph, so nothing is dropped silently but nothing minor gets a
  headline.
- End with
  `**Full Changelog**: https://github.com/crftwr/xefm/compare/vPREV...vNEW`.

Write the note to a scratch location outside the repo (it is never
committed), then:

```
gh release edit vX.Y.Z --notes-file <scratch>/release-note-x.y.z.md
```

## 5. After the release

- `make release-status` must show all of it: `XeFM-<ver>-macos.dmg`,
  `XeFM-<ver>-win64.zip`, the sdist + wheel, and "PyPI: published".
- The Store submission never appears there — it is not a Release asset. Its
  check is `msstore submission status <product id>`; report certification as
  in progress rather than waiting for it.
- List what this machine could not produce (the other OS's artifacts, the
  Store submission) as explicitly remaining, with the commands the other
  session must run.

## 6. Finishing on Windows

The macOS session ends with the Windows artifacts listed as remaining; a
later session on the Windows machine enters here ("finish the XeFM release on
Windows"). There is nothing to bump, tag, or confirm a version for — that all
happened — but there is still a publish gate: state which release is being
finished and get a yes before uploading.

1. Find the release being finished: `git fetch`, then `make release-status`
   on the latest tag (`git describe --tags --abbrev=0 origin/main`) — its
   missing Windows assets are the work. Confirm with the user.
2. Put the checkout on that tag's commit: `git pull` when `main` still sits
   on the release commit, `git checkout vX.Y.Z` when it has moved on. The
   artifacts must be built from the tagged code, not from whatever `main`
   has become.
3. `make release-windows-zip` — builds the bundle and the portable zip, and
   attaches the zip to the GitHub Release.
4. `make release-windows-msix` — repacks the unsigned MSIX and submits it to
   the Microsoft Store (needs `windows_app/store.env` and the configured
   `msstore` CLI; the target checks both). Certification proceeds
   asynchronously — poll with `msstore submission status <product id>` and
   report it as in progress rather than waiting for it.
5. `make release-status` — the release is finished when everything shows:
   DMG, win64 zip, sdist + wheel, PyPI published — with the Store submission
   handed off to certification.
