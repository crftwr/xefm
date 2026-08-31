"""Incremental search refuses a character that would leave it no candidate
(issue #370).

Three layers, because the decision is split across three: ``search_match.
dead_end`` (is a query with no hits actually finished?), ``ISearchBar.
reject_edit`` (roll the field back to the last accepted pattern), and
``XeFMApp._isearch_recompute``, which joins them over a live file list — twice
here, once on an ASCII listing and once on one holding Japanese, because that
is what decides how long a half-typed romaji token stays open.

Run with: python -m pytest test/test_isearch_dead_end.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit.backends import create_backend
from puikit.event import Event, EventType, char_key_event

from xefm import app as xefm_app
from xefm import migemo_search, search_match
from xefm.isearch_bar import ISearchBar
from xefm.state_manager import XeFMStateManager


def _key(name, mods=()):
    return Event(type=EventType.KEY, key=name, modifiers=frozenset(mods))


@pytest.fixture
def migemo_on(monkeypatch):
    """Migemo's gates pinned to their defaults, independent of ~/.xefm/config.py
    (mirrors test_migemo_search)."""
    cfg = SimpleNamespace(MIGEMO_SEARCH=True, MIGEMO_MIN_LENGTH=3,
                          MIGEMO_ROMAJI_TABLE="default")
    monkeypatch.setattr(migemo_search, "_config", lambda: cfg)
    return cfg


# --- which queries are finished ----------------------------------------------


def test_a_plain_query_is_a_dead_end(migemo_on):
    assert search_match.dead_end("readme")


def test_a_query_with_no_tokens_is_not(migemo_on):
    """Nothing has been asked for yet, so the next character can only widen."""
    assert not search_match.dead_end("")
    assert not search_match.dead_end("   ")


def test_a_token_under_migemos_gate_is_not(migemo_on):
    """"ni" is a plain substring search; "nih" also finds 日本 (#332)."""
    assert not search_match.dead_end("n")
    assert not search_match.dead_end("ni")
    assert search_match.dead_end("nih")
    # Any one undecided token holds the whole query open.
    assert not search_match.dead_end("readme ni")


def test_the_gate_follows_the_config(migemo_on):
    migemo_on.MIGEMO_SEARCH = False
    assert search_match.dead_end("n")
    migemo_on.MIGEMO_SEARCH = True
    migemo_on.MIGEMO_MIN_LENGTH = 5
    assert not search_match.dead_end("nih")


def test_candidates_with_nothing_to_find_settle_the_short_tokens(migemo_on):
    """``migemo=False``: every candidate is ASCII, so no romaji token can ever
    become a hit and the query is finished at its first character."""
    assert search_match.dead_end("n", migemo=False)
    assert search_match.dead_end("ni", migemo=False)
    assert not search_match.dead_end("", migemo=False)


def test_a_glob_is_a_dead_end_but_an_open_class_is_not(migemo_on):
    """Globs bypass Migemo, so a short one is already decided — except while a
    ``[`` is still hanging open, where fnmatch reads the bracket literally."""
    assert search_match.dead_end("*.py")
    assert not search_match.dead_end("a[b")
    assert search_match.dead_end("a[bc]")


# --- the bar's rollback ------------------------------------------------------


def _typing_bar():
    """A bar whose owner refuses any pattern added to ``refuse``, recording in
    ``seen`` what ``reject_edit`` answered each time it was asked."""
    bar = ISearchBar()
    refuse: set[str] = set()
    seen: list[bool] = []

    def on_change(text):
        if text in refuse:
            seen.append(bar.reject_edit())

    bar.on_change = on_change
    return bar, refuse, seen


def _type(bar, text):
    for ch in text:
        bar.handle_event(char_key_event(ch))


def test_a_refused_character_never_lands():
    bar, refuse, seen = _typing_bar()
    refuse.add("abz")
    _type(bar, "abz")
    assert bar.pattern == "ab"
    assert bar.edit.cursor == 2
    assert seen == [True]
    # …and the pattern goes on from where it stopped.
    _type(bar, "c")
    assert bar.pattern == "abc"


def test_a_refusal_mid_pattern_puts_the_caret_back():
    bar, refuse, _seen = _typing_bar()
    refuse.add("azbc")
    _type(bar, "abc")
    bar.handle_event(_key("home"))
    bar.handle_event(_key("right"))
    _type(bar, "z")
    assert bar.pattern == "abc"
    assert bar.edit.cursor == 1


def test_a_deletion_is_never_refused():
    """Refusing one would strand the user in a pattern they cannot back out of,
    so ``reject_edit`` answers False and the deletion stands."""
    bar, refuse, seen = _typing_bar()
    _type(bar, "abc")
    refuse.update({"ab", "a", ""})
    for _ in range(3):
        bar.handle_event(_key("backspace"))
    assert bar.pattern == ""
    assert seen == [False, False, False]


# --- through a live file list -------------------------------------------------


class LiveSearch:
    """An app over a temp directory of ``NAMES``, with its footer drawn (the
    rect isearch anchors to). Not a TestCase: two listings use it."""

    NAMES: list = []

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        for name in self.NAMES:
            open(os.path.join(self.tmp, name), "w").close()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app._settle_listings()
        self.pane = self.app.active_pane()
        self.assertEqual(sorted(f.name for f in self.pane["files"]),
                         sorted(self.NAMES))
        self.app.panel.render()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def type(self, text):
        for ch in text:
            self.app.panel.dispatch_event(char_key_event(ch))

    def pattern(self):
        return self.app._isearch_bar.pattern

    def focused(self):
        return self.pane["files"][self.pane["focused_index"]].name


class ISearchDeadEndTest(LiveSearch, unittest.TestCase):
    """An all-ASCII listing: nothing Migemo could ever find, so the search
    stops on the first character that misses."""

    NAMES = ["alpha.txt", "beta.txt", "gamma_alpha.txt"]

    def test_the_pattern_stops_at_its_last_match(self):
        self.app.enter_isearch()
        self.type("alphaz")
        self.assertEqual(self.pattern(), "alpha")
        self.assertEqual(self.app._isearch_matches, [0, 2])
        self.assertEqual(self.app._isearch_status(), (1, 2))
        self.assertEqual(self.focused(), "alpha.txt")

    def test_a_miss_is_refused_on_its_first_character(self):
        self.app.enter_isearch()
        self.type("z")
        self.assertEqual(self.pattern(), "")
        self.assertEqual(self.app._isearch_matches, [])

    def test_a_second_token_that_matches_nothing_is_refused(self):
        """The whole query has to keep matching, so a keyword typed after a
        space is refused exactly like the first one."""
        self.app.enter_isearch()
        self.type("alpha zzz")
        self.assertEqual(self.pattern(), "alpha ")
        self.assertEqual(self.app._isearch_matches, [0, 2])
        self.assertEqual(self.focused(), "alpha.txt")

    def test_backspace_still_walks_the_pattern_back(self):
        self.app.enter_isearch()
        self.type("beta")
        for _ in range(4):
            self.app.panel.dispatch_event(_key("backspace"))
        self.assertEqual(self.pattern(), "")
        self.assertEqual(self.app._isearch_matches, [])
        self.assertEqual(self.focused(), "alpha.txt")   # back to the origin

    def test_escape_still_cancels_after_a_refusal(self):
        self.app.enter_isearch()
        self.pane["focused_index"] = 1                    # beta.txt
        self.app._isearch_origin = 1
        self.type("alphaz")
        self.app.panel.dispatch_event(_key("escape"))
        self.assertFalse(self.app._isearch_active)
        self.assertEqual(self.focused(), "beta.txt")

    def test_enter_still_stops_at_the_match(self):
        self.app.enter_isearch()
        self.type("gammaz")
        self.app.panel.dispatch_event(_key("enter"))
        self.assertFalse(self.app._isearch_active)
        self.assertEqual(self.focused(), "gamma_alpha.txt")


class ISearchDeadEndJapaneseTest(LiveSearch, unittest.TestCase):
    """A listing holding a Japanese name: a romaji token stays open until it
    reaches Migemo's length gate, because that is where it can start matching."""

    NAMES = ["alpha.txt", "検索結果.txt"]

    def test_a_pattern_migemo_has_yet_to_reach_is_accepted(self):
        self.app.enter_isearch()
        self.type("zy")                    # matches no name, ASCII or not
        self.assertEqual(self.pattern(), "zy")
        self.assertEqual(self.app._isearch_status(), (0, 0))
        # The third character is where Migemo would have spoken up.
        self.type("x")
        self.assertEqual(self.pattern(), "zy")

    def test_romaji_finds_the_japanese_name(self):
        if migemo_search._load_engine() is None:
            self.skipTest("pymigemo not installed")
        self.app.enter_isearch()
        self.type("kensaku")
        self.assertEqual(self.pattern(), "kensaku")
        self.assertEqual(self.focused(), "検索結果.txt")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
