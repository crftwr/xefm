"""AI agent sessions drawn by XeFM for the agents that speak JSON-RPC: Codex's
app-server, and the Agent Client Protocol of Copilot and Antigravity.

Stand-in agents (written below, run with this Python) speak each protocol in
the shapes recorded from the real CLIs - codex-cli 0.171, GitHub Copilot CLI
1.0.114, Antigravity CLI 1.5.14 - so nothing here needs an account or a
network. How a conversation is drawn is test_agent_chat.py's."""

import os
import sys
import textwrap
from types import SimpleNamespace

import pytest

from test_agent_chat import _key, _Posts, _screen_text, _type
from xefm import agent_acp, agent_codex, agent_rpc, agents
from xefm import agent_chat as C

# --- stand-ins ----------------------------------------------------------------------

COMMON = r'''
import json, sys

def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

def read():
    line = sys.stdin.readline()
    return json.loads(line) if line else sys.exit(0)

log = open(sys.argv[0] + ".log", "a", encoding="utf-8")

def note(msg):
    log.write(json.dumps(msg) + "\n")
    log.flush()

def answer(msg, result):
    out({"id": msg["id"], "result": result, "jsonrpc": "2.0"})

def ask(rid, method, params):
    out({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    while True:
        msg = read()
        note(msg)
        if msg.get("id") == rid and "method" not in msg:
            return msg.get("result") or msg.get("error")
'''

FAKE_CODEX = COMMON + r'''
T = "thread-1"

def tell(method, **params):
    out({"method": method, "params": dict(params, threadId=T)})

def item(method, **data):
    tell("item/" + method, turnId="turn", item=data)

def finish(status="completed", **more):
    tell("turn/completed", turn=dict({"id": "turn", "status": status, "error": None}, **more))

def say(text, key="msg"):
    item("started", type="agentMessage", id=key, text="", phase="final_answer")
    for part in (text[:3], text[3:]):
        tell("item/agentMessage/delta", turnId="turn", itemId=key, delta=part)
    item("completed", type="agentMessage", id=key, text=text, phase="final_answer")

n = 0
while True:
    msg = read()
    note(msg)
    method = msg.get("method")
    if method == "initialize":
        answer(msg, {"userAgent": "x"})
    elif method == "account/read":
        signed_out = "--signed-out" in sys.argv
        answer(msg, {"account": None if signed_out else {"type": "chatgpt"},
                     "requiresOpenaiAuth": True})
    elif method == "skills/list":
        answer(msg, {"data": [{"cwd": ".", "skills": [
            {"name": "xefm", "enabled": True, "path": "/s/xefm/SKILL.md", "scope": "user",
             "description": "Work with XeFM"},
            {"name": "off", "enabled": False, "path": "/s/off", "scope": "user"}]}]})
    elif method == "model/list":
        answer(msg, {"data": [
            {"model": "gpt-a", "displayName": "GPT A", "hidden": False,
             "supportedReasoningEfforts": [{"reasoningEffort": "low"},
                                           {"reasoningEffort": "high"}]},
            {"model": "gpt-b", "displayName": "GPT B", "hidden": False,
             "supportedReasoningEfforts": [{"reasoningEffort": "max"}]},
            {"model": "gpt-h", "hidden": True}]})
    elif method in ("thread/start", "thread/resume"):
        answer(msg, {"thread": {"id": T}, "model": "gpt-a", "approvalPolicy": "on-request",
                     "sandbox": {"type": "readOnly", "networkAccess": False}})
    elif method == "thread/compact/start":
        answer(msg, {})
        tell("turn/started", turn={"id": "c"})
        item("completed", type="contextCompaction", id="cc")
        finish()
    elif method == "turn/interrupt":
        answer(msg, {})
        finish("interrupted")
    elif method == "turn/start":
        n += 1
        answer(msg, {"turn": {"id": "turn", "status": "inProgress"}})
        tell("turn/started", turn={"id": "turn"})
        text = msg["params"]["input"][-1]["text"]
        if "hang" in text:
            item("started", type="commandExecution", id="h", command="sleep 9",
                 status="inProgress")
            continue
        if "run" in text:
            command = text.split("run ", 1)[1]
            shell = "/bin/bash -lc '%s'" % command
            item("started", type="commandExecution", id=f"e{n}", command=shell,
                 status="inProgress")
            got = ask(n, "item/commandExecution/requestApproval", {
                "threadId": T, "turnId": "turn", "itemId": f"e{n}", "command": shell,
                "reason": "May I?", "availableDecisions": ["accept", "acceptForSession", "cancel"]})
            ok = got["decision"].startswith("accept")
            if ok:
                tell("item/commandExecution/outputDelta", turnId="turn", itemId=f"e{n}",
                     delta="part")
            item("completed", type="commandExecution", id=f"e{n}", command=shell,
                 status="completed" if ok else "declined",
                 aggregatedOutput="whole\n" if ok else None, exitCode=0 if ok else None)
            say(got["decision"], f"m{n}")
        elif "edit" in text:
            changes = [{"path": "/w/note.txt", "kind": {"type": "update", "move_path": None},
                        "diff": "@@ -1,3 +1,3 @@\n alpha\n-beta\n+BETA\n gamma\n"},
                       {"path": "/w/new.txt", "kind": {"type": "add"}, "diff": "hi\n"}]
            item("started", type="fileChange", id="f", changes=changes, status="inProgress")
            got = ask(n, "item/fileChange/requestApproval", {
                "threadId": T, "turnId": "turn", "itemId": "f"})
            item("completed", type="fileChange", id="f", changes=changes, status="completed")
        elif "ask me" in text:
            got = ask(n, "item/tool/requestUserInput", {
                "threadId": T, "turnId": "turn", "itemId": "q", "questions": [
                    {"id": "color", "header": "Color", "question": "Red or blue?",
                     "isOther": True, "isSecret": False,
                     "options": [{"label": "Red", "description": "r"},
                                 {"label": "Blue", "description": "b"}]}]})
            say(json.dumps(got), "a")
        elif "agent" in text:
            item("started", type="subAgentActivity", id="sa", kind="started",
                 agentThreadId="T2", agentPath="/root/host")
            for step in ("started", "completed"):
                out({"method": "item/" + step, "params": {"threadId": "T2", "item": {
                    "type": "commandExecution", "id": "x", "command": "bash -lc hostname",
                    "status": "completed", "aggregatedOutput": "box", "exitCode": 0}}})
            out({"method": "turn/completed", "params": {"threadId": "T2", "turn": {
                "id": "t2", "status": "completed"}}})
            item("completed", type="subAgentActivity", id="sb", kind="completed",
                 agentThreadId="T2", agentPath="/root/host")
        elif "fail" in text:
            finish("failed", error={"message": "Usage limit reached"})
            continue
        elif msg["params"].get("collaborationMode", {}).get("mode") == "plan":
            item("started", type="plan", id="p", text="")
            item("completed", type="plan", id="p", text="Do it")
        else:
            tell("turn/plan/updated", turnId="turn", plan=[
                {"step": "One", "status": "completed"}, {"step": "Two", "status": "inProgress"}])
            say("Hello **there**", f"m{n}")
        tell("thread/tokenUsage/updated", turnId="turn", tokenUsage={
            "last": {"totalTokens": 1000}, "modelContextWindow": 10000})
        finish()
'''

