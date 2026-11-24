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

`agents.turned_off()` is `AGENTS` empty (`[]`, or `None`/`{}`): a config.py
without `AGENTS` gets the template's through `_copy_missing_fields`, so an
empty one was written on purpose. `_agent_menu` then leaves both Tools items
out of the menu it builds (rebuilt by `_rebuild_keymap` on a config reload,
as MenuItem has no visibility predicate), and `_agents_ready` logs that
agents are off rather than how to set one up.

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
   - `read`, `fetch`, `find-in-files` outside the local disk (a UNC path is
     outside): one question per session (`app._remote_read_sessions`).
   - `terminal-session close` of another session: confirmed.
   - `fetch` to a named file, `terminal-session start`, and `invoke` of
     `AGENT_ASKED_ACTIONS` (they run programs and have no confirmation of
     their own): `_ask_first`. The question shows all of the command or the
     paths, with nothing unprintable in it, or the request is refused
     (`ASK_LIMIT`, `ASK_ITEMS`). With the terminal handed over there is no
     screen to ask on, so these are refused (exit 6).
   - A session an agent starts gets the agent's policy
     (`app._new_session_policy`, read by `_start_session`): with the user's,
     a program in it could do through `xefmctl` what the agent may not.
   - `fetch` without a name writes into a new temporary folder under
     `_file_name`: a server's file name may hold what this OS takes for a
     separator.

   A command added to `remote_commands` that changes a file or runs a program
   has to do one of these. `test/test_agent_restrictions.py` holds them.
   An answer waiting for the user is acknowledged at once (`_late`), so the
   client does not time out on any of them.

An agent can still change files with its own tools where layer 1 does not
reach (another CLI, an editor tool writing a file). Layer 2 holds for
everything that goes through XeFM; the rules ask the agent to go through
XeFM.

## Conversations drawn by XeFM (`'terminal': False`, #959)

Step 2 of #880. Claude Code only, through its stream-json mode, which needs
nothing beyond the CLI the user installed (the ACP adapter would be an npm
package to install; the Agent SDK a dependency in the core, which #880
ruled out). ACP stays the candidate for other agents.

- `agents.normalize` takes `terminal` (a bool); its default is whether the
  preset is missing from `DRAWN_PRESETS`, so a preset is drawn as soon as
  it joins that tuple, and `False` with any other preset is refused. The
  key replaced `'ui': 'terminal' | 'xefm'` before it shipped (the app's
  name read oddly as a value, and drawn is meant to become the default);
  an entry still saying `ui` gets a message naming the new key. `agents.chat_argv` is `command` +
  `agent_chat.CLAUDE_STREAM_ARGS` (`-p --input-format stream-json
  --output-format stream-json --verbose --include-partial-messages
  --permission-prompt-tool stdio`) + the same `--plugin-dir`, rules and
  `--settings` a terminal session gets. The rules go through
  `drawn_rules`, which drops what speaks of a terminal. The first request is
  sent as a message, never on the command line.
- `xefm/agent_chat.py` (no UI): `ChatClient` runs the process (its own
  process group / `CREATE_NEW_PROCESS_GROUP`, so closing stops what its
  tools started; stdin closed, then SIGTERM to the group after 2 s), reads
  stdout on a thread and hands each JSON object to the UI thread through
  `post` (`XeFMApp._call_later`). It opens with the `initialize` control
  request, as Claude Code's SDKs do. `Conversation` folds the messages into
  `Item`s: `stream_event` deltas open and grow blocks per message id; the
  finished `assistant` blocks that follow are matched to them by position
  within the message (each arrives as an `assistant` message of its own,
  sharing the id); `user` tool results close tool items; `result` ends a
  turn (`pending_turns`: a message sent mid-turn queues in the CLI and gets
  its own `result`). `to_markdown` renders the items: a user message in
  a MarkdownView `::: box` (a rounded panel; a fill in a terminal, its fence
  longer than any colon run in the text), each thing the agent did in a
  `::: bullet <role>` whose dot is green for a tool that worked, red for one
  that failed or was declined, the accent while it runs, muted for text. A
  Bash call is one `console` block: the command after `$` (continuation lines
  after `>`), its output under it, the agent's `description` in the head.
