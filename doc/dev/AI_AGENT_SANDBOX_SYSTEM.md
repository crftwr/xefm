# AI agents' sandboxes: System

Some AI agents run their shell commands in an OS sandbox. This is XeFM's policy
on that, the same for every agent and platform, how it is met, and the tests that
show it holds (#995, where the measurements are). User-facing:
[AI_AGENT_SESSIONS_FEATURE.md](../AI_AGENT_SESSIONS_FEATURE.md), "The agent's own
sandbox".

## Policy

1. **The sandbox belongs to the user and the agent.** XeFM never turns it on, off
   or wider, directly or as a side effect of something else it sets.
2. **`xefmctl` works the same everywhere**: sandbox on or off, drawn or terminal
   session, every agent and platform.
3. **XeFM does not open a hole in the sandbox to get there.** `xefmctl` reaches
   XeFM through a tool the agent's own process calls, over a channel the agent
   offers outside its sandbox. XeFM does not change the sandbox's settings, loosen
   the ACL of the socket, the pipe or the shim folder, or ask for network access;
   where the user's settings close the channel, `xefmctl` says so. Where the
   channel is a port, it listens on loopback only, on a port chosen when it
   starts, and closes with XeFM. It answers nothing without the session's token,
   and refuses a request whose `Host` is not its own or that carries an `Origin`.
   The token belongs to one session, ends with it, and is not put in the
   environment of the commands the agent runs. Whatever holds the token may do
   what that session's agent may do, and no more.
4. **The channel gives no more than the sandbox does, without the user.** It runs
   with the user's rights, so every command is allowed, asked or refused.
5. **Approvals and the sandbox stay separate.** `restrict` is not a sandbox.
6. **The user can see it**: on, off, or not known.
7. **It fails in words.**

What rule 3 accepts: the pipe and the Unix socket are closed to other users by
the OS, and a port is not. There the token alone stands between XeFM and another
user of the same machine.

## The channel: `xefm/mcp_server.py`

An MCP server in XeFM over HTTP on loopback, for every session of every agent,
whether or not a sandbox is on (its state is often not known). Not stdio: Copilot
starts stdio servers inside its sandbox, and the Store version's and the macOS
app's interpreters do not start in some of them. It is started with the first
agent session (`XeFMApp._agent_channel`) and answers through
`remote_dispatch.handle`, as `xefmctl`'s own listener does, so the policy is the
same code.

Two tools: `xefmctl_read`, with `readOnlyHint` (Codex with approvals set to
`never` refuses a tool without it), for commands whose effect is `READ`, save
`fetch` and `--show`; and `xefmctl`, for all. A command is a list of words, parsed
by `remote_cli.parse` with the session's folder as `cwd`. Parsed there it reads no
file (`--plan` takes `-` alone): XeFM may read what the agent may not. A model
sometimes gives the words as one string (Claude haiku in layer F): a JSON list in
it is taken as that list, anything else is split as a shell would.

An answer that takes more than a second becomes an event stream with comments,
and progress notifications for a client that gave a token: the user is being
asked, and a client gives up on silence.

### Handing it over (`agents.CHANNELS`)

| | Drawn | Terminal |
|---|---|---|
| Claude Code | `--mcp-config` file | the same |
| Codex | `config` of `thread/start` and `thread/resume` | `-c`, with `http_headers_helper` printing a file |
| Copilot | `session/new` | `--additional-mcp-config @file` |
| Antigravity | `session/new` | `.agents/mcp_config.json` in the session's own workspace folder |
| no preset | | `{mcp_config_file}` |

- **The file** is owner-only, in a folder of the session's own under
  `~/.xefm/cache/agents/`, deleted with the session (`agents.discard`). Never in
  the temporary folder: Copilot's sandbox lets its shell read that and reach the
  port on macOS, so the shell would have both. No other shell measured had both,
  Codex's `unelevated` on Windows apart (it may open the user's other processes).
- **Not in an environment variable or on a command line.** Codex's shell inherits
  the first, and its Seatbelt sandbox lets it read other processes' of both
  (`KERN_PROCARGS2`).
- **Codex's key is dotted** (`mcp_servers.<name>`): as a table under
  `mcp_servers` it drops the servers given with `-c`.
- **The server's name is not to be guessed** (`xefm_` and eight hex digits). XeFM
  answers the agent's question about its own tools - one question, not two - and
  goes by the name: `mcp__<name>__` for Claude Code, `serverName` for Codex, and
  `--allow-tool=<name>` for Copilot. A repository's own MCP server called `xefm`
  must not be answered for. Only in drawn sessions. Antigravity's request was not
  measured, so it is asked.
- **The first message** of a JSON-RPC agent waits until it has asked for the
  tools (`TOOLS_WAIT` at most). An ACP agent is given the server only where its
  `mcpCapabilities` say `http`.

## Rule 4: reading local files

`read`, `fetch` and `find-in-files` return contents an agent's sandbox may keep
from it, so for an agent's session `_local_read_allowed` asks once per folder.
Unasked: below the session's folder (`app._agent_folders`) and below a folder
already agreed to; and the files directly in a pane's folder, where the user went
there. `pane_moved` (from `_fire_directory_changed`) remembers the folders the
agent took a pane to while a request of its runs (`_acting`), since `pane cd` is
not asked. Links are resolved first, and the file that was opened is checked again
(`_final_path`), so a link changed meanwhile gets nothing. A search leaves out
what a link leads out of its folder.

It is the same with the sandbox off, where the agent can read the file with its
own shell and the question does little.

## Rule 6: the state

`Conversation.sandbox`, shown in the header, and `sandbox` of `xefmctl state`.
Codex's drawn session says its thread's policy; for the rest, what the entry's
command line says (`agents.sandbox_state`); otherwise *not known*. XeFM does not
read the agents' settings.

