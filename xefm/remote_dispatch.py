"""What each ``xefmctl`` command does, on XeFM's side (#900, #951, #952).

:mod:`xefm.remote_server` receives a request on its listener thread and hands
it to :func:`handle`. The commands are described in
:mod:`xefm.remote_commands`; this module carries them out:

- **Through the public API.** A command is an ``ActionContext`` call wherever
  one exists (``ctx.pane.cd``, ``ctx.copy``, ``ctx.confirm``, ``ctx.invoke``),
  so ``xefmctl`` can do nothing an action cannot. ``--from pane|selection``
  is :meth:`PaneApi.shows_list` / ``entries`` / ``path`` and
  :meth:`PaneApi.selected_or_focused` (:func:`_from_pane`).
- **On the file manager.** Whatever a command opens - a viewer, a dialog -
  opens on the file manager's screen, and the user is taken there when it
  needs them. A question asked for an agent (``confirm``, a copy to approve)
  takes the user back to the agent's terminal once answered.
- **Only what a hand could do now.** A command that changes the file manager
  is let in as a key on its screen would be: with the panes on top, anything;
  with a viewer, anything but an action of the file list (``view`` replaces
  the viewer, at once, so two are never open); with a dialog, menu or palette
  open there, nothing - the answer says so, for the agent to tell the user.
- **An agent's session is restricted** (policy ``"agent"``, the hard layer of
  ``AGENTS``' ``restrict``): every write is confirmed in XeFM whatever the
  ``CONFIRM_*`` settings say, ``delete`` and ``delete_permanently`` are
  refused, an action run with ``invoke`` gets the confirmations forced on and
  deletes to the trash, and the first read outside the local disk is asked.
  A file's contents outside the session's own folder are asked too, once for
  each folder (:func:`_local_read_allowed`, #995): XeFM reads with the user's
  rights, and a sandbox may keep the agent from them. Each command's class is
  in :data:`xefm.remote_commands.AGENT_CLASS`. Whatever else would change a file or run a program is asked first
  (:func:`_ask_first`): ``fetch`` to a named file, ``terminal-session start``
  (whose session keeps the agent's policy), an action that hands files to
  other programs. What asks the user for an agent starts with no button
  selected (:func:`_start_unselected`).

Reads of the panes are answered even while terminal mode has its terminal
handed over (the UI thread is parked in the child's wait and nothing else
touches them); everything else is refused with :data:`SUSPENDED`, an exit
status of its own, since it will not pass until the shell exits - unlike
:data:`BUSY`, which is worth a retry (#961). ``state`` says so too, so an
agent learns it from its first command.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import sys
import tempfile
import threading
import unicodedata
from pathlib import Path as _FsPath
from typing import Any

from xefm import remote_commands as T
from xefm.log_manager import getLogger

logger = getLogger("Remote")

USER = "user"
AGENT = "agent"

#: Seconds a request waits for the UI thread before reporting XeFM busy
#: (under remote_cli.TIMEOUT, so the answer still reaches the client).
UI_WAIT = 8.0

#: Seconds of UI-thread work after which the client is told XeFM has the
#: request and is still at it (under the client's own TIMEOUT).
ACK_AFTER = 2.0

#: Exit statuses (``xefmctl``'s, documented in the skill's reference).
FAILED, USAGE, UNREACHABLE, BUSY, REFUSED, SUSPENDED = 1, 2, 3, 4, 5, 6

#: The refusal of a command that needs XeFM's screen while terminal mode has
#: handed the terminal to this shell. ASCII: it reaches a stream.
SUSPENDED_MESSAGE = (
    "XeFM is suspended until this shell exits (terminal mode), so only "
    "commands that read work in this session; this one needs XeFM's screen. "
    "Retrying will not help: show results here and ask in the chat instead.")

#: Actions an agent's session may not invoke.
AGENT_DENIED_ACTIONS = frozenset({"delete_permanently", "quit", "quit_app"})

#: Actions an agent's session may invoke only once the user agrees, and what
#: each would do: they run programs, and have no confirmation of their own.
AGENT_ASKED_ACTIONS = {
    "open_with_os": "open the item under the cursor with another program",
    "open_items_with_os": "open the selected items with other programs",
    "sync_python_packages": "install the Python packages ~/.xefm/requirements.txt lists",
    "reload_config": "reload ~/.xefm/config.py, which runs what is in it",
}

#: The longest command line or path a question to the user shows. A longer
#: one is refused: the user would be agreeing to what they cannot see.
ASK_LIMIT = 2000

#: Settings forced while an agent's session runs an action: every operation
#: asks first, and a delete goes to the trash.
AGENT_FORCED_SETTINGS = {
    "CONFIRM_COPY": True, "CONFIRM_MOVE": True, "CONFIRM_DELETE": True,
    "CONFIRM_TRASH": True, "CONFIRM_DUPLICATE": True,
    "CONFIRM_EXTRACT_ARCHIVE": True, "CONFIRM_ARCHIVE_CREATE": True,
    "DELETE_TO_TRASH": True,
}

#: The operations' own confirmations, always shown for an agent's write.
_ALWAYS_CONFIRM = {"CONFIRM_COPY": True, "CONFIRM_MOVE": True,
                   "CONFIRM_TRASH": True}

READ_LIMIT = 1_000_000


class Pending:
    """An answer that comes later, from a callback on the UI thread (the user
    answered, a copy finished). The listener thread waits for it."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.answer: Any = None  # an answer, or an iterator of them
        self._next: Pending | None = None

    def set(self, answer: Any) -> None:
        if not self._event.is_set():
            self.answer = answer
            self._event.set()
            if self._next is not None:
                self._next.set(answer)

    def forward(self, other: Pending) -> None:
        """Give ``other`` this one's answer, when it comes."""
        self._next = other
        if self._event.is_set():
            other.set(self.answer)

    def wait(self) -> Any:
        self._event.wait()
        return self.answer or ok()


def ok(items=None, **extra) -> dict:
    return dict(ok=True, items=list(items or []), **extra)


def refuse(message: str, code: int = REFUSED) -> dict:
    return {"ok": False, "error": message, "code": code}


class _Refused(Exception):
    def __init__(self, message: str, code: int = REFUSED):
        super().__init__(message)
        self.code = code


# --- the entry point ------------------------------------------------------------


def handle(app, req: dict):
    """One request, on the listener's thread. Returns an answer, or an
    iterator of answers for a command that streams."""
    cmd = T.find(str(req.get("cmd", "")).split())[0]
    if cmd is None or cmd.local or cmd.name != req.get("cmd"):
        return refuse(f"unknown command {req.get('cmd')!r}", USAGE)
    req.setdefault("args", {})
    req.setdefault("opts", {})
    if getattr(app, "_terminal_handed_over", False):
        if cmd.effect != T.READ:
            return refuse(SUSPENDED_MESSAGE, SUSPENDED)
        # The UI thread is parked in the child's wait (_run_in_terminal):
        # nothing else reads or changes the panes until it returns.
        req["opts"].pop("show", None)
        return _finish(_answer(app, cmd, req))
    started, done = threading.Event(), threading.Event()
    lock = threading.Lock()
    box: dict = {}

    def run() -> None:
        with lock:
            if box.get("abandoned"):
                return  # the client was told XeFM is busy: do nothing late
            started.set()
        try:
            box["answer"] = _answer(app, cmd, req)
        except _Refused as exc:
            box["answer"] = refuse(str(exc), exc.code)
        except Exception as exc:
            logger.error(f"xefmctl {cmd.name} failed: {exc}")
            box["answer"] = refuse(str(exc), FAILED)
        finally:
            done.set()

    app._call_later(run)
    # Busy means the UI thread did not get to it: once it has started, the
    # work is waited for however long it takes (a long document laid out
    # for show-markdown), so a slow success is never reported as a failure.
    if not started.wait(UI_WAIT):
        with lock:
            if not started.is_set():
                box["abandoned"] = True
                return refuse("XeFM is busy; try again", BUSY)
    if done.wait(ACK_AFTER) and not isinstance(box["answer"], Pending):
        return box["answer"]
    return _late(done, box)  # still at it, or waiting for the user


