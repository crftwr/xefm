"""Drag-out and drop-in wiring for the file panes.

Two directions, both GUI-only in practice but driven here headlessly:

- **Drag-out** — a left-press over a row that travels past ``DRAG_THRESHOLD``
  starts a native OS file drag. The FilePane detects the gesture and calls
  ``on_drag``; ``XeFMApp._start_drag`` turns that into ``panel.begin_file_drag``
  with the row (or the whole selection) and skips non-local entries.
- **Drop-in** — a ``FILE_DROP`` event carrying OS paths is routed to the pane
  under the pointer; the FilePane calls ``on_drop`` and ``XeFMApp._on_drop``
  copies the dropped files into the target directory (a folder row targets that
  folder), refusing read-only / virtual destinations.
"""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.file_pane import FilePane, DRAG_THRESHOLD  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402


def _pane(files):
    """A minimal pane-data dict the FilePane reads for gesture routing."""
    return {
        "files": list(files),
        "file_info": {},
        "selected_files": set(),
        "path": Path("/tmp"),
        "focused_index": 0,
        "scroll_offset": 0,
    }


class _F:
    """A file entry the pane renders — only ``.name`` / ``str()`` are read here."""
    def __init__(self, path):
        self._p = path
        self.name = os.path.basename(path)

    def __str__(self):
        return self._p


class FilePaneGesture(unittest.TestCase):
    def _pane_widget(self, files, **cb):
        view = FilePane(_pane(files), **cb)
        view._margin_y = 0.0  # no inset: row index == floor(y)
        return view

    def test_press_then_far_drag_starts_drag_once(self):
        calls = []
        view = self._pane_widget([_F("/a/one"), _F("/a/two")],
                                 on_drag=lambda i, ev: calls.append(i))
        view.handle_event(Event(type=EventType.MOUSE_DOWN, x=1.0, y=0.5, button="left"))
        # A tiny move stays a click, not a drag.
        view.handle_event(Event(type=EventType.MOUSE_DRAG, x=1.2, y=0.6, button="left"))
        self.assertEqual(calls, [])
        # Past the threshold: exactly one drag fires for row 0.
        view.handle_event(Event(type=EventType.MOUSE_DRAG,
                                x=1.0 + DRAG_THRESHOLD, y=2.0, button="left"))
        view.handle_event(Event(type=EventType.MOUSE_DRAG, x=8.0, y=6.0, button="left"))
        self.assertEqual(calls, [0])

    def test_press_on_empty_space_never_drags(self):
        calls = []
        view = self._pane_widget([_F("/a/one")],
                                 on_drag=lambda i, ev: calls.append(i))
        # Press below the only row (index out of range) → no draggable row.
        view.handle_event(Event(type=EventType.MOUSE_DOWN, x=1.0, y=5.0, button="left"))
        view.handle_event(Event(type=EventType.MOUSE_DRAG, x=9.0, y=9.0, button="left"))
        self.assertEqual(calls, [])

    def test_file_drop_reports_paths_and_row(self):
        drops = []
        view = self._pane_widget([_F("/a/one"), _F("/a/two")],
                                 on_drop=lambda i, paths: drops.append((i, paths)))
        view.handle_event(Event(type=EventType.FILE_DROP, x=1.0, y=1.0,
                                hints={"paths": ["/x/f.txt"]}))
        self.assertEqual(drops, [(1, ["/x/f.txt"])])

    def test_file_drop_below_rows_targets_pane_dir(self):
        drops = []
        view = self._pane_widget([_F("/a/one")],
                                 on_drop=lambda i, paths: drops.append((i, paths)))
        view.handle_event(Event(type=EventType.FILE_DROP, x=1.0, y=9.0,
                                hints={"paths": ["/x/f.txt"]}))
        self.assertEqual(drops, [(-1, ["/x/f.txt"])])


