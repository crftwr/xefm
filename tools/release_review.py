"""Review what is about to ship against the core's rules (#697).

    PYTHONPATH=. python tools/release_review.py                  # last tag..origin/main
    PYTHONPATH=. python tools/release_review.py --base v1.11.0 --head HEAD

The xefm-release skill runs this in step 2, before tagging. It reports and
fixes nothing: the user decides what to fix while the tag is still retractable.
One pass over everything about to ship catches drift no single PR shows, and
XeFM has no CI to catch it on the way in.

Two kinds of output, both from the same diff:

- **Findings** — the mechanical rules in CLAUDE.md, checked the same way every
  time: no ``print()`` under ``xefm/``, ``getLogger("Name")`` names, no bare
  ``except:``, no ``if self.logger:`` gate, ``*.py`` not executable, file
  placement, a doc for every new setting, a dev doc beside a new feature doc,
  current skill references and translations — and the public API compared
  across the whole release (below). Exit status 1 when there are any.
- **For review** — what the judgment rules (CLAUDE.md, "What belongs in the
  core") need looked at: new modules, new dependencies, scheme checks,
  capability reads, the firewall modules' imports, changed default keys, new
  actions no doc names. These are pointers for the reviewer, not verdicts, and
  never affect the exit status.

The public API is compared snapshot to snapshot, ``--base``'s
``test/data/api_snapshot.txt`` against ``--head``'s, with
``tools/api_snapshot.py``'s own classifier. ``make api-snapshot`` guards each
change against the commit before it; this sees what only the release as a
whole shows: an API deprecated and removed inside one release (its
deprecation never shipped, against STABLE_API_PLAN.md §9), a breaking change
whose bump was lost, ``API_VERSION`` moving more than once. Its breaking
changes, deprecations and stable additions are listed for the release note.

Only lines and files the range added are judged, so a deliberate ``print()``
from before the range is not reported again; file permissions are judged over
the whole tree at ``--head``. The skill-reference and translation checks run
the existing tools on the working tree, which should be checked out at
``--head`` (the script says so when it is not).
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import api_snapshot

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where ``print()`` is the output, not a stray diagnostic: the command-line
#: subcommands, and the end-user programs that run outside XeFM.
PRINT_OK = (re.compile(r"^xefm/tools/"), re.compile(r"^xefm/[^/]*_cli\.py$"))

#: The one module allowed to call ``logging.getLogger`` itself.
LOGGING_OK = ("xefm/log_manager.py",)

LOGGER_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{0,14}$")

#: Files the repo root already holds; anything else added there is a finding.
ROOT_FILES = {
    ".dockerignore", ".gitignore", "CLAUDE.md", "CONTRIBUTING.md", "LICENSE",
    "MANIFEST.in", "Makefile", "PRIVACY.md", "README.ja.md", "README.md",
    "SECURITY.md", "_config.yml", "pyproject.toml", "pytest.ini",
    "requirements-dev.txt", "requirements.txt",
}

USER_DOC = re.compile(r"^doc/[^/]+_FEATURE(\.ja)?\.md$")
DEV_DOC = re.compile(r"^doc/dev/[^/]+_(SYSTEM|IMPLEMENTATION)\.md$")

ACTIONS_MD = "xefm/skills/xefm/references/actions.md"
CONFIG_TEMPLATE = "xefm/_config.py"
API_SNAPSHOT = "test/data/api_snapshot.txt"
ACTION_ROW = re.compile(r"^\| `([a-z0-9_.]+)` \|")

#: The modules whose signatures are the public API (CLAUDE.md, "The public API").
FIREWALL = ("xefm/user_api.py", "xefm/path_base.py")

SCHEME_CHECK = re.compile(r"\.scheme\s*(==|!=|in\b|not in\b)")
CAPABILITY_READ = re.compile(
    r"\b(vector_shapes|colored_underlines|is_desktop_mode\(|ctx\.images)\b")


@dataclass
class Item:
    rule: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"  [{self.rule}] {self.where}: {self.message}"


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True,
                            cwd=REPO_ROOT)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def show(ref: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True,
                            text=True, cwd=REPO_ROOT)
    return result.stdout if result.returncode == 0 else None


def changed_files(base: str, head: str) -> list[tuple[str, str]]:
    """(status letter, path at *head*) for every file the range touched."""
    out = []
    for line in git("diff", "--name-status", "-M", base, head).splitlines():
        fields = line.split("\t")
        if fields[0].startswith("D"):
            continue
        out.append((fields[0][0], fields[-1]))
    return out


def added_lines(base: str, head: str, path: str) -> set[int]:
    """Line numbers in *head*'s copy of *path* that the range added."""
    lines: set[int] = set()
    diff = git("diff", "-U0", "-M", base, head, "--", path)
    for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        lines.update(range(start, start + count))
    return lines