def _late(done, box):
    """The answers of work still running on the UI thread, or waiting for the
    user: an empty one at once, which tells the client XeFM has the request
    (it then waits as long as it takes), then the work's own."""
    yield ok()
    done.wait()
    answer = _finish(box["answer"])
    if isinstance(answer, dict):
        yield answer
    else:
        yield from answer


def _finish(answer):
    if isinstance(answer, Pending):
        return answer.wait()
    return answer


def _answer(app, cmd, req):
    """The command's work, on the UI thread."""
    try:
        if cmd.effect != T.READ:
            _gate(app, cmd, req)
        with _acting(app, req):
            return _HANDLERS[cmd.name](app, req)
    except _Refused as exc:
        return refuse(str(exc), exc.code)


# --- the gate: only what a hand could do now -------------------------------------


def files_top(app) -> Any:
    """The topmost layer on the file manager's screen, shown or not, or None
    when the panes are on top."""
    panel = app.panel
    layers = panel.layer_children(app._screens.files.group)
    top = None
    while layers:
        top = layers[-1]
        layers = panel.layer_children(top)
    return top


def is_viewer(layer) -> bool:
    return layer is not None and hasattr(layer, "palette_actions")


def _layer_name(layer) -> str:
    title = getattr(layer, "title", "") or ""
    if isinstance(title, str) and title.strip():
        return f" ({title.strip()})"
    return ""


def _gate(app, cmd, req) -> None:
    """Refuse a command a key on the file manager's screen could not reach
    now."""
    if cmd.name in ("message", "screen show", "terminal-session start",
                    "terminal-session close"):
        return  # not about what is on the file manager's screen
    top = files_top(app)
    if top is None:
        return
    if is_viewer(top):
        if cmd.name == "invoke":
            from xefm import actions as A
            action = A.registry.resolve(A.COMMON, req["args"].get("name") or "")
            if action is None:
                raise _Refused("a viewer is open on XeFM's file manager, and only "
                               "actions that work over a viewer can run; ask the user "
                               "to close the viewer first (or use xefmctl view, which "
                               "replaces it)")
        return
    raise _Refused(f"a dialog is open in XeFM's file manager{_layer_name(top)}; ask the "
                   f"user to finish it first")


@contextlib.contextmanager
def on_files(app):
    """Run with what opens landing on the file manager's screen, whichever
    screen is shown: PuiKit's default layer parent is the file manager's
    group for the duration."""
    panel = app.panel
    before = panel.default_layer_parent
    panel.set_default_layer_parent(app._screens.files.group)
    try:
        yield
    finally:
        if before is None or panel.has_layer(before):
            panel.set_default_layer_parent(before)
        else:
            panel.set_default_layer_parent(app._screens.current.group)


def _bring_user(app, before: list) -> Any:
    """Show the file manager's screen when something opened on it (``before``:
    its layers then). Returns the screen that was shown before, or None when
    nothing moved."""
    screens = app._screens
    if screens.current is screens.files:
        return None
    if list(app.panel.layer_children(screens.files.group)) == before:
        return None
    came_from = screens.current
    app._show_screen(screens.files)
    return came_from


def _go_back(app, screen) -> None:
    """After an answer the agent waited for: back to its screen, if the user
    is still on the file manager where the question took them."""
    screens = app._screens
    if screen is None or screens.current is not screens.files:
        return
    if screen in screens.recent():
        app._show_screen(screen)


def _ui(app, req, work):
    """Do ``work()`` on the file manager's screen and take the user there if
    it opened something. Returns ``(result, came_from)``: the screen the user
    was on, for a question to take them back to, or None."""
    before = list(app.panel.layer_children(app._screens.files.group))
    with on_files(app):
        result = work()
    if _is_agent(req):
        _start_unselected(app, before)
    came_from = _bring_user(app, before)
    return result, came_from


def _start_unselected(app, before: list) -> None:
    """Take the selection off the buttons of the confirmations just opened
    (not in ``before``). An agent asks whenever it likes, and the user may be
    typing: an Enter meant for something else must neither agree to it nor
    turn it down. That goes for the operations' own confirmations too, whose
    default is for a user who has just asked for the operation."""
    from puikit.widgets import MessageBox
    for layer in app.panel.layer_children(app._screens.files.group):
        if isinstance(layer, MessageBox) and len(layer.buttons) > 1 \
                and not any(layer is b for b in before):
            layer.default = layer.focused = None
            app.panel.render()


# --- who asks -----------------------------------------------------------------------


def _is_agent(req) -> bool:
    return req.get("policy") == AGENT


def _asker(app, req) -> str:
    """The session's name, for a question XeFM asks on its behalf."""
    sid = str(req.get("session") or "")
    for s in getattr(app, "_sessions", []) or []:
        if str(s.id) == sid:
            return s.name
    return "The AI agent" if _is_agent(req) else "A shell"


@contextlib.contextmanager
def _forced(app, settings: dict | None = None):
    """``settings`` (``AGENT_FORCED_SETTINGS`` by default) on ``app.config``
    while held."""
    saved = {}
    for name, value in (AGENT_FORCED_SETTINGS if settings is None else settings).items():
        saved[name] = getattr(app.config, name, None)
        setattr(app.config, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                with contextlib.suppress(AttributeError):
                    delattr(app.config, name)
            else:
                setattr(app.config, name, value)


@contextlib.contextmanager
def _acting(app, req):
    """While held, what moves a pane is the agent, not the user
    (:func:`pane_moved`)."""
    if not _is_agent(req):
        yield
        return
    before = getattr(app, "_agent_acting", False)
    app._agent_acting = True
    try:
        yield
    finally:
        app._agent_acting = before


def pane_moved(app, path) -> None:
    """A pane is about to list ``path`` (on the UI thread): remembered as the
    agent's doing, or as the user's, for :func:`_readable`."""
    went = app.__dict__.setdefault("_agent_went", set())
    if getattr(app, "_agent_acting", False):
        went.add(str(path))
    else:
        went.discard(str(path))


# --- panes ---------------------------------------------------------------------------


def _pane_api(app, req):
    from xefm import user_api as api
    which = req["opts"].get("pane") or "active"
    active = app.pm.active_pane
    name = {"active": active, "other": "right" if active == "left" else "left"}.get(which, which)
    return api.PaneApi(app, name)


def _entry(e) -> dict:
    return {"path": str(e.path), "name": e.name, "is_dir": bool(e.is_dir)}


def _c_state(app, req):
    panes = {}
    lines = []
    active = app.pm.active_pane
    for name in ("left", "right"):
        api = _pane_api(app, {"opts": {"pane": name}})
        pane = app.pane(name)
        focused = api.focused
        selected = api.selected()
        info = {
            "path": str(api.path),
            "active": name == active,
            "focused": str(focused.path) if focused else None,
            "selected": [str(e.path) for e in selected],
            "count": len(pane["files"]),
            "filter": pane.get("filter_pattern") or "",
            "list": (pane.get("virtual") or {}).get("kind") or "",
        }
        panes[name] = info
        mark = "*" if info["active"] else " "
        extra = f", filter {info['filter']}" if info["filter"] else ""
        extra += f", {info['list']} list" if info["list"] else ""
        lines.append(f"{mark} {name}: {info['path']} ({info['count']} items, "
                     f"{len(selected)} selected{extra})")
        if focused:
            lines.append(f"    cursor: {focused.path}")
    screens = app._screens
    current = screens.current
    top = files_top(app)
    over = ""
    if top is not None:
        path = getattr(top, "path", None) or getattr(top, "left_path", None)
        over = (f"viewer: {path}" if is_viewer(top) and path is not None
                else "viewer" if is_viewer(top) else f"dialog{_layer_name(top)}")
    lines.append(f"screen: {current.id} ({app._screen_label(current)})")
    if over:
        lines.append(f"over the panes: {over}")
    suspended = bool(getattr(app, "_terminal_handed_over", False))
    if suspended:
        lines.append("XeFM is suspended until this shell exits: only commands "
                     "that read work (exit status 6 for the rest)")
    sandbox = sandbox_of(app, req)
    if sandbox:
        lines.append(f"this session's sandbox: {sandbox}")
    item = {
        "panes": panes, "active": active,
        "screen": {"id": current.id, "kind": current.kind,
                   "label": app._screen_label(current)},
        "files_screen": "panes" if top is None else over,
        "desktop": _desktop(),
        "suspended": suspended,
        "sandbox": sandbox,
        "text": "\n".join(lines),
    }
    return ok([item])


def sandbox_of(app, req) -> str:
    """Whether the asking agent's own sandbox is ``on``, ``off`` or ``not
    known``, as far as XeFM can tell; "" for what is no agent's session."""
    sid = str(req.get("session") or "")
    for session in getattr(app, "_sessions", []) or []:
        if str(session.id) == sid:
            conv = getattr(getattr(session, "view", None), "conversation", None)
            return getattr(conv, "sandbox", "") or getattr(session, "sandbox", "")
    return (getattr(app, "_agent_sandboxes", None) or {}).get(sid, "")


def _desktop() -> bool:
    from xefm.user_api import is_desktop_mode
    return bool(is_desktop_mode())


def _c_pane_path(app, req):
    return ok([{"path": str(_pane_api(app, req).path)}])


def _c_pane_entries(app, req):
    entries = _pane_api(app, req).entries
    limit = req["opts"].get("limit")
    return ok([_entry(e) for e in (entries[:limit] if limit else entries)])


def _c_pane_focused(app, req):
    e = _pane_api(app, req).focused
    return ok([_entry(e)] if e else [])


def _c_pane_selected(app, req):
    return ok([_entry(e) for e in _pane_api(app, req).selected()])


def _c_pane_cd(app, req):
    from xefm.path import Path
    api = _pane_api(app, req)
    text = req["args"].get("path") or "."
    target = app._resolve_jump_target(text, str(api.path))
    if not target.exists():
        raise _Refused(f"no such file or directory: {target}", FAILED)
    focus = req["opts"].get("focus")
    if target.is_dir():
        api.cd(target, focus)
    else:
        api.cd(Path(str(target.parent)), focus or target.name)
    app.log_info(f"Jumped to: {target} (xefmctl)")
    return ok()


def _matcher(req):
    patterns = req["args"].get("pattern") or []
    if req["opts"].get("all"):
        return None
    if not patterns:
        raise _Refused("which items? name them, give a glob, or use --all", USAGE)

    def match(e) -> bool:
        name = e.path.name
        return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(str(e.path), p)
                   or name == p for p in patterns)
    return match


