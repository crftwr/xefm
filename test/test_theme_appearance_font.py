"""The OS appearance follows the theme, and a reload re-applies the base font (#857).

Every theme carries ``extras["appearance"]`` -- ``"light"`` or ``"dark"`` -- which
``XeFMApp._apply_appearance`` hands to ``Backend.set_appearance`` so the title bar
(and on macOS the native menus) match the theme. A config reload that changes
``MONO_FONT_NAME`` or ``FONT_SIZE`` hands the backend the new base font through
``Backend.set_base_font`` and drops the file panes' measured column widths.
No window: a recording backend stands in for the real one.
"""

import types

from xefm import app as xefm_app


def _themes(themes=None):
    return dict(xefm_app._build_theme_list(types.SimpleNamespace(THEMES=themes or {})))


class _Backend:
    def __init__(self):
        self.calls = []

    def set_appearance(self, appearance):
        self.calls.append(("appearance", appearance))

    def set_base_font(self, font):
        self.calls.append(("font", font))


class _View:
    def __init__(self):
        self.forgotten = 0

    def forget_measurements(self):
        self.forgotten += 1


def _app():
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app.backend = _Backend()
    app.left_view = _View()
    app.right_view = _View()
    return app


def _cfg(mono=None, size=12):
    return types.SimpleNamespace(MONO_FONT_NAME=mono, FONT_SIZE=size)


# -- appearance ------------------------------------------------------------

def test_the_background_decides_by_default():
    themes = _themes()
    assert themes["Dark+"].extras["appearance"] == "dark"
    assert themes["Light+"].extras["appearance"] == "light"
    assert themes["Solarized Light"].extras["appearance"] == "light"
    assert themes["Segment LCD"].extras["appearance"] == "light"


def test_pelagic_is_light_over_its_dark_water():
    # Its title bar meets the white shell, not the water its background names.
    assert xefm_app._theme_appearance(None, (3, 22, 26)) == "dark"
    assert _themes()["Pelagic"].extras["appearance"] == "light"


def test_every_builtin_theme_says_light_or_dark():
    for name, theme in xefm_app.THEMES:
        assert theme.extras.get("appearance") in ("light", "dark"), name


def test_a_config_theme_can_pin_it():
    themes = _themes({"Ocean": {"appearance": "light"},
                      "Paper": {"base": "Light+", "appearance": "dark"}})
    assert themes["Ocean"].extras["appearance"] == "light"
    assert themes["Paper"].extras["appearance"] == "dark"


def test_a_bad_value_falls_back_to_the_background():
    themes = _themes({"Odd": {"appearance": "sepia"}})
    assert themes["Odd"].extras["appearance"] == "dark"   # built on Dark+


def test_apply_appearance_pushes_the_theme_s():
    app = _app()
    app._apply_appearance(_themes()["Light+"])
    app._apply_appearance(_themes()["Dark+"])
    assert app.backend.calls == [("appearance", "light"), ("appearance", "dark")]


# -- base font -------------------------------------------------------------

def test_base_font_is_mono_at_font_size():
    font = xefm_app._base_font(_cfg("Menlo", 14))
    assert (font.family, font.size, font.monospace) == ("Menlo", 14.0, True)


def test_an_unchanged_font_is_left_alone():
    app = _app()
    app._apply_base_font(_cfg("Menlo", 12), _cfg("Menlo", 12))
    assert app.backend.calls == []
    assert app.left_view.forgotten == 0


def test_a_new_size_goes_to_the_backend_and_panes_measure_again():
    app = _app()
    app._apply_base_font(_cfg(None, 12), _cfg(None, 16))
    [(kind, font)] = app.backend.calls
    assert kind == "font" and font.size == 16.0 and font.family is None
    assert app.left_view.forgotten == 1 and app.right_view.forgotten == 1


def test_a_new_mono_face_goes_to_the_backend():
    app = _app()
    app._apply_base_font(_cfg(None, 12), _cfg("Menlo", 12))
    [(kind, font)] = app.backend.calls
    assert kind == "font" and font.family == "Menlo"


