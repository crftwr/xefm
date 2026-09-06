"""Tests for the libarchive-backed formats — 7z today (discussion #396).

Skipped wholesale when the machine has no usable libarchive, which is the point
of the capability probe: the format is simply absent from the registry there and
zip and tar carry on. Fixtures are written with libarchive's own 7z writer, so
these need no external ``7z`` binary; the encrypted one is a stored blob because
libarchive cannot *write* an encrypted 7z.

Run with: python -m pytest test/test_archive_libarchive.py -v
"""

import base64
import os
import sys
import types

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm import archive as A  # noqa: E402
from xefm.archive_libarchive import (  # noqa: E402
    LibarchiveHandler, can_decrypt_7z, clean_member_path, libarchive_formats,
    libarchive_info,
)
from xefm.path import Path  # noqa: E402

_HAS_7Z = any(fmt.label == "7z" for fmt in libarchive_formats())
requires_7z = pytest.mark.skipif(
    not _HAS_7Z, reason="no libarchive able to read 7z on this machine")

# One AES-256 encrypted 7z holding "secret.txt". libarchive's 7z *writer* has no
# encryption, so unlike every other fixture here this one cannot be generated.
_ENCRYPTED_7Z = base64.b64decode(
    "N3q8ryccAARfXI/4gwAAAAAAAAAUAAAAAAAAAA6xR+SEKLWDIBuLctmOWO0Ey2IM4ABuAGtdAA"
    "CBMweuD87zck5PYtmjlC7665Rvo9JyRHNFzqR/1QdFG0fWqjQSpDRUacop7qQGu8He6e+odaxF"
    "jYT8fZ8DdHgPvgXSf5V+mKUceOvZE6FVT+t7C9jXdEC+C7ustjoh8i/kafvfPF7UAAAAABcGEA"
    "EJcwAHCwEAASEhARgMbwAA"
)


def _write_7z(path, members):
    """Write ``members`` — ``(name, bytes)`` pairs — as a 7z at ``path``."""
    import libarchive
    with libarchive.file_writer(str(path), "7zip") as writer:
        for name, data in members:
            writer.add_file_from_memory(name, len(data), data)
    return path


@pytest.fixture
def sample_7z(tmp_path):
    path = _write_7z(tmp_path / "sample.7z", [
        ("a.txt", b"alpha"),
        ("sub/b.txt", b"beta"),
        ("sub/deep/c.bin", bytes(range(256)) * 4),
    ])
    A.get_archive_cache().clear()
    yield path
    A.get_archive_cache().clear()


@pytest.fixture
def encrypted_7z(tmp_path):
    path = tmp_path / "enc.7z"
    path.write_bytes(_ENCRYPTED_7Z)
    A.get_archive_cache().clear()
    A.clear_archive_password(Path(str(path)))
    yield path
    A.clear_archive_password(Path(str(path)))
    A.get_archive_cache().clear()


# --- probing ------------------------------------------------------------------


def test_probe_reports_what_it_found():
    """Whatever the answer, the probe has to be able to state it — this is the
    line a bug report carries, with three possible libraries behind it."""
    info = libarchive_info()
    if info.available:
        assert info.details.startswith("libarchive ")
        assert all(isinstance(codec, str) for codec in info.codecs)
    else:
        assert info.error


def test_registry_agrees_with_the_probe():
    """7z is in the readable table exactly when the loaded library justifies it —
    never because the module was imported."""
    assert (A.archive_format_label("x.7z") == "7z") is _HAS_7Z


@pytest.mark.parametrize("raw, cleaned", [
    ("a.txt", "a.txt"),
    ("./a.txt", "a.txt"),          # what bsdtar stores
    ("./sub/b.txt", "sub/b.txt"),
    ("./", ""),
    (".", ""),
    ("sub/", "sub"),
    ("sub\\b.txt", "sub/b.txt"),   # a Windows-built writer
    ("../escape.txt", "../escape.txt"),  # left for the extraction guard to refuse
    ("", ""),
])
def test_clean_member_path(raw, cleaned):
    assert clean_member_path(raw) == cleaned


