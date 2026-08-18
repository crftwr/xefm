"""Full-window modal viewers pad like the main window's chrome: each bar's
surface fills the window edge to edge, and only the *text* (and the scrolling
body) is inset by VIEWER_PAD_PX — not a bordered card around the whole viewer.

The MemoryBackend renders as a grid (no sub-cell), where the inset collapses to
flush; the GUI inset path is driven here with a minimal vector-reporting draw
context that records where things land.
"""

import os
import sys
import tempfile
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm.text_viewer import (  # noqa: E402
    TextViewer, viewer_pad, draw_status_bar, _header_bg, _content_bg, VIEWER_PAD_PX,
)
from xefm.diff_viewer import DiffViewer, _DiffPane  # noqa: E402
from xefm.directory_diff_viewer import DirectoryDiffView, _GUTTER_W  # noqa: E402
from xefm.file_pane import CONTENT_PAD_CELLS  # noqa: E402

PX, PY = VIEWER_PAD_PX / 8, VIEWER_PAD_PX / 16  # inset for an 8x16px base cell

_CONTENT = (30, 30, 30)
_HEADER = (73, 73, 76)
_STATUS = (0, 122, 204)


class _FakeTheme:
    """Minimal theme exposing distinct surface roles, so the header band's color
    can be told apart from the content background in a headless test."""

    text = (200, 200, 200)
    muted_text = (150, 150, 150)
    accent = (0, 122, 204)
    popup_bg = (37, 37, 38)
    extras = {}
    surfaces = {"content": _CONTENT, "header": _HEADER, "status": _STATUS}

    def surface_bg(self, role):
        return self.surfaces.get(role)

    def __getattr__(self, name):  # misc getattr(theme, x, default) probes
        return None


class _GuiCtx:
    """A vector (GUI) draw context stand-in: 8px-wide, 16px-tall base cells. It
    records fills / texts / children / scrollbars where they land."""

    vector_shapes = True
    base_size = (8, 16)
    wallpaper = False   # no animated/image background: the viewer fills its page

    def __init__(self, w, h):
        self.size_units = (w, h)
        self.width = int(w)
        self.height = int(h)
        self.panel = None
        self.theme = None
        self.fills = []
        self.styled_fills = []   # (x, y, w, h, bg)
        self.texts = []
        self.kids = []
        self.bars = []

    def measure_text(self, t, style=None):
        return float(len(t))

    def fill_rect(self, x, y, w, h, style=None):
        rect = (round(x, 3), round(y, 3), round(w, 3), round(h, 3))
        self.fills.append(rect)
        self.styled_fills.append(rect + (getattr(style, "bg", None),))

    def draw_text(self, x, y, t, style=None, **kw):
        self.texts.append((round(x, 3), round(y, 3), t))

    def draw_child(self, widget, x, y, w, h, **kw):
        self.kids.append((round(x, 3), round(y, 3), round(w, 3), round(h, 3)))

    def draw_scrollbar(self, x, y, h, pos, ratio, style=None, **kw):
        self.bars.append((round(x, 3), round(y, 3)))

    def set_cursor(self, *a, **kw):
        pass

    def screen_rect(self):
        return (0, 0, 0, 0)


class _GridCtx(_GuiCtx):
    vector_shapes = False


def test_viewer_pad_gui_and_grid():
    assert viewer_pad(_GuiCtx(200, 100)) == (PX, PY)
    assert viewer_pad(_GridCtx(200, 100)) == (0.0, 0.0)


def test_draw_status_bar_fills_full_width_insets_text():
    # The status surface spans the full window and reaches the bottom edge
    # (bottom_pad extra height); only the text is inset.
    ctx = _GuiCtx(200.0, 100.0)
    draw_status_bar(ctx, 98.75, "hello", pad_x=PX, bottom_pad=PY)
    assert (0.0, 98.75, 200.0, 1.0 + PY) in ctx.fills   # edge to edge, reaches hu
    assert any(t[0] == PX and t[1] == 98.75 for t in ctx.texts)  # text inset


def test_text_viewer_header_and_footer_are_full_width_with_inset_text():
    d = tempfile.mkdtemp()
    p = Path(d) / "f.txt"
    p.write_text("\n".join(f"line{i}" for i in range(200)))
    ctx = _GuiCtx(200.0, 100.0)
    TextViewer(p).draw(ctx)
    fy = 100.0 - 1.0 - PY
    # Header text inset from the top-left; body child inset below the header.
    assert (PX, PY) == ctx.texts[0][:2]
    assert ctx.kids[0][:2] == (PX, 1.0 + PY)
    # Footer surface full width to the bottom, text inset.
    assert (0.0, fy, 200.0, 1.0 + PY) in ctx.fills
    assert any(t[0] == PX and t[1] == fy for t in ctx.texts)


