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
    assert "::: bullet error\n**Bash** ✗ declined\n\n```console\n$ ls\n```" in md


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
    # The user's words on a panel, the agent's indented under them.
    assert md.startswith("::: box\nline one\nline two\n:::")
    assert "::: bullet muted\nReply with `code`\n:::" in md
    assert "::: bullet success\n**Read**" in md  # a tool that worked: green
    # A fence the text itself holds cannot close the panel.
    assert C.to_markdown([C.Item("user", "a\n:::\nb")]).startswith(":::: box\na\n:::\nb\n::::")
    assert "Reply with `code`" in md
    assert "**Read** `/a/b.txt` ✓" in md
    assert "[… 14 more lines](xefm-agent:expand/2)" in md  # a link shows the rest
    assert "```diff\n- x\n+ y\n```" in md
    # A command and its output in one block; a fence it prints cannot close it.
    assert "~~~console\n$ cat x\n```fence```\n~~~" in md  # a result's own fence cannot close it
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
        app._agent_chat_diff = lambda view, item: None
        app._agent_mention_paths = lambda: []
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


def test_bash_is_one_block_with_its_purpose_in_the_head():
    item = C.Item("tool", name="Bash", input={"command": "cd x\nls", "description": "List x"},
                  result="a\nb", tool_id="t")
    md = C.tool_markdown(item)
    assert md.startswith("**Bash** List x ✓\n\n```console\n$ cd x\n> ls\na\nb\n```")
    running = C.Item("tool", name="Bash", input={"command": "sleep 1"}, open=True)
    assert C.to_markdown([running]).startswith("::: bullet accent\n**Bash** …")



# --- typing aids, modes, links ----------------------------------------------------------

def _plain_view(tmp_path, **kw):
    from puikit import Panel
    from puikit.backends.memory_backend import MemoryBackend
    from xefm.agent_chat_view import ChatView
    panel = Panel(MemoryBackend(width=80, height=24))
    view = ChatView(["claude"], cwd=str(tmp_path), env={}, name="Claude Code",
                    post=lambda fn: fn(), ask=lambda v, p: None,
                    on_close_request=lambda v: None, on_hide=lambda v: None, **kw)
    view.conversation.state = C.IDLE
    panel.push_layer(view, z=10, hints={"x": 0, "y": 0, "w": 80, "h": 24})
    return panel, view


def _type(panel, text):
    for ch in text:
        panel.dispatch_event(_key(ch, ch))


def test_slash_lists_the_sessions_commands(tmp_path):
    panel, view = _plain_view(tmp_path)
    view.conversation.commands = [
        {"name": "compact", "description": "Free up context", "argumentHint": "<how>"},
        {"name": "context", "description": "Show context usage"}]
    _type(panel, "/co")
    labels = [row[0] for row in view.menu.items]
    assert labels == ["/compact <how>", "/context"]
    assert "Show context usage" in _screen_text(panel)
    panel.dispatch_event(_key("down"))
    sent = []
    view.send = lambda text: sent.append(text) or True
    panel.dispatch_event(_key("enter", "\r"))  # takes no argument: runs at once
    assert sent == ["/context"] and view.menu is None
    _type(panel, "/com")
    panel.dispatch_event(_key("tab"))  # takes it, waits for the argument
    assert view.input.text == "/compact " and view.menu is None
    view.input.set_text("")
    _type(panel, "/cl")
    panel.dispatch_event(_key("escape"))
    assert view.menu is None and view.input.text == "/cl"
    _type(panel, "e")
    assert view.menu is not None  # changed text: lists again
    view.input.set_text("")
    _type(panel, "hi /co")
    assert view.menu is None  # only at the start of the message


