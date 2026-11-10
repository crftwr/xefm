"""What a rename may land on (xefm.rename_check): #867, #869, #873, #875.

Every rename path runs against a small in-memory directory that can be any of
the four kinds the check has to tell apart:

- whether the disk ignores case (Windows, macOS by default) or not (Linux by
  default, a case-sensitive APFS volume, S3);
- whether the backend can identify a directory entry (``entry_identity``: the
  local disk) or only list the directory (SSH, S3).

Its ``rename`` replaces an existing target as ``rename(2)`` does, so a check
that lets the wrong rename through shows up as a lost file. Each entry holds the
name it was created with, so the tests can tell which ended up where. The
real-disk tests at the end run on whichever kind of disk the host has.

Run with: python -m pytest test/test_rename_entry_check.py -v
"""

import itertools
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm.batch_rename_dialog import compute_preview  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.rename_check import obstacle  # noqa: E402
from xefm.rename_in_editor import apply_plan, parse_plan  # noqa: E402

_KINDS = {
    # name: (ignores case, identifies entries)
    "local, case ignored": (True, True),
    "local, case kept": (False, True),
    "remote, case ignored": (True, False),
    "remote, case kept": (False, False),
}


class _Disk:
    """One directory. ``entries``: stored name -> [content, inode, link target
    or None]."""

    _inodes = itertools.count(1)

    def __init__(self, ignores_case, identifies, *names, links=()):
        self.ignores_case = ignores_case
        self.identifies = identifies
        self.entries = {n: [n, next(self._inodes), None] for n in names}
        for name, target in links:
            self.entries[name] = [f"->{target}", next(self._inodes), target]

    def find(self, name):
        if name in self.entries:
            return name
        if self.ignores_case:
            for stored in self.entries:
                if stored.casefold() == name.casefold():
                    return stored
        return None

    def resolves(self, name):
        stored = self.find(name)
        if stored is None:
            return False
        target = self.entries[stored][2]
        return target is None or self.find(target) is not None

    def contents(self):
        """name -> what the entry holds: the name it was created with, or
        ``->target`` for a symlink."""
        return {n: e[0] for n, e in self.entries.items()}

    def path(self, name):
        return _Path(self, name)


class _Stat:
    def __init__(self, ino):
        self.st_dev, self.st_ino = 1, ino


class _Dir:
    def __init__(self, disk):
        self.disk = disk

    def __truediv__(self, name):
        return _Path(self.disk, name)

    def iterdir(self):
        return [_Path(self.disk, n) for n in list(self.disk.entries)]

    def __str__(self):
        return "/disk"


class _Path:
    def __init__(self, disk, name):
        self.disk = disk
        self.name = name
        self.parent = _Dir(disk)

    def __str__(self):
        return f"/disk/{self.name}"

    def supports(self, capability):
        return capability == "entry_identity" and self.disk.identifies

    def exists(self):
        return self.disk.resolves(self.name)

    def is_symlink(self):
        stored = self.disk.find(self.name)
        return stored is not None and self.disk.entries[stored][2] is not None

    def lstat(self):
        stored = self.disk.find(self.name)
        if stored is None:
            raise FileNotFoundError(self.name)
        return _Stat(self.disk.entries[stored][1])

    def rename(self, dst):
        src = self.disk.find(self.name)
        if src is None:
            raise FileNotFoundError(self.name)
        entry = self.disk.entries.pop(src)
        taken = self.disk.find(dst.name)
        if taken is not None:
            del self.disk.entries[taken]  # rename(2) replaces the target
        self.disk.entries[dst.name] = entry


def _edit(disk, selected, text):
    """Rename in Editor over ``selected``: parse the edited ``text`` and apply it
    when it is a plan; returns the plan's errors."""
    plan = parse_plan([disk.path(n) for n in selected], text)
    if plan.ok:
        renamed, errors = apply_plan(plan)
        assert not errors, errors
    return plan.errors


def _prompt(disk, name, new):
    """The rename prompt: refused (True) or renamed."""
    entry = disk.path(name)
    if obstacle(entry, new):
        return True
    entry.rename(entry.parent / new)
    return False


def _rows(disk, names, search, replace):
    return {r["original"]: r for r in
            compute_preview([disk.path(n) for n in names], search, replace)}


class _EveryKind(unittest.TestCase):
    def kinds(self, **only):
        for label, (ignores, identifies) in _KINDS.items():
            if only.get("ignores_case", ignores) != ignores:
                continue
            with self.subTest(label):
                yield ignores, identifies


class CaseOnlyRename(_EveryKind):
    """``foo.txt -> Foo.txt`` is the file itself wherever the disk ignores case,
    on every backend (#867, and SSH, which the old samefile check refused)."""

    def test_the_prompt(self):
        for kind in self.kinds():
            disk = _Disk(*kind, "foo.txt", "bar.txt")
            self.assertFalse(_prompt(disk, "foo.txt", "Foo.txt"))
            self.assertEqual(disk.contents(), {"Foo.txt": "foo.txt", "bar.txt": "bar.txt"})

    def test_rename_in_editor(self):
        for kind in self.kinds():
            disk = _Disk(*kind, "foo.txt")
            self.assertEqual(_edit(disk, ["foo.txt"], "Foo.txt\n"), [])
            self.assertEqual(disk.contents(), {"Foo.txt": "foo.txt"})

    def test_the_batch_dialog(self):
        for kind in self.kinds():
            rows = _rows(_Disk(*kind, "foo.txt", "bar.txt"), ["foo.txt", "bar.txt"],
                         "^foo", "Foo")
            self.assertFalse(rows["foo.txt"]["conflict"])


