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

    def __call__(self, text):
        self.seen.append(text)


class EditSelected(unittest.TestCase):
    def test_the_highlighted_row_is_handed_over(self):
        edits = Edits()
        d = FilterListDialog(["rg -l TODO", "git ls-files -m"], on_edit=edits)
        d.list.selected = 1
        d.edit_selected()
        self.assertEqual(edits.seen, ["git ls-files -m"])

    def test_the_label_not_the_value(self):
        edits = Edits()
        d = FilterListDialog([("id", "shown")], to_label=lambda v: v[1],
                             on_edit=edits)
        d.edit_selected()
        self.assertEqual(edits.seen, ["shown"])

    def test_with_no_row_matching_the_query_is_handed_over(self):
        edits = Edits()
        d = FilterListDialog(["rg -l TODO"], on_edit=edits)
        d.filter_edit.text = "fd -e py"
        d._refilter("fd -e py")
        self.assertEqual(d.filtered, [])
        d.edit_selected()
        self.assertEqual(edits.seen, ["fd -e py"])

    def test_without_a_hook_nothing_happens(self):
        d = FilterListDialog(["a"])
        d.edit_selected()           # no error, no hook


class KeyRouting(unittest.TestCase):
    def test_tab_edits(self):
        edits = Edits()
        d = FilterListDialog(["alpha", "beta"], on_edit=edits)
        d.list.selected = 1
        d.handle_event(_key("tab"))
        self.assertEqual(edits.seen, ["beta"])

    def test_tab_does_nothing_without_the_hook(self):
        d = FilterListDialog(["alpha"])
        d.handle_event(_key("tab"))
        self.assertEqual(d.filter_edit.text, "")

    def test_the_hint_offers_the_key_only_with_the_hook(self):
        self.assertIn("edit", FilterListDialog(["a"], on_edit=Edits()).hint())
        self.assertNotIn("edit", FilterListDialog(["a"]).hint())


if __name__ == "__main__":
    unittest.main()
