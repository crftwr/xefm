# AI agent sessions

English \| [日本語](AI_AGENT_SESSIONS_FEATURE.ja.md)

XeFM can open an AI coding agent beside the file manager, as a
[terminal session](TERMINAL_FEATURE.md) of its own. The agent knows it runs
inside XeFM: it can see what you are looking at, search anywhere XeFM can go,
show you what it found, and ask you before it changes a file.

| Action | Menu |
|--------|------|
| `open_agent` | Tools → Open AI Agent… |
| `ask_agent` | Tools → Ask AI Agent… |

Both ship unbound; to give them keys, see [Key Bindings](KEY_BINDINGS_FEATURE.md).

## What you need

An agent's command-line program, installed and signed in to on its own:
XeFM starts it the way it starts an editor, and never sees its account,
credentials or model. Claude Code (`claude`) is set up out of the box; other
agents are on the wiki (see [Other agents](#other-agents)).

## Opening a session

- **Open AI Agent…** (`open_agent`) starts the agent in the active pane's
  directory. Ask it anything; it reads what XeFM shows when you say "this
  file" or "these".
- **Ask AI Agent…** (`ask_agent`) asks for a request first, then starts the
  agent with it, the directory, and the selected items (or the item under
  the cursor).

With more than one agent set up, XeFM asks which one. The session gets a
screen of its own, like any terminal session: **Screens…** switches between
it and the file manager, and it keeps running while you are away. In the
screen switcher, its row shows what the agent calls itself in its title
(`✳ Claude Code`).

In terminal mode, XeFM hands the agent its terminal and waits, as it does
for the subshell. While the agent runs there, XeFM answers what it asks
about the panes and its searches, but cannot show it anything or ask you
anything: those need the desktop app.

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
- **The agent's own shell is limited** (Claude Code): the commands that
  delete or move files (`rm`, `rmdir`, `mv`, `unlink`, `shred`, `git clean`)
  are denied in its permission settings, so those changes go through
  `xefmctl`.

To lift both, for an agent you trust with your files, set `'restrict':
False` on its entry.

## Setting up agents: `AGENTS`

```python
AGENTS = [
    {'name': 'Claude Code', 'command': ['claude'], 'preset': 'claude-code'},
]

# Your own rules, added after XeFM's in every session.
AGENT_RULES = "Never touch ~/Documents/Taxes. Answer in Japanese."
```

| Key | What it is |
|---|---|
| `name` | Its name in the menu and the screen switcher |
| `command` | The program and its arguments, a list (or a string, split like a shell would) |
| `preset` | `'claude-code'`: XeFM adds the arguments that hand Claude Code the skill, the rules and its permission settings |
| `restrict` | `True` (the default): the limits above. `False`: none |
| `settings` | Claude Code only: the settings to pass instead of XeFM's, e.g. `{'permissions': {'deny': ['Bash(rm:*)']}}` |
| `env` | Extra environment variables |
| `prompt_args` | Without a preset: what `ask_agent` adds for the request (default `['{prompt}']`) |

To pass Claude Code more options, add them to `command`:
`['claude', '--model', 'opus']`.

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
