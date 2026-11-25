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
        self.entries, self.hits = [], []

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
        return iter(self.hits or [{"path": Path(f"{root}/f"), "line": 1, "text": "hit"}])

    @property
    def pane(self):
        entries = [SimpleNamespace(path=p) for p in self.entries]
        return SimpleNamespace(focused=entries[0] if entries else None,
                               selected_or_focused=lambda: entries)


@pytest.fixture
def app(monkeypatch, tmp_path):
    app = SimpleNamespace(_terminal_handed_over=False, _sessions=[], config=SimpleNamespace())
    app._screens = SimpleNamespace(files=SimpleNamespace(group="files"))
    app._screens.current = app._screens.files
    app.panel = SimpleNamespace(layer_children=lambda g: [], default_layer_parent=None,
                                set_default_layer_parent=lambda p: None,
                                has_layer=lambda p: True, render=lambda: None)
    app._user_ctx = Ctx(app)
    app._agent_folders = {"3": str(tmp_path), "4": str(tmp_path)}
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

def test_searching_inside_files_far_away_is_asked(app, tmp_path):
    pending = _do(app, ["find-in-files", "x", "ssh://host/dir"])
    assert isinstance(pending, Pending) and not app._user_ctx.did
    app._user_ctx.answer(False)
    assert _refused(pending.wait()) and not app._user_ctx.did
    pending = _do(app, ["find-in-files", "x", "ssh://host/dir"])
    app._user_ctx.answer(True)
    [answer] = list(pending.wait())
    assert answer["items"][0]["text"] == "hit"
    # Asked once per session; never for the session's own folder.
    list(_do(app, ["find-in-files", "x", "ssh://host/dir"]))
    list(_do(app, ["find-in-files", "x", str(tmp_path)], session="4"))
    assert not app._user_ctx.asked


@pytest.mark.skipif(sys.platform != "win32", reason="UNC paths")
@pytest.mark.parametrize("path, local", [
    (r"\\server\share\x", False), ("//server/share/x", False), (r"\\?\UNC\server\x", False),
    (r"\\?\C:\x", True), (r"C:\x", True)])
def test_a_server_by_its_unc_path_is_not_local(path, local):
    assert remote_dispatch._is_local(path) is local


# --- reading outside the session's folder (#995) ------------------------------------------

@pytest.fixture
def places(app, tmp_path):
    """``own`` is the session's folder; ``far`` is another, with a file."""
    for name in ("own", "far", "far/sub"):
        (tmp_path / name).mkdir()
    for name in ("own/a", "far/b", "far/c", "far/sub/d"):
        (tmp_path / name).write_text(name)
    app._agent_folders = {"3": str(tmp_path / "own")}
    app.pm = SimpleNamespace(left_pane={"path": Path(str(tmp_path / "own"))},
                             right_pane={"path": Path(str(tmp_path / "own"))})
    app.at = lambda name: str(tmp_path / name)
    return app


def _text(answer):
    return answer["items"][0]["text"]


def test_a_read_outside_the_sessions_folder_is_asked_once_for_each_folder(places):
    app = places
    assert _text(_do(app, ["read", app.at("own/a")])) == "own/a" and not app._user_ctx.asked
    pending = _do(app, ["read", app.at("far/b")])
    prompt, _ = app._user_ctx.asked[0]
    assert os.path.realpath(app.at("far/b")) in prompt
    app._user_ctx.answer(False)
    assert _refused(pending.wait())
    pending = _do(app, ["read", app.at("far/b")])
    app._user_ctx.answer(True)
    assert _text(pending.wait()) == "far/b"
    for name in ("far/c", "far/sub/d"):  # agreed to for the folder, and below
        assert _text(_do(app, ["read", app.at(name)])) == name
    # Not for another session, nor for a folder above.
    assert isinstance(_do(app, ["read", app.at("far/b")], session="9"), Pending)
    assert not app._user_ctx.did and len(app._user_ctx.asked) == 1


