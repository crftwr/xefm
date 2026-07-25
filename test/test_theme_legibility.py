"""Proof that Layer-3 auto-ink guarantees legibility across all 7 XeFM themes.

For every place text actually paints (file rows, columns, headers, footers,
status bar), we take the *intended* semantic ink (accent for directories, text
for files, muted for columns) and the background it lands on, then run it
through ``legible_ink``. The claim under test:

  wherever the background has the physical headroom, auto-ink lifts the ink to
  its APCA target in every theme — no per-theme, per-widget color tuning.

Where it can't, we prove the invariant that matters: auto-ink only ever falls
short because the *background* physically can't reach the target (a low-headroom
accent bar, or a light theme's accent-tinted selection fill) — never because a
better foreground existed. That residue is the theme-recipe layer's job.

Run just this file:  python -m pytest test/test_theme_legibility.py -v
Print the report:    python test/test_theme_legibility.py
"""

import pytest

from puikit.color import (
    LC_BODY,
    LC_LARGE,
    apca_lc,
    ensure_text_headroom,
    legible_ink,
    max_achievable_lc,
)
from puikit.theme import derive_theme

# The 7 palettes, mirroring xefm/app.py THEMES (kept inline so the proof does not
# import the whole app). background, foreground, muted, accent, surface, selection.
PALETTES = {
    "Dark+":           ((30, 30, 30),    (212, 212, 212), (157, 157, 157), (0, 122, 204),   (48, 48, 52),    (10, 105, 178)),
    "Monokai":         ((39, 40, 34),    (248, 248, 242), (140, 140, 130), (166, 226, 46),  (56, 57, 48),    (86, 122, 38)),
    "Dracula":         ((40, 42, 54),    (248, 248, 242), (98, 114, 164),  (189, 147, 249), (56, 59, 76),    (120, 86, 175)),
    "Nord":            ((46, 52, 64),    (216, 222, 233), (76, 86, 106),   (136, 192, 208), (62, 70, 88),    (76, 128, 158)),
    "Solarized":       ((0, 43, 54),     (147, 161, 161), (88, 110, 117),  (38, 139, 210),  (10, 62, 78),    (26, 102, 150)),
    "Light+":          ((255, 255, 255), (30, 30, 30),    (110, 110, 110), (0, 122, 204),   (235, 235, 238), (120, 180, 240)),
    "Solarized Light": ((253, 246, 227), (88, 110, 117),  (147, 161, 161), (38, 139, 210),  (234, 228, 206), (150, 195, 230)),
}

SELECT_MIX_ACTIVE = 0.42  # from xefm/file_pane.py


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rendered_pairs(name):
    """Yield (label, ink, background, target_lc) for every text-on-surface pair
    a pane paints, for one theme — faithful to the production draw code."""
    bg, fg, muted, accent, surface, selection = PALETTES[name]
    t = derive_theme(background=bg, foreground=fg, muted=muted,
                     accent=accent, surface=surface, selection=selection)
    content = t.surfaces["content"]
    header = t.surfaces["header"]
    status = t.surfaces["status"]              # accent, deepened for headroom
    # Selection fill as FilePane paints it: the accent tint, then the same
    # recipe nudge back toward the background that keeps it text-bearing.
    sel = ensure_text_headroom(_mix(content, t.accent, SELECT_MIX_ACTIVE), content, LC_BODY)
    return [
        ("dir name",            t.accent,     content, LC_BODY),
        ("dir name (selected)", t.accent,     sel,     LC_BODY),
        ("file name",           t.text,       content, LC_BODY),
        ("file name (selected)",t.text,       sel,     LC_BODY),
        ("size/date column",    t.muted_text, content, LC_LARGE),
        ("active header path",  t.accent,     header,  LC_LARGE),
        ("inactive header path",t.text,       header,  LC_LARGE),
        ("active footer",       t.text,       status,  LC_LARGE),
        ("inactive footer",     t.muted_text, status,  LC_LARGE),
        ("status bar hints",    t.muted_text, status,  LC_LARGE),
    ]


def _has_headroom(bg, target):
    return max_achievable_lc(bg) >= target


