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
adds a workspace folder: XeFM writes one holding both. Its shell may start in
that folder, so the rules there name the session's (#1001). Its deny rules go
in a session-only settings file (``--settings``).

Copilot loads the same plugin folder (``--plugin-dir``), denies commands with
``--deny-tool``, and takes the rules as an instructions file
(``xefm.instructions.md``, ``applyTo: "**"``) in a folder named by
``COPILOT_CUSTOM_INSTRUCTIONS_DIRS``: it has no option for system-prompt text,
and an ``AGENTS.md`` there is read only as a nested one.

Codex has no option that adds a skills folder, so its preset hands the skill
the way Codex lists its own: the rules (``-c developer_instructions=...``)
name the skill's ``SKILL.md`` for the agent to read. Codex has no settings
file to deny ``rm`` with either; its own sandbox and approvals apply.

A conversation XeFM draws (:func:`drawn`) runs the agent in the mode made for
that instead of its screen: Claude Code's stream-json (:mod:`xefm.agent_chat`),
Codex's app-server (:mod:`xefm.agent_codex`), the Agent Client Protocol for
Copilot and Antigravity (:mod:`xefm.agent_acp`). It is handed the same things,
each the way that mode takes them (:func:`chat_argv`, :func:`protocol`).

**The way to XeFM (#995).** The agent's own sandbox, where it has one, keeps
its shell from the socket ``xefmctl`` uses, so every session also gets
``xefmctl`` as MCP tools, from a server in XeFM (:mod:`xefm.mcp_server`):
:data:`CHANNELS` says how each is handed the address and the session's token.
The token is in no environment and on no command line, and a file that holds
it is in a folder of the session's own (:func:`prepare`), never a temporary
one: Copilot's sandbox lets its shell read those. XeFM turns no agent's
sandbox on, off or wider; :func:`sandbox_state` only says what it is.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import shutil
import sys
import tempfile
import time
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
PLACEHOLDERS = ("{plugin_dir}", "{skills_dir}", "{skill_dir}", "{user_plugin_dir}",
                "{user_skills_dir}", "{rules}", "{rules_file}", "{settings_file}",
                "{mcp_config_file}", "{prompt}")

#: The plugin the user's own skills (``~/.xefm/skills/``) are handed in, apart
#: from XeFM's: in Claude Code they are ``xefm-user:<name>`` (#1009).
USER_PLUGIN = "xefm-user"

DEFAULT_RULES = """\
You are running inside XeFM, a dual-pane file manager, in a terminal session \
XeFM started. The user is looking at XeFM's window, beside this session.

- Start with `xefmctl state` to see what the user is looking at: both panes, \
the cursor, the selection, what is open. `xefmctl help` lists every command; \
the `xefm` skill explains them.
- If this session has XeFM's tools `xefmctl_read` and `xefmctl`, run xefmctl \
commands with them, not in the shell: they are the same commands, and work \
where a sandbox keeps the shell from XeFM. `xefmctl_read` takes what only reads.
- To look at files, use your own tools for reading, listing and searching \
files, or `xefmctl_read`, rather than shell commands (`ls`, `cat`, `find`, \
loops): the user is asked about nearly every shell command, and about those \
tools far less often.
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
- A skill the user asks for "for XeFM" ("an XeFM skill", "install it in \
XeFM") goes in ~/.xefm/skills/<name>/, not in your own skills folder; the \
`xefm` skill's references/skills.md says how, and `xefmctl skill check <name>` \
checks it; `xefmctl skill list` lists them (rather than the shell). XeFM hands those skills to every \
session it starts, from the next one on: in this session, read the new \
SKILL.md yourself.
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

_KEYS = {"name", "command", "preset", "restrict", "settings", "env", "prompt_args", "terminal"}

#: The presets XeFM can draw a conversation for (#959). Their sessions are
#: drawn unless the entry says ``'terminal': True``; every other session is
#: the agent CLI's own screen in a terminal session. A preset joins once XeFM
#: can draw it.
DRAWN_PRESETS = (CLAUDE_CODE, CODEX, COPILOT, ANTIGRAVITY)

#: How a session is handed the way to XeFM's MCP tools, by its preset and
#: whether XeFM draws it: in the request that opens the session
#: (``"session"``), in a file of the session's own named on the command line
#: (``"file"``), or in a file where the agent looks (``"workspace"``). An entry
#: without a preset names the file itself, with ``{mcp_config_file}``.
CHANNELS = {
    (CLAUDE_CODE, True): "file", (CLAUDE_CODE, False): "file",
    (CODEX, True): "session", (CODEX, False): "file",
    (COPILOT, True): "session", (COPILOT, False): "file",
    (ANTIGRAVITY, True): "session", (ANTIGRAVITY, False): "workspace",
    (None, False): "file",
}

#: Seconds an agent that has a limit for a tool's answer is told to wait: the
#: user may be asked meanwhile.
TOOL_TIMEOUT = 24 * 60 * 60


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
    if "ui" in unknown:
        return ("'ui' is gone: a session with a preset is drawn by XeFM unless "
                "the entry says 'terminal': True")
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
    terminal = item.get("terminal", preset not in DRAWN_PRESETS)
    if not isinstance(terminal, bool):
        return f"{name}: 'terminal' is True or False"
    if not terminal and preset not in DRAWN_PRESETS:
        return (f"{name}: 'terminal': False needs 'preset': one of "
                f"{', '.join(DRAWN_PRESETS)} (XeFM draws only those)")
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
        "terminal": terminal,
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


#: What Antigravity's rules say in a terminal session, after everyone's.
_FOLDER_RULES = """
The session's folder is {folder}

Work there: it is what "here", "this folder" and a relative path mean. Your
shell may start in another of your workspace folders, the one with these rules,
which is XeFM's own and not for work. So begin every shell command by changing
to the session's folder, and give file tools absolute paths.
"""


def _for_windows_powershell(name: str, data: bytes) -> bytes:
    """A skill file as a session gets it. On Windows an agent reads it with
    Windows PowerShell's ``Get-Content``, which takes a file without a BOM
    for the ANSI code page (#995: Codex read `\u2014` garbled). So the
    references get a UTF-8 BOM there; ``SKILL.md`` cannot (its frontmatter
    starts the file) and is kept ASCII instead (``test_agents.py``)."""
    if (sys.platform != "win32" or not name.endswith(".md") or name == "SKILL.md"
            or data.startswith(codecs.BOM_UTF8) or data.isascii()):
        return data
    return codecs.BOM_UTF8 + data


def prepare(config: Any, entry: dict, *, root: _FsPath | None = None,
            version: str | None = None, cwd: str | None = None,
            channel: Any = None, user_skills: _FsPath | None = None) -> dict:
    """Write what the session is handed - the skill (as a plugin folder),
    the user's own skills (another plugin folder), the rules and, for Claude
    Code, its settings - and return the placeholders' values. ``cwd`` is the
    session's folder, ``channel`` its way to XeFM
    (:class:`xefm.mcp_server.Channel`), ``user_skills`` where the user's
    skills are (``~/.xefm/skills/``)."""
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
        file.write_bytes(_for_windows_powershell(name, data))
    manifest = tmp / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "name": "xefm",
        "description": "Work with the XeFM file manager this session runs in "
                       "(xefmctl, configuration, extensions).",
    }, indent=2), encoding="utf-8")
    shutil.rmtree(plugin, ignore_errors=True)
    tmp.rename(plugin)
    user_plugin, mine = _user_plugin(base, user_skills)
    rules = rules_text(config)
    session_dir = base / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    rules_file = session_dir / "rules.md"
    rules_file.write_text(rules, encoding="utf-8")
    # A drawn session's files, apart from a terminal one's: the rules differ.
    apart = "-drawn" if drawn(entry) else ""
    told = drawn_rules(rules) if drawn(entry) else rules
    # The rules as an instructions file for Copilot (applied to everything).
    instructions = session_dir / f"instructions{apart}"
    instructions.mkdir(exist_ok=True)
    (instructions / "xefm.instructions.md").write_text(
        '---\napplyTo: "**"\n---\n\n' + told, encoding="utf-8")
    settings = entry.get("settings")
    own = settings is not None
    if settings is None and not entry.get("restrict", True):
        settings = {}
    elif settings is None:
        settings = (ANTIGRAVITY_DEFAULT_SETTINGS if entry.get("preset") == ANTIGRAVITY
                    else CLAUDE_DEFAULT_SETTINGS)
    if entry.get("preset") == CLAUDE_CODE and not own:
        settings = _with_skills_readable(settings, [plugin, user_plugin])
    settings_file = session_dir / f"settings-{_safe(entry['name'])}.json"
    settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    extra = {"channel": channel}
    way = CHANNELS.get((entry.get("preset"), drawn(entry)))
    if way == "file" and channel is not None:
        # A folder of the session's own, readable by this user alone, gone
        # with the session (:func:`discard`): the file holds its token.
        _prune_session_folders(root)
        own = _FsPath(tempfile.mkdtemp(prefix=f"session-{os.getpid()}-", dir=session_dir))
        extra["session_folder"] = str(own)
        extra.update(_channel_files(entry, channel, own))
    if entry.get("preset") == ANTIGRAVITY:
        if drawn(entry):
            folder = session_dir / "antigravity-drawn"
        else:
            # A terminal session's own, readable by this user alone, gone with
            # the session (:func:`discard`): its rules name its folder.
            _prune_session_folders(root)
            folder = _FsPath(tempfile.mkdtemp(
                prefix=f"antigravity-{os.getpid()}-", dir=session_dir))
            extra["session_folder"] = str(folder)
            if cwd:
                # Its shell starts in whichever workspace folder sorts first,
                # and ~/.xefm sorts before nearly all (1.5.16, #1001); over ACP
                # it starts in the session's. As JSON: a folder's name may hold
                # a line break, and is no rule. With slashes: a model may take
                # a backslash for an escape.
                name = json.dumps(_FsPath(cwd).as_posix(), ensure_ascii=False)
                told += _FOLDER_RULES.format(
                    folder=name.encode("utf-8", "backslashreplace").decode("utf-8"))
        extra["workspace_dir"] = str(_antigravity_workspace(
            folder, [skill, *(user_plugin / "skills" / s.name for s in mine)], told))
        if way == "workspace" and channel is not None:
            _write_private(folder / ".agents" / "mcp_config.json", {"mcpServers": {
                channel.name: {"serverUrl": channel.url, "headers": channel.headers}}})
    return {**extra,
        "{plugin_dir}": str(plugin),
        "{skills_dir}": str(plugin / "skills"),
        "{skill_dir}": str(skill),
        "{user_plugin_dir}": str(user_plugin),
        "{user_skills_dir}": str(user_plugin / "skills"),
        # The user's skills as handed: (name, description, folder).
        "user_skills": [(s.name, s.description, str(user_plugin / "skills" / s.name))
                        for s in mine],
        "{rules}": rules,
        "{rules_file}": str(rules_file),
        "{settings_file}": str(settings_file),
        "{mcp_config_file}": extra.get("{mcp_config_file}", ""),
        "instructions_dir": str(instructions),  # for the copilot preset; not a placeholder
    }


def _user_plugin(base: _FsPath, source: _FsPath | None) -> tuple[_FsPath, list]:
    """The user's skills that pass the check, copied as a plugin folder of
    their own under ``base`` (written afresh, like XeFM's: the user edits
    them between sessions), and the skills themselves. The folder is there,
    with an empty ``skills/``, when there are none: an entry's ``command`` may
    name it."""
    from xefm import agent_skills
    mine = agent_skills.found(source)
    plugin, tmp = base / "user-plugin", base / "user-plugin.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "skills").mkdir(parents=True)
    for s in mine:
        for file in sorted(s.path.rglob("*")):
            rel = file.relative_to(s.path)
            if not file.is_file() or any(p.startswith(".") for p in rel.parts):
                continue
            to = tmp / "skills" / s.name / rel
            to.parent.mkdir(parents=True, exist_ok=True)
            to.write_bytes(_for_windows_powershell(file.name, file.read_bytes()))
    manifest = tmp / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "name": USER_PLUGIN,
        "description": "The user's own skills for the sessions XeFM starts "
                       "(~/.xefm/skills/).",
    }, indent=2), encoding="utf-8")
    shutil.rmtree(plugin, ignore_errors=True)
    tmp.rename(plugin)
    return plugin, mine


def _claude_path_rule(path: str) -> str:
    """An absolute path as Claude Code's permission rules write it: ``//``
    then the path in POSIX form (on Windows ``C:\\x`` is ``/c/x``)."""
    path = path.replace("\\", "/")
    if re.match(r"[A-Za-z]:/", path):
        path = f"/{path[0].lower()}{path[2:]}"
    return "/" + path if path.startswith("/") else "//" + path


def _with_skills_readable(settings: dict, folders: list[_FsPath]) -> dict:
    """``settings`` that also let Claude Code read the skill folders XeFM
    handed the session without asking: they are outside the session's folder,
    so each reference a skill names was asked about. Both spellings of a
    folder reached through a link, as Claude Code checks both."""
    import copy
    out = copy.deepcopy(settings)
    allow = out.setdefault("permissions", {}).setdefault("allow", [])
    for folder in folders:
        for spelled in dict.fromkeys([str(folder), os.path.realpath(folder)]):
            rule = f"Read({_claude_path_rule(spelled)}/**)"
            if rule not in allow:
                allow.append(rule)
    return out


def _user_plugin_args(values: dict) -> list[str]:
    """``--plugin-dir`` for the user's plugin, when it holds a skill."""
    return ["--plugin-dir", values["{user_plugin_dir}"]] if values.get("user_skills") else []


def _write_private(path: _FsPath, data: dict) -> str:
    """``data`` as JSON in a new file only this user may read."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return str(path)


def _channel_files(entry: dict, channel: Any, folder: _FsPath) -> dict:
    """The files that tell the agent of XeFM's MCP server, in the session's
    own ``folder``, as values for its command line."""
    if entry.get("preset") == CODEX:
        # What its ``http_headers_helper`` prints.
        return {"headers_file": _write_private(folder / "headers.json", channel.headers)}
    server = {"type": "http", "url": channel.url, "headers": channel.headers}
    if entry.get("preset") == COPILOT:
        server["tools"] = ["*"]
    return {"{mcp_config_file}": _write_private(
        folder / "mcp.json", {"mcpServers": {channel.name: server}})}


def codex_server(channel: Any) -> dict:
    """The setting that gives a Codex thread XeFM's MCP server. The key is
    dotted: under ``mcp_servers`` as a table it takes the place of the servers
    the entry's own ``-c`` options name (0.171.0, #995)."""
    return {f"mcp_servers.{channel.name}": {
        "url": channel.url, "http_headers": channel.headers,
        "tool_timeout_sec": TOOL_TIMEOUT}}


def _codex_options(values: dict) -> list[str]:
    """The same for Codex's own screen: its command line is open to others,
    so it names a command that prints the header from a file (the sandboxed
    shell, which may read that file, cannot reach the port)."""
    channel, file = values.get("channel"), values.get("headers_file")
    if channel is None or not file:
        return []
    import shlex
    helper = f'type "{file}"' if os.name == "nt" else f"cat {shlex.quote(file)}"
    key = f"mcp_servers.{channel.name}"
    return ["-c", f"{key}.url={_toml_string(channel.url)}",
            "-c", f"{key}.http_headers_helper={_toml_string(helper)}",
            "-c", f"{key}.tool_timeout_sec={TOOL_TIMEOUT}"]


#: A command line's words that say what the agent's sandbox is (an option and
#: its value as ``--sandbox value``). Read only, never added.
_SANDBOX_OPTIONS = {
    CODEX: (("--dangerously-bypass-approvals-and-sandbox", "off"), ("--yolo", "off"),
            ("--sandbox danger-full-access", "off"), ("-s danger-full-access", "off"),
            ("--sandbox workspace-write", "on"), ("-s workspace-write", "on"),
            ("--sandbox read-only", "on"), ("-s read-only", "on")),
    COPILOT: (("--sandbox", "on"), ("--no-sandbox", "off")),
    ANTIGRAVITY: (("--sandbox", "on"),),
}


def sandbox_state(entry: dict) -> str:
    """The agent's own sandbox as far as the entry's command line says:
    ``on``, ``off``, or ``not known`` (it is the user's settings, or the
    agent's default)."""
    line = f" {' '.join(entry['command'][1:]).replace('=', ' ')} "
    for words, state in _SANDBOX_OPTIONS.get(entry.get("preset"), ()):
        if f" {words} " in line:
            return state
    return "not known"


def discard(values: dict) -> None:
    """Delete what :func:`prepare` wrote for one session alone, once it has
    ended. A file still open stays; a later start deletes it."""
    folder = values.get("session_folder")
    if folder:
        shutil.rmtree(folder, ignore_errors=True)


#: The name of a session's own folder: the XeFM that made it, then its own part.
_SESSION_FOLDER = re.compile(r"(?:antigravity|session)-(\d+)-")

#: Seconds before the folder of an XeFM that is gone is deleted. Not at once: a
#: process id says nothing about an XeFM in a container that shares this home.
_SESSION_FOLDER_KEPT = 24 * 60 * 60


def _prune_session_folders(root: _FsPath) -> None:
    """Delete the sessions' own folders that an XeFM left when it ended, under
    every version's folder."""
    from xefm.similar_scan import pid_alive
    for folder in root.glob("*/sessions/*-*-*"):
        made_by = _SESSION_FOLDER.match(folder.name)
        try:
            if made_by and time.time() - folder.stat().st_mtime > _SESSION_FOLDER_KEPT \
                    and not pid_alive(int(made_by[1])):
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue  # another XeFM deleted it


def _antigravity_workspace(folder: _FsPath, skills_in: list[_FsPath],
                           rules: str) -> _FsPath:
    """A folder for Antigravity's ``--add-dir``: it reads a workspace's
    ``AGENTS.md`` as rules and its ``.agents/skills/`` as skills (XeFM's,
    then the user's)."""
    skills = folder / ".agents" / "skills"
    shutil.rmtree(skills, ignore_errors=True)
    for skill in skills_in:
        for file in skill.rglob("*"):
            # Written, not copied: in a Windows VM where a sandboxed Codex had
            # just run, CopyFile2 (shutil's) took two minutes over one of these.
            if file.is_file():
                to = skills / skill.name / file.relative_to(skill)
                to.parent.mkdir(parents=True, exist_ok=True)
                to.write_bytes(file.read_bytes())
    (folder / "AGENTS.md").write_text(rules, encoding="utf-8")
    return folder


def argv(entry: dict, values: dict, prompt: str | None = None) -> list[str]:
    """The command line that starts the agent: the entry's ``command`` with
    its placeholders filled, then what the preset adds, then the prompt."""
    values = dict(values, **{"{prompt}": prompt or ""})
    out = [_fill(a, values) for a in entry["command"]]
    if entry.get("preset") == CLAUDE_CODE:
        out += _mcp_config(values, "--mcp-config")
        out += ["--plugin-dir", values["{plugin_dir}"], *_user_plugin_args(values),
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
        out += _codex_options(values)
        if prompt:
            out.append(prompt)  # `codex "request"` starts the TUI with it
        return out
    if entry.get("preset") == COPILOT:
        out += ["--plugin-dir", values["{plugin_dir}"], *_user_plugin_args(values)]
        out += _mcp_config(values, "--additional-mcp-config", "@")
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


def _mcp_config(values: dict, option: str, mark: str = "") -> list[str]:
    file = values.get("{mcp_config_file}")
    return [option, mark + file] if file else []


def drawn(entry: dict) -> bool:
    """Whether XeFM draws the entry's conversation (``'terminal': False``)."""
    return entry.get("terminal") is False


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
    """The command line of a drawn session (``'terminal': False``): the
    entry's ``command`` in the mode a program talks to it in, then what the
    preset passes a terminal session too. The first request goes in as a
    message, not on the command line.

    - Claude Code: its stream-json mode with its permission questions sent to
      XeFM; the skill, the rules, the settings.
    - Codex: its app-server. The rules and the skill go in as the session
      opens (:func:`protocol`).
    - Copilot: its ACP server; the skill and the denied commands (the rules
      are in the environment, :func:`session_env`).
    - Antigravity: its ACP server with the workspace that holds the rules and
      the skill. It takes no settings there, so XeFM declines the denied
      commands itself (:func:`refusal`)."""
    values = dict(values, **{"{prompt}": ""})
    out = [_fill(a, values) for a in entry["command"]]
    preset = entry.get("preset")
    if preset == CODEX:
        from xefm.agent_codex import app_server_argv
        return app_server_argv(out)
    if preset == COPILOT:
        out += ["--acp", "--plugin-dir", values["{plugin_dir}"], *_user_plugin_args(values)]
        if values.get("channel") is not None:
            # XeFM's own tools: XeFM asks, so Copilot does not ask as well.
            out.append(f"--allow-tool={values['channel'].name}")
        if entry.get("restrict", True):
            out += [f"--deny-tool={rule}" for rule in COPILOT_DENY_TOOLS]
        return out
    if preset == ANTIGRAVITY:
        return _without_options(out, ANTIGRAVITY_FIRST)[0] + [
            "acp", "--add-dir", values["workspace_dir"]]
    from xefm.agent_chat import CLAUDE_STREAM_ARGS
    out += list(CLAUDE_STREAM_ARGS)
    out += _mcp_config(values, "--mcp-config")
    out += ["--plugin-dir", values["{plugin_dir}"], *_user_plugin_args(values),
            "--append-system-prompt", drawn_rules(values["{rules}"]),
            "--settings", values["{settings_file}"]]
    return out


#: Antigravity's options that its ACP server does not read, set once the
#: session is open instead.
ANTIGRAVITY_FIRST = {"--model": "model", "--mode": "mode", "--effort": "effort"}


def _without_options(args: list[str], options: dict) -> tuple[list[str], dict]:
    """``args`` without ``options`` (``--model x`` or ``--model=x``), and
    their values by the name ``options`` gives them."""
    out: list[str] = []
    found: dict[str, str] = {}
    rest = iter(args)
    for arg in rest:
        name, eq, value = arg.partition("=")
        if name in options:
            found[options[name]] = value if eq else next(rest, "")
        else:
            out.append(arg)
    return out, found


def protocol(entry: dict, values: dict) -> Any:
    """How a drawn session of ``entry`` is driven (a
    :class:`xefm.agent_chat.Protocol`), with what it is handed as its session
    opens."""
    preset, channel = entry.get("preset"), values.get("channel")
    if preset == CODEX:
        from xefm.agent_codex import CodexProtocol
        told = dict(values, **{"{rules}": drawn_rules(values["{rules}"])})
        return CodexProtocol(refuse=refusal(entry), channel=channel, instructions=codex_instructions(told),
                             skills_roots=[values["{skills_dir}"]]
                             + ([values["{user_skills_dir}"]] if values.get("user_skills") else []))
    if preset == COPILOT:
        from xefm.agent_acp import AcpProtocol
        return AcpProtocol(refuse=refusal(entry), channel=channel, agent=entry["name"],
                           sandbox=sandbox_state(entry),
                           login=f"{entry['command'][0]} login", plain_commands=True,
                           restrict=entry.get("restrict", True))
    if preset == ANTIGRAVITY:
        from xefm.agent_acp import AcpProtocol
        return AcpProtocol(refuse=refusal(entry), channel=channel, agent=entry["name"],
                           sandbox=sandbox_state(entry),
                           login=f"{entry['command'][0]} acp --login",
                           restrict=entry.get("restrict", True),
                           first=_without_options(entry["command"], ANTIGRAVITY_FIRST)[1])
    from xefm.agent_chat import ClaudeProtocol
    return ClaudeProtocol(channel, sandbox=sandbox_state(entry))


def denied_commands(entry: dict) -> tuple[str, ...]:
    """The shell commands a drawn session of ``entry`` may not run:
    DENIED_COMMANDS for a restricted one, or what an Antigravity entry's own
    ``settings`` deny instead."""
    settings = entry.get("settings")
    if entry.get("preset") == ANTIGRAVITY and settings is not None:
        deny = (settings.get("permissions") or {}).get("deny") or []
        return tuple(m.group(1) for rule in deny if isinstance(rule, str)
                     and (m := re.fullmatch(r"command\((.+)\)", rule.strip())))
    return (*DENIED_COMMANDS, "xefmctl delete") if entry.get("restrict", True) else ()


def refusal(entry: dict) -> Any:
    """``refuse(command)``: why XeFM declines a shell command the agent asks
    to run, or None - the limits above, for the agents that take no such rule
    in the mode XeFM draws. Like the agents' own rules it goes by the name as
    typed, of each command on the line; it is not a sandbox."""
    denied = [name.lower().split() for name in denied_commands(entry)]
    if not denied:
        return None

    def refuse(command: str) -> str | None:
        for part in re.split(r"&&|\|\||[;|&\n(){}]", command):
            words = part.strip().lower().split()
            if not words:
                continue
            words[0] = re.split(r"[\\/]", words[0].strip("\"'"))[-1].removesuffix(".exe")
            for name in denied:
                if words[:len(name)] == name:
                    return (f"XeFM declined `{' '.join(part.split())}`: files are deleted and "
                            "moved through xefmctl, which asks you")
        return None
    return refuse


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
    text = (values["{rules}"]
            + "\n## The xefm skill\n\n"
            "XeFM handed this session its `xefm` skill: read "
            f"`{skill}/SKILL.md` before running xefmctl or changing XeFM's "
            "configuration, and resolve the paths it mentions against that "
            "folder.\n")
    mine = values.get("user_skills") or []
    if mine:
        text += ("\n## The user's skills\n\n"
                 "The user's own skills for XeFM sessions. When a task matches "
                 "one's description, read its SKILL.md first and resolve the "
                 "paths it mentions against its folder.\n\n")
        text += "".join(f"- {name}: {' '.join(description.split())} "
                        f"(file: {_FsPath(folder).as_posix()}/SKILL.md)\n"
                        for name, description, folder in mine)
    return text


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
