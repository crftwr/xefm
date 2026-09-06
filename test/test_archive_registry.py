"""Tests for the readable-format registry (discussion #396, stage 1).

``ArchiveCache._create_handler`` used to be an if/elif chain over filename
suffixes, and the password gate used to ask ``isinstance(handler, ZipHandler)``.
Both now go through one table, :data:`xefm.archive.ARCHIVE_HANDLERS`. What is
worth pinning down is the part the old chain got right only by accident — that
``.tar.gz`` beats ``.tar`` — plus the contract a new format is written against.

Run with: python -m pytest test/test_archive_registry.py -v
"""

import os
import sys
import tarfile
import types

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import archive as A  # noqa: E402
from xefm.archive import (  # noqa: E402
    ArchiveCache, ArchiveFormat, ArchiveFormatError, ArchiveHandler, TarHandler,
    ZipHandler, archive_format_for_name, archive_format_label,
    archive_readable_suffixes, archive_strip_suffix, is_safe_member_path,
    register_archive_format,
)
from xefm.path import Path  # noqa: E402


@pytest.fixture
def isolated_registry():
    """Let a test register formats without leaking them into the next one."""
    saved = list(A.ARCHIVE_HANDLERS)
    yield
    A.ARCHIVE_HANDLERS = saved


# --- matching -----------------------------------------------------------------


@pytest.mark.parametrize("name, label", [
    ("photos.zip", "zip"),
    ("PHOTOS.ZIP", "zip"),
    ("src.tar", "tar"),
    ("src.tar.gz", "tar.gz"),
    ("src.tgz", "tar.gz"),
    ("src.tar.bz2", "tar.bz2"),
    ("src.tbz2", "tar.bz2"),
    ("src.tar.xz", "tar.xz"),
    ("src.txz", "tar.xz"),
    ("notes.txt", None),
    ("archive", None),
])
def test_label_for_builtin_formats(name, label):
    assert archive_format_label(name) == label


def test_longest_suffix_wins_regardless_of_registration_order(isolated_registry):
    """The old chain tested ``.tar.gz`` before ``.tar`` because of where the
    branches sat in the source. The table must not depend on that: registering a
    short suffix last still leaves the long one winning."""
    A.ARCHIVE_HANDLERS = []
    register_archive_format(ArchiveFormat("tar.gz", (".tar.gz",), TarHandler))
    register_archive_format(ArchiveFormat("tar", (".tar",), TarHandler))
    assert archive_format_label("src.tar.gz") == "tar.gz"

    A.ARCHIVE_HANDLERS = []
    register_archive_format(ArchiveFormat("tar", (".tar",), TarHandler))
    register_archive_format(ArchiveFormat("tar.gz", (".tar.gz",), TarHandler))
    assert archive_format_label("src.tar.gz") == "tar.gz"


def test_register_replaces_an_earlier_entry_with_the_same_label(isolated_registry):
    marker = object()
    register_archive_format(ArchiveFormat("zip", (".zip", ".jar"), lambda p: marker))
    assert archive_format_label("app.jar") == "zip"
    assert archive_format_for_name("app.zip").factory(None) is marker
    assert sum(1 for f in A.ARCHIVE_HANDLERS if f.label == "zip") == 1


def test_strip_suffix_uses_the_longest_match():
    assert archive_strip_suffix("src.tar.gz") == "src"
    assert archive_strip_suffix("src.TAR.GZ") == "src"
    assert archive_strip_suffix("photos.zip") == "photos"
    assert archive_strip_suffix("notes.txt") == "notes.txt"


def test_readable_suffixes_are_generated_longest_first():
    suffixes = archive_readable_suffixes()
    assert ".zip" in suffixes and ".tar.gz" in suffixes
    assert suffixes.index(".tar.gz") < suffixes.index(".tar")
    assert len(set(suffixes)) == len(suffixes)


# --- dispatch -----------------------------------------------------------------


def test_cache_dispatches_through_the_table(tmp_path):
    cache = ArchiveCache()
    zp = tmp_path / "a.zip"
    import zipfile
    with zipfile.ZipFile(str(zp), "w") as zf:
        zf.writestr("x.txt", b"x")
    assert isinstance(cache._create_handler(Path(str(zp))), ZipHandler)

    tp = tmp_path / "a.tgz"
    with tarfile.open(str(tp), "w:gz") as tf:
        tf.add(str(zp), arcname="x.zip")
    handler = cache._create_handler(Path(str(tp)))
    assert isinstance(handler, TarHandler) and handler._compression == "gz"


def test_cache_rejects_an_unregistered_format(tmp_path):
    p = tmp_path / "a.rar"
    p.write_bytes(b"Rar!")
    with pytest.raises(ArchiveFormatError):
        ArchiveCache()._create_handler(Path(str(p)))


# --- the contract a new handler is written against ----------------------------


def test_abc_defaults_are_the_unencrypted_answer():
    """A format that is never encrypted implements neither method."""
    handler = ArchiveHandler(Path("/nowhere.zip"))
    assert handler.encryption_status() == "none"
    assert handler.verify_password(b"anything") is False


@pytest.mark.parametrize("member, safe", [
    ("a.txt", True),
    ("sub/a.txt", True),
    ("..a.txt", True),          # a leading dot-dot in the *name* is not a climb
    ("", False),
    ("/etc/passwd", False),
    ("../escape.txt", False),
    ("sub/../../escape.txt", False),
    ("C:/Windows/evil.dll", False),
    ("\\\\server\\share", False),
])
def test_is_safe_member_path(member, safe):
    assert is_safe_member_path(member) is safe