FAKE_ACP = COMMON + r'''
S = "session-1"
OPTIONS = [{"id": "model", "category": "model", "type": "select", "currentValue": "fast",
            "options": [{"value": "fast", "name": "Fast One"}, {"value": "deep", "name": "Deep"}]},
           {"id": "thought_level", "category": "thought_level", "type": "select",
            "currentValue": "high", "options": [{"value": "low", "name": "Low"},
                                                {"value": "high", "name": "High"}]}]

def update(what, **data):
    out({"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": S, "update": dict(data, sessionUpdate=what)}})

def chunk(text, what="agent_message_chunk", **more):
    update(what, content={"type": "text", "text": text}, **more)

def session():
    return {"sessionId": S, "configOptions": OPTIONS, "modes": {
        "currentModeId": "auto" if "--auto" in sys.argv else "default", "availableModes": [
            {"id": "default", "name": "Default"}, {"id": "accept-edits", "name": "Accept edits"},
            {"id": "auto", "name": "Auto"}, {"id": "plan", "name": "Plan"}]}}

prompt = None
while True:
    msg = read()
    note(msg)
    method = msg.get("method")
    if method == "initialize":
        answer(msg, {"protocolVersion": 1, "agentCapabilities": {
            "loadSession": True, "sessionCapabilities":
            {"resume": {}} if "--resume" in sys.argv else {}}})
    elif method == "session/new":
        if "--signed-out" in sys.argv:
            out({"jsonrpc": "2.0", "id": msg["id"], "error": {
                "code": -32000, "message": "Authentication required"}})
            continue
        answer(msg, session())
        update("available_commands_update", availableCommands=[
            {"name": "compact", "description": "Summarize", "input": {"hint": "focus"}}])
    elif method == "session/resume":
        answer(msg, session())
    elif method == "session/load":
        chunk("played back", "user_message_chunk")
        chunk("played back")
        answer(msg, session())
    elif method in ("session/set_mode", "session/set_config_option"):
        result = {}
        if method.endswith("option"):
            for o in OPTIONS:
                if o["id"] == msg["params"]["configId"]:
                    o["currentValue"] = msg["params"]["value"]
            result = {"configOptions": OPTIONS}
        answer(msg, result)
    elif method == "session/cancel":
        if prompt is not None:
            answer(prompt, {"stopReason": "cancelled"})
    elif method == "session/prompt":
        prompt = msg
        text = msg["params"]["prompt"][0]["text"]
        if "hang" in text:
            update("tool_call", toolCallId="h", kind="execute", title="sleep 9",
                   status="in_progress", rawInput={"command": "sleep 9"})
            continue
        if text.startswith("/"):
            chunk("Context Usage\n\n  17k *used*")
        elif "run" in text:
            command = text.split("run ", 1)[1]
            update("tool_call", toolCallId="r", kind="execute", title="Run it", status="pending",
                   rawInput={"command": command, "description": "Run it"})
            got = ask(7, "session/request_permission", {"sessionId": S, "toolCall": {
                "toolCallId": "r", "title": command, "kind": "execute", "status": "pending",
                "rawInput": {"command": command}}, "options": [
                {"optionId": "once", "kind": "allow_once", "name": "Allow once"},
                {"optionId": "always", "kind": "allow_always", "name": "Always"},
                {"optionId": "no", "kind": "reject_once", "name": "Deny"}]})
            if got["outcome"].get("optionId") in ("once", "always"):
                update("tool_call_update", toolCallId="r", content=[
                    {"type": "content", "content": {"type": "text", "text": "par"}}])
                done = "box\n<shellId: 0 completed with exit code 0>"
                update("tool_call_update", toolCallId="r", status="completed", content=[
                    {"type": "content", "content": {"type": "text", "text": done}}])
            else:
                update("tool_call_update", toolCallId="r", status="failed")
            chunk(json.dumps(got), messageId="m")
        elif "edit" in text:
            update("tool_call", toolCallId="e", kind="edit", title="File note.txt",
                   status="in_progress", rawInput={"Path": "/w/note.txt"},
                   locations=[{"path": "/w/note.txt"}])
            update("tool_call_update", toolCallId="e", status="completed", kind="edit",
                   rawInput={"Path": "/w/note.txt"}, rawOutput={}, content=[
                       {"type": "diff", "path": "/w/note.txt",
                        "oldText": "alpha\nbeta\ngamma\n", "newText": "alpha\nBETA\ngamma\n"}])
        elif "ask me" in text:
            update("tool_call", toolCallId="q", kind="other", title="Run ask_question",
                   name="ask_question", status="in_progress", rawInput={"questions": []})
            got = ask(8, "elicitation/create", {
                "sessionId": S, "toolCallId": "q", "mode": "form", "message": "A question.",
                "requestedSchema": {"type": "object", "properties": {
                    "q1": {"type": "string", "title": "Which color?", "oneOf": [
                        {"const": "1", "title": "Red"}, {"const": "2", "title": "Blue"}]},
                    "q1_other": {"type": "string", "title": "Other"},
                    "q2": {"type": "array", "title": "Which sizes?", "items": {
                        "enum": ["S", "M", "L"]}}}}})
            update("tool_call_update", toolCallId="q", kind="other", title="Run ask_question",
                   name="ask_question", status="completed")
            chunk(json.dumps(got))
        else:
            chunk("Let me think", "agent_thought_chunk")
            update("plan", entries=[{"content": "One", "status": "in_progress"}])
            update("tool_call", toolCallId="t", kind="read", title="Viewing note.txt",
                   status="pending", rawInput={"path": "/w/note.txt"})
            update("tool_call_update", toolCallId="t", status="completed",
                   rawOutput={"content": "alpha\nbeta\n"})
            chunk("Hello ", messageId="m1")
            chunk("**there**", messageId="m1")
            chunk("Second", messageId="m2")
            update("usage_update", used=500, size=1000)
        answer(prompt, {"stopReason": "end_turn"})
        prompt = None
'''


