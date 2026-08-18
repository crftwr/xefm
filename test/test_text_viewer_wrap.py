"""Text viewer line wrap over wide (CJK) characters.

Wrap chunks are cut by display columns, not character count: a CJK character
fills two columns, so an 80-char Japanese line must wrap where an 80-char
ASCII line need not (issue #315). See doc/dev/TEXT_VIEWER_SYSTEM.md.

Run with: python -m pytest test/test_text_viewer_wrap.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend
from puikit.text import display_width

from xefm.path import Path
from xefm.text_viewer import show_text_viewer


def _key(name=None, char=None, mods=frozenset()):
    return Event(type=EventType.KEY, key=name, char=char, modifiers=mods)


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=60, height=12, capabilities=request.param)


def _open_wrapped(panel, path):
    v = show_text_viewer(panel, path)
    panel.render()
    panel.dispatch_event(_key("w", "w"))
    panel.render()
    assert v.wrap is True
    return v


def _chunks_for_line(v, line_idx):
    return [(start, end) for (src, start, end) in v._row_map if src == line_idx]


def test_wide_line_wraps_by_display_columns(backend, tmp_path):
    # 40 CJK chars: fits the content width by char count (40 < ~55) but spans 80
    # display columns — the issue #315 shape, where wrap did nothing at all.
    p = tmp_path / "wide.txt"
    p.write_text("あ" * 40 + "\n", encoding="utf-8")
    panel = Panel(backend)
    v = _open_wrapped(panel, Path(str(p)))

    chunks = _chunks_for_line(v, 0)
    assert len(chunks) > 1
    line = v.lines[0]
    for start, end in chunks:
        assert display_width(line[start:end]) <= v._content_w
    # Lossless: the chunks tile the line exactly.
    assert chunks[0][0] == 0
    assert chunks[-1][1] == len(line)
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert prev_end == next_start


def test_ascii_line_chunking_unchanged(backend, tmp_path):
    # ASCII wrap still cuts at exactly content_w chars per row (the old math).
    p = tmp_path / "ascii.txt"
    p.write_text("x" * 130 + "\n", encoding="utf-8")
    panel = Panel(backend)
    v = _open_wrapped(panel, Path(str(p)))

    w = v._content_w
    chunks = _chunks_for_line(v, 0)
    expected = -(-130 // w)  # ceil
    assert len(chunks) == expected
    assert all(end - start == w for start, end in chunks[:-1])
    assert chunks[-1][1] == 130


def test_mixed_width_line_chunks_fit(backend, tmp_path):
    p = tmp_path / "mixed.txt"
    p.write_text(("abcあいうdef漢字ghi" * 12) + "\n", encoding="utf-8")
    panel = Panel(backend)
    v = _open_wrapped(panel, Path(str(p)))

    line = v.lines[0]
    chunks = _chunks_for_line(v, 0)
    assert len(chunks) > 1
    for start, end in chunks:
        assert display_width(line[start:end]) <= v._content_w
    assert "".join(line[s:e] for s, e in chunks) == line


def test_short_lines_stay_single_row(backend, tmp_path):
    p = tmp_path / "short.txt"
    p.write_text("hello\n日本語\n\n", encoding="utf-8")
    panel = Panel(backend)
    v = _open_wrapped(panel, Path(str(p)))
    for i, line in enumerate(v.lines):
        assert _chunks_for_line(v, i) == [(0, len(line))]
