"""tools/fetch_libghostty.py: what the desktop bundles ship for XeFM's
terminal. Offline: downloads are faked; the real assets are pinned by hash."""

import hashlib
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import fetch_libghostty as fl  # noqa: E402

pytestmark = pytest.mark.host_only


def test_every_desktop_target_is_pinned_by_hash():
    assert set(fl.PINS) == {"macos", "windows-x64", "windows-arm64"}
    for asset, sha, member, name in fl.PINS.values():
        assert fl.VERSION in asset and len(sha) == 64 and int(sha, 16) >= 0
        assert name in ("libghostty-vt.dylib", "ghostty-vt.dll")


def test_every_notice_names_a_license_file_that_is_there():
    names = [n for n, _f in fl.notices()]
    assert any(n.startswith("libghostty-vt ") for n in names)
    for _name, file in fl.notices():
        path = os.path.join(fl.LICENSE_DIR, file)
        assert os.path.getsize(path) > 500, path


def test_print_notices_needs_no_target(capsys):
    assert fl.main(["--print-notices"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(fl.notices())
    assert all("=" in line and os.path.isfile(line.split("=", 1)[1]) for line in lines)


def test_a_macos_target_older_than_the_objects_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        fl.main(["--target", "macos", "--dest", str(tmp_path), "--macos-min", "12.0"])


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_cached_download_with_the_wrong_hash_is_fetched_again(tmp_path, monkeypatch):
    good = b"the real asset"
    sha = hashlib.sha256(good).hexdigest()
    (tmp_path / "a.zip").write_bytes(b"truncated")
    fetched = []
    monkeypatch.setattr(fl.urllib.request, "urlopen",
                        lambda req: fetched.append(req.full_url) or _Resp(good))
    path = fl.download("a.zip", sha, str(tmp_path))
    assert fetched and open(path, "rb").read() == good
    fetched.clear()
    fl.download("a.zip", sha, str(tmp_path))  # now cached and right: no fetch
    assert not fetched


def test_a_download_that_does_not_match_its_pin_stops_the_build(tmp_path, monkeypatch):
    monkeypatch.setattr(fl.urllib.request, "urlopen", lambda req: _Resp(b"something else"))
    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        fl.download("a.zip", "0" * 64, str(tmp_path))
    assert not os.path.exists(tmp_path / "a.zip")


def test_the_pin_is_the_version_the_installed_puikit_declares():
    from puikit import _ghostty
    assert fl.puikit_declared_version() == _ghostty.LIBGHOSTTY_VERSION == fl.VERSION


def test_a_puikit_written_for_another_version_stops_the_build(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "puikit_declared_version", lambda: "1.1.0")
    fetched = []
    monkeypatch.setattr(fl, "fetch", lambda *a, **k: fetched.append(a))
    with pytest.raises(SystemExit, match="written for libghostty-vt 1.1.0"):
        fl.main(["--target", "windows-x64", "--dest", str(tmp_path)])
    assert not fetched
