"""xefmctl and the socket it reaches XeFM on (#900).

The client's argument handling, the server end to end (a real socket, a real
shim run as a separate process), and what the app answers."""

import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from xefm import remote_cli, remote_server
from xefm.app import XeFMApp

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="the end-to-end parts use a Unix socket path")


# --- the client's arguments --------------------------------------------------------

def test_parse_defaults_and_panes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert remote_cli._parse("selected", []) == {"cmd": "selected", "pane": "this"}
    assert remote_cli._parse("selected", ["--pane", "other", "-0"]) == \
        {"cmd": "selected", "pane": "other", "nul": True}
    assert remote_cli._parse("pwd", ["--pane=left"])["pane"] == "left"
    # cd is relative to the shell's directory, not to the pane's.
    assert remote_cli._parse("cd", [])["path"] == os.path.abspath(".")
    assert remote_cli._parse("cd", ["sub"])["path"] == os.path.join(os.path.abspath("."), "sub")
    assert remote_cli._parse("cd", ["s3://bucket/dir"])["path"] == "s3://bucket/dir"


@pytest.mark.parametrize("cmd, args, code", [
    ("selected", ["--pane", "middle"], 2),
    ("pwd", ["--bogus"], 2),
    ("pwd", ["extra"], 2),
    ("view", [], 2),
    ("cd", ["a", "b"], 2),
    ("focused", ["-0"], 2),
    ("selected", ["--help"], 0),
])
def test_parse_refuses(cmd, args, code):
    with pytest.raises(remote_cli.RemoteError) as info:
        remote_cli._parse(cmd, args)
    assert info.value.code == code


def test_outside_an_xefm_shell(monkeypatch, capsys):
    monkeypatch.delenv("XEFM_SOCKET", raising=False)
    assert remote_cli.run("pwd", []) == 2
    assert "not in a shell XeFM started" in capsys.readouterr().err


# --- the server, end to end ---------------------------------------------------------

@pytest.fixture
def server():
    seen = []

    def handle(req):
        seen.append(req)
        if req["cmd"] == "pwd":
            return {"ok": True, "lines": ["/some/where"]}
        if req["cmd"] == "selected":
            return {"ok": True, "lines": ["/a b", "/c"], "nul": req.get("nul", False)}
        return {"ok": False, "error": "nope", "code": 5}

    srv = remote_server.RemoteServer(handle, python=sys.executable)
    srv.seen = seen
    yield srv
    srv.close()


def _env(monkeypatch, srv, session="7"):
    for k, v in srv.env(session).items():
        if k != "PATH":
            monkeypatch.setenv(k, v)


def test_a_request_round_trip(server, monkeypatch):
    _env(monkeypatch, server)
    answer = remote_cli.request({"cmd": "pwd", "pane": "this"})
    assert answer["lines"] == ["/some/where"]
    assert server.seen[-1]["session"] == "7"


def test_output_one_per_line_or_nul(server, monkeypatch):
    import io
    _env(monkeypatch, server)
    out = io.StringIO()
    assert remote_cli.run("selected", [], out=out) == 0
    assert out.getvalue() == "/a b\n/c\n"
    out = io.StringIO()
    assert remote_cli.run("selected", ["-0"], out=out) == 0
    assert out.getvalue() == "/a b\0/c\0"


