"""
A move that does not happen leaves no trace (#982, #984).

Back / Forward and the ``directory_changed`` hook record a move only once the
new directory has been listed — the rule History already followed. Before, they
were committed ahead of the read, so:

- a jump that failed and went back (a favorite that is gone, a drive that is
  not there) pushed the old folder onto Back, emptied Forward, and fired the
  hook for a move that never happened (#982);
- a folder entered but not listable stayed on Back once you left it, and fired
  the hook both ways (#984);
- a favorite naming a file (#525) left the file's path on Back.

Back and Forward are provisional like any jump: an entry whose folder is gone
leaves the pane where it is, and the entry is dropped.

Run with: python -m pytest test/test_failed_navigation_history.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.favorites import FavoriteEntry  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


class FailedNavigationLeavesNoTrace(unittest.TestCase):
    def setUp(self):
        from puikit.backends import create_backend
        # realpath: on macOS the app lands on /private/var..., and these tests
        # compare the pane's path against it.
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        for name in ("old", "start", "next"):
            os.mkdir(os.path.join(self.tmp, name))
        with open(os.path.join(self.tmp, "next", "x.txt"), "w") as f:
            f.write("x")
        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.pane = self.app.active_pane()

        # A directory_changed hook, as a config would install one.
        self.events = []
        hooks = xefm_app._hooks
        real_get = hooks.get

        def fire(name, ctx, **kw):
            if name == "directory_changed":
                self.events.append((self._rel(kw["old_path"]),
                                    self._rel(kw["new_path"])))

        def get(name):
            return [fire] if name == "directory_changed" else real_get(name)

        for p in (patch.object(hooks, "fire", fire), patch.object(hooks, "get", get)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    # --- helpers ------------------------------------------------------------

    def _p(self, *parts):
        return os.path.join(self.tmp, *parts)

    def _rel(self, path):
        return None if path is None else os.path.relpath(str(path), self.tmp)

    def _go(self, *parts):
        self.app._go_to_dir(self.pane, Path(self._p(*parts)), None)
        self.app._settle_listings()

    def _back(self):
        self.app.go_back()
        self.app._settle_listings()

    def _forward(self):
        self.app.go_forward()
        self.app._settle_listings()

    def _where(self):
        return self._rel(self.pane["path"])

    def _stacks(self):
        return ([self._rel(p) for p in self.pane.get("_back", [])],
                [self._rel(p) for p in self.pane.get("_forward", [])])

    # --- #982: a jump that fails --------------------------------------------

    def test_a_failed_jump_leaves_back_forward_and_the_hook_alone(self):
        self._go("old")
        self._go("start")
        self._go("next")
        self._back()                                # start, with next on Forward
        stacks = self._stacks()
        self.assertEqual(stacks, ([".", "old"], ["next"]))
        shutil.rmtree(self._p("old"))
        self.events.clear()

        self.app._jump_to_favorite(FavoriteEntry("Old", self._p("old")))
        self.app._settle_listings()

        self.assertEqual(self._where(), "start")
        self.assertEqual(self._stacks(), stacks)
        self.assertEqual(self.events, [])

    def test_back_after_a_failed_jump_goes_where_the_pane_really_was(self):
        self._go("start")
        missing = self._p("gone")
        self.app._jump_to_favorite(FavoriteEntry("Gone", missing))
        self.app._settle_listings()
        self._go("next")
        self.assertEqual(self.events, [(".", "start"), ("start", "next")])

        self._back()
        self.assertEqual(self._where(), "start")
        self.assertFalse(self.pane.get("error"))

    def test_a_favorite_naming_a_file_is_one_move(self):
        """The jump to the file fails and becomes a jump to its folder; only
        that second one happened."""
        self._go("start")
        self.events.clear()

        self.app._jump_to_favorite(FavoriteEntry("X", self._p("next", "x.txt")))
        self.app._settle_listings()

        self.assertEqual(self._where(), "next")
        self.assertEqual(self.pane["files"][self.pane["focused_index"]].name, "x.txt")
        self.assertEqual(self.events, [("start", "next")])
        self._back()
        self.assertEqual(self._where(), "start")

    # --- #984: a folder entered but not listable ----------------------------

    def test_a_folder_that_could_not_be_listed_is_not_on_back(self):
        """Entered (the pane stays on it and says why), then left: Back goes to
        where the pane was before, as History has it."""
        self._go("start")
        self.events.clear()
        self._go("locked")                          # not there: cannot be listed
        self.assertEqual(self._where(), "locked")
        self.assertTrue(self.pane.get("error"))

        self._go("start")                           # Backspace
        self.assertEqual(self.events, [])
        self.assertNotIn(self._p("locked"), self.app._history)

        self._back()
        self.assertEqual(self._where(), ".")
        self.assertEqual(self._stacks(), ([], ["start"]))

    def test_leaving_an_unlistable_folder_for_another_is_one_move(self):
        self._go("start")
        self.events.clear()
        self._go("locked")
        self._go("next")
        self.assertEqual(self.events, [("start", "next")])
        self._back()
        self.assertEqual(self._where(), "start")

    # --- Back / Forward to a folder that is gone -----------------------------

    def test_back_to_a_folder_that_is_gone_stays_and_drops_it(self):
        self._go("old")
        self._go("start")
        self.pane["focused_index"] = 0
        shutil.rmtree(self._p("old"))
        self.events.clear()

        self._back()

        self.assertEqual(self._where(), "start")
        self.assertFalse(self.pane.get("error"))
        self.assertEqual(self._stacks(), (["."], []))
        self.assertEqual(self.events, [])
        # The next Back steps on past the entry that led nowhere.
        self._back()
        self.assertEqual(self._where(), ".")
        self.assertEqual(self._stacks(), ([], ["start"]))

    def test_forward_to_a_folder_that_is_gone_stays_and_drops_it(self):
        self._go("next")
        self._back()
        shutil.rmtree(self._p("next"))

        self._forward()

        self.assertEqual(self._where(), ".")
        self.assertEqual(self._stacks(), ([], []))

    def test_a_failed_step_does_not_make_the_next_move_a_step(self):
        """The step is spent with its listing: the next ordinary move pushes
        onto Back and clears Forward as usual."""
        self._go("old")
        self._go("start")
        self._go("next")
        self._back()                                # start, next on Forward
        shutil.rmtree(self._p("old"))
        self._back()                                # old is gone: stays

        self._go("next")
        self.assertEqual(self._stacks(), ([".", "start"], []))

    def test_back_to_a_folder_that_became_a_file_is_refused(self):
        self._go("old")
        self._go("start")
        os.rmdir(self._p("old"))
        with open(self._p("old"), "w") as f:
            f.write("x")

        self._back()

        self.assertEqual(self._where(), "start")
        self.assertEqual(self._stacks(), (["."], []))

    def test_two_quick_backs_step_twice(self):
        """The stacks move on the key, not on the listing, so a second press
        before the first lands steps on from there."""
        self._go("old")
        self._go("start")
        self.app.go_back()
        self.app.go_back()
        self.app._settle_listings()

        self.assertEqual(self._where(), ".")
        self.assertEqual(self._stacks(), ([], ["start", "old"]))
        self.assertEqual(self.events[-1], ("start", "."))


if __name__ == "__main__":
    unittest.main()
