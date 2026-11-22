"""The xefmctl commands left from #952 (#962), and the public API they mirror.

The rule they all follow: where an action takes its items from the pane, the
API and xefmctl are told them - any number, anywhere XeFM can go - and do
with each what the action does: a folder is searched below, a file is
itself. ``--from pane|selection`` takes the items from the pane the same way
for every command that takes items."""

import json
import os
import shlex
import sys
import threading
from types import SimpleNamespace

import pytest

from xefm import attributes, remote_cli, remote_commands, remote_dispatch, tree_walk
from xefm import user_api
from xefm.path import Path
from xefm.user_api import ActionContext, PaneApi, TaskOutcome


# --- fixtures -------------------------------------------------------------------------

def _app(tmp_path, *, virtual=None, selected=("a",), focused=1):
    """Two panes over real folders: left lists a, b, d and the folder sub."""
    left_dir = tmp_path / "L"
    left_dir.mkdir()
    for name in ("a", "b", "d"):
        # Bytes, not text: Windows would write "\r\n" and change the sizes.
        (left_dir / name).write_bytes(f"{name} needle\n".encode())
    (left_dir / "sub").mkdir()
    (left_dir / "sub" / "deep.txt").write_bytes(b"deep needle\n")
    files = [Path(str(left_dir / n)) for n in ("a", "b", "d", "sub")]
    info = {str(files[3]): {"is_dir": True}}
    left = {"path": Path(str(left_dir)), "files": files, "file_info": info,
            "selected_files": {str(left_dir / n) for n in selected},
            "focused_index": focused}
    if virtual:
        left["virtual"] = virtual
    right = {"path": Path(str(tmp_path)), "files": [], "selected_files": set(),
             "focused_index": 0}
    app = SimpleNamespace(logged=[], _terminal_handed_over=False, later=[])
    app.pm = SimpleNamespace(active_pane="left", left_pane=left, right_pane=right)
    app.pane = lambda name: left if name == "left" else right
    app._sessions = []
    app.log_info = app.logged.append
    app._call_later = app.later.append
    app.flm = SimpleNamespace(show_hidden=False)
    app.config = SimpleNamespace()
    app._screens = SimpleNamespace(files=SimpleNamespace(group="files"))
    app._screens.current = app._screens.files
    app.panel = SimpleNamespace(layer_children=lambda g: [], default_layer_parent=None,
                                set_default_layer_parent=lambda p: None,
                                has_layer=lambda p: True, render=lambda: None)
    from xefm.app import XeFMApp
    app._iter_filename_matches = lambda *a, **k: XeFMApp._iter_filename_matches(app, *a, **k)
    app._iter_content_matches = lambda *a, **k: XeFMApp._iter_content_matches(app, *a, **k)
    app._user_ctx = ActionContext(app)
    return app, left_dir


def _q(path) -> str:
    """A path quoted for :func:`_ask`'s command line. ``shlex.split`` is POSIX:
    unquoted, a Windows path loses its backslashes. (xefmctl itself gets its
    arguments from the OS, already split.)"""
    return shlex.quote(str(path))


def _ask(app, line, stdin=None, **extra):
    req = remote_cli.parse(shlex.split(line), stdin)
    req.update(extra)
    cmd = remote_commands.find(req["cmd"].split())[0]
    return remote_dispatch._answer(app, cmd, req)


def _items(answer):
    if isinstance(answer, dict):
        return answer["items"]
    out = []
    for a in answer:
        assert a["ok"], a
        out += a["items"]
    return out


def _names(items):
    return sorted(os.path.basename(i["path"]) for i in items)


# --- a root someone named: a folder is searched, a file is itself -------------------------

