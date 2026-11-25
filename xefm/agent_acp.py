"""Copilot and Antigravity drawn by XeFM: the Agent Client Protocol
(``copilot --acp``, ``agy acp``), the JSON-RPC protocol editors use to host an
agent (checked against GitHub Copilot CLI 1.0.114 and Antigravity CLI 1.5.14).

XeFM opens a session in the folder (``session/new``, or ``session/resume`` /
``session/load`` to go back to one) and sends each message as a
``session/prompt``, whose answer ends the turn. What the agent does meanwhile
comes as ``session/update`` notifications - its reply in chunks, its tool
calls, its plan - and what it may not do unasked as
``session/request_permission`` requests, whose options XeFM offers the user.
XeFM offers the agent no file or terminal methods of its own: it works on the
disk as it does in a terminal.
"""

from __future__ import annotations

import re
from typing import Any

from xefm.agent_chat import Item, Permission
from xefm.agent_rpc import RpcClient, RpcProtocol, ask_user, normal_path, unified_patch
from xefm.log_manager import getLogger

logger = getLogger("AgentAcp")

PROTOCOL_VERSION = 1

#: The error an agent that is not signed in answers with.
AUTH_REQUIRED = -32000

#: How a tool call is named in the transcript, by its ACP kind.
_KINDS = {"read": "Read", "edit": "Edit", "delete": "Delete", "move": "Move",
          "search": "Search", "execute": "Shell", "think": "Think", "fetch": "Fetch"}

#: A stop that is not simply the end of the turn, in words.
_STOPS = {"cancelled": "Interrupted", "max_tokens": "Stopped: the reply's length limit",
          "max_turn_requests": "Stopped: too many steps in one turn",
          "refusal": "The agent declined to go on"}

#: What the agents put around a command's output: Antigravity's report of it,
#: Copilot's last line.
_AGY_OUTPUT = re.compile(r"\A(?:Created At: .*\n)?(?:Completed At: .*\n)?"
                         r"(?:Command exited with code -?\d+\.\n)?\n*Command output:\n")
_COPILOT_EXIT = re.compile(r"\n?<(?:shellId: \S+ )?(?:command )?"
                           r"(?:completed|exited) with exit code -?\d+>\s*\Z")

#: A patch's lines that name the file it changes (Copilot's ``apply_patch``).
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)


def _mode_name(mode: str) -> str:
    """The short name in a mode's id (Copilot's are URLs)."""
    return mode.rsplit("#", 1)[-1]


#: The modes Shift+Tab leaves out, as it leaves out Claude Code's
#: ``bypassPermissions``: those that run tools without asking.
_UNASKED = ("autopilot", "auto", "yolo", "bypassPermissions")


#: What a restricted session that opens in a mode that does not ask says.
AUTO_NOTICE = ("{agent} is in auto mode: it decides itself which commands it runs, and XeFM "
               "can turn down only those it asks about. What it does through XeFM is asked "
               "as always.")


def _content_text(content: Any) -> str:
    """The text of one content block."""
    if not isinstance(content, dict):
        return ""
    kind = content.get("type")
    if kind == "text":
        return str(content.get("text") or "")
    if kind == "resource_link":
        return f"[{content.get('name') or content.get('uri')}]({content.get('uri')})"
    if kind == "resource":
        return str((content.get("resource") or {}).get("text") or "")
    return f"[{kind}]" if kind else ""


def _git_patch(diff: str) -> str:
    """A ``git diff``'s hunks, without the headers that name the file."""
    at = diff.find("\n@@")
    return diff[at + 1:].rstrip() if at >= 0 else diff.strip()


