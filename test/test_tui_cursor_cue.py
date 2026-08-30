"""The TUI cursor cue: an underlined row, or two brackets, never both.

On a character grid the cursor used to be a bold ``[`` … ``]`` pair in the gutter
columns — two characters at the far ends of a wide row, with their color the only
thing telling the active pane's cursor from the resting one's (xefm#350). Where
the terminal can color an underline it now rules the whole row instead, which is
what makes the row readable at a glance and which pane owns it.

Where it cannot, a rule would ink in the row's own text color and say only "this
row is underlined" — so there the brackets stay, being the spelling that carries
the cursor color no matter what the terminal implements. That choice is
``ctx.colored_underlines``; these tests render both sides of it.

The rule is drawn cell by cell (each grid cell holds one style), so these tests
walk the row: the blanks between columns have to carry it just as the text does,
or the line comes out dashed.
"""

import os
import sys
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.file_pane import BRACKET_W, CURSOR_ACTIVE, GUTTER_W, FilePane  # noqa: E402
from puikit import Panel  # noqa: E402
from puikit.backend import TextAttribute  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402
from puikit.capability import PROFILE_TUI, CapabilityProfile  # noqa: E402

THEME = dict(xefm_app.THEMES)["Dark+"]

CURSOR_ROW = 1
WIDTH, HEIGHT = 30, 6


def _render(active=True, theme=THEME, colored=True):
    """One settled TUI frame of a pane whose cursor sits on row CURSOR_ROW.

    ``colored`` is the terminal half: whether an underline can be given a color
    of its own, which is what decides the cue's spelling."""
    pane = {"files": [Path(f"/tmp/file{i}.txt") for i in range(5)],
            "focused_index": CURSOR_ROW, "selected_files": set(), "path": "/tmp"}
    backend = MemoryBackend(width=WIDTH, height=HEIGHT,
                            capabilities=CapabilityProfile(
                                {**PROFILE_TUI, "colored_underlines": colored}))
    panel = Panel(backend)
    panel.theme = theme
    view = FilePane(pane)
    view.active = active
    panel.add(view, x=0, y=0, w=WIDTH, h=HEIGHT)
    panel.render()
    return backend, view


def _row_styles(backend, row):
    return [backend.style_at(x, row) for x in range(WIDTH)]


class TUICursorCue(unittest.TestCase):

    def test_the_cursor_row_is_ruled_end_to_end(self):
        backend, view = _render()
        color = view._cursor_fg(THEME)
        for x, style in enumerate(_row_styles(backend, CURSOR_ROW)):
            self.assertTrue(style.attr & TextAttribute.UNDERLINE,
                            f"column {x} of the cursor row carries no rule")
            self.assertEqual(style.underline_color, color,
                             f"column {x} rules in the wrong color")

    def test_a_ruled_row_drops_the_brackets(self):
        # One cue, not two. The rule already marks the whole row, and the
        # brackets would be charging the listing two columns to repeat it.
        row = _render(colored=True)[0].snapshot()[CURSOR_ROW]
        self.assertNotEqual(row[0], "[")
        self.assertNotEqual(row[WIDTH - 1], "]")

    def test_a_terminal_without_colored_underlines_gets_the_brackets(self):
        # A rule inking in the row's own text color says "this row is
        # underlined", not "you are here", and nothing about which pane owns it.
        # The brackets carry the cursor color in their foreground, which every
        # terminal draws.
        backend, _ = _render(colored=False)
        row = backend.snapshot()[CURSOR_ROW]
        self.assertEqual(row[0], "[")
        self.assertEqual(row[WIDTH - 1], "]")
        for x, style in enumerate(_row_styles(backend, CURSOR_ROW)):
            self.assertFalse(style.attr & TextAttribute.UNDERLINE,
                             f"column {x} was ruled with no color to rule it in")

    def test_the_gutter_is_kept_either_way(self):
        # The cue's two columns are reserved whichever spelling the terminal
        # gets, so a pane's columns land in the same places on every terminal —
        # the row above the cursor is laid out identically in both.
        ruled = _render(colored=True)[0].snapshot()[CURSOR_ROW + 1]
        bracketed = _render(colored=False)[0].snapshot()[CURSOR_ROW + 1]
        self.assertEqual(ruled, bracketed)
        self.assertTrue(ruled.startswith(" file"), f"gutter not kept: {ruled!r}")

    def test_other_rows_are_untouched(self):
        backend, _ = _render()
        for row in (CURSOR_ROW - 1, CURSOR_ROW + 1):
            for x, style in enumerate(_row_styles(backend, row)):
                self.assertFalse(style.attr & TextAttribute.UNDERLINE,
                                 f"row {row} column {x} was ruled")
                self.assertIsNone(style.underline_color)

    def test_the_resting_pane_rules_in_a_colorless_cue(self):
        # Color means "you are working in this pane". The resting pane's rule is
        # a gray — not a dimmed version of the same hue, which is what made the
        # two panes hard to tell apart (xefm#350).
        active, _ = _render(active=True)
        resting, _ = _render(active=False)
        hot = active.style_at(0, CURSOR_ROW).underline_color
        cold = resting.style_at(0, CURSOR_ROW).underline_color
        self.assertEqual(hot, dict(xefm_app.THEMES)["Dark+"].extras.get(
            "cursor", {}).get("active", CURSOR_ACTIVE))
        self.assertNotEqual(hot, cold)
        self.assertEqual(len(set(cold)), 1, f"the resting cue is not gray: {cold}")

    def test_a_theme_that_names_a_resting_cue_keeps_it(self):
        # Segment LCD is a two-colour panel with no gray to spend, so it names
        # its own — and a user's config.py can do the same.
        lcd = dict(xefm_app.THEMES)["Segment LCD"]
        backend, _ = _render(active=False, theme=lcd)
        self.assertEqual(backend.style_at(0, CURSOR_ROW).underline_color,
                         lcd.extras["cursor"]["inactive"])

    def test_the_gutters_are_exactly_the_bracket_cells(self):
        # One column each side is what the cue costs the listing, and all it
        # costs — and what the ruled spelling has to fill to reach the row's ends.
        self.assertEqual((GUTTER_W, BRACKET_W), (1, 1))


if __name__ == "__main__":
    unittest.main()