def test_a_fetch_and_a_search_outside_it_are_asked_too(places):
    app = places
    for argv in (["fetch", app.at("far/b")], ["find-in-files", "x", app.at("far")]):
        pending = _do(app, argv)
        assert isinstance(pending, Pending) and not app._user_ctx.did
        app._user_ctx.answer(False)
        assert _refused(pending.wait())


def test_the_users_own_shell_reads_as_before(places):
    app = places
    assert _text(_do(app, ["read", app.at("far/b")], policy="user")) == "far/b"
    assert not app._user_ctx.asked


def test_files_in_a_panes_folder_are_read_unasked_where_the_user_went(places):
    app = places
    app.pm.right_pane["path"] = Path(app.at("far"))
    remote_dispatch.pane_moved(app, app.pm.right_pane["path"])
    assert _text(_do(app, ["read", app.at("far/b")])) == "far/b"
    list(_do(app, ["find-in-files", "x", app.at("far"), "--no-recursive"]))
    assert not app._user_ctx.asked
    # The files in it: what is below, or a search of that, is asked.
    assert isinstance(_do(app, ["read", app.at("far/sub/d")]), Pending)
    assert isinstance(_do(app, ["find-in-files", "x", app.at("far")]), Pending)


def test_a_folder_the_agent_went_to_does_not_count(places):
    app = places
    with remote_dispatch._acting(app, {"policy": "agent"}):
        app.pm.right_pane["path"] = Path(app.at("far"))
        remote_dispatch.pane_moved(app, app.pm.right_pane["path"])
    assert isinstance(_do(app, ["read", app.at("far/b")]), Pending)
    app._user_ctx.answer(False)
    remote_dispatch.pane_moved(app, Path(app.at("far")))  # the user, then
    assert _text(_do(app, ["read", app.at("far/b")])) == "far/b"


def test_the_panes_tell_who_moved_them(tmp_path):
    """The app's own hook: a re-read of the same folder is nobody's move."""
    from xefm.app import XeFMApp
    app = SimpleNamespace(_user_ctx=None, _BACK_MAX=9)
    pane = {"path": Path("/a"), "_hook_path": Path("/a")}
    fire = XeFMApp._fire_directory_changed.__get__(app)
    with remote_dispatch._acting(app, {"policy": "agent"}):
        pane["path"] = Path("/b")
        fire("left", pane)
    assert app._agent_went == {str(Path("/b"))} and not app._agent_acting
    fire("left", pane)  # the monitor re-reads it
    assert app._agent_went == {str(Path("/b"))}


@pytest.mark.skipif(sys.platform == "win32", reason="links need a privilege")
def test_a_link_is_followed_before_it_is_judged(places, monkeypatch):
    app = places
    os.symlink(app.at("far/b"), app.at("own/link"))
    os.symlink(app.at("far"), app.at("own/dir"))
    for argv in (["read", app.at("own/link")], ["read", app.at("own/dir/c")],
                 ["find-in-files", "x", app.at("own/dir")]):
        pending = _do(app, argv)
        assert isinstance(pending, Pending)
        app._user_ctx.answer(False)
        assert _refused(pending.wait())
    # A search of its own folder leaves out what a link leads out of it.
    app._user_ctx.hits = [{"path": Path(app.at(n)), "line": 1, "text": n}
                          for n in ("own/a", "own/link", "own/dir/c")]
    found = [i["text"] for a in _do(app, ["find-in-files", "x", app.at("own")])
             for i in a["items"]]
    assert found == ["own/a"]
    # Changed between the question and the opening: the file opened is judged.
    monkeypatch.setattr(remote_dispatch, "_real", lambda p: str(p))
    answer = _do(app, ["read", app.at("own/link")])
    assert _refused(answer) and "far/b" not in str(answer)


def test_with_the_terminal_handed_over_a_read_outside_is_refused(places):
    app = places
    app._terminal_handed_over = True
    for name, code in (("own/a", None), ("far/b", remote_dispatch.SUSPENDED)):
        answer = remote_dispatch.handle(app, dict(
            remote_cli.parse(["read", app.at(name)]), policy="agent", session="3"))
        assert answer.get("code") == code


# --- every command has its class ----------------------------------------------------------