def _c_pane_select(app, req):
    n = _pane_api(app, req).select(_matcher(req))
    return ok([{"count": n, "text": f"{n} selected"}])


def _c_pane_unselect(app, req):
    n = _pane_api(app, req).unselect(_matcher(req))
    return ok([{"count": n, "text": f"{n} unselected"}])


def _c_pane_open_list(app, req):
    paths = req["args"].get("path") or []
    if not paths:
        raise _Refused("no paths given", USAGE)
    _pane_api(app, req).open_list(paths, title=req["opts"].get("title") or "xefmctl")
    return ok()


def _c_pane_refresh(app, req):
    _pane_api(app, req).refresh()
    return ok()


def _c_pane_activate(app, req):
    _pane_api(app, req).activate()
    return ok()


# --- places and searches ------------------------------------------------------------------


def _from_pane(app, req) -> list | None:
    """The items ``--from`` names, or None without it: ``pane`` is the pane's
    folder, or the entries of the list it shows; ``selection`` the selected
    items, or else the one under the cursor (#962)."""
    which = req["opts"].get("from")
    if not which:
        return None
    api = _pane_api(app, req)
    if which == "selection":
        items = [e.path for e in api.selected_or_focused()]
        if not items:
            raise _Refused(f"nothing is selected in the {api.name} pane and there is "
                           f"no item under its cursor", FAILED)
        return items
    if api.shows_list:
        items = [e.path for e in api.entries if e.path.name != ".."]
        if not items:
            raise _Refused(f"the list in the {api.name} pane is empty", FAILED)
        return items
    return [api.path]


def _roots(app, req, key: str = "url") -> list:
    """The places a command works on: its arguments, ``--from``, or else the
    pane's folder."""
    from xefm.path import Path
    found = _from_pane(app, req)
    if found is not None:
        return found
    urls = req["args"].get(key)
    if isinstance(urls, str):
        urls = [urls]
    if not urls:
        return [_pane_api(app, req).path]
    return [Path(u) for u in urls]


def _operands(app, req, key: str) -> list[str]:
    """The items a command acts on - its arguments, or ``--from`` - written
    back into the request as strings, as the client sends them."""
    found = _from_pane(app, req)
    if found is not None:
        req["args"][key] = [str(p) for p in found]
    items = req["args"].get(key) or []
    if not items:
        raise _Refused("which items? name them, - for standard input, or --from", USAGE)
    return items


def _stream(app, req, produce, *, mode: str, query: str = "", root=None):
    """The answers of a streaming command: ``produce(cancel)`` yields items
    (on the listener's thread); every 50 go out as one answer. With --show,
    what was found is shown in the pane at the end, on the UI thread."""
    limit = req["opts"].get("limit")
    show = bool(req["opts"].get("show"))
    cancel = threading.Event()

    def answers():
        found: list = []
        batch: list = []
        count = 0
        try:
            for value, item in produce(cancel):
                batch.append(item)
                if show:
                    found.append(value)
                count += 1
                if len(batch) >= 50:
                    yield ok(batch)
                    batch = []
                if limit and count >= limit:
                    break
            if batch:
                yield ok(batch)
            if show:
                app._call_later(lambda: _show_results(app, req, mode, found, root, query))
        except _Refused as exc:
            yield refuse(str(exc), exc.code)
        finally:
            cancel.set()
    return answers()


def _show_results(app, req, mode: str, found: list, root, query: str) -> None:
    api = _pane_api(app, req)
    if not api.is_active:
        api.activate()
    if mode == "similar":
        if found:
            from xefm import xft
            from xefm.path import Path
            api.cd(Path(xft.uri_for(found[0]["result"])))
    elif mode in ("filename", "content", "index") and root is not None:
        app._feed_search_results(mode, found, root, query)
    else:
        api.open_list([str(p) for p in found], title=req["opts"].get("title") or "xefmctl")
    app.panel.render()


def _c_entries(app, req):
    roots = _roots(app, req)
    recursive = bool(req["opts"].get("recursive"))
    depth = req["opts"].get("depth")

    def produce(cancel):
        for root in roots:
            try:
                for e in app._user_ctx.entries(root, recursive=recursive, depth=depth,
                                               cancel=cancel):
                    yield e.path, {"path": str(e.path), "name": e.path.name,
                                   "is_dir": bool(e.is_dir), "size": e.size,
                                   "mtime": e.mtime}
            except FileNotFoundError as exc:
                raise _Refused(str(exc), FAILED) from None
    return _stream(app, req, produce, mode="list")


def _parts(p) -> tuple:
    return tuple(part for part in str(p).replace("\\", "/").split("/") if part)


def _c_find_files(app, req):
    roots = _roots(app, req)
    pattern = req["args"]["pattern"]
    case = bool(req["opts"].get("case"))
    recursive = not req["opts"].get("no-recursive")

    def produce(cancel):
        for root in roots:
            for p in app._user_ctx.find_files(root, pattern, case=case,
                                              recursive=recursive, cancel=cancel):
                yield p, {"path": str(p), "name": p.name}
    return _stream(app, req, produce, mode="filename", query=pattern, root=roots[0])


