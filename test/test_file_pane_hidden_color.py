"""A hidden entry looks hidden, without costing the palette a second entry per type.

``file_types`` colors a filename by type — link, directory, file. Hidden is not a
fourth type but a property orthogonal to all three (a hidden directory is still a
directory), so the pane spends the one channel that *composes* with a type color
instead of replacing it: the name keeps its type hue and recedes toward the pane
background. What these tests pin is that composition — the type survives the fade,
the fade is configurable, and a theme that would rather have one flat color for
every hidden entry (a monochrome palette, with no second hue to spend) can say so.

The last class renders a pane for real, which is the test that matters: the
color arithmetic below can be perfectly correct while the pane still draws the
two alike, because ``ctx.ink`` floors every name for legibility and a dark
theme's body text clears that floor by a hair. Asserting on ``_type_fg``'s
return value alone would not have noticed.

Also covers where the flag comes from: the listing's own attribute record, through
the same ``is_hidden`` predicate the hidden-files toggle filters on, so an entry
the toggle calls hidden is the one the pane fades. On Windows that is the whole
feature — hidden there is a file attribute, not a leading dot (issue #354).

Run just this file:  python -m pytest test/test_file_pane_hidden_color.py -v
"""

import math
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.file_pane import (  # noqa: E402
    DIRECTORY_FG_DEFAULT, HIDDEN_DIM, HIDDEN_LC, LINK_FG_DEFAULT, FilePane, _mix,
)
from puikit import PROFILE_GUI_DESKTOP, Panel  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402
from puikit.capability import CapabilityProfile  # noqa: E402
from puikit.color import apca_lc, rgb_to_oklab  # noqa: E402

#: The pane background the wash aims at. Any color works; a near-black one is
#: what the dark themes actually use.
BG = (30, 30, 30)
TEXT = (212, 212, 212)


def _theme(**file_types):
    """A theme stub carrying just what ``_type_fg`` reads."""
    extras = {"file_types": dict(file_types)} if file_types else {}
    return SimpleNamespace(extras=extras, text=TEXT)


def _fg(theme, kind, hidden=False, base=BG):
    is_dir = kind == "directory"
    is_link = kind == "link"
    return FilePane._type_fg(theme, is_dir, is_link, hidden, base)


def _chroma(color):
    """How much color is left in it — OKLab chroma, the thing the ink lift eats."""
    _, a, b = rgb_to_oklab(color)
    return math.hypot(a, b)


def _distance(c1, c2):
    """Perceptual distance in OKLab: how far apart two rows look."""
    l1, a1, b1 = rgb_to_oklab(c1)
    l2, a2, b2 = rgb_to_oklab(c2)
    return math.hypot(math.hypot(a1 - a2, b1 - b2), l1 - l2)


class HiddenKeepsItsType(unittest.TestCase):

    def test_every_type_recedes_toward_the_pane_background(self):
        theme = _theme()
        for kind in ("file", "directory", "link"):
            with self.subTest(kind=kind):
                plain = _fg(theme, kind)
                faded = _fg(theme, kind, hidden=True)
                self.assertNotEqual(plain, faded, "a hidden entry must look different")
                # Exactly the wash, with nothing between the theme's color and
                # the row: keeping a faint name findable is the draw site's job.
                self.assertEqual(faded, _mix(plain, BG, HIDDEN_DIM))
                self.assertLess(abs(apca_lc(faded, BG)), abs(apca_lc(plain, BG)))
                # Between the type color and the background, on every channel:
                # receded, not recolored.
                for i in range(3):
                    lo, hi = sorted((plain[i], BG[i]))
                    self.assertTrue(lo <= faded[i] <= hi)

    def test_the_wash_takes_chroma_with_it(self):
        """Not only lightness. Fading toward the background spends both, which is
        what the eye reads as faded; darkening alone leaves a deeper, more vivid
        color, and vivid reads as prominent — it made the hidden rows the loud
        ones. Asserted on a chromatic type, greys having none to lose."""
        theme = _theme()
        self.assertLess(_chroma(_fg(theme, "directory", hidden=True)),
                        _chroma(_fg(theme, "directory")))

    def test_the_three_types_stay_apart_once_hidden(self):
        """The reason the palette needs no hidden_dir / hidden_link entries: the
        type is still legible in the faded color."""
        theme = _theme()
        faded = {kind: _fg(theme, kind, hidden=True)
                 for kind in ("file", "directory", "link")}
        self.assertEqual(len(set(faded.values())), 3)

    def test_a_link_to_a_folder_is_still_a_link(self):
        """Type precedence is unchanged by the fade."""
        theme = _theme()
        both = FilePane._type_fg(theme, True, True, True, BG)
        self.assertEqual(both, _mix(LINK_FG_DEFAULT, BG, HIDDEN_DIM))

    def test_a_visible_entry_is_untouched(self):
        """The whole feature is invisible to a pane with nothing hidden in it."""
        theme = _theme()
        self.assertEqual(_fg(theme, "file"), TEXT)
        self.assertEqual(_fg(theme, "directory"), DIRECTORY_FG_DEFAULT)
        self.assertEqual(_fg(theme, "link"), LINK_FG_DEFAULT)