def test_an_invalid_value_waits_for_the_next_launch():
    app = _app()
    app._apply_base_font(_cfg(None, 12), _cfg(None, 200))
    app._apply_base_font(_cfg(None, 12), _cfg("   ", 12))
    assert app.backend.calls == []


def test_file_pane_forgets_its_measurements():
    view = xefm_app.FilePane.__new__(xefm_app.FilePane)
    view._measure_cache = (("key",), {"values": {0: 5.0}})
    view.forget_measurements()
    assert view._measure_cache == (None, None)


# -- temporary font size (View > Font Size) ----------------------------------

def _desktop_app(monkeypatch, *, desktop=True, size=12):
    monkeypatch.setattr(xefm_app, "is_desktop_mode", lambda: desktop)
    app = _app()
    app.config = _cfg(None, size)
    app.logged = []
    app.log_info = app.logged.append
    return app


def _sizes(app):
    return [font.size for kind, font in app.backend.calls if kind == "font"]


def test_larger_and_smaller_step_one_point(monkeypatch):
    app = _desktop_app(monkeypatch)
    app._step_font_size(+1)
    app._step_font_size(+1)
    app._step_font_size(-1)
    assert _sizes(app) == [13.0, 14.0, 13.0]
    assert app._font_size_override == 13
    assert app.left_view.forgotten == 3


def test_default_size_goes_back_to_font_size(monkeypatch):
    app = _desktop_app(monkeypatch, size=14)
    app._step_font_size(+1)
    app._step_font_size(0)
    assert _sizes(app) == [15.0, 14.0]
    assert app._font_size_override is None
    app._step_font_size(0)                 # already there: nothing to do
    assert _sizes(app) == [15.0, 14.0]


def test_stepping_back_to_font_size_clears_the_override(monkeypatch):
    app = _desktop_app(monkeypatch)
    app._step_font_size(+1)
    app._step_font_size(-1)
    assert app._font_size_override is None


def test_the_size_stops_at_the_valid_range(monkeypatch):
    app = _desktop_app(monkeypatch, size=72)
    app._step_font_size(+1)
    assert _sizes(app) == [] and "largest" in app.logged[-1]
    app = _desktop_app(monkeypatch, size=8)
    app._step_font_size(-1)
    assert _sizes(app) == [] and "smallest" in app.logged[-1]


def test_a_terminal_only_says_so(monkeypatch):
    app = _desktop_app(monkeypatch, desktop=False)
    app._step_font_size(+1)
    assert app.backend.calls == [] and app._font_size_override is None
    assert "terminal" in app.logged[-1]


def test_reload_keeps_the_size_when_font_size_is_unchanged(monkeypatch):
    app = _desktop_app(monkeypatch)
    app._step_font_size(+1)                # 13 for this run
    app._apply_base_font(_cfg(None, 12), _cfg("Menlo", 12))
    [*_, (kind, font)] = app.backend.calls
    assert (font.family, font.size) == ("Menlo", 13.0)


def test_a_new_font_size_in_config_wins_over_the_adjusted_one(monkeypatch):
    app = _desktop_app(monkeypatch)
    app._step_font_size(+1)
    app._apply_base_font(_cfg(None, 12), _cfg(None, 16))
    assert _sizes(app)[-1] == 16.0
    assert app._font_size_override is None


# -- how the keys read in a menu and the help ---------------------------------

def test_named_punctuation_shows_as_its_glyph():
    # A native menu reads the hint as a key: "Cmd-Minus" or "Cmd-Left_bracket"
    # showed no accelerator at all.
    from xefm.config import KeyBindings
    kb = KeyBindings({})
    assert kb.format_key_for_display("Command-MINUS") == "Cmd--"
    assert kb.format_key_for_display("Command-LEFT_BRACKET") == "Cmd-["
    assert kb.format_key_for_display("Command-RIGHT_BRACKET") == "Cmd-]"
    assert kb.format_key_for_display("Ctrl-COMMA") == "Ctrl-,"
    assert kb.format_key_for_display("Shift-EQUAL") == "Shift-="