def _c_find_in_files(app, req):
    from xefm import search_options as search_opts
    roots = _roots(app, req)
    query = req["args"]["pattern"]
    opts = req["opts"]
    flags = dict(case=bool(opts.get("case")), word=bool(opts.get("word")),
                 regex=bool(opts.get("regex")))
    try:
        search_opts.content_regex(query, **flags)  # refused before anything is read
    except Exception as exc:
        raise _Refused(f"invalid pattern: {exc}", USAGE) from None
    recursive = not opts.get("no-recursive")

    def produce(cancel):
        for root in roots:
            for hit in app._user_ctx.find_in_files(root, query, recursive=recursive,
                                                   cancel=cancel, **flags):
                if readable is not None and not may_read(hit["path"]):
                    continue  # a link out of what may be read
                yield hit, {"path": str(hit["path"]), "line": hit["line"],
                            "text": hit["text"]}
    readable = None
    seen: dict = {}

    def may_read(path) -> bool:
        key = str(path)
        if key not in seen:
            seen[key] = not _is_local(key) or readable.file(_real(key))
        return seen[key]

    def search():
        nonlocal readable
        readable = _Readable(app, req) if _is_agent(req) else None
        return _stream(app, req, produce, mode="content", query=query, root=roots[0])
    return _remote_read_allowed(app, req, roots, search, below=recursive)


def _c_index_search(app, req):
    from xefm import os_index
    why = os_index.unavailable()
    if why:
        raise _Refused(why, FAILED)
    roots = _roots(app, req)
    query = req["args"]["query"]
    for root in roots:  # refused before anything is searched
        try:
            app._user_ctx.index_search(root, query)
        except OSError as exc:
            raise _Refused(str(exc), FAILED) from None

    def produce(cancel):
        for root in roots:
            try:
                for p in app._user_ctx.index_search(root, query, cancel=cancel):
                    yield p, {"path": str(p)}
            except OSError as exc:
                raise _Refused(str(exc), FAILED) from None
            except Exception as exc:  # SearchFailed: the index could not be asked
                raise _Refused(f"{os_index.engine()}: {exc}", FAILED) from None
    return _stream(app, req, produce, mode="index", query=query, root=roots[0])


def _c_find_similar(app, req):
    from xefm import similar_scan
    opts = req["opts"]
    method = opts.get("method")
    if not method:
        raise _Refused("which method? give --method identical, image, video or audio",
                       USAGE)
    threshold = opts.get("threshold")
    if threshold is not None and method != similar_scan.IDENTICAL:
        steps = dict(similar_scan.threshold_steps(method))
        if threshold in steps:
            threshold = steps[threshold]
        else:
            try:
                threshold = float(threshold)
            except ValueError:
                raise _Refused(f"--threshold takes {', '.join(steps) or 'a number'} "
                               f"or a number from 0 to 1", USAGE) from None
    else:
        threshold = None
    roots = _roots(app, req)
    try:
        groups = app._user_ctx.find_similar(roots, method=method, threshold=threshold)
    except ValueError as exc:
        raise _Refused(str(exc), USAGE) from None
    except OSError as exc:
        raise _Refused(str(exc), FAILED) from None

    def produce(cancel):
        try:
            for g in groups:
                if cancel.is_set():
                    return
                for path, similarity in zip(g["paths"], g["similarity"]):
                    item = {"group": g["group"], "path": str(path),
                            "similarity": similarity, "result": g["result"]}
                    yield item, item
        except OSError as exc:
            raise _Refused(str(exc), FAILED) from None
    return _stream(app, req, produce, mode="similar")


def _c_path_scheme_list(app, req):
    return ok([{"name": s.name, "source": s.source}
               for s in app._user_ctx.path_schemes()])


def _is_local(path) -> bool:
    from xefm import path_schemes
    text = str(path)
    if path_schemes.is_uri(text):
        return False
    if os.name == "nt":
        # A UNC path is a server; the same form can also name a local drive.
        text = text.replace("/", "\\")
        return not text.startswith("\\\\") or (
            text.startswith("\\\\?\\") and text[5:6] == ":")
    return True


def _shown_to_user(text) -> str:
    """``text`` as a question shows it: nothing in it can pass for another
    line, or turn the text around it."""
    text = "".join(c if c.isprintable() else ascii(c)[1:-1] for c in str(text))
    if len(text) > ASK_LIMIT:
        raise _Refused("too long to show the user, who has to agree to it")
    return text


def _fit(app, text: str) -> str:
    """A question as the box shows it, which does not wrap: broken at the
    width it can have, a path too, or refused where the screen has no room for
    all of it. What the user cannot see they cannot agree to."""
    backend = getattr(app.panel, "backend", None)
    if backend is None:
        return text
    from puikit import Font, Style
    from puikit.text import wrap_text
    width, height = backend.size_units
    style = Style(font=Font())
    rows = [row for line in text.split("\n") for row in wrap_text(
        line, max(10.0, width - 8), lambda t: backend.measure_text(t, style))]
    if len(rows) > height - 9:
        raise _Refused("too long to show the user, who has to agree to it")
    return "\n".join(rows)


def _ask_first(app, req, question: str, title: str, then, *, declined: str) -> Any:
    """Run ``then()`` if the user agrees, for an agent's session; at once for
    any other. Returns an answer or a Pending. Refused while terminal mode
    has its terminal handed over: there is no screen to ask on."""
    if not _is_agent(req):
        return then()
    if getattr(app, "_terminal_handed_over", False):
        raise _Refused(SUSPENDED_MESSAGE, SUSPENDED)
    question = _fit(app, question)
    pending = Pending()
    came_from = [None]

    def answered(yes: bool) -> None:
        _go_back(app, came_from[0])
        if not yes:
            pending.set(refuse(declined, FAILED))
            return
        try:
            with _acting(app, req):
                answer = then()
        except _Refused as exc:
            answer = refuse(str(exc), exc.code)
        except Exception as exc:
            logger.error(f"xefmctl {req['cmd']} failed: {exc}")
            answer = refuse(str(exc), FAILED)
        if isinstance(answer, Pending):  # another question: its answer is ours
            answer.forward(pending)
        else:
            pending.set(answer)
    _, came_from[0] = _ui(app, req, lambda: app._user_ctx.confirm(
        question, title=title, on_result=answered))
    return pending


# --- the folders an agent reads in ---------------------------------------------------------


def _real(path) -> str:
    """``path`` with its links resolved."""
    return os.path.realpath(str(path))


def _key(real: str) -> str:
    """``real`` as it is compared: where the file system takes two spellings
    for one name, they are one here too."""
    if sys.platform == "darwin":
        return unicodedata.normalize("NFC", real).casefold()
    return os.path.normcase(real)


def _within(key: str, folder: str) -> bool:
    return key == folder or key.startswith(folder.rstrip(os.sep) + os.sep)


class _Readable:
    """The local files whose contents an agent's session has unasked, as of
    now (made on the UI thread, asked from any)."""

    def __init__(self, app, req) -> None:
        sid = str(req.get("session") or "")
        own = (getattr(app, "_agent_folders", None) or {}).get(sid)
        agreed = (getattr(app, "_read_folders", None) or {}).get(sid, ())
        #: Everything below: the session's folder, and those agreed to.
        self.below = [_key(_real(p)) for p in ([own] if own else [])] + list(agreed)
        #: The files in them alone: a pane's folder, where the user went there.
        went = getattr(app, "_agent_went", ())
        pm = getattr(app, "pm", None)
        self.files_in = []
        for name in ("left_pane", "right_pane"):
            pane = getattr(pm, name, None)
            path = pane.get("path") if isinstance(pane, dict) else None
            if path is not None and _is_local(path) and str(path) not in went:
                self.files_in.append(_key(_real(path)))

    def file(self, real: str) -> bool:
        key = _key(real)
        return any(_within(key, f) for f in self.below) or os.path.dirname(key) in self.files_in

    def folder(self, real: str, *, below: bool = True) -> bool:
        key = _key(real)
        return any(_within(key, f) for f in self.below) or (not below and key in self.files_in)


