# User Extensions Directory — Implementation

`~/.xefm/extensions/` is on `sys.path`, so `config.py` can import the user's own
modules. Motivated by [issue #459](https://github.com/crftwr/xefm/issues/459),
and modeled on Keyhac's `~/.keyhac/extensions/`.

User-facing documentation:
[`doc/CUSTOMIZATION_FEATURE.md`](../CUSTOMIZATION_FEATURE.md#your-own-modules-xefmextensions).

---

## Where

`ConfigManager.prepare_user_extensions()` in `xefm/config.py`, called from
`load_config()` right after `ensure_user_tools_dir()` and before the user's
config module executes. `reload_config()` goes through `load_config()`, so the
same step runs on every **Tools ▸ Reload Configuration**.

It does three things.

### 1. Create the directory

`mkdir(exist_ok=True)`, every load. An empty directory is the whole
discoverability story; failure is a warning, not an error — nothing depends on
the directory existing.

### 2. Append it to `sys.path`

*Appended*, not prepended. Extensions are named after what they do, and
`email.py` (an .eml handler) or `queue.py` are not far-fetched names; prepending
would let one shadow the standard library for the whole process, with a
traceback surfacing nowhere near this directory. The cost is the reverse: a
module named like a stdlib or installed package is unreachable, which the user
doc says plainly.

The comparison is on `os.path.realpath`, so a reload never adds a second entry.

Deliberately **not** on the path:

- `~/.xefm/` — its `config.py` would claim the module name `config`.
- `~/.xefm/tools/` — external programs run as subprocesses
  ([`EXTERNAL_PROGRAMS_FEATURE.md`](../EXTERNAL_PROGRAMS_FEATURE.md)), not
  in-process code.

A user who keeps extensions in a separate project directory appends it to
`sys.path` in `config.py` themselves; there is no config variable for it.

### 3. Evict what was imported from it

Every `sys.modules` entry whose `__file__` resolves under the directory is
deleted, so the `import` in the re-executed `config.py` reads the file again.
Without this, editing an extension and reloading silently runs the previous
version.

Each evicted module's `.pyc` (`importlib.util.cache_from_source`) is removed
too. A timestamp `.pyc` is validated against the source's mtime **in whole
seconds** plus its size, so an edit that lands in the same second and keeps the
file the same length would load the old bytecode through an otherwise correct
eviction — Keyhac hit exactly this (keyhac#41).
`test_config_imports_extension_and_reload_picks_up_edit` reproduces it: it
fails with the removal disabled. `importlib.invalidate_caches()` then drops the
finder's directory listing, so a newly added file is found.

Only modules that were actually loaded are touched, so a nested package's
`__pycache__` is handled per module rather than by walking the tree.

## What eviction does not do

Objects created from the old module — a `PATH_SCHEMES` class already
registered, an instance held by a pane — keep referring to the old module. The
reload path re-registers everything `config.py` names, so this matters only for
state an extension stashed somewhere outside that.

## Tests

`test/test_user_extensions_dir.py` — directory creation and append position,
no duplicate entry on reload, `~/.xefm` and `tools/` staying off the path, and
end-to-end reloads of a module and of a package submodule.
