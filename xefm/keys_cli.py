"""``xefm keys`` — the keys XeFM would use, read without starting it (#801).

A binding XeFM does not understand is never an error at run time: an unknown
key name is logged and that binding never fires, and so is an action name
nothing answers to. Pressing the key is the only other way to find out, and
that needs the app running. This loads ``config.py`` and the installed
extension packages the way XeFM does, lays the keymap preset over them, and
prints what a key does in each context, with every binding that cannot fire
named as an error. It writes nothing.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: The keymap preset chosen at the first launch or from View > Keymap, as
#: :class:`xefm.app.XeFMApp` stores it.
_PRESET_STATE = "keymap.preset"

#: The selection gates a ``KEY_BINDINGS`` entry may name.
_SELECTIONS = ("any", "required", "none")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xefm keys",
        description="Show what each key does in XeFM, read from your config.py, "
        "your extension packages and the keymap preset, without starting XeFM. "
        "Bindings XeFM cannot use (an unknown key name, an action that does not "
        "exist) are reported as errors, and the exit status is 1 when there is "
        "one.")
    parser.add_argument("names", nargs="*", metavar="KEY_OR_ACTION",
                        help="show only these keys ('F12', 'Ctrl-T', 'g g') or "
                        "actions ('reload_config')")
    parser.add_argument("--config", metavar="FILE",
                        help="read this config.py instead of ~/.xefm/config.py "
                        "(the extensions still come from ~/.xefm)")
    parser.add_argument("--keymap", metavar="PRESET",
                        help="use this preset instead of the one XeFM would use: "
                        "afx, orthodox, native or vim")
    parser.add_argument("--backend", choices=("tui", "gui"), default="tui",
                        help="the app the keys are for: the terminal (default) or "
                        "the desktop app (the OS native preset differs)")
    parser.add_argument("--context", metavar="NAME",
                        help="show one context only: filer, text_viewer, "
                        "image_viewer, file_diff, dir_diff, isearch, filter_list, "
                        "search")
    return parser


@dataclass
class Row:
    key: str
    action: str
    selection: str = "any"
    #: The actions listed before this one on the same key in its context. Most
    #: surfaces run the first that matches; some ask for one action by name
    #: (the picker's F1), so this is said, not judged.
    shares: list[str] = field(default_factory=list)
    #: Why this key never fires, when XeFM does not understand it.
    problem: str | None = None


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: ``{context: [Row, ...]}`` in the order a key is tried.
    contexts: dict[str, list[Row]] = field(default_factory=dict)


def _chosen_preset(config_dir: Path) -> str | None:
    """The preset stored in ``state.db``, read without creating or changing it."""
    db = config_dir / "state.db"
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?",
                               (_PRESET_STATE,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        value = json.loads(row[0])
    except ValueError:
        return None
    return value if isinstance(value, str) else None


def _no_action(name: str) -> str:
    from xefm.actions import CONTEXTS, registry
    known = sorted({a.name for c in CONTEXTS for a in registry.actions(c)})
    close = difflib.get_close_matches(name, known, n=1)
    return (f"no action is called {name!r}"
            + (f" — did you mean {close[0]!r}?" if close else ""))


def _binding_problems(name, value) -> list[str]:
    """Why a ``KEY_BINDINGS`` entry could never fire, entry by entry."""
    from xefm.config import key_problem
    from xefm.keymap_presets import _reach
    where = f"KEY_BINDINGS[{name!r}]"
    if not isinstance(name, str) or not name:
        return [f"{where}: an action name is a non-empty string"]
    problems = []
    if not _reach(name):
        problems.append(f"{where}: {_no_action(name)}")
    if isinstance(value, dict):
        keys = value.get("keys")
        selection = value.get("selection", "any")
        if selection not in _SELECTIONS:
            problems.append(f"{where}: selection is 'any', 'required' or 'none', "
                            f"not {selection!r}")
    else:
        keys = value
    if not isinstance(keys, (list, tuple)):
        problems.append(f"{where}: the keys are a list, like ['F12'] — or "
                        "{'keys': [...], 'selection': ...}")
        return problems
    for expr in keys:
        problem = key_problem(expr)
        if problem:
            problems.append(f"{where}: {problem}")
    return problems


def _context_rows(kb, context: str) -> list[Row]:
    """What each key does in ``context``, in the order XeFM tries them."""
    from xefm.actions import registry
    from xefm.config import key_problem
    exprs: dict[tuple, str] = {}
    for action in registry.actions(context):
        for expr in kb._context_binding(context, action.name)[0]:
            if isinstance(expr, str):
                exprs.setdefault((action.name, kb._parse_key_expression(expr)), expr)
    rows = []
    taken: dict[tuple, list[str]] = {}
    for parsed, action, selection in kb._context_entries(context):
        expr = exprs.get((action, parsed))
        if expr is None:
            continue
        rows.append(Row(expr, action, selection, shares=list(taken.get(parsed, [])),
                        problem=key_problem(expr)))
        taken.setdefault(parsed, []).append(action)
    return rows


def build(config_file: Path | None = None, keymap: str | None = None,
          backend: str = "tui") -> tuple[Report, dict]:
    """Load the config as XeFM would and report on its keys. Also returns what
    was read: ``config``, ``preset`` and how the preset was chosen
    (``preset_source``), and the loaded ``extensions``."""
    from xefm import keymap_presets
    from xefm.actions import COMMON, registry
    from xefm.config import (ConfigManager, KeyBindings, printable_text_bindings,
                             terminal_shadowed_bindings, deprecated_binding_names)
    from xefm.user_api import load_user_entries

    report = Report()
    manager = ConfigManager()
    if config_file is not None:
        manager.config_file = Path(config_file)
    config = manager.load_config(create=False)
    if manager.load_error is not None:
        report.errors.append(f"{manager.config_file} does not load — XeFM would "
                             f"start on the template instead: {manager.load_error}")
    elif not manager.config_file.is_file():
        report.warnings.append(f"no {manager.config_file}: XeFM's template is shown")
    for problem in manager.validate_config(config):
        report.warnings.append(problem)
    extensions = manager.extension_report
    if extensions is not None:
        for label, reason in extensions.skipped:
            report.warnings.append(f"extension {label} is not loaded: {reason}")
        report.warnings.extend(extensions.warnings)
    # The user's actions and the extensions' are registered first: a binding
    # to one is reached only where it is (#662).
    load_user_entries(config)

    own = keymap_presets.overrides(config)
    for name, value in own.items():
        report.errors.extend(_binding_problems(name, value))
    for old, current in deprecated_binding_names(own):
        report.warnings.append(f"KEY_BINDINGS[{old!r}]: an old name — "
                               f"now {current!r}; it still works")
    for action, key in printable_text_bindings(own):
        report.errors.append(f"KEY_BINDINGS[{action!r}]: {key!r} types a "
                             "character on that surface, so it never fires")
    if backend == "tui" and sys.platform != "win32":
        for action, key in terminal_shadowed_bindings(own):
            report.warnings.append(f"KEY_BINDINGS[{action!r}]: {key!r} arrives as "
                                   "Tab, Enter or Backspace in most terminals")

    if keymap is not None:
        preset, source = keymap_presets.canonical(keymap), "--keymap"
    elif keymap_presets.resolve(config, None):
        preset, source = keymap_presets.resolve(config, None), "KEY_PRESET in config.py"
    else:
        preset = keymap_presets.resolve(config, _chosen_preset(manager.config_dir))
        source = "chosen in XeFM"
        if preset is None:
            preset, source = keymap_presets.FALLBACK, (
                "none chosen yet — XeFM asks at its next launch")
    keymap_presets.apply(config, preset)
    bindings = KeyBindings(config.KEY_BINDINGS)
    for context in registry.contexts():
        if context == COMMON:
            continue  # inherited by every other context, and listed there
        report.contexts[context] = _context_rows(bindings, context)
    return report, {"config": manager.config_file, "preset": preset,
                    "preset_source": source,
                    "extensions": list(extensions.loaded) if extensions else []}


def _matcher(names: list[str]):
    """A row filter for the names given — each an action or a key — or an
    error message for a name that is neither."""
    from xefm.actions import registry
    from xefm.config import KeyBindings, key_problem
    if not names:
        return (lambda context, row: True), None
    parse = KeyBindings({})._parse_key_expression
    actions, keys = set(), set()
    for name in names:
        current = {registry.canonical(c, name) for c in registry.contexts()} - {None}
        if current:
            actions |= current
        elif key_problem(name) is None:
            keys.add(parse(name))
        elif name.isidentifier() and name.islower() and len(name) > 1:
            return None, _no_action(name)
        else:
            return None, key_problem(name)
    return (lambda context, row: row.action in actions or parse(row.key) in keys), None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Read by the config (TEXT_EDITOR per app) and the OS native preset; set
    # before anything loads, as `xefm --backend` does.
    os.environ["XEFM_BACKEND"] = args.backend
    # Nothing written: no bytecode beside config.py or an extension, and the
    # log lines loading would print are what this reports, said once.
    sys.dont_write_bytecode = True
    from xefm import log_manager
    log_manager.set_log_sink(lambda source, line: None)
    from xefm import keymap_presets
    from xefm.actions import CONTEXTS
    if args.keymap and keymap_presets.canonical(args.keymap) not in keymap_presets.PRESETS:
        print(f"error: no keymap preset {args.keymap!r} "
              f"({', '.join(sorted(keymap_presets.PRESETS))})", file=sys.stderr)
        return 2
    if args.context and args.context not in CONTEXTS:
        print(f"error: no context {args.context!r} ({', '.join(CONTEXTS)})",
              file=sys.stderr)
        return 2
    config_file = Path(args.config).expanduser() if args.config else None
    if config_file is not None and not config_file.is_file():
        print(f"error: no file {config_file}", file=sys.stderr)
        return 2

    report, read = build(config_file, args.keymap, args.backend)
    wanted, problem = _matcher(args.names)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2

    print(f"config:  {read['config']}")
    print(f"keymap:  {read['preset']} ({read['preset_source']}), {args.backend}")
    if read["extensions"]:
        print("extensions: " + ", ".join(f"{m.id} {m.version}"
                                         for m in read["extensions"]))
    shown = 0
    for context, rows in report.contexts.items():
        if args.context and context != args.context:
            continue
        rows = [r for r in rows if wanted(context, r)]
        if not rows:
            continue
        print(f"\n[{context}]")
        width = max(len(r.key) for r in rows)
        for row in rows:
            notes = []
            if row.selection != "any":
                notes.append(f"selection {row.selection}")
            if row.problem:
                notes.append("never fires: not a key XeFM knows")
            if row.shares:
                notes.append(f"same key as {', '.join(row.shares)}")
            print(f"  {row.key:<{width}}  {row.action}"
                  + (f"  ({'; '.join(notes)})" if notes else ""))
            shown += 1
    if args.names and not shown:
        print("\nnot bound in any context" if not args.context
              else f"\nnot bound in {args.context}")
    if report.warnings:
        print()
        for warning in report.warnings:
            print(f"warning: {warning}")
    if report.errors:
        print()
        for error in report.errors:
            print(f"error: {error}")
        return 1
    return 0 if shown or not args.names else 1


if __name__ == "__main__":
    sys.exit(main())
