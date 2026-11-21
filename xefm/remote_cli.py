"""``xefmctl``: talking to the XeFM that started this shell (#900, #951, #952).

A shell XeFM starts - a terminal session, the subshell, a terminal program,
a background program, an AI agent's session - gets four variables:

- ``XEFM_SOCKET``: the address XeFM listens on (a Unix socket, or a named
  pipe on Windows);
- ``XEFM_TOKEN``: the key the connection authenticates with;
- ``XEFM_SESSION_KEY``: this shell's own key, which tells XeFM which
  session asks and what that session may do (an agent's session has its
  writes confirmed in XeFM);
- ``XEFM_SESSION``: the session's id, for people and scripts to read.

Each command asks XeFM for the state *at the moment it runs*. The commands
themselves are described in :mod:`xefm.remote_commands`, one table that the
parser, ``xefmctl help`` and the skill's reference are all made from.

This module imports only the standard library: the ``xefmctl`` shim XeFM puts
first on ``PATH`` runs it as a script, with ``-I``, so that
``$(xefmctl pane selected)`` returns at once, without loading the file
manager. The command table is loaded from the file next to this one.

Every message is ASCII (CLAUDE.md, "Text written to stdout/stderr").
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

#: Seconds to wait for XeFM's answer to a command that neither streams nor
#: waits for the user. A modal dialog does not hold a request up (they run
#: between frames), but a file manager busy for longer than this is better
#: reported than waited on forever.
TIMEOUT = 10.0


def _table():
    """:mod:`xefm.remote_commands`, loaded by path (``-I`` keeps this file's
    directory off ``sys.path``)."""
    name = "xefm_remote_commands"
    module = sys.modules.get(name)
    if module is not None:
        return module
    try:
        from xefm import remote_commands  # imported within XeFM, or by tests
        return remote_commands
    except ImportError:
        pass
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "remote_commands.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


class RemoteError(Exception):
    """A request that could not be made, or that XeFM refused. ``code`` is the
    exit status the command ends with."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def _abs(value: str) -> str:
    """A path as XeFM should read it: relative to this shell's directory, not
    to the pane's (``xefmctl pane cd .`` brings the pane to where the shell
    is); a URL as written."""
    if value == "-" or "://" in value:
        return value
    return os.path.abspath(os.path.expanduser(value))


def parse(argv: list[str], stdin=None) -> dict:
    """``argv`` (after ``xefmctl``) as a request: ``{"cmd": "pane cd", "args":
    {...}, "opts": {...}, "json": bool}``. Raises :class:`RemoteError` with
    exit status 2 for a usage mistake, 0 for ``--help``."""
    T = _table()
    cmd, used = T.find(argv)
    if cmd is None:
        verbs = T.nouns().get(argv[0]) if argv else None
        if verbs:
            raise RemoteError(f"xefmctl {argv[0]}: which one? {', '.join(verbs)}", 2)
        what = f"unknown command {argv[0]!r}" if argv else "which command?"
        raise RemoteError(f"xefmctl: {what}\n\n{T.usage()}", 2)
    rest = argv[used:]
    opts: dict = {}
    positional: list[str] = []
    want_json = False
    it = iter(rest)
    for token in it:
        if token in ("-h", "--help"):
            raise RemoteError(T.command_help(cmd), 0)
        if token == "--json":
            want_json = True
            continue
        if token.startswith("-") and token != "-":
            name, eq, value = token.partition("=")
            opt = cmd.opt(name)
            if opt is None:
                raise RemoteError(f"xefmctl {cmd.name}: unknown option {name}\n\n"
                                  f"{T.synopsis(cmd)}", 2)
            if opt.value:
                if not eq:
                    value = next(it, None)
                    if value is None:
                        raise RemoteError(f"xefmctl {cmd.name}: {name} takes {opt.value}", 2)
                if opt.choices and value not in opt.choices:
                    raise RemoteError(f"xefmctl {cmd.name}: {name} takes one of "
                                      f"{', '.join(opt.choices)}", 2)
                opts[opt.name.lstrip("-")] = _abs(value) if opt.path else value
            else:
                if eq:
                    raise RemoteError(f"xefmctl {cmd.name}: {name} takes no value", 2)
                opts[opt.name.lstrip("-")] = True
            continue
        positional.append(token)
    args = _bind(cmd, positional, stdin)
    if cmd.name == "pane cd" and not args.get("path"):
        args["path"] = _abs(".")  # the pane comes to where the shell is
    for key in ("limit", "depth", "line", "max-bytes"):
        if key in opts:
            try:
                opts[key] = int(opts[key])
            except ValueError:
                raise RemoteError(f"xefmctl {cmd.name}: --{key} takes a number", 2) from None
    return {"cmd": cmd.name, "args": args, "opts": opts, "json": want_json}


