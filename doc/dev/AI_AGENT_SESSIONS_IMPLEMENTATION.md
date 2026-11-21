# AI agent sessions: Implementation

`AGENTS`, `agent`, `ask_agent` (discussion #880, the "open an agent
here" step, made concrete in #952). User documentation:
[AI_AGENT_SESSIONS_FEATURE.md](../AI_AGENT_SESSIONS_FEATURE.md).

## Shape

XeFM runs an agent CLI the user installed and signed in to, as it runs an
editor: no SDK, no credentials, no provider. What it adds is what the agent
needs to work *in XeFM*: the skill, the rules, and limits it cannot talk
its way around.

- `xefm/agents.py`: `AGENTS` normalized (`entries`, `normalize`), the rules
  (`DEFAULT_RULES` + `AGENT_RULES`), the files a session is handed
  (`prepare`), the command line (`argv`), and `ask_agent`'s request with its
  context (`prompt_with_context`).
- `XeFMApp.open_agent` / `ask_agent` / `_pick_agent` / `_start_agent`: pick
  the entry (a `ctx.choose` when there are several), prepare, build the
  argv, take `_program_env` for the active pane (the home directory when it
  shows a remote place or a list), and start it: `_start_session(...,
  policy=)` on the desktop, `_run_in_terminal` after `_with_remote_env(env,
  "agent", policy)` in terminal mode.
- The policy rides the session key (see
  [XEFMCTL_IMPLEMENTATION.md](XEFMCTL_IMPLEMENTATION.md)): `agent` for an
  entry with `restrict` (the default), `user` without.

## Entry points and availability

Opening an agent parallels opening a shell: the action `agent` (`>` in
every preset: the prompt an agent's CLI shows, a glyph no type-ahead takes)
beside `subshell`, **Tools > AI Agent Here** beside Subshell Here, and a
"New <agent> in <dir>" row per installed entry in the Screens switcher
beside "New shell in <dir>".

`agents.available()` is the entries whose program `shutil.which` finds.
The menu items' `enabled` asks it each time the menu opens (cheap, and a
fresh install counts without a restart); `_agents_ready()` says in the log
why nothing can start, for a key or the palette, which a greyed menu item
cannot explain.

`ask_agent` is a filter list of `agents.prompts()` - `AGENT_PROMPTS`, name
-> request or `{prompt, agent}`, config.py's and the extensions'
(`[contributes.agent_prompts]`, merged like any dict table) - with
`on_accept_text` for a request typed instead. A prompt's `agent` picks its
entry without asking. A contributed prompt is text: `_value_for` returns
it as is and `Manifest.references()` skips the kind, so a colon in it is
never taken for `module:name`.

## What a session is handed

`prepare()` writes under `~/.xefm/cache/agents/<skill_version>/`:

- `plugin/`: the `xefm` skill as a Claude Code plugin -
  `.claude-plugin/plugin.json` and `skills/xefm/` (`extensions._skill_files`,
  the version token resolved). Rewritten on every launch through
  `plugin.tmp` and a rename: a development tree keeps its version while the
  skill changes, and a session already running has read its copy.
- `sessions/rules.md`: the rules. They name the skill (`xefm:xefm` in Claude
  Code): a copy of an older `xefm` skill installed in the agent's own
  folders, or uploaded to the user's account, is listed beside it.
- `sessions/settings-<name>.json`: the entry's `settings`, else
  `CLAUDE_DEFAULT_SETTINGS` for a restricted entry (deny `rm`, `rmdir`,
  `unlink`, `shred`, `mv`, `trash`, `srm`, `git clean`, `xefmctl delete`),
  else `{}`.

The placeholders' values (`{plugin_dir}`, `{skills_dir}`, `{skill_dir}`,
`{rules}`, `{rules_file}`, `{settings_file}`, `{prompt}`) are filled into
`command` and `prompt_args` by plain replacement, so a brace elsewhere in
an argument is left alone.

The `claude-code` preset appends `--plugin-dir`, `--append-system-prompt`
(the rules as text: Claude Code 2.1 has no `-file` form of it),
`--settings`, and the request as the last argument (`claude "request"`
starts an interactive session with it).

The `codex` preset appends `-c developer_instructions=<TOML string>` and
the request as the last argument (`codex "request"` starts the TUI with
it). Codex (0.171) has no option that adds a skills folder: `skills.config`
only enables or disables skills Codex already found, and its user folder
`~/.agents/skills` is global. So the instructions (`codex_instructions`)
are the rules plus a paragraph naming `{skill_dir}/SKILL.md` - the same
thing Codex's own skill list gives the model, a name and a path to read.
The value is always written as a quoted TOML string (`_toml_string`):
`-c` takes an unparsable value raw, but rules that happened to parse as
TOML would be silently changed. It replaces a `developer_instructions` in
the user's `~/.codex/config.toml` for the session; `AGENTS.md` still
applies. Codex is a native `codex.exe` on Windows (the standalone
installer), so the multi-line request reaches it intact; an npm install's
`codex.cmd` goes through cmd.exe, which cuts an argument at its first
newline.