class AppDragDrop(unittest.TestCase):
    """End-to-end through a headless XeFMApp on the memory backend."""

    def setUp(self):
        from puikit.backends import create_backend
        self.src = tempfile.mkdtemp()
        self.dst = tempfile.mkdtemp()
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.src, self.dst,
                              left_provided=True, right_provided=True)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.src, ignore_errors=True)
        shutil.rmtree(self.dst, ignore_errors=True)

    def _write(self, root, rel, content="x"):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p) or root, exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        return p

    # --- drag-out ---

    def test_start_drag_calls_begin_file_drag_with_row(self):
        self._write(self.src, "a.txt")
        self.app._list_pane("left")
        self.app._settle_listings()
        pane = self.app.pane("left")
        idx = next(i for i, f in enumerate(pane["files"]) if f.name == "a.txt")

        seen = {}

        def fake(paths, event=None, operations=("copy",), on_complete=None):
            seen["paths"] = list(paths)
            seen["ops"] = operations
            return True

        self.app.panel.begin_file_drag = fake
        self.app._start_drag("left", idx, Event(type=EventType.MOUSE_DRAG, x=0, y=0))
        # The exported path is exactly the pane entry's path (symlink-resolved dirs
        # and all), and copy is the only operation offered.
        self.assertEqual(seen["paths"], [str(pane["files"][idx])])
        self.assertEqual(seen["ops"], ("copy",))

    def test_start_drag_carries_whole_selection(self):
        for n in ("a.txt", "b.txt", "c.txt"):
            self._write(self.src, n)
        self.app._list_pane("left")
        self.app._settle_listings()
        pane = self.app.pane("left")
        by_name = {f.name: (i, f) for i, f in enumerate(pane["files"])}
        # Select a and c; drag c → both a and c go, in listing order.
        pane["selected_files"] = {str(by_name["a.txt"][1]), str(by_name["c.txt"][1])}

        seen = {}
        self.app.panel.begin_file_drag = (
            lambda paths, **kw: (seen.__setitem__("paths", list(paths)), True)[1])
        self.app._start_drag("left", by_name["c.txt"][0],
                             Event(type=EventType.MOUSE_DRAG, x=0, y=0))
        self.assertEqual(
            seen["paths"],
            [str(by_name["a.txt"][1]), str(by_name["c.txt"][1])],
        )

    # --- drop-in ---

    def _capture_copy(self):
        """Replace the copy engine with a recorder so the wiring (targets +
        destination) is asserted without running the threaded operation."""
        calls = []
        self.app._fileops.copy = (
            lambda panel, targets, dest_dir, **kw: calls.append((targets, dest_dir)))
        return calls

    def test_drop_copies_external_file_into_pane_dir(self):
        outside = tempfile.mkdtemp()
        try:
            src_file = self._write(outside, "dropped.txt", "hello")
            calls = self._capture_copy()
            self.app._on_drop("left", -1, [src_file])
            self.assertEqual(len(calls), 1)
            targets, dest_dir = calls[0]
            self.assertEqual([str(t) for t in targets], [src_file])
            self.assertEqual(str(dest_dir), str(self.app.pane("left")["path"]))
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_drop_onto_directory_row_targets_that_dir(self):
        os.makedirs(os.path.join(self.src, "sub"))
        self.app._list_pane("left")
        self.app._settle_listings()
        pane = self.app.pane("left")
        idx = next(i for i, f in enumerate(pane["files"]) if f.name == "sub")
        calls = self._capture_copy()
        self.app._on_drop("left", idx, ["/elsewhere/f.txt"])
        self.assertEqual(len(calls), 1)
        _targets, dest_dir = calls[0]
        self.assertEqual(str(dest_dir), str(pane["files"][idx]))

    def test_drop_skips_source_already_in_dest(self):
        existing = self._write(self.src, "already.txt")
        calls = self._capture_copy()
        logs = []
        self.app.log_info = lambda m: logs.append(m)
        # Use the pane entry's (resolved) path so its parent matches dest_dir.
        self.app._list_pane("left")
        self.app._settle_listings()
        entry = next(f for f in self.app.pane("left")["files"] if f.name == "already.txt")
        self.app._on_drop("left", -1, [str(entry)])
        self.assertEqual(calls, [])
        self.assertTrue(any("already in this folder" in m for m in logs))

    def test_drop_back_onto_source_pane_cancels_silently(self):
        """A native drag released back onto its own source pane, over that pane's
        own directory, is a released-in-place gesture: cancel it silently rather
        than reporting a no-op copy — the files are already here (#230)."""
        self._write(self.src, "here.txt")
        self.app._list_pane("left")
        self.app._settle_listings()
        pane = self.app.pane("left")
        idx = next(i for i, f in enumerate(pane["files"]) if f.name == "here.txt")

        # Start a native drag from the left pane. Returning True keeps the session
        # "open" (no synchronous on_complete), so the source pane stays recorded.
        self.app.panel.begin_file_drag = lambda paths, **kw: True
        self.app._start_drag("left", idx, Event(type=EventType.MOUSE_DRAG, x=0, y=0))
        self.assertEqual(self.app._drag_source_pane, "left")

        calls = self._capture_copy()
        logs = []
        self.app.log_info = lambda m: logs.append(m)
        # Release back onto the same pane's own directory (index -1).
        self.app._on_drop("left", -1, [str(pane["files"][idx])])
        self.assertEqual(calls, [])
        self.assertFalse(any("already in this folder" in m for m in logs))
        # The session then ends (the OS still reports "copy") — no drag-out log,
        # and the cancel flag is cleared for the next drag.
        self.app._on_drag_complete([str(pane["files"][idx])], "copy")
        self.assertFalse(any("Dragged" in m for m in logs))
        self.assertFalse(self.app._drag_cancelled_in_place)
        self.assertIsNone(self.app._drag_source_pane)

    def test_drop_onto_subdir_of_source_pane_still_copies(self):
        """Dropping onto a *sub-directory row* of the source pane targets a real,
        different location, so it copies even though the release is over the same
        pane — only a released-in-place gesture cancels (#230)."""
        os.makedirs(os.path.join(self.src, "sub"))
        self._write(self.src, "f.txt")
        self.app._list_pane("left")
        self.app._settle_listings()
        pane = self.app.pane("left")
        sub_idx = next(i for i, f in enumerate(pane["files"]) if f.name == "sub")
        file_idx = next(i for i, f in enumerate(pane["files"]) if f.name == "f.txt")

        self.app.panel.begin_file_drag = lambda paths, **kw: True
        self.app._start_drag("left", file_idx, Event(type=EventType.MOUSE_DRAG, x=0, y=0))
        calls = self._capture_copy()
        self.app._on_drop("left", sub_idx, [str(pane["files"][file_idx])])
        self.assertEqual(len(calls), 1)
        _targets, dest_dir = calls[0]
        self.assertEqual(str(dest_dir), str(pane["files"][sub_idx]))

    def test_drag_complete_clears_source_pane(self):
        """Once the session ends, the recorded source pane is forgotten so a later
        external drop that lands where its files already sit is never mistaken for
        a released-in-place cancel (#230)."""
        self.app._drag_source_pane = "left"
        self.app._on_drag_complete(["/x/f.txt"], "none")
        self.assertIsNone(self.app._drag_source_pane)

    def test_drop_refused_on_virtual_pane(self):
        pane = self.app.pane("left")
        pane["virtual"] = {"mode": "filename", "query": "x"}
        calls = self._capture_copy()
        logs = []
        self.app.log_info = lambda m: logs.append(m)
        self.app._on_drop("left", -1, ["/x/f.txt"])
        self.assertEqual(calls, [])
        self.assertTrue(any("search-results" in m for m in logs))


if __name__ == "__main__":
    unittest.main()
