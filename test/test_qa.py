"""XeFM's quality-loop half: scenarios, their checks, the adapter, the evidence.

A run costs minutes and money, so what can be checked without one is checked
here: every scenario parses and has a check module; every check fails on the
untouched fixture (a run that did nothing must fail, unless doing nothing is
the right answer) and passes on its reference edit; the evidence tool answers
from a room's record; the room's `xefm` refuses to open the file manager; and
the friction reader finds what went wrong in a transcript. No session is
started here.

Run with: python -m pytest test/test_qa.py -v
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

pytest.importorskip("quality_loop", reason="quality-loop is not installed in this venv")

from quality_loop import cli, config, room as rooms, scenario  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
QA = ROOT / "qa"
sys.path.insert(0, str(QA / "checks"))
sys.path.insert(0, str(QA))

import outcome  # noqa: E402

SCENARIOS = outcome.load_checks()
CASES = scenario.load(QA / "scenarios")
FIXTURE = outcome.fixture_config()
#: A reply that says what a good one would, for the checks that read it.
REPLY = "Done. Ctrl-T was the command palette; choose the theme in View ▸ Theme."


def _fixture(scenario):
    return outcome.fixture_config(getattr(scenario, "FIXTURE", "template"))


def _failures(scenario, after, reply=REPLY):
    o = outcome.Outcome(before=_fixture(scenario), after=after, reply=reply)
    return outcome.common_failures(o, scenario.KIND) + scenario.check(o)


def _adapter():
    sys.modules.pop("run", None)
    return config.load_adapter(config.find(QA))


def test_every_scenario_has_its_check_and_they_are_in_order():
    names = [s.NAME for s in SCENARIOS]
    assert len(names) >= 7 and names == sorted(names)
    assert [c.name for c in CASES] == names, "a Markdown scenario per check module"
    assert [c.number for c in CASES] == list(range(1, len(CASES) + 1))
    for s in SCENARIOS:
        assert s.KIND in ("config", "extension")
        assert not hasattr(s, "PROMPT"), "the prompt lives in the Markdown only"


def test_the_fixture_loads_cleanly_and_carries_the_user_s_edits():
    loaded = outcome.inspect_config(FIXTURE)
    assert loaded["errors"] == []
    values = loaded["values"]
    assert values["KEY_PRESET"] == "afx"
    assert values["KEY_BINDINGS"] == {"quit": ["Shift-Q"]}
    assert values["CONFIRM_DELETE"] is False
    assert FIXTURE.count(outcome.KEEP) == 5
    assert outcome.common_failures(outcome.Outcome(FIXTURE, FIXTURE), "config") == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.NAME)
def test_doing_nothing_fails(scenario):
    failures = _failures(scenario, _fixture(scenario))
    if getattr(scenario, "UNTOUCHED_PASSES", False):
        assert failures == []
    else:
        assert failures, "a run that changed nothing would pass this check"


@pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s.reference],
                         ids=lambda s: s.NAME)
def test_the_reference_edit_passes(scenario):
    assert _failures(scenario, scenario.reference(_fixture(scenario))) == []


def test_losing_a_user_line_fails():
    edited = SCENARIOS[0].reference(_fixture(SCENARIOS[0])).replace("  # keep: my notes", "")
    assert any("lost the user's line" in f for f in _failures(SCENARIOS[0], edited))


def test_regenerating_the_file_from_the_template_fails():
    regenerated = (ROOT / "xefm" / "_config.py").read_text(encoding="utf-8")
    assert _failures(SCENARIOS[0], regenerated)


def test_launching_xefm_fails():
    o = outcome.Outcome(FIXTURE, FIXTURE, xefm_calls=["ext check .", "--backend gui"])
    assert any("launch XeFM" in f for f in outcome.common_failures(o, "config"))


def test_a_scripted_try_is_not_a_launch_and_an_interactive_one_is():
    scripted = ["try --config /h/.xefm/config.py --keys steps.json", "try --keys=s.json"]
    o = outcome.Outcome(FIXTURE, FIXTURE, xefm_calls=scripted)
    assert outcome.common_failures(o, "config") == []
    o = outcome.Outcome(FIXTURE, FIXTURE, xefm_calls=["try --config /h/.xefm/config.py"])
    assert any("launch XeFM" in f for f in outcome.common_failures(o, "config"))


def test_the_bare_fixture_has_no_template_text_but_the_same_edits():
    bare = outcome.fixture_config("bare")
    loaded = outcome.inspect_config(bare)
    assert loaded["errors"] == []
    assert loaded["values"]["KEY_BINDINGS"] == {"quit": ["Shift-Q"]}
    assert loaded["values"]["CONFIRM_DELETE"] is False
    assert "reload_config" not in bare and "FILE_ASSOCIATIONS" not in bare
    assert outcome.common_failures(outcome.Outcome(bare, bare), "config") == []


def test_some_scenarios_run_on_the_bare_fixture():
    assert {"template", "bare"} <= {getattr(s, "FIXTURE", "template") for s in SCENARIOS}


def test_dropping_the_default_associations_fails():
    """04's trap: a FILE_ASSOCIATIONS holding only the new rule."""
    scenario = next(s for s in SCENARIOS if s.NAME.startswith("04"))
    bare = _fixture(scenario)
    only_new = bare.replace("    CONFIRM_DELETE = False",
                            "    FILE_ASSOCIATIONS = [{'pattern': '*.log', 'view': ['less']}]\n"
                            "    CONFIRM_DELETE = False", 1)
    assert any(".jpg" in f for f in _failures(scenario, only_new))


