"""What each ``xefmctl`` command does, on XeFM's side (#900, #951, #952).

:mod:`xefm.remote_server` receives a request on its listener thread and hands
it to :func:`handle`. The commands are described in
:mod:`xefm.remote_commands`; this module carries them out:

- **Through the public API.** A command is an ``ActionContext`` call wherever
  one exists (``ctx.pane.cd``, ``ctx.copy``, ``ctx.confirm``, ``ctx.invoke``),
  so ``xefmctl`` can do nothing an action cannot.
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

Reads of the panes are answered even while terminal mode has its terminal
handed over (the UI thread is parked in the child's wait and nothing else
touches them); everything else waits until the user is back.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import tempfile
import threading
from typing import Any

from xefm import remote_commands as T
from xefm.log_manager import getLogger

logger = getLogger("Remote")

USER = "user"
AGENT = "agent"

#: Seconds a request waits for the UI thread before reporting XeFM busy
#: (under remote_cli.TIMEOUT, so the answer still reaches the client).
UI_WAIT = 8.0

#: Exit statuses (``xefmctl``'s, documented in the skill's reference).
FAILED, USAGE, UNREACHABLE, BUSY, REFUSED = 1, 2, 3, 4, 5

#: Actions an agent's session may not invoke.
AGENT_DENIED_ACTIONS = frozenset({"delete_permanently", "quit", "quit_app"})

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
        self.answer: dict | None = None

    def set(self, answer: dict) -> None:
        if not self._event.is_set():
            self.answer = answer
            self._event.set()

    def wait(self) -> dict:
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
            return refuse("XeFM is waiting for this shell to exit; run it after you "
                          "return", BUSY)
        # The UI thread is parked in the child's wait (_run_in_terminal):
        # nothing else reads or changes the panes until it returns.
        req["opts"].pop("show", None)
        return _finish(_answer(app, cmd, req))
    done = threading.Event()
    box: dict = {}

    def run() -> None:
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
    if not done.wait(UI_WAIT):
        return refuse("XeFM is busy; try again", BUSY)
    return _finish(box["answer"])


def _finish(answer):
    if isinstance(answer, Pending):
        return answer.wait()
    return answer


def _answer(app, cmd, req):
    """The command's work, on the UI thread."""
    try:
        if cmd.effect != T.READ:
            _gate(app, cmd, req)
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


def _ui(app, work):
    """Do ``work()`` on the file manager's screen and take the user there if
    it opened something. Returns ``(result, came_from)``: the screen the user
    was on, for a question to take them back to, or None."""
    before = list(app.panel.layer_children(app._screens.files.group))
    with on_files(app):
        result = work()
    came_from = _bring_user(app, before)
    return result, came_from


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
    item = {
        "panes": panes, "active": active,
        "screen": {"id": current.id, "kind": current.kind,
                   "label": app._screen_label(current)},
        "files_screen": "panes" if top is None else over,
        "desktop": _desktop(),
        "text": "\n".join(lines),
    }
    return ok([item])


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


def _roots(app, req, key: str = "url") -> list:
    from xefm.path import Path
    urls = req["args"].get(key)
    if isinstance(urls, str):
        urls = [urls]
    if not urls:
        return [_pane_api(app, req).path]
    return [Path(u) for u in urls]


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
    if mode in ("filename", "content", "index") and root is not None:
        app._feed_search_results(mode, found, root, query)
    else:
        api.open_list([str(p) for p in found], title=req["opts"].get("title") or "xefmctl")
    app.panel.render()


def _c_entries(app, req):
    from xefm import path as xpath
    from xefm import tree_walk
    roots = _roots(app, req)
    recursive = bool(req["opts"].get("recursive"))
    depth = req["opts"].get("depth")

    def produce(cancel):
        for root in roots:
            if not root.exists():
                raise _Refused(f"no such directory: {root}", FAILED)
            if not root.is_dir():
                raise _Refused(f"{root} is not a directory", FAILED)
            base = len(_parts(root))
            if recursive:
                def descend(entry, attrs):
                    if not attrs.get("is_dir") or attrs.get("is_link"):
                        return False
                    return depth is None or len(_parts(entry)) - base < depth
                pairs = tree_walk.walk(root, cancel, descend)
            else:
                pairs = iter(xpath.listdir_attrs(root))
            for entry, attrs in pairs:
                if cancel.is_set():
                    return
                yield entry, {"path": str(entry), "name": entry.name,
                              "is_dir": bool(attrs.get("is_dir")),
                              "size": attrs.get("size"), "mtime": attrs.get("mtime")}
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
                yield hit, {"path": str(hit["path"]), "line": hit["line"],
                            "text": hit["text"]}
    return _stream(app, req, produce, mode="content", query=query, root=roots[0])


