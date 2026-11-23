"""AI agent sessions drawn by XeFM (#959): Claude Code's stream-json mode,
folded into a conversation and drawn on a screen of its own.

A stand-in CLI (written below, run with this Python) speaks the protocol the
way Claude Code 2.1 does - checked against the real CLI while building this -
so nothing here needs an account or a network."""

import os
import queue
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from xefm import agent_chat as C
from xefm import agents

# --- a stand-in for `claude -p --input-format stream-json ...` --------------------

FAKE_CLI = textwrap.dedent(r'''
    import json, sys

    def out(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    turn = 0
    for line in sys.stdin:
        msg = json.loads(line)
        if msg["type"] == "control_request":
            sub = msg["request"]["subtype"]
            if sub == "initialize":
                # As Claude Code: only the answer at start; `system init`
                # comes with the first turn.
                out({"type": "control_response", "response": {
                    "subtype": "success", "request_id": msg["request_id"],
                    "response": {"commands": [{"name": "compact"}]}}})
            elif sub == "interrupt":
                out({"type": "result", "subtype": "error_during_execution",
                     "is_error": True, "session_id": "S1"})
            continue
        if msg["type"] == "control_response":
            continue
        turn += 1
        if turn == 1:
            out({"type": "system", "subtype": "init", "session_id": "S1",
                 "model": "fake-model", "cwd": "/tmp", "tools": ["Bash"]})
        text = msg["message"]["content"]
        mid = f"m{turn}"
        if "tool" in text:
            out({"type": "stream_event", "event": {"type": "message_start",
                 "message": {"id": mid}}})
            out({"type": "stream_event", "event": {"type": "content_block_start",
                 "index": 0, "content_block": {"type": "tool_use", "id": "t1",
                 "name": "Bash", "input": {}}}})
            out({"type": "assistant", "message": {"id": mid, "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash",
                 "input": {"command": "echo hi"}}], "stop_reason": None}})
            out({"type": "control_request", "request_id": "p1", "request": {
                "subtype": "can_use_tool", "tool_name": "Bash",
                "input": {"command": "echo hi"}, "tool_use_id": "t1",
                "permission_suggestions": [{"type": "addRules", "rules": [
                    {"toolName": "Bash", "ruleContent": "echo *"}],
                    "behavior": "allow", "destination": "localSettings"}]}})
            answer = json.loads(sys.stdin.readline())
            allowed = answer["response"]["response"]["behavior"] == "allow"
            out({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "hi" if allowed else "denied", "is_error": not allowed}]}})
            reply = "ran it: " + json.dumps(answer["response"]["response"])
        else:
            reply = "Hello **there**"
        mid = f"r{turn}"
        out({"type": "stream_event", "event": {"type": "message_start",
             "message": {"id": mid}}})
        out({"type": "stream_event", "event": {"type": "content_block_start",
             "index": 0, "content_block": {"type": "text", "text": ""}}})
        for part in (reply[:5], reply[5:]):
            out({"type": "stream_event", "event": {"type": "content_block_delta",
                 "index": 0, "delta": {"type": "text_delta", "text": part}}})
        out({"type": "assistant", "message": {"id": mid, "content": [
            {"type": "text", "text": reply}], "stop_reason": None}})
        out({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}})
        out({"type": "result", "subtype": "success", "is_error": False,
             "session_id": "S1", "result": reply})
''')


@pytest.fixture
def fake_cli(tmp_path):
    path = tmp_path / "fake_claude.py"
    path.write_text(FAKE_CLI, encoding="utf-8")
    return [sys.executable, str(path)]


class _Posts:
    """``post`` for the client: callbacks queued, run on the test's thread."""

    def __init__(self):
        self.q = queue.Queue()

    def __call__(self, fn):
        self.q.put(fn)

    def until(self, cond, timeout=10.0):
        end = time.monotonic() + timeout
        while not cond():
            left = end - time.monotonic()
            if left <= 0:
                raise AssertionError("timed out waiting for the agent")
            try:
                self.q.get(timeout=min(left, 0.2))()
            except queue.Empty:
                pass


# --- the conversation ---------------------------------------------------------------

def _stream(index, event):
    return {"type": "stream_event", "event": dict(event, index=index)}