# --- Findings --------------------------------------------------------------

def check_source(path: str, source: str, added: set[int]) -> list[Item]:
    """print(), logger use and bare except: on the lines the range added."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Item("syntax", f"{path}:{exc.lineno}", str(exc.msg))]
    print_ok = any(p.match(path) for p in PRINT_OK)
    found = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if line not in added:
            continue
        where = f"{path}:{line}"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "print" and not print_ok:
                found.append(Item("print", where,
                                  "print() under xefm/ — use the unified logger"))
            elif (isinstance(func, ast.Attribute) and func.attr == "getLogger"
                  and isinstance(func.value, ast.Name) and func.value.id == "logging"
                  and path not in LOGGING_OK):
                found.append(Item("logger", where,
                                  "logging.getLogger — use xefm.log_manager.getLogger"))
            elif isinstance(func, ast.Name) and func.id == "getLogger":
                arg = node.args[0] if node.args else None
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and LOGGER_NAME.match(arg.value)):
                    found.append(Item("logger", where,
                                      'logger name is not getLogger("PascalCase"), '
                                      "≤15 chars"))
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            found.append(Item("except", where, "bare except: — name the exception"))
        elif (isinstance(node, ast.If) and isinstance(node.test, ast.Attribute)
              and node.test.attr == "logger"):
            found.append(Item("logger", where,
                              "if self.logger: — the logger is always present"))
    return found


def check_permissions(head: str) -> list[Item]:
    found = []
    for line in git("ls-tree", "-r", head).splitlines():
        meta, path = line.split("\t", 1)
        if meta.split()[0] == "100755" and path.endswith(".py"):
            found.append(Item("mode", path, "*.py is executable — run it via python3"))
    return found


def check_placement(path: str) -> list[Item]:
    name = path.rsplit("/", 1)[-1]
    if path.startswith("temp/") or name.lower().startswith("temp_"):
        return [Item("place", path, "a temporary file is committed")]
    if "/" not in path and path not in ROOT_FILES:
        return [Item("place", path, "new file at the repo root")]
    if path.startswith("doc/") and path.endswith(".md"):
        # A translation is named after its English page, so only that is judged.
        if path.count("/") == 1 and not path.endswith(".ja.md") \
                and not USER_DOC.match(path):
            return [Item("place", path, "user doc not named <NAME>_FEATURE.md")]
        if path.startswith("doc/dev/") and path.count("/") == 2 \
                and not DEV_DOC.match(path):
            return [Item("place", path,
                         "dev doc not named <NAME>_SYSTEM.md / _IMPLEMENTATION.md")]
    if name.startswith("test_") and name.endswith(".py") \
            and not path.startswith("test/"):
        return [Item("place", path, "a test outside test/")]
    return []


def setting_names(text: str | None) -> list[str]:
    """The ``Config`` class's settings, in order."""
    if not text:
        return []
    for node in ast.parse(text).body:
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            names = []
            for stmt in node.body:
                targets = stmt.targets if isinstance(stmt, ast.Assign) else \
                    [stmt.target] if isinstance(stmt, ast.AnnAssign) else []
                names += [t.id for t in targets
                          if isinstance(t, ast.Name) and t.id not in names]
            return names
    return []


def user_docs_text(head: str) -> str:
    paths = [p for p in git("ls-tree", "-r", "--name-only", head, "--", "doc").split()
             if p.count("/") == 1 and p.endswith(".md") and not p.endswith(".ja.md")]
    return "\n".join(show(head, p) or "" for p in paths)


