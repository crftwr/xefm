"""Extension packages — a manifest, a static check, an installed set (#583).

A hand-written module in ``~/.xefm/extensions/`` has always been importable
from ``config.py``, and the config then wired what it imported into its own
tables by hand. A *package* is the next step on that path: a directory in the
same place holding ``xefm-extension.toml`` beside its code. The manifest
declares what the package contributes to those same tables — ``ACTIONS``,
``EVENT_HOOKS``, ``THEMES`` and the rest — and names the code by reference
(``"hello_xefm.actions:greet"``), so XeFM does the wiring instead.

Declared, not executed, is the point. :func:`check_package` validates a
manifest without running any of the package's code: references are resolved
by reading the referenced module's syntax tree for a top-level binding of the
name, key suggestions are parsed the way ``KEY_BINDINGS`` entries are, and every
problem comes back as one :class:`Problem` naming the manifest field it is
about. That is the check ``xefm ext check`` runs, the one an install runs before
copying anything, and the one a load runs before importing anything — so an
assistant writing a package gets the same precise error the user would.

Precedence: **``config.py`` wins everything.** Where a package's contribution
and the user's own config name the same thing — an action, a scheme, a filter,
a theme — the package's entry is skipped with a warning. A package's keys are
only *suggestions*: one is applied only when the action has no binding of its
own and every key in it is free.

Three places on disk, all under ``~/.xefm/``:

- ``extensions/<dir>/`` — the packages themselves, next to the hand-written
  modules. Treated as a cache: they can be rebuilt from the installed set.
- ``extensions.toml`` — the installed set: which packages came from where, at
  which version, and whether they are enabled. A package directory the set does
  not list is a *local* package (one the user made by adding a manifest to their
  own code) and is enabled.
- ``extension-data/<id>/`` — a package's own files, out of reach of a
  reinstall.

Code-bearing contributions run against :data:`xefm.user_api.API_VERSION`
(1, the first with a stable part): a package declares the ``api_version`` it
was written for, and one asking for a newer version than this XeFM has is not
loaded, with the reason given. One written for an older version loads with a
warning. :func:`preview_uses` lists the Preview parts a package relies on.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

from xefm import __version__ as _XEFM_VERSION
from xefm.log_manager import getLogger
from xefm import python_packages as _python_packages

logger = getLogger("Extensions")

MANIFEST = "xefm-extension.toml"
#: The AI-agent skill for working with XeFM — config edits and extensions —
#: shipped inside the package so every install channel has it (``xefm skill``).
SKILL_DIR = Path(__file__).parent / "skills" / "xefm"
#: The skill's folder name before #639 widened it beyond extensions. An agent
#: installing the new one removes this one beside it.
LEGACY_SKILL_NAME = "xefm-extension-authoring"


def skill_zip_name(version: str = _XEFM_VERSION) -> str:
    """The release asset's name, ``xefm-X.Y.Z-skill.zip``. Versioned, because
    the skill describes one XeFM's config and API (#639); the install doc
    resolves the latest tag rather than relying on a fixed URL."""
    return f"xefm-{version}-skill.zip"


#: Where the source ``SKILL.md`` names the XeFM it describes. Resolved when the
#: skill leaves the source tree (the zip, ``xefm skill --install``), so the
#: tree itself carries no version that a bump could forget (#690).
SKILL_VERSION_TOKEN = "{XEFM_VERSION}"


def skill_version() -> str:
    """The version a skill made from this tree describes: ``__version__``, or
    ``X.Y.Z+dev`` from a git checkout that is not at the ``vX.Y.Z`` tag — main
    between releases still carries the last release's ``__version__``, and a
    skill made there must not pass for that release's. An install with no
    checkout (a wheel, the app bundle) is the release it says it is."""
    root = SKILL_DIR.parents[2]
    if not (root / ".git").exists():
        return _XEFM_VERSION
    import subprocess
    try:
        done = subprocess.run(["git", "-C", str(root), "describe", "--tags",
                               "--exact-match", "HEAD"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"Cannot tell whether the skill is a release build: {e}")
        return _XEFM_VERSION
    if done.stdout.strip() == f"v{_XEFM_VERSION}":
        return _XEFM_VERSION
    return f"{_XEFM_VERSION}+dev"


def _skill_files(version: str) -> Iterable[tuple[str, bytes]]:
    """``(path inside the skill folder, contents)`` for every skill file, with
    the version token resolved."""
    for file in sorted(SKILL_DIR.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts:
            data = file.read_bytes()
            if file.suffix == ".md":
                data = data.decode("utf-8").replace(
                    SKILL_VERSION_TOKEN, version).encode("utf-8")
            yield file.relative_to(SKILL_DIR).as_posix(), data


def write_skill_zip(path: Path) -> Path:
    """Zip the skill as one top-level folder, ``xefm/SKILL.md`` plus its
    ``references/``, so unzipping it into any agent's skills directory gives
    the layout every Agent Skills client expects."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in _skill_files(skill_version()):
            archive.writestr(f"{SKILL_DIR.name}/{name}", data)
    return path


def install_skill(skills_dir: Path) -> Path:
    """Copy the skill into ``skills_dir/xefm/``, replacing what is there, and
    return that folder."""
    target = Path(skills_dir) / SKILL_DIR.name
    if target.exists():
        shutil.rmtree(target)
    for name, data in _skill_files(skill_version()):
        file = target / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    return target


INSTALLED_SET = "extensions.toml"

#: Where packages may say they run. ``desktop`` is the native GUI, ``tui`` the
#: terminal (``web`` serves the TUI's widget model, so it counts as ``tui``).
BACKENDS = ("desktop", "tui")
PLATFORMS = ("macos", "windows", "linux")

#: ``[contributes.<kind>]`` → the ``Config`` table it feeds. ``key_suggestions``
#: is handled apart: it feeds ``KEY_BINDINGS``, but only where nothing else does.
CONTRIBUTION_TABLES = {
    "actions": "ACTIONS",
    "event_hooks": "EVENT_HOOKS",
    "sort_keys": "SORT_KEYS",
    "filters": "FILTERS",
    "image_decoders": "IMAGE_DECODERS",
    "path_schemes": "PATH_SCHEMES",
    "lexers": "LEXERS",
    "themes": "THEMES",
    "menus": "MENU_ITEMS",
    "attributes": "ATTRIBUTES",
    "layouts": "LAYOUTS",
    "layout_extras": "LAYOUT_EXTRAS",
}
#: Kinds whose entries may be plain data rather than a code reference — the
#: tier that runs no code at all.
_DATA_KINDS = {"themes", "filters", "lexers", "menus", "layouts", "layout_extras"}

_KNOWN_SECTIONS = {"extension", "contributes", "requires", "settings"}
_KNOWN_EXTENSION_KEYS = {"id", "version", "api_version", "min_xefm", "name",
                         "description", "backends", "platforms", "homepage",
                         "updates"}
#: The keys of an ``[contributes.actions]`` entry's table form, and of
#: ``[settings]``.
ACTION_ENTRY_KEYS = ("entry", "description")
SETTINGS_KEYS = ("defaults", "config_class")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REF_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


# --- problems -----------------------------------------------------------------

@dataclass(frozen=True)
class Problem:
    """One finding of :func:`check_package`. ``where`` is the manifest field it
    is about (``contributes.actions."hello.greet".entry``), so the fix is never
    a search."""
    severity: str          # "error" | "warning" | "preview"
    where: str
    message: str

    def __str__(self) -> str:
        if self.where.startswith(_CODE):
            return f"{self.severity}: {self.where[len(_CODE):]}: {self.message}"
        return f"{self.severity}: {MANIFEST}: {self.where}: {self.message}"


#: ``Problem.where`` prefix for a finding in the package's code rather than its
#: manifest; what follows is ``path/in/package.py:line``.
_CODE = "code:"


def _quote(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else f'"{key}"'


# --- the manifest -------------------------------------------------------------

@dataclass
class Manifest:
    """A parsed ``xefm-extension.toml``. Only :func:`read_manifest` builds one;
    every field is as declared, unchecked — :func:`check_manifest` judges."""
    root: Path
    data: dict

    @property
    def id(self) -> str:
        return str(self.data.get("extension", {}).get("id", ""))

    @property
    def version(self) -> str:
        return str(self.data.get("extension", {}).get("version", ""))

    @property
    def name(self) -> str:
        ext = self.data.get("extension", {})
        return str(ext.get("name") or ext.get("id") or self.root.name)

    @property
    def api_version(self) -> Any:
        return self.data.get("extension", {}).get("api_version")

    @property
    def updates(self) -> str:
        """``[extension] updates``: where newer versions are tagged, or ""."""
        value = self.data.get("extension", {}).get("updates")
        return value if isinstance(value, str) else ""

    @property
    def contributes(self) -> dict:
        value = self.data.get("contributes", {})
        return value if isinstance(value, dict) else {}

    @property
    def requires(self) -> dict:
        value = self.data.get("requires", {})
        return value if isinstance(value, dict) else {}

    def references(self) -> list[tuple[str, str]]:
        """Every ``module:name`` reference, as ``(where, reference)``."""
        out = []
        for kind, table in self.contributes.items():
            if kind == "key_suggestions" or not isinstance(table, dict):
                continue
            for key, value in table.items():
                where = f"contributes.{kind}.{_quote(key)}"
                for sub, ref in _refs_in(value):
                    out.append((where + sub, ref))
        settings = self.data.get("settings")
        if isinstance(settings, dict) and isinstance(settings.get("defaults"), str):
            out.append(("settings.defaults", settings["defaults"]))
        return out

    @property
    def runs_code(self) -> bool:
        """Whether anything here is a code reference — false for the data-only
        tier (themes, glob filters, lexer aliases, key suggestions)."""
        return bool(self.references())


def _refs_in(value) -> list[tuple[str, str]]:
    """The code references inside one contribution value: the value itself
    when it is a reference string, its ``entry`` when it is a table, each item
    when it is a list (an event's hooks). An attribute's ``read`` and a
    layout's ``format``, in its columns and their markers, are references
    too."""
    if isinstance(value, str):
        return [("", value)] if ":" in value else []
    if isinstance(value, dict):
        out = []
        for key in ("entry", "read", "format", "when"):
            ref = value.get(key)
            if isinstance(ref, str) and (key == "entry" or ":" in ref):
                out.append((f".{key}", ref))
        for key in ("columns", "markers"):
            items = value.get(key)
            if isinstance(items, list):
                out += [(f".{key}" + sub, ref) for sub, ref in _refs_in(items)
                        if sub]
        return out
    if isinstance(value, list):
        out = []
        for i, item in enumerate(value):
            out += [(f"[{i}]" + sub, ref) for sub, ref in _refs_in(item)]
        return out
    return []


class ManifestError(Exception):
    """No manifest, or one that is not TOML; carries the :class:`Problem`."""

    def __init__(self, problem: Problem):
        super().__init__(str(problem))
        self.problem = problem


def read_manifest(root: Path) -> Manifest:
    root = Path(root)
    path = root / MANIFEST
    if tomllib is None:
        raise ManifestError(Problem("error", "(file)",
                                    "reading a manifest needs Python 3.11 or later"))
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        # Windows reports a path through a file as missing, not as
        # NotADirectoryError, so the file has to be told apart here.
        if root.is_file():
            raise ManifestError(Problem("error", "(file)", f"{root} is not a directory")) from None
        raise ManifestError(Problem("error", "(file)", f"no {MANIFEST} in {root}")) from None
    except NotADirectoryError:
        raise ManifestError(Problem("error", "(file)", f"{root} is not a directory")) from None
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(Problem("error", "(file)", f"not valid TOML: {exc}")) from None
    return Manifest(root, data)


# --- the static check ---------------------------------------------------------

def _version_tuple(text: str) -> tuple[int, ...]:
    parts = []
    for piece in str(text).split("."):
        digits = re.match(r"\d+", piece)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts)


