# Help Menu Links and Check for Updates

The Help menu's ways out of XeFM: **XeFM Documentation**, **Release Notes**,
**Report an Issue…** and **Check for Updates…**. Each is a keymap action
(`open_documentation`, `release_notes`, `report_issue`, `check_for_updates`),
so the command palette and a user's `KEY_BINDINGS` reach them as well; none is
bound by default.

## Where the code is

- `xefm/updates.py` - everything that does not touch the UI: the URLs, how
  XeFM was installed, version ordering, the PyPI request, the upgrade text and
  the prefilled issue URL. Pure functions over injectable inputs, tested in
  `test/test_updates.py`.
- `XeFMApp._open_link`, `open_documentation`, `open_release_notes`,
  `report_issue`, `check_for_updates`, `_show_update_check` in `xefm/app.py`.

## Opening a link

`panel.open_url(url)` is PuiKit's one intent for it: a backend with the
`os_open` capability launches the browser, the others (the terminal backends)
copy the URL to the clipboard and return False. `_open_link` only reads that
result to word the log line - no capability branch in XeFM.

## Install kind

`install_kind()` reads where the `xefm` package sits (realpath):

| Kind | Evidence |
|------|----------|
| `msix` | path contains `/WindowsApps/` |
| `source` | the package's parent holds `pyproject.toml` (a checkout, editable or not) |
| `zip` | Windows, no `xefm` distribution metadata (the bundle copies the source tree in) |
| `cask` / `dmg` | macOS, no metadata, inside `.app/Contents/`; `cask` when `Caskroom/xefm` exists under `/opt/homebrew` or `/usr/local` |
| `formula` | `/Cellar/xefm/` |
| `pipx` / `uv` | `/pipx/venvs/` / `/uv/tools/` |
| `pip` | any other installed distribution |

The kind picks the upgrade text and the bug form's `install` dropdown option.
Those option labels must equal `.github/ISSUE_TEMPLATE/bug_report.yml`'s word for
word (GitHub selects only on an exact match); a test reads the template.

`msix` drops Check for Updates from the menu: the Store updates that copy on
its own, and pointing a Store user at a download would only lead them off it.

## Check for Updates

A worker thread reads `https://pypi.org/pypi/xefm/json` (User-Agent
`XeFM/<version>`, nothing else identifying) and hands the result to the UI
thread with `_call_later`. PyPI is the one place every release lands first;
the Homebrew formula follows a day later, which the dialog says.

`latest_version` ranks `releases` keys with a small PEP 440 subset (`X.Y.Z`
and `aN`/`bN`/`rcN` - the only versions XeFM publishes), skipping releases that
are yanked or have no files. Pre-releases count only when the running version
is one. `info.version` is not used: it hides pre-releases, which an `rc` user
wants to see.

It runs only from the menu or the action. There is no startup check: PRIVACY.md
promises XeFM never looks on its own, and that page lists this request.

## Report an Issue

`issue_url` builds `issues/new?template=bug_report.yml&version=…&install=…&os=…`
plus `terminal=` in the TUI (`WT_SESSION`, else `TERM_PROGRAM` +
`TERM_PROGRAM_VERSION`, else `TERM`). The Python line from About rides in the
version field. Nothing is sent: the user reads the form before submitting it.
