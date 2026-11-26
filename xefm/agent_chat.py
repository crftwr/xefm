"""AI agent sessions drawn by XeFM (discussion #959): the conversation itself,
not the agent CLI's own screen in a terminal.

XeFM still runs only the CLI the user installed and signed in to - no SDK, no
credentials (#880). For Claude Code that is its streaming JSON mode::

    claude -p --input-format stream-json --output-format stream-json
           --verbose --include-partial-messages --permission-prompt-tool stdio

One JSON object per line each way. XeFM writes the user's messages and its
answers; Claude Code writes the conversation as it happens (``stream_event``
deltas, then each finished ``assistant`` block, ``user`` tool results, a
``result`` at the end of each turn) and, because of ``--permission-prompt-tool
stdio``, a ``control_request`` (``can_use_tool``) each time it would ask the
user whether a tool may run. That question becomes an XeFM dialog - the same
place XeFM's own confirmations of the agent's writes appear.

This module has no UI: :class:`ChatClient` runs the process and hands each
message to the UI thread; :class:`Conversation` folds the messages into the
items the screen draws, and :func:`to_markdown` turns those into the source
of the transcript's ``MarkdownView``. The screen is :mod:`xefm.agent_chat_view`.

The other agents speak JSON-RPC instead: Codex through its app-server
(:mod:`xefm.agent_codex`), Copilot and Antigravity through the Agent Client
Protocol (:mod:`xefm.agent_acp`). Their clients fold what they receive into
the same :class:`Conversation`, as the same items; a :class:`Protocol` is what
the screen drives any of them through.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from xefm.log_manager import getLogger

logger = getLogger("AgentChat")

#: What the ``claude-code`` preset adds to ``command`` for a drawn session.
CLAUDE_STREAM_ARGS = (
    "-p", "--input-format", "stream-json", "--output-format", "stream-json",
    "--verbose", "--include-partial-messages", "--permission-prompt-tool", "stdio",
)

#: Conversation states, as the screen and the screen switcher name them.
STARTING = "starting"
IDLE = "waiting for you"
WORKING = "working"
ASKING = "asking you"
EXITED = "exited"

#: Lines of a tool's result shown in the transcript; the rest is counted.
RESULT_LINES = 6
#: Lines of an edit shown as a diff.
DIFF_LINES = 12


# --- the process -----------------------------------------------------------------


class ChatClient:
    """The agent CLI as a child process speaking stream-json.

    ``post(fn)`` runs ``fn`` on the UI thread (``XeFMApp._call_later``); every
    callback below runs there. ``on_message(msg)`` gets each JSON object the
    CLI writes; ``on_exit(code, stderr_tail)`` once the process is gone."""

    def __init__(self, argv: list[str], *, cwd: str, env: dict,
                 post: Callable[[Callable[[], None]], None],
                 on_message: Callable[[dict], None],
                 on_exit: Callable[[int | None, str], None]) -> None:
        self.argv = list(argv)
        self.cwd = cwd
        self.env = env
        self._post = post
        self._on_message = on_message
        self._on_exit = on_exit
        self._proc: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._stderr: list[str] = []
        self._ids = itertools.count(1)
        self.exit_code: int | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Start the process and its readers. Raises ``OSError`` when it
        cannot start (the program is gone, not executable)."""
        self._spawn()
        self._open()

    def _spawn(self) -> None:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                       | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            # Its own process group, so closing the session also stops what
            # its tools started (a Bash command still running).
            kwargs["start_new_session"] = True
        self._proc = subprocess.Popen(
            self.argv, cwd=self.cwd, env=self.env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, **kwargs)
        threading.Thread(target=self._read_stdout, name="agent-chat-out",
                         daemon=True).start()
        threading.Thread(target=self._read_stderr, name="agent-chat-err",
                         daemon=True).start()

    def _open(self) -> None:
        # Claude Code's SDKs open with this; it answers with what the
        # session has (commands, models) and starts its control channel.
        self.request({"subtype": "initialize", "hooks": None})

    # --- writing ---------------------------------------------------------------

    def _write(self, obj: dict) -> bool:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return False
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as e:
                logger.warning(f"Could not write to the agent: {e}")
                return False
        return True

    def send(self, text: str) -> bool:
        """A user message. One sent while a turn runs waits for it."""
        return self._write({"type": "user", "session_id": "",
                            "message": {"role": "user", "content": text},
                            "parent_tool_use_id": None})

    def request(self, body: dict) -> str | None:
        """A control request (``initialize``, ``interrupt``); its id."""
        rid = f"xefm_{next(self._ids)}"
        ok = self._write({"type": "control_request", "request_id": rid, "request": body})
        return rid if ok else None

    def interrupt(self) -> bool:
        """Stop the turn now running, as Escape does in the CLI."""
        return self.request({"subtype": "interrupt"}) is not None

    def respond(self, request_id: str, response: dict) -> bool:
        """Answer a control request the CLI sent (``can_use_tool``)."""
        return self._write({"type": "control_response", "response": {
            "subtype": "success", "request_id": request_id, "response": response}})

    # --- reading ---------------------------------------------------------------

    def _read_stdout(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                logger.warning(f"Agent wrote a line that is not JSON: {line[:200]}")
                continue
            if isinstance(msg, dict):
                self._post(lambda m=msg: self._on_message(m))
        code = proc.wait()
        self.exit_code = code
        tail = "".join(self._stderr[-20:]).strip()
        self._post(lambda: self._on_exit(code, tail))

    def _read_stderr(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        for raw in proc.stderr:
            self._stderr.append(raw.decode("utf-8", errors="replace"))
            del self._stderr[:-50]

    # --- ending ----------------------------------------------------------------

    def close(self) -> None:
        """End the process: stdin closed (the CLI's own way out), then a
        signal to its process group if it lingers."""
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is not None:
            return
        threading.Thread(target=self._reap, args=(proc,), name="agent-chat-reap",
                         daemon=True).start()

    @staticmethod
    def _reap(proc: subprocess.Popen) -> None:
        try:
            proc.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            if sys.platform == "win32":
                proc.terminate()
            else:
                os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


# --- the conversation ------------------------------------------------------------


@dataclass
class Item:
    """One thing the transcript shows."""

    #: ``user``, ``text``, ``thinking``, ``tool``, ``notice`` or ``error``.
    kind: str
    text: str = ""
    #: A tool's name, input, result, and whether it failed.
    name: str = ""
    input: dict = field(default_factory=dict)
    result: str | None = None
    is_error: bool = False
    #: Still arriving (a reply being streamed, a tool not yet answered).
    open: bool = False
    tool_id: str = ""
    #: The tool's input as streamed so far (JSON text), until it is whole.
    partial: str = ""
    #: Whether the user denied it.
    denied: bool = False
    #: Whether its whole output is shown (the user asked for it).
    expanded: bool = False
    #: A subagent's (``Agent`` / ``Task``) own steps, in order: its tool
    #: calls and what it said, nested under the call that started it.
    children: list = field(default_factory=list)
    #: What a running subagent says it is doing (``task_progress``).
    progress: str = ""
    #: Plain text, not Markdown: a command's reply (``/usage``), shown with
    #: its line breaks and spacing as written.
    plain: bool = False
    #: An edit's changed lines as a diff, where the agent gave one (or both
    #: texts whole) rather than the strings it replaced.
    patch: str = ""


@dataclass
class Permission:
    """A question the CLI asks: may this tool run?"""

    request_id: str
    tool: str
    input: dict
    description: str = ""
    suggestions: list = field(default_factory=list)
    #: What **Always Allow** lets through for the rest of the session, a line
    #: each, in the agent's own terms: the rule it would remember. Empty where
    #: the agent did not say.
    remembers: list = field(default_factory=list)
    #: Whether what is asked would run outside the agent's sandbox, where the
    #: agent says so (#995 rule 6): a sandbox's approval and XeFM's are two
    #: things, and the user should know which this is.
    leaves_sandbox: bool = False
    tool_use_id: str = ""
    blocked_path: str = ""
    #: What an edit would change, as a diff, where the agent said.
    patch: str = ""
    #: The labels picked per question (``ASK_USER_TOOL``), as a list each.
    picked: dict = field(default_factory=dict)


class Conversation:
    """The items of one session, folded from the CLI's messages."""

    def __init__(self) -> None:
        self.items: list[Item] = []
        self.state = STARTING
        self.session_id = ""
        self.model = ""
        self.cwd = ""
        #: Blocks streamed per message id, in order: matched to the finished
        #: ``assistant`` blocks that follow.
        self._blocks: dict[str, list[Item]] = {}
        self._consumed: dict[str, int] = {}
        self._stream_msg = ""
        self._stream_index: dict[int, Item] = {}
        self._tools: dict[str, Item] = {}
        #: Turns asked for and not yet ended: a message sent while one runs
        #: waits for it, and each ends with its own ``result``.
        self.pending_turns = 0
        self.permissions: dict[str, Permission] = {}
        #: Commands the session has (``/compact``...), from the initialize answer.
        self.commands: list[dict] = []
        #: The CLI's permission mode (MODES), as it last reported it.
        self.permission_mode = "default"
        self.last_error = ""
        #: The models the session offers (the initialize answer's ``models``:
        #: ``value``, ``displayName``, ``description``).
        self.models: list[dict] = []
        #: The model the user picked (a ``models`` value), kept across a
        #: restart; "" for the session's own default.
        self.model_choice = ""
        #: The id of a ``set_model`` request not yet answered: its refusal
        #: is the user's to see.
        self.model_request = ""
        #: Tokens the conversation holds (the last main-thread call's
        #: input, cached or not) and the model's context window, once a
        #: turn's ``result`` named it (0 until then).
        self.context_tokens = 0
        self.context_window = 0
        #: The effort ``/effort <level>`` set ("" for the default) and whether
        #: fast mode is on (``system init``'s ``fast_mode_state``): the CLI
        #: keeps both for its process only, so a restart passes them on.
        self.effort_choice = ""
        self.fast_mode = False
        #: The permission modes Shift+Tab steps through, how the header names
        #: them, and the one the user set ("" for the session's own).
        self.modes: tuple = MODES
        self.mode_labels: dict = MODE_LABELS
        self.mode_choice = ""
        #: The efforts ``/effort`` takes where XeFM sets it itself (Claude
        #: Code's is a command of its own).
        self.efforts: tuple = ()
        #: The agent's own sandbox, as far as XeFM can tell: ``on``, ``off``
        #: or ``not known`` ("" until it is asked).
        self.sandbox = ""

    # --- what the user did -------------------------------------------------------

    def add_user(self, text: str) -> None:
        self.items.append(Item("user", text))
        self.pending_turns += 1
        self.state = WORKING

    def add_notice(self, text: str, *, error: bool = False) -> None:
        self.items.append(Item("error" if error else "notice", text))

    # --- what the agent did ------------------------------------------------------

    def handle(self, msg: dict) -> Permission | str | None:
        """Fold one message in. Returns a :class:`Permission` to ask, the id
        of a question the CLI withdrew (``control_cancel_request``), or None."""
        kind = msg.get("type")
        parent = msg.get("parent_tool_use_id")
        if parent and kind in ("stream_event", "assistant", "user"):
            self._sub(str(parent), msg)
            return None
        if kind == "stream_event":
            self._stream(msg.get("event") or {})
        elif kind == "assistant":
            self._assistant(msg.get("message") or {})
        elif kind == "user":
            self._tool_results(msg)
        elif kind == "system":
            self._system(msg)
        elif kind == "result":
            self._result(msg)
        elif kind == "control_request":
            return self._control(msg)
        elif kind == "control_cancel_request":
            rid = str(msg.get("request_id") or "")
            self.permissions.pop(rid, None)
            self._update_state()
            return rid
        elif kind == "control_response":
            response = (msg.get("response") or {})
            body = response.get("response") or {}
            if isinstance(body.get("commands"), list):
                self.commands = body["commands"]
            if isinstance(body.get("models"), list):
                self.models = [m for m in body["models"]
                               if isinstance(m, dict) and isinstance(m.get("value"), str)]
            if isinstance(body.get("model"), str) and body["model"]:
                self.model = body["model"]  # set_model's answer
            if self.model_request and response.get("request_id") == self.model_request:
                self.model_request = ""
                if response.get("subtype") == "error":
                    self.add_notice(f"Could not switch the model: {response.get('error')}",
                                    error=True)
            mode = body.get("current_permission_mode") or body.get("mode")
            if isinstance(mode, str) and mode:
                self.permission_mode = mode
            if response.get("subtype") == "error":
                logger.warning(f"Agent refused a request: {response.get('error')}")
            elif self.state == STARTING:
                # The answer to initialize: the CLI is ready. Its `system
                # init` comes only with the first turn, so waiting for that
                # would show "starting" until the user sends something.
                self._update_state()
        elif kind == "rate_limit_event":
            info = msg.get("rate_limit_info") or {}
            if info.get("status") not in (None, "allowed", "allowed_warning"):
                self.add_notice(f"Rate limited ({info.get('rateLimitType', 'limit')})")
        return None

    def _stream(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "message_start":
            self._stream_msg = str((event.get("message") or {}).get("id") or "")
            self._stream_index = {}
        elif etype == "content_block_start":
            block = event.get("content_block") or {}
            item = self._new_block(block)
            if item is None:
                return
            item.open = True
            self._stream_index[int(event.get("index", 0))] = item
            self._blocks.setdefault(self._stream_msg, []).append(item)
        elif etype == "content_block_delta":
            item = self._stream_index.get(int(event.get("index", 0)))
            delta = event.get("delta") or {}
            if item is None:
                return
            dtype = delta.get("type")
            if dtype == "text_delta":
                item.text += delta.get("text", "")
            elif dtype == "thinking_delta":
                item.text += delta.get("thinking", "")
            elif dtype == "input_json_delta":
                item.partial += delta.get("partial_json", "")
        elif etype == "content_block_stop":
            item = self._stream_index.get(int(event.get("index", 0)))
            if item is not None and item.kind != "tool":
                item.open = False

    def _new_block(self, block: dict) -> Item | None:
        btype = block.get("type")
        if btype == "text":
            item = Item("text", block.get("text", ""))
        elif btype == "thinking":
            item = Item("thinking", block.get("thinking", ""))
        elif btype in ("tool_use", "server_tool_use"):
            item = Item("tool", name=str(block.get("name", "")),
                        input=dict(block.get("input") or {}),
                        tool_id=str(block.get("id", "")), open=True)
            self._tools[item.tool_id] = item
        else:
            return None
        self.items.append(item)
        return item

    def _assistant(self, message: dict) -> None:
        usage = message.get("usage")
        if isinstance(usage, dict):
            held = sum(int(usage.get(k) or 0) for k in (
                "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            if held:
                self.context_tokens = held
        mid = str(message.get("id") or "")
        streamed = self._blocks.get(mid, [])
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            n = self._consumed.get(mid, 0)
            item = streamed[n] if n < len(streamed) else None
            btype = block.get("type")
            want = {"text": "text", "thinking": "thinking", "tool_use": "tool",
                    "server_tool_use": "tool"}.get(btype)
            if want is None:
                continue
            if item is None or item.kind != want:
                item = self._new_block(block)
                if item is None:
                    continue
                streamed = self._blocks.setdefault(mid, [])
                streamed.append(item)
            self._consumed[mid] = n + 1
            if want == "text":
                item.text = block.get("text", item.text)
                item.open = False
                item.plain = message.get("model") == SYNTHETIC_MODEL
            elif want == "thinking":
                item.text = block.get("thinking", item.text)
                item.open = False
            else:
                item.input = dict(block.get("input") or item.input)
                item.partial = ""
        if message.get("stop_reason") is None and self.state != ASKING:
            self.state = WORKING

    def _tool_results(self, msg: dict) -> None:
        content = (msg.get("message") or {}).get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            item = self._tools.get(str(block.get("tool_use_id", "")))
            if item is None:
                continue
            item.result = _result_text(block.get("content"))
            item.is_error = bool(block.get("is_error"))
            item.open = False

    def _sub(self, parent: str, msg: dict) -> None:
        """A message from inside a subagent: its tool calls and what it says
        nest under the call that started it (``parent``), its tool results
        go to its calls. Its prompt and its streamed deltas are not shown -
        the finished blocks carry the same."""
        kind = msg.get("type")
        owner = self._tools.get(parent)
        if kind == "user":
            self._tool_results(msg)
            return
        if kind != "assistant" or owner is None:
            return
        for block in (msg.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and str(block.get("text") or "").strip():
                owner.children.append(Item("text", str(block["text"])))
            elif btype in ("tool_use", "server_tool_use"):
                tid = str(block.get("id", ""))
                if tid in self._tools:
                    continue
                child = Item("tool", name=str(block.get("name", "")),
                             input=dict(block.get("input") or {}), tool_id=tid, open=True)
                self._tools[tid] = child
                owner.children.append(child)

    def _system(self, msg: dict) -> None:
        sub = msg.get("subtype")
        if sub == "init":
            self.session_id = str(msg.get("session_id") or self.session_id)
            self.model = str(msg.get("model") or self.model)
            self.cwd = str(msg.get("cwd") or self.cwd)
            if isinstance(msg.get("permissionMode"), str):
                self.permission_mode = msg["permissionMode"]
            if msg.get("fast_mode_state") in ("on", "off"):
                self.fast_mode = msg["fast_mode_state"] == "on"
            if self.state == STARTING:
                self.state = WORKING if self.pending_turns else IDLE
        elif sub == "compact_boundary":
            self.add_notice("Earlier conversation compacted")
        elif sub == "status" and isinstance(msg.get("permissionMode"), str):
            self.permission_mode = msg["permissionMode"]
        elif sub == "notification" and str(msg.get("text") or "").strip():
            # What the CLI tells the user beside the conversation ("Fast mode
            # disabled - out of usage credits").
            self.add_notice(str(msg["text"]).strip(), error=msg.get("color") == "error")
            if msg.get("key") == "fast-mode-overage-rejected":
                self.fast_mode = False
        elif sub == "task_progress":
            owner = self._tools.get(str(msg.get("tool_use_id") or ""))
            if owner is not None and isinstance(msg.get("description"), str):
                owner.progress = msg["description"]

    def _result(self, msg: dict) -> None:
        self.session_id = str(msg.get("session_id") or self.session_id)
        self.pending_turns = max(0, self.pending_turns - 1)
        self.close_open_items()
        windows = [u.get("contextWindow") for name, u in (msg.get("modelUsage") or {}).items()
                   if isinstance(u, dict) and isinstance(u.get("contextWindow"), int)
                   and (not self.model or name == self.model)]
        if windows:
            self.context_window = max(windows)
        self._blocks.clear()
        self._consumed.clear()
        if msg.get("is_error") or msg.get("subtype") not in (None, "success"):
            errors = msg.get("errors")
            text = "; ".join(map(str, errors)) if isinstance(errors, list) and errors \
                else str(msg.get("result") or msg.get("subtype") or "error")
            if msg.get("subtype") == "error_during_execution" and not errors:
                text = "Interrupted"
            self.last_error = text
            self.add_notice(text, error=text != "Interrupted")
        self._update_state()

    def _control(self, msg: dict) -> Permission | None:
        req = msg.get("request") or {}
        if req.get("subtype") != "can_use_tool":
            return None
        perm = Permission(
            request_id=str(msg.get("request_id") or ""),
            tool=str(req.get("tool_name") or ""),
            input=dict(req.get("input") or {}),
            description=str(req.get("description") or req.get("title") or ""),
            suggestions=list(req.get("permission_suggestions") or []),
            tool_use_id=str(req.get("tool_use_id") or ""),
            blocked_path=str(req.get("blocked_path") or ""))
        perm.remembers = rules_remembered(perm.suggestions)
        # Claude Code's Bash asks to run with its sandbox off this way.
        perm.leaves_sandbox = perm.input.get("dangerouslyDisableSandbox") is True
        self.permissions[perm.request_id] = perm
        self.state = ASKING
        return perm

    def answered(self, perm: Permission, allowed: bool,
                 updated_input: dict | None = None) -> None:
        """The user answered ``perm`` (with the tool's input as it was let
        through: ``AskUserQuestion``'s carries the answers)."""
        self.permissions.pop(perm.request_id, None)
        item = self._tools.get(perm.tool_use_id)
        if item is not None:
            if not allowed:
                item.denied = True
            elif updated_input is not None and updated_input != perm.input:
                item.input = dict(updated_input)
        self._update_state()

    def exited(self, code: int | None, stderr: str) -> None:
        self.state = EXITED
        self.pending_turns = 0
        self.permissions.clear()
        for item in self._all_items():
            item.open = False
        if code not in (0, None):
            text = f"The agent stopped (exit code {code})"
            if stderr:
                text += ":\n\n" + stderr
            self.add_notice(text, error=True)

    def _update_state(self) -> None:
        if self.state == EXITED:
            return
        if self.permissions:
            self.state = ASKING
        elif self.pending_turns:
            self.state = WORKING
        else:
            self.state = IDLE

    @property
    def busy(self) -> bool:
        return self.state in (WORKING, ASKING)

    def close_open_items(self) -> None:
        """A turn is over: nothing is arriving any more."""
        for item in self._all_items():
            if item.open:
                item.open = False
                if item.kind == "tool" and item.result is None:
                    item.result = ""

    def _all_items(self):
        """Every item, a subagent's steps after the call that holds them."""
        stack = list(reversed(self.items))
        while stack:
            item = stack.pop()
            yield item
            stack.extend(reversed(item.children))

    def todos(self) -> list[dict]:
        """The agent's to-do list as its last ``TodoWrite`` left it
        (``content``, ``activeForm``, ``status``), while anything on it is
        still to do; empty once it is all done or there is none."""
        for item in reversed(self.items):
            if item.kind == "tool" and item.name == "TodoWrite" and not item.denied:
                todos = [t for t in item.input.get("todos") or [] if isinstance(t, dict)]
                if any(t.get("status") != "completed" for t in todos):
                    return todos
                return []
        return []

    def sandbox_label(self) -> str:
        """What the header says of the agent's sandbox."""
        return f"sandbox {self.sandbox}" if self.sandbox else ""

    def context_label(self) -> str:
        """How full the context is - ``"12% context"`` once the window is
        known, ``"37k context"`` before; "" before any call."""
        if not self.context_tokens:
            return ""
        if self.context_window:
            pct = max(1, round(100 * self.context_tokens / self.context_window))
            return f"{pct}% context"
        return f"{max(1, round(self.context_tokens / 1000))}k context"


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                elif part.get("type") == "image":
                    parts.append("[image]")
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return "" if content is None else str(content)


# --- permission answers ----------------------------------------------------------


def rules_remembered(suggestions: list) -> list[str]:
    """What Claude Code's ``permission_suggestions`` would remember, a line
    each: ``Bash(ssh:*)``, a folder, a mode. A command's own line does not
    say how far a rule reaches (``ssh *`` for one ``ssh`` to one host), so
    the question shows the rule. A suggestion of a kind not known here gives
    nothing, and the question then says it was not said."""
    out: list[str] = []
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        kind = s.get("type")
        if kind in ("addRules", "replaceRules"):
            behavior = s.get("behavior", "allow")
            for rule in s.get("rules") or []:
                if not isinstance(rule, dict) or not rule.get("toolName"):
                    continue
                name = str(rule["toolName"])
                content = rule.get("ruleContent")
                text = f"`{name}({content})`" if content else f"`{name}`, any use"
                out.append(text if behavior == "allow" else f"{behavior}: {text}")
        elif kind == "addDirectories":
            out.extend(f"files in `{d}`" for d in s.get("directories") or [])
        elif kind == "setMode" and s.get("mode"):
            out.append(f"the mode `{s['mode']}`")
    return out


def always_allow_line(agent: str, perm: Permission) -> str:
    """The line of the question that says what **Always Allow** would let
    through for the rest of the session, or that the agent did not say."""
    if not perm.remembers:
        return (f"**Always Allow**: {agent or 'the agent'} did not say what it would "
                "remember for the rest of this session.")
    return ("**Always Allow** lets through, for the rest of this session: "
            + "; ".join(perm.remembers) + ".")


def allow(perm: Permission, *, always: bool = False, updated_input: dict | None = None) -> dict:
    """The answer that lets ``perm``'s tool run; ``always`` adds the CLI's
    own suggested rules for the rest of this session (never to a settings
    file: XeFM does not change the user's settings)."""
    out: dict[str, Any] = {"behavior": "allow",
                           "updatedInput": updated_input if updated_input is not None
                           else perm.input}
    if always and perm.suggestions:
        out["updatedPermissions"] = [dict(s, destination="session")
                                     for s in perm.suggestions if isinstance(s, dict)]
    return out


def deny(message: str = "The user declined this in XeFM.", *, interrupt: bool = False) -> dict:
    out: dict[str, Any] = {"behavior": "deny", "message": message}
    if interrupt:
        out["interrupt"] = True
    return out


#: The ``model`` of an ``assistant`` message the CLI wrote itself - a
#: command's reply (``/usage``, ``/effort``) - rather than the model.
SYNTHETIC_MODEL = "<synthetic>"
#: ``/effort``'s levels when the CLI's command list does not say.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max", "auto")

#: The tool Claude Code asks the user multiple-choice questions with: answered
#: by filling ``answers`` into its input rather than with a yes or no.
ASK_USER_TOOL = "AskUserQuestion"
#: The tool that ends plan mode by showing the plan for approval.
PLAN_TOOL = "ExitPlanMode"

#: The permission modes Shift+Tab steps through, as the CLI does: ask before
#: each tool, accept file edits without asking, plan without changing
#: anything. ``bypassPermissions`` is only ever what the session started in.
MODES = ("default", "acceptEdits", "plan")
MODE_LABELS = {"default": "", "acceptEdits": "accept edits", "plan": "plan mode",
               "bypassPermissions": "bypass permissions"}

#: Lines of a change shown when asking whether it may be made.
PERMISSION_LINES = 24
#: How many lines of a tool's output "show all" shows at most.
EXPANDED_LINES = 2000
#: A subagent's latest steps shown under its call; the earlier are counted.
SUBAGENT_STEPS = 5
#: The tools that run a shell command: Claude Code's, and the other agents'.
SHELL_TOOLS = ("Bash", "Shell")
#: The tools that run a subagent.
SUBAGENT_TOOLS = ("Agent", "Task")
#: The scheme of the transcript's own links (expand an output, open a diff).
LINK_SCHEME = "xefm-agent:"


def questions(perm: Permission) -> list[dict]:
    """``AskUserQuestion``'s questions: ``{'question', 'header', 'options':
    [{'label', 'description'}], 'multiSelect'}``, the malformed ones left out."""
    out = []
    for q in perm.input.get("questions") or []:
        if isinstance(q, dict) and isinstance(q.get("question"), str):
            opts = [o for o in q.get("options") or []
                    if isinstance(o, dict) and isinstance(o.get("label"), str)]
            out.append(dict(q, options=opts))
    return out


# --- the transcript --------------------------------------------------------------


def summary(name: str, data: dict) -> str:
    """One line saying what a tool call does: the command, the file, the
    pattern."""
    def first(*keys):
        for k in keys:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    text = {
        "Bash": lambda: first("command"),
        "Shell": lambda: first("command"),
        "Read": lambda: first("file_path", "path"),
        "Write": lambda: first("file_path"),
        "Edit": lambda: first("file_path"),
        "MultiEdit": lambda: first("file_path"),
        "NotebookEdit": lambda: first("notebook_path"),
        "Glob": lambda: first("pattern"),
        "Grep": lambda: " in ".join(p for p in (first("pattern"), first("path")) if p),
        "WebFetch": lambda: first("url"),
        "WebSearch": lambda: first("query"),
        "Task": lambda: first("description", "prompt"),
        "Agent": lambda: first("description", "prompt"),
        "Skill": lambda: first("skill", "command"),
    }.get(name, lambda: first("description", "command", "file_path", "path",
                              "pattern", "url", "query"))()
    if not text and data:
        text = json.dumps(data, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= 200 else text[:199] + "…"


def _fence(text: str) -> tuple[str, str]:
    """A code fence that ``text`` cannot close early."""
    return ("~~~", "~~~") if "```" in text else ("```", "```")


def _code(text: str, lang: str = "") -> str:
    open_, close = _fence(text)
    return f"{open_}{lang}\n{text}\n{close}"


def _clip(text: str, lines: int) -> tuple[str, int]:
    rows = text.rstrip("\n").split("\n")
    if len(rows) <= lines:
        return "\n".join(rows), 0
    return "\n".join(rows[:lines]), len(rows) - lines


def _inline(text: str) -> str:
    """``text`` as an inline code span."""
    ticks = "``" if "`" in text else "`"
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{pad}{text}{pad}{ticks}"


def _role(item: Item) -> str:
    """The color of an item's dot in the transcript: a tool that worked is
    green, one that failed or was declined red, one still running the
    accent; text and notices muted."""
    if item.kind == "error":
        return "error"
    if item.kind != "tool":
        return "muted"
    if item.denied or item.is_error:
        return "error"
    if item.open:
        return "accent"
    return "success"


def _fenced(name: str, text: str) -> str:
    """``text`` in a MarkdownView fenced container (``::: box`` ...; ``name``
    may carry an argument, ``bullet success``): its
    fence longer than any run of colons the text holds, so none closes it."""
    runs = [len(m.group(0)) for m in re.finditer(r":{3,}", text)]
    fence = ":" * max([3] + [n + 1 for n in runs])
    return f"{fence} {name}\n{text}\n{fence}"


def _questions_markdown(item: Item) -> str:
    """``AskUserQuestion`` as the questions asked and the answers given."""
    answers = item.input.get("answers") if isinstance(item.input.get("answers"), dict) else {}
    parts = []
    for q in item.input.get("questions") or []:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str):
            continue
        text = q["question"]
        given = answers.get(text)
        if given is not None:
            parts.append(f"{text}  \n→ **{given}**")
        else:
            opts = ", ".join(str(o.get("label")) for o in q.get("options") or []
                             if isinstance(o, dict))
            parts.append(f"{text}  \n_{opts}_" if opts else text)
    if item.denied:
        mark = " ✗ not answered"
    elif item.open and item.result is None and not answers:
        mark = " …"
    else:
        mark = ""
    return f"**Question**{mark}\n\n" + "\n\n".join(parts)


def _clipped(item: Item, text: str, lines: int, index: int) -> tuple[str, str]:
    """``text`` cut to ``lines`` (all of it, up to EXPANDED_LINES, once the
    user expanded it) and the note under it: a link that shows the rest or
    folds it again when the item has an ``index`` in the transcript."""
    if item.expanded:
        shown, more = _clip(text, EXPANDED_LINES)
        if index < 0:
            return shown, ""
        note = f"_… {more} more lines not shown_ · " if more else ""
        return shown, f"\n\n{note}[show less]({LINK_SCHEME}collapse/{index})"
    shown, more = _clip(text, lines)
    if not more:
        return shown, ""
    if index < 0:
        return shown, f"\n\n_… {more} more lines_"
    return shown, f"\n\n[… {more} more lines]({LINK_SCHEME}expand/{index})"


def _bash_markdown(item: Item, mark: str, index: int = -1) -> str:
    """A shell command and what it printed as one block, the way a terminal
    shows them: the command after a ``$`` prompt, its output under it. The
    head says what the command is for when the agent said so."""
    desc = item.input.get("description")
    head = f"**{item.name}**" + (f" {desc.strip()}" if isinstance(desc, str) and desc.strip() else "")
    lines = item.input["command"].rstrip("\n").split("\n")
    body = "\n".join(["$ " + lines[0]] + ["> " + l for l in lines[1:]])
    note = ""
    if item.result and not item.denied:
        shown, note = _clipped(item, item.result, RESULT_LINES, index)
        if shown.strip():
            body += "\n" + shown
    return f"{head} {mark}\n\n{_code(body, 'console')}{note}"


def _mark(item: Item) -> str:
    """How a tool call went, after its name: running, declined, failed, done."""
    if item.open:
        return "…"
    if item.denied:
        return "✗ declined"
    return "✗" if item.is_error else "✓"


def _steps_markdown(item: Item, index: int) -> str:
    """A subagent's steps, one line each - the latest SUBAGENT_STEPS, the
    rest behind a link when the item has an ``index`` - with what it says it
    is doing under them while it runs."""
    rows = []
    for child in item.children:
        if child.kind == "tool":
            what = summary(child.name, child.input) if child.input else ""
            rows.append(f"- **{child.name or 'tool'}**" + (f" {_inline(what)}" if what else "")
                        + f" {_mark(child)}")
        elif child.kind == "text":
            line = " ".join(child.text.split())
            if line:
                rows.append(f"- _{line if len(line) <= 160 else line[:159] + '…'}_")
    out = "\n".join(rows)
    hidden = len(rows) - SUBAGENT_STEPS
    if hidden > 0 and not item.expanded:
        note = (f"[… {hidden} earlier steps]({LINK_SCHEME}expand/{index})" if index >= 0
                else f"_… {hidden} earlier steps_")
        out = note + "\n\n" + "\n".join(rows[hidden:])
    elif hidden > 0 and index >= 0:
        out = f"[show fewer steps]({LINK_SCHEME}collapse/{index})\n\n" + out
    if item.open and item.result is None and item.progress:
        out += ("\n\n" if out else "") + f"_{item.progress}_"
    return out


def tool_markdown(item: Item, index: int = -1) -> str:
    """One tool call as Markdown. With its ``index`` in the transcript, a
    clipped output gets a link that shows all of it and an edit one that
    opens it in the diff viewer (LINK_SCHEME links the view handles)."""
    name = item.name or "tool"
    if name == ASK_USER_TOOL and isinstance(item.input.get("questions"), list):
        return _questions_markdown(item)
    if name == PLAN_TOOL and isinstance(item.input.get("plan"), str):
        verdict = " ✗ kept planning" if item.denied else \
            (" ✓ approved" if item.result is not None and not item.is_error else "")
        return f"**Plan**{verdict}\n\n{item.input['plan'].strip()}"
    todos = name == "TodoWrite" and isinstance(item.input.get("todos"), list)
    what = summary(name, item.input) if item.input and not todos else ""
    mark = _mark(item)
    if name in SHELL_TOOLS and isinstance(item.input.get("command"), str):
        return _bash_markdown(item, mark, index)
    head = "**Todos**" if todos else f"**{name}**"
    if what:
        head += " " + _inline(what)
    head += f" {mark}"
    parts = [head]
    if item.patch:
        shown, note = _clipped(item, item.patch, DIFF_LINES, index)
        if index >= 0 and not item.denied and not item.is_error:
            link = f"[open diff]({LINK_SCHEME}diff/{index})"
            note = f"{note} · {link}" if note else f"\n\n{link}"
        parts.append(_code(shown, "diff") + note)
        if item.is_error and item.result:
            parts.append(_code(_clip(item.result, RESULT_LINES)[0]))
        return "\n\n".join(parts)
    if name == "Edit" and isinstance(item.input.get("old_string"), str):
        diff = ["- " + l for l in item.input["old_string"].split("\n")] + \
               ["+ " + l for l in str(item.input.get("new_string", "")).split("\n")]
        shown, note = _clipped(item, "\n".join(diff), DIFF_LINES, index)
        if index >= 0 and not item.denied and not item.is_error:
            link = f"[open diff]({LINK_SCHEME}diff/{index})"
            note = f"{note} · {link}" if note else f"\n\n{link}"
        parts.append(_code(shown, "diff") + note)
    elif name in SUBAGENT_TOOLS and (item.children or item.progress):
        steps = _steps_markdown(item, index)
        if steps:
            parts.append(steps)
    elif todos:
        rows = []
        for todo in item.input["todos"]:
            if isinstance(todo, dict):
                done = todo.get("status") == "completed"
                label = str(todo.get("content") or todo.get("activeForm") or "")
                rows.append(f"- [{'x' if done else ' '}] {label}")
        if rows:
            parts.append("\n".join(rows))
        return "\n\n".join(parts)
    if item.result and not item.denied and name not in ("TodoWrite",):
        shown, note = _clipped(item, item.result, RESULT_LINES, index)
        if shown.strip():
            parts.append(_code(shown) + note)
    return "\n\n".join(parts)


_MD_PUNCT = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~])")


def _plain_markdown(text: str) -> str:
    """Plain text as Markdown that shows it as written: punctuation escaped,
    each line its own row (a hard break), runs of spaces inside a line kept
    (no-break spaces; a line's indent is not - a paragraph's rows start at
    its edge). Blank lines stay paragraph breaks."""
    out = []
    for line in text.rstrip().split("\n"):
        line = _MD_PUNCT.sub(r"\\\1", line.strip())
        out.append(re.sub(r"  +", lambda m: "\u00a0" * len(m.group(0)), line))
    rows = []
    for i, line in enumerate(out):
        nxt = out[i + 1] if i + 1 < len(out) else ""
        rows.append(line + ("  " if line and nxt else ""))
    return "\n".join(rows)


def _thought_markdown(item: Item, index: int) -> str:
    """Finished thinking: folded to a line that opens it, or shown (as a
    quote) with a link that folds it again. The CLI often sends thinking
    without its text; that leaves nothing to show."""
    if not item.expanded:
        return f"[_Thought_ ›]({LINK_SCHEME}expand/{index})"
    quoted = "\n".join("> " + line for line in item.text.strip().split("\n"))
    return f"[_Thought_ ‹]({LINK_SCHEME}collapse/{index})\n\n{quoted}"


def to_markdown(items: list[Item]) -> str:
    """The transcript's Markdown source: what the user wrote on a panel
    (``::: box``), each thing the agent did under it with a dot colored by
    how it went (``::: bullet <role>``)."""
    out: list[str] = []
    for index, item in enumerate(items):
        n = len(out)
        if item.kind == "user":
            out.append(_fenced("box", item.text.rstrip() or " "))
            continue
        elif item.kind == "text":
            if item.text.strip():
                out.append(_plain_markdown(item.text) if item.plain else item.text.rstrip())
        elif item.kind == "thinking":
            if item.open:
                out.append("_Thinking…_")
            elif item.text.strip():
                out.append(_thought_markdown(item, index))
        elif item.kind == "tool":
            out.append(tool_markdown(item, index))
        elif item.kind in ("notice", "error"):
            first, _, rest = item.text.strip().partition("\n")
            head = f"**Error:** {first}" if item.kind == "error" else f"_{first}_"
            out.append(head + ("\n\n" + _code(rest.strip()) if rest.strip() else ""))
        if len(out) > n:
            out[-1] = _fenced(f"bullet {_role(item)}", out[-1])
    return "\n\n".join(out) + "\n"


def edit_before(item: Item, current: str) -> str | None:
    """The file an ``Edit`` / ``MultiEdit`` changed as it was before, from
    ``current`` (the file as it is now) with the edits undone - last first,
    each the way it was made (every occurrence with ``replace_all``, else the
    first). None when an edit's new text is not in the file any more (it was
    changed again since), so the whole-file comparison would lie."""
    if item.name == "Edit" and "edits" not in item.input:
        edits = [item.input]
    elif item.name == "Write" and item.input.get("old_string") == "":
        edits = [item.input]  # a new file: it was empty before
    elif item.name in ("Edit", "MultiEdit") and isinstance(item.input.get("edits"), list):
        edits = [e for e in item.input["edits"] if isinstance(e, dict)]
    else:
        return None
    text = current
    for edit in reversed(edits):
        old, new = edit.get("old_string"), edit.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        if new == "":
            return None  # a deletion leaves no mark to find it by
        if new not in text:
            return None
        text = text.replace(new, old) if edit.get("replace_all") else text.replace(new, old, 1)
    return text


# --- how the screen drives an agent --------------------------------------------------


class Protocol:
    """What differs between the agents, as the screen
    (:class:`xefm.agent_chat_view.ChatView`, ``view`` below) drives them:
    starting and starting again, and what the user sets."""

    def conversation(self) -> Conversation:
        """An empty conversation."""
        return Conversation()

    def client(self, argv: list[str], conv: Conversation, **kwargs: Any) -> ChatClient:
        """The agent's process, not yet started, over ``conv``."""
        raise NotImplementedError

    def handle(self, view, msg: dict) -> Permission | str | None:
        """Fold one message in (see :meth:`Conversation.handle`)."""
        raise NotImplementedError

    def set_mode(self, view, mode: str) -> None:
        raise NotImplementedError

    def set_model(self, view, model: str) -> None:
        raise NotImplementedError

    def approve_plan(self, view, perm: Permission, mode: str) -> None:
        """The user approved the plan ``perm`` showed: go on in ``mode``."""
        raise NotImplementedError

    def can_set_model(self, conv: Conversation) -> bool:
        """Whether ``/model`` is XeFM's to run (else it goes to the agent)."""
        return True

    def local_commands(self, conv: Conversation) -> list[dict]:
        """``/`` commands XeFM runs for this agent, beside its own."""
        return []

    def command(self, view, text: str) -> bool:
        """Run one; whether ``text`` was one."""
        return False

    def restart(self, view, *, resume: bool) -> bool:
        """A new process: the same conversation, or a new one."""
        raise NotImplementedError


class ClaudeProtocol(Protocol):
    """Claude Code's stream-json mode. ``channel`` is the session's way to
    XeFM (:class:`xefm.mcp_server.Channel`)."""

    def __init__(self, channel: Any = None, sandbox: str = "not known") -> None:
        self.channel = channel
        self.sandbox = sandbox

    def conversation(self) -> Conversation:
        conv = Conversation()
        conv.sandbox = self.sandbox
        return conv

    def client(self, argv: list[str], conv: Conversation, **kwargs: Any) -> ChatClient:
        return ChatClient(argv, **kwargs)

    def handle(self, view, msg: dict) -> Permission | str | None:
        result = view.conversation.handle(msg)
        if isinstance(result, Permission) and self.channel is not None \
                and result.tool.startswith(f"mcp__{self.channel.name}__"):
            # XeFM's own tool: what it does is asked by XeFM, once.
            view.answer(result, allow(result))
            return None
        return result

    def set_mode(self, view, mode: str) -> None:
        if view.client.request({"subtype": "set_permission_mode", "mode": mode}) is not None:
            view.conversation.permission_mode = mode  # the CLI confirms with a status

    def set_model(self, view, model: str) -> None:
        conv = view.conversation
        rid = view.client.request({"subtype": "set_model", "model": model})
        if rid is not None:
            conv.model_request = rid
            conv.model_choice = "" if model == "default" else model

    def approve_plan(self, view, perm: Permission, mode: str) -> None:
        view.answer(perm, allow(perm))
        view.set_mode(mode)

    def command(self, view, text: str) -> bool:
        """``/effort <level>`` goes to the CLI, but is kept, so a restarted
        agent gets it with ``--effort`` (the CLI keeps it for its process
        only)."""
        conv = view.conversation
        m = re.fullmatch(r"/effort\s+(\S+)", text)
        if m:
            level = m.group(1).lower()
            levels: tuple = EFFORT_LEVELS
            for cmd in conv.commands:
                if cmd.get("name") == "effort":
                    hint = re.findall(r"[\w-]+", str(cmd.get("argumentHint") or ""))
                    levels = tuple(hint) or levels
            if level in levels:
                conv.effort_choice = "" if level == "auto" else level
        return False

    def restart(self, view, *, resume: bool) -> bool:
        conv = view.conversation
        sid, mode = conv.session_id, conv.permission_mode
        argv = view.argv
        if resume and sid and view._restart_argv is not None:
            argv = view._restart_argv(sid)
        if mode in MODES and mode != "default":
            argv = list(argv) + ["--permission-mode", mode]
        model = conv.model_choice
        if model:
            argv = list(argv) + ["--model", model]
        # What the CLI keeps for its process only, set again in the new one.
        effort, fast = conv.effort_choice, conv.fast_mode
        if effort:
            argv = list(argv) + ["--effort", effort]
        if not resume:
            view.new_conversation()
        ok = view.start(argv=argv)
        conv = view.conversation
        if mode in MODES:
            conv.permission_mode = mode
        conv.model_choice, conv.effort_choice = model, effort
        if ok and fast and view.client is not None:
            # No flag turns fast mode on: its own command does, as a turn of
            # its own (its reply shows it is on again).
            if view.client.send("/fast on"):
                conv.pending_turns += 1
                conv.state = WORKING
        return ok