def test_walk_root_takes_a_file_as_itself(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "g").write_text("y")
    cancel = threading.Event()
    always = lambda e, a: True
    [(entry, attrs)] = list(tree_walk.walk_root(Path(str(tmp_path / "f.txt")), cancel, always))
    assert entry.name == "f.txt" and attrs["explicit"] and not attrs["is_dir"]
    assert [e.name for e, _a in tree_walk.walk_root(Path(str(tmp_path / "d")), cancel,
                                                    always)] == ["g"]
    assert list(tree_walk.walk_root(Path(str(tmp_path / "gone")), cancel, always)) == []


def test_find_files_and_find_in_files_take_a_file_root(tmp_path):
    app, left = _app(tmp_path)
    ctx = app._user_ctx
    hidden = left / ".hidden"
    hidden.write_text("needle\n")
    # A file named on purpose is a candidate, hidden or not.
    assert [p.name for p in ctx.find_files(Path(str(left / "a")), "a")] == ["a"]
    assert [p.name for p in ctx.find_files(Path(str(hidden)), "*")] == [".hidden"]
    assert list(ctx.find_files(Path(str(left / "a")), "b")) == []
    hits = list(ctx.find_in_files(Path(str(left / "b")), "needle"))
    assert [(h["path"].name, h["line"]) for h in hits] == [("b", 1)]
    # A folder is searched below, as before; its hidden file is skipped.
    found = sorted(p.name for p in ctx.find_files(Path(str(left)), "*"))
    assert ".hidden" not in found and "deep.txt" in found


def test_entries_lists_a_folder_and_a_file_as_itself(tmp_path):
    app, left = _app(tmp_path)
    ctx = app._user_ctx
    assert sorted(e.name for e in ctx.entries(Path(str(left)))) == ["a", "b", "d", "sub"]
    [only] = list(ctx.entries(Path(str(left / "a"))))
    assert only.name == "a" and only.size == len("a needle\n")
    deep = sorted(e.name for e in ctx.entries(Path(str(left)), recursive=True))
    assert "deep.txt" in deep
    shallow = sorted(e.name for e in ctx.entries(Path(str(left)), recursive=True, depth=0))
    assert "deep.txt" not in shallow
    with pytest.raises(FileNotFoundError):
        list(ctx.entries(Path(str(left / "gone"))))


# --- the pane, as the API sees it ---------------------------------------------------------

def test_selected_or_focused_is_what_an_action_works_on(tmp_path):
    app, _left = _app(tmp_path)
    pane = PaneApi(app, "left")
    assert [e.name for e in pane.selected_or_focused()] == ["a"]
    pane.unselect()
    assert [e.name for e in pane.selected_or_focused()] == ["b"]  # the cursor's
    assert PaneApi(app, "right").selected_or_focused() == []


def test_shows_list(tmp_path):
    app, _left = _app(tmp_path)
    assert PaneApi(app, "left").shows_list is False
    app.pane("left")["virtual"] = {"kind": "search"}
    assert PaneApi(app, "left").shows_list is True


# --- --from -----------------------------------------------------------------------------------

def test_from_lets_the_items_be_left_out_but_not_doubled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    req = remote_cli.parse(["trash", "--from", "selection"])
    assert req["args"]["path"] == [] and req["opts"]["from"] == "selection"
    with pytest.raises(remote_cli.RemoteError) as e:
        remote_cli.parse(["trash", "x", "--from", "selection"])
    assert e.value.code == 2
    with pytest.raises(remote_cli.RemoteError) as e:
        remote_cli.parse(["trash"])
    assert e.value.code == 2
    with pytest.raises(remote_cli.RemoteError):
        remote_cli.parse(["trash", "--from", "everything"])


def test_from_means_the_same_for_every_command(tmp_path):
    app, left = _app(tmp_path)
    # pane: the folder, searched below.
    found = _items(_ask(app, "find-files 'deep*' --from pane"))
    assert _names(found) == ["deep.txt"]
    # selection: the selected item, itself.
    assert _names(_items(_ask(app, "find-in-files needle --from selection"))) == ["a"]
    assert _names(_items(_ask(app, "entries --from selection"))) == ["a"]
    # Nothing selected: the item under the cursor.
    app.pane("left")["selected_files"].clear()
    assert _names(_items(_ask(app, "entries --from selection"))) == ["b"]
    # No arguments at all: the pane's folder.
    assert _names(_items(_ask(app, "entries"))) == ["a", "b", "d", "sub"]


