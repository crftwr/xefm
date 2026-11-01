"""tools/release_review.py reviews a release range against the core's rules
(#697): the mechanical ones as findings, the judgment ones as pointers, and
the public API compared across the whole release."""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import release_review as rr  # noqa: E402


def rules(items):
    return [(item.rule, item.where) for item in items]


# --- Source rules, on the lines the range added -----------------------------

SOURCE = '''\
import logging
from xefm.log_manager import getLogger

logger = getLogger("Fine")
bad = getLogger("not_pascal")
long = getLogger("AVeryLongLoggerName")
raw = logging.getLogger(__name__)


def f(self):
    print("hello")
    if self.logger:
        pass
    try:
        pass
    except:
        pass
'''


def test_every_source_rule_on_added_lines():
    found = rr.check_source("xefm/mod.py", SOURCE, set(range(1, 30)))
    assert sorted(rules(found)) == sorted([
        ("logger", "xefm/mod.py:5"), ("logger", "xefm/mod.py:6"),
        ("logger", "xefm/mod.py:7"), ("print", "xefm/mod.py:11"),
        ("logger", "xefm/mod.py:12"), ("except", "xefm/mod.py:16")])


def test_lines_from_before_the_range_are_not_judged_again():
    assert rr.check_source("xefm/mod.py", SOURCE, {1, 2, 4}) == []


@pytest.mark.parametrize("path", ["xefm/tools/vscode.py", "xefm/keys_cli.py"])
def test_print_is_the_output_of_a_cli_or_an_external_program(path):
    found = rr.check_source(path, 'print("out")\n', {1})
    assert found == []


def test_log_manager_may_call_logging_getlogger():
    source = "import logging\nlogging.getLogger('x')\n"
    assert rr.check_source("xefm/log_manager.py", source, {2}) == []


# --- Placement --------------------------------------------------------------

@pytest.mark.parametrize("path,flagged", [
    ("notes.txt", True),
    ("README.md", False),
    ("temp/temp_scratch.py", True),
    ("tools/temp_probe.py", True),
    ("doc/NEW_THING.md", True),
    ("doc/NEW_THING_FEATURE.md", False),
    ("doc/XEFM_USER_GUIDE.ja.md", False),        # named after its English page
    ("doc/dev/NOTES.md", True),
    ("doc/dev/NEW_THING_IMPLEMENTATION.md", False),
    ("doc/images/shot.png", False),
    ("xefm/test_inline.py", True),
    ("test/test_new.py", False),
])
def test_placement(path, flagged):
    assert bool(rr.check_placement(path)) is flagged


# --- Tables read from the tree ----------------------------------------------

ACTIONS = """\
## File list

| Action | What it does | AFX style | Vim style |
|---|---|---|---|
| `copy_files` | Copy | `C` | `y y` |
| `new_one` | New | — | — |

## Viewer

| Action | What it does | Keys |
|---|---|---|
| `viewer.close` | Close | `ESCAPE` |

## Old names

| Old name | Now |
|---|---|
| `old_copy` | `copy_files` |
"""


def test_default_keys_reads_action_tables_only():
    keys = rr.default_keys(ACTIONS)
    assert keys == {"copy_files": {"AFX style": "`C`", "Vim style": "`y y`"},
                    "new_one": {"AFX style": "—", "Vim style": "—"},
                    "viewer.close": {"Keys": "`ESCAPE`"}}


def test_setting_names():
    text = "class Config:\n    A = 1\n    B: int = 2\n    A = 3\n    def f(self): pass\n"
    assert rr.setting_names(text) == ["A", "B"]


def test_requirement_names():
    text = "# comment\npuikit>=1.17.0\nDoc_Files>=0.1  # why\n\ntruststore; sys_platform=='darwin'\n"
    assert rr.requirement_names(text) == {"puikit", "doc-files", "truststore"}


# --- The public API across the release --------------------------------------

def snapshot(version, *lines):
    return "\n".join([f"stable\tversion\txefm.user_api.API_VERSION\t{version}", *lines])


@pytest.fixture
def api(monkeypatch):
    """Serve *old* and *new* as the base's and head's snapshot; returns a
    function giving api_changes' (finding rules, note rules)."""
    def run(old, new):
        snapshots = {"BASE": old, "HEAD": new}
        monkeypatch.setattr(rr, "show", lambda ref, path: snapshots[ref])
        findings, notes = rr.api_changes("BASE", "HEAD")
        return [i.where for i in findings], [i.where for i in notes]
    return run


