"""The public API an extension needs for a long, read-only job with a result
to show (#632): ``ctx.run_task`` and its ``TaskJob`` / ``TaskOutcome``,
``ctx.show_markdown`` with copyable code blocks, ``ctx.copy_text``, the
``md_code_block`` / ``md_escape`` helpers, and ``MENU_ITEMS``.

Driven on the memory backend, which runs animation ticks on request — the
TaskManager's pump — so a task really runs on its worker thread here.

Run with: python -m pytest test/test_user_task_api.py -v
"""

from xefm.hint_bar import hints_text
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Event, EventType, Panel, PROFILE_TUI  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402
from puikit.widgets.markdown_view import parse_markdown  # noqa: E402

from xefm import actions as xa  # noqa: E402
from xefm import user_api  # noqa: E402
from xefm._config import Config as DefaultConfig  # noqa: E402
from xefm.task import Task, TaskManager, TaskStatus  # noqa: E402
from xefm.text_dialog import MarkdownDialog  # noqa: E402
from xefm.user_api import (ActionContext, TaskJob, md_code_block,  # noqa: E402
                           md_escape)


def _key(name, mods=()):
    return Event(type=EventType.KEY, key=name, modifiers=frozenset(mods))


def _pump(panel, until, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        panel.backend.run_animation_ticks()
        time.sleep(0.01)
    panel.backend.run_animation_ticks()
    assert until(), "condition never held"


@pytest.fixture
def app(tmp_path):
    from puikit.backends import create_backend
    from xefm import app as xefm_app
    from xefm.state_manager import XeFMStateManager
    root = os.path.realpath(str(tmp_path))
    for name in ("a.txt", "b.txt"):
        with open(os.path.join(root, name), "w") as fh:
            fh.write(name)
    backend = create_backend("memory")
    backend.open()
    a = xefm_app.XeFMApp(backend, root, root, left_provided=True,
                         right_provided=True,
                         state_manager=XeFMStateManager(
                             db_path=os.path.join(root, "state.db")))
    a.file_monitor.stop_monitoring()
    a.file_monitor.enabled = False
    a._settle_listings()
    yield a
    for t in a.tasks.active_tasks():
        t.request_cancel()
    backend.close()


# --------------------------------------------------------------------------- #
# Markdown helpers
# --------------------------------------------------------------------------- #

def _code_text(source):
    (sem,) = [s for s in parse_markdown(source) if s.block == "code"]
    return "\n".join(t for t, _, _ in sem.runs)


@pytest.mark.parametrize("text", [
    "plain",
    "has ``` a fence",
    "```\nfenced inside\n```",
    "````` five",
    "~~~\ntilde fence\n~~~",
])
def test_md_code_block_holds_any_text_as_written(text):
    assert _code_text(md_code_block(text)) == text


def test_md_code_block_names_the_language():
    assert md_code_block("x = 1", "python").startswith("```python\n")


@pytest.mark.parametrize("name", [
    "a_b*.txt", "# not a heading", "1. not a list", "- dash", "> quote",
    "[x](y)", "`tick`", "~~s~~", "<b>", "C:\\dir\\f.txt", "v1.2-3.txt",
    "two\n# lines",
])
def test_md_escape_reads_back_literally(name):
    sems = parse_markdown(md_escape(name))
    assert all(s.block == "para" for s in sems)
    shown = " ".join("".join(t for t, _, _ in s.runs) for s in sems)
    assert shown == name.replace("\n", " ")


# --------------------------------------------------------------------------- #
# TaskJob
# --------------------------------------------------------------------------- #

def test_job_progress_drives_the_dialog_bar():
    task = Task("Hash")
    job = TaskJob(task)
    assert task.progress.get_current_operation() is None
    job.progress(0, 4, detail="a.txt")
    op = task.progress.get_current_operation()
    assert not op["counting"] and op["total_items"] == 4
    job.progress(2, 4, detail="c.txt")
    assert task.progress.get_progress_percentage() == 50
    assert task.progress.get_current_operation()["current_item"] == "c.txt"


def test_job_progress_without_a_total_stays_a_spinner():
    task = Task("Hash")
    TaskJob(task).progress(3, 0)
    assert task.progress.get_current_operation()["counting"]


def test_item_progress_drives_the_byte_bar_of_the_current_item():
    task = Task("Hash")
    job = TaskJob(task)
    job.progress(0, 2, detail="big.iso")
    job.item_progress(3 * 2**30, 30 * 2**30)
    op = task.progress.get_current_operation()
    assert (op["file_bytes_copied"], op["file_bytes_total"]) == (3 * 2**30, 30 * 2**30)
    assert op["total_items"] == 2 and op["current_item"] == "big.iso"
    job.progress(1, 2, detail="small.txt")          # the next item starts clean
    op = task.progress.get_current_operation()
    assert (op["file_bytes_copied"], op["file_bytes_total"]) == (0, 0)


def test_item_progress_leaves_the_item_bar_to_the_item_count():
    """#686: bytes read within an item, with no byte total for the whole
    task, must not move the item bar — it filled after 8 KiB."""
    task = Task("Hash")
    job = TaskJob(task)
    job.progress(0, 1, detail="big")
    for read in (1024, 2**20, 6 * 2**30, 12 * 2**30):
        job.item_progress(read, 12 * 2**30)
        assert task.progress.get_progress_percentage() == 0
    job.progress(1, 1)
    assert task.progress.get_progress_percentage() == 100


def test_items_and_bytes_still_weigh_together_with_a_byte_total():
    from xefm.progress_manager import OperationType, ProgressManager
    pm = ProgressManager()
    pm.start_operation(OperationType.COPY, 0)
    pm.update_operation_total(2, total_bytes=10 * 2**20)
    pm.update_progress("big")
    pm.update_file_byte_progress(5 * 2**20, 10 * 2**20)
    assert 40 < pm.get_progress_percentage() < 100


def test_item_progress_alone_counts_the_work_as_one_item():
    task = Task("Hash")
    TaskJob(task).item_progress(10, 100)
    op = task.progress.get_current_operation()
    assert op["total_items"] == 1 and not op["counting"]
    assert op["file_bytes_total"] == 100


def test_the_dialog_shows_the_byte_bar(app):
    from xefm.task import ProgressDialog
    task = Task("Compute Hash")
    job = TaskJob(task)
    job.progress(0, 1, detail="huge.bin")
    job.item_progress(512 * 2**20, 2**30)
    dialog = ProgressDialog(task)
    dialog.show(app.panel)
    app.panel.render()
    screen = "\n".join(app.panel.backend.snapshot())
    assert "huge.bin" in screen and "0 / 1 items" in screen
    assert "512" in screen and "1.0" in screen and "GB" in screen
    dialog.close()


def test_job_checkpoint_raises_once_cancelled():
    task = Task("Hash")
    job = TaskJob(task)
    job.checkpoint()
    task.request_cancel()
    assert job.cancelled()
    with pytest.raises(Exception):
        job.checkpoint()


# --------------------------------------------------------------------------- #
# ctx.run_task against a live app
# --------------------------------------------------------------------------- #

def test_run_task_hands_the_value_to_on_done_with_a_fresh_ctx(app):
    ctx = ActionContext(app)
    seen = []
    threads = []

    def work(job):
        threads.append(threading.current_thread())
        job.progress(1, 1, detail="a.txt")
        return ["digest  a.txt"]

    ctx.run_task("Hash", work, on_done=lambda c, o: seen.append((c, o)))
    _pump(app.panel, lambda: seen)
    (done_ctx, outcome), = seen
    assert threads[0] is not threading.main_thread()
    assert outcome.ok and outcome.status == "done"
    assert outcome.value == ["digest  a.txt"] and outcome.error is None
    assert done_ctx is not ctx


def test_run_task_reports_a_cancel(app):
    ctx = ActionContext(app)
    seen, started = [], threading.Event()

    def work(job):
        started.set()
        while True:
            job.checkpoint()
            time.sleep(0.005)

    ctx.run_task("Hash", work, on_done=lambda c, o: seen.append(o))
    assert started.wait(2)
    (task,) = app.tasks.active_tasks()
    task.request_cancel()
    _pump(app.panel, lambda: seen)
    assert seen[0].status == "cancelled" and seen[0].value is None


def test_run_task_reports_a_failure_and_logs_it(app, monkeypatch):
    logged = []
    monkeypatch.setattr(user_api.logger, "error", logged.append)
    ctx = ActionContext(app)
    seen = []

    def work(job):
        raise ValueError("unreadable")

    ctx.run_task("Hash", work, on_done=lambda c, o: seen.append(o))
    _pump(app.panel, lambda: seen)
    assert seen[0].status == "failed" and isinstance(seen[0].error, ValueError)
    assert any("ValueError: unreadable" in line for line in logged)
    assert any("raise ValueError" in line for line in logged), "the traceback"


def test_a_failing_on_done_is_contained(app, monkeypatch):
    logged = []
    monkeypatch.setattr(user_api.logger, "error", logged.append)
    ctx = ActionContext(app)

    def on_done(c, o):
        raise RuntimeError("bad callback")

    ctx.run_task("Hash", lambda job: 1, on_done=on_done)
    _pump(app.panel, lambda: not app.tasks.active_tasks())
    assert any("bad callback" in line for line in logged)


def test_read_only_makes_the_task_non_exclusive(app):
    ctx = ActionContext(app)
    release = threading.Event()
    ctx.run_task("Hash", lambda job: release.wait(2), read_only=True)
    ctx.run_task("Rewrite", lambda job: release.wait(2))
    hashing, rewriting = app.tasks.active_tasks()
    assert hashing.exclusive is False and rewriting.exclusive is True
    release.set()
    _pump(app.panel, lambda: not app.tasks.active_tasks())


# --------------------------------------------------------------------------- #
# TaskManager: a non-exclusive task beside the slot
# --------------------------------------------------------------------------- #

@pytest.fixture
def panel():
    return Panel(MemoryBackend(width=100, height=30, capabilities=PROFILE_TUI))


def _held(manager, panel, *, exclusive=True, detached=False, title="Copy…"):
    release, done = threading.Event(), []
    task = Task(title)
    task.exclusive = exclusive

    def run(t):
        while not release.wait(0.01):
            t.checkpoint()
        return {"done": 1}

    manager.submit(task, panel, run=run, on_done=done.append, detached=detached)
    return task, release, done


def test_a_read_only_task_sent_back_keeps_running_beside_the_slot(panel):
    manager = TaskManager()
    copy, release_copy, _ = _held(manager, panel, detached=True)
    hashing, release_hash, done = _held(manager, panel, exclusive=False, title="Hash…")
    manager.detach(hashing)
    assert not hashing.suspended and not manager.is_queued(hashing)
    assert manager.background_tasks() == [copy, hashing]
    release_hash.set()
    _pump(panel, lambda: done)
    assert copy.status is TaskStatus.RUNNING
    release_copy.set()


def test_a_detached_read_only_task_does_not_wait_for_the_slot(panel):
    manager = TaskManager()
    _copy, release_copy, _ = _held(manager, panel, detached=True)
    hashing, release_hash, done = _held(manager, panel, exclusive=False,
                                        detached=True, title="Hash…")
    assert hashing.status is TaskStatus.RUNNING
    assert manager.queued_count() == 0
    release_hash.set()
    _pump(panel, lambda: done)
    release_copy.set()


def test_running_task_names_a_read_only_job_when_the_slot_is_free(panel):
    manager = TaskManager()
    hashing, release, done = _held(manager, panel, exclusive=False,
                                   detached=True, title="Hash…")
    assert manager.running_task() is hashing
    release.set()
    _pump(panel, lambda: done)
    assert manager.running_task() is None


# --------------------------------------------------------------------------- #
# ctx.show_markdown / ctx.copy_text
# --------------------------------------------------------------------------- #

def _top_dialog(app):
    widget = app.panel._layers[-1].widget
    assert isinstance(widget, MarkdownDialog)
    return widget


def test_show_markdown_copies_a_code_block_from_the_keyboard(app):
    ActionContext(app).show_markdown(
        "Compute Hash", "**SHA-256**\n\n" + md_code_block("abc  a.txt\ndef  b.txt"))
    dialog = _top_dialog(app)
    assert dialog.title == "Compute Hash"
    app.panel.render()
    dialog.handle_event(_key("tab"))
    dialog.handle_event(_key("enter"))
    assert app.panel.get_clipboard() == "abc  a.txt\ndef  b.txt"
    assert _top_dialog(app) is dialog, "Enter on the button does not close"
    dialog.handle_event(_key("escape"))
    assert not any(isinstance(layer.widget, MarkdownDialog) for layer in app.panel._layers)


def test_show_markdown_on_close_runs_once_the_dialog_has_closed(app):
    closed = []
    ActionContext(app).show_markdown("Share", "http://192.0.2.1:8000/",
                                     on_close=lambda: closed.append(True))
    dialog = _top_dialog(app)
    assert closed == [], "not before the user closes it"
    dialog.handle_event(_key("escape"))
    assert closed == [True]
    assert not any(isinstance(layer.widget, MarkdownDialog) for layer in app.panel._layers)


def test_show_markdown_on_close_failure_is_logged_not_raised(app):
    def boom():
        raise RuntimeError("no server")
    ActionContext(app).show_markdown("Share", "text", on_close=boom)
    dialog = _top_dialog(app)
    dialog.handle_event(_key("escape"))        # must not raise into the dialog
    assert not any(isinstance(layer.widget, MarkdownDialog) for layer in app.panel._layers)


def test_show_markdown_text_is_selectable(app):
    ActionContext(app).show_markdown("Result", "hello world")
    dialog = _top_dialog(app)
    app.panel.render()
    dialog.handle_event(_key("a", {"ctrl"}))
    assert dialog.md.selection_text() == "hello world"


def test_copy_text_puts_text_on_the_clipboard(app):
    ActionContext(app).copy_text("9f86d081  setup.exe")
    assert app.panel.get_clipboard() == "9f86d081  setup.exe"


# --------------------------------------------------------------------------- #
# MENU_ITEMS
# --------------------------------------------------------------------------- #

@pytest.fixture
def clean_registry():
    yield
    xa.registry.unregister_source("user")
    user_api.hooks.clear()
    user_api.menu_entries.clear()


def _config(**attrs):
    cfg = DefaultConfig()
    for name, value in attrs.items():
        setattr(cfg, name, value)
    return cfg


def test_menu_items_load_for_their_menus(clean_registry):
    cfg = _config(ACTIONS={"hash.compute": lambda ctx: None},
                  MENU_ITEMS={"hash.compute": {"menus": ["file", "context"],
                                               "label": "Compute Hash…",
                                               "when": "entry"},
                              "copy_names": {"menus": "context", "label": "Names"}})
    warnings = user_api.load_user_entries(cfg)[0]
    assert warnings == []
    assert [e.label for e in user_api.menu_items("file")] == ["Compute Hash…"]
    assert [e.action for e in user_api.menu_items("context")] == ["hash.compute",
                                                                  "copy_names"]


@pytest.mark.parametrize("spec, says", [
    ({"menus": ["toolbar"], "label": "X"}, "needs 'menus'"),
    ({"menus": ["file"]}, "needs a 'label'"),
    ({"menus": ["file"], "label": "X", "when": "later"}, "has 'when'"),
    ({"menus": ["file"], "label": "X", "where": 3}, "unknown keys where"),
    ("file", "must be a dict"),
])
def test_a_bad_menu_item_is_skipped_with_a_warning(clean_registry, spec, says):
    cfg = _config(ACTIONS={"mine": lambda ctx: None}, MENU_ITEMS={"mine": spec})
    warnings = user_api.load_user_entries(cfg)[0]
    assert len(warnings) == 1 and says in warnings[0]
    assert user_api.menu_items("file") == []


def test_a_menu_item_must_name_an_action(clean_registry):
    cfg = _config(MENU_ITEMS={"nobody.home": {"menus": ["file"], "label": "X"}})
    assert "names no action" in user_api.load_user_entries(cfg)[0][0]
    # Validation without loading still knows the config's own actions.
    cfg = _config(ACTIONS={"mine": lambda ctx: None},
                  MENU_ITEMS={"mine": {"menus": ["file"], "label": "X"}})
    assert user_api.validate_user_entries(cfg) == []


def _labels(menu):
    return [getattr(item, "label", None) for item in menu.items]


def test_the_menus_carry_the_items_and_run_their_actions(app, clean_registry):
    calls = []
    app.config.ACTIONS = {"hash.compute": lambda ctx: calls.append(ctx)}
    app.config.MENU_ITEMS = {"hash.compute": {"menus": ["file", "context"],
                                              "label": "Compute Hash…",
                                              "when": "selection"}}
    app._load_user_entries(app.config)
    file_menu = app._build_menu().items[0].submenu
    assert "Compute Hash…" in _labels(file_menu)
    assert _labels(file_menu)[-1] == "Quit"
    context = app._item_context_menu(app.active_pane())
    (item,) = [i for i in context.items if getattr(i, "label", None) == "Compute Hash…"]
    assert not item.is_enabled(), "nothing is selected"
    app.active_pane()["selected_files"].add(str(app.active_pane()["files"][0]))
    assert item.is_enabled()
    item.activate()
    assert len(calls) == 1


def test_more_than_three_menu_items_go_under_custom(app, clean_registry):
    """A few stay inline; more gather under Custom ▸, so File still fits the 23
    rows a terminal leaves (it is near that already)."""
    names = [f"mine.a{i}" for i in range(4)]
    app.config.ACTIONS = {n: (lambda ctx: None) for n in names}
    app.config.MENU_ITEMS = {n: {"menus": ["file"], "label": n} for n in names[:3]}
    app._load_user_entries(app.config)
    assert "mine.a0" in _labels(app._build_menu().items[0].submenu)
    app.config.MENU_ITEMS = {n: {"menus": ["file"], "label": n} for n in names}
    app._load_user_entries(app.config)
    file_menu = app._build_menu().items[0].submenu
    assert "mine.a0" not in _labels(file_menu)
    (custom,) = [i for i in file_menu.items if getattr(i, "label", None) == "Custom"]
    assert _labels(custom.submenu) == names


# --------------------------------------------------------------------------- #
# Preview marks
# --------------------------------------------------------------------------- #

from xefm import extensions as _ext  # noqa: E402
from xefm import path_base  # noqa: E402
from xefm.preview import NOTE, is_preview  # noqa: E402

# Which public names are stable and which Preview is held still by the API
# snapshot (test/test_api_snapshot.py); these check the mark itself.


def test_a_preview_api_says_so_in_its_docstring():
    assert ActionContext.run_task.__doc__.startswith(NOTE)
    assert ActionContext.input.__doc__.startswith(NOTE)
    assert user_api.TaskJob.__doc__.startswith(NOTE)
    assert path_base.UriPathImpl.__doc__.startswith(NOTE)
    for stable in (ActionContext.pane, ActionContext.api_version,
                   user_api.PaneApi, path_base.ReadOnlyPathImpl):
        assert not (stable.__doc__ or "").startswith(NOTE), stable


def test_a_class_entry_covers_its_members():
    assert is_preview("xefm.user_api.TaskJob.progress")
    assert not is_preview("xefm.user_api.PaneApi.cd")
    assert not is_preview("xefm.user_api.ActionContext.api_version")


def test_the_tables_and_manifest_sections_are_named():
    stable = {"ACTIONS", "SORT_KEYS", "FILTERS", "PATH_SCHEMES"}
    tables = set(_ext.CONTRIBUTION_TABLES.values()) - {"THEMES"}
    for table in tables:
        assert (f"config.{table}" in user_api.PREVIEW_APIS) == (table not in stable), table
    stable_kinds = {"actions", "sort_keys", "filters", "path_schemes", "key_suggestions"}
    for kind in set(_ext.CONTRIBUTION_TABLES) | {"key_suggestions"}:
        assert (f"manifest.contributes.{kind}" in user_api.PREVIEW_APIS) \
            == (kind not in stable_kinds), kind


# --------------------------------------------------------------------------- #
# The Markdown dialog's footer names what Tab reaches (#681)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("source, says", [
    ("plain text", "↑/↓ scroll  Esc close"),
    ("see [docs](https://example.com)", "Tab next link  Enter open"),
    (md_code_block("abc  a.txt"), "Tab Copy button  Enter copy"),
    ("[docs](https://example.com)\n\n" + md_code_block("x"), "Tab next link or Copy"),
])
def test_the_footer_says_what_tab_reaches(app, source, says):
    ActionContext(app).show_markdown("Result", source)
    assert says in hints_text(_top_dialog(app).hint)


def test_an_explicit_hint_still_wins():
    from xefm.text_dialog import MarkdownDialog as Dialog
    assert Dialog("[a](u:1)", hint="mine").hint == "mine"
