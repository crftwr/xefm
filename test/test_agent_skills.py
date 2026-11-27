"""The user's own skills for XeFM's agent sessions (discussion #1009)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from xefm import agent_skills, agents, skills_cli


def _skill(root: Path, name: str, description: str = "Does a thing. Use when asked.",
           *, body: str = "# Steps\n", meta: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    head = meta if meta is not None else f"name: {name}\ndescription: {description}\n"
    (folder / "SKILL.md").write_text(f"---\n{head}---\n\n{body}", encoding="utf-8")
    return folder


def _entry(preset, command, **kw):
    return agents.normalize({"name": preset, "command": command, "preset": preset, **kw})


# --- reading a skill ----------------------------------------------------------------

def test_frontmatter_reads_what_a_skill_holds():
    text = ("﻿---\nname: a\ndescription: >\n  Two lines\n  folded.\n"
            "license: 'it''s MIT'\ncompatibility: \"say \\\"hi\\\"\"\n"
            "metadata:\n  owner: me\n# a comment\nother: plain # trailing\n---\nbody\n")
    assert agent_skills.frontmatter(text) == {
        "name": "a", "description": "Two lines folded.", "license": "it's MIT",
        "compatibility": 'say "hi"', "metadata": "", "other": "plain"}
    literal = "---\ndescription: |\n  one\n  two\n---\n"
    assert agent_skills.frontmatter(literal) == {"description": "one\ntwo"}
    assert agent_skills.frontmatter("no frontmatter") is None
    assert agent_skills.frontmatter("---\nname: a\n") is None


def test_a_good_skill_passes(tmp_path):
    skill = agent_skills.read(_skill(tmp_path, "sort-photos"))
    assert skill.ok and skill.name == "sort-photos"
    assert skill.description == "Does a thing. Use when asked."


@pytest.mark.parametrize("folder, meta, problem", [
    ("a", "description: d\n", "no 'name'"),
    ("a", "name: a\n", "no 'description'"),
    ("b", "name: a\ndescription: d\n", "differs from the folder's name"),
    ("Big", "name: Big\ndescription: d\n", "lowercase letters"),
    ("a--b", "name: a--b\ndescription: d\n", "lowercase letters"),
    ("-a", "name: -a\ndescription: d\n", "lowercase letters"),
    ("xefm", "name: xefm\ndescription: d\n", "XeFM's own skill"),
    ("a", "name: a\ndescription: " + "x" * 1025 + "\n", "longer than 1024"),
])
def test_what_keeps_a_skill_out(tmp_path, folder, meta, problem):
    skill = agent_skills.read(_skill(tmp_path, folder, meta=meta))
    assert not skill.ok and problem in " ".join(skill.problems)


def test_a_folder_without_a_readable_skill_md(tmp_path):
    (tmp_path / "empty").mkdir()
    assert "no SKILL.md" in agent_skills.read(tmp_path / "empty").problems[0]
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "SKILL.md").write_text("# no frontmatter\n")
    assert "frontmatter" in agent_skills.read(tmp_path / "plain").problems[0]
    assert "not a folder" in agent_skills.read(tmp_path / "missing").problems[0]


def test_scan_skips_hidden_folders_and_found_skips_bad_skills(tmp_path):
    _skill(tmp_path, "good")
    _skill(tmp_path, "bad", meta="name: other\ndescription: d\n")
    _skill(tmp_path, ".git")
    (tmp_path / "loose.md").write_text("x")
    assert [s.path.name for s in agent_skills.scan(tmp_path)] == ["bad", "good"]
    assert [s.name for s in agent_skills.found(tmp_path)] == ["good"]
    assert agent_skills.scan(tmp_path / "none") == []


def test_skills_live_in_the_config_folder():
    from xefm.config import config_manager
    assert agent_skills.skills_dir() == Path(config_manager.config_dir) / "skills"


# --- handing them to sessions -------------------------------------------------------

@pytest.fixture
def mine(tmp_path):
    root = tmp_path / "skills"
    folder = _skill(root, "sort-photos", "Sort photos by date.\n  Use for photos.",
                    meta="name: sort-photos\ndescription: >\n  Sort photos by date.\n"
                         "  Use for photos.\n")
    (folder / "references").mkdir()
    (folder / "references" / "more.md").write_text("more", encoding="utf-8")
    (folder / ".DS_Store").write_bytes(b"junk")
    _skill(root, "broken", meta="name: nope\n")
    return root


def _prepare(tmp_path, entry, user_skills):
    return agents.prepare(SimpleNamespace(), entry, root=tmp_path / "cache", version="t",
                          user_skills=user_skills)


def test_prepare_copies_the_users_skills_as_a_plugin_of_their_own(tmp_path, mine):
    values = _prepare(tmp_path, _entry("claude-code", ["claude"], terminal=True), mine)
    plugin = Path(values["{user_plugin_dir}"])
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == agents.USER_PLUGIN == "xefm-user"
    assert Path(values["{user_skills_dir}"]) == plugin / "skills"
    assert sorted(p.name for p in (plugin / "skills").iterdir()) == ["sort-photos"]
    copy = plugin / "skills" / "sort-photos"
    assert (copy / "references" / "more.md").read_text() == "more"
    assert not (copy / ".DS_Store").exists()
    assert values["user_skills"] == [("sort-photos", "Sort photos by date. Use for photos.",
                                      str(copy))]
    assert plugin != Path(values["{plugin_dir}"])


def test_a_skill_edited_or_removed_shows_at_the_next_launch(tmp_path, mine):
    entry = _entry("claude-code", ["claude"], terminal=True)
    _prepare(tmp_path, entry, mine)
    _skill(mine, "sort-photos", "Changed.")
    _skill(mine, "second")
    values = _prepare(tmp_path, entry, mine)
    assert [s[:2] for s in values["user_skills"]] == [("second", "Does a thing. Use when asked."),
                                                      ("sort-photos", "Changed.")]
    for name in ("second", "sort-photos", "broken"):
        if (mine / name).exists():
            import shutil
            shutil.rmtree(mine / name)
    values = _prepare(tmp_path, entry, mine)
    plugin = Path(values["{user_plugin_dir}"])
    assert values["user_skills"] == [] and list((plugin / "skills").iterdir()) == []


def test_claude_code_gets_a_second_plugin_dir_only_with_skills(tmp_path, mine):
    entry = _entry("claude-code", ["claude"], terminal=True)
    values = _prepare(tmp_path, entry, mine)
    argv = agents.argv(entry, values)
    at = argv.index(values["{plugin_dir}"])
    assert argv[at + 1:at + 3] == ["--plugin-dir", values["{user_plugin_dir}"]]
    drawn = agents.chat_argv(dict(entry, terminal=False), values)
    assert values["{user_plugin_dir}"] in drawn
    none = _prepare(tmp_path, entry, tmp_path / "nothing")
    assert argv.count("--plugin-dir") == 2
    assert agents.argv(entry, none).count("--plugin-dir") == 1


def test_copilot_gets_the_users_plugin_too(tmp_path, mine):
    entry = _entry("copilot", ["copilot"], restrict=False, terminal=True)
    values = _prepare(tmp_path, entry, mine)
    assert agents.argv(entry, values) == ["copilot", "--plugin-dir", values["{plugin_dir}"],
                                          "--plugin-dir", values["{user_plugin_dir}"]]
    drawn = agents.chat_argv(dict(entry, terminal=False), values)
    assert drawn[:6] == ["copilot", "--acp", "--plugin-dir", values["{plugin_dir}"],
                         "--plugin-dir", values["{user_plugin_dir}"]]


def test_codex_is_told_each_skills_name_description_and_path(tmp_path, mine):
    entry = _entry("codex", ["codex"], terminal=True)
    values = _prepare(tmp_path, entry, mine)
    argv = agents.argv(entry, values)
    text = tomllib.loads(f"v = {argv[2].partition('=')[2]}")["v"]
    path = Path(values["user_skills"][0][2]).as_posix()
    assert (f"- sort-photos: Sort photos by date. Use for photos. (file: {path}/SKILL.md)"
            in text)
    assert "broken" not in text
    # Drawn: the folder is added to Codex's skill roots.
    options = agents.protocol(dict(entry, terminal=False), values).options
    assert options["skills_roots"] == [values["{skills_dir}"], values["{user_skills_dir}"]]
    none = _prepare(tmp_path, entry, tmp_path / "nothing")
    assert "The user's skills" not in agents.codex_instructions(none)
    assert agents.protocol(dict(entry, terminal=False), none).options["skills_roots"] == [
        none["{skills_dir}"]]


def test_antigravitys_workspace_holds_the_users_skills(tmp_path, mine):
    for terminal in (True, False):
        entry = _entry("antigravity", ["agy"], terminal=terminal)
        values = agents.prepare(SimpleNamespace(), entry, root=tmp_path / "cache",
                                version="t", cwd="/work", user_skills=mine)
        skills = Path(values["workspace_dir"]) / ".agents" / "skills"
        assert sorted(p.name for p in skills.iterdir()) == ["sort-photos", "xefm"]
        assert (skills / "sort-photos" / "references" / "more.md").exists()


def test_an_entry_without_a_preset_may_name_the_folders(tmp_path, mine):
    entry = agents.normalize({"name": "X", "command": [
        "x", "--skills={user_skills_dir}", "--plugin={user_plugin_dir}"]})
    values = _prepare(tmp_path, entry, mine)
    assert agents.argv(entry, values) == [
        "x", f"--skills={values['{user_skills_dir}']}",
        f"--plugin={values['{user_plugin_dir}']}"]


def test_the_rules_say_where_an_xefm_skill_goes():
    rules = agents.rules_text(SimpleNamespace())
    assert "~/.xefm/skills/<name>/" in rules and "references/skills.md" in rules
    assert "next one" in rules


# --- xefm skills ----------------------------------------------------------------------

def test_list_says_which_skills_sessions_get(tmp_path, mine, capsys):
    assert skills_cli.main(["list"], root=mine) == 0
    out = capsys.readouterr().out
    assert "sort-photos  (ok)" in out and "Sort photos by date. Use for photos." in out
    assert "broken  (left out:" in out
    assert skills_cli.main(["list"], root=tmp_path / "none") == 0
    assert "no skills in" in capsys.readouterr().out


def test_check_by_name_by_folder_and_all(tmp_path, mine, capsys):
    assert skills_cli.main(["check", "sort-photos"], root=mine) == 0
    assert capsys.readouterr().out == "ok: sort-photos\n"
    assert skills_cli.main(["check", "broken"], root=mine) == 1
    assert "error: nope: name 'nope' differs" in capsys.readouterr().err
    assert skills_cli.main(["check"], root=mine) == 1
    elsewhere = _skill(tmp_path / "draft", "draft-skill")
    assert skills_cli.main(["check", str(elsewhere)], root=mine) == 0
    assert "not in" in capsys.readouterr().out
    assert skills_cli.main(["check", "missing"], root=mine) == 1


def test_path_prints_the_folder(tmp_path, capsys):
    assert skills_cli.main(["path"], root=tmp_path) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path)


# --- xefmctl skill (what a session has, with or without `xefm` on PATH) ---------------

def _xefmctl(app, line):
    import shlex
    from xefm import remote_cli, remote_commands, remote_dispatch
    req = remote_cli.parse(shlex.split(line))
    cmd = remote_commands.find(req["cmd"].split())[0]
    return remote_dispatch._answer(app, cmd, req)


@pytest.fixture
def xefmctl(monkeypatch, mine):
    monkeypatch.setattr(agent_skills, "skills_dir", lambda: mine)
    app = SimpleNamespace(_terminal_handed_over=False, _sessions=[])
    return lambda line: _xefmctl(app, line)


def test_xefmctl_skill_list(xefmctl, mine):
    answer = xefmctl("skill list")
    assert answer["folder"] == str(mine)
    rows = {r["name"]: r for r in answer["items"]}
    assert rows["sort-photos"]["state"] == "ok"
    assert rows["sort-photos"]["description"] == "Sort photos by date. Use for photos."
    assert rows["broken"]["state"].startswith("left out: ") and not rows["broken"]["ok"]


def test_xefmctl_skill_check(xefmctl, mine):
    good = xefmctl("skill check sort-photos")
    assert good.get("status", 0) == 0 and good["items"][0]["state"] == "ok"
    bad = xefmctl("skill check broken sort-photos")
    assert bad["status"] == 1 and "1 of 2" in bad["note"]
    assert xefmctl("skill check")["status"] == 1  # every skill, and one fails
    missing = xefmctl("skill check nothing-here")
    assert missing["status"] == 1 and "not a folder" in missing["items"][0]["state"]
    # A name, never a path: only the folder sessions are handed is read.
    for name in ("../etc", "/tmp/x", ".."):
        refused = xefmctl(f"skill check {name}")
        assert refused["ok"] is False and refused["code"] == 2


def test_xefmctl_skill_reads_only():
    from xefm import mcp_server, remote_commands
    for words in (["skill", "list"], ["skill", "check"]):
        cmd = remote_commands.find(words)[0]
        assert mcp_server.reads_only(cmd, {})
        assert remote_commands.AGENT_CLASS[cmd.name] == remote_commands.ALLOWED
        assert not remote_commands.needs_screen(cmd)  # works while XeFM is suspended