def test_every_command_is_classified():
    assert set(remote_commands.AGENT_CLASS) == {c.name for c in remote_commands.COMMANDS}
    for cmd in remote_commands.COMMANDS:  # what changes files is never at once
        if cmd.effect == remote_commands.WRITE:
            assert remote_commands.AGENT_CLASS[cmd.name] != remote_commands.ALLOWED, cmd.name


#: A way to give each command that is asked, or asked for some of what it can
#: be given, that is. A new one fails until it is here.
ASKED = {
    "copy": ["SRC", "--to", "TO"], "move": ["SRC", "--to", "TO"], "trash": ["SRC"],
    "rename": ["--plan", "PLAN"], "tag add": ["t", "SRC"], "tag remove": ["t", "SRC"],
    "terminal-session start": ["cmd"], "terminal-session close": ["7"],
    "read": ["FAR"], "fetch": ["FAR"], "find-in-files": ["x", "FARDIR"],
    "invoke": ["reload_config"],
}


def test_what_is_asked_has_a_case():
    asked = {n for n, c in remote_commands.AGENT_CLASS.items()
             if c in (remote_commands.ASKED, remote_commands.DEPENDS)}
    assert asked == set(ASKED)


@pytest.mark.parametrize("name", sorted(ASKED))
def test_what_is_asked_does_nothing_before_the_answer(screen, name, tmp_path, monkeypatch):
    """Against the dispatcher and, for the operations, their own dialogs."""
    app = screen
    far = tmp_path / "far"
    far.mkdir()
    (far / "f").write_text("secret")
    plan = tmp_path / "plan.json"
    plan.write_text('[{"path": "%s", "name": "new"}]' % app.src.replace("\\", "/"))
    app._agent_folders = {"3": str(tmp_path / "to")}
    app._tag_store_of = lambda items: object()
    app._sessions = [SimpleNamespace(id=7, name="other", view=None)]
    app._close_session = lambda s: app._user_ctx.did.append(("close", s.id))
    app.log_info = lambda text: None
    ctx = app._user_ctx
    ctx.move = lambda items, dest, on_done=None: app.ops.move(
        app.panel, [Path(i) for i in items], Path(dest))
    ctx.rename = lambda pairs, on_done=None: ctx.confirm("rename?", on_result=lambda yes: None)
    ctx.add_tags = lambda *a, **k: ctx.did.append("tag")
    ctx.remove_tags = lambda *a, **k: ctx.did.append("untag")
    words = [w.replace("SRC", app.src).replace("FARDIR", str(far)).replace("FAR", str(far / "f"))
             .replace("PLAN", str(plan)) for w in ASKED[name]]
    words = [app.to if w == "TO" else w for w in words]
    answer = _do(app, [*name.split(), *words])
    assert app.box() is not None, "the user is asked"
    assert "secret" not in str(answer)
    _press(app, "escape")
    assert app.box() is None
    assert os.path.exists(app.src) and os.listdir(app.to) == [] and not ctx.did
    if isinstance(answer, Pending) and answer.answer is not None:
        assert "secret" not in str(answer.answer)


def test_what_is_refused_is_refused(app, tmp_path):
    src = tmp_path / "src"
    src.write_text("x")
    for name, kind in remote_commands.AGENT_CLASS.items():
        if kind == remote_commands.REFUSED:
            assert _refused(_do(app, [*name.split(), str(src)]))
    assert src.exists()


def test_an_action_of_the_users_own_is_asked(app, monkeypatch):
    action = SimpleNamespace(name="mine", description="Do mine", source="user", func=None)
    monkeypatch.setattr(actions.registry, "resolve", lambda ctx, name: action)
    pending = _do(app, ["invoke", "mine"])
    prompt, _ = app._user_ctx.asked[0]
    assert "mine" in prompt and not app._user_ctx.did
    app._user_ctx.answer(True)
    assert pending.wait()["ok"] and app._user_ctx.did == [("invoke", "mine")]
    assert _do(app, ["invoke", "mine"], policy="user")["ok"] and not app._user_ctx.asked


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
    app.ops = ops = FileOperationService(app.config)
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
