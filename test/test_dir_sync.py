"""Directory sync: applying a directory diff in bulk (#560).

Two halves. :mod:`xefm.dir_sync` turns a finished comparison and a mode into
copies and deletions, tested against trees the viewer scanned synchronously.
The viewer half opens a plan with ``s``, changes a node with Space, and runs
it — on the memory backend, through the real file-operation engine.

Run with: python -m pytest test/test_dir_sync.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import (Event, EventType, Panel, PROFILE_GUI_DESKTOP,  # noqa: E402
                    PROFILE_TUI)
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402

from xefm import _config, dir_sync  # noqa: E402
from xefm.directory_diff_viewer import (  # noqa: E402
    DirectoryDiffView, show_directory_diff_viewer)
from xefm.path import Path  # noqa: E402
from xefm.hint_bar import hints_text


@pytest.fixture
def trees(tmp_path):
    """L is the source unless a test says otherwise."""
    left, right = tmp_path / "L", tmp_path / "R"
    (left / "sub").mkdir(parents=True)
    (right / "sub").mkdir(parents=True)
    (left / "same.txt").write_text("same")
    (right / "same.txt").write_text("same")
    (left / "changed.txt").write_text("new")
    (right / "changed.txt").write_text("old")
    os.utime(right / "changed.txt", (1_000_000, 1_000_000))
    (left / "new.txt").write_text("n")
    (right / "extra.txt").write_text("e")
    (left / "newdir").mkdir()
    (left / "newdir" / "f.txt").write_text("f")
    (left / "sub" / "a.txt").write_text("1")
    (right / "sub" / "a.txt").write_text("2")
    os.utime(right / "sub" / "a.txt", (1_000_000, 1_000_000))
    return left, right


def _view(left, right):
    return DirectoryDiffView(Path(str(left)), Path(str(right)), background=False)


def _node(view, rel):
    node = view.root
    for part in rel.split("/"):
        node = next(c for c in node.children if c.name == part)
    return node


def _plan(view, mode, source="left"):
    return dir_sync.SyncPlan(mode, source, view.left_path, view.right_path)


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #

def test_update_copies_new_and_changed_and_keeps_extra(trees):
    view = _view(*trees)
    ops = _plan(view, dir_sync.UPDATE).operations(view.root)
    copied = sorted(str(src).split(os.sep + "L" + os.sep)[1] for src, _d, _o in ops.copies)
    assert copied == ["changed.txt", "new.txt", "newdir",
                      os.path.join("sub", "a.txt")]
    assert ops.deletes == []
    assert (ops.new, ops.replaced) == (2, 2)
    # extra.txt is only on the target: Update leaves it, and says so.
    assert ops.skipped == 1


def test_destinations_mirror_the_source_tree(trees):
    left, right = trees
    view = _view(*trees)
    ops = _plan(view, dir_sync.UPDATE).operations(view.root)
    dests = {str(src): (str(dest), ow) for src, dest, ow in ops.copies}
    assert dests[str(left / "new.txt")] == (str(right / "new.txt"), False)
    assert dests[str(left / "newdir")] == (str(right / "newdir"), False)
    assert dests[str(left / "sub" / "a.txt")] == (str(right / "sub" / "a.txt"), True)


def test_mirror_also_deletes_what_only_the_target_has(trees):
    left, right = trees
    view = _view(*trees)
    ops = _plan(view, dir_sync.MIRROR).operations(view.root)
    assert [str(p) for p in ops.deletes] == [str(right / "extra.txt")]
    assert ops.skipped == 0


def test_a_newer_target_defaults_to_skip(trees):
    left, right = trees
    os.utime(left / "changed.txt", (1_000_000, 1_000_000))
    os.utime(right / "changed.txt", (2_000_000, 2_000_000))
    view = _view(*trees)
    plan = _plan(view, dir_sync.UPDATE)
    assert plan.action(_node(view, "changed.txt")) == dir_sync.SKIP
    ops = plan.operations(view.root)
    assert str(left / "changed.txt") not in [str(s) for s, _d, _o in ops.copies]
    assert ops.newer_kept == 1


def test_cycling_a_node_changes_only_it(trees):
    left, right = trees
    view = _view(*trees)
    plan = _plan(view, dir_sync.UPDATE)
    node = _node(view, "changed.txt")
    assert plan.cycle(node) == dir_sync.SKIP
    assert plan.cycle(node) == dir_sync.BACK
    ops = plan.operations(view.root)
    assert (str(right / "changed.txt"), str(left / "changed.txt"), True) in \
        [(str(s), str(d), o) for s, d, o in ops.copies]
    assert ops.back == 1
    # Back round to the default, and nothing is remembered.
    assert plan.cycle(node) == dir_sync.COPY
    assert plan.is_default(node)


def test_skipping_a_directory_skips_everything_below(trees):
    view = _view(*trees)
    plan = _plan(view, dir_sync.UPDATE)
    sub = _node(view, "sub")
    assert plan.action(sub) == dir_sync.DESCEND
    plan.cycle(sub)
    assert plan.action(_node(view, "sub/a.txt")) == dir_sync.SKIP
    copied = [str(s) for s, _d, _o in plan.operations(view.root).copies]
    assert not any(c.endswith(os.path.join("sub", "a.txt")) for c in copied)


def test_a_file_against_a_folder_is_never_copied(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir()
    (right / "thing").mkdir(parents=True)
    (right / "thing" / "inside.txt").write_text("x")
    (left / "thing").write_text("a file")
    view = _view(left, right)
    for mode in (dir_sync.UPDATE, dir_sync.MIRROR):
        ops = _plan(view, mode).operations(view.root)
        assert ops.copies == [] and ops.deletes == []
        assert ops.mismatched == 1


def test_right_to_left_is_the_mirror_image(trees):
    left, right = trees
    view = _view(*trees)
    ops = _plan(view, dir_sync.MIRROR, source="right").operations(view.root)
    assert (str(right / "extra.txt"), str(left / "extra.txt"), False) in \
        [(str(s), str(d), o) for s, d, o in ops.copies]
    assert sorted(str(p) for p in ops.deletes) == sorted(
        [str(left / "new.txt"), str(left / "newdir")])


def test_identical_nodes_have_no_action(trees):
    view = _view(*trees)
    plan = _plan(view, dir_sync.MIRROR)
    assert plan.action(_node(view, "same.txt")) is None
    assert plan.glyph(_node(view, "same.txt")) is None
    assert plan.glyph(_node(view, "new.txt")) == " → "
    assert plan.glyph(_node(view, "extra.txt")) == " × "


# --------------------------------------------------------------------------- #
# the viewer
# --------------------------------------------------------------------------- #

def _key(name, char=None):
    return Event(type=EventType.KEY, key=name, char=char)


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def opened(trees, request):
    backend = MemoryBackend(width=120, height=30, capabilities=request.param)
    panel = Panel(backend)
    left, right = trees
    view = show_directory_diff_viewer(panel, Path(str(left)), Path(str(right)),
                                      background=False, config=_config.Config())
    panel.render()
    return panel, view


def _start(panel, view, mode_rows_down=0):
    panel.dispatch_event(_key("s", "s"))
    for _ in range(mode_rows_down):
        panel.dispatch_event(_key("down"))
    panel.dispatch_event(_key("enter"))
    assert view._plan is not None


def test_update_from_the_viewer(opened, trees):
    panel, view = opened
    left, right = trees
    _start(panel, view)
    assert view._plan.mode == dir_sync.UPDATE
    panel.render()
    panel.dispatch_event(_key("s", "s"))       # confirmation
    panel.dispatch_event(_key("enter"))        # default: Sync
    view.join()
    assert (right / "new.txt").read_text() == "n"
    assert (right / "newdir" / "f.txt").read_text() == "f"
    assert (right / "changed.txt").read_text() == "new"
    assert (right / "sub" / "a.txt").read_text() == "1"
    assert (right / "extra.txt").exists()
    assert view._plan is None


def test_mirror_confirmation_defaults_to_cancel(opened, trees):
    """Deleting for good asks twice: the confirmation starts on Cancel."""
    panel, view = opened
    left, right = trees
    view._fileops.config.DELETE_TO_TRASH = False   # no trash: for good
    _start(panel, view, mode_rows_down=1)
    assert view._plan.mode == dir_sync.MIRROR
    panel.dispatch_event(_key("s", "s"))
    panel.dispatch_event(_key("enter"))        # default: Cancel
    assert (right / "extra.txt").exists()
    assert not (right / "new.txt").exists()
    assert view._plan is not None              # still open to adjust

    panel.dispatch_event(_key("s", "s"))
    panel.dispatch_event(_key("left"))         # to "Sync"
    panel.dispatch_event(_key("enter"))
    view.join()
    assert not (right / "extra.txt").exists()
    assert (right / "new.txt").exists()


def test_mirror_deletes_to_the_trash_where_there_is_one(opened, trees, monkeypatch):
    """#603: a Mirror's deletions go to the trash, so the confirmation says so
    and starts on Sync — what it removes can be put back."""
    from xefm import trash
    sent = []

    def send(path):
        sent.append(str(path))
        os.remove(str(path))

    monkeypatch.setattr(trash, "available", lambda path: True)
    monkeypatch.setattr(trash, "send", send)
    panel, view = opened
    left, right = trees
    _start(panel, view, mode_rows_down=1)
    assert f"to the {trash.NAME}" in view._plan_summary(view._plan.operations(view.root))
    panel.dispatch_event(_key("s", "s"))
    panel.dispatch_event(_key("enter"))        # default: Sync
    view.join()
    assert sent == [str(right / "extra.txt")]
    assert (right / "new.txt").exists()


def test_space_skips_the_focused_node(opened, trees):
    panel, view = opened
    left, right = trees
    _start(panel, view)
    node = next(n for n in view.visible if n.name == "new.txt")
    view.cursor = view.visible.index(node)
    panel.dispatch_event(_key("space", " "))
    assert view._plan.action(node) == dir_sync.SKIP
    panel.dispatch_event(_key("s", "s"))
    panel.dispatch_event(_key("enter"))
    view.join()
    assert not (right / "new.txt").exists()
    assert (right / "changed.txt").read_text() == "new"


def test_esc_leaves_the_plan_not_the_viewer(opened):
    panel, view = opened
    _start(panel, view)
    panel.dispatch_event(_key("escape"))
    assert view._plan is None
    assert panel._layers[-1].widget is view


def test_tab_turns_the_plan_around(opened):
    panel, view = opened
    _start(panel, view)
    panel.dispatch_event(_key("tab"))
    assert view._plan.source == "right"
    panel.render()
    assert "right → left" in hints_text(view._footer())


def test_toggle_identical_hides_identical_rows(opened):
    panel, view = opened
    assert any(n.name == "same.txt" for n in view.visible)
    panel.dispatch_event(_key("d", "d"))
    assert not any(n.name == "same.txt" for n in view.visible)
    panel.dispatch_event(_key("d", "d"))
    assert any(n.name == "same.txt" for n in view.visible)


def test_the_plan_opens_showing_only_differences(opened):
    panel, view = opened
    _start(panel, view)
    assert not any(n.name == "same.txt" for n in view.visible)
    panel.render()   # the plan's gutter and footer draw
    assert "Update left → right" in hints_text(view._footer())