def test_a_streamed_reply_folds_into_one_text_item():
    conv = C.Conversation()
    conv.handle({"type": "system", "subtype": "init", "session_id": "S", "model": "m"})
    assert conv.state == C.IDLE
    conv.add_user("hi")
    assert conv.state == C.WORKING
    conv.handle({"type": "stream_event", "event": {"type": "message_start",
                                                   "message": {"id": "a"}}})
    conv.handle(_stream(0, {"type": "content_block_start",
                            "content_block": {"type": "text", "text": ""}}))
    conv.handle(_stream(0, {"type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": "Hel"}}))
    assert conv.items[-1].text == "Hel" and conv.items[-1].open
    conv.handle({"type": "assistant", "message": {"id": "a", "content": [
        {"type": "text", "text": "Hello"}]}})
    conv.handle({"type": "result", "subtype": "success", "session_id": "S"})
    texts = [i for i in conv.items if i.kind == "text"]
    assert [t.text for t in texts] == ["Hello"]
    assert conv.state == C.IDLE and not conv.busy


def test_a_tool_call_its_permission_and_its_result():
    conv = C.Conversation()
    conv.add_user("run it")
    conv.handle({"type": "assistant", "message": {"id": "a", "content": [
        {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "ls"}}]}})
    perm = conv.handle({"type": "control_request", "request_id": "r", "request": {
        "subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls"},
        "tool_use_id": "t"}})
    assert isinstance(perm, C.Permission) and conv.state == C.ASKING
    conv.answered(perm, False)
    conv.handle({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t", "content": [
            {"type": "text", "text": "no"}], "is_error": True}]}})
    [tool] = [i for i in conv.items if i.kind == "tool"]
    assert tool.denied and tool.is_error and tool.result == "no"
    md = C.to_markdown(conv.items)
    assert "**Bash** `ls` ✗ declined" in md


def test_a_withdrawn_question_and_an_interrupted_turn():
    conv = C.Conversation()
    conv.add_user("x")
    conv.handle({"type": "control_request", "request_id": "r", "request": {
        "subtype": "can_use_tool", "tool_name": "Bash", "input": {}}})
    assert conv.handle({"type": "control_cancel_request", "request_id": "r"}) == "r"
    assert conv.state == C.WORKING
    conv.handle({"type": "result", "subtype": "error_during_execution", "is_error": True})
    assert conv.state == C.IDLE
    assert conv.items[-1].kind == "notice" and conv.items[-1].text == "Interrupted"


def test_the_transcript_reads_as_markdown():
    items = [C.Item("user", "line one\nline two"),
             C.Item("text", "Reply with `code`"),
             C.Item("tool", name="Read", input={"file_path": "/a/b.txt"},
                    result="\n".join(str(n) for n in range(20))),
             C.Item("tool", name="Edit", input={"file_path": "/a", "old_string": "x",
                                                "new_string": "y"}, result="ok"),
             C.Item("tool", name="Bash", input={"command": "cat x"}, result="```fence```"),
             C.Item("thinking", "", open=True)]
    md = C.to_markdown(items)
    assert "> line one\n> line two" in md
    assert "Reply with `code`" in md
    assert "**Read** `/a/b.txt` ✓" in md
    assert "_… 14 more lines_" in md
    assert "```diff\n- x\n+ y\n```" in md
    assert "~~~\n```fence```\n~~~" in md  # a result's own fence cannot close it
    assert "_Thinking…_" in md


def test_answers_to_the_cli():
    perm = C.Permission("r", "Bash", {"command": "ls"},
                        suggestions=[{"type": "addRules", "destination": "localSettings"}])
    assert C.allow(perm) == {"behavior": "allow", "updatedInput": {"command": "ls"}}
    always = C.allow(perm, always=True)
    # The suggested rules hold for this session only: XeFM writes no settings.
    assert always["updatedPermissions"] == [{"type": "addRules", "destination": "session"}]
    assert C.deny()["behavior"] == "deny"


def test_ask_user_question_options():
    perm = C.Permission("r", C.ASK_USER_TOOL, {"questions": [
        {"question": "Which?", "options": [{"label": "A"}, {"label": "B"}, {"x": 1}]},
        {"bad": True}]})
    [q] = C.questions(perm)
    assert [o["label"] for o in q["options"]] == ["A", "B"]


# --- the AGENTS entry ---------------------------------------------------------------

