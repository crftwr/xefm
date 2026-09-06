"""App-level tests for encrypted-zip extraction and the browse/view password
gate (issue #180).

Covers ``XeFMApp._extract_archive`` (real extraction with a password), the
``extract_archive`` UI flow (password prompt, wrong-then-right retry, AES
refusal), and ``_ensure_archive_password`` (the gate that guards opening a file
inside a browsed password-protected zip).

Run with: python -m pytest test/test_xefm_app_archive_password.py -v
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
from xefm.path import Path  # noqa: E402
from xefm.task import TaskManager  # noqa: E402

# Same ZipCrypto fixture as test_archive_password.py: message.txt +
# folder/note.txt, password "s3cr3t".
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
    p = tmp_path / "enc.zip"
    p.write_bytes(base64.b64decode(_ENCRYPTED_ZIP_B64))
    A.get_archive_cache().clear()
    A.clear_archive_password(Path(str(p)))
    yield p
    A.clear_archive_password(Path(str(p)))
    A.get_archive_cache().clear()


def _app():
    """A bare XeFMApp carrying only what the tested methods touch."""
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    app.logs = []
    app.log_info = app.logs.append
    app.panel = types.SimpleNamespace(render=lambda: None)
    app._active_pane_region = lambda: (0.0, 80.0)
    app.state_manager = None
    return app


class _InlineTasks(TaskManager):
    """The app's real task manager forced into synchronous mode: extraction runs
    on a worker thread behind a progress dialog, and these flow tests drive a bare
    app with no live panel to host one. Running the task inline keeps them about
    the password flow; the worker path itself is covered in
    test_archive_task.py."""

    def submit(self, task, panel, **kw):
        kw["background"] = False
        return super().submit(task, panel, **kw)


def _extract_app(entry, dest_dir, *, confirm=False):
    app = _app()
    app._focused_entry = lambda: entry
    app.pm = types.SimpleNamespace(get_inactive_pane=lambda: {"path": dest_dir})
    app.refreshes = []
    app._relist = lambda pane, **kw: app.refreshes.append(pane)
    app.config = types.SimpleNamespace(CONFIRM_EXTRACT_ARCHIVE=confirm)
    app.tasks = _InlineTasks()
    return app


# --- _extract_archive (core extraction) --------------------------------------


def test_extract_archive_with_correct_password(enc_zip, tmp_path):
    app = _app()
    dest = Path(str(tmp_path / "out"))
    count = app._extract_archive(Path(str(enc_zip)), dest, "zip", pwd=_PASSWORD.encode())
    assert count == 2
    assert (tmp_path / "out" / "message.txt").read_bytes() == _MESSAGE
    assert (tmp_path / "out" / "folder" / "note.txt").exists()


def test_extract_archive_wrong_password_raises_before_writing(enc_zip, tmp_path):
    app = _app()
    dest = Path(str(tmp_path / "out"))
    with pytest.raises(RuntimeError):
        app._extract_archive(Path(str(enc_zip)), dest, "zip", pwd=b"wrong")
    # The password is verified before extractall, so no member files were written.
    assert not (tmp_path / "out" / "message.txt").exists()


def test_extract_archive_missing_password_raises(enc_zip, tmp_path):
    app = _app()
    dest = Path(str(tmp_path / "out"))
    with pytest.raises(RuntimeError):
        app._extract_archive(Path(str(enc_zip)), dest, "zip", pwd=None)


# --- extract_archive UI flow -------------------------------------------------


def test_extract_flow_prompts_and_extracts(enc_zip, tmp_path, monkeypatch):
    out = Path(str(tmp_path / "dest"))
    (tmp_path / "dest").mkdir()
    entry = Path(str(enc_zip))
    app = _extract_app(entry, out)

    captured = []
    monkeypatch.setattr(xefm_app, "show_input", lambda panel, **kw: captured.append(kw))

    assert app.extract_archive() is False
    # A password prompt was raised (masked), not an immediate extraction.
    assert captured and captured[-1]["password"] is True
    assert not (tmp_path / "dest" / "enc" / "message.txt").exists()

    # Answer with the correct password → the extraction runs.
    captured[-1]["on_accept"](_PASSWORD)
    assert (tmp_path / "dest" / "enc" / "message.txt").read_bytes() == _MESSAGE
    # The working password is remembered for the session.
    assert A.get_archive_password(entry) == _PASSWORD.encode()


def test_extract_flow_wrong_then_right_password(enc_zip, tmp_path, monkeypatch):
    out = Path(str(tmp_path / "dest"))
    (tmp_path / "dest").mkdir()
    app = _extract_app(Path(str(enc_zip)), out)

    captured = []
    monkeypatch.setattr(xefm_app, "show_input", lambda panel, **kw: captured.append(kw))

    app.extract_archive()
    captured[-1]["on_accept"]("wrong")          # rejected → re-prompt
    assert len(captured) == 2
    assert "Incorrect password" in captured[-1]["prompt"]
    assert not (tmp_path / "dest" / "enc" / "message.txt").exists()

    captured[-1]["on_accept"](_PASSWORD)        # accepted → extracts
    assert (tmp_path / "dest" / "enc" / "message.txt").read_bytes() == _MESSAGE


def test_extract_flow_refuses_undecryptable(enc_zip, tmp_path, monkeypatch):
    out = Path(str(tmp_path / "dest"))
    (tmp_path / "dest").mkdir()
    app = _extract_app(Path(str(enc_zip)), out)

    monkeypatch.setattr(A, "archive_encryption_status_path", lambda path: "unsupported")
    prompted = []
    monkeypatch.setattr(xefm_app, "show_input", lambda panel, **kw: prompted.append(kw))

    app.extract_archive()
    assert prompted == []  # no password prompt for a scheme no password unlocks
    assert any("its encryption is not supported" in m for m in app.logs)


def test_extract_flow_plain_zip_no_prompt(tmp_path, monkeypatch):
    import zipfile
    zp = tmp_path / "plain.zip"
    with zipfile.ZipFile(str(zp), "w") as zf:
        zf.writestr("a.txt", b"hello")
    out = Path(str(tmp_path / "dest"))
    (tmp_path / "dest").mkdir()
    app = _extract_app(Path(str(zp)), out)

    prompted = []
    monkeypatch.setattr(xefm_app, "show_input", lambda panel, **kw: prompted.append(kw))

    app.extract_archive()
    assert prompted == []  # unencrypted → extracts straight away
    assert (tmp_path / "dest" / "plain" / "a.txt").read_bytes() == b"hello"


# --- _ensure_archive_password (browse/view gate) -----------------------------


def test_gate_ok_for_ordinary_file(tmp_path):
    app = _app()
    f = tmp_path / "plain.txt"
    f.write_text("hi")
    called = []
    app._ensure_archive_password(Path(str(f)), lambda: called.append(True))
    assert called == [True]  # ran immediately, no prompt


def test_gate_prompts_and_opens_on_correct_password(enc_zip, monkeypatch):
    app = _app()
    zp = os.path.abspath(str(enc_zip))
    member = Path(f"archive://{zp}#message.txt")

    captured = []
    monkeypatch.setattr(xefm_app, "show_input", lambda panel, **kw: captured.append(kw))
    called = []
    app._ensure_archive_password(member, lambda: called.append(True))

    assert captured and captured[-1]["password"] is True
    assert called == []                          # not opened yet
    captured[-1]["on_accept"]("wrong")           # rejected → re-prompt, still closed
    assert len(captured) == 2 and called == []
    captured[-1]["on_accept"](_PASSWORD)         # accepted → opens
    assert called == [True]
    assert A.get_archive_password(Path(zp)) == _PASSWORD.encode()


def test_gate_refuses_undecryptable(enc_zip, monkeypatch):
    app = _app()
    member = Path(f"archive://{os.path.abspath(str(enc_zip))}#message.txt")
    monkeypatch.setattr(A, "archive_password_state", lambda path: "unsupported")
    prompted = []
    monkeypatch.setattr(xefm_app, "show_input", lambda panel, **kw: prompted.append(kw))
    called = []
    app._ensure_archive_password(member, lambda: called.append(True))
    assert prompted == [] and called == []
    assert any("its encryption is not supported" in m for m in app.logs)


def test_gate_ok_when_password_already_known(enc_zip):
    app = _app()
    zp = os.path.abspath(str(enc_zip))
    A.set_archive_password(Path(zp), _PASSWORD.encode())
    member = Path(f"archive://{zp}#message.txt")
    called = []
    app._ensure_archive_password(member, lambda: called.append(True))
    assert called == [True]  # already unlocked → no prompt