def test_from_pane_on_a_list_is_its_entries(tmp_path):
    app, left = _app(tmp_path, virtual={"kind": "search"})
    hits = _items(_ask(app, "find-in-files needle --from pane"))
    # Each listed file itself, and the listed folder below.
    assert _names(hits) == ["a", "b", "d", "deep.txt"]


def test_from_selection_with_nothing_there_is_refused(tmp_path):
    app, _left = _app(tmp_path)
    answer = _ask(app, "entries --from selection --pane right")
    assert not answer["ok"] and answer["code"] == remote_dispatch.FAILED


def test_copy_from_selection_copies_the_selection(tmp_path):
    app, left = _app(tmp_path)
    got = {}
    app._user_ctx = SimpleNamespace(copy=lambda items, dest, on_done=None:
                                    got.update(items=list(items), dest=dest))
    assert _ask(app, f"copy --from selection --to {_q(tmp_path)}")["ok"]
    assert got["items"] == [str(left / "a")] and got["dest"] == str(tmp_path)


# --- searches and places ------------------------------------------------------------------------

def test_index_search_takes_several_folders(tmp_path, monkeypatch):
    app, left = _app(tmp_path)
    from xefm import os_index
    monkeypatch.setattr(os_index, "unavailable", lambda: None)
    asked = []

    def index_search(root, query, cancel=None):
        asked.append(str(root))
        return iter([Path(str(root) + "/hit")])
    app._user_ctx = SimpleNamespace(index_search=index_search)
    items = _items(_ask(app, f"index-search q {_q(left)} {_q(tmp_path)}"))
    assert [i["path"] for i in items] == [str(Path(f"{left}/hit")),
                                          str(Path(f"{tmp_path}/hit"))]


def test_path_schemes_lists_the_built_ins(tmp_path):
    app, _left = _app(tmp_path)
    names = {s.name: s.source for s in app._user_ctx.path_schemes()}
    assert names["ssh"] == "builtin" and names["s3"] == "builtin"
    items = _items(_ask(app, "path-scheme list"))
    assert {"name": "archive", "source": "builtin"} in items


def test_find_similar_refuses_before_it_starts(tmp_path):
    app, left = _app(tmp_path)
    ctx = app._user_ctx
    with pytest.raises(ValueError):
        ctx.find_similar([str(left)], method="smell")
    with pytest.raises(ValueError):
        ctx.find_similar(["ssh://host/x"], method="identical")
    with pytest.raises(ValueError):
        ctx.find_similar([str(left)], method="image", threshold=2)
    with pytest.raises(ValueError):
        ctx.find_similar([], method="identical")
    with pytest.raises(remote_cli.RemoteError):
        remote_cli.parse(["find-similar", "--method", "smell"])
    assert _ask(app, "find-similar")["code"] == remote_dispatch.USAGE


def test_find_similar_yields_the_groups_once_the_scan_ends(tmp_path, monkeypatch):
    app, left = _app(tmp_path)
    from xefm import similar_scan
    result = tmp_path / "result.xft"
    result.write_text(json.dumps({
        "format": "xft", "version": 1, "final": True, "nodes": [
            {"name": "g1", "children": [
                {"name": "a", "target": str(left / "a"), "extra": {"similarity": 1.0}},
                {"name": "b", "target": str(left / "b"), "extra": {"similarity": 0.9}}]},
            {"name": "empty", "children": []}]}))
    states = iter([similar_scan.RUNNING, similar_scan.DONE, similar_scan.DONE])
    job = SimpleNamespace(state=lambda: next(states), result_path=result,
                          log_path=tmp_path / "log", stop=lambda: None)
    started = {}

    def start(roots, method, threshold=None):
        started.update(roots=roots, method=method, threshold=threshold)
        return job
    monkeypatch.setattr(similar_scan, "start", start)
    monkeypatch.setattr(similar_scan, "unavailable", lambda m: None)
    monkeypatch.setattr("time.sleep", lambda s: None)
    from xefm import xft
    monkeypatch.setattr(xft, "FORMAT", "xft")
    monkeypatch.setattr(xft, "VERSION", 1)
    items = _items(_ask(app, "find-similar --method image --threshold strict --from pane"))
    assert [(i["group"], os.path.basename(i["path"])) for i in items] == [(1, "a"), (1, "b")]
    assert started["roots"] == [str(left)] and started["method"] == "image"
    assert started["threshold"] == dict(similar_scan.threshold_steps("image"))["strict"]
    assert remote_cli.format_item(remote_commands.find(["find-similar"])[0], items[1],
                                  False) == f"1\t{left / 'b'}"


