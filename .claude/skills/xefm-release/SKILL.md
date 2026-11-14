---
name: xefm-release
description: Release a new version of XeFM — confirm the version bump, run the pre-tag checks, cut the tag, publish the GitHub Release with a hand-written note, attach the PyPI sdist + wheel, macOS DMG, and Windows zip, bump the Homebrew tap (crftwr/homebrew-tap), and submit the MSIX to the Microsoft Store. Use when the user says "release XeFM", "release a patch/minor/major version of XeFM", or "ship xefm X.Y.Z" — and also on the Windows machine afterwards, when they say "finish the XeFM release on Windows" or "attach the Windows artifacts" (step 6: no new tag — the Windows zip and the Store MSIX at the existing tag) — and for the Homebrew formula, which goes out a day later, when they say "is the formula out yet", "check the Homebrew tap" or "publish the brew formula" (step 7).
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
- `make release-review` — reviews `v<current>..origin/main` against the
  core's rules (CLAUDE.md, "What belongs in the core"), in three layers.
  Report each to the user; fix nothing here, the user decides what is fixed
  before tagging.
  1. **Core or extension?** For each `in-core?` line (a new module), and for
     the release as a whole, judge whether it could have been an extension.
  2. **Findings** (exit 1) are the mechanical rules — `print()`, logger
     names, permissions, placement, docs, skill references, translations,
     and the public API compared against the last tag (a deprecation that
     never shipped before its removal, a break with no bump, `API_VERSION`
     moving twice). Same result every time; list them as they are.
  3. **For review** lines point at what the judgment rules need looked at —
     dependencies, scheme checks, capability reads, the firewall, default
     keys, actions no doc names. Read each site and give a verdict per
     line; a pointer is not a violation by itself.
- **The previous release reached Homebrew.** Run step 7's status script.
  It must say `next: done`: formula, bottles and cask all on the current
  release. Anything else means the last release never fully reached
  Homebrew. Handle it as step 7 says before tagging, or report it to the
  user and let them decide whether to go on.
- `make icons-check` (macOS only) — the committed icon assets must still
  match their SVG masters in `tools/icon/` before they ship inside bundles.
- `make api-compat` — every package in crftwr/xefm-extensions still passes
  its check and its own tests against the release code. A failure is a
  broken promise to a real extension: stop and fix, or confirm with the user
  that the package is the one to change.
- `git diff v<current> -- test/data/api_snapshot.txt` — what the public API
  did since the last release (`make release-review` lists the breaking
  changes, deprecations and stable additions; this diff is the detail
  behind them). If the `API_VERSION` line moved, the release
  broke something stable on purpose: say so in a bullet of the note, with
  what an extension author must change. A line that turned `deprecated`
  gets the same treatment: name the replacement. Stable additions and
  Preview changes an extension author would notice go in the note's "Also"
  paragraph.
