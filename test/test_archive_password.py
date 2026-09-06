"""
Tests for encrypted-zip support (issue #180): password detection, the ZipHandler
read path, the session password registry, and the UI-facing gate helpers.

Run with: python -m pytest test/test_archive_password.py -v

Python's stdlib ``zipfile`` can *read* ZipCrypto-encrypted archives but cannot
*write* them, so the encrypted fixture is a tiny pre-built ZipCrypto zip embedded
as base64 (two files: ``message.txt`` and ``folder/note.txt``, password
``s3cr3t``). This keeps the tests hermetic — no external ``zip`` tool needed.
"""

import base64
import tempfile
import zipfile
from pathlib import Path as PathlibPath

import pytest

from xefm.path import Path
from xefm import archive as A
from xefm.archive import (
    ZipHandler,
    ArchivePasswordRequired,
    ArchiveEncryptionUnsupported,
    zip_encryption_status,
    archive_encryption_status_path,
    verify_zip_password,
    set_archive_password,
    get_archive_password,
    clear_archive_password,
    archive_password_state,
    try_archive_password,
    get_member_archive_path,
)

# A ZipCrypto-encrypted zip: message.txt + folder/note.txt, password "s3cr3t".
_ENCRYPTED_ZIP_B64 = (
    "UEsDBAoACQAAABao71xT1X0WIwAAABcAAAALABwAbWVzc2FnZS50eHRVVAkAA2tXWGprV1hqdXgL"
    "AAEE9QEAAAQUAAAAMPr10rBGMXQZSW6Onn5ZbIPYfcGPchF5roW/HPhnO4hRplFQSwcIU9V9FiMA"
    "AAAXAAAAUEsDBAoACQAAABao71xuqL4oGgAAAA4AAAAPABwAZm9sZGVyL25vdGUudHh0VVQJAANr"
    "V1hqa1dYanV4CwABBPUBAAAEFAAAAIa4vvlX6bwj/k8ZoqSrenwnvl4atu8ttgirUEsHCG6oviga"
    "AAAADgAAAFBLAQIeAwoACQAAABao71xT1X0WIwAAABcAAAALABgAAAAAAAEAAACkgQAAAABtZXNz"
    "YWdlLnR4dFVUBQADa1dYanV4CwABBPUBAAAEFAAAAFBLAQIeAwoACQAAABao71xuqL4oGgAAAA4A"
    "AAAPABgAAAAAAAEAAACkgXgAAABmb2xkZXIvbm90ZS50eHRVVAUAA2tXWGp1eAsAAQT1AQAABBQA"
    "AABQSwUGAAAAAAIAAgCmAAAA6wAAAAAA"
)
_PASSWORD = "s3cr3t"
_MESSAGE = b"top secret\nsecond line\n"


@pytest.fixture
def enc_zip(tmp_path):
    """Write the embedded encrypted zip to a temp file and yield its Path.

    The session password registry and the archive cache are cleared before and
    after so tests don't leak a remembered password into one another."""
    p = tmp_path / "enc.zip"
    p.write_bytes(base64.b64decode(_ENCRYPTED_ZIP_B64))
    fs_path = Path(str(p))
    A.get_archive_cache().clear()
    clear_archive_password(fs_path)
    yield p
    clear_archive_password(fs_path)
    A.get_archive_cache().clear()


@pytest.fixture
def plain_zip(tmp_path):
    """An ordinary (unencrypted) zip for the negative cases."""
    p = tmp_path / "plain.zip"
    with zipfile.ZipFile(str(p), "w") as zf:
        zf.writestr("hello.txt", b"plain content")
    return p


# --- encryption classification ----------------------------------------------


def test_status_none_for_plain_zip(plain_zip):
    with zipfile.ZipFile(str(plain_zip)) as zf:
        assert zip_encryption_status(zf) == "none"
    assert archive_encryption_status_path(str(plain_zip)) == "none"


def test_status_zipcrypto_for_encrypted_zip(enc_zip):
    # The zip-level classifier keeps the scheme names; the path-level one speaks
    # the handler contract's neutral vocabulary, so a non-zip format can answer.
    with zipfile.ZipFile(str(enc_zip)) as zf:
        assert zip_encryption_status(zf) == "zipcrypto"
    assert archive_encryption_status_path(str(enc_zip)) == "password"


def test_status_path_none_on_bad_file(tmp_path):
    bad = tmp_path / "notazip.zip"
    bad.write_bytes(b"not a zip at all")
    assert archive_encryption_status_path(str(bad)) == "none"


def test_status_path_none_on_unreadable_format(tmp_path):
    """A suffix no registered handler reads classifies as 'none' — the read path
    is what reports that it cannot be opened, not the password gate."""
    other = tmp_path / "archive.notanarchive"
    other.write_bytes(b"nope")
    assert archive_encryption_status_path(str(other)) == "none"


class _FakeInfo:
    """Stand-in for ZipInfo — stdlib can't write AES, so AES is tested this way."""

    def __init__(self, encrypted, aes=False, size=1):
        self.flag_bits = 0x1 if encrypted else 0
        self.compress_type = 99 if aes else zipfile.ZIP_DEFLATED
        self.file_size = size

    def is_dir(self):
        return False


class _FakeZip:
    def __init__(self, infos):
        self._infos = infos

    def infolist(self):
        return self._infos


