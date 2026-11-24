"""What the drawn agents that speak JSON-RPC share: Codex's app-server
(:mod:`xefm.agent_codex`) and the Agent Client Protocol
(:mod:`xefm.agent_acp` - Copilot, Antigravity).

Both keep a session inside a long-running process, one JSON-RPC message per
line each way: XeFM opens a session (or goes back to one), sends a turn at a
time, folds the notifications into a :class:`~xefm.agent_chat.Conversation`
and answers the requests the agent sends (may this command run?).
:class:`RpcClient` holds what does not depend on which of the two it is; a
subclass fills in the methods. Like :mod:`xefm.agent_chat`, no UI here.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
from typing import Any, Callable

from xefm.agent_chat import (ASK_USER_TOOL, ASKING, ChatClient, Conversation, Item,
                             Permission, Protocol)
from xefm.log_manager import getLogger

logger = getLogger("AgentRpc")

#: JSON-RPC's "no such method": what XeFM answers a request it does not know.
METHOD_NOT_FOUND = -32601


def normal_path(path: str) -> str:
    """A path as Codex and Antigravity write it in a link or a tool call
    (``/C:/Users/...`` on Windows), as this system does."""
    if os.name == "nt" and re.match(r"/[A-Za-z]:[\\/]", path):
        return path[1:].replace("/", "\\")
    return path


def unified_patch(old: str, new: str) -> str:
    """The changed lines between two texts as a diff's hunks, without the
    file headers (the transcript names the file over it)."""
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2))
    return "\n".join(lines[2:])


def hunk_edits(diff: str) -> list[dict]:
    """A unified diff's hunks as the edits that made them (``old_string`` /
    ``new_string``), which :func:`xefm.agent_chat.edit_before` can undo."""
    edits: list[dict] = []
    old: list[str] = []
    new: list[str] = []

    def flush() -> None:
        if old != new:
            edits.append({"old_string": "\n".join(old), "new_string": "\n".join(new)})
        old.clear()
        new.clear()

    for line in diff.split("\n"):
        if line.startswith("@@"):
            flush()
        elif line.startswith(("--- ", "+++ ", "\\")):
            continue
        elif line.startswith("-"):
            old.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
        elif line.startswith(" "):
            old.append(line[1:])
            new.append(line[1:])
    flush()
    return edits


class RpcClient(ChatClient):
    """A drawn agent that speaks JSON-RPC, over ``conv``.

    ``resume`` is the session to go back to ("" for a new one). ``refuse``
    says why a shell command may not run at all (None when it may be asked):
    such a command is declined without asking the user."""

    def __init__(self, argv: list[str], *, conv: Conversation, resume: str = "",
                 refuse: Callable[[str], str | None] | None = None, **kwargs: Any) -> None:
        super().__init__(argv, **kwargs)
        self.conv = conv
        self.resume = resume
        self._refuse = refuse
        self._calls: dict[int, tuple[Callable[[dict], Any], Callable[[dict], Any]]] = {}
        #: How to answer each question asked of the user, by request id.
        self._answers: dict[str, Callable[[dict], Any]] = {}
        #: Messages typed before the session was ready or while a turn ran.
        self._queue: list[str] = []
        self.ready = False
        self.in_turn = False

    # --- the process -------------------------------------------------------------

    def _spawn(self) -> None:
        # A .cmd an npm install made (codex.cmd) is found by its full path only.
        found = shutil.which(self.argv[0], path=self.env.get("PATH"))
        if found:
            self.argv[0] = found
        super()._spawn()

    def _open(self) -> None:
        """Open the session; a subclass ends with :meth:`_ready`."""
        raise NotImplementedError

    def _ready(self) -> None:
        self.ready = True
        self.conv._update_state()
        self._next()

    def _failed(self, text: str) -> None:
        """The session cannot open: say so and end the process (Enter in the
        view starts it again)."""
        self.conv.add_notice(text, error=True)
        self._queue.clear()
        self.close()

    # --- messages ------------------------------------------------------------------

    def call(self, method: str, params: dict, then: Callable[[dict], Any] | None = None,
             failed: Callable[[dict], Any] | None = None) -> bool:
        """A request; ``then(result)`` or ``failed(error)`` once answered."""
        rid = next(self._ids)

        def log(error: dict) -> None:
            logger.warning(f"Agent refused {method}: {error.get('message')}")
        self._calls[rid] = (then or (lambda result: None), failed or log)
        ok = self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not ok:
            self._calls.pop(rid, None)
        return ok

    def notify(self, method: str, params: dict | None = None) -> bool:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        return self._write(msg)

    def reply(self, request_id: Any, result: Any) -> bool:
        return self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def refuse_request(self, request_id: Any, method: str) -> bool:
        logger.warning(f"Agent asked for {method}, which XeFM does not offer")
        return self._write({"jsonrpc": "2.0", "id": request_id, "error": {
            "code": METHOD_NOT_FOUND, "message": f"{method} is not supported"}})

    def handle(self, msg: dict) -> Permission | str | None:
        """Take in one message (on the UI thread): a question to ask the
        user, the id of one the agent withdrew, or None."""
        method = msg.get("method")
        if isinstance(method, str):
            params = msg.get("params")
            params = params if isinstance(params, dict) else {}
            if "id" in msg:
                return self._on_request(msg["id"], method, params)
            return self._on_notification(method, params)
        rid = msg.get("id")
        call = self._calls.pop(rid, None) if isinstance(rid, int) else None
        if call is None:
            return None
        then, failed = call
        if isinstance(msg.get("error"), dict):
            failed(msg["error"])
        else:
            result = msg.get("result")
            then(result if isinstance(result, dict) else {})
        return None

    def _on_request(self, request_id: Any, method: str, params: dict) -> Permission | None:
        self.refuse_request(request_id, method)
        return None

    def _on_notification(self, method: str, params: dict) -> Permission | str | None:
        return None

    # --- turns -----------------------------------------------------------------------

    def send(self, text: str) -> bool:
        """A user message: a turn of its own, after the one now running."""
        if not self.running:
            return False
        self._queue.append(text)
        self._next()
        return True

    def _next(self) -> None:
        if self.ready and not self.in_turn and self._queue:
            self.in_turn = True
            self._start_turn(self._queue.pop(0))

    def _start_turn(self, text: str) -> None:
        raise NotImplementedError

    def _turn_ended(self, notice: str = "", *, error: bool = False) -> None:
        """The turn now running is over (``notice`` when it did not simply
        finish); the next message typed meanwhile goes out."""
        if not self.in_turn:
            return
        self.in_turn = False
        conv = self.conv
        conv.pending_turns = max(0, conv.pending_turns - 1)
        if notice:
            for item in conv._all_items():
                if item.kind == "tool" and item.open:
                    item.is_error = True  # cut short, not done
        conv.close_open_items()
        if notice:
            conv.add_notice(notice, error=error)
        self._answers.clear()
        conv.permissions.clear()
        conv._update_state()
        self._next()

    def interrupt(self) -> bool:
        return self.in_turn and self._cancel_turn()

    def _cancel_turn(self) -> bool:
        raise NotImplementedError

    # --- questions to the user ---------------------------------------------------------

    def _ask(self, perm: Permission, answer: Callable[[dict], Any],
             command: str = "") -> Permission | None:
        """Hand ``perm`` to the user, ``answer(response)`` with what they say
        (:func:`xefm.agent_chat.allow` / :func:`~xefm.agent_chat.deny`) - or
        decline it here when ``command`` may not run at all."""
        reason = self._refuse(command) if self._refuse is not None and command else None
        if reason:
            answer({"behavior": "deny", "message": reason})
            item = self.conv._tools.get(perm.tool_use_id)
            if item is not None:
                item.denied = True
            self.conv.add_notice(reason)
            return None
        self._answers[perm.request_id] = answer
        self.conv.permissions[perm.request_id] = perm
        self.conv.state = ASKING
        return perm

    def respond(self, request_id: str, response: dict) -> bool:
        answer = self._answers.pop(request_id, None)
        if answer is None:
            return False  # withdrawn meanwhile
        answer(response)
        return True

    def _withdraw(self, request_id: str) -> str:
        self._answers.pop(request_id, None)
        self.conv.permissions.pop(request_id, None)
        self.conv._update_state()
        return request_id

    # --- what the user sets --------------------------------------------------------------

    def set_mode(self, mode: str) -> bool:
        raise NotImplementedError

    def set_model(self, model: str) -> bool:
        raise NotImplementedError

    def set_effort(self, level: str) -> bool:
        return False

    def approve_plan(self, request_id: str, mode: str) -> None:
        """The user approved a plan: go on with it in ``mode``."""
        self.set_mode(mode)
        self.respond(request_id, {"behavior": "allow"})

    def command(self, text: str) -> bool:
        """Run a ``/`` command the agent has no message for; whether it was
        one."""
        return False

    # --- folding ---------------------------------------------------------------------------

    def _tool(self, item: Item) -> Item:
        """Add a tool call to the transcript."""
        self._close_text()
        self.conv.items.append(item)
        if item.tool_id:
            self.conv._tools[item.tool_id] = item
        return item

    def _close_text(self) -> None:
        """What was being said is over: the next thing is another item."""
        items = self.conv.items
        if items and items[-1].kind in ("text", "thinking"):
            items[-1].open = False

    def _set_todos(self, todos: list[dict]) -> None:
        """The agent's plan as its to-do list: one step of the transcript
        per turn, changed as the plan moves on."""
        for item in reversed(self.conv.items):
            if item.kind == "user":
                break
            if item.kind == "tool" and item.name == "TodoWrite":
                item.input = {"todos": todos}
                return
        self._tool(Item("tool", name="TodoWrite", input={"todos": todos}, result="ok"))


class RpcProtocol(Protocol):
    """How the view drives an :class:`RpcClient`. What the user set - mode,
    model, effort - is kept in the conversation (``*_choice``) and set again
    in a new process."""

    client_class: type[RpcClient]

    def __init__(self, refuse: Callable[[str], str | None] | None = None,
                 **options: Any) -> None:
        self.refuse = refuse
        self.options = options

    def conversation(self) -> Conversation:
        conv = Conversation()
        conv.modes, conv.mode_labels = (), {}
        conv.permission_mode = ""
        return conv

    def client(self, argv: list[str], conv: Conversation, **kwargs: Any) -> RpcClient:
        return self.client_class(argv, conv=conv, resume=conv.session_id,
                                 refuse=self.refuse, **self.options, **kwargs)

    def handle(self, view, msg: dict) -> Permission | str | None:
        return view.client.handle(msg)

    def set_mode(self, view, mode: str) -> None:
        conv = view.conversation
        if view.client.set_mode(mode):
            conv.permission_mode = conv.mode_choice = mode

    def approve_plan(self, view, perm: Permission, mode: str) -> None:
        conv = view.conversation
        conv.answered(perm, True)
        conv.permission_mode = conv.mode_choice = mode
        view.client.approve_plan(perm.request_id, mode)

    def set_model(self, view, model: str) -> None:
        view.client.set_model(model)

    def can_set_model(self, conv: Conversation) -> bool:
        return bool(conv.models)

    def local_commands(self, conv: Conversation) -> list[dict]:
        if not conv.efforts:
            return []
        return [{"name": "effort", "description": "Set how hard the model thinks",
                 "argumentHint": f"<{'|'.join(conv.efforts)}>"}]

    def command(self, view, text: str) -> bool:
        conv = view.conversation
        m = re.fullmatch(r"/effort\s+(\S+)", text)
        if m and conv.efforts:
            level = m.group(1).lower()
            if level not in conv.efforts:
                conv.add_notice(f"No such effort: {level} ({', '.join(conv.efforts)})",
                                error=True)
            elif not view.running:
                conv.add_notice("Start the agent first (Enter) to set the effort", error=True)
            elif view.client.set_effort(level):
                conv.effort_choice = level
                conv.add_notice(f"Effort: {level}")
            return True
        return view.running and view.client.command(text)

    def restart(self, view, *, resume: bool) -> bool:
        old = view.conversation
        if not resume:
            view.new_conversation()
            conv = view.conversation
            conv.mode_choice, conv.model_choice, conv.effort_choice = (
                old.mode_choice, old.model_choice, old.effort_choice)
        return view.start()


def ask_user(request_id: str, questions: list[dict], tool_use_id: str = "") -> Permission:
    """Questions to the user, asked the way Claude Code's are."""
    return Permission(request_id, ASK_USER_TOOL, {"questions": questions},
                      tool_use_id=tool_use_id)