def test_ui_is_checked():
    ok = agents.normalize({"name": "C", "command": ["claude"], "preset": "claude-code",
                           "ui": "xefm"})
    assert ok["ui"] == "xefm" and agents.drawn(ok)
    assert agents.normalize({"name": "C", "command": ["claude"]})["ui"] == "terminal"
    assert "'ui'" in agents.normalize({"name": "C", "command": ["c"], "ui": "web"})
    # Only Claude Code can be drawn today.
    assert "needs 'preset'" in agents.normalize(
        {"name": "X", "command": ["codex"], "preset": "codex", "ui": "xefm"})


def test_chat_argv_is_stream_json_with_the_skill_rules_and_settings(tmp_path):
    entry = agents.normalize({"name": "Claude Code", "command": ["claude", "--model", "m"],
                              "preset": "claude-code", "ui": "xefm"})
    values = agents.prepare(SimpleNamespace(), entry, root=tmp_path, version="t")
    argv = agents.chat_argv(entry, values)
    assert argv[:3] == ["claude", "--model", "m"]
    for flag in ("-p", "--verbose", "--include-partial-messages"):
        assert flag in argv
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    assert argv[argv.index("--plugin-dir") + 1] == values["{plugin_dir}"]
    assert argv[argv.index("--settings") + 1] == values["{settings_file}"]
    rules = argv[argv.index("--append-system-prompt") + 1]
    assert "xefmctl state" in rules
    assert "terminal" not in rules.split("\n\n")[0]
    assert "XeFM draws this conversation" in rules
    assert "rather than long output in your reply" in rules


# --- the process ---------------------------------------------------------------------

def test_the_client_talks_to_the_cli(fake_cli, tmp_path):
    posts = _Posts()
    got, exits = [], []
    client = C.ChatClient(fake_cli, cwd=str(tmp_path), env=dict(os.environ), post=posts,
                          on_message=got.append, on_exit=lambda c, e: exits.append(c))
    client.start()
    posts.until(lambda: any(m.get("type") == "control_response" for m in got))
    assert client.send("hello")
    posts.until(lambda: any(m.get("type") == "result" for m in got))
    assert any(m.get("type") == "assistant" for m in got)
    client.close()
    posts.until(lambda: exits)
    assert exits == [0]


# --- the screen ------------------------------------------------------------------------

def _view(fake_cli, tmp_path, posts, asked):
    from puikit import Panel
    from puikit.backends.memory_backend import MemoryBackend
    from xefm.agent_chat_view import ChatView
    panel = Panel(MemoryBackend(width=80, height=24))
    closed, hidden = [], []
    view = ChatView(fake_cli, cwd=str(tmp_path), env=dict(os.environ), name="Claude Code",
                    post=posts, ask=lambda v, p: asked.append(p),
                    on_close_request=closed.append, on_hide=hidden.append)
    panel.push_layer(view, z=10, hints={"x": 0, "y": 0, "w": 80, "h": 24})
    view.closed, view.hidden = closed, hidden
    return panel, view


def _screen_text(panel):
    panel.render()
    return "\n".join(panel.backend.snapshot())


def _key(name, char=None, mods=()):
    from puikit import Event, EventType
    return Event(type=EventType.KEY, key=name, char=char, modifiers=frozenset(mods))


def test_the_view_sends_streams_and_asks(fake_cli, tmp_path):
    posts, asked = _Posts(), []
    panel, view = _view(fake_cli, tmp_path, posts, asked)
    assert view.start(panel)
    posts.until(lambda: view.conversation.state == C.IDLE)
    # Ready on the answer to initialize, before any message.
    assert "waiting for you" in _screen_text(panel)
    for ch in "hi":
        panel.dispatch_event(_key(ch, ch))
    panel.dispatch_event(_key("enter", "\r"))
    assert view.input.text == "" and view.history == ["hi"]
    posts.until(lambda: view.conversation.state == C.IDLE
                and any(i.kind == "text" for i in view.conversation.items))
    text = _screen_text(panel)
    assert "fake-model" in text  # known from `system init`, with the first turn
    assert "Hello there" in text and "> hi" not in text  # quoted, as a block
    # A tool that needs permission: the app is asked, the answer goes back.
    view.send("use a tool")
    posts.until(lambda: asked)
    assert view.conversation.state == C.ASKING
    view.answer(asked[0], C.allow(asked[0], always=True))
    posts.until(lambda: view.conversation.state == C.IDLE)
    reply = [i for i in view.conversation.items if i.kind == "text"][-1].text
    assert '"behavior": "allow"' in reply and '"destination": "session"' in reply
    view.close()