def _local_read_allowed(app, req, paths, then, *, below: bool = True) -> Any:
    """Run ``then()`` once an agent's session may read the contents of the
    local ``paths`` (files, or folders searched, with those ``below`` them):
    the user agrees first, once for each folder that is neither the session's
    nor, for a file, one the user went to in a pane."""
    if not _is_agent(req):
        return then()
    readable = _Readable(app, req)
    for path in paths:
        if not _is_local(path):
            continue
        real = _real(path)
        is_folder = os.path.isdir(real)
        if readable.folder(real, below=below) if is_folder else readable.file(real):
            continue
        folder = real if is_folder else os.path.dirname(real)

        def agreed(folder=folder):
            sid = str(req.get("session") or "")
            app.__dict__.setdefault("_read_folders", {}).setdefault(sid, set()).add(_key(folder))
            return _local_read_allowed(app, req, paths, then, below=below)
        if getattr(app, "_terminal_handed_over", False):
            raise _Refused(f"{folder} is outside this session's folder, so the user has to "
                           f"agree to reading there, and XeFM is suspended until this shell "
                           f"exits (terminal mode): it cannot ask", SUSPENDED)
        return _ask_first(
            app, req, f"{_asker(app, req)} wants to read {_shown_to_user(real)}.\n\n"
            f"Allow it to read the files in {_shown_to_user(folder)}, and below, for the rest "
            f"of its session?", "Allow reading?", agreed,
            declined=f"the user did not allow reading in {folder}")
    return then()


def _open_to_read(app, req, path):
    """``path`` opened for reading. For an agent the file that was opened is
    checked, not its name: a link may have been changed since it was asked
    about."""
    if not _is_agent(req) or not _is_local(path):
        return path.open("rb")
    f = open(_real(path), "rb")
    try:
        final = _final_path(f.fileno())
        if final is not None and not _Readable(app, req).file(final):
            raise _Refused(f"{path} is not the file the user was asked about")
    except BaseException:
        f.close()
        raise
    return f


def _final_path(fd: int) -> str | None:
    """Where the open file ``fd`` is, or None where the system cannot say."""
    try:
        if sys.platform == "darwin":
            import fcntl
            return os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0"))
        if sys.platform == "win32":
            import ctypes
            import msvcrt
            from ctypes import wintypes as w
            get = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
            get.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
            get.restype = w.DWORD
            buf = ctypes.create_unicode_buffer(32768)
            if not get(msvcrt.get_osfhandle(fd), buf, len(buf), 0):
                return None
            name = buf.value
            if name.startswith("\\\\?\\UNC\\"):
                return "\\\\" + name[8:]
            return name[4:] if name.startswith("\\\\?\\") else name
        return os.readlink(f"/proc/self/fd/{fd}")
    except (OSError, AttributeError):
        return None


def _remote_read_allowed(app, req, paths, then, *, below: bool = True) -> Any:
    """Run ``then()`` once an agent's session may read ``paths``: those outside
    the local disk after the user agrees for the first of them, the local ones
    folder by folder (:func:`_local_read_allowed`). Returns an answer or a
    Pending."""
    far = [p for p in paths if not _is_local(p)]
    if not _is_agent(req):
        return then()
    work = then

    def then():
        return _local_read_allowed(app, req, paths, work, below=below)
    if not far:
        return then()
    allowed = app.__dict__.setdefault("_remote_read_sessions", set())
    sid = str(req.get("session"))
    if sid in allowed:
        return then()

    def agreed():
        allowed.add(sid)
        return then()
    return _ask_first(
        app, req, f"{_asker(app, req)} wants to read from {_shown_to_user(far[0])}.\n\n"
        f"Allow it to read places outside this computer's disk (servers, cloud "
        f"storage, archives) for the rest of its session?", "Allow reading?", agreed,
        declined="the user did not allow reading outside the local disk")


def _c_read(app, req):
    from xefm.path import Path
    path = Path(req["args"]["url"])
    limit = req["opts"].get("max-bytes") or READ_LIMIT

    def then():
        if not path.exists():
            raise _Refused(f"no such file: {path}", FAILED)
        if path.is_dir():
            raise _Refused(f"{path} is a directory (see xefmctl entries)", FAILED)
        with _open_to_read(app, req, path) as f:
            data = f.read(limit + 1)
        note = f"(only the first {limit} bytes)" if len(data) > limit else None
        text = data[:limit].decode("utf-8", errors="replace")
        return ok([{"path": str(path), "text": text}], **({"note": note} if note else {}))
    return _remote_read_allowed(app, req, [path], then)


def _c_fetch(app, req):
    from xefm.path import Path
    src = Path(req["args"]["url"])
    local = req["args"].get("local")

    def then():
        if not src.exists() or src.is_dir():
            raise _Refused(f"no such file: {src}", FAILED)
        dest = local or os.path.join(tempfile.mkdtemp(prefix="xefmctl-"),
                                     _file_name(src.name))
        with _open_to_read(app, req, src) as fin, open(dest, "wb") as fout:
            while True:
                chunk = fin.read(1 << 20)
                if not chunk:
                    break
                fout.write(chunk)
        return ok([{"path": dest, "source": str(src)}])

    def fetch():
        if not local:  # a folder of its own in the temporary folder
            return then()
        there = (" The file there is replaced." if os.path.lexists(local) else "")
        return _ask_first(
            app, req, f"{_asker(app, req)} wants to copy {_shown_to_user(src)} to "
            f"{_shown_to_user(local)}.{there}", "Allow fetch?", then,
            declined="the user did not allow writing that file")
    return _remote_read_allowed(app, req, [src], fetch)


def _file_name(name: str) -> str:
    """A name from anywhere (a server's, where a backslash or a colon is a
    letter like any other) as one that stays in the folder it is put in."""
    name = name.replace("\\", "/").rpartition("/")[2]
    name = "".join("_" if c in '<>:"|?*' or ord(c) < 32 else c for c in name)
    return name if name.strip(". ") else "file"


# --- showing ------------------------------------------------------------------------------


def _close_viewers_now(app) -> None:
    """Close what is open over the panes, viewers only, at once (no fade):
    what replaces them must not arrive while they are still leaving."""
    from xefm.dialog_geometry import no_motion
    with no_motion():
        for layer in list(app.panel.layer_children(app._screens.files.group)):
            if not is_viewer(layer):
                continue
            close = getattr(layer, "_close", None)
            if close is not None:
                close()
            if app.panel.has_layer(layer):
                app.panel.remove_layer(layer)


def _open_on_files(app, work) -> None:
    """Switch to the file manager, close its viewer, and open a new one."""
    screens = app._screens
    if screens.current is not screens.files:
        app._show_screen(screens.files)
    _close_viewers_now(app)
    with on_files(app):
        work()
    app.panel.render()


def _c_view(app, req):
    from xefm.path import Path
    target = Path(req["args"]["path"])
    if not target.exists():
        raise _Refused(f"no such file: {target}", FAILED)
    if target.is_dir():
        raise _Refused(f"{target} is a directory (use xefmctl pane cd)", FAILED)
    line = req["opts"].get("line")

    _open_on_files(app, lambda: app._user_ctx.view(target, line=line))
    return ok()


def _c_diff(app, req):
    from xefm.path import Path
    left, right = Path(req["args"]["left"]), Path(req["args"]["right"])
    for p in (left, right):
        if not p.exists():
            raise _Refused(f"no such file or directory: {p}", FAILED)
    if left.is_dir() != right.is_dir():
        raise _Refused("compare two files, or two folders", USAGE)
    if left.is_dir():
        from xefm.directory_diff_viewer import show_directory_diff_viewer
        _open_on_files(app, lambda: show_directory_diff_viewer(
            app.panel, left, right, show_hidden=app.flm.show_hidden,
            config=app.config, monitor=app.file_monitor))
    else:
        _open_on_files(app, lambda: app._user_ctx.diff(left, right))
    return ok()


def _c_show_markdown(app, req):
    from xefm.path import Path
    args = req["args"]
    if args.get("file") == "-":
        source = args.get("file_text") or ""
        title = req["opts"].get("title") or "xefmctl"
    else:
        path = Path(args["file"])
        if not path.exists():
            raise _Refused(f"no such file: {path}", FAILED)
        source = path.read_text(encoding="utf-8", errors="replace")
        title = req["opts"].get("title") or path.name
    _open_on_files(app, lambda: app._user_ctx.show_markdown(title, source))
    return ok()


