"""Layer E of #995: the agents' real CLIs, driven by XeFM's own code, with a
stand-in model (agent_standin.py) in place of theirs - no account, no quota.
That a CLI's sandbox keeps its shell from XeFM, that XeFM's tools answer all the
same, and that XeFM turned nothing off to get there.

It downloads the CLIs (pinned, checksummed) and runs them, so it belongs in a
guest, where nothing is signed in and everything is thrown away after:

    make test-vm GUEST=qa-mac ARGS="--agent-cli test/test_agent_cli.py"

Skipped without --agent-cli (or XEFM_AGENT_CLI=1). Where a version here is no
longer what people run, change it, and the checksum."""

import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from types import SimpleNamespace

import pytest

from agent_standin import Model
from xefm import agents, mcp_server, remote_server
from xefm import agent_chat as C

CODEX = "https://github.com/openai/codex/releases/download/rust-v0.171.0/codex-package-"
COPILOT = "https://github.com/github/copilot-cli/releases/download/v1.0.115/copilot-"
#: (program, system, machine): where it is, and its SHA-256.
CLIS = {
    ("codex", "darwin", "arm64"): (
        CODEX + "aarch64-apple-darwin.tar.gz",
        "58c88032ec446e72922d911d8f03773102da20c16a6059cf21f6744bce57f210"),
    ("codex", "linux", "aarch64"): (
        CODEX + "aarch64-unknown-linux-musl.tar.gz",
        "d8c43bee6cf11b01eb18b95f4d7961092bc40228180808859e70dabb7784c1c9"),
    ("copilot", "darwin", "arm64"): (
        COPILOT + "darwin-arm64.tar.gz",
        "f0858bbff5e35c4fe92d97a0061cb4a2a12b06defacf5512b77ca294175a12cf"),
    ("copilot", "linux", "aarch64"): (
        COPILOT + "linux-arm64.tar.gz",
        "889b423ce7e0dd41a298b95716d3d8fe80dc30f1fd9cf5419a95b6fb8d4e1bc8"),
    ("codex", "win32", "arm64"): (
        CODEX + "aarch64-pc-windows-msvc.tar.gz",
        "9715d5b310d05b0d878725763362b837857f5eb90fbe4ac57997f5e8656dc178"),
    ("codex", "win32", "amd64"): (
        CODEX + "x86_64-pc-windows-msvc.tar.gz",
        "669941eff23dd8470fbf85d919a03d80c4e3d35b441e3fcd361c0f8630945be8"),
    ("copilot", "win32", "arm64"): (
        COPILOT + "win32-arm64.zip",
        "cc3accfcf3bbce431cf9cd41198aec1e81c11908542825a6031726e6eac215cc"),
    ("copilot", "win32", "amd64"): (
        COPILOT + "win32-x64.zip",
        "256de3c3b8c00cbe5f738c9830f30b1d790d6693563689baade984295606af2c"),
}
WINDOWS = sys.platform == "win32"


def machine():
    """The computer's own: the Python may be an emulated x64 one on ARM."""
    if WINDOWS and os.environ.get("PROCESSOR_IDENTIFIER", "").startswith("ARM"):
        return "arm64"
    return platform.machine().lower() if WINDOWS else platform.machine()


pytestmark = pytest.mark.timeout(300)


def asked_for_clis(config):
    if not (config.getoption("--agent-cli", False) or os.environ.get("XEFM_AGENT_CLI")):
        pytest.skip("runs the agents' CLIs: --agent-cli, in a guest")


@pytest.fixture(autouse=True)
def asked_for(request):
    asked_for_clis(request.config)


