"""Config-registered sort keys (``SORT_KEYS``, :mod:`xefm.sort_keys`).

XeFM answers #380 — its order is not the platform shell's — by exposing the
choice rather than building one shell's collation in. These cover the contract a
registered key gets: what it receives, what it may return, what it does *not*
have to re-implement, and what happens when it is wrong.
"""

import os
import sys
import tempfile
import types
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xefm import _config  # noqa: E402
from xefm import sort_keys  # noqa: E402
from xefm import user_api  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.path import Path  # noqa: E402


@pytest.fixture(autouse=True)
def clean_registry():
    """The registry is process-wide; keep it out of every other test."""
    sort_keys.clear()
    yield
    sort_keys.clear()


@pytest.fixture
def tree(tmp_path):
    """Three files of distinct sizes plus a directory, as a pane feed."""
    for name, size in (("a.txt", 300), ("b.txt", 100), ("c.txt", 200)):
        (tmp_path / name).write_text("x" * size)
    (tmp_path / "zdir").mkdir()
    return tmp_path


def order(tree, mode, reverse=False):
    flm = FileListManager(_config.Config())
    pane = {"path": Path(str(tree)), "focused_index": 0, "scroll_offset": 0,
            "files": [], "selected_files": set(), "sort_mode": mode,
            "sort_reverse": reverse, "filter_pattern": ""}
    flm.refresh_files(pane)
    return [p.name for p in pane["files"]]


def load(**sort_keys_table):
    cfg = types.SimpleNamespace(SORT_KEYS=sort_keys_table)
    warnings, _actions, _hooks, count = user_api.load_user_entries(cfg)
    return warnings, count


# --- what a key may return ---------------------------------------------------

def test_a_bare_callable_is_the_simple_form(tree):
    warnings, count = load(bysize=lambda e: e.size)
    assert (warnings, count) == ([], 1)
    assert order(tree, "bysize") == ["zdir", "b.txt", "c.txt", "a.txt"]


def test_a_key_may_return_a_tuple(tree):
    # Tuples compare element by element, which is how a multi-level order is
    # written — the usual answer, not an edge case.
    load(sizename=lambda e: (e.size, e.name))
    assert order(tree, "sizename") == ["zdir", "b.txt", "c.txt", "a.txt"]


def test_a_key_may_return_a_mixed_list(tree):
    # What a natural-order key looks like: text and numbers alternating. Legal
    # as long as every key agrees on what sits at each position.
    load(natural=lambda e: [e.name[0], len(e.name), e.name])
    assert order(tree, "natural") == ["zdir", "a.txt", "b.txt", "c.txt"]


# --- what a key does not have to do ------------------------------------------

def test_directories_still_lead_and_reverse_still_applies(tree):
    load(bysize=lambda e: e.size)
    assert order(tree, "bysize") == ["zdir", "b.txt", "c.txt", "a.txt"]
    # Reversed within each group, directories still first — the key said nothing
    # about either.
    assert order(tree, "bysize", reverse=True) == ["zdir", "a.txt", "c.txt", "b.txt"]


def test_size_and_mtime_cost_no_filesystem_call(tree):
    seen = {}

    def key(entry):
        seen["size"] = entry.size
        seen["mtime"] = entry.mtime
        return entry.name

    load(probe=key)
    # Any stat from inside the key is a bug: the listing already read these.
    with mock.patch.object(Path, "stat", side_effect=AssertionError("stat!")):
        assert order(tree, "probe") == ["zdir", "a.txt", "b.txt", "c.txt"]
    assert seen["size"] > 0 and seen["mtime"] > 0


# --- overriding a built-in ---------------------------------------------------

def test_shadowing_a_builtin_needs_an_explicit_override(tree):
    warnings, count = load(name=lambda e: e.name)
    assert count == 0
    assert len(warnings) == 1 and "override" in warnings[0]
    assert order(tree, "name") == ["zdir", "a.txt", "b.txt", "c.txt"]