# --- files ----------------------------------------------------------------------------------


def _write(app, req, verb: str, run, *, results: bool = False,
           ask_agent: str = "") -> Any:
    """A file operation, through the operation's own path: ``run(on_done)``
    starts it, with its confirmation, conflict dialog and progress. For an
    agent's session its confirmation is shown whatever ``CONFIRM_*`` says
    (the question the user answers is the operation's own, naming what and
    where), and the user is taken back to the agent's screen once it has
    ended or been declined. With --wait the answer is the outcome.

    ``results`` answers one item per :class:`ItemResult` (its path and status)
    rather than the items given. ``ask_agent`` is the question an agent's
    session is asked first, for a write with no confirmation of its own
    (tags)."""
    items = req["args"].get("source") or req["args"].get("path") or []
    wait = bool(req["opts"].get("wait"))
    agent = _is_agent(req)
    pending = Pending()
    came_from = [None]

    def finished(_ctx, outcome) -> None:
        if agent:
            back, came_from[0] = came_from[0], None
            _go_back(app, back)
        status = getattr(outcome, "status", "done")
        if status == "done" and results:
            rows = [dict({"path": str(r.source), "status": r.status},
                         **({"dest": str(r.dest)} if r.dest is not None else {}),
                         **({"errors": [m for _n, m in r.errors]} if r.errors else {}))
                    for r in (outcome.value or [])]
            bad = sum(1 for r in rows if r["status"] == "failed")
            answer = ok(rows, status=FAILED if bad else 0, outcome="done",
                        note=f"{verb}: {len(rows) - bad} item(s) done"
                             + (f", {bad} failed" if bad else ""))
        elif status == "done":
            answer = ok([{"path": p} for p in items], status=0, outcome="done",
                        note=f"{verb}: {len(items)} item(s) done")
        elif status == "cancelled":
            answer = ok([], status=FAILED, outcome="cancelled",
                        note=f"{verb}: the user cancelled it")
        else:
            error = getattr(outcome, "error", None)
            answer = ok([], status=FAILED, outcome=status,
                        note=f"{verb}: {status}" + (f" ({error})" if error else ""))
        pending.set(answer)

    def start():
        # The agent's copy, move or trash is confirmed in XeFM's own dialog,
        # which says who asks and starts with no button selected (#995).
        forced = dict(_ALWAYS_CONFIRM, AGENT_ASKING=_asker(app, req))
        with (_forced(app, forced) if agent else contextlib.nullcontext()):
            run(finished if (wait or agent) else None)

    def begin():
        if not (agent and ask_agent):
            start()
            return
        from xefm.user_api import TaskOutcome

        def answered(yes: bool) -> None:
            if not yes:
                finished(None, TaskOutcome("cancelled", []))
                return
            try:
                start()
            except Exception as exc:
                logger.error(f"xefmctl {verb} failed: {exc}")
                finished(None, TaskOutcome("failed", error=exc))
        app._user_ctx.confirm(_fit(app, f"{_asker(app, req)} wants to "
                                        f"{_shown_to_user(ask_agent)}."),
                              title=f"Allow {verb}?", on_result=answered)

    _, came_from[0] = _ui(app, req, begin)
    if wait:
        return pending
    return ok(outcome="started")


def _c_copy(app, req):
    _operands(app, req, "source")
    dest = req["opts"].get("to")
    if not dest:
        raise _Refused("where to? give --to DIR", USAGE)
    return _write(app, req, "copy", lambda on_done: app._user_ctx.copy(
        req["args"]["source"], dest, on_done=on_done))


def _c_move(app, req):
    _operands(app, req, "source")
    dest = req["opts"].get("to")
    if not dest:
        raise _Refused("where to? give --to DIR", USAGE)
    return _write(app, req, "move", lambda on_done: app._user_ctx.move(
        req["args"]["source"], dest, on_done=on_done))


def _c_trash(app, req):
    _operands(app, req, "path")
    return _write(app, req, "trash", lambda on_done: app._user_ctx.trash(
        req["args"]["path"], on_done=on_done))


def _c_delete(app, req):
    if _is_agent(req):
        raise _Refused("an AI agent's session may not delete for good; use xefmctl "
                       "trash, which the user can undo")
    _operands(app, req, "path")
    return _write(app, req, "delete", lambda on_done: app._user_ctx.delete(
        req["args"]["path"], on_done=on_done))


def _c_rename(app, req):
    plan = req["opts"].get("plan")
    if plan is None:
        raise _Refused('which names? give --plan FILE (a JSON list of {"path", "name"})',
                       USAGE)
    req["args"]["path"] = [p["path"] for p in plan]
    pairs = [(p["path"], p["name"]) for p in plan]
    try:
        return _write(app, req, "rename", lambda on_done: app._user_ctx.rename(
            pairs, on_done=on_done), results=True)
    except ValueError as exc:
        raise _Refused(str(exc), USAGE) from None


def _tag_names(req) -> list[str]:
    return [req["args"]["name"], *(req["opts"].get("tag") or [])]


def _tag_items(app, req) -> list[str]:
    """The items to tag, refused before anyone is asked when they have no
    tag storage (or two)."""
    from xefm.path import Path
    items = _operands(app, req, "path")
    if app._tag_store_of([Path(i) for i in items]) is None:
        raise _Refused("tags are not supported for these items (or they are on "
                       "different storages)", FAILED)
    return items


def _c_tag_list(app, req):
    return ok([{"name": t.name, "color": t.color or ""} for t in app._user_ctx.tags()])


def _c_tag_add(app, req):
    items = _tag_items(app, req)
    names = _tag_names(req)
    color = req["opts"].get("color")
    what = f"add the tag(s) {', '.join(names)} to {len(items)} item(s)"
    try:
        return _write(app, req, "tag", lambda on_done: app._user_ctx.add_tags(
            items, names, color=color, on_done=on_done), results=True, ask_agent=what)
    except ValueError as exc:
        raise _Refused(str(exc), FAILED) from None


def _c_tag_remove(app, req):
    items = _tag_items(app, req)
    names = _tag_names(req)
    what = f"remove the tag(s) {', '.join(names)} from {len(items)} item(s)"
    try:
        return _write(app, req, "untag", lambda on_done: app._user_ctx.remove_tags(
            items, names, on_done=on_done), results=True, ask_agent=what)
    except ValueError as exc:
        raise _Refused(str(exc), FAILED) from None


def _c_attribute_list(app, req):
    return ok([{"name": a.name, "label": a.label, "type": a.type, "compute": a.compute,
                "source": a.source} for a in app._user_ctx.attributes()])


def _plain(value):
    """An attribute value as JSON can carry it."""
    from xefm.user_api import TagInfo
    if isinstance(value, TagInfo):
        return {"name": value.name, "color": value.color}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _shown(value) -> str:
    if isinstance(value, list):
        return ",".join(v["name"] if isinstance(v, dict) else str(v) for v in value)
    return "" if value is None else str(value)


def _c_attribute_get(app, req):
    from xefm.path import Path
    items = [Path(p) for p in _operands(app, req, "path")]
    wanted = req["opts"].get("attributes")
    names = [n.strip() for n in wanted.split(",") if n.strip()] if wanted else None
    try:
        found = app._user_ctx.get_attributes(items, names)
    except ValueError as exc:
        raise _Refused(str(exc), USAGE) from None

    def produce(cancel):
        for row in found:
            if cancel.is_set():
                return
            values = {k: _plain(v) for k, v in row["values"].items()}
            text = "\t".join([str(row["path"])]
                             + [f"{k}={_shown(v)}" for k, v in values.items()])
            yield row["path"], {"path": str(row["path"]), "values": values, "text": text}
    return _stream(app, req, produce, mode="list")


