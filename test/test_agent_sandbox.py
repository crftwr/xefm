"""The policy on AI agents' sandboxes (#995, doc/dev/AI_AGENT_SANDBOX_SYSTEM.md):
XeFM turns none off or wider, every session has a way to XeFM from outside it,
and the token of that way stays out of reach. Then the premise itself, in real
OS sandboxes of the tests' own: a shell in one is refused, with words that help,
while the tools answer."""

import ctypes
import io
import itertools
import json
import os
import pathlib
import platform
import stat
import subprocess
import sys
import urllib.request
from types import SimpleNamespace

import pytest

from xefm import agents, mcp_server, remote_cli, remote_server

REPO = pathlib.Path(__file__).resolve().parent.parent
PROGRAMS = {agents.CLAUDE_CODE: "claude", agents.CODEX: "codex",
            agents.COPILOT: "copilot", agents.ANTIGRAVITY: "agy", None: "other"}


def _channel():
    return mcp_server.Channel(name="xefm_0a1b2c3d", url="http://127.0.0.1:9/mcp",
                              token="T0KEN-" + "x" * 20, policy="agent", cwd="/work")


def _entry(preset, drawn, restrict=True, command=()):
    item = {"name": "A", "command": [PROGRAMS[preset], *command], "restrict": restrict,
            "terminal": not drawn}
    entry = agents.normalize(item | ({"preset": preset} if preset else {}))
    assert isinstance(entry, dict), entry
    return entry


def _handed(entry, root, channel=None):
    """``(argv, environment, values)`` of a session of ``entry``."""
    values = agents.prepare(SimpleNamespace(), entry, root=root, version="t",
                            cwd="/work", channel=channel)
    argv = agents.chat_argv(entry, values) if agents.drawn(entry) \
        else agents.argv(entry, values, "do it")
    return argv, agents.session_env(entry, values, {}), values


EVERY = [pytest.param(p, d, r, id=f"{p}-{'drawn' if d else 'terminal'}-{'' if r else 'un'}restricted")
         for (p, d), r in itertools.product(agents.CHANNELS, (True, False))]


# --- A. the policy ----------------------------------------------------------------------

def test_every_session_has_its_row():
    """A new preset, drawn or not, fails here until it has one."""
    kinds = {(p, False) for p in (*agents.PRESETS, None)} | {
        (p, True) for p in agents.DRAWN_PRESETS}
    assert set(agents.CHANNELS) == kinds


#: What would turn an agent's sandbox on, off or wider.
SANDBOX_WORDS = ("sandbox", "bypass", "yolo", "danger", "full-access", "fullaccess",
                 "allow-all", "skip-permissions", "approval", "--mode", "--add-dir",
                 "writable", "network", "permission-mode", "--allow-tool", "--allowed")
#: ... and what XeFM sends that reads like one of them, with why it is not.
ALLOWED_WORDS = {
    ("antigravity", "--add-dir"): "XeFM's own folder of rules, not the user's files",
    ("copilot", "--allow-tool=xefm_0a1b2c3d"): "XeFM's own tools, which XeFM asks about",
}


@pytest.mark.parametrize("preset, drawn, restrict", EVERY)
def test_nothing_xefm_sends_touches_a_sandbox(preset, drawn, restrict, tmp_path):
    entry = _entry(preset, drawn, restrict)
    argv, env, values = _handed(entry, tmp_path, _channel())
    prose = {values["{rules}"], agents.drawn_rules(values["{rules}"])}
    for arg in argv:
        if arg in prose or arg.startswith("developer_instructions=") or os.sep in arg:
            continue
        if (preset, arg) in ALLOWED_WORDS:
            continue
        assert not any(w in arg.lower() for w in SANDBOX_WORDS), arg
    settings = json.loads(pathlib.Path(values["{settings_file}"]).read_text())
    assert set(settings) <= {"permissions"} and set(settings.get("permissions", {})) <= {"deny"}
    assert not any(w in f"{k}={v}".lower() for k, v in env.items()
                   for w in ("sandbox", "yolo", "bypass"))
    if preset == agents.CODEX and drawn:
        [server] = agents.codex_server(_channel()).values()
        assert set(server) == {"url", "http_headers", "tool_timeout_sec"}


def test_a_users_own_sandbox_options_stay(tmp_path):
    for preset, drawn, words in ((agents.COPILOT, True, ["--sandbox"]),
                                 (agents.ANTIGRAVITY, False, ["--sandbox"]),
                                 (agents.CODEX, False, ["--sandbox", "read-only"])):
        argv, _, _ = _handed(_entry(preset, drawn, command=words), tmp_path, _channel())
        assert argv[1:1 + len(words)] == words