# --- Layer-3 guarantee --------------------------------------------------------
@pytest.mark.parametrize("theme", list(PALETTES))
def test_auto_ink_reaches_target_wherever_background_allows(theme):
    for label, ink, bg, target in _rendered_pairs(theme):
        if not _has_headroom(bg, target):
            continue  # recipe-blocked; covered by the boundary test below
        fixed = legible_ink(ink, bg, target)
        lc = abs(apca_lc(fixed, bg))
        assert lc >= target - 0.5, f"{theme} / {label}: got Lc {lc:.1f}, need {target}"


# --- Layer 2 closes the residue: every rendered pair is now legible -----------
def test_every_rendered_pair_is_legible_on_every_theme():
    # With the recipe layer in place — the status surface deepened for headroom
    # (derive_theme) and the selection fill nudged back toward the background
    # (FilePane) — the residue auto-ink alone could not reach is gone: every text
    # pair the panes paint clears its target on all seven themes.
    residue = []
    for theme in PALETTES:
        for label, ink, bg, target in _rendered_pairs(theme):
            reached = abs(apca_lc(legible_ink(ink, bg, target), bg))
            if reached < target - 0.5:
                residue.append((theme, label, round(reached, 1), target))
    assert residue == [], residue


def test_recipe_only_deepens_low_headroom_surfaces():
    # The recipe is floor-only: it changes a theme's status surface only when the
    # raw accent can't bear chrome text (Dracula), and leaves the vivid accents
    # (blue/green/cyan) exactly as the accent. Same idea for selection fills.
    for name, (bg, fg, muted, accent, surface, selection) in PALETTES.items():
        t = derive_theme(background=bg, foreground=fg, muted=muted,
                         accent=accent, surface=surface, selection=selection)
        status = t.surfaces["status"]
        if max_achievable_lc(accent) >= LC_LARGE + 3:
            assert status == accent, (name, status)          # untouched
        else:
            assert status != accent and max_achievable_lc(status) >= LC_LARGE
    # Dracula is the one theme whose accent needed deepening.
    drac = derive_theme(background=(40, 42, 54), foreground=(248, 248, 242),
                        muted=(98, 114, 164), accent=(189, 147, 249),
                        surface=(56, 59, 76), selection=(120, 86, 175))
    assert drac.surfaces["status"] != (189, 147, 249)


# --- end-to-end: the wiring reaches the screen --------------------------------
def test_render_lifts_directory_and_keeps_legible_file():
    """Render a real FilePane through a Panel and read back the fg that reached
    the cells: the directory name (colored from the theme's ``extras['directory']``)
    is lifted off its dim raw value, while an already-legible file name is left
    exactly as the theme declared it."""
    from puikit import Item, Panel, VSplit
    from puikit.backends.memory_backend import MemoryBackend
    from xefm.file_pane import FilePane

    bg, fg, muted, accent, surface, selection = PALETTES["Dark+"]
    # Give the theme a deliberately dim directory color (the accent, invisible at
    # raw value on the content surface) so this exercises both the extras['directory']
    # wiring and the readability lift.
    theme = derive_theme(background=bg, foreground=fg, muted=muted,
                         accent=accent, surface=surface, selection=selection,
                         extras={"directory": accent})

    class _Entry:
        def __init__(self, name, is_dir):
            self.name, self._d = name, is_dir

        def is_dir(self):
            return self._d

        def __str__(self):
            return "/x/" + self.name

    d, f = _Entry("mydir", True), _Entry("myfile.txt", False)
    pane = {
        "files": [d, f],
        "file_info": {str(d): {"size_str": "<DIR>", "date_str": "", "is_dir": True},
                      str(f): {"size_str": "1.0K", "date_str": "", "is_dir": False}},
        "virtual": None, "selected_files": set(), "focused_index": 1,  # cursor on file
    }
    backend = MemoryBackend(width=40, height=8)
    panel = Panel(backend, theme=theme)
    panel.set_layout(VSplit(Item(FilePane(pane), hints={"surface": "content"})))
    panel.render()

    content = theme.surfaces["content"]
    # Row 0 = directory (not the cursor row): its accent name, invisible at raw
    # value, is lifted to the body target — and to exactly what legible_ink gives.
    r0 = backend.snapshot()[0]
    dir_fg = backend.style_at(next(i for i, c in enumerate(r0) if c.isalpha()), 0).fg
    assert dir_fg != theme.accent
    assert dir_fg == legible_ink(theme.accent, content, LC_BODY)
    assert abs(apca_lc(dir_fg, content)) >= LC_BODY - 0.5

    # Row 1 = file name (already legible): floor-only leaves theme.text untouched.
    r1 = backend.snapshot()[1]
    file_fg = backend.style_at(next(i for i, c in enumerate(r1) if c.isalpha()), 1).fg
    assert file_fg == theme.text


