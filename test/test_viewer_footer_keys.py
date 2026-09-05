"""Viewer footers name the keys that are actually bound (issue #382).

Every modal viewer draws a status bar of key hints. Most of those hints were
already read from the live keymap; the navigation ones — the text viewer's
``↑↓ scroll``, the diff viewers' ``n/N jump``, the image viewer's ``+/- zoom``
— were literals, so rebinding e.g. ``text_viewer.scroll_down`` changed the help
dialog and left the footer advertising a key that no longer scrolled.

These tests pin both ends: the shared label helpers in xefm/text_viewer.py, and
each viewer's own footer text under a rebind.

Run with: python -m pytest test/test_viewer_footer_keys.py -v
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm._config import Config as DefaultConfig
from xefm.actions import FILE_DIFF, IMAGE_VIEWER, TEXT_VIEWER
from xefm.config import config_manager
from xefm.directory_diff_viewer import DirectoryDiffView
from xefm.path import Path
from xefm.text_viewer import TextViewer, footer_key, footer_pair


@pytest.fixture(autouse=True)
def shipped_config(monkeypatch):
    """Resolve bindings from xefm/_config.py, not from the developer's own
    ~/.xefm/config.py — these assert on XeFM's defaults."""
    monkeypatch.setattr(config_manager, "config", DefaultConfig())
    monkeypatch.setattr(config_manager, "_key_bindings", None)


def rebind(monkeypatch, **actions):
    """Install a config whose KEY_BINDINGS carry ``actions`` (``action=keys``,
    dots spelled as double underscores)."""
    cfg = DefaultConfig()
    bindings = dict(cfg.KEY_BINDINGS)
    for name, keys in actions.items():
        bindings[name.replace("__", ".")] = keys
    cfg.KEY_BINDINGS = bindings  # instance attr shadows the class dict
    monkeypatch.setattr(config_manager, "config", cfg)
    monkeypatch.setattr(config_manager, "_key_bindings", None)


def text_file(tmp_path):
    p = Path(str(tmp_path)) / "a.txt"
    p.write_text("one\ntwo\nthree\n")
    return p


# --- the shared label helpers -------------------------------------------------


def test_footer_key_names_only_the_first_binding():
    """The bar elides from the right; the help dialog is where every binding is
    listed. Zoom is bound twice by default ('+'/'=') — the footer takes '+'."""
    assert footer_key("image_viewer.zoom_in", IMAGE_VIEWER) == "+"
    assert footer_key("image_viewer.zoom_out", IMAGE_VIEWER) == "-"


def test_footer_pair_collapses_two_plain_arrows():
    assert footer_pair("text_viewer.scroll_up", "text_viewer.scroll_down",
                       TEXT_VIEWER) == "↑↓"
    assert footer_pair("text_viewer.scroll_left", "text_viewer.scroll_right",
                       TEXT_VIEWER) == "←→"


def test_footer_pair_slash_joins_anything_else():
    assert footer_pair("file_diff.next_block", "file_diff.prev_block",
                       FILE_DIFF) == "n/Shift-N"
    assert footer_pair("image_viewer.zoom_in", "image_viewer.zoom_out",
                       IMAGE_VIEWER) == "+/-"


def test_footer_pair_drops_an_unbound_side(monkeypatch):
    rebind(monkeypatch, text_viewer__scroll_up=[])
    assert footer_pair("text_viewer.scroll_up", "text_viewer.scroll_down",
                       TEXT_VIEWER) == "↓"


def test_footer_pair_is_empty_when_neither_side_is_bound(monkeypatch):
    """Empty, so the caller drops the whole segment rather than printing a word
    no key triggers."""
    rebind(monkeypatch, text_viewer__scroll_up=[], text_viewer__scroll_down=[])
    assert footer_pair("text_viewer.scroll_up", "text_viewer.scroll_down",
                       TEXT_VIEWER) == ""


# --- text viewer --------------------------------------------------------------


