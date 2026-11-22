"""xefmctl and the socket it reaches XeFM on (#900, #952).

The command table, the client's arguments and output, the server end to end
(a real socket, a real shim run as a separate process, session keys,
streamed answers), and what XeFM answers (remote_dispatch)."""

import io
import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from xefm import remote_cli, remote_commands, remote_dispatch, remote_server
from xefm.path import Path

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="the end-to-end parts use a Unix socket path")


# --- the command table ---------------------------------------------------------------

def test_every_command_has_a_handler_and_a_reference_entry():
    names = {c.name for c in remote_commands.COMMANDS if not c.local}
    assert names == set(remote_dispatch._HANDLERS)
    reference = remote_commands.reference_markdown()
    for name in names:
        assert f"### `{name}`" in reference
    described = {d["command"] for d in remote_commands.describe()}
    assert described == names


def test_names_follow_the_api_with_hyphens():
    for cmd in remote_commands.COMMANDS:
        for word in cmd.words:
            assert word == word.lower() and "_" not in word, cmd.name


def test_the_skill_reference_is_current():
    from xefm import extensions
    page = extensions.SKILL_DIR / "references" / "xefmctl.md"
    assert page.read_text(encoding="utf-8") == remote_commands.reference_markdown(), \
        "run `make skill-references`"


# --- the client's arguments ----------------------------------------------------------

