# AI agent sessions

English \| [日本語](AI_AGENT_SESSIONS_FEATURE.ja.md)

XeFM can open an AI coding agent beside the file manager, as a
[terminal session](TERMINAL_FEATURE.md) of its own. The agent knows it runs
inside XeFM: it can see what you are looking at, search anywhere XeFM can go,
show you what it found, and ask you before it changes a file.

| Action | Menu |
|--------|------|
| `agent` | Tools → AI Agent Here |
| `ask_agent` | Tools → Ask AI Agent… |

`agent` is `>` in every keymap preset, the prompt an agent's command line shows; `ask_agent` ships unbound. To change them, see [Key Bindings](KEY_BINDINGS_FEATURE.md) and [Keymap Presets](KEYMAP_PRESETS_FEATURE.md).

## What you need

An agent's command-line program, installed and signed in to on its own:
XeFM starts it the way it starts an editor, and never sees its account,
credentials or model. Claude Code (`claude`), Codex (`codex`), GitHub
Copilot CLI (`copilot`) and Antigravity CLI (`agy`, which replaced Gemini
CLI) are set up out of the box; other agents are on the wiki (see
[Other agents](#other-agents)).

## Opening a session

- **AI Agent Here** (`agent`) starts the agent in the active pane's
  directory. Ask it anything; it reads what XeFM shows when you say "this
  file" or "these".
- **Ask AI Agent…** (`ask_agent`) asks for a request first - one of your
  [saved requests](#saved-requests-agent_prompts), or one you type - then
  starts the agent with it, the directory, and the selected items (or the
  item under the cursor).

Both are off in the menu while no agent in `AGENTS` is installed (its
program is not on `PATH`); from a key or the command palette, the log pane
says which program is missing. They come on once it is installed, with no
restart.

To turn agent sessions off, set `AGENTS = []` in `config.py`: the two
items leave the menu, no agent can start, and `agent` and `ask_agent` only
say in the log pane that agents are off. To free the `>` key as well, unbind
`agent` (see [Key Bindings](KEY_BINDINGS_FEATURE.md)).

With more than one agent set up, XeFM asks which one. The **Screens…**
switcher also has a row for each, **New Claude Code in ~/...**, beside **New
shell in ~/...**. The session gets a
screen of its own, like any terminal session: **Screens…** switches between
it and the file manager, and it keeps running while you are away. In the
screen switcher, its row shows what the agent calls itself in its title
(`✳ Claude Code`).

In terminal mode, XeFM hands the agent its terminal and waits, as it does
for the subshell. While the agent runs there, XeFM answers what it asks
about the panes and its searches, but cannot show it anything or ask you
anything: those need the desktop app, or a
[conversation drawn by XeFM](#conversations-drawn-by-xefm), which keeps
XeFM's screen in terminal mode too.

## Conversations drawn by XeFM

Claude Code can also run without a terminal: with `'ui': 'xefm'` on its
entry, XeFM draws the conversation itself, on a screen of its own. It looks
and works the same in the desktop app and in terminal mode. In terminal mode
the agent no longer takes the terminal over, so it can show you things and
XeFM can ask you things there too.

```python
AGENTS = [
    {'name': 'Claude Code', 'command': ['claude'], 'preset': 'claude-code', 'ui': 'xefm'},
]
```

The screen has the agent, its folder and what it is doing at the top, the
conversation in the middle, and the field you type in at the bottom. Each
tool the agent uses shows as one line - the command, the file, the pattern -
with the first lines of what it returned.

| Key | What it does |
|---|---|
| `Enter` | Send the message. One sent while the agent works waits for its turn to end |
| `Alt+Enter`, `Shift+Enter`, `Ctrl+J` | A new line in the message (a terminal cannot send `Shift+Enter`; the other two work everywhere) |
| `Esc` | Stop the agent while it works; otherwise go back to the file manager, the session kept |
| `↑` / `↓` | On the first (last) line of the field: an earlier (later) message you sent |
| `PageUp` / `PageDown` | Scroll the conversation (so does the wheel) |

Type `/clear` to start a new conversation, and `/exit` to end the session.

- **The agent asks in XeFM.** When the agent wants to run a tool that needs
  your permission, XeFM asks: **Allow**, **Always Allow** (the same kind of
  command, for the rest of this session; nothing is written to your
  settings) or **Deny**. When the agent asks you to choose between options,
  XeFM shows each question with its options - one to pick, or checkboxes
  where several may be chosen - and a field for an answer of your own. The confirmations of
  [What the agent may not do](#what-the-agent-may-not-do) apply as in any
  agent session.
- **Back to the session.** **AI Agent Here** in the same folder goes back to
  the session there instead of starting another; **Screens…** lists it too,
  in terminal mode as well. While you are away, the status bar says when the
  agent is asking you something or has finished.
- **Links.** A link in the agent's reply to a file or folder on this
  computer opens it in the active pane.
- **If the agent stops** (it crashed, or you ended it outside XeFM), the
  conversation stays on screen; `Enter` starts it again in the same
  conversation.

Only Claude Code can be drawn for now, and this is Preview. XeFM runs your
own `claude` in its non-interactive mode (`claude -p`, with its streaming
JSON input and output), signed in as you set it up: what that use counts
against is between you and your Claude Code plan, as it is in a terminal.

## What the agent gets

- **The `xefm` skill**, of the very XeFM it runs in: how to use
  [`xefmctl`](XEFMCTL_FEATURE.md), how XeFM's configuration and extensions
  work. Nothing is installed in the agent's own folders; each session is
  handed the skill when it starts.
- **Rules** for working inside XeFM: start with `xefmctl state`; read what
  you see rather than guessing; change files only through `xefmctl`, so that
  you confirm each change; never delete for good; show results in XeFM.
  Your own rules come after XeFM's (`AGENT_RULES`).
- **[`xefmctl`](XEFMCTL_FEATURE.md)**, with a key that tells XeFM the request
  comes from this agent's session.

## What the agent may not do

Rules can be ignored, so two things hold whatever the agent decides:

- **XeFM confirms every change.** A copy, move or trash asked for through
  `xefmctl` shows that operation's own confirmation in XeFM, listing the
  items, even where your `CONFIRM_*` settings turned it off; it goes ahead
  only if you allow it, and XeFM takes you back to the agent once it is done
  or declined.
  `xefmctl delete` is refused (the trash can be undone), and so is the
  `delete_permanently` action. An action the agent runs with `xefmctl
  invoke` asks first too, and deletes to the trash. The first time the agent
  reads somewhere off this computer's disk - a server, cloud storage, an
  archive - XeFM asks whether it may, for the rest of the session.
- **The agent's own shell is limited** (Claude Code, Copilot, Antigravity):
  the commands that delete or move files (`rm`, `rmdir`, `mv`, `unlink`,
  `shred`, `git clean`, and for Copilot and Antigravity PowerShell's
  `Remove-Item`, `Move-Item`, `del` and their kin) are denied in its permission settings, so those changes go
  through `xefmctl`. Codex has no such setting to pass: its own sandbox and
  approvals decide what its shell may run, as they do outside XeFM.

To lift both, for an agent you trust with your files, set `'restrict':
False` on its entry.

## Setting up agents: `AGENTS`

```python
AGENTS = [
    {'name': 'Claude Code', 'command': ['claude'], 'preset': 'claude-code'},
    {'name': 'Codex', 'command': ['codex'], 'preset': 'codex'},
    {'name': 'Copilot', 'command': ['copilot'], 'preset': 'copilot'},
    {'name': 'Antigravity', 'command': ['agy'], 'preset': 'antigravity'},
]

# Your own rules, added after XeFM's in every session.
AGENT_RULES = "Never touch ~/Documents/Taxes. Answer in Japanese."
```

| Key | What it is |
|---|---|
| `name` | Its name in the menu and the screen switcher |
| `command` | The program and its arguments, a list (or a string, split like a shell would) |
| `preset` | `'claude-code'`: XeFM adds the arguments that hand Claude Code the skill, the rules and its permission settings. `'codex'`: XeFM hands Codex the rules, which tell it where the skill is. `'copilot'`: XeFM hands GitHub Copilot CLI the skill, the rules and the commands it may not run. `'antigravity'`: XeFM hands Antigravity CLI the skill, the rules and its permission settings |
| `restrict` | `True` (the default): the limits above. `False`: none |
| `settings` | Claude Code and Antigravity: the settings to pass instead of XeFM's, in that agent's own form, e.g. `{'permissions': {'deny': ['Bash(rm:*)']}}` for Claude Code, `{'permissions': {'deny': ['command(rm)']}}` for Antigravity |
| `env` | Extra environment variables |
| `prompt_args` | Without a preset: what `ask_agent` adds for the request (default `['{prompt}']`) |
| `ui` | `'terminal'` (the default): the agent's own screen in a terminal session. `'xefm'`: [the conversation drawn by XeFM](#conversations-drawn-by-xefm) (Claude Code only) |

To pass the agent more options, add them to `command`:
`['claude', '--model', 'opus']`.

The `codex` preset sets Codex's `developer_instructions` for the session,
so one in your `~/.codex/config.toml` is not used there; put what you want
every session to know in `AGENT_RULES` (or Codex's own `AGENTS.md`).

Copilot and Antigravity ask whether you trust a folder the first time they
start there; answer it in the session.

A `config.py` that has its own `AGENTS` keeps it: add the Codex, Copilot or
Antigravity line to it to get that agent.

### Saved requests: `AGENT_PROMPTS`

Requests you make often, listed in **Ask AI Agent…**: pick one, or type
your own. The agent gets the directory and the selection with it, so
"these files" means what you selected.

```python
AGENT_PROMPTS = {
    'Summarize': 'Summarize these files, a few lines each.',
    'Sort photos by month': 'Move these photos into folders named YYYY-MM by the date taken.',
    'Review': {'prompt': 'Review the uncommitted changes here.', 'agent': 'Claude Code'},
}
```

A request is a string, or a table with `prompt` and `agent` (the `name` of
an `AGENTS` entry, to send it there without asking). The config template
has more examples, commented out. [Extension packages](EXTENSIONS_FEATURE.md)
can add their own (`[contributes.agent_prompts]`). `AGENT_PROMPTS` is
Preview.

### Other agents

An agent without a preset is given what it needs through placeholders in
`command` (and `prompt_args`), which XeFM fills in when it starts the
session:

| Placeholder | Becomes |
|---|---|
| `{skills_dir}` | A skills folder holding the `xefm` skill (`xefm/SKILL.md`) |
| `{skill_dir}` | The `xefm` skill's own folder |
| `{plugin_dir}` | The same skill as a Claude Code plugin folder |
| `{rules}` / `{rules_file}` | The rules, as text / in a Markdown file |
| `{settings_file}` | A JSON file of the `settings` given (empty without them) |
| `{prompt}` | The request, for `ask_agent` |

Each agent takes these in its own way. The wiki page
[AI agents](https://github.com/crftwr/xefm/wiki/AI-agents) collects entries
for other agents, written and kept up by the people who use them. XeFM's
own limits on `xefmctl` apply to every agent.

## See also

- [xefmctl](XEFMCTL_FEATURE.md): the commands an agent uses
- [The XeFM skill for AI agents](AGENT_SKILL_FEATURE.md): installing the skill for an agent you run yourself
- [Terminal](TERMINAL_FEATURE.md): terminal sessions and screens
