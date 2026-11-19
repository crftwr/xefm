"""``xefmctl``: talking to the XeFM that started this shell (discussion #900).

``xefmctl selected``, ``xefmctl cd .`` and the rest. A shell XeFM starts - a
terminal session, the subshell, a terminal program, a background program -
gets three variables:

- ``XEFM_SOCKET``: the address XeFM listens on (a Unix socket, or a named
  pipe on Windows);
- ``XEFM_TOKEN``: the key that connection authenticates with;
- ``XEFM_SESSION``: which session the request comes from.

Each command asks XeFM for the state *at the moment it runs*, unlike the
``XEFM_*_SELECTED`` snapshot taken when the shell started, which goes stale
in a shell that keeps running.

This module is imported by nothing heavy and imports only the standard
library: the ``xefmctl`` shim XeFM puts first on ``PATH`` runs it as a
script, so that ``$(xefmctl selected)`` returns at once, without loading the
file manager. It is named apart from ``xefm``, the command that starts XeFM.

Every message is ASCII (CLAUDE.md, "Text written to stdout/stderr").
"""

from __future__ import annotations

import json
import os
import sys

#: The commands this module answers.
COMMANDS = ("selected", "focused", "pwd", "cd", "view", "sessions")

PANES = ("this", "other", "left", "right")

USAGE = """\
usage: xefmctl selected [--pane PANE] [-0]   the selected items' full paths
       xefmctl focused  [--pane PANE]        the item under the cursor
       xefmctl pwd      [--pane PANE]        the pane's directory
       xefmctl cd       [PATH] [--pane PANE] point the pane at PATH (default: .)
       xefmctl view     FILE                 open FILE in XeFM's viewer
       xefmctl sessions                      list XeFM's terminal sessions

PANE is this (the active pane, the default), other, left or right.
These work in a shell XeFM started; they ask that XeFM for its state now."""

#: Seconds to wait for XeFM's answer. A modal dialog does not hold a request
#: up (they run between frames), but a file manager busy for longer than this
#: is better reported than waited on forever.
TIMEOUT = 10.0


class RemoteError(Exception):
    """A request that could not be made, or that XeFM refused. ``code`` is the
    exit status the command ends with."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def _parse(command: str, args: list[str]) -> dict:
    request: dict = {"cmd": command, "pane": "this"}
    rest: list[str] = []
    it = iter(args)
    for arg in it:
        if arg in ("-h", "--help"):
            raise RemoteError(USAGE, 0)
        if arg == "--pane":
            pane = next(it, None)
            if pane not in PANES:
                raise RemoteError(f"xefmctl {command}: --pane takes one of "
                                  f"{', '.join(PANES)}", 2)
            request["pane"] = pane
        elif arg.startswith("--pane="):
            pane = arg.split("=", 1)[1]
            if pane not in PANES:
                raise RemoteError(f"xefmctl {command}: --pane takes one of "
                                  f"{', '.join(PANES)}", 2)
            request["pane"] = pane
        elif arg == "-0" and command == "selected":
            request["nul"] = True
        elif arg.startswith("-") and arg != "-":
            raise RemoteError(f"xefmctl {command}: unknown option {arg}\n\n{USAGE}", 2)
        else:
            rest.append(arg)
    if command in ("cd", "view"):
        if len(rest) > 1:
            raise RemoteError(f"xefmctl {command}: one path only", 2)
        if command == "view" and not rest:
            raise RemoteError("xefmctl view: which file?", 2)
        target = rest[0] if rest else "."
        # Relative to this shell's directory, not to the pane's: "xefmctl cd ."
        # brings the pane to where the shell is.
        if "://" not in target:
            target = os.path.abspath(os.path.expanduser(target))
        request["path"] = target
    elif rest:
        raise RemoteError(f"xefmctl {command}: unexpected argument {rest[0]}", 2)
    return request


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


def request(req: dict) -> dict:
    """Send one request to XeFM and return its answer."""
    req = dict(req, session=os.environ.get("XEFM_SESSION", ""))
    conn = _connect()
    try:
        conn.send_bytes(json.dumps(req).encode("utf-8"))
        if not conn.poll(TIMEOUT):
            raise RemoteError("xefmctl: XeFM did not answer in time", 4)
        answer = json.loads(conn.recv_bytes().decode("utf-8"))
    except (EOFError, OSError) as exc:
        raise RemoteError(f"xefmctl: the connection to XeFM broke: {exc}", 3) from None
    finally:
        conn.close()
    if not answer.get("ok"):
        raise RemoteError(f"xefmctl {req['cmd']}: {answer.get('error', 'failed')}",
                          int(answer.get("code", 1)))
    return answer


def run(command: str, args: list[str], out=None) -> int:
    """Run ``xefmctl <command> <args>``; return the exit status."""
    out = out if out is not None else sys.stdout
    try:
        answer = request(_parse(command, args))
    except RemoteError as exc:
        stream = out if exc.code == 0 else sys.stderr
        print(str(exc), file=stream)
        return exc.code
    lines = answer.get("lines") or []
    if lines:
        if answer.get("nul"):
            out.write("".join(line + "\0" for line in lines))
        else:
            out.write("".join(line + "\n" for line in lines))
        out.flush()
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
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if args[0] in COMMANDS:
        return run(args[0], args[1:])
    print(f"xefmctl: unknown command {args[0]!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
