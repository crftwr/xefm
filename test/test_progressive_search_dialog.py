"""
ProgressiveSearchDialog — the live search-as-you-type file/content finder.

The dialog owns the background-search machinery: each query supersedes the
previous search, results stream in via a worker thread and are installed on a
per-frame tick, the result cap bounds the list, and an invalid content-search
regex surfaces as an error. With no panel attached, ``_ensure_ticking`` falls
back to settling synchronously (join the worker + drain), so the streaming logic
is exercised deterministically here without a backend. One end-to-end test drives
the real dialog through a MemoryBackend + XeFMApp to pin down the wiring
(``search_iter`` / ``to_label`` / ``on_accept`` / pane anchoring).
"""

import os
import re
import sys
import shutil
import tempfile
import threading
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit.event import Event, EventType  # noqa: E402
from puikit.panel import Rect  # noqa: E402

from xefm import app as xefm_app  # noqa: E402
from xefm import search_options as search_opts  # noqa: E402
from xefm.options import OptionSet  # noqa: E402
from xefm.options_dialog import OptionsDialog  # noqa: E402
from xefm.progressive_search_dialog import ProgressiveSearchDialog  # noqa: E402
from xefm.search_options import SEARCH_OPTIONS  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


def _run(dialog, query):
    """Type ``query`` and settle the resulting search synchronously (no panel ->
    the tick falls back to join-and-drain)."""
    dialog.query_edit.text = query
    dialog._start_search()


class Streaming(unittest.TestCase):
    def test_matches_stream_in(self):
        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter(range(5)),
            to_label=lambda mode, v: str(v),
        )
        _run(dlg, "x")
        self.assertEqual(dlg.results, [0, 1, 2, 3, 4])
        self.assertFalse(dlg._searching)

    def test_empty_query_clears_and_runs_nothing(self):
        called = []

        def it(mode, q, cancel):
            called.append(q)
            return iter([1])

        dlg = ProgressiveSearchDialog(search_iter=it, to_label=lambda m, v: str(v))
        _run(dlg, "a")
        self.assertEqual(dlg.results, [1])
        _run(dlg, "   ")  # whitespace-only -> no search
        self.assertEqual(dlg.results, [])
        self.assertEqual(called, ["a"])  # the blank query never reached search_iter

    def test_result_cap_bounds_the_list(self):
        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter(range(10_000)),
            to_label=lambda mode, v: str(v),
            result_cap=25,
        )
        _run(dlg, "x")
        self.assertEqual(len(dlg.results), 25)

    def test_cap_signals_cancel_to_stop_the_walk(self):
        # The worker sets the cancel event once the cap is hit, so an unbounded
        # generator that honors it stops instead of running forever.
        seen = []

        def it(mode, q, cancel):
            i = 0
            while not cancel.is_set():
                seen.append(i)
                yield i
                i += 1

        dlg = ProgressiveSearchDialog(
            search_iter=it, to_label=lambda m, v: str(v), result_cap=10)
        _run(dlg, "x")
        self.assertEqual(len(dlg.results), 10)
        # The generator was stopped shortly after the cap, not left spinning.
        self.assertLess(len(seen), 1000)


class Supersede(unittest.TestCase):
    def test_new_query_replaces_previous_results(self):
        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter([q + "!"]),
            to_label=lambda mode, v: v,
        )
        _run(dlg, "one")
        self.assertEqual(dlg.results, ["one!"])
        _run(dlg, "two")
        self.assertEqual(dlg.results, ["two!"])

    def test_stale_batches_are_dropped(self):
        # A late batch tagged with an old generation must not land in the new
        # search's results.
        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter([1]),
            to_label=lambda mode, v: str(v),
        )
        _run(dlg, "a")
        stale_gen = dlg._gen - 5
        dlg._queue.put((stale_gen, [999], False, None))
        dlg._drain()
        self.assertNotIn(999, dlg.results)


class ContentErrors(unittest.TestCase):
    def test_invalid_regex_surfaces_as_error(self):
        def it(mode, q, cancel):
            re.compile(q)  # raises re.error for a bad pattern
            yield from ()

        dlg = ProgressiveSearchDialog(search_iter=it, to_label=lambda m, v: str(v))
        _run(dlg, "(unclosed")
        self.assertIsNotNone(dlg._error)
        self.assertIn("Invalid pattern", dlg._error)
        self.assertEqual(dlg.results, [])


class ModeSwitch(unittest.TestCase):
    def test_tab_switches_mode_and_reruns(self):
        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter([f"{mode}:{q}"]),
            to_label=lambda mode, v: v,
            initial_mode="filename",
        )
        _run(dlg, "q")
        self.assertEqual(dlg.results, ["filename:q"])
        dlg._switch_mode()  # Tab
        self.assertEqual(dlg.mode, "content")
        self.assertEqual(dlg.results, ["content:q"])


