"""AI agent sessions: ``AGENTS``, ``agent`` and ``ask_agent`` (#880).

An entry of ``AGENTS`` names an agent CLI the user installed and signed in to
(Claude Code: ``claude``). ``agent`` starts it as a terminal session in
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

Claude Code (``'preset': 'claude-code'``), Codex (``'preset': 'codex'``),
GitHub Copilot CLI (``'preset': 'copilot'``) and Antigravity CLI
(``'preset': 'antigravity'``, the ``agy`` that replaced Gemini CLI) are
supported here; another agent CLI is configured with placeholders in its
``command`` - see the wiki.

Antigravity has no option for a skills folder or system-prompt text, but
reads a workspace's ``AGENTS.md`` and ``.agents/skills/``, and ``--add-dir``
adds a workspace folder: XeFM writes one holding both. Its deny rules go in
a session-only settings file (``--settings``).

Copilot loads the same plugin folder (``--plugin-dir``), denies commands with
``--deny-tool``, and takes the rules as an instructions file
(``xefm.instructions.md``, ``applyTo: "**"``) in a folder named by
``COPILOT_CUSTOM_INSTRUCTIONS_DIRS``: it has no option for system-prompt text,
and an ``AGENTS.md`` there is read only as a nested one.

Codex has no option that adds a skills folder, so its preset hands the skill
the way Codex lists its own: the rules (``-c developer_instructions=...``)
name the skill's ``SKILL.md`` for the agent to read. Codex has no settings
file to deny ``rm`` with either; its own sandbox and approvals apply.
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
CODEX = "codex"
COPILOT = "copilot"
ANTIGRAVITY = "antigravity"
PRESETS = (CLAUDE_CODE, CODEX, COPILOT, ANTIGRAVITY)

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

#: The shell commands that delete or move files, denied in a restricted
#: session by the agents that take command rules (Copilot, Antigravity).
#: Both match a command by the name as typed, aliases not included, so
#: PowerShell's names and aliases are listed beside the POSIX ones.
DENIED_COMMANDS = (
    "rm", "rmdir", "unlink", "shred", "mv", "trash", "srm", "git clean",
    "Remove-Item", "ri", "del", "erase", "rd", "Move-Item", "mi", "move",
)

#: Copilot's ``--deny-tool`` rules for a restricted session.
COPILOT_DENY_TOOLS = tuple(f"shell({c})" for c in DENIED_COMMANDS)

#: Antigravity's settings (``--settings``) for a restricted session.
ANTIGRAVITY_DEFAULT_SETTINGS = {
    "permissions": {"deny": [f"command({c})" for c in DENIED_COMMANDS]},
}

#: The environment variable naming Copilot's extra instructions folders.
COPILOT_INSTRUCTIONS_ENV = "COPILOT_CUSTOM_INSTRUCTIONS_DIRS"

_KEYS = {"name", "command", "preset", "restrict", "settings", "env", "prompt_args", "ui"}

#: How a session is shown (an entry's ``'ui'``): the agent CLI's own screen
#: in a terminal session, or the conversation drawn by XeFM (#959; Claude
#: Code only, through its stream-json mode - :mod:`xefm.agent_chat`).
UI_TERMINAL = "terminal"
UI_XEFM = "xefm"
UIS = (UI_TERMINAL, UI_XEFM)
#: The presets XeFM can draw a conversation for.
DRAWN_PRESETS = (CLAUDE_CODE,)


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
    ui = item.get("ui", UI_TERMINAL)
    if ui not in UIS:
        return f"{name}: 'ui' is one of {', '.join(UIS)}"
    if ui == UI_XEFM and preset not in DRAWN_PRESETS:
        return (f"{name}: 'ui': 'xefm' needs 'preset': one of "
                f"{', '.join(DRAWN_PRESETS)}")
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
        "ui": ui,
    }


PROMPT_KEYS = ("prompt", "agent")


def check_prompt(name: Any, value: Any) -> str | None:
    """What is wrong with one ``AGENT_PROMPTS`` entry, or None: a string (the
    request), or ``{'prompt': ..., 'agent': ...}``."""
    if not isinstance(name, str) or not name.strip():
        return "names must be non-empty strings"
    if isinstance(value, str):
        return None if value.strip() else "the prompt is empty"
    if not isinstance(value, dict):
        return "must be the request (a string) or { prompt = ..., agent = ... }"
    unknown = sorted(set(value) - set(PROMPT_KEYS))
    if unknown:
        return f"unknown key(s) {', '.join(unknown)} - known: {', '.join(PROMPT_KEYS)}"
    if not isinstance(value.get("prompt"), str) or not value["prompt"].strip():
        return "needs prompt = 'the request'"
    if "agent" in value and not isinstance(value["agent"], str):
        return "agent is the name of an AGENTS entry"
    return None


def prompts(config: Any) -> list[dict]:
    """``AGENT_PROMPTS`` (config.py's and the extensions') as ``{'name',
    'prompt', 'agent'}``, in order; a malformed entry is skipped with a
    warning in the log."""
    raw = getattr(config, "AGENT_PROMPTS", None) or {}
    if not isinstance(raw, dict):
        logger.warning("AGENT_PROMPTS is a dict of name -> request")
        return []
    out = []
    for name, value in raw.items():
        problem = check_prompt(name, value)
        if problem:
            logger.warning(f"AGENT_PROMPTS[{name!r}]: {problem}")
            continue
        spec = {"prompt": value} if isinstance(value, str) else value
        out.append({"name": name.strip(), "prompt": spec["prompt"].strip(),
                    "agent": spec.get("agent")})
    return out


def turned_off(config: Any) -> bool:
    """Whether the user turned agent sessions off: ``AGENTS = []`` in
    config.py. (A config.py without ``AGENTS`` gets the template's, so an
    empty one is always written on purpose.) The menu then leaves the agent
    items out; with entries none of which is installed, they stay, greyed."""
    return not getattr(config, "AGENTS", None)


def available(config: Any) -> list[dict]:
    """The ``AGENTS`` entries whose program is installed."""
    return [e for e in entries(config) if installed(e)]


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
    # The rules as an instructions file for Copilot (applied to everything).
    instructions = session_dir / "instructions"
    instructions.mkdir(exist_ok=True)
    (instructions / "xefm.instructions.md").write_text(
        '---\napplyTo: "**"\n---\n\n' + rules, encoding="utf-8")
    settings = entry.get("settings")
    if settings is None and not entry.get("restrict", True):
        settings = {}
    elif settings is None:
        settings = (ANTIGRAVITY_DEFAULT_SETTINGS if entry.get("preset") == ANTIGRAVITY
                    else CLAUDE_DEFAULT_SETTINGS)
    settings_file = session_dir / f"settings-{_safe(entry['name'])}.json"
    settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    extra = {}
    if entry.get("preset") == ANTIGRAVITY:
        extra["workspace_dir"] = str(_antigravity_workspace(session_dir, skill, rules))
    return {**extra,
        "{plugin_dir}": str(plugin),
        "{skills_dir}": str(plugin / "skills"),
        "{skill_dir}": str(skill),
        "{rules}": rules,
        "{rules_file}": str(rules_file),
        "{settings_file}": str(settings_file),
        "instructions_dir": str(instructions),  # for the copilot preset; not a placeholder
    }


def _antigravity_workspace(session_dir: _FsPath, skill: _FsPath, rules: str) -> _FsPath:
    """A folder for Antigravity's ``--add-dir``: it reads a workspace's
    ``AGENTS.md`` as rules and its ``.agents/skills/`` as skills."""
    folder = session_dir / "antigravity"
    skills = folder / ".agents" / "skills"
    shutil.rmtree(skills, ignore_errors=True)
    shutil.copytree(skill, skills / skill.name)
    (folder / "AGENTS.md").write_text(rules, encoding="utf-8")
    return folder


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
    if entry.get("preset") == CODEX:
        # `codex -c key=value` parses the value as TOML; a string that fails
        # to parse would be taken raw, so it is always given quoted.
        out += ["-c", "developer_instructions="
                + _toml_string(codex_instructions(values))]
        if prompt:
            out.append(prompt)  # `codex "request"` starts the TUI with it
        return out
    if entry.get("preset") == COPILOT:
        out += ["--plugin-dir", values["{plugin_dir}"]]
        if entry.get("restrict", True):
            out += [f"--deny-tool={rule}" for rule in COPILOT_DENY_TOOLS]
        if prompt:
            out += ["-i", prompt]  # interactive, starting with the request
        return out
    if entry.get("preset") == ANTIGRAVITY:
        out += ["--add-dir", values["workspace_dir"],
                "--settings", values["{settings_file}"]]
        if prompt:
            out += ["-i", prompt]  # interactive, starting with the request
        return out
    if prompt:
        out += [_fill(a, values) for a in entry["prompt_args"]]
    return out


def drawn(entry: dict) -> bool:
    """Whether XeFM draws the entry's conversation (``'ui': 'xefm'``)."""
    return entry.get("ui") == UI_XEFM


