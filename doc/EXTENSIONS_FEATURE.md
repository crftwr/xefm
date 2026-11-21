# Extension Packages

English \| [日本語](EXTENSIONS_FEATURE.ja.md)

An extension package is a folder that adds actions, event hooks, themes, sort
orders, filters, picture formats, locations or syntax highlighting to XeFM.
These are the same kinds of things `config.py` can add, with no lines in
`config.py`. A package can be installed, shared, disabled and removed as one
unit.

Extensions run against the same API as `config.py` customization, version 1
(see [Customization](CUSTOMIZATION_FEATURE.md)). Most of it is stable; the parts
marked Preview may still change, and `xefm ext check` lists every Preview part
a package uses. In the manifest, `[contributes.actions]`, `sort_keys`,
`filters`, `path_schemes` and `key_suggestions` are stable; `menus`,
`event_hooks`, `image_decoders`, `lexers`, `themes`, `agent_prompts`,
`[settings]`, `[requires]`, `updates` and `agent_guide` are Preview.

## Finding extensions

The wiki's [Extensions](https://github.com/crftwr/xefm/wiki/Extensions) page
lists what is available, both the official packages and the ones written by
others.

The XeFM project keeps its own extensions in
[crftwr/xefm-extensions](https://github.com/crftwr/xefm-extensions). They are
written against the same public API as anyone else's, so they also serve as
examples to copy. Each has a README with its usage, and each release is a tag
such as `compute-hash-v0.1.0`. An install source without `@<tag>` installs the
newest release; add `@<tag>` to pin one.

## Installing and managing

From a shell — this works the same for pip/pipx/uv and Homebrew installs, the
macOS app and the Windows app:

```bash
xefm ext install ~/Downloads/hello-xefm.zip   # a .zip
xefm ext install ./hello-xefm                 # a folder
xefm ext install github:someone/hello-xefm    # a GitHub repository: its newest release, or @ref
xefm ext install github:crftwr/xefm-extensions/compute-hash   # one package of several in a repository
xefm ext install https://example.com/hello-xefm.zip

xefm ext list                 # what is installed, and whether it will load
xefm ext disable hello-xefm   # keep it, but don't load it
xefm ext enable hello-xefm
xefm ext uninstall hello-xefm # asks whether to delete its data too
xefm ext sync                 # reinstall anything listed but missing
xefm ext settings hello-xefm  # its settings class, ready to paste into config.py
xefm ext guide hello-xefm     # its guide for AI agents, if it has one

xefm ext outdated             # which packages have a newer version
xefm ext upgrade              # install the newer versions (asks first)
xefm ext upgrade compute-hash # just this one
```

Inside XeFM:

- To install, choose **Tools ▸ Advanced ▸ Install Extension…** and paste
  where the package is: anything `xefm ext install` takes, such as
  `github:crftwr/xefm-extensions/compute-hash`, an `https://` zip URL, or a
  path. With the cursor on a package folder or `.zip`, its path is already
  filled in, so Enter installs it. A relative path is taken from the active
  pane's folder.
- **Tools ▸ Advanced ▸ Extensions…** shows which packages loaded, and why any did not.
- **Tools ▸ Advanced ▸ Check for Extension Updates…** looks for newer versions
  and offers to upgrade them.

### Newer versions

A package says where its newer versions are published (its `updates` field;
see [Publishing](#publishing-and-where-newer-versions-come-from)). It does not
matter how you installed it: a package installed from a downloaded zip still
knows where to look. Compute Hash does this.

XeFM never looks on its own. Checking reaches GitHub, so it happens only when
you run `xefm ext outdated`, `xefm ext upgrade` or **Check for Extension
Updates…**. An upgrade goes through the same check as an install. A version
that needs a newer XeFM is refused and says so, and the version you have stays
installed. A package you disabled stays disabled.

A package that does not say where it is published cannot be checked; the
command says so. Checking needs no GitHub account or token, and packages
published in the same repository are checked together.

At startup XeFM warns, without going online, about a package nothing could
reinstall: one installed from a file that is now gone, with no `updates`.
It keeps working. Only `xefm ext sync`, on another machine or after
`extensions/` is lost, could not bring it back.

Before installing, XeFM checks the package and shows everything it adds,
including which code each item runs. Extensions run inside XeFM with your
permissions, and there is no sandbox. Install only packages you trust.

After installing, upgrading or enabling a package from a shell, reload the
configuration (**Tools ▸ Reload Configuration**) or restart XeFM. Inside XeFM
the configuration reloads by itself.

### Your config.py always wins

If a package and your `config.py` both define the same action, theme, filter,
location or other entry, your entry is used. The package's entry is skipped,
with a note in the log.

Packages only *suggest* keys. A suggested key is used only when you haven't
bound that action yourself and the key isn't already in use. Otherwise bind it
in `KEY_BINDINGS`. Any action is also reachable from the command palette.

### Settings

A package with settings reads them from a class in your `config.py`. Write it
the way `Config` is written: a plain class with no base class and no import.

```python
class CommandPaletteConfig:
    MAX_ITEMS = 30

class Config:
    ...
```

The class name comes from the package id in PascalCase plus `Config`, so
`command-palette` becomes `CommandPaletteConfig`. A package can choose a
different name. `xefm ext list` shows each package's class name.

`xefm ext settings <id>` prints a ready-to-paste class with every setting and
its default. Settings you leave out keep their defaults.

XeFM warns in the log in two cases:

- **A setting the package doesn't have**, such as a typo. The warning lists the
  settings that do exist.
- **A `…Config` class that no installed package claims**, such as a misspelled
  class name.

If you uninstall the package, its class stays in `config.py` unused, and the
config still loads.

### Where things live

| What | Where |
|---|---|
| Packages | `~/.xefm/extensions/<id>/`, beside your own modules |
| What is installed, from where, enabled or not | `~/.xefm/extensions.toml` |
| A package's own files | `~/.xefm/extension-data/<id>/` |
| A package's remembered state | XeFM's state database |

`extensions.toml` is the part worth keeping. Copy it to another machine and run
`xefm ext sync`, and the packages are fetched again. A reinstall never touches
`extension-data/`.

## Writing a package

The quickest start is the scaffold. It creates a package that already passes
the check, with one action, settings and a test:

```bash
xefm ext new hello-xefm
```

### With an AI assistant

XeFM provides a skill for AI agents, `xefm`, that walks through writing,
checking and installing a package (it also covers editing your `config.py`).
It covers the manifest, the API your code may use, settings, dependencies and
testing, and it has the agent run `xefm ext check` until the package is clean.
It works with any agent that reads [Agent Skills](https://agentskills.io).

You can let the agent install the skill itself. Give it the page
[The XeFM Skill for AI Agents](AGENT_SKILL_FEATURE.md)
(https://crftwr.github.io/xefm/doc/AGENT_SKILL_FEATURE.html)
and ask it to install the skill. You can also download
`xefm-X.Y.Z-skill.zip` from the releases page and unzip it into your
agent's skills folder yourself; that page explains both.

Then ask for the feature ("make an XeFM extension that…"). If the agent follows
the skill, the result meets the requirements below. `xefm ext check` verifies
every one of them, so a clean check confirms it.

### Publishing, and where newer versions come from

Push the package to GitHub; nothing has to be uploaded. `github:owner/repo@ref`
installs any tag, branch or commit, `github:owner/repo` alone installs the newest
release (or the default branch when there is none), and a version is a **tag**:

- a package at the repository's root: `v0.2.0`
- a package in a subdirectory — one of several in a repository, as in
  `github:crftwr/xefm-extensions/compute-hash` — the id first:
  `compute-hash-v0.2.0`

`updates` in `[extension]` says where newer versions are published, as
`github:owner/repo` or `github:owner/repo/path/to/package`, with no `@ref`. It
belongs to the package, not to how it was installed, so a copy installed from a
downloaded zip still knows where its next version is. Set it from the first
release: a version that lacks it cannot point its users to the next one.

A release can also carry the package as an asset named after its tag
(`compute-hash-v0.2.0.zip`, holding the package folder). XeFM downloads that
instead of the whole repository when it is there, and it gives anyone who
wants the package as a file something to download. Without it, XeFM downloads
the repository at that tag and keeps only the package.

To have it listed on the wiki's [Extensions](https://github.com/crftwr/xefm/wiki/Extensions)
page, post it in the
[Show and tell](https://github.com/crftwr/xefm/discussions/categories/show-and-tell)
discussion category with a link to the repository, a one-line description and
its install source.

### The layout

A package is a folder containing a manifest and, if it runs code, a Python
package:

```
hello-xefm/
  xefm-extension.toml
  hello_xefm/
    __init__.py
    actions.py
    settings.py
```

```toml
[extension]
id = "hello-xefm"
version = "0.1.0"
api_version = 1                       # the XeFM API it was written for
# optional:
name = "Hello"
description = "Says hello"
min_xefm = "1.8.0"
backends = ["desktop", "tui"]         # default: both
platforms = ["macos", "windows", "linux"]   # default: all
updates = "github:someone/hello-xefm" # where newer versions are published
agent_guide = "AGENT.md"              # how AI agents should use it (Preview)

[contributes.actions]
"hello.greet" = { entry = "hello_xefm.actions:greet", description = "Say hello" }

[contributes.key_suggestions]
"hello.greet" = ["Ctrl-Shift-G"]

[settings]
defaults = "hello_xefm.settings:Settings"
# config_class = "HelloConfig"        # default: derived from the id

[requires]
programs = ["ffmpeg"]                 # missing → its actions say so when run
host_packages = ["PIL"]               # must already be in this XeFM build
python_packages = ["PyYAML>=6"]       # installed from PyPI by the sync
```

```python
# hello_xefm/actions.py
from xefm.user_api import extension


def greet(ctx):
    """Say hello in the log."""
    me = extension(__name__)
    times = me.state.get("times", 0) + 1
    me.state.set("times", times)
    ctx.message(f"{me.settings.GREETING} (#{times})")
```

```python
# hello_xefm/settings.py
class Settings:
    GREETING = "Hello"
```

Code is only referenced, as `module:name`. XeFM imports it only when the
package loads, never when it is checked.

### What a package can contribute

Each `[contributes.<kind>]` table feeds the `config.py` table of the same name
— see [Customization](CUSTOMIZATION_FEATURE.md) for what each entry does.

| Kind | Feeds | Entry |
|---|---|---|
| `actions` | `ACTIONS` | `"mod:func"`, or `{ entry = "mod:func", description = "..." }` |
| `event_hooks` | `EVENT_HOOKS` | `"mod:func"`, or a list of them |
| `sort_keys` | `SORT_KEYS` | `"mod:name"` |
| `filters` | `FILTERS` | `"mod:name"`, or a table such as `{ globs = ["*.png"] }` |
| `image_decoders` | `IMAGE_DECODERS` | `"mod:name"` |
| `path_schemes` | `PATH_SCHEMES` | `"mod:Class"` |
| `lexers` | `LEXERS` | a Pygments alias, or `{ entry = "mod:LexerClass" }` |
| `themes` | `THEMES` | a table of colors, as in `config.py` |
| `menus` | `MENU_ITEMS` | `{ menus = ["file", "context"], label = "...", when = "entry" }`, for the package's own actions |
| `agent_prompts` | `AGENT_PROMPTS` | a request, `"Summarize these files."`, or `{ prompt = "...", agent = "Claude Code" }` |
| `key_suggestions` | `KEY_BINDINGS` | a list of keys, for the package's own actions |

A package with only themes, glob filters, lexer aliases, menus and key
suggestions runs no code at all.

Name actions `<something>.<name>`, such as `hello.greet`. A name without a dot
gets a warning, and a built-in action's name is refused. Give each action a
description, in the manifest or as its function's docstring: the command
palette shows it, and an AI agent learns the action from it (`xefmctl action
show`). An action with neither gets a warning.

### A guide for AI agents

An [AI agent](AI_AGENT_SESSIONS_FEATURE.md) working in XeFM finds your actions
with `xefmctl action list` and reads each one's description. What a single
description cannot say - when to use the package, how its actions go
together, how its settings change them, how to read what they produce - goes
in a Markdown file in the package, named by `agent_guide` (Preview):

```toml
[extension]
agent_guide = "AGENT.md"
```

An agent sees it with `xefmctl action show` on any of the package's actions,
and `xefm ext guide <id>` prints it. Write it for the agent: what to run, in
what order, and what not to do. Keep the README for people.

### What your code is given

`xefm.user_api.extension(__name__)` returns your package's handle:

- `id`, `version`
- `settings` — your defaults, overlaid with the user's settings class
- `state` — `get(key, default)`, `set(key, value)`, `delete(key)` and `keys()`;
  values are anything JSON can hold; safe from any thread
- `data_dir` — your folder under `~/.xefm/extension-data/`, created on first use

The package is found from the module's own name, so it works anywhere in your
code and at any time — in an action, in the callback of a prompt that answers
after the action has returned, in a background task, in a sort key. Outside a
loaded package (in `config.py`) it returns `None`.

(Earlier previews had `ctx.extension`, set only while an action ran, so a
prompt's callback found `None`. It is gone, and `xefm ext check` names the
replacement.)

### Checking a package

```bash
xefm ext check ./hello-xefm
xefm ext check ~/Downloads/hello-xefm.zip
xefm ext check github:crftwr/xefm-extensions/compute-hash
```

The check takes anything `xefm ext install` takes, so a package can be checked
straight from a download or a link, before it is installed. It first lists
what the package adds — the same list an install shows before it asks:

```
Hello 0.1.0 (hello-xefm) adds:
  action: hello.greet  (runs hello_xefm.actions:greet)
  installs Python package from PyPI: PyYAML>=6
```

The check validates the manifest without running any of the package's code.
Each problem it reports names the manifest field it concerns:

```
error: xefm-extension.toml: contributes.actions."hello.greet".entry: module hello_xefm.actions has no top-level 'greet'
```

The check also reads the package's Python files, again without running
them:

- **Error:** using a private name such as `ctx._app` (anything starting with
  `_` on an object other than `self`), or importing an XeFM module other than
  `xefm.user_api` and `xefm.path_base`. From those two, only the names in
  their `__all__` are public; anything else they contain is XeFM's own, and
  using it is an error too — the message lists the names you may use. Such
  code works today and breaks on any release.
- **Warning:** `print()`, which never reaches you (use `ctx.message`), and
  changing `sys.path`. Also any use of a deprecated API: it still works, the
  warning names what replaces it, and it is removed no earlier than the next
  minor XeFM release.

Files under a `_vendor/` folder are skipped.

Last, it lists every part of the API the package uses that is still Preview —
a manifest section, a name it imports, a `ctx` method:

```
preview: xefm-extension.toml: contributes.menus: Preview, may change in any release
preview: hello_xefm/actions.py:42: ctx.run_task — Preview, may change in any release
2 Preview API(s) in use; everything else this package uses is stable.
```

These are not problems — using Preview is fine, and a package with only these
lines installs and loads. They tell you which parts of your package may need
a change after an XeFM release. To keep a package on the stable part only,
check it with `--stable-only`, which reports them as errors:

```bash
xefm ext check --stable-only ./hello-xefm
```

The same shows at run time: the first time a package calls a Preview
function, XeFM writes one line to the log pane naming the package and the
function, and the startup line that lists your extensions names the Preview
manifest sections each one uses.

The exit status is 0 when the package would install. An install runs the same
check and installs nothing if it finds an error.

### Trying a package

```bash
xefm try --ext ./hello-xefm
```

This runs XeFM in the terminal with your package and nothing else, so you can
see its menus, dialogs and tasks before you install it. It runs in a
temporary home folder, so your own `~/.xefm`, its config and your other
extensions are never touched. Quit XeFM as usual and the temporary home is
deleted. An AI assistant uses the same command with a script of keys. See
[Trying XeFM in a Throwaway Home](TRY_FEATURE.md).

### Dependencies

- **Libraries from PyPI** (PyYAML, numpy, rawpy, compiled or not): list them
  in `python_packages` and import them normally. They are installed by the
  same sync as `~/.xefm/requirements.txt`
  ([Extra Python Libraries](PYTHON_PACKAGES_FEATURE.md)), into one shared
  directory, resolved together with every other extension's and your own.
- **Libraries XeFM already ships** (Pillow, for example): list them in
  `host_packages`.
- **Small pure-Python helpers:** you can also vendor them inside your own
  package (`hello_xefm/_vendor/`) and import them through it. A vendored
  library needs no sync and no network. Every loaded package shares one Python
  process, so a top-level module name may belong to only one package. Two
  packages providing `foo` are refused, and so is a name that would hide a
  standard-library module.
- **External programs:** list them in `programs`.

`python_packages` entries are plain requirements: a project name, optional
`[extras]`, version specifiers and a `;` marker. Pip options (`--index-url`),
URLs and paths are refused by the check, so no extension can redirect where
pip downloads from.

What the user sees:

- Installing shows each package under "installs Python package from PyPI".
  `xefm ext install` then asks to sync (with `-y` it just does). Install
  Extension in XeFM syncs right after installing.
- Until a sync has installed exactly the listed packages, the extension is not
  loaded, and the log says it needs Sync Python Packages.
- If two extensions (or an extension and XeFM itself) need versions that can't
  both be installed, the sync fails and the log names the extensions.
- Uninstalling or disabling an extension leaves its packages in place until
  the next sync, and `xefm ext` says a sync is due.

## Things to know

- Actions and hooks run on the UI thread, as they do in `config.py`. Running a
  slow external program from one freezes the window until it finishes.
- A package that fails the check or fails to import is skipped as a whole,
  with the reason in the log. It is never partly loaded.
- This version has no catalog. Packages are installed from a folder, a zip or a
  repository.