def _bind(cmd, positional: list[str], stdin) -> dict:
    """Give the positional words to the command's arguments in order."""
    args: dict = {}
    pending = list(positional)
    for i, a in enumerate(cmd.args):
        later_required = sum(1 for b in cmd.args[i + 1:] if b.nargs in ("1", "+"))
        if a.nargs == "1":
            if not pending:
                raise RemoteError(f"xefmctl {cmd.name}: {a.name.upper()} is missing\n\n"
                                  f"{_table().synopsis(cmd)}", 2)
            values = [pending.pop(0)]
        elif a.nargs == "?":
            values = [pending.pop(0)] if len(pending) > later_required else []
        else:
            take = max(0, len(pending) - later_required)
            values, pending = pending[:take], pending[take:]
            if a.nargs == "+" and not values:
                raise RemoteError(f"xefmctl {cmd.name}: {a.name.upper()} is missing\n\n"
                                  f"{_table().synopsis(cmd)}", 2)
        if a.stdin and values == ["-"]:
            stream = stdin if stdin is not None else sys.stdin
            text = stream.read()
            if a.nargs in ("*", "+"):
                values = [line for line in text.splitlines() if line.strip()]
                values = [_path_of(line) for line in values]
            else:
                args[a.name + "_text"] = text
                values = ["-"]
        if a.path:
            values = [_abs(v) for v in values]
        args[a.name] = values[0] if a.nargs in ("1", "?") and values else (
            None if a.nargs in ("1", "?") else values)
    if pending:
        raise RemoteError(f"xefmctl {cmd.name}: unexpected argument {pending[0]}", 2)
    return args


def _path_of(line: str) -> str:
    """A line of standard input as a path: a JSON object from another
    ``xefmctl ... --json`` gives its ``path``; anything else is the path."""
    line = line.strip()
    if line.startswith("{"):
        try:
            item = json.loads(line)
            if isinstance(item, dict) and item.get("path"):
                return str(item["path"])
        except ValueError:
            pass
    return line


def _connect():
    address = os.environ.get("XEFM_SOCKET")
    token = os.environ.get("XEFM_TOKEN")
    if not address or not token:
        raise RemoteError("xefmctl: not in a shell XeFM started (XEFM_SOCKET is not set)", 2)
    from multiprocessing.connection import Client
    try:
        key = bytes.fromhex(token)
    except ValueError:
        raise RemoteError("xefmctl: XEFM_TOKEN is not valid", 2) from None
    try:
        return Client(address, authkey=key)
    except (FileNotFoundError, ConnectionRefusedError):
        raise RemoteError("xefmctl: the XeFM that started this shell has quit", 3) from None
    except OSError as exc:
        raise RemoteError(f"xefmctl: cannot reach XeFM: {exc}", 3) from None
    except Exception as exc:  # AuthenticationError, a peer gone mid-handshake
        raise RemoteError(f"xefmctl: XeFM refused the connection: {exc}", 3) from None