@pytest.fixture(scope="module")
def clis(tmp_path_factory):
    """A folder with the CLIs found for this machine."""
    into = tmp_path_factory.mktemp("clis")

    def get(program):
        spot = into / program
        if not spot.exists():
            key = (program, sys.platform, machine())
            if key not in CLIS:
                pytest.skip(f"no {program} pinned for {key[1:]}")
            url, digest = CLIS[key]
            archive = into / url.rpartition("/")[2]
            if shutil.which("curl"):  # a python.org Python in a fresh guest has no CAs
                subprocess.run(["curl", "-fsSL", "-o", str(archive), url], check=True)
            else:
                with urllib.request.urlopen(url, timeout=120) as src, \
                        open(archive, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest, url
            if archive.suffix == ".zip":
                shutil.unpack_archive(archive, spot)
            else:
                with tarfile.open(archive) as tar:
                    tar.extractall(spot, filter="data")
        name = program + ".exe" * WINDOWS
        [found] = [p for p in spot.rglob(name) if p.is_file() and os.access(p, os.X_OK)]
        return str(found)
    return get


def sandbox_runs():
    """Docker's default profile lets no CLI make the namespaces its sandbox is."""
    if sys.platform != "linux":
        return True
    bwrap = shutil.which("bwrap")
    return bool(bwrap) and subprocess.run(
        [bwrap, "--unshare-all", "--ro-bind", "/", "/", "true"], capture_output=True).returncode == 0


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home of the test's own, outside every temporary folder (which a
    sandbox may let its shell write), with a session's folder in it."""
    import tempfile
    if WINDOWS:  # conftest moves USERPROFILE, not this
        real = pathlib.Path(os.environ["LOCALAPPDATA"]).parents[1]
    else:
        import pwd
        real = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
    home = pathlib.Path(tempfile.mkdtemp(prefix="xefm-agent-cli-", dir=real))
    (home / "ws").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / "codex"))
    (home / "codex").mkdir()
    monkeypatch.setenv("COPILOT_HOME", str(home / "copilot"))
    (home / "copilot").mkdir()
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    yield home
    shutil.rmtree(home, ignore_errors=True)


READ = {"command": ["pane", "selected"]}
WRITE = {"command": ["copy", "a", "--to", "b", "--wait"]}
# The path outside is in a variable: a path the CLI can read in the command it
# asks about first, and allowed it is no longer outside.
SHELL = ("xefmctl pane selected; echo rc=$?; "
         "curl -s -o /dev/null -w 'port=%{http_code}' \"$PROBE_URL\"; "
         "echo in-env=$(env | grep -v ^PROBE_ | grep -c \"$PROBE_SHAPE\"); "
         "echo x > \"$PROBE_OUTSIDE\" && echo wrote-outside")
if WINDOWS:
    SHELL = ("xefmctl pane selected; echo \"rc=$LASTEXITCODE\"; "
             "echo \"in-env=$(@(Get-ChildItem env: | Where-Object { $_.Name -notlike 'PROBE_*' "
             "-and $_.Value -like ('*' + $env:PROBE_SHAPE + '*') }).Count)\"; "
             "try { Set-Content -ErrorAction Stop $env:PROBE_OUTSIDE x; echo wrote-outside } "
             "catch { }")
STEPS = [("shell", SHELL),
         ("tool", mcp_server.READ_TOOL, READ), ("tool", mcp_server.TOOL, WRITE)]


#: The kind of sandbox that needs nothing set up by an administrator first.
WINDOWS_CODEX = ["-c", "windows.sandbox='unelevated'"] if WINDOWS else []


