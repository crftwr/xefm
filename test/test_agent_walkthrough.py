"""What an AI agent's session is like to the user (#995): the hand check of
#1003, on a real XeFM with real panes, dialogs and file operations.

Each test runs with the agent's tools called directly (every run, every
platform), and, with --agent-cli, by the real Codex and Copilot CLIs with a
stand-in model choosing the calls (see test_agent_cli.py)."""

import json
import os
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request

import pytest

from anim_helper import settle
from agent_standin import Model
from test_agent_cli import WINDOWS_CODEX, asked_for_clis, clis, home, sandbox_runs  # noqa: F401 (fixtures)
from test_agent_rpc import FAKE_ACP
from xefm import agents, mcp_server
from xefm import agent_chat as C
from xefm.path import Path

FILES = {"own/a.txt": "own a", "far/b.txt": "far b", "far/c.txt": "far c",
         "far/sub/d.txt": "far d"}


class Call:
    """A tool call under way: ``text`` once the agent has its answer."""

    def __init__(self):
        self.text = None


class Walk:
    """XeFM with both panes in ``own``, and an agent's session drawn there."""

    def __init__(self, root, kind, get_cli, monkeypatch):
        from puikit.backends import create_backend
        from xefm import app as xefm_app
        from xefm.state_manager import XeFMStateManager
        self.root, self.kind, self.model, self.denied = root, kind, None, []
        for name, text in FILES.items():
            path = root / "ws" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        monkeypatch.setattr(agents, "cache_root", lambda: root / "cache")
        monkeypatch.setattr("xefm.app.is_desktop_mode", lambda: False)
        self.backend = create_backend("memory")
        self.backend.open()
        own = self.at("own")
        self.app = app = xefm_app.XeFMApp(
            self.backend, own, own, left_provided=True, right_provided=True,
            state_manager=XeFMStateManager(db_path=str(root / "state.db")))
        app.file_monitor.stop_monitoring()
        app.file_monitor.enabled = False
        app._settle_listings()
        app._agent_chat_ask = self._ask
        if kind == "tools":
            fake = root / "fake_agent.py"
            fake.write_text(textwrap.dedent(FAKE_ACP), encoding="utf-8")
            entry = {"command": [sys.executable, str(fake)], "preset": "copilot"}
        else:
            self.model = Model([])
            program = get_cli(kind)
            entry = {"preset": kind, "command": [program]}
            if kind == "codex":
                entry["command"] += [
                    "-c", "model='standin'", "-c", "model_provider='standin'", "-c",
                    "model_providers.standin={name='standin',base_url='%s',wire_api='responses',"
                    "requires_openai_auth=false}" % self.model.url,
                    "-c", "sandbox_mode='workspace-write'", *WINDOWS_CODEX]
            else:
                entry["command"] += ["--sandbox"]
                for name, value in {"BASE_URL": self.model.url, "TYPE": "openai",
                                    "API_KEY": "none"}.items():
                    monkeypatch.setenv(f"COPILOT_PROVIDER_{name}", value)
                monkeypatch.setenv("COPILOT_MODEL", "gpt-4.1")
                monkeypatch.setenv("COPILOT_OFFLINE", "true")
        app.config.AGENTS = [dict(entry, name="Agent")]
        self.start()

    def at(self, name):
        return os.path.realpath(str(self.root / "ws" / name))

    # --- the user ------------------------------------------------------------------

    def start(self):
        """The agent key, in the file manager."""
        self.app.open_agent()
        [self.session] = list(self.app._sessions)
        self.view = self.session.view
        self.until(lambda: self.view.conversation.state in (C.IDLE, C.EXITED), 60)
        assert self.view.conversation.state == C.IDLE, self.screen()
        self.channel = self.app._mcp_server._channels[-1]

    def again(self):
        """End the session, put both panes back in own, and start another."""
        self.app._agent_chat_close_request(self.view)
        self.until(lambda: not list(self.app._sessions))
        for pane in (self.app.pm.left_pane, self.app.pm.right_pane):
            self.go(pane, "own")
        self.start()

    def go(self, pane, name):
        """The user points a pane at a folder."""
        self.app._go_to_dir(pane, Path(self.at(name)), None)
        self.app._settle_listings()

    def key(self, key):
        from puikit.event import Event, EventType
        self.app.panel.dispatch_event(Event(EventType.KEY, key=key))
        settle(self.app.panel)

    def _ask(self, view, perm):
        """The agent's own question: none of XeFM's tools should get here."""
        self.denied.append((perm.tool, dict(perm.input)))
        view.answer(perm, C.deny())

    # --- XeFM ------------------------------------------------------------------------

    def pump(self):
        self.app._pump_monitoring()
        self.backend.run_animation_ticks()
        settle(self.app.panel)

    def until(self, cond, timeout=30):
        end = time.monotonic() + timeout
        while not cond():
            assert time.monotonic() < end, f"timed out\n{self.screen()}"
            self.pump()
            time.sleep(0.01)

    def screen(self):
        self.app.panel.render()
        return "\n".join(self.backend.snapshot())

    def box(self):
        from puikit.widgets import MessageBox
        layers = self.app.panel.layer_children(self.app._screens.files.group)
        found = [w for w in layers if isinstance(w, MessageBox)]
        assert len(found) <= 1, "one question at a time"
        return found[0] if found else None

    def on_agent(self):
        return self.app._screens.current.session is self.session

    # --- the agent ---------------------------------------------------------------------

    def call(self, *argv, tool=mcp_server.TOOL):
        call = Call()
        if self.model is not None:
            n = len(self.model.steps)
            self.model.steps.append(("tool", tool, {"command": list(argv)}))
            self.view._submit("go")

            def answer():
                return self.model.results.get(f"call_{n}")
            call.poll = answer
            return call

        def send():
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": tool, "arguments": {"command": list(argv)}}}
            req = urllib.request.Request(
                self.channel.url, data=json.dumps(body).encode(), method="POST",
                headers=dict(self.channel.headers, Accept="application/json"))
            with urllib.request.urlopen(req, timeout=60) as got:
                result = json.loads(got.read())["result"]
            call.text = result["content"][0]["text"]
        threading.Thread(target=send, daemon=True).start()
        call.poll = lambda: call.text
        return call

    def done(self, call):
        """The answer, with nothing asked of the user on the way."""
        self.until(lambda: call.poll() is not None or self.box() is not None, 90)
        assert self.box() is None, self.screen()
        return self.settled(call)

    def settled(self, call):
        self.until(lambda: call.poll() is not None
                   and self.view.conversation.state == C.IDLE, 90)
        assert not self.denied, "the agent asked about XeFM's own tool"
        return call.poll()

    def asked(self, call):
        """The question XeFM asks of the user, whom it took to the panes."""
        self.until(lambda: call.poll() is not None or self.box() is not None, 90)
        box = self.box()
        assert box is not None, call.poll()
        assert box.focused is None and not self.on_agent()
        for key in ("enter", "space"):  # typed for something else
            self.key(key)
            assert self.box() is box
        return box

    def read(self, name):
        return self.call("read", self.at(name), tool=mcp_server.READ_TOOL)

    def close(self):
        for session in list(self.app._sessions):
            self.app._close_session(session)
        if getattr(self.app, "_mcp_server", None) is not None:
            self.app._mcp_server.close()
        self.app._remote_server.close()
        if self.model is not None:
            self.model.close()
        self.backend.close()