@pytest.mark.parametrize("key,safe", [
    ("F2", True), ("Ctrl-UP", True), ("Ctrl-T", True), ("Shift-F", True),
    ("Ctrl-Shift-P", False), ("Cmd-K", False), ("Command-ENTER", False),
    ("Shift-SPACE", False), ("Ctrl-ENTER", False)])
def test_terminal_safe_keys(key, safe):
    assert outcome.terminal_safe(key) is safe


# --- friction: what the room stumbled on, noticed or not ---------------------------

import friction  # noqa: E402


def _transcript(path, calls, texts=(), result="Done.", subtype="success"):
    """A stream-json transcript: ``calls`` are (name, input, result, is_error)."""
    events = [{"type": "system", "subtype": "init", "slash_commands": []}]
    for n, (name, given, answer, error) in enumerate(calls):
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{n}", "name": name, "input": given}]}})
        events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{n}", "content": answer,
             "is_error": error}]}})
    for text in texts:
        events.append({"type": "assistant", "message": {"content": [
            {"type": "text", "text": text}]}})
    events.append({"type": "result", "subtype": subtype, "result": result})
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return path


def test_friction_finds_what_went_wrong(tmp_path):
    config = str(pathlib.Path.home() / ".xefm" / "config.py")
    transcript = _transcript(tmp_path / "t.jsonl", [
        ("Bash", {"command": "rm -rf /"}, "Permission to use Bash has been denied", True),
        ("Bash", {"command": "xefm ext check ."}, "error: contributes.actions: entry missing", False),
        ("Bash", {"command": "python -m pytest"}, "1 failed, 3 passed in 0.2s", False),
        ("Bash", {"command": "xefm ext check ."}, "ok", False),
        ("Grep", {"pattern": "reload_config"}, "No matches found", False),
        ("Write", {"file_path": config}, "File created", False),
        ("Write", {"file_path": config}, "File created", False),
        ("Bash", {"command": "xefm ext install ./logpaths"}, "installed", False),
        ("Bash", {"command": "xefm ext install ./logpaths"}, "installed", False),
    ], texts=["The skill does not say which key is free, so I guessed F12."],
        result="Stopped.", subtype="error_max_turns")
    kinds = [incident.kind for incident in friction.incidents(transcript)]
    assert kinds.count("tool error") == 1
    assert kinds.count("command trouble") == 2
    assert kinds.count("searched, found nothing") == 1
    assert kinds.count("rework") == 2          # config.py written twice, installed twice
    assert kinds.count("said so") == 1
    assert kinds.count("session") == 1


def test_friction_reads_a_refusal_logged_as_a_system_event(tmp_path):
    """A refused call is also logged as a system event whose "message" is a
    string, not a dict - every confined room has one."""
    transcript = _transcript(tmp_path / "t.jsonl", [
        ("Bash", {"command": "cat /etc/hosts"}, "Permission to use Bash has been denied", True)])
    lines = transcript.read_text(encoding="utf-8").splitlines()
    lines.insert(2, json.dumps({"type": "system", "subtype": "permission_denied",
                                "tool_name": "Bash", "tool_use_id": "t0",
                                "message": "Permission to use Bash has been denied"}))
    transcript.write_text("\n".join(lines), encoding="utf-8")
    kinds = [incident.kind for incident in friction.incidents(transcript)]
    assert kinds == ["tool error"]


def test_a_clean_run_has_no_friction_and_says_so(tmp_path):
    room = tmp_path / "room"
    room.mkdir()
    _transcript(room / "transcript.jsonl", [
        ("Edit", {"file_path": "x"}, "updated", False),
        ("Edit", {"file_path": "x"}, "updated", False),          # edits are not rework
        ("Bash", {"command": "xefm ext check ."}, "ok - no problems", False)],
        result="Put Reload Configuration on F12. Reload once to pick it up.")
    assert friction.incidents(room / "transcript.jsonl") == []
    assert "Nothing:" in friction.report(room)