def _api_version() -> int:
    from xefm.user_api import API_VERSION
    return API_VERSION


def _module_file(root: Path, module: str) -> Optional[Path]:
    base = root.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _top_level_names(tree: ast.Module) -> set[str]:
    """Names a module binds at top level, read off its syntax tree."""
    names: set[str] = set()

    def targets(node):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                targets(elt)

    def visit(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    targets(target)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets(node.target)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.If, ast.Try)):
                visit(node.body)
                visit(getattr(node, "orelse", []))
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)
                visit(getattr(node, "finalbody", []))
    visit(tree.body)
    return names


#: How XeFM calls the code a contribution kind references, as
#: ``(positional argument count, the shape to name)``. A callback's arguments
#: never grow — a new fact arrives as an attribute of ``ctx`` or ``event`` — so
#: this is a contract, and checking it catches a hook still written for the
#: old per-event arguments.
_CALL_SHAPES = {
    "actions": (1, "fn(ctx)"),
    "event_hooks": (2, "fn(ctx, event)"),
}


def _check_reference(root: Path, ref: str, call: Optional[tuple[int, str]] = None
                     ) -> Optional[str]:
    """Why ``module:name`` does not resolve inside ``root``, or None — read
    from the module's source, never by importing it. With ``call``, a
    top-level ``def`` must also accept that many positional arguments."""
    if not _REF_RE.match(ref):
        return f"{ref!r} is not a reference — write it as 'package.module:name'"
    module, name = ref.split(":")
    path = _module_file(root, module)
    if path is None:
        return (f"module {module} is not in the package — expected "
                f"{module.replace('.', '/')}.py or {module.replace('.', '/')}/__init__.py")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return f"{path.relative_to(root)}:{exc.lineno}: syntax error: {exc.msg}"
    except (OSError, UnicodeDecodeError) as exc:
        return f"cannot read {path.relative_to(root)}: {exc}"
    if name not in _top_level_names(tree):
        return f"module {module} has no top-level '{name}'"
    if call is not None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == name and not _accepts(node.args, call[0]):
                return (f"{name} cannot be called as {call[1]} — XeFM passes "
                        f"exactly that, and anything more it has to say is an "
                        f"attribute of ctx or event")
    return None


def _accepts(args: ast.arguments, n: int) -> bool:
    """Whether a ``def`` with ``args`` can be called with ``n`` positional
    arguments and nothing else."""
    positional = len(args.posonlyargs) + len(args.args)
    required = positional - len(args.defaults)
    needs_keyword = any(d is None for d in args.kw_defaults)
    return required <= n and (n <= positional or args.vararg is not None) \
        and not needs_keyword


def _check_key(expr) -> Optional[str]:
    from xefm.config import key_problem
    return key_problem(expr)


def python_top_level(root: Path) -> set[str]:
    """The importable top-level names a package directory provides."""
    names = set()
    try:
        children = list(Path(root).iterdir())
    except OSError:
        return names
    for child in children:
        if child.name.startswith((".", "_")) and child.name != "__init__.py":
            continue
        if child.is_dir() and (child / "__init__.py").is_file():
            names.add(child.name)
        elif child.suffix == ".py" and child.is_file():
            names.add(child.stem)
    return names


def check_manifest(manifest: Manifest, *, others: Iterable[Manifest] = (),
                   machine: bool = True) -> list[Problem]:
    """Every problem with ``manifest``, without executing anything.

    ``others`` are the other packages installed beside it, for the checks that
    are about coexisting: the same id, and the same top-level module name —
    ``sys.modules`` is one per process, so two packages providing ``foo`` would
    otherwise collide silently, in load order. With ``machine`` the
    machine-dependent requirements (programs, host packages) are checked too,
    as warnings: a package is not wrong for needing ``ffmpeg``."""
    problems: list[Problem] = []
    err = lambda where, msg: problems.append(Problem("error", where, msg))  # noqa: E731
    warn = lambda where, msg: problems.append(Problem("warning", where, msg))  # noqa: E731
    data = manifest.data

    for section in data:
        if section not in _KNOWN_SECTIONS:
            err(section, f"unknown section — known: {', '.join(sorted(_KNOWN_SECTIONS))}")

    ext = data.get("extension")
    if not isinstance(ext, dict):
        err("extension", "missing — every manifest starts with an [extension] table")
        ext = {}
    for key in ext:
        if key not in _KNOWN_EXTENSION_KEYS:
            err(f"extension.{key}", "unknown key — known: "
                f"{', '.join(sorted(_KNOWN_EXTENSION_KEYS))}")
    updates = ext.get("updates")
    if updates is not None:
        parsed = parse_github_source(updates) if isinstance(updates, str) else None
        if parsed is None or parsed[3] is not None:
            err("extension.updates", "must be 'github:owner/repo', or "
                "'github:owner/repo/path/to/package' for a package in a "
                "subdirectory — with no @ref: newer versions are found from the "
                "repository's tags")
    ext_id = ext.get("id")
    if not isinstance(ext_id, str) or not _ID_RE.match(ext_id):
        err("extension.id", "required: lowercase letters, digits, '.', '_' or "
            "'-', starting with a letter or digit (e.g. 'hello-xefm')")
    version = ext.get("version")
    if not isinstance(version, str) or not _version_tuple(version):
        err("extension.version", "required: a version string such as '0.1.0'")
    api = ext.get("api_version")
    current = _api_version()
    if not isinstance(api, int) or isinstance(api, bool):
        err("extension.api_version", f"required: an integer — this XeFM's API "
            f"version is {current}")
    elif api > current:
        err("extension.api_version", f"asks for API version {api}; this XeFM "
            f"has {current}")
    elif api < current:
        warn("extension.api_version", f"written for API version {api}; this "
             f"XeFM has {current}")
    min_xefm = ext.get("min_xefm")
    if min_xefm is not None:
        if not isinstance(min_xefm, str) or not _version_tuple(min_xefm):
            err("extension.min_xefm", "must be a version string such as '1.8.0'")
        elif _version_tuple(min_xefm) > _version_tuple(_XEFM_VERSION):
            err("extension.min_xefm", f"needs XeFM {min_xefm}; this is {_XEFM_VERSION}")
    for key, allowed in (("backends", BACKENDS), ("platforms", PLATFORMS)):
        value = ext.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not value:
            err(f"extension.{key}", f"must be a non-empty list of {', '.join(allowed)}")
            continue
        for item in value:
            if item not in allowed:
                err(f"extension.{key}", f"{item!r} is not one of {', '.join(allowed)}")

    contributes = data.get("contributes", {})
    if not isinstance(contributes, dict):
        err("contributes", "must be a table")
        contributes = {}
    actions = contributes.get("actions", {})
    action_names = set(actions) if isinstance(actions, dict) else set()
    for kind, table in contributes.items():
        if kind != "key_suggestions" and kind not in CONTRIBUTION_TABLES:
            err(f"contributes.{kind}", "unknown contribution — known: "
                f"{', '.join(sorted(list(CONTRIBUTION_TABLES) + ['key_suggestions']))}")
            continue
        if not isinstance(table, dict):
            err(f"contributes.{kind}", "must be a table")
            continue
        for key, value in table.items():
            where = f"contributes.{kind}.{_quote(key)}"
            problem = _check_contribution(kind, key, value, action_names)
            if problem:
                err(where, problem)
    if action_names:
        from xefm import actions as _actions
        for name in sorted(action_names):
            where = f"contributes.actions.{_quote(name)}"
            builtin = _actions.registry.builtin(_actions.FILER, name)
            if builtin is not None:
                err(where, f"'{name}' is a built-in action — prefix it with the "
                    f"extension's own name, e.g. '{ext_id or 'myext'}.{name}'")
            elif "." not in name:
                warn(where, f"name it '<extension>.{name}' so it cannot collide "
                     "with another extension's or a future built-in action")

    for where, ref in manifest.references():
        kind = where.split(".")[1] if where.startswith("contributes.") else ""
        problem = _check_reference(manifest.root, ref, _CALL_SHAPES.get(kind))
        if problem:
            err(where, problem)

    settings = data.get("settings")
    if settings is not None:
        if not isinstance(settings, dict):
            err("settings", "must be a table")
        else:
            for key in set(settings) - set(SETTINGS_KEYS):
                err(f"settings.{key}", "unknown key — known: "
                    f"{', '.join(sorted(SETTINGS_KEYS))}")
            if not isinstance(settings.get("defaults"), str):
                err("settings.defaults", "required: the class holding the "
                    "defaults, as 'package.module:Settings'")
            name = settings.get("config_class")
            if name is not None and (not isinstance(name, str)
                                     or not name.isidentifier() or name == "Config"):
                err("settings.config_class", "must be a class name (not 'Config')")

    requires = data.get("requires", {})
    if not isinstance(requires, dict):
        err("requires", "must be a table")
        requires = {}
    for key in requires:
        if key not in REQUIRES_KEYS:
            err(f"requires.{key}", "unknown key — known: " + ", ".join(REQUIRES_KEYS))
    for key in REQUIRES_KEYS:
        value = requires.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            err(f"requires.{key}", "must be a list of strings")
        elif key == "python_packages":
            for line in value:
                reason = requirement_problem(line)
                if reason:
                    err("requires.python_packages", f"'{line}': {reason}")
    if machine:
        for program in requires.get("programs", []) or []:
            if isinstance(program, str) and shutil.which(program) is None:
                warn("requires.programs", f"'{program}' is not on PATH here — "
                     "the actions that need it will say so when run")
        for package in requires.get("host_packages", []) or []:
            if isinstance(package, str) and not _importable(package):
                warn("requires.host_packages", f"'{package}' is not importable "
                     "in this XeFM — the extension will not load here")

    problems.extend(lint_code(manifest.root))
    problems.extend(deprecated_uses(manifest))

    own = python_top_level(manifest.root)
    if manifest.runs_code and not own:
        err("(layout)", "the manifest references code, but the package has no "
            "Python package or module beside it")
    reserved = set(sys.stdlib_module_names) | {"xefm", "puikit"}
    for name in sorted(own & reserved):
        err("(layout)", f"top-level module '{name}' would shadow "
            f"{'the standard library' if name in sys.stdlib_module_names else name}"
            " — rename it")
    for other in others:
        if other.root == manifest.root:
            continue
        if ext_id and other.id == ext_id:
            err("extension.id", f"'{ext_id}' is already used by {other.root}")
        if settings is not None and other.data.get("settings") is not None \
                and ext_id and config_class_name(manifest) == config_class_name(other):
            err("settings.config_class", f"both this and '{other.id}' read their "
                f"settings from class {config_class_name(manifest)} — name one "
                "explicitly with settings.config_class")
        for name in sorted(own & python_top_level(other.root)):
            err("(layout)", f"top-level module '{name}' is also provided by "
                f"'{other.id or other.root.name}' — one process has one "
                f"'{name}'; rename it (e.g. vendor it under your own package)")
    return problems


