"""Key hints are drawn and clicked one way everywhere (xefm.hint_bar, #1019
follow-up): the file manager's status bar, a session's screen, a viewer's
status bar and a dialog's hint band."""

from puikit import Style
from puikit.backend import TextAttribute
from puikit.event import Event, EventType
from puikit.theme import DEFAULT_THEME

from xefm.hint_bar import (GAP, Hint, Key, click_hint, draw_hints, hints_text,
                           hints_width, key, note)


def _keys(hint):
    return [(k.text, k.press) for k in hint.keys]


# --- the parts ------------------------------------------------------------------


def test_a_part_names_one_key_a_pair_or_an_arrow_cluster():
    assert _keys(key("Shift-Tab", "mode")) == [("Shift-Tab", "")]
    assert _keys(key("q/Esc", "close")) == [("q", ""), ("Esc", "")]
    assert _keys(key("n/Shift-N", "jump")) == [("n", ""), ("Shift-N", "")]
    assert _keys(key("+/-", "zoom")) == [("+", ""), ("-", "")]
    assert _keys(key("[/]", "resize")) == [("[", ""), ("]", "")]
    # A cluster's shared modifier reads with the first arrow, holds for all.
    assert _keys(key("Shift-↑↓←→", "pan")) == [
        ("Shift-↑", "Shift-↑"), ("↓", "Shift-↓"), ("←", "Shift-←"), ("→", "Shift-→")]
    assert key("/", "commands").keys == (Key("/"),)
    assert key("", "nothing") == note("nothing")


def test_the_plain_text_form_puts_the_parts_two_cells_apart():
    line = [note("12 rows"), key("q/Esc", "close"), key("↑↓", "scroll")]
    assert hints_text(line) == "12 rows  q/Esc close  ↑↓ scroll"
    assert hints_width(line, len) >= len("12 rows") + len("q/Esc close") \
        + len("↑↓ scroll") + 2 * GAP


# --- drawing --------------------------------------------------------------------


class _Ctx:
    """Just enough of a DrawContext: one unit per character; texts recorded."""

    theme = DEFAULT_THEME
    background = None
    base_size = (8, 16)

    def __init__(self, vector=False, over=None):
        self.vector_shapes = vector
        self.over = over  # the x the pointer is at, or None
        self.texts = []

    def measure_text(self, text, style=None):
        return float(len(text))

    def pointer_in(self, x, y, w, h):
        return self.over is not None and x <= self.over < x + w

    def draw_text(self, x, y, text, style):
        self.texts.append((x, text, style))

    def round_rect(self, *a, **kw):
        pass

    def set_cursor(self, shape):
        pass


MUTED = Style(fg=(120, 120, 120))


def test_a_parts_key_stands_out_from_its_words():
    ctx = _Ctx(vector=True)
    draw_hints(ctx, 0.0, 0.0, [key("Enter", "choose"), key("Esc", "cancel")],
               avail=80.0, muted=MUTED)
    drawn = [(x, t, s.fg == MUTED.fg, bool(s.attr & TextAttribute.BOLD))
             for x, t, s in ctx.texts]
    assert drawn == [(0.0, "Enter", False, True), (5.0, " choose", True, False),
                     (12.0 + GAP, "Esc", False, True), (15.0 + GAP, " cancel", True, False)]
    # On a grid the colour alone sets the key apart.
    grid = _Ctx()
    draw_hints(grid, 0.0, 0.0, [key("Enter", "choose")], avail=80.0, muted=MUTED)
    assert not grid.texts[0][2].attr & TextAttribute.BOLD
    assert grid.texts[0][2].fg != MUTED.fg


def test_a_part_that_does_not_fit_is_cut_and_ends_the_line():
    ctx = _Ctx()
    hits = draw_hints(ctx, 0.0, 0.0, [key("Enter", "choose"), key("Esc", "cancel"),
                                      key("Tab", "next")], avail=18.0, muted=MUTED)
    texts = [t for _x, t, _s in ctx.texts]
    assert texts[:2] == ["Enter", " choose"]
    assert texts[-1].endswith("…") and "Tab" not in texts
    assert len(hits) == 1  # the cut part is no target


