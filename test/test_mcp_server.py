"""The MCP server AI agents reach XeFM through from outside their sandboxes
(:mod:`xefm.mcp_server`, #995), over real connections."""

import http.client
import json
import socket
import threading
import time
from contextlib import closing

import pytest

from xefm import mcp_server, remote_commands as T


class Server:
    def __init__(self):
        self.requests, self.answer = [], {"ok": True, "items": [{"path": "/a"}]}
        self.mcp = mcp_server.McpServer(self.handle, version="1")
        self.channel = self.mcp.open("agent", "/work")
        self.channel.session = "3"

    def handle(self, req):
        self.requests.append(req)
        return self.answer(req) if callable(self.answer) else self.answer

    def send(self, body=None, *, method="POST", path="/mcp", token=None, **headers):
        """``(status, body, response)`` of one request."""
        conn = http.client.HTTPConnection("127.0.0.1", self.mcp.port, timeout=20)
        with closing(conn):
            given = {"Authorization": f"Bearer {token or self.channel.token}",
                     "Accept": "application/json, text/event-stream"}
            given.update({k.replace("_", "-"): v for k, v in headers.items()})
            conn.request(method, path, body if isinstance(body, (str, bytes)) or body is None
                         else json.dumps(body), {k: v for k, v in given.items() if v is not None})
            got = conn.getresponse()
            return got.status, got.read(), got

    def rpc(self, method, params=None, **kw):
        status, body, _ = self.send({"jsonrpc": "2.0", "id": 1, "method": method,
                                     "params": params or {}}, **kw)
        assert status == 200
        return json.loads(body)

    def call(self, *argv, tool=mcp_server.TOOL, stdin=None):
        args = {"command": list(argv)} | ({"stdin": stdin} if stdin is not None else {})
        result = self.rpc("tools/call", {"name": tool, "arguments": args})["result"]
        return result["content"][0]["text"], result["isError"]


@pytest.fixture
def srv():
    server = Server()
    yield server
    server.mcp.close()


# --- who is let in -------------------------------------------------------------------

PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def test_it_listens_on_loopback_alone(srv):
    assert srv.mcp._server.server_address[0] == "127.0.0.1"


def test_nothing_is_answered_without_a_sessions_token(srv):
    assert srv.send(PING)[0] == 200
    for given in ({"Authorization": None}, {"Authorization": "Bearer "},
                  {"Authorization": f"Basic {srv.channel.token}"}, {"token": "x"},
                  {"token": srv.channel.token[:-1]}, {"token": "é"}):
        status, body, _ = srv.send(PING, **given)
        assert status == 401 and body == b""
    for method in ("GET", "DELETE", "PUT", "OPTIONS", "HEAD"):
        assert srv.send(method=method, token="x")[0] == 401
        assert srv.send(method=method)[0] == 405
    assert not srv.requests


def test_a_request_refused_gets_its_answer(srv):
    """Closed with the body unread, the connection is reset (Windows)."""
    for size in (2, 1000, 60_000):
        for _ in range(20):
            assert srv.send(b"x" * size, token="x")[0] == 401


def test_a_token_is_one_sessions_and_ends_with_it(srv):
    other = srv.mcp.open("user", "/")
    assert other.token != srv.channel.token and other.name != srv.channel.name
    srv.mcp.forget(srv.channel)
    assert srv.send(PING)[0] == 401
    assert srv.send(PING, token=other.token)[0] == 200


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"}, {"Host": "127.0.0.1"}, {"Host": "127.0.0.1:1"},
    {"Origin": "http://evil.example"}, {"Origin": "null"}, {"Origin": ""}])
def test_a_web_page_is_not_let_in_with_the_token_either(srv, headers):
    assert srv.send(PING, **headers)[0] == 403


def test_a_request_that_is_not_one_message_is_refused(srv):
    for body, code in ((b"", 400), (b"[]", 400), (b"{", 400), (b"[" * 100_000, 400)):
        assert srv.send(body)[0] == code
    assert srv.send(b"", Content_Length=str(T.MAX_REQUEST + 1))[0] == 413
    assert srv.send(b"", Content_Length="x")[0] == 411
    assert srv.send(PING, path="/")[0] == 404
    assert srv.send(PING)[0] == 200


