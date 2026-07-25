"""CSV / TSV (rich) view mode of the built-in file viewer.

The modal text viewer opens ``*.csv`` / ``*.tsv`` files in raw text and toggles
to a ``TableView`` grid in place, via the ``toggle_view_mode`` action and the
rich-renderer registry (``xefm.viewer_registry``). The TableView widget's own
behavior (frozen header, scroll, selection, search) is covered in PuiKit's
test_table_view.py; these check XeFM wires it up, including the CSV vs TSV
delimiter split.

Run with: python -m pytest test/test_table_viewer.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from puikit import Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend

from xefm.path import Path
from xefm.text_viewer import TextViewer, show_text_viewer
from xefm.viewer_registry import RichRenderer, rich_renderer_for


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=100, height=30, capabilities=request.param)


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "fruit.csv"
    p.write_text("id,name,qty\n1,apple,12\n2,banana,7\n")
    return Path(str(p))


@pytest.fixture
def tsv_file(tmp_path):
    p = tmp_path / "fruit.tsv"
    p.write_text("id\tname\tqty\n1\tapple\t12\n2\tbanana\t7\n")
    return Path(str(p))


# --- registry ----------------------------------------------------------------


def test_registry_maps_table_extensions():
    for name in ("a.csv", "b.CSV", "c.tsv"):
        r = rich_renderer_for(Path(name))
        assert isinstance(r, RichRenderer)
        assert r.name == "Table"


# --- toggling + delimiter split ----------------------------------------------


def test_toggle_builds_table_from_csv(backend, csv_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, csv_file)
    panel.render()
    v._toggle_view_mode()
    assert v.mode == "rich"
    tv = v._rich_widget
    assert type(tv).__name__ == "TableView"
    assert tv.header == ["id", "name", "qty"]
    assert tv.rows == [["1", "apple", "12"], ["2", "banana", "7"]]


def test_tsv_uses_tab_delimiter(backend, tsv_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, tsv_file)
    panel.render()
    v._toggle_view_mode()
    tv = v._rich_widget
    # A tab delimiter keeps each field separate; a comma reader would have made
    # each row a single column.
    assert tv.header == ["id", "name", "qty"]
    assert tv.rows[0] == ["1", "apple", "12"]


def test_draw_both_modes_no_crash(backend, csv_file):
    panel = Panel(backend)
    v = show_text_viewer(panel, csv_file)
    panel.render()                   # raw
    v._toggle_view_mode()
    panel.render()                   # rich (embedded TableView)
    assert type(panel._layers[-1].widget).__name__ == "TextViewer"


def test_empty_csv_does_not_crash(backend, tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("")
    v = show_text_viewer(Panel(backend), Path(str(p)))
    v._panel.render()
    assert v._ensure_rich_widget() is True   # empty is valid — an empty grid
    v._toggle_view_mode()
    v._panel.render()
    assert v.mode == "rich"