def test_at_lists_files_from_the_panes_the_folder_and_below(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "deep_main.py").write_text("x")
    (tmp_path / "readme.md").write_text("x")
    picked = tmp_path / "picked.txt"
    picked.write_text("x")
    panel, view = _plain_view(tmp_path, mention_paths=lambda: [str(picked)])
    _type(panel, "look at @")
    labels = [row[0] for row in view.menu.items]
    assert labels[0] == "picked.txt" and "readme.md" in labels and "src/" in labels
    _type(panel, "src/")
    assert [row[0] for row in view.menu.items] == ["src/deep_main.py"]
    panel.dispatch_event(_key("tab"))
    assert view.input.text == "look at @src/deep_main.py "
    view.input.set_text("")
    _type(panel, "@deep")  # by name, from the index walked on a thread
    deadline = time.monotonic() + 5
    while view._file_index is None and time.monotonic() < deadline:
        time.sleep(0.02)
    view._update_menu()
    assert any(row[0] == "src/deep_main.py" for row in view.menu.items)
    view.input.set_text("")
    _type(panel, "@sr")
    panel.dispatch_event(_key("enter", "\r"))  # a folder taken lists inside it
    assert view.input.text == "@src/" and view.menu is not None


def test_shift_tab_steps_the_permission_mode(fake_cli, tmp_path):
    posts, asked = _Posts(), []
    panel, view = _view(fake_cli, tmp_path, posts, asked)
    view.start(panel)
    posts.until(lambda: view.conversation.state == C.IDLE)
    sent = []
    orig = view.client.request
    view.client.request = lambda body: sent.append(body) or orig(body)
    panel.dispatch_event(_key("tab", None, ("shift",)))
    assert sent[-1] == {"subtype": "set_permission_mode", "mode": "acceptEdits"}
    assert "accept edits" in _screen_text(panel)
    panel.dispatch_event(_key("tab", None, ("shift",)))
    assert view.conversation.permission_mode == "plan"
    view.close()


def test_the_cli_reports_its_mode():
    conv = C.Conversation()
    conv.handle({"type": "control_response", "response": {
        "subtype": "success", "request_id": "i",
        "response": {"commands": [], "current_permission_mode": "acceptEdits"}}})
    assert conv.permission_mode == "acceptEdits"
    conv.handle({"type": "system", "subtype": "status", "permissionMode": "plan"})
    assert conv.permission_mode == "plan"


def test_long_output_expands_and_an_edit_opens_its_diff(tmp_path):
    diffs = []
    panel, view = _plain_view(tmp_path, on_diff=lambda v, item: diffs.append(item))
    edit = C.Item("tool", name="Edit", input={"file_path": "/a", "old_string": "x",
                                              "new_string": "y"}, result="ok")
    long = C.Item("tool", name="Read", input={"file_path": "/b"},
                  result="\n".join(str(n) for n in range(40)))
    view.conversation.items = [edit, long]
    md = C.to_markdown(view.conversation.items)
    assert "[open diff](xefm-agent:diff/0)" in md
    assert "[… 34 more lines](xefm-agent:expand/1)" in md
    assert view.transcript.on_link("xefm-agent:expand/1")
    assert long.expanded
    md = C.to_markdown(view.conversation.items)
    assert "\n39\n" in md and "[show less](xefm-agent:collapse/1)" in md
    view.transcript.on_link("xefm-agent:collapse/1")
    assert not long.expanded
    view.transcript.on_link("xefm-agent:diff/0")
    assert diffs == [edit]


def test_an_edit_is_undone_to_show_the_file_before():
    item = C.Item("tool", name="Edit", input={"old_string": "b", "new_string": "B"})
    assert C.edit_before(item, "a\nB\nc\n") == "a\nb\nc\n"
    assert C.edit_before(item, "changed since") is None
    multi = C.Item("tool", name="MultiEdit", input={"edits": [
        {"old_string": "a", "new_string": "A"}, {"old_string": "A", "new_string": "AA"}]})
    assert C.edit_before(multi, "AA b") == "a b"


def test_a_plan_reads_as_the_plan():
    item = C.Item("tool", name=C.PLAN_TOOL, input={"plan": "1. Do it\n2. Check"})
    md = C.tool_markdown(item, 0)
    assert md.startswith("**Plan**") and "1. Do it" in md and "{" not in md