- `make release-test` runs inside `make tag` (#842): `pytest --host-only`
  here, then the whole suite in `qa-mac` (Tart), `qa-win` (VMware) and
  `qa-linux` (Docker) on PuiKit, doc-files, similar-files and quality-loop
  **as PyPI has them**, and the musl probe - side by side, about ten to
  fifteen minutes (as long as `qa-win`), so tell the user before starting it. It needs VMware Fusion, Tart and Docker up on this
  Mac, and neither VM held by a `run-vm` here or in Keyhac. Because the
  guests install our packages from PyPI, anything this release relies on
  must already be released there (preflight's editable-PuiKit warning is the
  same point). A failure stops the tag: report it with the log under
  `temp/release-test-<time>/<guest>.log` (and the JUnit XML under
  `temp/vm-test-<guest>-<time>/`), never retry it away. Docker down is
  refused before any guest starts: start Docker Desktop and run it again. Running it ahead
  of `make tag` on its own is fine and shortens the tag step's surprises.
- Nothing automated exercises the real UI, and Claude cannot run it (the TUI/GUI blocks — per CLAUDE.md,
  never launch it). Ask the user whether they have actually run the app on
  the release code recently, on the backends this release touches (macOS GUI,
  Windows, TUI); anything not exercised is *recorded as skipped* in the
  conversation, never silently assumed.
- Draft the release note now (style in step 4). Writing it forces a review of
  what is actually shipping while the tag is still retractable.

## 3. The Makefile pipeline

```
make tag VERSION=x.y.z   # preflight → release-test → bump __version__ → commit
                         # "Releasing x.y.z" → tag vx.y.z → build gate
                         # (sdist+wheel+twine check) → push commit and tag
make release-github      # open the GitHub Release (auto body — replaced in step 4)
                         # and attach xefm-X.Y.Z-skill.zip (the agent skill)
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

The bundle targets (DMG, Windows zip, MSIX) refuse a venv holding anything
not installed from a package index — an editable PuiKit included — or below
a requirement (#809). Before `release-macos-dmg` and the Windows targets, put
the released versions in: `make install-puikit PUIKIT_DIR=`, `pip install
--force-reinstall --no-deps <whatever the error names>`, `pip install -r
requirements.txt`. Never set `XEFM_BUNDLE_ALLOW_LOCAL` for a release build;
it is for local development builds. Restore the editable installs afterwards
if the user develops against them.

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

- Bump the Homebrew **cask** once the DMG is attached (doing it earlier
  points the tap at a file that does not exist yet). When CI passes, a bot
  comment says to merge it, so merge it with the button (a cask has no bottles):
  ```
  brew bump-cask-pr --no-fork --version X.Y.Z crftwr/tap/xefm   # only if this release has a DMG
  ```
  Do **not** bump the formula by hand. It goes out a day later on its
  own: see step 7. Report "formula: autobump after <date+1>, then
  auto-publish" as remaining. Both bumps use the branch `bump-xefm-X.Y.Z`,
  and autobump waits while the cask PR is still open, so an unmerged cask PR
  holds back the formula. If PuiKit raised its PyObjC floor in this release,
  bump the hand-kept `pyobjc-core` / `pyobjc-framework-cocoa` resources under
  the formula's `on_macos` block, and `truststore` there if
  `requirements.txt` raised its floor. A new requirement marked for macOS
  only must be added to that block by hand: autobump resolves on Ubuntu and
  never sees it. See `doc/dev/RELEASE_SYSTEM.md`, "The Homebrew tap".
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
   attaches the zip to the GitHub Release. If the collector refuses the venv
   (a local install, a version below `requirements.txt`), bring it to the
   released versions as above and rebuild with `make windows-zip`.
4. `make release-windows-msix` — repacks the unsigned MSIX and submits it to
   the Microsoft Store (needs `windows_app/store.env` and the configured
   `msstore` CLI; the target checks both). Certification proceeds
   asynchronously — poll with `msstore submission status <product id>` and
   report it as in progress rather than waiting for it.
5. `make release-status` — the release is finished when everything shows:
   DMG, win64 zip, sdist + wheel, PyPI published — with the Store submission
   handed off to certification.

## 7. The Homebrew formula (a day later, and before the next release)

The tap carries two `xefm` entries. Step 5 bumps the **cask** (desktop app,
from the DMG) on release day. The **formula** (terminal app, from the PyPI
sdist) cannot be bumped then: Homebrew resolves its Python resources only
from uploads at least a day old. So the formula goes out on its own, one or
two days after the release, through the tap's workflows:

| Stage | Runs | Result |
|---|---|---|
| `autobump.yml` | every 6 h, or `workflow_dispatch` | once the sdist is 24.5 h old, a PR `xefm X.Y.Z` on branch `bump-xefm-X.Y.Z` |
| `tests.yml` (test-bot) | on that PR | bottles for macOS and Linux, as CI artifacts; then a bot comment |
| `auto-publish.yml` | when test-bot passes on a formula `bump-*` PR | starts `publish.yml` with the PR number and the head SHA test-bot passed on |
| `publish.yml` (`brew pr-pull`) | from auto-publish, or by hand | bottles uploaded to the tap's Release, PR committed to main with the bottle block, PR closed |

When everything works, nobody has to do anything. Nothing notices when it
does not, though: after 1.10.1 autobump skipped every formula bump
behind a green run, and nobody saw it for three weeks. So this step runs at
two points: whenever the user asks about the tap ("is the formula out yet",
"publish the brew formula"), and in step 2 of the **next** release, for the
release before it. Every action is idempotent, so it is safe at any time.
The background and the past failures are in `doc/dev/RELEASE_SYSTEM.md`,
"The Homebrew tap".

### Read the state

```
python3 .claude/skills/xefm-release/brew_status.py
```

It prints the formula version and the version its bottles are for, the cask
version, the PyPI version and sdist age, the latest Release, the open
`bump-*` PRs with their check state and head SHA, and the recent autobump
and publish runs. The last line is the next action, `next: <action>`. It
only reads, so it is always safe to run. `--json` prints the same as JSON.

### Act on `next:`


Do the one action, then run the status script again and continue until it
says `done` or a `wait-*`. Don't skip the re-check. Each action changes what
is due next.

- **`done`**: formula, bottles and cask all match the latest release. Nothing
  to do.
- **`wait-cooldown <time>`**, **`wait-sdist`**, **`wait-autobump`**,
  **`wait-ci #<n>`**: nothing to do yet. Report what is pending and when it
  is due. Don't dispatch autobump early: before the cooldown it only logs
  "only N h old" and exits.
- **`dispatch-autobump`**: the cooldown passed more than 8 hours ago and no
  autobump has run since. GitHub drops scheduled runs sometimes. Run it now
  and watch it:
  ```
  gh workflow run autobump.yml -R crftwr/homebrew-tap
  gh run list -R crftwr/homebrew-tap --workflow autobump.yml -L 1   # its id
  gh run watch <id> -R crftwr/homebrew-tap --exit-status
  ```
- **`autobump-failed`**: the latest run after the cooldown failed. Read it:
  `gh run view <id> -R crftwr/homebrew-tap --log-failed | tail -60`. A
  network error in the `check` job (PyPI or GitHub unreachable) is
  transient: dispatch it again once. Anything else (a `bump-formula-pr`
  error, a resource that cannot be resolved, an expired
  `HOMEBREW_TAP_BUMP_TOKEN`) is for the user: stop and report the error
  lines.
- **`autobump-no-pr`**: autobump succeeded after the cooldown and still no
  PR exists. Read its `bump` job log. That is how the duplicate-title bug
  showed itself (`brew bump` skipped because the cask PR had the same title,
  fixed in tap PR #28). Report it. Don't open the formula PR by hand.
- **`investigate-ci #<n>`**: test-bot failed. Find the failed job and its
  error lines:
  ```
  gh pr checks <n> -R crftwr/homebrew-tap
  gh run view <run id> -R crftwr/homebrew-tap --log-failed | tail -80
  ```
  Report them and stop. The usual fixes are edits to the formula on the PR
  branch: a macOS-only requirement missing from the `on_macos` block, a
  PyObjC or truststore floor to raise there (see `RELEASE_SYSTEM.md`). Those
  are the user's call. A runner or network flake can be re-run once with
  `gh run rerun <run id> --failed -R crftwr/homebrew-tap`.
- **`wait-publish #<n>`**: a publish run is in progress, normally the one
  auto-publish started. Watch it (`gh run watch <id> -R crftwr/homebrew-tap
  --exit-status`), then re-check.
- **`publish-failed #<n> run <id>`**: the latest publish run failed. Read it
  (`gh run view <id> -R crftwr/homebrew-tap --log-failed | tail -80`). A
  network error is transient: start it again as under `publish`. Anything
  else, report and stop.
- **`publish #<n> <sha>`**: test-bot passed on a formula PR and no publish
  has run since. auto-publish did not fire (check
  `gh run list -R crftwr/homebrew-tap --workflow auto-publish.yml -L 3`).
  Publish it by hand:
  ```
  gh workflow run publish.yml -R crftwr/homebrew-tap -f pull_request=<n> -f head_sha=<sha>
  gh run list -R crftwr/homebrew-tap --workflow publish.yml -L 1    # its id
  gh run watch <id> -R crftwr/homebrew-tap --exit-status
  ```
  Always pass the `head_sha` the status script printed. If something was
  pushed to the branch after CI passed, pr-pull refuses instead of
  publishing untested bottles. **Never press Merge (or `gh pr merge`) on a
  formula PR.** That publishes no bottles, and installs of the new version
  404. If publish fails, report `--log-failed` and stop.
- **`bottles-missing`**: the formula on main names a version its bottle block
  does not. A formula PR was merged with the button. Find it
  (`gh pr list -R crftwr/homebrew-tap --state merged -L 5`) and publish its
  bottles. This works while the test-bot artifacts last (90 days):
  ```
  gh workflow run publish.yml -R crftwr/homebrew-tap -f pull_request=<n> -f already_merged=true
  ```
- **`merge-cask #<n>`**: a cask PR (xefm or Keyhac) passed its checks. A cask
  has no bottles, so it is merged with the button:
  `gh pr merge <n> -R crftwr/homebrew-tap --merge`.
- **`cask-behind`**: the latest Release has a DMG but the cask is older and
  no cask PR is open. Release day skipped step 5's cask bump.
  That bump runs `brew` on this Mac against the live tap checkout, so report
  it with the command (`brew bump-cask-pr --no-fork --version X.Y.Z
  crftwr/tap/xefm`) rather than running it unattended.

### Verify and report


After a publish, the status script must say `done` (or `merge-cask` /
`cask-behind`, for the cask). Also look at the bottle block on main:

```
gh api repos/crftwr/homebrew-tap/contents/Formula/xefm.rb --jq .content | base64 -d | sed -n '/bottle do/,/^  end/p'
```

It must name `xefm-<version>` in `root_url` and have an `arm64_*` and an
`x86_64_linux` line. The PR shows as **Closed**, not Merged. That is how
pr-pull lands it, and it is correct.

Report in a few lines: what was done (with run and PR links), the versions
now on main, and what is still pending and when it is due. Leave out the
stages that were already done.

### Rules


- Don't post comments on tap PRs or issues. Don't push to the PR branches.
  Fixing a formula is for the user.
- Don't run `brew bump-formula-pr` or `brew bump-cask-pr` on this Mac
  unattended. A failed bump leaves the live tap checkout edited
  (`git -C "$(brew --repo crftwr/tap)" checkout -- Formula/xefm.rb` restores
  it).
- With nothing due (`done` or `wait-*`), say so in one line and go on.
