"""AI agent sessions: ``AGENTS``, ``open_agent`` and ``ask_agent`` (#880).

An entry of ``AGENTS`` names an agent CLI the user installed and signed in to
(Claude Code: ``claude``). ``open_agent`` starts it as a terminal session in
the active pane's folder; ``ask_agent`` starts it with a request and the
selection. XeFM never touches credentials, models or providers: it runs a
program it finds on ``PATH``, the way it runs an editor.

What XeFM hands the agent, beyond the ``XEFM_*`` variables every program
gets:

- **The skill**, the ``xefm`` skill of this very XeFM, written to a
  versioned folder under ``~/.xefm/cache/agents/`` and passed on the command
  line, so a session always has the skill that matches the XeFM it runs in,
  with nothing installed globally. For Claude Code it is a plugin folder
  (``--plugin-dir``).
- **The rules** (the soft layer): what to do and not to do inside XeFM,
  :data:`DEFAULT_RULES` followed by the user's ``AGENT_RULES``. For Claude
  Code, ``--append-system-prompt``.
- **Permissions** (the first hard layer, the agent's own): for Claude Code a
  settings file (``--settings``) that denies the shell commands that delete
  or move files, so they go through ``xefmctl``, which XeFM confirms.
- **A restricted session key** (the second hard layer, XeFM's own, for any
  agent): ``xefmctl`` from the session has its writes confirmed in XeFM,
  ``delete`` refused, and its first read outside the local disk asked (see
  :mod:`xefm.remote_dispatch`). ``'restrict': False`` lifts both hard layers.

Claude Code is supported here (``'preset': 'claude-code'``); another agent
CLI is configured with placeholders in its ``command`` - see the wiki.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path as _FsPath
from typing import Any

from xefm.log_manager import getLogger

logger = getLogger("Agents")

CLAUDE_CODE = "claude-code"
PRESETS = (CLAUDE_CODE,)

#: The placeholders a ``command`` (or ``prompt_args``) may hold.
PLACEHOLDERS = ("{plugin_dir}", "{skills_dir}", "{skill_dir}", "{rules}",
                "{rules_file}", "{settings_file}", "{prompt}")

DEFAULT_RULES = """\
You are running inside XeFM, a dual-pane file manager, in a terminal session \
XeFM started. The user is looking at XeFM's window, beside this session.