def test_a_skill_page_that_says_error_is_not_trouble(tmp_path):
    """A room reads the skill through the shell; the page's own prose is not
    the command going wrong - even when a long output is cut mid-line."""
    room = tmp_path / "room"
    (room / "skills").mkdir(parents=True)
    (room / "skills" / "config.md").write_text(
        "A key bound to two actions is not an\n"
        "  error — one of them silently never fires. A `KEY_BINDINGS` entry\n",
        encoding="utf-8")
    _transcript(room / "transcript.jsonl", [
        ("Bash", {"command": "cat skills/config.md"},
         "A key bound to two actions is not an\n  error — one of them silently", False),
        ("Bash", {"command": "xefm ext check ."}, "error: contributes.actions", False)])
    found = friction.incidents(room / "transcript.jsonl")
    assert [(i.kind, i.step) for i in found] == [("command trouble", 2)]


def test_a_failure_shows_why_and_a_refusal_shows_what(tmp_path):
    transcript = _transcript(tmp_path / "t.jsonl", [
        ("Bash", {"command": "cat a.md; echo =====; cat b.md"},
         "Exit code 1\n# A\nsome text\n(eval):1: ==== not found", True),
        ("Bash", {"command": "rm log-paths/settings.py"},
         "Permission to use Bash has been denied because Claude Code is running in "
         "don't ask mode. IMPORTANT: You *may* attempt…", True)])
    failed, refused = friction.incidents(transcript)
    assert failed.evidence == "(eval):1: ==== not found"
    assert refused.detail == "refused: `rm log-paths/settings.py`"
    assert refused.evidence == ""


def test_writing_up_the_guesses_is_not_doubt(tmp_path):
    transcript = _transcript(tmp_path / "t.jsonl", [
        ("Edit", {"file_path": "QUESTIONS.md"}, "updated", False)],
        texts=["Now recording what I had to guess.",
               "Next I'll write the guesses into QUESTIONS.md.",
               "The config already binds the old name, so I edit that entry instead."])
    assert friction.incidents(transcript) == []


# --- the adapter: what a room gets, and what it may do -------------------------------

def test_the_command_line_finds_the_adapter_and_its_scenarios_check():
    settings = config.find(QA)
    assert settings.root == ROOT and settings.rooms() == (ROOT / "cleanroom").resolve()
    product = config.load_adapter(settings)
    assert product.name == "xefm"
    errors, _warnings = cli.check(product)
    assert errors == []


def test_bash_is_narrowed_and_the_room_reaches_only_the_run_s_home():
    product = _adapter()
    try:
        session = product.session(ROOT / "cleanroom" / "x")
        assert "Bash" in session.tools
        assert "Bash" not in session.allow and "Bash(*)" not in session.allow
        assert "Bash(xefm ext *)" in session.allow
        assert "Bash(xefm try *)" in session.allow
        assert "Bash(xefm keys *)" in session.allow
        assert session.add_dirs == [product.home.xefm]
        if os.name != "nt":  # Windows keeps its temp directory in the profile
            assert pathlib.Path.home() not in product.home.root.parents
        assert ROOT not in product.home.root.parents, "a room must not reach the checkout"
        assert session.env["PATH"].startswith(str(product.home.bin))
        policy = product.policy(ROOT / "cleanroom" / "x")
        assert policy.bash and any("puikit" in path for path in policy.forbidden)
        assert policy.leaked_skill("xefm-release") and policy.leaked_skill("quality-loop")
        rules = product.rules()
        assert f"{product.home.xefm}/config.py" in rules and "{" not in rules
    finally:
        product.home.remove()


def test_the_room_holds_the_skill_as_shipped_and_the_prompt_alone(tmp_path):
    product = _adapter()
    try:
        built = rooms.build(tmp_path / "rooms" / CASES[0].name, prompt=CASES[0].prompt,
                            rules=product.rules(), bundle=product.bundle(),
                            skill_name=product.skill_name, rooms=tmp_path / "rooms")
    finally:
        product.home.remove()
    assert (built / "skills" / "xefm" / "SKILL.md").is_file()
    task = (built / "TASK.md").read_text(encoding="utf-8")
    assert "Reload Configuration on F12" in task and "Must" not in task