@pytest.fixture(params=["tools", "codex", "copilot"])
def walk(request, tmp_path, monkeypatch):
    root, get = tmp_path, None
    if request.param != "tools":
        asked_for_clis(request.config)
        if not sandbox_runs():
            pytest.skip("no CLI's sandbox starts here")
        root, get = request.getfixturevalue("home"), request.getfixturevalue("clis")
    made = Walk(root, request.param, get, monkeypatch)
    yield made
    made.close()


pytestmark = pytest.mark.timeout(240)


# --- the hand check, A: by its numbers -------------------------------------------------

def test_1_the_state_and_the_header(walk):
    text = walk.done(walk.call("state", tool=mcp_server.READ_TOOL))
    assert walk.at("own") in text
    said = walk.view.conversation.sandbox
    assert said == {"tools": "not known", "codex": "on", "copilot": "on"}[walk.kind]
    assert f"this session's sandbox: {said}" in text
    assert f"sandbox {said}" in walk.screen()


def test_2_a_file_of_the_sessions_folder_is_read_at_once(walk):
    assert "own a" in walk.done(walk.read("own/a.txt"))


def test_3_4_5_a_file_elsewhere_is_asked_once_for_its_folder(walk):
    call = walk.read("far/b.txt")
    box = walk.asked(call)
    # All of it is on the screen, however long the path: nothing runs off it.
    shown = "".join(line.strip("\u2502 ") for line in walk.screen().splitlines())
    for words in ("far/b.txt", "and below, for the rest of its session?"):
        assert words.replace(" ", "").replace("/", os.sep) in shown.replace(" ", "")
    walk.key("escape")
    assert "did not allow" in walk.settled(call) and walk.box() is None
    assert walk.on_agent()  # back where the user was
    call = walk.read("far/b.txt")
    walk.asked(call)
    walk.key("left")
    walk.key("enter")
    assert "far b" in walk.settled(call) and walk.on_agent()
    for name, text in (("far/c.txt", "far c"), ("far/sub/d.txt", "far d")):
        assert text in walk.done(walk.read(name))
    assert box is not walk.box()