class Options(unittest.TestCase):
    """The dialog's half of the options contract (#312): it shows them, opens the
    box, and re-runs when one changes — and reads no value itself."""

    def _dialog(self, **kw):
        return ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter([f"{mode}:{q}"]),
            to_label=lambda mode, v: v,
            options=OptionSet(SEARCH_OPTIONS),
            **kw,
        )

    def test_chips_follow_the_mode(self):
        dlg = self._dialog(initial_mode="content")
        self.assertEqual([o.flag for o, _on in dlg.options.chips(dlg.mode)],
                         ["Aa", "Word", ".*", "Sub"])
        dlg._switch_mode()  # filename search speaks glob, not regex
        self.assertEqual([o.flag for o, _on in dlg.options.chips(dlg.mode)],
                         ["Aa", "Sub"])

    def test_a_chip_says_on_or_off_by_its_state_not_its_text(self):
        # The fill carries the state, so the name stays put — no chip has to
        # grow a space inside it to say it is off.
        dlg = self._dialog()
        option, on = dlg.options.chips(dlg.mode)[0]
        self.assertEqual((option.flag, on), ("Aa", False))
        dlg.options.toggle(search_opts.CASE)
        option, on = dlg.options.chips(dlg.mode)[0]
        self.assertEqual((option.flag, on), ("Aa", True))

    def test_changing_an_option_reruns_the_search(self):
        runs = []

        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter([runs.append(q) or q]),
            to_label=lambda mode, v: v,
            options=OptionSet(SEARCH_OPTIONS),
        )
        _run(dlg, "needle")
        self.assertEqual(runs, ["needle"])
        dlg.options.toggle(search_opts.CASE)
        self.assertEqual(runs, ["needle", "needle"])  # same query, run again

    def test_a_closed_dialog_stops_answering_its_options(self):
        # The set outlives the dialog (the app keeps it for the session), so a
        # later change must not start a worker for a box that is gone.
        runs = []
        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter([runs.append(q) or q]),
            to_label=lambda mode, v: v,
            options=OptionSet(SEARCH_OPTIONS),
        )
        _run(dlg, "needle")
        dlg._close()
        dlg.options.toggle(search_opts.CASE)
        self.assertEqual(runs, ["needle"])

    def test_a_click_on_a_chip_toggles_it(self):
        # A chip is a switch, so it answers to the mouse like one.
        dlg = self._dialog(initial_mode="content")
        dlg._size = (60.0, 20.0)
        dlg._chip_hits = [(search_opts.CASE, Rect(40.0, 3.0, 4.0, 1.0))]
        dlg.handle_event(Event(EventType.MOUSE_CLICK, x=41.0, y=3.0))
        self.assertIs(dlg.options[search_opts.CASE], True)
        dlg.handle_event(Event(EventType.MOUSE_CLICK, x=41.0, y=3.0))
        self.assertIs(dlg.options[search_opts.CASE], False)

    def test_the_padding_inside_a_chip_is_part_of_its_target(self):
        # What looks like the button is the button: the block is drawn with a
        # space either side of the name, and both are live.
        dlg = self._dialog(initial_mode="content")
        dlg._size = (60.0, 20.0)
        dlg._chip_hits = [(search_opts.CASE, Rect(40.0, 3.0, 4.0, 1.0))]
        dlg.handle_event(Event(EventType.MOUSE_CLICK, x=40.0, y=3.0))
        self.assertIs(dlg.options[search_opts.CASE], True)

    def test_a_click_between_chips_toggles_nothing(self):
        dlg = self._dialog(initial_mode="content")
        dlg._size = (60.0, 20.0)
        dlg._chip_hits = [(search_opts.CASE, Rect(40.0, 3.0, 4.0, 1.0))]
        dlg.handle_event(Event(EventType.MOUSE_CLICK, x=45.0, y=3.0))
        self.assertIs(dlg.options[search_opts.CASE], False)

    def test_a_press_is_not_a_click(self):
        # Press and drag belong to the field and the list; only a completed
        # click flips a switch, as everywhere else in XeFM.
        dlg = self._dialog(initial_mode="content")
        dlg._size = (60.0, 20.0)
        dlg._chip_hits = [(search_opts.CASE, Rect(40.0, 3.0, 4.0, 1.0))]
        dlg.handle_event(Event(EventType.MOUSE_DOWN, x=41.0, y=3.0))
        self.assertIs(dlg.options[search_opts.CASE], False)

    def test_the_hint_band_names_the_options_key_before_esc(self):
        dlg = self._dialog(initial_mode="filename")
        self.assertEqual(
            dlg.hint(),
            "↑/↓ select · Enter choose · Tab content · Ctrl-O options · Esc cancel")

    def test_a_narrow_band_drops_whole_entries(self):
        # A truncated entry spends the width and says nothing, and it is always
        # the rightmost that loses — never the one that deserves to.
        dlg = self._dialog(initial_mode="filename")
        measure = len
        full = dlg.hint()
        self.assertEqual(dlg.hint(len(full), measure), full)
        # Too narrow for the arrows: they go first, the rest survives intact.
        tight = dlg.hint(len(full) - 1, measure)
        self.assertEqual(tight,
                         "Enter choose · Tab content · Ctrl-O options · Esc cancel")
        # Narrower still: Esc goes, and what a user cannot guess is what is left.
        tighter = dlg.hint(len(tight) - 1, measure)
        self.assertEqual(tighter, "Enter choose · Tab content · Ctrl-O options")

    def test_the_options_key_outlives_every_drop(self):
        dlg = self._dialog(initial_mode="filename")
        self.assertIn("Ctrl-O options", dlg.hint(1.0, len))

    def test_a_dialog_without_options_names_no_key(self):
        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter(()),
            to_label=lambda mode, v: str(v))
        self.assertNotIn("options", dlg.hint())

    def test_the_key_label_follows_a_rebind(self):
        from xefm.config import KeyBindings, config_manager

        dlg = self._dialog()
        saved = config_manager._key_bindings
        config_manager._key_bindings = KeyBindings({"search.options": ["Ctrl-P"]})
        try:
            self.assertEqual(dlg._options_key_label(), "Ctrl-P")
        finally:
            config_manager._key_bindings = saved

    def test_an_unbound_options_key_is_not_named(self):
        from xefm.config import KeyBindings, config_manager

        dlg = self._dialog()
        saved = config_manager._key_bindings
        config_manager._key_bindings = KeyBindings({"search.options": []})
        try:
            self.assertEqual(dlg._options_key_label(), "")
        finally:
            config_manager._key_bindings = saved

    def test_the_options_key_is_resolved_by_action(self):
        # Ctrl-O reaches the dialog identically on all four backends: the TUI
        # paths deliver key="o" with no char, so this must not be a char match.
        dlg = self._dialog()
        opened = []
        dlg._open_options = lambda: opened.append(True)
        handled = dlg._handle_option_key(
            Event(EventType.KEY, key="o", modifiers=frozenset({"ctrl"})))
        self.assertTrue(handled)
        self.assertEqual(opened, [True])

    def test_a_plain_letter_is_still_typing(self):
        dlg = self._dialog()
        self.assertFalse(dlg._handle_option_key(
            Event(EventType.KEY, key="o", char="o", modifiers=frozenset())))

    def test_an_option_chord_is_unbound_until_a_config_asks(self):
        dlg = self._dialog()
        self.assertFalse(dlg._handle_option_key(
            Event(EventType.KEY, key="t", modifiers=frozenset({"ctrl"}))))
        self.assertIs(dlg.options[search_opts.CASE], False)

    def test_a_bound_option_chord_toggles_that_option(self):
        from xefm.config import KeyBindings, config_manager

        dlg = self._dialog()
        saved = config_manager._key_bindings
        config_manager._key_bindings = KeyBindings(
            {"search.toggle_case": ["Ctrl-T"]})
        try:
            handled = dlg._handle_option_key(
                Event(EventType.KEY, key="t", modifiers=frozenset({"ctrl"})))
        finally:
            config_manager._key_bindings = saved
        self.assertTrue(handled)
        self.assertIs(dlg.options[search_opts.CASE], True)