A question says when what it asks would leave the sandbox (`Permission.leaves_sandbox`),
where the agent says so: Claude Code's Bash with `dangerouslyDisableSandbox`, and
Codex's requests for the network or for access beyond its sandbox. A Codex command
and Copilot's retry do not say, and nothing is claimed for them.

## Rule 7: failing in words

- A connection the OS refuses (`PermissionError`) says to use the tools
  (`remote_cli.SANDBOXED`).
- The shim (`remote_server.posix_shim`, `windows_shim`) asks, only after a failure,
  whether XeFM's interpreter starts at all, and if not adds `CANNOT_START`: in
  Copilot's sandbox on macOS the app's Python ends in `Abort trap: 6`, and a venv
  under the home folder is not readable in some (Linux, layer E).
- Where the sandbox does not show the shim's folder at all (Codex on Linux in
  qa-linux; Codex `unelevated` on Windows cannot read it), the shell's own
  `command not found` is all there is: nothing of XeFM's runs.

## Tests

| Layer | Where |
|---|---|
| A. The policy as a table: no argv, setting or mode XeFM sends touches a sandbox; every session has a channel and hides its token | `test_agent_sandbox.py` |
| B. Every command has its class; what is asked does nothing before the answer | `test_agent_restrictions.py` |
| C. Stand-in agents: what each is sent, resumed too; the header | `test_agent_rpc.py`, `test_mcp_server.py` |
| D. A real OS sandbox, no agent: Seatbelt on macOS, seccomp on Linux, a low-integrity token on Windows (as Codex's `unelevated`) | `test_agent_sandbox.py` |
| E. The real CLIs, driven by XeFM's code, with a stand-in model (`agent_standin.py`): no account, no quota. Claude Code, Codex and Copilot, pinned; macOS, Windows and Linux. Also Always Allow's scope and a request to leave the sandbox, as each CLI sends them | `test_agent_cli.py` |
| The hand check, on a real XeFM with its panes and dialogs: what is asked, when, and what is left after | `test_agent_walkthrough.py`: with the tools called directly in every run, by the real CLIs with `--agent-cli` |
| F. A live turn: does the model use the tools unprompted? | by hand, with a signed-in Claude Code (2026-11-25, haiku: yes, three of three) |

Layers A to D run with the suite. E downloads the CLIs, pinned and checksummed,
so it runs in a guest, by hand, before a release and when a CLI is updated:

```bash
make test-vm GUEST=qa-mac ARGS="--agent-cli test/test_agent_cli.py test/test_agent_walkthrough.py"
make test-vm GUEST=qa-win ARGS="--agent-cli test/test_agent_cli.py test/test_agent_walkthrough.py"
make test-vm GUEST=qa-linux ARGS="--agent-cli test/test_agent_cli.py"
```

The CLIs' own screens (a terminal session) run in a pseudo-terminal on macOS and
Linux (`Run.screen`): started as XeFM starts them, the request typed once the
screen has drawn. Each CLI's first-run questions are answered in its own settings
(`_trusted`: the folder trusted, Claude Code's API key approved and its auto mode,
whose check runs on Anthropic's server, set to default); Copilot's offer to install
its proxy's certificate authority is declined on the screen.

The stand-in answers OpenAI's chat completions and responses and Anthropic's
messages, and searches for the tools Claude Code defers (`ToolSearch`) as a model
has to. On Windows Codex runs its `unelevated` sandbox, which needs no setup;
`--codex-windows-sandbox` picks `mxc` (it passes as `unelevated` does: the pipe
refused in XeFM's words, both tools answer) or `elevated`.

Codex's `elevated` sandbox has to be set up once, with an administrator's consent
(UAC); until then a command waits without a word. A drawn Codex session on Windows
asks `windowsSandbox/readiness` as it opens, and where it is not `ready` says so
and offers `/setup-sandbox`, which sends `windowsSandbox/setupStart` and reports
`windowsSandbox/setupCompleted`. XeFM starts nothing that asks for administrator
rights on its own (rule 1). In a guest nobody consents, so that test is skipped
once the session has said so. Claude Code has no sandbox on
Windows.

For a run with `--agent-cli`, qa-linux's container is started with
`--security-opt seccomp=unconfined --security-opt systempaths=unconfined
--device /dev/net/tun` and installs bubblewrap, socat, slirp4netns, iproute2 and
iptables (`qa/guest.py`): with Docker's default profile there are no user
namespaces and no CLI's sandbox starts. The rest of the suite keeps the plain
container. The sandboxes differ by platform (Copilot reaches XeFM through the
temporary folder on macOS and keeps a write outside in a copy of its own on Linux;
Codex cannot read the shim on Windows and does not see it on Linux), so a Linux
container stands for none of the others.

## Seen in the GUI

2026-11-25, in the Tart VM `xefm-demo` (macOS 27, Pelagic), Claude Code with the
stand-in model asking: the read of a long path outside the session's folder
(wrapped, whole), a command outside the sandbox (**Outside the sandbox**), and a
copy. That showed two faults, now fixed: Claude Code's MCP tool names
(`mcp__server__tool`) lost their underscores to Markdown emphasis, and the copy's
own confirmation did not say which agent asked and had Copy selected
(`AGENT_ASKING`, set by `remote_dispatch` while the agent's request runs).

## Not done

- Sessions started by the Store's XeFM (they need a person).
- XeFM still breaks its agents' plain questions itself (`_fit`), though PuiKit
  1.33.1, the floor, wraps a plain `MessageBox` too (puikit#247). `_fit` can keep
  only the refusal of a question too tall for the screen once the floor is
  called hard.
- Antigravity, put off: what to check is in #1002 and #995.