def _c_pane_pick(app, req):
    api = _pane_api(app, req)
    pending = Pending()
    screens = app._screens
    came_from = None
    if screens.current is not screens.files:
        came_from = screens.current
        app._show_screen(screens.files)
    prompt = req["opts"].get("prompt") or "Select items"
    if _is_agent(req):
        prompt = f"{_asker(app, req)}: {prompt}"

    def result(entries) -> None:
        _go_back(app, came_from)
        if entries is None:
            pending.set(ok([], status=FAILED, note="cancelled"))
        else:
            pending.set(ok([_entry(e) for e in entries]))
    api.pick(prompt=prompt, on_result=result)
    return pending


# --- asking the user ----------------------------------------------------------------------------


def _ask(app, req, open_dialog) -> Pending:
    """Open a question on the file manager's screen; the answer waits for the
    user, who is taken back to the asking screen once they answer."""
    pending = Pending()
    came_from = [None]

    def answer(result: dict) -> None:
        _go_back(app, came_from[0])
        pending.set(result)

    _, came_from[0] = _ui(app, req, lambda: open_dialog(answer))
    return pending


def _c_confirm(app, req):
    def open_dialog(answer):
        prompt = req["args"]["prompt"]
        if _is_agent(req):
            prompt = _fit(app, prompt)
        app._user_ctx.confirm(prompt, title=req["opts"].get("title") or "Confirm",
                              on_result=lambda yes: answer(ok(
                                  [{"answer": "yes" if yes else "no"}],
                                  status=0 if yes else FAILED)))
    return _ask(app, req, open_dialog)


def _c_choose(app, req):
    items = req["args"]["item"]

    def open_dialog(answer):
        def picked(index):
            if index is None:
                answer(ok([], status=FAILED, note="cancelled"))
            else:
                answer(ok([{"answer": items[index], "index": index}]))
        app._user_ctx.choose(req["args"]["title"], items, on_result=picked)
    return _ask(app, req, open_dialog)


def _c_input(app, req):
    def open_dialog(answer):
        app._user_ctx.input(req["args"]["prompt"], req["opts"].get("default") or "",
                            title=req["opts"].get("title") or "",
                            on_accept=lambda text: answer(ok([{"answer": text}])),
                            on_cancel=lambda: answer(ok([], status=FAILED, note="cancelled")))
    return _ask(app, req, open_dialog)


def _c_message(app, req):
    text = req["args"]["text"]
    prefix = f"[{_asker(app, req)}] " if _is_agent(req) else ""
    app._user_ctx.message(prefix + text)
    app.panel.render()
    return ok()


# --- actions ----------------------------------------------------------------------------------


def _action_records(app) -> list[dict]:
    from xefm import actions as A
    from xefm import extensions as ext
    keys = app.keys
    out = []
    for a in A.registry.actions(A.FILER):
        source = getattr(a, "source", "builtin")
        package = ext.package_of(a.func) if a.func is not None else None
        if package is not None:
            source = f"extension {package.id}"
        elif source == "user":
            source = "config.py"
        out.append({
            "name": a.name,
            "description": a.description,
            "details": getattr(a, "details", "") or "",
            "context": a.context,
            "keys": list(keys.get_keys_for_action(a.name, A.FILER)[0]),
            "source": source,
            "selection": getattr(a, "selection", "any"),
            "_package": package,
        })
    return out


def _c_action_list(app, req):
    return ok([{k: v for k, v in r.items() if k not in ("details", "_package")}
               for r in _action_records(app)])


def _c_action_show(app, req):
    name = req["args"]["name"]
    record = next((r for r in _action_records(app) if r["name"] == name), None)
    if record is None:
        raise _Refused(f"no action {name!r} (see xefmctl action list)", FAILED)
    keys = ", ".join(record["keys"]) or "(no key)"
    text = (f"{record['name']}: {record['description']}\n"
            f"context: {record['context']}   keys: {keys}   from: {record['source']}   "
            f"selection: {record['selection']}")
    if record["details"]:
        text += "\n\n" + record["details"]
    package = record.pop("_package")
    guide = package.agent_guide if package is not None else None
    if guide is not None and guide.is_file():
        try:
            record["guide"] = guide.read_text(encoding="utf-8")
            text += f"\n\n--- {package.id}'s guide for agents ---\n\n" + record["guide"]
        except OSError as exc:
            logger.warning(f"Could not read {guide}: {exc}")
    return ok([dict(record, text=text)])


def _ext_layout():
    from xefm import extensions as ext
    from xefm.config import config_manager
    return ext.Layout(config_manager.config_dir)


def _lines(lines, **extra) -> dict:
    """Lines of a CLI's output as items, one ``text`` each."""
    return ok([{"text": line} for line in lines], **extra)


def _c_ext_list(app, req):
    from xefm import extension_cli
    layout = _ext_layout()
    rows = extension_cli.list_rows(layout)
    return ok(rows, **({} if rows else {"note": f"no extension packages in {layout.packages}"}))


def _c_ext_check(app, req):
    from xefm import extension_cli, extensions as ext
    from xefm.path import Path
    path = req["args"]["path"]
    if not _is_local(Path(path)):
        raise _Refused(f"{path}: give a folder or a .zip on this computer's disk", USAGE)

    def then():
        with tempfile.TemporaryDirectory(prefix="xefm-ext-") as tmp:
            try:
                root = ext.fetch(path, _FsPath(tmp))
            except ext.InstallError as exc:
                raise _Refused(str(exc), FAILED) from None
            lines, bad = extension_cli.check_lines(
                root, _ext_layout(), stable_only=bool(req["opts"].get("stable-only")),
                source=path)
        return _lines(lines, status=FAILED if bad else 0)
    return _remote_read_allowed(app, req, [Path(path)], then)


def _c_ext_install(app, req):
    source = req["args"]["source"]
    if not source.startswith(("github:", "https://")) and not os.path.exists(source):
        raise _Refused(f"no such file or folder: {source}", FAILED)
    agent = _is_agent(req)
    pending = Pending()
    came_from = [None]

    def around(show):
        _, came_from[0] = _ui(app, req, show)

    def done(outcome):
        if agent:
            _go_back(app, came_from[0])
        status = outcome["status"]
        if status == "busy":
            pending.set(refuse(outcome["message"], BUSY))
        elif status == "installed":
            pending.set(ok([{"id": outcome["id"], "version": outcome["version"],
                             "text": outcome["message"]}], status=0, outcome=status))
        else:
            pending.set(_lines(outcome.get("problems") or [], status=FAILED,
                               outcome=status, note=outcome["message"]))

    app._fetch_extension(source, done=done, around=around,
                         asker=_asker(app, req) if agent else None)
    if req["opts"].get("wait"):
        return pending
    return ok(note="Install Extension: XeFM asks the user once it has the package "
                   "(--wait waits for the answer)")


def _c_keys(app, req):
    from xefm import keymap_presets, keys_cli
    from xefm.actions import CONTEXTS
    from xefm.config import config_manager
    names = req["args"].get("name") or []
    context = req["opts"].get("context")
    if context and context not in CONTEXTS:
        raise _Refused(f"no context {context!r} ({', '.join(CONTEXTS)})", USAGE)
    wanted, problem = keys_cli._matcher(names)
    if problem:
        raise _Refused(problem, USAGE)
    from xefm.user_api import is_desktop_mode
    backend = "gui" if is_desktop_mode() else "tui"
    # What this XeFM loaded and uses: nothing is loaded again (that would
    # register the user's actions a second time).
    report = keys_cli.check_config(app.config, config_manager)
    keys_cli.check_bindings(report, app.config, backend)
    keys_cli.add_contexts(report, app.keys)
    extensions = config_manager.extension_report
    read = {"config": config_manager.config_file,
            "preset": app._keymap_preset or keymap_presets.FALLBACK,
            "preset_source": "in use" if app._keymap_preset else
                             "none chosen yet - XeFM asks at its next launch",
            "extensions": list(extensions.loaded) if extensions else []}
    lines, status = keys_cli.render(report, read, wanted, names, context, backend)
    return _lines(lines, status=status)


def _skill_row(skill) -> dict:
    return {"name": skill.path.name, "ok": skill.ok, "path": str(skill.path),
            "description": " ".join(skill.description.split()),
            "problems": skill.problems,
            "state": "ok" if skill.ok else "left out: " + "; ".join(skill.problems)}


