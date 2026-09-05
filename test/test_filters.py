"""Config-defined filters (``FILTERS``, :mod:`xefm.filters`).

The pane filter was one ``fnmatch`` pattern typed at the ';' prompt, which can
only ask about a name. These cover what a config may define instead — globs or a
predicate over the entry — where the definitions show up (fixed rows under the
picker's "clear filter", never in its history), and what happens when one is
wrong: a filter fails *open*, showing everything, because a filter that hides
files quietly is how one gets caught in an operation nobody could see.
"""

import os
import sys
import time
import types
import unicodedata
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xefm import _config  # noqa: E402
from xefm import filters  # noqa: E402
from xefm import user_api  # noqa: E402
from xefm.app import XeFMApp, _FILTER_HISTORY_KEY  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.path import Path  # noqa: E402


@pytest.fixture(autouse=True)
def clean_registry():
    """The registry is process-wide; keep it out of every other test."""
    filters.clear()
    yield
    filters.clear()


@pytest.fixture
def tree(tmp_path):
    """Three files of distinct types and sizes plus a directory, as a pane feed."""
    for name, size in (("a.txt", 300), ("b.png", 100), ("c.py", 200)):
        (tmp_path / name).write_text("x" * size)
    (tmp_path / "zdir").mkdir()
    return tmp_path


def load(**filters_table):
    cfg = types.SimpleNamespace(FILTERS=filters_table)
    warnings, _actions, _hooks, _sorts, count = user_api.load_user_entries(cfg)
    return warnings, count


def shown(tree, pattern):
    """The names a pane lists under ``pattern`` — a filter's name or a glob."""
    flm = FileListManager(_config.Config())
    pane = {"path": Path(str(tree)), "focused_index": 0, "scroll_offset": 0,
            "files": [], "selected_files": set(), "sort_mode": "filename",
            "sort_reverse": False, "filter_pattern": pattern}
    flm.refresh_files(pane)
    return [p.name for p in pane["files"]]


# --- how a filter may be written ---------------------------------------------

def test_a_pattern_string_is_the_simple_form(tree):
    warnings, count = load(images="*.png")
    assert (warnings, count) == ([], 1)
    assert shown(tree, "images") == ["zdir", "b.png"]


def test_a_list_of_patterns_matches_any_one_of_them(tree):
    load(code=["*.py", "*.txt"])
    assert shown(tree, "code") == ["zdir", "a.txt", "c.py"]


def test_a_bare_callable_is_a_predicate(tree):
    warnings, count = load(big=lambda e: e.size > 150)
    assert (warnings, count) == ([], 1)
    assert shown(tree, "big") == ["zdir", "a.txt", "c.py"]


def test_a_dict_carries_the_label(tree):
    load(big={"label": "Over 150 bytes", "match": lambda e: e.size > 150})
    assert filters.rows() == [filters.Row("big", "Over 150 bytes")]
    assert shown(tree, "big") == ["zdir", "a.txt", "c.py"]


def test_a_typed_glob_is_unaffected(tree):
    """The filter nobody defined: still the pattern it always was."""
    assert shown(tree, "*.py") == ["zdir", "c.py"]
    assert shown(tree, "") == ["zdir", "a.txt", "b.png", "c.py"]


def test_a_defined_name_wins_over_reading_it_as_a_pattern(tree):
    """``matcher`` is the one place the question is decided, and the registry is
    what it asks first — otherwise a name would filter by matching files called
    after it."""
    (tree / "photos").write_text("x")
    load(photos="*.png")
    assert shown(tree, "photos") == ["zdir", "b.png"]


def test_a_pattern_matches_the_name_the_pane_shows(tmp_path):
    """Composed, whatever the filesystem stored — the same rule the built-in
    filter has always followed (:mod:`xefm.name_key`)."""
    (tmp_path / unicodedata.normalize("NFD", "が.png")).write_text("x")
    load(ga="が*")
    assert shown(tmp_path, "ga") == [unicodedata.normalize("NFD", "が.png")]