class _Agent:
    """A drawn session of a stand-in, in a real view."""

    def __init__(self, tmp_path, source, protocol, *args):
        from puikit import Panel
        from puikit.backends.memory_backend import MemoryBackend
        from xefm.agent_chat_view import ChatView
        self.path = tmp_path / "fake_agent.py"
        self.path.write_text(textwrap.dedent(source), encoding="utf-8")
        self.posts, self.asked = _Posts(), []
        self.view = ChatView(
            [sys.executable, str(self.path), *args], cwd=str(tmp_path), env=dict(os.environ),
            name="Agent", post=self.posts, ask=lambda view, perm: self.asked.append(perm),
            on_close_request=lambda v: None, on_hide=lambda v: None, protocol=protocol)
        self.panel = Panel(MemoryBackend(width=100, height=40))
        self.panel.push_layer(self.view, z=10, hints={"x": 0, "y": 0, "w": 100, "h": 40})
        self.view.start(self.panel)

    @property
    def conv(self):
        return self.view.conversation

    def until(self, cond):
        self.posts.until(cond)

    def idle(self):
        self.until(lambda: self.conv.state == C.IDLE)
        return self

    def say(self, text, *, asks=False):
        self.view._submit(text)
        if asks:
            n = len(self.asked)
            self.until(lambda: len(self.asked) > n)
        else:
            self.idle()
        return self

    def sent(self, method):
        """The parameters of each ``method`` the stand-in received."""
        import json
        lines = (self.path.parent / (self.path.name + ".log")).read_text("utf-8").splitlines()
        return [m.get("params") for m in map(json.loads, lines) if m.get("method") == method]

    @property
    def last_text(self):
        return [i for i in self.conv.items if i.kind == "text"][-1].text

    def tools(self, name):
        return [i for i in self.conv.items if i.kind == "tool" and i.name == name]


