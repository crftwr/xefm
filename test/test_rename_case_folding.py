"""Renames on a disk that folds case and on one that does not (#869, #873).

``xefm.rename_check`` asks the disk whether two names that differ only in case
are one file. These tests run every rename path against both kinds of disk on
any host, using a small in-memory disk that either folds case (Windows, macOS by
default) or does not (Linux by default), and whose ``rename`` replaces an
existing target as ``rename(2)`` does — so a plan that would lose a file shows
up as a lost file. The real-disk tests at the end run on whichever kind the host
has.

Run with: python -m pytest test/test_rename_case_folding.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm.batch_rename_dialog import compute_preview  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.rename_check import folding_dirs, is_itself  # noqa: E402
from xefm.rename_in_editor import apply_plan, parse_plan  # noqa: E402


class _Disk:
    """One directory: stored name -> content, looked up with or without case."""

    def __init__(self, folds, *names):
        self.folds = folds
        self.files = {name: name for name in names}

    def find(self, name):
        if name in self.files:
            return name
        if self.folds:
            for stored in self.files:
                if stored.casefold() == name.casefold():
                    return stored
        return None

    def contents(self):
        """name -> the name the file was created with."""
        return dict(self.files)


class _Dir:
    def __init__(self, disk):
        self.disk = disk

    def __truediv__(self, name):
        return _Path(self.disk, name)

    def __str__(self):
        return "/disk"


class _Path:
    def __init__(self, disk, name):
        self.disk = disk
        self.name = name
        self.parent = _Dir(disk)

    def __str__(self):
        return f"/disk/{self.name}"

    def exists(self):
        return self.disk.find(self.name) is not None

    def samefile(self, other):
        mine, theirs = self.disk.find(self.name), other.disk.find(other.name)
        if mine is None or theirs is None:
            raise FileNotFoundError(self.name if mine is None else other.name)
        return mine == theirs

    def rename(self, dst):
        src = self.disk.find(self.name)
        if src is None:
            raise FileNotFoundError(self.name)
        content = self.disk.files.pop(src)
        taken = self.disk.find(dst.name)
        if taken is not None:
            del self.disk.files[taken]  # rename(2) replaces the target
        self.disk.files[dst.name] = content


def _entries(disk, *names):
    return [_Path(disk, name) for name in names]


def _edit(disk, selected, text):
    """Rename in Editor over ``selected``: parse the edited ``text`` and apply
    it when it is a plan; returns the plan's errors."""
    plan = parse_plan(_entries(disk, *selected), text)
    if plan.ok:
        renamed, errors = apply_plan(plan)
        assert not errors, errors
    return plan.errors


class FoldingDirs(unittest.TestCase):
    def test_each_disk_is_told_apart(self):
        self.assertEqual(folding_dirs(_entries(_Disk(True, "a.txt"), "a.txt")),
                         {"/disk"})
        self.assertEqual(folding_dirs(_entries(_Disk(False, "a.txt"), "a.txt")),
                         set())

    def test_a_disk_no_name_can_settle_counts_as_folding(self):
        disk = _Disk(False, "1", "2")
        self.assertEqual(folding_dirs(_entries(disk, "1", "2")), {"/disk"})

    def test_is_itself_asks_the_disk(self):
        self.assertTrue(is_itself(_Path(_Disk(True, "foo.txt"), "foo.txt"), "Foo.txt"))
        disk = _Disk(False, "foo.txt", "Foo.txt")
        self.assertFalse(is_itself(_Path(disk, "foo.txt"), "Foo.txt"))


class RenameInEditorWhereCaseFolds(unittest.TestCase):
    def test_a_name_freed_in_another_case_is_taken_869(self):
        disk = _Disk(True, "a.txt", "B.txt")
        self.assertEqual(_edit(disk, ["a.txt", "B.txt"], "b.txt\nz.txt\n"), [])
        self.assertEqual(disk.contents(), {"b.txt": "a.txt", "z.txt": "B.txt"})

    def test_a_case_only_rename_goes_through(self):
        disk = _Disk(True, "foo.txt", "bar.txt")
        self.assertEqual(_edit(disk, ["foo.txt"], "Foo.txt\n"), [])
        self.assertEqual(disk.contents(), {"Foo.txt": "foo.txt", "bar.txt": "bar.txt"})

    def test_a_file_outside_the_batch_in_another_case_is_refused(self):
        disk = _Disk(True, "a.txt", "b.txt")
        self.assertEqual(_edit(disk, ["a.txt"], "B.txt\n"),
                         ["line 1 (a.txt): B.txt already exists"])
        self.assertEqual(disk.contents(), {"a.txt": "a.txt", "b.txt": "b.txt"})

    def test_two_lines_differing_only_in_case_are_refused(self):
        disk = _Disk(True, "a.txt", "b.txt")
        errors = _edit(disk, ["a.txt", "b.txt"], "X.txt\nx.txt\n")
        self.assertEqual(len(errors), 2)
        self.assertEqual(disk.contents(), {"a.txt": "a.txt", "b.txt": "b.txt"})

    def test_a_swap_in_another_case(self):
        disk = _Disk(True, "a.txt", "b.txt")
        self.assertEqual(_edit(disk, ["a.txt", "b.txt"], "B.txt\nA.txt\n"), [])
        self.assertEqual(disk.contents(), {"B.txt": "a.txt", "A.txt": "b.txt"})