@pytest.mark.parametrize("preset, command, state", [
    (agents.CODEX, [], "not known"), (agents.CODEX, ["--yolo"], "off"),
    (agents.CODEX, ["--sandbox=danger-full-access"], "off"),
    (agents.CODEX, ["-s", "workspace-write"], "on"),
    (agents.COPILOT, [], "not known"), (agents.COPILOT, ["--sandbox"], "on"),
    (agents.COPILOT, ["--sandboxed-thing"], "not known"),
    (agents.ANTIGRAVITY, ["--sandbox"], "on"), (agents.CLAUDE_CODE, [], "not known"),
    (None, ["--sandbox"], "not known")])
def test_the_state_said_is_what_is_known(preset, command, state):
    assert agents.sandbox_state(_entry(preset, False, command=command)) == state


def test_a_terminal_session_says_its_sandbox_to_xefmctl_state():
    from xefm import remote_dispatch
    app = SimpleNamespace(_sessions=[
        SimpleNamespace(id=3, sandbox="on", view=object()),
        SimpleNamespace(id=4, sandbox="", view=SimpleNamespace(
            conversation=SimpleNamespace(sandbox="off"))),
        SimpleNamespace(id=5, sandbox="", view=object())], _agent_sandboxes={"agent": "not known"})
    said = [remote_dispatch.sandbox_of(app, {"session": s}) for s in ("3", "4", "5", "agent")]
    assert said == ["on", "off", "", "not known"]


# --- the way to XeFM ----------------------------------------------------------------------