def test_selection_fill_override_pins_the_selected_row_bg():
    """A theme's ``extras['selection_fill']`` is used verbatim as the selected-row
    background on the active pane — the two-colour escape hatch — instead of the
    accent-tinted, legibility-corrected default (which corrects itself invisible)."""
    from puikit import Item, Panel, VSplit
    from puikit.backends.memory_backend import MemoryBackend
    from xefm.file_pane import FilePane

    bg, fg, muted, accent, surface, selection = PALETTES["Light+"]
    sel_fill = (70, 100, 58)
    theme = derive_theme(background=bg, foreground=fg, muted=muted, accent=accent,
                         surface=surface, selection=selection,
                         extras={"selection_fill": sel_fill})

    class _Entry:
        def __init__(self, name):
            self.name = name

        def is_dir(self):
            return False

        def __str__(self):
            return "/x/" + self.name

    f = _Entry("picked.txt")
    pane = {
        "files": [f],
        "file_info": {str(f): {"size_str": "1.0K", "date_str": "", "is_dir": False}},
        "virtual": None, "selected_files": {str(f)}, "focused_index": 0,
    }
    backend = MemoryBackend(width=40, height=8)
    panel = Panel(backend, theme=theme)
    fp = FilePane(pane)
    fp.active = True  # active pane uses the pinned fill verbatim
    panel.set_layout(VSplit(Item(fp, hints={"surface": "content"})))
    panel.render()

    r0 = backend.snapshot()[0]
    x = next(i for i, c in enumerate(r0) if c.isalpha())
    assert backend.style_at(x, 0).bg == sel_fill


def test_log_message_lifted_on_light_theme():
    """XeFM's own log lines now resolve to ``theme.text`` at draw time (see
    ``log_info``), but a widget can still hand the log a fixed RGB style with no
    theme in reach — e.g. XeFM's stderr warning red. Under auto_ink such a fixed,
    theme-blind color, laid on the light theme's white content, is lifted to
    legibility on render."""
    from puikit import Item, Panel, Style, VSplit
    from puikit.backends.memory_backend import MemoryBackend
    from puikit.widgets import LogView

    bg, fg, muted, accent, surface, selection = PALETTES["Light+"]
    theme = derive_theme(background=bg, foreground=fg, muted=muted,
                         accent=accent, surface=surface, selection=selection)
    content = theme.surfaces["content"]          # white
    fixed_fg = (150, 160, 170)                   # a fixed low-contrast, theme-blind style

    log = LogView(max_lines=50, auto_scroll=True, wrap=True)
    log.append("stderr line here", Style(fg=fixed_fg))
    backend = MemoryBackend(width=40, height=6)
    panel = Panel(backend, theme=theme)
    panel.auto_ink = True
    panel.set_layout(VSplit(Item(log, hints={"surface": "content"})))
    panel.render()

    rows = backend.snapshot()
    ry = next(i for i, r in enumerate(rows) if "stderr" in r)
    drawn = backend.style_at(rows[ry].index("s"), ry).fg
    assert drawn != fixed_fg
    assert drawn == legible_ink(fixed_fg, content, LC_BODY)
    assert abs(apca_lc(drawn, content)) >= LC_BODY - 0.5


# --- human-readable before/after report ---------------------------------------
def _report():
    def bar(lc, target):
        return "ok " if lc >= target - 0.5 else "LOW"
    print(f"\n{'theme':<16}{'element':<22}{'before':>7}{'after':>7}{'target':>7}  verdict")
    print("-" * 70)
    for theme in PALETTES:
        for label, ink, bg, target in _rendered_pairs(theme):
            before = abs(apca_lc(ink, bg))
            if _has_headroom(bg, target):
                fixed = legible_ink(ink, bg, target)
                after = abs(apca_lc(fixed, bg))
                verdict = "kept" if fixed == tuple(ink) else "lifted"
                verdict += "" if after >= target - 0.5 else " !!"
            else:
                after = max_achievable_lc(bg)
                verdict = f"RECIPE-BLOCKED (ceiling {after:.0f})"
            print(f"{theme:<16}{label:<22}{before:>7.1f}{after:>7.1f}{target:>7.0f}  {verdict}")
        print()


if __name__ == "__main__":
    _report()