def test_the_app_opens_an_edit_as_the_whole_file_before_and_now(tmp_path):
    import types
    from xefm.app import XeFMApp
    target = tmp_path / "f.py"
    target.write_text("one\nTWO\nthree\n")
    opened = []

    def open_diff(left, right, titles=(None, None), on_close=None):
        opened.append((open(str(left)).read(), str(right), titles))
        on_close()

    app = types.SimpleNamespace(open_diff=open_diff, log_info=lambda m: None,
                                panel=types.SimpleNamespace(render=lambda: None),
                                _on_screen_of=lambda view, fn: fn())
    item = C.Item("tool", name="Edit", input={"file_path": str(target), "old_string": "two",
                                              "new_string": "TWO"})
    XeFMApp._agent_chat_diff(app, None, item)
    [(before, right, titles)] = opened
    assert before == "one\ntwo\nthree\n" and right == str(target)
    assert "before" in titles[0]
    target.write_text("rewritten")  # changed since: just the two texts
    XeFMApp._agent_chat_diff(app, None, item)
    assert opened[-1][0] == "two" and opened[-1][2] == ("Replaced text", "Replacement")


def _agent_call(conv, tid="a1"):
    conv.handle({"type": "assistant", "message": {"id": "m1", "content": [
        {"type": "tool_use", "id": tid, "name": "Agent",
         "input": {"description": "List folder files", "prompt": "ls"}}],
        "stop_reason": None}})


def _sub_step(conv, n, parent="a1"):
    conv.handle({"type": "assistant", "parent_tool_use_id": parent, "message": {
        "id": f"s{n}", "content": [{"type": "tool_use", "id": f"b{n}", "name": "Bash",
                                    "input": {"command": f"ls {n}"}}]}})
    conv.handle({"type": "user", "parent_tool_use_id": parent, "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"b{n}", "content": "x"}]}})


def test_a_subagents_steps_nest_under_its_call():
    conv = C.Conversation()
    _agent_call(conv)
    # Its prompt comes as a user message from inside: not shown.
    conv.handle({"type": "user", "parent_tool_use_id": "a1",
                 "message": {"content": [{"type": "text", "text": "Run ls"}]}})
    _sub_step(conv, 1)
    conv.handle({"type": "system", "subtype": "task_progress", "tool_use_id": "a1",
                 "description": "Running List all files"})
    assert len(conv.items) == 1
    agent = conv.items[0]
    assert [c.name for c in agent.children] == ["Bash"] and agent.children[0].result == "x"
    md = C.to_markdown(conv.items)
    assert "- **Bash** `ls 1` ✓" in md and "_Running List all files_" in md
    for n in range(2, 8):
        _sub_step(conv, n)
    md = C.to_markdown(conv.items)
    assert "[… 2 earlier steps](xefm-agent:expand/0)" in md
    assert "`ls 1`" not in md and "`ls 7`" in md
    agent.expanded = True
    md = C.to_markdown(conv.items)
    assert "`ls 1`" in md and "[show fewer steps](xefm-agent:collapse/0)" in md
    conv.handle({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "a1", "content": "two files"}]}})
    conv.handle({"type": "result", "subtype": "success", "session_id": "S"})
    md = C.to_markdown(conv.items)
    assert "Running" not in md and "two files" in md


def test_finished_thinking_folds_to_a_line_that_opens_it():
    conv = C.Conversation()
    conv.items = [C.Item("thinking", "first idea\nsecond"), C.Item("thinking", "")]
    md = C.to_markdown(conv.items)
    assert "[_Thought_ ›](xefm-agent:expand/0)" in md and "first idea" not in md
    assert md.count("Thought") == 1  # thinking sent without its text: nothing
    conv.items[0].expanded = True
    md = C.to_markdown(conv.items)
    assert "> first idea\n> second" in md and "collapse/0" in md