@pytest.fixture
def start(tmp_path):
    made = []

    def run(source, protocol, *args):
        made.append(_Agent(tmp_path, source, protocol, *args))
        return made[-1]
    yield run
    for agent in made:
        agent.view.close()


def _refuse(command):
    return "XeFM declined it" if command.startswith("rm ") else None


@pytest.fixture
def codex(start):
    return start(FAKE_CODEX, agent_codex.CodexProtocol(
        refuse=_refuse, instructions="The rules", skills_root="/skills")).idle()


@pytest.fixture
def acp(start):
    return start(FAKE_ACP, agent_acp.AcpProtocol(
        refuse=_refuse, agent="Agent", login="agent login", plain_commands=True)).idle()


# --- Codex --------------------------------------------------------------------------

def test_codex_opens_with_the_rules_and_the_skill(codex):
    [params] = codex.sent("thread/start")
    assert params["developerInstructions"] == "The rules"
    assert "sandbox" not in params and "approvalPolicy" not in params  # the user's own
    assert codex.sent("skills/extraRoots/set") == [{"extraRoots": ["/skills"]}]
    conv = codex.conv
    assert conv.model == "gpt-a" and conv.modes == ("default", "acceptEdits", "plan")
    assert [m["value"] for m in conv.models] == ["gpt-a", "gpt-b"]
    assert [c["name"] for c in conv.commands] == ["compact", "xefm"]


def test_a_codex_reply_its_plan_and_its_context(codex):
    codex.say("hello")
    assert codex.last_text == "Hello **there**" and not codex.conv.items[-1].open
    assert codex.conv.context_label() == "10% context"
    assert [t["status"] for t in codex.conv.todos()] == ["completed", "in_progress"]
    codex.panel.render()
    text = _screen_text(codex.panel)
    assert "To do · 1/2 done" in text and "gpt-a" in text
    assert '{"todos"' not in C.to_markdown(codex.conv.items)


@pytest.mark.parametrize("response, decision", [
    ("allow", "accept"), ("always", "acceptForSession"), ("deny", "decline")])
def test_codex_asks_before_a_command(codex, response, decision):
    codex.say("run ls -l", asks=True)
    [perm] = codex.asked
    assert codex.conv.state == C.ASKING
    assert perm.tool == "Shell" and perm.input == {"command": "ls -l"}
    assert perm.description == "May I?" and perm.suggestions
    codex.view.answer(perm, C.deny() if response == "deny"
                      else C.allow(perm, always=response == "always"))
    codex.idle()
    [step] = codex.tools("Shell")
    assert codex.last_text == decision and not step.open
    if response == "deny":
        assert step.denied and "✗ declined" in C.to_markdown([step])
    else:
        assert step.result == "whole\n" and "$ ls -l" in C.to_markdown([step])


def test_a_command_a_restricted_session_may_not_run_is_declined_unasked(codex):
    codex.say("run rm x")
    assert codex.asked == [] and codex.last_text == "decline"
    assert codex.tools("Shell")[0].denied
    assert any(i.kind == "notice" and "XeFM declined it" in i.text for i in codex.conv.items)


def test_a_codex_change_is_an_edit_per_file(codex):
    codex.say("edit it", asks=True)
    [perm] = codex.asked
    assert "+BETA" in perm.patch and "+hi" in perm.patch
    codex.view.answer(perm, C.allow(perm))
    codex.idle()
    [edit], [write] = codex.tools("Edit"), codex.tools("Write")
    md = C.to_markdown(codex.conv.items)
    assert "-beta\n+BETA" in md and "[open diff](xefm-agent:diff/1)" in md
    # The answer does not write over what the edit was.
    assert C.edit_before(edit, "alpha\nBETA\ngamma\n") == "alpha\nbeta\ngamma\n"
    assert C.edit_before(edit, "changed since") is None
    assert C.edit_before(write, "hi\n") == ""


def test_codex_asks_the_user_a_question(codex):
    codex.say("ask me", asks=True)
    [perm] = codex.asked
    assert perm.tool == C.ASK_USER_TOOL
    [q] = C.questions(perm)
    assert q["question"] == "Red or blue?" and [o["label"] for o in q["options"]] == [
        "Red", "Blue"]
    perm.picked["Red or blue?"] = ["Blue"]
    codex.view.answer(perm, C.allow(perm, updated_input=dict(
        perm.input, answers={"Red or blue?": "Blue"})))
    codex.idle()
    assert codex.last_text == '{"answers": {"color": {"answers": ["Blue"]}}}'
    assert "→ **Blue**" in C.to_markdown(codex.conv.items)