def drawn_rules(rules: str) -> str:
    """The rules for a conversation XeFM draws: the same, but nothing about a
    terminal - the user reads the agent in XeFM's own screen."""
    return (rules
            .replace("in a terminal session XeFM started. The user is looking "
                     "at XeFM's window, beside this session.",
                     "and XeFM draws this conversation in its own window. The "
                     "user reads your replies there, beside the file manager; "
                     "XeFM asks them each time a tool needs permission.")
            .replace("rather than long output in this terminal",
                     "rather than long output in your reply"))


def chat_argv(entry: dict, values: dict) -> list[str]:
    """The command line of a drawn session (``'ui': 'xefm'``): the entry's
    ``command``, Claude Code's stream-json mode with its permission questions
    sent to XeFM, then what the preset passes a terminal session too - the
    skill, the rules, the settings. The first request goes in as a message,
    not on the command line."""
    from xefm.agent_chat import CLAUDE_STREAM_ARGS
    values = dict(values, **{"{prompt}": ""})
    out = [_fill(a, values) for a in entry["command"]]
    out += list(CLAUDE_STREAM_ARGS)
    out += ["--plugin-dir", values["{plugin_dir}"],
            "--append-system-prompt", drawn_rules(values["{rules}"]),
            "--settings", values["{settings_file}"]]
    return out


def session_env(entry: dict, values: dict, env: dict) -> dict:
    """The environment variables the entry's preset adds to ``env`` (the
    session's, the entry's own ``env`` already in it)."""
    if entry.get("preset") != COPILOT:
        return {}
    dirs = [d for d in env.get(COPILOT_INSTRUCTIONS_ENV, "").split(",") if d.strip()]
    return {COPILOT_INSTRUCTIONS_ENV: ",".join([*dirs, values["instructions_dir"]])}


def codex_instructions(values: dict) -> str:
    """What the ``codex`` preset hands Codex as its developer instructions:
    the rules, then where the skill is, the way Codex names its own skills
    (a path to ``SKILL.md`` for the agent to read)."""
    skill = _FsPath(values["{skill_dir}"]).as_posix()
    return (values["{rules}"]
            + "\n## The xefm skill\n\n"
            "XeFM handed this session its `xefm` skill: read "
            f"`{skill}/SKILL.md` before running xefmctl or changing XeFM's "
            "configuration, and resolve the paths it mentions against that "
            "folder.\n")


def _toml_string(text: str) -> str:
    """``text`` as a TOML basic string."""
    out = []
    for ch in text:
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


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
