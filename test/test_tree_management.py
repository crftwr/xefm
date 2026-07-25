"""
Unit tests for tree flattening / expand-collapse in the ported DirectoryDiffView.

The PuiKit port replaced the old ``DirectoryDiffViewer`` internals: the visible
list is now built by ``_flatten(node, out)`` (respecting each node's
``is_expanded``) rather than a ``_flatten_tree`` that populated ``visible_nodes``
+ ``node_index_map``. These tests exercise that flattening directly — it's pure
(uses only the node), so a bare view instance is enough — covering the same
behaviour the old suite did, minus the removed ``node_index_map`` concept.

Run with: PYTHONPATH=.. pytest test/test_tree_management.py -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xefm.directory_diff_viewer import (  # noqa: E402
    TreeNode, DifferenceType, DirectoryDiffView,
)


def _node(name, depth, parent, is_dir=True, expanded=False,
          diff=DifferenceType.CONTAINS_DIFFERENCE):
    node = TreeNode(
        name=name, left_path=None, right_path=None, is_directory=is_dir,
        difference_type=diff, depth=depth, is_expanded=expanded,
        children=[], parent=parent,
    )
    if parent is not None:
        parent.children.append(node)
    return node


class TestTreeFlattening(unittest.TestCase):
    def setUp(self):
        # root/
        #   dir1/        (file1.txt, file2.txt)
        #   dir2/        (subdir/ (file3.txt))
        #   file4.txt
        self.root = _node("root", 0, None, expanded=True)
        self.dir1 = _node("dir1", 1, self.root)
        _node("file1.txt", 2, self.dir1, is_dir=False, diff=DifferenceType.IDENTICAL)
        _node("file2.txt", 2, self.dir1, is_dir=False, diff=DifferenceType.CONTENT_DIFFERENT)
        self.dir2 = _node("dir2", 1, self.root)
        self.subdir = _node("subdir", 2, self.dir2)
        _node("file3.txt", 3, self.subdir, is_dir=False, diff=DifferenceType.ONLY_LEFT)
        _node("file4.txt", 1, self.root, is_dir=False, diff=DifferenceType.IDENTICAL)

        # _flatten is pure (reads node.depth / is_expanded / children only), so a
        # bare instance without __init__ suffices.
        self.view = DirectoryDiffView.__new__(DirectoryDiffView)

    def _flatten(self):
        out = []
        self.view._flatten(self.root, out)
        return [n.name for n in out]

    def test_root_only_shows_top_level(self):
        # Root expanded, children collapsed: only the top-level entries, and the
        # root itself (depth 0) is never listed.
        self.assertEqual(self._flatten(), ["dir1", "dir2", "file4.txt"])

    def test_expanding_a_directory_reveals_its_children(self):
        self.dir1.is_expanded = True
        self.assertEqual(
            self._flatten(),
            ["dir1", "file1.txt", "file2.txt", "dir2", "file4.txt"])

    def test_nested_expansion(self):
        self.dir2.is_expanded = True
        self.assertEqual(self._flatten(), ["dir1", "dir2", "subdir", "file4.txt"])
        self.subdir.is_expanded = True
        self.assertEqual(
            self._flatten(),
            ["dir1", "dir2", "subdir", "file3.txt", "file4.txt"])

    def test_collapsing_hides_all_descendants(self):
        self.dir2.is_expanded = True
        self.subdir.is_expanded = True
        self.assertEqual(len(self._flatten()), 5)
        self.dir2.is_expanded = False  # collapse the ancestor
        self.assertEqual(self._flatten(), ["dir1", "dir2", "file4.txt"])

    def test_collapsed_root_shows_nothing(self):
        self.root.is_expanded = False
        self.assertEqual(self._flatten(), [])


if __name__ == "__main__":
    unittest.main()