def test_connections_held_open_do_not_stop_it_for_good(srv, monkeypatch):
    held = [socket.create_connection(("127.0.0.1", srv.mcp.port))
            for _ in range(mcp_server.CONNECTIONS)]
    time.sleep(0.2)
    with pytest.raises((OSError, http.client.HTTPException)):
        srv.send(PING)
    for s in held:
        s.close()
    for _ in range(50):
        try:
            assert srv.send(PING)[0] == 200
            return
        except (OSError, http.client.HTTPException):
            time.sleep(0.1)
    pytest.fail("the port stays closed")


def test_it_is_gone_once_closed(srv):
    port = srv.mcp.port
    srv.mcp.close()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), 2)


# --- the protocol --------------------------------------------------------------------

def test_it_opens_as_an_mcp_server(srv):
    got = srv.rpc("initialize", {"protocolVersion": "2025-03-26"})["result"]
    assert got["protocolVersion"] == "2025-03-26" and "tools" in got["capabilities"]
    assert srv.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"][
        "protocolVersion"] in mcp_server.VERSIONS
    assert srv.send({"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202
    assert srv.rpc("ping")["result"] == {}
    assert srv.rpc("resources/list")["error"]["code"] == mcp_server.METHOD_NOT_FOUND


def test_a_session_knows_when_its_tools_were_asked_for(srv):
    told = []
    srv.channel.when_listed(lambda: told.append(1))
    assert not told
    srv.rpc("tools/list")
    assert told == [1]
    srv.channel.when_listed(lambda: told.append(2))
    srv.channel.expect()  # a new process of the agent's
    srv.channel.when_listed(lambda: told.append(3))
    assert told == [1, 2]


def test_the_tools_say_which_reads(srv):
    read, write = srv.rpc("tools/list")["result"]["tools"]
    assert read["name"] == mcp_server.READ_TOOL and read["annotations"]["readOnlyHint"] is True
    assert write["name"] == mcp_server.TOOL and write["annotations"]["readOnlyHint"] is False
    for cmd in T.COMMANDS:
        where = read if cmd.local or mcp_server.reads_only(cmd, {}) else write
        assert f"\n{cmd.name} - " in where["description"], cmd.name


@pytest.mark.parametrize("args", [{}, {"command": []}, {"command": "state"},
                                  {"command": [1]}, {"command": ["state"], "stdin": 1}])
def test_a_call_that_is_not_one_is_an_error(srv, args):
    for name in (mcp_server.TOOL, "other"):
        got = srv.rpc("tools/call", {"name": name, "arguments": args})
        assert got["error"]["code"] == mcp_server.INVALID_PARAMS
    assert not srv.requests


# --- what a call does -----------------------------------------------------------------

def test_a_call_is_the_sessions_request(srv):
    assert srv.call("pane", "selected") == ("/a", False)
    [req] = srv.requests
    assert (req["cmd"], req["session"], req["policy"]) == ("pane selected", "3", "agent")
    srv.call("xefmctl", "state")
    assert srv.requests[-1]["cmd"] == "state"


def test_it_cannot_name_another_session_or_policy(srv):
    srv.rpc("tools/call", {"name": mcp_server.TOOL, "session": "1", "policy": "user",
                           "arguments": {"command": ["state"], "policy": "user"}})
    assert (srv.requests[0]["session"], srv.requests[0]["policy"]) == ("3", "agent")


def test_paths_are_taken_from_the_sessions_folder(srv, tmp_path):
    srv.channel.cwd = str(tmp_path)
    srv.call("read", "a.txt", tool=mcp_server.READ_TOOL)
    assert srv.requests[0]["args"]["url"] == str(tmp_path / "a.txt")
    srv.call("read", "ssh://host/a")
    assert srv.requests[1]["args"]["url"] == "ssh://host/a"
    srv.call("pane", "cd")
    assert srv.requests[2]["args"]["path"] == str(tmp_path)


def test_standard_input_is_what_it_is_given_and_no_file_is_read(srv, tmp_path):
    srv.channel.cwd = str(tmp_path)
    srv.call("copy", "-", "--to", "d", stdin="a\nb\n")
    assert srv.requests[0]["args"]["source"] == [str(tmp_path / "a"), str(tmp_path / "b")]
    plan = tmp_path / "plan.json"
    plan.write_text('[{"path": "secret", "name": "x"}]')
    text, bad = srv.call("rename", "--plan", str(plan))
    assert bad and "secret" not in text and len(srv.requests) == 1
    srv.call("rename", "--plan", "-", stdin=plan.read_text())
    assert srv.requests[1]["opts"]["plan"] == [
        {"path": str(tmp_path / "secret"), "name": "x"}]


@pytest.mark.parametrize("argv", [
    ["copy", "a", "--to", "b"], ["trash", "a"], ["fetch", "a"], ["entries", "--show"],
    ["pane", "cd", "/"], ["invoke", "x"], ["confirm", "sure?"],
    ["terminal-session", "start"]])
def test_the_tool_that_reads_takes_nothing_else(srv, argv):
    text, bad = srv.call(*argv, tool=mcp_server.READ_TOOL)
    assert bad and "xefmctl" in text and not srv.requests
    srv.call(*argv)
    assert len(srv.requests) == 1


def test_what_xefm_refuses_is_told(srv):
    srv.answer = {"ok": False, "error": "a dialog is open", "code": 5}
    text, bad = srv.call("state")
    assert bad and "a dialog is open" in text and "exit status 5" in text
    srv.answer = {"ok": True, "items": [{"answer": "no"}], "status": 1, "note": "said no"}
    assert srv.call("confirm", "sure?") == ("no\nsaid no\n(exit status 1)", False)


def test_help_and_mistakes_are_answered_here(srv):
    assert "usage: xefmctl" in srv.call("help", tool=mcp_server.READ_TOOL)[0]
    assert "--to DIR" in srv.call("help", "copy")[0]
    assert srv.call("nonsense")[1] and srv.call("copy")[1]
    assert not srv.requests


def test_a_search_is_gathered_and_a_flood_is_cut(srv, monkeypatch):
    closed = []

    def stream(_req):
        try:
            for i in range(10_000):
                yield {"ok": True, "items": [{"path": f"/{i:04}"}]}
        finally:
            closed.append(True)
    srv.answer = stream
    monkeypatch.setattr(mcp_server, "OUTPUT_LIMIT", 60)
    text, bad = srv.call("entries")
    assert text.startswith("/0000\n/0001\n") and "cut after 60" in text and closed == [True]
    assert len(text) < 200 and not bad


def test_a_slow_answer_comes_as_a_stream_that_stays_open(srv, monkeypatch):
    monkeypatch.setattr(mcp_server, "STREAM_AFTER", 0.05)
    monkeypatch.setattr(mcp_server, "KEEP_ALIVE", 0.05)
    srv.answer = lambda req: (time.sleep(0.4), {"ok": True, "items": [{"path": "/late"}]})[1]
    msg = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
        "name": mcp_server.TOOL, "arguments": {"command": ["pane", "path"]},
        "_meta": {"progressToken": "p"}}}
    _, body, got = srv.send(msg)
    assert got.getheader("Content-Type") == "text/event-stream"
    events = [json.loads(line[6:]) for line in body.decode().splitlines()
              if line.startswith("data: ")]
    assert events[0]["method"] == "notifications/progress"
    assert events[-1]["id"] == 7 and "/late" in str(events[-1]["result"])
    # A client that takes no stream waits for the answer.
    _, body, got = srv.send(msg, Accept="application/json")
    assert got.getheader("Content-Type") == "application/json" and b"/late" in body


def test_a_client_that_goes_away_stops_the_search(srv, monkeypatch):
    monkeypatch.setattr(mcp_server, "STREAM_AFTER", 0.05)
    monkeypatch.setattr(mcp_server, "KEEP_ALIVE", 0.05)
    closed = threading.Event()

    def stream(_req):
        try:
            while True:
                time.sleep(0.02)
                yield {"ok": True, "items": []}
        finally:
            closed.set()
    srv.answer = stream
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": mcp_server.READ_TOOL, "arguments": {"command": ["entries"]}}})
    with closing(socket.create_connection(("127.0.0.1", srv.mcp.port))) as s:
        s.sendall((f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{srv.mcp.port}\r\n"
                   f"Authorization: Bearer {srv.channel.token}\r\n"
                   f"Accept: text/event-stream\r\nContent-Length: {len(body)}\r\n\r\n"
                   f"{body}").encode())
        assert s.recv(100).startswith(b"HTTP/1.1 200")
    assert closed.wait(10)