class AcpClient(RpcClient):
    """One ACP agent process with one session."""

    def __init__(self, argv: list[str], *, agent: str = "", login: str = "",
                 plain_commands: bool = False, restrict: bool = True,
                 first: dict | None = None, sandbox: str = "not known",
                 **kwargs: Any) -> None:
        super().__init__(argv, **kwargs)
        self.conv.sandbox = sandbox
        self.agent = agent
        #: How to sign in, for the notice when the agent says it is not.
        self.login = login
        #: Whether a ``/`` command's reply is plain text, not Markdown.
        self.plain_commands = plain_commands
        self.restrict = restrict
        #: What the entry's command asked for: ``mode``, ``model``, ``effort``.
        self.first = dict(first or {})
        self._capabilities: dict = {}
        self._loading = False
        self._command_turn = False
        #: The session's options (``configOptions``), by category: model,
        #: thought_level.
        self._options: dict[str, dict] = {}
        self._all_modes: tuple = ()
        self._said_id: Any = None

    # --- opening ------------------------------------------------------------------

    def _open(self) -> None:
        self.call("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "clientInfo": {"name": "xefm", "title": "XeFM", "version": "1"},
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                   "terminal": False, "elicitation": {"form": {}}}},
            self._initialized, self._refused)

    def _refused(self, error: dict) -> None:
        text = str(error.get("message") or "the agent refused")
        if error.get("code") == AUTH_REQUIRED or "auth" in text.lower():
            hint = f": run `{self.login}` in a terminal" if self.login else ""
            self._failed(f"Not signed in{hint} ({text})")
        else:
            self._failed(f"{self.agent} could not open a session: {text}")

    def _initialized(self, result: dict) -> None:
        caps = result.get("agentCapabilities")
        self._capabilities = caps if isinstance(caps, dict) else {}
        params = {"cwd": self.cwd, "mcpServers": self._servers()}
        session = self._capabilities.get("sessionCapabilities")
        if self.resume and isinstance(session, dict) and "resume" in session:
            self.call("session/resume", dict(params, sessionId=self.resume),
                      self._session, self._refused)
        elif self.resume and self._capabilities.get("loadSession"):
            # It sends the whole conversation again, which is on screen.
            self._loading = True
            self.call("session/load", dict(params, sessionId=self.resume),
                      self._session, self._refused)
        else:
            if self.resume:
                self.conv.add_notice("This agent cannot go back to a conversation: "
                                     "it starts a new one")
            self.call("session/new", params, self._session, self._refused)

    def _servers(self) -> list[dict]:
        """XeFM's MCP server, for an agent that takes one over HTTP."""
        takes = self._capabilities.get("mcpCapabilities")
        if self.channel is None or not isinstance(takes, dict) or not takes.get("http"):
            return []
        self._tools_coming = True
        return [{"type": "http", "name": self.channel.name, "url": self.channel.url,
                 "headers": [{"name": k, "value": v}
                             for k, v in self.channel.headers.items()]}]

    def _session(self, result: dict) -> None:
        conv = self.conv
        self._loading = False
        conv.session_id = str(result.get("sessionId") or self.resume or conv.session_id)
        self._have_modes(result.get("modes"))
        self._have_options(result.get("configOptions"))
        self._have_old_models(result.get("models"))
        mode = conv.mode_choice or self.first.get("mode", "")
        if not mode and self.restrict and _mode_name(conv.permission_mode) == "auto":
            # Left as it is: Antigravity's "default" turns its sandbox off,
            # which is not XeFM's to do (#995).
            conv.add_notice(AUTO_NOTICE.format(agent=self.agent or "The agent"))
        if mode and self._known_mode(mode) and self.set_mode(self._known_mode(mode)):
            conv.permission_mode = self._known_mode(mode)
        model = conv.model_choice or self.first.get("model", "")
        if model:
            self.set_model(model)
        effort = conv.effort_choice or self.first.get("effort", "")
        if effort in conv.efforts:
            self.set_effort(effort)
        self._ready()

    def _known_mode(self, mode: str) -> str:
        for known in self._all_modes:
            if mode in (known, _mode_name(known)):
                return known
        return ""

    def _have_modes(self, modes: Any) -> None:
        if not isinstance(modes, dict):
            return
        conv = self.conv
        offered = [m for m in modes.get("availableModes") or []
                   if isinstance(m, dict) and isinstance(m.get("id"), str)]
        self._all_modes = tuple(m["id"] for m in offered)
        conv.modes = tuple(m["id"] for m in offered if _mode_name(m["id"]) not in _UNASKED)
        conv.permission_mode = str(modes.get("currentModeId") or "")
        labels = {m["id"]: str(m.get("name") or m["id"]).lower() for m in offered}
        for mode in labels:
            # The plain one needs no name in the header.
            if _mode_name(mode) in ("default", "agent"):
                labels[mode] = ""
            elif _mode_name(mode) == "plan":
                labels[mode] = "plan mode"
        conv.mode_labels = labels

    def _have_options(self, options: Any) -> None:
        conv = self.conv
        for option in options if isinstance(options, list) else []:
            if not isinstance(option, dict) or not isinstance(option.get("id"), str):
                continue
            values = []
            for v in option.get("options") or []:
                if isinstance(v, dict) and isinstance(v.get("options"), list):
                    values += [w for w in v["options"] if isinstance(w, dict)]  # a group
                elif isinstance(v, dict):
                    values.append(v)
            values = [v for v in values if isinstance(v.get("value"), str)]
            current = option.get("currentValue")
            category = option.get("category") or option["id"]
            if category == "model":
                self._options["model"] = option
                conv.models = [{"value": v["value"], "displayName": str(v.get("name")
                                                                        or v["value"]),
                                "description": str(v.get("description") or "")} for v in values]
                conv.model = next((str(v.get("name") or v["value"]) for v in values
                                   if v["value"] == current), str(current or conv.model))
            elif category == "thought_level":
                self._options["effort"] = option
                conv.efforts = tuple(v["value"] for v in values)

    def _have_old_models(self, models: Any) -> None:
        """The models of an agent that has no option for them."""
        if not isinstance(models, dict) or "model" in self._options:
            return
        offered = [m for m in models.get("availableModels") or []
                   if isinstance(m, dict) and isinstance(m.get("modelId"), str)]
        self.conv.models = [{"value": m["modelId"], "displayName": str(m.get("name")
                                                                       or m["modelId"]),
                             "description": str(m.get("description") or "")} for m in offered]
        self.conv.model = str(models.get("currentModelId") or self.conv.model)

    # --- turns -----------------------------------------------------------------------

    def _start_turn(self, text: str) -> None:
        self._command_turn = text.startswith("/")
        self._said_id = None
        self.call("session/prompt", {"sessionId": self.conv.session_id,
                                     "prompt": [{"type": "text", "text": text}]},
                  self._stopped, self._prompt_failed)

    def _stopped(self, result: dict) -> None:
        reason = str(result.get("stopReason") or "end_turn")
        if reason == "end_turn":
            self._turn_ended()
        else:
            self._turn_ended(_STOPS.get(reason, f"Stopped: {reason}"),
                             error=reason != "cancelled")

    def _prompt_failed(self, error: dict) -> None:
        text = str(error.get("message") or "The agent could not answer")
        data = error.get("data")
        if isinstance(data, dict):
            data = data.get("details") or data.get("message")
        if isinstance(data, str) and data and data not in text:
            text += f"\n{data}"
        self._turn_ended(text, error=True)

    def _cancel_turn(self) -> bool:
        ok = self.notify("session/cancel", {"sessionId": self.conv.session_id})
        for answer in list(self._answers.values()):
            answer({"behavior": "cancel"})
        self._answers.clear()
        self.conv.permissions.clear()
        self.conv._update_state()
        return ok

    # --- what the user sets --------------------------------------------------------------

    def set_mode(self, mode: str) -> bool:
        return self.call("session/set_mode",
                         {"sessionId": self.conv.session_id, "modeId": mode})

    def set_model(self, model: str) -> bool:
        conv = self.conv

        def switched(result: dict) -> None:
            conv.model_choice = model
            self._have_options(result.get("configOptions"))
            if "model" not in self._options:
                conv.model = model

        def failed(error: dict) -> None:
            conv.add_notice(f"Could not switch the model: {error.get('message')}", error=True)
        option = self._options.get("model")
        if option is not None:
            return self.call("session/set_config_option", {
                "sessionId": conv.session_id, "configId": option["id"], "value": model},
                switched, failed)
        return self.call("session/set_model", {"sessionId": conv.session_id, "modelId": model},
                         switched, failed)

    def set_effort(self, level: str) -> bool:
        option = self._options.get("effort")
        return option is not None and self.call("session/set_config_option", {
            "sessionId": self.conv.session_id, "configId": option["id"], "value": level})

    # --- notifications ----------------------------------------------------------------------

    def _on_notification(self, method: str, params: dict) -> Permission | str | None:
        conv = self.conv
        if method == "$/cancel_request":
            rid = f"rpc{params.get('requestId')}"
            return self._withdraw(rid) if rid in conv.permissions else None
        update = params.get("update")
        if method != "session/update" or not isinstance(update, dict):
            return None
        what = update.get("sessionUpdate")
        if what == "available_commands_update":
            conv.commands = [
                {"name": str(c.get("name")), "description": str(c.get("description") or ""),
                 "argumentHint": str((c.get("input") or {}).get("hint") or "")
                 if isinstance(c.get("input"), dict) else ""}
                for c in update.get("availableCommands") or [] if isinstance(c, dict)]
        elif what == "current_mode_update":
            conv.permission_mode = str(update.get("currentModeId") or conv.permission_mode)
        elif what == "config_option_update":
            self._have_options(update.get("configOptions"))
        elif what == "usage_update":
            conv.context_tokens = int(update.get("used") or 0)
            conv.context_window = int(update.get("size") or 0)
        elif self._loading:
            return None  # the conversation played back
        elif what == "agent_message_chunk":
            self._chunk("text", update)
        elif what == "agent_thought_chunk":
            self._chunk("thinking", update)
        elif what in ("tool_call", "tool_call_update"):
            self._tool_update(update)
        elif what == "plan":
            self._set_todos([{"content": str(e.get("content") or ""),
                              "activeForm": str(e.get("content") or ""),
                              "status": str(e.get("status") or "pending")}
                             for e in update.get("entries") or [] if isinstance(e, dict)])
        return None

    def _chunk(self, kind: str, update: dict) -> None:
        text, said = _content_text(update.get("content")), update.get("messageId")
        items = self.conv.items
        last = items[-1] if items else None
        if last is None or last.kind != kind or not last.open or said != self._said_id:
            self._close_text()
            last = Item(kind, open=True)
            last.plain = kind == "text" and self.plain_commands and self._command_turn \
                and said is None
            items.append(last)
        self._said_id = said
        last.text += text

    def _tool_update(self, update: dict) -> None:
        tid = str(update.get("toolCallId") or "")
        item = self.conv._tools.get(tid)
        if item is None:
            item = self._tool(Item("tool", name="Tool", tool_id=tid, open=True))
        _fold_tool(item, update)

    # --- requests -----------------------------------------------------------------------------

    def _on_request(self, request_id: Any, method: str, params: dict) -> Permission | None:
        if method == "session/request_permission":
            return self._ask_tool(request_id, params)
        if method == "elicitation/create" and params.get("mode", "form") == "form":
            return self._ask_form(request_id, params)
        return super()._on_request(request_id, method, params)

    def _ask_tool(self, request_id: Any, params: dict) -> Permission | None:
        call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
        options = [o for o in params.get("options") or []
                   if isinstance(o, dict) and "optionId" in o]
        by_kind = {str(o.get("kind")): o["optionId"] for o in reversed(options)}
        probe = Item("tool", name="Tool")
        _fold_tool(probe, call)
        perm = Permission(f"rpc{request_id}", probe.name, dict(probe.input),
                          tool_use_id=str(call.get("toolCallId") or ""),
                          patch=probe.patch)
        title = str(call.get("title") or "")
        if title and title not in probe.input.values():
            perm.description = title
        if "allow_always" in by_kind:
            perm.suggestions = [{"optionId": by_kind["allow_always"]}]
        item = self.conv._tools.get(perm.tool_use_id)
        if item is None and perm.tool_use_id:
            self._tool_update(dict(call))
        elif item is not None and probe.patch and not item.patch:
            item.patch, item.input = probe.patch, dict(probe.input)

        def answer(response: dict) -> None:
            behavior = response.get("behavior")
            option = None
            if behavior == "allow":
                kinds = ("allow_always", "allow_once") if "updatedPermissions" in response \
                    else ("allow_once", "allow_always")
                option = next((by_kind[k] for k in kinds if k in by_kind), None)
            elif behavior == "deny":
                option = next((by_kind[k] for k in ("reject_once", "reject_always")
                               if k in by_kind), None)
            self.reply(request_id, {"outcome": {"outcome": "cancelled"} if option is None
                                    else {"outcome": "selected", "optionId": option}})
        return self._ask(perm, answer, str(probe.input.get("command") or ""))

    def _ask_form(self, request_id: Any, params: dict) -> Permission | None:
        """A question with a form to fill in: each field one question."""
        schema = params.get("requestedSchema")
        fields = schema.get("properties") if isinstance(schema, dict) else None
        fields = {k: v for k, v in (fields or {}).items() if isinstance(v, dict)}
        asked: dict[str, dict] = {}
        questions = []
        for key, spec in fields.items():
            if key.endswith("_other") and key[:-6] in fields:
                continue  # the field of another's typed answer
            many = spec.get("type") == "array"
            source = spec.get("items") if many and isinstance(spec.get("items"), dict) else spec
            choices = [(c.get("const"), str(c.get("title") or c.get("const")))
                       for c in source.get("oneOf") or source.get("anyOf") or []
                       if isinstance(c, dict)]
            choices = choices or [(v, str(v)) for v in source.get("enum") or []]
            if spec.get("type") == "boolean":
                choices = [(True, "Yes"), (False, "No")]
            text = str(spec.get("title") or spec.get("description") or key)
            while text in asked:
                text += " "  # two fields with one title: each its own question
            asked[text] = {"key": key, "choices": choices, "many": many,
                           "type": spec.get("type")}
            questions.append({"question": text, "header": "Question", "multiSelect": many,
                              "options": [{"label": label} for _value, label in choices]})
        message = str(params.get("message") or "")
        if len(questions) == 1 and message and message not in questions[0]["question"]:
            questions[0]["header"] = message
        perm = ask_user(f"rpc{request_id}", questions, str(params.get("toolCallId") or ""))
        item = self.conv._tools.get(perm.tool_use_id)
        if item is None:
            item = self._tool(Item("tool", tool_id=perm.tool_use_id or perm.request_id, open=True))
            perm.tool_use_id = item.tool_id
        item.name, item.input = perm.tool, dict(perm.input)

        def answer(response: dict) -> None:
            item.result = item.result or ""
            item.open = False
            if response.get("behavior") != "allow":
                self.reply(request_id, {"action": "cancel" if response.get("behavior")
                                        == "cancel" else "decline"})
                return
            content: dict[str, Any] = {}
            for text, field in asked.items():
                value, other = _form_value(field, perm.picked.get(text, []))
                if value is not None:
                    content[field["key"]] = value
                if other:
                    okey = field["key"] + "_other"
                    content[okey if okey in fields else field["key"]] = other
            self.reply(request_id, {"action": "accept", "content": content})
        return self._ask(perm, answer)


