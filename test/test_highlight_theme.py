"""Search / isearch match highlights track the active theme.

The file-pane isearch wash and the text-viewer search-match backgrounds were
fixed dark constants, so they read dark on the light themes. They are now
derived from the pane/content background, so a match highlight is a dark wash on
a dark theme and a pale one on a light theme. The isearch wash also draws its
base hue from the theme's secondary accent (``accent2`` / an ``isearch_match``
override), and the text-viewer syntax palette is theme-configurable too.
"""

from types import SimpleNamespace

from xefm.file_pane import MATCH_TINT, _mix
from xefm.text_viewer import DEFAULT_SYNTAX, _is_light, _match_bg, _syntax_palette

DARK = (30, 30, 38)
LIGHT = (255, 255, 255)


def _luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def test_is_light_polarity():
    assert _is_light(LIGHT)
    assert not _is_light(DARK)
    assert not _is_light(None)


def test_filepane_isearch_wash_uses_accent2_base_and_tracks_theme():
    # The wash defaults to the theme's secondary accent blended into the pane
    # background (FilePane resolves it as theme.extras['isearch_match'] or
    # theme.accent2), so it tracks polarity — dark bg -> dark wash, light -> pale —
    # and leans toward the accent2 hue on both.
    accent2 = (78, 201, 176)  # a teal secondary accent
    dark = _mix(DARK, accent2, MATCH_TINT)
    light = _mix(LIGHT, accent2, MATCH_TINT)
    assert _luma(dark) < _luma(light)
    for band in (dark, light):
        assert band[1] > band[0]   # leans toward accent2 (green above red) on both


def test_syntax_palette_merges_theme_extras_onto_default():
    from puikit.theme import Theme
    # No extras -> the built-in VS Code default palette.
    assert _syntax_palette(SimpleNamespace(theme=Theme())) == DEFAULT_SYNTAX
    # A partial override recolors only the named tokens, keeping the rest.
    themed = Theme(extras={"syntax": {"keyword": (1, 2, 3)}})
    pal = _syntax_palette(SimpleNamespace(theme=themed))
    assert pal["keyword"] == (1, 2, 3)
    assert pal["string"] == DEFAULT_SYNTAX["string"]


def test_text_match_backgrounds_track_theme():
    for current in (False, True):
        dark = _match_bg(DARK, current)
        light = _match_bg(LIGHT, current)
        assert _luma(dark) < _luma(light)
        # amber wash: red & green above blue on both polarities
        assert dark[0] > dark[2] and dark[1] > dark[2]
        assert light[0] > light[2] and light[1] > light[2]


def test_current_match_is_firmer_than_plain_match():
    # On a dark theme the current match is darker/more saturated (further from bg);
    # either way it is visually distinct from a plain match.
    assert _match_bg(DARK, True) != _match_bg(DARK, False)
    assert _match_bg(LIGHT, True) != _match_bg(LIGHT, False)