def test_paths_are_the_shells_and_urls_stand(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    here = os.path.abspath(".")
    assert remote_cli.parse(["pane", "cd"])["args"]["path"] == here
    assert remote_cli.parse(["pane", "cd", "sub"])["args"]["path"] == os.path.join(here, "sub")
    assert remote_cli.parse(["pane", "cd", "s3://b/d"])["args"]["path"] == "s3://b/d"
    req = remote_cli.parse(["pane", "selected", "--pane=other", "-0"])
    assert req["opts"] == {"pane": "other", "0": True}


@pytest.mark.parametrize("argv, code", [
    (["pane", "selected", "--pane", "middle"], 2),
    (["pane", "path", "--bogus"], 2),
    (["pane", "path", "extra"], 2),
    (["view"], 2),
    (["pane", "cd", "a", "b"], 2),
    (["pane", "focused", "-0"], 2),
    (["find-files", "x", "--limit", "many"], 2),
    (["pane"], 2),
    (["pane", "selected", "--help"], 0),
])
def test_parse_refuses(argv, code):
    with pytest.raises(remote_cli.RemoteError) as info:
        remote_cli.parse(argv)
    assert info.value.code == code


def test_outside_an_xefm_shell(monkeypatch, capsys):
    monkeypatch.delenv("XEFM_SOCKET", raising=False)
    assert remote_cli.run(["pane", "path"]) == 2
    assert "not in a shell XeFM started" in capsys.readouterr().err


def test_help_is_made_from_the_table(capsys):
    assert remote_cli.run(["help"]) == 0
    out = capsys.readouterr().out
    assert "  state " in out and "find-in-files" in out
    assert remote_cli.run(["help", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    copy = next(d for d in data if d["command"] == "copy")
    assert copy["effect"] == "write" and copy["waits"] == "option"
    assert remote_cli.run(["help", "pane"]) == 0
    assert "xefmctl pane open-list" in capsys.readouterr().out


# --- the server, end to end ------------------------------------------------------------

@pytest.fixture
def server():
    seen = []

    def handle(req):
        seen.append(req)
        if req["cmd"] == "pane path":
            return {"ok": True, "items": [{"path": "/some/where"}]}
        if req["cmd"] == "pane selected":
            return {"ok": True, "items": [{"path": "/a b"}, {"path": "/c"}]}
        if req["cmd"] == "find-files":
            return iter([{"ok": True, "items": [{"path": "/1", "name": "1"}]},
                         {"ok": True, "items": [{"path": "/2", "name": "2"}]}])
        if req["cmd"] == "diff":  # slow work: acknowledged, then answered
            return iter([{"ok": True}, {"ok": True, "status": 1, "note": "it differs"}])
        if req["cmd"] == "confirm":
            return {"ok": True, "items": [{"answer": "no"}], "status": 1}
        return {"ok": False, "error": "nope", "code": 5}

    srv = remote_server.RemoteServer(handle, python=sys.executable)
    srv.seen = seen
    yield srv
    srv.close()


def _env(monkeypatch, srv, session="7", policy="user"):
    for k, v in srv.env(session, policy).items():
        if k != "PATH":
            monkeypatch.setenv(k, v)


def test_a_request_round_trip_names_the_session_by_its_key(server, monkeypatch):
    _env(monkeypatch, server, policy="agent")
    monkeypatch.setenv("XEFM_SESSION", "someone-else")  # claimed, not believed
    out = io.StringIO()
    assert remote_cli.run(["pane", "path"], out=out) == 0
    assert out.getvalue() == "/some/where\n"
    assert server.seen[-1]["session"] == "7" and server.seen[-1]["policy"] == "agent"


def test_output_lines_nul_and_json(server, monkeypatch):
    _env(monkeypatch, server)
    out = io.StringIO()
    assert remote_cli.run(["pane", "selected"], out=out) == 0
    assert out.getvalue() == "/a b\n/c\n"
    out = io.StringIO()
    assert remote_cli.run(["pane", "selected", "-0"], out=out) == 0
    assert out.getvalue() == "/a b\0/c\0"
    out = io.StringIO()
    assert remote_cli.run(["pane", "selected", "--json"], out=out) == 0
    assert [json.loads(line) for line in out.getvalue().splitlines()] == \
        [{"path": "/a b"}, {"path": "/c"}]


def test_a_streamed_answer_arrives_in_pieces(server, monkeypatch):
    _env(monkeypatch, server)
    out = io.StringIO()
    assert remote_cli.run(["find-files", "*"], out=out) == 0
    assert out.getvalue() == "/1\n/2\n"


def test_an_answer_carries_its_exit_status(server, monkeypatch):
    _env(monkeypatch, server)
    out = io.StringIO()
    assert remote_cli.run(["confirm", "sure?"], out=out) == 1
    assert out.getvalue() == "no\n"


def test_a_request_too_large_is_refused_before_it_is_sent(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    monkeypatch.setattr(remote_commands, "MAX_REQUEST", 200)
    paths = io.StringIO("".join(f"/some/long/path/{i:04d}\n" for i in range(50)))
    assert remote_cli.run(["pane", "open-list", "-"], stdin=paths) == 2
    assert "too large" in capsys.readouterr().err and not server.seen


def test_the_limit_takes_a_long_document():
    assert remote_commands.MAX_REQUEST >= 4 * 1024 * 1024
    assert remote_server.MAX_REQUEST == remote_commands.MAX_REQUEST


def test_the_status_of_a_late_answer_reaches_the_exit_code(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    assert remote_cli.run(["diff", "/a", "/b"], out=io.StringIO()) == 1
    assert "it differs" in capsys.readouterr().err


def test_a_refusal_carries_its_code(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    assert remote_cli.run(["view", "/x"]) == 5
    assert "nope" in capsys.readouterr().err


def test_a_wrong_key_is_refused(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    monkeypatch.setenv("XEFM_TOKEN", "00" * 32)
    assert remote_cli.run(["pane", "path"]) == 3
    assert not server.seen
    # The listener survives a bad client.
    _env(monkeypatch, server)
    assert remote_cli.run(["pane", "path"], out=io.StringIO()) == 0


def test_a_session_key_xefm_never_handed_out_is_refused(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    monkeypatch.setenv("XEFM_SESSION_KEY", "made-up")
    assert remote_cli.run(["pane", "path"]) == 3
    assert "XEFM_SESSION_KEY" in capsys.readouterr().err and not server.seen
    monkeypatch.delenv("XEFM_SESSION_KEY")
    assert remote_cli.run(["pane", "path"]) == 3


def test_after_xefm_quits(server, monkeypatch, capsys):
    _env(monkeypatch, server)
    server.close()
    assert remote_cli.run(["pane", "path"]) == 3
    assert "has quit" in capsys.readouterr().err


def test_the_shim_runs_the_client_as_its_own_process(server):
    env = server.apply_env({"PATH": os.environ["PATH"]}, "9")
    shim = os.path.join(server.bin_dir, "xefmctl")
    assert os.access(shim, os.X_OK)
    done = subprocess.run(["xefmctl", "pane", "path"], env=env, capture_output=True,
                          text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "/some/where\n"
    assert server.seen[-1]["session"] == "9"
    done = subprocess.run(["xefmctl", "help", "--json"], env=env, capture_output=True,
                          text=True, timeout=20)
    assert done.returncode == 0 and json.loads(done.stdout)


def test_apply_env_puts_the_shim_first_once(server):
    env = {"PATH": os.pathsep.join(["/usr/bin", server.bin_dir, "/bin"])}
    server.apply_env(env, "1")
    assert env["PATH"].split(os.pathsep) == [server.bin_dir, "/usr/bin", "/bin"]
    assert env["XEFM_SESSION"] == "1" and env["XEFM_SOCKET"] == server.address
    assert server.lookup(env["XEFM_SESSION_KEY"]) == ("1", "user")


def test_close_removes_the_socket_and_shim(server):
    path = server.address
    assert os.path.exists(path)
    server.close()
    assert not os.path.exists(path) and not os.path.exists(server.bin_dir)


# --- what XeFM answers ------------------------------------------------------------------

def _app(tmp_path):
    left_dir = tmp_path / "L"
    left_dir.mkdir()
    for name in ("a", "b c", "d"):
        (left_dir / name).write_text(name)
    (left_dir / "sub").mkdir()
    files = [Path(str(left_dir / n)) for n in ("a", "b c", "d")]
    left = {"path": Path(str(left_dir)), "files": files,
            "selected_files": {str(files[2]), str(files[0])}, "focused_index": 1}
    right = {"path": Path(str(tmp_path)), "files": [], "selected_files": set(),
             "focused_index": 0}
    app = SimpleNamespace(went=[], logged=[], _terminal_handed_over=False)
    app.pm = SimpleNamespace(active_pane="left")
    app.pane = lambda name: left if name == "left" else right
    app._sessions = []

    def go(pane, target, focus):
        app.went.append((str(pane["path"]), str(target), focus))
    app._go_to_dir = go
    from xefm.app import XeFMApp
    app._resolve_jump_target = XeFMApp._resolve_jump_target
    app.log_info = app.logged.append
    # The file manager's screen, with nothing over the panes.
    app._screens = SimpleNamespace(files=SimpleNamespace(group="files"))
    app._screens.current = app._screens.files
    app.panel = SimpleNamespace(layer_children=lambda g: [], default_layer_parent=None,
                                set_default_layer_parent=lambda p: None,
                                has_layer=lambda p: True)
    return app, left_dir


def _ask(app, line, **extra):
    import shlex
    req = remote_cli.parse(shlex.split(line))
    req.update(extra)
    cmd = remote_commands.find(req["cmd"].split())[0]
    return remote_dispatch._answer(app, cmd, req)


def _paths(answer):
    return [os.path.basename(i["path"]) for i in answer["items"]]


def test_xefm_reads_the_panes_now(tmp_path):
    app, left = _app(tmp_path)
    assert _ask(app, "pane path")["items"] == [{"path": str(left)}]
    assert _ask(app, "pane path --pane other")["items"] == [{"path": str(tmp_path)}]
    # Pane order, not set order; selected only.
    assert _paths(_ask(app, "pane selected")) == ["a", "d"]
    assert _paths(_ask(app, "pane selected --pane right")) == []
    assert _paths(_ask(app, "pane focused")) == ["b c"]
    assert _paths(_ask(app, "pane entries --limit 2")) == ["a", "b c"]


def test_pane_cd_goes_to_a_folder_or_a_files_folder(tmp_path):
    app, left = _app(tmp_path)
    assert _ask(app, f"pane cd {left / 'sub'}")["ok"]
    assert _ask(app, f"pane cd {left / 'a'}")["ok"]  # a file: its folder, cursor on it
    assert app.went == [(str(left), str(left / "sub"), None), (str(left), str(left), "a")]
    refused = _ask(app, f"pane cd {left / 'nope'}")
    assert not refused["ok"] and refused["code"] == 1


def test_entries_and_find_files_stream(tmp_path):
    app, left = _app(tmp_path)
    from xefm.user_api import ActionContext
    app._user_ctx = ActionContext(app)
    answers = list(_ask(app, f"entries {left}"))
    names = sorted(os.path.basename(i["path"]) for a in answers for i in a["items"])
    assert names == ["a", "b c", "d", "sub"]
    (left / "sub" / "deep.txt").write_text("needle here\n")
    app._user_ctx = SimpleNamespace(
        find_files=lambda root, pattern, **k: iter([Path(str(left / "sub" / "deep.txt"))]))
    answers = list(_ask(app, f"find-files deep {left}"))
    assert [i["name"] for a in answers for i in a["items"]] == ["deep.txt"]


def test_read_gives_the_text(tmp_path):
    app, left = _app(tmp_path)
    import shlex
    [item] = _ask(app, f"read {shlex.quote(str(left / 'b c'))}")["items"]
    assert item["text"] == "b c"
    assert _ask(app, f"read {left / 'sub'}")["code"] == 1


def test_requests_wait_for_the_ui_thread(tmp_path):
    app, left = _app(tmp_path)
    queued = []
    app._call_later = queued.append
    result = {}
    t = threading.Thread(target=lambda: result.update(remote_dispatch.handle(
        app, dict(remote_cli.parse(["pane", "path"]), policy="user"))))
    t.start()
    while not queued:
        time.sleep(0.01)
    assert not result  # nothing answered until the UI thread runs it
    queued[0]()
    t.join(5)
    assert result["items"] == [{"path": str(left)}]


def test_slow_work_is_acknowledged_then_answered(tmp_path, monkeypatch):
    app, left = _app(tmp_path)
    monkeypatch.setattr(remote_dispatch, "ACK_AFTER", 0.05)
    slow = remote_dispatch._HANDLERS["pane path"]
    monkeypatch.setitem(remote_dispatch._HANDLERS, "pane path",
                        lambda app, req: (time.sleep(0.3), slow(app, req))[1])
    app._call_later = lambda fn: threading.Thread(target=fn).start()
    answers = list(remote_dispatch.handle(app, dict(remote_cli.parse(["pane", "path"]))))
    assert answers[0] == {"ok": True, "items": []}  # XeFM has it
    assert answers[1]["items"] == [{"path": str(left)}]


def test_work_the_ui_thread_never_started_is_not_done_late(tmp_path, monkeypatch):
    app, left = _app(tmp_path)
    monkeypatch.setattr(remote_dispatch, "UI_WAIT", 0.05)
    queued = []
    app._call_later = queued.append
    answer = remote_dispatch.handle(app, dict(remote_cli.parse(["pane", "cd", str(left)])))
    assert answer["code"] == 4 and "busy" in answer["error"]
    queued[0]()  # the UI thread gets to it after all
    assert app.went == []  # told busy, so nothing happens


def test_while_terminal_mode_has_handed_over_only_reads_run(tmp_path):
    app, left = _app(tmp_path)
    app._terminal_handed_over = True
    answer = remote_dispatch.handle(app, dict(remote_cli.parse(["pane", "selected"])))
    assert _paths(answer) == ["a", "d"]
    refused = remote_dispatch.handle(app, dict(remote_cli.parse(["pane", "cd", str(left)])))
    # Not "busy" (4): it lasts until the shell exits, so not worth a retry (#961).
    assert not refused["ok"] and refused["code"] == 6 and not app.went
    assert "suspended" in refused["error"] and refused["error"].isascii()


def test_state_says_xefm_is_suspended(tmp_path, monkeypatch):
    app, _left = _app(tmp_path)
    app._screens.current = SimpleNamespace(id="files", kind="files")
    app._screen_label = lambda screen: "Files"
    monkeypatch.setattr(remote_dispatch, "_pane_api", lambda app, req: SimpleNamespace(
        path=Path(str(tmp_path)), focused=None, selected=lambda: []))
    item, = _ask(app, "state")["items"]
    assert item["suspended"] is False and "suspended" not in item["text"]
    app._terminal_handed_over = True
    item, = remote_dispatch.handle(app, dict(remote_cli.parse(["state"])))["items"]
    assert item["suspended"] is True and "suspended" in item["text"]


def test_which_commands_need_the_screen_is_in_the_help():
    from xefm import remote_commands as T
    cd, = [c for c in T.COMMANDS if c.name == "pane cd"]
    state, = [c for c in T.COMMANDS if c.name == "state"]
    assert T.needs_screen(cd) and not T.needs_screen(state)
    assert " *pane cd" in T.usage() and "  state" in T.usage()
    assert "exit status 6" in T.command_help(cd)
    assert {d["command"]: d["needs_screen"] for d in T.describe()}["view"] is True


def test_an_agents_first_read_outside_the_disk_is_asked(tmp_path, monkeypatch):
    app, left = _app(tmp_path)
    asked = []
    app._user_ctx = SimpleNamespace(confirm=lambda prompt, title="", on_result=None:
                                    asked.append(on_result))
    monkeypatch.setattr(remote_dispatch, "_is_local", lambda p: False)
    pending = _ask(app, f"read {left / 'a'}", policy="agent", session="3")
    assert isinstance(pending, remote_dispatch.Pending) and len(asked) == 1
    asked[0](True)
    assert pending.wait()["items"][0]["text"] == "a"
    # Asked once per session.
    assert _ask(app, f"read {left / 'd'}", policy="agent", session="3")["ok"]
    assert len(asked) == 1


# --- the command line ---------------------------------------------------------------------

def test_xefmctl_has_its_own_commands_only(capsys):
    assert remote_cli.main([]) == 0 and "usage: xefmctl" in capsys.readouterr().out
    # Not a front for xefm: anything else is a usage error, not forwarded.
    assert remote_cli.main(["ext", "list"]) == 2
    assert "unknown command 'ext'" in capsys.readouterr().err
