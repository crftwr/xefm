"""``xefmctl`` as tools of an MCP server in XeFM, for an AI agent whose sandbox
keeps its shell from the socket (#995).

The agent's own process, outside its sandbox, calls the tools; XeFM answers
in its own. Over HTTP on loopback, because that is what every agent reaches
from outside its sandbox: a stdio server is started inside Copilot's.

**What guards the port.** The pipe and the Unix socket ``xefmctl`` uses are
closed to other users by the OS; a port is not, so the token is all there is:

- it listens on ``127.0.0.1`` only, on a port the system picks, and is closed
  with XeFM;
- nothing is answered without a session's token (:class:`Channel`), made for
  that session, never in the environment of what the agent runs, and dead once
  the session ends;
- a request whose ``Host`` is not this server's, or that carries an
  ``Origin``, is refused: no web page talks to it.

**What it gives.** Exactly what ``xefmctl`` gives the session: the same
commands through :mod:`xefm.remote_dispatch`, with the session's policy. Two
tools: :data:`READ_TOOL`, which changes nothing and says so
(``readOnlyHint``), and :data:`TOOL`, which takes every command.

The protocol is MCP's Streamable HTTP, kept to what a server with two tools
needs: a POST for each message, answered with JSON, or, for an answer that
takes a while (the user is being asked), with an event stream that stays open
with a comment now and then.
"""

from __future__ import annotations

import hmac
import http.server
import io
import json
import secrets
import socket
import socketserver
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from xefm import remote_cli
from xefm import remote_commands as T
from xefm.log_manager import getLogger

logger = getLogger("McpServer")

READ_TOOL = "xefmctl_read"
TOOL = "xefmctl"

#: The protocol versions answered in their own name; the first one otherwise.
VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

#: Seconds before a slow answer becomes an event stream, and between the
#: comments that keep that stream open (a client gives up on a silent one).
STREAM_AFTER = 1.0
KEEP_ALIVE = 15.0

#: Seconds a connection may sit idle, or take over sending a request.
IDLE = 60.0

#: The most connections served at once; another is closed unanswered.
CONNECTIONS = 64

#: The most characters one call's answer holds.
OUTPUT_LIMIT = 1_000_000

METHOD_NOT_FOUND, INVALID_REQUEST, INVALID_PARAMS = -32601, -32600, -32602


@dataclass
class Channel:
    """One session's way in: the server's name in the agent's configuration,
    its address and the session's token."""

    #: Not to be guessed: XeFM answers the agent's question about this
    #: server's tools itself, and another server must not pass for it.
    name: str
    url: str
    token: str
    policy: str
    #: The session's folder: a relative path in a command is taken from it.
    cwd: str
    #: The session's id, once it has one.
    session: str = ""
    _listed: threading.Event = field(default_factory=threading.Event)
    _waiting: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def expect(self) -> None:
        """A process of the agent's is about to start: its tools are not there
        yet."""
        with self._lock:
            self._listed.clear()
            self._waiting.clear()

    def when_listed(self, then: Callable[[], Any]) -> None:
        """Run ``then()`` once the agent has asked what the tools are (on the
        server's thread), at once when it has."""
        with self._lock:
            if not self._listed.is_set():
                self._waiting.append(then)
                return
        then()

    def listed(self) -> None:
        with self._lock:
            self._listed.set()
            waiting, self._waiting[:] = list(self._waiting), []
        for then in waiting:
            then()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    block_on_close = False
    #: On Windows reusing an address would let another process share the port.
    allow_reuse_address = False

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, owner: McpServer) -> None:
        self.owner = owner
        self._free = threading.BoundedSemaphore(CONNECTIONS)
        super().__init__(("127.0.0.1", 0), _Handler)

    def process_request(self, request, client_address) -> None:
        if not self._free.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._free.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._free.release()

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]  # the agent went away with its connection open
        if not isinstance(exc, OSError):
            logger.error(f"A request to the MCP server failed: {exc}")