# --- tags and attributes ---------------------------------------------------------------------------

def test_tag_add_takes_several_names_and_reports_each_item(tmp_path):
    app, left = _app(tmp_path)
    req = remote_cli.parse(["tag", "add", "Work", "--tag", "Red", "--tag", "x",
                            str(left / "a")])
    assert req["args"]["name"] == "Work" and req["opts"]["tag"] == ["Red", "x"]
    store = SimpleNamespace()
    app._tag_store_of = lambda targets: store
    seen = {}

    def change(targets, *, add=(), remove=(), color=None, on_complete=None):
        seen.update(targets=[str(t) for t in targets], add=list(add), color=color)
        on_complete({"changed": 1, "failed": [f"{targets[1]}: no xattr"]})
    app._change_tags_for_api = change
    pending = _ask(app, f"tag add Work --tag Red --color blue --wait {_q(left / 'a')} "
                        f"{_q(left / 'b')}")
    answer = pending.wait()
    assert seen["add"] == ["Work", "Red"] and seen["color"] == 4
    assert [(os.path.basename(i["path"]), i["status"]) for i in answer["items"]] == \
        [("a", "done"), ("b", "failed")]
    assert answer["status"] == remote_dispatch.FAILED


def test_tags_are_refused_where_there_is_no_store(tmp_path):
    app, left = _app(tmp_path)
    app._tag_store_of = lambda targets: None
    answer = _ask(app, f"tag remove Work {_q(left / 'a')}")
    assert not answer["ok"] and "not supported" in answer["error"]
    with pytest.raises(ValueError):
        app._user_ctx.add_tags([str(left / "a")], ["Work"], color="mauve")
    with pytest.raises(ValueError):
        app._user_ctx.add_tags([str(left / "a")], [])


def test_an_agents_tag_write_is_asked_first(tmp_path):
    app, left = _app(tmp_path)
    app._tag_store_of = lambda targets: object()
    asked, wrote = [], []
    app._change_tags_for_api = lambda targets, **k: wrote.append(k)
    app._user_ctx.confirm = lambda prompt, title="", on_result=None: asked.append(
        (prompt, on_result))
    _ask(app, f"tag add Work {_q(left / 'a')}", policy="agent", session="3")
    assert len(asked) == 1 and "add the tag(s) Work" in asked[0][0] and not wrote
    asked[0][1](True)
    assert wrote and wrote[0]["add"] == ["Work"]


def test_tag_list(tmp_path):
    app, _left = _app(tmp_path)
    from xefm import tags
    app._known_tags = lambda: [tags.Tag("Work", 6), tags.Tag("Plain", 0)]
    assert app._user_ctx.tags() == [user_api.TagInfo("Work", "red"),
                                    user_api.TagInfo("Plain", None)]
    assert _items(_ask(app, "tag list")) == [{"name": "Work", "color": "red"},
                                             {"name": "Plain", "color": ""}]


