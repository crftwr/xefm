"""The size and date columns read a tier below the filenames, on every row.

`_draw_row` inks them at `LC_LARGE` deliberately: a pane is a list of names, and
the numbers beside them are there to be consulted, not read down. That intent was
not reaching the screen. `Panel.auto_ink` — which `XeFMApp` turns on — holds every
text run with a concrete background to a weight-aware floor, `LC_BODY` for
ordinary text, and it does not know the pane already chose a lower one. Gruvbox's
muted ink (146, 131, 116) arrived at the row as (214, 208, 201), a hair off the
filename's own color, which is why a pane's numbers looked as loud as its names.

It also did not do it uniformly: a run drawn over a *transparent* background is
left alone, and on a GUI backend that is the cursor row, which fills and then
draws over its own fill. So the columns were quiet on the cursor row and loud
everywhere else.

Both are the same fix — `ink=False`, PuiKit's opt-out for a color its widget owns
— and both are asserted here, on a rendered pane rather than on the inputs, since
the whole failure lived downstream of what the pane passed in.

Run just this file:  python -m pytest test/test_file_pane_column_weight.py -v
"""

import os
import sys
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.file_pane import FilePane  # noqa: E402
from puikit import PROFILE_GUI_DESKTOP, Panel  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402
from puikit.capability import CapabilityProfile  # noqa: E402
from puikit.color import LC_LARGE, apca_lc, legible_ink  # noqa: E402

SIZE = "12.3K"
DATE = "26-09-24 21:00"
NAMES = ("first_row", "second_row")


class _VectorBackend(MemoryBackend):
    """GUI-like: vector shapes on, so the cursor row fills and draws over itself.
    MemoryBackend masks them off, being a character grid."""

    @property
    def capabilities(self):
        return CapabilityProfile({**PROFILE_GUI_DESKTOP, "native_menus": False})

    @property
    def base_size(self):
        return (8, 16)


def _render(theme, cursor=-1, vector=False):
    """One pane of two ordinary rows; the color of each row's name and of its
    size column, keyed by row name."""
    files, info = [], {}
    for name in NAMES:
        p = Path("/tmp") / name
        files.append(p)
        info[str(p)] = {"size_str": SIZE, "date_str": DATE, "is_dir": False,
                        "is_link": False, "hidden": False}
    pane = {"files": files, "focused_index": cursor, "selected_files": set(),
            "path": "/tmp", "file_info": info}
    backend = (_VectorBackend if vector else MemoryBackend)(width=64, height=8)
    panel = Panel(backend)
    panel.theme = theme
    # As XeFMApp configures it (app.py): without this the Panel's second ink pass
    # never runs, and a test measures a pipeline the app does not have.
    panel.auto_ink = True
    view = FilePane(pane)
    view.active = True
    panel.add(view, x=0, y=0, w=64, h=8, hints={"surface": "content"})
    panel.render()
    for wid in list(panel._text_anims):  # settle any arriving-text effect
        panel._text_anims[wid] -= 99.0
    panel.render()
    grid = backend.snapshot()
    out = {}
    for y, row in enumerate(grid):
        line = "".join(row)
        for name in NAMES:
            if name in line and SIZE in line:
                out[name] = {"name": backend.style_at(line.index(name), y).fg,
                             "size": backend.style_at(line.index(SIZE), y).fg}
    if len(out) != len(NAMES):
        raise AssertionError("the pane drew no rows")
    return out


def _bg(name):
    return dict(xefm_app._THEME_SPECS)[name]["bg"]


class TheColumnsSitBelowTheNames(unittest.TestCase):

    #: How much quieter, in APCA Lc, the numbers must read than the name beside
    #: them. The two targets are 15 apart (LC_BODY 75, LC_LARGE 60) and a name
    #: whose color clears its own floor widens the gap rather than narrowing it.
    MIN_GAP = 10.0

    def test_the_pane_s_own_color_reaches_the_row(self):
        """The exact color ``_draw_row`` inked, not a lifted one. Stated as an
        identity rather than as a contrast band because the pane's ink is a
        *floor*: on most themes it lands the muted ink at LC_LARGE, and on the
        ones whose muted ink already clears it (Light+, Segment LCD) it hands
        back the theme's own color untouched. Either way nothing after the pane
        may move it."""
        for name, theme in xefm_app.THEMES:
            with self.subTest(theme=name):
                row = _render(theme)[NAMES[0]]
                self.assertEqual(row["size"],
                                 legible_ink(theme.muted_text, _bg(name), LC_LARGE))

    def test_a_name_still_reads_louder_than_its_numbers(self):
        for name, theme in xefm_app.THEMES:
            with self.subTest(theme=name):
                row = _render(theme)[NAMES[0]]
                gap = (abs(apca_lc(row["name"], _bg(name)))
                       - abs(apca_lc(row["size"], _bg(name))))
                self.assertGreater(gap, self.MIN_GAP)


class TheCursorRowIsNotASpecialCase(unittest.TestCase):
    """The columns under the cursor must match the columns beside it — the one
    place they used to be right while every other row was lifted."""

    def test_on_a_gui_backend(self):
        for name, theme in xefm_app.THEMES:
            with self.subTest(theme=name):
                rows = _render(theme, cursor=0, vector=True)
                self.assertEqual(rows[NAMES[0]]["size"], rows[NAMES[1]]["size"])

    def test_on_a_grid_backend(self):
        for name, theme in xefm_app.THEMES:
            with self.subTest(theme=name):
                rows = _render(theme, cursor=0)
                self.assertEqual(rows[NAMES[0]]["size"], rows[NAMES[1]]["size"])

    def test_and_matches_a_pane_with_no_cursor_at_all(self):
        for name, theme in xefm_app.THEMES:
            with self.subTest(theme=name):
                under = _render(theme, cursor=0, vector=True)[NAMES[0]]
                alone = _render(theme)[NAMES[0]]
                self.assertEqual(under["size"], alone["size"])


if __name__ == "__main__":
    unittest.main()
