"""
Tests for the recursive disk-usage scanner behind the file-details dialog.

The scan keeps two byte totals, Finder's "Size" and its "on disk": how long the
files are, and how much of the volume they occupy. A single sparse file puts
three orders of magnitude between them (issue #275), so a backend that cannot
report the second has to say so rather than sum zeros into it.

Run with: python -m pytest test/test_disk_usage.py -v
"""

import os
import sys

import pytest

from xefm.disk_usage import UsageScan, reports_allocation
from xefm.path import Path


def _sparse(path, length):
    """A file ``length`` bytes long holding one byte, the rest a hole."""
    with open(path, "wb") as f:
        f.truncate(length)
        f.seek(length - 1)
        f.write(b"z")


class _FakePath:
    """A directory from a backend with no notion of allocated space — what SSH,
    S3 and archive paths all look like to the walk. Its records carry
    ``alloc: None``, the way those backends' do."""

    def __init__(self, name, entries):
        self._name = name
        self._entries = entries

    def __str__(self):
        return self._name

    def stat(self):
        class _Stat:      # no st_blocks, like S3StatResult and SSH's StatResult
            st_size = 0
            st_mtime = 0.0
        return _Stat()

    def listdir_attrs(self):
        return [(_FakePath(f"{self._name}/{n}", []),
                 {"is_dir": False, "is_link": False, "size": size,
                  "alloc": alloc, "mtime": 0.0, "hidden": False, "ok": True})
                for n, size, alloc in self._entries]


def _build_tree(base):
    """A small known tree: 3 files totalling 350 bytes across root + 1 subdir."""
    (base / "f1.bin").write_bytes(b"x" * 100)
    (base / "f2.bin").write_bytes(b"y" * 200)
    sub = base / "sub"
    sub.mkdir()
    (sub / "f3.bin").write_bytes(b"z" * 50)
    return base


def test_totals_single_root(tmp_path):
    """Bytes, file count and folder count over a nested tree."""
    root = _build_tree(tmp_path)
    scan = UsageScan([Path(str(root))])
    scan.run_sync()

    totals = scan.totals[str(root)]
    assert totals.bytes == 350
    assert totals.files == 3
    assert totals.dirs == 1          # "sub"; the root itself is not counted
    assert totals.errors == 0
    assert totals.done is True
    assert scan.done is True


def test_grand_totals_multiple_roots(tmp_path):
    """Per-root records stay separate; grand_totals sums them."""
    (tmp_path / "a").mkdir()
    a = _build_tree(tmp_path / "a")
    b = tmp_path / "b"
    b.mkdir()
    (b / "only.bin").write_bytes(b"q" * 10)

    scan = UsageScan([Path(str(a)), Path(str(b))])
    scan.run_sync()

    assert scan.totals[str(a)].bytes == 350
    assert scan.totals[str(b)].bytes == 10
    assert scan.totals[str(b)].files == 1
    assert scan.grand_totals() == (360, 4, 1, 0)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="symlink creation needs privileges on Windows")
def test_symlinked_directory_is_not_followed(tmp_path):
    """A symlink to a directory counts as one entry; its contents are not
    walked (following links could cycle or double-count)."""
    root = _build_tree(tmp_path)
    os.symlink(str(tmp_path / "sub"), str(tmp_path / "link_to_sub"))

    scan = UsageScan([Path(str(root))])
    scan.run_sync()

    totals = scan.totals[str(root)]
    assert totals.dirs == 1          # still just "sub"
    assert totals.files == 4         # 3 real files + the link itself
    assert totals.bytes == 350       # nothing double-counted through the link


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                    reason="root ignores permission bits")
def test_unlistable_directory_counts_as_error(tmp_path):
    """An unreadable subdirectory is recorded in ``errors``, not raised."""
    root = _build_tree(tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "hidden.bin").write_bytes(b"h" * 42)
    locked.chmod(0o000)
    try:
        scan = UsageScan([Path(str(root))])
        scan.run_sync()
        totals = scan.totals[str(root)]
        assert totals.errors == 1
        assert totals.dirs == 2      # the locked dir is still counted as a dir
        assert totals.bytes == 350   # its contents are not
    finally:
        locked.chmod(0o755)