def test_an_explicit_override_replaces_the_builtin(tree):
    warnings, count = load(name={"key": lambda e: [-ord(c) for c in e.name],
                                 "override": True})
    assert (warnings, count) == ([], 1)
    assert order(tree, "name") == ["zdir", "c.txt", "b.txt", "a.txt"]


def test_an_override_keeps_the_builtin_row_in_place(tree):
    load(name={"key": lambda e: e.name, "override": True})
    modes = [m for m, _l, _h in sort_keys.rows()]
    assert modes == ["name", "ext", "size", "date"]     # no extra row
    assert sort_keys.label("name") == "Filename"        # and the same label


# --- being wrong -------------------------------------------------------------

def test_a_key_that_raises_loses_the_sort_not_the_pane(tree):
    load(boom=lambda e: 1 / 0)
    # Falls back to the built-in filename order rather than failing the listing.
    assert order(tree, "boom") == ["zdir", "a.txt", "b.txt", "c.txt"]


def test_a_key_returning_incomparable_values_falls_back_too(tree):
    load(mixed=lambda e: e.size if e.name < "b" else e.name)
    assert order(tree, "mixed") == ["zdir", "a.txt", "b.txt", "c.txt"]


@pytest.mark.parametrize("spec, expected", [
    (42, "must be a function or a dict"),
    ({"label": "No key"}, "no callable 'key'"),
    ({"key": lambda e: e, "hotkey": "9"}, "not a letter"),
])
def test_a_malformed_entry_is_one_warning_not_a_failure(spec, expected):
    warnings, count = load(broken=spec)
    assert count == 0
    assert len(warnings) == 1 and expected in warnings[0]


# --- how it shows up ---------------------------------------------------------

def test_a_new_key_becomes_a_row_after_the_builtins():
    load(grouped={"label": "Grouped", "key": lambda e: e.name})
    assert sort_keys.rows()[-1] == ("grouped", "Grouped", "G")


def test_a_hotkey_is_offered_only_when_the_initial_is_free():
    # The dialog does not draw hotkeys — each row's initial *is* its key — so a
    # row whose initial is taken gets none rather than some unhinted letter.
    load(sizes={"label": "Size then name", "key": lambda e: e.name},
         grouped={"label": "Grouped", "key": lambda e: e.name})
    keys = {mode: hotkey for mode, _l, hotkey in sort_keys.rows()}
    assert keys["sizes"] is None      # S belongs to the built-in Size
    assert keys["grouped"] == "G"


def test_an_explicit_hotkey_wins():
    load(name={"key": lambda e: e.name, "override": True, "hotkey": "n"})
    assert ("name", "Filename", "N") in sort_keys.rows()


def test_the_dialog_explains_a_registered_key():
    load(grouped={"label": "Grouped", "key": lambda e: e.name,
                  "explain": "docs/ → src/ → a.txt"})
    assert sort_keys.explanation("grouped", False) == "(docs/ → src/ → a.txt)"
    assert sort_keys.explanation("grouped", True).endswith(", reversed)")
    # One with no explanation still gets a line, so the dialog never draws blank.
    load(plain=lambda e: e.name)
    assert sort_keys.explanation("plain", False) == "(a key from your config)"


def test_the_status_bar_names_a_registered_key():
    load(grouped={"label": "Grouped", "key": lambda e: e.name})
    flm = FileListManager(_config.Config())
    pane = {"sort_mode": "grouped", "sort_reverse": False}
    assert flm.get_sort_description(pane) == "Grouped ↑"


def test_the_preview_notice_counts_sort_keys():
    assert "sort key" not in (user_api.preview_notice(1, 0) or "")
    assert "2 sort key(s)" in user_api.preview_notice(0, 0, 2)


# --- lifecycle ---------------------------------------------------------------

def test_a_reload_drops_a_key_the_config_no_longer_defines():
    load(grouped=lambda e: e.name)
    assert sort_keys.is_known("grouped")
    load()                                   # the config was edited and reloaded
    assert not sort_keys.is_known("grouped")


def test_is_known_covers_the_builtins_and_the_legacy_alias():
    for mode in ("name", "ext", "size", "date", "type"):
        assert sort_keys.is_known(mode)
    assert not sort_keys.is_known("nope")
