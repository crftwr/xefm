"""A stand-in model: a small OpenAI-style server (and Anthropic-style, for Claude
Code: ``/v1/messages``) that answers an agent CLI's n-th
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
            yield (spec.get("name") or tool.get("type"), None,
                   spec.get("parameters") or spec.get("input_schema") or {})


class Model:
    """``steps``: ``("shell", command)``, ``("shell", command, more)`` - ``more``
    the shell tool's other arguments, those it takes - or ``("tool", end of a
    name, arguments)``.
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
                path = self.path.split("?")[0].rstrip("/")
                if path.endswith("/messages/count_tokens"):
                    return self._send("application/json", b'{"input_tokens": 1}')
                if path.endswith("/messages"):
                    whole, text = me.messages(req)
                    if not req.get("stream"):
                        return self._send("application/json", json.dumps(whole).encode())
                    return self._send("text/event-stream", text.encode())
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

    def _done(self):
        """How many steps have their result: a tool search is not a step."""
        return sum(1 for k in self.results if str(k).startswith("call_"))

    def _pick(self, tools):
        """The next call: ``(name, namespace, arguments, id)``, or None at the
        end. A step's id is ``call_<n>``."""
        n = self._done()
        if not tools or n >= len(self.steps):
            return None
        offered = list(_offered(tools))
        self.offered = [name for name, _, _ in offered]
        kind, what, *given = self.steps[n]
        if kind == "tool":
            for name, space, _ in offered:
                if name == what or name.endswith(("-" + what, "__" + what)):
                    return name, space, given[0], f"call_{n}"
            # Claude Code defers MCP tools until the model searches for them.
            search = f"search_{n}"
            if "ToolSearch" in self.offered and search not in self.results:
                return "ToolSearch", None, {"query": what, "max_results": 5}, search
            return f"missing_{what}", None, {}, f"call_{n}"
        for name, space, params in offered:
            if name and name.lower() in SHELLS:
                props = params.get("properties") or {}
                key = "cmd" if "cmd" in props else "command"
                args = {key: what}
                if "yield_time_ms" in props:
                    args["yield_time_ms"] = 30000
                if "description" in props:
                    args["description"] = "check"
                args.update({k: v for k, v in (given[0] if given else {}).items()
                             if k in props})
                return name, space, args, f"call_{n}"
        return "missing_shell", None, {}, f"call_{n}"

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
                "index": 0, "id": pick[3], "type": "function",
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

    def messages(self, req):
        """Anthropic's Messages API: the whole message, and its event stream."""
        tools = req.get("tools")
        for m in req.get("messages") or []:
            if m.get("role") == "user" and isinstance(m.get("content"), list):
                for block in m["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        self.results[block.get("tool_use_id")] = _text(block.get("content"))
        pick = self._pick(tools)
        if pick:
            block = {"type": "tool_use", "id": pick[3],
                     "name": pick[0], "input": pick[2]}
            start = dict(block, input={})
            delta = {"type": "input_json_delta", "partial_json": json.dumps(pick[2])}
        else:
            block = {"type": "text", "text": "done"}
            start, delta = {"type": "text", "text": ""}, {"type": "text_delta", "text": "done"}
        why = "tool_use" if pick else "end_turn"
        usage = {"input_tokens": 1, "output_tokens": 1}
        whole = {"id": f"msg_{time.time_ns()}", "type": "message", "role": "assistant",
                 "model": req.get("model") or "standin", "content": [block],
                 "stop_reason": why, "stop_sequence": None, "usage": usage}
        events = [("message_start", {"message": dict(whole, content=[], stop_reason=None)}),
                  ("content_block_start", {"index": 0, "content_block": start}),
                  ("content_block_delta", {"index": 0, "delta": delta}),
                  ("content_block_stop", {"index": 0}),
                  ("message_delta", {"delta": {"stop_reason": why, "stop_sequence": None},
                                     "usage": {"output_tokens": 1}}),
                  ("message_stop", {})]
        return whole, "".join(f"event: {kind}\ndata: {json.dumps({'type': kind, **body})}\n\n"
                              for kind, body in events)

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
            item = {"type": "function_call", "id": f"fc_{pick[3]}", "call_id": pick[3],
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