def _form_value(field: dict, labels: list[str]) -> tuple[Any, str]:
    """A form field's value from the labels picked, and what was typed
    instead of one."""
    known = {label: value for value, label in field["choices"]}
    picked = [known[lb] for lb in labels if lb in known]
    typed = ", ".join(lb for lb in labels if lb not in known)
    if field["many"]:
        return picked, typed
    if picked:
        return picked[0], typed
    if typed and not known:
        kind = field["type"]
        try:
            if kind == "integer":
                return int(typed), ""
            if kind == "number":
                return float(typed), ""
        except ValueError:
            logger.warning(f"Not a number: {typed}")
        return typed, ""
    return None, typed


def _fold_tool(item: Item, update: dict) -> None:
    """What a tool call (or an update of one) says, folded into ``item``."""
    kind = update.get("kind")
    if item.name in ("", "Tool") and isinstance(kind, str):
        item.name = _KINDS.get(kind, "Tool")
    if item.name == "AskUserQuestion":
        kind = None  # its form made it one; the updates still name the tool
    raw = update.get("rawInput")
    raw = raw if isinstance(raw, (dict, str)) else {}
    title = str(update.get("title") or "")
    path = _path_of(update, raw)
    if isinstance(kind, str):
        command = _first(raw, "command", "CommandLine", "cmd")
        data: dict[str, Any] = {}
        if item.name == "Shell":
            # The call says what it is for; the permission request does not.
            data["command"] = command or title
            purpose = _first(raw, "description", "toolSummary") \
                or item.input.get("description", "")
            if purpose:
                data["description"] = purpose
        elif item.name in ("Read", "Edit", "Delete") and path:
            data["file_path"] = path
        elif item.name == "Search":
            data["pattern"] = _first(raw, "pattern", "query", "Query", "Pattern") or title
        elif item.name == "Fetch":
            data["url"] = _first(raw, "url", "Url") or title
        else:
            data["description"] = title
            if update.get("name") and item.name == "Tool":
                item.name = str(update["name"])
        item.input = data if any(data.values()) else item.input
        if item.name == "Edit" and isinstance(raw, dict) and isinstance(raw.get("diff"), str):
            item.patch = item.patch or _git_patch(raw["diff"])
    texts = []
    content = update.get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "content":
            texts.append(_content_text(block.get("content")))
        elif block.get("type") == "diff":
            old, new = str(block.get("oldText") or ""), str(block.get("newText") or "")
            file = normal_path(str(block.get("path") or ""))
            patch = unified_patch(old, new)
            first = item.input.get("file_path") in (None, "", file) \
                or "new_string" not in item.input
            if first:
                item.input = {"file_path": file, "old_string": old, "new_string": new}
                item.patch = patch
            else:
                item.patch += f"\n--- {file}\n{patch}"  # one call, several files
    out = update.get("rawOutput")
    if texts:
        text = "\n".join(texts)
        item.result = _output(text) if item.name == "Shell" else text
    elif isinstance(out, str):
        item.result = out
    elif isinstance(out, dict):
        text = _first(out, "content", "output", "message", "error")
        if text:
            item.result = _output(text) if item.name == "Shell" else text
    if isinstance(out, dict):
        codes = [out.get("exit_code"), out.get("exitCode")]
        codes += [c.get("exitCode") for c in out.get("contents") or [] if isinstance(c, dict)]
        if any(isinstance(c, int) and c for c in codes):
            item.is_error = True
    status = update.get("status")
    if status in ("completed", "failed"):
        item.open = False
        item.is_error = item.is_error or status == "failed"
        if isinstance(out, dict) and out.get("code") == "denied":
            item.denied = True
        item.result = item.result or ""
    if item.result is not None and item.open and not item.result:
        item.result = None


def _output(text: str) -> str:
    """A command's output without what the agent put around it."""
    return _COPILOT_EXIT.sub("", _AGY_OUTPUT.sub("", text))


def _first(data: Any, *keys: str) -> str:
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key]
    return ""


def _path_of(update: dict, raw: Any) -> str:
    for place in update.get("locations") or []:
        if isinstance(place, dict) and isinstance(place.get("path"), str):
            return normal_path(place["path"])
    if isinstance(raw, str):
        return ", ".join(_PATCH_FILE.findall(raw))
    return normal_path(_first(raw, "path", "file_path", "Path", "fileName", "filePath"))


class AcpProtocol(RpcProtocol):
    client_class = AcpClient
