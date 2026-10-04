"""The favorites list: the config/state merge, adding, renaming and forgetting.

No state database is involved — it is faked over a dict — so these run as fast
as the rest of the suite and leave nothing behind on the machine.

Run with: python -m pytest test/test_favorites.py -v
"""

import os
import unittest
from unittest.mock import patch

from xefm import favorites


class _FakeState:
    """The two ``StateManager`` methods this module uses, over a dict."""

    def __init__(self, rows=None):
        self.store = {favorites._STATE_KEY: list(rows or [])}
        self.fail = False

    def get_state(self, key, default=None):
        return self.store.get(key, default)

    def set_state(self, key, value):
        if self.fail:
            return False
        self.store[key] = value
        return True


class FavoritesTest(unittest.TestCase):
    def setUp(self):
        self.state = _FakeState()
        self.config_rows = []
        for target, value in (
                ("get_state_manager", lambda: self.state),
                ("get_favorite_directories", lambda: self.config_rows)):
            patcher = patch.object(favorites, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def names(self):
        return [e.name for e in favorites.get_favorites()]

    # --- the merge ----------------------------------------------------------

    def test_an_empty_list_is_empty(self):
        self.assertEqual(favorites.get_favorites(), [])

    def test_config_rows_come_first_then_added_ones_in_order(self):
        self.config_rows = [{"name": "Home", "path": "/home/me"}]
        favorites.add_favorite("Work", "/srv/work")
        favorites.add_favorite("Notes", "/srv/notes.txt", is_file=True)
        self.assertEqual(self.names(), ["Home", "Work", "Notes"])
        origins = [e.origin for e in favorites.get_favorites()]
        self.assertEqual(origins, [favorites.CONFIG, favorites.STATE, favorites.STATE])

    def test_is_file_survives_the_round_trip(self):
        favorites.add_favorite("Notes", "/srv/notes.txt", is_file=True)
        favorites.add_favorite("Work", "/srv/work")
        rows = {e.name: e.is_file for e in favorites.get_favorites()}
        self.assertEqual(rows, {"Notes": True, "Work": False})

    def test_a_config_row_shadows_an_added_duplicate(self):
        self.state.store[favorites._STATE_KEY] = [{"name": "Mine", "path": "/srv/work"}]
        self.config_rows = [{"name": "Work", "path": "/srv/work"}]
        self.assertEqual(self.names(), ["Work"])

    def test_malformed_state_rows_are_skipped(self):
        self.state.store[favorites._STATE_KEY] = [
            "junk", {"name": "No path"}, {"path": "/srv/x"}]
        entries = favorites.get_favorites()
        self.assertEqual([(e.name, e.path) for e in entries], [("/srv/x", "/srv/x")])

    # --- adding -------------------------------------------------------------

    def test_adding_a_config_favorite_writes_nothing(self):
        self.config_rows = [{"name": "Work", "path": "/srv/work"}]
        self.assertEqual(favorites.add_favorite("Again", "/srv/work/"),
                         favorites.IN_CONFIG)
        self.assertEqual(self.state.store[favorites._STATE_KEY], [])

    def test_adding_again_renames_in_place(self):
        favorites.add_favorite("A", "/a")
        favorites.add_favorite("B", "/b")
        self.assertEqual(favorites.add_favorite("Alpha", "/a/"), favorites.RENAMED)
        self.assertEqual(self.names(), ["Alpha", "B"])

    def test_a_trailing_separator_is_the_same_favorite(self):
        favorites.add_favorite("A", "/a/b")
        self.assertIsNotNone(favorites.find_favorite("/a/b/"))
        self.assertIsNotNone(favorites.find_favorite("/a//b"))

    def test_remote_paths_dedupe_on_a_trailing_slash(self):
        favorites.add_favorite("Dev", "ssh://devbox/var/www/")
        self.assertEqual(favorites.find_favorite("ssh://devbox/var/www").name, "Dev")
        self.assertIsNone(favorites.find_favorite("ssh://devbox/var"))

    def test_a_failed_write_is_reported(self):
        self.state.fail = True
        self.assertEqual(favorites.add_favorite("A", "/a"), favorites.FAILED)

    @unittest.skipUnless(os.name == "nt", "case-insensitive paths are Windows'")
    def test_case_does_not_make_a_second_favorite_on_windows(self):
        favorites.add_favorite("A", r"C:\Work")
        self.assertIsNotNone(favorites.find_favorite(r"c:\work"))

    # --- forgetting ---------------------------------------------------------

    def test_an_added_favorite_can_be_forgotten(self):
        favorites.add_favorite("A", "/a")
        favorites.add_favorite("B", "/b")
        entry = favorites.get_favorites()[0]
        self.assertTrue(favorites.remove_favorite(entry))
        self.assertEqual(self.names(), ["B"])

    def test_a_config_row_cannot_be_forgotten(self):
        self.config_rows = [{"name": "Home", "path": "/home/me"}]
        entry = favorites.get_favorites()[0]
        self.assertFalse(entry.removable)
        self.assertFalse(favorites.remove_favorite(entry))
        self.assertEqual(self.names(), ["Home"])


if __name__ == "__main__":
    unittest.main()
