"""Headless tests for the PuiKit directory diff viewer.

Run with: python -m pytest test/test_directory_diff_viewer.py -v

Covers the backend-agnostic classification/tree logic and the widget's
navigation + rendering on the MemoryBackend (TUI + GUI profiles); see
doc/dev/DIRECTORY_DIFF_VIEWER_SYSTEM.md.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import (
    CapabilityProfile, Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI,
)
from puikit.backends.memory_backend import MemoryBackend

from xefm.path import Path
from xefm.directory_diff_viewer import (
    DifferenceType,
    DiffEngine,
    DirectoryScanner,
    DirectoryDiffView,
    show_directory_diff_viewer,
)


from xefm import _config


def _sync_view(left, right, **kw):
    """A viewer scanned synchronously (deterministic for tests)."""
    return DirectoryDiffView(left, right, background=False, **kw)


@pytest.fixture
def config():
    """A real Config so the viewer's file-op keys + shared engine are enabled."""
    return _config.Config()


@pytest.fixture
def trees(tmp_path):
    """Two directory trees exercising every classification."""
    left = tmp_path / "L"
    right = tmp_path / "R"
    (left / "sub").mkdir(parents=True)
    (right / "sub").mkdir(parents=True)
    (left / "same.txt").write_text("hello")
    (right / "same.txt").write_text("hello")            # identical
    (left / "diff.txt").write_text("aaa")
    (right / "diff.txt").write_text("bbb")              # content-different
    (left / "only_left.txt").write_text("x")            # only-left
    (right / "only_right.txt").write_text("y")          # only-right
    (left / "sub" / "a.txt").write_text("1")
    (right / "sub" / "a.txt").write_text("2")           # nested difference
    return Path(str(left)), Path(str(right))


def _key(name, char=None):
    return Event(type=EventType.KEY, key=name, char=char)


def _find(node, name):
    return next((c for c in node.children if c.name == name), None)


# --- classification ----------------------------------------------------------


def test_classification(trees):
    left, right = trees
    tree = DiffEngine(DirectoryScanner().scan(left), DirectoryScanner().scan(right)).build_tree()
    assert _find(tree, "same.txt").difference_type is DifferenceType.IDENTICAL
    assert _find(tree, "diff.txt").difference_type is DifferenceType.CONTENT_DIFFERENT
    assert _find(tree, "only_left.txt").difference_type is DifferenceType.ONLY_LEFT
    assert _find(tree, "only_right.txt").difference_type is DifferenceType.ONLY_RIGHT
    sub = _find(tree, "sub")
    assert sub.difference_type is DifferenceType.CONTAINS_DIFFERENCE
    # Root summarises to "contains difference".
    assert tree.difference_type is DifferenceType.CONTAINS_DIFFERENCE


def test_scanner_respects_show_hidden(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "visible.txt").write_text("v")
    (d / ".hidden").write_text("h")
    shown = DirectoryScanner(show_hidden=True).scan(Path(str(d)))
    hidden = DirectoryScanner(show_hidden=False).scan(Path(str(d)))
    assert ".hidden" in shown
    assert ".hidden" not in hidden
    assert "visible.txt" in hidden


# --- tree / navigation -------------------------------------------------------


def test_directories_start_collapsed(trees):
    # Only the root is open — directories are NOT auto-expanded, even
    # when they contain a difference. The user drills down themselves.
    view = _sync_view(*trees)
    sub = _find(view.root, "sub")
    assert sub.difference_type is DifferenceType.CONTAINS_DIFFERENCE
    assert not sub.is_expanded
    assert not any(n.name == "a.txt" for n in view.visible)


def test_expand_reveals_nested_difference(trees):
    view = _sync_view(*trees)
    sub = _find(view.root, "sub")
    view.cursor = view.visible.index(sub)
    view._toggle(expand=True)   # user opens it
    assert any(n.name == "a.txt" and n.depth == 2 for n in view.visible)