def test_text_viewer_footer_follows_a_scroll_rebind(tmp_path, monkeypatch):
    """The issue as reported: K/J in the config, K/J in the footer."""
    rebind(monkeypatch, text_viewer__scroll_up=["K"], text_viewer__scroll_down=["J"])
    viewer = TextViewer(text_file(tmp_path))
    assert viewer._scroll_hint_segment() == "K/J scroll · "


def test_text_viewer_footer_keeps_the_default_arrow_cluster(tmp_path):
    viewer = TextViewer(text_file(tmp_path))
    assert viewer._scroll_hint_segment() == "↑↓ scroll · "
    assert viewer._pan_hint_segment() == "←→ pan · "


def test_text_viewer_footer_follows_a_pan_rebind(tmp_path, monkeypatch):
    rebind(monkeypatch, text_viewer__scroll_left=["H"],
           text_viewer__scroll_right=["L"])
    viewer = TextViewer(text_file(tmp_path))
    assert viewer._pan_hint_segment() == "H/L pan · "


def test_text_viewer_footer_drops_an_unbound_scroll_segment(tmp_path, monkeypatch):
    rebind(monkeypatch, text_viewer__scroll_up=[], text_viewer__scroll_down=[])
    viewer = TextViewer(text_file(tmp_path))
    assert viewer._scroll_hint_segment() == ""


# --- file diff viewer ---------------------------------------------------------


def test_diff_viewer_footer_follows_a_block_jump_rebind(tmp_path, monkeypatch):
    rebind(monkeypatch, file_diff__next_block=["]"], file_diff__prev_block=["["])
    assert footer_pair("file_diff.next_block", "file_diff.prev_block",
                       FILE_DIFF) == "]/["


def test_diff_viewer_footer_follows_a_pan_rebind(tmp_path, monkeypatch):
    rebind(monkeypatch, file_diff__scroll_left=["H"], file_diff__scroll_right=["L"])
    assert footer_pair("file_diff.scroll_left", "file_diff.scroll_right",
                       FILE_DIFF) == "H/L"


# --- directory diff viewer ----------------------------------------------------


def dir_diff(tmp_path):
    left = Path(str(tmp_path)) / "L"
    left.mkdir()
    right = Path(str(tmp_path)) / "R"
    right.mkdir()
    return DirectoryDiffView(left, right, background=False)


def test_dir_diff_footer_names_the_default_keys(tmp_path):
    """Including ``quit``, which the footer used to spell ``q`` while the help
    dialog — reading the same keymap these now read — said ``Q``."""
    footer = dir_diff(tmp_path)._footer()
    for expected in ("n/Shift-N jump", "←→ expand", "[/] resize", "Tab side",
                     "Enter diff", "E merge", "Q close"):
        assert expected in footer, f"{expected!r} not in {footer!r}"


def test_dir_diff_footer_follows_a_rebind(tmp_path, monkeypatch):
    rebind(monkeypatch, dir_diff__next_change=["F"], dir_diff__prev_change=["B"],
           dir_diff__switch_side=["O"], quit=["X"])
    footer = dir_diff(tmp_path)._footer()
    assert "F/B jump" in footer
    assert "O side" in footer
    assert "X close" in footer
    assert "n/Shift-N" not in footer


def test_dir_diff_footer_drops_an_unbound_action(tmp_path, monkeypatch):
    rebind(monkeypatch, dir_diff__split_left=[], dir_diff__split_right=[])
    footer = dir_diff(tmp_path)._footer()
    assert "resize" not in footer
    assert "Tab side" in footer  # the rest of the bar is untouched


# --- image viewer -------------------------------------------------------------


def test_image_viewer_zoom_hint_follows_a_rebind(monkeypatch):
    rebind(monkeypatch, image_viewer__zoom_in=["I"], image_viewer__zoom_out=["O"])
    assert footer_pair("image_viewer.zoom_in", "image_viewer.zoom_out",
                       IMAGE_VIEWER) == "I/O"