class McpServer:
    """Answer the agents' tool calls until :meth:`close`. ``handle(req)`` is
    :func:`xefm.remote_dispatch.handle` for this XeFM."""

    def __init__(self, handle: Callable[[dict], Any], *, version: str = "") -> None:
        self._handle = handle
        self.version = version
        self._channels: list[Channel] = []
        self._lock = threading.Lock()
        self._server = _Server(self)
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="xefm-mcp", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        # Not serve_forever, which wakes twice a second to see if it is over.
        server = self._server
        while True:
            try:
                request, address = server.get_request()
            except OSError as exc:
                if self._stop.is_set() or server.socket.fileno() < 0:
                    return
                logger.warning(f"The MCP server could not accept a connection: {exc}")
                self._stop.wait(0.5)  # too many open files, say: not for ever
                continue
            if self._stop.is_set():
                server.shutdown_request(request)
                server.server_close()
                return
            try:
                server.process_request(request, address)
            except Exception as exc:
                logger.error(f"Could not serve a connection: {exc}")
                server.shutdown_request(request)

    def open(self, policy: str, cwd: str) -> Channel:
        """A channel for a session about to start."""
        channel = Channel(name=f"xefm_{secrets.token_hex(4)}", url=self.url,
                          token=secrets.token_urlsafe(32), policy=policy, cwd=cwd)
        with self._lock:
            self._channels.append(channel)
        return channel

    def forget(self, channel: Channel) -> None:
        """The session ended: its token is dead."""
        with self._lock:
            if channel in self._channels:
                self._channels.remove(channel)

    def lookup(self, token: str) -> Channel | None:
        given = token.encode("utf-8", "replace")
        with self._lock:
            channels = list(self._channels)
        found = None
        for channel in channels:
            if hmac.compare_digest(channel.token.encode(), given):
                found = channel
        return found

    def close(self) -> None:
        with self._lock:
            self._channels.clear()
        if self._stop.is_set():
            return
        self._stop.set()
        try:  # wake the accept; the thread then closes the port
            socket.create_connection(("127.0.0.1", self.port), 1).close()
        except OSError:
            pass
        self._thread.join(1)

    # --- what a message asks for ----------------------------------------------------

    def answer(self, channel: Channel, msg: dict, gone: threading.Event) -> dict | None:
        """The answer to one message, or None to one that takes none."""
        method, rid = msg.get("method"), msg.get("id")
        if rid is None or not isinstance(method, str):
            return None  # a notification, or an answer to a question never asked
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        try:
            result = self._result(channel, method, params, gone)
        except _Bad as exc:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": exc.code, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _result(self, channel: Channel, method: str, params: dict,
                gone: threading.Event) -> dict:
        if method == "initialize":
            wanted = params.get("protocolVersion")
            return {"protocolVersion": wanted if wanted in VERSIONS else VERSIONS[0],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "xefm", "title": "XeFM",
                                   "version": self.version or "0"},
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            channel.listed()
            return {"tools": tools()}
        if method == "tools/call":
            return self._call(channel, params, gone)
        raise _Bad(f"{method} is not supported", METHOD_NOT_FOUND)

    def _call(self, channel: Channel, params: dict, gone: threading.Event) -> dict:
        name = params.get("name")
        if name not in (TOOL, READ_TOOL):
            raise _Bad(f"no tool {name!r}", INVALID_PARAMS)
        given = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        argv, stdin = given.get("command"), given.get("stdin")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise _Bad('"command" is a list of words: ["pane", "selected"]', INVALID_PARAMS)
        if stdin is not None and not isinstance(stdin, str):
            raise _Bad('"stdin" is a string', INVALID_PARAMS)
        text, bad = self.run(channel, argv, stdin or "", read_only=name == READ_TOOL, gone=gone)
        return {"content": [{"type": "text", "text": text}], "isError": bad}

    def run(self, channel: Channel, argv: list[str], stdin: str = "", *,
            read_only: bool = False, gone: threading.Event | None = None) -> tuple[str, bool]:
        """Run ``xefmctl <argv>`` for the channel's session: what it printed
        and whether it failed. Stops when the caller is ``gone``."""
        if argv and argv[0] == "xefmctl":
            argv = argv[1:]  # the model's habit
        try:
            req = remote_cli.parse(argv, io.StringIO(stdin), cwd=channel.cwd)
        except remote_cli.RemoteError as exc:
            return str(exc), exc.code != 0
        cmd = T.find(req["cmd"].split())[0]
        if cmd.local:
            out = io.StringIO()
            bad = remote_cli._help(req, out)
            return out.getvalue() or f"no command {' '.join(argv[1:])!r}", bool(bad)
        if read_only and not reads_only(cmd, req["opts"]):
            return (f"xefmctl {cmd.name}{' --show' if req['opts'].get('show') else ''} changes "
                    f"something, or asks the user: call the tool {TOOL} for it", True)
        req.update(session=channel.session, policy=channel.policy)
        out: list[str] = []
        size, status, note, cut = 0, 0, "", False
        end = "\0" if req["opts"].get("0") else "\n"
        answers = self._handle(req)
        if isinstance(answers, dict):
            answers = iter([answers])
        try:
            for answer in answers:
                if not answer.get("ok"):
                    return ("".join(out) + f"xefmctl {cmd.name}: {answer.get('error', 'failed')}"
                            f"\n(exit status {answer.get('code', 1)})", True)
                for item in answer.get("items") or []:
                    line = remote_cli.format_item(cmd, item, req["json"])
                    if line is None:
                        continue
                    if size + len(line) > OUTPUT_LIMIT:
                        line, cut = line[:OUTPUT_LIMIT - size], True
                    out.append(line + end)
                    size += len(line) + 1
                    if cut:
                        break
                status = answer.get("status", status)
                note = answer.get("note") or note
                if cut or (gone is not None and gone.is_set()):
                    break
        finally:
            close = getattr(answers, "close", None)
            if close is not None:
                close()
        if cut:
            note = f"(cut after {OUTPUT_LIMIT} characters: ask for less, with --limit)"
        if note:
            out.append(note + "\n")
        if status:
            out.append(f"(exit status {status})\n")
        return "".join(out).rstrip("\n") or "done", False