def test_expand_collapse_index_integrity(trees):
    view = _sync_view(*trees)
    sub = _find(view.root, "sub")
    view.cursor = view.visible.index(sub)
    view._toggle(expand=False)
    assert not any(n.name == "a.txt" for n in view.visible)
    # Cursor stays on the (now collapsed) sub node.
    assert view.visible[view.cursor] is sub
    view._toggle(expand=True)
    assert any(n.name == "a.txt" for n in view.visible)
    assert view.visible[view.cursor] is sub


def test_step_diff_skips_identical(trees):
    view = _sync_view(*trees)
    seen = set()
    for _ in range(len(view.visible)):
        view._step_diff(1)
        node = view.visible[view.cursor]
        assert node.difference_type is not DifferenceType.IDENTICAL
        seen.add(node.name)
    # The identical file is never landed on.
    assert "same.txt" not in seen


def test_cursor_clamps_at_ends(trees):
    view = _sync_view(*trees)
    view._move_cursor(-100)
    assert view.cursor == 0
    view._move_cursor(100)
    assert view.cursor == len(view.visible) - 1


# --- rendering + wiring ------------------------------------------------------


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=100, height=30, capabilities=request.param)


def test_push_and_render(backend, trees):
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False)
    assert panel._layers[-1].widget is view
    panel.render()  # must not raise
    rows = backend.snapshot()
    # A difference separator glyph is drawn somewhere in the tree.
    assert any(" ! " in row or " < " in row or " > " in row for row in rows)
    # Names render in both the grid (box-char) and vector (drawn-line) paths.
    text = "\n".join(rows)
    assert "diff.txt" in text and "sub" in text


def test_navigation_events_render(backend, trees):
    panel = Panel(backend)
    show_directory_diff_viewer(panel, *trees, background=False)
    panel.render()
    for ev in (_key("down"), _key("up"), _key("tab"),
               _key(None, "n"), _key(None, "N"), _key("end"), _key("home")):
        panel.dispatch_event(ev)
        panel.render()  # each must not raise


def test_gutter_drag_is_offset_preserving_and_brightens(trees):
    # The centre gutter drags through the shared DragBar: grabbing it off the
    # divider line does not jump the split to the pressed point, and while
    # dragging the whole band brightens (GUI profile: transparency composites).
    from puikit.widgets import dragbar as dragbar_mod

    backend = MemoryBackend(width=100, height=30, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False)
    panel.render()
    assert view._resizable
    ratio0 = view._split_ratio
    gx = view._sep_x + 1.0  # inside the 3-unit gutter, off its left edge

    # Press: arms the drag WITHOUT moving the split (no jump to the pressed point).
    panel.dispatch_event(Event(type=EventType.MOUSE_DOWN, x=gx, y=5.0, button="left"))
    assert view._drag.dragging
    assert view._split_ratio == pytest.approx(ratio0)

    # While dragging, the gutter band brightens with the neutral wash.
    panel.render()
    assert backend.style_at(round(view._sep_x) + 1, 3).bg == dragbar_mod._WASH

    # Drag right by 10: the split tracks the pointer's motion (offset preserved),
    # so the left pane grows.
    panel.dispatch_event(Event(type=EventType.MOUSE_DRAG, x=gx + 10.0, y=5.0, button="left"))
    assert view._split_ratio > ratio0

    # Release ends the drag; the brighten stops.
    panel.dispatch_event(Event(type=EventType.MOUSE_UP, x=gx + 10.0, y=5.0, button="left"))
    assert not view._drag.dragging


def test_escape_closes(backend, trees):
    panel = Panel(backend)
    show_directory_diff_viewer(panel, *trees, background=False)
    panel.render()
    panel.dispatch_event(_key("escape"))
    assert panel._layers == []


def test_help_key_pushes_markdown_overlay(backend, trees):
    panel = Panel(backend)
    show_directory_diff_viewer(panel, *trees, background=False)
    panel.render()
    panel.dispatch_event(_key(None, "?"))
    panel.render()  # must not raise
    # A help overlay (Markdown) stacks above the viewer.
    assert len(panel._layers) == 2
    assert type(panel._layers[-1].widget).__name__ == "MarkdownDialog"


