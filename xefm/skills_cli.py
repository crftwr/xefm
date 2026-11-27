"""``xefm skills ...`` - the user's own skills for XeFM's agent sessions (#1009).

The skills in ``~/.xefm/skills/`` are handed to every agent session XeFM
starts. ``check`` is what an agent runs after writing one there; its exit
status says whether XeFM takes it. No window opens.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from xefm import agent_skills


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xefm skills",
        description="The user's own skills for the AI agent sessions XeFM starts, "
                    "kept in ~/.xefm/skills/<name>/SKILL.md. (`xefm skill` is XeFM's "
                    "own skill.)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the skills and whether sessions get them")
    check = sub.add_parser("check", help="say whether XeFM takes a skill")
    check.add_argument("skills", nargs="*", metavar="NAME|DIR",
                       help="a skill's name in ~/.xefm/skills/ or a folder "
                            "(default: every skill there)")
    sub.add_parser("path", help="print the folder the skills are in")
    return parser


def _where(skill: agent_skills.Skill) -> str:
    return skill.name or skill.path.name


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = _parser().parse_args(argv)
    root = agent_skills.skills_dir() if root is None else Path(root)

    if args.command == "path":
        print(root)
        return 0

    if args.command == "list":
        skills = agent_skills.scan(root)
        if not skills:
            print(f"no skills in {root}")
            return 0
        print(f"{root}:")
        for s in skills:
            state = "ok" if s.ok else "left out: " + "; ".join(s.problems)
            print(f"  {s.path.name}  ({state})")
            if s.ok:
                print(f"      {' '.join(s.description.split())}")
        return 0

    # check
    if args.skills:
        folders = [Path(a).expanduser() if any(c in a for c in "/\\~") or a.startswith(".")
                   else root / a for a in args.skills]
        skills = [agent_skills.read(f) for f in folders]
    else:
        skills = agent_skills.scan(root)
        if not skills:
            print(f"no skills in {root}")
            return 0
    bad = 0
    for s in skills:
        if s.ok:
            inside = s.path.resolve().parent == root.resolve()
            print(f"ok: {s.name}" + ("" if inside else
                  f" (not in {root}: sessions get it once it is there)"))
        else:
            bad += 1
            for problem in s.problems:
                print(f"error: {_where(s)}: {problem}", file=sys.stderr)
    return 1 if bad else 0