class TheThemeCanOverrideIt(unittest.TestCase):

    def test_a_number_is_honored_verbatim(self):
        """The wash is exactly what the theme asked for. Keeping a name findable
        is the draw site's job (HIDDEN_LC), not this one's — see
        ``ItSurvivesTheLegibilityFloor`` for the backstop."""
        for amount in (0.05, 0.6, 0.9):
            with self.subTest(amount=amount):
                self.assertEqual(_fg(_theme(hidden=amount), "file", hidden=True),
                                 _mix(TEXT, BG, amount))

    def test_zero_turns_the_fade_off(self):
        for spec in (0, 0.0, False):
            with self.subTest(spec=spec):
                theme = _theme(hidden=spec)
                self.assertEqual(_fg(theme, "file", hidden=True), TEXT)

    def test_out_of_range_is_clamped_not_an_error(self):
        self.assertEqual(_fg(_theme(hidden=5), "file", hidden=True), BG)
        self.assertEqual(_fg(_theme(hidden=-1), "file", hidden=True), TEXT)

    def test_nonsense_falls_back_to_the_default(self):
        """A config typo dims by the default rather than taking the pane down."""
        self.assertEqual(_fg(_theme(hidden="dim"), "file", hidden=True),
                         _mix(TEXT, BG, HIDDEN_DIM))

    def test_a_color_replaces_the_type_color_for_every_type(self):
        """What a monochrome theme wants: one flat hidden color, type and all."""
        flat = (110, 110, 110)
        theme = _theme(hidden=flat)
        for kind in ("file", "directory", "link"):
            with self.subTest(kind=kind):
                self.assertEqual(_fg(theme, kind, hidden=True), flat)
                # ...and it never leaks onto a visible entry.
                self.assertNotEqual(_fg(theme, kind), flat)

    def test_a_list_is_accepted_like_a_tuple(self):
        """``config.py`` is hand-written; both spellings of a color are honored."""
        self.assertEqual(_fg(_theme(hidden=[1, 2, 3]), "file", hidden=True), (1, 2, 3))

    def test_the_type_colors_still_come_from_the_theme(self):
        theme = _theme(directory=(10, 200, 10), hidden=0.5)
        self.assertEqual(_fg(theme, "directory", hidden=True),
                         _mix((10, 200, 10), BG, 0.5))


#: Built-ins that name their own ``hidden``. None do yet — the default covers
#: every palette — and this is the list to add to when one wants its own look,
#: the way ``test_pane_focus_chrome`` tracks the themes opting into the focus
#: chrome. It exists so the guarantee below stays "a theme that names nothing is
#: faded by the default" rather than "no theme may ever name it".
HIDDEN_OPTED_IN = ()


class EveryBuiltInThemeFadesHiddenEntries(unittest.TestCase):
    """The feature costs a theme nothing to receive: a palette that says nothing
    about hidden entries still shows them as hidden."""

    def test_all_of_them(self):
        for name, theme in xefm_app.THEMES:
            with self.subTest(theme=name):
                named = "hidden" in (theme.extras.get("file_types") or {})
                self.assertEqual(named, name in HIDDEN_OPTED_IN)
                if named:
                    continue
                plain = FilePane._type_fg(theme, False, False, False, BG)
                faded = FilePane._type_fg(theme, False, False, True, BG)
                self.assertEqual(faded, _mix(plain, BG, HIDDEN_DIM))


class TheFlagComesFromTheListing(unittest.TestCase):
    """``_build_file_info`` copies it out of the record ``dir_scan`` already
    collected, so rendering issues no ``stat`` of its own."""

    def setUp(self):
        self.flm = FileListManager(SimpleNamespace(SHOW_HIDDEN_FILES=True,
                                                   DATE_FORMAT=None))

    def _info(self, name, **attrs):
        path = Path("/tmp") / name
        record = {"is_dir": False, "is_link": False, "size": 1, "alloc": 1,
                  "mtime": 0.0, "hidden": False, "ok": True}
        record.update(attrs)
        info = self.flm._build_file_info([path], attrs={str(path): record})
        return info[str(path)]

    def test_a_dotfile_is_hidden_on_every_platform(self):
        self.assertTrue(self._info(".bashrc")["hidden"])

    def test_the_platform_attribute_is_hidden_too(self):
        """The Windows half (issue #284): no dot in the name, hidden all the
        same — and nothing but the color would say so."""
        self.assertTrue(self._info("desktop.ini", hidden=True)["hidden"])

    def test_an_ordinary_file_is_not(self):
        self.assertFalse(self._info("notes.txt")["hidden"])

    def test_a_hidden_directory_keeps_being_a_directory(self):
        info = self._info(".git", is_dir=True)
        self.assertTrue(info["hidden"])
        self.assertTrue(info["is_dir"])


