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

**The status bar.** A modal owns the keyboard while it is up and names its own
keys, so the window's bar listing the file list's keys was advertising keys that
could not fire. It goes quiet — except under the search bar, which is a layer
too but hands the bar its keys to show.

Run with: python -m pytest test/test_dialog_hint_row.py -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit import CapabilityProfile, Panel, PROFILE_GUI_DESKTOP  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402

from xefm import dialog_geometry as dg  # noqa: E402
from xefm.filter_list_dialog import show_filter_list  # noqa: E402
from xefm.text_dialog import show_text  # noqa: E402


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
