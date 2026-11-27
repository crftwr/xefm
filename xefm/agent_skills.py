"""The user's own skills for the agent sessions XeFM starts (discussion #1009).

A skill in ``~/.xefm/skills/<name>/SKILL.md`` is handed to every agent session
XeFM opens, and to no agent run anywhere else. It is a plain Agent Skills
folder (https://agentskills.io): the same folder still works when copied into
an agent's own skills folder.

It is picked up by being there, so "write a skill that ... and install it as
an XeFM skill", asked inside a session, needs nothing but the agent writing a
folder; ``xefm skills check`` says whether XeFM takes it. :func:`found` is
what :func:`xefm.agents.prepare` hands the sessions: the skills that pass,
each read afresh at every launch.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from pathlib import Path

from xefm.log_manager import getLogger

logger = getLogger("AgentSkills")

#: The name XeFM's own skill has: an agent that does not keep plugins' skills
#: apart would be handed two of them.
RESERVED = ("xefm",)

#: What the Agent Skills specification allows a name to be.
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
NAME_MAX = 64
DESCRIPTION_MAX = 1024


def skills_dir() -> Path:
    """``~/.xefm/skills/``: where the user's session skills live."""
    from xefm.config import config_manager
    return Path(config_manager.config_dir) / "skills"


@dataclass
class Skill:
    """One skill folder as read from disk."""
    path: Path
    name: str = ""
    description: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def frontmatter(text: str) -> dict[str, str] | None:
    """The top-level ``key: value`` pairs of a SKILL.md's YAML frontmatter, or
    None when it has none. Enough YAML for what a skill's frontmatter holds:
    plain and quoted scalars and ``>`` / ``|`` blocks; a nested mapping
    (``metadata:``) is taken as present and left unread."""
    text = text.removeprefix(codecs.BOM_UTF8.decode("utf-8"))
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    out: dict[str, str] = {}
    body = lines[1:end]
    i = 0
    while i < len(body):
        line = body[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            continue
        key, colon, value = line.partition(":")
        if not colon:
            continue
        value = value.strip()
        if value[:1] in (">", "|"):
            block = []
            while i < len(body) and (not body[i].strip() or body[i][:1].isspace()):
                block.append(body[i].strip())
                i += 1
            joiner = " " if value[0] == ">" else "\n"
            value = joiner.join(block).strip()
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote, value = value[0], value[1:-1]
            value = value.replace("''", "'") if quote == "'" \
                else value.replace('\\"', '"').replace("\\\\", "\\")
        else:
            value = value.split(" #", 1)[0].strip()
        out[key.strip()] = value
    return out


def read(path: Path) -> Skill:
    """The skill in folder ``path``, with what keeps XeFM from handing it on."""
    path = Path(path)
    skill = Skill(path)
    skill_md = path / "SKILL.md"
    if not path.is_dir():
        skill.problems.append(f"{path} is not a folder")
        return skill
    try:
        text = skill_md.read_text(encoding="utf-8")
    except FileNotFoundError:
        skill.problems.append("no SKILL.md in the folder")
        return skill
    except (OSError, UnicodeDecodeError) as exc:
        skill.problems.append(f"SKILL.md cannot be read as UTF-8: {exc}")
        return skill
    meta = frontmatter(text)
    if meta is None:
        skill.problems.append("SKILL.md does not start with YAML frontmatter "
                              "between two '---' lines")
        return skill
    skill.name = meta.get("name", "")
    skill.description = meta.get("description", "")
    name = skill.name
    if not name:
        skill.problems.append("the frontmatter has no 'name'")
    elif len(name) > NAME_MAX or not _NAME.fullmatch(name):
        skill.problems.append(
            f"name {name!r}: lowercase letters, digits and single hyphens, "
            f"at most {NAME_MAX} characters, no hyphen at either end")
    elif name != path.name:
        skill.problems.append(f"name {name!r} differs from the folder's name {path.name!r}")
    elif name in RESERVED:
        skill.problems.append(f"name {name!r} is XeFM's own skill; choose another")
    if not skill.description:
        skill.problems.append("the frontmatter has no 'description' (what the skill "
                              "does and when to use it)")
    elif len(skill.description) > DESCRIPTION_MAX:
        skill.problems.append(f"the description is longer than {DESCRIPTION_MAX} characters")
    return skill


def scan(root: Path | None = None) -> list[Skill]:
    """Every folder in ``root`` (``~/.xefm/skills/``), read, by name. A folder
    whose name starts with ``.`` is left out (an editor's or a VCS's)."""
    root = skills_dir() if root is None else Path(root)
    try:
        folders = sorted(p for p in root.iterdir()
                         if p.is_dir() and not p.name.startswith("."))
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning(f"Cannot read {root}: {exc}")
        return []
    return [read(p) for p in folders]


def found(root: Path | None = None) -> list[Skill]:
    """The skills sessions are handed; one that fails the check is left out
    with a warning in the log."""
    out = []
    for skill in scan(root):
        if skill.ok:
            out.append(skill)
        else:
            logger.warning(f"Skill {skill.path.name} left out of agent sessions: "
                           + "; ".join(skill.problems))
    return out
