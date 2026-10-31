"""What a quality-loop room left behind, and the checks every scenario shares.

A scenario's check (``NN_name.py`` beside this file, named like its Markdown
scenario in ``qa/scenarios/``) receives an :class:`Outcome` and returns the
list of things that went wrong - empty means none. The helpers here answer the
questions a check asks the way XeFM itself would: the config is loaded by
XeFM's own ``ConfigManager`` (in a subprocess, under a throwaway HOME), keys
are compared as XeFM parses them, and file associations are matched with
XeFM's own matcher.

The operator reaches them through ``qa/evidence.py check <room>``; a check
answers facts, the operator judges. ``test/test_qa.py`` runs every check
against the untouched fixture and against its reference edit, so a check that
cannot fail - or cannot pass - is caught without spending a run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from types import SimpleNamespace

CHECKS = pathlib.Path(__file__).resolve().parent
ROOT = CHECKS.parents[1]
TEMPLATE = ROOT / "xefm" / "_config.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Marks the lines of the fixture that stand for the user's own edits. Every
#: one of them must survive any edit the room makes: "change only what was
#: asked" is the skill's first rule, and these are what it protects.
KEEP = "# keep:"

#: The user's own edits, laid over the template to make the fixture: the
#: config of someone who has used XeFM for a while. ``(anchor, replacement)``,
#: each anchor a whole line of ``xefm/_config.py`` that must occur once.
_USER_EDITS = (
    ("    KEY_PRESET = None",
     "    KEY_PRESET = 'afx'  # keep: I use the letter keys"),
    ("    KEY_BINDINGS = {",
     "    KEY_BINDINGS = {\n"
     "        'quit': ['Shift-Q'],  # keep: no accidental quits"),
    ("    CONFIRM_DELETE = True   # Show confirmation dialog before deleting files/directories",
     "    CONFIRM_DELETE = False  # keep: I know what I'm doing"),
    ("        {'name': 'Desktop', 'path': '~/Desktop'},",
     "        {'name': 'Desktop', 'path': '~/Desktop'},\n"
     "        {'name': 'Notes', 'path': '~/notes'},  # keep: my notes"),
)


#: A user who wrote their own short config, or deleted the template's
#: comments: the same edits, and nothing else. A skill that leans on the
#: comments in the user's file (the commented examples, the explanations next
#: to each setting) has nothing to lean on here.
BARE = """\
class Config:
    KEY_PRESET = 'afx'  # keep: I use the letter keys

    KEY_BINDINGS = {
        'quit': ['Shift-Q'],  # keep: no accidental quits
    }

    CONFIRM_DELETE = False  # keep: I know what I'm doing

    FAVORITES = [
        {'name': 'Home', 'path': '~'},
        {'name': 'Notes', 'path': '~/notes'},  # keep: my notes
    ]
