---
name: xefm-brew-publish
description: Carry an XeFM release the rest of the way into Homebrew (crftwr/homebrew-tap) - check that the tap's autobump opened the formula PR, wait for or diagnose its test-bot CI, check that auto-publish ran the publish workflow (brew pr-pull) and start it when it did not, merge a green cask PR, and verify the bottles landed. Safe to run at any time - it acts only on what is due and does nothing when the tap is current. Use when the user says "publish the brew formula", "check the Homebrew tap", "is the formula out yet", "run brew pr-pull for xefm", or when a scheduled check of the tap fires.
---

# Publishing XeFM to Homebrew

The tap carries two `xefm` entries. The **cask** (desktop app, from the DMG)
is bumped on release day by `xefm-release` step 5. The **formula** (terminal
app, from the PyPI sdist) cannot be: Homebrew resolves its Python resources
only from uploads at least a day old. So the formula goes out in three
stages, one or two days after the release:

| Stage | Runs | Result |
|---|---|---|
| `autobump.yml` | every 6 h, or `workflow_dispatch` | once the sdist is 24.5 h old, a PR `xefm X.Y.Z` on branch `bump-xefm-X.Y.Z` |
| `tests.yml` (test-bot) | on that PR | bottles for macOS and Linux, as CI artifacts; then a bot comment |
| `auto-publish.yml` | when test-bot passes on a formula `bump-*` PR | starts `publish.yml` with the PR number and the head SHA test-bot passed on |
| `publish.yml` (`brew pr-pull`) | from auto-publish, or by hand | bottles uploaded to the tap's Release, PR committed to main with the bottle block, PR closed |

So when everything works, nobody has to do anything. This skill is for when
something did not: it reads where the pipeline stands, finishes a stage that
did not start, and diagnoses one that failed. Every step is idempotent, so it
can run at any time.
The background and the past failures are in `doc/dev/RELEASE_SYSTEM.md`,
"The Homebrew tap".

## 1. Read the state

```
python3 .claude/skills/xefm-brew-publish/brew_status.py
```

It prints the formula version and the version its bottles are for, the cask
version, the PyPI version and sdist age, the latest Release, the open
`bump-*` PRs with their check state and head SHA, the recent autobump and
publish runs. The last line is the next action, `next: <action>`. It only
reads, so it is always safe to run. `--json` prints the same as JSON.

## 2. Act on `next:`

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
  no cask PR is open. Release day skipped `xefm-release` step 5's cask bump.
  That bump runs `brew` on this Mac against the live tap checkout, so report
  it with the command (`brew bump-cask-pr --no-fork --version X.Y.Z
  crftwr/tap/xefm`) rather than running it unattended.

## 3. Verify and report

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

## Rules

- Don't post comments on tap PRs or issues. Don't push to the PR branches.
  Fixing a formula is for the user.
- Don't run `brew bump-formula-pr` or `brew bump-cask-pr` on this Mac
  unattended. A failed bump leaves the live tap checkout edited
  (`git -C "$(brew --repo crftwr/tap)" checkout -- Formula/xefm.rb` restores
  it).
- With nothing due (`done` or `wait-*`), say so in one line and stop.
