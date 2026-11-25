"""What an AI agent's session may do through xefmctl without the user: nothing
that changes a file or runs a program (the restricted session's hard layer,
:mod:`xefm.remote_dispatch`)."""

import io
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from xefm import actions, remote_cli, remote_commands, remote_dispatch, remote_server
from xefm.path import Path
from xefm.remote_dispatch import Pending


class Ctx:
    """The ActionContext calls the dispatcher makes, recorded; a question
    waits in ``asked`` for the test to answer it."""

    def __init__(self, app):
        self.app, self.asked, self.did = app, [], []
        self.entries = []

    def confirm(self, prompt, title="", on_result=None):
        self.asked.append((prompt, on_result))

    def answer(self, yes):
        self.asked.pop(0)[1](yes)

    def invoke(self, name):
        self.did.append(("invoke", name))

    def start_terminal_session(self, command, **kw):
        self.did.append(("start", command, getattr(self.app, "_new_session_policy", "user")))
        return SimpleNamespace(id=5, name="t")

    def find_in_files(self, root, query, **kw):
        self.did.append(("search", str(root)))
        return iter([{"path": Path("f"), "line": 1, "text": "hit"}])

    @property
    def pane(self):
        entries = [SimpleNamespace(path=p) for p in self.entries]
        return SimpleNamespace(focused=entries[0] if entries else None,
                               selected_or_focused=lambda: entries)


@pytest.fixture
def app(monkeypatch):
    app = SimpleNamespace(_terminal_handed_over=False, _sessions=[], config=SimpleNamespace())
    app._screens = SimpleNamespace(files=SimpleNamespace(group="files"))
    app._screens.current = app._screens.files
    app.panel = SimpleNamespace(layer_children=lambda g: [], default_layer_parent=None,
                                set_default_layer_parent=lambda p: None,
                                has_layer=lambda p: True, render=lambda: None)
    app._user_ctx = Ctx(app)
    monkeypatch.setattr(remote_dispatch, "_desktop", lambda: True)
    return app


def _do(app, argv, policy="agent", session="3"):
    req = dict(remote_cli.parse(argv), policy=policy, session=session)
    cmd = remote_commands.find(req["cmd"].split())[0]
    return remote_dispatch._answer(app, cmd, req)


def _refused(answer):
    return isinstance(answer, dict) and not answer["ok"]


# --- fetch ----------------------------------------------------------------------------

