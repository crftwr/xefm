"""Every built-in theme keeps its cursor and its selections visible (#844-#847).

The numbers are OKLab ΔE between two fills, or APCA Lc of a cue on a fill.
ΔE 0.10 reads at a glance; the reports that started this were at 0.02-0.06
(Dark+'s search-dialog selection on the dialog, Shinagawa's cursor against its
file names). Each rule is checked over ``THEMES``, so a new theme is held to it
the day it is added.
"""
from types import SimpleNamespace

import pytest
from puikit.color import LC_MIN_NONTEXT, apca_lc, oklab_distance

from xefm.app import THEMES
from xefm.file_pane import (DIRECTORY_FG_DEFAULT, FilePane, match_fill,
                            selection_fill)

VISIBLE = 0.10
#: A match row beside a selected one: two marks, told apart by hue. Solarized
#: Light's pale tints leave no hue past 0.099 from its selection; 0.09 still
#: separates them, and the report was at 0.04 (#847).
MARKS_APART = 0.09

#: Two colours in all: the cursor outline is the segments' black, the black of
#: every name it frames. The frame is a shape, not a hue, by design.
ONE_INK = {"Segment LCD"}

IDS = [name for name, _theme in THEMES]


def _cursor(theme, active, on=None):
    pane = SimpleNamespace(active=active)
    return FilePane._cursor_fg(pane, theme, theme.surfaces["content"], on=on)


def _names(theme):
    file_types = theme.extras.get("file_types") or {}
    directory = (file_types.get("directory") or theme.extras.get("directory")
                 or DIRECTORY_FG_DEFAULT)
    return {"text": theme.text, "directory": directory, "link": file_types.get("link")}


@pytest.mark.parametrize("name,theme", THEMES, ids=IDS)
def test_dialog_list_selection_shows_on_the_dialog(name, theme):
    # A dialog's list is drawn on popup_bg with the active fill (#844).
    assert oklab_distance(theme.selection_active_bg, theme.popup_bg) >= VISIBLE - 1e-3


@pytest.mark.parametrize("name,theme", THEMES, ids=IDS)
def test_file_pane_selection_shows_on_the_pane(name, theme):
    base = theme.surfaces["content"]
    assert oklab_distance(selection_fill(theme, base), base) >= VISIBLE


@pytest.mark.parametrize("name,theme", THEMES, ids=IDS)
def test_isearch_match_is_not_the_selection(name, theme):
    base = theme.surfaces["content"]
    assert oklab_distance(match_fill(theme, base), selection_fill(theme, base)) >= MARKS_APART


@pytest.mark.parametrize("name,theme", THEMES, ids=IDS)
def test_cursor_is_not_the_color_of_the_names_it_frames(name, theme):
    if name in ONE_INK:
        pytest.skip("a two-colour palette by design")
    for active in (True, False):
        cue = _cursor(theme, active)
        for what, ink in _names(theme).items():
            if ink is None or (not active and what != "text"):
                continue
            assert oklab_distance(cue, ink) >= VISIBLE, (active, what, cue, ink)


@pytest.mark.parametrize("name,theme", THEMES, ids=IDS)
def test_cursor_shows_on_a_selected_row(name, theme):
    base = theme.surfaces["content"]
    for active in (True, False):
        fill = selection_fill(theme, base, active)
        cue = _cursor(theme, active, on=fill)
        assert abs(apca_lc(cue, fill)) >= LC_MIN_NONTEXT, (active, cue, fill)


def test_a_cue_already_visible_on_the_fill_keeps_its_color():
    name, theme = THEMES[0]
    assert _cursor(theme, True, on=(255, 255, 255)) == _cursor(theme, True)
