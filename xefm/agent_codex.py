"""Codex drawn by XeFM: ``codex app-server``, the JSON-RPC protocol Codex's own
IDE extensions speak (checked against codex-cli 0.171).

A thread is the conversation (``thread/start``, ``thread/resume``), a turn one
request and what Codex does about it (``turn/start`` ... ``turn/completed``).
What Codex does comes as items (``item/started``, deltas, ``item/completed``):
what it says, its reasoning, the commands it runs, the files it changes. Where
its own approval settings ask, it sends a request and waits for the answer.

The sandbox and approval policy stay the user's own (``~/.codex/config.toml``)
until they step the mode: **accept edits** is Codex's "workspace-write, ask
when needed", **plan** its plan mode, and **ask** what the thread started with.
"""

from __future__ import annotations

import re
import shlex
import sys
from typing import Any

from xefm.agent_chat import PLAN_TOOL, Conversation, Item, Permission
from xefm.agent_rpc import RpcClient, RpcProtocol, ask_user, hunk_edits
from xefm.log_manager import getLogger

logger = getLogger("AgentCodex")

#: Codex's options that set a configuration value, by the key they set: its
#: app-server takes the value (``-c``) but ignores the option.
_OPTION_KEYS = {"-m": "model", "--model": "model",
                "-s": "sandbox_mode", "--sandbox": "sandbox_mode",
                "-a": "approval_policy", "--ask-for-approval": "approval_policy",
                "-p": "profile", "--profile": "profile"}

#: The shells Codex wraps a command in, and the options before the command.
_SHELLS = {"bash", "sh", "zsh", "fish", "dash", "pwsh", "powershell", "cmd"}
_SHELL_FLAGS = {"-c", "-lc", "-command", "-noprofile", "-nologo", "-noninteractive",
                "/c", "/d", "/s"}

MODE_LABELS = {"default": "", "acceptEdits": "accept edits", "plan": "plan mode"}

#: What XeFM sends once a plan is approved, as Codex's own screen does.
IMPLEMENT = "Implement the plan."

_STATUS = {"inProgress": "in_progress", "completed": "completed"}


def app_server_argv(command: list[str]) -> list[str]:
    """The command line of the app-server: the entry's ``command`` with the
    options that set a model, a sandbox... as configuration values."""
    out: list[str] = []
    args = iter(command)
    for arg in args:
        name, eq, value = arg.partition("=")
        key = _OPTION_KEYS.get(name)
        if key is None or (eq and not name.startswith("--")):
            out.append(arg)
            continue
        if not eq:
            value = next(args, "")
        out += ["-c", f"{key}={value}"]
    return out + ["app-server"]


def shell_command(command: str) -> str:
    """The command itself, out of the shell Codex runs it with
    (``/bin/bash -lc '...'``, ``pwsh.exe -Command '...'``)."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if len(parts) < 3:
        return command
    shell = re.split(r"[\\/]", parts[0])[-1].lower().removesuffix(".exe")
    if shell in _SHELLS and all(p.lower() in _SHELL_FLAGS for p in parts[1:-1]):
        return parts[-1]
    return command


def _file_item(change: dict, tool_id: str) -> Item:
    """One file of a ``fileChange`` as an edit."""
    path = str(change.get("path") or "")
    kind = change.get("kind") if isinstance(change.get("kind"), dict) else {}
    diff = str(change.get("diff") or "").replace("\r\n", "\n")
    what = kind.get("type")
    if what == "add":
        return Item("tool", name="Write", tool_id=tool_id,
                    input={"file_path": path, "old_string": "", "new_string": diff},
                    patch="\n".join("+" + line for line in diff.rstrip("\n").split("\n")))
    if what == "delete":
        return Item("tool", name="Delete", tool_id=tool_id,
                    input={"file_path": path, "old_string": diff, "new_string": ""},
                    patch="\n".join("-" + line for line in diff.rstrip("\n").split("\n")))
    moved = kind.get("move_path")
    return Item("tool", name="Edit", tool_id=tool_id, patch=diff.rstrip("\n"),
                input={"file_path": str(moved or path), "edits": hunk_edits(diff)})


def _sandbox_state(policy: Any) -> str:
    """A thread's sandbox policy as the header says it."""
    kind = policy.get("type") if isinstance(policy, dict) else None
    return {"workspaceWrite": "on", "readOnly": "on",
            "dangerFullAccess": "off"}.get(kind, "not known")


