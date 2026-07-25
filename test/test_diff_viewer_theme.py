"""The file diff viewer's band backgrounds track the active theme.

Previously the delete/insert/replace/empty bands were fixed dark RGB constants,
so a diff read dark on every theme (most rows are non-identical). They are now
derived from the theme's content background, so a band is dark on a dark theme
and pastel on a light one — while unchanged lines still never tint.
"""

from xefm.diff_viewer import _diff_bgs, _side_bg

DARK = (30, 30, 30)
LIGHT = (255, 255, 255)


def test_bands_follow_content_polarity():
    dark, light = _diff_bgs(DARK), _diff_bgs(LIGHT)
    for band in ("delete", "insert", "replace", "char_del", "char_ins", "empty"):
        assert sum(dark[band]) < sum(light[band]), band  # dark theme darker than light


def test_delete_band_reads_red_on_both_polarities():
    for content in (DARK, LIGHT):
        r, g, b = _diff_bgs(content)["delete"]
        assert r > g and r > b            # a red-tinted band in either theme


def test_insert_band_reads_green_on_both_polarities():
    for content in (DARK, LIGHT):
        r, g, b = _diff_bgs(content)["insert"]
        assert g > r and g > b            # a green-tinted band in either theme


def test_dark_theme_matches_previous_constants_closely():
    # The dark-theme values stay within a couple of units of the old hardcoded
    # constants, so switching to derivation does not visibly change dark themes.
    dark = _diff_bgs(DARK)
    for band, old in {"delete": (60, 30, 30), "insert": (28, 50, 30),
                      "replace": (50, 46, 28), "empty": (32, 32, 34)}.items():
        assert all(abs(dark[band][i] - old[i]) <= 8 for i in range(3)), (band, dark[band])


def test_side_bg_picks_from_palette_and_skips_equal_rows():
    pal = _diff_bgs(LIGHT)
    assert _side_bg({"tag": "equal"}, "l", pal) is None
    assert _side_bg({"tag": "delete"}, "l", pal) == pal["delete"]
    assert _side_bg({"tag": "delete"}, "r", pal) == pal["empty"]
    assert _side_bg({"tag": "insert"}, "r", pal) == pal["insert"]
    assert _side_bg({"tag": "replace"}, "l", pal) == pal["replace"]