class ItSurvivesTheLegibilityFloor(unittest.TestCase):
    """Rendered through a real pane, on every built-in theme.

    ``ctx.ink`` lifts any ink that falls below its contrast target, and a
    filename is floored as body text. Dark+ body text sits at Lc 78.7 against a
    75 target, so fading it lands under the floor and comes back up: the first
    cut of this feature drew a hidden file at (206, 206, 208) next to a visible
    one at (212, 212, 212) — arithmetically faded, indistinguishable on screen.
    A hidden name is therefore floored at the *quiet* tier (``LC_LARGE``), the
    one the size/date columns already read at, which leaves somewhere to fade to
    while keeping the name readable."""

    #: How much quieter a hidden name must read, in APCA Lc. Below ~10 the two
    #: rows look alike; the floor puts every built-in well past it (Dark+ drops
    #: 33.7, from body weight to HIDDEN_LC).
    MIN_DROP = 20.0

    #: The three types, as ``_draw_row`` sees them.
    KINDS = (("file", False, False), ("dir", True, False), ("link", False, True))

    @staticmethod
    def _name_fgs(theme, hidden, cursor=-1, backend=None):
        """One rendered pane holding all three types; the color each name was
        drawn in, keyed by type."""
        files, info = [], {}
        for kind, is_dir, is_link in ItSurvivesTheLegibilityFloor.KINDS:
            p = Path("/tmp") / f"{kind}_one"
            files.append(p)
            info[str(p)] = {"size_str": "1 K", "date_str": "", "is_dir": is_dir,
                            "is_link": is_link, "hidden": hidden}
        pane = {"files": files, "focused_index": cursor, "selected_files": set(),
                "path": "/tmp", "file_info": info}
        panel = Panel(backend or MemoryBackend(width=44, height=8))
        panel.theme = theme
        # As XeFMApp configures it (app.py). Without this the Panel's own
        # auto-ink never runs and the pane measures a pipeline the app does not
        # have — which is exactly how a hidden name that the app was lifting
        # back to body weight passed these tests looking correctly faded.
        panel.auto_ink = True
        view = FilePane(pane)
        view.active = True
        # The pane's background is what the ink floor measures against, and the
        # app gives it one through the layout's surface role — without the hint
        # every theme would be inked against the fallback dark.
        panel.add(view, x=0, y=0, w=44, h=8, hints={"surface": "content"})
        panel.render()
        for wid in list(panel._text_anims):  # settle any arriving-text effect
            panel._text_anims[wid] -= 99.0
        panel.render()
        grid = panel.backend.snapshot()
        out = {}
        for y, row in enumerate(grid):
            line = "".join(row)
            for kind, _, _ in ItSurvivesTheLegibilityFloor.KINDS:
                if f"{kind}_one" in line:
                    out[kind] = panel.backend.style_at(line.index(f"{kind}_one"), y).fg
        if len(out) != len(ItSurvivesTheLegibilityFloor.KINDS):
            raise AssertionError("the pane drew no filenames")
        return out

    def test_a_hidden_name_reads_quieter_in_every_theme(self):
        for name, theme in xefm_app.THEMES:
            with self.subTest(theme=name):
                bg = dict(xefm_app._THEME_SPECS)[name]["bg"]
                visible = abs(apca_lc(self._name_fgs(theme, False)["file"], bg))
                hidden = abs(apca_lc(self._name_fgs(theme, True)["file"], bg))
                self.assertGreater(visible - hidden, self.MIN_DROP)
                # ...and is still a name the user can read.
                self.assertGreaterEqual(hidden, HIDDEN_LC - 1.0)


class _VectorBackend(MemoryBackend):
    """GUI-like: vector shapes on. MemoryBackend masks them off (it is a
    character grid), and the cursor row's fill — the thing that made the cursor
    row differ — only happens on a backend that has them."""

    @property
    def capabilities(self):
        return CapabilityProfile({**PROFILE_GUI_DESKTOP, "native_menus": False})

    @property
    def base_size(self):
        return (8, 16)