def test_a_codex_plan_is_approved_and_carried_out(codex):
    codex.panel.dispatch_event(_key("tab", None, ("shift",)))
    codex.panel.dispatch_event(_key("tab", None, ("shift",)))
    assert codex.conv.permission_mode == "plan"
    codex.panel.render()
    assert "plan mode" in _screen_text(codex.panel)
    codex.say("think about it", asks=True)
    [perm] = codex.asked
    assert perm.tool == C.PLAN_TOOL and perm.input["plan"] == "Do it"
    codex.view.approve_plan(perm, "acceptEdits")
    codex.idle()
    assert codex.conv.permission_mode == "acceptEdits"
    assert [i.text for i in codex.conv.items if i.kind == "user"][-1] == agent_codex.IMPLEMENT
    plan, implement = codex.sent("turn/start")
    assert plan["collaborationMode"]["mode"] == "plan"
    assert plan["sandboxPolicy"]["type"] == "readOnly"
    assert implement["collaborationMode"]["mode"] == "default"
    assert implement["sandboxPolicy"]["type"] == "workspaceWrite"


def test_keep_planning_leaves_codex_waiting(codex):
    codex.view.set_mode("plan")
    codex.say("think about it", asks=True)
    codex.view.answer(codex.asked[0], C.deny("no"))
    assert codex.conv.state == C.IDLE and len(codex.sent("turn/start")) == 1


def test_escape_stops_codex_and_the_next_message_goes_out(codex):
    codex.view._submit("hang")
    codex.until(lambda: codex.tools("Shell"))
    codex.view._submit("hello")  # waits for the turn to end
    assert codex.conv.pending_turns == 2
    codex.view.interrupt()
    codex.idle()
    [step] = codex.tools("Shell")
    assert step.is_error and not step.open  # cut short, not done
    assert any(i.text == "Interrupted" for i in codex.conv.items)
    assert codex.last_text == "Hello **there**"


def test_a_codex_turn_that_failed_says_why(codex):
    codex.say("fail")
    assert codex.conv.items[-1].kind == "error"
    assert "Usage limit reached" in codex.conv.items[-1].text


def test_a_codex_subagents_steps_nest_under_it(codex):
    codex.say("agent")
    [agent] = codex.tools("Agent")
    [step] = agent.children
    assert step.input == {"command": "hostname"} and step.result == "box"
    assert not agent.open and "- **Shell** `hostname` ✓" in C.to_markdown(codex.conv.items)


def test_codex_model_effort_skill_and_compact(codex):
    codex.view._submit("/model nope")
    assert "No such model" in codex.conv.items[-1].text
    codex.view._submit("/model gpt-b")
    assert codex.conv.model == "gpt-b" and codex.conv.efforts == ("max",)
    codex.view._submit("/effort low")
    assert "No such effort" in codex.conv.items[-1].text
    _type(codex.panel, "/eff")
    assert codex.view.menu.items[0][0] == "/effort <max>"
    codex.view.input.set_text("")
    codex.view._submit("/effort max")
    codex.say("/xefm do this")
    [turn] = codex.sent("turn/start")
    assert turn["model"] == "gpt-b" and turn["effort"] == "max"
    assert turn["input"][0] == {"type": "skill", "name": "xefm", "path": "/s/xefm/SKILL.md"}
    assert turn["input"][1]["text"] == "$xefm do this"
    codex.say("again")
    assert "model" not in codex.sent("turn/start")[-1]  # the thread keeps it
    codex.say("/compact")
    assert any("compacted" in i.text for i in codex.conv.items if i.kind == "notice")
    assert len(codex.sent("turn/start")) == 2


def test_codex_goes_back_to_its_thread_in_a_new_process(codex):
    codex.say("hello")
    codex.view.set_mode("acceptEdits")
    codex.view.set_model("gpt-b")
    codex.view.client._proc.kill()
    codex.until(lambda: codex.conv.state == C.EXITED)
    items = len(codex.conv.items)
    codex.say("hello again")
    [params] = codex.sent("thread/resume")
    assert params["threadId"] == "thread-1" and len(codex.conv.items) > items
    turn = codex.sent("turn/start")[-1]
    assert turn["model"] == "gpt-b" and turn["sandboxPolicy"]["type"] == "workspaceWrite"
    codex.view._submit("/clear")
    assert codex.conv.items == [] and codex.conv.model_choice == "gpt-b"
    codex.until(lambda: len(codex.sent("thread/start")) == 2)


def test_a_codex_not_signed_in_says_how(start):
    codex = start(FAKE_CODEX, agent_codex.CodexProtocol(), "--signed-out")
    codex.until(lambda: codex.conv.state == C.EXITED)
    assert "codex login" in codex.conv.items[0].text