def test_status_aes_detected_from_method_99():
    zf = _FakeZip([_FakeInfo(encrypted=True, aes=False), _FakeInfo(encrypted=True, aes=True)])
    assert zip_encryption_status(zf) == "aes"


# --- verify_zip_password -----------------------------------------------------


def test_verify_noop_for_plain_zip(plain_zip):
    with zipfile.ZipFile(str(plain_zip)) as zf:
        # No encrypted entries → returns without raising, even with no password.
        verify_zip_password(zf, None)


def test_verify_raises_for_missing_and_wrong_password(enc_zip):
    with zipfile.ZipFile(str(enc_zip)) as zf:
        with pytest.raises(RuntimeError):
            verify_zip_password(zf, None)
        with pytest.raises(RuntimeError):
            verify_zip_password(zf, b"wrong")


def test_verify_passes_for_correct_password(enc_zip):
    with zipfile.ZipFile(str(enc_zip)) as zf:
        verify_zip_password(zf, _PASSWORD.encode())  # no raise


# --- password registry -------------------------------------------------------


def test_registry_set_get_clear(tmp_path):
    p = Path(str(tmp_path / "a.zip"))
    assert get_archive_password(p) is None
    set_archive_password(p, b"pw")
    assert get_archive_password(p) == b"pw"
    clear_archive_password(p)
    assert get_archive_password(p) is None


def test_registry_keyed_by_absolute_path(tmp_path, monkeypatch):
    # A relative and absolute Path to the same file share one registry entry.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.zip").write_bytes(b"")
    set_archive_password(Path("x.zip"), b"pw")
    assert get_archive_password(Path(str(tmp_path / "x.zip"))) == b"pw"
    clear_archive_password(Path("x.zip"))


# --- ZipHandler read path ----------------------------------------------------


def test_handler_encryption_status(enc_zip):
    h = ZipHandler(Path(str(enc_zip)))
    h.open()
    try:
        # The handler speaks the ABC's neutral vocabulary: ZipCrypto is a
        # scheme a password unlocks, whatever the format calls it.
        assert h.encryption_status() == "password"
    finally:
        h.close()


def test_handler_verify_password(enc_zip):
    h = ZipHandler(Path(str(enc_zip)))
    h.open()
    try:
        assert h.verify_password(b"wrong") is False
        assert h.verify_password(_PASSWORD.encode()) is True
    finally:
        h.close()


def test_handler_read_without_password_raises(enc_zip):
    h = ZipHandler(Path(str(enc_zip)))
    h.open()
    try:
        with pytest.raises(ArchivePasswordRequired):
            h.extract_to_bytes("message.txt")
    finally:
        h.close()


def test_handler_read_with_registered_password(enc_zip):
    fs_path = Path(str(enc_zip))
    set_archive_password(fs_path, _PASSWORD.encode())
    h = ZipHandler(fs_path)
    h.open()
    try:
        assert h.extract_to_bytes("message.txt") == _MESSAGE
    finally:
        h.close()


def test_handler_extract_to_file_with_password(enc_zip, tmp_path):
    fs_path = Path(str(enc_zip))
    set_archive_password(fs_path, _PASSWORD.encode())
    h = ZipHandler(fs_path)
    h.open()
    try:
        target = Path(str(tmp_path / "out.txt"))
        h.extract_to_file("message.txt", target)
        assert target.read_bytes() == _MESSAGE
    finally:
        h.close()


def test_handler_extract_to_file_without_password_raises(enc_zip, tmp_path):
    h = ZipHandler(Path(str(enc_zip)))
    h.open()
    try:
        with pytest.raises(ArchivePasswordRequired):
            h.extract_to_file("message.txt", Path(str(tmp_path / "out.txt")))
    finally:
        h.close()


# --- archive:// member path reads --------------------------------------------


def test_member_read_bytes_after_registering_password(enc_zip):
    zp = str(PathlibPath(str(enc_zip)).absolute())
    set_archive_password(Path(zp), _PASSWORD.encode())
    member = Path(f"archive://{zp}#message.txt")
    assert member.read_bytes() == _MESSAGE


# --- UI-facing gate helpers --------------------------------------------------


def test_get_member_archive_path(enc_zip):
    zp = str(PathlibPath(str(enc_zip)).absolute())
    member = Path(f"archive://{zp}#message.txt")
    assert str(get_member_archive_path(member)) == zp
    assert get_member_archive_path(Path(str(enc_zip))) is None  # ordinary file


def test_archive_password_state_transitions(enc_zip):
    zp = str(PathlibPath(str(enc_zip)).absolute())
    member = Path(f"archive://{zp}#message.txt")
    # Ordinary file is always ok (and never opens an archive).
    assert archive_password_state(Path(str(enc_zip))) == "ok"
    # Encrypted member needs a password until one is known.
    assert archive_password_state(member) == "need"
    assert try_archive_password(member, "wrong") is False
    assert archive_password_state(member) == "need"
    assert try_archive_password(member, _PASSWORD) is True
    assert archive_password_state(member) == "ok"


def test_archive_password_state_ok_for_plain_member(plain_zip):
    zp = str(PathlibPath(str(plain_zip)).absolute())
    member = Path(f"archive://{zp}#hello.txt")
    assert archive_password_state(member) == "ok"


def test_try_password_returns_false_for_non_member(enc_zip):
    assert try_archive_password(Path(str(enc_zip)), _PASSWORD) is False