@pytest.mark.parametrize("preset, drawn, restrict", EVERY)
def test_every_session_is_told_of_the_server_and_hides_the_token(preset, drawn, restrict, tmp_path):
    channel, entry = _channel(), _entry(preset, drawn, restrict)
    argv, env, values = _handed(entry, tmp_path, channel)
    assert channel.token not in " ".join(argv) + str(env)
    way = agents.CHANNELS[(preset, drawn)]
    holds = [p for p in tmp_path.rglob("*") if p.is_file()
             and channel.token in p.read_text(encoding="utf-8", errors="replace")]
    if way == "session":
        assert holds == []  # in the request that opens the session, over stdin
        assert agents.protocol(entry, values).channel is channel
        return
    [file] = holds
    folder = pathlib.Path(values["session_folder"])
    assert folder in file.parents
    if os.name != "nt":
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
    if way == "workspace":
        assert file == folder / ".agents" / "mcp_config.json"
        assert values["workspace_dir"] == str(folder)
    elif preset is not None:
        assert any(file.name in a for a in argv)
    # Another session's is another; both go with their sessions.
    _, _, other = _handed(entry, tmp_path, _channel())
    assert other["session_folder"] != values["session_folder"]
    agents.discard(values)
    assert not folder.exists() and os.path.isdir(other["session_folder"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs")
def test_on_windows_the_folder_is_open_to_its_user_alone(tmp_path):
    _, _, values = _handed(_entry(agents.CLAUDE_CODE, True), tmp_path, _channel())
    for path in (values["session_folder"], values["{mcp_config_file}"]):
        said = subprocess.run(["icacls", path], capture_output=True, text=True).stdout
        who = [line.replace(path, "").strip().partition(":(")[0]
               for line in said.splitlines() if ":(" in line]
        me = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
        assert {me, "owner rights"} & {w.lower() for w in who}, said
        others = [w for w in who if w.lower() != me and not w.lower().startswith(
            ("nt authority\\", "builtin\\administrators", "owner rights",
             "creator owner"))]
        assert not others, said


def test_the_file_opened_says_where_it_is(tmp_path):
    from xefm import remote_dispatch as D
    file = tmp_path / "Name.txt"
    file.write_text("x")
    with open(file, "rb") as f:
        final = D._final_path(f.fileno())
    assert final is not None or sys.platform not in ("darwin", "win32", "linux")
    assert D._key(final) == D._key(D._real(file))


def test_the_files_are_under_xefms_own_folder_not_a_temporary_one(monkeypatch, tmp_path):
    """Copilot's sandbox lets its shell read the temporary folder, and reach
    the port (macOS, measured)."""
    from xefm import config
    monkeypatch.setattr(config.config_manager, "config_dir", tmp_path / ".xefm")
    root = agents.cache_root()
    assert root == tmp_path / ".xefm" / "cache" / "agents"
    assert pathlib.Path.home() in type(config.config_manager)().config_dir.parents \
        or os.environ.get("XEFM_CONFIG_DIR")


def test_what_each_agent_is_told(tmp_path):
    channel = _channel()
    server = {"url": channel.url, "headers": channel.headers}

    def file(argv, option):
        path = argv[argv.index(option) + 1].removeprefix("@")
        return json.loads(pathlib.Path(path).read_text())["mcpServers"][channel.name]
    for drawn in (True, False):
        argv, _, _ = _handed(_entry(agents.CLAUDE_CODE, drawn), tmp_path, channel)
        assert file(argv, "--mcp-config") == dict(server, type="http")
        # It takes all that follows up to an option: never the request.
        assert argv[argv.index("--mcp-config") + 2].startswith("--")
    argv, _, _ = _handed(_entry(agents.COPILOT, False), tmp_path, channel)
    assert file(argv, "--additional-mcp-config") == dict(server, type="http", tools=["*"])
    argv, _, values = _handed(_entry(agents.ANTIGRAVITY, False), tmp_path, channel)
    told = json.loads((pathlib.Path(values["workspace_dir"]) / ".agents" / "mcp_config.json")
                      .read_text())
    assert told["mcpServers"][channel.name] == {"serverUrl": channel.url,
                                                "headers": channel.headers}
    argv, _, _ = _handed(_entry(agents.COPILOT, True), tmp_path, channel)
    assert f"--allow-tool={channel.name}" in argv
    entry = _entry(None, False, command=["--mcp", "{mcp_config_file}"])
    argv, _, _ = _handed(entry, tmp_path, channel)
    assert file(argv, "--mcp") == dict(server, type="http")


def test_codexs_screen_is_given_a_command_that_prints_the_header(tmp_path):
    root = tmp_path / "it's here"
    root.mkdir()
    channel = _channel()
    argv, _, values = _handed(_entry(agents.CODEX, False), root, channel)
    key = f"mcp_servers.{channel.name}"
    options = dict(a.split("=", 1) for a in argv if a.startswith(key))
    import tomllib
    options = {k: tomllib.loads(f"v = {v}")["v"] for k, v in options.items()}
    assert options[f"{key}.url"] == channel.url
    assert options[f"{key}.tool_timeout_sec"] == agents.TOOL_TIMEOUT
    printed = subprocess.run(options[f"{key}.http_headers_helper"], shell=True,
                             capture_output=True, text=True, check=True).stdout
    assert json.loads(printed) == channel.headers


def test_a_session_without_a_server_starts_as_before(tmp_path):
    for (preset, drawn) in agents.CHANNELS:
        argv, _, values = _handed(_entry(preset, drawn), tmp_path)
        assert not any("mcp" in a.lower() for a in argv if not os.sep in a and len(a) < 200)
        assert values["channel"] is None


# --- in the app -----------------------------------------------------------------------------

def test_a_sessions_token_lives_as_long_as_the_session(monkeypatch, tmp_path):
    from test_terminal_sessions import _agent_app
    from xefm.app import XeFMApp
    app = _agent_app(monkeypatch, tmp_path, [
        {"name": "Claude", "command": ["claude"], "preset": "claude-code", "terminal": True}])
    app._remote_handle = lambda req: {"ok": True, "items": []}
    app._agent_channel = XeFMApp._agent_channel.__get__(app)
    app.open_agent()
    app.open_agent()
    server = app._mcp_server
    try:
        first, second = list(app._sessions)
        one, two = server._channels
        assert (one.session, two.session) == (str(first.id), str(second.id))
        assert one.policy == "agent" and one.cwd == first.cwd == app._agent_folders[one.session]
        assert first.sandbox == "not known"
        app._read_folders = {one.session: {"/x"}}
        app._close_session(first)
        assert server._channels == [two] and one.session not in app._agent_folders
        assert app._read_folders == {}
        app._close_session(second)
        assert server._channels == [] and not list(tmp_path.glob("*/sessions/session-*"))
    finally:
        server.close()


def test_what_the_user_agreed_to_ends_with_a_session_in_terminal_mode(monkeypatch, tmp_path):
    """There every agent's session has the same id."""
    from test_terminal_sessions import _agent_app
    app = _agent_app(monkeypatch, tmp_path, [
        {"name": "Claude", "command": ["claude"], "preset": "claude-code", "terminal": True}])
    monkeypatch.setattr("xefm.app.is_desktop_mode", lambda: False)

    def run(argv, **kw):
        assert app._agent_folders["agent"] == kw["cwd"]
        app._read_folders = {"agent": {"/x"}}
        app._remote_read_sessions = {"agent"}
        return 0
    app._run_in_terminal = run
    app.open_agent()
    assert app._read_folders == {} and app._remote_read_sessions == set()
    assert app._agent_folders == {}


# --- D. a real OS sandbox ---------------------------------------------------------------------

# Run inside the sandbox: the client xefmctl runs, and the port.
INSIDE = r'''
import os, subprocess, sys, urllib.error, urllib.request
p = subprocess.run([sys.executable, "-I", sys.argv[1], "state", "--json"],
                   capture_output=True, text=True)
print("client", p.returncode, p.stdout.strip(), p.stderr.strip())
try:
    urllib.request.urlopen(urllib.request.Request(sys.argv[2], data=b"{}", method="POST"),
                           timeout=10)
    print("port answered")
except urllib.error.HTTPError as e:
    print("port", e.code)
except OSError as e:
    print("port refused")
if len(sys.argv) > 3:
    try:
        open(sys.argv[3], "w").close()
        print("wrote outside")
    except OSError as e:
        print("write refused")
'''


def _seatbelt(argv):
    """macOS, as Codex's and Claude Code's: no network, sockets included."""
    profile = ('(version 1)(deny default)(allow process*)(allow sysctl-read)(allow mach-lookup)'
               '(allow file-read*)(allow file-write* (literal "/dev/null"))'
               '(allow file-ioctl)(allow signal (target same-sandbox))')
    return ["/usr/bin/sandbox-exec", "-p", profile, *argv], {}


def _no_connect():
    """Linux, as Codex's: seccomp answers connect with EPERM."""
    arch, connect = {"x86_64": (0xC000003E, 42), "aarch64": (0xC00000B7, 203)}[platform.machine()]
    import struct
    code = [(0x20, 0, 0, 4), (0x15, 0, 3, arch), (0x20, 0, 0, 0), (0x15, 0, 1, connect),
            (0x06, 0, 0, 0x00050001), (0x06, 0, 0, 0x7FFF0000)]
    raw = ctypes.create_string_buffer(b"".join(struct.pack("HBBI", *c) for c in code))

    class Prog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]
    prog = Prog(len(code), ctypes.addressof(raw))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(prog), 0, 0):
        os._exit(99)