def test_attributes_are_computed_now(tmp_path):
    app, left = _app(tmp_path)
    calls = []

    def read(directory, entries):
        calls.append((str(directory), [e.name for e in entries]))
        return [e.name.upper() for e in entries]
    attributes.register(attributes.Attribute("shout", "Shout", read=read,
                                             compute="on_request"))
    try:
        listed = {a.name: a for a in app._user_ctx.attributes()}
        assert listed["shout"].source == "config" and listed["shout"].compute == "on_request"
        assert listed["name"].compute == "sync"
        rows = list(app._user_ctx.get_attributes(
            [str(left / "a"), str(left / "b"), str(left / "sub")],
            ["shout", "size", "ext"]))
        values = {os.path.basename(str(r["path"])): r["values"] for r in rows}
        assert values["a"] == {"shout": "A", "size": len("a needle\n"), "ext": ""}
        # A folder's size is its total; one provider call per folder.
        assert values["sub"]["size"] == len("deep needle\n")
        assert calls == [(str(left), ["a", "b", "sub"])]
        with pytest.raises(ValueError):
            app._user_ctx.get_attributes([str(left / "a")], ["nope"])
        items = _items(_ask(app, f"attribute get --attributes shout,ext {_q(left / 'a')}"))
        assert items[0]["text"] == f"{left / 'a'}\tshout=A\text="
        assert _ask(app, f"attribute get --attributes nope {_q(left / 'a')}")["code"] == \
            remote_dispatch.USAGE
    finally:
        attributes.clear()


# --- rename from a plan ------------------------------------------------------------------------------

def test_the_plan_is_read_by_the_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"path": "a", "name": "A"}]))
    req = remote_cli.parse(["rename", "--plan", "plan.json"])
    assert req["opts"]["plan"] == [{"path": str(tmp_path / "a"), "name": "A"}]
    import io
    req = remote_cli.parse(["rename", "--plan", "-"],
                           io.StringIO('[{"path": "/x/b", "name": "B"}]'))
    # Made absolute like any path: on Windows, /x/b is on the current drive.
    assert req["opts"]["plan"] == [{"path": os.path.abspath("/x/b"), "name": "B"}]
    for bad in ("{}", "[1]", "not json", '[{"path": "a"}]'):
        plan.write_text(bad)
        with pytest.raises(remote_cli.RemoteError) as e:
            remote_cli.parse(["rename", "--plan", "plan.json"])
        assert e.value.code == 2


def _rename_app(tmp_path, monkeypatch):
    app, left = _app(tmp_path)
    from xefm import app as app_module
    from xefm.app import XeFMApp
    boxes = []
    monkeypatch.setattr(app_module, "show_message_box",
                        lambda panel, text, **k: boxes.append((text, k)))
    app._is_archive = lambda p: False
    app._RENAME_PREVIEW_ROWS = 20
    app._relist = lambda pane, **k: None
    app._rename_for_api = lambda *a: XeFMApp._rename_for_api(app, *a)
    app._ui_thread = None
    return app, left, boxes


def test_rename_is_reviewed_then_done(tmp_path, monkeypatch):
    app, left, boxes = _rename_app(tmp_path, monkeypatch)
    outcomes = []
    # A swap goes through temporary names.
    app._user_ctx.rename([(str(left / "a"), "b"), (str(left / "b"), "a"),
                          (str(left / "d"), "d")],
                         on_done=lambda ctx, outcome: outcomes.append(outcome))
    [(text, k)] = boxes
    assert "a  →  b" in text and k["buttons"] == ("Rename", "Cancel")
    k["on_result"]("Rename")
    assert (left / "a").read_text() == "b needle\n"
    [outcome] = outcomes
    assert [(r.source.name, r.status) for r in outcome.value] == \
        [("a", "done"), ("b", "done"), ("d", "skipped")]


