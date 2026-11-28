# AI agent sessions

English \| [日本語](AI_AGENT_SESSIONS_FEATURE.ja.md)

XeFM can open an AI coding agent beside the file manager, on a screen of
its own: for Claude Code, Codex, Copilot and Antigravity, a
[conversation XeFM draws](#conversations-drawn-by-xefm); for the other agents,
or where you prefer it, a [terminal session](TERMINAL_FEATURE.md) running the
agent's own screen. The agent knows it runs
inside XeFM: it can see what you are looking at, search anywhere XeFM can go,
show you what it found, and ask you before it changes a file.

| Action | Menu |
|--------|------|
| `agent` | Tools → AI Agent |
| `new_agent` | Tools → New AI Agent Here |
| `resume_agent` | Tools → Resume AI Conversation… |
| `ask_agent` | Tools → Ask AI Agent… |

`agent` is `>` in every keymap preset, the prompt an agent's command line shows; `new_agent`, `resume_agent` and `ask_agent` ship unbound. To change them, see [Key Bindings](KEY_BINDINGS_FEATURE.md) and [Keymap Presets](KEYMAP_PRESETS_FEATURE.md).

## What you need

An agent's command-line program, installed and signed in to on its own:
XeFM starts it the way it starts an editor, and never sees its account,
credentials or model. Claude Code (`claude`), Codex (`codex`), GitHub
Copilot CLI (`copilot`) and Antigravity CLI (`agy`, which replaced Gemini
CLI) are set up out of the box; other agents are on the wiki (see
[Other agents](#other-agents)).

## Opening a session

- **AI Agent** (`agent`) goes back to the agent session you used last. With
  none open, it starts the agent in the active pane's directory. Ask it
  anything; it reads what XeFM shows when you say "this file" or "these".
- **New AI Agent Here** (`new_agent`) starts another session in the active
  pane's directory, even when one is open.
- **Ask AI Agent…** (`ask_agent`) asks for a request first - one of your
  [saved requests](#saved-requests-agent_prompts), or one you type - then
  starts the agent with it, the directory, and the selected items (or the
  item under the cursor).

They are off in the menu while no agent in `AGENTS` is installed (its
program is not on `PATH`); from a key or the command palette, the log pane
says which program is missing. They come on once it is installed, with no
restart.

To turn agent sessions off, set `AGENTS = []` in `config.py`: the
items leave the menu, no agent can start, and `agent`, `new_agent` and
`ask_agent` only say in the log pane that agents are off. To free the `>` key as well, unbind
`agent` (see [Key Bindings](KEY_BINDINGS_FEATURE.md)).

With more than one agent set up, XeFM asks which one; the `+` after the
window's tabs offers each, **New Claude Code**, beside **New Shell**. The
session gets a screen of its own, like any terminal session,
and keeps running while you are away. It is one of the window's tabs, as a
shell is, marked `✦`: `agent` comes back to the agent session you used
last, and **Switch Screen** goes between it and the file manager (see
[Terminal](TERMINAL_FEATURE.md#in-the-desktop-app-terminal-sessions-and-screens)).
The conversation's screen keeps the menu bar (in a terminal, `F10` opens
it), the tabs and the status bar, which says the keys that work there; the
command palette opens on its key too.

### A name for each session

A session is named after what it is about, so a list of them says at a
glance which one to go back to and which one can go. Once its first turn is
over, it takes the title the agent gives the conversation, where the agent
gives one, or else the start of your first request (**Fix the login bug**).
For an agent in a terminal session, it is the first title the agent sets
that says more than its own name. The name then stays: it is what the
session's tab and its row in **Screens…** show, and only you change it, with
the rename key (`rename_list_item`) in **Screens…**. What the agent is doing
now is shown beside it.

### Closing loses nothing

A conversation [drawn by XeFM](#conversations-drawn-by-xefm) that you close
is kept. **Tools → Resume AI Conversation…** (`resume_agent`) lists the ones
you closed - this run's and earlier ones', the last 20 - by name, with the
agent and when you closed it; pick one to start the agent on that
conversation again, in its folder, with what was said so far on screen. The
remove key forgets one; the rename key renames it.

So closing an agent that is not in the middle of a turn does not ask: `/exit`,
`terminal.close`, `Ctrl-D` on an empty message, the remove key in
**Screens…**, and **Close N idle sessions** there all close it at once. An
agent in a terminal session runs its own program, which XeFM cannot take
back to a conversation; closing it still asks first.

For an agent in a terminal session, terminal mode hands it XeFM's terminal
and waits, as it does for the subshell. While the agent runs there, XeFM answers what it asks
about the panes and its searches, but cannot show it anything or ask you
anything: those need the desktop app, or a
[conversation drawn by XeFM](#conversations-drawn-by-xefm), which keeps
XeFM's screen in terminal mode too.

## Conversations drawn by XeFM

For Claude Code, Codex, Copilot and Antigravity (the agents with a
`preset`), XeFM draws the conversation itself, on a screen of its
own, rather than running the agent's own screen in a terminal. It looks
and works the same in the desktop app and in terminal mode, whichever the
agent. In terminal mode
the agent does not take the terminal over, so it can show you things and
XeFM can ask you things there too. An agent without a preset runs in a
terminal session. Where the agents differ is listed
[below](#differences-between-the-agents).

To have the agent's own screen in a terminal session instead, set
`'terminal': True` on its entry:

```python
AGENTS = [
    {'name': 'Claude Code', 'command': ['claude'], 'preset': 'claude-code', 'terminal': True},
]
```

The screen has the agent, its folder and what it is doing at the top, the
conversation in the middle, and the field you type in at the bottom. What
you wrote is on a panel; each step the agent takes follows with a dot - green
for a tool that worked, red for one that failed or that you declined. A tool
shows as one line - the file, the pattern - with the first lines of what it
returned, and **… more lines** under it shows the rest (**show less** folds it
again). A shell command and its output read as in a terminal, in one block.
An edit shows its first changed lines, and **open diff** opens the whole file,
before the edit and now, in the diff viewer. A thin line joins the dots of
steps that follow one another.

- **Subagents.** A subagent's own steps show under the step that started it,
  one line each - the latest few, with **… earlier steps** opening the rest -
  and what it says it is doing while it runs.
- **Thinking.** **Thought ›** opens what the agent thought before it
  answered, when the agent sends that text (Claude Code often sends only that
  it thought).
- **The to-do list.** While the agent works through a to-do list, the list
  stays over the field you type in - the step in progress and those after it,
  the finished ones counted - until all of it is done.
- **The model and the context.** The header shows the model and how full the
  conversation's context is. `/model` lists the models the session offers;
  pick one to switch to it. It stays picked if the agent is started again.
  `/effort` sets how hard the model thinks, where it can be set.

| Key | What it does |
|---|---|
| `Enter` | Send the message. One sent while the agent works waits for its turn to end |
| `Shift+Enter`, `Ctrl+J`, `Alt+Enter` | A new line in the message. The status bar names `Shift+Enter` in the desktop app and `Ctrl+J` in a terminal, which every terminal sends; many terminals cannot send `Shift+Enter`, and `Alt+Enter` is Windows Terminal's full-screen key and needs Option sent as Meta on a Mac |
| `Esc` | Stop the agent while it works, or clear a selection in the conversation. It does not leave the tab: go back to the file manager with its tab or `` Ctrl-` `` |
| `↑` / `↓` | On the first (last) line of the field: an earlier (later) message you sent |
| `PageUp` / `PageDown` | Scroll the conversation (so does the wheel) |
| `Shift+Tab` | The next permission mode: ask before tools, accept edits (file changes go ahead without asking), plan (the agent looks and plans but changes nothing). The header shows the mode |

**Commands and files.** Type `/` at the start of the message to list the
session's commands - XeFM's own and the agent's (`/compact`,
your skills) - narrowing as you type. Type `@` to mention a file: the files
selected in the panes come first (or the ones under the cursors), then the
folder's files and folders, then files further down by name. `↑` / `↓` pick,
`Tab` takes the one picked, and `Enter` takes it too - and runs a command that
needs no argument. `Esc` closes the list. `/clear` starts a new conversation,
`/model` switches the model, and `/exit` ends the session. Claude Code's
own commands run as in Claude Code: `/usage` shows what you have used,
`/effort` and `/fast` set the effort and fast mode. Their replies keep
their lines as written, what Claude Code tells you beside them (fast mode
turned off, for one) appears in the conversation, and the effort and fast
mode you set stay set if the agent is started again.

- **The agent asks in XeFM.** When the agent wants to run a tool that needs
  your permission, XeFM asks: **Allow**, **Always Allow** (for the rest of
  this session; nothing is written to your settings), where the agent offers
  it, or **Deny**. The question shows the whole command, or the lines an edit
  would change, and what **Always Allow** would let through, as the agent
  says it: a rule such as `Bash(ssh:*)` can reach further than the one
  command you see. Where the agent does not say, the question says so. A
  request to run with the agent's sandbox off, or to reach past it, says
  **Outside the sandbox**, where the agent tells XeFM so.
  No button is selected at first, so an Enter or a Space you were typing
  answers nothing: choose with the Left or Right key and press Enter, click a
  button, or press Esc to deny. When the agent asks you to choose between options,
  XeFM shows each question with its options - one to pick, or checkboxes
  where several may be chosen - and a field for an answer of your own. The confirmations of
  [What the agent may not do](#what-the-agent-may-not-do) apply as in any
  agent session.
- **Plans.** In plan mode Claude Code and Codex end with a plan for you to approve:
  **Approve** (it goes on, asking before tools as usual), **Approve, Accept
  Edits** (file changes then go ahead without asking), or **Keep Planning**.
  No button is selected at first here either, and Esc keeps planning.
- **Back to the session.** **AI Agent** goes back to the session you used
  last, and **Ask AI Agent…** sends a request to the session already open in
  that folder instead of starting another; **Screens…** lists them, in
  terminal mode as well. While you are away, the status bar says when the
  agent is asking you something or has finished.
- **Links.** A link in the agent's reply to a file or folder on this
  computer opens it in the active pane.
- **If the agent stops** (it crashed, or you ended it outside XeFM), the
  conversation stays on screen; `Enter` starts it again in the same
  conversation.

This is Preview. XeFM runs your own program, signed in as you set it up, in
the mode it has for being run by another one: Claude Code's streaming JSON
(`claude -p`), Codex's app server (`codex app-server`), and the
[Agent Client Protocol](https://agentclientprotocol.com) for Copilot
(`copilot --acp`) and Antigravity (`agy acp`). What that use counts against is
between you and your plan with the agent's maker, as it is in a terminal.

### Differences between the agents

| | Claude Code | Codex | Copilot | Antigravity |
|---|---|---|---|---|
| Modes of `Shift+Tab` | ask, accept edits, plan | ask, accept edits, plan | ask, plan | ask, accept edits, plan |
| A plan to approve in a dialog | yes | yes | no: it writes the plan and stops | no: it writes the plan and stops |
| **Always Allow** | yes | where Codex offers it | yes | no |
| Questions with options | yes | yes | no: it asks in its reply | yes |
| A subagent's steps under it | yes | yes | no: they show as steps of their own | no |
| `/model` | pick from a list | pick from a list | Copilot's own command | pick from a list |
| `/effort` | Claude Code's own command | yes | no | yes |
| Other `/` commands | Claude Code's, your skills | `/compact`, your skills | Copilot's | Antigravity's, your skills |

- **Codex** works in the sandbox and with the approvals you set for it. Until
  you step the mode, XeFM changes neither; **accept edits** lets it write in
  the folder and ask for the rest, as Codex's own mode of that kind does.
- **Copilot** stops its turn when you deny a tool; type what it should do
  instead.
- **Antigravity** starts in the mode it opens in. In its *Auto* mode it decides
  itself which commands it runs, and XeFM can decline only those
  [it may not run](#what-the-agent-may-not-do) that it asks about; the
  conversation says so when it opens in that mode. XeFM does not change it: the
  mode that asks turns Antigravity's sandbox off.
- **Sign in** to an agent outside XeFM first. When one is not signed in, the
  conversation says which command to run.
- **Trust.** Copilot and Antigravity do not ask here whether you trust a
  folder, as they do on their own screen.

## What the agent gets

- **The `xefm` skill**, of the very XeFM it runs in: how to use
  [`xefmctl`](XEFMCTL_FEATURE.md), how XeFM's configuration and extensions
  work. Nothing is installed in the agent's own folders; each session is
  handed the skill when it starts.
- **[Your own skills](#your-own-skills-xefmskills)** from `~/.xefm/skills/`,
  handed the same way, to these sessions alone.
- **Rules** for working inside XeFM: start with `xefmctl state`; read what
  you see rather than guessing; change files only through `xefmctl`, so that
  you confirm each change; never delete for good; show results in XeFM.
  Your own rules come after XeFM's (`AGENT_RULES`).
- **[`xefmctl`](XEFMCTL_FEATURE.md)**, with a key that tells XeFM the request
  comes from this agent's session: as a command in the agent's shell, and as two
  tools, `xefmctl_read` (what only reads) and `xefmctl` (the rest), which
  [work where the agent's sandbox stops the command](#the-agents-own-sandbox).

## What the agent may not do

Rules can be ignored, so two things hold whatever the agent decides:

- **XeFM confirms every change.** A copy, move or trash asked for through
  `xefmctl` shows that operation's own confirmation in XeFM, saying which
  agent asks and listing the items, even where your `CONFIRM_*` settings
  turned it off; it goes ahead
  only if you allow it, and XeFM takes you back to the agent once it is done
  or declined.
  `xefmctl delete` is refused (the trash can be undone), and so is the
  `delete_permanently` action. An action the agent runs with `xefmctl
  invoke` asks first too, and deletes to the trash. Copying a file to a place
  the agent names (`xefmctl fetch`) is asked, and so is running a program:
  starting a terminal session, which is then as limited as the agent's own,
  opening files with other programs, reloading the configuration, or running an
  action of your own or an extension's. The first time the agent reads a file off this computer's
  disk - on a server, in cloud storage, in an archive - or searches inside
  files there, XeFM asks whether it may, for the rest of the session. On this
  computer's disk it asks before the agent reads a file outside the session's
  folder through `xefmctl`, once for each folder. It does not ask for the files
  directly in a folder you went to in a pane; a folder the agent took the pane to
  does not count. All of
  these confirmations start with no button selected, so that an Enter you typed
  for something else neither agrees to one nor turns it down: choose with the
  Left or Right key and press Enter, click a button, or press Esc to cancel.
- **The agent's own shell is limited**:
  the commands that delete or move files (`rm`, `rmdir`, `mv`, `unlink`,
  `shred`, `git clean`, and for Copilot and Antigravity PowerShell's
  `Remove-Item`, `Move-Item`, `del` and their kin) are denied, so those changes go
  through `xefmctl`. Claude Code and Copilot deny them by their permission
  settings, as does Antigravity in a terminal session. Where the agent takes
  no such setting - Codex, and Antigravity in a conversation XeFM draws - XeFM
  declines the command itself when the agent asks to run it. That reaches only
  what the agent asks: a command its own sandbox or settings let through
  without asking is not stopped. Codex in a terminal session has no such limit:
  its own sandbox and approvals decide, as they do outside XeFM.

To lift both, for an agent you trust with your files, set `'restrict':
False` on its entry.

## The agent's own sandbox

Some agents can run their shell commands in a sandbox of the operating system's,
which limits what a command reaches whatever the agent decides: typically it
writes only in the session's folder and has no network. It is a setting of the
agent's, and yours. XeFM never turns it on, off or wider.

- **What it is now.** The header of a conversation XeFM draws says *sandbox on*,
  *off* or *not known*, and so does `xefmctl state` in an agent's session. *Not
  known* means that it is up to the agent's settings, which XeFM does not read.
- **`xefmctl` in a sandbox.** Most sandboxes keep the agent's shell from XeFM, so
  XeFM also gives every session two tools the agent itself calls, outside the
  sandbox. They run the same commands under the same limits. If the agent tries
  the command in its shell instead, the message says to use the tools.
- **What the tools use.** They are an MCP server inside XeFM that listens on this
  computer only, and answers nothing without a token made for the one session,
  which ends with it. Other users of the same computer can reach the port, but
  not without the token. If your agent's settings close it (Copilot's
  `allowLocalNetwork`), the tools are not there.
- **Being asked.** In a conversation XeFM draws with Claude Code, Codex or
  Copilot, calling XeFM's tools is not asked by the agent: XeFM asks, where it
  would have. Antigravity asks first, and so does an agent on its own screen.

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
| `settings` | Claude Code and Antigravity: the settings to pass instead of XeFM's, in that agent's own form, e.g. `{'permissions': {'deny': ['Bash(rm:*)']}}` for Claude Code, `{'permissions': {'deny': ['command(rm)']}}` for Antigravity. In a conversation XeFM draws, only the denied commands of Antigravity's are used |
| `env` | Extra environment variables |
| `prompt_args` | Without a preset: what `ask_agent` adds for the request (default `['{prompt}']`) |
| `terminal` | `True`: the agent's own screen in a terminal session. `False`: [the conversation drawn by XeFM](#conversations-drawn-by-xefm). The default is `False` with a `preset` and `True` without one, which XeFM cannot draw |

To pass the agent more options, add them to `command`:
`['claude', '--model', 'opus']`. In a conversation XeFM draws, Codex's
`--model`, `--sandbox`, `--ask-for-approval`, `--profile` and `-c`, and
Antigravity's `--model`, `--mode` and `--effort` are passed on; their options
for their own screen have no effect there.

The `codex` preset sets Codex's `developer_instructions` for the session,
so one in your `~/.codex/config.toml` is not used there; put what you want
every session to know in `AGENT_RULES` (or Codex's own `AGENTS.md`).

In a terminal session, Copilot and Antigravity ask whether you trust a folder
the first time they start there; answer it in the session. Antigravity may run a
shell command in XeFM's own folder of rules instead of yours; XeFM tells it
which folder is yours. A conversation XeFM draws does not have this.

A `config.py` that has its own `AGENTS` keeps it: add the Codex, Copilot or
Antigravity line to it to get that agent.

### Your own skills: `~/.xefm/skills/`

A skill in `~/.xefm/skills/<name>/SKILL.md` is handed to every agent session
XeFM starts, and to no agent you run anywhere else. Use it for what only makes
sense beside the file manager: a workflow built on `xefmctl`, how you sort and
rename photos, where downloads go. Kept in the agent's own skills folder, the
same instructions would show up in every coding session too.

The easiest way to make one is to ask for it in a session:

> Write a skill that sorts photos into year/month folders by date taken, and
> install it as an XeFM skill.

The agent writes the folder and checks it. A skill is a plain
[Agent Skills](https://agentskills.io) folder: `SKILL.md`, with a `name` that
matches the folder's and a `description` of when to use it, and any files
beside it. You can write one by hand, or copy one in.

- A new or changed skill reaches the **next** session; no reload is needed.
  The session that wrote it reads it directly if you want to use it at once.
- In Claude Code they appear as `xefm-user:<name>`, apart from XeFM's own
  `xefm:xefm`. Every agent with a preset gets them; for Codex in a terminal
  session, the rules list each skill and where it is.
- `xefmctl skill list` shows your skills and whether sessions get them;
  `xefmctl skill check <name>` says what is wrong with one. They work in
  every session, whichever way XeFM was installed; from any shell, so does
  `xefm skills list|check` where `xefm` is on PATH (a pip or Homebrew
  install). A skill that fails the check is left out (with a warning in the
  log), and the name `xefm` is taken by XeFM's own.
- To remove one, move its folder to the trash.

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
| `{user_skills_dir}` | A skills folder holding [your own skills](#your-own-skills-xefmskills) (empty when you have none) |
| `{user_plugin_dir}` | The same as a Claude Code plugin folder (`xefm-user`) |
| `{rules}` / `{rules_file}` | The rules, as text / in a Markdown file |
| `{settings_file}` | A JSON file of the `settings` given (empty without them) |
| `{mcp_config_file}` | A JSON file of [XeFM's tools](#the-agents-own-sandbox), as an MCP configuration (`mcpServers`, over HTTP); empty where they could not be started |
| `{prompt}` | The request, for `ask_agent` |

Each agent takes these in its own way. The wiki page
[AI agents](https://github.com/crftwr/xefm/wiki/AI-agents) collects entries
for other agents, written and kept up by the people who use them. XeFM's
own limits on `xefmctl` apply to every agent.

## See also

- [xefmctl](XEFMCTL_FEATURE.md): the commands an agent uses
- [The XeFM skill for AI agents](AGENT_SKILL_FEATURE.md): installing the skill for an agent you run yourself
- [Terminal](TERMINAL_FEATURE.md): terminal sessions and screens