def _low_integrity(argv, env):
    """Windows, as Codex's unelevated sandbox: the user's own token at low
    integrity, which may read what the user may but not write or open for
    writing what is at medium - the pipe of xefmctl among it. Output comes back
    through inherited pipes: the process could open no file of ours."""
    import msvcrt
    from ctypes import wintypes as w
    k32, adv = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL(
        "advapi32", use_last_error=True)
    P = ctypes.POINTER
    k32.GetCurrentProcess.restype = w.HANDLE
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, P(w.HANDLE)]
    adv.DuplicateTokenEx.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_int, P(w.HANDLE)]
    adv.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, P(ctypes.c_void_p)]
    adv.GetLengthSid.argtypes = [ctypes.c_void_p]
    adv.SetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k32.CloseHandle.argtypes = [w.HANDLE]
    token, low = w.HANDLE(), w.HANDLE()
    # duplicate, query, assign primary, adjust default
    assert adv.OpenProcessToken(k32.GetCurrentProcess(), 0x008B, ctypes.byref(token)), \
        ctypes.get_last_error()
    assert adv.DuplicateTokenEx(token, 0x02000000, None, 2, 1, ctypes.byref(low))
    sid = ctypes.c_void_p()
    assert adv.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(sid))  # low

    class Label(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", w.DWORD)]
    label = Label(sid, 0x20)  # SE_GROUP_INTEGRITY
    assert adv.SetTokenInformation(low, 25, ctypes.byref(label),
                                   ctypes.sizeof(label) + adv.GetLengthSid(sid))

    class StartupInfo(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("r", w.LPWSTR), ("desktop", w.LPWSTR),
                    ("title", w.LPWSTR), *[(n, w.DWORD) for n in "x y cx cy ccx ccy fill".split()],
                    ("flags", w.DWORD), ("show", w.WORD), ("r2", w.WORD), ("r3", ctypes.c_void_p),
                    ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]

    class ProcessInfo(ctypes.Structure):
        _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD),
                    ("tid", w.DWORD)]
    read, write = os.pipe()
    os.set_inheritable(write, True)
    out = msvcrt.get_osfhandle(write)
    info = StartupInfo(cb=ctypes.sizeof(StartupInfo), flags=0x100, stdout=out, stderr=out)
    proc = ProcessInfo()
    adv.CreateProcessAsUserW.argtypes = [
        w.HANDLE, w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
        ctypes.c_void_p, w.LPCWSTR, P(StartupInfo), P(ProcessInfo)]
    block = ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in env.items()) + "\0")
    assert adv.CreateProcessAsUserW(low, None, ctypes.create_unicode_buffer(
        subprocess.list2cmdline(argv)), None, None, True, 0x08000400, block,
        None, ctypes.byref(info), ctypes.byref(proc)), ctypes.get_last_error()
    os.close(write)
    with os.fdopen(read, encoding="utf-8", errors="replace") as f:
        text = f.read()
    k32.WaitForSingleObject(proc.process, 60000)
    for h in (proc.process, proc.thread, token, low):
        k32.CloseHandle(h)
    return SimpleNamespace(stdout=text, stderr="")


