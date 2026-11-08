# Extension Packages — Implementation

Issue #583, from discussion #543 (§§2–7 plus additions A–H). §8, the check on
core changes, became a check before each release (#697).

## Modules

- `xefm/extensions.py` — the manifest, the static check, the installed set,
  install/uninstall/sync, loading into a config, settings, and the
  `ExtensionHandle` that `user_api.extension(__name__)` returns.
- `xefm/extension_cli.py` — `xefm ext check|install|uninstall|list|enable|disable|sync|settings|try`.
  `xefm.app.main` dispatches `argv[1] == "ext"` here before the UI's argparse
  runs, so no backend is opened.
- `XeFMApp.install_extension` / `show_extensions` — the in-app install, with a
  summary-and-confirm box, and the load report.
- `xefm try --ext <dir>` runs XeFM with a package in a throwaway home: see
  [TRY_IMPLEMENTATION.md](TRY_IMPLEMENTATION.md).

## The static check (`check_manifest`)

The check never imports package code. A reference `pkg.mod:name` is resolved
like this:

1. Find `pkg/mod.py` or `pkg/mod/__init__.py` under the package root.
2. `ast.parse` it.
3. Look for a top-level binding of `name`. `_top_level_names` covers `def`,
   `class`, assignments and imports, and descends into top-level `if`/`try`
   blocks.

Each finding is a `Problem(severity, where, message)`. `where` is the manifest
field, with TOML-style quoting.

Unknown sections, keys and contribution kinds are errors, not warnings. The
point is that an assistant can correct its output from the message.

Machine-dependent checks are warnings, and only when `machine=True`:

- a program missing from `PATH`;
- a host package that cannot be imported.

Checks that involve other installed packages:

- a duplicate id;
- the same top-level module name in two packages (the vendoring collision in
  addition C, option 2);
- the same derived settings class name in two packages.

A top-level name in `sys.stdlib_module_names`, `xefm` or `puikit` is refused
outright.

Keys are validated against `xefm.config`'s `_MODIFIER_ALIASES`, `_NAMED_KEYS`
and `_PUNCT_NAMES`, the same tables `KeyBindings` parses with.

### The code lint (`lint_code`)

The check also lints every `.py` file in the package, skipping `_vendor/` and
dot-paths. It uses `ast.walk` over each file's syntax tree:

- **Error:** an `Attribute` whose name starts with `_` but not `__`, unless it
  is on `self` or `cls`. This is the `user_api` firewall.
- **Error:** an absolute import of an `xefm` module outside `PUBLIC_MODULES`
  (`xefm.user_api`, `xefm.path_base`). `from xefm import config` counts: each
  alias of a `from xefm import …` names a module.
- **Error:** a name taken from a public module that is not in its `__all__`
  (`public_names()` imports the module and reads it, so the list has one
  home) — by `from xefm.user_api import run_guarded`, or as an attribute
  through any name the file bound to the module (`import xefm.user_api as ua`
  → `ua.hooks`; `from xefm import user_api`; a bare `import xefm.user_api` →
  `xefm.user_api.Path`). The message lists the public names, so an assistant
  writing the package can correct itself without a search (#632). Before
  `__all__`, a public module was public whole, so `load_user_entries`,
  `run_guarded` or the re-exported `Path` were indistinguishable from
  `md_code_block` to anyone reading the code — the docs were the only line.
- **Warning:** a call to `print`.
- **Warning:** `sys.path`.

These findings use `where = "code:<rel path>:<line>"`, and `Problem.__str__`
prints them without the manifest prefix.

## The authoring skill and the scaffold

The user asked for an AI-agent skill whose instructions, followed as written,
satisfy every extension requirement. Three pieces make that hold.

- **The skill:** `xefm/skills/xefm/` — a short `SKILL.md` that routes, plus
  `references/extensions.md` (this system) and `references/config.md`
  (editing `~/.xefm/config.py`). It was `xefm-extension-authoring`, covering
  extensions only, until #639 widened and renamed it. It ships as package data
  (`pyproject.toml` takes `skills/*/*` and `skills/*/*/*`; `MANIFEST.in`). The
  macOS and Windows bundle scripts copy the whole `xefm/` tree, so the skill
  reaches every channel.

  **Distribution is client-neutral.** `release-github` attaches
  `xefm-X.Y.Z-skill.zip` (`skill_zip_name()`) to every GitHub Release
  (`make skill-zip` / `release-skill`). The name is versioned because the
  skill describes one release's config and API, so there is no fixed
  `releases/latest/download/...` URL: the install instructions have the agent
  resolve the latest tag (GitHub API or `gh`) when no `xefm` is on PATH.
  `write_skill_zip` puts the skill under one top-level folder, so unzipping it
  into any skills directory gives the right layout.

  **The skill states the XeFM it describes (#690).** The source `SKILL.md`
  carries `{XEFM_VERSION}` (`SKILL_VERSION_TOKEN`) in a
  `metadata.xefm-version` frontmatter key and in a *Which XeFM this
  describes* section placed before the ground rules; the generated
  references carry it in their "Generated from" line. `write_skill_zip` and
  `install_skill` (`xefm skill --install`) resolve it from `skill_version()`
  on the way out, so the tree never holds a version a bump could miss. The
  stamp is a PEP 440 local version (#855, the same form as Keyhac's skill
  bundle): a clean checkout at `vX.Y.Z` stamps `X.Y.Z`; off the tag,
  `X.Y.Z+dev.g<sha>`, since main keeps the last release's `__version__` until
  the bump and a skill made there must not pass for that release (the sha
  tells two dev builds apart); uncommitted changes add `.dirty`, at the tag
  too. A wheel or app bundle has no checkout, and a tree where git cannot be
  asked has no answer: both stamp the plain release. The git lookup is
  injectable (`skill_version(git=...)`), so the tests do not depend on the
  checkout's state.

  The zip is named after the same stamp: `write_skill_zip(<folder>)` writes
  `skill_zip_name(version)` there, and `make skill-zip` and the clean room
  (`qa/run.py`) both use it, so a dev build never overwrites the release zip
  in `dist/`. `skill_zip_name()`'s default stays the plain release name, the
  one the install doc resolves and `SKILL_ZIP` uploads. `release-skill`
  removes `$(SKILL_ZIP)`, rebuilds, and stops if it is missing, so a release
  from anywhere but a clean checkout at the tag fails instead of uploading a
  zip an earlier build left behind. The section tells the agent to compare major.minor with
  `xefm --version` and, on a mismatch, say so once and carry on. Patch
  releases do not change what the skill describes, so comparing the patch
  part would only make the agent nag. Without `xefm` on PATH there is no
  running version to compare, so the check is skipped (#639 dropped detection).

  `doc/AGENT_SKILL_FEATURE.md` (published on GitHub Pages) has a section
  written as instructions to an agent: pick the version, get the zip, verify,
  choose the directory (its own, preferring `~/.agents/skills/`; ask if
  unsure), replace, remove the old `xefm-extension-authoring/` (only when its
  frontmatter says so), report. `EXTENSION_AUTHORING_SKILL_FEATURE.md` stays
  as a pointer, since that URL was handed to agents before the rename.

  `xefm skill` prints the path, `--install DIR` copies the skill (`DIR` is
  required: no client's directory is assumed) and removes the legacy folder
  beside it, and `--zip FILE` writes the same zip offline. `xefm ext skill`
  is the same command, kept as an alias.
- **The scaffold:** `scaffold(id, parent)`, behind `xefm ext new`, writes a
  package with zero findings. It has a manifest, a thin `actions.py` over a
  plain `logic.py`, `settings.py`, `tests/`, and a `pytest.ini` with
  `pythonpath = .`. A root `conftest.py` would do the same job, but it would be
  a top-level module name shared by every package, and the collision check
  would refuse it.
- **The checker:** it enforces everything the skill states as a rule, and the
  skill's workflow ends at "`xefm ext check` is clean".

`test/test_extension_skill.py` keeps the three in step. It asserts that:

- the scaffold has no findings, and its generated test passes when run in a
  subprocess;
- the skill's example manifest passes, with each reference stubbed;
- the contribution kinds, events and public modules the skill lists equal the
  checker's;
- every `ctx.*`, `PaneApi` and `EntryInfo` name the skill cites exists;
- every `xefm ext` subcommand the skill uses exists.

If the API or the checker changes, these tests fail until the skill is updated.

## Loading

`ConfigManager.load_config` runs these steps in order:

1. Run `config.py`.
2. `_copy_missing_fields` from the template.
3. `_load_extensions()`, which calls `extensions.load(config, Layout(config_dir), namespace=vars(config_module))`.

The order means "config.py wins" compares against the user's own entries and
the template defaults alike. Reload goes through the same path.
`prepare_user_extensions` already purges modules under `~/.xefm/extensions/`
from `sys.modules`, so a package's edited code reloads too.

For each package directory (sorted; dot-directories skipped), `load` does:

1. Skip it if `extensions.toml` lists it as disabled. A directory that
   `extensions.toml` does not list is a *local* package and is loaded (the
   promotion path in G).
2. Run `check_manifest(machine=False)`. On errors, skip the package and report
   the first error, with a count and a pointer to `xefm ext check`.
3. Apply the backend, platform, `host_packages` and `python_packages` gates.
   The last one is `python_packages.synced_for`: the stamp of
   `~/.xefm/site-packages/X.Y` must record exactly this extension's list,
   for this platform. See `PYTHON_PACKAGES_IMPLEMENTATION.md`.
4. `_apply`:
   - Resolve every contribution first: `_import_ref` appends the package root
     to `sys.path` and imports.
   - Then fold the results into copies of the config's tables, skipping keys
     the config already has.
   - An exception during resolution skips the whole package, before any table
     is touched.
5. Apply key suggestions only when `KEY_BINDINGS` has no entry for the action
   (an empty list counts: the user unbound it on purpose) and every key is
   free. "Free" is judged by `_bound_keys`: every key in `KEY_BINDINGS`, plus
   the registry defaults of `FILER` actions the config does not mention.

A package with `requires.programs` has its actions and hooks wrapped by
`_in_extension`, which refuses to run them, with a warning naming the program,
while one is missing. The wrapped function keeps its docstring and signature
(`functools.wraps`), so `user_api._build_action` still takes the help text from
it and the call-shape check still reads the author's `def`.

**Which package is running** (#679). Each loaded package registers its
top-level module names (`python_top_level`) in `_handles_by_module`, rebuilt by
every `load()`, and `user_api.extension(__name__)` looks the caller up there
(`handle_for_module`). It replaced `ctx.extension`, which `_in_extension` set
on the one shared `ActionContext` for the duration of the call and then
cleared. A prompt answers after the action has returned, so its callback found
`None`, and so did a `run_task` worker, a sort key and anything else that runs
outside the call or never receives a `ctx`. Asking "what is running now" made
the answer depend on time; asking "whose module is this" does not. Hard-coding
the id in the call was considered and refused: it would duplicate the
manifest's `id`, and a rename or a fork would silently read another package's
state. The lint reports a leftover `ctx.extension` as an error that names the
replacement.

The result is a `LoadReport` with `loaded`, `skipped` (label and reason) and
`warnings`. `XeFMApp._report_extensions` logs it at startup and on every reload,
and also hands the app's state manager to `ExtensionHandle` for its `state`.

## Settings (addition A, revised)

The discussion sketched a `settings_base(id)` base class. The user chose plain
classes instead:

- A settings class in `config.py` is an ordinary top-level class, found by name
  in the executed module's namespace.
- The name is `config_class_name(manifest)`: `settings.config_class` if the
  manifest gives one, otherwise the id split on `-`, `.` and `_`, PascalCased,
  plus `Config`.

`_load_settings` builds an object for each loaded package that has
`settings.defaults`:

1. Copy the upper-case attributes of the defaults class, inherited ones
   included.
2. Overlay the user class's own upper-case attributes.
3. Skip, with a warning, any attribute the defaults class lacks. The warning
   lists the names that do exist.

It also warns about any class in the config module whose name ends in `Config`
(other than `Config`) and that no discovered package claims. Without that
warning, a misspelled class name would pass silently.

Because `config.py` never references the package, uninstalling one leaves a
harmless class behind. Nothing needs a stub.

`settings_template` prints a commented class with every default; it backs
`xefm ext settings <id>`.

## The installed set

`~/.xefm/extensions.toml` holds one `[extensions."<id>"]` table each, with
`version`, `source`, `directory` and `enabled`, plus `updates` when the
package declares one (copied at install, so `sync` and the update check have
it even with the package's folder gone). Python only reads TOML, so
`write_installed` writes this fixed shape itself, escaping strings, and replaces
the file atomically.

`install(source)`:

1. `fetch` the source:
   - A directory is used in place.
   - A zip is extracted with `_safe_extract`, which refuses members that
     resolve outside the target.
   - A `github:owner/repo[/path][@ref]` source or a github.com URL
     (`_github_parts`, `_fetch_github`). The optional path names a package in
     a subdirectory, so one repository can hold several
     (crftwr/xefm-extensions); a `.` or `..` component is refused.
     - With no `@ref`, the newest release tag is looked up the way
       `published_versions` does, taking the folder's name as the id for the
       tag prefix. No tags, or no answer from GitHub, leaves the default
       branch (`HEAD`), with a warning in the log.
     - At a ref, the release asset
       `releases/download/<ref>/<ref>.zip` is tried first. It holds the package
       alone. Any failure there (a 404 for a branch, or a tag with no
       release) falls back to the codeload zip of the whole repository at
       `ref`, and that one's error is the one reported.
   - Any other `https://` URL is fetched as is.
   - The manifest root is the extracted top, or its single child directory
     (GitHub zips wrap everything in `repo-ref/`) — followed by the path, when
     the source named one.
2. Check the package against the others already installed.
3. Copy it to `.<id>.installing` and swap it into place.

A directory with the same id that `extensions.toml` does not list is a local
package and is never overwritten. A reinstall keeps the entry's `enabled`
flag.

`xefm ext check` runs step 1 the same way (into a temporary directory) and
then `check_for_install`, which judges the package as step 2 does (#743).
"The others" are the packages of *other* ids, since an installed package of
the same id is the one an install replaces. A local package of the same id is
reported as an error, because install refuses it. A package that checks clean
therefore installs. `xefm ext install` without `--yes` fetches once: it shows
the summary of that copy and installs it through `install(fetched=…)`, as the
app's Install Extension does. Both commands print the summary through one
helper, `_print_summary`.

`uninstall` deletes `extension-data/<id>/` only when asked; the CLI asks
interactively. `sync` reinstalls every listed package whose directory is
missing. When the recorded source is a local file or folder that is gone and
the package has an `updates` source, `sync` installs the same version from
there (`release_source`).

All downloads go through `_open_url`, one function a test can replace.

## Newer versions (#676)

A package's versions are tags at its `updates` source: `v<version>` at a
repository's root, `<id>-v<version>` in a subdirectory (`tag_prefix`).

- `published_versions` reads the repository's tags from git's ref
  advertisement, `github.com/<owner>/<repo>.git/info/refs?service=git-upload-pack`
  — what `git ls-remote` reads (`_remote_tags`, `_parse_ref_advertisement`).
  It is not the REST API, so it has no hourly limit and takes no token; the
  REST API's 60 requests an hour without one was the reason to move off
  `git/matching-refs`. The answer holds every ref of the repository, a few KB
  for a repository of packages, so `check_updates` keeps it per repository
  (`tags=`) and packages that share one cost one request. A missing or private
  repository answers 401, asking for credentials, as well as 404; both read
  "no such public repository". Only dotted-number versions count. A tag such as `v0.3.0-beta` is a
  pre-release and is never offered.
- `check_updates` returns an `UpdateCheck` per installed package. It has
  `latest` when something newer exists and `problem` otherwise.
  - `failed` tells a source that gave no answer (offline, no such
    repository) from a package with no `updates`. The second is a
    fact about the package, so the CLI reports it but it does not make the
    exit status non-zero.
  - Local packages (made in `extensions/`, listed as `(local)`) are left out.
  - An entry written before `updates` was recorded falls back to the installed
    manifest (`_updates_of`).
- `upgrade` installs `updates@<tag>` through `install`, so the new version
  passes the same check, keeps the `enabled` flag, and replaces the old one
  only once it has passed. An `api_version` or `min_xefm` refusal is reworded
  as "cannot run on this XeFM". After an upgrade the recorded source is the
  tag, so `sync` reinstalls that exact version.
- `stranded` is the offline startup check, added to the load report's
  warnings. It lists packages installed from a local source that is gone and
  have no `updates`: nothing could reinstall them.

Nothing here runs unasked, because it reaches GitHub. The entry points are:

- `xefm ext outdated [id…]`: lists newer versions. Exit 1 when something is
  outdated or could not be checked, like `xefm deps status`.
- `xefm ext upgrade [id…] [--yes]`: lists the upgrades, asks, upgrades, then
  offers the Python-packages sync if a new version needs it.
- **Tools ▸ Advanced ▸ Check for Extension Updates…**
  (`check_extension_updates`):
  - The check runs on a worker thread, and the pump
    (`_pump_extension_updates`) shows the result in a message box.
  - **Upgrade** runs the upgrades on a worker, then reloads the config and
    starts the Python-packages sync when a new version lists
    `python_packages`.
  - The menu item is greyed out while either step runs.

Requests send `User-Agent: xefm/<version>`. None of them goes to the REST
API — the tag list, codeload zips and release assets are all outside it — so
none needs a token.

The issue's "what is newer, then what can run" order is not split further:
when the newest release needs a newer XeFM, `upgrade` refuses it. It does not
fall back to the newest release this XeFM can run, which would mean fetching
every candidate's manifest.

## Decisions on the discussion's open questions

1. **Native wheels XeFM doesn't ship:** out of scope for v1, then covered by
   `requires.python_packages`, which feeds the `requirements.txt` sync (#664).
   `host_packages` still covers what the build already has.
2. **Name:** "extension". Packages live in the existing `~/.xefm/extensions/`,
   as G proposes.
3. **Catalog:** none in v1. Install is from a source only.
4. **Pre-PR check:** a check before each release instead, not on every PR
   (#697).

Not done yet:

- Enter on an extension zip offering to install it. The explicit action exists
  instead.
- The Microsoft Store dynamic-code policy check (§5). It matters only once a
  catalog exists.
- Rewriting vendored imports (C, option 1). Only the collision refusal is done.

Set aside: the `xefm.testing` fixtures (F). The skill's own fake and
`xefm try --keys` cover extension testing for now. The compatibility check
against real extensions arrived with API_VERSION 1 (#713): `make api-compat`
(`tools/api_compat.py`) runs every package in xefm-extensions through the check
and its own tests against the working tree, and the release skill runs it
before tagging. A package's `requires.python_packages` go through the same
`python_packages.sync` a user's install does, into a directory that lasts for
the run, so the tests see them and the dev venv stays as it was.

Preview use is reported by `preview_uses()`, kept apart from `check_manifest`
so that install and loading — which gate on `check_manifest`'s errors — never
see a `preview` finding. Only the `xefm ext check` CLI asks for it, and
`--stable-only` (`stable_only()`) raises the findings to errors there.

## Tests

`test/test_extensions.py` covers:

- the check: precise fields, no import during the check, collisions,
  data-only packages;
- loading: config.py wins, all-or-nothing loading, gates, missing programs,
  `user_api.extension(__name__)` from any module of a package and after a
  reload;
- key suggestions;
- settings: derived and declared class names, overlay, typo warnings, an
  unclaimed `…Config` class, the template;
- install, uninstall and sync from a directory, a zip, and GitHub with a fake
  opener, plus refusal of a zip that escapes its folder;
- the CLI;
- `ConfigManager` integration;
- the in-app install.
