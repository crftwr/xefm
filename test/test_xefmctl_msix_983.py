"""xefmctl from the Store (MSIX) install (#983).

Nothing inside the package can be started by a process without its identity,
and no shell XeFM starts has it (Windows starts a child whose program lies
outside the package without it), so the shim's runtime\\python.exe was
"Access is denied" from every shell. The packaged XeFM's shim calls the
package's app execution alias instead, which starts xefmctl.exe with the
identity from anywhere."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from xefm import remote_server

ROOT = Path(__file__).resolve().parent.parent
WINDOWS_APP = ROOT / "windows_app"


# --- the shim's text --------------------------------------------------------------------

def test_outside_a_package_the_shim_runs_the_client_with_xefms_python():
    text = remote_server.windows_shim(r"C:\X\python.exe", r"C:\X\remote_cli.py",
                                      packaged=False)
    assert text == '@"C:\\X\\python.exe" -I "C:\\X\\remote_cli.py" %*\n'


def test_in_the_package_the_shim_calls_the_alias(tmp_path):
    alias = tmp_path / "xefmctl.exe"
    alias.write_bytes(b"")
    text = remote_server.windows_shim(r"C:\X\python.exe", r"C:\X\remote_cli.py",
                                      packaged=True, alias=str(alias))
    assert text == f'@"{alias}" %*\n'
    assert "python.exe" not in text


def test_with_the_alias_off_the_shim_says_how_to_turn_it_on(tmp_path):
    text = remote_server.windows_shim(r"C:\X\python.exe", r"C:\X\remote_cli.py",
                                      packaged=True, alias=str(tmp_path / "missing.exe"))
    # Never the interpreter's path: it exists in the package and cannot work.
    assert "python.exe" not in text
    assert remote_server.ALIAS_OFF in text and "exit /b 3" in text


def test_the_alias_off_message_is_safe_for_cmds_echo():
    message = remote_server.ALIAS_OFF
    assert message.isascii()
    assert not set(message) & set("<>|&^%")


def test_the_alias_lives_where_windows_puts_aliases(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    assert remote_server.store_alias_path() == os.path.join(
        r"C:\Users\me\AppData\Local", "Microsoft", "WindowsApps", "xefmctl.exe")


def test_a_test_run_is_not_packaged():
    assert remote_server.running_packaged() is False


def test_shells_are_not_handed_xefms_interpreter():
    # XEFM_PYTHON is gone: no shell in the Store package could start it.
    srv = remote_server.RemoteServer(lambda req: {"ok": True}, python=sys.executable)
    try:
        env = srv.apply_env({"PATH": ""}, "1")
        assert "XEFM_PYTHON" not in env
        assert {"XEFM_SOCKET", "XEFM_TOKEN", "XEFM_SESSION_KEY", "XEFM_SESSION"} <= set(env)
    finally:
        srv.close()


# --- the alias, the launcher and the client agree ----------------------------------------

def test_the_manifest_declares_the_alias_on_the_launcher():
    script = (WINDOWS_APP / "build_msix.ps1").read_text(encoding="utf-8")
    assert 'Category="windows.appExecutionAlias"' in script
    assert 'Executable="xefmctl.exe"' in script
    assert f'Alias="{remote_server.STORE_ALIAS}"' in script


def test_the_bundle_builds_the_launcher():
    script = (WINDOWS_APP / "build.ps1").read_text(encoding="utf-8")
    assert "'xefmctl.c'" in script and "'xefmctl.exe'" in script


def test_the_launcher_runs_the_client_where_the_bundle_puts_it():
    source = (WINDOWS_APP / "src" / "xefmctl.c").read_text(encoding="utf-8")
    found = re.search(r'runtime\\\\python\.exe\\" -I \\"%lsapp\\\\(\w+)\\\\(\w+\.py)', source)
    assert found, "the launcher's command line changed shape"
    package, client = found.groups()
    assert (ROOT / package / client).is_file()
    assert Path(remote_server.__file__).with_name(client).is_file()


# --- the shim as cmd runs it -------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
def test_cmd_runs_the_alias_off_shim(tmp_path):
    shim = tmp_path / "xefmctl.cmd"
    with open(shim, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(remote_server.windows_shim(sys.executable, "unused", packaged=True,
                                           alias=str(tmp_path / "missing.exe")))
    done = subprocess.run(["cmd", "/d", "/c", str(shim), "state"], capture_output=True,
                          text=True, timeout=20)
    assert done.returncode == 3
    assert done.stderr.strip() == remote_server.ALIAS_OFF and done.stdout == ""


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
def test_cmd_runs_the_shim_outside_a_package(tmp_path):
    client = Path(remote_server.__file__).with_name("remote_cli.py")
    shim = tmp_path / "xefmctl.cmd"
    with open(shim, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(remote_server.windows_shim(sys.executable, str(client), packaged=False))
    env = {k: v for k, v in os.environ.items() if not k.startswith("XEFM_")}
    done = subprocess.run(["cmd", "/d", "/c", str(shim), "state"], capture_output=True,
                          text=True, timeout=20, env=env)
    assert done.returncode == 2
    assert "XEFM_SOCKET is not set" in done.stderr