def test_a_refusal_carries_its_code(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    assert remote_cli.run("view", ["/x"]) == 5
    assert "nope" in capsys.readouterr().err


def test_a_wrong_key_is_refused(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    monkeypatch.setenv("XEFM_TOKEN", "00" * 32)
    assert remote_cli.run("pwd", []) == 3
    assert not server.seen
    # The listener survives a bad client.
    _env(monkeypatch, server)
    assert remote_cli.request({"cmd": "pwd"})["lines"] == ["/some/where"]


def test_after_xefm_quits(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    server.close()
    assert remote_cli.run("pwd", []) == 3
    assert "has quit" in capsys.readouterr().err


def test_the_shim_runs_the_client_as_its_own_process(server):
    env = remote_server.RemoteServer.apply_env(server, {"PATH": os.environ["PATH"]}, "9")
    shim = os.path.join(server.bin_dir, "xefmctl")
    assert os.access(shim, os.X_OK)
    done = subprocess.run(["xefmctl", "pwd"], env=env, capture_output=True, text=True,
                          timeout=20)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "/some/where\n"
    assert server.seen[-1]["session"] == "9"


def test_apply_env_puts_the_shim_first_once(server):
    env = {"PATH": os.pathsep.join(["/usr/bin", server.bin_dir, "/bin"])}
    server.apply_env(env, "1")
    assert env["PATH"].split(os.pathsep) == [server.bin_dir, "/usr/bin", "/bin"]
    assert env["XEFM_SESSION"] == "1" and env["XEFM_SOCKET"] == server.address


def test_close_removes_the_socket_and_shim(server):
    path = server.address
    assert os.path.exists(path)
    server.close()
    assert not os.path.exists(path) and not os.path.exists(server.bin_dir)


# --- what the app answers -----------------------------------------------------------

class _P(str):
    """A path stand-in: str with the bits _remote_answer uses."""

    def __new__(cls, value, *, is_dir=False, exists=True):
        obj = super().__new__(cls, value)
        obj._is_dir, obj._exists = is_dir, exists
        return obj

    def is_dir(self):
        return self._is_dir

    def exists(self):
        return self._exists

    @property
    def parent(self):
        return os.path.dirname(self)

    @property
    def name(self):
        return os.path.basename(self)


def _app():
    left = {"path": "/L", "files": [_P("/L/a"), _P("/L/b c"), _P("/L/d")],
            "selected_files": {"/L/d", "/L/a"}, "focused_index": 1}
    right = {"path": "/R", "files": [], "selected_files": set(), "focused_index": 0}
    app = SimpleNamespace(went=[], viewed=[], logged=[])
    app.pm = SimpleNamespace(get_current_pane=lambda: left, get_inactive_pane=lambda: right)
    app.pane = lambda name: left if name == "left" else right
    app._sessions = []
    app._remote_pane = lambda name: XeFMApp._remote_pane(app, name)
    targets = {"/L/sub": _P("/L/sub", is_dir=True), "/L/a": _P("/L/a"),
               "/nope": _P("/nope", exists=False)}
    app._resolve_jump_target = lambda text, current: targets[text]
    app._go_to_dir = lambda pane, d, name: app.went.append((pane["path"], d, name))
    app._open_viewer = lambda target: app.viewed.append(target)
    app._view_on_file_manager = lambda target: app.viewed.append(target)
    app.log_info = app.logged.append
    return app


def _ask(app, **req):
    return XeFMApp._remote_answer(app, req)


def test_app_reads_the_panes_now():
    app = _app()
    assert _ask(app, cmd="pwd")["lines"] == ["/L"]
    assert _ask(app, cmd="pwd", pane="other")["lines"] == ["/R"]
    # Pane order, not set order; selected only.
    assert _ask(app, cmd="selected")["lines"] == ["/L/a", "/L/d"]
    assert _ask(app, cmd="selected", pane="right")["lines"] == []
    assert _ask(app, cmd="focused")["lines"] == ["/L/b c"]
    assert _ask(app, cmd="focused", pane="other")["lines"] == []


def test_app_cd_and_view():
    app = _app()
    assert _ask(app, cmd="cd", path="/L/sub")["ok"]
    assert _ask(app, cmd="cd", path="/L/a")["ok"]  # a file: its folder, cursor on it
    assert app.went == [("/L", "/L/sub", None), ("/L", "/L", "a")]
    assert not _ask(app, cmd="cd", path="/nope")["ok"]
    assert _ask(app, cmd="view", path="/L/a")["ok"] and app.viewed == ["/L/a"]
    assert not _ask(app, cmd="view", path="/L/sub")["ok"]
    assert _ask(app, cmd="bogus")["code"] == 2


def test_requests_wait_for_the_ui_thread():
    app = _app()
    app._terminal_handed_over = False
    app._REMOTE_WAIT = 5.0
    app._remote_answer = lambda req: XeFMApp._remote_answer(app, req)
    queued = []
    app._call_later = queued.append
    result = {}
    t = threading.Thread(target=lambda: result.update(
        XeFMApp._remote_handle(app, {"cmd": "pwd"})))
    t.start()
    while not queued:
        time.sleep(0.01)
    assert not result  # nothing answered until the UI thread runs it
    queued[0]()
    t.join(5)
    assert result["lines"] == ["/L"]


def test_while_terminal_mode_has_handed_over_only_reads_run():
    app = _app()
    app._terminal_handed_over = True
    app._REMOTE_READS = XeFMApp._REMOTE_READS
    app._remote_answer = lambda req: XeFMApp._remote_answer(app, req)
    assert XeFMApp._remote_handle(app, {"cmd": "selected"})["lines"] == ["/L/a", "/L/d"]
    refused = XeFMApp._remote_handle(app, {"cmd": "cd", "path": "/L/sub"})
    assert not refused["ok"] and not app.went


# --- the command line -----------------------------------------------------------------

def test_xefmctl_has_its_own_commands_only(capsys):
    assert remote_cli.main([]) == 0 and "usage: xefmctl" in capsys.readouterr().out
    # Not a front for xefm: anything else is a usage error, not forwarded.
    assert remote_cli.main(["ext", "list"]) == 2
    assert "unknown command 'ext'" in capsys.readouterr().err