def test_enter_on_differing_file_opens_file_diff(backend, trees):
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False)
    panel.render()
    diff_node = _find(view.root, "diff.txt")
    view.cursor = view.visible.index(diff_node)
    view.active = "left"
    panel.dispatch_event(_key("enter"))
    # A per-file DiffViewer layer is pushed on top.
    assert len(panel._layers) == 2


class _VectorBackend(MemoryBackend):
    """A grid backend that *claims* vector_shapes so the viewer's drawn-line
    (GUI) path — including the disclosure chevron — is exercised headlessly.
    (The real MemoryBackend masks the capability off.)"""

    @property
    def capabilities(self) -> CapabilityProfile:
        return CapabilityProfile({**self._capabilities, "vector_shapes": True})


def test_directory_rows_draw_vector_chevron_not_glyph(trees):
    backend = _VectorBackend(width=100, height=30, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    show_directory_diff_viewer(panel, *trees, background=False)
    panel.render()
    # The "sub" directory draws a disclosure chevron on the vector path (once
    # per side it exists on), and the ▸/▾ glyph no longer leaks onto the grid.
    assert backend.chevron_calls, "a directory row should stroke a vector chevron"
    text = "\n".join(backend.snapshot())
    assert "▸" not in text and "▾" not in text
    assert "sub" in text  # the label still renders next to the chevron


@pytest.fixture
def lopsided(tmp_path):
    """Root dirs sorted 0lead < a_dir < m_dir < z_dir < zztrail. ``a_dir``/
    ``z_dir`` exist on both sides; ``0lead`` (leads), the nested ``m_dir``
    (bridges), and ``zztrail`` (trails) are left-only. On the right side these
    exercise: a root-level leading row (spine still reaches the header), a
    bridging row, a trailing row (no bar), and an absent deep subtree (blanked)."""
    left = tmp_path / "L"
    right = tmp_path / "R"
    for base in (left, right):
        (base / "a_dir").mkdir(parents=True)
        (base / "z_dir").mkdir(parents=True)
    (left / "0lead").mkdir()
    (left / "zztrail").mkdir()
    (left / "m_dir" / "deep").mkdir(parents=True)
    (left / "m_dir" / "deep" / "f.txt").write_text("x")
    return Path(str(left)), Path(str(right))


def test_missing_side_connector_spanning_rules(lopsided):
    view = _sync_view(*lopsided)
    lead = _find(view.root, "0lead")
    trail = _find(view.root, "zztrail")
    m = _find(view.root, "m_dir")
    f = _find(_find(m, "deep"), "f.txt")

    # The chain is the ancestor node path; each level's owner is its parent.
    assert [n.name for n in view._connector_chain(f)] == ["m_dir", "deep", "f.txt"]

    # RIGHT side (0lead / m_dir / zztrail all absent there):
    # - a root-level LEADING row still draws its bar: the root spine runs up to
    #   the pane header even with nothing present above it.
    assert view._tree_lines(lead, branch=False, side_is_left=False) == "│ "
    # - a root-level TRAILING row draws nothing (no header below, nothing follows).
    assert view._tree_lines(trail, branch=False, side_is_left=False).strip() == ""
    # - a deep left-only row keeps the root bar; its absent ancestors (m_dir,
    #   deep) stay blank — no floating skeleton.
    right = view._tree_lines(f, branch=False, side_is_left=False)
    assert right[:2] == "│ "
    assert right[2:] == "    "

    # LEFT side: every ancestor of f exists, so the chain renders in full.
    left = view._tree_lines(f, branch=False, side_is_left=True)
    assert left[:2] == "│ "        # root list continues (z_dir follows m_dir)
    assert left.strip("│ ") == ""  # only bars/blanks, all ancestors present


# --- progressive scanning (slice 3) ------------------------------------------


def test_scan_level_lists_immediate_children_only(tmp_path):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "top.txt").write_text("t")
    (d / "sub" / "nested.txt").write_text("n")
    level = DirectoryScanner().scan_level(Path(str(d)))
    assert set(level) == {"sub", "top.txt"}          # nested.txt NOT listed
    assert level["sub"].is_directory and level["sub"].relative_path == "sub"


