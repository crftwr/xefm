"""Removing a row from a searchable-list picker (issue #271).

Two halves, tested from both ends.

The **dialog** (``xefm.filter_list_dialog``) knows how a list is shown and
nothing about where it is stored: the highlighted value goes to ``on_remove``
and the row disappears only if that reports it was actually forgotten. So the
tests here cover the local edit — the row leaves both ``filtered`` and
``all_items`` (a re-filter must not resurrect it), the cursor holds its
*position* rather than its value, and an active query survives untouched —
plus the key routing, which is the delicate part: the picker's query field takes
every printable key, so the default Shift-Delete has to be claimed ahead of the
field while a plain Delete still edits the text.

The **owners** (``XeFMApp``) do the forgetting. The recent-directory history
keeps one entry per visit and the picker shows the de-duplicated view, so a
single row stands for every occurrence and all of them must go; the filter
history is a flat list, and its "clear filter" row is not a saved pattern at
all, which is what makes it survive the key with no special case in the dialog.

See xefm/filter_list_dialog.py, the ``filter_list`` context in xefm/actions.py,
and XeFMApp._forget_history_path / _forget_filter_pattern.

Run with: python -m pytest test/test_filter_list_remove.py -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit.event import Event, EventType  # noqa: E402

from xefm.actions import FILTER_LIST, registry  # noqa: E402
from xefm.app import XeFMApp, _FILTER_HISTORY_KEY  # noqa: E402
from xefm.filter_list_dialog import FilterListDialog  # noqa: E402


def _key(name, mods=()):
    return Event(type=EventType.KEY, key=name, modifiers=frozenset(mods))


class Removals:
    """Recorder standing in for the owner that does the forgetting."""

    def __init__(self, accept=True):
        self.seen = []
        self._accept = accept

    def __call__(self, value):
        self.seen.append(value)
        return self._accept


# --------------------------------------------------------------------------- #
# The dialog's local edit
# --------------------------------------------------------------------------- #

class RemoveSelected(unittest.TestCase):

    def test_row_goes_and_the_owner_sees_the_value(self):
        removals = Removals()
        d = FilterListDialog(["alpha", "beta", "gamma"], on_remove=removals)
        d.list.selected = 1

        self.assertTrue(d.remove_selected())
        self.assertEqual(removals.seen, ["beta"])
        self.assertEqual(d.list.items, ["alpha", "gamma"])
        self.assertEqual(d.filtered, ["alpha", "gamma"])

    def test_a_refused_removal_keeps_the_row(self):
        removals = Removals(accept=False)
        d = FilterListDialog(["alpha", "beta"], on_remove=removals)
        d.list.selected = 0

        self.assertFalse(d.remove_selected())
        self.assertEqual(removals.seen, ["alpha"])  # asked, and declined
        self.assertEqual(d.list.items, ["alpha", "beta"])

    def test_the_cursor_holds_its_position_so_repeats_walk_down(self):
        d = FilterListDialog(["a", "b", "c", "d"], on_remove=Removals())
        d.list.selected = 1

        d.remove_selected()
        self.assertEqual(d.list.selected, 1)   # "c" slid up under the cursor
        d.remove_selected()
        self.assertEqual(d.list.items, ["a", "d"])
        self.assertEqual(d.list.selected, 1)

    def test_removing_the_last_row_clamps_the_cursor(self):
        d = FilterListDialog(["a", "b"], on_remove=Removals())
        d.list.selected = 1

        d.remove_selected()
        self.assertEqual(d.list.selected, 0)

    def test_emptying_the_list_leaves_a_valid_cursor(self):
        d = FilterListDialog(["only"], on_remove=Removals())

        self.assertTrue(d.remove_selected())
        self.assertEqual(d.list.items, [])
        self.assertEqual(d.list.selected, 0)
        self.assertFalse(d.remove_selected())  # nothing left to take

    def test_an_active_query_survives_the_removal(self):
        d = FilterListDialog(["apple", "apricot", "banana"], on_remove=Removals())
        d.filter_edit.text = "ap"
        d._refilter("ap")
        d.list.selected = 0

        d.remove_selected()
        self.assertEqual(d.list.items, ["apricot"])
        self.assertEqual(d.filter_edit.text, "ap")  # not reset by the edit

    def test_a_removed_row_does_not_come_back_on_a_wider_query(self):
        """The value leaves ``all_items`` too — otherwise widening the query
        (which re-filters from ``all_items``) would resurrect it."""
        d = FilterListDialog(["apple", "apricot", "banana"], on_remove=Removals())
        d.filter_edit.text = "ap"
        d._refilter("ap")
        d.list.selected = 0
        d.remove_selected()

        d._refilter("")
        self.assertEqual(d.list.items, ["apricot", "banana"])

    def test_without_the_hook_nothing_is_removable(self):
        d = FilterListDialog(["alpha", "beta"])

        self.assertFalse(d.remove_selected())
        self.assertEqual(d.list.items, ["alpha", "beta"])


# --------------------------------------------------------------------------- #
# Key routing — the query field competes for the same keys
# --------------------------------------------------------------------------- #

class RemoveKey(unittest.TestCase):

    def test_registered_in_its_own_context_on_shift_delete(self):
        action = registry.resolve(FILTER_LIST, "remove_list_item")
        self.assertIsNotNone(action)
        self.assertEqual(action.resolved_default_keys(), ("Shift-DELETE",))

    def test_the_name_is_not_bound_in_the_file_list(self):
        """A generic name, but scoped: the filer must not answer it — there
        ``remove``-shaped keys mean files on disk."""
        self.assertIsNone(registry.resolve("filer", "remove_list_item"))

    def test_shift_delete_removes_the_row(self):
        removals = Removals()
        d = FilterListDialog(["alpha", "beta"], on_remove=removals)
        d.list.selected = 0

        d.handle_event(_key("delete", ("shift",)))
        self.assertEqual(removals.seen, ["alpha"])
        self.assertEqual(d.list.items, ["beta"])

    def test_plain_delete_still_edits_the_query(self):
        removals = Removals()
        d = FilterListDialog(["alpha", "beta"], on_remove=removals)

        d.handle_event(_key("delete"))
        self.assertEqual(removals.seen, [])
        self.assertEqual(d.list.items, ["alpha", "beta"])

    def test_shift_delete_is_inert_without_the_hook(self):
        d = FilterListDialog(["alpha", "beta"])

        d.handle_event(_key("delete", ("shift",)))
        self.assertEqual(d.list.items, ["alpha", "beta"])


class Hint(unittest.TestCase):

    def test_the_remove_key_is_named_when_removal_is_wired(self):
        hint = FilterListDialog(["a"], on_remove=Removals()).hint()
        self.assertIn("remove", hint)
        self.assertIn("Shift-Del", hint)  # display-formatted, as the footer does

    def test_a_declared_list_offers_no_remove_key(self):
        hint = FilterListDialog(["a"]).hint()
        self.assertNotIn("remove", hint)
        self.assertIn("Esc cancel", hint)


# --------------------------------------------------------------------------- #
# The owners: what "forgetting" means for each list
# --------------------------------------------------------------------------- #

class FakeState:
    """Stands in for the state manager: records what was persisted."""

    def __init__(self, filter_history=()):
        self.state = {_FILTER_HISTORY_KEY: list(filter_history)}
        self.recent = None

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def set_state(self, key, value, *a, **kw):
        self.state[key] = value
        return True

    def save_recent_directories(self, dirs, max_count=50):
        self.recent = list(dirs)
        return True


class FakeApp:
    """The slice of ``XeFMApp`` the forget methods touch, so they can be
    exercised without building a window."""

    def __init__(self, history=(), filter_history=()):
        self._history = list(history)
        self.state_manager = FakeState(filter_history)
        self.logged = []

    log_info = lambda self, msg: self.logged.append(msg)  # noqa: E731
    _recent_dirs_most_recent_first = XeFMApp._recent_dirs_most_recent_first
    _filter_history = XeFMApp._filter_history
    _forget_history_path = XeFMApp._forget_history_path
    _forget_filter_pattern = XeFMApp._forget_filter_pattern


class ForgetHistoryPath(unittest.TestCase):

    def test_every_occurrence_goes(self):
        """One visited directory can sit in ``_history`` many times; the picker
        shows it once, so removing that row must clear all of them — otherwise
        the row stays on screen, apparently untouched."""
        app = FakeApp(history=["/a", "/b", "/a", "/c", "/a"])

        self.assertTrue(app._forget_history_path("/a"))
        self.assertEqual(app._history, ["/b", "/c"])

    def test_persisted_immediately_not_at_quit(self):
        app = FakeApp(history=["/a", "/b"])

        app._forget_history_path("/a")
        self.assertEqual(app.state_manager.recent, ["/b"])

    def test_an_unknown_path_reports_nothing_removed(self):
        app = FakeApp(history=["/a"])

        self.assertFalse(app._forget_history_path("/nope"))
        self.assertEqual(app._history, ["/a"])
        self.assertIsNone(app.state_manager.recent)  # nothing written either


class ForgetFilterPattern(unittest.TestCase):

    def test_the_pattern_goes_and_is_persisted(self):
        app = FakeApp(filter_history=["*.py", "*.txt"])

        self.assertTrue(app._forget_filter_pattern("*.py"))
        self.assertEqual(app.state_manager.state[_FILTER_HISTORY_KEY], ["*.txt"])

    def test_the_clear_filter_row_is_not_a_saved_pattern(self):
        """The Filter picker's first row is a sentinel, not history — so it
        matches nothing here, ``on_remove`` reports False, and the dialog keeps
        the row with no special case of its own."""
        app = FakeApp(filter_history=["*.py"])

        self.assertFalse(app._forget_filter_pattern(XeFMApp._FILTER_CLEAR))
        self.assertEqual(app.state_manager.state[_FILTER_HISTORY_KEY], ["*.py"])

    def test_an_unknown_pattern_reports_nothing_removed(self):
        app = FakeApp(filter_history=["*.py"])

        self.assertFalse(app._forget_filter_pattern("*.md"))


if __name__ == "__main__":
    unittest.main()