# --- what the predicate is handed --------------------------------------------

def test_the_argument_is_an_entryinfo(tree):
    seen = []
    load(probe=lambda e: seen.append(type(e).__name__) or True)
    shown(tree, "probe")
    assert set(seen) == {"EntryInfo"}


def test_size_and_mtime_cost_no_filesystem_call(tree):
    seen = {}

    def match(entry):
        seen["size"] = entry.size
        seen["mtime"] = entry.mtime
        return True

    load(probe=match)
    # Any stat from inside the predicate is a bug: the listing already read these.
    with mock.patch.object(Path, "stat", side_effect=AssertionError("stat!")):
        assert shown(tree, "probe") == ["zdir", "a.txt", "b.png", "c.py"]
    assert seen["size"] > 0 and seen["mtime"] > 0


def test_a_predicate_can_filter_by_something_the_name_never_says(tree):
    """The point of the whole thing: a question no glob can ask."""
    load(today={"label": "Modified today",
                "match": lambda e: e.mtime >= time.time() - 24 * 3600})
    assert shown(tree, "today") == ["zdir", "a.txt", "b.png", "c.py"]


def test_the_raw_listing_records_are_enough_to_match(tmp_path):
    """What the content search's narrowing passes: the records a directory walk
    reads, before any listing has filled in the compared name."""
    (tmp_path / "b.png").write_text("x")
    path = Path(str(tmp_path / "b.png"))
    assert filters.matcher("*.png")(path, {})
    assert not filters.matcher("*.txt")(path, {})


# --- what a filter does not have to do ---------------------------------------

def test_directories_are_shown_whatever_the_filter_says(tree):
    """A filter that hid them would take away the folder you were about to
    open — so it only ever decides which files are visible, and this is how
    "directories only" is written."""
    load(dirs=lambda e: False)
    assert shown(tree, "dirs") == ["zdir"]


# --- being wrong -------------------------------------------------------------

def test_a_predicate_that_raises_loses_the_filter_not_the_pane(tree):
    load(boom=lambda e: 1 / 0)
    # Fails open: every entry stays visible rather than half a directory going
    # missing under a filter nobody can see is broken.
    assert shown(tree, "boom") == ["zdir", "a.txt", "b.png", "c.py"]


@pytest.mark.parametrize("spec, expected", [
    (42, "must be a function, a pattern, or a dict"),
    ({"label": "Nothing"}, "no 'match' function and no 'pattern'"),
    ({"match": "*.py"}, "'match' that is not callable"),
    ({"match": lambda e: True, "pattern": "*.py"}, "one or the other"),
    ({"pattern": []}, "not a non-empty string or list"),
    ({"pattern": ["*.py", 7]}, "not a non-empty string or list"),
])
def test_a_malformed_entry_is_one_warning_not_a_failure(spec, expected):
    warnings, count = load(broken=spec)
    assert count == 0
    assert len(warnings) == 1 and expected in warnings[0]


def test_a_name_may_not_be_readable_as_a_pattern():
    """A filter is remembered under its name where a typed pattern is remembered
    as itself; a name that reads as a glob could not be told from one."""
    warnings, count = load(**{"*.py": lambda e: True})
    assert count == 0
    assert len(warnings) == 1 and "glob characters" in warnings[0]


# --- how it shows up ---------------------------------------------------------

def test_rows_come_in_the_order_the_config_defined_them():
    load(images="*.png", big=lambda e: e.size > 10)
    assert filters.rows() == [filters.Row("images", "images"),
                              filters.Row("big", "big")]


def test_the_status_bar_names_a_defined_filter():
    load(images={"label": "Images", "pattern": "*.png"})
    assert filters.label("images") == "Images"
    # A typed pattern is already its own name.
    assert filters.label("*.py") == "*.py"


# --- the picker ---------------------------------------------------------------