def test_a_note_is_no_target_and_a_plain_string_is_drawn_whole():
    ctx = _Ctx()
    assert draw_hints(ctx, 0.0, 0.0, [note("12 rows")], avail=80.0, muted=MUTED) == []
    assert draw_hints(ctx, 0.0, 0.0, "Jump to: ab", avail=80.0, muted=MUTED) == []
    assert ctx.texts[-1][1] == "Jump to: ab"


# --- clicking -------------------------------------------------------------------


class _Widget:
    def __init__(self):
        self.keys = []

    def handle_event(self, event):
        self.keys.append((event.key, tuple(sorted(event.modifiers))))
        return True


def _click(x, y=0.0, kind=EventType.MOUSE_CLICK, button="left"):
    return Event(type=kind, x=x, y=y, button=button)


def test_a_click_presses_the_key_a_part_names():
    line = [key("↑/↓", "select"), key("Enter", "choose"), key("Shift-↑↓", "pan")]
    hits = draw_hints(_Ctx(), 2.0, 9.0, line, avail=80.0, muted=MUTED)
    widget = _Widget()
    # "↑/↓ select" is 2..12; the gap; "Enter choose" from 14.
    assert click_hint(widget, hits, _click(15.0, 9.5))
    assert click_hint(widget, hits, _click(4.2, 9.0))  # ↓
    pan = 14.0 + len("Enter choose") + GAP
    assert click_hint(widget, hits, _click(pan + len("Shift-↑") + 0.5, 9.0))
    assert widget.keys == [("enter", ()), ("down", ()), ("down", ("shift",))]
    # The press and release on a target are the hint's, and press nothing.
    assert click_hint(widget, hits, _click(15.0, 9.0, EventType.MOUSE_DOWN))
    assert click_hint(widget, hits, _click(15.0, 9.0, button="right"))
    assert len(widget.keys) == 3
    # Off the targets - the words after a pair, the gap, another row - not.
    assert not click_hint(widget, hits, _click(8.0, 9.0))
    assert not click_hint(widget, hits, _click(12.5, 9.0))
    assert not click_hint(widget, hits, _click(15.0, 8.0))


def test_a_part_with_a_run_of_its_own_runs_it():
    ran = []
    hits = draw_hints(_Ctx(), 0.0, 0.0, [key("C", "copy", lambda: ran.append("copy"))],
                      avail=80.0, muted=MUTED)
    widget = _Widget()
    assert click_hint(widget, hits, _click(3.0))
    assert ran == ["copy"] and widget.keys == []


def test_a_target_lights_up_whole_under_the_pointer():
    ctx = _Ctx(over=8.0)
    draw_hints(ctx, 0.0, 0.0, [key("Enter", "choose")], avail=80.0, muted=MUTED)
    # Drawn, then drawn again over the backing: the key and its words both.
    assert [t for _x, t, _s in ctx.texts] == ["Enter", " choose", "Enter", " choose"]


def test_a_dialogs_hint_click_answers_as_its_key_does():
    from xefm.input_dialog import InputDialog
    results = []
    dialog = InputDialog(title="Rename", text="a.txt",
                         on_cancel=lambda: results.append("cancel"))
    dialog._hint_hits = draw_hints(_Ctx(), 2.0, 5.0, dialog.hint(), avail=80.0,
                                   muted=MUTED)
    x = 2.0 + len("Enter accept") + GAP + 1
    assert dialog.handle_event(_click(x, 5.0))
    assert results == ["cancel"]  # Esc cancel


def test_every_bar_builds_its_line_from_parts():
    # The viewers' and dialogs' lines are parts, not strings to read back.
    from xefm.sort_dialog import SortDialog
    from xefm.tips_dialog import TipsDialog
    for line in (SortDialog._HINT, TipsDialog._HINT):
        assert all(isinstance(h, Hint) for h in line)
