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


@dataclass
class Permission:
    """A question the CLI asks: may this tool run?"""

    request_id: str
    tool: str
    input: dict
    description: str = ""
    suggestions: list = field(default_factory=list)
    tool_use_id: str = ""
    blocked_path: str = ""


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

    def _system(self, msg: dict) -> None:
        sub = msg.get("subtype")
        if sub == "init":
            self.session_id = str(msg.get("session_id") or self.session_id)
            self.model = str(msg.get("model") or self.model)
            self.cwd = str(msg.get("cwd") or self.cwd)
            if isinstance(msg.get("permissionMode"), str):
                self.permission_mode = msg["permissionMode"]
            if self.state == STARTING:
                self.state = WORKING if self.pending_turns else IDLE
        elif sub == "compact_boundary":
            self.add_notice("Earlier conversation compacted")
        elif sub == "status" and isinstance(msg.get("permissionMode"), str):
            self.permission_mode = msg["permissionMode"]

    def _result(self, msg: dict) -> None:
        self.session_id = str(msg.get("session_id") or self.session_id)
        self.pending_turns = max(0, self.pending_turns - 1)
        for item in self.items:
            if item.open:
                item.open = False
                if item.kind == "tool" and item.result is None:
                    item.result = ""
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
            elif updated_input is not None:
                item.input = dict(updated_input)
        self._update_state()

    def exited(self, code: int | None, stderr: str) -> None:
        self.state = EXITED
        self.pending_turns = 0
        self.permissions.clear()
        for item in self.items:
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

#: How many lines of a tool's output "show all" shows at most.
EXPANDED_LINES = 2000
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
    if item.open and item.result is None:
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
    head = "**Bash**" + (f" {desc.strip()}" if isinstance(desc, str) and desc.strip() else "")
    lines = item.input["command"].rstrip("\n").split("\n")
    body = "\n".join(["$ " + lines[0]] + ["> " + l for l in lines[1:]])
    note = ""
    if item.result and not item.denied:
        shown, note = _clipped(item, item.result, RESULT_LINES, index)
        if shown.strip():
            body += "\n" + shown
    return f"{head} {mark}\n\n{_code(body, 'console')}{note}"


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
    what = summary(name, item.input) if item.input else ""
    if item.open and item.result is None:
        mark = "…"
    elif item.denied:
        mark = "✗ declined"
    elif item.is_error:
        mark = "✗"
    else:
        mark = "✓"
    if name == "Bash" and isinstance(item.input.get("command"), str):
        return _bash_markdown(item, mark, index)
    head = f"**{name}**"
    if what:
        head += " " + _inline(what)
    head += f" {mark}"
    parts = [head]
    if name == "Edit" and isinstance(item.input.get("old_string"), str):
        diff = ["- " + l for l in item.input["old_string"].split("\n")] + \
               ["+ " + l for l in str(item.input.get("new_string", "")).split("\n")]
        shown, note = _clipped(item, "\n".join(diff), DIFF_LINES, index)
        if index >= 0 and not item.denied and not item.is_error:
            link = f"[open diff]({LINK_SCHEME}diff/{index})"
            note = f"{note} · {link}" if note else f"\n\n{link}"
        parts.append(_code(shown, "diff") + note)
    elif name == "TodoWrite" and isinstance(item.input.get("todos"), list):
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
                out.append(item.text.rstrip())
        elif item.kind == "thinking":
            if item.open:
                out.append("_Thinking…_")
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
    if item.name == "Edit":
        edits = [item.input]
    elif item.name == "MultiEdit" and isinstance(item.input.get("edits"), list):
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