- Typing aids in `ChatView`: `/` at the start of the message lists
  `_LOCAL_COMMANDS` plus `Conversation.commands` (the initialize answer:
  name, description, argumentHint); `@` lists `mention_paths()` (the app's
  `_agent_mention_paths`: selected files in both panes, else the cursors'),
  the folder named so far, and names from a file index walked once on a
  thread (`_SKIP_DIRS`, `_INDEX_LIMIT`). The list is `_Menu`, drawn over the
  field; Enter runs a command without an argument hint.
- Permission mode: Shift+Tab sends `set_permission_mode` (default ->
  acceptEdits -> plan); the CLI reports the mode in the initialize answer
  (`current_permission_mode`), `system init` and `system status`
  (`permissionMode`). A restart passes `--permission-mode` to keep it.
  `ExitPlanMode` gets its own dialog (`_agent_chat_plan`): Approve, Approve
  with accept edits (then `set_mode`), Keep Planning (a deny asking what to
  change).
- Links in the transcript with `LINK_SCHEME` (`xefm-agent:`) are the view's:
  `expand/N` and `collapse/N` toggle `Item.expanded` (up to
  `EXPANDED_LINES`), `diff/N` calls `on_diff` - the app's `_agent_chat_diff`,
  which undoes the edit on the file as it is now (`edit_before`) and opens
  that against the file in the diff viewer, or the two texts alone when the
  file has changed since. A tool result is clipped to `RESULT_LINES` and fenced with
  `~~~` when it holds a backtick fence itself. `ChatView` keeps about 5% of
  the width as a margin on each side.
- Subagents: a message with `parent_tool_use_id` comes from inside the
  `Agent` / `Task` call of that id (no `stream_event`s, only finished
  blocks). `Conversation._sub` nests its tool calls and text as
  `Item.children` of that call (registered in `_tools`, so their results and
  permission answers find them) and drops its prompt; `system
  task_progress` sets `Item.progress`. The transcript lists the latest
  `SUBAGENT_STEPS` under the call, the rest behind `expand/N`.
- Finished thinking with text folds to `[Thought ›](xefm-agent:expand/N)`;
  Claude Code often sends `thinking` blocks with an empty text and only a
  signature, which shows nothing.
- Context and model: `Conversation.context_tokens` is the last main-thread
  `assistant` usage (input + cache creation + cache read);
  `context_window` comes from the turn `result`'s `modelUsage[model]
  .contextWindow`. `models` is the initialize answer's list; `/model <value>`
  (a `_Menu` of kind `model`) sends `set_model`, whose answer carries the
  resolved `model` and whose refusal (`model_request`) becomes a notice.
  `model_choice` is passed as `--model` on a restart.
- Commands XeFM does not handle go to the CLI as a user message. Its reply
  is an `assistant` message with `model` `<synthetic>` (`SYNTHETIC_MODEL`):
  `Item.plain`, shown by `_plain_markdown` (punctuation escaped, hard
  breaks, inner runs of spaces as no-break spaces; a line's indent is lost,
  as MarkdownView strips it). `system notification` becomes a notice (an
  error when `color` is `error`). `/effort <level>` and fast mode
  (`system init` `fast_mode_state`, off again on the
  `fast-mode-overage-rejected` notification) last for the CLI's process
  only - checked in the session file, a resumed process went back to the
  default effort - so `_restart` passes `--effort` and, as there is no flag
  for it, sends `/fast on` as a turn of its own.
- The to-do list: `Conversation.todos()` is the last main-thread
  `TodoWrite`'s list while any of it is not completed; `ChatView._draw_todos`
  pins it over the field (in progress and after, `_TODO_ROWS`). The
  transcript's dots are joined by PuiKit's timeline line (MarkdownView
  `::: bullet` in a row).
- Permissions: `--permission-prompt-tool stdio` makes the CLI send a
  `control_request` `can_use_tool` wherever it would ask in its own UI; its
  settings (the deny list) decide first, so a denied `rm` never reaches
  XeFM. `XeFMApp._agent_chat_ask` answers with a `show_message_box` on the
  session's screen (`_on_screen_of` points the default layer parent at its
  group when it is hidden, and the status bar says it is asking).
  **Always Allow** returns the CLI's `permission_suggestions` with
  `destination` forced to `session`: XeFM never writes the user's or the
  project's settings. `AskUserQuestion` comes the same way and is answered
  with `updatedInput.answers` (question -> label, several joined with
  ", ") from one `agent_question_dialog.QuestionDialog` per question: radio
  rows, checkbox rows for `multiSelect`, an Other row with a field. The
  answers are kept in the tool item's input, so the transcript shows each
  question with its answer rather than the input as JSON. A `control_cancel_request` withdraws a question.
- `xefm/agent_chat_view.py`: `ChatView`, a full-window layer with the
  viewers' hints, header / `MarkdownView` transcript (`follow_end`, fed by
  `update_source`, which re-wraps only the changed tail) / PuiKit
  `TextArea` (`submit_on_enter`) / status bar. It duck-types what
  `Session` reads from a terminal view (`running`, `busy`, `exit_code`,
  `shown`, `closing`, `close`, `start`) plus `chat_state`, which
  `Session.state` reports for kind `AGENT`. Keys a binding in the
  `terminal` context takes win, as in the terminal (`terminal.close`,
  `terminal.screens`, user actions there).
- The app: `_start_agent` branches to `_start_agent_chat` for a drawn entry,
  in both modes (no `_terminal_ready`, no hand-over). The session registry
  and screens are the terminal sessions' own, so the switcher, `xefmctl
  terminal-session list`, the quit check (`busy` = mid-turn) and remote
  dispatch's "back to the asking screen" work unchanged. `screens` works in
  terminal mode when there is a drawn session or entry. `_agent_chat_for`
  sends the agent key back to a live session of the same entry in the same
  folder. When the process ends unasked, the transcript stays and the next
  message restarts it with `--resume <session_id>`.

Checked against Claude Code 2.1.323: the event shapes in
`test/test_agent_chat.py`'s stand-in CLI were taken from a real run; a live
run with the preset's argv loaded the plugin (`xefm:xefm`), followed the
rules, and had `rm` denied by the settings without asking.

Open: the terms-of-use check #880 asks for before this leaves Preview;
other agents (ACP); per-tool rendering beyond Bash/Read/Edit/TodoWrite;
images in the conversation; effort; resuming an older conversation;
editing or rewinding a message.

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
- #880's step 3: proposals confirmed in XeFM's own dialogs beyond
  copy/move/trash. (Step 2, the drawn conversation, is above.)

## Tests

`test/test_agent_chat.py`: the conversation folding, the transcript, the
answers, `terminal` checking and `chat_argv`, the client and the view against a
stand-in CLI, and `agent` opening (and going back to) a drawn session in
both modes.

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
