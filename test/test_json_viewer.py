"""JSON / JSON Lines (rich) view mode of the built-in file viewer.

The modal text viewer opens ``*.json`` / ``*.jsonl`` / ``*.ndjson`` files in raw
text and toggles to a collapsible ``JsonView`` tree in place, via the
``toggle_view_mode`` action and the rich-renderer registry
(``xefm.viewer_registry``). The JsonView widget's own behavior (expand/collapse,
search, copy) is covered in PuiKit's test_json_view.py; these check XeFM wires it
up and degrades gracefully on malformed JSON.

Run with: python -m pytest test/test_json_viewer.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend

from xefm.path import Path
from xefm.text_viewer import TextViewer, show_text_viewer
from xefm.viewer_registry import RichRenderer, rich_renderer_for


def _key(name=None, char=None):
    return Event(type=EventType.KEY, key=name, char=char)


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=100, height=30, capabilities=request.param)


@pytest.fixture
def json_file(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"name": "xefm", "tags": ["tui", "files"], "nested": {"n": 42}}')
    return Path(str(p))


@pytest.fixture
def jsonl_file(tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_text('{"a": 1}\n{"a": 2}\n{"a": 3}\n')
    return Path(str(p))


# --- registry ----------------------------------------------------------------


def test_registry_maps_json_extensions():
    for name in ("a.json", "b.JSON", "c.jsonl", "d.ndjson"):
        r = rich_renderer_for(Path(name))
        assert isinstance(r, RichRenderer)
        assert r.name == "JSON"


# --- viewer defaults + toggling ----------------------------------------------


def test_json_file_opens_in_raw_text(json_file):
    v = TextViewer(json_file)
    assert v.mode == "text"          # raw by default
    assert v._rich is not None       # a renderer is available
    assert v._rich_widget is None    # built lazily on first switch


def test_toggle_builds_json_view(backend, json_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, json_file)
    panel.render()
    v._toggle_view_mode()
    assert v.mode == "rich"
    assert type(v._rich_widget).__name__ == "JsonView"
    # Top-level object → its keys are the tree roots.
    assert [n.key for n in v._rich_widget.roots] == ["name", "tags", "nested"]


def test_jsonl_wraps_records_in_a_list(backend, jsonl_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, jsonl_file)
    panel.render()
    v._toggle_view_mode()
    assert v.mode == "rich"
    # Three line-delimited records → an array of three objects at the root.
    assert len(v._rich_widget.roots) == 3


def test_draw_both_modes_no_crash(backend, json_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, json_file)
    panel.render()                   # raw
    v._toggle_view_mode()
    panel.render()                   # rich (embedded JsonView)
    assert type(panel._layers[-1].widget).__name__ == "TextViewer"


def test_malformed_json_stays_raw(backend, tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ this is not valid json ,,, }")
    bad = Path(str(p))
    panel = Panel(backend)
    v = show_text_viewer(panel, bad)
    panel.render()
    assert v._rich is not None       # extension is registered
    assert v._ensure_rich_widget() is False   # but build fails -> stay raw
    v._toggle_view_mode()
    assert v.mode == "text"          # toggle refused, no crash
    assert v._rich_widget is None
