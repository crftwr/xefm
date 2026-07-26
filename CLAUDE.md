# XeFM — Claude Code Instructions

XeFM is a dual-pane file manager. It is **not terminal-only**: the same widget code runs as a native desktop app on Windows and macOS *and* as a terminal (TUI) app on Windows, macOS and Linux, selected with `--backend`. That comes from its rendering/UI layer, **[PuiKit](https://github.com/crftwr/puikit)** — an external, capability-based framework whose backends (curses, macOS, Windows, web) each realize one widget model. PuiKit is **not vendored** here; it is installed editable from `../puikit` (see `make install-puikit`).

XeFM itself is a single Python package, `xefm/`, at the repo root (flat layout, matching PuiKit's own repo): `xefm/app.py` is the entry module holding the `XeFMApp` shell, and its siblings (`xefm/config.py`, `xefm/path.py`, …) hold the storage-agnostic business logic. Tests live in `test/`, docs in `doc/`.

---

## Terminal session rules

### Virtual environment

- A venv lives at `.venv/`. Assume it is active in ongoing sessions; only activate when starting fresh.
- If you do activate, run it as a separate command (not chained with `&&`):
  ```bash
  source .venv/bin/activate
  python script.py
  ```

### Import path

Run everything **from the repo root**. `python -m <mod>` puts the working directory on `sys.path`, so the root-level `xefm` package resolves with no install and no `PYTHONPATH`. PuiKit comes from its editable install in `.venv/`.

```bash
python -m pytest test/test_file.py -v     # `-m` puts the repo root on sys.path
```

Running a script **directly** puts the *script's* directory on the path instead, not the repo root, so those need `PYTHONPATH=.`:

```bash
PYTHONPATH=. python tools/some_script.py
```

### Git pager

Use `--no-pager` for any git command that may page output: `diff`, `log`, `show`, `branch`, `tag`, `blame`, `grep`. `status`/`add`/`commit`/`push`/`pull` don't need it.

### Don't run TUIs

- **Never execute `python -m xefm` (or `xefm/app.py`)** — it launches the interactive file manager (curses / native PuiKit backend) and blocks indefinitely. Read the source instead.
- Anything importing `curses`, PuiKit backends, or the `xefm` UI modules is blocking. PuiKit demos (`../puikit/demo/*.py`) block too.
- `test/test_*.py` are safe — run them with `pytest`, not `python` directly.
- If the user explicitly wants to see the app or a demo, tell them to run it manually rather than starting it yourself.
- Last-resort timeout wrapper: `python3 tools/timeout.py 5 python <script>`.

---

## Project file placement

| File type | Location | Naming |
|-----------|----------|--------|
| XeFM app entry | `xefm/` | `app.py` (plus `__main__.py` for `python -m xefm`) |
| XeFM source | `xefm/` | `*.py`, imported as `xefm.<module>` |
| XeFM tests | `test/` | `test_*.py` |
| Dev tools (internal) | `tools/` | `*.sh`, `*.py` |
| End-user external programs | `xefm/tools/` | `*.sh`, `*.py` |
| XeFM end-user docs | `doc/` | `FEATURE_NAME_FEATURE.md` |
| XeFM developer docs | `doc/dev/` | `SYSTEM_NAME_SYSTEM.md`, `FEATURE_NAME_IMPLEMENTATION.md` |
| Temporary files | `temp/` | `temp_*`, `TEMP_*` |

- `tools/` is for internal/dev utilities. `xefm/tools/` is for end-user-facing external programs (different audience).
- PuiKit is a separate project (`../puikit`, its own repo). Don't add UI-toolkit / backend / renderer code to XeFM — that belongs in PuiKit.
- Use `temp/` for any throwaway file produced during development.

### Documentation policy

- User-facing features → write **both** `doc/<NAME>_FEATURE.md` and `doc/dev/<NAME>_IMPLEMENTATION.md`.
- Internal-only changes → `doc/dev/` only.
- Don't put implementation details in end-user docs; don't put basic usage in developer docs.
- Only create docs when the user asks or the change clearly warrants it — don't generate docs for every edit.

---

## Coding standards

### Logging

**All XeFM source files MUST use the unified logger.** `print()` is prohibited in production code under `xefm/`.

```python
from xefm.log_manager import getLogger

# Class-based:
class MyComponent:
    def __init__(self):
        self.logger = getLogger("ComponentName")
    def foo(self):
        self.logger.info("...")

# Module-level:
logger = getLogger("ModuleName")
```

Logger names: PascalCase, descriptive, ≤15 chars (e.g. `Main`, `FileOp`, `Archive`, `Cache`, `UILayer`, `ExtProg`).

Levels:
- `error` — failures, exceptions, data loss
- `warning` — degraded behavior the user should know about
- `info` — normal operation, user actions (most common)
- `debug` — rarely used

Don't gate calls on `if self.logger:` — the logger is always present.

When migrating `print()` → logger, **preserve the exact message string**.

### Exceptions

- Prefer specific exception types over bare `except:`.
- When catching `Exception`, always log with context via `self.logger.error(...)`.

```python
try:
    risky()
except FileNotFoundError as e:
    self.logger.error(f"File not found: {e}")
except Exception as e:
    self.logger.error(f"Unexpected error: {e}")
```

### Imports

Before adding an import, check whether the module is already imported at the top of the file.

### File permissions

Python files should NOT be executable. Run them via `python3 script.py`, not `./script.py`. Shell scripts in `xefm/tools/` (end-user external programs) may be executable.

---

## Release notes

`make release-github` opens the Release with `--generate-notes`, which here lists
every merged PR — two dozen lines of "Cg optimization 20251214" that tell a user
nothing. Rewrite it once the Release exists:

```bash
gh release edit vX.Y.Z --notes-file notes.md
```

These are read by people who run a file manager, not by people reading the diff.
**At most three bullets**, one for each change a user would actually notice, one
to three sentences each: what changed for them, not how it was built. Name the
platform or backend when a change is specific to one (macOS, Windows, GUI, TUI).
Then fold everything else — smaller fixes, packaging, docs — into one short
"Also" paragraph, so nothing is dropped silently but nothing minor gets a
headline either. Close with the `**Full Changelog**` compare link.

The shape, sketched from work already on `main`:

```markdown
## XeFM 1.0.2

- **Directory listings no longer block the UI** — a directory is read in one pass
  on a worker thread and sorted from that same pass, instead of being scanned on
  the UI thread and re-read to sort.
- **Comparing two panes reuses what they already hold** — the compare no longer
  re-reads either side from disk.

Also: the conflict dialog's accent moved to the button Enter actually presses.

**Full Changelog**: https://github.com/crftwr/xefm/compare/v1.0.1...v1.0.2
```

The reasoning behind a change belongs in the commit body and in `doc/`, where it
is already written at length — notes that restate it are the failure mode to
avoid.

---

## References

- Logging system: `doc/dev/LOGGING_SYSTEM.md`
- Logging feature: `doc/LOGGING_FEATURE.md`
- Log manager: `xefm/log_manager.py`
