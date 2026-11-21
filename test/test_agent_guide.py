"""What an extension tells AI agents (#952): ``[extension] agent_guide``, the
description its actions need, and ``xefm ext guide``."""

import pytest

from xefm import extensions as ext


@pytest.fixture
def package(tmp_path):
    return ext.scaffold("demo-pkg", tmp_path)


def _problems(root):
    _manifest, problems = ext.check_package(root)
    return problems


def _set(root, before, after):
    manifest = root / "xefm-extension.toml"
    text = manifest.read_text(encoding="utf-8")
    assert before in text
    manifest.write_text(text.replace(before, after), encoding="utf-8")


def test_the_scaffold_says_what_its_action_does(package):
    assert not [p for p in _problems(package) if "says nothing" in p.message]


def test_an_agent_guide_is_a_file_in_the_package(package):
    _set(package, 'min_xefm', 'agent_guide = "AGENT.md"\nmin_xefm')
    problems = _problems(package)
    assert any(p.where == "extension.agent_guide" and p.severity == "error"
               for p in problems)
    (package / "AGENT.md").write_text("# Using demo\n", encoding="utf-8")
    problems = _problems(package)
    assert not [p for p in problems if p.severity == "error"]
    assert "extension.agent_guide" in ext.preview_sections(ext.read_manifest(package))
    assert ext.read_manifest(package).agent_guide == package / "AGENT.md"


@pytest.mark.parametrize("value", ['"/etc/passwd"', '"../x.md"', '3'])
def test_an_agent_guide_outside_the_package_is_refused(package, value):
    _set(package, 'min_xefm', f'agent_guide = {value}\nmin_xefm')
    assert any(p.where == "extension.agent_guide" and p.severity == "error"
               for p in _problems(package))


def test_an_action_with_nothing_to_say_is_warned(package):
    actions = package / "demo_pkg" / "actions.py"
    source = actions.read_text(encoding="utf-8")
    import re
    bare = re.sub(r'(def hello\(ctx\):\n)(\s+"""[\s\S]*?"""\n)', r"\1", source)
    assert bare != source
    actions.write_text(bare, encoding="utf-8")
    [warning] = [p for p in _problems(package) if "says nothing" in p.message]
    assert warning.severity == "warning" and warning.where == 'contributes.actions."demo.hello"'
    # A description in the manifest is enough.
    _set(package, '{ entry = "demo_pkg.actions:hello" }',
         '{ entry = "demo_pkg.actions:hello", description = "Say hello" }')
    assert not [p for p in _problems(package) if "says nothing" in p.message]


def test_an_extension_contributes_agent_prompts(package):
    with open(package / "xefm-extension.toml", "a", encoding="utf-8") as f:
        f.write('\n[contributes.agent_prompts]\n'
                '"Durations" = "List these videos: length and resolution."\n'
                '"Review" = { prompt = "Review the diff.", agent = "Claude Code" }\n')
    problems = _problems(package)
    assert not [p for p in problems if p.severity == "error"], problems
    manifest = ext.read_manifest(package)
    # Text with a colon is a request, not a module:name reference.
    assert not [w for w, _ref in manifest.references() if "agent_prompts" in w]
    assert "contributes.agent_prompts" in ext.preview_sections(manifest)
    value = manifest.contributes["agent_prompts"]["Durations"]
    assert ext._value_for("agent_prompts", value, manifest, None, []) == value


def test_a_bad_agent_prompt_is_refused(package):
    with open(package / "xefm-extension.toml", "a", encoding="utf-8") as f:
        f.write('\n[contributes.agent_prompts]\n"Broken" = { text = "x" }\n')
    assert any(p.where.startswith("contributes.agent_prompts") and p.severity == "error"
               for p in _problems(package))