def test_background_scan_grows_breadth_first_and_converges(tmp_path):
    """The background pass must reach the same finished tree the synchronous full
    walk builds — deep both-sided branches included."""
    left, right = tmp_path / "L", tmp_path / "R"
    for root in (left, right):
        (root / "a" / "b" / "c").mkdir(parents=True)
        (root / "a" / "b" / "c" / "leaf.txt").write_text("same")
    (right / "a" / "b" / "c" / "leaf.txt").write_text("changed")   # deep diff
    lp, rp = Path(str(left)), Path(str(right))

    bg = DirectoryDiffView(lp, rp, background=True)
    bg.join()
    # Expand the whole tree so every node is flattened into `visible`.
    for n in bg._iter_nodes(bg.root):
        if n.is_directory:
            n.is_expanded = True
    bg._reflow()
    leaf = next(n for n in bg.visible if n.name == "leaf.txt")
    assert leaf.difference_type is DifferenceType.CONTENT_DIFFERENT
    # The deep difference propagates up every ancestor directory.
    assert all(n.difference_type is DifferenceType.CONTAINS_DIFFERENCE
               for n in bg.visible if n.is_directory)


def test_empty_two_sided_dir_resolves_identical(tmp_path):
    """A two-sided directory with no children must settle on IDENTICAL, not stay
    PENDING (an empty dir has no child resolution to trigger a reclassify)."""
    left, right = tmp_path / "L", tmp_path / "R"
    (left / "empty").mkdir(parents=True)
    (right / "empty").mkdir(parents=True)
    view = DirectoryDiffView(Path(str(left)), Path(str(right)), background=True)
    view.join()
    assert _find(view.root, "empty").difference_type is DifferenceType.IDENTICAL
    assert view.root.difference_type is DifferenceType.IDENTICAL


def test_one_sided_dir_scanned_lazily_on_expand(tmp_path):
    """One-sided directories aren't walked up front; their contents materialise
    only when the user expands them (lazy scan)."""
    left, right = tmp_path / "L", tmp_path / "R"
    (left / "only" / "deep").mkdir(parents=True)
    (left / "only" / "deep" / "x.txt").write_text("x")
    right.mkdir()
    view = DirectoryDiffView(Path(str(left)), Path(str(right)), background=True)
    view.join()
    only = _find(view.root, "only")
    assert only.difference_type is DifferenceType.ONLY_LEFT
    assert not only.children_scanned          # not walked during the initial pass
    # Focus + expand it: the level is scanned inline and its child appears.
    view.cursor = view.visible.index(only)
    view._toggle(expand=True)
    assert only.children_scanned
    assert _find(only, "deep") is not None


def test_footer_reports_scan_queue_progress(trees):
    # Use the synchronous view (no worker thread) and drive the progress fields
    # directly so the assertion can't race a background finish.
    view = _sync_view(*trees)
    view._scanning = True
    view._phase = "scan"
    view._dirs_scanned, view._dirs_total = 2, 5
    footer = view._footer()
    assert "40%" in footer and "queued" in footer


def test_background_scan_populates_and_resolves(trees):
    view = DirectoryDiffView(*trees, background=True)
    view.join()
    assert not view._scanning
    # The nested child was discovered (in the tree, though "sub" stays collapsed).
    assert _find(_find(view.root, "sub"), "a.txt") is not None
    # Deferred comparison resolved every file's verdict (nothing left pending).
    assert _find(view.root, "diff.txt").difference_type is DifferenceType.CONTENT_DIFFERENT
    assert _find(view.root, "same.txt").difference_type is DifferenceType.IDENTICAL
    assert not any(n.difference_type is DifferenceType.PENDING
                   for n in view._iter_nodes(view.root))


def test_tick_renders_when_dirty_and_stops_when_done(trees):
    view = DirectoryDiffView(*trees, background=True)
    calls = []
    view._panel = type("P", (), {"render": lambda self: calls.append(1)})()
    view.join()
    # Drive ticks until the callback unregisters (returns False).
    for _ in range(10):
        if not view._tick():
            break
    assert calls, "tick should have rendered at least the final frame"
    # Once idle and clean, the tick returns False so the backend drops it.
    assert view._tick() is False


