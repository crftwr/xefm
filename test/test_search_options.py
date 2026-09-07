"""What the search dialog's options mean (xefm.search_options), and the two
walks honouring them (xefm.app).

The options are two kinds of thing and the tests are split the same way: how the
query is *read* (case, regex vs literal), which can be derived from the query
itself, and what is *walked* (subfolders), which cannot. Issue #312.

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


class SmartCase(unittest.TestCase):
    def test_all_lowercase_ignores_case(self):
        self.assertFalse(so.case_sensitive("smart", "todo"))

    def test_a_capital_makes_it_exact(self):
        self.assertTrue(so.case_sensitive("smart", "TODO"))
        self.assertTrue(so.case_sensitive("smart", "toDo"))

    def test_non_cased_text_stays_insensitive(self):
        # Japanese has no case, so a CJK query must not trip the rule.
        self.assertFalse(so.case_sensitive("smart", "検索"))

    def test_explicit_settings_ignore_the_query(self):
        self.assertTrue(so.case_sensitive("sensitive", "todo"))
        self.assertFalse(so.case_sensitive("insensitive", "TODO"))


class Metacharacters(unittest.TestCase):
    def test_plain_words_hold_none(self):
        self.assertFalse(so.has_meta("needle"))
        self.assertFalse(so.has_meta("let clip"))

    def test_regex_syntax_is_recognized(self):
        for query in (".", "a.*b", "^start", "end$", "a|b", "[abc]", "x{2}",
                      "(group)", "\\s"):
            self.assertTrue(so.has_meta(query), query)

    def test_the_chip_lights_when_the_query_starts_to_matter(self):
        chip = dict((o.name, o) for o in so.SEARCH_OPTIONS)[so.PATTERN]
        self.assertFalse(chip.is_active("regex", "needle"))
        self.assertTrue(chip.is_active("regex", "need.e"))
        self.assertTrue(chip.is_active("literal", "needle"))


class ContentRegex(unittest.TestCase):
    def test_regex_mode_keeps_metacharacters_live(self):
        self.assertTrue(so.content_regex("a.c", case="smart", pattern="regex")
                        .search("abc"))

    def test_literal_mode_matches_the_characters_typed(self):
        pattern = so.content_regex("a.c", case="smart", pattern="literal")
        self.assertIsNone(pattern.search("abc"))
        self.assertTrue(pattern.search("a.c"))

    def test_literal_mode_cannot_raise_on_a_broken_pattern(self):
        # The other half of #305: "C++(" is a search, not a syntax error.
        self.assertTrue(so.content_regex("C++(", case="smart", pattern="literal")
                        .search("void C++( x"))

    def test_case_follows_the_option(self):
        self.assertTrue(so.content_regex("todo", case="smart", pattern="regex")
                        .search("TODO"))
        self.assertIsNone(so.content_regex("TODO", case="smart", pattern="regex")
                          .search("todo"))
        self.assertTrue(so.content_regex("TODO", case="insensitive", pattern="regex")
                        .search("todo"))


class FilenameMatcher(unittest.TestCase):
    def test_smart_case_lowercase_matches_either(self):
        match = so.filename_matcher("readme*", case="smart")
        self.assertTrue(match("README.md"))
        self.assertTrue(match("readme.md"))

    def test_smart_case_capital_is_exact(self):
        match = so.filename_matcher("README*", case="smart")
        self.assertTrue(match("README.md"))
        self.assertFalse(match("readme.md"))

    def test_exact_glob_rule_survives(self):
        # Issue #231: matched against the whole name, wildcards are explicit.
        match = so.filename_matcher("report", case="smart")
        self.assertTrue(match("report"))
        self.assertFalse(match("report.txt"))


class Declarations(unittest.TestCase):
    def test_pattern_is_content_only(self):
        options = OptionSet(so.SEARCH_OPTIONS)
        names = [o.name for o in options.visible("filename")]
        self.assertNotIn(so.PATTERN, names)
        self.assertIn(so.PATTERN, [o.name for o in options.visible("content")])

    def test_defaults_change_nothing_that_shipped(self):
        # Content search has always been a case-insensitive regex over the whole
        # tree; #312 makes that visible, it does not change it.
        options = OptionSet(so.SEARCH_OPTIONS)
        self.assertEqual(options[so.PATTERN], "regex")
        self.assertEqual(options[so.CASE], "smart")
        self.assertIs(options[so.SUBDIRS], True)

    def test_accelerators_are_unique(self):
        accels = [o.accel for o in so.SEARCH_OPTIONS]
        self.assertEqual(len(accels), len(set(accels)))

    def test_only_the_scope_option_is_transient(self):
        options = OptionSet(so.SEARCH_OPTIONS)
        options.set(so.CASE, "sensitive")
        options.set(so.SUBDIRS, False)
        options.reset_transient()
        self.assertEqual(options[so.CASE], "sensitive")
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

    def _grep(self, query, *, case="smart", pattern="regex", **kw):
        app = _bare_app()
        regex = so.content_regex(query, case=case, pattern=pattern)
        return [h["path"].name for h in app._iter_content_matches(
            Path(self.tmp), regex, threading.Event(), **kw)]

    def test_filename_walk_defaults_to_smart_case(self):
        self._write("README.md")
        self.assertEqual(self._names("readme*"), ["README.md"])
        self.assertEqual(self._names("README*"), ["README.md"])

    def test_filename_walk_can_be_forced_sensitive(self):
        self._write("README.md")
        self.assertEqual(self._names("readme*", case="sensitive"), [])

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

    def test_content_walk_honours_smart_case(self):
        self._write("a.txt", "TODO: fix\n")
        self.assertEqual(self._grep("todo"), ["a.txt"])
        self.assertEqual(self._grep("TODO"), ["a.txt"])
        self._write("b.txt", "todo: fix\n")
        self.assertEqual(self._grep("TODO"), ["a.txt"])   # capital means exact

    def test_content_walk_honours_a_literal_query(self):
        self._write("a.txt", "cost is 3*4\n")
        self._write("b.txt", "3444\n")
        self.assertEqual(self._grep("3*4", pattern="literal"), ["a.txt"])


if __name__ == "__main__":
    unittest.main()