def test_the_view_keys(fake_cli, tmp_path):
    posts, asked = _Posts(), []
    panel, view = _view(fake_cli, tmp_path, posts, asked)
    view.start(panel)
    posts.until(lambda: view.conversation.state == C.IDLE)
    # Alt+Enter breaks the line; Enter sends both lines as one message.
    panel.dispatch_event(_key("a", "a"))
    panel.dispatch_event(_key("enter", "\r", mods=("alt",)))
    panel.dispatch_event(_key("b", "b"))
    assert view.input.text == "a\nb"
    panel.dispatch_event(_key("enter", "\r"))
    posts.until(lambda: view.conversation.state == C.IDLE)
    assert view.conversation.items[0].text == "a\nb"
    # Up on an empty field brings the message back; Down returns to the draft.
    panel.dispatch_event(_key("up"))
    assert view.input.text == "a\nb"
    panel.dispatch_event(_key("down"))
    assert view.input.text == ""
    # Escape with nothing running goes back to the file manager.
    panel.dispatch_event(_key("escape", "\x1b"))
    assert view.hidden == [view]
    # /exit asks to close the session.
    for ch in "/exit":
        panel.dispatch_event(_key(ch, ch))
    panel.dispatch_event(_key("enter", "\r"))
    assert view.closed == [view]
    view.close()


def test_the_view_starts_again_after_the_agent_ended(fake_cli, tmp_path):
    posts, asked = _Posts(), []
    panel, view = _view(fake_cli, tmp_path, posts, asked)
    seen = []
    view._restart_argv = lambda sid: seen.append(sid) or list(fake_cli)
    view.start(panel)
    posts.until(lambda: view.conversation.state == C.IDLE)
    view.send("first")  # the session id comes with the first turn
    posts.until(lambda: view.conversation.session_id == "S1"
                and view.conversation.state == C.IDLE)
    view.client._proc.kill()
    posts.until(lambda: view.conversation.state == C.EXITED)
    assert view.send("again")
    assert seen == ["S1"]  # --resume the same conversation
    posts.until(lambda: view.conversation.state == C.IDLE
                and view.conversation.items[-1].kind == "text")
    view.close()


# --- the app -----------------------------------------------------------------------------

def test_the_agent_key_opens_a_drawn_session_in_terminal_mode_too(monkeypatch, tmp_path,
                                                                  fake_cli):
    from test_terminal_sessions import _AGENT_METHODS, _app
    from xefm.app import XeFMApp
    from xefm.terminal_sessions import AGENT
    for desktop in (True, False):
        app = _app(monkeypatch, desktop=desktop)
        posts = _Posts()
        app._call_later = posts
        app.config.AGENTS = [{"name": "Claude Code", "command": fake_cli,
                              "preset": "claude-code", "ui": "xefm"}]
        monkeypatch.setattr(agents, "cache_root", lambda: tmp_path)
        monkeypatch.setattr(agents, "installed", lambda entry: True)
        app._program_env = lambda pane: (dict(os.environ), str(tmp_path))
        app.active_pane = lambda: {"path": str(tmp_path), "files": [],
                                   "selected_files": set()}
        app._focused_entry = lambda: None
        for name in _AGENT_METHODS + ("_start_agent_chat", "_agent_chat_for",
                                      "_agent_chat_changed", "_agent_chat_close_request"):
            setattr(app, name, getattr(XeFMApp, name).__get__(app))
        app._agent_chat_ask = lambda view, perm: None
        app._agent_chat_link = lambda href: False
        app.open_agent()
        [session] = list(app._sessions)
        assert session.kind == AGENT and session.name == "Claude Code"
        assert app._screens.current.session is session
        assert app.remote_policies[-1] == "agent"
        assert app.handed == []  # terminal mode does not hand its terminal over
        view = session.view
        assert "stream-json" in view.argv
        posts.until(lambda: view.conversation.state == C.IDLE)
        assert session.state == C.IDLE
        # The key again, from the file manager: back to the same session.
        app._show_screen(app._screens.files)
        app.open_agent()
        assert list(app._sessions) == [session]
        assert app._screens.current.session is session
        app._agent_chat_close_request(view)
        assert list(app._sessions) == []


