"""Mouse operation in the file list (#589): marking with Cmd/Ctrl-click and
Shift-click, double-click to open, middle-click, the back / forward buttons
and actions, the draggable scrollbar, breadcrumbs in the pane header,
clickable hints and footer settings, and move-or-copy on drop.

Run with: python -m pytest test/test_mouse_operation.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit.backends import create_backend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402

from xefm import app as xefm_app  # noqa: E402
from xefm.file_pane import FilePane  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


class _F:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return "/a/" + self.name


def _pane(files):
    return {"files": list(files), "file_info": {}, "selected_files": set(),
            "path": Path("/tmp"), "focused_index": 0, "scroll_offset": 0}


def _ev(kind, y, button="left", mods=(), x=1.0):
    return Event(type=kind, x=x, y=y, button=button, modifiers=frozenset(mods))


def _press_release(view, y, mods=(), x=1.0):
    view.handle_event(_ev(EventType.MOUSE_DOWN, y, mods=mods, x=x))
    view.handle_event(_ev(EventType.MOUSE_UP, y, mods=mods, x=x))
    return view.handle_event(_ev(EventType.MOUSE_CLICK, y, mods=mods, x=x))


class FilePaneGestures(unittest.TestCase):
    def _view(self, n=3, **cb):
        view = FilePane(_pane([_F(str(i)) for i in range(n)]), **cb)
        view._margin_y = 0.0
        return view

    def test_modifiers_and_click_count_reach_the_controller(self):
        seen = []
        view = self._view(on_click=lambda i, mods, clicks: seen.append((i, mods, clicks)))
        _press_release(view, 1.0, mods=("cmd",))
        _press_release(view, 2.0)
        _press_release(view, 2.0)
        self.assertEqual(seen, [(1, frozenset({"cmd"}), 1), (2, frozenset(), 1),
                                (2, frozenset(), 2)])

    def test_a_drag_between_presses_is_not_a_double_click(self):
        seen = []
        view = self._view(on_click=lambda i, mods, clicks: seen.append(clicks),
                          on_drag=lambda i, ev: None)
        _press_release(view, 1.0)
        view.handle_event(_ev(EventType.MOUSE_DOWN, 1.0))
        view.handle_event(_ev(EventType.MOUSE_DRAG, 9.0, x=9.0))
        view.handle_event(_ev(EventType.MOUSE_UP, 1.0))
        _press_release(view, 1.0)
        self.assertEqual(seen[-1], 1)

    def test_middle_and_side_buttons(self):
        middle, nav = [], []
        view = self._view(on_middle=middle.append, on_nav=nav.append)
        view.handle_event(_ev(EventType.MOUSE_CLICK, 1.0, button="middle"))
        view.handle_event(_ev(EventType.MOUSE_CLICK, 1.0, button="back"))
        view.handle_event(_ev(EventType.MOUSE_CLICK, 1.0, button="forward"))
        self.assertEqual(middle, [1])
        self.assertEqual(nav, ["back", "forward"])

    def _bar_view(self):
        clicks = []
        view = self._view(n=100, on_click=lambda *a: clicks.append(a))
        view._bar = (19.0, 0.0, 10.0, 100)   # x, top, height, rows
        return view, clicks

    def test_the_scrollbar_track_pages(self):
        view, clicks = self._bar_view()
        _press_release(view, 8.0, x=19.5)   # below the thumb at the top
        self.assertEqual(view.offset, 10.0)
        self.assertEqual(clicks, [], "a press on the bar is not a row click")

    def test_the_thumb_drags(self):
        view, _ = self._bar_view()
        view.handle_event(_ev(EventType.MOUSE_DOWN, 0.5, x=19.5))   # on the thumb
        view.handle_event(_ev(EventType.MOUSE_DRAG, 9.5, x=19.5))   # to the bottom
        view.handle_event(_ev(EventType.MOUSE_UP, 9.5, x=19.5))
        self.assertEqual(view.offset, 90.0)


class Breadcrumbs(unittest.TestCase):
    def test_components_map_to_ancestors_from_the_right(self):
        measure = len
        crumbs = xefm_app._breadcrumbs("/…/b/c", Path("/x/a/b/c"), 0.0, measure)
        targets = [(text_x0, str(target), child) for text_x0, _x1, target, child in crumbs]
        # A local path is spelled with the native separator (\ on Windows).
        self.assertIn((5, str(Path("/x/a/b/c")), None), targets)
        self.assertIn((3, str(Path("/x/a/b")), "c"), targets)
        self.assertFalse(any(t == str(Path("/x/a")) for _, t, _c in targets),
                         "… is not a place")
        self.assertIn((0, str(Path("/")), "x"), targets, "the leading / is the root")

    def test_home_abbreviation(self):
        home = os.path.expanduser("~")
        crumbs = xefm_app._breadcrumbs("~/p", Path(os.path.join(home, "p")), 0.0, len)
        self.assertEqual([str(t) for _a, _b, t, _c in crumbs],
                         [os.path.join(home, "p"), home])


class AppMouse(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.state_dir = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.tmp, "sub"))
        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write(name)
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.b.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def idx(self, name, pane="left"):
        return [f.name for f in self.app.pane(pane)["files"]].index(name)

    def marked(self, pane="left"):
        return sorted(os.path.basename(p) for p in self.app.pane(pane)["selected_files"])

    def test_cmd_or_ctrl_click_toggles_and_plain_click_keeps_marks(self):
        self.app._on_click("left", self.idx("a.txt"), frozenset({"cmd"}))
        self.app._on_click("left", self.idx("c.txt"), frozenset({"ctrl"}))
        self.assertEqual(self.marked(), ["a.txt", "c.txt"])
        self.app._on_click("left", self.idx("d.txt"))
        self.assertEqual(self.marked(), ["a.txt", "c.txt"], "a plain click leaves marks")
        self.app._on_click("left", self.idx("a.txt"), frozenset({"cmd"}))
        self.assertEqual(self.marked(), ["c.txt"])

    def test_shift_click_adds_the_range_from_the_anchor(self):
        self.app._on_click("left", self.idx("a.txt"))
        self.app._on_click("left", self.idx("c.txt"), frozenset({"shift"}))
        self.assertEqual(self.marked(), ["a.txt", "b.txt", "c.txt"])
        self.assertEqual(self.app.pane("left")["focused_index"], self.idx("c.txt"))

    def test_double_click_opens_a_directory(self):
        self.app._on_click("left", self.idx("sub"), frozenset(), 2)
        self.app._settle_listings()
        self.assertEqual(str(self.app.pane("left")["path"]), os.path.join(self.tmp, "sub"))

    def test_a_modified_double_click_opens_nothing(self):
        self.app._on_click("left", self.idx("sub"), frozenset({"cmd"}), 2)
        self.app._settle_listings()
        self.assertEqual(str(self.app.pane("left")["path"]), self.tmp)

    def test_middle_click_opens_a_directory_in_the_other_pane(self):
        self.app._on_middle_click("left", self.idx("sub"))
        self.app._settle_listings()
        self.assertEqual(str(self.app.pane("right")["path"]), os.path.join(self.tmp, "sub"))
        self.assertEqual(str(self.app.pane("left")["path"]), self.tmp)

    def test_back_and_forward(self):
        pane = self.app.pane("left")
        self.app.pm.active_pane = "left"
        self.app._go_to_dir(pane, Path(os.path.join(self.tmp, "sub")), None)
        self.app._settle_listings()
        self.app.go_back()
        self.app._settle_listings()
        self.assertEqual(str(pane["path"]), self.tmp)
        self.assertEqual(pane["files"][pane["focused_index"]].name, "sub",
                         "back to the parent lands on the folder left")
        self.app.go_forward()
        self.app._settle_listings()
        self.assertEqual(str(pane["path"]), os.path.join(self.tmp, "sub"))
        logs = []
        with patch.object(self.app, "log_info", logs.append):
            self.app.go_forward()
        self.assertIn("Nothing to go forward to", logs)

    def test_a_new_step_clears_forward(self):
        pane = self.app.pane("left")
        self.app._go_to_dir(pane, Path(os.path.join(self.tmp, "sub")), None)
        self.app._settle_listings()
        self.app.go_back()
        self.app._settle_listings()
        self.app._go_to_dir(pane, Path(os.path.join(self.tmp, "sub")), None)
        self.app._settle_listings()
        self.assertEqual(pane.get("_forward"), [])

    def _capture(self):
        calls = []
        self.app._fileops.copy = lambda panel, t, d, **kw: calls.append(("copy", t, d))
        self.app._fileops.move = lambda panel, t, d, **kw: calls.append(("move", t, d))
        return calls

    def test_an_unmodified_drop_moves_within_a_volume(self):
        outside = os.path.realpath(tempfile.mkdtemp(dir=os.path.dirname(self.tmp)))
        try:
            src = os.path.join(outside, "x.txt")
            open(src, "w").close()
            calls = self._capture()
            self.app._on_drop("left", -1, [src])
            self.assertEqual(calls[0][0], "move")
            self.app._on_drop("left", -1, [src], "copy")
            self.assertEqual(calls[1][0], "copy", "the modifier wins")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_a_drop_across_volumes_copies(self):
        calls = self._capture()
        with patch.object(xefm_app, "_same_volume", return_value=False):
            self.app._on_drop("left", -1, ["/elsewhere/x.txt"])
        self.assertEqual(calls[0][0], "copy")

    def test_a_link_drop_is_refused(self):
        calls = self._capture()
        self.app._on_drop("left", -1, ["/elsewhere/x.txt"], "link")
        self.assertEqual(calls, [])

    def _render(self):
        self.app.panel.render()

    def test_status_bar_hints_run_their_action(self):
        self._render()
        bar = self.app.status
        self.assertTrue(bar._hits, "hints were laid out")
        hit = bar._hits[0]
        ran = []
        with patch.object(self.app, "_run_action", lambda ctx, a, **kw: ran.append(a)):
            bar.handle_event(Event(type=EventType.MOUSE_CLICK, x=(hit.x0 + hit.x1) / 2,
                                   y=0.0, button="left"))
        self.assertEqual(ran, [bar._HINTS[0][0]])

    def test_footer_sort_opens_the_sort_menu(self):
        # The test window is 80 columns; leave the free-space readout out so
        # the sort label is not elided away.
        self.app.disk_free_total = lambda pane: None
        self._render()
        footer = self.app._footers["left"]
        hit = next(h for h in footer._hits if h[2] == "sort")
        ran = []
        with patch.object(self.app, "_run_action", lambda ctx, a, **kw: ran.append(a)):
            footer.handle_event(Event(type=EventType.MOUSE_CLICK, x=(hit[0] + hit[1]) / 2,
                                      y=0.0, button="left"))
        self.assertEqual(ran, ["sort"])

    def test_header_click_goes_to_that_directory(self):
        pane = self.app.pane("left")
        self.app._go_to_dir(pane, Path(os.path.join(self.tmp, "sub")), None)
        self.app._settle_listings()
        self._render()
        header = self.app._headers["left"]
        crumb = next(c for c in header._crumbs if str(c[2]) == self.tmp)
        header.handle_event(Event(type=EventType.MOUSE_CLICK, x=(crumb[0] + crumb[1]) / 2,
                                  y=0.0, button="left"))
        self.app._settle_listings()
        self.assertEqual(str(pane["path"]), self.tmp)
        self.assertEqual(pane["files"][pane["focused_index"]].name, "sub")


if __name__ == "__main__":
    unittest.main()


class DragOverBadge(unittest.TestCase):
    """While files are dragged over a pane, it answers what a drop there would
    do, so the cursor badge matches the drop (#589 hand check)."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.state_dir = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        os.mkdir(self.src)
        self.file = os.path.join(self.src, "a.txt")
        open(self.file, "w").close()
        self.dest = os.path.join(self.tmp, "dest")
        os.mkdir(self.dest)
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.dest, self.src,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app.file_monitor.stop_monitoring()
        self.app._settle_listings()
        self.app.panel.render()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.b.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _ask(self, operation=None):
        rect = self.app.left_view._abs
        query = Event(type=EventType.FILE_DRAG_OVER, x=rect[0] + 2, y=rect[1] + 3,
                      hints={"paths": [self.file], "operation": operation})
        self.app.on_event(query)
        return query.hints.get("effect")

    def test_an_unmodified_drag_on_the_same_volume_shows_a_move(self):
        self.assertEqual(self._ask(), "move")

    def test_the_modifier_s_choice_is_shown(self):
        self.assertEqual(self._ask("copy"), "copy")

    def test_a_drag_across_volumes_shows_a_copy(self):
        with patch.object(xefm_app, "_same_volume", return_value=False):
            self.assertEqual(self._ask(), "copy")

    def test_a_place_that_refuses_shows_none(self):
        self.app.pane("left")["virtual"] = {"kind": "list", "title": "x", "root": None}
        self.assertEqual(self._ask(), "none")


class FooterClickAfterRowClick(unittest.TestCase):
    """The footer sits on the log splitter's grab band. A click on its sort
    label opens the sort menu even after a file row was clicked (#589 hand
    check), and dragging it resizes the log without opening anything."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.state_dir = tempfile.mkdtemp()
        for n in ("a", "b", "c"):
            open(os.path.join(self.tmp, n), "w").close()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app.file_monitor.stop_monitoring()
        self.app._settle_listings()
        self.app.disk_free_total = lambda pane: None
        self.app.panel.render()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.b.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _press(self, x, y, drag_to=None):
        self.app.on_event(Event(type=EventType.MOUSE_DOWN, x=x, y=y, button="left"))
        if drag_to is not None:
            self.app.on_event(Event(type=EventType.MOUSE_DRAG, x=x, y=drag_to, button="left"))
        self.app.on_event(Event(type=EventType.MOUSE_UP, x=x,
                                y=y if drag_to is None else drag_to, button="left"))

    def test_sort_label_click_after_a_row_click(self):
        footer = self.app._footers["left"]
        x0, x1, _ = next(h for h in footer._hits if h[2] == "sort")
        fx, fy, _w, _h = footer.rect
        ran = []
        with patch.object(self.app, "_run_action", lambda c, n, **k: ran.append(n)):
            self._press(5, 3)                          # a file row first
            self._press(fx + (x0 + x1) / 2, fy + 0.2)  # then the sort label
            self.assertEqual(ran, ["sort"])
            before = self.app.content_splitter.fraction
            self._press(fx + (x0 + x1) / 2, fy + 0.2, drag_to=fy - 4)
        self.assertEqual(ran, ["sort"], "a resize is not a click")
        self.assertNotEqual(self.app.content_splitter.fraction, before)