# keep: a note of mine at the very end
"""


def fixture_config(kind: str = "template") -> str:
    """What the room finds in ``~/.xefm/config.py``: ``"template"`` is the
    template with the user's edits on it, ``"bare"`` the same edits with no
    template text at all (:data:`BARE`)."""
    if "\n" in kind:          # a scenario's own fixture, written out in full
        return kind
    if kind == "bare":
        return BARE
    if kind != "template":
        raise ValueError(f"unknown fixture {kind!r}")
    text = TEMPLATE.read_text(encoding="utf-8")
    lines = text.split("\n")
    for anchor, replacement in _USER_EDITS:
        hits = [i for i, line in enumerate(lines) if line == anchor]
        if len(hits) != 1:
            raise RuntimeError(f"fixture anchor not found once in {TEMPLATE}: {anchor!r}")
        lines[hits[0]] = replacement
    return "\n".join(lines) + "\n# keep: a note of mine at the very end\n"


def template_source(name: str) -> str:
    """``Config.<name>``'s assignment in the template, verbatim — for a
    reference edit that has to copy a default the way a correct run would."""
    import ast
    text = TEMPLATE.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", None) == name):
            return "    " + ast.get_source_segment(text, node)
    raise KeyError(name)


def terminal_safe(key: str) -> bool:
    """Whether a terminal on every platform delivers ``key`` as itself:
    not a Command chord, not Ctrl-Shift-<letter> (a POSIX terminal sends that
    as Ctrl-<letter>), not Shift on a printable key, not Ctrl/Alt-ENTER."""
    parts = [p.lower() for p in key.split("-")]
    mods, base = set(parts[:-1]), parts[-1]
    ctrl = bool(mods & {"ctrl", "control"})
    if mods & {"cmd", "command"}:
        return False
    if ctrl and "shift" in mods and len(base) == 1 and base.isalpha():
        return False
    if mods == {"shift"} and (base == "space" or (len(base) == 1 and not base.isalpha())):
        return False
    if base in ("enter", "return") and mods:
        return False
    return True


def load_checks(names: list[str] | None = None) -> list:
    """Every scenario's check module, in file order, or the ones ``names``
    picks (by file stem, or by the part after the number: ``reload_on_f12``)."""
    found = []
    for path in sorted(CHECKS.glob("[0-9][0-9]_*.py")):
        spec = importlib.util.spec_from_file_location(f"scenario_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.NAME = path.stem
        found.append(module)
    if not names:
        return found
    wanted = []
    for name in names:
        match = [m for m in found if name in (m.NAME, m.NAME.split("_", 1)[1])]
        if not match:
            raise SystemExit(f"no check {name!r}; have: "
                             + ", ".join(m.NAME for m in found))
        wanted += match
    return wanted


# --- reading the config the way XeFM does ------------------------------------

_INSPECT = r"""
import json, logging, sys
from xefm.log_manager import getLogger
errors = []
class Catch(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            errors.append(record.getMessage())
getLogger("Config").addHandler(Catch())
from xefm.config import ConfigManager
manager = ConfigManager()
config = manager.load_config()
values = {name: getattr(config, name) for name in dir(config) if name.isupper()}
print(json.dumps({"values": values, "errors": errors,
                  "warnings": manager.validate_config(config)}, default=repr))
"""


def inspect_config(text: str, backend: str = "tui") -> dict:
    """``text`` loaded by XeFM's own ``ConfigManager`` under a throwaway HOME,
    as the ``backend`` would see it (``is_desktop_mode`` reads XEFM_BACKEND).

    Returns ``{"values": {NAME: value}, "errors": [...], "warnings": [...]}``;
    a value JSON cannot carry (a function) comes back as its repr."""
    with tempfile.TemporaryDirectory() as home:
        xefm_dir = pathlib.Path(home) / ".xefm"
        xefm_dir.mkdir()
        (xefm_dir / "config.py").write_text(text, encoding="utf-8")
        env = dict(os.environ, HOME=home, USERPROFILE=home, XEFM_BACKEND=backend,
                   PYTHONPATH=str(ROOT))
        done = subprocess.run([sys.executable, "-c", _INSPECT], env=env, cwd=home,
                              capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        return {"values": {}, "errors": [f"inspect failed: {done.stderr[-2000:]}"],
                "warnings": []}
    return json.loads(done.stdout.strip().splitlines()[-1])


def same_key(a: str, b: str) -> bool:
    """Whether two key expressions are the same key to XeFM (``Ctrl-T`` is
    ``Control-t``)."""
    from xefm.config import KeyBindings
    parse = KeyBindings({})._parse_key_expression
    return parse(a) == parse(b)


def keys_of(binding) -> list:
    if isinstance(binding, dict):
        return list(binding.get("keys", []))
    return list(binding or [])


def effective_keymap(values: dict, preset: str | None = None,
                     backend: str = "tui") -> dict:
    """The keymap XeFM would run: the preset in force, ``KEY_BINDINGS`` laid
    over it. ``preset`` defaults to the config's ``KEY_PRESET``."""
    from xefm import backend_detector, keymap_presets
    saved = os.environ.get("XEFM_BACKEND")
    os.environ["XEFM_BACKEND"] = backend
    backend_detector._cached_backend = None      # it caches the first answer
    try:
        config = SimpleNamespace(KEY_BINDINGS=dict(values.get("KEY_BINDINGS") or {}))
        keymap_presets.apply(config, preset or values.get("KEY_PRESET") or "afx")
        return config.KEY_BINDINGS
    finally:
        if saved is None:
            os.environ.pop("XEFM_BACKEND", None)
        else:
            os.environ["XEFM_BACKEND"] = saved
        backend_detector._cached_backend = None


def actions_on(keymap: dict, key: str) -> list[str]:
    """The file-list actions (no viewer prefix) ``key`` is bound to."""
    return sorted(action for action, binding in keymap.items()
                  if "." not in action
                  and any(same_key(k, key) for k in keys_of(binding)))


def association(values: dict, filename: str, action: str):
    """``(found, value)`` for ``action`` on ``filename``, matched the way
    XeFM's FILE_ASSOCIATIONS lookup does (top to bottom, first rule that
    matches and names the action)."""
    from xefm.config import _entry_matches
    for entry in values.get("FILE_ASSOCIATIONS") or []:
        if not _entry_matches(filename.lower(), entry):
            continue
        for key, value in entry.items():
            if key != "pattern" and action in (a.strip() for a in str(key).split("|")):
                return True, value
    return False, None


def argv(command) -> list:
    """A configured command as argv, as XeFM splits it."""
    from xefm.external_programs import command_argv
    return command_argv(command)


# --- the outcome ---------------------------------------------------------------

@dataclass
class Outcome:
    """What one run left behind."""
    before: str                        # the fixture, as the room found it
    after: str | None                  # ~/.xefm/config.py afterwards (None: gone)
    reply: str = ""                    # the room's final message
    xefm_calls: list = field(default_factory=list)   # every `xefm` it ran
    room: pathlib.Path | None = None
    installed: list = field(default_factory=list)    # extension dirs it installed
    _loaded: dict = field(default_factory=dict, repr=False)

    def config(self, backend: str = "tui") -> dict:
        """The resulting config's values, as ``backend`` would load them."""
        if backend not in self._loaded:
            self._loaded[backend] = inspect_config(self.after or "", backend)
        return self._loaded[backend]["values"]

    def load_errors(self, backend: str = "tui") -> list:
        self.config(backend)
        return self._loaded[backend]["errors"]

    @property
    def changed(self) -> bool:
        return self.after != self.before


def _cli_call(call: str) -> bool:
    """Whether an `xefm` call ran the CLI rather than the app: `ext`, `skill`,
    `--version`, or `try` with a script (#803), which runs XeFM in a pty and a
    temporary home of its own and ends with the script."""
    words = call.split()
    if words[:1] == ["try"]:
        return any(w == "--keys" or w.startswith("--keys=") for w in words)
    return words[:1] in (["ext"], ["skill"], ["--version"], ["-v"])


def common_failures(o: Outcome, kind: str) -> list[str]:
    """What every run must get right, whatever it was asked."""
    failures = []
    launched = [c for c in o.xefm_calls if not _cli_call(c)]
    if launched:
        failures.append(f"tried to launch XeFM itself: {launched}")
    if o.after is None:
        failures.append("~/.xefm/config.py is gone")
        return failures
    if kind == "config" or o.changed:
        failures += preserved_failures(o)
    return failures


def preserved_failures(o: Outcome) -> list[str]:
    """The user's own edits and the rest of the file, still there."""
    failures = []
    if errors := o.load_errors():
        failures.append(f"XeFM could not load the result: {errors[:2]}")
        return failures
    after_lines = set(o.after.splitlines())
    for line in o.before.splitlines():
        if KEEP in line and line not in after_lines:
            failures.append(f"lost the user's line: {line.strip()}")
    before_lines = o.before.splitlines()
    kept = sum(1 for line in before_lines if line in after_lines)
    # A real edit changes a line or two of the original; a rewrite changes
    # many. Two lines or 3%, whichever is more, so a short file is not held
    # to a ratio one edited line already breaks.
    if kept < len(before_lines) - max(2, 0.03 * len(before_lines)):
        failures.append(f"rewrote the file: only {kept} of {len(before_lines)} "
                        f"original lines are still there")
    values = o.config()
    if values.get("CONFIRM_DELETE") is not False:
        failures.append("the user's CONFIRM_DELETE = False is no longer in force")
    if not any(f.get("name") == "Notes" for f in values.get("FAVORITES") or []
               if isinstance(f, dict)):
        failures.append("the user's 'Notes' favorite is gone")
    return failures