def test_an_agents_fetch_to_a_file_is_asked(app, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.write_text("new")
    dst.write_text("old")
    pending = _do(app, ["fetch", str(src), str(dst)])
    assert isinstance(pending, Pending) and dst.read_text() == "old"
    prompt, _ = app._user_ctx.asked[0]
    assert str(dst) in prompt and "replaced" in prompt
    app._user_ctx.answer(False)
    assert _refused(pending.wait()) and dst.read_text() == "old"

    pending = _do(app, ["fetch", str(src), str(dst)])
    app._user_ctx.answer(True)
    assert pending.wait()["items"][0]["path"] == str(dst) and dst.read_text() == "new"


def test_fetch_is_not_asked_for_a_temporary_file_or_for_the_users_shell(app, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.write_text("x")
    path = _do(app, ["fetch", str(src)])["items"][0]["path"]
    with open(path) as f:
        assert f.read() == "x" and os.path.basename(path) == "src"
    assert _do(app, ["fetch", str(src), str(dst)], policy="user")["ok"]
    assert dst.read_text() == "x" and not app._user_ctx.asked


def test_a_fetch_from_far_to_a_file_is_asked_both(app, tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.write_text("x")
    monkeypatch.setattr(remote_dispatch, "_is_local", lambda p: False)
    pending = _do(app, ["fetch", str(src), str(dst)])
    app._user_ctx.answer(True)   # may it read there
    assert not dst.exists()
    app._user_ctx.answer(True)   # may it write here
    assert pending.wait()["ok"] and dst.read_text() == "x"


def test_with_the_terminal_handed_over_what_must_be_asked_is_refused(app, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.write_text("x")
    app._terminal_handed_over = True
    for argv in (["fetch", str(src), str(dst)], ["read", "ssh://host/x"]):
        answer = remote_dispatch.handle(app, dict(remote_cli.parse(argv), policy="agent"))
        assert _refused(answer) and answer["code"] == remote_dispatch.SUSPENDED
    assert not dst.exists() and not app._user_ctx.asked


@pytest.mark.parametrize("name, safe", [
    ("a.txt", "a.txt"), ("..\\..\\x", "x"), ("../x", "x"), ("..", "file"), ("", "file"),
    (".", "file"), ("C:evil", "C_evil"), ("x:stream", "x_stream"), ("a\\", "file"),
    ("a\x00b", "a_b"), (".profile", ".profile")])
def test_a_fetched_name_stays_in_its_folder(name, safe):
    assert remote_dispatch._file_name(name) == safe


# --- running programs -----------------------------------------------------------------

def test_an_agents_terminal_session_is_asked_and_as_restricted(app):
    pending = _do(app, ["terminal-session", "start", "--hidden", "cmd", "a b"])
    prompt, _ = app._user_ctx.asked[0]
    assert "a b" in prompt and not app._user_ctx.did
    app._user_ctx.answer(True)
    assert pending.wait()["items"][0]["id"] == "5"
    assert app._user_ctx.did == [("start", ["cmd", "a b"], "agent")]
    assert app._new_session_policy == "user"  # only while it was started

    pending = _do(app, ["terminal-session", "start"])
    app._user_ctx.answer(False)
    assert _refused(pending.wait()) and len(app._user_ctx.did) == 1


def test_the_users_shell_starts_a_session_as_before(app):
    assert _do(app, ["terminal-session", "start", "cmd"], policy="user")["ok"]
    assert app._user_ctx.did == [("start", ["cmd"], "user")] and not app._user_ctx.asked


@pytest.mark.parametrize("name", sorted(remote_dispatch.AGENT_ASKED_ACTIONS))
def test_an_action_that_runs_programs_is_asked(app, name):
    app._user_ctx.entries = [Path("evil.bat")]
    pending = _do(app, ["invoke", name])
    prompt, _ = app._user_ctx.asked[0]
    assert ("evil.bat" in prompt) == name.startswith("open")
    app._user_ctx.answer(False)
    assert _refused(pending.wait()) and not app._user_ctx.did
    pending = _do(app, ["invoke", name])
    app._user_ctx.answer(True)
    assert pending.wait()["ok"] and app._user_ctx.did == [("invoke", name)]
    assert _do(app, ["invoke", name], policy="user")["ok"] and not app._user_ctx.asked


def test_the_actions_named_exist():
    for name in (*remote_dispatch.AGENT_ASKED_ACTIONS, *remote_dispatch.AGENT_DENIED_ACTIONS):
        assert actions.registry.resolve(actions.FILER, name) is not None, name


# --- what the question shows ----------------------------------------------------------

def test_a_question_shows_all_of_it_and_nothing_hides_in_it(app):
    shown = remote_dispatch._shown_to_user("ls\n\nin C:\\safe\u202egnp")
    assert "\n" not in shown and "\u202e" not in shown
    assert remote_dispatch._shown_to_user("写真.jpg") == "写真.jpg"
    assert _refused(_do(app, ["terminal-session", "start", "x" * 5000]))
    app._user_ctx.entries = [Path(f"f{i}") for i in range(50)]
    assert _refused(_do(app, ["invoke", "open_items_with_os"]))
    assert not app._user_ctx.asked and not app._user_ctx.did


# --- reading outside the local disk -----------------------------------------------------

def test_searching_inside_files_far_away_is_asked(app):
    pending = _do(app, ["find-in-files", "x", "ssh://host/dir"])
    assert isinstance(pending, Pending) and not app._user_ctx.did
    app._user_ctx.answer(False)
    assert _refused(pending.wait()) and not app._user_ctx.did
    pending = _do(app, ["find-in-files", "x", "ssh://host/dir"])
    app._user_ctx.answer(True)
    [answer] = list(pending.wait())
    assert answer["items"][0]["text"] == "hit"
    # Asked once per session; never for the local disk.
    list(_do(app, ["find-in-files", "x", "ssh://host/dir"]))
    list(_do(app, ["find-in-files", "x", "."], session="4"))
    assert not app._user_ctx.asked


@pytest.mark.skipif(sys.platform != "win32", reason="UNC paths")
@pytest.mark.parametrize("path, local", [
    (r"\\server\share\x", False), ("//server/share/x", False), (r"\\?\UNC\server\x", False),
    (r"\\?\C:\x", True), (r"C:\x", True)])
def test_a_server_by_its_unc_path_is_not_local(path, local):
    assert remote_dispatch._is_local(path) is local


# --- no default button --------------------------------------------------------------------

@pytest.fixture
def screen(app, tmp_path):
    """``app`` on a real panel, with the real ``confirm`` and file operations."""
    from puikit.backends.memory_backend import MemoryBackend
    from puikit.panel import Panel
    from xefm.file_operations import FileOperationService
    from xefm.user_api import ActionContext
    app.panel = panel = Panel(MemoryBackend(width=100, height=30))
    group = panel.push_layer_group(z=10, name="files")
    panel.set_default_layer_parent(group)
    app._screens.files.group = group
    app.config = SimpleNamespace(CONFIRM_COPY=False, CONFIRM_MOVE=False, CONFIRM_TRASH=False)
    ops = FileOperationService(app.config)
    src = tmp_path / "src"
    src.write_text("x")
    to = tmp_path / "to"
    to.mkdir()
    ctx = app._user_ctx
    ctx.confirm = ActionContext(app).confirm
    ctx.copy = lambda items, dest, on_done=None: ops.copy(
        panel, [Path(i) for i in items], Path(dest))
    ctx.trash = lambda items, on_done=None: ops.trash(panel, [Path(i) for i in items])
    app.src, app.to = str(src), str(to)
    app.box = lambda: panel.layer_children(group)[-1] if panel.layer_children(group) else None
    return app


def _press(app, key):
    from puikit.event import Event, EventType
    app.panel.dispatch_event(Event(EventType.KEY, key=key))


@pytest.mark.parametrize("argv", [
    ["copy", "SRC", "--to", "TO"], ["trash", "SRC"], ["fetch", "SRC", "TO/new"],
    ["terminal-session", "start", "cmd"], ["invoke", "sync_python_packages"],
    ["read", "ssh://host/x"], ["confirm", "sure?"]])
def test_what_an_agent_asks_starts_with_no_button_selected(screen, argv):
    argv = [a.replace("SRC", screen.src).replace("TO", screen.to) for a in argv]
    _do(screen, argv)
    box = screen.box()
    assert box.focused is None
    for key in ("enter", "space"):  # meant for something else
        _press(screen, key)
        assert screen.box() is box
    _press(screen, "escape")
    assert screen.box() is None
    assert os.path.exists(screen.src) and os.listdir(screen.to) == []
    assert not screen._user_ctx.did


def test_the_left_key_then_enter_agrees(screen):
    pending = _do(screen, ["terminal-session", "start", "cmd"])
    _press(screen, "left")
    _press(screen, "enter")
    assert pending.wait()["ok"] and screen._user_ctx.did


def test_the_right_key_then_enter_declines(screen):
    pending = _do(screen, ["terminal-session", "start", "cmd"])
    _press(screen, "right")
    _press(screen, "enter")
    assert not pending.wait()["ok"] and not screen._user_ctx.did


def test_the_users_own_confirmations_keep_their_default(screen):
    _do(screen, ["confirm", "sure?"], policy="user")
    box = screen.box()
    assert box.buttons[box.focused] == "OK"


# --- the wait ---------------------------------------------------------------------------

def test_the_client_waits_for_the_users_answer(app, monkeypatch):
    """A question takes as long as the user does: the client is told XeFM has
    the request, and does not give up after TIMEOUT."""
    monkeypatch.setattr(remote_cli, "TIMEOUT", 0.5)
    app._call_later = lambda fn: threading.Thread(target=fn).start()
    server = remote_server.RemoteServer(lambda req: remote_dispatch.handle(app, req),
                                        python=sys.executable)
    try:
        for k, v in server.env("3", "agent").items():
            if k != "PATH":
                monkeypatch.setenv(k, v)

        def user():
            while not app._user_ctx.asked:
                time.sleep(0.01)
            time.sleep(1.5)
            app._user_ctx.answer(True)
        t = threading.Thread(target=user, daemon=True)
        t.start()
        out = io.StringIO()
        assert remote_cli.run(["terminal-session", "start", "cmd"], out=out) == 0
        t.join(5)
        assert out.getvalue() == "5\n"
    finally:
        server.close()