@pytest.mark.skipif(os.name == "nt", reason="the room's xefm is a POSIX shell script")
def test_the_room_s_xefm_runs_the_cli_in_the_run_s_home_and_refuses_the_app():
    product = _adapter()
    home = product.home
    try:
        shim = str(home.bin / "xefm")
        refused = subprocess.run([shim, "--backend", "gui"], capture_output=True, text=True)
        assert refused.returncode == 64 and "refused" in refused.stderr
        # Without a script, try would hand the room's terminal to XeFM.
        refused = subprocess.run([shim, "try", "--keymap", "afx"], capture_output=True,
                                 text=True, timeout=10)
        assert refused.returncode == 64 and "--keys" in refused.stderr
        listed = subprocess.run([shim, "ext", "list"], capture_output=True, text=True,
                                timeout=120)
        assert listed.returncode == 0, listed.stderr
        keys = subprocess.run([shim, "keys", "quit"], capture_output=True, text=True,
                              timeout=120)
        assert keys.returncode == 0 and "quit" in keys.stdout, keys.stdout + keys.stderr
        calls = (home.calls / "xefm-calls.log").read_text().splitlines()
        assert calls == ["--backend gui", "try --keymap afx", "ext list", "keys quit"]
    finally:
        home.remove()


def _room(tmp_path, scenario, after, reply="Reload XeFM once to pick it up.", calls=()):
    room = tmp_path / scenario.NAME
    for part in ("before", "after", "calls"):
        (room / "evidence" / part).mkdir(parents=True)
    (room / "evidence" / "before" / "config.py").write_text(_fixture(scenario),
                                                            encoding="utf-8")
    (room / "evidence" / "after" / "config.py").write_text(after, encoding="utf-8")
    (room / "evidence" / "calls" / "xefm-calls.log").write_text(
        "".join(c + "\n" for c in calls), encoding="utf-8")
    (room / "transcript.jsonl").write_text(
        json.dumps({"type": "result", "result": reply}), encoding="utf-8")
    return room


def _evidence(*args):
    done = subprocess.run([sys.executable, str(QA / "evidence.py"), *map(str, args)],
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_check_answers_from_the_room_s_record(tmp_path):
    first = SCENARIOS[0]
    good = _room(tmp_path / "good", first, first.reference(_fixture(first)))
    assert _evidence("check", good)["failures"] == []
    untouched = _room(tmp_path / "bad", first, _fixture(first), calls=["--backend gui"])
    failures = _evidence("check", untouched)["failures"]
    assert any("F12" in f for f in failures) and any("launch XeFM" in f for f in failures)
    assert _evidence("calls", untouched) == ["--backend gui"]
    assert "reload_config" in _evidence("keys", good, "F12")["actions"]
    assert _evidence("keys", good, "F12", "--before")["actions"] == []
    assert _evidence("config", good)["values"]["KEY_PRESET"] == "afx"


def test_the_desktop_backend_is_read_as_the_desktop_app(tmp_path):
    """`--backend desktop` once loaded the terminal config (the first run's
    operator caught it): XeFM's name for the desktop backend is `gui`."""
    second = next(s for s in SCENARIOS if s.NAME.startswith("02"))
    room = _room(tmp_path, second, second.reference(_fixture(second)))
    tui = _evidence("config", room)["values"]["TEXT_EDITOR"]
    for name in ("gui", "desktop"):
        gui = _evidence("config", room, "--backend", name)["values"]["TEXT_EDITOR"]
        assert gui != tui and "code" in str(gui), name


# --- the live check: XeFM itself, in the terminal -----------------------------------

@pytest.mark.skipif(os.name == "nt", reason="terminal apps are driven in a POSIX pty")
@pytest.mark.timeout(90)
def test_the_live_check_s_xefm_starts_in_the_run_s_home_and_takes_keys(tmp_path):
    """What a Live check does first: start XeFM under the run's home, see the
    panes, press a key. The Tip of the Day used to open first and take it."""
    pytest.importorskip("pyte")
    from quality_loop import drive
    product = _adapter()
    try:
        home = product.home
        (home.xefm / "config.py").write_text(outcome.fixture_config("bare"), encoding="utf-8")
        apps = drive.manifest_entries(product.apps)
        assert apps["xefm"]["env"]["HOME"] == str(home.root)
        driver = drive.Driver(apps, tmp_path / "record")
        try:
            started = driver.start("xefm", "open XeFM on the work directory")
            assert "a" in started["screen"] and ".txt" in started["screen"]
            assert "Tip of the Day" not in started["screen"]
            helped = driver.keys(started["id"], ["F1"], "open the help")
            assert "Esc close" in helped["screen"]
        finally:
            driver.stop_all()
        steps = (tmp_path / "record" / "steps.jsonl").read_text().splitlines()
        assert len(steps) == 3
    finally:
        product.home.remove()


def test_only_scenarios_with_a_live_check_drive_the_app():
    live = [c.name for c in CASES if c.section("Live check").strip()]
    assert live == ["01_reload_on_f12", "07_extension_log_paths"]