def _sandboxed(argv, env):
    if sys.platform == "win32":
        return _low_integrity(argv, env)
    more = {}
    if sys.platform == "darwin":
        argv, more = _seatbelt(argv)
    elif sys.platform == "linux":
        more = {"preexec_fn": _no_connect}
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60, **more)


#: Linux musl, another machine: none is written for it.
HAS_SANDBOX = (sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec")) or (
    sys.platform == "linux" and platform.machine() in ("x86_64", "aarch64")) or (
    sys.platform == "win32")


@pytest.fixture
def xefm_here(tmp_path):
    """XeFM's two ways in, as a session has them."""
    def handle(req):
        return {"ok": True, "items": [{"reached": req["session"]}]}
    remote = remote_server.RemoteServer(handle, python=sys.executable)
    mcp = mcp_server.McpServer(handle)
    channel = mcp.open("agent", str(tmp_path))
    channel.session = "3"
    env = remote.apply_env(dict(os.environ), "3", "agent")
    yield SimpleNamespace(env=env, mcp=mcp, channel=channel)
    remote.close()
    mcp.close()


@pytest.mark.skipif(not HAS_SANDBOX, reason="no sandbox of the tests' own here")
def test_in_a_sandbox_the_shell_is_refused_in_words_and_the_tools_answer(xefm_here, tmp_path):
    script = tmp_path / "inside.py"
    script.write_text(INSIDE)
    target = pathlib.Path(os.path.expanduser("~")) / f"xefm-layer-d-{os.getpid()}"
    argv = [sys.executable, str(script), str(REPO / "xefm" / "remote_cli.py"), xefm_here.mcp.url,
            str(target)]
    outside = subprocess.run(argv, env=xefm_here.env, capture_output=True, text=True, timeout=60)
    assert 'client 0 {"reached": "3"}' in outside.stdout and "port 401" in outside.stdout
    target.unlink()
    inside = _sandboxed(argv, xefm_here.env)
    told = inside.stdout + inside.stderr
    assert "client 3" in inside.stdout, told
    assert "xefmctl_read" in inside.stdout and "sandbox" in inside.stdout
    if sys.platform != "linux":  # the tests' Linux sandbox stops connect alone
        assert "write refused" in inside.stdout and not target.exists(), told
    target.unlink(missing_ok=True)
    # Low integrity keeps the network; the port answers nothing without the token.
    assert ("port 401" if sys.platform == "win32" else "port refused") in inside.stdout, told
    # The agent's own process is outside: its tool call answers.
    req = urllib.request.Request(xefm_here.mcp.url, method="POST", headers=dict(
        xefm_here.channel.headers, Accept="application/json"), data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": mcp_server.READ_TOOL,
                "arguments": {"command": ["state", "--json"]}}}).encode())
    with urllib.request.urlopen(req, timeout=10) as got:
        assert '{\\"reached\\": \\"3\\"}' in got.read().decode()


def test_a_refused_connection_is_told_in_words(monkeypatch, capsys):
    import multiprocessing.connection as mc
    monkeypatch.setenv("XEFM_SOCKET", "/nowhere")
    monkeypatch.setenv("XEFM_TOKEN", "00")

    def refused(*a, **k):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(mc, "Client", refused)
    assert remote_cli.run(["state"], out=io.StringIO()) == 3
    said = capsys.readouterr().err
    assert "Operation not permitted" in said and "sandbox" in said and "xefmctl_read" in said