def _c_index_search(app, req):
    from xefm import os_index
    why = os_index.unavailable()
    if why:
        raise _Refused(why, FAILED)
    root = (req["args"].get("url") or str(_pane_api(app, req).path))
    query = req["args"]["query"]

    def produce(cancel):
        for p in app._iter_index_matches(str(root), query, cancel, {}):
            yield p, {"path": str(p)}
    from xefm.path import Path
    return _stream(app, req, produce, mode="index", query=query, root=Path(str(root)))


def _is_local(path) -> bool:
    from xefm import path_schemes
    return not path_schemes.is_uri(str(path))


def _remote_read_allowed(app, req, path, then) -> Any:
    """Run ``then()`` once an agent's session may read ``path``: at once for
    a local path or a session already allowed; after the user agrees for the
    first read outside the local disk. Returns an answer or a Pending."""
    if not _is_agent(req) or _is_local(path):
        return then()
    allowed = app.__dict__.setdefault("_remote_read_sessions", set())
    sid = str(req.get("session"))
    if sid in allowed:
        return then()
    pending = Pending()
    who = _asker(app, req)

    def answered(yes: bool) -> None:
        _go_back(app, came_from[0])
        if not yes:
            pending.set(refuse("the user did not allow reading outside the local disk",
                               FAILED))
            return
        allowed.add(sid)
        try:
            pending.set(then())
        except _Refused as exc:
            pending.set(refuse(str(exc), exc.code))
        except Exception as exc:
            pending.set(refuse(str(exc), FAILED))

    came_from = [None]
    _, came_from[0] = _ui(app, lambda: app._user_ctx.confirm(
        f"{who} wants to read from {path}.\n\nAllow it to read places outside this "
        f"computer's disk (servers, cloud storage, archives) for the rest of its "
        f"session?", title="Allow reading?", on_result=answered))
    return pending


def _c_read(app, req):
    from xefm.path import Path
    path = Path(req["args"]["url"])
    limit = req["opts"].get("max-bytes") or READ_LIMIT

    def then():
        if not path.exists():
            raise _Refused(f"no such file: {path}", FAILED)
        if path.is_dir():
            raise _Refused(f"{path} is a directory (see xefmctl entries)", FAILED)
        with path.open("rb") as f:
            data = f.read(limit + 1)
        note = f"(only the first {limit} bytes)" if len(data) > limit else None
        text = data[:limit].decode("utf-8", errors="replace")
        return ok([{"path": str(path), "text": text}], **({"note": note} if note else {}))
    return _remote_read_allowed(app, req, path, then)


def _c_fetch(app, req):
    from xefm.path import Path
    src = Path(req["args"]["url"])
    local = req["args"].get("local")

    def then():
        if not src.exists() or src.is_dir():
            raise _Refused(f"no such file: {src}", FAILED)
        if local:
            dest = local
        else:
            folder = tempfile.mkdtemp(prefix="xefmctl-")
            dest = os.path.join(folder, src.name or "file")
        with src.open("rb") as fin, open(dest, "wb") as fout:
            while True:
                chunk = fin.read(1 << 20)
                if not chunk:
                    break
                fout.write(chunk)
        return ok([{"path": dest, "source": str(src)}])
    return _remote_read_allowed(app, req, src, then)


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