def test_diff_viewer_footer_full_width_panes_inset():
    d = tempfile.mkdtemp()
    a = Path(d) / "a.txt"; a.write_text("\n".join(f"a{i}" for i in range(300)))
    b = Path(d) / "b.txt"; b.write_text("\n".join(f"b{i}" for i in range(300)))
    ctx = _GuiCtx(200.0, 100.0)
    DiffViewer(a, b).draw(ctx)
    fy = 100.0 - 1.0 - PY
    # The two-pane splitter is inset from top/left; footer surface fills full width.
    assert ctx.kids[0][:2] == (PX, PY)
    assert (0.0, fy, 200.0, 1.0 + PY) in ctx.fills
    assert any(t[0] == PX and t[1] == fy for t in ctx.texts)


def test_header_bg_is_the_distinct_header_surface():
    th = _FakeTheme()
    assert _header_bg(th) == _HEADER
    assert _header_bg(th) != _content_bg(th)


def _header_band_bg(ctx):
    """The bg of the full-width band that reaches the top edge (y=0, w=window)."""
    for x, y, w, h, bg in ctx.styled_fills:
        if x == 0.0 and y == 0.0 and w == 200.0 and 0.0 < h <= 1.0 + PY + 1e-6:
            return bg
    return None


def test_all_viewers_paint_a_distinct_header_band():
    d = tempfile.mkdtemp()
    p = Path(d) / "f.txt"; p.write_text("x\ny\n")
    a = Path(d) / "a.txt"; a.write_text("a\nb\n")
    bb = Path(d) / "b.txt"; bb.write_text("a\nc\n")
    ld = Path(d) / "L"; ld.mkdir()
    rd = Path(d) / "R"; rd.mkdir()
    for viewer in (TextViewer(p), DiffViewer(a, bb),
                   DirectoryDiffView(ld, rd, background=False)):
        ctx = _GuiCtx(200.0, 100.0)
        ctx.theme = _FakeTheme()
        viewer.draw(ctx)
        band = _header_band_bg(ctx)
        assert band == _HEADER, f"{type(viewer).__name__}: header band {band} != {_HEADER}"


class _WallpaperCtx(_GuiCtx):
    """A GUI context over an animated / image background (ctx.wallpaper)."""

    wallpaper = True


def _page_fills(ctx):
    """Fills covering the whole window in the content surface — the viewer's page."""
    return [f for f in ctx.styled_fills
            if f[:4] == (0.0, 0.0, 200.0, 100.0) and f[4] == _CONTENT]


def test_viewers_drop_the_page_fill_over_a_wallpaper():
    # A full-window viewer replaces the file panes, which are transparent over a
    # wallpaper — so it must be too, or the background animation dims to the theme's
    # surface opacity the moment a viewer opens. Same viewer, two contexts: only the
    # wallpaper decides. Without one the page is filled as before.
    d = tempfile.mkdtemp()
    p = Path(d) / "f.txt"; p.write_text("x\ny\n")
    a = Path(d) / "a.txt"; a.write_text("a\nb\n")
    bb = Path(d) / "b.txt"; bb.write_text("a\nc\n")
    ld = Path(d) / "L"; ld.mkdir()
    rd = Path(d) / "R"; rd.mkdir()
    for viewer in (TextViewer(p), DiffViewer(a, bb),
                   DirectoryDiffView(ld, rd, background=False)):
        name = type(viewer).__name__
        plain = _GuiCtx(200.0, 100.0); plain.theme = _FakeTheme()
        viewer.draw(plain)
        assert len(_page_fills(plain)) == 1, f"{name}: no wallpaper -> fills its page"

        over_bg = _WallpaperCtx(200.0, 100.0); over_bg.theme = _FakeTheme()
        viewer.draw(over_bg)
        assert _page_fills(over_bg) == [], f"{name}: over a wallpaper -> transparent"
        # Only the page goes: the chrome bands still paint (they dissolve at the
        # theme's surface opacity, like the main window's header / status bars).
        assert _header_band_bg(over_bg) == _HEADER, f"{name}: header band dropped too"