def exchange(req: dict, on_items=None) -> dict:
    """Send one request; hand every chunk of items to ``on_items`` as it
    arrives; return the last answer. A command that streams or waits for the
    user is waited on for as long as it takes (Ctrl-C stops it)."""
    T = _table()
    cmd = T.find(req["cmd"].split())[0]
    # Waited on for as long as it takes: a search, a question to the user,
    # and anything XeFM may first ask the user about (a write from an
    # agent's session, its first read outside the local disk).
    patient = bool(cmd and (cmd.stream or cmd.effect in (T.WRITE, T.ASK)
                            or cmd.name in ("read", "fetch")
                            or (cmd.wait and req["opts"].get("wait"))))
    req = dict(req, key=os.environ.get("XEFM_SESSION_KEY", ""),
               session=os.environ.get("XEFM_SESSION", ""))
    payload = json.dumps(req).encode("utf-8")
    if len(payload) > T.MAX_REQUEST:
        raise RemoteError(f"xefmctl {req['cmd']}: the request is too large "
                          f"({len(payload)} bytes; XeFM takes at most "
                          f"{T.MAX_REQUEST}). Send less at once.", 2)
    conn = _connect()
    try:
        conn.send_bytes(payload)
        while True:
            if patient:
                while not conn.poll(0.5):
                    pass
            elif not conn.poll(TIMEOUT):
                raise RemoteError("xefmctl: XeFM did not answer in time", 4)
            answer = json.loads(conn.recv_bytes().decode("utf-8"))
            if not answer.get("ok"):
                raise RemoteError(f"xefmctl {req['cmd']}: {answer.get('error', 'failed')}",
                                  int(answer.get("code", 1)))
            if on_items is not None and answer.get("items"):
                on_items(answer["items"])
            if not answer.get("more"):
                return answer
    except (EOFError, OSError) as exc:
        raise RemoteError(f"xefmctl: the connection to XeFM broke: {exc}", 3) from None
    finally:
        conn.close()


def format_item(cmd, item, as_json: bool) -> str | None:
    """One answered item as a line of output, or None for nothing."""
    if as_json:
        return json.dumps(item, ensure_ascii=False)
    if isinstance(item, str):
        return item
    if not cmd.text:
        return None
    try:
        return cmd.text.format(**item)
    except (KeyError, IndexError, ValueError):
        return item.get("path") or json.dumps(item, ensure_ascii=False)


def run(argv: list[str], out=None, stdin=None) -> int:
    """Run ``xefmctl <argv>``; return the exit status."""
    out = out if out is not None else sys.stdout
    T = _table()
    try:
        req = parse(argv, stdin)
    except RemoteError as exc:
        print(str(exc), file=out if exc.code == 0 else sys.stderr)
        return exc.code
    cmd = T.find(req["cmd"].split())[0]
    if cmd.local:
        return _help(req, out)
    end = "\0" if req["opts"].get("0") else "\n"

    def emit(items) -> None:
        for item in items:
            line = format_item(cmd, item, req["json"])
            if line is not None:
                out.write(line + end)
        out.flush()

    try:
        answer = exchange(req, emit)
    except RemoteError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        return 130
    if answer.get("note"):
        print(answer["note"], file=sys.stderr)
    return int(answer.get("status", 0))


def _help(req: dict, out) -> int:
    T = _table()
    words = req["args"].get("command") or []
    if req["json"]:
        data = T.describe()
        if words:
            name = " ".join(words)
            data = [d for d in data if d["command"] == name or d["command"].startswith(name + " ")]
        out.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
        return 0
    if not words:
        out.write(T.usage() + "\n")
        return 0
    cmd, used = T.find(words)
    if cmd is None or used != len(words):
        verbs = T.nouns().get(words[0])
        if verbs and len(words) == 1:
            out.write("\n\n".join(T.command_help(T.find([words[0], v])[0])
                                  for v in verbs) + "\n")
            return 0
        print(f"xefmctl help: no command {' '.join(words)!r}", file=sys.stderr)
        return 2
    out.write(T.command_help(cmd) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        # A path the console's code page cannot spell is written with "?"
        # rather than ending the command (xefm's main() does the same, #829).
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if not args or args[0] in ("-h", "--help"):
        print(_table().usage())
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
