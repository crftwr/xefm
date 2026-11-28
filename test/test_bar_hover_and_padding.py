"""Hand-check follow-ups of #1019: what a bar shows under the pointer, the
path bar's padding, and tabs whose labels sit level in every strip."""

from types import SimpleNamespace

from puikit import Style
from puikit.theme import DEFAULT_THEME


class _Ctx:
    """Just enough of a DrawContext: one unit per character, calls recorded."""

    theme = DEFAULT_THEME
    background = (40, 40, 40)
    base_size = (8, 16)

    def __init__(self, vector=True, over=True):
        self.vector_shapes = vector
        self.over = over
        self.calls = []

    def measure_text(self, text, style=None):
        return float(len(text))

    def pointer_in(self, x, y, w, h):
        return self.over

    def round_rect(self, x, y, w, h, style, radius=0.0, hints=None):
        self.calls.append(("round", x, w))

    def draw_text(self, x, y, text, style):
        self.calls.append(("text", x, text, style.bg))

    def set_cursor(self, shape):
        self.calls.append(("cursor", shape))


def test_a_clickable_part_shows_it_is_one_under_the_pointer():
    from xefm.app import _hover_part
    ctx = _Ctx()
    assert _hover_part(ctx, 4.0, "C copy", Style(fg=(150, 150, 150)))
    kinds = [c[0] for c in ctx.calls]
    assert kinds == ["round", "text", "cursor"] and ("cursor", "pointer") in ctx.calls
    grid = _Ctx(vector=False)
    assert _hover_part(grid, 4.0, "C copy", Style())
    assert grid.calls[0][0] == "text" and grid.calls[0][3] is not None  # its cells
    away = _Ctx(over=False)
    assert not _hover_part(away, 4.0, "C copy", Style()) and away.calls == []


def test_the_path_bar_keeps_its_height():
    from xefm.app import BAR_PAD_PX, PaneHeader
    header = PaneHeader.__new__(PaneHeader)
    tabs = {"left": [object()]}
    header.app = SimpleNamespace(pm=SimpleNamespace(tabs=tabs))
    header.pane_name = "left"
    ctx = SimpleNamespace(snap=False, base_h=16, vector_shapes=True)
    pad = BAR_PAD_PX / 16
    assert header.measure(ctx, "y", 100).preferred == 1.0 + pad  # split, not added
    grid = SimpleNamespace(snap=True, base_h=0, vector_shapes=False)
    assert header.measure(grid, "y", 100).preferred == 1.0


def test_a_tabs_label_sits_the_same_in_every_strip():
    # A strip whose place had a fraction in it showed its labels a pixel low:
    # the OS puts a baseline on a whole pixel, a chip's edge where it falls.
    from xefm.tab_strip import _snap_row
    offsets = set()
    for top in (0.0, 2.37, 3.81, 5.5):
        ctx = SimpleNamespace(vector_shapes=True, base_size=(8, 16),
                              screen_rect=(0.0, top, 50.0, 2.0),
                              font_metrics=lambda: SimpleNamespace(ascent=0.79))
        y, h, ty = _snap_row(ctx, 0.25, 1.3)
        chip_top = (top + y) * 16
        baseline = (top + ty) * 16 + 0.79 * 16
        assert abs(chip_top - round(chip_top)) < 1e-6
        assert abs(baseline - round(baseline)) < 1e-6
        offsets.add(round(baseline - chip_top))
    assert len(offsets) == 1


def test_on_every_theme_the_hover_backing_shows_on_its_bar():
    # A fixed mix of bar and text was lost on a theme whose bar and text sit
    # close, or whose bars are translucent over a scene (#1019 hand check).
    from xefm._config import Config
    from xefm.app import _build_theme_list
    from xefm.tab_strip import HOVER_SEPARATION, _lightness as L, _mix, hover_backing
    for name, theme in _build_theme_list(Config()):
        opacity = theme.extras.get("opacity", 1.0)
        page = theme.surface_bg("content")
        for role in ("status", "footer"):
            bar = theme.surface_bg(role) or page
            backing = hover_backing(theme, bar, opacity)
            seen = _mix(page, bar, opacity) if opacity < 1.0 else tuple(bar)[:3]
            assert abs(L(backing) - L(seen)) >= HOVER_SEPARATION - 0.01, (name, role)


def test_a_drawn_conversations_status_parts_run_what_their_keys_do():
    # Laid out and clicked as the file manager's hints (#1019 hand check).
    from xefm import agent_chat as C
    from xefm.agent_chat_view import ChatView
    view = ChatView.__new__(ChatView)
    view._pixel_layout = True
    ran = []
    view.conversation = SimpleNamespace(state=C.WORKING)
    view.interrupt = lambda: ran.append("stop")
    parts = view.status_parts
    assert [t for t, _r in parts] == ["Esc stop", "Enter send next", "PgUp/PgDn scroll"]
    dict(parts)["Esc stop"]()
    assert ran == ["stop"] and dict(parts)["PgUp/PgDn scroll"] is None
    assert view.status_hint == "Esc stop · Enter send next · PgUp/PgDn scroll"


def test_a_click_on_a_sessions_part_runs_it():
    from xefm.app import StatusBar
    bar = StatusBar.__new__(StatusBar)
    ran = []
    bar._hits = [(0.0, 5.0, lambda: ran.append("x")), (6.0, 9.0, "help")]
    bar.app = SimpleNamespace(panel=SimpleNamespace(render=lambda: None),
                              _run_action=lambda ctx, a: ran.append(a))
    bar._clip_hit = bar._jobs_hit = None
    assert bar.click_at(2.0) and bar.click_at(7.0)
    assert ran == ["x", "help"]


def test_a_name_in_the_path_lights_up_under_the_pointer():
    from xefm.app import _hover_part
    ctx = _Ctx()
    assert _hover_part(ctx, 3.0, "projects", Style(), y=0.5)
    assert ctx.calls[0][0] == "round"
