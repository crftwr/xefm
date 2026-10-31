"""XeFM's quality-loop adapter: the scenarios in qa/scenarios against the skill.

    make qa                          # every scenario
    make qa SCENARIO=reload_on_f12   # one (SCENARIO="01 07" for several)

`make qa` is `quality-loop run --foreground`; qa/quality-loop.toml names this
file as the adapter, so `quality-loop run 01` (in the background),
`quality-loop watch`, `quality-loop findings` and the conductor skill in
.claude/skills/quality-loop all reach it the same way.

Each scenario gets a room holding the skill exactly as `xefm skill --zip`
ships it and nothing else, and an operator agent that afterwards reports
what it finds, citing qa/evidence.py: the scenario's mechanical check (its
module in qa/checks/), the friction read off the transcript, the `xefm` calls.
A scenario with a Live check has the operator drive XeFM itself afterwards,
in the terminal, with what the room made still in place.

**Nothing of yours is touched.** The run has a home of its own, a temporary
directory: the room's `xefm` command runs with HOME pointing there, so its
`~/.xefm` (config.py, extensions/) is the run's, and a fixture config stands
in for config.py there. Your ~/.xefm is never set aside, so there is nothing
to put back after a run that died, and a running XeFM of yours is unaffected.
The room's own session keeps your HOME - Claude Code's login lives there -
and RULES.md tells it where the run's home is.

**In a VM** (xefm#750): with XEFM_QA_GUEST naming a guest (`qa-win`,
`qa-mac`; doc/dev/VM_TESTING_SYSTEM.md), the live check's XeFM runs in that
VM rather than here. The VM starts from its clean state for the run, this
working tree is staged there (qa/guest.py), and the run's home goes on the
shared folder, so XeFM in the guest loads what the room made. The operator's
terminal is still a pty on this machine; tools/vm_live.py puts the guest's
XeFM in it over `ssh -tt`. The room and the operator stay here.

The design is crftwr/keyhac#205; the harness is quality-loop
(crftwr/quality-loop). Before it, this was .claude/skills/xefm-skill-cleanroom.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import pathlib
import shlex
import shutil
import sys
import tempfile
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE / "checks"))

import outcome  # noqa: E402
import xefm  # noqa: E402
from quality_loop import adapter, audit, drive, session, standin  # noqa: E402

#: Tools the session has. `--restricted` removes Bash unless it is named, and
#: the extension scenario cannot be done without `xefm ext …` - so Bash is
#: named, and narrowed by ALLOW below instead.
TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "TodoWrite"]

#: What the room may run without asking - and, in a `-p` session under
#: dontAsk, everything else is refused. A shell can reach past the file tools'
#: confinement, so it gets the commands the skill tells an agent to run and no
#: more; a refusal is a finding (the skill named a command the room could not
#: run).
ALLOW = [
    "Read", "Glob", "Grep", "Write", "Edit", "TodoWrite",
    "Bash(xefm ext *)", "Bash(xefm skill *)", "Bash(xefm --version)",
    "Bash(python3 -c \"import ast*)", "Bash(python -c \"import ast*)",
    "Bash(python3 -m pytest*)", "Bash(python -m pytest*)",
    "Bash(cd *)", "Bash(ls *)", "Bash(mkdir *)",
    # The skill says to copy config.py before a larger edit.
    "Bash(cp *)",
]

#: Skills of this checkout that a clean room must not be able to see.
CHECKOUT_SKILLS = ("xefm-release", "puikit-release", "quality-loop")

#: The room's `xefm`: the subcommands the skill may run, nothing that opens a
#: window, with the run's home as HOME. Every call is logged, which is how
#: "never launch XeFM" is checked.
SHIM = """\
#!/bin/sh
printf '%s\\n' "$*" >> {log}
case "$1" in
  ext|skill|--version|-v)
    HOME={home} USERPROFILE={home} PYTHONPATH={root} exec {python} -c 'import sys; sys.argv[0] = "xefm"; from xefm.app import main; main()' "$@" ;;
  *)
    echo "xefm: refused in the clean room - this would open the file manager" >&2
    exit 64 ;;