class AppIntegration(unittest.TestCase):
    """Drive the real dialog through a MemoryBackend + XeFMApp, so the wiring
    (search_iter/to_label/on_accept + the tick-driven drain) is covered too."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        # Temp state DB, never the real ~/.xefm/state.db: the app restores each
        # pane's sort mode, sort direction and filter from it, so the developer's
        # own last-used settings would otherwise decide these panes' row order.
        self.sm = XeFMStateManager(
            db_path=os.path.join(self.state_dir, "state.db"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _write(self, rel, content=""):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        return p

    def test_filename_search_streams_via_ticks(self):
        from puikit.backends import create_backend

        self._write("sub/needle_here.txt")
        self._write("sub/other.txt")
        self._write("noise.log")

        b = create_backend("memory")
        b.open()
        app = xefm_app.XeFMApp(b, self.tmp, self.tmp, left_provided=True,
                               right_provided=True, state_manager=self.sm)
        try:
            app._settle_listings()
            app._open_search("filename")
            dlg = app.panel._layers[-1].widget
            self.assertIsInstance(dlg, ProgressiveSearchDialog)

            # Exact-glob matching (issue #231): a wildcard is used explicitly for
            # a partial match — a bare "needle" would match nothing here.
            dlg.query_edit.text = "needle*"
            dlg._start_search()
            dlg._thread.join(timeout=5)
            b.run_animation_ticks()  # drain the queue on the tick

            names = [os.path.basename(dlg.to_label("filename", v)) for v in dlg.results]
            self.assertIn("needle_here.txt", names)
            self.assertNotIn("other.txt", names)
        finally:
            app.file_monitor.stop_monitoring()
            b.close()

    def test_filename_search_is_exact_match(self):
        # Issue #231: the query is matched against the whole filename, not as a
        # substring. A bare "report" matches only a file named exactly "report";
        # wildcards opt into partial matches.
        from puikit.backends import create_backend

        self._write("dir/report")
        self._write("dir/report.txt")
        self._write("dir/annual_report")

        b = create_backend("memory")
        b.open()
        app = xefm_app.XeFMApp(b, self.tmp, self.tmp, left_provided=True,
                               right_provided=True, state_manager=self.sm)
        try:
            app._settle_listings()
            app._open_search("filename")
            dlg = app.panel._layers[-1].widget

            def search(query):
                dlg.query_edit.text = query
                dlg._start_search()
                dlg._thread.join(timeout=5)
                b.run_animation_ticks()
                return {os.path.basename(dlg.to_label("filename", v)) for v in dlg.results}

            # Exact: only the file named exactly "report".
            self.assertEqual(search("report"), {"report"})
            # Prefix glob picks up the others.
            self.assertEqual(search("report*"), {"report", "report.txt"})
            # Substring still available via an explicit surrounding wildcard.
            self.assertEqual(search("*report*"),
                             {"report", "report.txt", "annual_report"})
        finally:
            app.file_monitor.stop_monitoring()
            b.close()

    def test_content_search_honors_pane_filter(self):
        # Issue #305: an active pane filter narrows content search to the files
        # it matches (directories are still descended), and the dialog title
        # names the pattern so the narrowing is visible.
        from puikit.backends import create_backend

        self._write("a.txt", "needle\n")
        self._write("b.nim", "needle\n")
        self._write("sub/c.txt", "needle\n")

        b = create_backend("memory")
        b.open()
        app = xefm_app.XeFMApp(b, self.tmp, self.tmp, left_provided=True,
                               right_provided=True, state_manager=self.sm)
        try:
            app._settle_listings()
            app.active_pane()["filter_pattern"] = "*.txt"
            app._open_search("content")
            dlg = app.panel._layers[-1].widget
            self.assertEqual(dlg._titles["content"], "Search Content (*.txt)")

            dlg.query_edit.text = "needle"
            dlg._start_search()
            dlg._thread.join(timeout=5)
            b.run_animation_ticks()

            names = sorted(v["path"].name for v in dlg.results)
            self.assertEqual(names, ["a.txt", "c.txt"])
        finally:
            app.file_monitor.stop_monitoring()
            b.close()

    def test_accept_lands_pane_cursor_on_picked_hit(self):
        # Issue #224: accepting a row feeds the whole result set into the pane,
        # and the cursor must land on the row that was picked.
        from puikit.backends import create_backend

        for i in range(5):
            self._write(f"sub{i}/needle{i}.txt")

        b = create_backend("memory")
        b.open()
        app = xefm_app.XeFMApp(b, self.tmp, self.tmp, left_provided=True,
                               right_provided=True, state_manager=self.sm)
        try:
            app._settle_listings()
            app._open_search("filename")
            dlg = app.panel._layers[-1].widget

            dlg.query_edit.text = "needle*"
            dlg._start_search()
            dlg._thread.join(timeout=5)
            b.run_animation_ticks()
            self.assertEqual(len(dlg.results), 5)

            # Accept the *last* streamed hit. The fed listing preserves the
            # stream order here (the files are empty, so they tie under the pane's
            # size sort), so the last result lands on the last row — a cursor left
            # at the top would be a visible failure. Assert against the row where
            # the picked hit actually landed, so the test is robust to sort order.
            picked = dlg.results[-1]
            dlg._accept_index(len(dlg.results) - 1)

            pane = app.active_pane()
            self.assertIsNotNone(pane["virtual"])
            self.assertEqual(len(pane["files"]), 5)  # whole set fed
            landed = pane["focused_index"]
            self.assertGreater(landed, 0)  # cursor moved off the top row
            self.assertEqual(str(pane["files"][landed]), str(picked))
        finally:
            app.file_monitor.stop_monitoring()
            b.close()


    def _search_app(self, backend):
        app = xefm_app.XeFMApp(backend, self.tmp, self.tmp, left_provided=True,
                               right_provided=True, state_manager=self.sm)
        app._settle_listings()
        return app

    def test_options_key_opens_the_box_over_the_search(self):
        from puikit.backends import create_backend

        self._write("a.txt")
        b = create_backend("memory")
        b.open()
        app = self._search_app(b)
        try:
            app._open_search("content")
            dlg = app.panel._layers[-1].widget
            dlg.handle_event(Event(EventType.KEY, key="o",
                                   modifiers=frozenset({"ctrl"})))
            box = app.panel._layers[-1].widget
            self.assertIsInstance(box, OptionsDialog)

            # A plain letter is an accelerator in here — the whole reason the
            # options live behind one key rather than one chord each.
            box.handle_event(Event(EventType.KEY, key="s", char="s"))
            self.assertIs(dlg.options[search_opts.SUBDIRS], False)

            box.handle_event(Event(EventType.KEY, key="escape"))
            self.assertIs(app.panel._layers[-1].widget, dlg)  # search still up
        finally:
            app.file_monitor.stop_monitoring()
            b.close()

    def test_turning_off_subfolders_narrows_the_search(self):
        from puikit.backends import create_backend

        self._write("top.txt", "needle\n")
        self._write("sub/deep.txt", "needle\n")
        b = create_backend("memory")
        b.open()
        app = self._search_app(b)
        try:
            app._open_search("content")
            dlg = app.panel._layers[-1].widget

            def settle():
                if dlg._thread is not None:
                    dlg._thread.join(timeout=5)
                b.run_animation_ticks()
                return sorted(h["path"].name for h in dlg.results)

            dlg.query_edit.text = "needle"
            dlg._start_search()
            self.assertEqual(settle(), ["deep.txt", "top.txt"])

            # Changing the option re-runs the same query on its own.
            dlg.options.toggle(search_opts.SUBDIRS)
            self.assertEqual(settle(), ["top.txt"])
        finally:
            app.file_monitor.stop_monitoring()
            b.close()

    def test_the_drawn_chips_are_where_the_clicks_land(self):
        from puikit.backends import create_backend

        self._write("top.txt", "needle\n")
        self._write("sub/deep.txt", "needle\n")
        b = create_backend("memory")
        b.open()
        app = self._search_app(b)
        try:
            app._open_search("content")
            dlg = app.panel._layers[-1].widget
            dlg.query_edit.text = "needle"
            dlg._start_search()

            def settle():
                if dlg._thread is not None:
                    dlg._thread.join(timeout=5)
                b.run_animation_ticks()
                app.panel.render()
                return sorted(h["path"].name for h in dlg.results)

            self.assertEqual(settle(), ["deep.txt", "top.txt"])

            # The rects come from the frame that was just drawn, so this clicks
            # the block a user would be looking at.
            hits = dict(dlg._chip_hits)
            self.assertEqual(sorted(hits), sorted(
                o.name for o in dlg.options.visible("content")))
            rect = hits[search_opts.SUBDIRS]
            dlg.handle_event(Event(EventType.MOUSE_CLICK,
                                   x=rect.x + rect.w / 2, y=rect.y))

            self.assertIs(dlg.options[search_opts.SUBDIRS], False)
            self.assertEqual(settle(), ["top.txt"])   # the click re-ran it
            self.assertIs(app.panel._layers[-1].widget, dlg)  # and stayed open
        finally:
            app.file_monitor.stop_monitoring()
            b.close()

    def test_a_narrowed_scope_does_not_outlive_the_dialog(self):
        from puikit.backends import create_backend

        self._write("a.txt")
        b = create_backend("memory")
        b.open()
        app = self._search_app(b)
        try:
            app._open_search("filename")
            dlg = app.panel._layers[-1].widget
            dlg.options.toggle(search_opts.SUBDIRS)   # scope: transient
            dlg.options.toggle(search_opts.CASE)      # reading: persists
            dlg._cancel_dialog()

            app._open_search("filename")
            reopened = app.panel._layers[-1].widget
            self.assertIs(reopened.options[search_opts.SUBDIRS], True)
            self.assertIs(reopened.options[search_opts.CASE], True)
        finally:
            app.file_monitor.stop_monitoring()
            b.close()


if __name__ == "__main__":
    unittest.main()