def test_the_header_says_how_full_the_context_is(tmp_path):
    conv = C.Conversation()
    assert conv.context_label() == ""
    conv.model = "claude-opus-5-5"
    conv.handle({"type": "assistant", "message": {"id": "m", "content": [], "usage": {
        "input_tokens": 2, "cache_creation_input_tokens": 3909,
        "cache_read_input_tokens": 36550}}})
    assert conv.context_label() == "40k context"
    # A subagent's calls are not the conversation's context.
    conv.handle({"type": "assistant", "parent_tool_use_id": "x", "message": {
        "id": "s", "content": [], "usage": {"input_tokens": 900000}}})
    conv.handle({"type": "result", "subtype": "success", "session_id": "S", "modelUsage": {
        "claude-haiku-5-5": {"contextWindow": 1000},
        "claude-opus-5-5": {"contextWindow": 200000}}})
    assert conv.context_label() == "20% context"
    panel, view = _plain_view(tmp_path)
    view.conversation = conv
    view._dirty = True
    panel.render()
    assert "20% context" in _screen_text(panel)


def test_the_todo_list_is_pinned_while_something_is_left(tmp_path):
    panel, view = _plain_view(tmp_path)
    todos = [{"content": "Read", "status": "completed"},
             {"content": "Write", "activeForm": "Writing", "status": "in_progress"},
             {"content": "Test", "status": "pending"}]
    item = C.Item("tool", name="TodoWrite", input={"todos": todos}, result="ok")
    view.conversation.items = [item]
    view._dirty = True
    panel.render()
    text = _screen_text(panel)
    assert "To do · 1/3 done" in text and "▸ Writing" in text and "○ Test" in text
    assert "✓ Read" not in text  # the finished ones are counted, not listed
    item.input = {"todos": [dict(t, status="completed") for t in todos]}
    assert view.conversation.todos() == []
    view._dirty = True
    panel.render()
    assert "To do" not in _screen_text(panel)


def test_slash_model_lists_the_models_and_switches(tmp_path):
    panel, view = _plain_view(tmp_path)
    conv = view.conversation
    conv.handle({"type": "control_response", "response": {
        "subtype": "success", "request_id": "i", "response": {"commands": [], "models": [
            {"value": "default", "displayName": "Default (recommended)"},
            {"value": "sonnet", "displayName": "Sonnet 5.5", "description": "Efficient"},
            {"value": "haiku", "displayName": "Haiku 5.5"}]}}})
    sent = []
    view.client = SimpleNamespace(running=True, close=lambda: None,
                                  request=lambda body: sent.append(body) or "xefm_9")
    _type(panel, "/mod")
    assert view.menu.items[0][0] == "/model <model>"
    panel.dispatch_event(_key("tab"))  # takes it: the models are listed
    assert view.input.text == "/model " and view.menu.kind == "model"
    assert [row[0] for row in view.menu.items] == [
        "Default (recommended)", "Sonnet 5.5", "Haiku 5.5"]
    _type(panel, "son")
    panel.dispatch_event(_key("enter", "\r"))
    assert sent == [{"subtype": "set_model", "model": "sonnet"}]
    assert conv.model_choice == "sonnet" and view.input.text == ""
    conv.handle({"type": "control_response", "response": {
        "subtype": "success", "request_id": "xefm_9",
        "response": {"model": "claude-sonnet-5-5"}}})
    assert conv.model == "claude-sonnet-5-5"
    view._submit("/model bogus")
    conv.handle({"type": "control_response", "response": {
        "subtype": "error", "request_id": "xefm_9", "error": "Model 'bogus' not found"}})
    assert "Model 'bogus' not found" in conv.items[-1].text
    # A new process keeps the model picked.
    conv.model_choice = "sonnet"
    started = []
    view.start = lambda panel=None, argv=None: started.append(argv) or True
    view._restart(resume=False)
    assert started[-1][-2:] == ["--model", "sonnet"]
    assert view.conversation.model_choice == "sonnet"