# --- browsing -----------------------------------------------------------------


@requires_7z
def test_lists_a_tree_with_implied_directories(sample_7z):
    with LibarchiveHandler(Path(str(sample_7z))) as handler:
        root = {e.internal_path: e for e in handler.list_entries("")}
        assert set(root) == {"a.txt", "sub"}
        assert root["sub"].is_dir and not root["a.txt"].is_dir
        assert root["a.txt"].size == 5
        assert root["a.txt"].archive_type == "7z"

        sub = {e.internal_path for e in handler.list_entries("sub")}
        assert sub == {"sub/b.txt", "sub/deep"}
        assert {e.internal_path for e in handler.list_entries("sub/deep")} \
            == {"sub/deep/c.bin"}


@requires_7z
def test_entry_info_and_bytes(sample_7z):
    with LibarchiveHandler(Path(str(sample_7z))) as handler:
        entry = handler.get_entry_info("sub/b.txt")
        assert entry is not None and entry.size == 4
        assert handler.extract_to_bytes("sub/b.txt") == b"beta"
        assert handler.extract_to_bytes("a.txt") == b"alpha"
        assert handler.get_entry_info("nope.txt") is None


@requires_7z
def test_reading_a_directory_or_a_missing_entry_raises(sample_7z):
    with LibarchiveHandler(Path(str(sample_7z))) as handler:
        with pytest.raises(A.ArchiveExtractionError):
            handler.extract_to_bytes("sub")
        with pytest.raises(FileNotFoundError):
            handler.extract_to_bytes("nope.txt")


@requires_7z
def test_extract_to_file(sample_7z, tmp_path):
    target = tmp_path / "out.txt"
    with LibarchiveHandler(Path(str(sample_7z))) as handler:
        handler.extract_to_file("sub/b.txt", Path(str(target)))
    assert target.read_bytes() == b"beta"


@requires_7z
def test_a_missing_archive_is_reported_as_such(tmp_path):
    handler = LibarchiveHandler(Path(str(tmp_path / "nope.7z")))
    with pytest.raises(FileNotFoundError):
        handler.open()


@requires_7z
def test_a_corrupt_archive_is_reported_as_such(tmp_path):
    bad = tmp_path / "bad.7z"
    bad.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"garbage" * 20)
    with pytest.raises(A.ArchiveCorruptedError):
        LibarchiveHandler(Path(str(bad))).open()


@requires_7z
def test_browsing_goes_through_the_cache(sample_7z):
    """The registry is what makes ``archive://`` browsing work for 7z — the pane
    never names a handler class."""
    handler = A.get_archive_cache().get_handler(Path(str(sample_7z)))
    assert isinstance(handler, LibarchiveHandler)
    member = Path(f"archive://{os.path.abspath(str(sample_7z))}#sub/b.txt")
    assert member.read_bytes() == b"beta"


# --- extraction ---------------------------------------------------------------


@requires_7z
def test_iter_extract_writes_everything_in_one_pass(sample_7z, tmp_path):
    out = tmp_path / "out"
    with LibarchiveHandler(Path(str(sample_7z))) as handler:
        total = handler.entry_count()
        listed = handler._entry_cache
        extracted = [e.internal_path for e in handler.iter_extract(Path(str(out)))]

    # The stored members, not the index: "sub" and "sub/deep" are implied by
    # their children and get created on the way past, so the progress total has
    # to be the three that are actually yielded.
    assert sorted(extracted) == ["a.txt", "sub/b.txt", "sub/deep/c.bin"]
    assert len(extracted) == total == 3
    assert set(listed) > set(extracted)
    assert (out / "a.txt").read_bytes() == b"alpha"
    assert (out / "sub" / "b.txt").read_bytes() == b"beta"
    assert (out / "sub" / "deep" / "c.bin").read_bytes() == bytes(range(256)) * 4