esac
"""


class Home:
    """The run's own home, and the room's `xefm` that uses it. A temporary
    directory: outside the checkout and the run's directory, which a room
    must not reach."""

    def __init__(self, parent: pathlib.Path | None = None):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="xefm-qa-home-", dir=parent)).resolve()
        #: What runs here and not in a VM - the room's `xefm` and its log - is
        #: kept off the shared folder when the home is on one (``parent``).
        self.host = (pathlib.Path(tempfile.mkdtemp(prefix="xefm-qa-host-")).resolve()
                     if parent else self.root)
        self.xefm = self.root / ".xefm"
        self.xefm.mkdir()
        #: Where the stand-in keeps the previous fixture: out of the room's
        #: reach, which is ~/.xefm only.
        self.stand_in = self.root / "stand-in"
        #: The `xefm` calls' log, collected into each room's evidence.
        self.calls = self.host / "calls"
        self.calls.mkdir()
        #: The live check's panes: a directory with two files to select.
        self.work = self.root / "work"
        self.work.mkdir()
        for name in ("a.txt", "b.txt"):
            (self.work / name).write_text(f"{name}\n", encoding="utf-8")
        # The Tip of the Day dialog opens on a first launch and takes the
        # first keys a live check sends; a person who has used XeFM has long
        # since turned it off.
        from xefm.state_manager import StateManager
        StateManager(self.xefm / "state.db").set_state("tips.enabled", False)
        # Gone at exit even when no run's product() took it down - a home made
        # only to list the apps for `quality-loop check`.
        atexit.register(self.remove)
        self.bin = self.host / "bin"
        self.bin.mkdir()
        shim = self.bin / "xefm"
        shim.write_text(SHIM.format(log=shlex.quote(str(self.calls / "xefm-calls.log")),
                                    home=shlex.quote(str(self.root)),
                                    root=shlex.quote(str(ROOT)),
                                    python=shlex.quote(sys.executable)), encoding="utf-8")
        shim.chmod(0o755)
        # The extension scenario runs its package's tests, which need pytest;
        # the system python3 may not have it. This interpreter does, and it
        # cannot import xefm on its own (no PYTHONPATH), so it gives nothing
        # away. A wrapper, not a symlink: a venv is found next to the path a
        # Python was *started* by, so a symlinked venv python is the bare base.
        for name in ("python3", "python"):
            wrapper = self.bin / name
            wrapper.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n",
                               encoding="utf-8")
            wrapper.chmod(0o755)

    def environment(self) -> dict:
        """For a process that should see this home as ~ - XeFM itself."""
        return {"HOME": str(self.root), "USERPROFILE": str(self.root),
                "PYTHONPATH": str(ROOT)}

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.host, ignore_errors=True)


class XeFM(adapter.Adapter):
    name = "xefm"
    version = xefm.__version__
    checkout = ROOT
    rooms = ROOT / "cleanroom"
    scenarios = HERE / "scenarios"
    skill_name = "xefm"
    python = sys.executable
    evidence = {"xefm": {
        "argv": [sys.executable, str(HERE / "evidence.py")],
        "help": "check | friction | calls | config | keys"}}
    evidence_help = (
        "`xefm` is qa/evidence.py. `check <room>` runs the scenario's mechanical "
        "check on what the room left - the config loaded by XeFM's own "
        "ConfigManager, keys as XeFM parses them, associations as XeFM matches "
        "them, the user's `# keep:` lines, how much was rewritten - and answers "
        "the failures, empty when there are none. `friction <room>` lists where "
        "the transcript shows the room stumbling. `calls <room>` is every `xefm` "
        "command it ran. `config <room> [--before] [--backend gui]` is the "
        "config's values as XeFM loads them; `keys <room> <key>` the actions a "
        "key runs. Hold every room to "
        f"{HERE / 'scenarios' / '_always.md'} as well as to its scenario.")

    def __init__(self):
        self._home: Home | None = None
        self._foreign: set[str] = set()
        import guest as vm  # qa/guest.py
        alias = os.environ.get("XEFM_QA_GUEST")
        #: The VM the live check's XeFM runs in, or None to run it here.
        self.guest = vm.Guest.for_alias(alias) if alias else None
        #: While a VM run is up: its stage, and the live app's settings.
        self._stage: pathlib.Path | None = None
        self._live: pathlib.Path | None = None

    @property
    def apps(self) -> dict:
        """XeFM in the terminal, for a scenario's live check: under the run's
        home, so it loads the config and the extensions the room left, with
        the left pane on a directory of two files. The operator drives it;
        the room never does - its surface is the skill. In a VM run,
        tools/vm_live.py runs it there."""
        if self._live is not None:
            return {"xefm": drive.TerminalApp(
                [sys.executable, str(ROOT / "tools" / "vm_live.py"), str(self._live)],
                rows=40, cols=120)}
        return {"xefm": drive.TerminalApp(
            [sys.executable, "-c", "import sys; sys.argv[0] = 'xefm'; "
             "from xefm.app import main; main()", "--backend", "tui",
             "--left", str(self.home.work), "--right", str(self.home.root)],
            rows=40, cols=120, env=self.home.environment(), cwd=str(self.home.root))}

    @property
    def home(self) -> Home:
        """The run's home, made when a run first needs it - not when the
        adapter is merely loaded to list or check scenarios."""
        if self._home is None:
            self._home = Home(self.guest.host_share if self._stage is not None else None)
        return self._home

    def platform(self) -> str:
        return self.guest.platform if self.guest is not None else sys.platform

    def bundle(self) -> pathlib.Path:
        """The skill as `xefm skill --zip` ships it, unpacked: the zip holds
        one folder, xefm/, which becomes the room's skills/xefm."""
        from xefm import extensions as ext
        where = pathlib.Path(tempfile.mkdtemp(prefix="xefm-qa-skill-"))
        bundle = ext.write_skill_zip(where / ext.skill_zip_name())
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(where / "unpacked")
        return where / "unpacked" / "xefm"

    def rules(self) -> str:
        return (HERE / "RULES.md").read_text(encoding="utf-8").format(
            home=self.home.root, xefm=self.home.xefm)

    def session(self, room) -> session.Session:
        env = {"PATH": f"{self.home.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        if os.name != "nt":
            # The operator's login shell is nobody's skill: under zsh,
            # `echo =====` fails as an `=cmd` expansion, and a room paid a
            # step for it.
            env["SHELL"] = env["CLAUDE_CODE_SHELL"] = "/bin/bash"
        return session.Session(allow=ALLOW, tools=TOOLS, add_dirs=[self.home.xefm],
                               env=env, max_turns=80)

    def policy(self, room) -> audit.Policy:
        return audit.Policy(
            checkout=ROOT, bash=True, foreign=self._foreign,
            forbidden={"site-packages/xefm": "the installed xefm package",
                       "/Applications/XeFM.app": "the installed app",
                       str(ROOT.parent / "puikit"): "the PuiKit checkout",
                       str(self.home.stand_in): "the previous fixture, set aside"},
            leaked_skill=lambda command: any(s in command for s in CHECKOUT_SKILLS))

    @contextlib.contextmanager
    def product(self):
        """Nothing runs for the length of a run; the home goes at the end. In
        a VM run, the VM is up for its length, with this tree staged."""
        with contextlib.ExitStack() as stack:
            if self.guest is not None:
                stack.enter_context(self.guest.machine())
                stack.callback(self._unstage)
                self._stage = self.guest.stage("xefm-qa-stage-")
                print("vm:      installing the third-party packages in the guest...", flush=True)
                self._live = self._live_settings(self.guest.venv(self._stage,
                                                                 self.guest.requirements()))
            try:
                yield
            finally:
                if self._home is not None:
                    self._home.remove()
                    self._home = None

    def _live_settings(self, python: str) -> pathlib.Path:
        """What tools/vm_live.py needs to put XeFM up in the guest: the same
        command as a local live check, from the stage, under the run's home."""
        guest, stage, home = self.guest, self._stage, self.home
        environ = guest.environment(stage)
        environ.update(HOME=guest.path(home.root), USERPROFILE=guest.path(home.root))
        separator = ";" if guest.windows else ":"
        settings = {
            "guest": guest.to_settings(), "stage": str(stage), "environ": environ,
            "path": environ["PYTHONPATH"].split(separator), "cwd": guest.path(home.root),
            "argv": ["--backend", "tui", "--left", guest.path(home.work),
                     "--right", guest.path(home.root)],
            "python": python,
            "script": guest.path(stage / "tree" / "tools" / "vm_guest_xefm.py")}
        path = home.host / "live.json"
        path.write_text(json.dumps(settings), encoding="utf-8")
        return path

    def _unstage(self) -> None:
        if self._stage is not None:
            shutil.rmtree(self._stage, ignore_errors=True)
        self._stage = self._live = None

    def stand_in(self, case, variant, room):
        home = self.home
        check = outcome.load_checks([case.name])[0]
        self._foreign = {p.name for p in (home.xefm / "extensions").glob("*")}
        # Nothing here is yours: the stand-in swaps one fixture for the next
        # inside the run's home, and collects what the room made - the
        # extension it installed, the backup the skill tells it to make, its
        # `xefm` calls.
        return standin.StandIn(
            home=home.xefm, marker=home.stand_in,
            fixtures={"config.py": outcome.fixture_config(getattr(check, "FIXTURE",
                                                                  "template"))},
            evidence=room / "evidence",
            watch=[standin.Watch(home.xefm / "extensions", "extensions"),
                   standin.Watch(home.xefm / "extension-data", "extension-data"),
                   standin.Watch(home.xefm, "xefm",
                                 skip=("extensions", "extension-data", "tools",
                                       "state.db")),
                   standin.Watch(home.calls, "calls")])

    def restore(self) -> list[str]:
        return ["Nothing to restore: runs use a home of their own, and your ~/.xefm "
                "is never set aside."]
