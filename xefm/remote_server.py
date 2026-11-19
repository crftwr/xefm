"""The local socket a shell XeFM started talks back on (discussion #900).

:mod:`xefm.remote_cli` is the client: ``xefmctl selected``, ``xefmctl cd .``,
``xefmctl view foo.log``. This is the listening side. It owns three things:

- **The listener.** ``multiprocessing.connection`` over a Unix socket in a
  private (0700) temp directory, or a named pipe on Windows. Every connection
  authenticates with a per-process key (HMAC challenge) before a byte of its
  request is read. Requests and answers are JSON, never pickles.
- **The shim directory.** An ``xefmctl`` script (``xefmctl.cmd`` on Windows)
  that runs the client with XeFM's own interpreter. It goes first on ``PATH``
  in every shell XeFM starts, so ``xefmctl`` works there even from an app
  bundle that put nothing on the system's ``PATH``, and answers without
  loading the file manager.
- **The environment.** :meth:`RemoteServer.env` - ``XEFM_SOCKET``,
  ``XEFM_TOKEN``, ``XEFM_SESSION``, ``XEFM_PYTHON`` and the ``PATH`` entry.

What a request does is the app's business: the server hands each one to a
``handle(request) -> answer`` callable. It is called on the listener's worker
thread; the app moves the work to its UI thread.

The key tells XeFM that a request comes from a shell it started, not who is
typing; it is not meant to keep out other programs running as the same user,
which could read the key from the shell's environment anyway.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import weakref
from collections.abc import Callable

from xefm.log_manager import getLogger

logger = getLogger("Remote")

#: Longest request accepted, in bytes: a path or two, never more.
MAX_REQUEST = 64 * 1024


class RemoteServer:
    """Listen for :mod:`xefm.remote_cli` requests until :meth:`close`."""

    def __init__(self, handle: Callable[[dict], dict], *, python: str) -> None:
        from multiprocessing.connection import Listener
        self._handle = handle
        self._key = secrets.token_bytes(32)
        self._dir = tempfile.mkdtemp(prefix="xefm-")  # 0700
        if sys.platform == "win32":
            self.address = rf"\\.\pipe\xefm-{os.getpid()}-{secrets.token_hex(8)}"
            family = "AF_PIPE"
        else:
            self.address = os.path.join(self._dir, "socket")
            family = "AF_UNIX"
        self._listener = Listener(self.address, family=family, authkey=self._key)
        # Gone at exit even when close() never runs (a crash, a test's app):
        # the listener first, so its own finalizer has nothing left to unlink.
        self._stop = threading.Event()
        weakref.finalize(self, _cleanup, self._listener, self._dir, self._stop)
        self.python = python
        self.bin_dir = self._write_shim(python)
        self._thread = threading.Thread(target=self._serve, name="xefm-remote",
                                        daemon=True)
        self._thread.start()

    # --- the shim ------------------------------------------------------------------
    def _write_shim(self, python: str) -> str:
        bin_dir = os.path.join(self._dir, "bin")
        os.mkdir(bin_dir)
        client = os.path.join(os.path.dirname(os.path.abspath(__file__)), "remote_cli.py")
        if sys.platform == "win32":
            path = os.path.join(bin_dir, "xefmctl.cmd")
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(f'@"{python}" -I "{client}" %*\n')
        else:
            import shlex
            path = os.path.join(bin_dir, "xefmctl")
            with open(path, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n"
                        f"exec {shlex.quote(python)} -I {shlex.quote(client)} \"$@\"\n")
            os.chmod(path, 0o755)
        return bin_dir

    # --- the environment -------------------------------------------------------------
    def env(self, session: str) -> dict:
        """What a shell XeFM starts needs to reach it, as session ``session``.
        ``PATH`` is the shim directory alone: :func:`apply_env` puts it in
        front of the shell's own."""
        return {
            "XEFM_SOCKET": self.address,
            "XEFM_TOKEN": self._key.hex(),
            "XEFM_SESSION": session,
            "XEFM_PYTHON": self.python,
            "PATH": self.bin_dir,
        }

    def apply_env(self, env: dict, session: str) -> dict:
        """Add :meth:`env` to ``env`` in place, prepending the shim directory
        to its ``PATH``; return ``env``."""
        extra = self.env(session)
        shim = extra.pop("PATH")
        env.update(extra)
        current = env.get("PATH", "")
        parts = [p for p in current.split(os.pathsep) if p and p != shim]
        env["PATH"] = os.pathsep.join([shim, *parts])
        return env

    # --- serving -----------------------------------------------------------------------
    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except OSError:
                if self._stop.is_set():
                    return
                logger.warning("The remote socket stopped accepting connections")
                return
            except Exception as exc:  # AuthenticationError: not one of ours
                if self._stop.is_set():
                    return
                logger.warning(f"Refused a connection to the remote socket: {exc}")
                continue
            threading.Thread(target=self._answer, args=(conn,),
                             name="xefm-remote-request", daemon=True).start()

    def _answer(self, conn) -> None:
        try:
            raw = conn.recv_bytes(MAX_REQUEST)
            try:
                req = json.loads(raw.decode("utf-8"))
                if not isinstance(req, dict) or not isinstance(req.get("cmd"), str):
                    raise ValueError("not a request")
            except ValueError as exc:
                answer = {"ok": False, "error": f"bad request: {exc}", "code": 2}
            else:
                try:
                    answer = self._handle(req)
                except Exception as exc:
                    logger.error(f"Remote request {req.get('cmd')!r} failed: {exc}")
                    answer = {"ok": False, "error": str(exc)}
            conn.send_bytes(json.dumps(answer).encode("utf-8"))
        except (EOFError, OSError) as exc:
            logger.info(f"A remote request was dropped: {exc}")
        finally:
            conn.close()

    def close(self) -> None:
        """Stop listening and remove the socket and the shim."""
        if self._stop.is_set():
            return
        _cleanup(self._listener, self._dir, self._stop)


def _cleanup(listener, directory: str, stop: threading.Event) -> None:
    stop.set()
    try:
        listener.close()
    except OSError:
        pass
    shutil.rmtree(directory, ignore_errors=True)


def start(handle: Callable[[dict], dict], *, python: str) -> RemoteServer | None:
    """A running :class:`RemoteServer`, or None (logged) where one cannot be
    started - the commands then report that they are not in an XeFM shell."""
    try:
        return RemoteServer(handle, python=python)
    except Exception as exc:
        logger.warning(f"xefmctl is unavailable in XeFM's shells: {exc}")
        return None