- Start with `xefmctl state` to see what the user is looking at: both panes, \
the cursor, the selection, what is open. `xefmctl help` lists every command; \
the `xefm` skill explains them.
- When the user says "this file", "these", "here", they mean what XeFM shows: \
read it with xefmctl, do not guess.
- Change files - delete, move, copy, overwrite, rename - only through \
`xefmctl copy|move|trash --wait`, so the user confirms each one in XeFM. Never \
delete anything for good.
- Read places outside this computer's disk (ssh://, s3://, archives, virtual \
folders) with `xefmctl entries`, `read` and `fetch`; propose changes there \
rather than making them.
- To show the user something, use `--show`, `xefmctl view`, `diff` or \
`show-markdown`, rather than long output in this terminal. To ask, use \
`xefmctl confirm`, `choose` or `input`.
- Do not change ~/.xefm/ unless the user asked. After editing config.py, run \
`xefmctl invoke reload_config`.
- Use the `xefm` skill XeFM handed this session (in Claude Code it is \
`xefm:xefm`): it matches this XeFM. Another copy of an xefm skill installed \
elsewhere may describe a different version; do not follow it.
"""

#: Claude Code's settings for a restricted session: the shell commands that
#: delete or move files are denied, so those go through xefmctl.
CLAUDE_DEFAULT_SETTINGS = {
    "permissions": {
        "deny": [
            "Bash(rm:*)", "Bash(rmdir:*)", "Bash(unlink:*)", "Bash(shred:*)",
            "Bash(mv:*)", "Bash(trash:*)", "Bash(srm:*)",
            "Bash(git clean:*)",
            "Bash(xefmctl delete:*)",
        ],
    },
}

_KEYS = {"name", "command", "preset", "restrict", "settings", "env", "prompt_args"}


def entries(config: Any) -> list[dict]:
    """``AGENTS`` as normalized entries; a malformed one is skipped with a
    warning in the log."""
    raw = getattr(config, "AGENTS", None) or []
    if isinstance(raw, dict):
        raw = [dict(v, name=v.get("name", k)) if isinstance(v, dict) else v
               for k, v in raw.items()]
    out = []
    for i, item in enumerate(raw):
        entry = normalize(item)
        if isinstance(entry, str):
            logger.warning(f"AGENTS[{i}]: {entry}")
            continue
        out.append(entry)
    return out


def normalize(item: Any) -> dict | str:
    """One ``AGENTS`` entry with every key filled, or what is wrong with it."""
    if not isinstance(item, dict):
        return "an entry is a dict with 'name' and 'command'"
    unknown = sorted(set(item) - _KEYS)
    if unknown:
        return f"unknown key(s) {', '.join(map(repr, unknown))}"
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return "'name' is missing"
    command = item.get("command")
    if isinstance(command, str):
        import shlex
        command = shlex.split(command)
    if not isinstance(command, (list, tuple)) or not command \
            or not all(isinstance(a, str) for a in command):
        return f"{name}: 'command' is a list of strings"
    preset = item.get("preset")
    if preset is not None and preset not in PRESETS:
        return f"{name}: 'preset' is one of {', '.join(PRESETS)}"
    settings = item.get("settings")
    if settings is not None and not isinstance(settings, dict):
        return f"{name}: 'settings' is a dict"
    env = item.get("env") or {}
    if not isinstance(env, dict):
        return f"{name}: 'env' is a dict"
    prompt_args = item.get("prompt_args", ["{prompt}"])
    if not isinstance(prompt_args, (list, tuple)) \
            or not all(isinstance(a, str) for a in prompt_args):
        return f"{name}: 'prompt_args' is a list of strings"
    return {
        "name": name.strip(),
        "command": list(command),
        "preset": preset,
        "restrict": bool(item.get("restrict", True)),
        "settings": settings,
        "env": {str(k): str(v) for k, v in env.items()},
        "prompt_args": list(prompt_args),
    }


def rules_text(config: Any) -> str:
    """The rules an agent gets: XeFM's, then the user's ``AGENT_RULES``."""
    extra = getattr(config, "AGENT_RULES", "") or ""
    if not isinstance(extra, str):
        logger.warning("AGENT_RULES is a string; ignoring it")
        extra = ""
    text = DEFAULT_RULES
    if extra.strip():
        text += "\nThe user's own rules:\n\n" + extra.strip() + "\n"
    return text


def cache_root() -> _FsPath:
    from xefm.config import config_manager
    return _FsPath(config_manager.config_dir) / "cache" / "agents"


def prepare(config: Any, entry: dict, *, root: _FsPath | None = None,
            version: str | None = None) -> dict:
    """Write what the session is handed - the skill (as a plugin folder),
    the rules and, for Claude Code, its settings - and return the
    placeholders' values."""
    from xefm import extensions as ext
    version = version or ext.skill_version()
    root = _FsPath(root) if root is not None else cache_root()
    base = root / _safe(version)
    plugin = base / "plugin"
    skill = plugin / "skills" / ext.SKILL_DIR.name
    # Written afresh each time (a few small files): a development tree's
    # version stays the same while its skill changes, and a session already
    # running has read its copy at start.
    tmp = base / "plugin.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    for name, data in ext._skill_files(version):
        file = tmp / "skills" / ext.SKILL_DIR.name / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    manifest = tmp / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "name": "xefm",
        "description": "Work with the XeFM file manager this session runs in "
                       "(xefmctl, configuration, extensions).",
    }, indent=2), encoding="utf-8")
    shutil.rmtree(plugin, ignore_errors=True)
    tmp.rename(plugin)
    rules = rules_text(config)
    session_dir = base / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    rules_file = session_dir / "rules.md"
    rules_file.write_text(rules, encoding="utf-8")
    settings = entry.get("settings")
    if settings is None:
        settings = CLAUDE_DEFAULT_SETTINGS if entry.get("restrict", True) else {}
    settings_file = session_dir / f"settings-{_safe(entry['name'])}.json"
    settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return {
        "{plugin_dir}": str(plugin),
        "{skills_dir}": str(plugin / "skills"),
        "{skill_dir}": str(skill),
        "{rules}": rules,
        "{rules_file}": str(rules_file),
        "{settings_file}": str(settings_file),
    }


def argv(entry: dict, values: dict, prompt: str | None = None) -> list[str]:
    """The command line that starts the agent: the entry's ``command`` with
    its placeholders filled, then what the preset adds, then the prompt."""
    values = dict(values, **{"{prompt}": prompt or ""})
    out = [_fill(a, values) for a in entry["command"]]
    if entry.get("preset") == CLAUDE_CODE:
        out += ["--plugin-dir", values["{plugin_dir}"],
                "--append-system-prompt", values["{rules}"],
                "--settings", values["{settings_file}"]]
        if prompt:
            out.append(prompt)
        return out
    if prompt:
        out += [_fill(a, values) for a in entry["prompt_args"]]
    return out


def _fill(arg: str, values: dict) -> str:
    for key in PLACEHOLDERS:
        if key in arg:
            arg = arg.replace(key, values.get(key, ""))
    return arg


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in text) or "_"


def installed(entry: dict) -> bool:
    """Whether the entry's program can be found."""
    program = entry["command"][0]
    return bool(shutil.which(program) or os.path.isfile(program))


def prompt_with_context(request: str, pane_path: str, selected: list[str],
                        focused: str | None) -> str:
    """``ask_agent``'s request, with where it was asked from."""
    lines = [request.strip(), "", f"(Asked from XeFM. The active pane shows {pane_path}."]
    if selected:
        shown = selected[:20]
        lines.append(f"Selected there ({len(selected)}):")
        lines += [f"  {p}" for p in shown]
        if len(selected) > len(shown):
            lines.append(f"  ... and {len(selected) - len(shown)} more "
                         f"(xefmctl pane selected)")
    elif focused:
        lines.append(f"Nothing is selected; the cursor is on {focused}.")
    lines.append("Run `xefmctl state` for more.)")
    return "\n".join(lines)