def named_in(name: str, text: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", text) is not None


def check_docs(base: str, head: str, changed: list[tuple[str, str]]) -> list[Item]:
    found = []
    docs = user_docs_text(head)
    old = set(setting_names(show(base, CONFIG_TEMPLATE)))
    for name in setting_names(show(head, CONFIG_TEMPLATE)):
        if name not in old and not named_in(name, docs):
            found.append(Item("doc", f"setting {name}",
                              "new setting is named in no doc/*.md"))
    paths = [p for _, p in changed]
    new_features = [p for s, p in changed
                    if s == "A" and USER_DOC.match(p) and not p.endswith(".ja.md")]
    if new_features and not any(DEV_DOC.match(p) for p in paths):
        for path in new_features:
            found.append(Item("doc", path, "new feature doc, but the range touches "
                                           "no doc/dev/*_IMPLEMENTATION.md"))
    return found


def api_changes(base: str, head: str) -> tuple[list[Item], list[Item]]:
    """(findings, for-review items) from the public API across the release."""
    old_text, new_text = show(base, API_SNAPSHOT), show(head, API_SNAPSHOT)
    if old_text is None or new_text is None:
        return [], []
    old, new = api_snapshot.parse(old_text), api_snapshot.parse(new_text)
    before, after = api_snapshot.version(old), api_snapshot.version(new)
    findings, notes = [], []
    changes = api_snapshot.classify(old, new)
    if after - before > 1:
        findings.append(Item("api", "API_VERSION",
                             f"{before} → {after}: one release moves it once"))
    for category, name, why in changes:
        if category == "breaking":
            if why == "removed without being deprecated first":
                findings.append(Item("api", name, f"stable at {base}, {why} — "
                                     "its deprecation must ship in a release"))
            elif after <= before:
                findings.append(Item("api", name,
                                     f"breaking ({why}) and API_VERSION is still "
                                     f"{after}"))
            else:
                notes.append(Item("api", name,
                                  f"breaking: {why} — a bullet of the note"))
        elif category == "deprecation":
            notes.append(Item("api", name, "deprecated — the note names the "
                                           "replacement"))
        elif category == "addition":
            notes.append(Item("api", name, f"stable {why} — the note's \"Also\""))
    preview = sum(1 for category, _, _ in changes if category == "preview")
    if preview:
        notes.append(Item("api", API_SNAPSHOT,
                          f"{preview} Preview changes — any an extension author "
                          "would notice go in the note's \"Also\""))
    return findings, notes


def run_tool(rule: str, argv: list[str], fix: str) -> list[Item]:
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    result = subprocess.run([sys.executable, *argv], capture_output=True,
                            text=True, cwd=REPO_ROOT, env=env)
    if result.returncode == 0:
        return []
    detail = (result.stderr or result.stdout).strip().splitlines()
    return [Item(rule, argv[0], f"{detail[-1] if detail else 'failed'} ({fix})")]


# --- For review ------------------------------------------------------------

def review_hints(base: str, head: str, changed: list[tuple[str, str]],
                 added: dict[str, set[int]]) -> list[Item]:
    hints = []
    for status, path in changed:
        if status == "A" and path.startswith("xefm/") and path.endswith(".py") \
                and not path.startswith("xefm/tools/"):
            hints.append(Item("in-core?", path, "new module — could it be an extension?"))
    for path in ("requirements.txt", "requirements-dev.txt"):
        old = requirement_names(show(base, path))
        for name in sorted(requirement_names(show(head, path)) - old):
            hints.append(Item("dependency", f"{path}: {name}",
                              "new dependency — supported but not required? license?"))
    for status, path in changed:
        if not (path.startswith("xefm/") and path.endswith(".py")):
            continue
        lines = (show(head, path) or "").splitlines()
        for n in sorted(added.get(path, ())):
            if n > len(lines):
                continue
            text = lines[n - 1]
            if SCHEME_CHECK.search(text):
                hints.append(Item("generalize", f"{path}:{n}",
                                  "scheme check — would a capability check do?"))
            if CAPABILITY_READ.search(text):
                hints.append(Item("puikit/parity", f"{path}:{n}",
                                  "backend capability read — ornament only, "
                                  "and does the other backend get the feature?"))
            if path in FIREWALL and re.match(r"\s*(from|import)\s+(puikit|xefm\.app)\b",
                                             text):
                hints.append(Item("firewall", f"{path}:{n}",
                                  "public API module imports PuiKit or the app"))
    base_actions = show(base, ACTIONS_MD)
    if base_actions is None:        # older than the generated table: no baseline
        return hints
    old_keys = default_keys(base_actions)
    docs = user_docs_text(head)
    for name, keys in default_keys(show(head, ACTIONS_MD)).items():
        old = old_keys.get(name, {})
        # A doc may name the menu item instead of the action (CLAUDE.md), so
        # no mention by name is a question, not a finding.
        if name not in old_keys and not named_in(name, docs):
            hints.append(Item("doc", f"action {name}",
                              "new action is named in no doc/*.md — "
                              "documented by its menu item?"))
        changed_keys = [f"{preset}: {cell}" for preset, cell in keys.items()
                        if cell != old.get(preset, cell if old else "—")]
        if changed_keys:
            hints.append(Item("keys", f"action {name}",
                              "new default keys — can a terminal deliver them? "
                              + "; ".join(changed_keys)))
    return hints


def default_keys(text: str | None) -> dict[str, dict[str, str]]:
    """Action name → {preset column: its key cell}, from actions.md's tables.

    Only tables headed ``| Action |`` count — the "Old names" table lists
    names, not actions — and a column is named by its header, so a preset
    added since the base is a new column rather than a change to every row.
    """
    actions: dict[str, dict[str, str]] = {}
    columns = None
    for line in (text or "").splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if not line.startswith("|"):
            columns = None
        elif cells[:1] == ["Action"]:
            columns = cells[2:]
        elif columns and (m := ACTION_ROW.match(line)):
            actions.setdefault(m.group(1), {}).update(zip(columns, cells[2:]))
    return actions


def requirement_names(text: str | None) -> set[str]:
    names = set()
    for line in (text or "").splitlines():
        m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line.split("#", 1)[0])
        if m:
            names.add(m.group(1).lower().replace("_", "-"))
    return names


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--head", default="origin/main")
    parser.add_argument("--base", help="default: the last tag before --head")
    args = parser.parse_args(argv)
    head = args.head
    base = args.base or git("describe", "--tags", "--abbrev=0", head).strip()

    changed = changed_files(base, head)
    added = {path: added_lines(base, head, path) for _, path in changed}

    findings: list[Item] = []
    for status, path in changed:
        if path.startswith("xefm/") and path.endswith(".py") and added[path]:
            findings += check_source(path, show(head, path) or "", added[path])
        if status == "A":
            findings += check_placement(path)
    findings += check_permissions(head)
    findings += check_docs(base, head, changed)
    api_findings, api_notes = api_changes(base, head)
    findings += api_findings

    notes = []
    if git("rev-parse", "HEAD") != git("rev-parse", head) or \
            git("status", "--porcelain", "--untracked-files=no").strip():
        notes.append(f"the working tree is not a clean checkout of {head}: the "
                     "skill-reference and translation checks below judged the "
                     "working tree")
    if show(base, API_SNAPSHOT) is None:
        notes.append(f"{base} has no {API_SNAPSHOT}: the public API was not "
                     "compared")
    if show(base, ACTIONS_MD) is None:
        notes.append(f"{base} has no {ACTIONS_MD}: new actions and changed "
                     "default keys were not compared")
    findings += run_tool("skill-refs", ["tools/gen_skill_references.py", "--check"],
                         "make skill-references")
    findings += run_tool("translations", ["tools/check_translations.py"],
                         "make check-docs")
    hints = review_hints(base, head, changed, added) + api_notes

    print(f"Release review {base}..{head}: {len(changed)} files changed")
    for note in notes:
        print(f"Note: {note}")
    print(f"\nFindings — CLAUDE.md's mechanical rules ({len(findings)})")
    print("\n".join(map(str, findings)) or "  none")
    print(f"\nFor review — CLAUDE.md, \"What belongs in the core\" ({len(hints)})")
    print("\n".join(map(str, hints)) or "  none")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