class RenameInEditorWhereCaseMatters(unittest.TestCase):
    def test_a_separate_file_in_another_case_is_not_overwritten_873(self):
        disk = _Disk(False, "foo.txt", "Foo.txt")
        self.assertEqual(_edit(disk, ["foo.txt"], "Foo.txt\n"),
                         ["line 1 (foo.txt): Foo.txt already exists"])
        self.assertEqual(disk.contents(), {"foo.txt": "foo.txt", "Foo.txt": "Foo.txt"})

    def test_a_batch_file_in_another_case_moving_away_frees_its_name(self):
        disk = _Disk(False, "foo.txt", "Foo.txt")
        self.assertEqual(_edit(disk, ["foo.txt", "Foo.txt"], "Foo.txt\nbar.txt\n"), [])
        self.assertEqual(disk.contents(), {"Foo.txt": "foo.txt", "bar.txt": "Foo.txt"})

    def test_a_swap_of_two_names_differing_only_in_case(self):
        disk = _Disk(False, "foo.txt", "Foo.txt")
        self.assertEqual(_edit(disk, ["foo.txt", "Foo.txt"], "Foo.txt\nfoo.txt\n"), [])
        self.assertEqual(disk.contents(), {"Foo.txt": "foo.txt", "foo.txt": "Foo.txt"})

    def test_two_lines_differing_only_in_case_are_two_files(self):
        disk = _Disk(False, "a.txt", "b.txt")
        self.assertEqual(_edit(disk, ["a.txt", "b.txt"], "X.txt\nx.txt\n"), [])
        self.assertEqual(disk.contents(), {"X.txt": "a.txt", "x.txt": "b.txt"})

    def test_a_name_differing_from_a_freed_one_in_case_is_free_anyway(self):
        disk = _Disk(False, "a.txt", "B.txt")
        self.assertEqual(_edit(disk, ["a.txt", "B.txt"], "b.txt\nz.txt\n"), [])
        self.assertEqual(disk.contents(), {"b.txt": "a.txt", "z.txt": "B.txt"})


class ApplyPlanOrder(unittest.TestCase):
    """``apply_plan`` handed the #869 plan directly: ``a.txt`` must not reach
    ``b.txt`` while ``B.txt`` is still there, where the disk folds case."""

    def test_the_freed_name_is_reached_by_way_of_a_temporary_name(self):
        disk = _Disk(True, "a.txt", "B.txt")
        a, b = _entries(disk, "a.txt", "B.txt")
        plan = parse_plan([a, b], "b.txt\nz.txt\n")
        plan.renames.reverse()  # B.txt -> z.txt last: the order that lost a.txt
        renamed, errors = apply_plan(plan)
        self.assertEqual(errors, [])
        self.assertEqual(disk.contents(), {"b.txt": "a.txt", "z.txt": "B.txt"})


class BatchRenameDialogRows(unittest.TestCase):
    def rows(self, disk, search, replace):
        return {r["original"]: r for r in
                compute_preview(_entries(disk, *disk.files), search, replace)}

    def test_case_only_differences_collide_only_where_case_folds(self):
        # Dropping the digit lands X1.txt on X.txt and x2.txt on x.txt: one
        # file where case folds, so the second rename would replace the first.
        for folds, expect in ((True, True), (False, False)):
            disk = _Disk(folds, "X1.txt", "x2.txt")
            rows = self.rows(disk, r"\d", "")
            self.assertEqual(rows["X1.txt"]["conflict"], expect, folds)
            self.assertEqual(rows["x2.txt"]["conflict"], expect, folds)

    def test_one_exact_name_collides_on_either_disk(self):
        for folds in (True, False):
            rows = self.rows(_Disk(folds, "a1.txt", "a2.txt"), r"\d", "")
            self.assertTrue(all(r["conflict"] for r in rows.values()), folds)


def _host_folds_case() -> bool:
    tmp = tempfile.mkdtemp()
    try:
        open(os.path.join(tmp, "a"), "w").close()
        return os.path.exists(os.path.join(tmp, "A"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_HOST_FOLDS = _host_folds_case()


class _RealDir(unittest.TestCase):
    names = ()

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        for name in self.names:
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write(name)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, selected, text):
        files = [Path(os.path.join(self.tmp, name)) for name in selected]
        plan = parse_plan(files, text)
        if plan.ok:
            self.assertEqual(apply_plan(plan)[1], [])
        return plan.errors

    def contents(self):
        out = {}
        for name in os.listdir(self.tmp):
            with open(os.path.join(self.tmp, name)) as f:
                out[name] = f.read()
        return out


@unittest.skipUnless(_HOST_FOLDS, "needs a disk that folds case")
class RealDiskWhereCaseFolds(_RealDir):
    names = ("a.txt", "B.txt")

    def test_a_name_freed_in_another_case_is_taken_869(self):
        self.assertEqual(self.edit(["a.txt", "B.txt"], "b.txt\nz.txt\n"), [])
        self.assertEqual(self.contents(), {"b.txt": "a.txt", "z.txt": "B.txt"})


@unittest.skipIf(_HOST_FOLDS, "needs a disk where case matters")
class RealDiskWhereCaseMatters(_RealDir):
    names = ("foo.txt", "Foo.txt")

    def test_a_separate_file_in_another_case_is_not_overwritten_873(self):
        self.assertEqual(self.edit(["foo.txt"], "Foo.txt\n"),
                         ["line 1 (foo.txt): Foo.txt already exists"])
        self.assertEqual(self.contents(), {"foo.txt": "foo.txt", "Foo.txt": "Foo.txt"})


if __name__ == "__main__":
    unittest.main()
