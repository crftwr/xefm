"""
The archive cache lets go of an archive file once nothing needs it (xefm#516).

On Windows a file XeFM holds open cannot be deleted, moved or renamed, and a
browsed zip used to stay open in the cache after the pane had left it. These
pin down when the cache now closes a handler — and that closing never pulls a
handler out from under a read that is still using it.

Run with: python -m pytest test/test_archive_release.py -v
"""

import io
import os
import shutil
import tarfile
import tempfile
import threading
import zipfile

import pytest

from xefm import archive as A
from xefm.archive import ArchiveCache, release_unshown_archives
from xefm.path import Path


@pytest.fixture
def tmp(monkeypatch):
    # realpath: the macOS sandbox TMPDIR is a symlink, and cache keys are
    # compared as spelled (xefm#505).
    root = os.path.realpath(tempfile.mkdtemp(prefix="test_archive_release_"))
    # A private global cache, so these tests neither see nor leave handlers in
    # the one other tests use.
    monkeypatch.setattr(A, "_archive_cache", ArchiveCache(max_open=5, ttl=300))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _zip(root, rel, members=(("a/b.txt", "hello"),)):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return path


def _is_closed(handler):
    return handler._archive_obj is None and not handler._is_open


def test_retain_only_closes_archives_no_pane_shows(tmp):
    cache = A.get_archive_cache()
    shown = cache.get_handler(Path(_zip(tmp, "shown.zip")))
    left = cache.get_handler(Path(_zip(tmp, "left.zip")))

    cache.retain_only([Path(os.path.join(tmp, "shown.zip"))])

    assert _is_closed(left)
    assert not _is_closed(shown)
    assert cache.get_stats()["open_archives"] == 1


def test_release_unshown_archives_reads_pane_paths(tmp):
    zpath = _zip(tmp, "t.zip")
    inside = Path(f"archive://{zpath}#a")
    assert [p.name for p in inside.iterdir()] == ["b.txt"]
    handler = A.get_archive_cache().get_handler(Path(zpath))

    # Still inside on one pane: kept.
    release_unshown_archives((inside, Path(tmp)))
    assert not _is_closed(handler)

    # Both panes out of it: closed.
    release_unshown_archives((Path(tmp), Path(tmp)))
    assert _is_closed(handler)
    assert A.get_archive_cache().get_stats()["open_archives"] == 0


def test_release_under_matches_the_file_and_directories_holding_it(tmp):
    cache = A.get_archive_cache()
    nested = cache.get_handler(Path(_zip(tmp, "dir/sub/n.zip")))
    sibling = cache.get_handler(Path(_zip(tmp, "dir2/s.zip")))

    cache.release_under(Path(os.path.join(tmp, "dir")))

    assert _is_closed(nested)
    # "dir2" shares the prefix "dir" but is not beneath it.
    assert not _is_closed(sibling)


def test_unlink_releases_the_browsed_archive_first(tmp):
    zpath = _zip(tmp, "gone.zip")
    list(Path(f"archive://{zpath}#").iterdir())
    handler = A.get_archive_cache().get_handler(Path(zpath))

    Path(zpath).unlink()

    assert _is_closed(handler)
    assert not os.path.exists(zpath)


def test_deleting_a_directory_releases_archives_inside_it(tmp):
    zpath = _zip(tmp, "d/inner.zip")
    list(Path(f"archive://{zpath}#").iterdir())
    handler = A.get_archive_cache().get_handler(Path(zpath))

    from xefm.file_operations import recursive_delete
    recursive_delete(Path(os.path.join(tmp, "d")))

    assert _is_closed(handler)
    assert not os.path.exists(os.path.join(tmp, "d"))


def test_rename_releases_both_source_and_overwritten_target(tmp):
    cache = A.get_archive_cache()
    src = _zip(tmp, "src.zip")
    dst = _zip(tmp, "dst.zip")
    src_handler = cache.get_handler(Path(src))
    dst_handler = cache.get_handler(Path(dst))

    Path(src).replace(Path(dst))

    assert _is_closed(src_handler)
    assert _is_closed(dst_handler)


def test_a_lease_keeps_a_released_handler_open_until_it_ends(tmp):
    cache = A.get_archive_cache()
    zpath = Path(_zip(tmp, "busy.zip"))
    with cache.lease(zpath) as handler:
        cache.retain_only([])
        # Out of the cache, but the reader still has it.
        assert cache.get_stats()["open_archives"] == 0
        assert handler.extract_to_bytes("a/b.txt") == b"hello"
    assert _is_closed(handler)


def test_member_stream_survives_the_pane_leaving(tmp):
    """A copy out of the archive streams through a lease; the pane navigating
    away mid-stream must not close the handler under it."""
    # tar, not zip: zipfile keeps its file open for a member stream on its own,
    # tarfile closes it outright, so only the lease stands between the two.
    payload = os.urandom(4 * 1024 * 1024)
    tpath = os.path.join(tmp, "big.tar")
    with tarfile.open(tpath, "w") as tf:
        info = tarfile.TarInfo("big.bin")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    member = Path(f"archive://{tpath}#big.bin")
    out = io.BytesIO()
    released = []

    def on_progress(done, total):
        if not released:
            release_unshown_archives((Path(tmp), Path(tmp)))
            released.append(True)

    member._impl.extract_to_stream(out, on_progress)

    assert released
    assert out.getvalue() == payload
    assert A.get_archive_cache().get_stats()["open_archives"] == 0


def test_retain_only_does_not_wait_for_a_busy_cache(tmp):
    """The UI thread calls it; a worker opening an archive holds the lock."""
    cache = A.get_archive_cache()
    handler = cache.get_handler(Path(_zip(tmp, "t.zip")))
    holding, done = threading.Event(), threading.Event()

    def worker():
        with cache._lock:
            holding.set()
            done.wait(5)

    t = threading.Thread(target=worker)
    t.start()
    holding.wait(5)
    try:
        cache.retain_only([])  # returns at once instead of blocking
        assert not _is_closed(handler)
    finally:
        done.set()
        t.join()
    cache.retain_only([])
    assert _is_closed(handler)
