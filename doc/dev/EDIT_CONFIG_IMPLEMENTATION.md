# Edit & Reload Configuration — Implementation

Adds an in-app "edit config" / "reload config" workflow (GitHub issue #218).

## Actions

Two new keymap actions, registered unbound (`[]`) in `_config.py`'s
`KEY_BINDINGS` so users can bind them and they appear in the help reference:

- `edit_config`
- `reload_config`

They are dispatched in `XeFMApp.dispatch` (both `return False` — they render
themselves) and exposed as **Tools** menu items in `_build_menu`.

## `XeFMApp.edit_config()` — `xefm/app.py`

1. Resolves the config path from the shared `config_manager.config_file`
   singleton (`~/.xefm/config.py`).
2. If the file does not exist, creates it from the template via
   `config_manager.create_default_config()`; aborts (with a log message) if that
   fails.
3. Launches `TEXT_EDITOR` on the path through the existing
   `_run_in_terminal(...)` helper — the same `backend.suspended()` hand-off used
   by `edit_file` / `subshell`.
4. On return, reloads **only in terminal mode**. Gated on `is_desktop_mode()`
   (`xefm.backend_detector`): a terminal editor (e.g. `vim`) blocks until quit,
   so reloading on return is correct; a GUI editor (e.g. VS Code, the desktop
   `TEXT_EDITOR` default) opens in its own window and `subprocess.run` returns
   immediately — before anything is saved — so an auto-reload would run against
   the unedited file. In GUI mode we instead log a hint to use
   Tools ▸ Reload Configuration and render. `is_desktop_mode()` reads the
   `XEFM_BACKEND` env var published by `main()`, so it's reliable at runtime.

## `XeFMApp.reload_config()` — `xefm/app.py`

Best-effort live reload:

1. `config_manager.reload_config()` clears the singleton's cached config and
   `_key_bindings`, re-reads the file (filling missing fields from the
   template), and returns the new `Config`. A syntax error in the user file is
   caught inside `load_config` and degrades to template defaults.
2. `config_manager.validate_config(new_config)` — any errors are logged as
   `Config warning: …` but still applied (a reload should reflect disk).
3. `self.config` is repointed and `self.keys` is rebuilt from
   `new_config.KEY_BINDINGS` — this is what the event loop
   (`find_action_for_event`) consults, so rebindings go live.
4. The `.config` reference is re-pointed on every long-lived subsystem that
   holds one: `_fileops`, `flm`, `pm`, `file_monitor`, `left_view`,
   `right_view`. They read config attributes on demand, so future reads pick up
   the new values without a rebuild.
5. `self.panel.render()` so the log message and any menu/footer changes show.

### Why "best effort"

`self.config` is captured once in `__init__` and threaded into many subsystems.
Values consumed **on demand** (key bindings, file associations, programs,
favorites, editor) apply immediately once the reference is repointed. Values
consumed **once at construction** — theme/colors and post effects (`panel.theme`,
`_build_theme_list`), fonts, splitter fractions (`pane_splitter` /
`content_splitter`), and file-monitoring intervals — are not re-derived, so they
apply on next launch. The reload log line states this explicitly rather than
silently doing nothing.

Module-level helpers in `xefm/config.py` (`get_program_for_file`,
`get_favorite_directories`, `get_keys_for_action`, …) go through the
`config_manager` singleton, which `reload_config()` updates, so they need no
repointing.

## Tests

`test/test_xefm_app_config_reload.py` (memory backend, `subprocess.run` mocked):

- `edit_config` launches the editor on the config path; in terminal mode it
  reloads on return, in GUI mode (`is_desktop_mode` patched True) it does **not**
  reload and logs the manual-reload hint; creates the default when missing;
  aborts when creation fails.
- `reload_config` applies a rebound key and new `TEXT_EDITOR` live, repoints
  `.config` on all subsystems, and logs validation warnings while still
  applying out-of-range values.

The tests snapshot/restore the shared `config_manager` singleton and keep the
temp `config.py` **outside** the monitored pane directory — writing into the
watched dir during a test can deadlock the watchdog observer against its own
teardown.