#: The XeFM modules an extension may import: the customization API itself and
#: the published base classes for storage backends. Everything else in the
#: ``xefm`` package is internal and moves without notice — and within these
#: two, only the names in their ``__all__`` (:func:`public_names`).
PUBLIC_MODULES = ("xefm.user_api", "xefm.path_base")


def public_names(module: str) -> tuple[str, ...]:
    """The names an extension may take from ``module``, one of
    :data:`PUBLIC_MODULES`: its ``__all__``, read from the module itself so
    the list has one home."""
    return tuple(importlib.import_module(module).__all__)


def _public_modules_bound(tree: ast.AST) -> dict[str, str]:
    """Each local name a file binds to a public module — ``ua`` for
    ``import xefm.user_api as ua``, ``user_api`` for ``from xefm import
    user_api``, ``xefm.user_api`` itself for a bare ``import xefm.user_api`` —
    so an attribute read through it can be checked against the module's
    ``__all__``."""
    bound = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in PUBLIC_MODULES:
                    bound[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 \
                and node.module == "xefm":
            for alias in node.names:
                if f"xefm.{alias.name}" in PUBLIC_MODULES:
                    bound[alias.asname or alias.name] = f"xefm.{alias.name}"
    return bound


def _dotted(node: ast.AST) -> Optional[str]:
    """``a.b.c`` for a chain of names and attributes, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _not_public(module: str, name: str) -> str:
    return (f"'{name}' is not part of {module}'s public API — use only: "
            f"{', '.join(public_names(module))}")


def _package_trees(root: Path) -> Iterator[tuple[Path, ast.AST]]:
    """``(relative path, syntax tree)`` for each of the package's own Python
    files. Vendored code (any ``_vendor`` directory) is someone else's and is
    skipped, and so is a file that does not parse — the reference check
    reports an unreadable module the manifest points at."""
    root = Path(root)
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if "_vendor" in rel.parts or any(p.startswith(".") for p in rel.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        yield rel, tree


def lint_code(root: Path) -> list[Problem]:
    """What the authoring rules say about the package's own Python files, read
    from their syntax trees — never imported. Vendored code (any ``_vendor``
    directory) is someone else's and is not judged.

    Errors are the API contract: a private name (``ctx._app``) or an import of
    an internal ``xefm`` module works today and breaks on any release. Warnings
    are conventions with a reason: ``print()`` does not reach the user (use
    ``ctx.message``), and editing ``sys.path`` is how two extensions' vendored
    copies of one library end up colliding."""
    problems: list[Problem] = []
    for rel, tree in _package_trees(root):
        where = lambda node: f"{_CODE}{rel.as_posix()}:{node.lineno}"  # noqa: E731
        bound = _public_modules_bound(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and not node.attr.startswith("_"):
                module = bound.get(_dotted(node.value) or "")
                if module and node.attr not in public_names(module):
                    problems.append(Problem("error", where(node),
                                            _not_public(module, node.attr)))
                    continue
            if isinstance(node, ast.Attribute) and node.attr == "extension" \
                    and isinstance(node.value, ast.Name) and node.value.id == "ctx":
                problems.append(Problem(
                    "error", where(node),
                    "ctx.extension was removed — use "
                    "xefm.user_api.extension(__name__), which works anywhere "
                    "in the package: callbacks, workers, sort keys"))
                continue
            if isinstance(node, ast.ImportFrom) and node.level == 0 \
                    and node.module in PUBLIC_MODULES:
                for alias in node.names:
                    if alias.name != "*" and alias.name not in public_names(node.module):
                        problems.append(Problem("error", where(node),
                                                _not_public(node.module, alias.name)))
                continue
            if isinstance(node, ast.Attribute) and node.attr.startswith("_") \
                    and not node.attr.startswith("__") \
                    and not (isinstance(node.value, ast.Name)
                             and node.value.id in ("self", "cls")):
                problems.append(Problem(
                    "error", where(node),
                    f"'.{node.attr}' is private — use only the public API "
                    "(ctx.pane, ctx.invoke, ctx.run_program, ctx.message, …)"))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif node.level:
                    names = []
                elif node.module == "xefm":
                    # ``from xefm import user_api`` names a module per alias.
                    names = [f"xefm.{a.name}" for a in node.names]
                else:
                    names = [node.module or ""]
                for name in names:
                    if (name == "xefm" or name.startswith("xefm.")) \
                            and not any(name == m or name.startswith(m + ".")
                                        for m in PUBLIC_MODULES):
                        problems.append(Problem(
                            "error", where(node),
                            f"'{name}' is internal to XeFM — import only "
                            f"{' or '.join(PUBLIC_MODULES)}"))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "print":
                problems.append(Problem(
                    "warning", where(node),
                    "print() does not reach the user — use ctx.message(...), or "
                    "logging.getLogger(__name__) for diagnostics"))
            elif isinstance(node, ast.Attribute) and node.attr == "path" \
                    and isinstance(node.value, ast.Name) and node.value.id == "sys":
                problems.append(Problem(
                    "warning", where(node),
                    "do not touch sys.path — import vendored code as "
                    "yourpackage._vendor.name"))
    return problems


#: What a ``preview`` finding's message ends with.
_PREVIEW_NOTE = "Preview, may change in any release"

#: Says, for an API's qualified name, why a use of it is worth reporting — or
#: None when it is not.
Marked = Callable[[str], Optional[str]]


def _preview_note(name: str) -> Optional[str]:
    from xefm.preview import is_preview
    return _PREVIEW_NOTE if is_preview(name) else None


def _deprecated_note(name: str) -> Optional[str]:
    from xefm.preview import is_deprecated
    instead = is_deprecated(name)
    return (f"deprecated — {instead}; it will be removed in a later release"
            if instead is not None else None)


def _marked_members(cls_name: str, marked: Marked) -> dict[str, str]:
    """The public members of ``xefm.user_api.<cls_name>`` that ``marked``
    reports, with what it says about each."""
    import xefm.user_api as user_api
    cls = getattr(user_api, cls_name)
    found = {}
    for name in dir(cls):
        note = None if name.startswith("_") else marked(f"xefm.user_api.{cls_name}.{name}")
        if note:
            found[name] = note
    return found


def _marked_sections(manifest: Manifest, marked: Marked) -> list[tuple[str, str]]:
    """``(section, note)`` for the parts of the manifest the package uses that
    ``marked`` reports, each named the way a finding's ``where`` names it:
    ``contributes.menus``, ``settings``, ``extension.updates``."""
    data = manifest.data
    candidates = [(f"contributes.{kind}", f"manifest.contributes.{kind}")
                  for kind in data.get("contributes", {}) or {}]
    candidates += [(section, f"manifest.{section}") for section in ("settings", "requires")
                   if data.get(section) is not None]
    if "updates" in (data.get("extension") or {}):
        candidates.append(("extension.updates", "manifest.extension.updates"))
    return [(where, note) for where, name in candidates if (note := marked(name))]


def preview_sections(manifest: Manifest) -> list[str]:
    """The Preview parts of the manifest the package uses (see
    :func:`_marked_sections`)."""
    return [where for where, _note in _marked_sections(manifest, _preview_note)]


def _marked_uses(manifest: Manifest, marked: Marked) -> list[tuple[str, Optional[str], str]]:
    """``(where, what, note)`` for every use in the package of an API that
    ``marked`` reports. ``what`` is None for a manifest section, whose
    ``where`` already names it.

    Read from the manifest and the syntax trees, never by running anything:
    the sections it uses, the names it takes from the public modules, the
    ``ReadOnlyPathImpl`` members a backend defines, and the members it reads
    off ``ctx`` / ``ctx.pane`` — where ``ctx`` is a function's first parameter
    or a name ``ctx``, which is how every action, hook and ``on_done`` callback
    is written."""
    import xefm.path_base as path_base
    found: list[tuple[str, Optional[str], str]] = [
        (where, None, note) for where, note in _marked_sections(manifest, marked)]

    ctx_members = _marked_members("ActionContext", marked)
    pane_members = _marked_members("PaneApi", marked)
    backend_members = {}
    for name in path_base.TIERS["overridable"] + path_base.TIERS["helpers"]:
        note = marked(f"xefm.path_base.ReadOnlyPathImpl.{name}")
        if note:
            backend_members[name] = note
    for rel, tree in _package_trees(manifest.root):
        hits: dict[tuple[int, str], str] = {}

        def hit(node: ast.AST, what: str, note: str) -> None:
            hits.setdefault((node.lineno, what), note)

        bound = _public_modules_bound(tree)
        # Local names for what the public modules export: ``ReadOnlyPathImpl``
        # after ``from xefm.path_base import ReadOnlyPathImpl``.
        imported: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 \
                    and node.module in PUBLIC_MODULES:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    qualified = f"{node.module}.{alias.name}"
                    imported[alias.asname or alias.name] = qualified
                    if note := marked(qualified):
                        hit(node, f"{node.module.split('.')[-1]}.{alias.name}", note)
            elif isinstance(node, ast.Attribute) and not node.attr.startswith("_"):
                module = bound.get(_dotted(node.value) or "")
                if module and (note := marked(f"{module}.{node.attr}")):
                    hit(node, f"{module.split('.')[-1]}.{node.attr}", note)

        receivers = {"ctx"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) \
                    and node.args.args:
                receivers.add(node.args.args[0].arg)
        receivers -= {"self", "cls"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id in receivers and node.attr in ctx_members:
                hit(node, f"ctx.{node.attr}", ctx_members[node.attr])
            elif isinstance(node, ast.Attribute) and node.attr in pane_members \
                    and isinstance(node.value, ast.Attribute) \
                    and node.value.attr in ("pane", "other", "left", "right") \
                    and isinstance(node.value.value, ast.Name) \
                    and node.value.value.id in receivers:
                hit(node, f"ctx.{node.value.attr}.{node.attr}", pane_members[node.attr])
            elif isinstance(node, ast.ClassDef) and "xefm.path_base.ReadOnlyPathImpl" in {
                    _public_name(base, imported, bound) for base in node.bases}:
                for item in node.body:
                    for name in _defined_names(item):
                        if name in backend_members:
                            hit(item, f"ReadOnlyPathImpl.{name}", backend_members[name])
        for (lineno, what), note in sorted(hits.items()):
            found.append((f"{_CODE}{rel.as_posix()}:{lineno}", what, note))
    return found


def _findings(severity: str, uses) -> list[Problem]:
    return [Problem(severity, where, f"{what} — {note}" if what else note)
            for where, what, note in uses]


def preview_uses(manifest: Manifest) -> list[Problem]:
    """Every use of a Preview API in the package, as ``preview`` findings —
    not faults: a package with only these installs and loads. ``xefm ext
    check`` lists them so the author knows which parts may need updating after
    an XeFM release, and ``--stable-only`` makes them errors. What is Preview
    is read from :data:`xefm.user_api.PREVIEW_APIS`, so this never needs a list
    of its own."""
    return _findings("preview", _marked_uses(manifest, _preview_note))


def deprecated_uses(manifest: Manifest) -> list[Problem]:
    """Every use of a deprecated API in the package, as warnings that say what
    replaces it (:data:`xefm.user_api.DEPRECATED_APIS`). Part of
    :func:`check_manifest`: unlike a Preview use, this is something to fix."""
    return _findings("warning", _marked_uses(manifest, _deprecated_note))


def _public_name(expr: ast.AST, imported: dict[str, str],
                 bound: dict[str, str]) -> Optional[str]:
    """The qualified public name ``expr`` refers to — ``ReadOnlyPathImpl``
    imported by name, or ``pb.ReadOnlyPathImpl`` through a bound module — or
    None."""
    dotted = _dotted(expr) or ""
    if dotted in imported:
        return imported[dotted]
    head, _, attr = dotted.rpartition(".")
    return f"{bound[head]}.{attr}" if head in bound else None


def _defined_names(item: ast.AST) -> list[str]:
    """The names one statement in a class body defines: a method, or the
    plain targets of an assignment."""
    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [item.name]
    if isinstance(item, ast.Assign):
        return [t.id for t in item.targets if isinstance(t, ast.Name)]
    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
        return [item.target.id]
    return []


def stable_only(problems: Iterable[Problem]) -> list[Problem]:
    """``problems`` with every ``preview`` finding raised to an error — what
    ``xefm ext check --stable-only`` judges by."""
    return [Problem("error", p.where, p.message) if p.severity == "preview" else p
            for p in problems]


def _check_contribution(kind: str, key: str, value, action_names: set) -> Optional[str]:
    if not isinstance(key, str) or not key:
        return "names must be non-empty strings"
    if kind == "key_suggestions":
        if key not in action_names:
            return (f"suggests keys for '{key}', which this extension does not "
                    "contribute in [contributes.actions]")
        if not isinstance(value, list) or not value:
            return "must be a non-empty list of keys, e.g. [\"Ctrl-G\"]"
        for expr in value:
            problem = _check_key(expr)
            if problem:
                return problem
        return None
    if kind == "actions":
        if isinstance(value, str):
            return None if ":" in value else "must be 'module:function'"
        if isinstance(value, dict):
            extra = set(value) - set(ACTION_ENTRY_KEYS)
            if "entry" not in value:
                return "needs entry = 'module:function'"
            if extra:
                return (f"unknown keys {', '.join(sorted(extra))} — known: "
                        f"{', '.join(sorted(ACTION_ENTRY_KEYS))}")
            return None
        return "must be 'module:function' or { entry = ..., description = ... }"
    if kind == "menus":
        return _check_menu(key, value, action_names)
    if kind == "attributes":
        # Its own table — 'entry' here is the provider, beside the rest of the
        # attribute, not the "this table is a reference" shorthand.
        if isinstance(value, str):
            return None if ":" in value else "must be a table or 'module:name'"
        if not isinstance(value, dict):
            return "must be a table with read = 'module:function'"
        from xefm.user_api import TABLE_KEYS
        unknown = sorted(set(value) - set(TABLE_KEYS["ATTRIBUTES"]))
        if unknown:
            return (f"unknown keys {', '.join(unknown)} — known: "
                    f"{', '.join(TABLE_KEYS['ATTRIBUTES'])}")
        read = value.get("read")
        if not isinstance(read, str) or ":" not in read:
            return "needs read = 'module:function'"
        return None
    if kind == "event_hooks":
        from xefm.user_api import EVENTS
        if key not in EVENTS:
            return f"'{key}' is not an event — known: {', '.join(sorted(EVENTS))}"
        items = value if isinstance(value, list) else [value]
        if not items or not all(isinstance(v, str) and ":" in v for v in items):
            return "must be 'module:function' or a list of them"
        return None
    if isinstance(value, str) and ":" in value:
        return None
    if isinstance(value, dict) and "entry" in value:
        if set(value) != {"entry"}:
            return "a table with 'entry' holds nothing else"
        return None
    if kind in _DATA_KINDS:
        if kind == "lexers" and not isinstance(value, str):
            return "must be a Pygments lexer alias or { entry = 'module:LexerClass' }"
        if kind in ("themes", "filters") and not isinstance(value, dict):
            return "must be a table (or 'module:name')"
        return None
    return "must be 'module:name'"


def _check_menu(key: str, value, action_names: set) -> Optional[str]:
    """One ``[contributes.menus]`` entry: keyed by one of this package's own
    actions, a table of ``menus``, ``label`` and an optional ``when`` — the
    shape ``MENU_ITEMS`` takes in config.py."""
    from xefm.user_api import MENU_WHEN, MENUS
    if key not in action_names:
        return (f"puts '{key}' in a menu, but this extension does not "
                "contribute it in [contributes.actions]")
    if not isinstance(value, dict):
        return ('must be a table, e.g. { menus = ["file", "context"], '
                'label = "Compute Hash…" }')
    unknown = sorted(set(value) - {"menus", "label", "when"})
    if unknown:
        return f"unknown keys {', '.join(unknown)} — known: label, menus, when"
    menus = value.get("menus")
    if not isinstance(menus, list) or not menus or not all(m in MENUS for m in menus):
        return f"needs menus = a list of {', '.join(MENUS)}"
    label = value.get("label")
    if not isinstance(label, str) or not label.strip():
        return "needs label = the text the menu shows"
    when = value.get("when", "always")
    if when not in MENU_WHEN:
        return f"when must be one of {', '.join(MENU_WHEN)}"
    return None


#: The keys ``[requires]`` understands.
REQUIRES_KEYS = ("programs", "host_packages", "python_packages")

#: A PEP 508 requirement as an extension may write it: a project name, extras,
#: version specifiers and an environment marker. Nothing that would let one
#: package steer pip for every other one: no options (``--index-url``), no
#: direct references (``name @ https://…``), no paths.
_REQUIREMENT = re.compile(
    r"\s*[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\s*"   # name
    r"(?:\[\s*[A-Za-z0-9._,\s-]*\])?\s*"                   # [extras]
    r"(?:(?:===|==|!=|~=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+\s*"
    r"(?:,\s*(?:===|==|!=|~=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+\s*)*)?"  # specifiers
    r"(?:;[^@\n]*)?")                                          # ; marker


def requirement_problem(line: str) -> Optional[str]:
    """Why ``line`` is not accepted in ``requires.python_packages``, or None."""
    if not line.strip():
        return "empty"
    if _REQUIREMENT.fullmatch(line) is None:
        return ("not a plain requirement — write a project name with optional "
                "[extras], version specifiers and ; marker (no pip options, "
                "URLs or paths)")
    return None


def requirement_name(line: str) -> str:
    """The project name a requirement line names."""
    return re.match(r"\s*([A-Za-z0-9._-]+)", line).group(1)


def python_requirements(layout: Layout | None = None) -> dict[str, list[str]]:
    """``{extension id: [requirement, …]}`` for every enabled package whose
    manifest asks for Python packages — what ``xefm deps sync`` installs
    beside ``requirements.txt``. Lists with a line the check would refuse are
    left out: that package does not load anyway."""
    layout = layout or Layout()
    installed = read_installed(layout)
    out: dict[str, list[str]] = {}
    for manifest in discover(layout):
        if manifest.root.name.startswith("."):
            continue
        entry = installed.get(manifest.id)
        if entry is not None and not entry.enabled:
            continue
        wanted = manifest.requires.get("python_packages") or []
        if (wanted and isinstance(wanted, list)
                and all(isinstance(r, str) and not requirement_problem(r) for r in wanted)):
            out[manifest.id] = [r.strip() for r in wanted]
    return out


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_package(root: Path, *, others: Iterable[Manifest] = (),
                  machine: bool = True) -> tuple[Optional[Manifest], list[Problem]]:
    """Read and check the package at ``root``: ``(manifest, problems)``, the
    manifest None when it could not be read at all."""
    try:
        manifest = read_manifest(root)
    except ManifestError as exc:
        return None, [exc.problem]
    return manifest, check_manifest(manifest, others=others, machine=machine)


def check_for_install(root: Path, layout: Layout | None = None, *,
                      machine: bool = True) -> tuple[Optional[Manifest], list[Problem]]:
    """:func:`check_package` as :func:`install` judges it, so a package that
    passes installs (#743): an installed package of the same id is the one it
    would replace, not a clash — but a *local* one is, since install never
    overwrites it."""
    layout = layout or Layout()
    try:
        manifest = read_manifest(root)
    except ManifestError as exc:
        return None, [exc.problem]
    problems = check_manifest(manifest, others=_installed_others(manifest, layout),
                              machine=machine)
    target = layout.packages / manifest.id
    if manifest.id and target.exists() and target.resolve() != Path(root).resolve() \
            and manifest.id not in read_installed(layout):
        problems.append(Problem("error", "extension.id", _local_clash(target)))
    return manifest, problems


def _installed_others(manifest: Manifest, layout: Layout) -> list[Manifest]:
    """The packages beside the one being installed: every other id."""
    return [m for m in discover(layout) if m.id != manifest.id]


def _local_clash(target: Path) -> str:
    return f"{target} already exists and was not installed by XeFM — move it away first"


def errors(problems: Iterable[Problem]) -> list[Problem]:
    return [p for p in problems if p.severity == "error"]


# --- a new package ------------------------------------------------------------

def package_name_for(ext_id: str) -> str:
    """The Python package a new extension gets: the id with ``-`` and ``.``
    turned into ``_`` (``hello-xefm`` → ``hello_xefm``)."""
    name = re.sub(r"[-.]+", "_", ext_id)
    return name if name.isidentifier() else f"ext_{name}"


def scaffold(ext_id: str, parent: Path) -> Path:
    """Create ``parent/<ext_id>/`` holding a package that passes
    :func:`check_package` with no findings at all: a manifest with one action,
    the action over a plain-function module, settings defaults and a test. The
    starting point ``xefm ext new`` gives an author — or an assistant — so the
    rules are met before the first edit rather than discovered after it."""
    if not _ID_RE.match(ext_id):
        raise InstallError(f"'{ext_id}' is not a valid id: lowercase letters, "
                           "digits, '.', '_' or '-', starting with a letter or digit")
    root = Path(parent) / ext_id
    if root.exists():
        raise InstallError(f"{root} already exists")
    pkg = package_name_for(ext_id)
    short = ext_id.split("-")[0].split(".")[0]
    (root / pkg).mkdir(parents=True)
    (root / "tests").mkdir()
    (root / MANIFEST).write_text(f'''[extension]
id = "{ext_id}"
version = "0.1.0"
api_version = {_api_version()}
name = "{ext_id}"
description = "TODO: one line saying what this extension does"
min_xefm = "{_XEFM_VERSION}"

[contributes.actions]
"{short}.hello" = {{ entry = "{pkg}.actions:hello" }}

[settings]
defaults = "{pkg}.settings:Settings"
''', encoding="utf-8")
    (root / pkg / "__init__.py").write_text(f'''"""{ext_id} — an XeFM extension."""
''', encoding="utf-8")
    (root / pkg / "actions.py").write_text(f'''"""The actions {ext_id} contributes. Each takes the action context ``ctx``;
keep the work itself in plain functions (see logic.py) so it can be tested
without XeFM."""

from xefm.user_api import extension

from {pkg}.logic import greeting


def hello(ctx):
    """Say hello in the log pane.

    Shows the configured greeting with the name under the cursor."""
    entry = ctx.pane.focused
    ctx.message(greeting(extension(__name__).settings.GREETING,
                         entry.name if entry else None))
''', encoding="utf-8")
    (root / pkg / "logic.py").write_text('''"""Plain functions with no XeFM in them — what the tests exercise."""


def greeting(text, name):
    return f"{text}, {name}" if name else text
''', encoding="utf-8")
    (root / pkg / "settings.py").write_text(f'''"""Defaults for the settings a user may change in config.py with a plain
class named {config_class_name(Manifest(root, {"extension": {"id": ext_id}}))}."""


class Settings:
    GREETING = "Hello"
''', encoding="utf-8")
    # pythonpath = . puts the package root on the path for the tests; a
    # conftest.py would do it too, but at the root it would be a top-level
    # module every package shares a name with.
    (root / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    (root / "tests" / f"test_{pkg}.py").write_text(f'''from {pkg}.logic import greeting


def test_greeting():
    assert greeting("Hello", "a.txt") == "Hello, a.txt"
    assert greeting("Hello", None) == "Hello"
''', encoding="utf-8")
    return root


# --- where things live --------------------------------------------------------

def default_home() -> Path:
    return Path.home() / ".xefm"


@dataclass
class Layout:
    """The three places under ``~/.xefm`` (or a test's stand-in for it)."""
    home: Path = field(default_factory=default_home)

    @property
    def packages(self) -> Path:
        return self.home / "extensions"

    @property
    def installed_file(self) -> Path:
        return self.home / INSTALLED_SET

    def data_dir(self, ext_id: str) -> Path:
        return self.home / "extension-data" / ext_id


def discover(layout: Layout) -> list[Manifest]:
    """Every readable package in ``extensions/``, in directory-name order.
    Unreadable manifests are skipped here; :func:`load` reports them."""
    out = []
    try:
        children = sorted(layout.packages.iterdir())
    except OSError:
        return out
    for child in children:
        if child.is_dir() and (child / MANIFEST).is_file():
            try:
                out.append(read_manifest(child))
            except ManifestError:
                continue
    return out


# --- the installed set ----------------------------------------------------------

@dataclass
class InstalledEntry:
    id: str
    version: str = ""
    source: str = ""
    directory: str = ""
    enabled: bool = True
    #: The package's ``[extension] updates``, copied at install so the update
    #: check and ``sync`` have it even when the package's folder is gone.
    updates: str = ""


def read_installed(layout: Layout) -> dict[str, InstalledEntry]:
    path = layout.installed_file
    if tomllib is None or not path.is_file():
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning(f"Could not read {path}: {exc}")
        return {}
    out = {}
    for ext_id, entry in (data.get("extensions") or {}).items():
        if not isinstance(entry, dict):
            continue
        out[ext_id] = InstalledEntry(
            id=ext_id, version=str(entry.get("version", "")),
            source=str(entry.get("source", "")),
            directory=str(entry.get("directory", ext_id)),
            enabled=bool(entry.get("enabled", True)),
            updates=str(entry.get("updates", "")))
    return out


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = "".join(c if c >= " " else f"\\u{ord(c):04x}" for c in escaped)
    return f'"{escaped}"'


def write_installed(layout: Layout, entries: dict[str, InstalledEntry]) -> None:
    lines = ["# The installed extensions — written by XeFM (`xefm ext ...`).",
             "# The package directories are rebuilt from this list by",
             "# `xefm ext sync`, so it is the part worth keeping.", ""]
    for ext_id in sorted(entries):
        e = entries[ext_id]
        lines += [f"[extensions.{_toml_str(ext_id)}]",
                  f"version = {_toml_str(e.version)}",
                  f"source = {_toml_str(e.source)}",
                  f"directory = {_toml_str(e.directory)}",
                  f"enabled = {'true' if e.enabled else 'false'}"]
        if e.updates:
            lines.append(f"updates = {_toml_str(e.updates)}")
        lines.append("")
    layout.home.mkdir(parents=True, exist_ok=True)
    tmp = layout.installed_file.with_suffix(".toml.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, layout.installed_file)


# --- install / uninstall ----------------------------------------------------------

class InstallError(Exception):
    """An install refused; ``problems`` holds the check's findings, if any."""

    def __init__(self, message: str, problems: Iterable[Problem] = ()):
        super().__init__(message)
        self.problems = list(problems)


#: ``github:owner/repo[/path/to/package][@ref]``. The path names a package in
#: a subdirectory, so one repository can hold several (crftwr/xefm-extensions).
_GITHUB_SOURCE = re.compile(
    r"github:([\w.-]+)/([\w.-]+)((?:/[\w.-]+)*)(?:@([\w./-]+))?")


def parse_github_source(source: str) -> Optional[tuple[str, str, str, Optional[str]]]:
    """``(owner, repo, subdirectory, ref)`` for a ``github:`` source — the
    subdirectory ``""`` for a package at the top, the ref None when the source
    names none — or None for anything else."""
    m = _GITHUB_SOURCE.fullmatch(source)
    if not m or any(part in (".", "..") for part in m.group(3).split("/")):
        return None
    return m.group(1), m.group(2), m.group(3).strip("/"), m.group(4)


def _github_parts(source: str) -> Optional[tuple[str, str, str, Optional[str]]]:
    """``github:owner/repo[/path][@ref]`` or a github.com repository URL →
    ``(owner, repo, subdirectory, ref)``, or None for anything else."""
    parsed = parse_github_source(source)
    if parsed is not None:
        return parsed
    m = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?"
                     r"(?:tree/([\w./-]+))?", source)
    return (m.group(1), m.group(2), "", m.group(3)) if m else None


def _latest_release_tag(owner: str, repo: str, subdir: str,
                        opener: Callable[[str], bytes] | None) -> Optional[str]:
    """The newest release tag of the package in ``subdir`` — named by the
    folder, as the tag prefix names a package by its id — or None when it has
    none or GitHub cannot be asked, and the default branch is installed."""
    ext_id = subdir.rsplit("/", 1)[-1]
    updates = f"github:{owner}/{repo}" + (f"/{subdir}" if subdir else "")
    try:
        versions = published_versions(updates, ext_id, opener=opener)
    except InstallError as exc:
        logger.warning(f"Could not look up the releases of {updates}: {exc}")
        return None
    return f"{tag_prefix(updates, ext_id)}{versions[-1]}" if versions else None


def _download_zip(url: str, workdir: Path, opener: Callable[[str], bytes] | None) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        payload = (opener or _open_url)(url)
    except OSError as exc:
        raise InstallError(f"could not download {url}: {exc}") from None
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            _safe_extract(archive, workdir)
    except zipfile.BadZipFile:
        raise InstallError(f"{url} did not return a zip file") from None


def _fetch_github(owner: str, repo: str, subdir: str, ref: Optional[str],
                  workdir: Path, opener: Callable[[str], bytes] | None) -> Path:
    """A GitHub source at ``ref`` — the newest release when it names none.
    A tag's release asset ``<tag>.zip`` holds just the package, so it is
    preferred; without one, the zip of the whole repository at ``ref``."""
    if ref is None:
        ref = _latest_release_tag(owner, repo, subdir, opener)
    if ref is not None:
        asset = f"https://github.com/{owner}/{repo}/releases/download/{ref}/{ref}.zip"
        try:
            _download_zip(asset, workdir / "release", opener)
            return _find_package_root(workdir / "release")
        except InstallError:
            # No such release or asset (a 404 most of the time): the
            # repository's zip below says what is wrong, if anything is.
            pass
    _download_zip(f"https://codeload.github.com/{owner}/{repo}/zip/{ref or 'HEAD'}",
                  workdir / "repo", opener)
    return _find_package_root(workdir / "repo", subdir)


def _safe_extract(archive: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for info in archive.infolist():
        target = (dest / info.filename).resolve()
        if dest != target and dest not in target.parents:
            raise InstallError(f"the archive holds a path outside itself: {info.filename}")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _find_package_root(top: Path, subdir: str = "") -> Path:
    """The directory holding the manifest: ``top`` itself, or its only child
    directory (a GitHub zip wraps everything in ``repo-ref/``) — and in either,
    ``subdir`` when the source named one."""
    children = [c for c in top.iterdir() if not c.name.startswith(".")]
    wrapped = children[0] if len(children) == 1 and children[0].is_dir() else None
    for base in (top, wrapped):
        if base is not None and (base / subdir / MANIFEST).is_file():
            return base / subdir if subdir else base
    if subdir:
        raise InstallError(f"no {MANIFEST} in {subdir}/ of the repository")
    raise InstallError(f"no {MANIFEST} at the top of the package")


def _open_url(url: str) -> bytes:
    """Every download an install or an update check makes: one place, so a
    test can stand in for the network."""
    request = urllib.request.Request(url, headers={"User-Agent": f"xefm/{_XEFM_VERSION}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch(source: str, workdir: Path,
          opener: Callable[[str], bytes] | None = None) -> Path:
    """Put the package named by ``source`` — a directory, a ``.zip``, an
    ``https://`` URL of a zip, or ``github:owner/repo[/path][@ref]`` — under
    ``workdir`` and return the directory holding its manifest."""
    path = Path(source).expanduser()
    if path.is_dir():
        return _find_package_root(path)
    if path.is_file():
        try:
            with zipfile.ZipFile(path) as archive:
                _safe_extract(archive, workdir)
        except zipfile.BadZipFile:
            raise InstallError(f"{source} is not a zip file") from None
        return _find_package_root(workdir)
    github = _github_parts(source)
    if github is not None:
        return _fetch_github(*github, workdir, opener)
    if not source.startswith("https://"):
        raise InstallError(f"{source} is not a directory, a zip, an https:// URL "
                           "or github:owner/repo[/path]")
    _download_zip(source, workdir, opener)
    return _find_package_root(workdir)


def summarize(manifest: Manifest) -> list[str]:
    """What a package would add, one line per contribution — shown before an
    install, since extensions run in-process with no sandbox."""
    lines = []
    for kind, table in manifest.contributes.items():
        if not isinstance(table, dict):
            continue
        for key, value in table.items():
            if kind == "key_suggestions":
                lines.append(f"key suggestion: {key} → {', '.join(map(str, value))}")
            else:
                refs = [ref for _, ref in _refs_in(value)]
                code = f"  (runs {', '.join(refs)})" if refs else ""
                lines.append(f"{kind[:-1] if kind.endswith('s') else kind}: {key}{code}")
    for key in ("programs", "host_packages"):
        for item in manifest.requires.get(key, []) or []:
            lines.append(f"requires {key[:-1].replace('_', ' ')}: {item}")
    for item in manifest.requires.get("python_packages", []) or []:
        lines.append(f"installs Python package from PyPI: {item}")
    return lines


def install(source: str, layout: Layout | None = None, *,
            opener: Callable[[str], bytes] | None = None,
            fetched: Path | None = None) -> Manifest:
    """Check the package at ``source`` and copy it into ``extensions/``,
    recording it in the installed set. Nothing is copied when the check finds
    an error. Reinstalling an installed id replaces it (an upgrade); a *local*
    package of the same id — one the user made — is never overwritten.

    ``fetched`` is ``source`` already put on disk by :func:`fetch` — the app
    downloads once to show what a package adds, and installs that copy rather
    than downloading it again after the user agrees."""
    layout = layout or Layout()
    installed = read_installed(layout)
    with tempfile.TemporaryDirectory(prefix="xefm-ext-") as tmp:
        root = Path(fetched) if fetched is not None else fetch(source, Path(tmp), opener=opener)
        manifest = read_manifest(root)
        problems = check_manifest(manifest, others=_installed_others(manifest, layout))
        if errors(problems):
            raise InstallError(f"{manifest.id or source} did not pass the check",
                               problems)
        target = layout.packages / manifest.id
        if target.exists() and manifest.id not in installed:
            raise InstallError(_local_clash(target))
        layout.packages.mkdir(parents=True, exist_ok=True)
        staging = layout.packages / f".{manifest.id}.installing"
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(root, staging, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git"))
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    previous = installed.get(manifest.id)
    source_text = source if not Path(source).expanduser().exists() \
        else str(Path(source).expanduser().resolve())
    installed[manifest.id] = InstalledEntry(
        id=manifest.id, version=manifest.version, source=source_text,
        directory=manifest.id, enabled=previous.enabled if previous else True,
        updates=manifest.updates)
    write_installed(layout, installed)
    logger.info(f"Installed extension {manifest.id} {manifest.version} from {source}")
    return read_manifest(target)


def uninstall(ext_id: str, layout: Layout | None = None, *,
              delete_data: bool = False) -> None:
    """Remove an installed package and its entry. Its ``extension-data/``
    directory goes only with ``delete_data``. A settings class left in
    ``config.py`` stays harmless: nothing refers to it any more."""
    layout = layout or Layout()
    installed = read_installed(layout)
    entry = installed.pop(ext_id, None)
    if entry is None:
        raise InstallError(f"{ext_id} is not installed"
                           + (" (it is a local package: delete its directory)"
                              if (layout.packages / ext_id).exists() else ""))
    shutil.rmtree(layout.packages / entry.directory, ignore_errors=True)
    write_installed(layout, installed)
    if delete_data:
        shutil.rmtree(layout.data_dir(ext_id), ignore_errors=True)
    logger.info(f"Uninstalled extension {ext_id}")


def set_enabled(ext_id: str, enabled: bool, layout: Layout | None = None) -> None:
    layout = layout or Layout()
    installed = read_installed(layout)
    if ext_id not in installed:
        if any(m.id == ext_id for m in discover(layout)):
            installed[ext_id] = InstalledEntry(id=ext_id, source="(local)",
                                               directory=_dir_of(layout, ext_id))
        else:
            raise InstallError(f"{ext_id} is not installed")
    installed[ext_id].enabled = enabled
    write_installed(layout, installed)


def _dir_of(layout: Layout, ext_id: str) -> str:
    for m in discover(layout):
        if m.id == ext_id:
            return m.root.name
    return ext_id


def sync(layout: Layout | None = None, *,
         opener: Callable[[str], bytes] | None = None) -> list[str]:
    """Reinstall every listed package whose directory is missing — after a
    Python upgrade, or on another machine with the same ``extensions.toml``.
    Returns one line per package acted on."""
    layout = layout or Layout()
    report = []
    for ext_id, entry in read_installed(layout).items():
        if (layout.packages / entry.directory).is_dir() or entry.source in ("", "(local)"):
            continue
        source = entry.source
        if _local_source_gone(source) and entry.updates and entry.version:
            # The zip it came from is gone, but the package said where its
            # versions are tagged: the same version, from there.
            source = release_source(entry.updates, ext_id, entry.version)
        try:
            install(source, layout, opener=opener)
            report.append(f"{ext_id}: reinstalled from {source}")
        except (InstallError, ManifestError, OSError) as exc:
            report.append(f"{ext_id}: could not reinstall from {source}: {exc}")
    return report


# --- newer versions (#676) ------------------------------------------------------
#
# A package says where its versions are published with ``[extension] updates =
# "github:owner/repo[/path]"``, and a version is a tag there: ``v<version>`` for
# a package at the repository's root, ``<id>-v<version>`` for one in a
# subdirectory. Nothing is looked up unless asked: ``xefm ext outdated`` /
# ``upgrade`` and Check for Extension Updates are the only callers that reach
# the network, and the startup check (:func:`stranded`) never does.

#: A release version: dotted numbers only. A tag such as ``v0.3.0-beta`` is a
#: pre-release and is never offered as an upgrade.
_RELEASE_RE = re.compile(r"\d+(?:\.\d+)*")


def _local_source_gone(source: str) -> bool:
    """Whether ``source`` names a file or folder on this machine that is no
    longer there. A ``github:`` or ``https://`` source is not local."""
    if not source or source == "(local)" or source.startswith(("github:", "https://")):
        return False
    return not Path(source).expanduser().exists()


def _updates_of(layout: Layout, entry: InstalledEntry) -> str:
    """The entry's update source: recorded at install, or — for an entry
    written before XeFM recorded it — read from the installed manifest."""
    if entry.updates:
        return entry.updates
    try:
        return read_manifest(layout.packages / entry.directory).updates
    except ManifestError:
        return ""


def tag_prefix(updates: str, ext_id: str) -> str:
    """``v`` for a package at the top of its repository, ``<id>-v`` for one in
    a subdirectory."""
    parsed = parse_github_source(updates)
    return f"{ext_id}-v" if parsed and parsed[2] else "v"


def release_source(updates: str, ext_id: str, version: str) -> str:
    """The install source of one version: ``updates`` at that version's tag."""
    return f"{updates}@{tag_prefix(updates, ext_id)}{version}"


def _parse_ref_advertisement(data: bytes) -> list[str]:
    """The tag names in git's ref advertisement: pkt-lines, each a 4-digit hex
    length (counting itself) and ``<sha> <ref>``; ``0000`` is a flush, the
    first ref carries capabilities after a NUL, and ``^{}`` lines peel an
    annotated tag."""
    tags, i = [], 0
    while i + 4 <= len(data):
        size = int(data[i:i + 4], 16)
        line, i = data[i + 4:i + size], i + max(size, 4)
        _, _, ref = line.split(b"\0", 1)[0].rstrip(b"\n").partition(b" ")
        if ref.startswith(b"refs/tags/") and not ref.endswith(b"^{}"):
            tags.append(ref[len(b"refs/tags/"):].decode("utf-8", "replace"))
    return tags


def _remote_tags(owner: str, repo: str,
                 opener: Callable[[str], bytes] | None) -> list[str]:
    """Every tag of a GitHub repository, from the ref advertisement ``git
    ls-remote`` reads — git's own endpoint, not the API, so no hourly limit
    and no token."""
    url = f"https://github.com/{owner}/{repo}.git/info/refs?service=git-upload-pack"
    try:
        return _parse_ref_advertisement((opener or _open_url)(url))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 404):
            # GitHub asks for credentials rather than say a repository is
            # missing or private.
            raise InstallError(f"no such public repository: github.com/{owner}/{repo}") from None
        raise InstallError(f"could not read {url}: {exc}") from None
    except (OSError, ValueError) as exc:
        raise InstallError(f"could not read {url}: {exc}") from None


def published_versions(updates: str, ext_id: str, *,
                       opener: Callable[[str], bytes] | None = None,
                       tags: dict[tuple[str, str], list[str]] | None = None) -> list[str]:
    """Every release version tagged at ``updates``, oldest first: the tags
    whose names start with this package's prefix. ``tags`` keeps each
    repository's tags across calls, so packages that share a repository cost
    one request between them."""
    parsed = parse_github_source(updates)
    if parsed is None or parsed[3] is not None:
        raise InstallError(f"updates = {updates!r} is not github:owner/repo[/path]")
    owner, repo, _subdir, _ref = parsed
    key = (owner.lower(), repo.lower())
    if tags is None or key not in tags:
        names = _remote_tags(owner, repo, opener)
        if tags is not None:
            tags[key] = names
    else:
        names = tags[key]
    prefix = tag_prefix(updates, ext_id)
    versions = [name[len(prefix):] for name in names if name.startswith(prefix)]
    return sorted({v for v in versions if _RELEASE_RE.fullmatch(v)}, key=_version_tuple)


@dataclass
class UpdateCheck:
    """One installed package, looked up. ``latest`` is set when a newer
    release exists; ``problem`` says why the package could not be checked."""
    id: str
    version: str
    updates: str = ""
    latest: str = ""
    problem: str = ""

    @property
    def outdated(self) -> bool:
        return bool(self.latest)

    @property
    def failed(self) -> bool:
        """Its source was asked and gave no answer — unlike a package with no
        update source at all, which is a fact about the package, not a
        failure."""
        return bool(self.problem) and bool(self.updates)

    @property
    def source(self) -> str:
        """Where the newer version installs from."""
        return release_source(self.updates, self.id, self.latest) if self.latest else ""


def check_updates(layout: Layout | None = None, *, ids: Iterable[str] = (),
                  opener: Callable[[str], bytes] | None = None) -> list[UpdateCheck]:
    """Look up every installed package (or those in ``ids``) at its update
    source. Local packages — ones the user made in ``extensions/`` — have no
    published versions and are left out."""
    layout = layout or Layout()
    installed = read_installed(layout)
    wanted = list(ids)
    unknown = [i for i in wanted if i not in installed]
    if unknown:
        raise InstallError(f"not installed: {', '.join(unknown)}")
    results = []
    tags: dict[tuple[str, str], list[str]] = {}
    for ext_id in wanted or sorted(installed):
        entry = installed[ext_id]
        if entry.source == "(local)":
            continue
        check = UpdateCheck(ext_id, entry.version, updates=_updates_of(layout, entry))
        if not check.updates:
            check.problem = "it does not say where newer versions are published"
        else:
            try:
                versions = published_versions(check.updates, ext_id, opener=opener,
                                              tags=tags)
            except InstallError as exc:
                check.problem = str(exc)
                versions = []
            newer = [v for v in versions
                     if _version_tuple(v) > _version_tuple(entry.version)]
            if newer:
                check.latest = newer[-1]
            elif not versions and not check.problem:
                check.problem = (f"no {tag_prefix(check.updates, ext_id)}<version> "
                                 f"tags at {check.updates}")
        results.append(check)
    return results


def upgrade(check: UpdateCheck, layout: Layout | None = None, *,
            opener: Callable[[str], bytes] | None = None) -> Manifest:
    """Install the newer version :func:`check_updates` found, through the same
    check an install runs: a version this XeFM cannot run (``api_version``,
    ``min_xefm``) is refused with the reason, and the installed one stays."""
    if not check.outdated:
        raise InstallError(f"{check.id} {check.version} is the newest version")
    try:
        return install(check.source, layout, opener=opener)
    except InstallError as exc:
        reasons = [p.message for p in exc.problems
                   if p.where in ("extension.api_version", "extension.min_xefm")]
        if reasons:
            raise InstallError(f"{check.id} {check.latest} cannot run on this XeFM: "
                               f"{'; '.join(reasons)}", exc.problems) from None
        raise


def stranded(layout: Layout | None = None) -> list[str]:
    """Offline, for startup: installed packages that nothing could reinstall —
    installed from a file or folder that is gone, with no update source. They
    keep working; ``xefm ext sync`` (another machine, a lost ``extensions/``)
    could not bring them back."""
    layout = layout or Layout()
    out = []
    for ext_id, entry in sorted(read_installed(layout).items()):
        if _local_source_gone(entry.source) and not _updates_of(layout, entry):
            out.append(f"{ext_id} was installed from {entry.source}, which is gone, "
                       "and it does not say where newer versions are published: "
                       "`xefm ext sync` could not reinstall it")
    return out


# --- settings -----------------------------------------------------------------
#
# An extension's hand-written settings are a plain class in config.py, written
# the way ``class Config:`` is — no base class, no import:
#
#     class CommandPaletteConfig:
#         MAX_ITEMS = 30
#
# XeFM finds it by name after config.py has run. The name is derived from the
# id (:func:`config_class_name`) unless the manifest names one, and the
# package's own defaults class fills in whatever the user's class leaves out —
# the same merge ``_copy_missing_fields`` does for ``Config``. Nothing in
# config.py refers to the package, so uninstalling it leaves an unused class
# behind and never a config that fails to load.

#: ext id → that extension's merged settings, rebuilt on every config load.
_settings: dict[str, Any] = {}


def config_class_name(manifest: Manifest) -> str:
    """The ``config.py`` class holding ``manifest``'s settings: the manifest's
    ``settings.config_class`` when it names one, else the id in PascalCase plus
    ``Config`` — ``command-palette`` → ``CommandPaletteConfig``."""
    settings = manifest.data.get("settings")
    if isinstance(settings, dict) and isinstance(settings.get("config_class"), str):
        return settings["config_class"]
    words = [w for w in re.split(r"[-._]+", manifest.id) if w]
    return "".join(w[:1].upper() + w[1:] for w in words) + "Config"


def _defaults_ref(manifest: Manifest) -> Optional[str]:
    settings = manifest.data.get("settings")
    if isinstance(settings, dict) and isinstance(settings.get("defaults"), str):
        return settings["defaults"]
    return None


def _import_ref(root: Path, ref: str):
    module, name = ref.split(":")
    entry = str(root.resolve())
    if entry not in sys.path:
        sys.path.append(entry)
    return getattr(importlib.import_module(module), name)


def _settings_names(cls) -> dict[str, Any]:
    """A settings class's settings: its upper-case attributes, inherited ones
    included, so a defaults class may itself be built by inheritance."""
    return {n: getattr(cls, n) for n in dir(cls) if n.isupper()}


def _merge_settings(manifest: Manifest, defaults: type, user: Optional[type],
                    warnings: list[str]) -> Any:
    """The extension's defaults overlaid with what the user's class sets. A
    name the extension does not have is skipped with a warning naming the
    ones it does — a typo must not pass silently."""
    merged = type(f"{config_class_name(manifest)}Settings", (), {})()
    known = _settings_names(defaults)
    for name, value in known.items():
        setattr(merged, name, value)
    if user is not None:
        for name, value in vars(user).items():
            if not name.isupper():
                continue
            if name not in known:
                warnings.append(
                    f"{user.__name__}.{name}: '{manifest.id}' has no setting "
                    f"'{name}' — ignored (known: {', '.join(sorted(known)) or 'none'})")
                continue
            setattr(merged, name, value)
    return merged


def _load_settings(manifests: list[Manifest], loaded: list[Manifest],
                   namespace: dict, warnings: list[str]) -> None:
    """Build every loaded extension's settings from ``config.py``'s
    ``namespace``, and warn about a ``…Config`` class nothing claims — the
    one way a misspelt class name would otherwise go unnoticed."""
    _settings.clear()
    for manifest in loaded:
        ref = _defaults_ref(manifest)
        if ref is None:
            continue
        user = namespace.get(config_class_name(manifest))
        if user is not None and not isinstance(user, type):
            warnings.append(f"{config_class_name(manifest)} in config.py is not "
                            f"a class — '{manifest.id}' keeps its defaults")
            user = None
        try:
            defaults = _import_ref(manifest.root, ref)
        except Exception as exc:
            warnings.append(f"{manifest.id}: could not import its settings "
                            f"defaults {ref}: {exc}")
            continue
        _settings[manifest.id] = _merge_settings(manifest, defaults, user, warnings)

    claimed = {config_class_name(m) for m in manifests}
    module = namespace.get("__name__")
    for name, value in namespace.items():
        if (isinstance(value, type) and name.endswith("Config") and name != "Config"
                and name not in claimed
                and getattr(value, "__module__", module) == module):
            warnings.append(f"config.py class {name} matches no installed "
                            "extension's settings — check the name with "
                            "`xefm ext list`")


def settings_for(ext_id: str) -> Any:
    """``ext_id``'s settings as of the last config load — its defaults overlaid
    with the user's class — or None when it declares no settings."""
    return _settings.get(ext_id)


def settings_template(manifest: Manifest) -> str:
    """A class definition to paste into ``config.py``: every setting with its
    default, commented out. Imports the package's defaults class."""
    ref = _defaults_ref(manifest)
    if ref is None:
        return f"# {manifest.id} has no settings"
    defaults = _import_ref(manifest.root, ref)
    lines = [f"class {config_class_name(manifest)}:",
             f"    # Settings of {manifest.id} {manifest.version}; uncomment to change."]
    names = _settings_names(defaults)
    for name, value in names.items():
        lines.append(f"    # {name} = {value!r}")
    if not names:
        lines.append("    pass")
    return "\n".join(lines)


# --- what an extension's code is handed ---------------------------------------

class ExtensionState:
    """An extension's runtime state: a key–value view of ``state.db`` under
    ``ext:<id>:``. Values are anything JSON can hold. No SQL, no schema."""

    def __init__(self, state_manager, ext_id: str):
        self._sm = state_manager
        self._prefix = f"ext:{ext_id}:"

    def get(self, key: str, default: Any = None) -> Any:
        return self._sm.get_state(self._prefix + key, default) if self._sm else default

    def set(self, key: str, value: Any) -> None:
        if self._sm:
            self._sm.set_state(self._prefix + key, value)

    def delete(self, key: str) -> None:
        if self._sm:
            self._sm.delete_state(self._prefix + key)

    def keys(self) -> list[str]:
        if not self._sm:
            return []
        return [k[len(self._prefix):] for k in self._sm.get_all_states(self._prefix)]


class ExtensionHandle:
    """What ``xefm.user_api.extension(__name__)`` returns to a package's code:
    its own id, version, settings, state and data directory."""

    def __init__(self, manifest: Manifest, layout: Layout, state_manager=None):
        self.id = manifest.id
        self.version = manifest.version
        self._layout = layout
        self._sm = state_manager

    @property
    def settings(self) -> Any:
        return settings_for(self.id)

    @property
    def state(self) -> ExtensionState:
        return ExtensionState(self._sm or state_manager_for_handles, self.id)

    @property
    def data_dir(self) -> Path:
        path = self._layout.data_dir(self.id)
        path.mkdir(parents=True, exist_ok=True)
        return path


#: The state manager handles are given; the app sets it once it has one.
state_manager_for_handles = None

#: Top-level module name → the handle of the loaded package that provides it,
#: rebuilt by every :func:`load`. A package's code finds itself through its own
#: ``__name__`` (:func:`handle_for_module`), so knowing which extension is
#: running never depends on *when* the code runs — a prompt's callback, a
#: worker thread, a sort key all find the same answer (#679).
_handles_by_module: dict[str, ExtensionHandle] = {}


def handle_for_module(module: str) -> Optional[ExtensionHandle]:
    """The handle of the loaded package ``module`` (a ``__name__``) belongs
    to, or None — for ``config.py``'s own code, a hand-written module in
    ``~/.xefm/extensions/``, or a package that did not load."""
    return _handles_by_module.get(str(module).partition(".")[0])


def _in_extension(handle: ExtensionHandle, func: Callable, *,
                  missing: list[str] = ()) -> Callable:
    """``func``, refused with the install hint while a program it requires is
    missing."""
    if not missing:
        return func
    import functools

    @functools.wraps(func)
    def run(ctx, *args):
        absent = [p for p in missing if shutil.which(p) is None]
        if absent:
            logger.warning(f"{handle.id}: needs {', '.join(absent)} on PATH — "
                           "install it to use this")
            return None
        return func(ctx, *args)
    return run


# --- loading into a config ------------------------------------------------------

@dataclass
class LoadReport:
    loaded: list[Manifest] = field(default_factory=list)
    #: ``(id or directory, reason)`` for each package not loaded.
    skipped: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: ``(table, key) -> extension id`` for each entry an extension placed, so
    #: a later package that names the same key is told which one it lost to.
    owners: dict[tuple[str, str], str] = field(default_factory=dict)


def _current_backend() -> str:
    from xefm.backend_detector import is_desktop_mode
    return "desktop" if is_desktop_mode() else "tui"


def _current_platform() -> str:
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def _bound_keys(config) -> set:
    """Every key the config and the built-in defaults already use in the file
    list, parsed, so a suggestion can be tested for being free."""
    from xefm import actions as _actions
    from xefm.config import KeyBindings
    parser = KeyBindings({})
    bindings = getattr(config, "KEY_BINDINGS", None) or {}
    used = set()
    for name, binding in bindings.items():
        keys, _ = KeyBindings._binding_parts(binding)
        for key in keys:
            used.add(parser._parse_key_expression(key))
    for action in _actions.registry.actions(_actions.FILER):
        if action.name in bindings:
            continue
        for key in action.resolved_default_keys():
            used.add(parser._parse_key_expression(key))
    return used


def _value_for(kind: str, value, manifest: Manifest, handle: ExtensionHandle,
               missing: list[str]):
    """The ``Config`` table value a manifest entry stands for, importing what
    it references."""
    root = manifest.root
    if kind == "actions":
        if isinstance(value, str):
            value = {"entry": value}
        func = _in_extension(handle, _import_ref(root, value["entry"]), missing=missing)
        spec = {"func": func}
        if "description" in value:
            spec["description"] = value["description"]
        return spec
    if kind == "event_hooks":
        items = value if isinstance(value, list) else [value]
        return [_in_extension(handle, _import_ref(root, ref), missing=missing)
                for ref in items]
    if kind == "attributes" and isinstance(value, dict):
        spec = dict(value)
        if "read" in spec:
            spec["read"] = _in_extension(handle, _import_ref(root, spec["read"]),
                                         missing=missing)
        return spec
    if kind in ("layouts", "layout_extras") and isinstance(value, dict):
        spec = _layout_refs(value, root, handle, missing)
        if isinstance(spec.get("when"), str) and ":" in spec["when"]:
            spec["when"] = _in_extension(handle, _import_ref(root, spec["when"]),
                                         missing=missing)
        return spec
    if isinstance(value, dict) and "entry" in value:
        return _import_ref(root, value["entry"])
    if isinstance(value, str) and ":" in value and kind != "lexers":
        return _import_ref(root, value)
    if kind == "lexers" and isinstance(value, str) and _REF_RE.match(value):
        return _import_ref(root, value)
    return value


def _layout_refs(spec: dict, root, handle, missing: list) -> dict:
    """A ``[contributes.layouts]`` table with each ``format = 'module:function'``
    in its columns and markers imported — a built-in format is a plain name
    and has no colon."""
    def fmt(item):
        if isinstance(item, dict) and isinstance(item.get("format"), str) \
                and ":" in item["format"]:
            item = dict(item)
            item["format"] = _in_extension(handle, _import_ref(root, item["format"]),
                                           missing=missing)
        return item

    spec = dict(spec)
    columns = []
    for col in spec.get("columns") or ():
        col = fmt(col)
        if isinstance(col, dict) and col.get("markers"):
            col = dict(col)
            col["markers"] = [fmt(m) for m in col["markers"]]
        columns.append(col)
    if "columns" in spec:
        spec["columns"] = columns
    if "markers" in spec:
        spec["markers"] = [fmt(m) for m in spec["markers"] or ()]
    return spec


def load(config, layout: Layout | None = None, *,
         namespace: Optional[dict] = None) -> LoadReport:
    """Fold every enabled, passing package into ``config``'s tables, under the
    rule that ``config.py`` wins. Called by the config loader after
    ``config.py`` has run and the template has filled what it left out;
    ``namespace`` is that module's globals, where settings classes are found."""
    layout = layout or Layout()
    report = LoadReport()
    installed = read_installed(layout)
    _handles_by_module.clear()
    manifests = []
    try:
        children = sorted(layout.packages.iterdir())
    except OSError:
        children = []
    for child in children:
        if not child.is_dir() or not (child / MANIFEST).is_file() \
                or child.name.startswith("."):
            continue
        try:
            manifests.append(read_manifest(child))
        except ManifestError as exc:
            report.skipped.append((child.name, str(exc.problem)))

    backend, platform = _current_backend(), _current_platform()
    for manifest in manifests:
        label = manifest.id or manifest.root.name
        entry = installed.get(manifest.id)
        if entry is not None and not entry.enabled:
            report.skipped.append((label, "disabled"))
            continue
        problems = check_manifest(manifest, others=manifests, machine=False)
        bad = errors(problems)
        if bad:
            report.skipped.append((label, str(bad[0]) + (
                f" (and {len(bad) - 1} more — run `xefm ext check {manifest.root}`)"
                if len(bad) > 1 else "")))
            continue
        ext = manifest.data.get("extension", {})
        if backend not in ext.get("backends", BACKENDS):
            report.skipped.append((label, f"not made for the {backend} backend"))
            continue
        if platform not in ext.get("platforms", PLATFORMS):
            report.skipped.append((label, f"not made for {platform}"))
            continue
        absent_hosts = [p for p in manifest.requires.get("host_packages", [])
                        if not _importable(p)]
        if absent_hosts:
            report.skipped.append((label, "this XeFM build has no "
                                   + ", ".join(absent_hosts)))
            continue
        wanted = [r.strip() for r in manifest.requires.get("python_packages", []) or []]
        if wanted and not _python_packages.synced_for(
                _python_packages.Layout(layout.home), manifest.id, wanted):
            report.skipped.append((label, "its Python packages are not installed "
                                   "yet — run Sync Python Packages (Tools ▸ Advanced), "
                                   "or `xefm deps sync`"))
            continue
        try:
            _apply(config, manifest, layout, report)
        except Exception as exc:
            report.skipped.append((label, f"failed to load: {exc}"))
            logger.error(f"Extension {label} failed to load: {exc}")
            continue
        report.loaded.append(manifest)
    _load_settings(manifests, report.loaded, namespace or {}, report.warnings)
    report.warnings.extend(stranded(layout))
    return report


def _apply(config, manifest: Manifest, layout: Layout, report: LoadReport) -> None:
    """Fold one package in. Everything is resolved first and the config is
    touched only after, so a reference that fails to import leaves no half of
    the package behind."""
    handle = ExtensionHandle(manifest, layout, state_manager_for_handles)
    missing = list(manifest.requires.get("programs", []) or [])
    staged: dict[str, dict] = {}
    for kind, table in manifest.contributes.items():
        if kind == "key_suggestions":
            continue
        for key, value in table.items():
            staged.setdefault(CONTRIBUTION_TABLES[kind], {})[key] = \
                _value_for(kind, value, manifest, handle, missing)

    for attr, entries in staged.items():
        current = dict(getattr(config, attr, None) or {})
        for key, value in entries.items():
            if attr == "LAYOUT_EXTRAS" and isinstance(current.get(key), dict) \
                    and isinstance(value, dict) and (attr, key) not in report.owners:
                # config.py overrides an extension's extra key by key: it names
                # only what it changes (#756).
                current[key] = {**value, **current[key]}
                report.owners[(attr, key)] = manifest.id
                continue
            if key in current:
                owner = report.owners.get((attr, key))
                if owner is None:
                    winner = "config.py wins"
                    where = "config.py"
                else:
                    winner = f"{owner} loaded first and wins"
                    where = f"the extension {owner}"
                report.warnings.append(
                    f"{manifest.id}: {attr}['{key}'] is also in {where} — "
                    f"{winner}, the extension's entry is skipped")
                continue
            current[key] = value
            report.owners[(attr, key)] = manifest.id
        setattr(config, attr, current)

    suggestions = manifest.contributes.get("key_suggestions", {}) or {}
    if suggestions:
        from xefm.config import KeyBindings
        bindings = dict(getattr(config, "KEY_BINDINGS", None) or {})
        used = _bound_keys(config)
        parser = KeyBindings({})
        for action, keys in suggestions.items():
            if action in bindings:
                continue  # the user bound (or unbound) it: theirs
            parsed = [parser._parse_key_expression(k) for k in keys]
            taken = [k for k, p in zip(keys, parsed) if p in used]
            if taken:
                report.warnings.append(
                    f"{manifest.id}: suggested key {', '.join(taken)} for "
                    f"'{action}' is already in use — bind it in KEY_BINDINGS "
                    "to use it")
                continue
            bindings[action] = list(keys)
            used.update(parsed)
        config.KEY_BINDINGS = bindings
    for name in python_top_level(manifest.root):
        _handles_by_module[name] = handle