STABLE_F = "stable\tfunction\txefm.user_api.f\t[]"
DEPRECATED_F = "deprecated\tfunction\txefm.user_api.f\t[]"


def test_a_deprecation_that_never_shipped_cannot_be_removed(api):
    # Deprecated and removed in the same release: each step passed --write
    # (the removal with a bump), but no release ever carried the deprecation.
    assert api(snapshot(1, STABLE_F), snapshot(2)) == (["xefm.user_api.f"], [])


def test_removing_what_a_release_shipped_deprecated_is_a_bumped_break(api):
    assert api(snapshot(1, DEPRECATED_F), snapshot(2)) == ([], ["xefm.user_api.f"])


def test_a_break_whose_bump_was_lost(api):
    assert api(snapshot(1, DEPRECATED_F), snapshot(1)) == (["xefm.user_api.f"], [])


def test_api_version_moves_once_per_release(api):
    assert api(snapshot(1), snapshot(3)) == (["API_VERSION"], [])


def test_deprecations_additions_and_preview_go_to_the_note(api):
    old = snapshot(1, STABLE_F, "preview\tfunction\txefm.user_api.p\t[]")
    new = snapshot(1, DEPRECATED_F, "stable\tfunction\txefm.user_api.g\t[]")
    assert api(old, new) == ([], ["xefm.user_api.f", "xefm.user_api.g",
                                  rr.API_SNAPSHOT])


def test_a_base_without_a_snapshot_compares_nothing(api):
    assert api(None, snapshot(1)) == ([], [])


# --- Against a real range ---------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = os.path.realpath(tmp_path)
    monkeypatch.setattr(rr, "REPO_ROOT", root)

    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "-c", "commit.gpgsign=false", *args],
                       cwd=root, check=True, capture_output=True)

    def write(path, text, mode=None):
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
        if mode:
            os.chmod(full, mode)

    def commit(tag=None):
        git("add", "-A")
        git("commit", "-q", "-m", "c")
        if tag:
            git("tag", tag)

    git("init", "-q")
    write("xefm/_config.py", "class Config:\n    OLD = 1\n")
    write("xefm/mod.py", 'print("from before")\n')
    write("doc/OLD_FEATURE.md", "OLD\n")
    commit("v1.0.0")
    return write, commit


def test_a_range_judges_only_what_it_added(repo):
    write, commit = repo
    write("xefm/mod.py", 'print("from before")\nprint("new")\n')
    write("xefm/_config.py", "class Config:\n    OLD = 1\n    NEW_SETTING = 2\n")
    write("doc/NEW_FEATURE.md", "NEW\n")
    write("tools/script.py", "", mode=0o755)
    commit()

    changed = rr.changed_files("v1.0.0", "HEAD")
    assert sorted(changed) == [("A", "doc/NEW_FEATURE.md"), ("A", "tools/script.py"),
                               ("M", "xefm/_config.py"), ("M", "xefm/mod.py")]
    added = rr.added_lines("v1.0.0", "HEAD", "xefm/mod.py")
    assert added == {2}
    assert rules(rr.check_source("xefm/mod.py", rr.show("HEAD", "xefm/mod.py"),
                                 added)) == [("print", "xefm/mod.py:2")]
    assert rules(rr.check_permissions("HEAD")) == [("mode", "tools/script.py")]
    assert rules(rr.check_docs("v1.0.0", "HEAD", changed)) == [
        ("doc", "setting NEW_SETTING"), ("doc", "doc/NEW_FEATURE.md")]


def test_a_new_dependency_and_a_new_module_are_for_review(repo):
    write, commit = repo
    write("requirements.txt", "puikit>=1.0\n")
    commit("v1.1.0")
    write("requirements.txt", "puikit>=1.1\nnewlib>=2\n")
    write("xefm/fresh.py", "x = 1\n")
    commit()
    changed = rr.changed_files("v1.1.0", "HEAD")
    added = {p: rr.added_lines("v1.1.0", "HEAD", p) for _, p in changed}
    assert rules(rr.review_hints("v1.1.0", "HEAD", changed, added)) == [
        ("in-core?", "xefm/fresh.py"), ("dependency", "requirements.txt: newlib")]