def _write(app, req, verb: str, run) -> Any:
    """A file operation, through the operation's own path: ``run(on_done)``
    starts it, with its confirmation, conflict dialog and progress. For an
    agent's session its confirmation is shown whatever ``CONFIRM_*`` says
    (the question the user answers is the operation's own, naming what and
    where), and the user is taken back to the agent's screen once it has
    ended or been declined. With --wait the answer is the outcome."""
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
        if status == "done":
            answer = ok([{"path": p} for p in items], status=0, outcome="done")
        elif status == "cancelled":
            answer = ok([], status=FAILED, outcome="cancelled",
                        note=f"{verb}: the user cancelled it")
        else:
            error = getattr(outcome, "error", None)
            answer = ok([], status=FAILED, outcome=status,
                        note=f"{verb}: {status}" + (f" ({error})" if error else ""))
        pending.set(answer)

    def begin():
        with (_forced(app, _ALWAYS_CONFIRM) if agent else contextlib.nullcontext()):
            run(finished if (wait or agent) else None)

    _, came_from[0] = _ui(app, begin)
    if wait:
        return pending
    return ok(outcome="started")


def _c_copy(app, req):
    dest = req["opts"].get("to")
    if not dest:
        raise _Refused("where to? give --to DIR", USAGE)
    return _write(app, req, "copy", lambda on_done: app._user_ctx.copy(
        req["args"]["source"], dest, on_done=on_done))


def _c_move(app, req):
    dest = req["opts"].get("to")
    if not dest:
        raise _Refused("where to? give --to DIR", USAGE)
    return _write(app, req, "move", lambda on_done: app._user_ctx.move(
        req["args"]["source"], dest, on_done=on_done))


def _c_trash(app, req):
    return _write(app, req, "trash", lambda on_done: app._user_ctx.trash(
        req["args"]["path"], on_done=on_done))


def _c_delete(app, req):
    if _is_agent(req):
        raise _Refused("an AI agent's session may not delete for good; use xefmctl "
                       "trash, which the user can undo")
    return _write(app, req, "delete", lambda on_done: app._user_ctx.delete(
        req["args"]["path"], on_done=on_done))


# --- asking the user ----------------------------------------------------------------------------


def _ask(app, req, open_dialog) -> Pending:
    """Open a question on the file manager's screen; the answer waits for the
    user, who is taken back to the asking screen once they answer."""
    pending = Pending()
    came_from = [None]

    def answer(result: dict) -> None:
        _go_back(app, came_from[0])
        pending.set(result)

    _, came_from[0] = _ui(app, lambda: open_dialog(answer))
    return pending


def _c_confirm(app, req):
    def open_dialog(answer):
        app._user_ctx.confirm(req["args"]["prompt"], title=req["opts"].get("title") or "Confirm",
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


def _c_invoke(app, req):
    from xefm import actions as A
    name = req["args"]["name"]
    if A.registry.resolve(A.FILER, name) is None:
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
    _ui(app, run)
    app.panel.render()
    return ok()


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
    session = app._user_ctx.start_terminal_session(
        command, cwd=opts.get("cwd"), name=opts.get("name"), show=not opts.get("hidden"))
    return ok([{"id": str(session.id), "name": session.name}])


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
        app._user_ctx.confirm(f"{_asker(app, req)} wants to end the terminal session "
                              f"{session.name}.", title="End session?", on_result=result)
    return _ask(app, req, open_dialog)


_HANDLERS = {
    "state": _c_state,
    "pane path": _c_pane_path, "pane entries": _c_pane_entries,
    "pane focused": _c_pane_focused, "pane selected": _c_pane_selected,
    "pane cd": _c_pane_cd, "pane select": _c_pane_select, "pane unselect": _c_pane_unselect,
    "pane open-list": _c_pane_open_list, "pane refresh": _c_pane_refresh,
    "pane activate": _c_pane_activate,
    "entries": _c_entries, "find-files": _c_find_files, "find-in-files": _c_find_in_files,
    "index-search": _c_index_search, "read": _c_read, "fetch": _c_fetch,
    "view": _c_view, "diff": _c_diff, "show-markdown": _c_show_markdown,
    "copy": _c_copy, "move": _c_move, "trash": _c_trash, "delete": _c_delete,
    "confirm": _c_confirm, "choose": _c_choose, "input": _c_input, "message": _c_message,
    "action list": _c_action_list, "action show": _c_action_show, "invoke": _c_invoke,
    "screen list": _c_screen_list, "screen show": _c_screen_show,
    "terminal-session list": _c_session_list, "terminal-session start": _c_session_start,
    "terminal-session close": _c_session_close,
}