The `copilot` preset (GitHub Copilot CLI 1.0.114) appends `--plugin-dir`
(Copilot loads the Claude Code plugin folder as is: `copilot --plugin-dir
<dir> skill list` lists `xefm` as a plugin skill), a `--deny-tool=` per
`COPILOT_DENY_TOOLS` for a restricted entry, and `-i <request>` (interactive,
starting with the request; `-p` would exit after it). Copilot matches a
shell rule by the command name as typed, aliases not included, so the list
names PowerShell's `Remove-Item`, `ri`, `del`, `erase`, `rd`, `Move-Item`,
`mi`, `move` beside the POSIX names; `xefmctl delete` is left to XeFM, which
refuses it (a `shell(xefmctl)` rule would deny every xefmctl command).
Copilot has no option for system-prompt text, so the rules go in
`sessions/instructions/xefm.instructions.md` with `applyTo: "**"`, a folder
`session_env` appends to `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` (after the
user's own, comma-separated). An `AGENTS.md` in that folder is listed as a
"nested" one, read only when the agent works under it, and a
`.github/copilot-instructions.md` there is not read at all; an
`*.instructions.md` file is. `--no-custom-instructions` in the user's
`command` turns the rules off.

The `antigravity` preset (Antigravity CLI `agy` 1.5.14, Gemini CLI's
successor) appends `--add-dir <workspace>`, `--settings <settings file>`
and `-i <request>`. Antigravity has no option for a skills folder or for
system-prompt text, but it reads a workspace's `AGENTS.md` (always on, no
frontmatter) and `.agents/skills/`, and a folder added with `--add-dir`
counts: `prepare` writes `sessions/antigravity/` with the rules as
`AGENTS.md` and a copy of the skill under `.agents/skills/xefm/`.
`--settings` takes a session-only settings JSON (inline or a file; it is in
`agy --help` though not in the online reference); a restricted entry gets
`ANTIGRAVITY_DEFAULT_SETTINGS`, `permissions.deny` of `command(<name>)` for
each of `DENIED_COMMANDS` (the list Copilot's rules are made from too), and
the entry's own `settings` replace it. A deny rule wins over an allow:
with `command(hostname)` in both, agy answered "Permission denied for
command(hostname). Matches user-configured deny rule."

Checked against the real CLIs. Codex: `codex debug prompt-input`, which
prints the model-visible input without calling the model: the rules arrive
as a developer message and the request whole. Copilot: a `-p` run answered
from the rules and quoted the skill, and `rm` was denied with
`--allow-all-tools` on; on a ConPTY the session loaded "1 instruction, 1
plugin" and answered a two-line request after the folder-trust question.
Antigravity: a `-p` run with the workspace answered from the rules and
named the skill; on a ConPTY, from a trusted folder, the preset's argv
answered from the rules, listed `xefm` and quoted a two-line request.

## The two hard layers

1. **The agent's own permissions** (Claude Code: the settings file above;
   Copilot: the `--deny-tool` rules; Antigravity: its `--settings` file).
   Only the preset knows how to say it; other agents get `{settings_file}`
   to pass if their CLI has an equivalent. Codex 0.171 has no
   command-line option that denies a command: its sandbox and approvals
   apply as configured.
2. **XeFM's** (any agent): in `remote_dispatch`, for policy `agent`:
   - `copy`, `move`, `trash`: the operation's own confirmation, shown
     whatever `CONFIRM_*` says (`_ALWAYS_CONFIRM` forced for the call, read
     when the operation starts). The question is the operation's, naming
     what and where; a separate "the agent wants to..." dialog asked the
     same thing twice. The user is taken to the file manager for it and
     back when the operation ends or is declined (its `on_done`).
   - `delete`, and `invoke` of `delete_permanently`, `quit`, `quit_app`:
     refused (exit 5).
   - `invoke`: run with `AGENT_FORCED_SETTINGS` set on `app.config` (every
     `CONFIRM_*` on, `DELETE_TO_TRASH` on) for the synchronous part, where
     the actions read them.
   - `read`, `fetch` outside the local disk: one `ctx.confirm` per session
     (`app._remote_read_sessions`).
   - `terminal-session close` of another session: confirmed.

An agent can still change files with its own tools where layer 1 does not
reach (another CLI, an editor tool writing a file). Layer 2 holds for
everything that goes through XeFM; the rules ask the agent to go through
XeFM.

## Knowledge of extensions

`xefmctl action list` gives each action's summary, context, keys and source
(`extension <id>` via `extensions.package_of(func)`, `config.py`, or
`builtin`); `action show` adds `details` and the package's
`[extension] agent_guide` (Preview manifest key; checked to be a file in
the package). `xefm ext guide <id>` prints the guide without a running
XeFM, and `xefm ext check` warns about an action with neither a description
nor a docstring (read with `ast`, not imported).

## Not yet

- Built-in presets beyond Claude Code, Codex, Copilot and Antigravity: the wiki page "AI agents"
  for now, kept up by their users (CLAUDE.md, "Core or extension?").
- #880's later steps: answers shown in XeFM rather than a terminal
  session, proposals confirmed in XeFM's own dialogs beyond copy/move/trash.

## Tests

`test/test_terminal_sessions.py`: the `codex` preset (the TOML value
parsed back, the skill path, the request last, the default `AGENTS`), the
`copilot` preset (plugin folder, deny rules and `restrict: False`, `-i`,
the instructions file and the folder added to the user's own), the
`antigravity` preset (the workspace with `AGENTS.md` and the skill, the
settings file, the entry's `settings`, `restrict: False`),
`agent` (argv, the plugin folder,
the rules with `AGENT_RULES`, the settings, the `agent` policy, the session
and its screen), `ask_agent` (the request with the selection, placeholders,
`restrict: False`), entry checking; the policy tests named in
XEFMCTL_IMPLEMENTATION.md. `test/test_agent_guide.py`: the manifest key and
the description warning.