@requires_7z
def test_iter_extract_refuses_an_escaping_member(tmp_path):
    path = _write_7z(tmp_path / "evil.7z", [
        ("../escape.txt", b"pwned"), ("fine.txt", b"ok")])
    out = tmp_path / "out"
    with LibarchiveHandler(Path(str(path))) as handler:
        extracted = [e.internal_path for e in handler.iter_extract(Path(str(out)))]
    assert extracted == ["fine.txt"]
    assert not (tmp_path / "escape.txt").exists()


@requires_7z
def test_app_extract_routes_a_7z_through_its_handler(sample_7z, tmp_path):
    """``_extract_archive`` sends anything zipfile and tarfile cannot read to the
    registered handler — the U key's half of 7z support."""
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    out = Path(str(tmp_path / "dest"))
    count = app._extract_archive(Path(str(sample_7z)), out, "7z")
    assert count == 3
    assert (tmp_path / "dest" / "sub" / "b.txt").read_bytes() == b"beta"


@requires_7z
def test_create_refuses_a_format_it_can_only_read(tmp_path, monkeypatch):
    """The two tables are deliberately different sizes. Typing a 7z name at the
    create prompt has to say so, not quietly produce ``bundle.7z.tar.gz``."""
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
    captured[-1]["on_accept"]("bundle.7z")

    assert any("Cannot create 7z archives" in m for m in app.logs)
    assert not (tmp_path / "bundle.7z.tar.gz").exists()
    assert not (tmp_path / "bundle.7z").exists()


# --- encryption ---------------------------------------------------------------


@requires_7z
def test_a_plain_7z_needs_no_password(sample_7z):
    with LibarchiveHandler(Path(str(sample_7z))) as handler:
        assert handler.encryption_status() == "none"
        assert handler.verify_password(b"anything") is False


@requires_7z
def test_an_encrypted_7z_is_classified_by_what_the_library_can_do(encrypted_7z):
    """Names are readable either way — 7z encrypts the data, not the header — so
    the classification turns entirely on whether the loaded libarchive has crypto
    compiled in. macOS's system build does not; a build from ``xefm-bin-deps``
    will. The gate has to be able to say which, rather than rejecting every
    password the user types."""
    expected = "password" if can_decrypt_7z() else "unsupported"
    with LibarchiveHandler(Path(str(encrypted_7z))) as handler:
        assert {e.internal_path for e in handler.list_entries("")} == {"secret.txt"}
        assert handler.encryption_status() == expected

    member = Path(f"archive://{os.path.abspath(str(encrypted_7z))}#secret.txt")
    assert A.archive_password_state(member) == (
        "need" if can_decrypt_7z() else "unsupported")
    assert A.archive_encryption_status_path(str(encrypted_7z)) == expected


@requires_7z
@pytest.mark.skipif(can_decrypt_7z(), reason="this libarchive can decrypt 7z")
def test_undecryptable_entries_report_the_reason(encrypted_7z):
    """Reading an encrypted entry on a crypto-less build is a distinct failure
    from a wrong password: no password would help, so the UI must not re-prompt."""
    with LibarchiveHandler(Path(str(encrypted_7z))) as handler:
        with pytest.raises(A.ArchiveEncryptionUnsupported):
            handler.extract_to_bytes("secret.txt")
        assert handler.verify_password(b"sesame") is False


@requires_7z
@pytest.mark.skipif(not can_decrypt_7z(), reason="this libarchive has no 7z crypto")
def test_a_correct_password_reads_an_encrypted_entry(encrypted_7z):
    with LibarchiveHandler(Path(str(encrypted_7z))) as handler:
        assert handler.verify_password(b"wrong") is False
        assert handler.verify_password(b"sesame") is True
        A.set_archive_password(Path(str(encrypted_7z)), b"sesame")
        assert handler.extract_to_bytes("secret.txt") == b"top secret\n"