class _Bad(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def reads_only(cmd: T.Command, opts: dict) -> bool:
    """Whether a command only answers: :data:`READ_TOOL` takes those alone.
    ``fetch`` writes a file, and ``--show`` changes a pane."""
    return cmd.effect == T.READ and cmd.name != "fetch" and not opts.get("show")


INSTRUCTIONS = (
    "XeFM is the file manager this session runs in. These tools run its xefmctl commands "
    f"outside any sandbox of yours: {READ_TOOL} for what only reads, {TOOL} for the rest, "
    "which the user confirms in XeFM where it changes files. Start with "
    f'{READ_TOOL} ["state"]; ["help"] lists the commands.')


def tools() -> list[dict]:
    """The two tools, as ``tools/list`` gives them."""
    schema = {
        "type": "object",
        "properties": {
            "command": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                        "description": "The words after xefmctl, one to an item, as they are "
                                       "(no shell quoting): [\"pane\", \"selected\"], "
                                       "[\"copy\", \"a b.txt\", \"--to\", \"/dir\", \"--wait\"]. "
                                       "A relative path is taken from the session's folder."},
            "stdin": {"type": "string",
                      "description": "Standard input, for a command given - "
                                     "(one item a line, a document, a plan)."},
        },
        "required": ["command"],
    }
    lists: dict[bool, list[str]] = {True: [], False: []}
    for cmd in T.COMMANDS:
        lists[cmd.local or reads_only(cmd, {})].append(f"{cmd.name} - {cmd.summary}")
    return [
        {"name": READ_TOOL, "title": "Read XeFM's state and files",
         "description": "Run an xefmctl command that only reads, in XeFM itself. Use it "
                        "instead of xefmctl in a shell. [\"help\", COMMAND...] tells one in "
                        "full.\n\n" + "\n".join(lists[True]),
         "inputSchema": schema,
         "annotations": {"readOnlyHint": True, "openWorldHint": False}},
        {"name": TOOL, "title": "Run an xefmctl command in XeFM",
         "description": "Run any xefmctl command, in XeFM itself. Use it instead of xefmctl "
                        "in a shell. XeFM asks the user about what changes files or runs "
                        f"programs. Beside those of {READ_TOOL} (with --show to show what "
                        "they find):\n\n" + "\n".join(lists[False]),
         "inputSchema": schema,
         "annotations": {"readOnlyHint": False, "destructiveHint": True,
                         "openWorldHint": False}},
    ]


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version, sys_version = "XeFM", ""
    timeout = IDLE

    def log_message(self, *args) -> None:
        pass  # a request line holds nothing worth a log

    def _reply(self, code: int, body: bytes = b"", *, close: bool = False) -> None:
        self.send_response(code)
        if body:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if code == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _channel(self) -> Channel | None:
        """The session the request is from; answered with a refusal, and None,
        when it is not from one."""
        owner = self.server.owner
        if self.headers.get("Host") not in (f"127.0.0.1:{owner.port}",
                                            f"localhost:{owner.port}") \
                or self.headers.get("Origin") is not None:
            self._reply(403, close=True)
            return None
        kind, _, token = (self.headers.get("Authorization") or "").partition(" ")
        channel = owner.lookup(token.strip()) if kind.lower() == "bearer" else None
        if channel is None:
            self._reply(401, close=True)
            return None
        if self.path.partition("?")[0] != "/mcp":
            self._reply(404, close=True)
            return None
        return channel

    def do_GET(self) -> None:
        if self._channel() is not None:
            self._reply(405, close=True)  # no stream of the server's own

    do_DELETE = do_GET  # no session to end
    do_PUT = do_OPTIONS = do_HEAD = do_GET

    def do_POST(self) -> None:
        channel = self._channel()
        if channel is None:
            return
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self._reply(411, close=True)
            return
        if not 0 <= length <= T.MAX_REQUEST:
            self._reply(413, close=True)
            return
        try:
            msg = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, RecursionError):
            msg = None
        if not isinstance(msg, dict):
            self._reply(400, json.dumps({"jsonrpc": "2.0", "id": None, "error": {
                "code": INVALID_REQUEST, "message": "not one message"}}).encode())
            return
        if msg.get("id") is None:
            self.server.owner.answer(channel, msg, threading.Event())
            self._reply(202)
            return
        self._answer(channel, msg)

    def _answer(self, channel: Channel, msg: dict) -> None:
        """Answer ``msg``: with JSON, or as an event stream once it takes a
        while and the client takes one."""
        box: dict = {}
        done, gone = threading.Event(), threading.Event()
        rid = msg.get("id")

        def work() -> None:
            try:
                box["answer"] = self.server.owner.answer(channel, msg, gone)
            except Exception as exc:
                logger.error(f"{msg.get('method')} failed: {exc}")
                box["answer"] = {"jsonrpc": "2.0", "id": rid,
                                 "error": {"code": -32603, "message": str(exc)}}
            finally:
                done.set()
        threading.Thread(target=work, name="xefm-mcp-call", daemon=True).start()
        streams = "text/event-stream" in (self.headers.get("Accept") or "")
        if done.wait(STREAM_AFTER) or not streams:
            done.wait()
            self._reply(200, json.dumps(box["answer"]).encode("utf-8"))
            return
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        token, step = meta.get("progressToken"), 0
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            self.wfile.write(b": waiting\n\n")
            while not done.wait(KEEP_ALIVE):
                step += 1
                if token is None:
                    self.wfile.write(b": waiting\n\n")
                else:  # a client's own time limit starts over
                    self._event({"jsonrpc": "2.0", "method": "notifications/progress", "params": {
                        "progressToken": token, "progress": step}})
            self._event(box["answer"])
        except OSError:
            gone.set()
            raise

    def _event(self, msg: dict) -> None:
        self.wfile.write(b"event: message\ndata: " + json.dumps(msg).encode("utf-8") + b"\n\n")


def start(handle: Callable[[dict], Any], *, version: str = "") -> McpServer | None:
    """A server, or None where it cannot listen (logged): the sessions then
    have ``xefmctl`` in their shells alone."""
    try:
        return McpServer(handle, version=version)
    except OSError as exc:
        logger.warning(f"Could not start the MCP server AI agents reach XeFM through: {exc}")
        return None