class Run:
    """XeFM's two ways in, and one turn of an agent through XeFM's own code."""

    def __init__(self, home, clis, preset, *, command=(), drawn, steps=STEPS):
        self.home, self.ws, self.requests = home, home / "ws", []
        self.remote = remote_server.RemoteServer(self.handle, python=sys.executable)
        self.mcp = mcp_server.McpServer(self.handle)
        self.channel = self.mcp.open("agent", str(self.ws))
        self.channel.session = "3"
        self.model = Model(steps)
        program = clis({"codex": "codex", "copilot": "copilot"}[preset])
        words = []
        if preset == agents.CODEX:
            words = ["-c", "model='standin'", "-c", "model_provider='standin'", "-c",
                     "model_providers.standin={name='standin',base_url='%s',wire_api='responses',"
                     "requires_openai_auth=false}" % self.model.url,
                     "-c", "sandbox_mode='workspace-write'", *WINDOWS_CODEX, *command]
        else:
            words = list(command)
        self.entry = agents.normalize({"name": "A", "command": [program, *words],
                                       "preset": preset, "terminal": not drawn})
        self.values = agents.prepare(SimpleNamespace(), self.entry, root=home / "cache",
                                     version="t", cwd=str(self.ws), channel=self.channel)
        env = self.remote.apply_env(dict(os.environ), "3", "agent")
        env.update(agents.session_env(self.entry, self.values, env))
        env.update(PROBE_URL=self.mcp.url, PROBE_SHAPE=self.channel.token[:8],
                   PROBE_OUTSIDE=str(home / "outside"))
        env["PATH"] += os.pathsep + os.path.dirname(os.path.realpath(sys.executable))
        if preset == agents.COPILOT:
            env.update(COPILOT_PROVIDER_BASE_URL=self.model.url, COPILOT_PROVIDER_TYPE="openai",
                       COPILOT_PROVIDER_API_KEY="none", COPILOT_MODEL="gpt-4.1",
                       COPILOT_OFFLINE="true")
        self.env, self.asked = env, []

    def handle(self, req):
        self.requests.append(req)
        return {"ok": True, "items": [{"path": f"reached-{req['cmd'].split()[0]}"}]}

    def chat(self):
        """The conversation XeFM draws."""
        from puikit import Panel
        from puikit.backends.memory_backend import MemoryBackend
        from test_agent_chat import _Posts
        from xefm.agent_chat_view import ChatView
        posts = _Posts()

        def ask(view, perm):
            # A command asked about again is asked to run outside the sandbox
            # (Copilot's two requests look the same).
            again = (perm.tool, dict(perm.input)) in self.asked
            self.asked.append((perm.tool, dict(perm.input)))
            view.answer(perm, C.deny() if again else C.allow(perm))
        self.view = ChatView(
            agents.chat_argv(self.entry, self.values), cwd=str(self.ws), env=self.env, name="A",
            post=posts, ask=ask, on_close_request=lambda v: None, on_hide=lambda v: None,
            protocol=agents.protocol(self.entry, self.values))
        panel = Panel(MemoryBackend(width=100, height=40))
        panel.push_layer(self.view, z=10, hints={"x": 0, "y": 0, "w": 100, "h": 40})
        self.view.start(panel)
        self.view._submit("go")
        import time
        end = time.monotonic() + 120
        conv = self.view.conversation

        def over():
            return len(self.model.results) >= len(self.model.steps) and conv.state == C.IDLE \
                or conv.state == C.EXITED or time.monotonic() > end
        posts.until(over, 130)
        self.view.close()
        return self

    def once(self, *instead):
        """The CLI's non-interactive mode, standing for its own screen: what
        XeFM gives that, ``instead`` of the request's option."""
        argv = agents.argv(self.entry, self.values)
        if self.entry["preset"] == agents.CODEX:
            argv = [argv[0], "exec", "--skip-git-repo-check", *argv[1:], *instead, "go"]
        else:
            argv = [*argv, *instead, "-p", "go"]
        done = subprocess.run(argv, cwd=self.ws, env=self.env, capture_output=True, text=True,
                              timeout=180, stdin=subprocess.DEVNULL)
        self.said = (done.stdout + done.stderr)[-1500:]
        return self

    def close(self):
        self.remote.close()
        self.mcp.close()
        self.model.close()
        agents.discard(self.values)

    @property
    def shell(self):
        return self.model.results.get("call_0", "")

    def check_tools(self):
        """Both tools answered, in order, as this session."""
        said = f"{self.model.results} {self.model.offered} {getattr(self, 'said', '')}"
        assert "reached-pane" in self.model.results.get("call_1", ""), said
        assert "reached-copy" in self.model.results.get("call_2", ""), said
        through = [r for r in self.requests if r["cmd"] in ("pane selected", "copy")]
        assert [r["policy"] for r in through][-1] == "agent" and through[-1]["session"] == "3"
        assert through[-1]["args"]["source"] == [str(self.ws / "a")]
        # XeFM's own tools are asked about by XeFM alone.
        assert not [a for a in self.asked if mcp_server.TOOL in json.dumps(a)
                    and "xefmctl pane selected;" not in json.dumps(a)], self.asked
        assert not [f for p in (self.home / "codex", self.home / "copilot")
                    for f in p.rglob("*") if self._holds_token(f)], "the token was written down"

    def _holds_token(self, file):
        try:
            return file.is_file() and self.channel.token.encode() in file.read_bytes()
        except PermissionError:
            return False  # the CLI has it open still (Windows)

    def check_contained(self):
        told = f"{self.shell}\nasked: {self.asked}"
        assert not (self.home / "outside").exists() and "wrote-outside" not in self.shell, told
        assert "in-env=0" in self.shell or "in-env" not in self.shell, told