class FakeState:
    """Stands in for the state manager (see test_filter_list_remove.py)."""

    def __init__(self, filter_history=()):
        self.state = {_FILTER_HISTORY_KEY: list(filter_history)}

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def set_state(self, key, value, *a, **kw):
        self.state[key] = value
        return True


class FakePicker:
    """The slice of ``XeFMApp`` the ';' prompt touches, so the rows it builds
    can be read without building a window."""

    _FILTER_CLEAR = XeFMApp._FILTER_CLEAR
    enter_filter = XeFMApp.enter_filter
    _filter_history = XeFMApp._filter_history
    _record_filter_pattern = XeFMApp._record_filter_pattern
    _forget_filter_pattern = XeFMApp._forget_filter_pattern

    def __init__(self, history=()):
        self.state_manager = FakeState(history)
        self.applied = []
        self.logged = []
        self.panel = types.SimpleNamespace(render=lambda: None)

    def active_pane(self):
        return {}

    def _active_pane_region(self):
        return None

    def _apply_filter(self, pane, pattern, on_count=None):
        self.applied.append(pattern)

    def log_info(self, msg):
        self.logged.append(msg)


@pytest.fixture
def picker(monkeypatch):
    """Open the ';' prompt and hand back the app plus the dialog's arguments."""
    def open_it(history=()):
        seen = {}
        monkeypatch.setattr(
            "xefm.app.show_filter_list",
            lambda panel, items, **kw: seen.update(items=items, **kw))
        app = FakePicker(history)
        app.enter_filter()
        return app, seen
    return open_it


def test_defined_filters_are_pinned_under_the_clear_row(picker):
    load(images={"label": "Images", "pattern": "*.png"}, big=lambda e: e.size > 1)
    app, seen = picker(history=["*.py", "*.md"])

    labels = [seen["to_label"](v) for v in seen["items"]]
    assert labels == [XeFMApp._FILTER_CLEAR, "Images", "big", "*.py", "*.md"]


def test_picking_one_applies_it_by_name(picker):
    load(images={"label": "Images", "pattern": "*.png"})
    app, seen = picker()

    seen["on_accept"](seen["items"][1])
    assert app.applied == ["images"]
    assert app.logged == []          # the count is logged when the listing lands


def test_picking_a_remembered_pattern_still_applies_the_text(picker):
    app, seen = picker(history=["*.py"])

    seen["on_accept"](seen["items"][1])
    assert app.applied == ["*.py"]


def test_the_clear_row_still_clears(picker):
    load(images="*.png")
    app, seen = picker()

    seen["on_accept"](XeFMApp._FILTER_CLEAR)
    assert app.applied == [""] and app.logged == ["Filter cleared"]


def test_a_defined_filter_never_enters_the_history(picker):
    """It has a fixed row of its own; recording it would list it twice and push
    a typed pattern out of the history to do it."""
    load(images="*.png")
    app, _seen = picker(history=["*.py"])

    app._record_filter_pattern("images")
    app._record_filter_pattern("*.md")
    assert app._filter_history() == ["*.md", "*.py"]


def test_a_defined_row_survives_the_remove_key(picker):
    """Same answer the "clear filter" row gets: nothing was forgotten, so the
    dialog leaves the row where it is."""
    load(images="*.png")
    app, seen = picker(history=["*.py"])

    assert seen["on_remove"](seen["items"][1]) is False
    assert app._filter_history() == ["*.py"]


# --- lifecycle ---------------------------------------------------------------

def test_the_preview_notice_counts_filters():
    assert "filter" not in (user_api.preview_notice(1, 0) or "")
    assert "2 filter(s)" in user_api.preview_notice(0, 0, 0, 2)


def test_a_reload_drops_a_filter_the_config_no_longer_defines():
    load(images="*.png")
    assert filters.is_known("images")
    load()                                   # the config was edited and reloaded
    assert not filters.is_known("images")
