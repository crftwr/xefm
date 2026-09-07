"""A modal's two chrome bands, and when the window's status bar shuts up.

Two things the screenshots for #271 turned up.

**The hint bar.** Modals disagreed about where their keys go: SortDialog and
TipsDialog put them below the content, TextDialog (Help, File Details) carried
them in the *header*, between the title and the body the title describes — and
the filter picker's floated loose in the client area with nothing separating it
from the list. They now share ``dialog_geometry.draw_hint_row``, built as the
mirror of ``draw_title_bar``: a frame-connecting rule, then the muted line of
keys hard against the bottom border. A modal is framed by two matched bands with
its content between them, on the grid and on a vector backend alike.

Every modal that owns the keyboard draws it now, not just the two that started
it: the search dialog, the input prompts, batch rename, sort, the choice picker,
Compare & Select, and Tip of the Day. The band is where *keys* go — the search
dialog's result count and batch rename's macro legend stay in the client area,
each with the thing it describes, and each gave up the ``Tab …`` fragment it used
to carry.

**The status bar.** A modal owns the keyboard while it is up and names its own
keys, so the window's bar listing the file list's keys was advertising keys that
could not fire. It goes quiet — except under the search bar, which is a layer
too but hands the bar its keys to show.

Run with: python -m pytest test/test_dialog_hint_row.py -v
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit import CapabilityProfile, Panel, PROFILE_GUI_DESKTOP  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402

from xefm import dialog_geometry as dg  # noqa: E402
from xefm.batch_rename_dialog import show_batch_rename  # noqa: E402
from xefm.choice_dialog import show_choice_dialog  # noqa: E402
from xefm.compare_dialog import show_compare_select  # noqa: E402
from xefm.filter_list_dialog import show_filter_list  # noqa: E402
from xefm.input_dialog import show_input  # noqa: E402
from xefm.progressive_search_dialog import show_progressive_search  # noqa: E402
from xefm.sort_dialog import show_sort_dialog  # noqa: E402
from xefm.text_dialog import show_text  # noqa: E402
from xefm.tips_dialog import show_tips_dialog  # noqa: E402


class _Ctx:
    """The DrawContext fields the band metrics read."""

    theme = None

    def __init__(self, hu, *, vector=False, line_h=1.0):
        self.size_units = (60.0, hu)
        self.vector_shapes = vector
        self._line_h = line_h

    def line_height(self, _style):
        return self._line_h


def _settle(backend, panel):
    for _ in range(40):
        backend.run_animation_ticks()
    panel.render()


def _rows(backend):
    return [("".join(row)).rstrip() for row in backend.snapshot()]


class _Vector(MemoryBackend):
    @property
    def capabilities(self):
        return CapabilityProfile({**self._capabilities, "vector_shapes": True})


# --------------------------------------------------------------------------- #
# The band metrics mirror the title bar's
# --------------------------------------------------------------------------- #

class BandMetrics(unittest.TestCase):

    def test_a_grid_leaves_the_rule_and_the_hint_row(self):
        """Bottom border, hint row, rule — the top's border/title/rule upside
        down, so the content stops on the rule row."""
        self.assertEqual(dg.hint_content_bottom(_Ctx(20.0), None), 17.0)

    def test_the_two_bands_are_the_same_height_on_a_vector_backend(self):
        ctx = _Ctx(20.0, vector=True, line_h=1.4)
        style = dg.hint_style(ctx, None)
        self.assertEqual(dg.gui_hint_bar_height(ctx, style),
                         dg.gui_title_bar_height(ctx, style))

    def test_the_content_clears_each_rule_by_the_same_gap(self):
        """``draw_title_bar`` drops the content ``_GUI_CONTENT_GAP`` below its
        rule; the bottom band lifts it the same amount above its own."""
        ctx = _Ctx(20.0, vector=True, line_h=1.4)
        style = dg.hint_style(ctx, None)
        rule_y = ctx.size_units[1] - dg.gui_hint_bar_height(ctx, style)
        self.assertAlmostEqual(rule_y - dg.hint_content_bottom(ctx, None),
                               dg._GUI_CONTENT_GAP)

    def test_the_bottom_band_is_pinned_to_the_frame(self):
        """Not floating in the client area: the band runs from its rule to the
        bottom edge of the box, whatever the box height."""
        for hu in (12.0, 20.0, 31.5):
            ctx = _Ctx(hu, vector=True, line_h=1.4)
            style = dg.hint_style(ctx, None)
            bar_h = dg.gui_hint_bar_height(ctx, style)
            with self.subTest(hu=hu):
                self.assertAlmostEqual(hu - dg.hint_content_bottom(ctx, None),
                                       bar_h + dg._GUI_CONTENT_GAP)


# --------------------------------------------------------------------------- #
# Both dialogs draw the band, and draw it the same way
# --------------------------------------------------------------------------- #

class BandPlacement(unittest.TestCase):

    def setUp(self):
        self.b = MemoryBackend(width=80, height=24)
        self.b.open()
        self.panel = Panel(self.b)

    def tearDown(self):
        self.b.close()

    def _bands(self, hint_head):
        """``(rule_above, hint, border_below)`` rows for the open dialog. Matched
        on the head of the hint line: a narrow box elides its tail."""
        rows = _rows(self.b)
        hint = next(i for i, r in enumerate(rows) if hint_head in r)
        return rows[hint - 1], rows[hint], rows[hint + 1]

    def test_the_filter_picker_hint_is_a_band_against_the_frame(self):
        show_filter_list(self.panel, ["*.py", "*.txt"], title="Filter",
                         to_label=lambda v: v, on_remove=lambda v: True)
        _settle(self.b, self.panel)
        above, _hint, below = self._bands("↑/↓ select")

        self.assertIn("├", above, "a frame-connecting rule separates it")
        self.assertIn("└", below, "and it sits hard against the bottom border")

    def test_the_scroll_modal_hint_moved_below_the_body(self):
        """This is the one that moved: the hint used to sit between the title bar
        and the first body line."""
        show_text(self.panel, [f"line {n}" for n in range(1, 9)], title="Help")
        _settle(self.b, self.panel)
        rows = _rows(self.b)

        title = next(i for i, r in enumerate(rows) if "Help" in r)
        first_line = next(i for i, r in enumerate(rows) if "line 1" in r)
        hint = next(i for i, r in enumerate(rows) if "↑/↓ scroll" in r)
        self.assertLess(title, first_line)
        self.assertLess(first_line, hint, "the keys come after the body, not before")

        above, _hint, below = self._bands("↑/↓ scroll")
        self.assertIn("├", above)
        self.assertIn("└", below)

    def test_the_bottom_rule_mirrors_the_title_rule(self):
        """Each band holds exactly one text row between its rule and the frame,
        so the box reads as symmetric top and bottom."""
        show_text(self.panel, [f"line {n}" for n in range(1, 9)], title="Help")
        _settle(self.b, self.panel)
        rows = _rows(self.b)

        top_border = next(i for i, r in enumerate(rows) if "┌" in r)
        top_rule = next(i for i, r in enumerate(rows) if "├" in r)
        bottom_rule = max(i for i, r in enumerate(rows) if "├" in r)
        bottom_border = next(i for i, r in enumerate(rows) if "└" in r)

        self.assertGreater(bottom_rule, top_rule, "two rules, not one")
        self.assertEqual(top_rule - top_border, 2)        # border, title, rule
        self.assertEqual(bottom_border - bottom_rule, 2)  # rule, hint, border

    def test_a_vector_modal_keeps_the_grid_glyphs_off_its_rules(self):
        """The divider primitive owns the visible-vs-grid choice: a vector
        backend strokes a thin rect, and no tee glyph leaks onto it."""
        b = _Vector(width=90, height=28, capabilities=PROFILE_GUI_DESKTOP)
        b.open()
        panel = Panel(b)
        try:
            show_filter_list(panel, ["*.py"], title="Filter",
                             to_label=lambda v: v, on_remove=lambda v: True)
            _settle(b, panel)
            text = "\n".join("".join(r) for r in b.snapshot())
            self.assertIn("↑/↓ select", text, "the band is drawn")
            self.assertNotIn("├", text)
            self.assertNotIn("┤", text)
        finally:
            b.close()


# --------------------------------------------------------------------------- #
# Every modal that owns the keyboard names its keys down there
# --------------------------------------------------------------------------- #

class EveryModalDrawsTheBand(unittest.TestCase):
    """One test per modal, each asserting the same three things: the keys are on
    screen, a frame-connecting rule sits directly above them, and the bottom
    border directly below. That is what makes it a band rather than a line that
    happens to be near the bottom."""

    def setUp(self):
        self.b = MemoryBackend(width=88, height=26)
        self.b.open()
        self.panel = Panel(self.b)

    def tearDown(self):
        self.b.close()

    def _assert_banded(self, head):
        rows = _rows(self.b)
        hint = next((i for i, r in enumerate(rows) if head in r), None)
        self.assertIsNotNone(hint, f"{head!r} is not on screen:\n" + "\n".join(rows))
        self.assertIn("├", rows[hint - 1], "a frame-connecting rule separates it")
        self.assertIn("└", rows[hint + 1], "and it sits hard against the bottom border")

    def test_the_search_dialog(self):
        show_progressive_search(
            self.panel, search_iter=lambda m, q, c: iter(()),
            to_label=lambda m, v: str(v))
        _settle(self.b, self.panel)
        self._assert_banded("↑/↓ select")

    def test_the_search_dialog_names_the_mode_tab_switches_to(self):
        """The one moving part of that line, and the fragment the status line
        above the results used to carry."""
        dlg = show_progressive_search(
            self.panel, search_iter=lambda m, q, c: iter(()),
            to_label=lambda m, v: str(v))
        self.assertIn("Tab content", dlg.hint())
        self.assertNotIn("Tab", dlg._status_text(), "the status line is about the search")
        dlg._switch_mode()
        self.assertIn("Tab filename", dlg.hint())

    def test_the_owner_says_what_enter_does(self):
        """The widget knows Enter is Enter; only its owner knows what accepting
        performs. XeFM's search feeds the whole result set into the pane, so the
        band must not promise the one highlighted file."""
        dlg = show_progressive_search(
            self.panel, search_iter=lambda m, q, c: iter(()),
            to_label=lambda m, v: str(v), accept_hint="results to pane")
        self.assertIn("Enter results to pane", dlg.hint())
        self.assertNotIn("open", dlg.hint())

    def test_an_input_prompt(self):
        show_input(self.panel, title="New Directory", prompt="Name:")
        _settle(self.b, self.panel)
        self._assert_banded("Enter accept")

    def test_a_prompt_offers_tab_only_where_it_completes(self):
        """Jump to Path completes; New Directory does not, and must not name a
        key that would do nothing."""
        from xefm.completion import FilepathCompleter
        plain = show_input(self.panel, title="New Directory", prompt="Name:")
        self.assertNotIn("Tab", plain.hint())
        plain._cancel()
        jump = show_input(self.panel, title="Jump to Path", prompt="Path:",
                          completer=FilepathCompleter())
        self.assertIn("Tab complete", jump.hint())

    def test_the_batch_rename_dialog(self):
        show_batch_rename(self.panel, [Path("/tmp/a.txt"), Path("/tmp/b.txt")])
        _settle(self.b, self.panel)
        self._assert_banded("Tab switch field")

    def test_batch_rename_keeps_its_macro_legend_with_the_field(self):
        """A syntax legend for the replace pattern, not a key list: it stays in
        the client area, and the keys it used to trail moved to the band."""
        show_batch_rename(self.panel, [Path("/tmp/a.txt")])
        _settle(self.b, self.panel)
        rows = _rows(self.b)
        legend = next(i for i, r in enumerate(rows) if r"\d index" in r)
        hint = next(i for i, r in enumerate(rows) if "Tab switch field" in r)
        self.assertLess(legend, hint)
        self.assertNotIn("Esc cancel", rows[legend], "the keys left the legend")

    def test_the_sort_dialog(self):
        show_sort_dialog(self.panel)
        _settle(self.b, self.panel)
        self._assert_banded("↑/↓ key")

    def test_the_choice_picker(self):
        show_choice_dialog(self.panel, "Encoding",
                           [("utf8", "UTF-8"), ("sjis", "Shift_JIS")])
        _settle(self.b, self.panel)
        self._assert_banded("↑/↓ or type to choose")

    def test_the_choice_picker_shows_its_type_ahead_buffer_in_the_band(self):
        """While a jump is being typed, what the dialog answers to *is* the
        buffer — so the band shows that instead of the keys."""
        dlg = show_choice_dialog(self.panel, "Encoding",
                                 [("utf8", "UTF-8"), ("sjis", "Shift_JIS")])
        dlg._typeahead("s")
        _settle(self.b, self.panel)
        self._assert_banded("Jump to: s")

    def test_the_compare_dialog(self):
        show_compare_select(self.panel, on_result=lambda r: None)
        _settle(self.b, self.panel)
        self._assert_banded("Space on/off")

    def test_the_tips_dialog_puts_its_counter_at_the_bands_right_end(self):
        show_tips_dialog(self.panel, index=2)
        _settle(self.b, self.panel)
        self._assert_banded("←/→ tip")
        rows = _rows(self.b)
        hint = next(i for i, r in enumerate(rows) if "←/→ tip" in r)
        self.assertRegex(rows[hint], r"3/\d+\s*│$",
                         "the counter is pinned to the right end of the same band")


# --------------------------------------------------------------------------- #
# The band's optional right-hand reading
# --------------------------------------------------------------------------- #

class TheRightHandReading(unittest.TestCase):
    """``right`` is for the one thing a modal says down there that is not a key.
    It keeps its whole width; the keys elide against it."""

    def setUp(self):
        self.b = MemoryBackend(width=40, height=10)
        self.b.open()
        self.panel = Panel(self.b)

    def tearDown(self):
        self.b.close()

    #: Longer than the 24-unit box it is drawn into, so something has to give.
    _KEYS = "a · b · c · d · e · f · g · h · i · j"

    def _band(self, **kw):
        """The hint row alone in a narrow box; returns the row it drew."""
        from puikit.widgets.base import Widget

        keys = self._KEYS

        class _Box(Widget):
            def draw(_self, ctx):
                dg.draw_hint_row(ctx, keys, surface_bg=None, border=None, **kw)

        self.panel.push_layer(_Box(), z=10, hints={"w": 24.0, "h": 6.0})
        self.panel.render()
        row = next(r for r in _rows(self.b) if "a · b" in r)
        self.panel.pop_layer()
        return row

    def test_the_right_reading_survives_a_box_too_narrow_for_the_keys(self):
        plain = self._band()
        counted = self._band(right="12/47")

        self.assertIn("12/47", counted, "the counter is never the part that elides")
        self.assertIn("…", counted, "the keys give way to it instead")
        self.assertLess(len(counted.split("12/47")[0].strip()), len(plain.strip()),
                        "and give way by exactly as much as it takes")


# --------------------------------------------------------------------------- #
# The window's status bar defers to whatever is on top
# --------------------------------------------------------------------------- #

class StatusBarGoesQuiet(unittest.TestCase):
    """``StatusBar._text`` reads two things off the app, so it is exercised
    against a stand-in rather than a live window."""

    class FakeApp:
        def __init__(self, isearch=False, layers=False):
            self._isearch_active = isearch
            self.panel = type("P", (), {"has_layers": layers})()

    def _bar(self, **kw):
        from xefm.app import StatusBar
        bar = StatusBar(self.FakeApp(**kw))
        bar._hints_cache = "Q quit  Tab switch"
        bar._isearch_cache = "I-Search  Enter stop"
        return bar

    def test_the_file_list_keys_show_when_nothing_is_over_them(self):
        self.assertEqual(self._bar()._text(), "Q quit  Tab switch")

    def test_a_modal_silences_the_bar(self):
        """The dialog names its own keys; the file list's cannot fire."""
        self.assertEqual(self._bar(layers=True)._text(), "")

    def test_the_search_bar_still_gets_to_speak(self):
        """It is a layer too, but it hands the bar its keys to show — the whole
        point of a footer overlay."""
        self.assertEqual(self._bar(isearch=True, layers=True)._text(),
                         "I-Search  Enter stop")


if __name__ == "__main__":
    unittest.main()
