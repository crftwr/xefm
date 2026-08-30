# XeFM Project Structure

## Overview

XeFM is organized so that the file-manager application,
its tests, and its documentation stay cleanly separated. The rendering/UI
toolkit is not vendored in this repo — XeFM depends on the external
[PuiKit](https://github.com/crftwr/puikit) framework.

## Directory Structure

```
xefm/
├── xefm/                   # The `xefm` package — everything the app ships
│   ├── app.py              # The application: XeFMApp + top-level UI (runs on PuiKit)
│   ├── __main__.py         # `python -m xefm` entry point
│   ├── tools/              # End-user external programs (shipped as package data)
│   └── *.py                # Business logic, imported as `xefm.<module>`
├── test/                   # Unit / integration tests (test_*.py), run with pytest
├── doc/                    # End-user docs (*_FEATURE.md, guides)
│   └── dev/                # Developer docs (*_IMPLEMENTATION.md, *_SYSTEM.md, plans)
├── tools/                  # Internal dev/build utilities (*.py, *.sh)
├── macos_app/              # macOS .app packaging (see MACOS_APP_BUILD_SYSTEM.md)
├── windows_app/            # Windows packaging (see WINDOWS_APP_BUILD_SYSTEM.md)
├── temp/                   # Throwaway work-in-progress files
├── pyproject.toml          # Packaging metadata (flat layout, `xefm` console script)
├── Makefile                # Build automation (run, test, venv, install-puikit, macos-app, ...)
├── requirements.txt        # Python dependencies
└── README.md               # Project overview and user guide
```

PuiKit itself lives in its **own repository** (`../puikit`) and is installed
editable into `.venv/` via `make install-puikit` (`PUIKIT_DIR ?= ../puikit`). It
is not part of this tree.

## Application (`xefm/`)

The application entry point and the top-level UI (the `XeFMApp` shell, the
dual `FilePane` layout, menus, and the main loop) live in **`xefm/app.py`**.
It imports PuiKit (`from puikit import ...`) and its sibling modules
(`from xefm.config import ...`). Those siblings, grouped by concern:

### Configuration & appearance
- **`xefm/config.py`** — configuration system and user settings
- **`xefm/const.py`** — application constants and key definitions
- **`xefm/_config.py`** — default user-config template (copied to `~/.xefm/config.py`)
- **`xefm/colors.py`** — color schemes and theme colors

### Path & storage system
- **`xefm/path.py`** — extended `Path` supporting local, S3, and SSH/SFTP paths
- **`xefm/s3.py`** — AWS S3 integration with pathlib compatibility
- **`xefm/ssh.py`**, **`xefm/ssh_connection.py`**, **`xefm/ssh_config.py`**, **`xefm/ssh_cache.py`** — SSH/SFTP backend and connection/config caching
- **`xefm/archive.py`** — archive creation/extraction and archive virtual directories

### Panes & file listing
- **`xefm/file_pane.py`** — a single file pane widget (PuiKit `Widget`)
- **`xefm/pane_manager.py`** — dual-pane management and navigation
- **`xefm/search_match.py`** — the incremental-search query language (tokens,
  wildcards, Migemo union) shared by the pane's isearch and the filter dialogs
- **`xefm/file_list_manager.py`** — directory listing, sorting, filtering

### File operations, tasks & progress
- **`xefm/file_operations.py`** — copy / move / delete / rename operations
- **`xefm/task.py`** — central `Task` / `TaskManager` and worker for threaded operations
- **`xefm/progress_manager.py`** — progress tracking for long operations
- **`xefm/progress_animator.py`** — configurable progress animation

### File monitoring
- **`xefm/file_monitor_manager.py`**, **`xefm/file_monitor_observer.py`** — watchdog-based auto-reload of directory listings

### Dialogs & bars
- **`xefm/input_dialog.py`** — single-line input (rename / mkdir / create)
- **`xefm/text_dialog.py`** — scrollable text / message dialogs
- **`xefm/filter_list_dialog.py`** — searchable list picker (favorites / drives / programs / jump)
- **`xefm/batch_rename_dialog.py`** — batch rename with regex
- **`xefm/progressive_search_dialog.py`** — filename / content search dialog
- **`xefm/isearch_bar.py`** — incremental-search bar
- **`xefm/compare_dialog.py`**, **`xefm/compare_selection.py`** — compare-and-select
- **`xefm/dialog_geometry.py`** — shared dialog sizing/anchoring helpers

### Viewers
- **`xefm/text_viewer.py`** — text viewer with pygments highlighting and isearch
- **`xefm/diff_viewer.py`** — file diff viewer
- **`xefm/directory_diff_viewer.py`** — directory diff viewer
- **`xefm/text_layout.py`** — text measurement / wrapping / layout helpers

### Logging
- **`xefm/log_manager.py`** — unified logger (`getLogger`) with in-app log pane
- **`xefm/logging_handlers.py`** — logging handlers (in-app log pane, remote)

### Backend, state & misc
- **`xefm/backend_detector.py`** — selects the PuiKit backend (terminal vs. native)
- **`xefm/state_manager.py`** — application state persistence and restoration
- **`xefm/str_format.py`** — string / size / date formatting helpers
- **`xefm/tools/`** — end-user-facing external programs (preview, diff wrappers, ...)

## Tests (`test/`)

Unit and integration tests, discovered by pytest as `test_*.py`. Run them with
`src` (and the repo root, for the few tests that `import xefm`) on the path;
PuiKit is resolved through its editable install:

```bash
python -m pytest test/                       # all
python -m pytest test/test_xefm_path.py -v    # one file
```

`make test` runs the suite; `make test-quick` runs a fast subset. Interactive
demos are **not** here — PuiKit ships its own demos in `../puikit/demo/`, which
should not be launched non-interactively (they block).

## Documentation (`doc/`)

- **`doc/*_FEATURE.md`** — end-user feature docs (usage, behavior)
- **`doc/dev/*_IMPLEMENTATION.md`, `*_SYSTEM.md`** — developer docs (design, internals)

## Entry Points

- **`python -m xefm`** / **`make run`** — launch the file manager
- **`xefm`** console script — created on `pip install` (see `setup.py`)

## Build System (Makefile targets)

- `make venv` / `make install-puikit` — create the venv and install PuiKit editable from `../puikit`
- `make run` / `make run-gui` — run XeFM (terminal / native)
- `make test` / `make test-quick` — run tests
- `make macos-app` / `make windows-app` — build platform packages
- `make clean` — every rebuildable artifact, by running `clean-python`,
  `clean-macos` and `clean-windows`. It keeps `.venv/` and
  `windows_app/.cache/`, since restoring those needs the network, and names both
  when it finishes — remove them with `make clean-venv` / `make clean-windows-cache`.
  The gitignored config files (`Makefile.local`, `*/signing.env`, `*/store.env`)
  are never cleaned by anything.

## Dependencies

### Runtime
- Python 3.9+ (3.13 supported)
- **PuiKit** (external, editable from `../puikit`)
- `pygments` (syntax highlighting), `boto3` (S3), `watchdog` (file monitoring)
- Platform extras via environment markers: `pyobjc` (macOS native backend), `windows-curses` (Windows)

### Development
- `pytest` (tests), plus optional `flake8` / `black`

## Configuration

- User config at `~/.xefm/config.py`, created from `xefm/_config.py`
- Defaults / constants / colors in `xefm/config.py`, `xefm/const.py`, `xefm/colors.py`