def test_writable_formats_are_ordered_across_both_sources(isolated_registry, tmp_path):
    """Creation has two tables behind it — the stdlib one on XeFMApp and the
    registry's writers — and the same longest-suffix rule has to hold across
    their union, not within each half."""
    rows = xefm_app.XeFMApp._writable_formats()
    lengths = [len(suffix) for suffix, _ in rows]
    assert lengths == sorted(lengths, reverse=True)
    assert dict(rows)[".tar.gz"] == "tar.gz" and dict(rows)[".tar"] == "tar"

    # A registered writer whose suffix is longer than a stdlib one it contains
    # must win, even though the stdlib table is the one listed first.
    register_archive_format(ArchiveFormat(
        "big-tar", (".big.tar",), TarHandler, writer=lambda *a, **kw: 0))
    assert xefm_app.XeFMApp._archive_format("x.big.tar") == "big-tar"
    assert xefm_app.XeFMApp._archive_format("x.tar") == "tar"


def test_create_refuses_a_readable_format_with_no_writer(isolated_registry, tmp_path,
                                                         monkeypatch):
    """A format the registry reads but brought no writer for — a rar, or a
    libarchive too old to write 7z. P has to say so rather than append .tar.gz to
    a name the user clearly meant as something else."""
    register_archive_format(ArchiveFormat("fake", (".fake",), ZipHandler))
    src = tmp_path / "src.txt"
    src.write_bytes(b"x")

    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app.logs = []
    app.log_info = app.logs.append
    app.panel = types.SimpleNamespace(render=lambda: None)
    app.active_pane = lambda: {}
    app._selected_or_focused = lambda pane: [Path(str(src))]
    app._is_archive = lambda p: False
    app.pm = types.SimpleNamespace(
        get_inactive_pane=lambda: {"path": Path(str(tmp_path))})
    app._active_pane_region = lambda: (0.0, 80.0)
    app.flm = types.SimpleNamespace(show_hidden=False)

    captured = []
    monkeypatch.setattr(xefm_app, "show_input", lambda panel, **kw: captured.append(kw))
    app.create_archive()
    captured[-1]["on_accept"]("bundle.fake")

    assert any("Cannot create fake archives" in m for m in app.logs)
    assert not (tmp_path / "bundle.fake.tar.gz").exists()
    assert not (tmp_path / "bundle.fake").exists()


def test_generic_iter_extract_yields_before_writing(tmp_path):
    """The ordering the byte bar depends on: the caller must see an entry while
    it can still open a bar at the right size, not after the bytes have gone."""
    payload = tmp_path / "payload.txt"
    payload.write_bytes(b"x" * 32)
    tp = tmp_path / "t.tar"
    with tarfile.open(str(tp), "w") as tf:
        tf.add(str(payload), arcname="a.txt")

    out = tmp_path / "out"
    reported = []
    with TarHandler(Path(str(tp)), compression=None) as handler:
        for entry in handler.iter_extract(Path(str(out)), on_bytes=reported.append):
            # Announced first: nothing of this member is on disk yet.
            assert not (out / entry.internal_path).exists()
    assert (out / "a.txt").read_bytes() == b"x" * 32
    assert reported == [32]


def test_generic_iter_extract_walks_the_cached_entries(tmp_path):
    """The default :meth:`ArchiveHandler.iter_extract` — what a format inherits
    when it has nothing faster to offer."""
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"alpha")
    (src / "sub" / "b.txt").write_bytes(b"beta")
    tp = tmp_path / "t.tar"
    with tarfile.open(str(tp), "w") as tf:
        tf.add(str(src / "a.txt"), arcname="a.txt")
        tf.add(str(src / "sub" / "b.txt"), arcname="sub/b.txt")

    out = tmp_path / "out"
    with TarHandler(Path(str(tp)), compression=None) as handler:
        extracted = [e.internal_path for e in handler.iter_extract(Path(str(out)))]
        # "sub" is implied by its child rather than stored, and the generic walk
        # creates it from the virtual entry the index built.
        assert handler.entry_count() == len(extracted) == 3

    assert (out / "a.txt").read_bytes() == b"alpha"
    assert (out / "sub" / "b.txt").read_bytes() == b"beta"
    assert sorted(extracted) == ["a.txt", "sub", "sub/b.txt"]


def test_generic_iter_extract_refuses_an_escaping_member(tmp_path):
    """A member reached through ``..`` is skipped, not written outside the
    destination — tarfile's ``data`` filter guards the tar path, and this is the
    same guard for the paths XeFM writes itself."""
    payload = tmp_path / "payload.txt"
    payload.write_bytes(b"pwned")
    tp = tmp_path / "evil.tar"
    with tarfile.open(str(tp), "w") as tf:
        tf.add(str(payload), arcname="../escape.txt")
        tf.add(str(payload), arcname="fine.txt")

    out = tmp_path / "out"
    with TarHandler(Path(str(tp)), compression=None) as handler:
        extracted = [e.internal_path for e in handler.iter_extract(Path(str(out)))]

    assert extracted == ["fine.txt"]
    assert not (tmp_path / "escape.txt").exists()