class AnotherEntryUnderTheNewName(_EveryKind):
    """Where case matters, ``Foo.txt`` beside ``foo.txt`` is another entry — a
    file (#873), a symlink, or the file ``foo.txt`` links to (#875) — and is
    never replaced."""

    CASES = {
        "a separate file": dict(names=("foo.txt", "Foo.txt")),
        "a symlink to it": dict(names=("foo.txt",), links=(("Foo.txt", "foo.txt"),)),
        "the file it links to": dict(names=("Foo.txt",), links=(("foo.txt", "Foo.txt"),)),
    }

    def each(self):
        for label, case in self.CASES.items():
            for kind in self.kinds(ignores_case=False):
                with self.subTest(label):
                    yield _Disk(*kind, *case["names"], links=case.get("links", ()))

    def test_the_prompt(self):
        for disk in self.each():
            before = disk.contents()
            self.assertTrue(_prompt(disk, "foo.txt", "Foo.txt"))
            self.assertEqual(disk.contents(), before)

    def test_rename_in_editor(self):
        for disk in self.each():
            before = disk.contents()
            self.assertEqual(_edit(disk, ["foo.txt"], "Foo.txt\n"),
                             ["line 1 (foo.txt): Foo.txt already exists"])
            self.assertEqual(disk.contents(), before)

    def test_the_batch_dialog(self):
        for disk in self.each():
            rows = _rows(disk, ["foo.txt"], "^foo", "Foo")
            self.assertTrue(rows["foo.txt"]["conflict"])

    def test_a_dangling_symlink_is_an_entry_too(self):
        for kind in self.kinds():
            disk = _Disk(*kind, "a.txt", links=(("b.txt", "nowhere"),))
            self.assertTrue(_prompt(disk, "a.txt", "b.txt"))
            self.assertEqual(_edit(disk, ["a.txt"], "b.txt\n"),
                             ["line 1 (a.txt): b.txt already exists"])
            self.assertIn("b.txt", disk.contents())


class NamesTheBatchFrees(_EveryKind):
    def test_a_name_freed_in_another_case_is_taken_869(self):
        for kind in self.kinds():
            disk = _Disk(*kind, "a.txt", "B.txt")
            self.assertEqual(_edit(disk, ["a.txt", "B.txt"], "b.txt\nz.txt\n"), [])
            self.assertEqual(disk.contents(), {"b.txt": "a.txt", "z.txt": "B.txt"})

    def test_a_file_outside_the_batch_is_not_freed(self):
        # Where case matters b.txt is its own file; B.txt leaving does not free it.
        for kind in self.kinds(ignores_case=False):
            disk = _Disk(*kind, "a.txt", "B.txt", "b.txt")
            self.assertEqual(_edit(disk, ["a.txt", "B.txt"], "b.txt\nz.txt\n"),
                             ["line 1 (a.txt): b.txt already exists"])
            self.assertEqual(len(disk.contents()), 3)

    def test_a_swap_in_another_case(self):
        for kind in self.kinds():
            disk = _Disk(*kind, "a.txt", "b.txt")
            self.assertEqual(_edit(disk, ["a.txt", "b.txt"], "B.txt\nA.txt\n"), [])
            self.assertEqual(disk.contents(), {"B.txt": "a.txt", "A.txt": "b.txt"})

    def test_apply_plan_parks_the_rename_onto_a_freed_name(self):
        # a.txt must not reach b.txt while B.txt is still there, whatever order
        # the plan lists them in.
        for kind in self.kinds():
            disk = _Disk(*kind, "a.txt", "B.txt")
            plan = parse_plan([disk.path("a.txt"), disk.path("B.txt")], "b.txt\nz.txt\n")
            plan.renames.reverse()
            self.assertEqual(apply_plan(plan)[1], [])
            self.assertEqual(disk.contents(), {"b.txt": "a.txt", "z.txt": "B.txt"})