def test_cancel_stops_the_walk(tmp_path):
    """A cancelled scan finishes as done with the root not marked complete."""
    root = _build_tree(tmp_path)
    scan = UsageScan([Path(str(root))])
    scan.cancel()
    scan.run_sync()

    assert scan.done is True
    assert scan.cancelled is True
    assert scan.totals[str(root)].done is False
    assert scan.grand_totals()[0] == 0


# --- the on-disk total ------------------------------------------------------

def test_a_sparse_file_separates_the_two_totals(tmp_path):
    """The issue's shape: a file far longer than the space it takes up. The
    total that used to be labelled "Disk usage" is the first of these."""
    root = _build_tree(tmp_path)
    _sparse(str(root / "sparse.raw"), 1 << 30)      # 1 GB long

    scan = UsageScan([Path(str(root))])
    scan.run_sync()

    totals = scan.totals[str(root)]
    assert totals.bytes == 350 + (1 << 30)
    # Three small files in a block each, plus the sparse file's written tail:
    # a few tens of KB against a logical gigabyte.
    assert totals.on_disk < (1 << 20)
    assert totals.alloc_unknown == 0
    assert scan.grand_alloc() == totals.on_disk


def test_a_dense_tree_rounds_up_to_whole_blocks(tmp_path):
    """The other direction, and the common one: on disk exceeds the byte count
    because each file occupies a whole block."""
    root = _build_tree(tmp_path)
    scan = UsageScan([Path(str(root))])
    scan.run_sync()

    totals = scan.totals[str(root)]
    assert totals.bytes == 350
    assert totals.on_disk >= 350
    assert totals.on_disk % 512 == 0


def test_a_backend_that_cannot_say_reports_unknown_not_zero():
    """A partial sum would read as a smaller directory rather than as an
    unmeasured one, so one unreported entry makes the whole total unknown."""
    root = _FakePath("fake://dir", [("a", 100, None), ("b", 200, None)])
    scan = UsageScan([root])
    scan.run_sync()

    totals = scan.totals["fake://dir"]
    assert totals.bytes == 300          # lengths still add up
    assert totals.alloc == 0
    assert totals.alloc_unknown == 2
    assert totals.on_disk is None
    assert scan.grand_alloc() is None


def test_one_unreported_entry_poisons_an_otherwise_known_total():
    root = _FakePath("fake://mixed", [("a", 100, 4096), ("b", 200, None)])
    scan = UsageScan([root])
    scan.run_sync()

    assert scan.totals["fake://mixed"].on_disk is None


def test_grand_alloc_is_unknown_when_any_root_is(tmp_path):
    """Mixing a local directory with one from a backend that cannot report an
    allocation: the local root keeps its own figure, the selection's is gone."""
    local = _build_tree(tmp_path)
    remote = _FakePath("fake://dir", [("a", 100, None)])

    scan = UsageScan([Path(str(local)), remote])
    scan.run_sync()

    assert scan.totals[str(local)].on_disk >= 350
    assert scan.grand_alloc() is None


# --- which backends get the row at all --------------------------------------

@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows stat_result has no st_blocks, by design")
def test_a_local_directory_reports_allocation(tmp_path):
    assert reports_allocation(Path(str(tmp_path))) is True


def test_a_backend_without_st_blocks_does_not():
    assert reports_allocation(_FakePath("fake://dir", [])) is False


def test_a_path_that_cannot_be_stat_d_does_not(tmp_path):
    """Probing must not raise out of the dialog's setup — an unreadable root
    simply gets no "On disk" row."""
    assert reports_allocation(Path(str(tmp_path / "nonexistent"))) is False


def test_no_roots_is_born_done():
    """An all-files selection has nothing to walk; callers need no special case."""
    scan = UsageScan([])
    assert scan.done is True
    assert scan.grand_totals() == (0, 0, 0, 0)
    assert scan.grand_alloc() == 0
