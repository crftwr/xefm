"""What the search dialog's options mean (xefm.search_options), and the two
walks honouring them (xefm.app).

The options are two kinds of thing and the tests are split the same way: how the
query is *read* (case, whole word, regular expression) and what is *walked*
(subfolders). Issue #312.

Run with: python -m pytest test/test_search_options.py -v
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import search_options as so  # noqa: E402
from xefm.options import OptionSet  # noqa: E402
from xefm.path import Path  # noqa: E402


def _bare_app(show_hidden=False):
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app.flm = type("_FLM", (), {"show_hidden": show_hidden})()
    return app


class ContentPattern(unittest.TestCase):
    def _re(self, query, *, case=False, word=False, regex=True):
        return so.content_regex(query, case=case, word=word, regex=regex)

    def test_defaults_match_what_content_search_always_did(self):
        # Case-insensitive regular expression: the shipped behaviour, unchanged.
        self.assertTrue(self._re("todo").search("TODO: fix"))
        self.assertTrue(self._re("a.c").search("abc"))

    def test_case_on_distinguishes(self):
        self.assertIsNone(self._re("TODO", case=True).search("todo"))
        self.assertTrue(self._re("TODO", case=True).search("TODO"))

    def test_regex_off_matches_the_characters_typed(self):
        pattern = self._re("a.c", regex=False)
        self.assertIsNone(pattern.search("abc"))
        self.assertTrue(pattern.search("a.c"))

    def test_regex_off_cannot_raise_on_a_broken_pattern(self):
        # The other half of #305: "C++(" is a search, not a syntax error.
        self.assertTrue(self._re("C++(", regex=False).search("void C++( x"))

    def test_word_anchors_both_ends(self):
        pattern = self._re("cat", word=True)
        self.assertTrue(pattern.search("a cat sat"))
        self.assertIsNone(pattern.search("concatenate"))

    def test_word_groups_the_whole_query(self):
        # Without the group, \b(?:a|b)\b would anchor only the first branch.
        pattern = self._re("cat|dog", word=True)
        self.assertIsNone(pattern.search("concatenate hotdogs"))
        self.assertTrue(pattern.search("one dog"))

    def test_word_and_regex_off_compose(self):
        pattern = self._re("a.c", word=True, regex=False)
        self.assertTrue(pattern.search("say a.c here"))
        self.assertIsNone(pattern.search("abc"))


class Declarations(unittest.TestCase):
    def test_the_query_language_options_are_content_only(self):
        options = OptionSet(so.SEARCH_OPTIONS)
        names = [o.name for o in options.visible("filename")]
        self.assertEqual(names, [so.CASE, so.SUBDIRS])
        self.assertEqual([o.name for o in options.visible("content")],
                         [so.CASE, so.WORD, so.REGEX, so.SUBDIRS])

    def test_defaults_change_nothing_that_shipped(self):
        # Content search has always been a case-insensitive regex over the whole
        # tree; #312 makes that visible, it does not change it.
        options = OptionSet(so.SEARCH_OPTIONS)
        self.assertEqual(options.snapshot(), {
            so.CASE: False, so.WORD: False, so.REGEX: True, so.SUBDIRS: True})

    def test_the_labels_initials_are_unique(self):
        # They are the keys in the options box, which draws no letter column.
        keys = [o.key for o in so.SEARCH_OPTIONS]
        self.assertEqual(sorted(keys), ["c", "r", "s", "w"])

    def test_only_the_scope_option_is_transient(self):
        options = OptionSet(so.SEARCH_OPTIONS)
        options.set(so.CASE, True)
        options.set(so.SUBDIRS, False)
        options.reset_transient()
        self.assertIs(options[so.CASE], True)
        self.assertIs(options[so.SUBDIRS], True)


class Walks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, relpath, content=""):
        p = os.path.join(self.tmp, relpath)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)

    def _names(self, pattern, **kw):
        app = _bare_app()
        return sorted(e.name for e in app._iter_filename_matches(
            Path(self.tmp), pattern, threading.Event(), **kw))

    def _grep(self, query, *, case=False, word=False, regex=True, **kw):
        app = _bare_app()
        pattern = so.content_regex(query, case=case, word=word, regex=regex)
        return [h["path"].name for h in app._iter_content_matches(
            Path(self.tmp), pattern, threading.Event(), **kw)]

    def test_filename_walk_ignores_case_by_default(self):
        self._write("README.md")
        self.assertEqual(self._names("readme*"), ["README.md"])

    def test_filename_walk_can_be_made_case_sensitive(self):
        self._write("README.md")
        self.assertEqual(self._names("readme*", case=True), [])

    def test_filename_walk_stops_at_this_directory(self):
        self._write("top.txt")
        self._write("sub/deep.txt")
        self.assertEqual(self._names("*.txt"), ["deep.txt", "top.txt"])
        self.assertEqual(self._names("*.txt", recursive=False), ["top.txt"])

    def test_a_subdirectory_still_matches_by_name_without_recursion(self):
        # "no subfolders" means it is not descended, not that it is invisible.
        self._write("logs/a.txt")
        self.assertEqual(self._names("logs", recursive=False), ["logs"])

    def test_content_walk_stops_at_this_directory(self):
        self._write("top.txt", "needle\n")
        self._write("sub/deep.txt", "needle\n")
        self.assertEqual(sorted(self._grep("needle")), ["deep.txt", "top.txt"])
        self.assertEqual(self._grep("needle", recursive=False), ["top.txt"])

    def test_content_walk_honours_the_case_option(self):
        self._write("a.txt", "TODO: fix\n")
        self._write("b.txt", "todo: fix\n")
        self.assertEqual(sorted(self._grep("TODO")), ["a.txt", "b.txt"])
        self.assertEqual(self._grep("TODO", case=True), ["a.txt"])

    def test_content_walk_honours_a_non_regex_query(self):
        self._write("a.txt", "cost is 3*4\n")
        self._write("b.txt", "3444\n")
        self.assertEqual(self._grep("3*4", regex=False), ["a.txt"])

    def test_content_walk_honours_whole_word(self):
        self._write("a.txt", "one cat here\n")
        self._write("b.txt", "concatenate\n")
        self.assertEqual(sorted(self._grep("cat")), ["a.txt", "b.txt"])
        self.assertEqual(self._grep("cat", word=True), ["a.txt"])


if __name__ == "__main__":
    unittest.main()
