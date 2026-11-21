# AI agent sessions: Implementation

`AGENTS`, `open_agent`, `ask_agent` (discussion #880, the "open an agent
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

## What a session is handed

`prepare()` writes under `~/.xefm/cache/agents/<skill_version>/`:

- `plugin/`: the `xefm` skill as a Claude Code plugin -
  `.claude-plugin/plugin.json` and `skills/xefm/` (`extensions._skill_files`,
  the version token resolved). Rewritten on every launch through
  `plugin.tmp` and a rename: a development tree keeps its version while the
  skill changes, and a session already running has read its copy.
- `sessions/rules.md`: the rules.
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

## The two hard layers

1. **The agent's own permissions** (Claude Code): the settings file above.
   Only the preset knows how to say it; other agents get `{settings_file}`
   to pass if their CLI has an equivalent.
2. **XeFM's** (any agent): in `remote_dispatch`, for policy `agent`:
   - `copy`, `move`, `trash`: `ctx.confirm` naming the session and listing
     the items first, whatever `CONFIRM_*` says; the user is taken to the
     file manager for it and back once answered.
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

- Built-in presets for other agents: the wiki page "AI agents" for now,
  kept up by their users (CLAUDE.md, "Core or extension?").
- #880's later steps: answers shown in XeFM rather than a terminal
  session, proposals confirmed in XeFM's own dialogs beyond copy/move/trash.

## Tests

`test/test_terminal_sessions.py`: `open_agent` (argv, the plugin folder,
the rules with `AGENT_RULES`, the settings, the `agent` policy, the session
and its screen), `ask_agent` (the request with the selection, placeholders,
`restrict: False`), entry checking; the policy tests named in
XEFMCTL_IMPLEMENTATION.md. `test/test_agent_guide.py`: the manifest key and
the description warning.