def test_the_view_draws_on_a_pixel_backend_and_routes_the_mouse(fake_cli, tmp_path):
    from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP
    from puikit.backends.memory_backend import MemoryBackend
    from xefm.agent_chat_view import ChatView
    panel = Panel(MemoryBackend(width=80, height=24, capabilities=PROFILE_GUI_DESKTOP))
    view = ChatView(fake_cli, cwd=str(tmp_path), env={}, name="Claude Code",
                    post=lambda fn: fn(), ask=lambda v, p: None,
                    on_close_request=lambda v: None, on_hide=lambda v: None)
    view.conversation.items = [C.Item("user", "q"),
                               C.Item("text", "\n\n".join(f"para {n}" for n in range(60)))]
    view._dirty = True
    panel.push_layer(view, z=10, hints={"x": 0, "y": 0, "w": 80, "h": 24})
    panel.render()
    panel.render()
    md = view.transcript
    assert md.offset > 0  # it follows the end
    r = view._transcript_rect
    offset = md.offset
    view.handle_event(Event(type=EventType.MOUSE_SCROLL, x=r.x + 2, y=r.y + 2, scroll=3))
    assert md.offset < offset
    r = view._input_rect
    view.handle_event(Event(type=EventType.MOUSE_DOWN, x=r.x + 2, y=r.y + 0.5, button="left"))
    view.handle_event(Event(type=EventType.MOUSE_UP, x=r.x + 2, y=r.y + 0.5, button="left"))
    assert view._mouse_target is None


# --- the question dialog (AskUserQuestion) ------------------------------------------------

_OPTS = [{"label": "blocks", "description": "thumb-blocks.jpg"},
         {"label": "crystal"}, {"label": "earth"}]


@pytest.fixture(params=["tui", "gui"])
def q_panel(request):
    from puikit import Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
    from puikit.backends.memory_backend import MemoryBackend
    caps = PROFILE_GUI_DESKTOP if request.param == "gui" else PROFILE_TUI
    return Panel(MemoryBackend(width=80, height=24, capabilities=caps))


def _ask(panel, multi=False):
    from xefm.agent_question_dialog import show_question_dialog
    got = []
    dialog = show_question_dialog(panel, "どれが好き？", _OPTS, multi=multi,
                                  title="Theme", on_result=got.append)
    panel.render()
    return dialog, got


def test_single_choice_answers_with_the_row_or_its_number(q_panel):
    dialog, got = _ask(q_panel)
    text = _screen_text(q_panel)
    if not q_panel.backend.capabilities.supports("pixel_layout"):
        assert "( ) 2. crystal" in text and "thumb-blocks.jpg" in text and "Other:" in text
    q_panel.dispatch_event(_key("down"))
    q_panel.dispatch_event(_key("enter", "\r"))
    assert got == [["crystal"]]
    dialog, got = _ask(q_panel)
    q_panel.dispatch_event(_key("3", "3"))
    assert got == [["earth"]]


def test_multiple_choice_checks_several(q_panel):
    dialog, got = _ask(q_panel, multi=True)
    q_panel.dispatch_event(_key("space", " "))
    q_panel.dispatch_event(_key("3", "3"))
    text = _screen_text(q_panel)
    if not q_panel.backend.capabilities.supports("pixel_layout"):
        assert "[x] 1. blocks" in text
    q_panel.dispatch_event(_key("enter", "\r"))
    assert got == [["blocks", "earth"]]


def test_other_takes_a_typed_answer_and_escape_declines(q_panel):
    dialog, got = _ask(q_panel, multi=True)
    q_panel.dispatch_event(_key("1", "1"))
    for _ in range(3):
        q_panel.dispatch_event(_key("down"))
    for ch in "mine":
        q_panel.dispatch_event(_key(ch, ch))
    q_panel.dispatch_event(_key("enter", "\r"))
    assert got == [["blocks", "mine"]]
    dialog, got = _ask(q_panel)
    q_panel.dispatch_event(_key("escape", "\x1b"))
    assert got == [None]


def test_the_transcript_shows_questions_and_answers():
    item = C.Item("tool", name=C.ASK_USER_TOOL, input={"questions": [
        {"question": "Which?", "options": [{"label": "A"}, {"label": "B"}]},
        {"question": "And?", "multiSelect": True, "options": [{"label": "X"}]}]})
    md = C.tool_markdown(item)
    assert "Which?" in md and "_A, B_" in md and "{" not in md
    item.input["answers"] = {"Which?": "B", "And?": "X, mine"}
    md = C.tool_markdown(item)
    assert "→ **B**" in md and "→ **X, mine**" in md