def test_the_app_server_gets_options_as_configuration():
    assert agent_codex.app_server_argv(
        ["codex", "-m", "x", "--sandbox=read-only", "-c", "a=1", "--enable", "f"]) == [
        "codex", "-c", "model=x", "-c", "sandbox_mode=read-only", "-c", "a=1", "--enable", "f",
        "app-server"]


@pytest.mark.parametrize("command, expected", [
    ("/bin/bash -lc 'ls -l | wc'", "ls -l | wc"),
    ('"C:\\\\Program Files\\\\pwsh.exe" -Command \'Get-Content a.txt\'', "Get-Content a.txt"),
    ("powershell.exe -NoProfile -Command dir", "dir"),
    ("git -c x=y status", "git -c x=y status"),
    ("echo 'open", "echo 'open")])
def test_the_shell_around_a_command_is_left_out(command, expected):
    assert agent_codex.shell_command(command) == expected


def test_codex_grants_access_and_declines_a_form_it_cannot_show(codex):
    sent = []
    client = codex.view.client
    client.reply = lambda rid, result: sent.append(result)
    wanted = {"network": {"enabled": True}, "fileSystem": None}
    perm = client.handle({"id": 5, "method": "item/permissions/requestApproval", "params": {
        "threadId": "thread-1", "itemId": "i", "permissions": wanted}})
    codex.view.answer(perm, C.allow(perm, always=True))
    assert sent[-1] == {"permissions": {"network": {"enabled": True}}, "scope": "session"}
    tool = {"mode": "form", "serverName": "srv", "message": "Run it?",
            "requestedSchema": {"type": "object", "properties": {}}}
    perm = client.handle({"id": 6, "method": "mcpServer/elicitation/request", "params": tool})
    codex.view.answer(perm, C.allow(perm))
    assert sent[-1]["action"] == "accept"
    form = dict(tool, requestedSchema={"properties": {"x": {"type": "string"}}})
    assert client.handle({"id": 7, "method": "mcpServer/elicitation/request",
                          "params": form}) is None
    assert sent[-1]["action"] == "decline" and "cannot show" in codex.conv.items[-1].text


# --- ACP (Copilot, Antigravity) --------------------------------------------------------

def test_an_acp_session_offers_its_modes_models_and_commands(acp):
    conv = acp.conv
    # Modes that run tools unasked are left out of Shift+Tab.
    assert conv.modes == ("default", "accept-edits", "plan")
    assert conv.model == "Fast One" and conv.efforts == ("low", "high")
    assert [m["value"] for m in conv.models] == ["fast", "deep"]
    acp.until(lambda: conv.commands)
    assert conv.commands == [{"name": "compact", "description": "Summarize",
                              "argumentHint": "focus"}]
    acp.panel.dispatch_event(_key("tab", None, ("shift",)))
    assert conv.permission_mode == "accept-edits"
    acp.panel.render()
    assert "accept edits" in _screen_text(acp.panel)
    acp.view._submit("/model deep")
    acp.until(lambda: conv.model == "Deep")
    assert conv.model_choice == "deep"


def test_an_acp_reply_comes_in_chunks(acp):
    acp.say("hello")
    kinds = [(i.kind, i.text) for i in acp.conv.items if i.kind in ("text", "thinking")]
    assert kinds == [("thinking", "Let me think"), ("text", "Hello **there**"),
                     ("text", "Second")]
    [read] = acp.tools("Read")
    assert read.input == {"file_path": "/w/note.txt"} and read.result == "alpha\nbeta\n"
    assert acp.conv.todos()[0]["content"] == "One"
    assert acp.conv.context_label() == "50% context"
    assert not any(i.open for i in acp.conv.items)


@pytest.mark.parametrize("response, option", [
    ("allow", "once"), ("always", "always"), ("deny", "no")])
def test_acp_asks_before_a_command(acp, response, option):
    acp.say("run hostname", asks=True)
    [perm] = acp.asked
    assert perm.tool == "Shell" and perm.input["command"] == "hostname" and perm.suggestions
    acp.view.answer(perm, C.deny() if response == "deny"
                    else C.allow(perm, always=response == "always"))
    acp.idle()
    assert f'"optionId": "{option}"' in acp.last_text
    [step] = acp.tools("Shell")
    assert not step.open and step.input["description"] == "Run it"
    if response == "deny":
        assert step.denied
    else:
        assert step.result == "box"  # without what Copilot puts after it


def test_acp_declines_unasked_what_a_restricted_session_may_not_run(acp):
    acp.say("run rm x")
    assert acp.asked == [] and '"optionId": "no"' in acp.last_text
    assert acp.tools("Shell")[0].denied


def test_an_acp_edit_shows_its_changed_lines(acp):
    acp.say("edit it")
    [edit] = acp.tools("Edit")
    assert edit.patch.endswith(" alpha\n-beta\n+BETA\n gamma")
    assert C.edit_before(edit, "alpha\nBETA\ngamma\n") == "alpha\nbeta\ngamma\n"
    assert "[open diff](xefm-agent:diff/1)" in C.to_markdown(acp.conv.items)