@pytest.fixture
def run(home, clis):
    made = []

    def make(*args, **kw):
        made.append(Run(home, clis, *args, **kw))
        return made[-1]
    yield make
    for r in made:
        r.close()


needs_sandbox = pytest.mark.skipif(not sandbox_runs(), reason="no CLI's sandbox starts here")


@needs_sandbox
@pytest.mark.parametrize("drawn", [True, False], ids=["drawn", "exec"])
def test_codexs_sandbox_stays_on_and_its_tools_answer(run, drawn):
    r = run(agents.CODEX, drawn=drawn)
    # exec asks nothing: a tool that writes is refused there, as a user who
    # chose never to be asked has it.
    r.chat() if drawn else r.once("-c", "approval_policy='never'")
    said = f"{r.model.results} {r.__dict__.get('said')}"
    if WINDOWS:  # its sandbox cannot read the shim's folder
        assert "rc=0" not in r.shell and "reached" not in r.shell, said
    else:
        assert "rc=3" in r.shell, said
        assert "xefmctl_read" in r.shell  # it says what to use instead
    # Windows lets it reach the port, where there is nothing without the token.
    assert WINDOWS or "port=000" in r.shell or not shutil.which("curl"), said
    r.check_contained()
    if drawn:
        assert r.view.conversation.sandbox == "on"
        r.check_tools()
    else:
        assert "reached-pane" in r.model.results.get("call_1", ""), r.said


@needs_sandbox
def test_copilots_sandbox_stays_on_and_its_tools_answer(run):
    r = run(agents.COPILOT, command=["--sandbox"], drawn=True).chat()
    assert r.view.conversation.sandbox == "on"
    r.check_contained()
    r.check_tools()


def test_copilot_with_no_sandbox(run):
    r = run(agents.COPILOT, drawn=True).chat()
    assert r.view.conversation.sandbox == "not known"
    r.check_tools()


@needs_sandbox
def test_copilots_own_screen_gets_the_tools(run):
    r = run(agents.COPILOT, command=["--sandbox"], drawn=False)
    r.once("--allow-all-tools", "--allow-all-paths", "--disable-builtin-mcps")
    r.check_contained()
    r.check_tools()


def test_codex_keeps_the_servers_the_entry_names(run):
    """What XeFM puts in the thread's configuration is beside them."""
    mine = {"command": sys.executable, "args": ["-c", MINE]}
    r = run(agents.CODEX, drawn=True, steps=[("tool", "mine", {})], command=[
        "-c", f"mcp_servers.mine.command={json.dumps(mine['command'])}",
        "-c", f"mcp_servers.mine.args={json.dumps(mine['args'])}"]).chat()
    assert "mine-answered" in r.model.results.get("call_0", ""), r.model.offered
    assert mcp_server.READ_TOOL in r.model.offered


MINE = r'''
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    r = {"initialize": lambda: {"protocolVersion": m["params"]["protocolVersion"],
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "mine", "version": "0"}},
         "tools/list": lambda: {"tools": [{"name": "mine", "description": "x", "annotations":
                                           {"readOnlyHint": True}, "inputSchema":
                                           {"type": "object", "properties": {}}}]},
         "tools/call": lambda: {"content": [{"type": "text", "text": "mine-answered"}]},
         }.get(m["method"], dict)()
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
'''