def test_text_viewer_draws_rows_to_cover_fractional_bottom():
    # With a fractional body height (the l/r-padded viewer rarely lands on a whole
    # cell) plus a fractional scroll offset, the bottom partial row must still be
    # drawn to be clipped — not vanish early (only one extra row would gap it).
    d = tempfile.mkdtemp()
    p = Path(d) / "f.txt"
    p.write_text("\n".join(f"line{i}" for i in range(300)))
    v = TextViewer(p)
    v.draw(_GuiCtx(200.0, 100.0))     # establishes _view_h / content geometry
    v.top = 5.7                        # scroll fraction (0.7) that exposes the gap
    ys = []
    v._draw_line = lambda ctx, y, li, c0, end=None: ys.append(y)  # record each row's top y
    v._draw_rows(_GuiCtx(200.0, 100.0))
    body_h = (100.0 - 1.0 - PY) - (1.0 + PY)   # fy - head_h (no h-scrollbar)
    # The union of drawn rows must reach the body's bottom clip; the last row's
    # bottom edge is max(top y) + 1.
    assert max(ys) + 1.0 >= body_h
    assert len(ys) == v._view_h + 2


def test_diff_pane_insets_rows_from_edges_like_the_main_panes():
    # The diff panes inset their gutter + content by CONTENT_PAD_CELLS on both
    # edges (the same amount the main file panes use), so rows don't butt the
    # pane edge — most visibly the shared splitter between the two panes.
    d = tempfile.mkdtemp()
    a = Path(d) / "a.txt"; a.write_text("\n".join("x" * 40 for _ in range(50)))
    b = Path(d) / "b.txt"; b.write_text("\n".join("y" * 40 for _ in range(50)))
    v = DiffViewer(a, b)
    gutter = v._gutter_w()
    ctx = _GuiCtx(60.0, 40.0)

    left = _DiffPane(v, "l"); left.draw(ctx)
    assert left._pad == CONTENT_PAD_CELLS
    assert left._content_x == CONTENT_PAD_CELLS + gutter          # gutter inset from the left
    assert left._content_x + left._content_w <= 60 - CONTENT_PAD_CELLS + 1e-9  # inset on the right

    right = _DiffPane(v, "r"); right.draw(ctx)   # reserves one column for the scrollbar
    assert right._content_x == CONTENT_PAD_CELLS + gutter
    assert right._content_x + right._content_w <= 60 - 1 - CONTENT_PAD_CELLS + 1e-9

    # On a character grid there is no sub-cell inset (matches the main panes).
    grid = _GridCtx(60.0, 40.0)
    left.draw(grid)
    assert left._pad == 0.0 and left._content_x == gutter


def test_text_viewer_draws_columns_to_cover_fractional_right_edge():
    # Horizontal analog of the row-coverage fix: a fractional visible width plus a
    # fractional pan offset must still draw the partial right-edge column, so
    # characters don't vanish early while scrolling out at the right.
    d = tempfile.mkdtemp()
    p = Path(d) / "f.txt"
    p.write_text("".join(chr(65 + (i % 26)) for i in range(300)) + "\n")  # one long line
    v = TextViewer(p)
    v.draw(_GuiCtx(100.3, 40.0))          # fractional width -> fractional content width
    xs = []

    class _Rec(_GuiCtx):
        def draw_text(self, x, y, t, style=None, **kw):
            if t.strip():
                xs.append(x + len(t))     # right edge of this drawn run

    # Pan fraction 0.9: with the content width's own fraction (~0.3) this pushes
    # the visible span two whole columns past the count — the case the old single
    # extra column missed.
    v._draw_line(_Rec(100.3, 40.0), 0.0, 0, 5.9)
    iw = 100.3 - 2 * PX
    right_edge = v._content_x + (iw - v._gutter - 1)   # visible content right edge
    assert max(xs) >= right_edge - 1e-6


def test_dir_diff_viewer_bars_full_width_text_inset_and_hit_testing():
    d = tempfile.mkdtemp()
    ld = Path(d) / "L"; ld.mkdir()
    rd = Path(d) / "R"; rd.mkdir()
    v = DirectoryDiffView(ld, rd, background=False)
    ctx = _GuiCtx(200.0, 100.0)
    v.draw(ctx)
    head_h = 1.0 + PY
    fy = 100.0 - 1.0 - PY
    # Header bar surface reaches the top edge and is full width; text inset.
    assert (0.0, 0.0, 200.0, head_h) in ctx.fills
    assert any(t[0] == PX and t[1] == PY for t in ctx.texts)
    # Footer surface full width to the bottom; text inset.
    assert (0.0, fy, 200.0, 1.0 + PY) in ctx.fills
    assert any(t[0] == PX and t[1] == fy for t in ctx.texts)
    # The l/r pad is baked into the column geometry (events stay window-space).
    assert v._left_x == PX
    assert v._avail == 200.0 - _GUTTER_W - 2 * PX
    # A click above the header row (in the top pad) is not a row hit.
    assert v._row_at(PY) is None
    # The left header column starts at the inset, not the window edge.
    assert v._side_at(PX + 1) == "left"
    assert v._side_at(0.0) is None