def test_an_acp_form_is_asked_as_questions(acp):
    acp.say("ask me", asks=True)
    [perm] = acp.asked
    color, sizes = C.questions(perm)
    assert color["question"] == "Which color?" and not color["multiSelect"]
    assert sizes["multiSelect"] and [o["label"] for o in sizes["options"]] == ["S", "M", "L"]
    perm.picked.update({"Which color?": ["Green"], "Which sizes?": ["S", "L"]})
    acp.view.answer(perm, C.allow(perm, updated_input=dict(perm.input, answers={
        "Which color?": "Green", "Which sizes?": "S, L"})))
    acp.idle()
    # A typed answer goes into the field made for it.
    assert acp.last_text == ('{"action": "accept", "content": '
                             '{"q1_other": "Green", "q2": ["S", "L"]}}')
    md = C.to_markdown(acp.conv.items)
    assert "Which color?  \n→ **Green**" in md and "ask_question" not in md


def test_a_picked_row_is_sent_as_its_value():
    field = {"choices": [("1", "Red"), ("2", "Blue")], "many": False, "type": "string"}
    assert agent_acp._form_value(field, ["Blue"]) == ("2", "")
    assert agent_acp._form_value({"choices": [], "many": False, "type": "integer"},
                                 ["4"]) == (4, "")
    assert agent_acp._form_value({"choices": [(True, "Yes"), (False, "No")], "many": False,
                                  "type": "boolean"}, ["No"]) == (False, "")


def test_a_commands_reply_is_plain_where_the_agent_writes_plain(acp):
    acp.say("/context")
    assert acp.conv.items[-1].plain
    acp.say("hello")
    assert not acp.conv.items[-1].plain


def test_escape_stops_an_acp_turn(acp):
    acp.view._submit("hang")
    acp.until(lambda: acp.tools("Shell"))
    acp.view.interrupt()
    acp.idle()
    assert any(i.text == "Interrupted" and i.kind == "notice" for i in acp.conv.items)
    assert acp.tools("Shell")[0].is_error


def test_escape_while_acp_asks_answers_it_cancelled(acp):
    acp.say("run hostname", asks=True)
    acp.view.interrupt()
    acp.idle()
    assert '"outcome": "cancelled"' in acp.last_text
    # The dialog may still be up: its answer goes nowhere.
    acp.view.answer(acp.asked[0], C.allow(acp.asked[0]))
    assert acp.conv.state == C.IDLE


@pytest.mark.parametrize("args, method", [((), "session/load"),
                                          (("--resume",), "session/resume")])
def test_an_acp_agent_goes_back_to_its_session(start, args, method):
    acp = start(FAKE_ACP, agent_acp.AcpProtocol(agent="Agent"), *args).idle()
    acp.say("hello")
    acp.view.set_mode("plan")
    acp.view._submit("/effort low")
    acp.view.client._proc.kill()
    acp.until(lambda: acp.conv.state == C.EXITED)
    acp.say("hello again")
    assert acp.sent(method)[0]["sessionId"] == "session-1"
    assert not any("played back" in i.text for i in acp.conv.items)  # it is on screen
    assert acp.conv.permission_mode == "plan"
    assert acp.sent("session/set_config_option")[-1]["value"] == "low"


def test_an_acp_agent_not_signed_in_says_how(start):
    acp = start(FAKE_ACP, agent_acp.AcpProtocol(agent="Agent", login="agent login"),
                "--signed-out")
    acp.until(lambda: acp.conv.state == C.EXITED)
    assert "agent login" in acp.conv.items[0].text


@pytest.mark.parametrize("restrict, mode", [(True, "default"), (False, "auto")])
def test_a_restricted_session_does_not_start_in_a_mode_that_does_not_ask(start, restrict, mode):
    acp = start(FAKE_ACP, agent_acp.AcpProtocol(agent="Agent", restrict=restrict),
                "--auto").idle()
    assert acp.conv.permission_mode == mode


def test_what_antigravitys_command_asked_for_is_set_in_the_session(start):
    acp = start(FAKE_ACP, agent_acp.AcpProtocol(agent="Agent", first={
        "mode": "plan", "model": "deep", "effort": "low"})).idle()
    acp.until(lambda: acp.conv.model == "Deep")
    assert acp.conv.permission_mode == "plan"


def test_what_antigravity_puts_before_a_commands_output_is_left_out():
    item = C.Item("tool", name="Tool", open=True)
    agent_acp._fold_tool(item, {
        "kind": "execute", "title": "ls", "status": "completed",
        "rawInput": {"CommandLine": "ls", "toolSummary": "List"},
        "rawOutput": {"output": "x", "exit_code": 1}, "content": [
            {"type": "content", "content": {"type": "text", "text": (
                "Created At: 2026-11-23T22:47:40-08:00\nCompleted At: 2026-11-23T22:47:40-08:00\n"
                "Command exited with code 1.\n\nCommand output:\nno such file\n")}}]})
    assert item.name == "Shell" and item.input == {"command": "ls", "description": "List"}
    assert item.result == "no such file\n" and item.is_error