def _c_skill_list(app, req):
    from xefm import agent_skills
    return ok([_skill_row(s) for s in agent_skills.scan()],
              folder=str(agent_skills.skills_dir()))


def _c_skill_check(app, req):
    from xefm import agent_skills
    names = req["args"].get("name") or []
    root = agent_skills.skills_dir()
    for name in names:
        # A name, not a path: only the folder sessions are handed is checked.
        if not name or name in (".", "..") or any(c in name for c in "/\\:"):
            raise _Refused(f"{name!r} is not a skill's name (a folder in {root})", USAGE)
    skills = [agent_skills.read(root / n) for n in names] or agent_skills.scan()
    rows = [_skill_row(s) for s in skills]
    bad = [r for r in rows if not r["ok"]]
    note = (f"{len(bad)} of {len(rows)} skill(s) fail the check" if bad
            else "" if rows else f"no skills in {root}")
    return ok(rows, status=FAILED if bad else 0, folder=str(root),
              **({"note": note} if note else {}))


def _c_invoke(app, req):
    from xefm import actions as A
    name = req["args"]["name"]
    action = A.registry.resolve(A.FILER, name)
    if action is None:
        raise _Refused(f"no action {name!r} (see xefmctl action list)", FAILED)
    agent = _is_agent(req)
    if agent and name in AGENT_DENIED_ACTIONS:
        raise _Refused(f"an AI agent's session may not run {name}")
    if req["opts"].get("pane"):
        api = _pane_api(app, req)
        if not api.is_active:
            api.activate()

    def run():
        with (_forced(app) if agent else contextlib.nullcontext()):
            app._user_ctx.invoke(name)

    def then():
        _ui(app, req, run)
        app.panel.render()
        return ok()
    what = AGENT_ASKED_ACTIONS.get(name)
    if getattr(action, "source", "builtin") != "builtin":
        # Code of the user's or an extension's: what it does is not known.
        what = f"run the action {_shown_to_user(name)} ({_shown_to_user(action.description)})"
    if what is None:
        return then()
    items = _opened_items(app, name) if agent else []
    listed = "".join(f"\n- {_shown_to_user(p)}" for p in items)
    return _ask_first(app, req, f"{_asker(app, req)} wants to "
                      f"{what}.{chr(10) if listed else ''}{listed}",
                      f"Allow {name}?", then, declined=f"the user did not allow {name}")


#: The most items a question lists; more are refused.
ASK_ITEMS = 20


def _opened_items(app, name: str) -> list[str]:
    """What ``open_with_os`` or ``open_items_with_os`` would open, for the
    question."""
    if name not in ("open_with_os", "open_items_with_os"):
        return []
    pane = app._user_ctx.pane
    if name == "open_with_os":
        entries = [pane.focused] if pane.focused is not None else []
    else:
        entries = pane.selected_or_focused()
    if len(entries) > ASK_ITEMS:
        raise _Refused(f"too many items to show the user, who has to agree to opening "
                       f"them (at most {ASK_ITEMS})")
    return [str(e.path) for e in entries]


# --- screens and terminal sessions ---------------------------------------------------------------


def _c_screen_list(app, req):
    current = app._screens.current
    return ok([{"marker": "*" if sc is current else " ", "id": sc.id, "kind": sc.kind,
                "label": app._screen_label(sc), "shown": sc is current}
               for sc in app._screens.recent()])


def _c_screen_show(app, req):
    if not _desktop():
        raise _Refused("screens are only in the desktop app", FAILED)
    target = app._screens.by_id(str(req["args"]["id"]))
    if target is None:
        raise _Refused(f"no screen {req['args']['id']!r} (see xefmctl screen list)", FAILED)
    app._show_screen(target)
    return ok()


def _c_session_list(app, req):
    here = str(req.get("session") or "")
    return ok([{"marker": "*" if str(s.id) == here else " ", "id": str(s.id),
                "name": s.name, "kind": s.kind, "state": s.state,
                "directory": s.directory, "cwd": s.cwd, "activity": s.activity}
               for s in app._sessions])


def _c_session_start(app, req):
    if not _desktop():
        raise _Refused("terminal sessions are only in the desktop app", FAILED)
    command = req["args"].get("command") or None
    opts = req["opts"]

    def then():
        with _session_policy(app, str(req.get("policy") or USER)):
            session = app._user_ctx.start_terminal_session(
                command, cwd=opts.get("cwd"), name=opts.get("name"),
                show=not opts.get("hidden"))
        return ok([{"id": str(session.id), "name": session.name}])
    if not _is_agent(req):
        return then()
    what = f"run this in a new terminal session:\n\n{_shown_to_user(_line(command))}" \
        if command else "start a shell in a new terminal session."
    where = f"\n\nin {_shown_to_user(opts['cwd'])}" if opts.get("cwd") else ""
    return _ask_first(app, req, f"{_asker(app, req)} wants to {what}{where}",
                      "Allow terminal session?", then,
                      declined="the user did not allow the terminal session")


def _line(argv: list[str]) -> str:
    if os.name == "nt":
        import subprocess
        return subprocess.list2cmdline(argv)
    import shlex
    return shlex.join(argv)


@contextlib.contextmanager
def _session_policy(app, policy: str):
    """Sessions started while held get ``policy``: one an agent starts is as
    restricted as the agent."""
    before = getattr(app, "_new_session_policy", USER)
    app._new_session_policy = policy
    try:
        yield
    finally:
        app._new_session_policy = before


def _c_session_close(app, req):
    sid = str(req["args"]["id"])
    session = next((s for s in app._sessions if str(s.id) == sid), None)
    if session is None:
        raise _Refused(f"no terminal session {sid!r} (see xefmctl terminal-session list)",
                       FAILED)
    if not _is_agent(req) or sid == str(req.get("session")):
        app._close_session(session)
        return ok()

    def open_dialog(answer):
        def result(yes):
            if yes and session in list(app._sessions):
                app._close_session(session)
            answer(ok(status=0 if yes else FAILED,
                      note=None if yes else "the user kept the session"))
        app._user_ctx.confirm(_fit(app, f"{_asker(app, req)} wants to end the terminal "
                                        f"session {_shown_to_user(session.name)}."), title="End session?", on_result=result)
    return _ask(app, req, open_dialog)


_HANDLERS = {
    "state": _c_state,
    "pane path": _c_pane_path, "pane entries": _c_pane_entries,
    "pane focused": _c_pane_focused, "pane selected": _c_pane_selected,
    "pane cd": _c_pane_cd, "pane select": _c_pane_select, "pane unselect": _c_pane_unselect,
    "pane open-list": _c_pane_open_list, "pane refresh": _c_pane_refresh,
    "pane activate": _c_pane_activate, "pane pick": _c_pane_pick,
    "entries": _c_entries, "find-files": _c_find_files, "find-in-files": _c_find_in_files,
    "index-search": _c_index_search, "find-similar": _c_find_similar,
    "path-scheme list": _c_path_scheme_list, "read": _c_read, "fetch": _c_fetch,
    "view": _c_view, "diff": _c_diff, "show-markdown": _c_show_markdown,
    "copy": _c_copy, "move": _c_move, "trash": _c_trash, "delete": _c_delete,
    "rename": _c_rename, "tag list": _c_tag_list, "tag add": _c_tag_add,
    "tag remove": _c_tag_remove, "attribute list": _c_attribute_list,
    "attribute get": _c_attribute_get,
    "confirm": _c_confirm, "choose": _c_choose, "input": _c_input, "message": _c_message,
    "action list": _c_action_list, "action show": _c_action_show, "invoke": _c_invoke,
    "skill list": _c_skill_list, "skill check": _c_skill_check,
    "ext list": _c_ext_list, "ext check": _c_ext_check, "ext install": _c_ext_install,
    "keys": _c_keys,
    "screen list": _c_screen_list, "screen show": _c_screen_show,
    "terminal-session list": _c_session_list, "terminal-session start": _c_session_start,
    "terminal-session close": _c_session_close,
}