def test_rename_refuses_a_bad_plan_at_once(tmp_path, monkeypatch):
    app, left, boxes = _rename_app(tmp_path, monkeypatch)
    ctx = app._user_ctx
    with pytest.raises(ValueError):
        ctx.rename([(str(left / "a"), "d")])           # taken
    with pytest.raises(ValueError):
        ctx.rename([(str(left / "a"), "x/y")])         # a path
    with pytest.raises(ValueError):
        ctx.rename([(str(left / "a"), "x"), (str(left / "a"), "y")])
    with pytest.raises(ValueError):
        ctx.rename([("a", "x")])                       # relative
    assert boxes == []
    answer = _ask(app, "rename --plan -", stdin=__import__("io").StringIO(
        json.dumps([{"path": str(left / "a"), "name": "d"}])))
    assert answer["code"] == remote_dispatch.USAGE and "already exists" in answer["error"]


def test_rename_declined_is_cancelled(tmp_path, monkeypatch):
    app, left, boxes = _rename_app(tmp_path, monkeypatch)
    import io
    pending = _ask(app, "rename --wait --plan -", stdin=io.StringIO(
        json.dumps([{"path": str(left / "a"), "name": "z"}])))
    boxes[0][1]["on_result"]("Cancel")
    answer = pending.wait()
    assert answer["outcome"] == "cancelled" and (left / "a").exists()


# --- picking in a pane -------------------------------------------------------------------------------

def _key(name, modifiers=()):
    return SimpleNamespace(key=name, modifiers=modifiers)


def test_pick_answers_on_enter_and_cancels_on_escape(tmp_path):
    app, left = _app(tmp_path)
    from xefm.app import XeFMApp
    for name in ("_start_pick", "_cancel_pick", "_pick_key"):
        setattr(app, name, getattr(XeFMApp, name).__get__(app))
    app._activate_pane = lambda name: setattr(app.pm, "active_pane", name)
    answers = []
    PaneApi(app, "right").pick(prompt="Choose", on_result=answers.append)
    assert app.pm.active_pane == "right" and "Choose" in app.logged[-1]
    assert not app._pick_key(_key("x"))
    assert not app._pick_key(_key("enter", ("shift",)))
    app.pm.active_pane = "left"          # the user switched panes
    assert app._pick_key(_key("enter"))
    assert [e.name for e in answers[0]] == ["a"]
    assert not app._pick_key(_key("enter"))  # over
    PaneApi(app, "left").pick(on_result=answers.append)
    PaneApi(app, "left").pick(on_result=answers.append)  # replaces the first
    assert answers[1] is None
    assert app._pick_key(_key("escape")) and answers[2] is None


def test_pane_pick_waits_for_the_user(tmp_path):
    app, left = _app(tmp_path)
    picks = []
    app._start_pick = lambda pane, prompt, cb: picks.append((pane, prompt, cb))
    pending = _ask(app, "pane pick --prompt 'Which photos?' --pane right",
                   policy="agent", session="3")
    assert isinstance(pending, remote_dispatch.Pending)
    pane, prompt, cb = picks[0]
    assert pane == "right" and prompt.endswith("Which photos?")
    cb([user_api.EntryInfo(Path(str(left / "a")))])
    assert _names(pending.wait()["items"]) == ["a"]
    pending = _ask(app, "pane pick")
    picks[-1][2](None)
    assert pending.wait()["status"] == remote_dispatch.FAILED


# --- the table ----------------------------------------------------------------------------------------

def test_the_new_commands_are_in_the_table_and_the_reference():
    names = {c.name for c in remote_commands.COMMANDS}
    for name in ("find-similar", "path-scheme list", "tag list", "tag add", "tag remove",
                 "attribute list", "attribute get", "pane pick", "rename"):
        assert name in names
        assert f"### `{name}`" in remote_commands.reference_markdown()
    tag_add = remote_commands.find(["tag", "add"])[0]
    assert "[--tag NAME]..." in remote_commands.synopsis(tag_add)


def test_every_command_that_takes_items_takes_from():
    for cmd in remote_commands.COMMANDS:
        takes_items = any(a.path and a.nargs in ("*", "+") for a in cmd.args)
        if takes_items and cmd.name != "pane open-list":
            assert cmd.opt("--from") is not None, cmd.name