def test_a_request_xefm_does_not_offer_is_refused(acp):
    sent = []
    acp.view.client._write = lambda obj: sent.append(obj) or True
    assert acp.view.client.handle({"id": 3, "method": "fs/read_text_file", "params": {}}) is None
    assert sent[0]["error"]["code"] == agent_rpc.METHOD_NOT_FOUND


# --- what each preset is handed ----------------------------------------------------------

def _entry(preset, command, **more):
    return agents.normalize({"name": "A", "command": command, "preset": preset, **more})


@pytest.mark.parametrize("preset", agents.PRESETS)
def test_every_preset_is_drawn_unless_the_entry_says_terminal(preset):
    assert agents.drawn(_entry(preset, ["x"]))
    assert not agents.drawn(_entry(preset, ["x"], terminal=True))


def test_codex_is_handed_the_rules_as_its_session_opens(tmp_path):
    entry = _entry("codex", ["codex", "-m", "x"])
    values = agents.prepare(SimpleNamespace(AGENT_RULES="Be kind."), entry, root=tmp_path,
                            version="t")
    assert agents.chat_argv(entry, values) == ["codex", "-c", "model=x", "app-server"]
    options = agents.protocol(entry, values).options
    assert "Be kind." in options["instructions"] and "SKILL.md" in options["instructions"]
    assert "XeFM draws this conversation" in options["instructions"]
    assert options["skills_root"] == values["{skills_dir}"]


def test_copilot_is_handed_the_skill_the_rules_and_the_denied_commands(tmp_path):
    entry = _entry("copilot", ["copilot", "--model", "x"])
    values = agents.prepare(SimpleNamespace(), entry, root=tmp_path, version="t")
    argv = agents.chat_argv(entry, values)
    assert argv[:6] == ["copilot", "--model", "x", "--acp", "--plugin-dir",
                        values["{plugin_dir}"]]
    assert "--deny-tool=shell(rm)" in argv and "-i" not in argv
    folder = agents.session_env(entry, values, {})[agents.COPILOT_INSTRUCTIONS_ENV]
    with open(os.path.join(folder, "xefm.instructions.md"), encoding="utf-8") as f:
        assert "XeFM draws this conversation" in f.read()
    # A terminal session's rules are another file.
    other = agents.prepare(SimpleNamespace(), dict(entry, terminal=True), root=tmp_path,
                           version="t")
    assert other["instructions_dir"] != values["instructions_dir"]


def test_antigravity_is_handed_a_workspace_and_its_options_later(tmp_path):
    entry = _entry("antigravity", ["agy", "--model", "m", "--mode=plan", "--sandbox"])
    values = agents.prepare(SimpleNamespace(), entry, root=tmp_path, version="t")
    assert agents.chat_argv(entry, values) == [
        "agy", "--sandbox", "acp", "--add-dir", values["workspace_dir"]]
    with open(os.path.join(values["workspace_dir"], "AGENTS.md"), encoding="utf-8") as f:
        assert "XeFM draws this conversation" in f.read()
    assert agents.protocol(entry, values).options["first"] == {"model": "m", "mode": "plan"}


@pytest.mark.parametrize("command, refused", [
    ("rm -rf x", True), ("/bin/rm x", True), ("Remove-Item x", True), ("cd a && RM b", True),
    ("ls | xargs ls; git clean -fd", True), ("xefmctl delete x", True),
    ("git status", False), ("xefmctl trash --wait x", False), ("echo rm", False),
    ("rmx", False), ("npm rm", False)])
def test_the_commands_a_restricted_session_may_not_run(command, refused):
    refuse = agents.refusal(_entry("codex", ["codex"]))
    assert bool(refuse(command)) is refused


def test_an_unrestricted_entry_refuses_nothing_and_settings_replace_the_list():
    assert agents.refusal(_entry("codex", ["codex"], restrict=False)) is None
    refuse = agents.refusal(_entry("antigravity", ["agy"], settings={
        "permissions": {"deny": ["command(sudo)", "read_file(x)"]}}))
    assert refuse("sudo ls") and refuse("rm x") is None


def test_hunks_undo_to_the_file_before():
    old = "".join(f"{n}\n" for n in range(30))
    new = old.replace("3\n4\n", "3\nfour\n", 1).replace("20\n", "twenty\nmore\n", 1)
    item = C.Item("tool", name="Edit", input={
        "edits": agent_rpc.hunk_edits(agent_rpc.unified_patch(old, new))})
    assert len(item.input["edits"]) == 2
    assert C.edit_before(item, new) == old