def test_5b_what_was_agreed_to_ends_with_the_session(walk):
    call = walk.read("far/b.txt")
    walk.asked(call)
    walk.key("left")
    walk.key("enter")
    assert "far b" in walk.settled(call)
    walk.again()
    call = walk.read("far/b.txt")
    walk.asked(call)
    walk.key("escape")
    walk.settled(call)


def test_6_a_folder_the_user_went_to_is_read_at_once_and_not_below(walk):
    walk.go(walk.app.pm.right_pane, "far")
    assert "far b" in walk.done(walk.read("far/b.txt"))
    call = walk.read("far/sub/d.txt")
    walk.asked(call)
    walk.key("escape")
    assert "far d" not in walk.settled(call)


def test_7_a_folder_the_agent_went_to_is_asked(walk):
    walk.done(walk.call("pane", "cd", "--pane", "other", walk.at("far")))
    walk.app._settle_listings()
    assert str(walk.app.pm.right_pane["path"]) == walk.at("far")
    call = walk.read("far/b.txt")
    walk.asked(call)
    walk.key("escape")
    assert "far b" not in walk.settled(call)


def test_8_a_copy_is_asked_once_and_comes_back(walk):
    argv = ("copy", walk.at("own/a.txt"), "--to", walk.at("far"), "--wait")
    copied = os.path.join(walk.at("far"), "a.txt")
    call = walk.call(*argv)
    walk.asked(call)
    walk.key("escape")
    assert "cancelled" in walk.settled(call) and not os.path.exists(copied)
    assert walk.on_agent()
    call = walk.call(*argv)
    walk.asked(call)
    walk.key("left")
    walk.key("enter")
    assert "copy: 1 item(s) done" in walk.settled(call)
    assert open(copied).read() == "own a" and walk.on_agent()


def test_9_reloading_the_configuration_is_asked(walk, monkeypatch):
    ran = []
    monkeypatch.setattr(walk.app, "reload_config", lambda: ran.append(1))
    call = walk.call("invoke", "reload_config")
    walk.asked(call)
    walk.key("escape")
    assert "did not allow" in walk.settled(call) and not ran


def test_10_nothing_of_a_session_is_left(walk):
    channel = walk.channel
    walk.done(walk.call("state", tool=mcp_server.READ_TOOL))
    walk.again()
    req = urllib.request.Request(channel.url, data=b"{}", headers=channel.headers)
    with pytest.raises(urllib.error.HTTPError) as got:
        urllib.request.urlopen(req, timeout=10)
    assert got.value.code == 401
    walk.app._close_terminal_sessions()
    assert not walk.app._mcp_server._channels and not walk.app._agent_folders
    left = [p for p in (walk.root / "cache").rglob("*") if p.is_file()
            and any(t in p.read_bytes() for t in (channel.token.encode(),
                                                  walk.channel.token.encode()))]
    assert not left and not list((walk.root / "cache").glob("*/sessions/session-*"))