class TheCursorRowIsNotASpecialCase(unittest.TestCase):
    """A hidden file under the cursor must look like every other hidden file.

    It did not. On a GUI backend the cursor row paints a fill and draws its text
    over it transparently, and the Panel skips auto-ink wherever there is no
    concrete background to measure — so the cursor row kept the faded color while
    every other row had it lifted back to body weight. The cursor became the one
    place the feature worked: Gruvbox drew the hidden file under the cursor at
    (165, 155, 128) and the hidden files around it at (213, 209, 196).

    The fix is to opt the hidden name out of auto-ink (``ink=False``) rather than
    to let two paths disagree, so this asserts the agreement on both backends."""

    def test_the_cursor_row_matches_its_neighbours(self):
        render = ItSurvivesTheLegibilityFloor._name_fgs
        for name, theme in xefm_app.THEMES:
            for label, backend in (("grid", None), ("vector", _VectorBackend(width=44, height=8))):
                with self.subTest(theme=name, backend=label):
                    # The cursor sits on the *second* row, which _name_fgs lays
                    # out as the directory; the file and symlink rows beside it
                    # are drawn the ordinary way.
                    under = render(theme, True, cursor=1, backend=backend)
                    alone = render(theme, True, cursor=-1)
                    self.assertEqual(under["dir"], alone["dir"])

    def test_it_holds_for_visible_rows_too(self):
        render = ItSurvivesTheLegibilityFloor._name_fgs
        for name, theme in xefm_app.THEMES:
            with self.subTest(theme=name):
                under = render(theme, False, cursor=1,
                               backend=_VectorBackend(width=44, height=8))
                alone = render(theme, False, cursor=-1)
                self.assertEqual(under["dir"], alone["dir"])


class HiddenRowsDoNotAllTurnGrey(unittest.TestCase):
    """The failure the floor-limited fade exists to prevent.

    Washing a name *past* the floor and letting ``ctx.ink`` lift it back does
    not give a dimmer color: the lift mixes toward white, so it returns a paler,
    flatter one. Dark+ drew hidden directories at (182, 182, 153) and hidden
    symlinks at (153, 186, 192) — a yellow and a cyan reduced to two shades of
    the same off-white, indistinguishable from each other and from a hidden
    plain file. The pane kept its type colors in theory and lost them on screen.

    So these assertions are about what survives the whole pipeline: hidden rows
    keep their chroma, and stay as far apart from each other as visible rows do.
    """

    #: A hidden row spends chroma — that is half of what makes it read as faded —
    #: but it may not spend nearly all of it. The built-ins keep 69% at worst
    #: (Shinagawa's symlinks). The failure this guards against is not the wash
    #: but the *lift*: auto-ink restoring contrast by mixing toward white left
    #: directories on 42% of their chroma and symlinks on 56%, every type pulled
    #: toward the same off-white.
    MIN_CHROMA_KEPT = 0.6
    #: How much of the visible types' separation the hidden ones must keep. The
    #: wash scales a pane's colors down together, so the types stay in the same
    #: arrangement: the built-ins keep 63% at worst. The washed-out failure this
    #: guards against kept 18–42%, having pushed every type toward one off-white.
    MIN_SEPARATION_KEPT = 0.55
    #: Below this, two rendered colors are near enough to the same that comparing
    #: them says nothing — a theme whose types genuinely share a color (Segment
    #: LCD paints files and directories alike) lands here and is skipped.
    SAME_COLOR = 0.03

    def setUp(self):
        self.render = ItSurvivesTheLegibilityFloor._name_fgs

    def test_a_hidden_entry_keeps_its_color(self):
        for name, theme in xefm_app.THEMES:
            visible, hidden = self.render(theme, False), self.render(theme, True)
            for kind in ("dir", "link"):
                if _chroma(visible[kind]) < 0.02:  # a monochrome theme's "hue"
                    continue
                with self.subTest(theme=name, kind=kind):
                    self.assertGreaterEqual(
                        _chroma(hidden[kind]),
                        _chroma(visible[kind]) * self.MIN_CHROMA_KEPT)

    def test_hidden_entries_stay_apart_from_each_other(self):
        pairs = (("dir", "file"), ("link", "file"), ("dir", "link"))
        for name, theme in xefm_app.THEMES:
            visible, hidden = self.render(theme, False), self.render(theme, True)
            for a, b in pairs:
                if _distance(visible[a], visible[b]) < self.SAME_COLOR:
                    continue  # this theme does not distinguish them either
                with self.subTest(theme=name, pair=f"{a}/{b}"):
                    self.assertGreaterEqual(
                        _distance(hidden[a], hidden[b]),
                        _distance(visible[a], visible[b]) * self.MIN_SEPARATION_KEPT)


if __name__ == "__main__":
    unittest.main()