def _text_of(content: Any) -> str:
    """The text of an MCP (or dynamic) tool's result."""
    if not isinstance(content, list):
        return ""
    return "\n".join(str(c["text"]) for c in content
                     if isinstance(c, dict) and isinstance(c.get("text"), str))


#: The command that sets Codex's elevated Windows sandbox up, where it waits.
SETUP_COMMAND = "setup-sandbox"
SETUP_ENTRY = {"name": SETUP_COMMAND,
               "description": "Set up Codex's Windows sandbox (asks for administrator rights)"}


class CodexClient(RpcClient):
    """One ``codex app-server`` process with one thread."""

    def __init__(self, argv: list[str], *, instructions: str = "",
                 skills_roots: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__(argv, **kwargs)
        #: What every thread is told (the rules), and the folders the
        #: session's skills are in (XeFM's, then the user's).
        self.instructions = instructions
        self.skills_roots = list(skills_roots or [])
        self._turn_id = ""
        #: The thread's own policy and sandbox, for the mode "default".
        self._policy: Any = None
        self._sandbox: Any = None
        #: What the next turn sets (the thread keeps it for those after).
        self._overrides: dict[str, Any] = {}
        self._items: dict[str, list[Item]] = {}
        self._skills: dict[str, str] = {}
        self._models: list[dict] = []
        #: Subagents: the step that started a thread, by the thread's id.
        self._agents: dict[str, Item] = {}
        self._plan = ""
        self._error = ""
        #: Codex's Windows sandbox waits to be set up (``windowsSandbox/readiness``).
        self._setup_needed = False
        #: Whether to ask after it: Windows alone has it.
        self.windows = sys.platform == "win32"

    # --- opening ----------------------------------------------------------------

    def _open(self) -> None:
        self.call("initialize", {
            "clientInfo": {"name": "xefm", "title": "XeFM", "version": "1"},
            # Plan mode is still behind it.
            "capabilities": {"experimentalApi": True}},
            self._initialized, lambda e: self._failed(f"Codex: {e.get('message')}"))

    def _initialized(self, _result: dict) -> None:
        self.notify("initialized")
        if self.windows:
            # A Codex that does not know it says so, and nothing waits on it.
            self.call("windowsSandbox/readiness", None, self._readiness, lambda e: None)
        self.call("account/read", {}, self._account, lambda e: self._start_thread())

    def _readiness(self, result: dict) -> None:
        """Codex's elevated Windows sandbox has to be set up once, with the
        administrator's consent; until then a command it runs waits without a
        word (#995: a drawn turn stalled, nothing reaching XeFM). Say so, and
        offer the setup as a command the user gives: XeFM starts nothing that
        asks for administrator rights on its own (rule 1). Unelevated and mxc
        say ready (Codex 0.171.0, measured)."""
        status = result.get("status")
        if status in (None, "ready"):
            return
        self._setup_needed = True
        again = " again" if status == "updateRequired" else ""
        self.conv.add_notice(
            f"Codex's elevated Windows sandbox needs setting up{again}, and its commands "
            f"wait until it is. Type /{SETUP_COMMAND} to set it up (Windows asks for "
            "administrator rights), or set windows.sandbox to 'unelevated' in Codex's "
            "configuration.")
        self.conv.commands = self._with_setup(self.conv.commands)

    def _with_setup(self, commands: list) -> list:
        if self._setup_needed and not any(c.get("name") == SETUP_COMMAND for c in commands):
            return [*commands, SETUP_ENTRY]
        return commands

    def _account(self, result: dict) -> None:
        if result.get("account") is None and result.get("requiresOpenaiAuth"):
            self._failed("Not signed in: run `codex login` in a terminal")
            return
        self._start_thread()

    def _start_thread(self) -> None:
        if self.skills_roots:
            self.call("skills/extraRoots/set", {"extraRoots": self.skills_roots})
        self.call("skills/list", {"cwds": [self.cwd]}, self._have_skills)
        self.call("model/list", {}, self._have_models)
        params: dict[str, Any] = {"cwd": self.cwd}
        if self.instructions:
            params["developerInstructions"] = self.instructions
        if self.channel is not None:
            # Over its stdin: in no environment, command line or file (#995).
            from xefm.agents import codex_server
            params["config"] = codex_server(self.channel)
            self._tools_coming = True

        def failed(error: dict) -> None:
            self._failed(f"Codex could not open a session: {error.get('message')}")
        if self.resume:
            self.call("thread/resume",
                      dict(params, threadId=self.resume, excludeTurns=True),
                      self._thread, failed)
        else:
            self.call("thread/start", params, self._thread, failed)

    def _thread(self, result: dict) -> None:
        conv = self.conv
        thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
        conv.session_id = str(thread.get("id") or conv.session_id)
        conv.model = str(result.get("model") or conv.model)
        self._policy = result.get("approvalPolicy")
        self._sandbox = result.get("sandbox")
        conv.sandbox = _sandbox_state(self._sandbox)
        conv.modes, conv.mode_labels = ("default", "acceptEdits", "plan"), MODE_LABELS
        conv.permission_mode = "default"
        # What the user set before, again in a new process.
        if conv.model_choice:
            self.set_model(conv.model_choice)
        if conv.effort_choice:
            self.set_effort(conv.effort_choice)
        if conv.mode_choice and self.set_mode(conv.mode_choice):
            conv.permission_mode = conv.mode_choice
        self._efforts()
        self._ready()

    def _have_skills(self, result: dict) -> None:
        commands = [{"name": "compact",
                     "description": "Summarize the conversation to free up the context"}]
        for entry in result.get("data") or []:
            for skill in (entry.get("skills") or []) if isinstance(entry, dict) else []:
                name = skill.get("name") if isinstance(skill, dict) else None
                if isinstance(name, str) and skill.get("enabled") and name not in self._skills:
                    self._skills[name] = str(skill.get("path") or "")
                    commands.append({"name": name, "argumentHint": "<request>",
                                     "description": str(skill.get("shortDescription")
                                                        or skill.get("description") or "")})
        self.conv.commands = self._with_setup(commands)

    def _have_models(self, result: dict) -> None:
        models = [m for m in result.get("data") or []
                  if isinstance(m, dict) and isinstance(m.get("model"), str)
                  and not m.get("hidden")]
        self._models = models
        self.conv.models = [{"value": m["model"],
                             "displayName": str(m.get("displayName") or m["model"]),
                             "description": str(m.get("description") or "")} for m in models]
        self._efforts()

    def _efforts(self) -> None:
        """The efforts the model now used takes."""
        for m in self._models:
            if m["model"] == self.conv.model:
                self.conv.efforts = tuple(
                    e["reasoningEffort"] for e in m.get("supportedReasoningEfforts") or []
                    if isinstance(e, dict) and isinstance(e.get("reasoningEffort"), str))

    # --- turns ---------------------------------------------------------------------

    def _start_turn(self, text: str) -> None:
        conv = self.conv
        self._plan = self._error = self._turn_id = ""
        content: list[dict] = [{"type": "text", "text": text, "text_elements": []}]
        m = re.match(r"/([\w:.-]+)(?:\s+|$)", text)
        if m and self._skills.get(m.group(1)):
            # A skill by name: Codex's own way to write one is `$name`.
            name = m.group(1)
            content = [{"type": "skill", "name": name, "path": self._skills[name]},
                       {"type": "text", "text": f"${name} {text[m.end():]}".rstrip(),
                        "text_elements": []}]
        params = {"threadId": conv.session_id, "input": content, **self._overrides}
        self._overrides = {}
        self.call("turn/start", params, self._turn_started,
                  lambda e: self._turn_ended(str(e.get("message") or "Codex refused the message"),
                                             error=True))

    def _turn_started(self, result: dict) -> None:
        turn = result.get("turn")
        if isinstance(turn, dict):
            self._turn_id = self._turn_id or str(turn.get("id") or "")

    def _cancel_turn(self) -> bool:
        return bool(self._turn_id) and self.call(
            "turn/interrupt", {"threadId": self.conv.session_id, "turnId": self._turn_id})

    def command(self, text: str) -> bool:
        if text == f"/{SETUP_COMMAND}" and self._setup_needed and self.running:
            self.conv.add_user(text)
            self.call("windowsSandbox/setupStart", {"mode": "elevated", "cwd": self.cwd},
                      lambda r: None if r.get("started") else self.conv.add_notice(
                          "Codex did not start setting up its sandbox", error=True),
                      lambda e: self.conv.add_notice(
                          f"Codex could not set up its sandbox: {e.get('message')}", error=True))
            return True
        if text != "/compact" or not self.ready or self.in_turn:
            return False
        conv = self.conv
        conv.add_user(text)
        self.in_turn = True  # it runs as a turn, with a turn's notifications
        self.call("thread/compact/start", {"threadId": conv.session_id},
                  failed=lambda e: self._turn_ended(str(e.get("message")), error=True))
        return True

    # --- what the user sets -----------------------------------------------------------

    def set_mode(self, mode: str) -> bool:
        """From the next turn on."""
        if mode not in MODE_LABELS:
            return False
        if mode == "acceptEdits":
            self._overrides["approvalPolicy"] = "on-request"
            self._overrides["sandboxPolicy"] = {
                "type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
                "excludeTmpdirEnvVar": False, "excludeSlashTmp": False}
        else:
            if self._policy is not None:
                self._overrides["approvalPolicy"] = self._policy
            if self._sandbox is not None:
                self._overrides["sandboxPolicy"] = self._sandbox
        self.conv.sandbox = _sandbox_state(self._overrides.get("sandboxPolicy"))
        self._overrides["collaborationMode"] = {
            "mode": "plan" if mode == "plan" else "default",
            "settings": {"model": self.conv.model_choice or self.conv.model,
                         "reasoning_effort": self.conv.effort_choice or None,
                         "developer_instructions": None}}
        return True

    def set_model(self, model: str) -> bool:
        conv = self.conv
        if conv.models and model not in [m["value"] for m in conv.models]:
            conv.add_notice(f"No such model: {model}", error=True)
            return False
        self._overrides["model"] = model
        conv.model = conv.model_choice = model
        self._collaboration("model", model)
        self._efforts()
        return True

    def set_effort(self, level: str) -> bool:
        self._overrides["effort"] = level
        self._collaboration("reasoning_effort", level)
        return True

    def _collaboration(self, key: str, value: str) -> None:
        # The mode's settings name the model and effort too, and win.
        if "collaborationMode" in self._overrides:
            self._overrides["collaborationMode"]["settings"][key] = value
        elif self.conv.mode_choice:
            self.set_mode(self.conv.mode_choice)
            self._overrides["collaborationMode"]["settings"][key] = value

    def approve_plan(self, request_id: str, mode: str) -> None:
        super().approve_plan(request_id, mode)
        if self.send(IMPLEMENT):
            self.conv.add_user(IMPLEMENT)

    # --- notifications -----------------------------------------------------------------

    def _on_notification(self, method: str, params: dict) -> Permission | str | None:
        conv = self.conv
        if method == "serverRequest/resolved":
            # Answered, or no longer needed (the turn was stopped).
            rid = f"rpc{params.get('requestId')}"
            return self._withdraw(rid) if rid in conv.permissions else None
        if method == "windowsSandbox/setupCompleted":
            if params.get("success"):
                self._setup_needed = False
                self.conv.commands = [c for c in self.conv.commands
                                      if c.get("name") != SETUP_COMMAND]
                conv.add_notice("Codex's Windows sandbox is set up")
            else:
                why = str(params.get("error") or "")
                if "1223" in why:  # ERROR_CANCELLED: the consent was not given
                    why = "administrator rights were not given"
                conv.add_notice(f"Codex's Windows sandbox was not set up: {why}", error=True)
            return None
        if method in ("warning", "guardianWarning"):
            if str(params.get("message") or "").strip():
                conv.add_notice(str(params["message"]).strip())
            return None
        thread = params.get("threadId")
        if thread is not None and thread != conv.session_id:
            self._sub(str(thread), method, params)
            return None
        if method == "turn/started":
            turn = params.get("turn") or {}
            self._turn_id = str(turn.get("id") or self._turn_id)
        elif method == "turn/completed":
            return self._completed(params.get("turn") or {})
        elif method in ("item/started", "item/completed"):
            item = params.get("item")
            if isinstance(item, dict):
                self._item(item, done=method == "item/completed")
        elif method in ("item/agentMessage/delta", "item/plan/delta"):
            self._delta(params, "text")
        elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
            self._delta(params, "thinking")
        elif method == "item/reasoning/summaryPartAdded":
            for item in self._items.get(str(params.get("itemId")), []):
                if item.text:
                    item.text += "\n\n"
        elif method == "item/commandExecution/outputDelta":
            for item in self._items.get(str(params.get("itemId")), []):
                item.result = (item.result or "") + str(params.get("delta") or "")
        elif method == "turn/plan/updated":
            self._set_todos([{"content": str(s.get("step") or ""),
                              "activeForm": str(s.get("step") or ""),
                              "status": _STATUS.get(s.get("status"), "pending")}
                             for s in params.get("plan") or [] if isinstance(s, dict)])
        elif method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage") or {}
            conv.context_tokens = int((usage.get("last") or {}).get("totalTokens") or 0)
            conv.context_window = int(usage.get("modelContextWindow") or 0)
        elif method == "model/rerouted":
            conv.model = str(params.get("toModel") or conv.model)
        elif method == "error" and not params.get("willRetry"):
            self._error = str((params.get("error") or {}).get("message") or "")
        return None

    def _completed(self, turn: dict) -> Permission | None:
        self._turn_id = ""
        status = turn.get("status")
        if status == "interrupted":
            self._turn_ended("Interrupted")
        elif status == "failed":
            error = turn.get("error") or {}
            self._turn_ended(str(error.get("message") or self._error or "The turn failed"),
                             error=True)
        else:
            self._turn_ended()
        plan, self._plan = self._plan.strip(), ""
        if plan and status == "completed" and self.conv.permission_mode == "plan" \
                and not self.in_turn:
            # Codex leaves it at the plan; its own screen asks this here.
            perm = Permission(f"plan-{turn.get('id')}", PLAN_TOOL, {"plan": plan})
            return self._ask(perm, lambda response: None)
        return None

    def _delta(self, params: dict, kind: str) -> None:
        key = str(params.get("itemId"))
        items = self._items.get(key)
        if not items:
            items = self._items[key] = [self._said(kind)]
        items[0].text += str(params.get("delta") or "")

    def _said(self, kind: str) -> Item:
        self._close_text()
        item = Item(kind, open=True)
        self.conv.items.append(item)
        return item

    def _item(self, data: dict, *, done: bool) -> None:
        """An item of the conversation's own thread, as it starts or as it
        finished."""
        key, what = str(data.get("id") or ""), data.get("type")
        items = self._items.get(key)
        if what in ("agentMessage", "plan"):
            if not items and (done or data.get("text")):
                items = self._items[key] = [self._said("text")]
            if items and done:
                items[0].text = str(data.get("text") or items[0].text)
                items[0].open = False
            if what == "plan" and done:
                self._plan = str(data.get("text") or "")
            return
        if what == "reasoning":
            text = "\n\n".join(str(t) for t in data.get("summary") or data.get("content") or [])
            if not items:
                items = self._items[key] = [self._said("thinking")]
            if done:
                items[0].text = text or items[0].text
                items[0].open = False
            return
        if what == "contextCompaction":
            if done:
                self.conv.add_notice("Earlier conversation compacted")
            return
        if not items:
            items = self._items[key] = self._steps(data, key)
            for item in items:
                item.open = True
                self._tool(item)
        self._update(items, data, done=done)

    def _steps(self, data: dict, key: str) -> list[Item]:
        """A new item as steps of the transcript (a file each for a change);
        none for what has no place there."""
        what = data.get("type")
        if what == "commandExecution":
            return [Item("tool", name="Shell", tool_id=key,
                         input={"command": shell_command(str(data.get("command") or ""))})]
        if what == "fileChange":
            return [_file_item(c, key) for c in data.get("changes") or []
                    if isinstance(c, dict)]
        if what == "mcpToolCall":
            args = data.get("arguments")
            return [Item("tool", name=f"{data.get('server')}: {data.get('tool')}", tool_id=key,
                         input=dict(args) if isinstance(args, dict) else {})]
        if what == "dynamicToolCall":
            args = data.get("arguments")
            return [Item("tool", name=str(data.get("tool") or "tool"), tool_id=key,
                         input=dict(args) if isinstance(args, dict) else {})]
        if what == "webSearch":
            return [Item("tool", name="WebSearch", tool_id=key,
                         input={"query": str(data.get("query") or "")})]
        if what == "imageView":
            return [Item("tool", name="Read", tool_id=key,
                         input={"file_path": str(data.get("path") or "")})]
        if what == "imageGeneration":
            return [Item("tool", name="Image", tool_id=key)]
        if what == "collabAgentToolCall":
            if data.get("tool") not in ("spawnAgent", "sendInput", "followupTask"):
                return []
            return [Item("tool", name="Agent", tool_id=key,
                         input={"description": str(data.get("prompt") or "")})]
        if what == "subAgentActivity":
            return self._activity(data, key)
        return []

    def _activity(self, data: dict, key: str) -> list[Item]:
        thread = str(data.get("agentThreadId") or "")
        owner = self._agents.get(thread)
        kind = data.get("kind")
        if kind in ("completed", "interrupted") and owner is not None:
            owner.open = False
            owner.is_error = kind == "interrupted"
            owner.result = owner.result or ""
        if owner is not None or kind != "started":
            return []
        item = Item("tool", name="Agent", tool_id=key,
                    input={"description": str(data.get("agentPath") or "")})
        self._agents[thread] = item
        return [item]

    def _update(self, items: list[Item], data: dict, *, done: bool) -> None:
        """What is known of a step now."""
        what, status = data.get("type"), data.get("status")
        for item in items:
            if status == "declined":
                item.denied = True
            elif status in ("failed", "interrupted"):
                item.is_error = True
        if what == "fileChange" and done and items:
            # Approved, the change may have been worked out again.
            for item, change in zip(items, data.get("changes") or []):
                fresh = _file_item(change, item.tool_id) if isinstance(change, dict) else item
                item.name, item.input, item.patch = fresh.name, fresh.input, fresh.patch
        if not items or not done:
            if what == "collabAgentToolCall" and items:
                self._own(items[0], data)
            return
        item = items[0]
        if what == "commandExecution":
            output = data.get("aggregatedOutput")
            item.result = str(output if output is not None else item.result or "")
            item.is_error = item.is_error or bool(data.get("exitCode"))
        elif what == "mcpToolCall":
            result, error = data.get("result"), data.get("error")
            if isinstance(error, dict):
                item.is_error, item.result = True, str(error.get("message") or "")
            elif isinstance(result, dict):
                item.result = _text_of(result.get("content"))
        elif what == "dynamicToolCall":
            item.result = _text_of(data.get("contentItems"))
            item.is_error = data.get("success") is False
        elif what == "webSearch":
            item.input = {"query": str(data.get("query") or item.input.get("query") or "")}
        elif what == "collabAgentToolCall":
            self._own(item, data)
        elif what == "subAgentActivity":
            return  # it ends with an activity of its own
        for item in items:
            item.open = False
            if item.result is None:
                item.result = ""

    def _own(self, item: Item, data: dict) -> None:
        for thread in data.get("receiverThreadIds") or []:
            self._agents.setdefault(str(thread), item)

    def _sub(self, thread: str, method: str, params: dict) -> None:
        """A subagent's thread: its finished steps nest under the call that
        started it."""
        owner, data = self._agents.get(thread), params.get("item")
        if owner is None or method not in ("item/started", "item/completed") \
                or not isinstance(data, dict):
            return
        done, key = method == "item/completed", f"{thread}/{data.get('id')}"
        if data.get("type") == "agentMessage":
            if done and str(data.get("text") or "").strip():
                owner.children.append(Item("text", str(data["text"])))
            return
        items = self._items.get(key)
        if items is None:
            items = self._items[key] = self._steps(data, str(data.get("id") or ""))
            for item in items:
                item.open = True
                self.conv._tools[item.tool_id] = item
                owner.children.append(item)
        self._update(items, data, done=done)

    # --- requests -------------------------------------------------------------------------

    def _on_request(self, request_id: Any, method: str, params: dict) -> Permission | None:
        rid = f"rpc{request_id}"
        item_id = str(params.get("itemId") or "")
        if method == "item/commandExecution/requestApproval":
            return self._ask_command(request_id, rid, item_id, params)
        if method == "item/fileChange/requestApproval":
            return self._ask_change(request_id, rid, item_id, params)
        if method == "item/tool/requestUserInput":
            return self._ask_user(request_id, rid, item_id, params)
        if method == "item/permissions/requestApproval":
            return self._ask_access(request_id, rid, item_id, params)
        if method == "mcpServer/elicitation/request":
            return self._ask_server(request_id, rid, params)
        return super()._on_request(request_id, method, params)

    def _decide(self, request_id: Any, response: dict) -> None:
        if response.get("behavior") != "allow":
            decision = "decline"  # the turn goes on
        else:
            decision = "acceptForSession" if "updatedPermissions" in response else "accept"
        self.reply(request_id, {"decision": decision})

    def _ask_command(self, request_id: Any, rid: str, item_id: str,
                     params: dict) -> Permission | None:
        command = shell_command(str(params.get("command") or ""))
        network = params.get("networkApprovalContext")
        if not command and isinstance(network, dict):
            perm = Permission(rid, "Network", {"url": str(network.get("host") or "")},
                              leaves_sandbox=True)
        else:
            perm = Permission(rid, "Shell", {"command": command})
        perm.description = str(params.get("reason") or "")
        perm.tool_use_id = item_id
        # Codex offers it only where a like command would be recognized; its
        # other way to remember writes a rule to the user's settings.
        if "acceptForSession" in (params.get("availableDecisions") or []):
            perm.suggestions = [{"decision": "acceptForSession"}]
            perm.remembers = ["commands Codex counts as this one"]
        return self._ask(perm, lambda r: self._decide(request_id, r), command)

    def _ask_change(self, request_id: Any, rid: str, item_id: str,
                    params: dict) -> Permission | None:
        items = self._items.get(item_id, [])
        perm = Permission(rid, "Edit", {"file_path": ", ".join(
            str(i.input.get("file_path") or "") for i in items)},
            description=str(params.get("reason") or ""), tool_use_id=item_id,
            suggestions=[{"decision": "acceptForSession"}],
            remembers=[f"changes under `{params['grantRoot']}`" if params.get("grantRoot")
                       else "changes Codex counts as these"],
            blocked_path=str(params.get("grantRoot") or ""),
            patch="\n".join(i.patch for i in items))
        return self._ask(perm, lambda r: self._decide(request_id, r))

    def _ask_access(self, request_id: Any, rid: str, item_id: str,
                    params: dict) -> Permission | None:
        wanted = params.get("permissions") if isinstance(params.get("permissions"), dict) else {}
        what = []
        if wanted.get("network"):
            what.append("the network")
        files = wanted.get("fileSystem")
        if isinstance(files, dict):
            for key in ("read", "write"):
                if isinstance(files.get(key), list) and files[key]:
                    what.append(f"{key}: {', '.join(map(str, files[key]))}")
        if not what:
            what = ["access outside the sandbox"]
        perm = Permission(rid, "Access", {"description": "; ".join(what)},
                          description=str(params.get("reason") or ""), tool_use_id=item_id,
                          suggestions=[{"scope": "session"}], remembers=list(what),
                          leaves_sandbox=True)

        def answer(response: dict) -> None:
            granted = {k: v for k, v in wanted.items() if v is not None} \
                if response.get("behavior") == "allow" else {}
            self.reply(request_id, {"permissions": granted, "scope":
                                    "session" if "updatedPermissions" in response else "turn"})
        return self._ask(perm, answer)

    def _ask_user(self, request_id: Any, rid: str, item_id: str,
                  params: dict) -> Permission | None:
        asked = [q for q in params.get("questions") or []
                 if isinstance(q, dict) and isinstance(q.get("question"), str)]
        perm = ask_user(rid, [{"question": q["question"], "header": str(q.get("header") or ""),
                               "options": q.get("options") or []} for q in asked], item_id)
        item = self._tool(Item("tool", name=perm.tool, input=dict(perm.input), open=True,
                               tool_id=item_id or rid))
        perm.tool_use_id = item.tool_id

        def answer(response: dict) -> None:
            item.open, item.result = False, ""
            allowed = response.get("behavior") == "allow"
            self.reply(request_id, {"answers": {
                str(q.get("id")): {"answers": perm.picked.get(q["question"], [])
                                   if allowed else []} for q in asked}})
        return self._ask(perm, answer)

    def _ask_server(self, request_id: Any, rid: str, params: dict) -> Permission | None:
        """An MCP server asks: whether a tool of its may run, or (what XeFM
        has no form for) something to fill in, which is declined."""
        schema = params.get("requestedSchema")
        fields = schema.get("properties") if isinstance(schema, dict) else None
        server = str(params.get("serverName") or "MCP server")
        if self.channel is not None and server == self.channel.name and not fields:
            # XeFM's own tool: what it does is asked by XeFM, once.
            self.reply(request_id, {"action": "accept", "content": {}, "_meta": None})
            return None
        if params.get("mode") not in ("form", "openai/form", "openaiForm") or fields:
            self.reply(request_id, {"action": "decline", "content": None, "_meta": None})
            self.conv.add_notice(f"{server} asked for something XeFM cannot show: "
                                 f"{params.get('message') or params.get('title') or ''}")
            return None
        perm = Permission(rid, server, {"description": str(params.get("message") or "")})

        def answer(response: dict) -> None:
            ok = response.get("behavior") == "allow"
            self.reply(request_id, {"action": "accept" if ok else "decline",
                                    "content": {} if ok else None, "_meta": None})
        return self._ask(perm, answer)


class CodexProtocol(RpcProtocol):
    client_class = CodexClient

    def conversation(self) -> Conversation:
        conv = super().conversation()
        conv.commands = [{"name": "compact",
                          "description": "Summarize the conversation to free up the context"}]
        return conv
