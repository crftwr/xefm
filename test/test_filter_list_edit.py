"""Editing a row before using it, in a searchable-list picker.

The command history (``import_list_from_command``) is a list of things to
*run*: Enter runs a row as it is, so changing one first needs a key of its own —
``edit_list_item``, Tab by default. It hands the owner the highlighted row's
text, or the query when no row matches, and the owner opens it in a field.
That is also how to run a new command that happens to match an old one, which
Enter would otherwise pick.

See xefm/filter_list_dialog.py and the ``filter_list`` context in
xefm/actions.py.

Run with: python -m pytest test/test_filter_list_edit.py -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit.event import Event, EventType  # noqa: E402

from xefm.filter_list_dialog import FilterListDialog  # noqa: E402


def _key(name, mods=()):
    return Event(type=EventType.KEY, key=name, modifiers=frozenset(mods))


class Edits:
    def __init__(self):
        self.seen = []

    def __call__(self, value, query):
        self.seen.append((value, query))


class EditSelected(unittest.TestCase):
    def test_the_highlighted_row_is_handed_over(self):
        edits = Edits()
        d = FilterListDialog(["rg -l TODO", "git ls-files -m"], on_edit=edits)
        d.list.selected = 1
        d.edit_selected()
        self.assertEqual(edits.seen, [("git ls-files -m", "")])

    def test_the_value_not_its_label(self):
        # A row may draw something other than the text it stands for.
        edits = Edits()
        d = FilterListDialog([("id", "shown")], to_label=lambda v: v[1],
                             on_edit=edits)
        d.edit_selected()
        self.assertEqual(edits.seen, [(("id", "shown"), "")])

    def test_with_no_row_matching_the_query_is_handed_over(self):
        edits = Edits()
        d = FilterListDialog(["rg -l TODO"], on_edit=edits)
        d.filter_edit.text = "fd -e py"
        d._refilter("fd -e py")
        self.assertEqual(d.filtered, [])
        d.edit_selected()
        self.assertEqual(edits.seen, [(None, "fd -e py")])

    def test_without_a_hook_nothing_happens(self):
        d = FilterListDialog(["a"])
        d.edit_selected()           # no error, no hook


class KeyRouting(unittest.TestCase):
    def test_tab_edits(self):
        edits = Edits()
        d = FilterListDialog(["alpha", "beta"], on_edit=edits)
        d.list.selected = 1
        d.handle_event(_key("tab"))
        self.assertEqual(edits.seen, [("beta", "")])

    def test_tab_does_nothing_without_the_hook(self):
        d = FilterListDialog(["alpha"])
        d.handle_event(_key("tab"))
        self.assertEqual(d.filter_edit.text, "")

    def test_the_hint_offers_the_key_only_with_the_hook(self):
        self.assertIn("edit", FilterListDialog(["a"], on_edit=Edits()).hint())
        self.assertNotIn("edit", FilterListDialog(["a"]).hint())


class FilterPrompt(unittest.TestCase):
    """The ';' Filter prompt: a row's *text* is what Tab opens, which for a
    defined filter is its name, not the label it draws."""

    def setUp(self):
        import shutil  # noqa: F401 — used in tearDown
        import tempfile
        from puikit.backends import create_backend
        from xefm import app as xefm_app, filters
        from xefm.state_manager import XeFMStateManager
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(
            self.b, self.tmp, self.tmp, left_provided=True, right_provided=True,
            state_manager=XeFMStateManager(
                db_path=os.path.join(self.state_dir, "state.db")))
        self.app.file_monitor.stop_monitoring()
        self.app._settle_listings()
        filters.clear()
        filters.register("big", label="Big files", match=lambda e: True)
        self.app._record_filter_pattern("*.py")

    def tearDown(self):
        import shutil
        from xefm import filters
        filters.clear()
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def _tab_on(self, label=None, query=""):
        """Open the prompt, highlight the row drawn as ``label`` (or type
        ``query``), press Tab, and return the field it opens."""
        from xefm.filter_list_dialog import FilterListDialog
        from xefm.input_dialog import InputDialog
        self.app.enter_filter()
        dialog = self.app.panel._layers[-1].widget
        self.assertIsInstance(dialog, FilterListDialog)
        if query:
            dialog.filter_edit.text = query
            dialog._refilter(query)
        else:
            labels = [dialog.to_label(v) for v in dialog.filtered]
            dialog.list.selected = labels.index(label)
        dialog.handle_event(_key("tab"))
        field = self.app.panel._layers[-1].widget
        self.assertIsInstance(field, InputDialog)
        return field.edit.text

    def test_a_remembered_pattern(self):
        self.assertEqual(self._tab_on("*.py"), "*.py")

    def test_a_defined_filter_opens_as_its_name(self):
        self.assertEqual(self._tab_on("Big files"), "big")

    def test_the_clear_row_opens_empty(self):
        self.assertEqual(self._tab_on(self.app._FILTER_CLEAR), "")

    def test_text_that_matches_nothing_opens_as_typed(self):
        self.assertEqual(self._tab_on(query="*.pyw zz"), "*.pyw zz")


if __name__ == "__main__":
    unittest.main()