def test_cancel_stops_the_tick(trees):
    view = DirectoryDiffView(*trees, background=True)
    view.join()
    view.cancel()
    assert view._tick() is False


# --- file operations across sides (slice 4) ----------------------------------


def test_copy_focused_creates_file_on_other_side(backend, trees, config):
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False, config=config)
    panel.render()
    node = _find(view.root, "only_left.txt")
    view.cursor = view.visible.index(node)
    view.active = "left"
    view._copy_focused()          # pushes a confirmation message box
    panel.dispatch_event(_key("enter"))  # default button is "Copy"
    view.join()
    assert (trees[1] / "only_left.txt").exists()


def test_copy_key_from_config_creates_file(backend, trees, config):
    """The copy key comes from KEY_BINDINGS (C), not a hardcoded 'c' branch."""
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False, config=config)
    panel.render()
    node = _find(view.root, "only_left.txt")
    view.cursor = view.visible.index(node)
    view.active = "left"
    panel.dispatch_event(_key("c"))      # 'C' binding → copy_files → confirm box
    panel.dispatch_event(_key("enter"))  # default button is "Copy"
    view.join()
    assert (trees[1] / "only_left.txt").exists()


def test_move_focused_moves_file_to_other_side(backend, trees, config):
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False, config=config)
    panel.render()
    node = _find(view.root, "only_left.txt")
    view.cursor = view.visible.index(node)
    view.active = "left"
    view._move_focused()
    panel.dispatch_event(_key("enter"))  # default button is "Move"
    view.join()
    assert (trees[1] / "only_left.txt").exists()
    assert not (trees[0] / "only_left.txt").exists()


def test_delete_focused_removes_file(backend, trees, config):
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False, config=config)
    panel.render()
    node = _find(view.root, "only_left.txt")
    view.cursor = view.visible.index(node)
    view.active = "left"
    view._delete_focused()        # confirm box, default = Cancel
    panel.dispatch_event(_key("left"))   # focus the "Delete" button
    panel.dispatch_event(_key("enter"))
    view.join()
    assert not (trees[0] / "only_left.txt").exists()


def test_delete_cancel_keeps_file(backend, trees, config):
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False, config=config)
    panel.render()
    node = _find(view.root, "only_left.txt")
    view.cursor = view.visible.index(node)
    view.active = "left"
    view._delete_focused()
    panel.dispatch_event(_key("enter"))  # default = Cancel
    assert (trees[0] / "only_left.txt").exists()


def test_rescan_preserves_collapsed_state(trees):
    view = DirectoryDiffView(*trees, background=True)
    view.join()
    sub = _find(view.root, "sub")
    view.cursor = view.visible.index(sub)
    view._toggle(expand=False)
    view._restart_scan()
    view.join()
    assert not _find(view.root, "sub").is_expanded


def test_rescan_preserves_expanded_state(trees):
    view = DirectoryDiffView(*trees, background=True)
    view.join()
    sub = _find(view.root, "sub")
    view.cursor = view.visible.index(sub)
    view._toggle(expand=True)                   # user expands it
    assert _find(view.root, "sub").is_expanded
    view._restart_scan()
    view.join()
    assert _find(view.root, "sub").is_expanded  # expansion survived the rescan


def test_help_pushes_message_box(backend, trees):
    panel = Panel(backend)
    view = show_directory_diff_viewer(panel, *trees, background=False)
    panel.render()
    view._show_help()
    assert len(panel._layers) == 2


def test_deferred_build_leaves_files_pending():
    # A tree built without content comparison marks two-sided files PENDING
    # and summarises their directory as PENDING (not yet known).
    from xefm.directory_diff_viewer import FileInfo

    def info(rel, is_dir=False):
        return FileInfo(Path("/x/" + rel), rel, is_dir, 0, 0.0, True)

    left = {"a.txt": info("a.txt")}
    right = {"a.txt": info("a.txt")}
    tree = DiffEngine(left, right, compare_content=False).build_tree()
    assert _find(tree, "a.txt").difference_type is DifferenceType.PENDING
    assert tree.difference_type is DifferenceType.PENDING
