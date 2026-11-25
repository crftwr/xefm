"""A stand-in model: a small OpenAI-style server that answers an agent CLI's n-th
request of a turn with the n-th scripted tool call, then "done". With it a real
CLI takes a real turn - its sandbox, its MCP client, its approvals - with no
account, no quota and no model. test_agent_cli.py's."""

import http.server
import json
import threading
import time

#: The names the agents give the tool that runs a shell command.
SHELLS = ("exec_command", "shell_command", "shell", "bash", "run_command", "powershell")


def _offered(tools):
    """Every tool's name, namespace and parameters, namespaces flattened."""
    for tool in tools or []:
        if tool.get("type") == "namespace":
            for inner in tool.get("tools", []):
                yield inner.get("name"), tool.get("name"), inner.get("parameters") or {}
        else:
            spec = tool.get("function") or tool
            yield spec.get("name") or tool.get("type"), None, spec.get("parameters") or {}


class Model:
    """``steps``: ``("shell", command)`` or ``("tool", end of a name, arguments)``.
    ``results`` is what the CLI sent back for each step."""

    def __init__(self, steps):
        self.steps, self.results, self.offered = list(steps), {}, []
        self.requests = 0
        me = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, kind, body):
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send("application/json", json.dumps(
                    {"models": [], "data": [{"id": "standin", "object": "model"}]}).encode())

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                me.requests += 1
                if self.path.rstrip("/").endswith("chat/completions"):
                    body = me.chat(req)
                    if not req.get("stream"):
                        return self._send("application/json", json.dumps(body[0]).encode())
                    text = body[1]
                else:
                    text = me.responses(req)
                return self._send("text/event-stream", text.encode())

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def _pick(self, tools):
        """The next call: ``(name, namespace, arguments)``, or None at the end."""
        if not tools or len(self.results) >= len(self.steps):
            return None
        offered = list(_offered(tools))
        self.offered = [n for n, _, _ in offered]
        kind, what, *given = self.steps[len(self.results)]
        if kind == "tool":
            for name, space, _ in offered:
                if name == what or name.endswith(("-" + what, "__" + what)):
                    return name, space, given[0]
            return f"missing_{what}", None, {}
        for name, space, params in offered:
            if name in SHELLS:
                props = params.get("properties") or {}
                key = "cmd" if "cmd" in props else "command"
                args = {key: what}
                if "yield_time_ms" in props:
                    args["yield_time_ms"] = 30000
                if "description" in props:
                    args["description"] = "check"
                return name, space, args
        return "missing_shell", None, {}

    def chat(self, req):
        tools = req.get("tools")
        if tools:
            for m in req["messages"]:
                if m.get("role") == "tool":
                    self.results[m.get("tool_call_id")] = _text(m.get("content"))
        pick = self._pick(tools)
        msg = {"role": "assistant", "content": "done"}
        if pick:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "index": 0, "id": f"call_{len(self.results)}", "type": "function",
                "function": {"name": pick[0], "arguments": json.dumps(pick[2])}}]}
        why = "tool_calls" if pick else "stop"
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        base = {"id": "c", "created": 0, "model": "standin"}
        whole = dict(base, object="chat.completion", usage=usage, choices=[
            {"index": 0, "message": msg, "finish_reason": why}])
        chunks = [dict(base, object="chat.completion.chunk", choices=[
                      {"index": 0, "delta": msg, "finish_reason": None}]),
                  dict(base, object="chat.completion.chunk", usage=usage, choices=[
                      {"index": 0, "delta": {}, "finish_reason": why}])]
        return whole, "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def responses(self, req):
        tools = list(req.get("tools") or [])
        for item in req.get("input") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "additional_tools":
                tools += item.get("tools") or []
            if str(item.get("type", "")).endswith("_call_output"):
                self.results[item.get("call_id")] = _text(item.get("output"))
        pick = self._pick(tools)
        if pick:
            n = len(self.results)
            item = {"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}",
                    "name": pick[0], "arguments": json.dumps(pick[2]), "status": "completed"}
            if pick[1]:
                item["namespace"] = pick[1]
        else:
            item = {"type": "message", "id": "m", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "done", "annotations": []}]}
        rid = f"resp_{time.time_ns()}"
        done = {"id": rid, "output": [item], "usage": {
            "input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0}}}
        events = [("response.created", {"response": {"id": rid}}),
                  ("response.output_item.added", {"output_index": 0, "item": item}),
                  ("response.output_item.done", {"output_index": 0, "item": item}),
                  ("response.completed", {"response": done})]
        return "".join(f"event: {kind}\ndata: {json.dumps({'type': kind, **body})}\n\n"
                       for kind, body in events)


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(v) for v in value)
    if isinstance(value, dict):
        return "\n".join(_text(v) for v in value.values())
    return ""
