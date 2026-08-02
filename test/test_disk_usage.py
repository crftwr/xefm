"""
Tests for the recursive disk-usage scanner behind the file-details dialog.

Run with: python -m pytest test/test_disk_usage.py -v
"""

import os
import sys

import pytest

from xefm.disk_usage import UsageScan
from xefm.path import Path


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


def test_no_roots_is_born_done():
    """An all-files selection has nothing to walk; callers need no special case."""
    scan = UsageScan([])
    assert scan.done is True
    assert scan.grand_totals() == (0, 0, 0, 0)