class NewNamesDifferingOnlyInCase(_EveryKind):
    """Two new names that differ only in case are one file where the disk
    ignores case. They are refused unless the directory is seen to keep such
    names apart — it already holds two of them."""

    def test_refused_without_evidence(self):
        for kind in self.kinds():
            disk = _Disk(*kind, "a.txt", "b.txt")
            self.assertEqual(len(_edit(disk, ["a.txt", "b.txt"], "X.txt\nx.txt\n")), 2)
            self.assertEqual(disk.contents(), {"a.txt": "a.txt", "b.txt": "b.txt"})
            rows = _rows(_Disk(*kind, "X1.txt", "x2.txt"), ["X1.txt", "x2.txt"], r"\d", "")
            self.assertTrue(rows["X1.txt"]["conflict"] and rows["x2.txt"]["conflict"])

    def test_allowed_where_the_directory_already_holds_such_a_pair(self):
        for kind in self.kinds(ignores_case=False):
            disk = _Disk(*kind, "a.txt", "b.txt", "y.txt", "Y.txt")
            self.assertEqual(_edit(disk, ["a.txt", "b.txt"], "X.txt\nx.txt\n"), [])
            self.assertEqual(disk.contents()["X.txt"], "a.txt")
            self.assertEqual(disk.contents()["x.txt"], "b.txt")
            disk = _Disk(*kind, "X1.txt", "x2.txt", "y.txt", "Y.txt")
            rows = _rows(disk, ["X1.txt", "x2.txt"], r"\d", "")
            self.assertFalse(rows["X1.txt"]["conflict"] or rows["x2.txt"]["conflict"])

    def test_swapping_names_that_differ_only_in_case(self):
        for kind in self.kinds(ignores_case=False):
            disk = _Disk(*kind, "x.txt", "X.txt")
            self.assertEqual(_edit(disk, ["x.txt", "X.txt"], "X.txt\nx.txt\n"), [])
            self.assertEqual(disk.contents(), {"X.txt": "x.txt", "x.txt": "X.txt"})

    def test_such_a_pair_left_unchanged_is_no_collision(self):
        for kind in self.kinds(ignores_case=False):
            disk = _Disk(*kind, "x.txt", "X.txt", "a.txt")
            self.assertEqual(_edit(disk, ["x.txt", "X.txt", "a.txt"],
                                   "x.txt\nX.txt\nb.txt\n"), [])
            self.assertEqual(disk.contents()["b.txt"], "a.txt")

    def test_the_exact_same_name_collides_everywhere(self):
        for kind in self.kinds():
            rows = _rows(_Disk(*kind, "a1.txt", "a2.txt"), ["a1.txt", "a2.txt"], r"\d", "")
            self.assertTrue(rows["a1.txt"]["conflict"] and rows["a2.txt"]["conflict"])


class CheckedAgainJustBefore(_EveryKind):
    def test_a_name_taken_after_the_plan_was_read_is_not_replaced(self):
        for kind in self.kinds():
            disk = _Disk(*kind, "a.txt")
            plan = parse_plan([disk.path("a.txt")], "b.txt\n")
            self.assertTrue(plan.ok)
            disk.entries["b.txt"] = ["late", 999, None]   # another program
            renamed, errors = apply_plan(plan)
            self.assertEqual(errors, ["a.txt: b.txt already exists"])
            self.assertEqual(disk.contents(), {"a.txt": "a.txt", "b.txt": "late"})


def _host_ignores_case() -> bool:
    tmp = tempfile.mkdtemp()
    try:
        open(os.path.join(tmp, "a"), "w").close()
        return os.path.exists(os.path.join(tmp, "A"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_HOST_IGNORES_CASE = _host_ignores_case()


class _RealDir(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, *names):
        for name in names:
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write(name)

    def path(self, name):
        return Path(os.path.join(self.tmp, name))

    def contents(self):
        out = {}
        for name in os.listdir(self.tmp):
            p = os.path.join(self.tmp, name)
            out[name] = (f"->{os.readlink(p)}" if os.path.islink(p)
                         else open(p).read())
        return out


@unittest.skipUnless(_HOST_IGNORES_CASE, "needs a disk that ignores case")
class RealDiskIgnoringCase(_RealDir):
    def test_a_name_freed_in_another_case_is_taken_869(self):
        self.make("a.txt", "B.txt")
        plan = parse_plan([self.path("a.txt"), self.path("B.txt")], "b.txt\nz.txt\n")
        self.assertEqual(plan.errors, [])
        self.assertEqual(apply_plan(plan)[1], [])
        self.assertEqual(self.contents(), {"b.txt": "a.txt", "z.txt": "B.txt"})

    def test_a_case_only_rename_is_the_file_itself(self):
        self.make("foo.txt")
        self.assertFalse(obstacle(self.path("foo.txt"), "Foo.txt"))


@unittest.skipIf(_HOST_IGNORES_CASE, "needs a disk where case matters")
class RealDiskKeepingCase(_RealDir):
    def test_a_separate_file_in_another_case_is_an_obstacle_873(self):
        self.make("foo.txt", "Foo.txt")
        self.assertTrue(obstacle(self.path("foo.txt"), "Foo.txt"))

    @unittest.skipIf(sys.platform == "win32", "symlinks need a privilege there")
    def test_the_file_a_symlink_points_at_is_an_obstacle_875(self):
        self.make("Foo.txt")
        os.symlink("Foo.txt", os.path.join(self.tmp, "foo.txt"))
        self.assertTrue(obstacle(self.path("foo.txt"), "Foo.txt"))
        self.assertEqual(self.contents(), {"Foo.txt": "Foo.txt", "foo.txt": "->Foo.txt"})


if __name__ == "__main__":
    unittest.main()
